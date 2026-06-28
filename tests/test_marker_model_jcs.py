"""Regression tests for segment coordinate systems (SCS) and JCS Cardan joint
angles in core.marker_model (Visual3D / ISB Grood-Suntay style).

Synthetic frames whose answers are known analytically pin:
  * SCS orthonormality / right-handedness and side (R/L) ML-axis consistency,
  * Cardan/Euler decomposition exactly recovering known rotation sequences
    (including a gimbal-lock-capable proper-Euler order),
  * neutral (standing) posture -> all components ~ 0,
  * a known flexion posture -> a POSITIVE flexion sign, mirror-consistent L/R,
  * the 3-component angle being exposed as <name>_FE/_AB/_IE channels,
  * full backward compatibility of the legacy vector (angle_between) path.
"""

import numpy as np

from core.marker_model import (
    MarkerModel,
    _decompose_cardan,
    jcs_angles,
    segment_frame,
    thorax_frame,
)


def test_thorax_frame_axes_meaning():
    """ISB thorax SCS mapped to this module's columns (x=ML right, y=AP anterior,
    z=sup up): with IJ anterior, C7 posterior, PX/T8 below, the frame is the lab
    identity (x=right, y=anterior, z=up). NaN-safe / orthonormal."""
    F = 2
    ij = np.tile([0.0, 80.0, 1350.0], (F, 1))
    c7 = np.tile([0.0, -80.0, 1350.0], (F, 1))
    px = np.tile([0.0, 80.0, 1150.0], (F, 1))
    t8 = np.tile([0.0, -80.0, 1150.0], (F, 1))
    R, origin = thorax_frame(ij, c7, px, t8)
    np.testing.assert_allclose(R[0].T @ R[0], np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R[0]), 1.0, atol=1e-9)
    np.testing.assert_allclose(R[0][:, 0], [1, 0, 0], atol=1e-9)   # x = right
    np.testing.assert_allclose(R[0][:, 1], [0, 1, 0], atol=1e-9)   # y = anterior
    np.testing.assert_allclose(R[0][:, 2], [0, 0, 1], atol=1e-9)   # z = up
    np.testing.assert_allclose(origin[0], [0, 80, 1350], atol=1e-9)


# --- elementary rotation helpers (intrinsic, right-handed) -----------------

def _Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _Ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _Rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


_ROT = {"x": _Rx, "y": _Ry, "z": _Rz}


def _rot_seq(seq, deg):
    """Intrinsic product Rot(deg[0], seq[0]) @ Rot(deg[1], seq[1]) @ ..."""
    R = np.eye(3)
    for axis, a in zip(seq, deg):
        R = R @ _ROT[axis](np.radians(a))
    return R


# --- Cardan / Euler decomposition ------------------------------------------

def test_pure_axis_rotations_recovered():
    """A pure 30 deg rotation about one axis loads only that component."""
    for axis, comp in (("x", 0), ("y", 1), ("z", 2)):
        out = _decompose_cardan(_ROT[axis](np.radians(30))[None], "xyz")[0]
        expected = np.zeros(3)
        expected[comp] = 30.0
        np.testing.assert_allclose(out, expected, atol=1e-6)


def test_cardan_recovers_composed_sequence():
    R = _rot_seq("xyz", [10, 20, 30])[None]
    np.testing.assert_allclose(_decompose_cardan(R, "xyz")[0],
                               [10, 20, 30], atol=1e-6)


def test_proper_euler_yxy_recovered():
    R = _rot_seq("yxy", [15, 25, 35])[None]
    np.testing.assert_allclose(_decompose_cardan(R, "yxy")[0],
                               [15, 25, 35], atol=1e-6)


def test_decomposition_round_trip_many_sequences():
    """Re-composing the extracted angles must reproduce the input matrix to
    machine precision, for several Cardan and proper-Euler orders."""
    rng = np.random.default_rng(0)
    for seq in ("xyz", "zyx", "xzy", "zxy", "yxy", "zxz"):
        for _ in range(100):
            ang = rng.uniform(-80, 80, 3)
            ang[1] = rng.uniform(-55, 55)   # keep middle axis away from gimbal
            R = _rot_seq(seq, ang)[None]
            out = _decompose_cardan(R, seq)[0]
            R_back = _rot_seq(seq, out)[None]
            np.testing.assert_allclose(R_back, R, atol=1e-9)


def test_decomposition_nan_safe():
    R = np.full((2, 3, 3), np.nan)
    R[0] = np.eye(3)
    out = _decompose_cardan(R, "xyz")
    np.testing.assert_allclose(out[0], [0, 0, 0], atol=1e-9)
    assert np.all(np.isnan(out[1]))


def test_bad_sequence_raises():
    import pytest
    with pytest.raises(ValueError):
        _decompose_cardan(np.eye(3)[None], "xy")


# --- segment coordinate system (SCS) ---------------------------------------

def _vertical_frame(side="R", plane_x=1.0, F=3):
    """A limb segment pointing straight up (+z), with the plane point to the
    subject's right (+x), built F times."""
    origin = np.tile([0.0, 0.0, 0.0], (F, 1))   # distal endpoint
    prox = np.tile([0.0, 0.0, 1.0], (F, 1))     # proximal endpoint -> z up
    plane = np.tile([plane_x, 0.0, 0.5], (F, 1))
    R, _ = segment_frame(origin, prox, plane, side=side)
    return R


def test_scs_orthonormal_right_handed():
    R = _vertical_frame("R")[0]
    np.testing.assert_allclose(R.T @ R, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-9)


def test_scs_axes_meaning_right_side():
    """For a vertical right-side segment with the plane point to the right,
    z = up (distal->proximal), x = subject-right, y = anterior."""
    R = _vertical_frame("R")[0]
    np.testing.assert_allclose(R[:, 2], [0, 0, 1], atol=1e-9)   # e_long up
    np.testing.assert_allclose(R[:, 0], [1, 0, 0], atol=1e-9)   # e_ml right
    np.testing.assert_allclose(R[:, 1], [0, 1, 0], atol=1e-9)   # e_ap anterior


def test_scs_side_flips_ml_axis():
    """The L frame's ML axis points opposite the R frame's, so both encode
    'subject right = +x' consistently (mirror-consistent angle signs)."""
    Rr = _vertical_frame("R", plane_x=1.0)[0]
    Rl = _vertical_frame("L", plane_x=-1.0)[0]
    # Mirror plane point for the left; the resulting +x should still be world +x.
    np.testing.assert_allclose(Rr[:, 0], Rl[:, 0], atol=1e-9)


def test_scs_nan_when_collinear():
    """A plane point collinear with the long axis cannot fix the frontal plane
    -> NaN frame (no crash)."""
    F = 2
    origin = np.zeros((F, 3))
    prox = np.tile([0.0, 0.0, 1.0], (F, 1))
    plane = np.tile([0.0, 0.0, 2.0], (F, 1))     # on the long axis
    R, _ = segment_frame(origin, prox, plane, "R")
    assert np.all(np.isnan(R))


# --- JCS joint angles (neutral / flexion sign) -----------------------------

def test_standing_posture_all_zero():
    """Two identical aligned segments -> all three components ~ 0."""
    R = _vertical_frame("R")
    out = jcs_angles(R, R, "xyz")
    np.testing.assert_allclose(out[0], [0, 0, 0], atol=1e-9)


def test_flexion_is_positive_and_mirror_consistent():
    """Flexing the distal segment forward (about its ML axis) by +20 deg gives a
    POSITIVE flexion component, identical on left and right (mirror-consistent),
    with no cross-talk into ab/adduction or rotation."""
    F = 3
    flex = np.broadcast_to(_Rx(np.radians(20)), (F, 3, 3)).copy()

    Rr = _vertical_frame("R", plane_x=1.0)
    Rdr = np.einsum("fij,fjk->fik", Rr, flex)
    out_r = jcs_angles(Rr, Rdr, "xyz")[0]
    np.testing.assert_allclose(out_r, [20, 0, 0], atol=1e-6)

    Rl = _vertical_frame("L", plane_x=-1.0)
    Rdl = np.einsum("fij,fjk->fik", Rl, flex)
    out_l = jcs_angles(Rl, Rdl, "xyz")[0]
    np.testing.assert_allclose(out_l, [20, 0, 0], atol=1e-6)


# --- model-level JCS path (channel expansion + backward compat) ------------

def _two_segment_markers(F=4):
    """A static-like trial with markers defining two stacked vertical segments
    (a lower 'shank' and an upper 'thigh') plus plane markers, so the model can
    build SCS frames purely from raw markers (no calibration needed for the
    angle math; we exercise compute_frames/compute_angles directly)."""
    # endpoints along z, plane markers to the right (+x).
    labels = ["ANK", "KNE", "HIP", "SH_PL", "TH_PL"]
    data = np.zeros((5, F, 3))
    data[0, :] = [0, 0, 0.0]     # ankle (shank distal)
    data[1, :] = [0, 0, 1.0]     # knee  (shank proximal / thigh distal)
    data[2, :] = [0, 0, 2.0]     # hip   (thigh proximal)
    data[3, :] = [1, 0, 0.5]     # shank plane marker (right)
    data[4, :] = [1, 0, 1.5]     # thigh plane marker (right)
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _jcs_model():
    return MarkerModel(
        segments=[
            {"name": "SHANK", "proximal": "KNE", "distal": "ANK",
             "frame": {"origin": "ANK", "long": "KNE", "plane": "SH_PL", "side": "R"}},
            {"name": "THIGH", "proximal": "HIP", "distal": "KNE",
             "frame": {"origin": "KNE", "long": "HIP", "plane": "TH_PL", "side": "R"}},
        ],
        angles=[
            {"name": "R_KNEE_angle", "segment_a": "THIGH", "segment_b": "SHANK",
             "mode": "jcs", "sequence": "xyz"},
        ],
    )


def test_jcs_angle_expands_into_three_channels():
    markers = _two_segment_markers()
    res = _jcs_model().compute_angles(markers, joint_centers={})
    assert set(res) == {"R_KNEE_angle_FE", "R_KNEE_angle_AB", "R_KNEE_angle_IE"}
    # Both segments are perfectly aligned (straight leg) -> neutral knee = 0.
    for k in res:
        np.testing.assert_allclose(res[k], 0.0, atol=1e-6)


def test_jcs_knee_flexion_sign():
    """Bend the knee: rotate the shank backward so the knee flexes. With z=up,
    x=ML-right, anatomical knee flexion swings the ankle POSTERIOR (heel toward
    buttock) -- a NEGATIVE world-x rotation of the shank -- and the FE channel
    must read POSITIVE flexion (knee FE is sign-corrected in compute_angles)."""
    markers = _two_segment_markers()
    data = markers["data"].copy()
    # Rotate the shank endpoints + plane about the knee (x axis) by -25 deg so
    # the ankle truly swings posteriorly (anatomical knee flexion).
    knee = data[1, 0]
    R = _Rx(np.radians(-25))
    for mk in (0, 3):  # ankle and shank-plane marker move with the shank
        rel = data[mk] - knee
        data[mk] = (R @ rel.T).T + knee
    markers = {**markers, "data": data}
    res = _jcs_model().compute_angles(markers, joint_centers={})
    np.testing.assert_allclose(res["R_KNEE_angle_FE"], 25.0, atol=1e-4)
    np.testing.assert_allclose(res["R_KNEE_angle_AB"], 0.0, atol=1e-4)
    np.testing.assert_allclose(res["R_KNEE_angle_IE"], 0.0, atol=1e-4)


# --- backward compatibility (vector mode unchanged) ------------------------

def test_vector_mode_unchanged_without_frame():
    """A model with no frame / no mode still produces the legacy single
    unsigned angle via angle_between (no _FE/_AB/_IE channels)."""
    markers = _two_segment_markers()
    model = MarkerModel(
        segments=[
            {"name": "SHANK", "proximal": "KNE", "distal": "ANK"},
            {"name": "THIGH", "proximal": "HIP", "distal": "KNE"},
        ],
        angles=[{"name": "R_KNEE_angle", "segment_a": "THIGH", "segment_b": "SHANK"}],
    )
    res = model.compute_angles(markers, joint_centers={})
    assert set(res) == {"R_KNEE_angle"}
    # Both segments point +z -> 0 deg between them.
    np.testing.assert_allclose(res["R_KNEE_angle"], 0.0, atol=1e-6)


def test_compute_frames_skips_segments_without_frame():
    """compute_frames only emits SCS for segments that declare a frame."""
    markers = _two_segment_markers()
    model = MarkerModel(segments=[
        {"name": "SHANK", "proximal": "KNE", "distal": "ANK"},                     # no frame
        {"name": "THIGH", "proximal": "HIP", "distal": "KNE",
         "frame": {"origin": "KNE", "long": "HIP", "plane": "TH_PL", "side": "R"}},  # frame
    ])
    frames = model.compute_frames(markers, joint_centers={})
    assert set(frames) == {"THIGH"}
    assert frames["THIGH"].shape == (markers["data"].shape[1], 3, 3)
