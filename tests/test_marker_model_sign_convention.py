"""Regression pins for the LEFT/RIGHT angle-sign UNIFICATION convention and the
declarative ANGLE_CONVENTION table in core.marker_model.

Convention under test (both legs share ONE clinical sign):
  * FE (sagittal, about ML): flexion +, extension - ; ANKLE = dorsi +/plantar -.
  * AB (frontal, about AP):  abduction +, adduction - ; ANKLE = inversion +.
  * IE (transverse, about long): internal rotation +, external rotation -.
  * 0 deg = anatomical neutral (segment frames aligned).

The mirror is realised by ``segment_frame`` flipping the ML axis on the left
(unifies FE) PLUS ``MarkerModel._left_sign_flip`` negating AB & IE on the left
(unifies the other two). These tests build MIRROR-IMAGE left/right limbs from
synthetic markers, apply identical anatomical motions, and assert the three
clinical components come out with IDENTICAL sign and magnitude on both legs.
"""

import numpy as np

from core.marker_model import (
    MarkerModel,
    allow_peak_flexion_op,
    angle_convention,
    fe_flexion_sign,
    left_negated_components,
    segment_frame,
    standing_zero_selfcheck,
)


# --- elementary intrinsic rotations (right-handed) -------------------------

def _Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _Ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _Rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# --- mirror-image leg builder ----------------------------------------------
#
# A two-segment leg (THIGH proximal, SHANK distal) built from raw markers, with
# the lateral plane markers on the leg's LATERAL (subject-outward) side. The left
# leg is the exact sagittal-plane mirror (world x -> -x) of the right leg, just
# like real left/right markers in a capture. A KNEE angle uses THIGH (segment_a)
# / SHANK (segment_b); moving the SHANK is a pure knee motion.

_BASE_R = {
    "ANK": [0.1, 0.0, 0.0], "KNE": [0.1, 0.0, 1.0], "HIP": [0.1, 0.0, 2.0],
    "SH_PL": [0.3, 0.0, 0.5], "TH_PL": [0.3, 0.0, 1.5],
}
_SHANK_PTS = ("ANK", "SH_PL")


def _mirror(m):
    return {k: [-v[0], v[1], v[2]] for k, v in m.items()}


def _rotate_about(markers, pivot, R, which):
    out = dict(markers)
    piv = np.array(markers[pivot], float)
    for k in which:
        rel = np.array(markers[k], float) - piv
        out[k] = list(R @ rel + piv)
    return out


def _markers_from(pts, F=2):
    labels = list(pts)
    data = np.zeros((len(labels), F, 3))
    for i, lab in enumerate(labels):
        data[i, :] = pts[lab]
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0}


def _knee_model(side):
    return MarkerModel(
        segments=[
            {"name": f"{side}_THIGH", "proximal": "HIP", "distal": "KNE",
             "frame": {"origin": "KNE", "long": "HIP", "plane": "TH_PL", "side": side}},
            {"name": f"{side}_SHANK", "proximal": "KNE", "distal": "ANK",
             "frame": {"origin": "ANK", "long": "KNE", "plane": "SH_PL", "side": side}},
        ],
        angles=[{"name": f"{side}_KNEE_angle", "segment_a": f"{side}_THIGH",
                 "segment_b": f"{side}_SHANK", "mode": "jcs", "sequence": "xyz"}],
    )


def _knee_components(side, motion_R, which=_SHANK_PTS):
    base = _BASE_R if side == "R" else _mirror(_BASE_R)
    moved = _rotate_about(base, "KNE", motion_R, which)
    res = _knee_model(side).compute_angles(_markers_from(moved), joint_centers={})
    pre = f"{side}_KNEE_angle"
    return np.array([res[pre + "_FE"][0], res[pre + "_AB"][0], res[pre + "_IE"][0]])


# --- the core unification pins ---------------------------------------------

def test_neutral_both_legs_zero():
    """A straight (neutral) leg reads 0 on all three components, both sides."""
    np.testing.assert_allclose(_knee_components("R", np.eye(3)), [0, 0, 0], atol=1e-6)
    np.testing.assert_allclose(_knee_components("L", np.eye(3)), [0, 0, 0], atol=1e-6)


def test_flexion_unified_sign_both_legs():
    """Knee flexion (sagittal, NOT mirrored: same world-x rotation) gives the
    SAME positive FE on both legs, no AB/IE cross-talk. Anatomical knee flexion
    swings the ankle POSTERIOR (a NEGATIVE world-x shank rotation); the knee FE
    sign correction then makes it read POSITIVE flexion."""
    ang = np.radians(-20)
    r = _knee_components("R", _Rx(ang))
    l = _knee_components("L", _Rx(ang))            # flexion is not mirrored
    np.testing.assert_allclose(r, [20, 0, 0], atol=1e-4)
    np.testing.assert_allclose(l, [20, 0, 0], atol=1e-4)


def test_knee_flexion_reads_positive_extension_negative():
    """Regression: anatomical knee flexion (ankle swings POSTERIOR, a negative
    world-x shank rotation) must read POSITIVE FE; the opposite anterior swing
    (hyper-extension) reads NEGATIVE. The knee is the lone joint whose flexion is
    geometrically opposite the hip/elbow Cardan convention, so its FE is sign-
    corrected (``fe_flexion_sign``)."""
    flex = _knee_components("R", _Rx(np.radians(-20)))      # ankle posterior
    ext = _knee_components("R", _Rx(np.radians(+20)))       # ankle anterior
    assert flex[0] > 0 and abs(flex[0] - 20) < 1e-4
    assert ext[0] < 0 and abs(ext[0] + 20) < 1e-4
    # the helper: knee flips, hip/ankle/elbow do not.
    assert fe_flexion_sign("R_KNEE_angle_FE") == -1.0
    assert fe_flexion_sign("L_KNEE_angle_FE") == -1.0
    assert fe_flexion_sign("R_HIP_angle_FE") == 1.0
    assert fe_flexion_sign("R_ANKLE_angle_FE") == 1.0
    assert fe_flexion_sign("R_ELBOW_angle_FE") == 1.0


def test_abduction_unified_sign_both_legs():
    """Abduction is a MIRRORED frontal-plane motion (world x->-x flips its world
    rotation). After the left AB sign flip both legs read the SAME positive AB."""
    ang = np.radians(15)
    r = _knee_components("R", _Ry(ang))
    l = _knee_components("L", _Ry(-ang))           # mirrored world rotation
    np.testing.assert_allclose(r, [0, 15, 0], atol=1e-4)
    np.testing.assert_allclose(l, [0, 15, 0], atol=1e-4)
    assert np.sign(r[1]) == np.sign(l[1]) == 1.0


def test_internal_rotation_unified_sign_both_legs():
    """Internal rotation is a MIRRORED transverse motion; after the left IE sign
    flip both legs read the SAME positive IE."""
    ang = np.radians(15)
    r = _knee_components("R", _Rz(ang))
    l = _knee_components("L", _Rz(-ang))           # mirrored world rotation
    np.testing.assert_allclose(r, [0, 0, 15], atol=1e-4)
    np.testing.assert_allclose(l, [0, 0, 15], atol=1e-4)
    assert np.sign(r[2]) == np.sign(l[2]) == 1.0


def test_left_flip_only_touches_ab_ie():
    """The left-side correction negates ONLY AB & IE, never FE: a combined
    flexion+abduction+rotation on mirror legs matches component-wise."""
    a = np.radians(12)
    # right: flex(+x) then abduct(+y) then int-rot(+z)
    Rr = _Rx(a) @ _Ry(a) @ _Rz(a)
    # left mirror: same flexion, mirrored frontal/transverse
    Rl = _Rx(a) @ _Ry(-a) @ _Rz(-a)
    r = _knee_components("R", Rr)
    l = _knee_components("L", Rl)
    np.testing.assert_allclose(r, l, atol=1e-3)


# --- ANGLE_CONVENTION table + peak-flexion op gating -----------------------

def test_angle_convention_directions():
    assert angle_convention("R_KNEE_angle_FE")["positive"] == "flexion"
    assert angle_convention("L_KNEE_angle_FE")["negative"] == "extension"
    assert angle_convention("R_HIP_angle_AB")["positive"] == "abduction"
    assert angle_convention("R_HIP_angle_IE")["positive"] == "internal_rotation"
    # ankle frontal plane is inversion/eversion, not ab/adduction:
    assert angle_convention("R_ANKLE_angle_AB")["positive"] == "inversion"
    assert angle_convention("R_ANKLE_angle_FE")["positive"] == "dorsiflexion"
    assert angle_convention("R_ANKLE_angle_FE")["negative"] == "plantarflexion"
    # frame-less (vector) angle -> unsigned:
    assert angle_convention("R_KNEE_angle")["positive"] == "unsigned_angle"


def test_left_negated_flag_matches_components():
    """The table records the lower-limb 'xyz' default: FE kept, AB & IE flipped."""
    assert angle_convention("L_KNEE_angle_FE")["left_negated"] is False
    assert angle_convention("L_KNEE_angle_AB")["left_negated"] is True
    assert angle_convention("L_KNEE_angle_IE")["left_negated"] is True


def test_left_negated_components_is_sequence_dependent():
    """The exact left flip negates the components whose Cardan axis is not ML.
    Lower-limb xyz/xzy -> (F,T,T); shoulder zxz/yxy -> (T,F,T) (the about-ML
    elevation term is the middle one and is preserved)."""
    assert left_negated_components("xyz") == (False, True, True)
    assert left_negated_components("xzy") == (False, True, True)
    assert left_negated_components("zxz") == (True, False, True)
    assert left_negated_components("yxy") == (True, False, True)


def test_shoulder_zxz_left_flip_preserves_elevation_sign():
    """A 'zxz' (shoulder) JCS: an about-ML (x) middle-axis motion -- elevation --
    keeps its sign on the left, while the plane-of-elevation/axial terms flip, so
    a mirror-image abduction reads the SAME elevation sign on both arms."""
    ang = np.radians(40)
    # Build a minimal upper-arm/trunk pair as two vertical segments and rotate the
    # distal (upper-arm) about world-x (elevation about ML) -- mirrored per side.
    base = {"WR": [0.1, 0, 0.0], "EL": [0.1, 0, 1.0], "SH": [0.1, 0, 2.0],
            "EL_PL": [0.3, 0, 0.5], "SH_PL": [0.3, 0, 1.5]}

    def comps(side, R):
        pts = base if side == "R" else {k: [-v[0], v[1], v[2]] for k, v in base.items()}
        moved = _rotate_about(pts, "EL", R, ("WR", "EL_PL"))
        model = MarkerModel(
            segments=[
                {"name": f"{side}_UA", "proximal": "SH", "distal": "EL",
                 "frame": {"origin": "EL", "long": "SH", "plane": "SH_PL", "side": side}},
                {"name": f"{side}_FA", "proximal": "EL", "distal": "WR",
                 "frame": {"origin": "WR", "long": "EL", "plane": "EL_PL", "side": side}},
            ],
            angles=[{"name": f"{side}_ELBOW_angle", "segment_a": f"{side}_UA",
                     "segment_b": f"{side}_FA", "mode": "jcs", "sequence": "zxz"}],
        )
        r = model.compute_angles(_markers_from(moved), joint_centers={})
        p = f"{side}_ELBOW_angle"
        return np.array([r[p + "_FE"][0], r[p + "_AB"][0], r[p + "_IE"][0]])

    # elevation about ML is the MIDDLE (_AB) zxz term: same sign both sides.
    r = comps("R", _Rx(ang))
    l = comps("L", _Rx(ang))           # about-ML elevation is NOT mirrored
    assert np.sign(r[1]) == np.sign(l[1])
    np.testing.assert_allclose(abs(r[1]), abs(l[1]), atol=1e-4)


def test_peak_flexion_op_gated_to_fe_only():
    """'peak flexion' (op=max/min) is allowed ONLY on the sagittal FE channel of
    a JCS joint -- never on AB/IE (which are ab/adduction, inv/ev, rotation) and
    never on an unsigned vector angle."""
    assert allow_peak_flexion_op("R_KNEE_angle_FE") is True
    assert allow_peak_flexion_op("L_ANKLE_angle_FE") is True       # dorsi/plantar
    assert allow_peak_flexion_op("R_KNEE_angle_AB") is False
    assert allow_peak_flexion_op("R_HIP_angle_IE") is False
    assert allow_peak_flexion_op("R_ANKLE_angle_AB") is False      # inv/ev
    assert allow_peak_flexion_op("R_KNEE_angle") is False          # vector/unsigned


def test_ankle_dorsi_plantar_op_labels_split():
    """The ankle FE op labels read dorsiflexion (max) vs plantarflexion (min),
    not a generic flexion/extension."""
    c = angle_convention("R_ANKLE_angle_FE")
    assert c["op_max_means"] == "peak_dorsiflexion"
    assert c["op_min_means"] == "peak_plantarflexion"
    # a knee, by contrast, reads peak flexion / peak extension:
    k = angle_convention("R_KNEE_angle_FE")
    assert k["op_max_means"] == "peak_flexion"
    assert k["op_min_means"] == "peak_extension"


# --- standing-zero self-check ----------------------------------------------

def test_standing_zero_selfcheck_passes_for_neutral_leg():
    """A neutral straight leg passes the FE-zero self-check (|FE| ~ 0)."""
    base = _BASE_R
    chk = standing_zero_selfcheck(_calib_knee_model("R", base),
                                  _markers_from(base))
    assert chk["ok"] is True
    assert all(abs(v) < 1e-6 for v in chk["channels"].values())


def test_standing_zero_selfcheck_flags_flexed_leg():
    """A leg held in 30 deg flexion fails the FE-zero self-check (it is not
    neutral); only the FE channel is examined."""
    base = _rotate_about(_BASE_R, "KNE", _Rx(np.radians(30)), _SHANK_PTS)
    chk = standing_zero_selfcheck(_calib_knee_model("R", base),
                                  _markers_from(base), tol_deg=10.0)
    assert chk["ok"] is False
    assert "R_KNEE_angle_FE" in chk["violations"]
    assert chk["worst"][0] == "R_KNEE_angle_FE"


def _calib_knee_model(side, pts):
    """A knee model whose apply() runs on raw markers (no joint reconstruction):
    the frames reference raw labels, so we monkeypatch reconstruct() to skip
    calibration for this frame-only self-check exercise."""
    model = _knee_model(side)
    model.reconstruct = lambda markers, label_map=None: {}   # frame-only path
    return model
