"""Regression tests for the UPPER-LIMB auto-build (core.marker_model).

``auto_build_model`` is capability-based: it scans the static trial's labels and
builds the upper limb only when the markers exist (ISB; Wu et al. 2005), leaving
the lower limb untouched. Joint centres: SHOULDER = acromion (single-landmark
surface estimate), ELBOW = midpoint(medial, lateral epicondyle), WRIST =
midpoint(ulnar, radial styloid). Segments TRUNK / UPPERARM / FOREARM each carry
a segment coordinate system (``frame``); angles are signed JCS (Cardan/Euler):
SHOULDER "zxz" (ISB Y-X-Y mapped to our z-long SCS), ELBOW/WRIST "xyz".

Synthetic trials with analytically known answers pin:
  * detection + role aliasing (ACR/MEL/LEL/USP/RSP/IJ/C7/PX/T8),
  * JC reconstruction is non-NaN and equals the expected anatomical point,
  * a straight (neutral) arm -> SHOULDER & ELBOW FE/AB/IE ~ 0,
  * 40 deg elbow flexion -> ELBOW_FE ~ 40, mirror-consistent L/R, no cross-talk,
  * graceful skip: no arm markers -> lower limb only; lone acromion -> pruned,
  * JSON round-trip preserves the upper-limb frames + JCS mode/sequence.

Units are MILLIMETRES (consistent with the Harrington hip regression elsewhere).
"""

import numpy as np

from core.marker_model import MarkerModel, auto_build_model, _detect_upper


# --- builders --------------------------------------------------------------

def _Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _Ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _markers(pts, F=4):
    labels = list(pts)
    data = np.stack([np.tile(np.asarray(pts[l], float), (F, 1)) for l in labels])
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _trunk_pts():
    """ISB thorax landmarks; lab frame x=right, y=anterior, z=up."""
    return {"IJ": [0.0, 80.0, 1350.0], "C7": [0.0, -80.0, 1350.0],
            "PX": [0.0, 80.0, 1150.0], "T8": [0.0, -80.0, 1150.0]}


def _arm_pts(side, R_fore=None):
    """One arm hanging straight down (long axis = world +z). The elbow JC is the
    midpoint of the epicondyles, the wrist JC the midpoint of the styloids.

    ``R_fore`` (3x3) optionally rotates the forearm markers (styloids + a forearm
    cluster marker) about the elbow JC, for flexion tests.
    """
    sx = 1.0 if side == "R" else -1.0
    base = 180.0 * sx
    sh = np.array([base, 0.0, 1400.0])
    el = np.array([base, 0.0, 1100.0])
    wr = np.array([base, 0.0, 850.0])
    pts = {
        f"{side}ACR": sh,
        f"{side}MEL": el + [-sx * 40.0, 0, 0], f"{side}LEL": el + [sx * 40.0, 0, 0],
        f"{side}USP": wr + [-sx * 30.0, 0, 0], f"{side}RSP": wr + [sx * 30.0, 0, 0],
        f"{side}FA": [base + sx * 50.0, 30.0, 975.0],    # extra forearm cluster
        f"{side}UA": [base + sx * 50.0, 30.0, 1250.0],   # extra upper-arm cluster
    }
    if R_fore is not None:
        for lab in (f"{side}USP", f"{side}RSP", f"{side}FA"):
            pts[lab] = (R_fore @ (np.asarray(pts[lab]) - el)) + el
    return pts


def _lower_pts():
    """A minimal one-leg lower-limb marker set (so we can prove the lower limb is
    unaffected by adding/omitting the arm)."""
    return {
        "RASIS": [120.0, 100.0, 1000.0], "LASIS": [-120.0, 100.0, 1000.0],
        "RPSIS": [60.0, -100.0, 1000.0], "LPSIS": [-60.0, -100.0, 1000.0],
        "RMKNEE": [30.0, 40.0, 500.0], "RLKNEE": [150.0, 40.0, 500.0],
        "RMANK": [30.0, 40.0, 80.0], "RLANK": [150.0, 40.0, 80.0],
        "RHEEL": [90.0, -20.0, 20.0], "RTOE": [90.0, 200.0, 20.0],
        "RTHI": [170.0, 90.0, 700.0], "RTIB": [170.0, 90.0, 300.0],
    }


def _build_apply(pts):
    m = _markers(pts)
    model = auto_build_model(m)
    model.calibrate(m)
    return model, model.apply(m), m


# --- detection / aliasing --------------------------------------------------

def test_detect_upper_roles_and_sides():
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R"))
    pts.update(_arm_pts("L"))
    det = _detect_upper(list(pts))
    for side in ("R", "L"):
        assert det[side]["acromion"] == f"{side}ACR"
        assert det[side]["epi_m"] == f"{side}MEL"
        assert det[side]["epi_l"] == f"{side}LEL"
        assert det[side]["styloid_u"] == f"{side}USP"
        assert det[side]["styloid_r"] == f"{side}RSP"
    assert det["TRUNK"] == {"ij": "IJ", "c7": "C7", "px": "PX", "t8": "T8"}


# --- structure + JC reconstruction -----------------------------------------

def test_autobuild_upper_structure_and_jc():
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R"))
    pts.update(_arm_pts("L"))
    model, res, _ = _build_apply(pts)

    jnames = {j["name"] for j in model.joints}
    assert {"R_SHOULDER", "R_ELBOW", "R_WRIST",
            "L_SHOULDER", "L_ELBOW", "L_WRIST"} <= jnames

    framed = {s["name"] for s in model.segments if "frame" in s}
    assert {"TRUNK", "R_UPPERARM", "R_FOREARM",
            "L_UPPERARM", "L_FOREARM"} <= framed

    # Joint centres land on the expected anatomical points (non-NaN).
    np.testing.assert_allclose(res["joint_centers"]["R_SHOULDER"][0], [180, 0, 1400], atol=1e-6)
    np.testing.assert_allclose(res["joint_centers"]["R_ELBOW"][0], [180, 0, 1100], atol=1e-6)
    np.testing.assert_allclose(res["joint_centers"]["R_WRIST"][0], [180, 0, 850], atol=1e-6)

    # SHOULDER uses the ISB proper-Euler order (mapped to z-long), elbow Cardan.
    seq = {a["name"]: a.get("sequence") for a in model.angles}
    assert seq["R_SHOULDER_angle"] == "zxz"
    assert seq["R_ELBOW_angle"] == "xyz"


def test_autobuild_upper_three_channels():
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R"))
    _, res, _ = _build_apply(pts)
    for joint in ("R_SHOULDER", "R_ELBOW"):
        for suf in ("_FE", "_AB", "_IE"):
            assert f"{joint}_angle{suf}" in res["angles"]


# --- neutral standing ------------------------------------------------------

def test_neutral_arm_near_zero():
    """A straight, vertically-hanging arm -> SHOULDER & ELBOW all components ~0
    (radial-styloid plane point keeps the forearm ML axis co-directed with the
    upper arm, so no constant axial offset)."""
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R"))
    pts.update(_arm_pts("L"))
    _, res, _ = _build_apply(pts)
    for side in ("R", "L"):
        for joint in ("SHOULDER", "ELBOW"):
            for suf in ("_FE", "_AB", "_IE"):
                v = res["angles"][f"{side}_{joint}_angle{suf}"][0]
                assert np.isfinite(v), f"{side}_{joint}{suf} is NaN"
                assert abs(v) < 1e-3, f"{side}_{joint}{suf} = {v} (expected ~0)"


# --- elbow flexion + mirror ------------------------------------------------

def test_elbow_flexion_sign_and_mirror():
    """Flex both elbows 40 deg (forearm swings about +x = ML): ELBOW_FE ~ 40 on
    both sides (mirror-consistent), with no cross-talk into AB/IE."""
    flex = _Rx(np.radians(40))
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R", R_fore=flex))
    pts.update(_arm_pts("L", R_fore=flex))
    _, res, _ = _build_apply(pts)
    for side in ("R", "L"):
        fe = res["angles"][f"{side}_ELBOW_angle_FE"][0]
        ab = res["angles"][f"{side}_ELBOW_angle_AB"][0]
        ie = res["angles"][f"{side}_ELBOW_angle_IE"][0]
        assert abs(fe - 40.0) < 1e-3, f"{side} ELBOW_FE = {fe} (expected ~40)"
        assert abs(ab) < 1e-3 and abs(ie) < 1e-3


# --- shoulder elevation (ISB Y-X-Y proper-Euler path) ----------------------

def _arm_rotated_about_shoulder(side, R):
    """A whole arm (upper + forearm) rigidly rotated by ``R`` about the shoulder
    JC, for thoracohumeral-elevation tests. The acromion (shoulder JC) is the
    fixed pivot; every distal arm marker rotates with the humerus + forearm."""
    pts = _arm_pts(side)
    sh = np.asarray(pts[f"{side}ACR"], float)
    for lab in list(pts):
        if lab == f"{side}ACR":
            continue
        pts[lab] = (R @ (np.asarray(pts[lab], float) - sh)) + sh
    return pts


def test_shoulder_elevation_uses_yxy_decomposition():
    """Abduct both arms 60 deg in the frontal plane. With the ISB Y-X-Y order
    (mapped to this module's z-long SCS as ``zxz``) the MIDDLE component
    (``_AB`` = elevation angle) must read ~60 deg -- proving the proper-Euler
    path in ``_decompose_cardan`` is actually exercised, not just stored.

    Frontal-plane elevation is the degenerate plane-of-elevation case of a
    Y-X-Y parametrisation, so the first/third components sit at the conventional
    +-90 deg; we only pin the well-defined elevation magnitude and that every
    component reads the SAME (left/right unified) positive sign.

    Abduction is a MIRRORED motion, so the left arm gets the mirror-image world
    rotation (``_Ry(-60)``); the left AB sign flip in ``compute_angles`` then
    makes both shoulders read +60 (the unified sign convention)."""
    pts = dict(_trunk_pts())
    pts.update(_arm_rotated_about_shoulder("R", _Ry(np.radians(60))))
    pts.update(_arm_rotated_about_shoulder("L", _Ry(np.radians(-60))))
    _, res, _ = _build_apply(pts)
    for side in ("R", "L"):
        comps = [res["angles"][f"{side}_SHOULDER_angle{suf}"][0]
                 for suf in ("_FE", "_AB", "_IE")]
        assert np.all(np.isfinite(comps)), f"{side} shoulder has NaN: {comps}"
        elevation = res["angles"][f"{side}_SHOULDER_angle_AB"][0]
        assert abs(elevation - 60.0) < 1e-3, f"{side} elevation = {elevation} (expected ~60)"


def test_shoulder_near_overhead_singularity_is_finite():
    """Raise the arm to ~175 deg elevation, into the neighbourhood of the Y-X-Y
    gimbal-lock singularity (true elevation 0/180 deg). The decomposition must
    stay FINITE and stable (no NaN/inf, no exception); the elevation magnitude
    still tracks (~175 deg). This pins the documented singularity caveat: the
    shoulder yxy order is well-behaved except exactly at full elevation."""
    overhead = _Ry(np.radians(175))
    pts = dict(_trunk_pts())
    pts.update(_arm_rotated_about_shoulder("R", overhead))
    _, res, _ = _build_apply(pts)
    comps = [res["angles"][f"R_SHOULDER_angle{suf}"][0]
             for suf in ("_FE", "_AB", "_IE")]
    assert np.all(np.isfinite(comps)), f"near-singularity not finite: {comps}"
    elevation = res["angles"]["R_SHOULDER_angle_AB"][0]
    assert abs(elevation - 175.0) < 1e-3, f"elevation = {elevation} (expected ~175)"


# --- wrist (needs a HAND segment from a hand/MCP marker) --------------------

def _arm_with_hand(side, R_hand=None):
    """``_arm_pts`` plus a 3rd-MCP hand marker straight below the wrist, so the
    optional HAND segment + WRIST angle are built. ``R_hand`` optionally rotates
    the hand marker about the wrist JC (for flexion tests)."""
    pts = _arm_pts(side)
    sx = 1.0 if side == "R" else -1.0
    base = 180.0 * sx
    wr = np.array([base, 0.0, 850.0])
    pts[f"{side}MCP"] = np.array([base, 0.0, 700.0])    # hand: straight down
    if R_hand is not None:
        pts[f"{side}MCP"] = (R_hand @ (pts[f"{side}MCP"] - wr)) + wr
    return pts


def test_wrist_segment_and_neutral_zero():
    """A hand/MCP marker builds the optional HAND segment and a JCS WRIST angle;
    a straight neutral hand reads ~0 on all three components (both sides)."""
    pts = dict(_trunk_pts())
    pts.update(_arm_with_hand("R"))
    pts.update(_arm_with_hand("L"))
    model, res, _ = _build_apply(pts)
    snames = {s["name"] for s in model.segments}
    assert {"R_HAND", "L_HAND"} <= snames
    for side in ("R", "L"):
        for suf in ("_FE", "_AB", "_IE"):
            v = res["angles"][f"{side}_WRIST_angle{suf}"][0]
            assert np.isfinite(v) and abs(v) < 1e-3, f"{side} WRIST{suf} = {v}"


def test_wrist_flexion_sign_and_mirror():
    """Flex the hand 30 deg about the ML axis: WRIST_FE ~ 30 on both sides
    (mirror-consistent), no cross-talk into deviation (AB) or axial (IE)."""
    flex = _Rx(np.radians(30))
    pts = dict(_trunk_pts())
    pts.update(_arm_with_hand("R", R_hand=flex))
    pts.update(_arm_with_hand("L", R_hand=flex))
    _, res, _ = _build_apply(pts)
    for side in ("R", "L"):
        fe = res["angles"][f"{side}_WRIST_angle_FE"][0]
        ab = res["angles"][f"{side}_WRIST_angle_AB"][0]
        ie = res["angles"][f"{side}_WRIST_angle_IE"][0]
        assert abs(fe - 30.0) < 1e-3, f"{side} WRIST_FE = {fe} (expected ~30)"
        assert abs(ab) < 1e-3 and abs(ie) < 1e-3


# --- graceful capability handling ------------------------------------------

def test_no_arm_markers_lower_limb_only():
    """A trial with no upper-limb markers builds the lower limb only (no error,
    no spurious upper joints) and calibrates cleanly."""
    model, _, _ = _build_apply(_lower_pts())
    jnames = {j["name"] for j in model.joints}
    assert jnames == {"R_HIP", "L_HIP", "R_KNEE", "R_ANKLE"}
    assert not any(n in jnames for n in ("R_SHOULDER", "R_ELBOW", "R_WRIST"))
    snames = {s["name"] for s in model.segments}
    assert {"PELVIS", "R_THIGH", "R_SHANK", "R_FOOT"} <= snames


def test_lone_acromion_is_pruned():
    """A single acromion (no elbow/wrist markers) cannot be rigidly tracked
    (cluster < 3) and is pruned -- the lower limb is unchanged, no exception."""
    pts = dict(_lower_pts())
    pts["RACR"] = [180.0, 0.0, 1400.0]
    model, _, _ = _build_apply(pts)
    jnames = {j["name"] for j in model.joints}
    assert "R_SHOULDER" not in jnames
    assert jnames == {"R_HIP", "L_HIP", "R_KNEE", "R_ANKLE"}


def test_lower_limb_unaffected_by_arm():
    """Adding a full arm must not change the lower-limb joint centres or angles
    (the upper limb is built on top, never altering the leg)."""
    lower = _lower_pts()
    _, res_lo, _ = _build_apply(dict(lower))
    pts = dict(lower)
    pts.update(_trunk_pts())
    pts.update(_arm_pts("R"))
    _, res_hi, _ = _build_apply(pts)
    for nm in ("R_HIP", "L_HIP", "R_KNEE", "R_ANKLE"):
        np.testing.assert_allclose(res_lo["joint_centers"][nm],
                                   res_hi["joint_centers"][nm], atol=1e-9)
    for ch in ("R_KNEE_angle_FE", "R_KNEE_angle_AB", "R_ANKLE_angle_FE"):
        np.testing.assert_allclose(res_lo["angles"][ch], res_hi["angles"][ch], atol=1e-9)


# --- persistence -----------------------------------------------------------

def test_upper_model_json_roundtrip():
    pts = dict(_trunk_pts())
    pts.update(_arm_pts("R"))
    m = _markers(pts)
    model = auto_build_model(m)
    reloaded = MarkerModel.from_dict(model.to_dict())
    framed = {s["name"] for s in reloaded.segments if "frame" in s}
    assert {"TRUNK", "R_UPPERARM", "R_FOREARM"} <= framed
    seq = {a["name"]: a.get("sequence") for a in reloaded.angles if a.get("mode") == "jcs"}
    assert seq.get("R_SHOULDER_angle") == "zxz"
    assert seq.get("R_ELBOW_angle") == "xyz"
    reloaded.calibrate(m)
    res = reloaded.apply(m)
    assert "R_ELBOW_angle_FE" in res["angles"]
