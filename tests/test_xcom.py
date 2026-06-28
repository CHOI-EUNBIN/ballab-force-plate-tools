"""Task #8B — XCOM (extrapolated centre of mass, Hof 2005) as a signal op.

XCOM is the dynamic-balance extension of the COM that the Margin-of-Stability
framework rests on (Hof, Gazendam & Sinke, J Biomech 2005):

    XCOM(t) = x_COM(t) + v_COM(t) / w0,     w0 = sqrt(g / L)

where ``L`` is the inverted-pendulum length (typically the COM height) and ``g``
is gravity. Equivalently XCOM = x + v * sqrt(L/g). It says where the COM "is
heading" — a fast-moving COM extrapolates ahead of itself. Its unit is the same
as the position (mm here).

Implemented as a signal->signal ComputeStep ``method="xcom"`` over one COM
position axis (e.g. ``com:x``), with ``L`` (pendulum length, metres) a step
param. The velocity is differentiated internally (so a single COM axis is the
only input). This is the scientifically-defensible building block; a window
metric (mean/range/std/RMS) can then reduce the XCOM signal.

Margin of Stability itself is DEFERRED here: it needs a reliable base-of-support
boundary from foot markers, which varies per marker set — see the report.
"""

import numpy as np
import pytest

from core import signal_ops
from core.pipeline import ComputeStep, Pipeline
from core.run import run_pipeline


G = 9.80665


# --- pure math --------------------------------------------------------------

def test_xcom_static_equals_position():
    """A stationary COM has zero velocity -> XCOM == position everywhere."""
    t = np.arange(100) / 100.0
    x = np.full(100, 50.0)            # constant 50 mm
    out = signal_ops.xcom(x, t, length_m=1.0)
    assert np.allclose(out, 50.0)


def test_xcom_constant_velocity_offset():
    """A COM moving at constant velocity v: XCOM = x + v*sqrt(L/g), a constant
    forward offset from the position. Analytic check with L and v known."""
    fs = 100.0
    t = np.arange(200) / fs
    v_mm_s = 30.0                      # 30 mm/s constant velocity (units: mm)
    x = v_mm_s * t                     # ramp
    L = 1.0                            # 1 m pendulum
    out = signal_ops.xcom(x, t, length_m=L)
    offset = v_mm_s * np.sqrt(L / G)   # mm
    # Interior points (central difference exact for a linear ramp).
    assert np.allclose(out[2:-2], x[2:-2] + offset, atol=1e-6)


def test_xcom_invalid_length_returns_nan():
    t = np.arange(10) / 100.0
    x = np.arange(10, dtype=float)
    out = signal_ops.xcom(x, t, length_m=0.0)
    assert np.all(np.isnan(out))
    out2 = signal_ops.xcom(x, t, length_m=-1.0)
    assert np.all(np.isnan(out2))


def test_xcom_unit_preserved():
    assert signal_ops.derive_unit("mm", "xcom") == "mm"


# --- pipeline integration ---------------------------------------------------

def _com_dataset(n=200, fs=100.0):
    com = np.zeros((n, 3))
    t = np.arange(n) / fs
    com[:, 0] = 30.0 * t              # x ramp at 30 mm/s
    com[:, 1] = 0.0
    com[:, 2] = 1000.0               # COM height 1000 mm = 1 m
    return {"time": t, "fs": fs, "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
            "model_result": {"angles": {"K": np.zeros(n)}, "time": t,
                             "com": {"com": com, "whole_body": True}}}


def test_xcom_compute_step_on_com_axis():
    ds = _com_dataset()
    p = Pipeline()
    p.add(ComputeStep(input="com:x", name="XCOM x", method="xcom",
                      params={"length_m": 1.0}))
    out = run_pipeline(ds, p)
    series = out["ctx"].signal("XCOM x")
    offset = 30.0 * np.sqrt(1.0 / G)
    expected = 30.0 * (np.arange(200) / 100.0) + offset
    assert np.allclose(series[2:-2], expected[2:-2], atol=1e-6)


def test_xcom_default_length_param():
    """Missing length_m -> NaN signal (we never guess a pendulum length)."""
    ds = _com_dataset()
    p = Pipeline()
    p.add(ComputeStep(input="com:x", name="XCOM x", method="xcom", params={}))
    out = run_pipeline(ds, p)
    series = out["ctx"].signal("XCOM x")
    assert np.all(np.isnan(series))
