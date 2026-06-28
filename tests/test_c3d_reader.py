"""Multi-plate force-signal extraction in core.c3d_reader.

Pins the per-plate ``fp{n}:*`` signal materialization (the data side of the
multi-plate DATA section): unit tests on the pure helpers, plus an integration
test against the bundled two-plate example when it is present.
"""

import os

import numpy as np
import pytest

from core.c3d_reader import _plate_cop, _plate_signals, ensure_fp1_from_bare


def test_plate_cop_formula():
    # cop_ap = -My/Fz, cop_ml = Mx/Fz (Fz clamped away from zero).
    fz = np.array([800.0, 800.0])
    mx = np.array([-4000.0, -4000.0])
    my = np.array([-8000.0, -8000.0])
    cop_ap, cop_ml = _plate_cop(fz, mx, my)
    np.testing.assert_allclose(cop_ap, [10.0, 10.0])   # -(-8000)/800
    np.testing.assert_allclose(cop_ml, [-5.0, -5.0])   # -4000/800


def test_plate_signals_builds_per_plate_keys():
    n = 4
    fp_raw = [
        {"fx": np.full(n, 1.0), "fy": np.full(n, 2.0), "fz": np.full(n, 100.0),
         "mx": np.zeros(n), "my": np.zeros(n)},
        {"fx": np.full(n, 3.0), "fy": np.full(n, 4.0), "fz": np.full(n, 200.0),
         "mx": np.zeros(n), "my": np.zeros(n)},
    ]
    signals, keys = _plate_signals(fp_raw, n)
    assert keys == [
        "fp1:fx", "fp1:fy", "fp1:fz", "fp1:cop_ap", "fp1:cop_ml",
        "fp2:fx", "fp2:fy", "fp2:fz", "fp2:cop_ap", "fp2:cop_ml",
    ]
    # Fz is exposed RAW (C3D-faithful): no sign flip. The synthetic raw Fz is
    # +200, so it stays +200 here.
    np.testing.assert_array_equal(signals["fp2:fz"], np.full(n, 200.0))
    np.testing.assert_array_equal(signals["fp2:fx"], np.full(n, 3.0))
    assert all(len(v) == n for v in signals.values())


def test_plate_signals_fz_raw_and_cop_invariant():
    """Fz is exposed exactly as the raw C3D channel (no flip), and COP matches
    the raw-Fz formula (cop_ap=-My/Fz, cop_ml=Mx/Fz)."""
    n = 5
    # Subject-applied vertical load is negative (down) per the C3D convention.
    raw_fz = np.full(n, -800.0)
    mx, my = np.full(n, -4000.0), np.full(n, -8000.0)
    fp_raw = [{"fx": np.full(n, 5.0), "fy": np.full(n, 6.0),
               "fz": raw_fz, "mx": mx, "my": my}]
    signals, _ = _plate_signals(fp_raw, n)
    # Exposed Fz is the RAW channel, unchanged (-800).
    np.testing.assert_array_equal(signals["fp1:fz"], np.full(n, -800.0))
    cop_ap_raw, cop_ml_raw = _plate_cop(raw_fz, mx, my)
    np.testing.assert_array_equal(signals["fp1:cop_ap"], cop_ap_raw)
    np.testing.assert_array_equal(signals["fp1:cop_ml"], cop_ml_raw)


def test_plate_signals_skips_plate_without_fz():
    n = 3
    fp_raw = [
        {"fx": None, "fy": None, "fz": np.ones(n), "mx": None, "my": None},
        {"fx": None, "fy": None, "fz": None, "mx": None, "my": None},  # no Fz
    ]
    signals, keys = _plate_signals(fp_raw, n)
    assert [k for k in keys if k.startswith("fp2:")] == []
    assert "fp1:fz" in signals


def test_plate_signals_empty_when_no_raw():
    assert _plate_signals(None, 5) == ({}, [])
    assert _plate_signals([], 5) == ({}, [])


def test_ensure_fp1_from_bare_synthesizes_single_plate():
    # Files without a FORCE_PLATFORM:CHANNEL mapping still get an FP1 group built
    # from the bare keys, so the UI is uniformly plate-grouped.
    n = 6
    data = {"fz": np.ones(n), "fx": np.full(n, 2.0), "fy": np.full(n, 3.0),
            "cop_ap": np.arange(n, dtype=float), "cop_ml": np.zeros(n)}
    ensure_fp1_from_bare(data)
    assert data["n_force_plates"] == 1
    assert data["force_signal_keys"] == [
        "fp1:fx", "fp1:fy", "fp1:fz", "fp1:cop_ap", "fp1:cop_ml"]
    np.testing.assert_array_equal(data["fp1:fz"], data["fz"])
    np.testing.assert_array_equal(data["fp1:cop_ap"], data["cop_ap"])


def test_ensure_fp1_noop_when_plate_signals_exist():
    data = {"fz": np.ones(3), "force_signal_keys": ["fp1:fz", "fp2:fz"],
            "n_force_plates": 2}
    ensure_fp1_from_bare(data)
    assert data["n_force_plates"] == 2  # untouched


def test_ensure_fp1_missing_force_is_noop():
    data = {"time": np.arange(3)}  # marker-only: no fz
    ensure_fp1_from_bare(data)
    assert "force_signal_keys" not in data


_YA01 = os.path.join(os.path.dirname(__file__), "..", "examples", "YA01", "dt_1.c3d")


@pytest.mark.skipif(not os.path.isfile(_YA01), reason="YA01 example not present")
def test_read_c3d_materializes_two_plates():
    from core.c3d_reader import read_c3d
    d = read_c3d(_YA01)
    assert d.get("n_force_plates") == 2
    assert "fp1:fz" in d and "fp2:fz" in d
    # Bare keys mirror plate 1; the two plates carry distinct force.
    np.testing.assert_array_equal(d["fz"], d["fp1:fz"])
    np.testing.assert_array_equal(d["cop_ap"], d["fp1:cop_ap"])
    assert not np.allclose(d["fp1:fz"], d["fp2:fz"])


@pytest.mark.skipif(not os.path.isfile(_YA01), reason="YA01 example not present")
def test_read_c3d_vgrf_raw_cop_unchanged():
    """Vertical force is exposed RAW (C3D convention: subject-applied, down = -),
    so the stance Fz is NEGATIVE; the user gets a positive vGRF via |Fz| (an abs
    ComputeStep). COP is independent of the Fz sign — re-deriving it from the raw
    -My/Fz, Mx/Fz must reproduce the exposed COP bit-for-bit."""
    from core.c3d_reader import read_c3d, _plate_cop
    from core import signal_ops
    d = read_c3d(_YA01)
    fz = np.asarray(d["fz"], dtype=float)
    t = np.asarray(d["time"], dtype=float)
    # Raw stance load is downward-negative.
    assert np.nanmin(fz) < 0
    # |Fz| (the abs op) makes the impulse positive — this is the user's tool.
    assert signal_ops.integral(np.abs(fz), t, kind="total", sign="all") > 0
    # COP invariance: rebuild plate-1 COP straight from the raw channels and
    # compare to the exposed cop_ap/cop_ml (bit-for-bit).
    raw = d["_fp_raw"][0]
    cop_ap, cop_ml = _plate_cop(raw["fz"], raw["mx"], raw["my"])
    # read_c3d trims nothing before COP/Fz here (clean_dataset runs in the UI),
    # so the full-length raw COP equals the exposed bare COP.
    np.testing.assert_array_equal(d["cop_ap"], cop_ap[: len(d["cop_ap"])])
    np.testing.assert_array_equal(d["cop_ml"], cop_ml[: len(d["cop_ml"])])
