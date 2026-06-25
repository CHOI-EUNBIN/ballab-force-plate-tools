import numpy as np
from core.normalize import resample_to_percent, epoch_windows, extract_epochs


def test_resample_ramp_hits_endpoints_and_midpoint():
    out = resample_to_percent(np.linspace(0.0, 10.0, 11), points=101)
    assert out.shape == (101,)
    assert np.isclose(out[0], 0.0)
    assert np.isclose(out[50], 5.0)
    assert np.isclose(out[100], 10.0)


def test_resample_interpolates_interior_nan():
    v = np.array([0.0, np.nan, 2.0])          # interior NaN bounded by finite
    out = resample_to_percent(v, points=3)
    assert np.allclose(out, [0.0, 1.0, 2.0])


def test_resample_all_nan_or_too_short_is_nan():
    assert np.all(np.isnan(resample_to_percent(np.array([np.nan, np.nan]), 5)))
    assert np.all(np.isnan(resample_to_percent(np.array([1.0]), 5)))


def test_epoch_windows_cycle_pairs_consecutive_same_event():
    events = {"HS": np.array([0, 10, 20])}
    w = epoch_windows(np.arange(30), events, "cycle", start_event="HS")
    assert w == [(0, 10), (10, 20)]


def test_epoch_windows_window_pairs_start_to_end():
    events = {"ON": np.array([0, 20]), "OFF": np.array([8, 28])}
    w = epoch_windows(np.arange(30), events, "window",
                      start_event="ON", end_event="OFF")
    assert w == [(0, 8), (20, 28)]


def test_epoch_windows_trial_is_whole():
    assert epoch_windows(np.arange(30), {}, "trial") == [(0, 29)]


def test_epoch_windows_missing_event_is_empty():
    assert epoch_windows(np.arange(30), {}, "cycle", start_event="HS") == []


def test_extract_epochs_resamples_each_window():
    values = np.arange(21, dtype=float)         # 0..20
    matrix, meta = extract_epochs(values, [(0, 10), (10, 20)], points=11)
    assert matrix.shape == (2, 11)
    assert np.isclose(matrix[0, 0], 0.0) and np.isclose(matrix[0, -1], 10.0)
    assert meta == [{"start": 0, "end": 10}, {"start": 10, "end": 20}]
