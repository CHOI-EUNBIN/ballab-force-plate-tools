import numpy as np
from core.pipeline import Pipeline, DetectEventStep, NormalizeStep
from core.run import run_pipeline


def _ramp_dataset():
    # 30 frames; a signal that ramps 0..29 so each HS->HS epoch is a sub-ramp.
    n = 30
    return {"time": np.arange(n) / 100.0, "fs": 100.0,
            "fz": np.arange(n, dtype=float)}


def test_normalize_step_emits_epoch_matrix():
    ds = _ramp_dataset()
    p = Pipeline()
    p.steps.append(DetectEventStep(
        input="fz", label="HS", method="threshold",
        params={"threshold": 5, "direction": "rising"}, selector={"mode": "all"}))
    p.steps.append(NormalizeStep(input="fz", name="fz_cyc", mode="cycle",
                                 event="HS", points=11))
    out = run_pipeline(ds, p)
    assert "normalized" in out
    norm = out["normalized"]["fz_cyc"]
    assert norm["matrix"].ndim == 2 and norm["matrix"].shape[1] == 11
    assert norm["label"] == "fz" and norm["mode"] == "cycle"
