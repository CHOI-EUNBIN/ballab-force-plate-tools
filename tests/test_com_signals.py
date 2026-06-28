"""Task #8A — com:* signal exposure (whole-body COM trajectory as a signal).

The COM engine (core.com.body_com) writes a (F,3) world-frame COM trajectory
into ``model_result["com"]["com"]`` (mm). These tests pin its exposure as the
catalog signals ``com:x`` / ``com:y`` / ``com:z`` (world axes, mm), resolved the
same way ``angle:*`` is — from the model result the pipeline's ComputeAngleStep
produces. The pipeline is the sole source: no model result -> no com:* in the
catalog and a clear ValueError from signal_series (no silent fallback).

AP/ML decomposition (``com:ap`` / ``com:ml``) is intentionally NOT exposed: it
needs a reliable progression axis (the unresolved P3 #13), so only world axes
are offered here to avoid emitting a wrong number.
"""

import numpy as np
import pytest

from core.signals import label_for, signal_catalog, signal_series, unit_for


def _com_dataset(n=10):
    """A trial whose model_result carries a known COM trajectory.

    COM x = ramp 0..n-1, y = const 100, z = const 900 (mm). The marker clock
    equals the master clock, so signal_series returns the values unchanged.
    """
    t = np.arange(n) / 100.0
    com = np.zeros((n, 3))
    com[:, 0] = np.arange(n, dtype=float)   # x ramp
    com[:, 1] = 100.0                        # y const
    com[:, 2] = 900.0                        # z const (COM height)
    return {
        "time": t,
        "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
        "model_result": {"angles": {"Knee": np.zeros(n)}, "time": t,
                         "com": {"com": com, "whole_body": True, "coverage": 1.0}},
    }


def test_com_axes_series_world_frame():
    ds = _com_dataset()
    ar = ds["model_result"]
    x = signal_series(ds, "com:x", angle_result=ar)
    y = signal_series(ds, "com:y", angle_result=ar)
    z = signal_series(ds, "com:z", angle_result=ar)
    assert np.allclose(x, np.arange(10))
    assert np.allclose(y, 100.0)
    assert np.allclose(z, 900.0)


def test_com_unit_is_mm():
    assert unit_for("com:x") == "mm"
    assert unit_for("com:y") == "mm"
    assert unit_for("com:z") == "mm"


def test_com_label():
    assert label_for("com:x") == "COM X"
    assert label_for("com:z") == "COM Z"


def test_com_in_catalog_when_model_result_present():
    ds = _com_dataset()
    keys = [k for k, _ in signal_catalog(ds, angle_result=ds["model_result"])]
    assert "com:x" in keys and "com:y" in keys and "com:z" in keys


def test_com_absent_from_catalog_without_model_result():
    """The pipeline is the sole source: no model result -> no com:* signals."""
    ds = _com_dataset()
    keys = [k for k, _ in signal_catalog(ds, angle_result=None)]
    assert not any(k.startswith("com:") for k in keys)


def test_com_series_raises_without_model_result():
    ds = _com_dataset()
    with pytest.raises(ValueError):
        signal_series(ds, "com:x", angle_result=None)


def test_com_series_raises_when_com_empty():
    """A model with no mass-bearing segments yields an empty (0,3) COM; a com:*
    read must raise (clear), not return a wrong-shaped array."""
    ds = _com_dataset()
    ds["model_result"]["com"] = {"com": np.zeros((0, 3)), "whole_body": False}
    with pytest.raises(ValueError):
        signal_series(ds, "com:x", angle_result=ds["model_result"])


def test_no_ap_ml_com_axes_exposed():
    """AP/ML COM decomposition is deferred (needs a progression axis) — it must
    NOT silently appear in the catalog or resolve to a number."""
    ds = _com_dataset()
    keys = [k for k, _ in signal_catalog(ds, angle_result=ds["model_result"])]
    assert "com:ap" not in keys and "com:ml" not in keys
    with pytest.raises(ValueError):
        signal_series(ds, "com:ap", angle_result=ds["model_result"])
