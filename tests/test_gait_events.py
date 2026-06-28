"""G2 — kinematic gait events (Zeni 2008 coordinate method) + stance/swing.

Pins the science of deriving heel-strike (HS) / toe-off (TO) from foot markers
on a treadmill (no force events) and splitting each cycle into stance vs swing:

  - ``foot_progression_series`` projects a foot marker onto the AP (progression)
    axis relative to the pelvis origin, oriented anterior-positive — the signal
    whose maxima are HS (heel) and minima are TO (toe).
  - ``progression_axis`` auto-detects the AP axis + anterior sign from the marker
    geometry (vertical = largest |mean offset| below the pelvis; AP = the
    remaining horizontal axis with the largest foot excursion).
  - ``split_stance_swing`` turns HS/TO frame lists into per-cycle stance/swing
    durations and percentages.
"""

import numpy as np

from core import gait_events as ge
from core import signals as sig


def _synth_markers(fs=100.0, n=400, stride_hz=1.0):
    """Synthetic treadmill gait: foot AP on axis 1, vertical on axis 2 (feet far
    below the pelvis), ML on axis 0. The toe sits anterior of the heel so +axis-1
    is unambiguously the forward direction."""
    t = np.arange(n) / fs
    ph = 2 * np.pi * stride_hz * t
    pelvis = np.zeros((n, 3)); pelvis[:, 2] = 900.0          # pelvis high, at AP 0
    heel = np.zeros((n, 3))
    heel[:, 1] = -70.0 + 300.0 * np.sin(ph)                   # AP oscillation
    heel[:, 2] = 60.0                                          # near the floor
    toe = np.zeros((n, 3))
    toe[:, 1] = 160.0 + 300.0 * np.sin(ph - 0.5)              # anterior of heel
    toe[:, 2] = 45.0
    labels = ["RASIS", "LASIS", "RPSIS", "LPSIS", "RHEEL", "RTOE"]
    data = np.stack([pelvis, pelvis, pelvis, pelvis, heel, toe], axis=0)  # (6,n,3)
    return {"labels": labels, "data": data, "time": t, "rate": fs}


def test_pelvis_origin_is_mean_of_pelvis_markers():
    mk = _synth_markers()
    origin = ge.pelvis_origin(mk)
    assert origin.shape == (mk["data"].shape[1], 3)
    # All four pelvis markers coincide here, so the mean is that point.
    np.testing.assert_allclose(origin, mk["data"][0])


def test_progression_axis_and_anterior_sign():
    mk = _synth_markers()
    axis, sign = ge.progression_axis(mk, "R")
    assert axis == 1            # AP = the large-excursion horizontal axis
    assert sign == 1            # toe is anterior of heel along +axis-1


def test_foot_progression_series_is_ap_relative_to_pelvis():
    mk = _synth_markers()
    heel_ap = ge.foot_progression_series(mk, "R", "heel")
    toe_ap = ge.foot_progression_series(mk, "R", "toe")
    n = mk["data"].shape[1]
    assert heel_ap.shape == (n,)
    # heel AP relative to pelvis (oriented anterior-positive) = raw axis-1 diff.
    expected_heel = mk["data"][4][:, 1] - mk["data"][0][:, 1]
    np.testing.assert_allclose(heel_ap, expected_heel)
    # the toe is on average anterior of the heel.
    assert np.nanmean(toe_ap) > np.nanmean(heel_ap)


def test_foot_progression_series_handles_inverted_axis():
    # If the lab's +AP points posterior (toe BEHIND heel in raw coords), the
    # series must still come out anterior-positive (toe mean > heel mean).
    mk = _synth_markers()
    mk["data"][:, :, 1] *= -1.0          # flip the AP axis sign
    heel_ap = ge.foot_progression_series(mk, "R", "heel")
    toe_ap = ge.foot_progression_series(mk, "R", "toe")
    assert np.nanmean(toe_ap) > np.nanmean(heel_ap)


def test_split_stance_swing_percentages():
    # HS at t=0.0, 1.0, 2.0 (frames 0,2,4); TO at t=0.6, 1.6 (frames 1,3).
    time = np.array([0.0, 0.6, 1.0, 1.6, 2.0])
    cycles = ge.split_stance_swing([0, 2, 4], [1, 3], time)
    assert len(cycles) == 2
    c = cycles[0]
    assert c["cycle_s"] == 1.0
    assert c["stance_s"] == 0.6
    assert c["swing_s"] == 0.4
    assert c["stance_pct"] == 60.0
    assert c["swing_pct"] == 40.0


def test_split_stance_swing_drops_cycle_without_toe():
    # A cycle whose [HS, next HS) window contains no TO is dropped (not guessed).
    time = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    # TO only at frame 1 (t=0.5), inside the first cycle 0->2; second cycle 2->4
    # has no TO -> only one valid cycle.
    cycles = ge.split_stance_swing([0, 2, 4], [1], time)
    assert len(cycles) == 1
    assert cycles[0]["stance_s"] == 0.5


# -- velocity method (O'Connor 2007 / Zeni 2008 velocity variant) -------------

def test_velocity_events_land_on_analytic_velocity_minima():
    """The velocity method finds HS at the heel-AP-velocity minima and TO at the
    toe-AP-velocity minima. For the synthetic foot traces (heel = sin(wt),
    toe = sin(wt-0.5), fs=100, stride 1 Hz) the heel velocity = w*cos(wt) is most
    negative where wt = pi (mod 2pi) -> t = 0.5, 1.5, 2.5, 3.5 s -> frames
    50,150,250,350; the toe (phase -0.5) is most negative at (pi+0.5)/w -> frame
    58 etc. These are analytic, so we can assert exact frames."""
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    ev = ge.velocity_events(mk, "R")
    np.testing.assert_array_equal(ev["HS"], [50, 150, 250, 350])
    np.testing.assert_array_equal(ev["TO"], [58, 158, 258, 358])


def test_velocity_events_one_per_stride():
    """One HS and one TO per stride: a 4 s, 1 Hz-stride trial has 4 of each, with
    every TO strictly inside the HS pair that brackets it (a real stance window)."""
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    ev = ge.velocity_events(mk, "R")
    assert len(ev["HS"]) == 4
    assert len(ev["TO"]) == 4
    # TO follows its own HS within the stride (HS 50/150/..., TO 58/158/...): each
    # toe-off sits a few frames after the matching heel-strike (stance phase).
    hs, to = ev["HS"], ev["TO"]
    for h, f in zip(hs, to):
        assert h < f < h + (hs[1] - hs[0])


def test_velocity_events_clock_independent_frame_scaling():
    """The velocity method works off marker time, so doubling the sample rate
    doubles the frame indices of the same physical events (frames are on the
    marker clock). At fs=200 the heel velocity minima move from 50,150,... to
    100,300,500,700."""
    mk = _synth_markers(fs=200.0, n=800, stride_hz=1.0)
    ev = ge.velocity_events(mk, "R")
    np.testing.assert_array_equal(ev["HS"], [100, 300, 500, 700])


def test_velocity_events_invariant_to_ap_axis_sign():
    """Flipping the lab's +AP direction (toe behind heel in raw coords) must not
    move the events: foot_progression_series re-orients anterior-positive, so the
    velocity minima land on the same frames."""
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    ev0 = ge.velocity_events(mk, "R")
    mk["data"][:, :, 1] *= -1.0          # flip the AP axis sign
    ev1 = ge.velocity_events(mk, "R")
    np.testing.assert_array_equal(ev0["HS"], ev1["HS"])
    np.testing.assert_array_equal(ev0["TO"], ev1["TO"])


def test_velocity_events_explicit_time_overrides_markers():
    """An explicit ``time`` argument (a master clock) overrides markers['time']
    for differentiation, but the returned indices stay on the marker clock (one
    per marker frame)."""
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    # Pass the same clock explicitly -> identical to the markers['time'] path.
    ev_default = ge.velocity_events(mk, "R")
    ev_explicit = ge.velocity_events(mk, "R", time=mk["time"])
    np.testing.assert_array_equal(ev_default["HS"], ev_explicit["HS"])
    np.testing.assert_array_equal(ev_default["TO"], ev_explicit["TO"])


def test_velocity_events_nan_safe():
    """A short occlusion (NaN burst) in a foot marker must not raise and must not
    spuriously add/drop a whole stride's events (gaps are linearly interpolated
    before differentiating)."""
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    mk["data"][4, 200:205, 1] = np.nan        # 5-frame heel occlusion mid-trial
    ev = ge.velocity_events(mk, "R")
    # still ~4 HS and 4 TO, none NaN, all in-range
    assert 4 == len(ev["HS"]) == len(ev["TO"])
    assert np.all(np.isfinite(ev["HS"])) and np.all(np.isfinite(ev["TO"]))


def test_gait_events_method_switch_coordinate_matches_legacy():
    """The shared entry point gait_events(method='coordinate') reproduces the
    legacy coordinate detection (heel-AP maxima for HS, toe-AP minima for TO),
    while method='velocity' delegates to velocity_events."""
    from scipy.signal import find_peaks
    mk = _synth_markers(fs=100.0, n=400, stride_hz=1.0)
    md = int(round(0.6 * mk["rate"]))
    heel = ge.foot_progression_series(mk, "R", "heel")
    toe = ge.foot_progression_series(mk, "R", "toe")
    hs_legacy, _ = find_peaks(heel, distance=md)
    to_legacy, _ = find_peaks(-toe, distance=md)
    coord = ge.gait_events(mk, "R", method="coordinate")
    np.testing.assert_array_equal(coord["HS"], hs_legacy)
    np.testing.assert_array_equal(coord["TO"], to_legacy)
    vel = ge.gait_events(mk, "R", method="velocity")
    np.testing.assert_array_equal(vel["HS"], ge.velocity_events(mk, "R")["HS"])


# -- signal-layer integration: gait:<SIDE>_<point>_ap is a catalog signal -----

def _gait_dataset(fs_master=200.0):
    """Wrap the synthetic markers in a dataset with a (different-rate) master
    clock so we also exercise the resample-onto-master-clock path."""
    mk = _synth_markers(fs=100.0, n=400)
    dur = mk["time"][-1]
    n = int(round(dur * fs_master)) + 1
    return {"time": np.arange(n) / fs_master, "fs": fs_master, "markers": mk}, mk


def test_signal_series_resolves_gait_keys():
    ds, mk = _gait_dataset()
    heel = sig.signal_series(ds, "gait:R_heel_ap", marker_disp=mk["data"])
    toe = sig.signal_series(ds, "gait:R_toe_ap", marker_disp=mk["data"])
    # On the master clock (resampled): one value per master frame.
    assert heel.shape == ds["time"].shape
    # Anterior-positive: toe leads the heel on average.
    assert np.nanmean(toe) > np.nanmean(heel)


def test_signal_series_gait_requires_markers():
    ds, mk = _gait_dataset()
    # No marker_disp -> graceful ValueError (like marker:* channels), not a crash.
    try:
        sig.signal_series(ds, "gait:R_heel_ap", marker_disp=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError without markers")


def test_gait_label_and_unit():
    assert sig.unit_for("gait:R_heel_ap") == "mm"
    # A human label, not the raw key.
    assert sig.label_for("gait:R_heel_ap") != "gait:R_heel_ap"


def test_gait_signals_listed_in_catalog():
    ds, mk = _gait_dataset()
    keys = [k for k, _ in sig.signal_catalog(ds, marker_disp=mk["data"])]
    # The synthetic markers carry R heel/toe + pelvis -> both R gait signals show.
    assert "gait:R_heel_ap" in keys
    assert "gait:R_toe_ap" in keys
    # No L foot markers -> no L gait signals offered.
    assert "gait:L_heel_ap" not in keys


# -- lab-frame foot coordinate signals (Task 1) --------------------------------

def test_foot_lab_series_is_absolute_not_pelvis_relative():
    mk = _synth_markers()
    lab = ge.foot_lab_series(mk, "R", "heel", axis="ap")
    rel = ge.foot_progression_series(mk, "R", "heel")
    n = mk["data"].shape[1]
    assert lab.shape == (n,)
    ap, sign = ge.progression_axis(mk, "R")
    expected = sign * mk["data"][4][:, ap]
    np.testing.assert_allclose(lab, expected)
    np.testing.assert_allclose(lab - rel, sign * mk["data"][0][:, ap])


def test_foot_lab_series_ml_axis():
    mk = _synth_markers()
    ml = ge.foot_lab_series(mk, "R", "heel", axis="ml")
    assert ml.shape == (mk["data"].shape[1],)


def test_signal_series_resolves_gait_lab_keys():
    ds, mk = _gait_dataset()
    v = sig.signal_series(ds, "gait:R_heel_ap_lab", marker_disp=mk["data"])
    assert v.shape == ds["time"].shape
    assert sig.unit_for("gait:R_heel_ap_lab") == "mm"
    assert sig.label_for("gait:R_heel_ap_lab") != "gait:R_heel_ap_lab"
