import numpy as np
import pytest
from core.ensemble import pool, ensemble_stats


def test_pool_stacks_and_skips_empty():
    a = np.ones((2, 5)); b = np.zeros((3, 5)); c = np.empty((0, 5))
    out = pool([a, c, b])
    assert out.shape == (5, 5)


def test_pool_raises_on_width_mismatch():
    with pytest.raises(ValueError):
        pool([np.ones((1, 5)), np.ones((1, 6))])


def test_ensemble_stats_mean_sd_n():
    m = np.array([[0.0, 2.0], [2.0, 4.0]])
    s = ensemble_stats(m)
    assert np.allclose(s["mean"], [1.0, 3.0])
    assert np.allclose(s["sd"], [np.sqrt(2), np.sqrt(2)])     # ddof=1
    assert s["n"] == 2
    assert np.allclose(s["x"], [0.0, 100.0])


def test_ensemble_stats_nan_aware_and_n1():
    s = ensemble_stats(np.array([[1.0, np.nan, 3.0]]))
    assert np.allclose(s["sd"], [0.0, 0.0, 0.0])             # n=1 -> sd 0
    assert s["n"] == 1


def test_ensemble_stats_empty():
    s = ensemble_stats(np.empty((0, 0)))
    assert s["n"] == 0
