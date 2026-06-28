"""Force-plate geometry + GRF transform (Visual3D-style 3D-view overlay)."""

import os

import numpy as np
import pytest

from core.c3d_reader import _extract_force_plates, build_grf, _plate_forces


class _FakeC3D:
    """Minimal mapping that mimics the ezc3d dict for FORCE_PLATFORM:CORNERS."""

    def __init__(self, corners, group="FORCE_PLATFORM"):
        self._d = {"parameters": {group: {"CORNERS": {"value": corners}}}}

    def __getitem__(self, k):
        return self._d[k]


def _axis_aligned_corners(cx=300.0, cy=200.0, hx=250.0, hy=200.0):
    """A flat, axis-aligned plate in C3D corner order (+x+y, -x+y, -x-y, +x-y)."""
    pts = np.array([
        [cx + hx, cy + hy, 0.0],
        [cx - hx, cy + hy, 0.0],
        [cx - hx, cy - hy, 0.0],
        [cx + hx, cy - hy, 0.0],
    ])
    return np.transpose(pts[None], (2, 1, 0))  # -> (3, 4, 1) rows X,Y,Z


def test_extract_axis_aligned_plate():
    plates = _extract_force_plates(_FakeC3D(_axis_aligned_corners()))
    assert plates is not None and len(plates) == 1
    p = plates[0]
    assert np.allclose(p["origin"], [300.0, 200.0, 0.0])
    assert np.allclose(p["R"], np.eye(3))
    assert p["corners"].shape == (4, 3)


def test_accepts_both_group_names():
    # Real files use the singular "FORCE_PLATFORM"; some exporters use plural.
    for group in ("FORCE_PLATFORM", "FORCE_PLATFORMS"):
        plates = _extract_force_plates(_FakeC3D(_axis_aligned_corners(), group=group))
        assert plates is not None and len(plates) == 1


def test_no_force_platforms_returns_none():
    class Empty:
        def __getitem__(self, k):
            return {}  # parameters dict with no force-plate group

    assert _extract_force_plates(Empty()) is None


def _raw(fz, mx, my, fx=None, fy=None):
    n = len(fz)
    return {"fx": fx or [0.0] * n, "fy": fy or [0.0] * n,
            "fz": fz, "mx": mx, "my": my}


def test_build_grf_lifts_cop_and_force_to_global():
    plates = _extract_force_plates(_FakeC3D(_axis_aligned_corners()))
    # cop_x = -My/Fz = 10, cop_y = Mx/Fz = -5  →  My=-8000, Mx=-4000 at Fz=800.
    data = {
        "force_plates": plates,
        "time": np.array([0.0, 0.01]),
        "_fp_raw": [_raw([800.0, 800.0], [-4000.0, -4000.0], [-8000.0, -8000.0])],
    }
    grf = build_grf(data)
    assert grf is not None and len(grf) == 1
    # COP lifted to global: origin + R @ [cop_x, cop_y, 0]
    assert np.allclose(grf[0]["point"][0], [310.0, 195.0, 0.0])
    assert np.allclose(grf[0]["vector"][0], [0.0, 0.0, 800.0])


def test_build_grf_hides_unloaded_frames():
    plates = _extract_force_plates(_FakeC3D(_axis_aligned_corners()))
    data = {
        "force_plates": plates,
        "time": np.array([0.0, 0.01]),
        "_fp_raw": [_raw([800.0, 2.0], [-4000.0, -10.0], [-8000.0, -20.0])],
    }
    grf = build_grf(data)
    assert np.isfinite(grf[0]["point"][0]).all()
    assert not np.isfinite(grf[0]["point"][1]).all()


def test_build_grf_handles_multiple_plates():
    # Two plates side by side; each should yield its own GRF entry.
    p1 = _axis_aligned_corners(cx=300, cy=200)[:, :, 0]
    p2 = _axis_aligned_corners(cx=900, cy=200)[:, :, 0]
    corners = np.stack([p1, p2], axis=2)            # (3, 4, 2)
    plates = _extract_force_plates(_FakeC3D(corners))
    data = {
        "force_plates": plates,
        "time": np.array([0.0, 0.01]),
        "_fp_raw": [_raw([800.0, 800.0], [0.0, 0.0], [0.0, 0.0]),
                    _raw([600.0, 600.0], [0.0, 0.0], [0.0, 0.0])],
    }
    grf = build_grf(data)
    assert grf is not None and len(grf) == 2
    assert np.allclose(grf[0]["point"][0], [300.0, 200.0, 0.0])
    assert np.allclose(grf[1]["point"][0], [900.0, 200.0, 0.0])


def test_build_grf_without_plates_returns_none():
    assert build_grf({"fz": np.ones(3), "time": np.arange(3)}) is None


class _FakeFP:
    """Mimics the ezc3d mapping for a FORCE_PLATFORM parameter group."""

    def __init__(self, group):
        self._d = {"parameters": {"FORCE_PLATFORM": group}}

    def __getitem__(self, k):
        return self._d[k]


def test_plate_forces_passthrough_type2():
    """TYPE-2 plates already store F/M in the channels — read verbatim, no cal."""
    labels = [f"CH{i}" for i in range(1, 7)]
    channels = {f"CH{i}": np.full(3, float(i)) for i in range(1, 7)}
    group = {
        "TYPE": {"value": [2]},
        "CHANNEL": {"value": np.array([[1], [2], [3], [4], [5], [6]])},
    }
    out = _plate_forces(_FakeFP(group), channels, labels)
    assert out is not None and len(out) == 1
    assert np.allclose(out[0]["fz"], 3.0)   # channel 3 verbatim
    assert np.allclose(out[0]["mx"], 4.0)


def test_plate_forces_applies_cal_matrix_type4():
    """TYPE-4 plates store RAW signals; F/M = CAL_MATRIX @ raw channels.

    Uses a non-diagonal matrix so a per-channel scaling would give a different
    (wrong) answer — proving the full matrix multiply is applied.
    """
    labels = [f"CH{i}" for i in range(1, 7)]
    raw = {f"CH{i}": np.full(4, float(i)) for i in range(1, 7)}  # raw "volts" 1..6
    # 6x6 matrix with off-diagonal coupling (column-stacked so M[r] mixes channels).
    M = np.arange(36, dtype=float).reshape(6, 6) * 0.1 + np.eye(6)
    group = {
        "TYPE": {"value": [4]},
        "CHANNEL": {"value": np.array([[1], [2], [3], [4], [5], [6]])},
        "CAL_MATRIX": {"value": M[:, :, None]},   # ezc3d shape (6, 6, n_plates)
    }
    out = _plate_forces(_FakeFP(group), raw, labels)
    expect = M @ np.arange(1, 7, dtype=float)     # (Fx,Fy,Fz,Mx,My,Mz)
    assert np.allclose(out[0]["fx"], expect[0])
    assert np.allclose(out[0]["fz"], expect[2])
    assert np.allclose(out[0]["mx"], expect[3])
    assert np.allclose(out[0]["my"], expect[4])


_EXAMPLE_C3D = os.path.join(
    os.path.dirname(__file__), "..", "examples", "YA01", "dt_1.c3d")


@pytest.mark.skipif(not os.path.isfile(_EXAMPLE_C3D),
                    reason="example c3d not available")
def test_cop_leaves_plate_centre_on_real_type4_file():
    """Regression: a real TYPE-4 lab trial must yield a COP that travels well off
    the plate centre (the calibration bug pinned the GRF arrow at the origin)."""
    from core.c3d_reader import read_c3d
    from core.data_quality import clean_dataset
    data = read_c3d(_EXAMPLE_C3D)
    clean_dataset(data)
    grf = build_grf(data)
    assert grf
    g = grf[0]
    origin = np.asarray(data["force_plates"][0]["origin"], float)
    pts = g["point"][np.isfinite(g["point"]).all(axis=1)]
    assert len(pts) > 0
    # Peak excursion of the COP from the plate centre, in mm.
    excursion = float(np.max(np.linalg.norm(pts - origin, axis=1)))
    assert excursion > 10.0, f"COP barely left centre ({excursion:.2f} mm)"


def test_rotated_plate_round_trips_force_direction():
    # 90-degree yaw plate (centre (400,300)): local +x -> global +y, +y -> global -x.
    pts = np.array([
        [200.0, 550.0, 0.0],   # +x+y
        [200.0, 50.0, 0.0],    # -x+y
        [600.0, 50.0, 0.0],    # -x-y
        [600.0, 550.0, 0.0],   # +x-y
    ])
    corners = np.transpose(pts[None], (2, 1, 0))
    plates = _extract_force_plates(_FakeC3D(corners))
    R = plates[0]["R"]
    # A purely vertical force stays vertical regardless of yaw.
    assert np.allclose(R @ np.array([0.0, 0.0, 1.0]), [0.0, 0.0, 1.0])
    # Local +x points along global +y, local +y along global -x for this layout.
    assert np.allclose(R @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-9)
    assert np.allclose(R @ np.array([0.0, 1.0, 0.0]), [-1.0, 0.0, 0.0], atol=1e-9)
