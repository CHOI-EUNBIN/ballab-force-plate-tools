"""Regression tests for the Phase A filter-as-first-class additions:
``FilterSpec`` and ``Workspace`` in core.signals.

Pins that the workspace serves raw keys identically to ``signal_series`` and
that "<key>:filt" matches a direct ``apply_lowpass``/``filter_marker_data`` call
(so absorbing the scattered UI filter calls is numerically a no-op).
"""

import numpy as np
import pytest
from scipy.integrate import cumulative_trapezoid

from core.pipeline import ComputeStep, FilterStep, Pipeline
from core.signal_proc import apply_lowpass, filter_marker_data
from core.signals import FilterSpec, Workspace, signal_catalog, signal_series


def _dataset(n=500, fs=100.0):
    t = np.arange(n) / fs
    # Sine + high-freq wiggle so a low-pass visibly changes the signal.
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


# -- FilterSpec --------------------------------------------------------------

def test_filterspec_apply_matches_apply_lowpass():
    ds = _dataset()
    spec = FilterSpec(type="Butterworth", cutoff_hz=10.0, order=4)
    got = spec.apply(ds["cop_ap"], ds["fs"])
    want = apply_lowpass(ds["cop_ap"], 10.0, ds["fs"], 4, "Butterworth", 0.5)
    np.testing.assert_allclose(got, want, atol=1e-9, rtol=0)


def test_filterspec_apply_marker_matches_filter_marker_data():
    fs = 100.0
    F = 300
    t = np.arange(F) / fs
    data = np.zeros((2, F, 3))
    data[0, :, 0] = np.sin(2 * np.pi * 1.0 * t) + 0.3 * np.sin(2 * np.pi * 20 * t)
    data[1, :, 1] = np.cos(2 * np.pi * 0.5 * t)
    spec = FilterSpec(cutoff_hz=6.0, order=4)
    got = spec.apply_marker(data, fs)
    want = filter_marker_data(data, fs, 6.0, 4, "Butterworth")
    np.testing.assert_allclose(got, want, atol=1e-9, rtol=0)


def test_filterspec_is_hashable():
    spec = FilterSpec(cutoff_hz=6.0)
    # frozen dataclass -> usable as a dict key / cache key.
    {spec: 1}
    assert spec.cache_key() == ("Butterworth", 6.0, 4, 0.5)


# -- Workspace raw passthrough ----------------------------------------------

def test_workspace_raw_matches_signal_series():
    ds = _dataset()
    ws = Workspace(ds)
    for key in ("time", "cop", "cop_ap", "cop_ml", "fx", "fy", "fz"):
        np.testing.assert_array_equal(ws.series(key), signal_series(ds, key))


def test_workspace_caches_series_identity():
    ds = _dataset()
    ws = Workspace(ds)
    a = ws.series("cop_ap")
    b = ws.series("cop_ap")
    assert a is b  # same array object returned from cache


# -- Workspace filtered derivative ------------------------------------------

def test_workspace_filt_matches_direct_apply_lowpass():
    ds = _dataset()
    spec = FilterSpec(type="Butterworth", cutoff_hz=10.0, order=4)
    ws = Workspace(ds, filter_spec=spec)
    got = ws.series("cop_ap:filt")
    want = apply_lowpass(ds["cop_ap"], 10.0, ds["fs"], 4, "Butterworth", 0.5)
    np.testing.assert_allclose(got, want, atol=1e-9, rtol=0)


def test_workspace_filt_without_spec_returns_raw():
    ds = _dataset()
    ws = Workspace(ds, filter_spec=None)
    np.testing.assert_array_equal(ws.series("cop_ap:filt"), ds["cop_ap"])


def test_workspace_fs_default_and_override():
    ds = _dataset(fs=100.0)
    assert Workspace(ds).fs == 100.0
    ds2 = {"time": np.arange(10) / 50.0}  # no "fs" -> default 1000
    assert Workspace(ds2).fs == 1000.0
    assert Workspace(ds, fs=200.0).fs == 200.0


# -- Workspace marker data ---------------------------------------------------

def _marker_dataset(F=300, rate=100.0):
    t = np.arange(F) / rate
    data = np.zeros((2, F, 3))
    data[0, :, 0] = np.sin(2 * np.pi * 1.0 * t) + 0.3 * np.sin(2 * np.pi * 20 * t)
    data[1, :, 1] = np.cos(2 * np.pi * 0.5 * t)
    ds = {
        "time": t,
        "fs": rate,
        "cop_ap": np.zeros(F),
        "cop_ml": np.zeros(F),
        "markers": {"labels": ["A", "B"], "data": data, "time": t, "rate": rate},
    }
    return ds, data


def test_workspace_filtered_marker_matches_direct():
    ds, data = _marker_dataset()
    spec = FilterSpec(cutoff_hz=6.0, order=4)
    ws = Workspace(ds, filter_spec=spec)
    got = ws.filtered_marker_data()
    want = filter_marker_data(data, ds["markers"]["rate"], 6.0, 4, "Butterworth")
    np.testing.assert_allclose(got, want, atol=1e-9, rtol=0)


def test_workspace_filtered_marker_without_spec_is_raw():
    ds, data = _marker_dataset()
    ws = Workspace(ds, filter_spec=None)
    assert ws.filtered_marker_data() is data


def test_workspace_filtered_marker_cached():
    ds, _ = _marker_dataset()
    ws = Workspace(ds, filter_spec=FilterSpec(cutoff_hz=6.0))
    assert ws.filtered_marker_data() is ws.filtered_marker_data()


# -- Workspace ComputeStep-produced signals (on-demand) ----------------------
#
# The view path (graph / value table) reads every signal through the Workspace,
# so a ComputeStep output must be resolvable there too — not only inside a full
# pipeline run. These pin each method against its raw signal_ops equivalent.

def _plate_dataset(n=200, fs=100.0):
    """A single-plate dataset whose Fz is the raw (down-negative) C3D form."""
    t = np.arange(n) / fs
    fz = -(np.abs(np.sin(2 * np.pi * 1.0 * t)) * 500.0)   # down-negative vGRF
    return {
        "time": t, "fs": fs,
        "cop_ap": np.zeros(n), "cop_ml": np.zeros(n),
        "fz": fz, "fp1:fz": fz,
        "fp1:fx": np.full(n, 3.0), "fp1:fy": np.full(n, 4.0),
        "n_force_plates": 1,
    }, t, fz


def test_workspace_compute_abs():
    ds, _, fz = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="abs", name="FP1 Fz |abs|")])
    ws = Workspace(ds, pipeline=p)
    got = ws.series("FP1 Fz |abs|")
    np.testing.assert_allclose(got, np.abs(fz))
    assert np.all(got >= 0)
    assert ws.unit_for_key("FP1 Fz |abs|") == "N"


def test_workspace_compute_derivative():
    ds, t, fz = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="derivative", name="dFz",
                              params={"order": 1})])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("dFz"), np.gradient(fz, t))
    assert ws.unit_for_key("dFz") == "N/s"


def test_workspace_compute_integral():
    ds, t, fz = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="integral", name="impulse",
                              params={"sign": "all"})])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("impulse"),
                               cumulative_trapezoid(fz, t, initial=0.0))
    assert ws.unit_for_key("impulse") == "N*s"


def test_workspace_compute_magnitude():
    ds, _, _ = _plate_dataset()
    # fx=3, fy=4, fz=0 -> resultant 5 everywhere.
    ds = dict(ds); ds["fp1:fz"] = np.zeros_like(ds["fp1:fz"])
    p = Pipeline([ComputeStep(input="fp1:fx", method="magnitude", name="Fres",
                              inputs=["fp1:fy", "fp1:fz"])])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("Fres"), 5.0)


def test_workspace_compute_normalize_const():
    ds, _, fz = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="normalize", name="Fz_n",
                              by=100.0)])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("Fz_n"), fz / 100.0)
    assert ws.unit_for_key("Fz_n") == ""   # ratio is dimensionless


def test_workspace_compute_normalize_by_metric_raises():
    # A metric divisor only exists during a pipeline RUN; the Workspace can't
    # resolve it, so series() raises (caller shows empty/NaN, not a wrong value).
    ds, _, _ = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="normalize", name="Fz_bw",
                              by="metric:bodyweight")])
    ws = Workspace(ds, pipeline=p)
    with pytest.raises(ValueError):
        ws.series("Fz_bw")


def test_workspace_compute_chain_filt_then_compute():
    ds, _, _ = _plate_dataset()
    spec = FilterSpec(cutoff_hz=10.0, order=4)
    p = Pipeline([FilterStep(spec=spec, targets=["fp1:fz"]),
                  ComputeStep(input="fp1:fz:filt", method="abs", name="absfilt")])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("absfilt"),
                               np.abs(ws.series("fp1:fz:filt")))


def test_workspace_compute_chain_compute_then_compute():
    ds, t, fz = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="abs", name="a1"),
                  ComputeStep(input="a1", method="derivative", name="a2")])
    ws = Workspace(ds, pipeline=p)
    np.testing.assert_allclose(ws.series("a2"), np.gradient(np.abs(fz), t))


def test_workspace_compute_circular_reference_raises():
    ds, _, _ = _plate_dataset()
    p = Pipeline([ComputeStep(input="c", method="abs", name="c")])  # c -> c
    ws = Workspace(ds, pipeline=p)
    with pytest.raises(ValueError):
        ws.series("c")


def test_workspace_compute_unknown_key_still_raises():
    # A bare unknown key (no matching ComputeStep) keeps the old error.
    ds, _, _ = _plate_dataset()
    ws = Workspace(ds, pipeline=Pipeline([]))
    with pytest.raises(ValueError):
        ws.series("does_not_exist")


def test_signal_catalog_lists_compute_output():
    ds, _, _ = _plate_dataset()
    p = Pipeline([ComputeStep(input="fp1:fz", method="abs", name="FP1 Fz |abs|")])
    cat = dict(signal_catalog(ds, pipeline=p))
    assert cat.get("FP1 Fz |abs|") == "FP1 Fz |abs|"
