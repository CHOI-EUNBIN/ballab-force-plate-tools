# Walk preset — UI/UX overhaul direction (multi-session handoff)

Date: 2026-06-27 (overnight session). Self-contained brief so a FRESH chat can
continue. Repo: `c:\Users\eunbin\Desktop\BalanceAnalyzer\BalanceAnalyzer`.
Python: `.venv\Scripts\python.exe`. Tests: `python -m pytest -q` (Qt: prefix
`QT_QPA_PLATFORM=offscreen`, retry once on native crash). Work is NOT committed
(user branches/commits later — do not ask about commits; keep changes in the
working tree). Respond to the user in Korean.

## Where we are
G4 walk preset is BUILT and engine-correct: `core/presets.py` has
`walk_treadmill(dataset)` and `walk_overground(dataset)` (registry `PRESETS`,
`build_preset(name, dataset)`). Supporting engine pieces shipped: lab-frame foot
signals `gait:<SIDE>_<heel|toe>_<ap|ml>_lab` (core/gait_events.py
`foot_lab_series` + core/signals.py), ops `product`/`quotient`/`displacement_between_events`
(core/metrics.py + metrics_compute.py). Suite: 554 passed / 30 skipped (the 30
skips are all MISSING YA01/YA02 example c3d files — harmless). A UI "Apply
preset" combo+button was added in `ui/analyze_tab.py` (`_apply_preset`, ~L3164;
widgets ~L850) — but see problem D, it is in the wrong place.

## Engine is CORRECT — verified headless on CEB (do NOT re-derive)
`build_preset("walk_treadmill", dyn)` → `run_pipeline` on CEB gives, per side:
stride time 1.123 s, stance 67.2 %, cadence 106.9, knee ROM 44°, double support
**0.196 s**, gait speed 1.077 m/s, stride length 1.21 m, L ankle angle@HS 104.6°.
**The headless `run_pipeline` is the authoritative, correct path.**

## The user's directive (the problems to fix — "uiux 제대로 구축")
The app SHOWS wrong/poor things even though the engine is right:

**A. Metrics give only the MEAN; reference ops pop up a single value.**
`ui/analyze_tab.py::_show_metric_table` (L1853): if a metric has a per-cycle
`cycles` array it opens a data TABLE (+ a mean±SD popup); else (n=1) it shows a
bare `QMessageBox` "value: …". The spatiotemporal/derived REFERENCE ops
(`cadence`, `cadence_stride`, `stance_pct`, `swing_pct`, `symmetry_index`,
`symmetry_ratio`, `product`, `quotient`, `cv`) compute ONE scalar from the
already-aggregated MEAN (see `core/metrics_compute.py::_reference_value`, which
reads scalar metric values via `_metric_ref`) → `cycles=None` → popup, NO raw
data. **User wants the RAW per-cycle data** ("stride time 구했는데 평균만 주면
안 되지 raw데이터를 왜 안줘"). Mean is secondary (a stats view / aggregate
metric). → ENGINE FIX: make these ops produce a PER-CYCLE array where it is
meaningful (cadence per stride = 120/each stride time; stance% per cycle =
each stance time / each stride time; symmetry needs paired L/R per cycle), so the
result carries `cycles` + mean±SD just like `time_between_events`.

**B. Results are a TABLE/popup, not GRAPHS.** Even cyclic metrics open a data
table. The user wants to SEE per-cycle series and signals as PLOTS. No
angle/signal graphs appear; `signal`-catalog values are not viewable as graphs.

**C. No filtering, no angle curves, no ensemble seeded.** The preset seeds only
DetectEvent + Metric(+ a few Compute) — NO `FilterStep` (markers/forces
unfiltered), no graphable joint-angle output, and no `NormalizeStep` → the
ensemble panel (0–100 % mean±SD curve, which EXISTS: `ui/ensemble_panel.py` +
`core/ensemble.py` `pool_sources`/`ensemble_from_runs`) stays empty. Gait
analysis is fundamentally about NORMALIZED CURVES; the preset omitted them.

**D. Preset belongs INSIDE the "+" Add-Pipeline-Step popup**, not as a separate
combo+button outside the pipeline. The popup (`AddStepDialog` in
`ui/analyze_dialogs.py`) already groups PROCESS (Filter / Compute joint angles /
Compute signal / COP trajectory), DETECT (Detect Event), MEASURE (Metric /
Normalize). Add a "Preset / Quick start" category there; REMOVE the outside
combo+button.

**E. Reproducible + native UIUX.** Whatever the preset computes, the user must be
able to rebuild by selecting steps in the UI and get the SAME result, displayed
in the CURRENT pipeline UI/UX (results inline as raw series + graphs, not a
popup mean).

## Key code locations
- Metric display / popup vs table: `ui/analyze_tab.py::_show_metric_table` L1853;
  `_open_data_table` (data-table widget); run result cached as
  `self._last_run_result` (full metric dicts with `cycles`/`mean`/`sd`/`n`).
- Reference-op aggregation (root of "mean only"): `core/metrics_compute.py::_reference_value` and `compute_metric_step`; per-cycle windows via `cycles_from_events`; `_window_value` per-cycle.
- Preset entry to move: `_apply_preset` (`ui/analyze_tab.py` ~L3164) + the
  combo/button (~L850 in `_build_pipeline_section`). Target popup:
  `ui/analyze_dialogs.py::AddStepDialog`.
- Ensemble (already built): `ui/ensemble_panel.py`, `core/ensemble.py`
  (`pool_sources`, `ensemble_from_runs`), NormalizeStep run in
  `core/run.py::_run_normalize`, math in `core/normalize.py`.
- Angle output "sole source" rule: angles graph only if a step generates them —
  see `ui/analyze_tab.py::_angle_result_for` / ComputeAngleStep. The preset must
  include the angle-producing step so angle curves are viewable.
- Presets: `core/presets.py`. Step classes: `core/pipeline.py`.

## Proposed build order (TDD, headless-testable first)
1. **Per-cycle for reference ops** (engine): `cadence`/`cadence_stride`,
   `stance_pct`/`swing_pct` (and ideally `symmetry`/`cv`) return a per-cycle
   array + mean±SD, not a scalar from the mean. Then `_show_metric_table` shows
   the table/graph for them automatically. Pin with tests + CEB (mean must match
   the current scalar, e.g. cadence ≈ 106.9, stance ≈ 67.2).
2. **Metric result as a GRAPH** (UI): plot the per-cycle series (and offer the
   0–100 % normalized curve) instead of / alongside the table; stop using a bare
   value popup.
3. **Preset into the "+" popup** (UI): add a Preset/Quick-start category in
   `AddStepDialog`; remove the outside combo+button.
4. **Preset seeds visualization** (presets): add `FilterStep` (marker + force
   low-pass), the angle-producing step (so `angle:*` curves show), and
   `NormalizeStep` for the key angle channels (so the ensemble panel draws
   mean±SD curves). Keep it editable.
5. **Reproducibility check**: app result == headless `run_pipeline`; the preset's
   steps are all individually addable via the popup.

## Progress (update as you go)
- [DONE 2026-06-27] **Step 1 (engine): per-cycle reference ops.**
  `core/metrics_compute.py::_reference_value` now computes `cadence`,
  `cadence_stride`, `stance_pct`, `swing_pct`, `product`, `quotient` PER CYCLE
  (helper `_reference_cycle_arrays` + set `_PER_CYCLE_REFERENCE`) → result carries
  a `cycles` array + mean±SD instead of one scalar from the means. So
  `_show_metric_table` shows the per-cycle table (not the value popup) for them.
  Pinned by `tests/test_run.py::test_reference_ops_are_per_cycle_not_mean_only`.
  Suite 555 passed / 30 skipped. (`symmetry_*` stay scalar — L/R, no per-stride
  pairing; `cv` already array-based.)
- [DONE 2026-06-27] **Step 4 (presets): seed filtering + angles + normalize.**
  `core/presets.py` both `walk_treadmill`/`walk_overground` now start with
  `_filter_and_angles()` = `FilterStep(FilterSpec(cutoff_hz=6.0), markers=True)` +
  `ComputeAngleStep(joints=_ANGLE_CHANNELS)` (so `angle:*` exist & graph — the
  pipeline is the SOLE angle source), and add `_normalize_curves(side)` =
  `NormalizeStep(input="angle:<S>_<J>_angle_FE", mode="cycle", event="<S>_HS",
  points=101)` per joint so the Ensemble panel draws 0–100 % mean±SD curves.
  Pinned by `tests/test_presets.py::test_walk_preset_seeds_filter_angles_and_normalize`.
  e2e CEB values held within tolerance; suite 556 passed / 30 skipped.
- [DROPPED] **Step 2 (metric→graph): cancelled** — conflicts with the user's
  EXISTING design (confirmed in code): signals (raw/`:filt`/`angle:*`/`gait:*`/
  Normalize "mean±SD" — all kind `"signal"`, `ui/analyze_tab.py` L1488) are
  GRAPHABLE; metrics are TABLES (`_show_metric_table` L1853). Step 1 (per-cycle
  table) + Step 4 (graphable signals/curves) already match this. Do NOT turn
  metrics into graphs.
- [DONE 2026-06-27] **Step 3 (UI): preset moved into the "+" popup.**
  `AddStepDialog` (ui/analyze_dialogs.py) has a new "Quick start" group with
  `preset_walk_treadmill`/`preset_walk_overground` commands (info pages); the "+"
  handler `_append_step` (ui/analyze_tab.py ~L3038) routes `kind.startswith("preset_")`
  → existing `_apply_preset(name)`. The outside combo+button were removed from
  `_build_pipeline_section`. Suite 559 passed / 30 skipped.
- [TODO] **Step 5 — verify in the RUNNING app** (needs the GUI, can't be done
  headless): (a) per-cycle TABLES show for cadence/stance%/swing% (no more value
  popup); (b) `angle:*` + `gait:*` graph, and the Normalize "% cycle (mean±SD)"
  ensemble curves draw; (c) **the "Double support = 200 s" display bug** — engine
  is CORRECT headless at BOTH fs=100 and fs=1000 (0.196 s), so the app's metric
  PANEL is not using the authoritative `run_pipeline` result (probably computes
  metrics with an incomplete cross-label event context → whole-trial fallback =
  trial length). Find the app's own metric-compute/display path (NOT
  `run.run_pipeline`; look near `ui/analyze_tab.py` ~L5824-5892 "Cache the full
  run result on the dataset" and `_last_run_result`) and make the panel read the
  same per-cycle result the engine produces. (d) app values == headless.

## RUNNING-APP findings 2026-06-27 (Step 5 — from screenshots, must fix next)
Ran the treadmill preset in the GUI. What's seen:
- ✅ **Ensemble curve WORKS** — "Ensemble — angle:R_HIP_angle_FE [R Hip % cycle]"
  draws a clean mean±SD curve. NormalizeStep→ensemble path is good.
- ❌ **Angle/spatiotemporal metric VALUES are wrong in the app**: L Ankle ROM
  **0.276°** (should be ~52°), L Ankle peak ang.vel **0.596 deg/s** (should be
  ~1110), Double support R **5 s** (should be 0.196 s). The app DOES call
  `core.run.run_pipeline` (ui/analyze_tab.py L5870-5879, caches `dataset["_run_result"]`,
  marker_disp = `self._marker_display_data(markers)` = display markers,
  angle_result = `_angle_result_for`). **ROOT CAUSE NOT YET CONFIRMED.** Note:
  `core/signals.py::Workspace.filtered_marker_data` filters at `markers["rate"]`
  (correct), so a marker-filter-fs mismatch is UNLIKELY — discard that earlier
  guess. REPRODUCE the app's exact path headless: load CEB, build the preset, run
  `run_pipeline(dataset, pipeline, marker_disp=self._marker_display_data-equivalent
  (FILTERED), angle_result=<model on filtered markers>, subject=...)` with the SAME
  master clock the app uses (check whether the app's `dataset["time"]/["fs"]` is the
  100 Hz marker clock or the 1000 Hz force clock — the screenshot logged fs=100, but
  confirm). Then inspect per-cycle windows for "L Ankle ROM": near-zero ROM ⇒ either
  the angle channel is read on a mismatched clock vs the event frames (tiny/incoherent
  windows) OR the angle array itself is flat. Compare to the known-good headless run
  (ROM ~52°) to find what input differs. Fix so the app result == headless.
- ❌ **Double support 5 s** (cross-label R_HS→L_TO) — separate from the filter;
  re-check after the filter fix with filtered disp; may be a cross-label pairing /
  clock issue in the app's event context.
- ❌ **Derived-signal graph EMPTY**: right-clicking `R_heel_vel` (a ComputeStep
  output) to graph it shows axes but NO curve. ComputeStep-output signals
  (`R_heel_vel`/`R_heel_speed`/`*_mps`) are listed under "Derived signals" and are
  togglable, but the plot draws nothing. The figure/plot path doesn't resolve
  ComputeStep outputs for drawing (works for the ensemble + raw signals). Fix the
  signal-plotting path to resolve compute outputs via the Workspace.
- ❌ **Filtered signals not in results**: user expects that once a FilterStep is
  added, the `:filt` twins appear in RESULTS·Signals exactly like a manually-built
  pipeline ("기존 사용자가 하는 파이프라인과 똑같은 결과를 남기라고"). The preset
  must leave the SAME result set as the manual path.
- ❌ **Ensemble shown twice**: as a Signals toggle ("Ensemble overlay" → "R Hip %
  cycle (mean ± SD)") AND as the separate bottom "Ensemble" panel/section. Pick
  ONE — if it's a signal toggle, remove the bottom Ensemble toggle (the §C item-4
  dedup, now concrete).

## RESOLVED 2026-06-27 (Step 5 metric-value bug — #1)
The metric-value bug (L Ankle ROM 0.276°, Double support 5 s) **does NOT reproduce
in the current code** — it was already fixed by the earlier [DONE] steps
(per-cycle reference ops + `_invalidate_event_caches()` in `_apply_preset` +
filter/angles seeding). Confirmed by driving the REAL `AnalyzeTab` path headless
(offscreen Qt) on CEB + walk preset: L Ankle ROM 41.4°, Double support R 0.187 s,
stride 1.123 s, cadence 106.9 — all match the headless `run_pipeline`. The panel
reads `dataset["_run_result"]` (pipeline), and the legacy self-calc paths are
disabled (`selected=[]`, `angle_stats=[]` in `_run_analysis`). Pinned by
`tests/test_preset_app_path.py` (drives the tab, asserts physiological per-cycle
metrics). KNOWN REMAINING (user said "leave for now"): `peak_angular_velocity` /
`peak_angular_acceleration` / `rfd` report a SIGNED cross-cycle mean via
`metrics._peak_abs`; for bidirectional joints (e.g. knee) per-cycle signs alternate
and cancel (R Knee peak ang.vel shows 100 vs true magnitude ~255 deg/s). Fix later:
make the `_peak_abs` family report magnitude, or split flexion/extension peaks.

## Watch out
- The app's metric PANEL value vs headless: confirm the panel uses the same
  `run_pipeline` result (`_last_run_result`). If the panel ever shows 200 s for
  "Double support" while headless gives 0.196 s, the UI is computing on a stale /
  partial event context — fix the UI to use the authoritative run result.
- Keep UI labels ENGLISH (project rule); converse in Korean.
- Do NOT break the 554-passing suite; TDD every engine change.
