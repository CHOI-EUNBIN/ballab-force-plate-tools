# Time-Normalization (0–100%) + Ensemble Curves — Design

Date: 2026-06-26
Status: Approved for planning

## 1. Goal & Scope

Add **time-normalization** of a signal/angle to 0–100% of a movement, and an
**ensemble** (mean ± SD) curve pooled across the user's chosen trials, shown as a
graph and exportable as CSV.

**In scope (V1)**
- Per-trial extraction of **epochs** (0–100% resampled segments) for a chosen
  signal/angle.
- **Ensemble** = pool epochs across the **checked trials** → mean ± SD curve.
- **Graph**: x = 0–100% cycle, mean line + ±1 SD band.
- **CSV export**: rows = 0–100%, columns = each epoch + mean + SD.

**Out of scope (V1) — but the structure must not preclude them**
- Discrete **value-at-event** cross-trial export (rides the existing scalar
  `ResultsStore` path later; see §9).
- In-app **SPM** statistics and the Statistics tab rework.
- Cross-**subject** group ensembles / between-group stats.

The Statistics tab is **not touched**. Curves are 2-D waveforms; the existing
`ResultsStore` / "Results" sheet carries only scalar metric rows (one flat row
per file × range), so curves get their **own** CSV channel, not the stats table.

## 2. Core Model — Epoch & Ensemble

| Concept | Definition |
|---|---|
| **Epoch** | One 0–100% resampled segment (default 101 points) of a chosen signal, extracted **per trial (c3d)**. A trial yields ≥1 epoch. |
| **Ensemble** | All epochs pooled across the **selected (checked) trials**, averaged at each % node → `mean(101)`, `sd(101)`, `n`. |

**Epoch definition modes** (a trial can yield many epochs or one):
1. **Consecutive same event** (cyclic, e.g. gait): each `event[i] → event[i+1]`
   pair of one event label is one epoch. Many per trial.
2. **Start → end event** (discrete rep): each `start_event[i] → end_event[i]`
   window (rep onset → offset) is one epoch; the rest between reps is excluded.
   1..N per trial.
3. **Whole trial** (fallback): first → last valid frame = one epoch.

This unifies all recording conventions: gait (many cycles/trial), discrete with
several reps per c3d (mode 2, several epochs/trial), and one-rep-per-c3d (one
epoch/trial). "Reps within a file vs split across files" does not matter — epochs
are extracted per trial, then pooled across the selected trials.

## 3. Architecture — Three Layers

```
[1] Per-trial extraction  (pipeline, runs per trial)
    NormalizeStep(input=<signal>, mode, event(s), points=101)
      → that trial's epoch matrix  (N_trial × 101)  + per-epoch metadata
        ↓  stored on the trial's run result
[2] Cross-trial aggregation  (pools the CHECKED trials' epoch matrices)
      → pooled matrix (ΣN × 101), mean(101), sd(101), n
        ↓
[3] Output
      · Ensemble plot  (x = % cycle, mean line + ±SD band)
      · CSV export     (rows 0..100, cols = epochs + mean + sd)
```

- **[1] lives in the pipeline** — consistent with "the pipeline is the sole
  source of derived data," and fills the existing `normalize` STAGE_ORDER slot.
- **[2]/[3] are cross-trial**, so they live **above** the per-trial pipeline (an
  Analyze-tab "Ensemble" panel that reads the checked trials' run results).

## 4. Components & Interfaces

### 4.1 `core/normalize.py` (new, pure / NaN-safe, UI-free)
- `resample_to_percent(values, points=101) -> np.ndarray`
  Linear-interpolate a 1-D epoch to `points` evenly spaced 0–100% nodes. NaN
  samples are interpolated across when possible; an all-NaN/too-short epoch
  yields an all-NaN row (kept so n is honest, dropped by nan-aware stats).
- `epoch_windows(time, events, mode, start_event=None, end_event=None) -> list[(i0, i1)]`
  Resolve frame-index windows. Mode 1 reuses the consecutive-pairing already in
  `core.metrics_compute.cycles_from_events`; mode 2 pairs start→end; mode 3
  returns one whole-trial window.
- `extract_epochs(values, windows, points=101) -> (matrix[N,points], meta)`
  `meta` = per-epoch start/end frame + start event index (so [2]/value-at-event
  can label columns).

### 4.2 `core/pipeline.py` — `NormalizeStep(PipelineStep)` (new)
- Fields: `input` (signal key, e.g. `angle:R_KNEE_FE` or `fz:filt`), `mode`
  (`"cycle" | "window" | "trial"`), `event` (mode cycle), `start_event` /
  `end_event` (mode window), `points` (default 101), `name`, `enabled`.
- `stage = "normalize"`. `requires()` = its `input` (and event keys); `produces()`
  = `{f"norm:{name}"}`. Serializable (`to_dict`/`from_dict`) like the other steps.

### 4.3 `core/run.py` — executor
- On a `NormalizeStep`, read the input signal (via `Workspace`, so `:filt` keys
  flow) + the referenced detected events, build windows, `extract_epochs`, and
  store under `result["normalized"][name] = {matrix, meta, label, units, points}`.
- Additive: leaves all existing signal/metric outputs unchanged.

### 4.4 `core/ensemble.py` (new, pure)
- `pool(matrices: list[np.ndarray]) -> np.ndarray` — vstack compatible (×101)
  matrices (skip empties / shape-mismatch defensively).
- `ensemble_stats(matrix) -> {"mean": (P,), "sd": (P,), "n": int, "x": (P,)}`
  nan-aware; `x` = 0..100 (percent). **Epoch-weighted**: every pooled epoch
  counts equally (a trial with more cycles contributes more epochs). Trial-equal
  weighting is deferred (a V2 option), not V1.

### 4.5 UI — Analyze "Ensemble" panel
- User picks a `NormalizeStep` output `name` + the **checked trials** that have
  it; the panel pools their matrices ([2]) and plots mean ± SD on a **% cycle**
  plot (its own x-axis, distinct from time plots).
- **Export CSV** button → §7 format. Reuses the existing file-save chrome.

## 5. Data Flow

`markers/forces → (FilterStep) → signal (Workspace) → (DetectEventStep) events`
`→ NormalizeStep: signal + events → epoch matrix (per trial)`
`→ Ensemble panel: pool checked trials → mean/sd → plot + CSV`.

Angles enter as signals via the existing `angle:*` catalog (already filter-aware
after the marker-filter fix), so a filtered marker flows all the way into the
normalized angle ensemble.

## 6. Resampling

- Each epoch's frame samples are mapped to normalized phase `0..1` (`linspace`
  over its own length) and linearly interpolated onto `points` nodes (default
  101). Cubic is deferred (linear is the gait-lab norm and monotone-safe).
- Unequal epoch lengths are handled by construction (every epoch → `points`).

## 7. CSV Export Format

```
percent, epoch_1, epoch_2, ..., epoch_K, mean, sd
0,       12.1,    11.4,    ...,         11.9, 0.6
1,       12.3,    11.6,    ...,         ...
...
100,     ...
```
- `K` = total pooled epochs across the checked trials. Column headers carry the
  source `File`+epoch index from `meta` so provenance is traceable.
- A companion header block (commented `#`) records signal label, units, mode,
  event(s), trial list, n — enough to reconstruct the analysis.
- This file is the SPM input (an `n × 101` matrix per group, taken to SPM1D
  externally in V1).

## 8. Error Handling / Edge Cases

- Trial with **0 epochs** (event missing / too few): contributes nothing; the
  panel notes "0 epochs" for it.
- **NaN** inside an epoch: interpolated in `resample_to_percent` when bounded by
  finite samples; otherwise that node is NaN and excluded by nan-aware stats.
- **n = 1** (single epoch pooled): SD = 0 / NaN band; still plots the mean.
- **Mismatched `points`** across trials: the panel requires one `points` per
  `NormalizeStep name` (it is a property of the step), so all trials agree.
- Selected trials lacking the chosen `NormalizeStep` output are skipped with a
  visible note.

## 9. Forward-Compat: Discrete value-at-event (NOT built in V1)

The same `[1]→[2]` index (epochs keyed by event occurrence, poolable across
trials) yields discrete values by taking the signal **at the event frame**
instead of the resampled curve. Because that output is **scalar**, it rides the
existing `ResultsStore` "Results" row schema and the current Export/Statistics
hand-off — no new export channel. V1 only ensures the epoch/event metadata
(`meta`) is rich enough to add this as a thin sibling later.

## 10. Testing Strategy

Pure-unit (no Qt):
- `resample_to_percent`: a known ramp/sine resamples to exact analytic values at
  0/50/100%; NaN-bounded interpolation; all-NaN → all-NaN.
- `epoch_windows`: gait events → correct consecutive pairs; start/end pairing;
  whole-trial fallback; unequal counts.
- `ensemble.pool` / `ensemble_stats`: nan-aware mean/sd, n counting, n=1.
- `NormalizeStep` through `run_pipeline` on synthetic signal+events → expected
  matrix shape and values; `:filt` input actually flows.
- Round-trip `to_dict`/`from_dict` for `NormalizeStep`.

UI-smoke (offscreen):
- Ensemble panel builds; pooling two synthetic trials yields the right mean/sd;
  CSV writer emits the §7 shape; editing/deleting the step updates the plot.

All existing tests stay green.

## 11. Build Order (for the plan)

1. `core/normalize.py` (resample + windows + extract) + tests.
2. `core/ensemble.py` (pool + stats) + tests.
3. `NormalizeStep` in `core/pipeline.py` + `run.py` wiring + tests.
4. Analyze "Ensemble" panel (plot) + the Add/Edit NormalizeStep dialog.
5. CSV export + tests.

Layers 1–3 are pure/headless and independently testable; 4–5 are the UI surface.
