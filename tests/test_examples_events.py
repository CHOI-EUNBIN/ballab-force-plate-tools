"""Integration tests on the *real* example C3D files (examples/).

Unlike the synthetic-signal regression tests, this module loads the bundled
recordings, runs the full pipeline at the *core* level (no UI) and asserts that
event detection + event-bounded search windows + metrics behave correctly across
a range of scenarios and edge cases.

These files live in ``examples/`` (two AMTI force plates each, 1000 Hz, raw
C3D-faithful down-negative Fz). If the folder / a file is missing, or ezc3d is
not installed, the affected tests are SKIPPED — so the suite stays green on a
checkout without the data, but exercises the real data when present.

Data shape (probed 2026-06-24):
  * ``YA0x/dt_*.c3d`` / ``st_*.c3d`` — a step trial: one foot loads fp1 (Fz starts
    loaded, then toe-off ~ falling edge), the other foot lands on fp2 (rising
    edge -> peak -> falling). Both plates ~ -390..-490 N peak (down-negative).
  * ``YA0x/static.c3d`` — quiet standing: fp1 stays loaded the whole trial (NO
    threshold crossings -> 0 events, the graceful static case), fp2 ~ empty.
"""

import os

import numpy as np
import pytest

from core import events_compute as ec
from core.pipeline import (ComputeStep, DetectEventStep, MetricStep, Pipeline)
from core.run import run_pipeline

try:
    from core.c3d_reader import read_c3d, C3D_AVAILABLE
    from core.data_quality import clean_dataset
except Exception:                                 # pragma: no cover
    C3D_AVAILABLE = False

_EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "examples")
# The bundled CEB treadmill-gait trials live under tests/examples/ (not the
# repo-root examples/ used above). Used by the G1 clock-independence test.
_TEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


def _has(rel):
    return os.path.isfile(os.path.join(_EX, rel))


def _load(rel):
    """Load + clean an example trial, or skip if absent / ezc3d missing."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    path = os.path.join(_EX, rel)
    if not os.path.isfile(path):
        pytest.skip(f"example file missing: {rel}")
    ds = read_c3d(path)
    clean_dataset(ds)
    return ds


# A couple of trials known to have a clean fp2 foot-contact (rising) + an fp1
# foot already loaded at start (falling). Picked from the probe run.
_DYNAMIC = "YA02/dt_1.c3d"
_DYNAMIC2 = "YA01/dt_1.c3d"
_STATIC = "YA01/static.c3d"


def _frames(det, label):
    for e in det:
        if e["label"] == label:
            return e["frames"]
    return []


# --------------------------------------------------------------------------
# 1. Detection methods on real data
# --------------------------------------------------------------------------

def test_real_threshold_rising_falling_on_rectified_fz():
    """abs() rectifies the down-negative raw Fz; a rising crossing = foot lands on
    fp2, a falling crossing = toe-off. Both must find >=1 instance, with the
    rising edge strictly before the falling edge (a real contact window)."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="OFF", method="threshold",
                          params={"threshold": 50.0, "direction": "falling"},
                          selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    on, off = _frames(det, "ON"), _frames(det, "OFF")
    assert len(on) >= 1 and len(off) >= 1
    assert on[0] < off[0]                       # contact then release


def test_real_peak_and_valley_prominence():
    """A prominence-gated peak on the rectified fp2 Fz finds the loading peak; the
    valley (kind=min) of the same signal sits near the unloaded baseline."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="PK", method="peak",
                          params={"kind": "max", "prominence": 100.0,
                                  "min_distance": 200},
                          selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    pk = _frames(det, "PK")
    assert len(pk) >= 1
    afz = np.abs(np.asarray(ds["fp2:fz"], float))
    # the detected peak frame is a genuinely high-load sample (> half the max)
    assert afz[pk[0]] > 0.5 * afz.max()


def test_real_global_max_min_single_instance():
    """global_maximum/minimum return exactly one frame (the overall extremum). On
    the rectified signal the global max is the single most-loaded frame."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="GMAX", method="global_maximum"))
    p.add(DetectEventStep(input="fp2:fz", label="GMIN", method="global_minimum"))
    det = ec.compute_detected_events(ds, p)
    gmax, gmin = _frames(det, "GMAX"), _frames(det, "GMIN")
    assert len(gmax) == 1 and len(gmin) == 1
    afz = np.abs(np.asarray(ds["fp2:fz"], float))
    assert gmax[0] == int(np.argmax(afz))
    # raw fz min (most-negative) == rectified max (most loaded): same instant.
    assert gmin[0] == int(np.argmin(np.asarray(ds["fp2:fz"], float)))


def test_real_zero_crossing_on_cop():
    """COP about its mean oscillates -> zero-crossings of the mean-removed COP_ML
    exist and are interleaved (no exception, multiple instances)."""
    ds = _load(_STATIC)
    cop = np.asarray(ds["fp1:cop_ml"], float)
    # Build a mean-centred COP signal as a derived input via a trivial normalize
    # is overkill; detect on the raw COP_ML shifted by injecting a centred copy.
    ds["cop_ml_centred"] = cop - np.nanmean(cop)
    p = Pipeline()
    p.add(DetectEventStep(input="cop_ml_centred", label="ZC", method="zero",
                          params={"direction": "both"}, selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    zc = _frames(det, "ZC")
    # A real sway signal crosses its mean many times.
    assert len(zc) >= 2


def test_real_fixed_frame_event():
    """A method='frame' event lands on the typed frame regardless of any signal."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    p = Pipeline()
    p.add(DetectEventStep(label="MID", method="frame", params={"frame": n // 2}))
    det = ec.compute_detected_events(ds, p)
    assert _frames(det, "MID") == [n // 2]


# --------------------------------------------------------------------------
# 2. Event-bounded search window (scope)
# --------------------------------------------------------------------------

def test_real_event_bounded_scope_limits_detection():
    """Detect ON/OFF (rising/falling) first; a later peak step scoped to
    {from: ON#1, to: OFF#1} must only return frames inside that contact window."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="OFF", method="threshold",
                          params={"threshold": 50.0, "direction": "falling"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="PK", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "event", "label": "ON", "instance": 1},
                                 "to": {"type": "event", "label": "OFF", "instance": 1}}))
    det = ec.compute_detected_events(ds, p)
    on, off, pk = _frames(det, "ON"), _frames(det, "OFF"), _frames(det, "PK")
    assert pk, "scoped peak found nothing inside the contact window"
    assert all(on[0] <= f <= off[0] for f in pk)


def test_real_frame_bounded_scope_limits_detection():
    """A legacy/explicit frame window {from: frame a, to: frame b} bounds the
    search; every detected instance is inside [a, b]."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    a, b = n // 3, 2 * n // 3
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="PK", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "frame", "frame": a},
                                 "to": {"type": "frame", "frame": b}}))
    det = ec.compute_detected_events(ds, p)
    pk = _frames(det, "PK")
    assert all(a <= f <= b for f in pk)


def test_real_legacy_list_scope_still_supported():
    """A legacy ``scope=[start, end]`` frame window (old project format) bounds
    the search the same way a dict frame window does."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    a, b = n // 3, 2 * n // 3
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="PK", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope=[a, b]))
    det = ec.compute_detected_events(ds, p)
    assert all(a <= f <= b for f in _frames(det, "PK"))


def test_real_scope_with_nth_bounds():
    """Event-instance bounds can use a non-first instance: from ON#1 to OFF#-1
    (last). Still resolves to a valid window when those instances exist."""
    ds = _load(_DYNAMIC2)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="OFF", method="threshold",
                          params={"threshold": 50.0, "direction": "falling"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="PK", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "event", "label": "ON", "instance": 1},
                                 "to": {"type": "event", "label": "OFF", "instance": -1}}))
    det = ec.compute_detected_events(ds, p)
    on, off, pk = _frames(det, "ON"), _frames(det, "OFF"), _frames(det, "PK")
    if on and off:
        lo, hi = sorted([on[0], off[-1]])
        assert all(lo <= f <= hi for f in pk)


# --------------------------------------------------------------------------
# 3. Edge cases — must be graceful (no exception)
# --------------------------------------------------------------------------

def test_real_static_trial_no_crossings():
    """Quiet standing keeps fp1 loaded the whole trial -> a threshold *crossing*
    detector finds ZERO events (the desired static behaviour), no exception."""
    ds = _load(_STATIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="afz", method="abs"))
    p.add(DetectEventStep(input="afz", label="HS", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    assert _frames(det, "HS") == []


def test_real_missing_scope_label_falls_back_to_whole_trial():
    """A scope referencing labels that no earlier step produced falls back to the
    trial edges (whole trial), never raising."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="P", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "event", "label": "NOPE", "instance": 1},
                                 "to": {"type": "event", "label": "ALSO_NO", "instance": 1}}))
    det = ec.compute_detected_events(ds, p)
    pk = _frames(det, "P")
    # fell back to [0, n] -> at least the peaks the unscoped run would find.
    assert all(0 <= f < n for f in pk)
    assert len(pk) >= 1


def test_real_out_of_range_instance_falls_back():
    """An out-of-range event instance in a bound falls back to the trial edge
    (start->0) without raising; detection still runs over the resolved window."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="P", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "event", "label": "ON", "instance": 99},
                                 "to": {"type": "frame", "frame": n - 1}}))
    det = ec.compute_detected_events(ds, p)
    # from=0 (fallback) to n-1 -> whole trial; no exception, frames in range.
    assert all(0 <= f < n for f in _frames(det, "P"))


def test_real_reversed_bounds_auto_ordered():
    """A reversed scope (from > to) is auto-ordered so the window is still valid."""
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    a, b = 2 * n // 3, n // 3        # intentionally reversed
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="P", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "frame", "frame": a},
                                 "to": {"type": "frame", "frame": b}}))
    det = ec.compute_detected_events(ds, p)
    lo, hi = b, a
    assert all(lo <= f <= hi for f in _frames(det, "P"))


def test_real_forward_reference_invisible():
    """A step's scope referencing a label produced by a LATER step sees nothing
    (only earlier-detected events are visible) -> that bound falls back, no error.
    """
    ds = _load(_DYNAMIC)
    n = len(ds["time"])
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    # B (earlier) references A (later) -> A invisible -> from bound falls back to 0.
    p.add(DetectEventStep(input="afz2", label="B", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"},
                          scope={"from": {"type": "event", "label": "A", "instance": 1},
                                 "to": {"type": "frame", "frame": n - 1}}))
    p.add(DetectEventStep(input="afz2", label="A", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    assert all(0 <= f < n for f in _frames(det, "B"))


def test_real_nonexistent_input_signal_graceful():
    """A detect step whose input signal doesn't exist (e.g. an angle on a trial
    with no model) yields an empty frame list, not an exception."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(DetectEventStep(input="angle:NopeJoint", label="X", method="peak",
                          params={"kind": "max"}, selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    assert _frames(det, "X") == []


# --------------------------------------------------------------------------
# 4. Metrics on detected events / segments — values must be sane
# --------------------------------------------------------------------------

def test_real_stance_peak_and_impulse_metrics():
    """Segment a metric on the fp2 contact window (ON->OFF): the peak rectified
    force is positive and near the signal max; the impulse (N*s) is positive and
    finite (not NaN)."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="afz2", label="OFF", method="threshold",
                          params={"threshold": 50.0, "direction": "falling"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="afz2", op="max", name="StancePeak", segment=["ON", "OFF"]))
    p.add(MetricStep(input="afz2", op="integral", name="Impulse", segment=["ON", "OFF"]))
    out = run_pipeline(ds, p, subject={"mass": 70.0})
    mv = out["metric_values"]
    peak, pu = mv["StancePeak"]
    imp, iu = mv["Impulse"]
    afz = np.abs(np.asarray(ds["fp2:fz"], float))
    assert np.isfinite(peak) and peak > 0
    assert peak == pytest.approx(afz.max(), rel=0.05)   # peak within the contact window ~ trial max
    assert pu == "N"
    assert np.isfinite(imp) and imp > 0 and iu == "N*s"


def test_real_value_at_event_reads_signal_at_peak_frame():
    """A max metric emits an event at the peak frame; value_at_event reading the
    same signal at that frame equals the metric value."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(MetricStep(input="afz2", op="max", name="PeakLoad"))
    p.add(MetricStep(input="afz2", op="value_at_event", name="Load@peak",
                     event="PeakLoad"))
    out = run_pipeline(ds, p)
    mv = out["metric_values"]
    assert mv["PeakLoad"][0] == pytest.approx(mv["Load@peak"][0])


def test_real_cop_metrics_on_static_are_finite():
    """COP sway metrics on the static trial (fp1) are finite and non-negative —
    a real balance recording yields a positive sway area / path length."""
    ds = _load(_STATIC)
    p = Pipeline()
    p.add(MetricStep(input="fp1:cop", op="ellipse_area", name="Sway area"))
    p.add(MetricStep(input="fp1:cop", op="sway_path", name="Path length"))
    out = run_pipeline(ds, p)
    mv = out["metric_values"]
    area, au = mv["Sway area"]
    path, _ = mv["Path length"]
    assert np.isfinite(area) and area >= 0
    assert np.isfinite(path) and path >= 0


def test_real_static_trial_pipeline_runs_without_events():
    """A whole-trial metric still computes on the static trial even though the
    detect step found no events (graceful: falls back to whole trial)."""
    ds = _load(_STATIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="afz", method="abs"))
    p.add(DetectEventStep(input="afz", label="HS", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    # Segment metric on an empty event set -> falls back to whole trial -> 1 value.
    p.add(MetricStep(input="afz", op="mean", name="MeanLoad", segment=["HS", "HS"]))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["MeanLoad"]
    assert np.isfinite(val) and val > 0 and unit == "N"


def test_real_unknown_metric_op_is_nan_not_crash():
    """A MetricStep with an op not in OP_INFO (a misconfigured / forward-version
    recipe) degrades to NaN rather than raising — one bad step must not break the
    whole run."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(MetricStep(input="afz2", op="not_a_real_op", name="Bogus"))
    p.add(MetricStep(input="afz2", op="max", name="Good"))
    out = run_pipeline(ds, p)
    mv = out["metric_values"]
    assert np.isnan(mv["Bogus"][0])              # graceful NaN
    assert np.isfinite(mv["Good"][0])            # the good step still ran


def test_real_multi_plate_independent_detection():
    """Detection on fp1 and fp2 is independent: each plate's own contact is found
    on its own rectified channel."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="a1", method="abs"))
    p.add(ComputeStep(input="fp2:fz", name="a2", method="abs"))
    p.add(DetectEventStep(input="a1", label="TO1", method="threshold",
                          params={"threshold": 50.0, "direction": "falling"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="a2", label="HS2", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    det = ec.compute_detected_events(ds, p)
    # Both plates carry a foot in a step trial -> each finds its own edge.
    assert len(_frames(det, "TO1")) >= 1
    assert len(_frames(det, "HS2")) >= 1


# --------------------------------------------------------------------------
# 5. G1 — refractory in SECONDS is clock-independent (CEB treadmill gait)
# --------------------------------------------------------------------------

def _ceb_hip_dataset():
    """Build the CEB model from its static, apply to the gait trial, and return
    (dataset-template, angle_result, marker_duration). Skips if data/ezc3d
    missing. The dataset's master clock is set per-test (1000 vs 100 Hz)."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d")
    dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB")
    model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    res = model.apply(dyn["markers"], label_map=lm)
    if "R_HIP_angle_FE" not in res.get("angles", {}):
        pytest.skip("CEB model has no R_HIP_angle_FE channel")
    dur = float(dyn["markers"]["time"][-1])
    return dyn, res, dur


def _ceb_hs(dyn, res, dur, master_fs, params):
    """Run a peak DetectEventStep on R_HIP_angle_FE at the given master clock,
    returning (n_heel_strikes, stride_mean_s, stride_CV_percent)."""
    n = int(round(dur * master_fs)) + 1
    ds = dict(dyn)
    ds["time"] = np.arange(n) / master_fs
    ds["fs"] = float(master_fs)
    ds.pop("_events_cache", None); ds.pop("_events_token", None)
    p = Pipeline()
    p.add(DetectEventStep(input="angle:R_HIP_angle_FE", label="R_HS",
                          method="peak", params={"kind": "max", **params},
                          selector={"mode": "all"}))
    frames = ec.compute_detected_events(ds, p, angle_result=res,
                                        use_cache=False)[0]["frames"]
    t = ds["time"][np.asarray(frames, int)]
    strides = np.diff(t)
    cv = 100.0 * strides.std() / strides.mean() if len(strides) else float("nan")
    return len(frames), float(strides.mean()), float(cv)


def test_ceb_seconds_refractory_clock_independent():
    """The headline G1 result: a 0.6 s refractory on R_HIP_angle_FE peaks finds
    178 heel-strikes (stride ~1.12 s, CV ~2.8 %) — and gives the SAME answer
    whether the master clock is 1000 Hz or 100 Hz (that is the whole point)."""
    dyn, res, dur = _ceb_hip_dataset()
    n1000, stride1000, cv1000 = _ceb_hs(dyn, res, dur, 1000.0, {"min_distance_s": 0.6})
    n100, stride100, cv100 = _ceb_hs(dyn, res, dur, 100.0, {"min_distance_s": 0.6})
    assert n1000 == 178 and n100 == 178
    assert stride1000 == pytest.approx(1.122, abs=0.01)
    assert cv1000 == pytest.approx(2.8, abs=0.3)
    # clock-independence: identical answer at both master rates.
    assert (n1000, round(stride1000, 3), round(cv1000, 1)) == \
           (n100, round(stride100, 3), round(cv100, 1))


def test_ceb_legacy_frames_stay_clock_dependent():
    """Back-compat: a legacy frame 'min_distance' is unchanged — 60 frames at the
    1000 Hz master clock is only 0.06 s, so it fails to collapse the stride and
    over-counts (274 HS, CV ~64 %), exactly the pre-G1 behaviour. The equivalent
    600 frames recovers the correct 178."""
    dyn, res, dur = _ceb_hip_dataset()
    n60, _, cv60 = _ceb_hs(dyn, res, dur, 1000.0, {"min_distance": 60})
    n600, _, cv600 = _ceb_hs(dyn, res, dur, 1000.0, {"min_distance": 600})
    assert n60 == 274 and cv60 > 50.0          # clock-error garbage, preserved
    assert n600 == 178 and cv600 == pytest.approx(2.8, abs=0.3)


# --------------------------------------------------------------------------
# 6. G2 — kinematic HS/TO (Zeni) + stance/swing on CEB treadmill gait
# --------------------------------------------------------------------------

def _ceb_gait_detect(side="R"):
    """Build the CEB model, expose the gait progression signals, and detect
    HS (heel AP peak-max) + TO (toe AP peak-min) on the 1000 Hz master clock.
    Returns (hs_frames, to_frames, time, n_frames). Skips if data/ezc3d absent."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d")
    dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB")
    model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    res = model.apply(dyn["markers"], label_map=lm)
    dur = float(dyn["markers"]["time"][-1])
    n = int(round(dur * 1000.0)) + 1
    ds = dict(dyn)
    ds["time"] = np.arange(n) / 1000.0
    ds["fs"] = 1000.0
    md = dyn["markers"]["data"]

    def det(key, kind):
        ds.pop("_events_cache", None); ds.pop("_events_token", None)
        p = Pipeline()
        p.add(DetectEventStep(input=key, label="X", method="peak",
                              params={"kind": kind, "min_distance_s": 0.6},
                              selector={"mode": "all"}))
        return ec.compute_detected_events(ds, p, marker_disp=md, angle_result=res,
                                          use_cache=False)[0]["frames"]

    hs = det(f"gait:{side}_heel_ap", "max")
    to = det(f"gait:{side}_toe_ap", "min")
    return hs, to, ds["time"], n


def test_ceb_kinematic_hs_to_counts():
    """Zeni heel/toe events on CEB find ~one HS and ~one TO per stride (≈178,
    matching the hip-flexion proxy), with TO strictly inside the HS pairs."""
    hs, to, time, n = _ceb_gait_detect("R")
    assert 176 <= len(hs) <= 180
    assert 176 <= len(to) <= 180
    # Every TO falls between the trial's first and last HS (real contact windows).
    assert all(hs[0] <= f <= hs[-1] for f in to)


def test_ceb_stance_swing_physiological():
    """Stance/swing split on CEB: ~178 valid cycles, mean stance fraction in a
    physiological band for treadmill walking, with low cycle-to-cycle variability
    (the kinematic method is consistent)."""
    from core import gait_events as ge
    hs, to, time, n = _ceb_gait_detect("R")
    cycles = ge.split_stance_swing(hs, to, time)
    assert len(cycles) >= 170
    stance = np.array([c["stance_pct"] for c in cycles])
    assert 60.0 <= stance.mean() <= 72.0       # treadmill stance ~60-68% (Zeni)
    assert stance.std() < 3.0                  # consistent across strides
    # stance + swing = 100% by construction.
    swing = np.array([c["swing_pct"] for c in cycles])
    np.testing.assert_allclose(stance + swing, 100.0)


def _ceb_markers_and_clock():
    """Build the CEB model and return its dynamic markers dict (carrying time +
    rate on the native marker clock) for the marker-clock velocity method, which
    differentiates foot position directly rather than going through the master
    clock. Skips if data / ezc3d absent."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d")
    dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB")
    model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    model.apply(dyn["markers"], label_map=lm)        # ensure the build path runs
    return dyn["markers"]


def test_ceb_velocity_vs_coordinate_stance_characterization():
    """Additive characterization of the O'Connor/Zeni *velocity* method on CEB,
    pinned against the *coordinate* method (NOT a claim that velocity is better).

    Measured 2026-06-27 on the bundled CEB_st trial (100 Hz markers, R side):
      * coordinate: ~178 HS/TO, mean stance ~67.2 % (its TO is detected late).
      * velocity:   ~178 HS/TO, mean stance ~50.3 % — it moves stance the *other*
        way past the ~60 % overground value, because the heel-velocity-minimum HS
        lands ~90 ms LATE while the toe-velocity-minimum TO lands ~120 ms EARLY,
        and the velocity HS is noisier (std an order larger).

    So the velocity method does NOT cleanly recover 60 %; it overshoots low. This
    test locks in that behaviour so a future change to either method is visible."""
    from core import gait_events as ge
    mk = _ceb_markers_and_clock()
    t = mk["time"]

    coord = ge.gait_events(mk, "R", method="coordinate")
    vel = ge.gait_events(mk, "R", method="velocity")

    # Both methods find ~one HS/TO per stride (~178).
    for ev in (coord, vel):
        assert 176 <= len(ev["HS"]) <= 180
        assert 176 <= len(ev["TO"]) <= 180

    cc = ge.split_stance_swing(coord["HS"].tolist(), coord["TO"].tolist(), t)
    vv = ge.split_stance_swing(vel["HS"].tolist(), vel["TO"].tolist(), t)
    coord_stance = np.array([c["stance_pct"] for c in cc]).mean()
    vel_stance = np.array([c["stance_pct"] for c in vv]).mean()

    # Coordinate stance is high (~67 %); velocity stance is low (~50 %).
    assert 66.0 <= coord_stance <= 68.0
    assert 47.0 <= vel_stance <= 54.0
    # The velocity method shortens stance (does NOT sit between coord and 60 %).
    assert vel_stance < coord_stance


def test_ceb_gait_spatiotemporal_end_to_end():
    """The whole G2 chain through run_pipeline (so it reaches metrics / export):
    kinematic HS+TO -> stride/stance/swing time -> stance%/swing% + cadence.
    Validates against the known CEB numbers (stride 1.12 s, cadence ~107)."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d")
    dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB")
    model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    res = model.apply(dyn["markers"], label_map=lm)
    dyn["model_result"] = res
    dur = float(dyn["markers"]["time"][-1])
    n = int(round(dur * 1000.0)) + 1
    dyn["time"] = np.arange(n) / 1000.0
    dyn["fs"] = 1000.0
    md = dyn["markers"]["data"]

    p = Pipeline()
    p.add(DetectEventStep(input="gait:R_heel_ap", label="R_HS", method="peak",
                          params={"kind": "max", "min_distance_s": 0.6},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="gait:R_toe_ap", label="R_TO", method="peak",
                          params={"kind": "min", "min_distance_s": 0.6},
                          selector={"mode": "all"}))
    p.add(MetricStep(op="time_between_events", name="StrideTime",
                     segment=["R_HS", "R_HS"]))
    p.add(MetricStep(op="time_between_events", name="StanceTime",
                     segment=["R_HS", "R_TO"]))
    p.add(MetricStep(op="time_between_events", name="SwingTime",
                     segment=["R_TO", "R_HS"]))
    p.add(MetricStep(op="stance_pct", name="Stance%",
                     input="metric:StanceTime", input2="metric:StrideTime"))
    p.add(MetricStep(op="swing_pct", name="Swing%",
                     input="metric:SwingTime", input2="metric:StrideTime"))
    p.add(MetricStep(op="cadence_stride", name="Cadence", input="metric:StrideTime"))
    mv = run_pipeline(dyn, p, marker_disp=md, angle_result=res)["metric_values"]

    assert mv["StrideTime"][0] == pytest.approx(1.122, abs=0.02)
    assert 60.0 <= mv["Stance%"][0] <= 72.0
    assert mv["Stance%"][0] + mv["Swing%"][0] == pytest.approx(100.0, abs=0.5)
    assert mv["Cadence"][0] == pytest.approx(107.0, abs=2.0)   # verified CEB cadence


def test_real_detection_cache_token_stable():
    """Re-running detection with the same recipe hits the cache (same object);
    changing a detection param invalidates it (different frames)."""
    ds = _load(_DYNAMIC)
    p = Pipeline()
    p.add(ComputeStep(input="fp2:fz", name="afz2", method="abs"))
    p.add(DetectEventStep(input="afz2", label="ON", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    first = ec.compute_detected_events(ds, p)
    second = ec.compute_detected_events(ds, p)
    assert first is second                       # cache hit (same object)
    # Bump the threshold high enough that nothing crosses -> different result.
    p.detect_event_steps()[0].params["threshold"] = 1e9
    third = ec.compute_detected_events(ds, p)
    assert _frames(third, "ON") == []


def test_walk_treadmill_preset_end_to_end():
    """Seeding the treadmill walk preset on CEB yields a finite, physiological
    comprehensive metric set through run_pipeline."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d"); dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    from core.run import run_pipeline
    from core import presets
    from core.pipeline import Pipeline
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB"); model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    res = model.apply(dyn["markers"], label_map=lm); dyn["model_result"] = res
    dur = float(dyn["markers"]["time"][-1]); n = int(round(dur * 1000.0)) + 1
    dyn["time"] = np.arange(n) / 1000.0; dyn["fs"] = 1000.0
    md = dyn["markers"]["data"]
    p = Pipeline()
    for s in presets.build_preset("walk_treadmill", dyn):
        p.add(s)
    mv = run_pipeline(dyn, p, marker_disp=md, angle_result=res)["metric_values"]
    print("metric_values keys:", sorted(mv.keys()))
    print("R Stride time:", mv.get("R Stride time"))
    print("R Stance %:", mv.get("R Stance %"))
    print("R Gait speed:", mv.get("R Gait speed"))
    print("R Stride length:", mv.get("R Stride length"))
    print("R Knee ROM:", mv.get("R Knee ROM"))
    assert mv["R Stride time"][0] == pytest.approx(1.122, abs=0.03)
    assert 60.0 <= mv["R Stance %"][0] <= 72.0
    assert mv["R Gait speed"][0] == pytest.approx(1.15, abs=0.2)     # belt speed m/s
    assert mv["R Stride length"][0] == pytest.approx(1.28, abs=0.2)  # speed x time
    assert np.isfinite(mv["R Knee ROM"][0]) and mv["R Knee ROM"][0] > 0
