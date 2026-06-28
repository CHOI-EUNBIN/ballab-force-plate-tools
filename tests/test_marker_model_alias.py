"""Regression tests for capability-based marker-role aliasing in
core.marker_model (researcher's normalize/alias/detect/tier design).

These pin the two real-data bugs and the safe-fallback policy:

  * BUG 1 -- suffix-medial labels. PiG/CGM2 label the medial knee/ankle markers
    as a SUFFIX (``RKNM``/``RANM``) or a bare ``RMED``; the old prefix-only
    parser missed them, so the joint centre could not be built. detect_knee_ankle
    now pairs prefix- AND suffix-medial forms.
  * BUG 2 -- subject prefix. Vicon multi-subject trials prefix every label with
    ``Subject:`` (e.g. ``Subject:RASI``); reading the side from the first char
    broke left/right. normalize_label drops the subject prefix first.
  * CODA variant. ``LIAS``/``RIAS`` (ASIS) and ``LIPS``/``RIPS`` (PSIS).
  * SAFE fallback. A knee with only the lateral marker (no medial) must NOT be
    fabricated -- that joint is simply omitted (no low-confidence guess).
  * before/after equivalence. The canonical prefix PiG set still builds the same
    joints (no regression).

Units are MILLIMETRES (Harrington hip regression constants are in mm).
"""

import numpy as np

from core.marker_model import (
    auto_build_model,
    detect_knee_ankle,
    detect_roles,
    normalize_label,
    _detect_pelvis,
    _detect_upper,
)
from core.marker_model import _match_role, ROLE_ALIASES


def _role_of(label):
    """Side-stripped role lookup through the lower-limb alias table."""
    n = normalize_label(label)
    return _match_role(n["core"], ROLE_ALIASES)


# --- helpers ---------------------------------------------------------------

def _markers(pts, F=4):
    labels = list(pts)
    data = np.stack([np.tile(np.asarray(pts[l], float), (F, 1)) for l in labels])
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _pelvis(prefix=""):
    return {
        f"{prefix}RASI": [120.0, 100.0, 1000.0], f"{prefix}LASI": [-120.0, 100.0, 1000.0],
        f"{prefix}RPSI": [60.0, -100.0, 1000.0], f"{prefix}LPSI": [-60.0, -100.0, 1000.0],
    }


def _right_leg(lateral_knee="RKNE", medial_knee="RKNM",
               lateral_ank="RANK", medial_ank="RANM"):
    pts = {
        lateral_knee: [150.0, 40.0, 500.0], medial_knee: [30.0, 40.0, 500.0],
        lateral_ank: [150.0, 40.0, 80.0], medial_ank: [30.0, 40.0, 80.0],
        "RHEE": [90.0, -20.0, 20.0], "RTOE": [90.0, 200.0, 20.0],
        "RTHI": [170.0, 90.0, 700.0], "RTIB": [170.0, 90.0, 300.0],
    }
    return {k: v for k, v in pts.items() if k}


# --- normalize_label -------------------------------------------------------

def test_normalize_strips_subject_prefix_and_reads_side():
    n = normalize_label("Subject:RASI")
    assert n["side"] == "R" and n["core"] == "ASI"
    n = normalize_label("Patient 3:LANK")
    assert n["side"] == "L" and n["core"] == "ANK"


def test_normalize_separators_and_words():
    assert normalize_label("R_KNE")["core"] == "KNE"
    assert normalize_label("R_KNE")["side"] == "R"
    assert normalize_label("RIGHT_ASIS") == {"raw": "RIGHT_ASIS", "side": "R", "core": "ASIS"}
    assert normalize_label("LEFT.PSIS")["side"] == "L"


def test_normalize_no_side_when_no_prefix():
    # A trunk landmark has no L/R; C7/T8/SACR keep their full core.
    assert normalize_label("C7") == {"raw": "C7", "side": "", "core": "C7"}
    assert normalize_label("SACR")["side"] == "" and normalize_label("SACR")["core"] == "SACR"


def test_normalize_side_suffix_off_by_default():
    # "SACR" ends in R but the suffix rule is OFF -> no spurious side.
    assert normalize_label("SACR")["side"] == ""
    # opt-in suffix rule (documented, high false-positive risk) does flip it.
    assert normalize_label("FOOTR", side_suffix=True)["side"] == "R"


# --- BUG 2: subject prefix in pelvis / knee detection ----------------------

def test_subject_prefix_pelvis_sides_correct():
    pel = _detect_pelvis(["Subject:RASI", "Subject:LASI",
                          "Subject:RPSI", "Subject:LPSI"])
    assert pel["asis_r"] == "Subject:RASI"
    assert pel["asis_l"] == "Subject:LASI"
    assert pel["psis_r"] == "Subject:RPSI"
    assert pel["psis_l"] == "Subject:LPSI"


def test_subject_prefix_knee_sides_correct():
    ka = detect_knee_ankle(["Subject:RKNE", "Subject:RKNM",
                            "Subject:LKNE", "Subject:LKNM"])
    assert ka[("R", "KNEE")] == {"L": "Subject:RKNE", "M": "Subject:RKNM"}
    assert ka[("L", "KNEE")] == {"L": "Subject:LKNE", "M": "Subject:LKNM"}


# --- BUG 1: suffix-medial knee/ankle ---------------------------------------

def test_suffix_medial_knee_and_ankle():
    ka = detect_knee_ankle(["RKNE", "RKNM", "RANK", "RANM"])
    assert ka[("R", "KNEE")] == {"L": "RKNE", "M": "RKNM"}
    assert ka[("R", "ANKLE")] == {"L": "RANK", "M": "RANM"}


def test_bare_med_is_ankle_medial():
    # PiG ``RMED`` = medial malleolus (ankle).
    ka = detect_knee_ankle(["RKNE", "RMED", "RANK"])
    assert ka[("R", "ANKLE")].get("M") == "RMED"


def test_prefix_medial_still_works():
    ka = detect_knee_ankle(["RMKNEE", "RLKNEE", "RMANK", "RLANK"])
    assert ka[("R", "KNEE")] == {"M": "RMKNEE", "L": "RLKNEE"}
    assert ka[("R", "ANKLE")] == {"M": "RMANK", "L": "RLANK"}


def test_suffix_medial_builds_full_knee_ankle_jcs():
    """End-to-end: a PiG suffix-medial set (RKNM/RANM) + subject-prefixed pelvis
    builds R_KNEE and R_ANKLE midpoint joints and produces finite JCS angles
    (the bug previously dropped these joints entirely)."""
    pts = dict(_pelvis(prefix="Subject:"))
    pts.update(_right_leg())             # RKNE/RKNM/RANK/RANM
    m = _markers(pts)
    model = auto_build_model(m)
    jn = {j["name"] for j in model.joints}
    assert {"R_KNEE", "R_ANKLE", "R_HIP", "L_HIP"} <= jn
    model.calibrate(m)
    res = model.apply(m)
    assert np.isfinite(res["angles"]["R_KNEE_angle_FE"][0])
    assert np.isfinite(res["angles"]["R_ANKLE_angle_FE"][0])


# --- CODA variant ----------------------------------------------------------

def test_coda_ias_ips_pelvis():
    pel = _detect_pelvis(["LIAS", "RIAS", "LIPS", "RIPS"])
    assert pel["asis_r"] == "RIAS" and pel["asis_l"] == "LIAS"
    assert pel["psis_r"] == "RIPS" and pel["psis_l"] == "LIPS"


# --- SAFE fallback: no fabrication -----------------------------------------

def test_lateral_only_knee_is_omitted_not_fabricated():
    """Only the lateral knee/ankle markers (no medial) -> the knee/ankle joints
    are OMITTED (the safe policy), never built from a single marker."""
    ka = detect_knee_ankle(["RKNE", "RANK"])
    assert ka[("R", "KNEE")] == {"L": "RKNE"}     # no medial -> no pair
    pts = dict(_pelvis())
    pts.update(_right_leg(medial_knee="", medial_ank=""))   # drop medials
    m = _markers(pts)
    model = auto_build_model(m)
    jn = {j["name"] for j in model.joints}
    assert "R_KNEE" not in jn and "R_ANKLE" not in jn
    # hips still build from the standard ASIS+PSIS regression (a real method).
    assert {"R_HIP", "L_HIP"} <= jn


# --- before/after equivalence (no regression) ------------------------------

def test_canonical_prefix_pig_unchanged():
    """The canonical prefix PiG set must build exactly the same lower-limb joints
    as before (the alias layer only adds coverage, never changes the model)."""
    pts = dict(_pelvis())
    pts.update({
        "RMKNEE": [30.0, 40.0, 500.0], "RLKNEE": [150.0, 40.0, 500.0],
        "RMANK": [30.0, 40.0, 80.0], "RLANK": [150.0, 40.0, 80.0],
        "RHEEL": [90.0, -20.0, 20.0], "RTOE": [90.0, 200.0, 20.0],
        "RTHI": [170.0, 90.0, 700.0], "RTIB": [170.0, 90.0, 300.0],
    })
    m = _markers(pts)
    model = auto_build_model(m)
    jn = {j["name"] for j in model.joints}
    assert {"R_HIP", "L_HIP", "R_KNEE", "R_ANKLE"} <= jn
    knee = next(j for j in model.joints if j["name"] == "R_KNEE")
    assert knee["method"] == "midpoint"
    assert knee["medial"] == "RMKNEE" and knee["lateral"] == "RLKNEE"


def test_detect_roles_pelvis_and_trunk():
    roles = detect_roles(["Subject:RASI", "Subject:LASI", "C7", "T8", "IJ", "PX"])
    assert roles["asis"]["R"] == "Subject:RASI"
    assert roles["asis"]["L"] == "Subject:LASI"
    assert roles["c7"]["_"] == "C7"
    assert roles["t8"]["_"] == "T8"


# --- ROLE_ALIASES side-strip clean-up (researcher confirmed) ---------------

def test_ankle_lat_codes_map_correctly():
    # ANK (lateral malleolus, PiG/OFM) -> ankle_lat, sided or bare.
    assert _role_of("ANK") == "ankle_lat"
    assert _role_of("RANK") == "ankle_lat"     # 'R' side stripped -> core ANK
    assert _role_of("ANKLE") == "ankle_lat"


def test_ankle_med_codes_map_correctly():
    # Medial malleolus, side-less cores: MM (HH), MMA (OFM), ANM (PiG condensed).
    assert _role_of("MM") == "ankle_med"
    assert _role_of("MMA") == "ankle_med"
    assert _role_of("ANM") == "ankle_med"
    # NB: bare MED is shared with knee_med and resolves to knee_med via the alias
    # table (insertion order). RMED -> ankle MEDIAL is decided by the dedicated
    # detect_knee_ankle logic (a leg already has a knee marker), not by the alias
    # lookup -- covered by test_bare_med_is_ankle_medial.
    ka = detect_knee_ankle(["RKNE", "RMED", "RANK"])
    assert ka[("R", "ANKLE")].get("M") == "RMED"


def test_removed_codes_no_longer_misclassified():
    # LM -> 'L' side stripped -> core 'M': must NOT be ankle_lat anymore.
    assert _role_of("LM") != "ankle_lat"
    # MANK removed from ankle_med exact set (collided with lateral once normalised).
    assert "MANK" not in ROLE_ALIASES["ankle_med"][0]
    # FMH (1st-MT head, medial -- a different landmark) removed from toe entirely.
    assert _role_of("FMH") != "toe"
    assert "FMH" not in ROLE_ALIASES["toe"][0]
    assert "FMH" not in ROLE_ALIASES["toe"][1]
    # TOE1 removed from the toe EXACT set; it still resolves via the generic
    # 'TOE' substring rule (any *TOE* label is a toe), which is intended.
    assert "TOE1" not in ROLE_ALIASES["toe"][0]
    # bare CA removed from heel (too short, false-positive risk).
    assert "CA" not in ROLE_ALIASES["heel"][0]
    assert _role_of("CA") != "heel"


def test_segment_cluster_markers_not_misread_as_joint():
    """A SEGMENT-named tracking cluster marker must never be claimed as a joint
    medial/lateral landmark. The classic collision: 'Shank' contains the ankle
    abbreviation 'ANK' as a substring (SH-ANK-F), so a loose substring match
    mis-reads 'RShank_F' as the lateral malleolus. Likewise 'Thigh' clusters."""
    ka = detect_knee_ankle(["RShank_F", "RShank_B", "RThigh_F", "RThigh_B",
                            "RLKNEE", "RMKNEE", "RLANKLE", "RMANKLE"])
    # the real lateral/medial ankle markers win their slots, NOT the shank cluster
    assert ka[("R", "ANKLE")] == {"L": "RLANKLE", "M": "RMANKLE"}
    assert ka[("R", "KNEE")] == {"L": "RLKNEE", "M": "RMKNEE"}
    # and the cluster markers are claimed by NOTHING (no ANKLE/KNEE key holds them)
    claimed = {lab for d in ka.values() for lab in d.values()}
    assert "RShank_F" not in claimed and "RShank_B" not in claimed
    assert "RThigh_F" not in claimed and "RThigh_B" not in claimed


def test_autobuild_foot_plane_is_lateral_ankle_not_shank():
    """Regression: with Thigh/Shank cluster markers present, the FOOT frame's
    plane point must be the lateral ANKLE marker, not a Shank cluster marker
    mis-detected as the malleolus."""
    pts = dict(_pelvis())
    # cluster markers listed BEFORE the ankle markers (as in real data) so the
    # order-dependent "first to claim wins" path actually exercises the collision.
    pts.update({
        "RThigh_F": [170.0, 90.0, 600.0], "RThigh_B": [170.0, -10.0, 600.0],
        "RShank_F": [170.0, 90.0, 300.0], "RShank_B": [170.0, -10.0, 300.0],
        "RMKNEE": [30.0, 40.0, 500.0], "RLKNEE": [150.0, 40.0, 500.0],
        "RMANKLE": [30.0, 40.0, 80.0], "RLANKLE": [150.0, 40.0, 80.0],
        "RHEEL": [90.0, -20.0, 20.0], "RTOE": [90.0, 200.0, 20.0],
    })
    model = auto_build_model(_markers(pts))
    foot = next((s for s in model.segments if s["name"] == "R_FOOT"), None)
    assert foot is not None and "frame" in foot
    assert foot["frame"]["plane"] == "RLANKLE"


def test_smh_maps_to_toe():
    # SMH = IOR 2nd-MT head, on the foot long axis -> toe.
    assert _role_of("SMH") == "toe"
    assert _role_of("RSMH") == "toe"           # 'R' stripped -> core SMH


def test_canonical_foot_codes_no_regression():
    # The everyday PiG foot codes still resolve (heel + toe = user's set).
    assert _role_of("HEE") == "heel"
    assert _role_of("RHEEL") == "heel"
    assert _role_of("TOE") == "toe"
    assert _role_of("RMET") == "toe"


def test_wrist_wra_radial_wrb_ulnar():
    # PiG wrist bar: WRA = radial (thumb side), WRB = ulnar (pinky side).
    up = _detect_upper(["RWRA", "RWRB", "LWRA", "LWRB"])
    assert up["R"]["styloid_r"] == "RWRA"
    assert up["R"]["styloid_u"] == "RWRB"
    assert up["L"]["styloid_r"] == "LWRA"
    assert up["L"]["styloid_u"] == "LWRB"
