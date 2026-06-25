import numpy as np
from core.normalize import resample_to_percent


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
