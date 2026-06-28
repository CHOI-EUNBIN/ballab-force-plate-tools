import numpy as np
import pytest
from core.ensemble import (pool, ensemble_stats, ensemble_csv,
                           pool_sources, ensemble_from_runs)


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


# --- pool_sources -----------------------------------------------------------

def test_pool_sources_pools_and_labels_columns():
    src = [
        ("A", {"matrix": np.zeros((3, 5))}),
        ("B", {"matrix": np.ones((2, 5))}),
    ]
    out = pool_sources(src)
    assert out["n"] == 5
    assert out["matrix"].shape == (5, 5)
    # column labels follow "<label>#<i+1>" per epoch
    assert out["columns"] == ["A#1", "A#2", "A#3", "B#1", "B#2"]
    # stats match pooling directly
    expect = ensemble_stats(np.vstack([np.zeros((3, 5)), np.ones((2, 5))]))
    assert np.allclose(out["stats"]["mean"], expect["mean"])
    assert out["stats"]["n"] == 5
    # mean at node 0 = (0*3 + 1*2)/5 = 0.4
    assert np.isclose(out["stats"]["mean"][0], 0.4)


def test_pool_sources_skips_empty_and_absent_matrices():
    src = [
        ("A", {"matrix": np.zeros((2, 4))}),
        ("empty", {"matrix": np.zeros((0, 4))}),   # zero-row -> skipped
        ("none", {}),                              # absent matrix -> skipped
        ("B", {"matrix": np.ones((1, 4))}),
    ]
    out = pool_sources(src)
    assert out["n"] == 3
    assert out["columns"] == ["A#1", "A#2", "B#1"]


def test_pool_sources_empty_gives_n_zero():
    out = pool_sources([])
    assert out["n"] == 0
    assert out["columns"] == []
    assert out["matrix"].shape == (0, 0)
    assert out["stats"]["n"] == 0


def test_pool_sources_width_mismatch_raises():
    src = [
        ("A", {"matrix": np.zeros((2, 5))}),
        ("B", {"matrix": np.zeros((1, 4))}),
    ]
    with pytest.raises(ValueError):
        pool_sources(src)


# --- subject-weighted pooling (mode="subject") ------------------------------

def test_pool_sources_subject_mode_unequal_counts():
    # Subject A: 3 cycles @0; Subject B: 1 cycle @10. Subject-weighting gives each
    # subject ONE vote -> mean = (0+10)/2 = 5, NOT the 4-row mean 2.5.
    src = [
        ("A1", {"matrix": np.zeros((3, 2))}, "A"),
        ("B1", {"matrix": np.full((1, 2), 10.0)}, "B"),
    ]
    out = pool_sources(src, mode="subject")
    np.testing.assert_allclose(out["stats"]["mean"], [5.0, 5.0])
    assert out["n_subjects"] == 2
    assert out["n_cycles"] == 4
    assert out["stats"]["n"] == 2            # two per-subject curves pooled


def test_pool_sources_cycle_mode_is_row_mean():
    # Same data, cycle mode (default) -> all 4 rows equally -> mean 2.5.
    src = [
        ("A1", {"matrix": np.zeros((3, 2))}, "A"),
        ("B1", {"matrix": np.full((1, 2), 10.0)}, "B"),
    ]
    out = pool_sources(src, mode="cycle")
    np.testing.assert_allclose(out["stats"]["mean"], [2.5, 2.5])
    assert out["n_cycles"] == 4
    assert out["n_subjects"] == 2


def test_pool_sources_subject_groups_multiple_trials_per_subject():
    # Subject A spread across two trials (2 + 1 cycles); B one trial. A's
    # representative = mean of its 3 cycles (0,0,6 -> 2); group = mean(2, 10) = 6.
    src = [
        ("A_walk1", {"matrix": np.array([[0.0], [0.0]])}, "A"),
        ("A_walk2", {"matrix": np.array([[6.0]])}, "A"),
        ("B_walk1", {"matrix": np.array([[10.0]])}, "B"),
    ]
    out = pool_sources(src, mode="subject")
    np.testing.assert_allclose(out["stats"]["mean"], [6.0])
    assert out["n_subjects"] == 2 and out["n_cycles"] == 4   # A:3 (2+1) + B:1


def test_pool_sources_subject_key_falls_back_to_label():
    # No subject id (2-tuples) -> each label is its own subject.
    src = [("t1", {"matrix": np.zeros((2, 1))}),
           ("t2", {"matrix": np.full((1, 1), 9.0)})]
    out = pool_sources(src, mode="subject")
    assert out["n_subjects"] == 2
    np.testing.assert_allclose(out["stats"]["mean"], [4.5])   # (0 + 9)/2


def test_pool_sources_subject_mode_nan_aware():
    # A subject whose column is all-NaN must not crash; the other carries it.
    src = [("A", {"matrix": np.array([[np.nan, 2.0]])}, "A"),
           ("B", {"matrix": np.array([[4.0, 4.0]])}, "B")]
    out = pool_sources(src, mode="subject")
    np.testing.assert_allclose(out["stats"]["mean"], [4.0, 3.0])


# --- ensemble_from_runs -----------------------------------------------------

def test_ensemble_from_runs_pulls_key_and_pools():
    runs = [
        ("trialA", {"normalized": {"Knee%": {"matrix": np.zeros((2, 3))}}}),
        ("trialB", {"normalized": {"Knee%": {"matrix": np.ones((3, 3))}}}),
    ]
    out = ensemble_from_runs(runs, "Knee%")
    assert out["n"] == 5
    assert out["columns"] == ["trialA#1", "trialA#2",
                              "trialB#1", "trialB#2", "trialB#3"]
    assert np.isclose(out["stats"]["mean"][0], 3 / 5)


def test_ensemble_from_runs_skips_runs_missing_key():
    runs = [
        ("has", {"normalized": {"Knee%": {"matrix": np.ones((2, 3))}}}),
        ("missing", {"normalized": {"Other%": {"matrix": np.ones((9, 3))}}}),
        ("nonorm", {}),
    ]
    out = ensemble_from_runs(runs, "Knee%")
    assert out["n"] == 2
    assert out["columns"] == ["has#1", "has#2"]


def test_ensemble_from_runs_empty_gives_n_zero():
    out = ensemble_from_runs([], "Knee%")
    assert out["n"] == 0
    assert out["columns"] == []


# --- integration: headless run -> ensemble, NO Qt, NO c3d -------------------

def _cyclic_dataset():
    # Like tests/test_run_normalize.py::_ramp_dataset, but a REPEATING ramp so
    # the threshold is crossed several times -> cycle mode yields >1 epoch.
    seg = np.arange(10, dtype=float)          # 0..9 ramp
    fz = np.tile(seg, 4)                       # 4 sub-ramps, 40 frames
    n = fz.size
    return {"time": np.arange(n) / 100.0, "fs": 100.0, "fz": fz}


def test_headless_run_to_ensemble_integration():
    from core.pipeline import Pipeline, DetectEventStep, NormalizeStep
    from core.run import run_pipeline

    ds = _cyclic_dataset()
    p = Pipeline()
    p.steps.append(DetectEventStep(
        input="fz", label="HS", method="threshold",
        params={"threshold": 5, "direction": "rising"},
        selector={"mode": "all"}))
    p.steps.append(NormalizeStep(input="fz", name="fz_cyc", mode="cycle",
                                 event="HS", points=11))
    out = run_pipeline(ds, p)

    per_trial = out["normalized"]["fz_cyc"]["matrix"]
    assert per_trial.shape[0] > 0

    ens = ensemble_from_runs([("trialA", out), ("trialB", out)], "fz_cyc")
    # two identical runs -> twice the per-trial epoch count
    assert ens["n"] == 2 * per_trial.shape[0]

    # stats must match pooling the two matrices directly
    direct = ensemble_stats(np.vstack([per_trial, per_trial]))
    assert np.allclose(ens["stats"]["mean"], direct["mean"], equal_nan=True)
    assert np.allclose(ens["stats"]["sd"], direct["sd"], equal_nan=True)
