"""Tests for per-channel angle reliability metadata and the foot/ankle frame
stability decision (core.marker_model).

Covers the foot/ankle redesign:
  * Step 1 (stability): the FOOT segment frame uses the LATERAL MALLEOLUS as its
    plane point (NOT the ankle joint centre), because an ankle-JC plane point is
    on the foot's sagittal plane -> near-degenerate frontal plane. We verify the
    chosen lat-malleolus frame is orthonormal/non-NaN and stable to a small
    medio-lateral heel-marker shift, and we DOCUMENT (numerically) why the ankle
    JC was rejected.
  * Step 2 (reliability): ``angle_reliability`` tags ANKLE _AB/_IE "low", and
    ANKLE _FE plus all knee/hip/upper-limb channels "high"; its keys match
    ``compute_angles`` exactly (drift guard); a foot medial/lateral marker pair
    (``frame["foot_ml"]``) promotes the ankle channels back to "high"; vector
    (frame-less) ankle has only one "high" channel and no _AB/_IE.
"""

import numpy as np

from core.marker_model import (
    MarkerModel,
    angle_reliability,
    auto_build_model,
    jcs_angles,
    segment_frame,
)


# --------------------------------------------------------------------------
# Step 1 -- foot frame stability (lateral malleolus, not the ankle JC)
# --------------------------------------------------------------------------

def _foot_static():
    """A flat right foot on the floor (x=ML right, y=AP anterior, z=up)."""
    heel = np.array([0.0, 0.0, 20.0])
    toe = np.array([0.0, 180.0, 20.0])
    lat_ankle = np.array([35.0, 30.0, 80.0])   # lateral malleolus (off-midline)
    ankle_jc = np.array([0.0, 30.0, 80.0])     # mid-malleoli -> ON the sagittal plane
    return heel, toe, lat_ankle, ankle_jc


def _tile(v, F=3):
    return np.tile(np.asarray(v, float), (F, 1))


def test_foot_frame_lateral_malleolus_is_well_conditioned():
    """The chosen FOOT frame (origin=toe, long=heel, plane=lateral malleolus) is
    orthonormal, right-handed and non-NaN for a flat static foot."""
    heel, toe, lat_ankle, _ = _foot_static()
    R, _ = segment_frame(_tile(toe), _tile(heel), _tile(lat_ankle), side="R")
    assert not np.isnan(R[0]).any()
    np.testing.assert_allclose(R[0].T @ R[0], np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R[0]), 1.0, atol=1e-9)


def test_foot_frame_lateral_is_far_more_stable_than_ankle_jc():
    """A 10 mm medio-lateral heel-marker shift must barely move the ankle angle
    with the lateral-malleolus plane point, but blows up with an ankle-JC plane
    point (near-degenerate frontal plane) -- the reason Step 1 keeps lat_ankle."""
    heel, toe, lat_ankle, ankle_jc = _foot_static()
    knee = np.array([0.0, 30.0, 480.0])
    Rsh, _ = segment_frame(_tile(ankle_jc), _tile(knee), _tile(lat_ankle), side="R")

    def ankle(heel_pt, plane_pt):
        Rf, _ = segment_frame(_tile(toe), _tile(heel_pt), _tile(plane_pt), side="R")
        return jcs_angles(Rsh, Rf, "xzy")[0]

    heel_off = heel + np.array([10.0, 0.0, 0.0])   # 10 mm lateral shift
    d_lat = np.abs(ankle(heel_off, lat_ankle) - ankle(heel, lat_ankle))
    d_jc = np.abs(ankle(heel_off, ankle_jc) - ankle(heel, ankle_jc))
    # lateral malleolus: small, bounded response (a few degrees).
    assert d_lat.max() < 15.0
    # ankle JC: huge response (tens to >100 deg) -> unstable, correctly rejected.
    assert d_jc.max() > 50.0


# --------------------------------------------------------------------------
# Step 2 -- angle_reliability metadata
# --------------------------------------------------------------------------

def _auto_lower_model(task="walk"):
    labels = ["RASI", "LASI", "RPSI", "LPSI",
              "RKNE", "RKNM", "RANK", "RANM", "RHEE", "RTOE",
              "LKNE", "LKNM", "LANK", "LANM", "LHEE", "LTOE",
              "RTHI", "LTHI", "RTIB", "LTIB"]
    F = 5
    data = (np.arange(len(labels))[:, None, None]
            + np.random.default_rng(0).normal(size=(len(labels), F, 3)))
    markers = {"labels": labels, "data": data, "time": np.arange(F) / 100.0}
    return auto_build_model(markers, task=task), markers


def test_ankle_frontal_rotation_low_others_high():
    model, _ = _auto_lower_model("walk")
    rel = angle_reliability(model)
    for side in ("R", "L"):
        assert rel[f"{side}_ANKLE_angle_FE"]["level"] == "high"
        assert rel[f"{side}_ANKLE_angle_AB"]["level"] == "low"
        assert rel[f"{side}_ANKLE_angle_IE"]["level"] == "low"
        # the low channels carry an explanatory reason
        assert "frontal plane" in rel[f"{side}_ANKLE_angle_AB"]["reason"]
        for joint in ("HIP", "KNEE"):
            for suf in ("_FE", "_AB", "_IE"):
                assert rel[f"{side}_{joint}_angle{suf}"]["level"] == "high"


def test_reliability_keys_match_compute_angles_exactly():
    """Drift guard: the reliability dict must key exactly the channels that
    ``compute_angles`` emits (no missing / no extra channels)."""
    model, markers = _auto_lower_model("walk")
    # compute_angles needs joint centres; reconstruct them from the static itself.
    model.calibrate(markers)
    res = model.apply(markers)
    angle_channels = set(res["angles"])
    rel_channels = set(angle_reliability(model))
    assert rel_channels == angle_channels


def test_foot_ml_pair_promotes_ankle_to_high():
    """If a FOOT frame declares a dedicated medial/lateral foot-marker pair
    (``frame["foot_ml"]``), the ankle inv/ev & rotation channels promote to
    'high' (Oxford-Foot-Model-style support)."""
    model = MarkerModel(
        segments=[
            {"name": "R_SHANK", "proximal": "R_KNEE", "distal": "R_ANKLE",
             "frame": {"origin": "R_ANKLE", "long": "R_KNEE", "plane": "RANK", "side": "R"}},
            {"name": "R_FOOT", "proximal": "RHEE", "distal": "RTOE",
             "frame": {"origin": "RTOE", "long": "RHEE", "plane": "RANK",
                       "side": "R", "foot_ml": True}},
        ],
        angles=[{"name": "R_ANKLE_angle", "segment_a": "R_SHANK",
                 "segment_b": "R_FOOT", "mode": "jcs", "sequence": "xzy"}],
    )
    rel = angle_reliability(model)
    assert rel["R_ANKLE_angle_AB"]["level"] == "high"
    assert rel["R_ANKLE_angle_IE"]["level"] == "high"


def test_vector_mode_ankle_single_high_channel():
    """A frame-less (vector) ankle angle emits ONE channel meaning FE; it is
    'high' and there is no _AB/_IE channel at all."""
    model = MarkerModel(
        segments=[
            {"name": "R_SHANK", "proximal": "R_KNEE", "distal": "R_ANKLE"},
            {"name": "R_FOOT", "proximal": "RHEE", "distal": "RTOE"},
        ],
        angles=[{"name": "R_ANKLE_angle", "segment_a": "R_SHANK",
                 "segment_b": "R_FOOT"}],   # no mode -> vector
    )
    rel = angle_reliability(model)
    assert set(rel) == {"R_ANKLE_angle"}
    assert rel["R_ANKLE_angle"]["level"] == "high"
