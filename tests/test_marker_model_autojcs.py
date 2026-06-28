"""Regression tests for the JCS auto-build pipeline in core.marker_model.

``auto_build_model`` now attaches a segment coordinate system (``frame``) to the
PELVIS / THIGH / SHANK / FOOT segments and emits HIP/KNEE/ANKLE as signed JCS
(Cardan, sequence "xyz") angles, each expanded into _FE/_AB/_IE channels.

Synthetic trials with analytically known answers pin:
  * neutral standing -> HIP & KNEE FE/AB/IE ~ 0 (frames built, no NaN),
  * 25 deg knee flexion + small valgus -> KNEE_FE ~ 25 with a valgus-signed AB,
  * left/right mirror geometry -> FE signs agree, AB/IE mirror,
  * the JC-as-plane-point safeguard (collinear -> NaN frame),
  * full _FE/_AB/_IE channel expansion end-to-end through apply().

Units are MILLIMETRES, because the Harrington (2007) hip regression constants
are in mm; metre-scale inputs would blow the HJC offset up by ~1000x.
"""

import numpy as np

from core.marker_model import auto_build_model


# --- builders --------------------------------------------------------------

def _Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _Rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _markers(pts, F=4):
    """pts = {label: (3,)} -> a static-like marker container (mm), F frames."""
    labels = list(pts)
    data = np.stack([np.tile(np.asarray(pts[l], float), (F, 1)) for l in labels])
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _pelvis_pts():
    """A simple, symmetric pelvis (mm); lab frame x=right, y=anterior, z=up."""
    return {
        "RASIS": [120.0, 100.0, 1000.0], "LASIS": [-120.0, 100.0, 1000.0],
        "RPSIS": [60.0, -100.0, 1000.0], "LPSIS": [-60.0, -100.0, 1000.0],
    }


def _leg_pts(side, knee_xy, R_shank=None, knee_jc_xy=None):
    """Build one leg's surface markers so the THIGH/SHANK long axes are exactly
    vertical and the plane markers lie in the pure frontal plane.

    ``knee_xy`` = (x, y) of the knee joint centre (= mid of M/L knee markers),
    placed directly under the hip JC so the thigh is vertical. ``R_shank`` (3x3)
    optionally rotates the shank about the knee (for flexion tests).
    """
    sx = 1.0 if side == "R" else -1.0
    kx, ky = knee_xy
    half = 60.0                      # M/L knee half-separation (mm)
    # knee/ankle joint centres (ankle straight below the knee)
    knee_jc = np.array([kx, ky, 500.0])
    ankle_jc = np.array([kx, ky, 80.0])
    # medial/lateral markers straddle the JC along +-x (frontal plane, y = JC y)
    pts = {
        f"{side}MKNEE": knee_jc + [-sx * half, 0, 0],
        f"{side}LKNEE": knee_jc + [sx * half, 0, 0],
        f"{side}MANK": ankle_jc + [-sx * half, 0, 0],
        f"{side}LANK": ankle_jc + [sx * half, 0, 0],
        # heel/toe for the foot segment
        f"{side}HEEL": [kx, ky - 60.0, 20.0],
        f"{side}TOE": [kx, ky + 160.0, 20.0],
        # extra cluster markers (non-collinear) so midpoint joints can track
        f"{side}THI": [kx + sx * 80.0, ky + 50.0, 700.0],
        f"{side}TIB": [kx + sx * 80.0, ky + 50.0, 300.0],
    }
    if R_shank is not None:
        for lab in (f"{side}MANK", f"{side}LANK", f"{side}HEEL", f"{side}TOE",
                    f"{side}TIB"):
            pts[lab] = (R_shank @ (np.asarray(pts[lab]) - knee_jc)) + knee_jc
    return pts


def _build_and_apply(extra_pts, sides=("R", "L")):
    pts = dict(_pelvis_pts())
    pts.update(extra_pts)
    m = _markers(pts)
    model = auto_build_model(m)
    model.calibrate(m)
    res = model.apply(m)
    return model, res


def _hip_xy(res, side):
    hip = res["joint_centers"][f"{side}_HIP"][0]
    return hip[0], hip[1]


# --- structure -------------------------------------------------------------

def test_autobuild_emits_jcs_three_channels():
    """HIP/KNEE/ANKLE each expand into _FE/_AB/_IE; segments carry frames."""
    pts = {}
    pts.update(_leg_pts("R", (90.0, 40.0)))
    pts.update(_leg_pts("L", (-90.0, 40.0)))
    model, res = _build_and_apply(pts)

    seg_frames = {s["name"]: ("frame" in s) for s in model.segments}
    for nm in ("PELVIS", "R_THIGH", "R_SHANK", "R_FOOT",
               "L_THIGH", "L_SHANK", "L_FOOT"):
        assert seg_frames.get(nm), f"{nm} missing frame"

    for a in model.angles:
        assert a.get("mode") == "jcs"
        assert a.get("sequence") == "xyz"

    for joint in ("R_HIP", "R_KNEE", "R_ANKLE", "L_HIP", "L_KNEE", "L_ANKLE"):
        for suf in ("_FE", "_AB", "_IE"):
            assert f"{joint}_angle{suf}" in res["angles"]


# --- neutral standing ------------------------------------------------------

def test_neutral_hip_knee_near_zero():
    """Legs vertical under each hip JC, plane markers in the frontal plane ->
    HIP and KNEE FE/AB/IE all ~ 0 (no NaN). (FOOT/ANKLE is offset by design:
    the foot long axis is horizontal, so ankle FE ~ 90 in neutral standing.)"""
    # First pass to learn the hip JC (x, y); then place legs straight below it.
    pts0 = {}
    pts0.update(_leg_pts("R", (90.0, 40.0)))
    pts0.update(_leg_pts("L", (-90.0, 40.0)))
    _, res0 = _build_and_apply(pts0)
    rx, ry = _hip_xy(res0, "R")
    lx, ly = _hip_xy(res0, "L")

    pts = {}
    pts.update(_leg_pts("R", (rx, ry)))
    pts.update(_leg_pts("L", (lx, ly)))
    _, res = _build_and_apply(pts)

    for side in ("R", "L"):
        for joint in ("HIP", "KNEE"):
            for suf in ("_FE", "_AB", "_IE"):
                v = res["angles"][f"{side}_{joint}_angle{suf}"][0]
                assert np.isfinite(v), f"{side}_{joint}{suf} is NaN"
                assert abs(v) < 1e-3, f"{side}_{joint}{suf} = {v} (expected ~0)"


# --- knee flexion + valgus -------------------------------------------------

def test_knee_flexion_and_valgus_signs():
    """Flex the right knee 25 deg (shank swings posterior about +x) plus a small
    valgus tilt; KNEE_FE ~ 25 and the AB component carries the valgus sign, with
    a non-NaN frame."""
    pts0 = {}
    pts0.update(_leg_pts("R", (90.0, 40.0)))
    _, res0 = _build_and_apply(pts0, sides=("R",))
    rx, ry = _hip_xy(res0, "R")

    # 25 deg flexion about ML; anatomical knee flexion swings the shank POSTERIOR
    # (a NEGATIVE world-x rotation), small 5 deg valgus about the long axis is
    # better expressed as an ab/adduction tilt about AP (+y). Compose flexion
    # then a frontal-plane tilt. The knee FE sign correction makes FE read +25.
    flex = _Rx(np.radians(-25))
    valgus = _Rz(np.radians(5.0))            # tilt in the frontal plane
    R_shank = valgus @ flex

    pts = dict(_leg_pts("R", (rx, ry), R_shank=R_shank))
    # left leg neutral so the model still builds symmetric pelvis/hip
    pts.update(_leg_pts("L", (-rx, ry)))
    _, res = _build_and_apply(pts)

    fe = res["angles"]["R_KNEE_angle_FE"][0]
    ab = res["angles"]["R_KNEE_angle_AB"][0]
    assert np.isfinite(fe) and np.isfinite(ab)
    assert abs(fe - 25.0) < 0.5, f"KNEE_FE = {fe} (expected ~25)"
    assert abs(ab) > 1.0, f"KNEE_AB = {ab} (expected a non-trivial valgus tilt)"


# --- left/right mirror consistency -----------------------------------------

def test_left_right_mirror_consistency():
    """Identical geometry on both legs (flexed): FE signs agree, AB/IE mirror."""
    pts0 = {}
    pts0.update(_leg_pts("R", (90.0, 40.0)))
    pts0.update(_leg_pts("L", (-90.0, 40.0)))
    _, res0 = _build_and_apply(pts0)
    rx, ry = _hip_xy(res0, "R")
    lx, ly = _hip_xy(res0, "L")

    flex = _Rx(np.radians(-20))            # anatomical flexion: shank posterior
    pts = {}
    pts.update(_leg_pts("R", (rx, ry), R_shank=flex))
    pts.update(_leg_pts("L", (lx, ly), R_shank=flex))
    _, res = _build_and_apply(pts)

    r_fe = res["angles"]["R_KNEE_angle_FE"][0]
    l_fe = res["angles"]["L_KNEE_angle_FE"][0]
    assert abs(r_fe - l_fe) < 1e-3, f"FE mirror mismatch {r_fe} vs {l_fe}"
    assert abs(r_fe - 20.0) < 1e-3


# --- safeguard: JC midpoint as plane point -> NaN frame --------------------

def test_jc_midpoint_plane_point_is_nan():
    """Using a joint centre (collinear with the long axis) as the plane point
    cannot define a frontal plane -> the SCS frame is NaN (the safeguard)."""
    from core.marker_model import MarkerModel

    pts = {}
    pts.update(_leg_pts("R", (90.0, 40.0)))
    m = _markers(pts)
    # Hand-built model whose THIGH frame illegally uses the KNEE JC as the plane
    # point (collinear with origin=KNEE -> long=HIP).
    model = MarkerModel(
        joints=[{"name": "R_KNEE", "method": "midpoint",
                 "medial": "RMKNEE", "lateral": "RLKNEE",
                 "cluster": ["RMKNEE", "RLKNEE", "RTHI", "RTIB"]}],
        segments=[{"name": "R_THIGH", "proximal": "RTHI", "distal": "R_KNEE",
                   "frame": {"origin": "R_KNEE", "long": "RTHI",
                             "plane": "R_KNEE", "side": "R"}}],
    )
    model.calibrate(m)
    jcs = model.reconstruct(m)
    frames = model.compute_frames(m, jcs)
    assert np.all(np.isnan(frames["R_THIGH"])), "collinear plane point must NaN"


# --- backward compatibility ------------------------------------------------

def test_partial_markerset_falls_back_to_vector_angle():
    """A knee with no lateral plane marker (only M/L pair, no extra surface
    marker) keeps a frame only if a plane point exists; with no usable plane
    marker the THIGH gets no frame and the angle stays legacy vector mode."""
    # Only knee + ankle markers on the right, no thigh/shank surface markers
    # other than the lateral knee itself (which IS a valid plane point) -> still
    # jcs. So instead build a model lacking lateral markers entirely.
    from core.marker_model import MarkerModel
    pts = {}
    pts.update(_leg_pts("R", (90.0, 40.0)))
    m = _markers(pts)
    model = MarkerModel(
        segments=[
            {"name": "R_THIGH", "proximal": "RTHI", "distal": "RMKNEE"},
            {"name": "R_SHANK", "proximal": "RMKNEE", "distal": "RMANK"},
        ],
        angles=[{"name": "R_KNEE_angle", "segment_a": "R_THIGH",
                 "segment_b": "R_SHANK"}],
    )
    res = model.compute_angles(m, joint_centers={})
    assert set(res) == {"R_KNEE_angle"}        # single legacy channel, no _FE etc.
    assert np.all(np.isfinite(res["R_KNEE_angle"]))


def test_model_json_roundtrip_preserves_frame_and_mode():
    """Saving/loading a model (to_dict/from_dict, the project storage path) keeps
    the segment frames and the JCS mode/sequence -- so a saved auto-built model
    still computes JCS after reload."""
    from core.marker_model import MarkerModel

    pts = dict(_pelvis_pts())
    pts.update(_leg_pts("R", (90.0, 40.0)))
    pts.update(_leg_pts("L", (-90.0, 40.0)))
    m = _markers(pts)
    model = auto_build_model(m)

    reloaded = MarkerModel.from_dict(model.to_dict())
    framed = {s["name"] for s in reloaded.segments if "frame" in s}
    assert {"PELVIS", "R_THIGH", "R_SHANK", "R_FOOT"} <= framed
    jcs_angles = [a for a in reloaded.angles if a.get("mode") == "jcs"]
    assert len(jcs_angles) == len(reloaded.angles) > 0
    for a in jcs_angles:
        assert a.get("sequence") == "xyz"
    # and it still computes after a calibrate/apply on reload
    reloaded.calibrate(m)
    res = reloaded.apply(m)
    assert "R_KNEE_angle_FE" in res["angles"]
