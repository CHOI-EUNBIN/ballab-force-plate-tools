"""Regression tests for core.com (de Leva 1996 centre-of-mass engine).

Synthetic segments with a known geometry pin: the de Leva BSP table totals,
segment_com linear interpolation, the mass-weighted whole-body / partial COM,
coverage + whole_body flags, the PELVIS double-count guard, body_mass=None
position-only mode, and the static-GRF body-mass estimate. Headless, pure numpy
(no Qt), reusing the auto-build fixtures from test_marker_model_autojcs.
"""

import numpy as np
import pytest

import core.com as com
from core.marker_model import MarkerModel, auto_build_model

from test_marker_model_autojcs import _markers, _pelvis_pts, _leg_pts


# --- A. de Leva table integrity --------------------------------------------

@pytest.mark.parametrize("sex,expected", [("F", 0.9999), ("M", 1.0000)])
def test_bsp_mass_fractions_sum_to_one(sex, expected):
    """head + trunk + 2x(arm+forearm+hand+thigh+shank+foot) ~= 1.0 (de Leva
    1996 Table 4 totals; F=0.9999 / M=1.0000 is the published rounding)."""
    total = 0.0
    for base, (mf, mm, cf, cm, bilat) in com.BSP.items():
        frac = (mf if sex == "F" else mm)
        total += 2 * frac if bilat else frac
    assert total == pytest.approx(expected, abs=1e-4)


def test_neutral_bsp_is_average_of_sexes():
    """sex=None uses the female/male average (documented neutral fallback)."""
    neutral = com._bsp_for(None)
    mf, mm, cf, cm, bilat = com.BSP["THIGH"]
    assert neutral["THIGH"][0] == pytest.approx((mf + mm) / 2)
    assert neutral["THIGH"][1] == pytest.approx((cf + cm) / 2)


def test_pelvis_excluded_from_bsp_table():
    """PELVIS has no BSP entry (its mass lives in TRUNK -> no double count)."""
    assert "PELVIS" not in com.BSP
    assert "PELVIS" in com.BSP_EXCLUDE


# --- B. segment_com linear interpolation -----------------------------------

def test_segment_com_linear_interp():
    prox = np.array([[0.0, 0, 0], [1, 1, 1]])
    dist = np.array([[10.0, 0, 0], [1, 1, 11]])
    out = com.segment_com(prox, dist, 0.4)
    np.testing.assert_allclose(out, [[4.0, 0, 0], [1, 1, 5]])


def test_segment_com_nan_safe():
    prox = np.array([[np.nan, 0, 0]])
    dist = np.array([[10.0, 0, 0]])
    out = com.segment_com(prox, dist, 0.5)
    assert np.isnan(out[0, 0])


# --- C. body_com mass-weighted COM (hand-computed) -------------------------

def _two_thigh_model():
    """Two identical THIGH segments (bilateral), each prox->dist = (0,0,0)->(0,0,-10)."""
    model = MarkerModel(segments=[
        {"name": "R_THIGH", "proximal": "HIP_R", "distal": "KNEE_R"},
        {"name": "L_THIGH", "proximal": "HIP_L", "distal": "KNEE_L"},
    ])
    jc = {
        "HIP_R": np.zeros((3, 3)), "KNEE_R": np.tile([0, 0, -10.0], (3, 1)),
        "HIP_L": np.zeros((3, 3)), "KNEE_L": np.tile([0, 0, -10.0], (3, 1)),
    }
    markers = {"labels": [], "data": np.zeros((0, 3, 3)), "time": np.arange(3)}
    resolve = com.point_traj_for(model, markers, jc)
    return model, resolve


def test_body_com_known_two_segments():
    """Both thighs share a CoM at z = -10*0.4095 (male) -> body COM z there too."""
    model, resolve = _two_thigh_model()
    res = com.body_com(model, resolve, body_mass=70.0, sex="M")
    np.testing.assert_allclose(res["com"][0], [0, 0, -4.095], atol=1e-9)
    # coverage = 2 x male thigh fraction
    assert res["coverage"] == pytest.approx(2 * com.BSP["THIGH"][1], abs=1e-9)
    assert res["mass_used_kg"] == 70.0


def test_body_com_unequal_segments_weighted():
    """Two different segments at different heights -> mass-weighted mean."""
    # THIGH (frac 0.1416 male) CoM at z=0; SHANK (frac 0.0433) CoM at z=100.
    model = MarkerModel(segments=[
        {"name": "R_THIGH", "proximal": "A", "distal": "B"},
        {"name": "R_SHANK", "proximal": "C", "distal": "D"},
    ])
    jc = {"A": np.zeros((1, 3)), "B": np.zeros((1, 3)),
          "C": np.tile([0, 0, 100.0], (1, 1)), "D": np.tile([0, 0, 100.0], (1, 1))}
    markers = {"labels": [], "data": np.zeros((0, 1, 3)), "time": np.arange(1)}
    resolve = com.point_traj_for(model, markers, jc)
    res = com.body_com(model, resolve, sex="M")
    mt, ms = com.BSP["THIGH"][1], com.BSP["SHANK"][1]
    expected_z = (mt * 0 + ms * 100.0) / (mt + ms)
    assert res["com"][0, 2] == pytest.approx(expected_z)


# --- D. partial coverage + whole_body flag ---------------------------------

def test_partial_com_coverage_and_flag():
    model, resolve = _two_thigh_model()
    res = com.body_com(model, resolve, sex="M")
    assert res["coverage"] < 1.0
    assert res["whole_body"] is False
    for base in ("HEAD", "TRUNK", "SHANK", "FOOT"):
        assert base in res["missing"]


# --- E. PELVIS double-count guard ------------------------------------------

def test_pelvis_segment_does_not_add_mass():
    """A PELVIS segment present alongside TRUNK/thigh must NOT contribute mass."""
    model = MarkerModel(segments=[
        {"name": "PELVIS", "proximal": "P0", "distal": "P1"},
        {"name": "R_THIGH", "proximal": "HIP_R", "distal": "KNEE_R"},
    ])
    jc = {"P0": np.zeros((1, 3)), "P1": np.tile([0, 5.0, 0], (1, 1)),
          "HIP_R": np.zeros((1, 3)), "KNEE_R": np.tile([0, 0, -10.0], (1, 1))}
    markers = {"labels": [], "data": np.zeros((0, 1, 3)), "time": np.arange(1)}
    resolve = com.point_traj_for(model, markers, jc)
    res = com.body_com(model, resolve, sex="M")
    assert list(res["segment_coms"].keys()) == ["R_THIGH"]
    assert "PELVIS" not in res["missing"]          # excluded entirely, not "missing"
    assert res["coverage"] == pytest.approx(com.BSP["THIGH"][1])


# --- F. body_mass=None: position valid, mass None --------------------------

def test_com_position_without_body_mass():
    model, resolve = _two_thigh_model()
    res = com.body_com(model, resolve, body_mass=None, sex="M")
    np.testing.assert_allclose(res["com"][0], [0, 0, -4.095], atol=1e-9)
    assert res["mass_used_kg"] is None


# --- G. mass_from_grf ------------------------------------------------------

def test_mass_from_grf_constant():
    fz = np.full(1000, 735.75)         # 75 kg x 9.81
    assert com.mass_from_grf(fz) == pytest.approx(75.0)


def test_mass_from_grf_multiplate_sum():
    fz = np.vstack([np.full(100, 367.875), np.full(100, 367.875)])
    assert com.mass_from_grf(fz) == pytest.approx(75.0)


def test_mass_from_grf_sign_and_nan():
    # negative convention + NaN gaps -> magnitude, NaN ignored.
    fz = np.full(50, -735.75)
    fz[::5] = np.nan
    assert com.mass_from_grf(fz) == pytest.approx(75.0)
    assert com.mass_from_grf(np.full(10, np.nan)) is None


# --- H. apply() integration (auto-build) -----------------------------------

def _fullbody_markers():
    pts = dict(_pelvis_pts())
    pts.update(_leg_pts("R", (90.0, 40.0)))
    pts.update(_leg_pts("L", (-90.0, 40.0)))
    # thorax landmarks (IJ/C7/PX/T8) so a TRUNK segment is built
    pts.update({"IJ": [0, 120.0, 1500.0], "C7": [0, -50.0, 1520.0],
                "PX": [0, 110.0, 1300.0], "T8": [0, -60.0, 1320.0]})
    return _markers(pts)


def test_apply_adds_com_block():
    m = _fullbody_markers()
    model = auto_build_model(m)
    model.calibrate(m)
    res = model.apply(m, body_mass=70.0, sex="M")
    assert "com" in res
    c = res["com"]
    assert "TRUNK" in c["segment_coms"]          # trunk endpoints resolved
    assert c["mass_used_kg"] == 70.0
    # legs + trunk present, head/arms absent -> partial but substantial coverage
    assert 0.8 < c["coverage"] < 0.97
    assert c["whole_body"] is False
    assert np.isfinite(c["com"]).all()


def test_apply_com_backward_compatible_keys():
    """COM is additive: the legacy keys are untouched."""
    m = _fullbody_markers()
    model = auto_build_model(m)
    model.calibrate(m)
    res = model.apply(m)                          # no body_mass / sex
    for k in ("joint_centers", "segments", "angles", "time"):
        assert k in res
    assert res["com"]["mass_used_kg"] is None     # position still valid w/o mass
    assert np.isfinite(res["com"]["com"]).all()


def test_apply_com_failure_leaves_breadcrumb(monkeypatch, caplog):
    """#4 robustness: a COM failure stays NON-FATAL (legacy angle/segment outputs
    intact, no 'com' key) but no longer vanishes silently — it leaves a debug
    breadcrumb so a genuine COM bug isn't invisible."""
    import logging
    m = _fullbody_markers()
    model = auto_build_model(m)
    model.calibrate(m)

    def _boom(*a, **k):
        raise RuntimeError("com kaboom")
    monkeypatch.setattr(com, "point_traj_for", _boom)

    with caplog.at_level(logging.DEBUG, logger="core.marker_model"):
        res = model.apply(m, body_mass=70.0, sex="M")

    # Non-fatal + additive: the backward-compatible outputs survive, no COM.
    for k in ("joint_centers", "segments", "angles", "time"):
        assert k in res
    assert "com" not in res
    # ...but a breadcrumb was left behind.
    assert any("com" in r.message.lower() for r in caplog.records)
