"""Tests for the cluster-embedded (CAST) THIGH/SHANK segment frames in
core.marker_model.

Background (verified diagnosis): the previous auto-built THIGH/SHANK frames fixed
their frontal plane with a SINGLE living lateral marker (lateral knee / lateral
malleolus). A few mm of soft-tissue wobble on that short lever arm swung the
segment ML axis tens of degrees, inflating hip internal/external-rotation (IE) and
producing a strong knee flexion<->IE correlation (kinematic cross-talk, Piazza &
Cavanagh 2000). The fix embeds an ANATOMICAL ML axis -- defined once on the static
trial from a true medial+lateral marker pair (the trans-epicondylar / trans-
malleolar line) -- into the segment's tracking cluster and transports it rigidly
each frame (CAST, Cappozzo et al. 1995). The single-marker frame is kept as a
backward-compatible fallback.

Coverage:
  * pure builders: ``segment_frame_from_ml`` (orthonormal / side flip / NaN) and
    ``cluster_pose_per_frame`` (recovers a known rigid rotation; NaN-safe).
  * SYNTHETIC ground truth: a pure-flexion thigh with a wobbling single lateral
    marker -- the single-marker frame inflates IE (true IE = 0), the cluster
    frame rejects the wobble (IE ~ 0). This pins the FEASIBILITY claim.
  * auto-build schema: THIGH/SHANK get ``ml_source="cluster"`` + the medial/
    lateral pair + a >=3-marker cluster; a sparse cluster / missing pair falls
    back to ``ml_source="marker"``; ``cluster_labels`` lists the dynamic cluster.
  * backward compatibility: a saved model with NO ml_source field computes frames
    via the single-marker path (no crash, identical to legacy).
  * reliability: KNEE _IE is "moderate" under CAST, HIP IE "high", ANKLE IE "low".
  * cross-talk diagnostic ``crosstalk_diagnosis`` on analytic signals.
  * REAL-DATA regression (examples/YA01,YA02, skipped if absent): CAST drops the
    hip IE range to ~12-15 deg while preserving hip/knee FE to <2 deg RMS.
"""

import os

import numpy as np
import pytest

from core.marker_model import (
    MarkerModel,
    auto_build_model,
    angle_reliability,
    cluster_pose_per_frame,
    crosstalk_diagnosis,
    jcs_angles,
    segment_frame,
    segment_frame_from_ml,
)

try:
    from core.c3d_reader import read_c3d, C3D_AVAILABLE
except Exception:                                     # pragma: no cover
    C3D_AVAILABLE = False

_EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "examples")


# --------------------------------------------------------------------------
# Pure builders
# --------------------------------------------------------------------------

def test_segment_frame_from_ml_orthonormal_right_handed():
    """A vertical right segment with ML = world +x reproduces the lab identity:
    x=right, y=anterior, z=up; orthonormal, det +1."""
    F = 3
    origin = np.zeros((F, 3))
    prox = np.tile([0.0, 0.0, 1.0], (F, 1))
    ml = np.tile([1.0, 0.0, 0.0], (F, 1))
    R, _ = segment_frame_from_ml(origin, prox, ml, side="R")
    np.testing.assert_allclose(R[0].T @ R[0], np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R[0]), 1.0, atol=1e-9)
    np.testing.assert_allclose(R[0][:, 0], [1, 0, 0], atol=1e-9)   # ML right
    np.testing.assert_allclose(R[0][:, 1], [0, 1, 0], atol=1e-9)   # AP anterior
    np.testing.assert_allclose(R[0][:, 2], [0, 0, 1], atol=1e-9)   # long up


def test_segment_frame_from_ml_orthogonalises_non_perpendicular_ml():
    """A supplied ML not exactly perpendicular to the long axis is Gram-Schmidt
    orthogonalised -> result stays orthonormal and the long axis is untouched."""
    F = 2
    origin = np.zeros((F, 3))
    prox = np.tile([0.0, 0.0, 2.0], (F, 1))
    ml = np.tile([1.0, 0.0, 0.7], (F, 1))            # tilted into the long axis
    R, _ = segment_frame_from_ml(origin, prox, ml, side="R")
    np.testing.assert_allclose(R[0].T @ R[0], np.eye(3), atol=1e-9)
    np.testing.assert_allclose(R[0][:, 2], [0, 0, 1], atol=1e-9)   # long preserved
    # ML re-orthogonalised: its long-axis component is removed.
    assert abs(R[0][2, 0]) < 1e-9


def test_segment_frame_from_ml_side_flip():
    """Left side flips the supplied ML so +x stays subject-right (mirror sign)."""
    F = 1
    origin = np.zeros((F, 3))
    prox = np.tile([0.0, 0.0, 1.0], (F, 1))
    ml = np.tile([1.0, 0.0, 0.0], (F, 1))
    Rr, _ = segment_frame_from_ml(origin, prox, ml, side="R")
    Rl, _ = segment_frame_from_ml(origin, prox, -ml, side="L")     # mirror ML
    np.testing.assert_allclose(Rr[0][:, 0], Rl[0][:, 0], atol=1e-9)


def test_segment_frame_from_ml_nan_when_collinear():
    """An ML parallel to the long axis cannot fix the frontal plane -> NaN."""
    F = 2
    origin = np.zeros((F, 3))
    prox = np.tile([0.0, 0.0, 1.0], (F, 1))
    ml = np.tile([0.0, 0.0, 1.0], (F, 1))            # collinear with long
    R, _ = segment_frame_from_ml(origin, prox, ml, side="R")
    assert np.all(np.isnan(R))


def _rot_about(axis, ang):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def test_cluster_pose_recovers_known_rotation():
    """A rigid cluster rotated by a known R is recovered (a cluster-local vector
    transported by the fitted pose lands on its world image)."""
    P_ref = np.array([[40.0, 30.0, 250.0],
                      [-40.0, -30.0, 230.0],
                      [45.0, 0.0, 20.0]])
    R_true = _rot_about([0.3, 1.0, 0.2], np.radians(35))
    F = 4
    cl = np.stack([(R_true @ P_ref.T).T + np.array([10.0, -5.0, 3.0])
                   for _ in range(F)], axis=1)        # (k,F,3) + a translation
    R = cluster_pose_per_frame(cl, P_ref)
    assert R.shape == (F, 3, 3)
    # rotation only (translation-invariant): R_fit ~ R_true
    np.testing.assert_allclose(R[0], R_true, atol=1e-6)
    # a cluster-local axis maps to its world image
    v_local = np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(R[0] @ v_local, R_true @ v_local, atol=1e-6)


def test_cluster_pose_nan_for_missing_marker_frames():
    P_ref = np.eye(3) * 50.0
    cl = np.tile(P_ref[:, None, :], (1, 3, 1)).astype(float)   # (3,3,3)
    cl[0, 1, :] = np.nan                                       # frame 1 incomplete
    R = cluster_pose_per_frame(cl, P_ref)
    assert np.isfinite(R[0]).all() and np.isfinite(R[2]).all()
    assert np.all(np.isnan(R[1]))


# --------------------------------------------------------------------------
# Synthetic ground truth: cluster ML rejects single-marker wobble
# --------------------------------------------------------------------------

def _build_synth_thigh(wobble_mm=4.0, seed=0):
    """A thigh in PURE flexion about the ML axis (true IE = 0), with a 4 Hz wobble
    injected ONLY into the lateral knee marker (soft-tissue artefact). Returns the
    knee/hip points, the wobbling cluster, the wobbling lateral marker, and the
    cluster reference configuration."""
    rng = np.random.default_rng(seed)
    F = 300
    t = np.linspace(0, 1, F)
    flex = np.radians(20 * np.sin(2 * np.pi * 1.0 * t))      # +-20 deg, true IE=0
    long0 = np.array([0, 0, 400.0])
    cl_local = np.array([[40, 30, 250.0],
                         [-40, -30, 230.0],
                         [45, 0, 20.0]])                     # 3rd = lateral knee
    R = np.array([_rot_about([1.0, 0, 0], a) for a in flex])  # rigid flexion
    knee = np.zeros((F, 3))
    hip = np.einsum('fij,j->fi', R, long0)
    cluster = np.stack([np.einsum('fij,j->fi', R, m) for m in cl_local], axis=0)
    w = wobble_mm * np.sin(2 * np.pi * 4.0 * t)
    wob = np.stack([w, 0.5 * w, 0 * w], axis=1)
    wob_world = np.einsum('fij,fj->fi', R, wob)
    latk = cluster[2] + wob_world
    cluster_w = cluster.copy()
    cluster_w[2] = latk
    P_ref = np.nanmean(cluster_w, axis=1)
    _ = rng
    return knee, hip, cluster_w, latk, P_ref


def _hip_like_ie(R_thigh):
    """IE of the thigh frame vs a FIXED identity pelvis; true value 0 (pure
    flexion). Unwrapped + median-centred so a constant branch offset is removed."""
    F = R_thigh.shape[0]
    R_pelvis = np.broadcast_to(np.eye(3), (F, 3, 3))
    ie = jcs_angles(R_pelvis, R_thigh, "xyz")[:, 2]
    g = np.isfinite(ie)
    if g.sum() > 1:
        ie = ie.copy()
        ie[g] = np.degrees(np.unwrap(np.radians(ie[g])))
        ie[g] -= 360 * np.round(np.nanmedian(ie[g]) / 360.0)
    return ie


def _rom_ci(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(np.nanpercentile(x, 97.5) - np.nanpercentile(x, 2.5)) if x.size else np.nan


def test_single_marker_inflates_ie():
    """The wobbling single lateral marker inflates transverse cross-talk well
    above the analytic truth of 0."""
    knee, hip, cluster_w, latk, _ = _build_synth_thigh(4.0)
    R_single = segment_frame(knee, hip, latk, side="R")[0]
    assert _rom_ci(_hip_like_ie(R_single)) > 3.0


def test_cluster_ml_rejects_wobble():
    """The cluster-embedded ML (here +x in the cluster reference, transported by
    the rigid pose) keeps transverse cross-talk near the analytic truth (0)."""
    knee, hip, cluster_w, latk, P_ref = _build_synth_thigh(4.0)
    R_cl = cluster_pose_per_frame(cluster_w, P_ref)
    g = np.isfinite(R_cl).all(axis=(1, 2))
    ml_local = R_cl[g][0].T @ np.array([1.0, 0, 0])         # static ML in cluster
    ml_world = np.einsum('fij,j->fi', R_cl, ml_local)
    R_cluster = segment_frame_from_ml(knee, hip, ml_world, side="R")[0]
    assert _rom_ci(_hip_like_ie(R_cluster)) < 2.0


def test_cluster_beats_single_marker_head_to_head():
    knee, hip, cluster_w, latk, P_ref = _build_synth_thigh(4.0)
    R_single = segment_frame(knee, hip, latk, side="R")[0]
    R_cl = cluster_pose_per_frame(cluster_w, P_ref)
    g = np.isfinite(R_cl).all(axis=(1, 2))
    ml_local = R_cl[g][0].T @ np.array([1.0, 0, 0])
    ml_world = np.einsum('fij,j->fi', R_cl, ml_local)
    R_cluster = segment_frame_from_ml(knee, hip, ml_world, side="R")[0]
    rom_single = _rom_ci(_hip_like_ie(R_single))
    rom_cluster = _rom_ci(_hip_like_ie(R_cluster))
    assert rom_cluster < 0.5 * rom_single


# --------------------------------------------------------------------------
# Auto-build schema + backward compatibility
# --------------------------------------------------------------------------

def _cast_labels():
    """A static marker set with thigh/shank tracking triads + medial/lateral
    knee/ankle pairs (the YA0x layout) so CAST frames are buildable."""
    return ["RASIS", "LASIS", "RPSIS", "LPSIS",
            "RThigh_F", "RThigh_B", "RLKNEE", "RMKNEE",
            "RShank_F", "RShank_B", "RLANKLE", "RMANKLE", "RHEEL", "RTOE",
            "LThigh_F", "LThigh_B", "LLKNEE", "LMKNEE",
            "LShank_F", "LShank_B", "LLANKLE", "LMANKLE", "LHEEL", "LTOE"]


def _synth_markers(labels, F=6, seed=1):
    rng = np.random.default_rng(seed)
    data = (np.arange(len(labels))[:, None, None] * 50.0
            + rng.normal(scale=2.0, size=(len(labels), F, 3)))
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def test_autobuild_stamps_cluster_ml_on_thigh_shank():
    model = auto_build_model(_synth_markers(_cast_labels()))
    by = {s["name"]: s for s in model.segments}
    for nm, med, lat in (("R_THIGH", "RMKNEE", "RLKNEE"),
                         ("R_SHANK", "RMANKLE", "RLANKLE"),
                         ("L_THIGH", "LMKNEE", "LLKNEE"),
                         ("L_SHANK", "LMANKLE", "LLANKLE")):
        fr = by[nm]["frame"]
        assert fr["ml_source"] == "cluster"
        assert fr["ml_medial"] == med and fr["ml_lateral"] == lat
        assert len(fr["cluster"]) >= 3
        assert "plane" in fr                              # legacy fallback kept


def test_cluster_labels_includes_frame_cluster_not_medial():
    """The dynamic cluster markers are reported by ``cluster_labels`` (needed each
    frame); the static-only medial pair marker is NOT."""
    model = auto_build_model(_synth_markers(_cast_labels()))
    labs = model.cluster_labels()
    assert {"RThigh_F", "RThigh_B", "RLKNEE"} <= labs     # thigh tracking cluster
    assert {"RShank_F", "RShank_B", "RLANKLE"} <= labs    # shank tracking cluster
    assert "RMKNEE" not in labs and "RMANKLE" not in labs  # medial pair: static-only


def test_sparse_cluster_falls_back_to_single_marker():
    """A thigh with a lone tracking marker (cluster < 3) and no second shank
    marker degrades to the single-marker (``ml_source='marker'``) frame -- the
    backward-compatible path -- rather than crashing."""
    labels = ["RASIS", "LASIS", "RPSIS", "LPSIS",
              "RKNE", "RKNM", "RANK", "RANM", "RHEEL", "RTOE", "RTHI", "RTIB"]
    model = auto_build_model(_synth_markers(labels))
    by = {s["name"]: s for s in model.segments}
    if "R_THIGH" in by and "frame" in by["R_THIGH"]:
        assert by["R_THIGH"]["frame"].get("ml_source") == "marker"


def test_legacy_model_without_ml_source_uses_single_marker():
    """A saved model whose frame predates this change (no ``ml_source`` field)
    computes frames via the single plane marker -- unchanged, no crash."""
    markers = _synth_markers(_cast_labels())
    model = MarkerModel(
        segments=[{"name": "R_THIGH", "proximal": "R_HIP", "distal": "R_KNEE",
                   "frame": {"origin": "RLKNEE", "long": "RThigh_F",
                             "plane": "RThigh_B", "side": "R"}}],   # legacy schema
    )
    frames = model.compute_frames(markers, joint_centers={})
    assert frames["R_THIGH"].shape == (markers["data"].shape[1], 3, 3)
    assert np.isfinite(frames["R_THIGH"]).all()


def test_uncalibrated_cluster_frame_falls_back_to_plane():
    """If a cluster frame is never calibrated (no static pass), compute_frames
    must not crash: it falls back to the single plane marker."""
    markers = _synth_markers(_cast_labels())
    model = MarkerModel(
        segments=[{"name": "R_THIGH", "proximal": "R_HIP", "distal": "R_KNEE",
                   "frame": {"origin": "RLKNEE", "long": "RThigh_F",
                             "plane": "RThigh_B", "side": "R",
                             "ml_source": "cluster", "ml_medial": "RMKNEE",
                             "ml_lateral": "RLKNEE",
                             "cluster": ["RThigh_F", "RThigh_B", "RLKNEE"]}}],
    )
    # no calibrate() -> _frame_calib empty -> single-marker fallback
    frames = model.compute_frames(markers, joint_centers={})
    assert frames["R_THIGH"].shape == (markers["data"].shape[1], 3, 3)


# --------------------------------------------------------------------------
# Reliability grading under CAST
# --------------------------------------------------------------------------

def test_knee_ie_moderate_hip_high_under_cast():
    model = auto_build_model(_synth_markers(_cast_labels()), task="walk")
    rel = angle_reliability(model)
    for side in ("R", "L"):
        assert rel[f"{side}_KNEE_angle_IE"]["level"] == "moderate"
        assert "cross-talk" in rel[f"{side}_KNEE_angle_IE"]["reason"]
        assert rel[f"{side}_HIP_angle_IE"]["level"] == "high"
        assert rel[f"{side}_KNEE_angle_FE"]["level"] == "high"
        assert rel[f"{side}_ANKLE_angle_IE"]["level"] == "low"


def test_reliability_keys_match_compute_angles_under_cast():
    """Drift guard with cluster frames active: reliability keys == emitted angle
    channels (no missing / extra)."""
    markers = _synth_markers(_cast_labels())
    model = auto_build_model(markers, task="walk")
    model.calibrate(markers)
    res = model.apply(markers)
    assert set(angle_reliability(model)) == set(res["angles"])


# --------------------------------------------------------------------------
# Cross-talk diagnostic
# --------------------------------------------------------------------------

def test_crosstalk_flags_correlated_secondary_plane():
    """A secondary plane that is a scaled copy of flexion (perfect cross-talk)
    triggers both the correlation and the ROM-ratio warning."""
    t = np.linspace(0, 1, 200)
    fe = 30.0 * np.sin(2 * np.pi * t)
    ie = 0.8 * fe + 1.0                              # perfectly correlated, large
    ab = np.zeros_like(fe)
    d = crosstalk_diagnosis(fe, ab, ie)
    assert d["warn"] is True
    assert "corr_fe_ie" in d["flags"]
    assert d["corr_fe_ie"] > 0.99
    assert d["ie_fe_ratio"] > 0.7


def test_crosstalk_clean_signal_no_warning():
    """A small, decorrelated rotation riding on a large flexion arc raises no
    warning."""
    rng = np.random.default_rng(0)
    t = np.linspace(0, 1, 400)
    fe = 30.0 * np.sin(2 * np.pi * t)
    ie = 3.0 * np.sin(2 * np.pi * 3.1 * t + 0.7) + rng.normal(scale=0.3, size=t.size)
    ab = 4.0 * np.sin(2 * np.pi * 2.3 * t)
    d = crosstalk_diagnosis(fe, ab, ie)
    assert d["warn"] is False
    assert d["ie_fe_ratio"] < 1.0


def test_crosstalk_nan_safe():
    nan = np.full(50, np.nan)
    d = crosstalk_diagnosis(nan, nan, nan)
    assert d["warn"] is False
    assert np.isnan(d["corr_fe_ie"]) and np.isnan(d["ie_fe_ratio"])


# --------------------------------------------------------------------------
# Real-data regression (examples/) -- skipped if data / ezc3d absent
# --------------------------------------------------------------------------

def _load_markers(subj, name):
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    path = os.path.join(_EX, subj, name + ".c3d")
    if not os.path.isfile(path):
        pytest.skip(f"example file missing: {subj}/{name}")
    return read_c3d(path)["markers"]


def _legacy_clone(model):
    import copy
    m = copy.deepcopy(model)
    for s in m.segments:
        fr = s.get("frame") or {}
        if fr.get("ml_source") == "cluster":
            fr["ml_source"] = "marker"
    return m


@pytest.mark.parametrize("subj", ["YA01", "YA02"])
def test_cast_drops_hip_ie_and_preserves_fe_on_examples(subj):
    """On the real YA0x standing trials, CAST cuts the hip IE range to a
    physiological ~10-16 deg (legacy single-marker inflates it to ~30-41 deg) and
    preserves hip/knee flexion to < 2 deg RMS per frame."""
    static = _load_markers(subj, "static")
    cast = auto_build_model(static, task="generic"); cast.calibrate(static)
    legacy = _legacy_clone(cast); legacy.calibrate(static)

    hip_ie_legacy, hip_ie_cast, fe_rms = [], [], []
    for tr in ("st_1", "st_2", "st_3", "st_4"):
        mk = _load_markers(subj, tr)
        a_new = cast.apply(mk)["angles"]
        a_old = legacy.apply(mk)["angles"]
        for nm in ("R_HIP_angle_IE", "L_HIP_angle_IE"):
            hip_ie_legacy.append(_rom_ci(a_old[nm]))
            hip_ie_cast.append(_rom_ci(a_new[nm]))
        for nm in ("R_HIP_angle_FE", "R_KNEE_angle_FE",
                   "L_HIP_angle_FE", "L_KNEE_angle_FE"):
            fe_new = np.asarray(a_new[nm], float)
            # FE preserved up to a constant neutral offset (a frame ML rotation
            # about the long axis cannot change the sagittal RANGE), so compare
            # the de-meaned (offset-free) flexion waveforms.
            d = fe_new - np.asarray(a_old[nm], float)
            d = d[np.isfinite(d)]
            d = d - np.mean(d)
            fe_rms.append(float(np.sqrt(np.mean(d ** 2))) if d.size else 0.0)

    # CAST hip IE in the physiological band; clearly below the legacy inflation.
    assert np.mean(hip_ie_cast) < 20.0
    assert np.mean(hip_ie_cast) < 0.7 * np.mean(hip_ie_legacy)
    # flexion waveform preserved (shape unchanged; only a neutral offset differs)
    assert np.max(fe_rms) < 2.0


@pytest.mark.parametrize("subj", ["YA01", "YA02"])
def test_cast_reduces_knee_crosstalk_on_examples(subj):
    """CAST lowers the knee flexion<->IE correlation (cross-talk) vs the legacy
    single-marker frame on the real standing trials."""
    static = _load_markers(subj, "static")
    cast = auto_build_model(static, task="generic"); cast.calibrate(static)
    legacy = _legacy_clone(cast); legacy.calibrate(static)

    c_old, c_new = [], []
    for tr in ("st_1", "st_2", "st_3", "st_4"):
        mk = _load_markers(subj, tr)
        a_new = cast.apply(mk)["angles"]
        a_old = legacy.apply(mk)["angles"]
        for side in ("R", "L"):
            do = crosstalk_diagnosis(a_old[f"{side}_KNEE_angle_FE"],
                                     a_old[f"{side}_KNEE_angle_AB"],
                                     a_old[f"{side}_KNEE_angle_IE"])
            dn = crosstalk_diagnosis(a_new[f"{side}_KNEE_angle_FE"],
                                     a_new[f"{side}_KNEE_angle_AB"],
                                     a_new[f"{side}_KNEE_angle_IE"])
            c_old.append(do["corr_fe_ie"])
            c_new.append(dn["corr_fe_ie"])
    assert np.nanmean(c_new) < np.nanmean(c_old)
