"""Pipeline dataflow executor (core.run) — the 3-catalog engine.

Pins the acceptance scenarios the redesign must support: artifacts produced by a
step are reusable as inputs to later steps (signal/event/metric reference),
min/max emit an event at the extremum, and subject metadata feeds normalization.
"""

import numpy as np
import pytest

from core.pipeline import (ComputeStep, DetectEventStep, MetricStep, Pipeline)
from core.run import run_pipeline


def _gait_dataset(n=400, fs=100.0):
    """A synthetic trial: a periodic Fz (for HS detection) + a Knee angle whose
    per-cycle range is exactly 40 deg, plus a single sharp vGRF peak."""
    t = np.arange(n) / fs
    # Fz: 4 clean bumps above/below a 20 N threshold -> HS at each rising edge.
    fz = 10 + 40 * (1 + np.sin(2 * np.pi * 4 * t / (n / fs)))  # 4 cycles
    knee = 20 + 20 * np.sin(2 * np.pi * 4 * t / (n / fs))      # 0..40 deg, ROM 40
    return {
        "time": t, "fs": fs,
        "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
        "fz": fz, "fp1:fz": fz.copy(),
        "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
        "n_force_plates": 1, "force_signal_keys": ["fp1:fz"],
        "model_result": {"angles": {"Knee": knee}, "time": t},
    }


def test_metric_whole_trial_scalar():
    ds = _gait_dataset()
    p = Pipeline()
    p.add(MetricStep(input="angle:Knee", op="max", name="Peak knee"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["Peak knee"]
    assert abs(val - 40.0) < 1e-6 and unit == "deg"


def test_min_max_emits_reusable_event_S2():
    """S2: max(fp1:fz) makes metric + event; value_at_event reads another signal
    at that frame."""
    ds = _gait_dataset()
    # Put a unique global max in Fz and a known Knee value at that frame.
    ds["fp1:fz"][123] = 9999.0
    ds["model_result"]["angles"]["Knee"][123] = 77.0
    p = Pipeline()
    p.add(MetricStep(input="fp1:fz", op="max", name="Peak vGRF"))
    p.add(MetricStep(input="angle:Knee", op="value_at_event", name="Knee@peak",
                     event="Peak vGRF"))
    out = run_pipeline(ds, p)
    assert out["metric_values"]["Peak vGRF"][0] == 9999.0
    assert out["events"]["Peak vGRF"][0] == 123
    assert out["metric_values"]["Knee@peak"][0] == 77.0


def test_per_cycle_aggregation_S3():
    """S3: range(angle:Knee) over HS->HS gives one value per stride + mean/SD."""
    ds = _gait_dataset()
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                          params={"threshold": 20.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="angle:Knee", op="range", name="Knee ROM",
                     segment=["HS", "HS"]))
    out = run_pipeline(ds, p)
    res = next(r for r in out["metrics"] if r["name"] == "Knee ROM")
    assert res["n"] >= 2                      # multiple strides found
    assert abs(res["mean"] - 40.0) < 2.0      # each stride ROM ~ 40 deg
    assert res["cycles"] is not None


def test_normalize_by_subject_mass_S1():
    """S1: ComputeStep normalizes fp1:fz by body weight (from subject mass)."""
    ds = _gait_dataset()
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", by="metric:bodyweight", name="fp1:fz_pctbw"))
    p.add(MetricStep(input="fp1:fz_pctbw", op="max", name="Peak %BW"))
    out = run_pipeline(ds, p, subject={"mass": 70.0})
    bw = 70.0 * 9.80665
    expected = float(np.max(ds["fp1:fz"]) / bw)
    assert abs(out["metric_values"]["Peak %BW"][0] - expected) < 1e-6


def test_detect_threshold_metric_reference_uses_subject():
    """A DetectEvent threshold can reference subject metrics (e.g. body weight):
    run_pipeline seeds mass/bodyweight before detection, so the step resolves."""
    ds = _gait_dataset()
    # Fz already swings 10..90 N (4 cycles). Detect HS where it rises past a
    # threshold = subject bodyweight scaled down so there ARE crossings: use a
    # tiny mass so bodyweight (mass*g) lands inside the 10..90 N band.
    mass = 5.0                          # bodyweight = 49.03 N (within 10..90 N)
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                          params={"threshold": "metric:bodyweight",
                                  "direction": "rising"},
                          selector={"mode": "all"}))
    out = run_pipeline(ds, p, subject={"mass": mass})
    # Same as a literal threshold at mass*9.80665 N.
    p2 = Pipeline()
    p2.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                           params={"threshold": mass * 9.80665,
                                   "direction": "rising"},
                           selector={"mode": "all"}))
    want = run_pipeline(ds, p2)
    assert list(out["events"]["HS"]) == list(want["events"]["HS"])
    assert len(out["events"]["HS"]) >= 1


def test_empty_pipeline_no_metrics():
    ds = _gait_dataset()
    out = run_pipeline(ds, Pipeline())
    assert out["metric_values"] == {} and out["metrics"] == []


def test_compute_derivative_then_metric_max_is_slope():
    """E2E: a linear force ramp -> ComputeStep derivative -> MetricStep max equals
    the ramp's slope (with the derived signal carrying a per-second unit)."""
    n, fs = 500, 200.0
    t = np.arange(n) / fs
    slope = 350.0                            # N/s
    fz = slope * t                           # ramp from 0
    ds = {"time": t, "fs": fs, "fp1:fz": fz, "fz": fz,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="dFz", method="derivative",
                      params={"order": 1}))
    p.add(MetricStep(input="dFz", op="max", name="Peak RFD"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["Peak RFD"]
    assert abs(val - slope) < 1e-3
    assert unit == "N/s"


def test_compute_integral_then_metric_max_is_area():
    """E2E: cumulative integral of a constant force -> max of the running area =
    force * total span (impulse), and the integrated signal's unit is N*s."""
    n, fs = 400, 100.0
    t = np.arange(n) / fs
    fz = np.full(n, 50.0)                     # constant 50 N
    ds = {"time": t, "fs": fs, "fp1:fz": fz, "fz": fz,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="impulse", method="integral",
                      params={"sign": "all"}))
    p.add(MetricStep(input="impulse", op="max", name="Total impulse"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["Total impulse"]
    assert abs(val - 50.0 * t[-1]) < 1e-6
    assert unit == "N*s"


def test_compute_abs_rectifies_then_integral_is_positive():
    """E2E: raw (down-negative) Fz -> ComputeStep abs -> |Fz| is positive and its
    cumulative integral (impulse) ends positive — the user's sign tool replacing
    any global flip. Unit is preserved (abs of N stays N)."""
    n, fs = 400, 100.0
    t = np.arange(n) / fs
    fz = np.full(n, -50.0)                    # raw C3D: subject pushes down (-)
    ds = {"time": t, "fs": fs, "fp1:fz": fz, "fz": fz,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fz", name="absFz", method="abs"))
    p.add(ComputeStep(input="absFz", name="impulse", method="integral",
                      params={"sign": "all"}))
    p.add(MetricStep(input="impulse", op="max", name="Total impulse"))
    out = run_pipeline(ds, p)
    # |−50| = 50 everywhere -> impulse = 50 * span > 0
    val, unit = out["metric_values"]["Total impulse"]
    assert val > 0
    assert abs(val - 50.0 * t[-1]) < 1e-6
    assert unit == "N*s"     # N (abs preserves) -> N*s (integral)


def test_metric_integral_op_needs_time_window():
    """The scalar 'integral' op (needs_time) gets the window time axis sliced from
    ctx.time and returns the trapezoidal area over the window = impulse (N*s)."""
    n, fs = 300, 100.0
    t = np.arange(n) / fs
    fz = np.full(n, 20.0)
    ds = {"time": t, "fs": fs, "fp1:fz": fz, "fz": fz,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(MetricStep(input="fp1:fz", op="integral", name="vGRF impulse"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["vGRF impulse"]
    assert abs(val - 20.0 * t[-1]) < 1e-6
    assert unit == "N*s"


def test_named_op_peak_angular_velocity_e2e():
    """E2E: a MetricStep with op=peak_angular_velocity reads a joint angle,
    differentiates internally, and reports A*w (deg/s) with the right unit and an
    extremum event frame. theta = A*sin(w t) -> peak |omega| = A*w."""
    n, fs = 4000, 1000.0
    t = np.arange(n) / fs
    A, f = 30.0, 1.5
    w = 2 * np.pi * f
    knee = A * np.sin(w * t)
    ds = {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": [],
          "model_result": {"angles": {"Knee": knee}, "time": t}}
    p = Pipeline()
    p.add(MetricStep(input="angle:Knee", op="peak_angular_velocity",
                     name="Peak knee angular velocity"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["Peak knee angular velocity"]
    assert abs(val) == pytest.approx(A * w, rel=1e-2)
    assert unit == "deg/s"


def test_named_op_braking_propulsive_impulse_e2e():
    """E2E: braking/propulsive impulse ops integrate the neg/pos part of an AP
    force over the trial; together they equal the total impulse (N*s)."""
    n, fs = 600, 1000.0
    t = np.arange(n) / fs
    fy = np.where(t < 0.3, -100.0, 150.0)      # brake then propel
    ds = {"time": t, "fs": fs, "fp1:fy": fy, "fy": fy,
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fy"]}
    p = Pipeline()
    p.add(MetricStep(input="fp1:fy", op="braking_impulse", name="Braking"))
    p.add(MetricStep(input="fp1:fy", op="propulsive_impulse", name="Propulsive"))
    out = run_pipeline(ds, p)
    brake, bu = out["metric_values"]["Braking"]
    prop, pu = out["metric_values"]["Propulsive"]
    assert brake == pytest.approx(-100.0 * 0.3, rel=1e-2) and brake <= 0
    assert prop == pytest.approx(150.0 * 0.3, rel=1e-2) and prop >= 0
    assert bu == "N*s" and pu == "N*s"


def test_compute_magnitude_resultant_force():
    """E2E: magnitude(fx, fy, fz) makes a resultant signal; its max equals the
    Euclidean resultant of the per-axis constants (3,4,12 -> 13)."""
    n, fs = 100, 100.0
    t = np.arange(n) / fs
    ds = {"time": t, "fs": fs,
          "fp1:fx": np.full(n, 3.0), "fp1:fy": np.full(n, 4.0),
          "fp1:fz": np.full(n, 12.0), "fz": np.full(n, 12.0),
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(ComputeStep(input="fp1:fx", inputs=["fp1:fy", "fp1:fz"],
                      name="Fres", method="magnitude"))
    p.add(MetricStep(input="Fres", op="max", name="Peak resultant GRF"))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["Peak resultant GRF"]
    assert abs(val - 13.0) < 1e-9
    assert unit == "N"


def test_cop_op_matches_compute_metrics():
    """A COP composite op (ellipse area) equals the legacy compute_metrics."""
    from core.metrics import compute_metrics
    n = 200
    rng = np.random.default_rng(0)
    ap = rng.normal(0, 5, n)
    ml = rng.normal(0, 3, n)
    ds = {"time": np.arange(n) / 100.0, "fs": 100.0,
          "fp1:cop_ap": ap, "fp1:cop_ml": ml, "fp1:fz": np.ones(n),
          "cop_ap": ap, "cop_ml": ml, "fz": np.ones(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(MetricStep(input="fp1:cop", op="ellipse_area", name="Sway area"))
    out = run_pipeline(ds, p)
    want = compute_metrics(ap, ml, 100.0, ["95% Ellipse area"])["95% Ellipse area"]
    assert abs(out["metric_values"]["Sway area"][0] - want[0]) < 1e-6


# --- Round B2: spatiotemporal / jump / symmetry-variability ---------------

def _stance_dataset(fs=100.0):
    """A synthetic gait Fz with KNOWN edges: foot on the ground (Fz=500 N) during
    [10,40), [60,90), [110,140) and off (Fz=0) otherwise. Rising edges (HS) at
    frames 10, 60, 110; falling edges (TO) at 40, 90, 140. So stance = 0.30 s,
    swing = 0.20 s, stride (HS->HS) = 0.50 s at fs=100."""
    n = 160
    t = np.arange(n) / fs
    fz = np.zeros(n)
    for lo, hi in [(10, 40), (60, 90), (110, 140)]:
        fz[lo:hi] = 500.0
    return {"time": t, "fs": fs, "fz": fz, "fp1:fz": fz.copy(),
            "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
            "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
            "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}


def _hs_to_pipeline():
    """HS at every rising edge, TO at every falling edge of Fz (threshold 250 N)."""
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                          params={"threshold": 250.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="fp1:fz", label="TO", method="threshold",
                          params={"threshold": 250.0, "direction": "falling"},
                          selector={"mode": "all"}))
    return p


def test_stride_and_stance_time_between_events():
    """time_between_events: stride (HS->HS) = 0.50 s, stance (HS->TO) = 0.30 s,
    swing (TO->HS) = 0.20 s, averaged over cycles. frames_between_events counts
    frames (stride = 50 frames)."""
    ds = _stance_dataset()
    p = _hs_to_pipeline()
    p.add(MetricStep(op="time_between_events", name="Stride time", segment=["HS", "HS"]))
    p.add(MetricStep(op="time_between_events", name="Stance time", segment=["HS", "TO"]))
    p.add(MetricStep(op="time_between_events", name="Swing time", segment=["TO", "HS"]))
    p.add(MetricStep(op="frames_between_events", name="Stride frames", segment=["HS", "HS"]))
    out = run_pipeline(ds, p)["metric_values"]
    assert out["Stride time"][0] == pytest.approx(0.50, abs=1e-9)
    assert out["Stride time"][1] == "s"
    assert out["Stance time"][0] == pytest.approx(0.30, abs=1e-9)
    assert out["Swing time"][0] == pytest.approx(0.20, abs=1e-9)
    assert out["Stride frames"][0] == pytest.approx(50.0)


def test_cadence_stance_swing_pct_references():
    """cadence = 120/stride (full-cycle convention); stance% = stance/stride*100
    = 60%, swing% = 40%."""
    ds = _stance_dataset()
    p = _hs_to_pipeline()
    p.add(MetricStep(op="time_between_events", name="Stride time", segment=["HS", "HS"]))
    p.add(MetricStep(op="time_between_events", name="Stance time", segment=["HS", "TO"]))
    p.add(MetricStep(op="time_between_events", name="Swing time", segment=["TO", "HS"]))
    p.add(MetricStep(op="cadence_stride", name="Cadence", input="metric:Stride time"))
    p.add(MetricStep(op="stance_pct", name="Stance %",
                     input="metric:Stance time", input2="metric:Stride time"))
    p.add(MetricStep(op="swing_pct", name="Swing %",
                     input="metric:Swing time", input2="metric:Stride time"))
    out = run_pipeline(ds, p)["metric_values"]
    assert out["Cadence"][0] == pytest.approx(120.0 / 0.50)   # 240 steps/min
    assert out["Cadence"][1] == "steps/min"
    assert out["Stance %"][0] == pytest.approx(60.0)
    assert out["Swing %"][0] == pytest.approx(40.0)


def test_jump_height_flight_time():
    """jump_height_flight_time: a known flight time t=0.50 s (TO->landing) gives
    h = g t^2/8 = 9.80665*0.25/8 = 0.30646 m."""
    from core.metrics import G
    ds = _stance_dataset()
    # Reuse HS as 'landing' and TO as 'takeoff': TO@40 -> next HS@60 = 0.20 s flight.
    p = _hs_to_pipeline()
    p.add(MetricStep(op="jump_height_flight_time", name="Jump height",
                     segment=["TO", "HS"]))   # TO->HS = 0.20 s flight
    out = run_pipeline(ds, p)["metric_values"]
    assert out["Jump height"][0] == pytest.approx(G * 0.20 ** 2 / 8.0)
    assert out["Jump height"][1] == "m"


def test_jump_height_impulse_and_takeoff_velocity():
    """Impulse-momentum jump: a body-weight-balanced quiet phase then a propulsion
    pulse. With mass m and a net impulse J over the window, v=J/m, h=v^2/2g."""
    from core.metrics import G
    n, fs = 1000, 1000.0
    t = np.arange(n) / fs
    mass = 70.0
    bw = mass * G
    # Quiet stand at body weight, then a 0.10 s push at bw + 700 N (net +700 N).
    fz = np.full(n, bw)
    fz[400:500] = bw + 700.0          # net force 700 N for 0.10 s -> J = 70 N*s
    ds = {"time": t, "fs": fs, "fz": fz, "fp1:fz": fz.copy(),
          "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    # A frame event at 0 (movement onset) and at 1000-1 region (takeoff) so the
    # window spans the whole trial -> net impulse = the 700 N * 0.10 s pulse.
    p = Pipeline()
    p.add(DetectEventStep(label="ON", method="frame", params={"frame": 0}))
    p.add(DetectEventStep(label="OFF", method="frame", params={"frame": n - 1}))
    p.add(MetricStep(op="jump_height_impulse", input="fp1:fz", name="Jump height",
                     segment=["ON", "OFF"]))
    p.add(MetricStep(op="takeoff_velocity", input="fp1:fz", name="Takeoff v",
                     segment=["ON", "OFF"]))
    out = run_pipeline(ds, p, subject={"mass": mass})["metric_values"]
    # J = 700 N * 0.10 s = 70 N*s; v = 70/70 = 1.0 m/s; h = 1/(2g).
    assert out["Takeoff v"][0] == pytest.approx(1.0, rel=1e-3)
    assert out["Takeoff v"][1] == "m/s"
    assert out["Jump height"][0] == pytest.approx(1.0 / (2 * G), rel=1e-3)
    assert out["Jump height"][1] == "m"


# -- #4 robustness: _run_normalize narrows its except (surface genuine bugs) --

class _SignalRaisingCtx:
    """A minimal RunContext stand-in whose ``signal`` raises a chosen error.

    ``_run_normalize`` resolves its input via ``ctx.signal`` before any event
    work, so this is enough to exercise the except clause in isolation.
    """

    def __init__(self, exc):
        self.time = np.arange(10) / 100.0
        self._exc = exc

    def signal(self, key):
        raise self._exc

    def event(self, label):
        return None


def test_run_normalize_surfaces_unexpected_error():
    """A genuine bug during signal resolution (e.g. a TypeError) must propagate,
    not be swallowed into a silent None by a broad ``except Exception``."""
    from core.run import _run_normalize
    from core.pipeline import NormalizeStep
    step = NormalizeStep(input="x", name="N", mode="trial")
    with pytest.raises(TypeError):
        _run_normalize(_SignalRaisingCtx(TypeError("genuine bug")), step)


def test_run_normalize_degrades_on_unresolvable_signal():
    """An expected data failure (unresolvable signal -> ValueError from the
    Workspace) still degrades gracefully to None."""
    from core.run import _run_normalize
    from core.pipeline import NormalizeStep
    step = NormalizeStep(input="x", name="N", mode="trial")
    ctx = _SignalRaisingCtx(ValueError("channel unavailable: x"))
    assert _run_normalize(ctx, step) is None


def test_rsi_reference():
    """RSI = jump height / contact time. h=0.3 m, contact=0.2 s -> RSI=1.5 m/s."""
    ds = _stance_dataset()
    p = _hs_to_pipeline()
    # contact time = HS->TO = 0.30 s here; build an explicit height metric via a
    # frame event window is overkill — reference a contact-time metric + a literal
    # height computed from flight time.
    p.add(MetricStep(op="time_between_events", name="Contact time", segment=["HS", "TO"]))
    p.add(MetricStep(op="jump_height_flight_time", name="Jump height", segment=["TO", "HS"]))
    p.add(MetricStep(op="rsi", name="RSI",
                     input="metric:Jump height", input2="metric:Contact time"))
    out = run_pipeline(ds, p)["metric_values"]
    h = out["Jump height"][0]
    c = out["Contact time"][0]
    assert out["RSI"][0] == pytest.approx(h / c)
    assert out["RSI"][1] == "m/s"


def test_symmetry_index_ratio_and_cv():
    """symmetry_index of two equal metrics = 0%; ratio = 1.0; CV of a per-cycle
    array with known mean/SD matches SD/mean*100."""
    from core.metrics import symmetry_index, symmetry_ratio, coefficient_of_variation
    # Pure-function pins (the engine math) — direct, scale-free.
    assert symmetry_index(0.5, 0.5) == pytest.approx(0.0)
    assert symmetry_index(0.6, 0.4) == pytest.approx(abs(0.6 - 0.4) / 0.5 * 100)  # 40%
    assert symmetry_ratio(0.6, 0.4) == pytest.approx(1.5)
    vals = np.array([0.48, 0.50, 0.52, 0.50])
    want = np.std(vals, ddof=1) / abs(np.mean(vals)) * 100
    assert coefficient_of_variation(vals) == pytest.approx(want)

    # E2E: CV through the pipeline reads the per-cycle stride-time array.
    ds = _stance_dataset()
    p = _hs_to_pipeline()
    p.add(MetricStep(op="time_between_events", name="Stride time", segment=["HS", "HS"]))
    p.add(MetricStep(op="cv", name="Stride CV", input="metric:Stride time"))
    out = run_pipeline(ds, p)["metric_values"]
    # All strides are exactly 0.50 s -> CV = 0%.
    assert out["Stride CV"][0] == pytest.approx(0.0, abs=1e-9)
    assert out["Stride CV"][1] == "%"


def test_metric_values_carries_every_op_category():
    """metric_values must collect results from ALL op categories in one run —
    scalar(signal), cop, event, jump, and reference (metric-derived). One
    pipeline mixes one op per category; every one must land in metric_values with
    the right unit. Guards against a category being silently dropped by the
    single-pass executor / glue."""
    from core.metrics import OP_INFO, G
    n, fs = 1000, 1000.0
    t = np.arange(n) / fs
    mass = 70.0
    bw = mass * G
    fz = np.full(n, bw)
    fz[400:500] = bw + 700.0                 # net +700 N for 0.10 s -> J = 70 N*s
    rng = np.random.default_rng(0)
    ap = rng.normal(0, 5, n)
    ml = rng.normal(0, 3, n)
    ds = {"time": t, "fs": fs, "fz": fz, "fp1:fz": fz.copy(),
          "cop_ap": ap, "cop_ml": ml, "fp1:cop_ap": ap, "fp1:cop_ml": ml,
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    # frame events spanning the trial, so the jump window has a real segment.
    p.add(DetectEventStep(label="ON", method="frame", params={"frame": 0}))
    p.add(DetectEventStep(label="OFF", method="frame", params={"frame": n - 1}))
    p.add(MetricStep(input="fp1:fz", op="max", name="ScalarM"))              # scalar/signal
    p.add(MetricStep(input="fp1:cop", op="ellipse_area", name="CopM"))       # cop
    p.add(MetricStep(op="time_between_events", name="EventM",
                     segment=["ON", "OFF"]))                                 # event
    p.add(MetricStep(input="fp1:fz", op="jump_height_impulse", name="JumpM",
                     segment=["ON", "OFF"]))                                 # jump
    p.add(MetricStep(op="cadence", name="RefM", input="metric:EventM"))      # reference
    out = run_pipeline(ds, p, subject={"mass": mass})
    mv = out["metric_values"]
    # every category's result is present
    for name in ("ScalarM", "CopM", "EventM", "JumpM", "RefM"):
        assert name in mv, f"{name} missing from metric_values"
    # spot-check the categories resolved to their expected category in OP_INFO
    assert OP_INFO["max"]["category"] == "scalar"
    assert OP_INFO["ellipse_area"]["category"] == "cop"
    assert OP_INFO["time_between_events"]["category"] == "event"
    assert OP_INFO["jump_height_impulse"]["category"] == "jump"
    assert OP_INFO["cadence"]["category"] == "reference"
    # units sane (non-empty) for each
    assert mv["ScalarM"][1] == "N"
    assert mv["CopM"][1] == "mm^2"
    assert mv["EventM"][1] == "s"
    assert mv["JumpM"][1] == "m"
    assert mv["RefM"][1] == "steps/min"
    # the reference op actually consumed the event metric (60 / 0.999 s)
    assert mv["RefM"][0] == pytest.approx(60.0 / mv["EventM"][0], rel=1e-6)


def test_symmetry_index_e2e_left_right_metrics():
    """E2E symmetry index referencing two limb metrics (L/R wired explicitly;
    auto L/R assignment is Phase E). Equal peaks -> SI = 0%."""
    ds = _stance_dataset()
    p = Pipeline()
    p.add(MetricStep(input="fp1:fz", op="max", name="Peak vGRF L"))
    p.add(MetricStep(input="fp1:fz", op="max", name="Peak vGRF R"))
    p.add(MetricStep(op="symmetry_index", name="vGRF SI",
                     input="metric:Peak vGRF L", input2="metric:Peak vGRF R"))
    out = run_pipeline(ds, p)["metric_values"]
    assert out["vGRF SI"][0] == pytest.approx(0.0)
    assert out["vGRF SI"][1] == "%"


def test_displacement_between_events_per_cycle():
    # 'pos' increases by 10 each frame; HS detected at frames 0,5,10 via 'trig'.
    # Each HS->HS stride spans 5 frames -> displacement 50 per cycle.
    n = 12
    ds = {"time": np.arange(n) / 100.0, "fs": 100.0,
          "pos": np.arange(n, dtype=float) * 10.0,
          "trig": np.array([1,0,0,0,0,1,0,0,0,0,1,0], dtype=float)}
    p = Pipeline()
    p.add(DetectEventStep(input="trig", label="HS", method="threshold",
                          params={"threshold": 0.5, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="pos", op="displacement_between_events",
                     name="StrideLen", segment=["HS", "HS"]))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["StrideLen"]
    assert val == pytest.approx(50.0)


def test_reference_ops_are_per_cycle_not_mean_only():
    # stance_pct / cadence_stride must carry a PER-CYCLE array (raw data), not a
    # single scalar derived from the means. HS at 1,11,25; TO at 7,19 ->
    # 2 strides: stride 0.10/0.14 s, stance 0.06/0.08 s -> stance% 60 / 57.142857.
    n = 30
    hs = np.zeros(n); hs[[1, 11, 25]] = 1.0
    to = np.zeros(n); to[[7, 19]] = 1.0
    ds = {"time": np.arange(n) / 100.0, "fs": 100.0, "hs": hs, "to": to}
    p = Pipeline()
    p.add(DetectEventStep(input="hs", label="HS", method="threshold",
                          params={"threshold": 0.5, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="to", label="TO", method="threshold",
                          params={"threshold": 0.5, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(MetricStep(op="time_between_events", name="Stride", segment=["HS", "HS"]))
    p.add(MetricStep(op="time_between_events", name="Stance", segment=["HS", "TO"]))
    p.add(MetricStep(op="stance_pct", name="Stance%",
                     input="metric:Stance", input2="metric:Stride"))
    p.add(MetricStep(op="cadence_stride", name="Cadence", input="metric:Stride"))
    out = run_pipeline(ds, p)
    m = next(x for x in out["metrics"] if x["name"] == "Stance%")
    assert m["cycles"] is not None
    cyc = np.asarray(m["cycles"], dtype=float)
    assert len(cyc) == 2
    np.testing.assert_allclose(sorted(cyc), [57.142857, 60.0], rtol=1e-4)
    assert m["mean"] == pytest.approx(float(np.mean(cyc)))
    assert m["n"] == 2
    # cadence per stride: 120/0.10=1200, 120/0.14=857.14 -> per-cycle array of 2.
    c = next(x for x in out["metrics"] if x["name"] == "Cadence")
    assert c["cycles"] is not None and len(c["cycles"]) == 2


# --- Regression: value_at_event must respect the per-cycle window -----------
def test_value_at_event_reads_event_inside_each_cycle():
    """REGRESSION (per-cycle value_at_event): with a segment [HS, TO], a
    ``value_at_event`` of event TO must read the input at the TO frame INSIDE each
    cycle, not always the first global TO instance.

    Before the fix every cycle reported sig[first_TO]; now cycle k reports the
    TO that falls within that cycle's [HS_k, TO_k] window."""
    n, fs = 400, 100.0
    t = np.arange(n) / fs
    # Periodic Fz crossing 20 N -> HS (rising) / TO (falling) edges.
    fz = 10 + 40 * (1 + np.sin(2 * np.pi * 4 * t / (n / fs)))
    knee = t * 100.0                       # strictly increasing -> distinct per TO
    ds = {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fz": fz, "fp1:fz": fz.copy(),
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"],
          "model_result": {"angles": {"Knee": knee}, "time": t}}
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                          params={"threshold": 20.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(DetectEventStep(input="fp1:fz", label="TO", method="threshold",
                          params={"threshold": 20.0, "direction": "falling"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="angle:Knee", op="value_at_event", name="Knee@TO",
                     event="TO", segment=["HS", "TO"]))
    out = run_pipeline(ds, p)
    res = next(r for r in out["metrics"] if r["name"] == "Knee@TO")
    hs = np.asarray(out["events"]["HS"], dtype=int)
    to = np.asarray(out["events"]["TO"], dtype=int)
    # Expected: for each HS, the next TO strictly after it -> knee at that TO.
    expected = []
    for h in hs:
        after = to[to > h]
        if after.size:
            expected.append(knee[int(after[0])])
    cyc = np.asarray(res["cycles"], dtype=float)
    assert len(cyc) == len(expected) >= 2
    np.testing.assert_allclose(cyc, expected, rtol=1e-9)
    # The first global TO (before any HS) must NOT contaminate every cycle.
    assert len(set(np.round(cyc, 6))) == len(cyc)


def test_value_at_event_whole_trial_keeps_first_instance():
    """Without a segment (whole trial), value_at_event still reads the FIRST
    instance — the legacy single-value behaviour is preserved."""
    n, fs = 200, 100.0
    t = np.arange(n) / fs
    fz = np.zeros(n); fz[[30, 80, 130]] = 100.0     # 3 spikes
    sig = np.arange(n, dtype=float) * 2.0
    ds = {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
          "fz": fz, "fp1:fz": fz.copy(), "extra": sig,
          "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
          "n_force_plates": 1, "force_signal_keys": ["fp1:fz"]}
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="Spike", method="threshold",
                          params={"threshold": 50.0, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="extra", op="value_at_event", name="V", event="Spike"))
    out = run_pipeline(ds, p)
    # first spike rises at frame 30 -> sig[30] = 60.0
    assert out["metric_values"]["V"][0] == pytest.approx(60.0)
