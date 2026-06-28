"""Task #7 — Total double-support % (a clinical single-value gait metric).

A normal gait cycle has TWO double-support phases (both feet on the ground):
R_HS -> L_TO and L_HS -> R_TO. The clinical standard reports their SUM as a
fraction of the stride (gait cycle), normally ~20% of the cycle (~10% each).

These tests pin:
  * the pure-math reference ops that build it (binary ``add``; ``double_support_pct``
    = phase / stride * 100), with analytic answers;
  * the end-to-end pipeline value on a synthetic gait trial with known event
    timings (so the computed % equals the hand-computed %);
  * the edge cases (no cycles / divide-by-zero) returning the right diagnostics
    status + reason;
  * the walk presets auto-seeding the metric.
"""

import numpy as np
import pytest

from core.metrics import REFERENCE_OPS, OP_INFO
from core.pipeline import DetectEventStep, MetricStep, Pipeline
from core.run import run_pipeline
from core import diagnostics, presets


# --- pure math --------------------------------------------------------------

def test_add_reference_op_sums_two_values():
    fn, n_inputs, unit = REFERENCE_OPS["add"]
    assert n_inputs == 2
    assert fn(0.10, 0.12) == pytest.approx(0.22)


def test_add_reference_op_nan_safe():
    fn = REFERENCE_OPS["add"][0]
    assert np.isnan(fn(float("nan"), 0.1))
    assert np.isnan(fn(0.1, float("inf")))


def test_double_support_pct_is_phase_over_stride():
    """double_support_pct(total_ds_time, stride_time) = ds/stride*100."""
    fn, n_inputs, unit = REFERENCE_OPS["double_support_pct"]
    assert n_inputs == 2 and unit == "%"
    # 0.2 s total DS over a 1.0 s stride -> 20 %.
    assert fn(0.20, 1.00) == pytest.approx(20.0)


def test_double_support_pct_divide_by_zero():
    fn = REFERENCE_OPS["double_support_pct"][0]
    assert np.isnan(fn(0.2, 0.0))


def test_double_support_pct_in_op_info_as_metric_reference():
    info = OP_INFO["double_support_pct"]
    assert info["category"] == "reference"
    assert info["input"] == "metric"
    assert info["n_inputs"] == 2


# --- end-to-end pipeline ----------------------------------------------------

#: Event plan (fs=100 Hz, so 1 frame = 0.01 s), two clean strides. Each label
#: gets its own synthetic signal with sharp peaks at exactly these frames, so a
#: peak detector with mode=all fires one event per frame (a single detect step
#: per label, unlike frame-method steps which carry only one instance each):
#:   R_HS: 50, 150   (stride = 100 frames = 1.00 s)
#:   L_TO: 60, 160   (DS_R = R_HS->L_TO = 10 frames = 0.10 s)
#:   L_HS: 100, 200  (mid-cycle)
#:   R_TO: 110, 210  (DS_L = L_HS->R_TO = 10 frames = 0.10 s)
#: Total DS per stride = 0.20 s; stride = 1.00 s -> Total DS% = 20 %.
_EVENT_FRAMES = {"R_HS": [50, 150], "L_TO": [60, 160],
                 "L_HS": [100, 200], "R_TO": [110, 210]}


def _ds_with_events(n=300, fs=100.0):
    """Synthetic trial: one impulse signal per event label peaking at its frames.

    Total DS% is built from event timings only, so the signals just need clean,
    well-separated peaks at the planned frames for a peak detector to find.
    """
    t = np.arange(n) / fs
    ds = {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n)}
    for label, frames in _EVENT_FRAMES.items():
        sig = np.zeros(n)
        for fr in frames:
            sig[fr] = 1.0
        ds[f"sig_{label}"] = sig
    return ds


def _plant_event(p, label):
    """A single peak detect step (mode=all) on this label's impulse signal."""
    p.add(DetectEventStep(input=f"sig_{label}", label=label, method="peak",
                          params={"kind": "max", "min_distance_s": 0.3},
                          selector={"mode": "all"}))


def _ds_pipeline():
    """Build the Total double-support % sub-pipeline (events + metrics)."""
    p = Pipeline()
    for label in _EVENT_FRAMES:
        _plant_event(p, label)
    p.add(MetricStep(op="time_between_events", name="Double support R",
                     segment=["R_HS", "L_TO"]))
    p.add(MetricStep(op="time_between_events", name="Double support L",
                     segment=["L_HS", "R_TO"]))
    p.add(MetricStep(op="time_between_events", name="R Stride time",
                     segment=["R_HS", "R_HS"]))
    p.add(MetricStep(op="add", name="Total double support time",
                     input="metric:Double support R",
                     input2="metric:Double support L"))
    p.add(MetricStep(op="double_support_pct", name="Total double support %",
                     input="metric:Total double support time",
                     input2="metric:R Stride time"))
    return p


def test_total_double_support_pct_end_to_end():
    out = run_pipeline(_ds_with_events(), _ds_pipeline())
    vals = out["metric_values"]
    assert vals["Double support R"][0] == pytest.approx(0.10)
    assert vals["Double support L"][0] == pytest.approx(0.10)
    assert vals["Total double support time"][0] == pytest.approx(0.20)
    val, unit = vals["Total double support %"]
    assert val == pytest.approx(20.0)
    assert unit == "%"


def test_total_double_support_pct_status_ok():
    out = run_pipeline(_ds_with_events(), _ds_pipeline())
    res = next(m for m in out["metrics"] if m["name"] == "Total double support %")
    assert res["status"] == diagnostics.OK


def test_total_double_support_pct_no_cycles_unavailable():
    """No events at all -> the spatiotemporal segments find no cycles, so the
    derived % has no reference -> UNAVAILABLE / NO_REFERENCE."""
    p = Pipeline()
    p.add(MetricStep(op="time_between_events", name="Double support R",
                     segment=["R_HS", "L_TO"]))
    p.add(MetricStep(op="time_between_events", name="Double support L",
                     segment=["L_HS", "R_TO"]))
    p.add(MetricStep(op="time_between_events", name="R Stride time",
                     segment=["R_HS", "R_HS"]))
    p.add(MetricStep(op="add", name="Total double support time",
                     input="metric:Double support R",
                     input2="metric:Double support L"))
    p.add(MetricStep(op="double_support_pct", name="Total double support %",
                     input="metric:Total double support time",
                     input2="metric:R Stride time"))
    out = run_pipeline(_ds_with_events(), p)
    res = next(m for m in out["metrics"] if m["name"] == "Total double support %")
    assert res["status"] == diagnostics.UNAVAILABLE
    assert res["reason"] == diagnostics.NO_REFERENCE
    assert np.isnan(res["value"])


# --- preset seeding ---------------------------------------------------------

@pytest.mark.parametrize("builder", [presets.walk_treadmill, presets.walk_overground])
def test_walk_presets_seed_total_double_support_pct(builder):
    names = [getattr(s, "name", "") for s in builder({})
             if isinstance(s, MetricStep)]
    assert "Total double support %" in names
    assert "Total double support time" in names
