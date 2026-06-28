"""Module-boundary guard for the master clock (#5 robustness).

``Workspace`` (and thus ``run_pipeline``) assumes ``dataset['time']`` is present,
1-D and monotonic. A broken clock used to surface as a cryptic KeyError or wrong
numbers deep inside a detector; the guard raises a clear ValueError at the door.
"""

import numpy as np
import pytest

from core.pipeline import Pipeline, MetricStep
from core.run import run_pipeline
from core.signals import Workspace


def test_missing_time_raises_clear_error():
    with pytest.raises(ValueError, match="time"):
        Workspace({"fs": 100.0})


def test_multidimensional_time_raises():
    with pytest.raises(ValueError, match="1-D|one-dimensional|time"):
        Workspace({"time": np.zeros((10, 2)), "fs": 100.0})


def test_non_monotonic_time_raises():
    t = np.array([0.0, 0.01, 0.02, 0.005, 0.03])   # one step goes backwards
    with pytest.raises(ValueError, match="monotonic|time"):
        Workspace({"time": t, "fs": 100.0})


def test_valid_time_is_accepted():
    t = np.arange(10) / 100.0
    ws = Workspace({"time": t, "fs": 100.0})
    assert ws.time.shape == (10,)


def test_empty_and_single_sample_time_are_allowed():
    # An empty / 1-sample trial is short, not broken — must not raise.
    Workspace({"time": np.array([]), "fs": 100.0})
    Workspace({"time": np.array([0.0]), "fs": 100.0})


def test_run_pipeline_surfaces_broken_clock_at_boundary():
    ds = {"time": np.array([0.0, 0.02, 0.01]), "fs": 100.0,
          "angle:Knee": np.zeros(3)}
    p = Pipeline()
    p.add(MetricStep(input="angle:Knee", op="max", name="m"))
    with pytest.raises(ValueError, match="monotonic|time"):
        run_pipeline(ds, p)
