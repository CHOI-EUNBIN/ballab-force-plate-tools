"""Regression tests for C2 event detection.

Pins the C2 contract:
  - ``detect_threshold_crossings`` finds EDGES (transitions), not levels: a
    square-wave Fz that rises past 30 N N times yields exactly N rising crossings
    at the theoretical frames; a signal that stays above the threshold the whole
    time (standing) yields ZERO crossings.
  - ``min_distance`` / ``hysteresis`` collapse threshold chatter into one event.
  - ``select_instances`` picks first / nth / range / all correctly.
  - ``detect_peaks`` finds the local maxima of a sine wave (multi-instance).
  - ``DetectEventStep`` to_dict/from_dict round-trips, and an old manifest (no
    detect step) gives only manual events.
  - ``compute_detected_events`` resolves a ":filt" input through the Workspace.
"""

import numpy as np

from core import events as ev
from core.events_compute import (_detect_token, _resolve_min_distance_frames,
                                  compute_detected_events,
                                  event_catalog, event_frames,
                                  resolve_endpoint_frame)
from core.pipeline import DetectEventStep, FilterStep, Pipeline
from core.signals import FilterSpec


# -- threshold crossings: edge not level -------------------------------------

def _square_wave(n_cycles=5, period=20, high=50.0, low=0.0):
    """A clean square wave: each cycle is `period` frames, first half high."""
    half = period // 2
    one = np.concatenate([np.full(half, high), np.full(period - half, low)])
    return np.tile(one, n_cycles)


def test_threshold_rising_counts_each_crossing():
    n_cycles = 5
    period = 20
    vals = _square_wave(n_cycles=n_cycles, period=period, high=50.0, low=0.0)
    # Start at low so the first frame of each high half is a rising crossing.
    vals = np.concatenate([[0.0], vals])  # prepend a low so cycle 0 also rises
    idx = ev.detect_threshold_crossings(vals, threshold=30.0, direction="rising")
    assert len(idx) == n_cycles
    # First rising crossing is at frame 1 (after the prepended low), then every
    # `period` frames.
    expected = 1 + period * np.arange(n_cycles)
    np.testing.assert_array_equal(idx, expected)


def test_threshold_falling_counts_each_crossing():
    vals = _square_wave(n_cycles=4, period=20, high=50.0, low=0.0)
    idx = ev.detect_threshold_crossings(vals, threshold=30.0, direction="falling")
    assert len(idx) == 4  # each high->low transition


def test_standing_above_threshold_yields_zero_crossings():
    # Fz stays at 700 N the whole trial (standing on the plate) -> no crossing.
    vals = np.full(1000, 700.0)
    assert len(ev.detect_threshold_crossings(vals, 30.0, "rising")) == 0
    assert len(ev.detect_threshold_crossings(vals, 30.0, "falling")) == 0


# -- noise guards ------------------------------------------------------------

def test_min_distance_collapses_chatter():
    # Two genuine rising crossings far apart, plus a 1-frame dip right after the
    # first that creates a spurious extra crossing.
    vals = np.array([0, 50, 50, 20, 50, 50, 50,  # chatter near frame 1 and 4
                     0, 0, 0, 0,
                     0, 50, 50, 50])  # second genuine crossing at 12
    raw = ev.detect_threshold_crossings(vals, 30.0, "rising")
    assert len(raw) == 3  # frames 1, 4, 12 without a guard
    guarded = ev.detect_threshold_crossings(vals, 30.0, "rising", min_distance=5)
    np.testing.assert_array_equal(guarded, [1, 12])


def test_hysteresis_rejects_reentry_without_excursion():
    # Signal rises past 30, dips only to 25 (not below the 30-10=20 band), rises
    # again: hysteresis should NOT count the second rise as a new crossing.
    vals = np.array([0, 35, 35, 25, 35, 35,   # one real excursion (re-entry at 25)
                     0, 0,                      # drops below the lower band -> rearmed
                     35, 35])                   # second real crossing
    simple = ev.detect_threshold_crossings(vals, 30.0, "rising")
    assert len(simple) == 3  # frames 1, 4, 8 without hysteresis
    hyst = ev.detect_threshold_crossings(vals, 30.0, "rising", hysteresis=10.0)
    np.testing.assert_array_equal(hyst, [1, 8])


# -- scope -------------------------------------------------------------------

def test_scope_limits_search_and_keeps_absolute_indices():
    vals = np.concatenate([[0.0], _square_wave(n_cycles=5, period=20)])
    # Limit search to frames 25..200; crossings outside are excluded, the ones
    # inside keep their absolute frame numbers.
    full = ev.detect_threshold_crossings(vals, 30.0, "rising")
    scoped = ev.detect_threshold_crossings(vals, 30.0, "rising", scope=(25, 200))
    assert all(25 <= i <= 200 for i in scoped)
    assert set(scoped).issubset(set(full))


# -- selector ----------------------------------------------------------------

def test_select_instances_modes():
    idx = np.array([3, 9, 15, 21, 27])
    np.testing.assert_array_equal(ev.select_instances(idx, "first"), [3])
    np.testing.assert_array_equal(ev.select_instances(idx, "nth", n=2), [9])
    np.testing.assert_array_equal(ev.select_instances(idx, "nth", n=-1), [27])
    np.testing.assert_array_equal(ev.select_instances(idx, "range", lo=2, hi=4),
                                  [9, 15, 21])
    np.testing.assert_array_equal(ev.select_instances(idx, "all"), idx)
    # out-of-range nth -> empty
    assert len(ev.select_instances(idx, "nth", n=99)) == 0
    # empty input
    assert len(ev.select_instances(np.array([], dtype=int), "all")) == 0


# -- peaks -------------------------------------------------------------------

def test_detect_peaks_sine_multi():
    fs = 100.0
    t = np.arange(0, 5, 1 / fs)  # 5 s
    freq = 1.0
    vals = np.sin(2 * np.pi * freq * t)
    peaks = ev.detect_peaks(vals, kind="max", min_distance=int(0.5 * fs))
    # ~1 peak per second over 5 s.
    assert 4 <= len(peaks) <= 5
    # all detected peaks are near the sine's max (1.0)
    assert np.all(vals[peaks] > 0.99)
    valleys = ev.detect_peaks(vals, kind="min", min_distance=int(0.5 * fs))
    assert np.all(vals[valleys] < -0.99)


# -- global extremum: the single overall max/min frame -----------------------

def test_detect_global_extreme_max_and_min():
    # A signal whose unique global max is at frame 30 and global min at frame 70.
    vals = np.zeros(100)
    vals[30] = 5.0   # global max
    vals[70] = -3.0  # global min
    # add some smaller local bumps that must NOT be picked
    vals[10] = 2.0
    vals[90] = -1.0
    np.testing.assert_array_equal(
        ev.detect_global_extreme(vals, kind="max"), [30])
    np.testing.assert_array_equal(
        ev.detect_global_extreme(vals, kind="min"), [70])


def test_detect_global_extreme_scope_excludes_outside():
    # Global max overall is at frame 30, but scoping to 50..99 must instead pick
    # the in-window maximum (frame 60), returned in absolute frame numbering.
    vals = np.zeros(100)
    vals[30] = 9.0   # biggest overall, but outside the scope
    vals[60] = 4.0   # biggest inside scope 50..99
    scoped = ev.detect_global_extreme(vals, kind="max", scope=(50, 99))
    np.testing.assert_array_equal(scoped, [60])
    # Without scope it returns the true global max.
    np.testing.assert_array_equal(ev.detect_global_extreme(vals, kind="max"), [30])


def test_detect_global_extreme_nan_safe_and_empty():
    # NaN gaps are ignored; the global max is the real peak at frame 5.
    vals = np.array([np.nan, 1.0, np.nan, 3.0, 2.0, 7.0, np.nan, 4.0])
    np.testing.assert_array_equal(ev.detect_global_extreme(vals, kind="max"), [5])
    # All-NaN window -> empty (nothing to pick), never raises.
    all_nan = np.full(20, np.nan)
    assert len(ev.detect_global_extreme(all_nan, kind="max")) == 0
    # Empty input -> empty.
    assert len(ev.detect_global_extreme(np.array([]), kind="max")) == 0


def test_compute_global_maximum_event_one_frame():
    # Integration: a DetectEventStep(method="global_maximum") over a synthetic
    # "knee" signal yields exactly the one global-max frame via the pipeline.
    n = 200
    knee = np.zeros(n)
    knee[120] = 60.0   # the single peak-flexion frame
    knee[40] = 30.0    # a smaller local bump that must be ignored
    ds = {"time": np.arange(n) / 100.0, "knee": knee}
    p = Pipeline()
    p.add(DetectEventStep(input="knee", label="PeakFlex",
                          method="global_maximum"))
    out = compute_detected_events(ds, p)
    assert len(out) == 1
    assert out[0]["label"] == "PeakFlex"
    assert out[0]["frames"] == [120]
    assert out[0]["times"] == [ds["time"][120]]


def test_compute_global_minimum_event_one_frame():
    n = 200
    knee = np.zeros(n)
    knee[150] = -45.0  # the single global minimum
    knee[30] = -20.0   # smaller dip, ignored
    ds = {"time": np.arange(n) / 100.0, "knee": knee}
    p = Pipeline()
    p.add(DetectEventStep(input="knee", label="MaxExt",
                          method="global_minimum"))
    out = compute_detected_events(ds, p)
    assert out[0]["frames"] == [150]


def test_detect_zero_crossings():
    fs = 100.0
    t = np.arange(0, 3, 1 / fs)
    vals = np.sin(2 * np.pi * 1.0 * t)
    up = ev.detect_zero_crossings(vals, "up")
    down = ev.detect_zero_crossings(vals, "down")
    both = ev.detect_zero_crossings(vals, "both")
    assert len(up) >= 2 and len(down) >= 2
    assert len(both) == len(up) + len(down)


# -- DetectEventStep persistence ---------------------------------------------

def test_detect_event_step_roundtrip():
    step = DetectEventStep(
        input="fz:filt", label="HS", method="threshold",
        params={"threshold": 20.0, "direction": "rising", "min_distance": 30},
        selector={"mode": "all"}, scope=[0, 500])
    d = step.to_dict()
    step2 = DetectEventStep.from_dict(d)
    assert step2.to_dict() == d
    assert step2.input == "fz:filt"
    assert step2.params["threshold"] == 20.0
    assert step2.scope == [0, 500]


def test_pipeline_with_detect_step_roundtrip():
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]))
    p.add(DetectEventStep(input="fz:filt", label="HS", method="threshold",
                          params={"threshold": 20.0}))
    d = p.to_dict()
    p2 = Pipeline.from_dict(d)
    assert p2.to_dict() == d
    assert len(p2.filter_steps()) == 1
    assert len(p2.detect_event_steps()) == 1


def test_old_manifest_has_no_detect_steps():
    # An old project (no detect steps) -> empty detected events, manual only.
    p = Pipeline.from_dict({"steps": []})
    assert p.detect_event_steps() == []
    ds = {"time": np.arange(100) / 100.0,
          "events": [{"name": "Mark", "index": 42}]}
    assert compute_detected_events(ds, p) == []
    assert event_catalog(ds, p) == ["Mark"]
    # endpoint resolves the manual event (single instance, backward-compat)
    assert resolve_endpoint_frame(ds, "Mark", pipeline=p) == 42


# -- compute_detected_events with :filt input --------------------------------

def _gait_dataset(n=600, fs=100.0):
    """Synthetic Fz: a noisy square wave so :filt smooths it before detection."""
    t = np.arange(n) / fs
    period = 100  # frames per "step"
    base = np.where((np.arange(n) % period) < 50, 600.0, 0.0)
    noise = 5.0 * np.sin(2 * np.pi * 30.0 * t)  # high-freq wobble
    return {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
            "fz": base + noise}


def test_compute_detected_events_resolves_filt_input():
    ds = _gait_dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]))
    p.add(DetectEventStep(input="fz:filt", label="HS", method="threshold",
                          params={"threshold": 300.0, "direction": "rising",
                                  "min_distance": 20},
                          selector={"mode": "all"}))
    out = compute_detected_events(ds, p)
    assert len(out) == 1
    entry = out[0]
    assert entry["label"] == "HS"
    # The trial starts already above threshold (no rising edge at frame 0), so
    # the rising crossings are at the start of each *later* step: 5 in 600 frames.
    assert len(entry["frames"]) == 5
    assert len(entry["times"]) == len(entry["frames"])
    # caching: second call returns the same cached object
    assert compute_detected_events(ds, p) is out


def test_detect_cache_invalidated_on_recipe_change():
    ds = _gait_dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]))
    p.add(DetectEventStep(input="fz:filt", label="HS", method="threshold",
                          params={"threshold": 300.0, "direction": "rising",
                                  "min_distance": 20},
                          selector={"mode": "all"}))
    first = compute_detected_events(ds, p)
    # change the recipe -> token changes -> recompute (new object)
    p.detect_event_steps()[0].label = "TO"
    second = compute_detected_events(ds, p)
    assert second is not first
    assert second[0]["label"] == "TO"


# -- fixed-frame ("frame") method: manual pin unified into the pipeline -------

def test_detect_at_frame_basic_and_clamp():
    # In range -> exactly that frame.
    np.testing.assert_array_equal(ev.detect_at_frame(1000, 473), [473])
    # Out of range high -> clamped to last frame.
    np.testing.assert_array_equal(ev.detect_at_frame(1000, 5000), [999])
    # Negative -> clamped to 0.
    np.testing.assert_array_equal(ev.detect_at_frame(1000, -3), [0])
    # No clock -> empty, never raises.
    assert len(ev.detect_at_frame(0, 10)) == 0


def test_frame_step_roundtrip():
    step = DetectEventStep(label="FRAME=473", method="frame",
                           params={"frame": 473})
    d = step.to_dict()
    step2 = DetectEventStep.from_dict(d)
    assert step2.to_dict() == d
    assert step2.method == "frame"
    assert step2.params["frame"] == 473
    assert step2.input == ""  # frame method needs no input signal


def test_compute_frame_event_exact_instance():
    # A frame step yields exactly one instance at the typed frame, with no signal.
    ds = {"time": np.arange(1000) / 100.0}
    p = Pipeline()
    p.add(DetectEventStep(label="HS", method="frame", params={"frame": 473}))
    out = compute_detected_events(ds, p)
    assert len(out) == 1
    assert out[0]["label"] == "HS"
    assert out[0]["frames"] == [473]
    assert out[0]["times"] == [ds["time"][473]]


def test_compute_frame_event_out_of_range_clamps():
    ds = {"time": np.arange(100) / 100.0}
    p = Pipeline()
    p.add(DetectEventStep(label="X", method="frame", params={"frame": 9999}))
    out = compute_detected_events(ds, p)
    assert out[0]["frames"] == [99]  # clamped to last frame


def test_compute_frame_event_without_input_signal():
    # No cop/fz signals at all in the dataset: frame method must still work
    # (it never resolves an input). Only a time clock is present.
    ds = {"time": np.arange(500) / 100.0}
    p = Pipeline()
    p.add(DetectEventStep(input="", label="Mark", method="frame",
                          params={"frame": 200}))
    out = compute_detected_events(ds, p)
    assert out[0]["frames"] == [200]
    # And it coexists with the event catalog / endpoint resolution.
    assert "Mark" in event_catalog(ds, p)
    assert resolve_endpoint_frame(ds, "Mark", pipeline=p) == 200


def test_resolve_endpoint_frame_picks_instance():
    ds = _gait_dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]))
    p.add(DetectEventStep(input="fz:filt", label="HS", method="threshold",
                          params={"threshold": 300.0, "direction": "rising",
                                  "min_distance": 20},
                          selector={"mode": "all"}))
    frames = event_frames(ds, "HS", pipeline=p)
    assert len(frames) == 5
    first = resolve_endpoint_frame(ds, "HS", mode="first", pipeline=p)
    third = resolve_endpoint_frame(ds, "HS", mode="nth", n=3, pipeline=p)
    assert first == int(frames[0])
    assert third == int(frames[2])


# -- threshold as a metric: reference (e.g. 5% body weight) ------------------

def test_threshold_metric_reference_resolves_with_metrics():
    # A step whose threshold is "metric:bodyweight" detects at that resolved
    # level only when a matching metrics dict is supplied.
    n = 600
    t = np.arange(n) / 100.0
    period = 100
    fz = np.where((np.arange(n) % period) < 50, 600.0, 0.0)
    ds = {"time": t, "fs": 100.0, "cop_ap": np.zeros(n),
          "cop_ml": np.zeros(n), "fz": fz}
    p = Pipeline()
    p.add(DetectEventStep(input="fz", label="HS", method="threshold",
                          params={"threshold": "metric:bodyweight",
                                  "direction": "rising", "min_distance": 20},
                          selector={"mode": "all"}))
    # bodyweight 300 N -> same rising edges as a literal 300 threshold (5 later steps).
    out = compute_detected_events(ds, p, metrics={"bodyweight": 300.0})
    assert out[0]["label"] == "HS"
    assert len(out[0]["frames"]) == 5
    # A literal-300 recipe gives the identical frames.
    p2 = Pipeline()
    p2.add(DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 300.0, "direction": "rising",
                                   "min_distance": 20},
                           selector={"mode": "all"}))
    assert out[0]["frames"] == compute_detected_events(ds, p2)[0]["frames"]


def test_threshold_metric_reference_no_metrics_yields_empty():
    # Without a metrics dict the metric: reference is unresolvable -> no events
    # (graceful skip, never raises). Matches the UI's bare catalog-call path.
    n = 200
    ds = {"time": np.arange(n) / 100.0, "fs": 100.0,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fz": np.where(np.arange(n) < 100, 0.0, 600.0)}
    p = Pipeline()
    p.add(DetectEventStep(input="fz", label="HS", method="threshold",
                          params={"threshold": "metric:bodyweight",
                                  "direction": "rising"}))
    assert compute_detected_events(ds, p)[0]["frames"] == []
    # Unknown metric name (dict given but missing the key) is also empty.
    assert compute_detected_events(
        ds, p, metrics={"mass": 70.0}, use_cache=False)[0]["frames"] == []


def test_threshold_metric_value_change_flips_token():
    # The resolved metric value is part of the cache token: changing the
    # subject's body weight must re-detect, while an unrelated recipe (literal
    # threshold) keeps the legacy plain-list token shape.
    p = Pipeline()
    p.add(DetectEventStep(input="fz", label="HS", method="threshold",
                          params={"threshold": "metric:bodyweight",
                                  "direction": "rising"}))
    tok_a = _detect_token(p, metrics={"bodyweight": 300.0})
    tok_b = _detect_token(p, metrics={"bodyweight": 350.0})
    assert tok_a != tok_b
    # An unrelated metric change does NOT churn the token.
    tok_c = _detect_token(p, metrics={"bodyweight": 300.0, "height": 1.8})
    assert tok_a == tok_c
    # A literal-threshold recipe keeps the legacy list token (metrics ignored).
    p2 = Pipeline()
    p2.add(DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 300.0}))
    assert _detect_token(p2, metrics={"bodyweight": 999.0}) == _detect_token(p2)


# -- G1: min_distance in SECONDS (clock-independent refractory) ---------------

def test_resolve_min_distance_frames_seconds_conversion():
    # A min_distance_s (seconds) converts to master-clock FRAMES via round(s*fs):
    # the same 0.6 s is 600 frames at 1000 Hz but 60 frames at 100 Hz.
    assert _resolve_min_distance_frames({"min_distance_s": 0.6}, 1000.0) == 600
    assert _resolve_min_distance_frames({"min_distance_s": 0.6}, 100.0) == 60


def test_resolve_min_distance_frames_legacy_is_frames_unchanged():
    # No min_distance_s -> the legacy 'min_distance' is returned verbatim (frames),
    # independent of fs (back-compat: a saved 60 stays 60 frames, not 60 s).
    assert _resolve_min_distance_frames({"min_distance": 60}, 1000.0) == 60
    assert _resolve_min_distance_frames({"min_distance": 60}, 100.0) == 60
    # Neither key present -> None (off).
    assert _resolve_min_distance_frames({}, 1000.0) is None


def test_resolve_min_distance_frames_seconds_takes_precedence():
    # When both are present the seconds value wins (new/edited steps write _s).
    assert _resolve_min_distance_frames(
        {"min_distance_s": 0.6, "min_distance": 999}, 1000.0) == 600
    # 0 s clamps to at least 1 frame (max(1, round(0*fs))) -> effectively off.
    assert _resolve_min_distance_frames({"min_distance_s": 0.0}, 1000.0) == 1


def _cosine_dataset(fs, freq=5.0, dur=2.0):
    """A clean 5 Hz cosine: local maxima are 1/freq = 0.2 s apart, regardless of
    sample rate, so a refractory expressed in SECONDS must thin them identically
    at fs=100 and fs=1000 (in FRAMES the spacing is 20 vs 200)."""
    n = int(round(dur * fs)) + 1
    t = np.arange(n) / fs
    return {"time": t, "fs": fs, "sig": np.cos(2 * np.pi * freq * t)}


def _n_peaks(ds, params):
    p = Pipeline()
    p.add(DetectEventStep(input="sig", label="PK", method="peak",
                          params={"kind": "max", **params},
                          selector={"mode": "all"}))
    return len(compute_detected_events(ds, p)[0]["frames"])


def test_min_distance_seconds_is_clock_independent():
    # Peaks 0.2 s apart; a 0.3 s refractory collapses the SAME real-time chatter
    # at both rates -> equal survivor count, and fewer than the raw peak count.
    raw100 = _n_peaks(_cosine_dataset(100.0), {})
    n100 = _n_peaks(_cosine_dataset(100.0), {"min_distance_s": 0.3})
    n1000 = _n_peaks(_cosine_dataset(1000.0), {"min_distance_s": 0.3})
    assert n100 == n1000          # seconds mean the same real time at any fs
    assert n100 < raw100          # the 0.3 s refractory actually thinned them


def test_legacy_min_distance_frames_stays_clock_dependent():
    # Back-compat: a legacy frame 'min_distance' still means FRAMES, so the same
    # 60 is 0.06 s at 1000 Hz (keeps the 0.2 s-spaced peaks) but 0.6 s at 100 Hz
    # (collapses them) -> intentionally clock-dependent, exactly as before.
    n1000 = _n_peaks(_cosine_dataset(1000.0), {"min_distance": 60})
    n100 = _n_peaks(_cosine_dataset(100.0), {"min_distance": 60})
    assert n1000 > n100


def test_min_distance_seconds_threshold_path_clock_independent():
    # The same seconds treatment applies to the threshold detector's refractory.
    def n_cross(fs):
        n = int(round(2.0 * fs)) + 1
        t = np.arange(n) / fs
        # A 5 Hz square wave: rising edges 0.2 s apart.
        sig = np.where((np.sin(2 * np.pi * 5.0 * t) >= 0), 1.0, 0.0)
        ds = {"time": t, "fs": fs, "sig": sig}
        p = Pipeline()
        p.add(DetectEventStep(input="sig", label="HS", method="threshold",
                              params={"threshold": 0.5, "direction": "rising",
                                      "min_distance_s": 0.3},
                              selector={"mode": "all"}))
        return len(compute_detected_events(ds, p)[0]["frames"])
    assert n_cross(100.0) == n_cross(1000.0)


# -- scope bounds in SECONDS (clock-independent search window) ----------------

def _scoped_frames(fs, scope):
    """Detect every above-threshold rising edge of a 5 Hz square wave (edges
    0.2 s apart) under a search-window ``scope`` -> the surviving frame list.
    The window is what we vary; ``select all`` keeps every instance inside it."""
    n = int(round(2.0 * fs)) + 1
    t = np.arange(n) / fs
    sig = np.where((np.sin(2 * np.pi * 5.0 * t) >= 0), 1.0, 0.0)
    ds = {"time": t, "fs": fs, "sig": sig}
    p = Pipeline()
    p.add(DetectEventStep(input="sig", label="HS", method="threshold",
                          params={"threshold": 0.5, "direction": "rising"},
                          selector={"mode": "all"}, scope=scope))
    return compute_detected_events(ds, p)[0]["frames"]


def test_scope_time_bound_resolves_to_round_seconds_times_fs():
    # A time bound resolves to frame round(seconds * fs): a 0.5..1.5 s window at
    # 1000 Hz limits detection to frames 500..1500.
    scope = {"from": {"type": "time", "seconds": 0.5},
             "to": {"type": "time", "seconds": 1.5}}
    frames = _scoped_frames(1000.0, scope)
    assert frames                                   # found something inside
    assert all(500 <= f <= 1500 for f in frames)    # nothing leaks outside


def test_scope_time_bound_is_clock_independent():
    # The SAME 0.5..1.5 s window selects the SAME real-time edges at fs=100 and
    # fs=1000 (in frames the window is 50..150 vs 500..1500, but the edges it
    # keeps are the same 5 events).
    scope = {"from": {"type": "time", "seconds": 0.5},
             "to": {"type": "time", "seconds": 1.5}}
    f100 = _scoped_frames(100.0, scope)
    f1000 = _scoped_frames(1000.0, scope)
    # Same count of survivors, and the same instant in seconds for each.
    assert len(f100) == len(f1000)
    assert np.allclose([f / 100.0 for f in f100],
                       [f / 1000.0 for f in f1000], atol=0.011)


def test_scope_time_and_frame_bounds_mix():
    # A from-time / to-frame mixed window resolves each bound on its own terms;
    # the frame bound stays clock-dependent, the time bound does not.
    scope = {"from": {"type": "time", "seconds": 0.5},
             "to": {"type": "frame", "frame": 1500}}
    frames = _scoped_frames(1000.0, scope)
    assert frames
    assert all(500 <= f <= 1500 for f in frames)
