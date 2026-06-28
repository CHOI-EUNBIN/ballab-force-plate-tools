"""Regression tests for core.marker_model (kinematic model engine).

Synthetic marker sets with a known geometry pin angle_between, the
calibrate/reconstruct round trip (midpoint joints), to_dict/from_dict
serialisation, and auto_build_model's structure.
"""

import numpy as np
import pytest

from core.marker_model import (
    MarkerModel,
    angle_between,
    auto_build_model,
)


# --- angle_between ---------------------------------------------------------

def test_angle_between_known_angles():
    va = np.array([[1.0, 0, 0], [1, 1, 0], [1, 0, 0]])
    vb = np.array([[0.0, 1, 0], [0, 1, 0], [1, 0, 0]])
    out = angle_between(va, vb)
    np.testing.assert_allclose(out, [90.0, 45.0, 0.0], atol=1e-6)


def test_angle_between_zero_vector_is_nan():
    va = np.array([[0.0, 0, 0]])
    vb = np.array([[1.0, 0, 0]])
    out = angle_between(va, vb)
    assert np.isnan(out[0])


# --- calibrate / reconstruct (midpoint joint) ------------------------------

def _knee_markers(F=5):
    """A static trial with a medial/lateral knee pair plus a 3-marker cluster."""
    labels = ["RMKNEE", "RLKNEE", "C1", "C2", "C3"]
    data = np.zeros((5, F, 3))
    data[0, :] = [0, 0, 0]      # medial
    data[1, :] = [2, 0, 0]      # lateral  -> midpoint (1, 0, 0)
    data[2, :] = [0, 1, 0]
    data[3, :] = [1, 1, 0]
    data[4, :] = [0, 0, 1]
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _knee_model():
    return MarkerModel(joints=[{
        "name": "R_KNEE", "method": "midpoint",
        "medial": "RMKNEE", "lateral": "RLKNEE",
        "cluster": ["C1", "C2", "C3"],
    }])


def test_calibrate_reconstruct_midpoint():
    markers = _knee_markers()
    m = _knee_model().calibrate(markers)
    jc = m.reconstruct(markers)
    np.testing.assert_allclose(jc["R_KNEE"][0], [1.0, 0.0, 0.0], atol=1e-9)


def test_reconstruct_follows_rigid_translation():
    """Translating the whole cluster translates the reconstructed JC equally."""
    markers = _knee_markers()
    m = _knee_model().calibrate(markers)
    moved = {k: v for k, v in markers.items()}
    moved["data"] = markers["data"].copy()
    moved["data"][2:5] += np.array([10.0, 0.0, 0.0])   # shift the cluster
    jc = m.reconstruct(moved)
    np.testing.assert_allclose(jc["R_KNEE"][0], [11.0, 0.0, 0.0], atol=1e-6)


def test_reconstruct_partial_occlusion_still_solves():
    markers = _knee_markers(F=3)
    m = _knee_model().calibrate(markers)
    occ = {k: v for k, v in markers.items()}
    occ["data"] = markers["data"].copy()
    # frame 1: hide one of three cluster markers -> still 3 visible? no, 2 left
    # keep exactly 3 cluster markers, so dropping one leaves 2 -> NaN frame.
    occ["data"][4, 1, :] = np.nan
    jc = m.reconstruct(occ)
    assert np.all(np.isfinite(jc["R_KNEE"][0]))
    assert np.all(np.isnan(jc["R_KNEE"][1]))   # < 3 visible -> NaN
    assert np.all(np.isfinite(jc["R_KNEE"][2]))


def test_reconstruct_missing_cluster_marker_degrades_to_nan():
    """REGRESSION: a cluster marker calibrated but ABSENT from the trial (a
    different label set, or occluded the whole trial) must NOT raise KeyError and
    crash the whole model — the joint centre degrades to NaN (the cluster simply
    has fewer visible markers). Before the fix ``reconstruct`` aborted the entire
    apply() with a KeyError."""
    markers = _knee_markers(F=4)
    m = _knee_model().calibrate(markers)
    # Trial is missing cluster marker "C3" entirely (3-marker cluster -> 2 left).
    trimmed = {
        "labels": ["RMKNEE", "RLKNEE", "C1", "C2"],
        "data": markers["data"][:4].copy(),
        "time": markers["time"],
    }
    jc = m.reconstruct(trimmed)            # must not raise
    assert jc["R_KNEE"].shape == (4, 3)
    assert np.all(np.isnan(jc["R_KNEE"]))  # < 3 visible cluster markers -> NaN


def test_reconstruct_missing_one_of_four_cluster_markers_still_solves():
    """With a 4-marker cluster, dropping ONE marker leaves 3 — enough for a rigid
    solve — so the joint centre is still finite (and matches the full-cluster
    result for a rigid cluster)."""
    labels = ["RMKNEE", "RLKNEE", "C1", "C2", "C3", "C4"]
    F = 4
    data = np.zeros((6, F, 3))
    data[0, :] = [0, 0, 0]; data[1, :] = [2, 0, 0]
    data[2, :] = [0, 1, 0]; data[3, :] = [1, 1, 0]
    data[4, :] = [0, 0, 1]; data[5, :] = [1, 0, 1]
    static = {"labels": labels, "data": data.copy(), "time": np.arange(F) / 100.0}
    m = MarkerModel(joints=[{"name": "R_KNEE", "method": "midpoint",
                             "medial": "RMKNEE", "lateral": "RLKNEE",
                             "cluster": ["C1", "C2", "C3", "C4"]}]).calibrate(static)
    full = m.reconstruct(static)["R_KNEE"]
    trimmed = {"labels": labels[:5], "data": data[:5].copy(),
               "time": static["time"]}
    part = m.reconstruct(trimmed)["R_KNEE"]
    assert np.isfinite(part).all()
    np.testing.assert_allclose(part, full, atol=1e-7)


def test_calibration_selfcheck_near_zero():
    markers = _knee_markers()
    m = _knee_model().calibrate(markers)
    assert m.calibration_selfcheck(markers) < 1e-6


def test_reconstruct_without_calibrate_raises():
    with pytest.raises(RuntimeError):
        _knee_model().reconstruct(_knee_markers())


# --- segments / angles end to end ------------------------------------------

def test_apply_produces_segments_and_angles():
    markers = _knee_markers()
    model = MarkerModel(
        joints=[{"name": "R_KNEE", "method": "midpoint", "medial": "RMKNEE",
                 "lateral": "RLKNEE", "cluster": ["C1", "C2", "C3"]}],
        segments=[{"name": "SEG", "proximal": "R_KNEE", "distal": "RLKNEE"}],
    )
    model.calibrate(markers)
    res = model.apply(markers)
    assert "R_KNEE" in res["joint_centers"]
    assert "SEG" in res["segments"]
    # SEG = lateral(2,0,0) - JC(1,0,0) = (1,0,0)
    np.testing.assert_allclose(res["segments"]["SEG"][0], [1.0, 0.0, 0.0], atol=1e-6)


# --- serialisation ---------------------------------------------------------

def test_to_dict_from_dict_roundtrip():
    m = _knee_model()
    m.name = "demo"
    d = m.to_dict()
    assert d["name"] == "demo"
    assert d["joints"][0]["name"] == "R_KNEE"
    m2 = MarkerModel.from_dict(d)
    assert m2.name == "demo"
    assert m2.joints == m.joints
    assert m2.segments == m.segments
    assert m2.angles == m.angles


# --- auto_build_model ------------------------------------------------------

def test_auto_build_model_creates_knee_joint():
    # auto_build builds a midpoint joint's tracking cluster from same-side limb
    # markers (those sharing the side letter), so the cluster markers are
    # R-prefixed here.
    labels = ["RMKNEE", "RLKNEE", "RC1", "RC2", "RC3"]
    data = np.zeros((5, 4, 3))
    data[1, :, 0] = 2.0          # lateral offset so the midpoint is well defined
    markers = {"labels": labels, "data": data, "time": np.arange(4) / 100.0}
    model = auto_build_model(markers, name="auto")
    names = {j["name"] for j in model.joints}
    assert "R_KNEE" in names
    knee = next(j for j in model.joints if j["name"] == "R_KNEE")
    assert knee["method"] == "midpoint"
    assert knee["medial"] == "RMKNEE"
    assert knee["lateral"] == "RLKNEE"
    assert len(knee["cluster"]) >= 3
