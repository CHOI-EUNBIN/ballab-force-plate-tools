# Time-Normalization + Ensemble Curves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Time-normalize a chosen signal/angle to 0–100% per movement epoch, pool epochs across the user's selected trials into a mean ± SD ensemble curve, shown as a graph and exportable as CSV.

**Architecture:** Three layers — (1) per-trial epoch extraction as a pipeline `NormalizeStep` (`core/normalize.py`), (2) cross-trial pooling/stats (`core/ensemble.py`), (3) an Analyze "Ensemble" panel that plots mean ± SD and writes CSV. Layers 1–2 are pure/headless and TDD-first; layer 3 is the Qt surface.

**Tech Stack:** Python 3.11, NumPy, PyQt6, pyqtgraph, pytest.

## Global Constraints

- Pure engine code in `core/` is UI-free (no Qt imports) and NaN-safe.
- Raw participant data is never mutated; derived artifacts are additive.
- Reuse `core.metrics_compute.cycles_from_events` for event pairing — do not reimplement.
- Signals are read through `RunContext.signal(key)` so `:filt` / `angle:*` keys flow (a marker filter must reach the normalized curve).
- Default epoch resolution `points = 101` (0–100% inclusive).
- Ensemble is **epoch-weighted** (each pooled epoch counts equally); SD uses `ddof=1` (sample SD), `0` when n=1.
- All existing tests stay green (`pytest -q`).
- Qt tests run offscreen: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` before importing `QApplication`; define a module-scope `app` fixture `QApplication.instance() or QApplication(sys.argv)`.

---

### Task 1: `resample_to_percent` (epoch → 101 nodes)

**Files:**
- Create: `core/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `resample_to_percent(values, points=101) -> np.ndarray` (shape `(points,)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalize.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py -q`
Expected: FAIL with `ModuleNotFoundError: core.normalize`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/normalize.py
"""Time-normalization of signal epochs to 0-100% phase (pure / NaN-safe).

An *epoch* is one movement segment (a gait cycle, a discrete rep, or a whole
trial). Each epoch is resampled onto evenly spaced 0-100% phase nodes so epochs
of different durations become comparable and poolable (see core.ensemble).
"""
import numpy as np


def resample_to_percent(values, points=101):
    """Resample a 1-D epoch to ``points`` evenly spaced 0-100% phase nodes.

    Interior NaNs bounded by finite samples are linearly interpolated across;
    nodes outside the finite span (leading/trailing NaN) stay NaN (no
    extrapolation). ``n < 2`` finite samples -> all-NaN row.
    """
    v = np.asarray(values, float)
    out = np.full(points, np.nan)
    if v.size < 2:
        return out
    finite = np.isfinite(v)
    if finite.sum() < 2:
        return out
    src_x = np.linspace(0.0, 1.0, v.size)
    dst_x = np.linspace(0.0, 1.0, points)
    out = np.interp(dst_x, src_x[finite], v[finite])
    lo, hi = src_x[finite][0], src_x[finite][-1]
    out[(dst_x < lo) | (dst_x > hi)] = np.nan
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): resample_to_percent for 0-100% epoch phase"
```

---

### Task 2: `epoch_windows` + `extract_epochs`

**Files:**
- Modify: `core/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `core.metrics_compute.cycles_from_events(start_frames, end_frames) -> list[(int,int)]`; `resample_to_percent` (Task 1).
- Produces:
  - `epoch_windows(time, events, mode, start_event=None, end_event=None) -> list[(int,int)]`
  - `extract_epochs(values, windows, points=101) -> (np.ndarray[N,points], list[dict])`
    where each meta dict is `{"start": int, "end": int}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_normalize.py
from core.normalize import epoch_windows, extract_epochs


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py -q`
Expected: FAIL with `ImportError: cannot import name 'epoch_windows'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to core/normalize.py
from core.metrics_compute import cycles_from_events


def epoch_windows(time, events, mode, start_event=None, end_event=None):
    """Frame-index windows ``[(i0, i1), ...]`` for the chosen epoch mode.

    ``events`` = ``{label: frame ndarray}``.
      "cycle"  -> consecutive same event: pairs of ``events[start_event]``.
      "window" -> ``events[start_event][k]`` to the next ``events[end_event]`` after it.
      "trial"  -> one whole-trial window ``[0, len(time)-1]``.
    Empty / short inputs -> ``[]``.
    """
    n = len(np.asarray(time))
    if mode == "trial":
        return [(0, n - 1)] if n >= 2 else []
    if mode == "cycle":
        f = events.get(start_event)
        if f is None or len(f) < 2:
            return []
        return cycles_from_events(f, f)
    if mode == "window":
        s = events.get(start_event)
        e = events.get(end_event)
        if s is None or e is None or len(s) == 0 or len(e) == 0:
            return []
        return cycles_from_events(s, e)
    return []


def extract_epochs(values, windows, points=101):
    """``(matrix[N, points], meta)`` resampling ``values[i0:i1+1]`` per window.

    Windows shorter than 2 samples are skipped. ``meta`` = list of
    ``{"start": i0, "end": i1}`` aligned with the matrix rows.
    """
    v = np.asarray(values, float)
    rows, meta = [], []
    for (i0, i1) in windows:
        seg = v[i0:i1 + 1]
        if seg.size < 2:
            continue
        rows.append(resample_to_percent(seg, points))
        meta.append({"start": int(i0), "end": int(i1)})
    matrix = np.vstack(rows) if rows else np.empty((0, points))
    return matrix, meta
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add core/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): epoch_windows + extract_epochs"
```

---

### Task 3: `core/ensemble.py` (pool + stats)

**Files:**
- Create: `core/ensemble.py`
- Test: `tests/test_ensemble.py`

**Interfaces:**
- Produces:
  - `pool(matrices: list[np.ndarray]) -> np.ndarray` (vstack of `(N_i, P)` → `(ΣN_i, P)`).
  - `ensemble_stats(matrix) -> {"mean": (P,), "sd": (P,), "n": int, "x": (P,)}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ensemble.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ensemble.py -q`
Expected: FAIL with `ModuleNotFoundError: core.ensemble`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/ensemble.py
"""Cross-trial ensemble of time-normalized epochs (pure / NaN-safe).

Pools epoch matrices (each ``(N_i, P)`` from core.normalize.extract_epochs) from
the user's selected trials and reduces them to an epoch-weighted mean +/- SD
curve over the 0-100% phase nodes.
"""
import numpy as np


def pool(matrices):
    """Vertically stack compatible ``(N_i, P)`` epoch matrices into ``(sum N_i, P)``.

    Skips empties; raises ``ValueError`` on a column-count (P) mismatch.
    """
    mats = []
    for m in matrices:
        m = np.asarray(m, float)
        if m.ndim == 2 and m.shape[0] > 0:
            mats.append(m)
    if not mats:
        return np.empty((0, 0))
    p = mats[0].shape[1]
    for m in mats:
        if m.shape[1] != p:
            raise ValueError(f"epoch width mismatch: {m.shape[1]} != {p}")
    return np.vstack(mats)


def ensemble_stats(matrix):
    """Epoch-weighted, NaN-aware mean/SD over a ``(N, P)`` pooled matrix.

    Returns ``{"mean": (P,), "sd": (P,), "n": N, "x": (P,)}`` where ``x`` is the
    0-100 percent axis. SD is sample SD (ddof=1); 0 when N=1; empty when N=0.
    """
    m = np.asarray(matrix, float)
    if m.ndim != 2 or m.shape[0] == 0:
        empty = np.array([])
        return {"mean": empty, "sd": empty, "n": 0, "x": empty}
    p = m.shape[1]
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(m, axis=0)
        sd = np.nanstd(m, axis=0, ddof=1) if m.shape[0] > 1 else np.zeros(p)
    return {"mean": mean, "sd": sd, "n": int(m.shape[0]),
            "x": np.linspace(0.0, 100.0, p)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ensemble.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/ensemble.py tests/test_ensemble.py
git commit -m "feat(ensemble): pool + epoch-weighted mean/SD stats"
```

---

### Task 4: `NormalizeStep` pipeline step

**Files:**
- Modify: `core/pipeline.py` (add class near the other steps; register in `_STEP_TYPES` at line ~634)
- Test: `tests/test_pipeline_normalize_step.py`

**Interfaces:**
- Consumes: `PipelineStep` base, `EVENT_PREFIX` (both in `core/pipeline.py`).
- Produces: `NormalizeStep(input, name, mode, event, start_event, end_event, points, enabled)` with `kind="normalize"`, `stage="normalize"`, `produces()/requires()/to_dict()/from_dict()`; module constant `NORMALIZE_MODES = ("cycle", "window", "trial")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_normalize_step.py
from core.pipeline import NormalizeStep, PipelineStep


def test_normalize_step_produces_and_requires_cycle():
    s = NormalizeStep(input="angle:R_KNEE_FE", name="knee_cycle",
                      mode="cycle", event="HS")
    assert s.kind == "normalize" and s.stage == "normalize"
    assert s.produces() == {"norm:knee_cycle"}
    assert s.requires() == {"angle:R_KNEE_FE", "event:HS"}


def test_normalize_step_window_requires_both_events():
    s = NormalizeStep(input="fz:filt", name="jump", mode="window",
                      start_event="ON", end_event="OFF")
    assert s.requires() == {"fz:filt", "event:ON", "event:OFF"}


def test_normalize_step_roundtrip():
    s = NormalizeStep(input="fz", name="n", mode="trial", points=51)
    d = s.to_dict()
    s2 = PipelineStep.from_dict(d)
    assert isinstance(s2, NormalizeStep)
    assert (s2.input, s2.name, s2.mode, s2.points) == ("fz", "n", "trial", 51)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_normalize_step.py -q`
Expected: FAIL with `ImportError: cannot import name 'NormalizeStep'`.

- [ ] **Step 3: Write minimal implementation**

Add this class to `core/pipeline.py` immediately after the `ComputeAngleStep` class (before the `_STEP_TYPES` assignment):

```python
NORMALIZE_MODES = ("cycle", "window", "trial")


class NormalizeStep(PipelineStep):
    """Time-normalize one signal to 0-100% phase per epoch (the ``normalize``
    stage). Produces a per-trial epoch matrix consumed by the cross-trial
    ensemble panel; see core.normalize / core.ensemble.

    Fields:
      - ``input``       — a catalog signal key (``angle:R_KNEE_FE``, ``fz:filt``).
      - ``name``        — output name; the artifact is ``norm:<name>``.
      - ``mode``        — ``"cycle"`` (consecutive ``event``) | ``"window"``
                          (``start_event`` -> ``end_event``) | ``"trial"`` (whole).
      - ``event``       — start label for ``cycle`` mode.
      - ``start_event`` / ``end_event`` — labels for ``window`` mode.
      - ``points``      — phase nodes (default 101).
    """

    kind = "normalize"
    stage = "normalize"

    def __init__(self, input=None, name="", mode="cycle", event=None,
                 start_event=None, end_event=None, points=101, enabled=True):
        self.input = input or ""
        self.name = name or ""
        self.mode = mode if mode in NORMALIZE_MODES else "cycle"
        self.event = event or ""
        self.start_event = start_event or ""
        self.end_event = end_event or ""
        try:
            self.points = int(points)
        except (TypeError, ValueError):
            self.points = 101
        if self.points < 2:
            self.points = 101
        self.enabled = bool(enabled)

    def produces(self):
        return {f"norm:{self.name}"} if self.name else set()

    def requires(self):
        req = set()
        if self.input:
            req.add(self.input)
        if self.mode == "cycle" and self.event:
            req.add(f"{EVENT_PREFIX}{self.event}")
        if self.mode == "window":
            if self.start_event:
                req.add(f"{EVENT_PREFIX}{self.start_event}")
            if self.end_event:
                req.add(f"{EVENT_PREFIX}{self.end_event}")
        return req

    def to_dict(self):
        return {"kind": self.kind, "input": self.input, "name": self.name,
                "mode": self.mode, "event": self.event,
                "start_event": self.start_event, "end_event": self.end_event,
                "points": self.points, "enabled": self.enabled}

    @staticmethod
    def from_dict(data):
        return NormalizeStep(
            input=data.get("input"), name=data.get("name", ""),
            mode=data.get("mode", "cycle"), event=data.get("event"),
            start_event=data.get("start_event"), end_event=data.get("end_event"),
            points=data.get("points", 101), enabled=data.get("enabled", True))
```

Then extend the `_STEP_TYPES` dict (line ~634) to register it. Change:

```python
_STEP_TYPES = {FilterStep.kind: FilterStep, DetectEventStep.kind: DetectEventStep,
```

so the dict also contains:

```python
               NormalizeStep.kind: NormalizeStep,
```

(add the entry alongside the existing ones; keep the others unchanged).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_normalize_step.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/pipeline.py tests/test_pipeline_normalize_step.py
git commit -m "feat(pipeline): NormalizeStep (normalize stage) + registry"
```

---

### Task 5: Execute `NormalizeStep` in `run.py`

**Files:**
- Modify: `core/run.py` (`run_pipeline` loop + new `_run_normalize`)
- Test: `tests/test_run_normalize.py`

**Interfaces:**
- Consumes: `RunContext.signal(key)`, `RunContext.event(label)`, `RunContext.time`; `core.normalize.epoch_windows`/`extract_epochs`; `NormalizeStep`.
- Produces: `run_pipeline(...)` result gains key `"normalized"` = `{name: {"matrix": (N,P), "meta": [...], "label": input, "points": P, "mode": mode}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_normalize.py
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
```

(If the threshold detector yields <2 HS on this ramp, the test still asserts the
key exists with a `(0, 11)` matrix — both are valid; the assertion only checks
shape width and metadata, not epoch count.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_normalize.py -q`
Expected: FAIL with `KeyError: 'normalized'`.

- [ ] **Step 3: Write minimal implementation**

Add the helper near `_run_compute` in `core/run.py`:

```python
def _run_normalize(ctx, step):
    """NormalizeStep: extract the trial's 0-100% epoch matrix for one signal.

    Returns ``{"matrix", "meta", "label", "points", "mode"}`` or ``None`` when the
    step is incomplete or its input signal is unavailable.
    """
    from core.normalize import epoch_windows, extract_epochs
    if not step.name or not step.input:
        return None
    try:
        values = ctx.signal(step.input)
    except Exception:
        return None
    if values is None:
        return None
    if step.mode == "cycle":
        start_lab, end_lab = step.event, step.event
    elif step.mode == "window":
        start_lab, end_lab = step.start_event, step.end_event
    else:
        start_lab = end_lab = None
    events = {}
    for lab in (start_lab, end_lab):
        if lab:
            fr = ctx.event(lab)
            if fr is not None:
                events[lab] = fr
    windows = epoch_windows(ctx.time, events, step.mode,
                            start_event=start_lab, end_event=end_lab)
    matrix, meta = extract_epochs(np.asarray(values, float), windows, step.points)
    return {"matrix": matrix, "meta": meta, "label": step.input,
            "points": step.points, "mode": step.mode}
```

In `run_pipeline`, import `NormalizeStep` at the top with the other step imports, initialize a `normalized = {}` dict just before the `for step in pipeline.steps:` loop, add a dispatch branch inside the loop, and include it in the return dict:

```python
            elif isinstance(step, NormalizeStep):
                res = _run_normalize(ctx, step)
                if res is not None and step.name:
                    normalized[step.name] = res
```

```python
    return {"ctx": ctx, "metrics": metrics, "metric_values": metric_values,
            "events": ctx._events, "normalized": normalized}
```

(Match the exact existing `return {...}` keys in this file; add `"normalized": normalized` to it. If `"events"` is not already a return key, leave the existing keys as-is and only append `"normalized"`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_run_normalize.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all green — no regressions).

- [ ] **Step 6: Commit**

```bash
git add core/run.py tests/test_run_normalize.py
git commit -m "feat(run): execute NormalizeStep -> per-trial epoch matrix"
```

---

### Task 6: Ensemble CSV writer (pure)

**Files:**
- Modify: `core/ensemble.py`
- Test: `tests/test_ensemble.py`

**Interfaces:**
- Consumes: `ensemble_stats` (Task 3).
- Produces: `ensemble_csv(matrix, stats, columns=None) -> str` — CSV text: header `percent,<col1>,...,<colK>,mean,sd`; one row per phase node.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ensemble.py
from core.ensemble import ensemble_csv


def test_ensemble_csv_shape_and_header():
    m = np.array([[0.0, 2.0], [2.0, 4.0]])   # 2 epochs x 2 nodes
    s = ensemble_stats(m)
    text = ensemble_csv(m, s, columns=["A", "B"])
    lines = text.strip().splitlines()
    assert lines[0] == "percent,A,B,mean,sd"
    assert len(lines) == 1 + 2                 # header + 2 phase nodes
    # node 0: epochs 0 and 2 -> mean 1
    assert lines[1].startswith("0.0,0.0,2.0,1.0,")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ensemble.py::test_ensemble_csv_shape_and_header -q`
Expected: FAIL with `ImportError: cannot import name 'ensemble_csv'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to core/ensemble.py
def ensemble_csv(matrix, stats, columns=None):
    """CSV text for a pooled ensemble: rows = phase nodes (0-100%), columns =
    each epoch + mean + sd. ``columns`` labels the K epoch columns (defaults to
    ``epoch_1..epoch_K``). One node per row; values are the transpose of
    ``matrix`` (which is epochs x nodes)."""
    m = np.asarray(matrix, float)
    k = m.shape[0] if m.ndim == 2 else 0
    cols = list(columns) if columns is not None else [f"epoch_{i+1}" for i in range(k)]
    x = stats.get("x")
    mean = stats.get("mean")
    sd = stats.get("sd")
    header = ",".join(["percent", *cols, "mean", "sd"])
    out = [header]
    p = len(x) if x is not None else 0
    for node in range(p):
        cells = [f"{x[node]}"]
        for e in range(k):
            cells.append(f"{m[e, node]}")
        cells.append(f"{mean[node]}")
        cells.append(f"{sd[node]}")
        out.append(",".join(cells))
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ensemble.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add core/ensemble.py tests/test_ensemble.py
git commit -m "feat(ensemble): ensemble_csv writer (epochs + mean + sd)"
```

---

### Task 7: Analyze "Ensemble" panel + NormalizeStep dialog (UI)

**Files:**
- Create: `ui/ensemble_panel.py` (the panel widget + add/edit `NormalizeStep` dialog)
- Modify: `ui/analyze_dialogs.py` (register `NormalizeStepDialog` import is optional — keep the dialog in `ensemble_panel.py` to stay focused)
- Modify: `ui/analyze_tab.py` (wire an "Add Normalize step" path + an Ensemble panel host) — follow the existing `_add_metric_step` pattern
- Test: `tests/test_ensemble_panel.py`

**Interfaces:**
- Consumes: `core.ensemble.pool`, `core.ensemble.ensemble_stats`, `core.ensemble.ensemble_csv`; per-trial `run_pipeline(...)["normalized"][name]`; `ui.components.cascading_signal_picker.CascadingSignalPicker`.
- Produces: `EnsemblePanel(parent)` with `set_sources(list_of_(file_label, norm_dict))` and `export_csv(path)`; `NormalizeStepDialog(parent, inputs, event_labels, step=None)` with `values() -> dict` suitable for `NormalizeStep(**values)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ensemble_panel.py
import os
import sys
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_panel_pools_sources_and_reports_n(app):
    from ui.ensemble_panel import EnsemblePanel
    panel = EnsemblePanel(None)
    src = [
        ("c3d_1", {"matrix": np.zeros((3, 101)), "label": "angle:R_KNEE_FE"}),
        ("c3d_2", {"matrix": np.ones((2, 101)),  "label": "angle:R_KNEE_FE"}),
    ]
    panel.set_sources(src)
    assert panel.n_epochs() == 5            # 3 + 2 pooled
    # mean at node 0 = (0*3 + 1*2)/5 = 0.4
    assert np.isclose(panel.stats()["mean"][0], 0.4)


def test_panel_export_csv_writes_file(app, tmp_path):
    from ui.ensemble_panel import EnsemblePanel
    panel = EnsemblePanel(None)
    panel.set_sources([("t", {"matrix": np.arange(202.0).reshape(2, 101),
                              "label": "fz"})])
    out = tmp_path / "ens.csv"
    panel.export_csv(str(out))
    text = out.read_text()
    assert text.splitlines()[0].startswith("percent,")
    assert "mean,sd" in text.splitlines()[0]


def test_normalize_dialog_values_roundtrip(app):
    from ui.ensemble_panel import NormalizeStepDialog
    from core.pipeline import NormalizeStep
    d = NormalizeStepDialog(None, [("fz", "Fz"), ("fz:filt", "Fz (filtered)")],
                            ["HS", "TO"])
    vals = d.values()
    step = NormalizeStep(**vals)               # must construct without error
    assert step.kind == "normalize"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ensemble_panel.py -q`
Expected: FAIL with `ModuleNotFoundError: ui.ensemble_panel`.

- [ ] **Step 3: Write minimal implementation**

```python
# ui/ensemble_panel.py
"""Cross-trial ensemble: pool per-trial normalized epoch matrices, plot mean +/-
SD over 0-100% phase, and export CSV. Plus the add/edit NormalizeStep dialog.

UI-thin: all math is in core.ensemble / core.normalize. The panel is fed
``(file_label, norm_dict)`` sources by the Analyze tab (one per checked trial
that produced the chosen NormalizeStep output).
"""
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QDialog, QLineEdit, QSpinBox, QFormLayout, QDialogButtonBox,
)

from core.ensemble import pool, ensemble_stats, ensemble_csv
from ui.components.cascading_signal_picker import CascadingSignalPicker


class EnsemblePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources = []          # list of (label, norm_dict)
        self._stats = ensemble_stats(np.empty((0, 0)))
        self._cols = []

        v = QVBoxLayout(self)
        head = QHBoxLayout()
        self._title = QLabel("Ensemble (% cycle)")
        self._n_label = QLabel("0 epochs")
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.clicked.connect(self._on_export)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._n_label)
        head.addWidget(self._export_btn)
        v.addLayout(head)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "% cycle")
        self._mean_curve = self._plot.plot(pen=pg.mkPen("#3B8FD9", width=2))
        self._band = pg.FillBetweenItem(brush=pg.mkBrush(59, 143, 217, 60))
        self._lo = self._plot.plot(pen=pg.mkPen(None))
        self._hi = self._plot.plot(pen=pg.mkPen(None))
        self._band.setCurves(self._lo, self._hi)
        self._plot.addItem(self._band)
        v.addWidget(self._plot, 1)

    def set_sources(self, sources):
        """``sources`` = list of ``(file_label, norm_dict)`` where ``norm_dict`` has
        ``matrix`` (N_i x P). Pools, recomputes stats, redraws."""
        self._sources = list(sources or [])
        mats, cols = [], []
        for label, nd in self._sources:
            m = np.asarray(nd.get("matrix"), float)
            if m.ndim == 2 and m.shape[0] > 0:
                mats.append(m)
                cols.extend(f"{label}#{i+1}" for i in range(m.shape[0]))
        matrix = pool(mats) if mats else np.empty((0, 0))
        self._matrix = matrix
        self._cols = cols
        self._stats = ensemble_stats(matrix)
        self._n_label.setText(f"{self._stats['n']} epochs")
        self._redraw()

    def n_epochs(self):
        return int(self._stats.get("n", 0))

    def stats(self):
        return self._stats

    def export_csv(self, path):
        text = ensemble_csv(getattr(self, "_matrix", np.empty((0, 0))),
                            self._stats, columns=self._cols)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def _redraw(self):
        x = self._stats.get("x")
        mean = self._stats.get("mean")
        sd = self._stats.get("sd")
        if x is None or len(x) == 0:
            self._mean_curve.setData([], [])
            self._lo.setData([], []); self._hi.setData([], [])
            return
        self._mean_curve.setData(x, mean)
        self._lo.setData(x, mean - sd)
        self._hi.setData(x, mean + sd)

    def _on_export(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export ensemble CSV",
                                              "ensemble.csv", "CSV (*.csv)")
        if path:
            self.export_csv(path)


class NormalizeStepDialog(QDialog):
    """Add/edit a NormalizeStep: pick a signal, an epoch mode + its event(s),
    and the phase resolution. ``values()`` returns kwargs for ``NormalizeStep``."""

    MODES = [("Consecutive event (cycle)", "cycle"),
             ("Start to end event (window)", "window"),
             ("Whole trial", "trial")]

    def __init__(self, parent, inputs, event_labels, step=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Normalize" if step else "Add Normalize")
        self.setModal(True)
        form = QFormLayout(self)

        self.input_combo = CascadingSignalPicker(keys=inputs)
        cur_in = getattr(step, "input", None) if step else None
        if cur_in:
            self.input_combo.set_key(cur_in)
        else:
            self.input_combo.prefer_filtered_default()
        form.addRow("Signal", self.input_combo)

        self.name_edit = QLineEdit(getattr(step, "name", "") if step else "")
        self.name_edit.setPlaceholderText("Output name (e.g. knee_cycle)")
        form.addRow("Name", self.name_edit)

        self.mode_combo = QComboBox()
        for label, key in self.MODES:
            self.mode_combo.addItem(label, key)
        if step is not None:
            i = self.mode_combo.findData(getattr(step, "mode", "cycle"))
            if i >= 0:
                self.mode_combo.setCurrentIndex(i)
        form.addRow("Epoch", self.mode_combo)

        labels = list(event_labels or [])
        self.event_combo = QComboBox(); self.event_combo.addItems(labels)
        self.start_combo = QComboBox(); self.start_combo.addItems(labels)
        self.end_combo = QComboBox(); self.end_combo.addItems(labels)
        if step is not None:
            for combo, val in ((self.event_combo, getattr(step, "event", "")),
                               (self.start_combo, getattr(step, "start_event", "")),
                               (self.end_combo, getattr(step, "end_event", ""))):
                j = combo.findText(val)
                if j >= 0:
                    combo.setCurrentIndex(j)
        form.addRow("Event (cycle)", self.event_combo)
        form.addRow("Start event", self.start_combo)
        form.addRow("End event", self.end_combo)

        self.points_spin = QSpinBox(); self.points_spin.setRange(2, 1001)
        self.points_spin.setValue(getattr(step, "points", 101) if step else 101)
        form.addRow("Points", self.points_spin)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        return {
            "input": self.input_combo.selected_key() or "",
            "name": self.name_edit.text().strip(),
            "mode": self.mode_combo.currentData(),
            "event": self.event_combo.currentText(),
            "start_event": self.start_combo.currentText(),
            "end_event": self.end_combo.currentText(),
            "points": int(self.points_spin.value()),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ensemble_panel.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Wire into the Analyze tab**

In `ui/analyze_tab.py`, follow the existing `_add_metric_step` pattern (around the other `_add_*_step` methods) to add an "Add Normalize step" action that opens `NormalizeStepDialog`, builds a `NormalizeStep(**dialog.values())`, and appends it via `self.pipeline.add(...)`. Host one `EnsemblePanel` in the results area; after a run, gather `(dataset_name, model_or_run_result["normalized"][name])` for every **checked** dataset that produced the selected `NormalizeStep` output and call `panel.set_sources(...)`. Use the existing `_event_input_options()` for the dialog `inputs` and `_event_label_options()` for `event_labels`.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 7: Commit**

```bash
git add ui/ensemble_panel.py ui/analyze_tab.py tests/test_ensemble_panel.py
git commit -m "feat(ui): ensemble panel (mean+/-SD plot, CSV) + NormalizeStep dialog"
```

---

## Self-Review

**Spec coverage:**
- §1 scope (curve viz + CSV, no stats tab) → Tasks 6–7. ✓
- §2 epoch model (3 modes) → Task 2 (`epoch_windows`) + Task 4 (`NormalizeStep.mode`). ✓
- §3 three layers → Tasks 1–5 (layer 1–2) + Task 7 (layer 3). ✓
- §4 components/interfaces → Tasks 1–7 map 1:1 to §4.1–4.5. ✓
- §5 data flow (`:filt`/`angle:*` reach the curve) → Task 5 reads via `ctx.signal`; Task 5 Step 1 note. ✓
- §6 resampling (linear, 101) → Task 1. ✓
- §7 CSV format → Task 6. ✓
- §8 edge cases (0 epochs, NaN, n=1, mismatched points) → Tasks 1–3 tests cover NaN/n=1/empty; mismatched width raises in `pool` (Task 3); 0 epochs → empty matrix flows through. ✓
- §9 forward-compat (value-at-event) → meta carries start/end frames (Task 2); no V1 task (intentional). ✓
- §10 testing → each task is TDD; UI-smoke in Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Task 7 Step 5 (Analyze wiring) is prose because it adapts to an existing large file's local patterns; the testable units (panel, dialog) have full code + tests. ✓

**Type consistency:** `resample_to_percent(values, points)`, `epoch_windows(time, events, mode, start_event, end_event)`, `extract_epochs(values, windows, points)`, `pool(matrices)`, `ensemble_stats(matrix)->{mean,sd,n,x}`, `ensemble_csv(matrix, stats, columns)`, `NormalizeStep(input,name,mode,event,start_event,end_event,points,enabled)`, panel `set_sources([(label, {"matrix":...})])` — names/signatures consistent across tasks. ✓
