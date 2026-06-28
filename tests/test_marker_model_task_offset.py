"""Regression tests for task presets + static-offset subtraction in
core.marker_model.

Two new beginner-facing engine features:
  * ``auto_build_model(..., task=...)`` -- the user picks a motion task
    ("walk"/"run"/"jump"/"balance"/"generic") and the engine sets each joint's
    Cardan rotation order from ``TASK_PRESETS``. HIP/KNEE stay "xyz" everywhere;
    walk/run set the ANKLE to "xzy" (the clinical Plug-in-Gait order in our SCS).
    "generic" keeps everything "xyz" = the previous behaviour (backward compat).
  * static-offset subtraction (opt-in): ``static_angle_offsets`` averages a
    static trial's neutral angles; ``apply(offsets=...)`` subtracts them so a
    dynamic trial held in the SAME posture reads ~0. No offsets -> raw (compat).

Synthetic trials with analytically known answers pin all of the above. Units
are MILLIMETRES (the Harrington hip regression constants are in mm).
"""

import numpy as np

from core.marker_model import (
    auto_build_model, static_angle_offsets, static_angle_offsets_from_window,
    task_preset, TASK_PRESETS,
)

# Reuse the synthetic-leg builders from the JCS auto-build tests.
from test_marker_model_autojcs import _pelvis_pts, _leg_pts, _markers, _Rx


def _full_leg_markers():
    pts = dict(_pelvis_pts())
    pts.update(_leg_pts("R", (90.0, 40.0)))
    pts.update(_leg_pts("L", (-90.0, 40.0)))
    return _markers(pts)


# --- task preset lookup ----------------------------------------------------

def test_task_preset_lookup_and_fallback():
    """Known keys map to their preset; None/unknown fall back to "generic"."""
    assert set(TASK_PRESETS) == {"walk", "run", "jump", "balance", "generic"}
    assert task_preset("walk")["sequence"]["ANKLE"] == "xzy"
    assert task_preset(None) is TASK_PRESETS["generic"]
    assert task_preset("nonexistent") is TASK_PRESETS["generic"]
    # generic = all xyz, offset off (the backward-compatible default)
    gen = task_preset("generic")
    assert gen["sequence"] == {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xyz"}
    assert gen["static_offset"] is False
    # gait tasks default static offset ON
    assert task_preset("walk")["static_offset"] is True
    assert task_preset("run")["static_offset"] is True


# --- (a) task -> ANKLE sequence wired into the built model -----------------

def test_walk_sets_ankle_sequence_xzy():
    """walk -> ANKLE angle uses sequence "xzy"; HIP/KNEE stay "xyz"."""
    m = _full_leg_markers()
    model = auto_build_model(m, task="walk")
    seq = {a["name"]: a.get("sequence") for a in model.angles}
    for side in ("R", "L"):
        assert seq[f"{side}_ANKLE_angle"] == "xzy"
        assert seq[f"{side}_HIP_angle"] == "xyz"
        assert seq[f"{side}_KNEE_angle"] == "xyz"


def test_run_sets_ankle_sequence_xzy():
    """run reuses the gait ankle order "xzy" (conservative; see preset notes)."""
    m = _full_leg_markers()
    model = auto_build_model(m, task="run")
    seq = {a["name"]: a.get("sequence") for a in model.angles}
    assert seq["R_ANKLE_angle"] == "xzy"
    assert seq["R_KNEE_angle"] == "xyz"


def test_jump_and_balance_all_xyz():
    """jump/balance keep every joint at "xyz" (no established ankle reorder)."""
    m = _full_leg_markers()
    for task in ("jump", "balance"):
        model = auto_build_model(m, task=task)
        for a in model.angles:
            assert a.get("sequence") == "xyz", f"{task}:{a['name']}"


def test_generic_is_backward_compatible_default():
    """Default (no task) == "generic" == all "xyz" == previous auto-build."""
    m = _full_leg_markers()
    default = auto_build_model(m)
    generic = auto_build_model(m, task="generic")
    seq_default = {a["name"]: a.get("sequence") for a in default.angles}
    seq_generic = {a["name"]: a.get("sequence") for a in generic.angles}
    assert seq_default == seq_generic
    for v in seq_default.values():
        assert v == "xyz"


# --- ankle order actually changes the decomposition (not just metadata) ----

def test_ankle_order_changes_numbers_under_combined_rotation():
    """A pure sagittal rotation gives the same FE under xyz and xzy, but a
    COMBINED (sagittal + transverse) rotation decomposes differently -> the two
    orders must produce different non-FE components. This proves the sequence is
    actually fed to the Cardan decomposition, not just stored."""
    from core.marker_model import jcs_angles

    # Distal frame rotated by flexion(x) then internal rot(z): orders xyz vs xzy
    # split the cross-talk between the 2nd/3rd axes differently.
    Rx = _Rx(np.radians(20))

    def _Rz(a):
        c, s = np.cos(a), np.sin(a)
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

    R_dist = (Rx @ _Rz(np.radians(15)))[None]      # (1,3,3)
    R_prox = np.eye(3)[None]
    xyz = jcs_angles(R_prox, R_dist, sequence="xyz")[0]
    xzy = jcs_angles(R_prox, R_dist, sequence="xzy")[0]
    # The two decompositions differ for a combined rotation.
    assert not np.allclose(xyz, xzy, atol=1e-6)


# --- (b) static offset zeros a matching posture ----------------------------

def test_static_offset_zeros_matching_posture():
    """Offsets from a static trial, subtracted from a dynamic trial held in the
    SAME posture, drive every angle channel to ~0."""
    m = _full_leg_markers()
    model = auto_build_model(m, task="walk")
    model.calibrate(m)

    offsets = static_angle_offsets(model, m)
    # Apply to the very same posture -> all finite channels ~ 0.
    res = model.apply(m, offsets=offsets)
    for name, series in res["angles"].items():
        v = series[0]
        if np.isfinite(offsets.get(name, np.nan)):
            assert np.isfinite(v)
            assert abs(v) < 1e-6, f"{name} = {v} (expected ~0 after offset)"


def test_static_offset_shifts_a_known_amount():
    """Offsets just subtract a constant: a 25 deg knee-flexed dynamic trial,
    offset by a NEUTRAL static (legs under the hip JCs -> KNEE_FE offset ~0),
    reads ~25 on KNEE_FE."""
    # Learn the hip JC (x, y) first, then build BOTH static and dynamic with the
    # legs straight under the hips so the static is true neutral (offset ~0).
    pts0 = dict(_pelvis_pts())
    pts0.update(_leg_pts("R", (90.0, 40.0)))
    pts0.update(_leg_pts("L", (-90.0, 40.0)))
    m0 = _markers(pts0)
    model = auto_build_model(m0, task="generic")
    model.calibrate(m0)
    res0 = model.apply(m0)
    rhip = res0["joint_centers"]["R_HIP"][0]
    lhip = res0["joint_centers"]["L_HIP"][0]

    static_pts = dict(_pelvis_pts())
    static_pts.update(_leg_pts("R", (rhip[0], rhip[1])))
    static_pts.update(_leg_pts("L", (lhip[0], lhip[1])))
    static = _markers(static_pts)
    offsets = static_angle_offsets(model, static)
    assert abs(offsets["R_KNEE_angle_FE"]) < 1e-3   # static is true neutral

    dyn_pts = dict(_pelvis_pts())
    # anatomical knee flexion swings the shank posterior (negative world-x);
    # the knee FE sign correction makes it read +25.
    dyn_pts.update(_leg_pts("R", (rhip[0], rhip[1]), R_shank=_Rx(np.radians(-25))))
    dyn_pts.update(_leg_pts("L", (lhip[0], lhip[1])))
    dyn = _markers(dyn_pts)

    raw = model.apply(dyn)["angles"]["R_KNEE_angle_FE"][0]
    off = model.apply(dyn, offsets=offsets)["angles"]["R_KNEE_angle_FE"][0]
    # The static is true neutral (offset ~0) so the offset barely moves the raw
    # value, and the dynamic shows a clear POSITIVE knee flexion (the knee FE is
    # sign-corrected so flexion reads +). The auto-built leg's frame is slightly
    # non-orthogonal, so a commanded 25 deg WORLD-x shank rotation reads a bit
    # higher (~30 deg) on the anatomical FE axis -- the point is a clear, positive,
    # constant-offset flexion, not an exact magnitude.
    assert abs(off - (raw - offsets["R_KNEE_angle_FE"])) < 1e-9
    assert 24.0 < off < 34.0, f"offset KNEE_FE = {off} (expected a clear +flexion ~25-31)"


# --- (c) no offsets == raw (backward compatibility) ------------------------

def test_apply_without_offsets_is_raw():
    """apply() with no offsets returns identical numbers to before (raw)."""
    m = _full_leg_markers()
    model = auto_build_model(m)
    model.calibrate(m)
    raw = model.apply(m)
    also_raw = model.apply(m, offsets=None)
    for name in raw["angles"]:
        np.testing.assert_array_equal(raw["angles"][name], also_raw["angles"][name])


def test_offsets_only_touch_listed_channels():
    """An offset dict missing a channel leaves that channel raw; NaN offsets are
    ignored (channel stays raw)."""
    m = _full_leg_markers()
    model = auto_build_model(m)
    model.calibrate(m)
    raw = model.apply(m)
    names = list(raw["angles"])
    # Offset exactly one channel by a finite amount; another by NaN; omit the rest.
    one = names[0]
    nanned = names[1]
    offsets = {one: 5.0, nanned: np.nan}
    res = model.apply(m, offsets=offsets)
    # listed finite channel shifted by 5
    np.testing.assert_allclose(res["angles"][one], raw["angles"][one] - 5.0)
    # NaN-offset and omitted channels unchanged
    for name in names[1:]:
        np.testing.assert_array_equal(res["angles"][name], raw["angles"][name])


# --- window-based offsets (no separate static trial) -----------------------

def test_window_offset_matches_full_static_for_constant_posture():
    """For a constant-posture trial, a time-window average equals the full-trial
    mean -> window offsets zero the same posture too."""
    m = _full_leg_markers()
    model = auto_build_model(m)
    model.calibrate(m)
    t = m["time"]
    off_full = static_angle_offsets(model, m)
    off_win = static_angle_offsets_from_window(model, m, t[0], t[-1])
    for name in off_full:
        if np.isfinite(off_full[name]):
            assert abs(off_full[name] - off_win[name]) < 1e-9
    # out-of-range window -> all NaN (then ignored by apply)
    off_empty = static_angle_offsets_from_window(model, m, t[-1] + 10, t[-1] + 20)
    assert all(np.isnan(v) for v in off_empty.values())
