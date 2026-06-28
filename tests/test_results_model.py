"""core.results_model — the by-type listing that feeds the RESULT panels.

Pins that build_results composes the existing catalogs (no recompute): signals
include raw + filtered twins + ComputeStep outputs; events come from detected
steps; metrics appear only after a run, grouped by their source signal.
"""

import numpy as np

from core.pipeline import (ComputeAngleStep, ComputeStep, DetectEventStep,
                           FilterStep, MetricStep, Pipeline, TrajectoryStep)
from core.results_model import build_results, results_token
from core.run import run_pipeline
from core.signals import FilterSpec


def _dataset(n=400, fs=100.0):
    t = np.arange(n) / fs
    fz = 10 + 40 * (1 + np.sin(2 * np.pi * 4 * t / (n / fs)))
    knee = 20 + 20 * np.sin(2 * np.pi * 4 * t / (n / fs))
    return {
        "time": t, "fs": fs,
        "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
        "fz": fz, "fp1:fz": fz.copy(),
        "fp1:cop_ap": np.zeros(n), "fp1:cop_ml": np.zeros(n),
        "n_force_plates": 1, "force_signal_keys": ["fp1:fz"],
        "model_result": {"angles": {"Knee": knee}, "time": t},
    }


def test_empty_pipeline_has_no_signals():
    # Nothing computed yet -> the Signals result list is empty (raw inputs are
    # NOT listed here; they belong to the RAW SIGNALS panel).
    ds = _dataset()
    assert build_results(ds, Pipeline(), run_result=None)["signal"] == []
    # raw force/COP/angle/marker keys never appear as result signals
    keys = {e.key for e in build_results(ds, Pipeline())["signal"]}
    assert keys == set()


def test_signals_are_pipeline_products_only():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=["fp1:fz"]))
    p.add(ComputeStep(input="fp1:fz", by="metric:bodyweight", name="fp1:fz_pctbw"))
    res = build_results(ds, p, run_result=None)
    keys = {e.key for e in res["signal"]}
    assert "fp1:fz" not in keys             # raw input excluded
    assert "fp1:fz:filt" in keys            # FilterStep product (processed)
    assert "fp1:fz_pctbw" in keys           # ComputeStep output (derived)
    by_key = {e.key: e for e in res["signal"]}
    assert by_key["fp1:fz:filt"].origin == "processed"
    assert by_key["fp1:fz:filt"].group == "Processed signals"
    assert by_key["fp1:fz_pctbw"].origin == "derived"
    assert by_key["fp1:fz_pctbw"].group == "Derived signals"


def test_angles_only_with_compute_angle_step():
    ds = _dataset()
    # model_result has a "Knee" angle, but with NO ComputeAngleStep it stays out.
    res = build_results(ds, Pipeline(), run_result=None)
    assert not any(e.key.startswith("angle:") for e in res["signal"])
    # add a ComputeAngleStep -> angle:* appears under "Joint angles"
    p = Pipeline()
    p.add(ComputeAngleStep())
    res = build_results(ds, p, run_result=None)
    by_key = {e.key: e for e in res["signal"]}
    assert "angle:Knee" in by_key
    assert by_key["angle:Knee"].group == "Joint angles"
    assert by_key["angle:Knee"].origin == "model"


def test_com_signals_grouped_when_present():
    # com:x/y/z are model products (like Joint angles): gated on a ComputeAngleStep
    # AND a non-empty COM trajectory in the model result.
    ds = _dataset()
    n = len(ds["time"])
    ds["model_result"]["com"] = {"com": np.zeros((n, 3))}   # as marker_model.apply writes

    # No ComputeAngleStep -> COM stays out (the pipeline is the sole source).
    res = build_results(ds, Pipeline(), run_result=None)
    assert not any(e.key.startswith("com:") for e in res["signal"])

    # With a ComputeAngleStep -> com:x/y/z appear under "Centre of mass".
    p = Pipeline()
    p.add(ComputeAngleStep())
    by_key = {e.key: e for e in build_results(ds, p, run_result=None)["signal"]}
    for ax in ("x", "y", "z"):
        assert f"com:{ax}" in by_key
        assert by_key[f"com:{ax}"].group == "Centre of mass"
        assert by_key[f"com:{ax}"].origin == "model"


def test_com_signals_absent_without_com_block():
    # Angles present but NO (or empty) COM block -> no com:* even with the step.
    ds = _dataset()                         # fixture has angles, no "com"
    p = Pipeline()
    p.add(ComputeAngleStep())
    res = build_results(ds, p, run_result=None)
    assert not any(e.key.startswith("com:") for e in res["signal"])
    ds["model_result"]["com"] = {"com": np.zeros((0, 3))}   # empty (0,3) -> nothing
    res = build_results(ds, p, run_result=None)
    assert not any(e.key.startswith("com:") for e in res["signal"])


def test_trajectory_signal_listed():
    ds = _dataset()
    p = Pipeline()
    p.add(TrajectoryStep(ap="fp1:cop_ap", ml="fp1:cop_ml"))
    res = build_results(ds, p, run_result=None)
    traj = [e for e in res["signal"] if e.group == "COP trajectory"]
    assert len(traj) == 1
    assert traj[0].key.startswith("trajectory:")
    assert traj[0].origin == "derived"


def test_events_listed_from_detect_steps():
    ds = _dataset()
    p = Pipeline()
    p.add(DetectEventStep(input="fp1:fz", label="HS", method="threshold",
                          params={"threshold": 20.0, "direction": "rising"},
                          selector={"mode": "all"}))
    res = build_results(ds, p, run_result=None)
    assert any(e.key == "event:HS" and e.kind == "event" for e in res["event"])


def test_metrics_only_after_run_and_grouped_by_source():
    ds = _dataset()
    p = Pipeline()
    p.add(MetricStep(input="angle:Knee", op="range", name="Knee ROM"))
    # before a run: no metrics
    assert build_results(ds, p, run_result=None)["metric"] == []
    # after a run: the metric appears, grouped under its source signal's joint
    run = run_pipeline(ds, p)
    res = build_results(ds, p, run_result=run)
    entry = next(e for e in res["metric"] if e.label == "Knee ROM")
    assert entry.kind == "metric" and entry.group == "Knee"


def test_token_changes_with_pipeline_and_subject():
    p = Pipeline()
    p.add(MetricStep(input="angle:Knee", op="max", name="Peak"))
    t0 = results_token(p, {})
    t1 = results_token(p, {"mass": 70})
    assert t0 != t1
    p.add(MetricStep(input="fp1:fz", op="max", name="Peak vGRF"))
    assert results_token(p, {}) != t0
