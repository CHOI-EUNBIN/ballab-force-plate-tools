"""Metric computation failure-feedback: every MetricStep result carries a
``status`` (ok/partial/unavailable) + ``reason`` code + English ``message``
explaining WHY a value is NaN/partial. Numeric fields are unchanged (additive).

These drive :func:`core.metrics_compute.compute_metric_step` directly through a
hand-built :class:`core.run.RunContext` so each case (no signal / not COP / no
event / no cycles / unknown op / no mass / no reference / divide-by-zero / window
too short / window all NaN / 1-cycle CV / whole-trial fallback / partial cycles /
ok) is pinned in isolation.
"""

import numpy as np

import core.diagnostics as diag
from core.metrics_compute import compute_metric_step
from core.pipeline import Pipeline, MetricStep, DetectEventStep
from core.run import RunContext, run_pipeline


class _NoSignalWS:
    """Workspace stub: every series lookup fails (so only ctx.add_signal'd keys
    resolve) — mirrors :meth:`core.signals.Workspace.series` raising ValueError."""

    def series(self, key):
        raise ValueError(f"channel unavailable: {key}")


def _ctx(n=12, fs=100.0):
    t = np.arange(n) / fs
    return RunContext(_NoSignalWS(), t, fs)


# -- UNAVAILABLE: data missing ---------------------------------------------

def test_missing_input_signal_is_unavailable_no_signal():
    ctx = _ctx()
    step = MetricStep(input="angle:Missing", op="max", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_SIGNAL
    assert "angle:Missing" in res["message"]
    assert not np.isfinite(res["value"])


def test_cop_op_on_non_cop_input_is_unavailable_not_cop():
    ctx = _ctx()
    ctx.add_signal("fp1:fz", np.ones(12))
    step = MetricStep(input="fp1:fz", op="ellipse_area", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NOT_COP


def test_value_at_event_with_no_instances_is_unavailable():
    ctx = _ctx()
    ctx.add_signal("angle:Knee", np.linspace(0, 10, 12))
    step = MetricStep(input="angle:Knee", op="value_at_event", name="m", event="HS")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_EVENT_INSTANCES
    assert "HS" in res["message"]


def test_event_op_segment_with_zero_cycles_is_unavailable_no_cycles():
    ctx = _ctx()
    step = MetricStep(op="time_between_events", name="m", segment=["HS", "HS"])
    res = compute_metric_step(ctx, step)            # HS never detected -> 0 cycles
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_CYCLES


# -- UNAVAILABLE: cannot compute -------------------------------------------

def test_event_op_without_segment_is_unavailable_no_segment():
    ctx = _ctx()
    step = MetricStep(op="time_between_events", name="m")   # no segment authored
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_SEGMENT


def test_unknown_op_is_unavailable_unknown_op():
    ctx = _ctx()
    ctx.add_signal("x", np.ones(12))
    step = MetricStep(input="x", op="frobnicate", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.UNKNOWN_OP
    assert "frobnicate" in res["message"]


def test_jump_op_without_mass_is_unavailable_no_mass():
    ctx = _ctx()
    ctx.add_signal("fp1:fz", np.ones(12) * 800.0)
    step = MetricStep(input="fp1:fz", op="jump_height_impulse", name="m")
    res = compute_metric_step(ctx, step)            # no mass metric seeded
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_MASS


def test_reference_op_missing_inputs_is_unavailable_no_reference():
    ctx = _ctx()
    step = MetricStep(op="symmetry_index", name="m",
                      input="metric:Left", input2="metric:Right")
    res = compute_metric_step(ctx, step)            # neither metric exists
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_REFERENCE


def test_quotient_by_zero_is_unavailable_divide_by_zero():
    ctx = _ctx()
    ctx.add_metric("A", 5.0)
    ctx.add_metric("B", 0.0)
    step = MetricStep(op="quotient", name="m",
                      input="metric:A", input2="metric:B")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.DIVIDE_BY_ZERO


# -- UNAVAILABLE: insufficient data ----------------------------------------

def test_window_all_nan_is_unavailable_window_all_nan():
    ctx = _ctx()
    ctx.add_signal("angle:Knee", np.full(12, np.nan))
    step = MetricStep(input="angle:Knee", op="mean", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.WINDOW_ALL_NAN


def test_window_too_short_for_derivative_is_unavailable():
    ctx = _ctx(n=1)
    ctx.add_signal("angle:Knee", np.array([5.0]))
    step = MetricStep(input="angle:Knee", op="peak_angular_velocity", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.WINDOW_TOO_SHORT


def test_cv_with_one_cycle_is_unavailable_needs_two_cycles():
    ctx = _ctx()
    ctx.add_metric_cycles("Stride", np.array([0.83]))   # single cycle
    step = MetricStep(op="cv", name="m", input="metric:Stride")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NEEDS_TWO_CYCLES


# -- PARTIAL ---------------------------------------------------------------

def test_scalar_op_no_cycles_falls_back_to_whole_trial_partial():
    ctx = _ctx()
    ctx.add_signal("angle:Knee", np.linspace(0, 40, 12))   # whole-trial range 40
    step = MetricStep(input="angle:Knee", op="range", name="m",
                      segment=["HS", "HS"])                # no HS -> fallback
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.PARTIAL
    assert res["reason"] == diag.WHOLE_TRIAL_FALLBACK
    assert abs(res["value"] - 40.0) < 1e-6                 # value still computed


def test_some_cycles_nan_is_partial_with_n_of_m():
    ctx = _ctx()
    knee = np.linspace(0, 40, 12)
    knee[4:9] = np.nan                # middle cycle (window 4..8) entirely missing
    ctx.add_signal("angle:Knee", knee)
    ctx.add_event("HS", np.array([0, 4, 8, 11]))           # 3 cycles
    step = MetricStep(input="angle:Knee", op="range", name="m",
                      segment=["HS", "HS"])
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.PARTIAL
    assert res["reason"] == diag.PARTIAL_CYCLES
    assert "2" in res["message"] and "3" in res["message"]
    assert np.isfinite(res["value"])


# -- OK --------------------------------------------------------------------

def test_clean_scalar_metric_is_ok_with_empty_message():
    ctx = _ctx()
    ctx.add_signal("angle:Knee", np.linspace(0, 40, 12))
    step = MetricStep(input="angle:Knee", op="range", name="m")
    res = compute_metric_step(ctx, step)
    assert res["status"] == diag.OK
    assert res["reason"] == ""
    assert res["message"] == ""
    assert abs(res["value"] - 40.0) < 1e-6


# -- integration: a missing signal must NOT crash the whole run ------------

def test_run_pipeline_with_missing_signal_does_not_crash():
    ds = {
        "time": np.arange(20) / 100.0, "fs": 100.0,
        "cop_ap": np.zeros(20), "cop_ml": np.zeros(20),
    }
    p = Pipeline()
    p.add(MetricStep(input="angle:Missing", op="max", name="Bad"))
    out = run_pipeline(ds, p)                               # must not raise
    res = next(r for r in out["metrics"] if r["name"] == "Bad")
    assert res["status"] == diag.UNAVAILABLE
    assert res["reason"] == diag.NO_SIGNAL
