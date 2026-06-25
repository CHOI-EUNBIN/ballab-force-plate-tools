import numpy as np
import pytest
from core.ensemble import pool, ensemble_stats, ensemble_csv


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


def test_ensemble_csv_shape_and_header():
    m = np.array([[0.0, 2.0], [2.0, 4.0]])   # 2 epochs x 2 nodes
    s = ensemble_stats(m)
    text = ensemble_csv(m, s, columns=["A", "B"])
    lines = text.strip().splitlines()
    assert lines[0] == "percent,A,B,mean,sd"
    assert len(lines) == 1 + 2                 # header + 2 phase nodes
    # node 0: epochs 0 and 2 -> mean 1
    assert lines[1].startswith("0.0,0.0,2.0,1.0,")
