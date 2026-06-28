# Walk Preset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Preset" picker that auto-seeds a complete, editable gait pipeline (all walk variables) in two variants — 보행(지면)/overground and 보행(트레드밀)/treadmill.

**Architecture:** A pure `core/presets.py` registry maps a preset name to a function `fn(dataset) -> list[PipelineStep]` that may inspect the dataset to adapt (force-vs-kinematic events). The UI calls it and seeds the pipeline. Almost every metric is existing-op assembly; the only new engine work is lab-frame foot signals + spatial-distance ops.

**Tech Stack:** Python 3.11, NumPy, SciPy, PyQt6. Tests: pytest.

## Global Constraints
- Repo root: `c:\Users\eunbin\Desktop\BalanceAnalyzer\BalanceAnalyzer`. Run everything from there.
- Python/tests: `.venv/Scripts/python.exe -m pytest -q`. Bash form: `cd "c:/Users/eunbin/Desktop/BalanceAnalyzer/BalanceAnalyzer" && ...`. Ad-hoc scripts: prefix `PYTHONPATH=.`.
- Qt crashes natively here: for the FULL suite or any UI test use `QT_QPA_PLATFORM=offscreen` and retry once on a native crash. Baseline before this plan: **538 passed, 30 skipped**.
- TDD: write the failing test, watch it fail, implement minimal code, watch it pass, commit. No production code without a failing test first.
- Pure core: `core/*` modules are NumPy-only, no Qt, NaN-safe. UI stays thin.
- Step constructors (from `core/pipeline.py`): `DetectEventStep(input,label,method,params,selector,scope,color)`, `ComputeStep(input,name,method,by,params,inputs,enabled)`, `MetricStep(input,op,name,segment,event,input2,enabled)`.
- Markers are mm → divide by 1000 for m / m·s⁻¹. AP axis is anterior-positive (the `core/gait_events.py` convention).

---

## File structure
- `core/gait_events.py` (modify) — add lab-frame foot coordinate series (Task 1).
- `core/signals.py` (modify) — resolve/label/unit the new `gait:*_lab` keys (Task 1).
- `core/metrics.py` (modify) — register `product`, `quotient` reference ops (Task 2) and `displacement_between_events` (Task 3).
- `core/metrics_compute.py` (modify) — dispatch `displacement_between_events` (Task 3).
- `core/presets.py` (create) — registry + the two walk preset builders (Tasks 4–5).
- `ui/analyze_tab.py` (modify) — preset picker that seeds the pipeline (Task 7).
- Tests: `tests/test_gait_events.py`, `tests/test_metrics.py`, `tests/test_presets.py` (new), `tests/test_examples_events.py`, `tests/test_ui_smoke.py`.

---

### Task 1: Lab-frame foot coordinate signals (`gait:<SIDE>_<heel|toe>_<ap|ml>_lab`)

**Files:**
- Modify: `core/gait_events.py`
- Modify: `core/signals.py`
- Test: `tests/test_gait_events.py`

**Interfaces:**
- Produces: `gait_events.foot_lab_series(markers, side, point="heel", axis="ap", label_map=None) -> np.ndarray` — the foot marker's LAB-frame coordinate along the AP (progression, anterior-positive) or ML axis, NOT pelvis-relative. And signal keys `gait:<SIDE>_<heel|toe>_<ap|ml>_lab` resolvable via `signals.signal_series`.
- Consumes: existing `gait_events.progression_axis`, `foot_marker_label`, `_marker_index`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_gait_events.py`, reuse the module's `_synth_markers`)

```python
def test_foot_lab_series_is_absolute_not_pelvis_relative():
    mk = _synth_markers()
    lab = ge.foot_lab_series(mk, "R", "heel", axis="ap")
    rel = ge.foot_progression_series(mk, "R", "heel")
    n = mk["data"].shape[1]
    assert lab.shape == (n,)
    # lab-frame AP = raw heel axis-1 (anterior-positive), NOT minus pelvis.
    ap, sign = ge.progression_axis(mk, "R")
    expected = sign * mk["data"][4][:, ap]
    np.testing.assert_allclose(lab, expected)
    # differs from the pelvis-relative series by exactly the pelvis AP.
    np.testing.assert_allclose(lab - rel, sign * mk["data"][0][:, ap])


def test_foot_lab_series_ml_axis():
    mk = _synth_markers()
    ml = ge.foot_lab_series(mk, "R", "heel", axis="ml")
    assert ml.shape == (mk["data"].shape[1],)


def test_signal_series_resolves_gait_lab_keys():
    ds, mk = _gait_dataset()
    v = sig.signal_series(ds, "gait:R_heel_ap_lab", marker_disp=mk["data"])
    assert v.shape == ds["time"].shape
    assert sig.unit_for("gait:R_heel_ap_lab") == "mm"
    assert sig.label_for("gait:R_heel_ap_lab") != "gait:R_heel_ap_lab"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gait_events.py -k "lab" -q`
Expected: FAIL (`AttributeError: foot_lab_series` / `channel unavailable`).

- [ ] **Step 3: Implement `foot_lab_series` in `core/gait_events.py`** (after `foot_progression_series`)

```python
def foot_lab_series(markers, side, point="heel", axis="ap", label_map=None):
    """A foot marker's LAB-frame coordinate (NOT pelvis-relative), (F,).

    ``axis="ap"`` = the progression axis, anterior-positive (so forward travel is
    positive); ``axis="ml"`` = the remaining horizontal (medio-lateral) axis,
    oriented by the same sign. Used for spatial gait variables (stride/step
    length, step width, and treadmill belt speed = its time-derivative)."""
    idx = _marker_index(markers, foot_marker_label(side, point), label_map)
    if idx is None:
        raise ValueError(f"missing {point} marker for side {side!r}")
    ap, sign = progression_axis(markers, side, label_map)
    if axis == "ap":
        col = ap
    elif axis == "ml":
        vertical = int(np.argmax(np.abs(np.nanmean(
            np.asarray(markers["data"][idx], dtype=float)
            - pelvis_origin(markers, label_map), axis=0))))
        col = [a for a in range(3) if a not in (ap, vertical)][0]
    else:
        raise ValueError(f"unknown axis: {axis!r}")
    return sign * np.asarray(markers["data"][idx], dtype=float)[:, col]
```

- [ ] **Step 4: Resolve the key in `core/signals.py`** — extend `_split_gait` and the `gait:` branch in `signal_series`, plus label/unit.

In `_split_gait`, accept the optional `_lab` suffix and the `ml` projection:
```python
def _split_gait(key):
    if not key.startswith("gait:"):
        return None, None, None
    body = key[len("gait:"):]
    lab = body.endswith("_lab")
    if lab:
        body = body[: -len("_lab")]
    parts = body.split("_")
    if len(parts) == 3 and parts[1] in ("heel", "toe") and parts[2] in ("ap", "ml"):
        return parts[0], parts[1], (parts[2], lab)   # (side, point, (axis, lab))
    return None, None, None
```
Update the two existing `_split_gait` call-sites (`_base_label`, `signal_series`) to unpack three values; in `_base_label` build a label like `f"{side} {point} ({axis.upper()}{', lab' if lab else ''})"`; `unit_for` already returns "mm" for any `gait:` key (no change). In `signal_series`'s `gait:` branch:
```python
side, point, proj = _split_gait(key)
if side is None:
    raise ValueError(f"channel unavailable: {key}")
if marker_disp is None or dataset.get("markers") is None:
    raise ValueError("no markers for gait channel")
from core import gait_events
mk = {"labels": dataset["markers"]["labels"], "data": marker_disp,
      "time": dataset["markers"]["time"]}
axis, lab = proj
if lab:
    series = gait_events.foot_lab_series(mk, side, point, axis=axis)
else:
    series = gait_events.foot_progression_series(mk, side, point)  # AP only
return _resample(dataset["markers"]["time"], series, t)
```
(Keep the existing pelvis-relative `gait:R_heel_ap` working: non-`_lab`, axis "ap".)

- [ ] **Step 5: Run tests** — `.venv/Scripts/python.exe -m pytest tests/test_gait_events.py -q` → PASS (all, including pre-existing).

- [ ] **Step 6: Commit**

```bash
git add core/gait_events.py core/signals.py tests/test_gait_events.py
git commit -m "feat(gait): lab-frame foot AP/ML signals for spatial gait metrics"
```

---

### Task 2: `product` and `quotient` binary reference ops

**Files:**
- Modify: `core/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: two `REFERENCE_OPS` entries — `product` (a×b) and `quotient` (a÷b), both binary (`n_inputs=2`), consumed as `MetricStep(op="product", input="metric:A", input2="metric:B")`. NaN/zero-safe. Unit "" (the preset names carry the unit; unit propagation is a noted follow-up).

- [ ] **Step 1: Failing test** (append to `tests/test_metrics.py`)

```python
from core.metrics import REFERENCE_OPS

def test_product_and_quotient_reference_ops():
    pfn, pn, _ = REFERENCE_OPS["product"]
    qfn, qn, _ = REFERENCE_OPS["quotient"]
    assert pn == 2 and qn == 2
    assert pfn(1.2, 0.8) == pytest.approx(0.96)        # speed * stride_time = length
    assert qfn(1.28, 1.12) == pytest.approx(1.142857, rel=1e-4)  # length / time = speed
    import math
    assert math.isnan(qfn(1.0, 0.0))                    # divide by zero -> NaN
    assert math.isnan(pfn(float("nan"), 2.0))
```

- [ ] **Step 2: Run to verify it fails** — `... -m pytest tests/test_metrics.py -k "product_and_quotient" -q` → FAIL (`KeyError: 'product'`).

- [ ] **Step 3: Implement in `core/metrics.py`** — add the functions near `_phase_pct`, register in `REFERENCE_OPS` and `_REFERENCE_LABELS`.

```python
def _product(a, b):
    a, b = float(a), float(b)
    return a * b if (np.isfinite(a) and np.isfinite(b)) else float("nan")

def _quotient(a, b):
    a, b = float(a), float(b)
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return float("nan")
    return a / b
```
In `REFERENCE_OPS` add:
```python
    "product":  (_product, 2, ""),
    "quotient": (_quotient, 2, ""),
```
In `_REFERENCE_LABELS` add:
```python
    "product":  ("Product (a x b)",  "metric"),
    "quotient": ("Quotient (a / b)", "metric"),
```

- [ ] **Step 4: Run tests** — `... -m pytest tests/test_metrics.py -q` → PASS. Also `tests/test_help_docs_sync.py` (new ops are non-COP, should not affect the COP 1:1 map) → PASS.

- [ ] **Step 5: Commit**

```bash
git add core/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): product and quotient binary reference ops"
```

---

### Task 3: `displacement_between_events` metric op

**Files:**
- Modify: `core/metrics.py`
- Modify: `core/metrics_compute.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Produces: op `displacement_between_events` — for a per-cycle window `[lo, hi]` (from `segment=[startLabel, endLabel]`) it returns `signal[hi] - signal[lo]` of `step.input` (per cycle → mean±SD over cycles), preserving the input's unit. Used for overground stride length (AP, segment HS→HS), step length (AP, contra→ipsi HS), step width (ML, R_HS→L_HS).
- Consumes: `_window_value` dispatch in `core/metrics_compute.py`; the cycle windowing already in `compute_metric_step`.

- [ ] **Step 1: Failing test** (append to `tests/test_run.py`)

```python
import numpy as np
from core.pipeline import Pipeline, DetectEventStep, MetricStep
from core.run import run_pipeline

def test_displacement_between_events_per_cycle():
    # A signal that increases by exactly 10 each frame; HS at frames 0,5,10
    # -> each HS->HS stride spans 5 frames -> displacement 50 per cycle.
    n = 12
    ds = {"time": np.arange(n) / 100.0, "fs": 100.0,
          "pos": np.arange(n, dtype=float) * 10.0,
          # a pulse signal to detect HS at 0,5,10
          "trig": np.array([1,0,0,0,0,1,0,0,0,0,1,0], dtype=float)}
    p = Pipeline()
    p.add(DetectEventStep(input="trig", label="HS", method="threshold",
                          params={"threshold": 0.5, "direction": "rising"},
                          selector={"mode": "all"}))
    p.add(MetricStep(input="pos", op="displacement_between_events",
                     name="StrideLen", segment=["HS", "HS"]))
    out = run_pipeline(ds, p)
    val, unit = out["metric_values"]["StrideLen"]
    assert val == pytest.approx(50.0)
```

- [ ] **Step 2: Run to verify it fails** — `... -m pytest tests/test_run.py -k "displacement_between_events" -q` → FAIL (op unknown → NaN, assertion fails).

- [ ] **Step 3: Register the op in `core/metrics.py`** — add a dedicated info builder so OP_INFO knows its input kind is a signal read at the window ends.

Add near `_event_info`:
```python
_DISPLACEMENT_OPS = {
    "displacement_between_events": ("Displacement between events", "signal"),
}

def _displacement_info(k):
    label, kind = _DISPLACEMENT_OPS[k]
    return {"label": label, "category": "displacement", "input": "displacement",
            "emits_event": False, "needs_time": False, "signal_kind": kind}
```
And in the `OP_INFO = {...}` dict add:
```python
    **{k: _displacement_info(k) for k in _DISPLACEMENT_OPS},
```

- [ ] **Step 4: Dispatch in `core/metrics_compute.py`** — add a branch in `_window_value` (before the final scalar branch):

```python
    if kind == "displacement":
        # signal[hi] - signal[lo] over the per-cycle event window. No segment
        # (i.e. whole-trial fallback) is meaningless here -> NaN.
        if not step.segment:
            return float("nan"), _unit(ctx, step.input), None
        sig = np.asarray(ctx.signal(step.input), dtype=float)
        if not (0 <= lo < sig.size and 0 <= hi < sig.size):
            return float("nan"), _unit(ctx, step.input), None
        return float(sig[hi] - sig[lo]), _unit(ctx, step.input), None
```

- [ ] **Step 5: Run tests** — `... -m pytest tests/test_run.py -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add core/metrics.py core/metrics_compute.py tests/test_run.py
git commit -m "feat(metrics): displacement_between_events op for spatial gait lengths"
```

---

### Task 4: `core/presets.py` registry + treadmill walk preset

**Files:**
- Create: `core/presets.py`
- Test: `tests/test_presets.py` (new)

**Interfaces:**
- Produces: `presets.PRESETS` (dict name→builder), `presets.build_preset(name, dataset) -> list[PipelineStep]`, and `presets.walk_treadmill(dataset) -> list`. Builders return ready-to-append `core.pipeline` step objects (kinematic events via `gait:*`, spatiotemporal, kinematics, spatial via belt speed, symmetry/CV), bilateral R+L. NO kinetics (treadmill has no force).
- Consumes: `core.pipeline.{DetectEventStep,ComputeStep,MetricStep}`; ops from Tasks 1–3 (`gait:*_ap_lab`, `product`); existing ops (`time_between_events`, `stance_pct`, `swing_pct`, `cadence_stride`, `mean`, `range`, `peak_angular_velocity`, `value_at_event`, `symmetry_index`, `cv`).

- [ ] **Step 1: Failing test** (`tests/test_presets.py`)

```python
from core import presets
from core.pipeline import DetectEventStep, MetricStep

def _labels(steps, kind):
    return [getattr(s, "name", getattr(s, "label", "")) for s in steps
            if s.__class__.__name__ == kind]

def test_walk_treadmill_seeds_kinematic_events_both_sides():
    steps = presets.walk_treadmill({})
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    inputs = {s.input for s in det}
    assert "gait:R_heel_ap" in inputs and "gait:R_toe_ap" in inputs
    assert "gait:L_heel_ap" in inputs and "gait:L_toe_ap" in inputs
    # all kinematic (no force threshold input like fp1:fz)
    assert all(s.input.startswith("gait:") for s in det)

def test_walk_treadmill_has_core_spatiotemporal_and_no_kinetics():
    names = _labels(presets.walk_treadmill({}), "MetricStep")
    for needed in ("R Stride time", "R Cadence", "R Stance %", "R Gait speed"):
        assert needed in names, needed
    ops = {s.op for s in presets.walk_treadmill({}) if isinstance(s, MetricStep)}
    assert "impulse" not in ops and "loading_rate" not in ops   # no force kinetics

def test_build_preset_registry():
    assert "walk_treadmill" in presets.PRESETS
    assert presets.build_preset("walk_treadmill", {}) == presets.walk_treadmill({})
```

- [ ] **Step 2: Run to verify it fails** — `... -m pytest tests/test_presets.py -q` → FAIL (`ModuleNotFoundError: core.presets`).

- [ ] **Step 3: Implement `core/presets.py`** (treadmill builder + registry). Keep helpers small and bilateral.

```python
"""Task presets: build a complete, EDITABLE pipeline for a movement task.

A preset is a pure function ``fn(dataset) -> list[PipelineStep]``. The UI appends
the returned steps to the pipeline; everything after is the normal editable
pipeline (the preset is just a non-blank starting point). Builders may inspect
``dataset`` to adapt (e.g. force-vs-kinematic events for overground).
"""
import numpy as np
from core.pipeline import DetectEventStep, ComputeStep, MetricStep

_JOINTS = ("HIP", "KNEE", "ANKLE")          # angle:<SIDE>_<JOINT>_angle_FE etc.


def _kinematic_events(side):
    s = side
    return [
        DetectEventStep(input=f"gait:{s}_heel_ap", label=f"{s}_HS", method="peak",
                        params={"kind": "max", "min_distance_s": 0.5},
                        selector={"mode": "all"}),
        DetectEventStep(input=f"gait:{s}_toe_ap", label=f"{s}_TO", method="peak",
                        params={"kind": "min", "min_distance_s": 0.5},
                        selector={"mode": "all"}),
    ]


def _spatiotemporal(side):
    s = side
    return [
        MetricStep(op="time_between_events", name=f"{s} Stride time",
                   segment=[f"{s}_HS", f"{s}_HS"]),
        MetricStep(op="time_between_events", name=f"{s} Stance time",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(op="time_between_events", name=f"{s} Swing time",
                   segment=[f"{s}_TO", f"{s}_HS"]),
        MetricStep(op="stance_pct", name=f"{s} Stance %",
                   input=f"metric:{s} Stance time", input2=f"metric:{s} Stride time"),
        MetricStep(op="swing_pct", name=f"{s} Swing %",
                   input=f"metric:{s} Swing time", input2=f"metric:{s} Stride time"),
        MetricStep(op="cadence_stride", name=f"{s} Cadence",
                   input=f"metric:{s} Stride time"),
    ]


def _treadmill_spatial(side):
    """Belt speed = mean |d/dt lab-foot-AP| over stance; stride length = speed x
    stride time. Normalize mm->m and mm/s->m/s."""
    s = side
    return [
        ComputeStep(input=f"gait:{s}_heel_ap_lab", name=f"{s}_heel_vel",
                    method="derivative", params={"order": 1}),
        ComputeStep(input=f"{s}_heel_vel", name=f"{s}_heel_speed", method="abs"),
        ComputeStep(input=f"{s}_heel_speed", name=f"{s}_heel_speed_mps",
                    method="normalize", by=1000.0),
        MetricStep(input=f"{s}_heel_speed_mps", op="mean", name=f"{s} Gait speed",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(op="product", name=f"{s} Stride length",
                   input=f"metric:{s} Gait speed", input2=f"metric:{s} Stride time"),
    ]


def _kinematics(side):
    out = []
    for j in _JOINTS:
        ch = f"angle:{side}_{j}_angle_FE"
        out.append(MetricStep(input=ch, op="range", name=f"{side} {j.title()} ROM",
                              segment=[f"{side}_HS", f"{side}_HS"]))
        out.append(MetricStep(input=ch, op="peak_angular_velocity",
                              name=f"{side} {j.title()} peak ang.vel",
                              segment=[f"{side}_HS", f"{side}_HS"]))
        out.append(MetricStep(input=ch, op="value_at_event",
                              name=f"{side} {j.title()} angle@HS", event=f"{side}_HS"))
    return out


def _symmetry():
    return [
        MetricStep(op="symmetry_index", name="Stride time symmetry",
                   input="metric:R Stride time", input2="metric:L Stride time"),
        MetricStep(op="symmetry_index", name="Stance % symmetry",
                   input="metric:R Stance %", input2="metric:L Stance %"),
        MetricStep(op="cv", name="R Stride time CV", input="metric:R Stride time"),
    ]


def _double_support():
    return [
        MetricStep(op="time_between_events", name="Double support R",
                   segment=["R_HS", "L_TO"]),
        MetricStep(op="time_between_events", name="Double support L",
                   segment=["L_HS", "R_TO"]),
    ]


def walk_treadmill(dataset):
    steps = []
    for side in ("R", "L"):
        steps += _kinematic_events(side)
    for side in ("R", "L"):
        steps += _spatiotemporal(side) + _treadmill_spatial(side) + _kinematics(side)
    steps += _double_support() + _symmetry()
    return steps


PRESETS = {"walk_treadmill": walk_treadmill}


def build_preset(name, dataset):
    fn = PRESETS.get(name)
    return fn(dataset) if fn else []
```

- [ ] **Step 4: Run tests** — `... -m pytest tests/test_presets.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add core/presets.py tests/test_presets.py
git commit -m "feat(presets): registry + treadmill walk preset (all gait variables)"
```

---

### Task 5: Overground walk preset (adaptive force/kinematic) + kinetics

**Files:**
- Modify: `core/presets.py`
- Test: `tests/test_presets.py`

**Interfaces:**
- Produces: `presets.walk_overground(dataset) -> list`, registered as `"walk_overground"`. Uses FORCE events (`fp{p}:fz` rectified, threshold) when force plates are loaded; else kinematic `gait:*`. Adds the kinetics group ONLY when force is present. Spatial via `displacement_between_events` on `gait:*_ap_lab` (overground displacement) + `quotient` for speed. Helper `presets._force_is_loaded(dataset) -> bool`.
- Consumes: `displacement_between_events`, `quotient` (Tasks 2–3); `gait:*_ap_lab` (Task 1); existing `impulse`/`loading_rate`/`max`.

- [ ] **Step 1: Failing test** (append to `tests/test_presets.py`)

```python
import numpy as np
from core.pipeline import ComputeStep

def _loaded_force_ds():
    n = 600
    fz = np.where((np.arange(n) % 120) < 70, 600.0, 0.0)   # repeated loading
    return {"time": np.arange(n)/1000.0, "fs": 1000.0, "n_force_plates": 1,
            "fp1:fz": fz}

def _flat_force_ds():
    n = 600
    return {"time": np.arange(n)/1000.0, "fs": 1000.0, "n_force_plates": 1,
            "fp1:fz": np.zeros(n)}

def test_overground_uses_force_events_when_loaded():
    steps = presets.walk_overground(_loaded_force_ds())
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    assert any("fz" in s.input for s in det)              # force-based events
    ops = {s.op for s in steps if isinstance(s, MetricStep)}
    assert "impulse" in ops                                # kinetics included

def test_overground_falls_back_to_kinematic_without_force():
    steps = presets.walk_overground(_flat_force_ds())
    det = [s for s in steps if isinstance(s, DetectEventStep)]
    assert all(s.input.startswith("gait:") for s in det)  # kinematic
    ops = {s.op for s in steps if isinstance(s, MetricStep)}
    assert "impulse" not in ops                            # no force -> no kinetics

def test_overground_stride_length_is_displacement():
    steps = presets.walk_overground(_flat_force_ds())
    sl = [s for s in steps if isinstance(s, MetricStep)
          and getattr(s, "name", "") == "R Stride length"]
    assert sl and sl[0].op == "displacement_between_events"
```

- [ ] **Step 2: Run to verify it fails** — `... -m pytest tests/test_presets.py -k overground -q` → FAIL (`AttributeError: walk_overground`).

- [ ] **Step 3: Implement in `core/presets.py`**

```python
def _force_is_loaded(dataset, thresh_n=50.0, frac=0.05):
    """True if any plate's |Fz| exceeds ``thresh_n`` for at least ``frac`` of the
    trial (a real overground contact), else False (flat/empty plates)."""
    n_p = int(dataset.get("n_force_plates", 0) or 0)
    keys = [f"fp{p}:fz" for p in range(1, n_p + 1)] or (["fz"] if "fz" in dataset else [])
    for k in keys:
        a = np.abs(np.asarray(dataset.get(k, []), dtype=float))
        if a.size and np.mean(a > thresh_n) >= frac:
            return True
    return False


def _force_events(side, plate):
    """HS = rising, TO = falling crossing of the rectified plate Fz at 50 N."""
    s = side
    return [
        ComputeStep(input=f"fp{plate}:fz", name=f"{s}_aFz", method="abs"),
        DetectEventStep(input=f"{s}_aFz", label=f"{s}_HS", method="threshold",
                        params={"threshold": 50.0, "direction": "rising",
                                "min_distance_s": 0.4}, selector={"mode": "all"}),
        DetectEventStep(input=f"{s}_aFz", label=f"{s}_TO", method="threshold",
                        params={"threshold": 50.0, "direction": "falling",
                                "min_distance_s": 0.4}, selector={"mode": "all"}),
    ]


def _kinetics(side, plate):
    s = side
    return [
        MetricStep(input=f"{s}_aFz", op="max", name=f"{s} Peak vGRF",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(input=f"{s}_aFz", op="impulse", name=f"{s} vGRF impulse",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(input=f"{s}_aFz", op="loading_rate", name=f"{s} Loading rate",
                   segment=[f"{s}_HS", f"{s}_TO"]),
    ]


def _overground_spatial(side):
    """Stride length = AP displacement of the foot between consecutive HS
    (mm->m); gait speed = stride length / stride time."""
    s = side
    return [
        ComputeStep(input=f"gait:{s}_heel_ap_lab", name=f"{s}_heel_ap_m",
                    method="normalize", by=1000.0),
        MetricStep(input=f"{s}_heel_ap_m", op="displacement_between_events",
                   name=f"{s} Stride length", segment=[f"{s}_HS", f"{s}_HS"]),
        MetricStep(op="quotient", name=f"{s} Gait speed",
                   input=f"metric:{s} Stride length", input2=f"metric:{s} Stride time"),
    ]


def walk_overground(dataset):
    loaded = _force_is_loaded(dataset)
    steps = []
    # plate assignment: R->plate1, L->plate2 when 2 plates; else both kinematic.
    n_p = int(dataset.get("n_force_plates", 0) or 0)
    for i, side in enumerate(("R", "L")):
        if loaded and n_p >= 1:
            steps += _force_events(side, plate=min(i + 1, n_p))
        else:
            steps += _kinematic_events(side)
    for i, side in enumerate(("R", "L")):
        steps += _spatiotemporal(side) + _overground_spatial(side) + _kinematics(side)
        if loaded and n_p >= 1:
            steps += _kinetics(side, plate=min(i + 1, n_p))
    steps += _double_support() + _symmetry()
    return steps


PRESETS["walk_overground"] = walk_overground
```

- [ ] **Step 4: Run tests** — `... -m pytest tests/test_presets.py -q` → PASS (all Task 4 + 5 tests).

- [ ] **Step 5: Commit**

```bash
git add core/presets.py tests/test_presets.py
git commit -m "feat(presets): adaptive overground walk preset (force/kinematic + kinetics)"
```

---

### Task 6: End-to-end preset run on the bundled trials

**Files:**
- Test: `tests/test_examples_events.py`

**Interfaces:**
- Consumes: `presets.build_preset`, `core.run.run_pipeline`; the CEB/KKM model-build pattern already in this file (`_ceb_gait_detect` / `auto_build_model` → `calibrate` → `suggest_label_map` → `apply`).

- [ ] **Step 1: Failing test** (append; skip-guarded like the other CEB tests)

```python
def test_walk_treadmill_preset_end_to_end():
    """Seeding the treadmill walk preset on CEB yields a finite, physiological
    comprehensive metric set through run_pipeline."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d"); dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model, suggest_label_map
    from core.run import run_pipeline
    from core import presets
    from core.pipeline import Pipeline
    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    model = auto_build_model(static["markers"], name="CEB"); model.calibrate(static["markers"])
    lm = suggest_label_map(model.cluster_labels(), dyn["markers"]["labels"])
    res = model.apply(dyn["markers"], label_map=lm); dyn["model_result"] = res
    dur = float(dyn["markers"]["time"][-1]); n = int(round(dur * 1000.0)) + 1
    dyn["time"] = np.arange(n) / 1000.0; dyn["fs"] = 1000.0
    md = dyn["markers"]["data"]
    p = Pipeline()
    for s in presets.build_preset("walk_treadmill", dyn):
        p.add(s)
    mv = run_pipeline(dyn, p, marker_disp=md, angle_result=res)["metric_values"]
    assert mv["R Stride time"][0] == pytest.approx(1.122, abs=0.03)
    assert 60.0 <= mv["R Stance %"][0] <= 72.0
    assert mv["R Gait speed"][0] == pytest.approx(1.15, abs=0.2)     # belt speed m/s
    assert mv["R Stride length"][0] == pytest.approx(1.28, abs=0.2)  # speed x time
    assert np.isfinite(mv["R Knee ROM"][0]) and mv["R Knee ROM"][0] > 0
```

- [ ] **Step 2: Run to verify it fails** — `QT_QPA_PLATFORM=offscreen ... -m pytest tests/test_examples_events.py -k walk_treadmill_preset -q` → FAIL until Tasks 1–5 are merged (KeyError on a metric / NameError).

- [ ] **Step 3: No new production code** — this task is integration coverage. If it fails, fix the offending preset/op task, not the test. Adjust the metric-name assertions only to match the exact names produced by Task 4.

- [ ] **Step 4: Run** — `QT_QPA_PLATFORM=offscreen ... -m pytest tests/test_examples_events.py -k "walk_treadmill_preset" -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_examples_events.py
git commit -m "test(presets): CEB end-to-end treadmill walk preset coverage"
```

---

### Task 7: UI — preset picker that seeds the pipeline

**Files:**
- Modify: `ui/analyze_tab.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `core.presets.{PRESETS, build_preset}`, the existing pipeline object on `AnalyzeTab`, and the existing "add step" plumbing (how `_add_detect_event_step` appends to the pipeline and refreshes — reuse the same append + refresh calls).
- Produces: a method `AnalyzeTab._apply_preset(name)` that appends `build_preset(name, current_dataset)` to the pipeline and refreshes; a small preset picker (e.g. a `QComboBox` + "Apply" or a menu) wired to it.

- [ ] **Step 1: Failing test** (append to `tests/test_ui_smoke.py`)

```python
def test_apply_preset_seeds_pipeline(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    from core import presets
    tab = AnalyzeTab()
    # a minimal current dataset so build_preset can run
    monkeypatch.setattr(tab, "_current_dataset", lambda: {"n_force_plates": 0})
    before = len(tab._pipeline.steps)
    tab._apply_preset("walk_treadmill")
    after = len(tab._pipeline.steps)
    assert after - before == len(presets.build_preset("walk_treadmill", {}))
```
(If `AnalyzeTab`'s pipeline attribute is not `_pipeline`, grep `self._pipeline`/`self.pipeline` in `ui/analyze_tab.py` and use the real name; same for the current-dataset accessor.)

- [ ] **Step 2: Run to verify it fails** — `QT_QPA_PLATFORM=offscreen ... -m pytest tests/test_ui_smoke.py -k apply_preset -q` → FAIL (`AttributeError: _apply_preset`).

- [ ] **Step 3: Implement `_apply_preset` in `ui/analyze_tab.py`** (place near `_add_detect_event_step`; reuse its append + refresh idiom)

```python
def _apply_preset(self, name):
    """Seed the pipeline with a task preset's steps (core.presets), then refresh
    exactly like a manual add. The seeded steps are normal, fully editable."""
    from core.presets import build_preset
    dataset = self._current_dataset()
    for step in build_preset(name, dataset or {}):
        self._pipeline.add(step)            # use the real pipeline attr/add method
    self._on_pipeline_changed()             # use the real refresh hook used by adds
```
Then add a picker in the pipeline toolbar: a `QComboBox` populated from `core.presets.PRESETS` labels (e.g. "보행 (트레드밀)" → `walk_treadmill`, "보행 (지면)" → `walk_overground`) plus an "Apply preset" button whose click calls `self._apply_preset(combo.currentData())`. Match the refresh method name to the one the existing add-step handlers call.

- [ ] **Step 4: Run tests** — `QT_QPA_PLATFORM=offscreen ... -m pytest tests/test_ui_smoke.py -q` → PASS.

- [ ] **Step 5: Full suite** — `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q` → all green (538 baseline + new). Retry once on a native Qt crash.

- [ ] **Step 6: Commit**

```bash
git add ui/analyze_tab.py tests/test_ui_smoke.py
git commit -m "feat(ui): task-preset picker that seeds the walk pipeline"
```

---

## Self-review notes (gaps / decisions)
- **Spec coverage:** events (T4/T5), spatiotemporal incl. double support (T4), spatial speed/length both modes (T1–T5), kinematics ROM/peak ang.vel/angle@event (T4), kinetics overground-only (T5), symmetry/CV (T4), preset registry + adaptive overground (T4/T5), UI seeding (T7), e2e (T6).
- **Deferred (note in PR):** step width (needs a cross-foot ML segment — the `gait:*_ml_lab` signal exists after T1, so it is a later one-line preset step, not new engine work); unit propagation for `product`/`quotient` (units carried in the metric NAME for v1); per-joint AB/IE planes (only FE seeded in T4 to keep the pipeline readable — add planes later).
- **Open decisions** carried from the spec/biomech catalog (L/R label convention = `R_HS/L_HS/R_TO/L_TO`, AP+ = anterior, symmetry = Robinson SI, derivative endpoint policy) are realized as written above; revisit if biomech review objects.
