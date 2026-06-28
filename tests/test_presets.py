"""Tests for core/presets.py — walk_treadmill preset registry.

NOTE on registry equality assertion: PipelineStep does NOT define __eq__, so
two separately-built lists of steps compare by identity (always unequal).
We compare class-name sequences instead, which holds structurally.
"""
from core import presets
from core.pipeline import DetectEventStep, MetricStep


def _labels(steps, kind):
    return [getattr(s, "name", getattr(s, "label", "")) for s in steps
            if s.__class__.__name__ == kind]


def test_walk_treadmill_seeds_kinematic_events_both_sides():
    steps = presets.walk_treadmill({})
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    inputs = {s.input for s in det}
    assert "gait:R_heel_ap" in inputs and "gait:R_toe_ap" in inputs
    assert "gait:L_heel_ap" in inputs and "gait:L_toe_ap" in inputs
    assert all(s.input.startswith("gait:") for s in det)


def test_walk_treadmill_has_core_spatiotemporal_and_no_kinetics():
    names = _labels(presets.walk_treadmill({}), "MetricStep")
    for needed in ("R Stride time", "R Cadence", "R Stance %", "R Gait speed"):
        assert needed in names, needed
    ops = {s.op for s in presets.walk_treadmill({}) if isinstance(s, MetricStep)}
    assert "impulse" not in ops and "loading_rate" not in ops


def test_build_preset_registry():
    assert "walk_treadmill" in presets.PRESETS
    # PipelineStep has no __eq__; compare class-name sequences instead (structural equality).
    assert [s.__class__.__name__ for s in presets.build_preset("walk_treadmill", {})] == \
           [s.__class__.__name__ for s in presets.walk_treadmill({})]


import numpy as np
from core.pipeline import ComputeStep

def _loaded_force_ds():
    n = 600
    fz = np.where((np.arange(n) % 120) < 70, 600.0, 0.0)
    return {"time": np.arange(n)/1000.0, "fs": 1000.0, "n_force_plates": 1,
            "fp1:fz": fz}

def _flat_force_ds():
    n = 600
    return {"time": np.arange(n)/1000.0, "fs": 1000.0, "n_force_plates": 1,
            "fp1:fz": np.zeros(n)}

def test_overground_uses_force_events_when_loaded():
    steps = presets.walk_overground(_loaded_force_ds())
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    assert any("fz" in s.input for s in det)
    ops = {s.op for s in steps if isinstance(s, MetricStep)}
    assert "impulse" in ops

def test_overground_falls_back_to_kinematic_without_force():
    steps = presets.walk_overground(_flat_force_ds())
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    assert all(s.input.startswith("gait:") for s in det)
    ops = {s.op for s in steps if isinstance(s, MetricStep)}
    assert "impulse" not in ops

def test_overground_stride_length_is_displacement():
    steps = presets.walk_overground(_flat_force_ds())
    sl = [s for s in steps if isinstance(s, MetricStep)
          and getattr(s, "name", "") == "R Stride length"]
    assert sl and sl[0].op == "displacement_between_events"


def test_walk_preset_seeds_filter_angles_and_normalize():
    from core.pipeline import FilterStep, ComputeAngleStep, NormalizeStep
    for builder in (presets.walk_treadmill, presets.walk_overground):
        steps = builder({})
        assert any(isinstance(s, FilterStep) for s in steps)        # filtering
        assert any(isinstance(s, ComputeAngleStep) for s in steps)  # graphable angles
        norm = [s for s in steps if isinstance(s, NormalizeStep)]
        ninputs = {s.input for s in norm}
        assert "angle:R_KNEE_angle_FE" in ninputs   # ensemble curve, R knee
        assert "angle:L_KNEE_angle_FE" in ninputs   # and L knee
