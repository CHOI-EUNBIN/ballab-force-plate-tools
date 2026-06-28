"""Regression tests for the C1 analysis pipeline (core.pipeline) and its
integration with core.signals (catalog + Workspace).

Pins the C1 contract:
  - A FilterStep added to the pipeline makes its processed "<key>:filt" signals
    appear in ``signal_catalog`` labelled "(filtered)", and
    ``Workspace.series("<key>:filt")`` equals a direct ``apply_lowpass``.
  - No filter step => catalog lists raw only and analysis runs on raw.
  - ``Pipeline.to_dict`` / ``from_dict`` round-trip.
  - An old manifest (no "pipeline" key) loads as an empty pipeline.
  - Per-key cutoffs: separate steps with different cutoffs coexist.
"""

import numpy as np

from core.events_compute import _detect_token, compute_detected_events
from core.pipeline import (COMPUTE_METHODS, STAGE_LABELS, STAGE_ORDER,
                           ComputeAngleStep, ComputeStep, DetectEventStep,
                           FilterStep, MetricStep, Pipeline, TrajectoryStep)
from core.signal_proc import apply_lowpass
from core.signals import FilterSpec, Workspace, signal_catalog
from core.trajectory import compute_trajectory, first_trajectory


def _dataset(n=500, fs=100.0):
    t = np.arange(n) / fs
    ap = np.sin(2 * np.pi * 1.0 * t) + 0.3 * np.sin(2 * np.pi * 20.0 * t)
    ml = np.cos(2 * np.pi * 0.7 * t) + 0.2 * np.sin(2 * np.pi * 25.0 * t)
    return {
        "time": t,
        "fs": fs,
        "cop_ap": ap,
        "cop_ml": ml,
        "fz": np.ones(n),
        "fx": np.full(n, 2.0),
        "fy": np.full(n, 3.0),
    }


# -- empty pipeline = raw ----------------------------------------------------

def test_empty_pipeline_catalog_is_raw_only():
    ds = _dataset()
    cat = signal_catalog(ds, pipeline=Pipeline())
    assert all(not k.endswith(":filt") for k, _ in cat)


def test_empty_pipeline_series_filt_returns_raw():
    ds = _dataset()
    ws = Workspace(ds, pipeline=Pipeline())
    np.testing.assert_array_equal(ws.series("cop_ap:filt"), ds["cop_ap"])
    np.testing.assert_array_equal(ws.series("fz:filt"), ds["fz"])


# -- filter step adds processed signals --------------------------------------

def test_filter_step_appears_in_catalog():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap", "cop_ml"]))
    cat = signal_catalog(ds, pipeline=p)
    keys = [k for k, _ in cat]
    labels = dict(cat)
    assert "cop_ap:filt" in keys and "cop_ml:filt" in keys
    assert "fz:filt" not in keys  # untargeted -> no processed entry
    assert labels["cop_ap:filt"] == "COP X (filtered)"
    # processed entry sits right after its raw entry
    assert keys.index("cop_ap:filt") == keys.index("cop_ap") + 1


def test_filter_step_series_matches_apply_lowpass():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(type="Butterworth", cutoff_hz=10.0, order=4),
                     targets=["cop_ap"]))
    ws = Workspace(ds, pipeline=p)
    got = ws.series("cop_ap:filt")
    want = apply_lowpass(ds["cop_ap"], 10.0, ds["fs"], 4, "Butterworth", 0.5)
    np.testing.assert_allclose(got, want, atol=1e-9, rtol=0)


def test_untargeted_key_stays_raw():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap"]))
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_array_equal(ws.series("fz:filt"), ds["fz"])


# -- per-key cutoffs via separate steps --------------------------------------

def test_separate_steps_different_cutoffs():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap"]))
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=["fz"]))
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(
        ws.series("cop_ap:filt"),
        apply_lowpass(ds["cop_ap"], 10.0, ds["fs"], 4, "Butterworth", 0.5),
        atol=1e-9)
    np.testing.assert_allclose(
        ws.series("fz:filt"),
        apply_lowpass(ds["fz"], 6.0, ds["fs"], 4, "Butterworth", 0.5),
        atol=1e-9)


def test_later_step_overrides_same_key():
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap"]))
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=["cop_ap"]))
    assert p.filter_spec_for("cop_ap").cutoff_hz == 6.0


# -- marker target -----------------------------------------------------------

def test_marker_filter_spec_from_step():
    p = Pipeline()
    assert p.marker_filter_spec() is None
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=[], markers=True))
    spec = p.marker_filter_spec()
    assert spec is not None and spec.cutoff_hz == 6.0


# -- editing -----------------------------------------------------------------

def test_pipeline_add_remove_move():
    p = Pipeline()
    a = p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap"]))
    b = p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=["fz"]))
    assert len(p) == 2 and list(p) == [a, b]
    p.move(0, 1)
    assert list(p) == [b, a]
    p.remove(0)
    assert list(p) == [a]


# -- persistence -------------------------------------------------------------

def test_pipeline_roundtrip():
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(type="Butterworth", cutoff_hz=10.0, order=4),
                     targets=["cop_ap", "cop_ml"]))
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=6.0, order=2), targets=[], markers=True))
    d = p.to_dict()
    p2 = Pipeline.from_dict(d)
    assert p2.to_dict() == d
    assert len(p2) == 2
    assert p2.filter_spec_for("cop_ap").cutoff_hz == 10.0
    assert p2.marker_filter_spec().cutoff_hz == 6.0


def test_old_manifest_no_pipeline_key_loads_empty():
    # Backward compat: v2 manifests have no "pipeline" key.
    assert len(Pipeline.from_dict(None)) == 0
    assert len(Pipeline.from_dict({})) == 0
    manifest = {"version": 2, "datasets": []}
    assert len(Pipeline.from_dict(manifest.get("pipeline"))) == 0


def test_unknown_step_kind_skipped():
    # Forward compat: a future step kind we don't know is skipped, not fatal.
    data = {"steps": [{"kind": "filter", "spec": {"cutoff_hz": 10.0},
                       "targets": ["cop_ap"], "markers": False},
                      {"kind": "future_thing", "foo": 1}]}
    p = Pipeline.from_dict(data)
    assert len(p) == 1
    assert p.filter_spec_for("cop_ap").cutoff_hz == 10.0


# -- DetectEventStep.color as a real field (out of the detection token) ------

def test_detect_event_color_roundtrip():
    step = DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 20.0}, color="#FF0000")
    d = step.to_dict()
    assert d["color"] == "#FF0000"
    # color is its own field, not a detection knob in params
    assert "color" not in d["params"]
    step2 = DetectEventStep.from_dict(d)
    assert step2.color == "#FF0000"
    assert step2.params == {"threshold": 20.0}


def test_metric_step_input2_roundtrip_and_backcompat():
    # Round B2: input2 (binary symmetry/reference ops) round-trips...
    step = MetricStep(op="symmetry_index", name="vGRF SI",
                      input="metric:Peak L", input2="metric:Peak R")
    d = step.to_dict()
    assert d["input2"] == "metric:Peak R"
    step2 = MetricStep.from_dict(d)
    assert step2.input2 == "metric:Peak R"
    # ...and an OLD project with no input2 key loads as None (back-compat).
    old = {"kind": "metric", "input": "angle:Knee", "op": "max", "name": "Peak",
           "segment": None, "event": None, "enabled": True}
    assert MetricStep.from_dict(old).input2 is None


def test_metric_event_op_requires_only_segment_events():
    # An event-kind op (time_between_events) has no signal input requirement —
    # only the two segment event labels. A reference op requires its metric refs.
    from core.pipeline import EVENT_PREFIX, METRIC_PREFIX
    ev_step = MetricStep(op="time_between_events", name="Stride",
                         segment=["HS", "HS"])
    assert ev_step.requires() == {f"{EVENT_PREFIX}HS"}
    ref = MetricStep(op="symmetry_index", name="SI",
                     input="metric:L", input2="metric:R")
    assert ref.requires() == {f"{METRIC_PREFIX}L", f"{METRIC_PREFIX}R"}


def test_detect_event_legacy_color_in_params_migrates():
    # Old projects stored colour inside params -> pulled into the color field.
    old = {"kind": "detect_event", "input": "fz", "label": "HS",
           "method": "threshold", "params": {"threshold": 20.0, "color": "#00FF00"},
           "selector": {"mode": "first"}, "scope": None}
    step = DetectEventStep.from_dict(old)
    assert step.color == "#00FF00"
    assert "color" not in step.params
    assert step.params == {"threshold": 20.0}


def test_color_change_does_not_change_detect_token():
    p1 = Pipeline()
    p1.add(DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 20.0}, color="#FF0000"))
    p2 = Pipeline()
    p2.add(DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 20.0}, color="#00FF00"))
    # Same detection recipe, different colour -> identical cache token.
    assert _detect_token(p1) == _detect_token(p2)
    # ...but a real detection change DOES flip the token.
    p3 = Pipeline()
    p3.add(DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 25.0}, color="#FF0000"))
    assert _detect_token(p1) != _detect_token(p3)


def test_color_change_keeps_event_cache():
    # The per-file detected-events cache must survive a recolour (no recompute).
    ds = _dataset()
    ds["fz"] = np.concatenate([np.zeros(250), np.full(250, 50.0)])  # one rising edge
    p = Pipeline()
    p.add(DetectEventStep(input="fz", label="HS", method="threshold",
                          params={"threshold": 20.0}, color="#FF0000"))
    first = compute_detected_events(ds, p)
    token_before = ds.get("_events_token")
    # recolour the step
    p.steps[0].color = "#00FF00"
    second = compute_detected_events(ds, p)
    assert ds.get("_events_token") == token_before          # token unchanged
    assert second is first                                  # cache reused (same object)
    assert first[0]["frames"] == [250]


# -- TrajectoryStep + compute_trajectory -------------------------------------

def test_trajectory_step_roundtrip():
    step = TrajectoryStep(ap="cop_ap", ml="cop_ml")
    d = step.to_dict()
    assert d == {"kind": "trajectory", "ap": "cop_ap", "ml": "cop_ml",
                 "enabled": True}
    step2 = TrajectoryStep.from_dict(d)
    assert step2.ap == "cop_ap" and step2.ml == "cop_ml"
    # via the generic Pipeline round-trip too
    p = Pipeline([step])
    assert Pipeline.from_dict(p.to_dict()).trajectory_steps()[0].ap == "cop_ap"


def test_trajectory_step_defaults():
    step = TrajectoryStep.from_dict({"kind": "trajectory"})
    assert step.ap == "cop_ap" and step.ml == "cop_ml"


def test_compute_trajectory_is_mean_centred():
    ds = _dataset()
    # known means so we can check centring exactly
    ds["cop_ap"] = np.array([10.0, 12.0, 14.0])  # mean 12
    ds["cop_ml"] = np.array([4.0, 5.0, 6.0])     # mean 5
    ds["time"] = np.arange(3) / 100.0
    ws = Workspace(ds, pipeline=Pipeline())
    traj = compute_trajectory(ws)
    np.testing.assert_allclose(traj["y"], [-2.0, 0.0, 2.0])   # ap - 12
    np.testing.assert_allclose(traj["x"], [-1.0, 0.0, 1.0])   # ml - 5
    assert traj["mean"] == (5.0, 12.0)                        # (ml_mean, ap_mean)
    # mean of the centred path is ~0 by construction
    assert abs(np.mean(traj["x"])) < 1e-12
    assert abs(np.mean(traj["y"])) < 1e-12


def test_compute_trajectory_uses_step_keys_and_filtering():
    ds = _dataset()
    p = Pipeline()
    p.add(FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap", "cop_ml"]))
    step = TrajectoryStep(ap="cop_ap:filt", ml="cop_ml:filt")
    p.add(step)
    ws = Workspace(ds, pipeline=p)
    traj = compute_trajectory(ws, step=step)
    # filtered AP, mean-centred -> matches apply_lowpass minus its mean
    want_ap = apply_lowpass(ds["cop_ap"], 10.0, ds["fs"], 4, "Butterworth", 0.5)
    np.testing.assert_allclose(traj["y"], want_ap - np.nanmean(want_ap), atol=1e-9)


def test_first_trajectory_helper():
    ds = _dataset()
    p = Pipeline()
    assert first_trajectory(Workspace(ds, pipeline=p), p) is None
    p.add(TrajectoryStep())
    traj = first_trajectory(Workspace(ds, pipeline=p), p)
    assert traj is not None and "x" in traj and "y" in traj


# -- Phase A+B contract: stages, enabled, steps_by_stage, warnings -----------

def test_stage_constants():
    # internal keys English-lowercase; labels English per direction doc
    assert STAGE_ORDER == ["derive", "detect", "segment", "metric", "normalize"]
    assert STAGE_LABELS == {
        "derive": "Compute", "detect": "Detect Events", "segment": "Segment",
        "metric": "Metric", "normalize": "Normalize",
    }
    # every ordered stage has a label
    assert set(STAGE_ORDER) == set(STAGE_LABELS)


def test_step_stage_tagging():
    assert FilterStep.stage == "derive"
    assert TrajectoryStep.stage == "derive"
    assert DetectEventStep.stage == "detect"
    # instance sees the class attribute
    assert FilterStep().stage == "derive"
    assert DetectEventStep().stage == "detect"


def test_steps_by_stage_order_index_and_all_keys():
    f = FilterStep(targets=["cop_ap"])
    d = DetectEventStep(input="fz", label="HS")
    t = TrajectoryStep()
    p = Pipeline([f, d, t])
    by = p.steps_by_stage()
    # all five stage keys present even when empty (place-holder menus)
    assert list(by.keys()) == STAGE_ORDER
    assert by["segment"] == [] and by["metric"] == [] and by["normalize"] == []
    # original indices carried; derive bucket holds both derive steps in order
    assert by["derive"] == [(0, f), (2, t)]
    assert by["detect"] == [(1, d)]


def test_steps_by_stage_includes_disabled():
    f = FilterStep(targets=["cop_ap"], enabled=False)
    p = Pipeline([f])
    # display view keeps the disabled step...
    assert p.steps_by_stage()["derive"] == [(0, f)]
    # ...while the execution view drops it
    assert p.filter_steps() == []


def test_enabled_roundtrip_and_default():
    f = FilterStep(targets=["cop_ap"], enabled=False)
    assert f.to_dict()["enabled"] is False
    assert FilterStep.from_dict(f.to_dict()).enabled is False

    d = DetectEventStep(input="fz", label="HS", enabled=False)
    assert d.to_dict()["enabled"] is False
    assert DetectEventStep.from_dict(d.to_dict()).enabled is False

    t = TrajectoryStep(enabled=False)
    assert TrajectoryStep.from_dict(t.to_dict()).enabled is False

    # legacy dicts (no "enabled" key) fall back to True
    assert FilterStep.from_dict({"kind": "filter", "targets": ["fz"]}).enabled
    assert DetectEventStep.from_dict({"kind": "detect_event"}).enabled
    assert TrajectoryStep.from_dict({"kind": "trajectory"}).enabled


def test_disabled_excluded_from_execution_accessors():
    on = FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap"],
                    markers=True)
    off = FilterStep(spec=FilterSpec(cutoff_hz=6.0), targets=["cop_ml"],
                     markers=True, enabled=False)
    p = Pipeline([on, off])
    assert p.filter_steps() == [on]
    # last enabled marker step wins; the disabled one is invisible
    assert p.marker_filter_spec().cutoff_hz == 10.0
    # filter_spec_for skips the disabled target -> stays raw
    assert p.filter_spec_for("cop_ml") is None
    assert p.filter_spec_for("cop_ap").cutoff_hz == 10.0
    # filtered_keys only lists enabled producers
    assert p.filtered_keys() == ["cop_ap:filt"]

    d_on = DetectEventStep(input="fz", label="HS")
    d_off = DetectEventStep(input="fz", label="TO", enabled=False)
    p2 = Pipeline([d_on, d_off])
    assert p2.detect_event_steps() == [d_on]

    t_off = TrajectoryStep(enabled=False)
    assert Pipeline([t_off]).trajectory_steps() == []


def test_enabled_flips_detect_cache_token():
    d = DetectEventStep(input="fz", label="HS")
    p = Pipeline([d])
    tok_on = _detect_token(p)
    d.enabled = False
    tok_off = _detect_token(p)
    # disabling removes the step from the token entirely -> recompute
    assert tok_on != tok_off
    assert tok_off == "[]"


def test_enabled_in_detect_token_field():
    # even with the step still enabled-vs-disabled, the field is part of to_dict
    # so any future single-disabled-among-many also invalidates correctly
    a = DetectEventStep(input="fz", label="A")
    b = DetectEventStep(input="fz", label="B")
    p = Pipeline([a, b])
    before = _detect_token(p)
    b.enabled = False
    after = _detect_token(p)
    assert before != after


# -- produces()/requires() contract ---------------------------------------

def test_filter_step_produces_and_requires():
    # produces = one "<target>:filt" per target; requires = the raw targets
    fs = FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["cop_ap", "cop_ml"])
    assert fs.produces() == {"cop_ap:filt", "cop_ml:filt"}
    assert fs.requires() == {"cop_ap", "cop_ml"}


def test_detect_step_produces_and_requires():
    de = DetectEventStep(input="fz:filt", label="HS")
    assert de.produces() == {"event:HS"}
    assert de.requires() == {"fz:filt"}
    # frame method reads no signal -> requires empty
    fr = DetectEventStep(method="frame", label="start", params={"frame": 0})
    assert fr.requires() == set()
    # an unlabelled step produces nothing
    blank = DetectEventStep(input="fz", label="")
    assert blank.produces() == set()


def test_trajectory_step_produces_and_requires():
    ts = TrajectoryStep(ap="cop_ap", ml="cop_ml")
    assert ts.requires() == {"cop_ap", "cop_ml"}
    # produces a single namespaced 2-D key
    assert ts.produces() == {"trajectory:cop_mlxcop_ap"}


def test_base_step_contract_defaults_to_empty():
    from core.pipeline import PipelineStep
    s = PipelineStep()
    assert s.produces() == set()
    assert s.requires() == set()


# -- data_dependency_warnings() lint --------------------------------------

def test_data_dependency_clean_recipe():
    # correct order: filter -> detect on its :filt output => no warning
    p = Pipeline([
        FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]),
        DetectEventStep(input="fz:filt", label="HS"),
    ])
    assert p.data_dependency_warnings() == []


def test_data_dependency_detect_before_filter_warns():
    # detect reads fz:filt but the filter step that makes it comes AFTER -> warn
    p = Pipeline([
        DetectEventStep(input="fz:filt", label="HS"),
        FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]),
    ])
    warns = p.data_dependency_warnings()
    assert (0, "'fz:filt' is not produced before this step") in warns


def test_data_dependency_missing_filter_warns():
    # detect on a :filt input with NO filter step at all -> warn (derived key)
    p = Pipeline([DetectEventStep(input="cop_ap:filt", label="x")])
    warns = p.data_dependency_warnings()
    assert any("cop_ap:filt" in m for _, m in warns)


def test_data_dependency_raw_input_no_warning():
    # detect on a bare RAW input (not derived) never warns when raw catalog unknown
    p = Pipeline([DetectEventStep(input="fz", label="HS")])
    assert p.data_dependency_warnings() == []


def test_data_dependency_interleaved_stages_no_warning():
    # the user's real recipe shape (Compute -> Detect -> Compute ...) is valid:
    # stages may interleave; only data dependency matters. filter -> detect(raw)
    # -> trajectory(on :filt) all resolve, so NO warning despite stage order.
    p = Pipeline([
        FilterStep(spec=FilterSpec(), targets=["cop_ap", "cop_ml"]),
        DetectEventStep(input="fz", label="HS"),
        TrajectoryStep(ap="cop_ap:filt", ml="cop_ml:filt"),
    ])
    assert p.data_dependency_warnings() == []


def test_data_dependency_ignores_disabled():
    # a disabled out-of-order detect must not trip the warning
    p = Pipeline([
        DetectEventStep(input="fz:filt", label="HS"),
        FilterStep(spec=FilterSpec(cutoff_hz=10.0), targets=["fz"]),
    ])
    p.steps[0].enabled = False
    assert p.data_dependency_warnings() == []


def test_data_dependency_exact_raw_keys():
    # when the dataset's raw catalog is passed, even a bare key is checked
    p = Pipeline([DetectEventStep(input="fz", label="HS")])
    assert p.data_dependency_warnings(raw_keys=set()) == [
        (0, "'fz' is not produced before this step")]
    assert p.data_dependency_warnings(raw_keys={"fz"}) == []


def test_stage_order_warnings_alias():
    # back-compat: the old name still resolves to the new lint
    p = Pipeline([DetectEventStep(input="fz:filt", label="HS")])
    assert p.stage_order_warnings() == p.data_dependency_warnings()


# -- reference-op ordering lint (Round D) ---------------------------------
# A metric-reference op (cadence / symmetry / CV / stance% / RSI ...) reads
# another metric's VALUE (metric:<name>). In the single-pass executor it MUST
# sit AFTER the metric it cites, else the value is absent at run time and the
# result is NaN. The dependency lint must surface that ordering mistake (the
# metric: key is a derived key, so it is provably-missing when read too early).

def test_reference_op_before_cited_metric_warns():
    # cadence references metric:StepTime but is placed BEFORE the StepTime step
    cad = MetricStep(op="cadence", name="Cadence", input="metric:StepTime")
    st = MetricStep(op="time_between_events", name="StepTime",
                    segment=["HSr", "HSl"])
    p = Pipeline([cad, st])
    warns = p.data_dependency_warnings()
    assert (0, "'metric:StepTime' is not produced before this step") in warns


def test_reference_op_after_cited_metric_clean():
    # correct order: the cited metric is produced first, so no metric-ref warning.
    # (The detect events feeding StepTime are raw-unknown here; pass them as raw so
    # only the metric-ref ordering is under test.)
    st = MetricStep(op="time_between_events", name="StepTime",
                    segment=["HSr", "HSl"])
    cad = MetricStep(op="cadence", name="Cadence", input="metric:StepTime")
    p = Pipeline([st, cad])
    warns = p.data_dependency_warnings(raw_keys={"event:HSr", "event:HSl"})
    assert warns == []


def test_cv_op_before_cited_metric_warns():
    # CV reads the per-cycle array of metric:Stride; placed first -> flagged.
    cv = MetricStep(op="cv", name="StrideCV", input="metric:Stride")
    stride = MetricStep(op="time_between_events", name="Stride",
                        segment=["HSr", "HSr"])
    p = Pipeline([cv, stride])
    warns = p.data_dependency_warnings()
    assert (0, "'metric:Stride' is not produced before this step") in warns


def test_symmetry_op_before_cited_metrics_warns():
    # symmetry_index reads metric:Left (input) and metric:Right (input2); both
    # produced later -> both flagged on the symmetry step.
    sym = MetricStep(op="symmetry_index", name="ROMsym",
                     input="metric:Left", input2="metric:Right")
    left = MetricStep(op="range", name="Left", input="angle:LKnee_FE")
    right = MetricStep(op="range", name="Right", input="angle:RKnee_FE")
    p = Pipeline([sym, left, right])
    warns = p.data_dependency_warnings()
    assert (0, "'metric:Left' is not produced before this step") in warns
    assert (0, "'metric:Right' is not produced before this step") in warns


# -- ComputeAngleStep: angles as a pipeline step (sole-source plumbing) -------

def test_compute_angle_step_roundtrip_and_defaults():
    s = ComputeAngleStep(joints=["RKNEE_FE", "LKNEE_FE"])
    d = s.to_dict()
    assert d == {"kind": "compute_angle", "joints": ["RKNEE_FE", "LKNEE_FE"],
                 "enabled": True}
    s2 = ComputeAngleStep.from_dict(d)
    assert s2.joints == ["RKNEE_FE", "LKNEE_FE"]
    assert s2.enabled is True
    # default: no joints, enabled
    s3 = ComputeAngleStep.from_dict({"kind": "compute_angle"})
    assert s3.joints == [] and s3.enabled is True
    # generic Pipeline round-trip dispatches on kind
    p = Pipeline([s])
    assert Pipeline.from_dict(p.to_dict()).compute_angle_steps()[0].joints == \
        ["RKNEE_FE", "LKNEE_FE"]


def test_compute_angle_step_produces_and_requires():
    s = ComputeAngleStep(joints=["RKNEE_FE"])
    assert s.produces() == {"angle:RKNEE_FE"}
    assert s.requires() == set()           # markers/model are out-of-band
    # no declared joints -> produces nothing nameable (still "makes angles")
    assert ComputeAngleStep().produces() == set()


def test_compute_angle_step_stage_and_accessors():
    assert ComputeAngleStep.stage == "derive"
    p = Pipeline([ComputeAngleStep(joints=["RKNEE_FE"]),
                  DetectEventStep(input="fz", label="HS")])
    assert p.has_angle_step() is True
    assert len(p.compute_angle_steps()) == 1
    # disabled angle step -> not in execution view, has_angle_step False
    p.steps[0].enabled = False
    assert p.compute_angle_steps() == []
    assert p.has_angle_step() is False
    # empty pipeline never has an angle step
    assert Pipeline().has_angle_step() is False
    # display view still keeps the (disabled) derive step
    assert (0, p.steps[0]) in p.steps_by_stage()["derive"]


def test_compute_angle_step_in_dependency_lint():
    # a metric reading a declared angle after the angle step => no warning
    p = Pipeline([
        ComputeAngleStep(joints=["RKNEE_FE"]),
        DetectEventStep(input="angle:RKNEE_FE", label="peak", method="peak"),
    ])
    # bare angle: keys are non-derived, so the lint never false-warns regardless
    assert p.data_dependency_warnings() == []


def test_compute_step_back_compat_old_dict_loads_as_normalize():
    """An old project saved before params/inputs existed must load unchanged: the
    extra fields default to empty and the method stays normalize."""
    old = {"kind": "compute", "input": "fp1:fz", "by": "metric:bodyweight",
           "name": "fp1:fz_pctbw", "method": "normalize", "enabled": True}
    s = ComputeStep.from_dict(old)
    assert s.method == "normalize"
    assert s.params == {} and s.inputs == []
    assert s.requires() == {"fp1:fz", "metric:bodyweight"}
    assert s.produces() == {"fp1:fz_pctbw"}


def test_compute_step_new_methods_roundtrip_and_deps():
    """derivative/integral/magnitude round-trip with params/inputs; requires()
    pulls the extra magnitude components in and drops the (unused) normalize ref."""
    deriv = ComputeStep(input="angle:Knee", name="Knee_vel", method="derivative",
                        params={"order": 2})
    d = deriv.to_dict()
    assert d["params"] == {"order": 2} and d["method"] == "derivative"
    assert ComputeStep.from_dict(d).params == {"order": 2}

    mag = ComputeStep(input="fp1:fx", inputs=["fp1:fy", "fp1:fz"], name="Fres",
                      method="magnitude", by="metric:bodyweight")
    # by is a normalize-only field; magnitude's requires must NOT include it,
    # but MUST include the extra component inputs.
    assert mag.requires() == {"fp1:fx", "fp1:fy", "fp1:fz"}
    assert mag.produces() == {"Fres"}
    assert ComputeStep.from_dict(mag.to_dict()).inputs == ["fp1:fy", "fp1:fz"]

    # all advertised methods exist in the registry
    assert set(COMPUTE_METHODS) == {"normalize", "derivative", "integral",
                                    "magnitude", "abs", "xcom"}

    # abs: |input|, unit preserved, requires only its input (no by/inputs).
    a = ComputeStep(input="fp1:fz", name="absFz", method="abs")
    assert a.requires() == {"fp1:fz"} and a.produces() == {"absFz"}
    assert ComputeStep.from_dict(a.to_dict()).method == "abs"


def test_compute_step_pipeline_roundtrip_dispatches_on_kind():
    p = Pipeline([ComputeStep(input="fp1:fz", name="dFz", method="derivative",
                              params={"order": 1})])
    back = Pipeline.from_dict(p.to_dict()).compute_steps()[0]
    assert back.method == "derivative" and back.params == {"order": 1}
