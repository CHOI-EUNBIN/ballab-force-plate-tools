# Pipeline Run / Clear Controls — Design

Date: 2026-06-29
Status: Approved (pre-implementation)
Area: `ui/analyze_tab.py` (PIPELINE sidebar + RESULTS panel), preset apply path

## Problem

The PIPELINE header `▶` button is a checkable toggle: ON runs the whole
pipeline over all checked files; OFF clears every file's results and returns to
raw review. In practice this reads as broken:

- Quick Start seeds the recipe and the panels immediately render the derived
  signals / events / graphs ("what the recipe would produce"). Only RESULTS ▸
  Metrics waits for `▶`. So pressing `▶` appears to do nothing — most of the
  screen is already populated.
- The toggle's second-press "clear all results" behavior is surprising: a Run
  control that also deletes results conflates two unrelated jobs.

The user builds pipelines incrementally and wants predictable, explicit
controls. Deletion should always be an explicit delete action; Run should only
ever generate.

## Decisions

1. **No auto-run anywhere.** Quick Start (and project load) seed steps only.
   Results are generated solely when the user presses Run.
2. **Before Run, show raw data only.** Loaded raw signals (force / COP / etc.)
   render. Pipeline-derived signals, events, and metrics appear only after Run.
3. **Run is a plain momentary button, generation-only.** It never deletes.
   Pressing it again (or repeatedly) just regenerates; nothing is cleared.
4. **Full recompute each Run.** The whole pipeline runs front-to-back on every
   press. Intermediate-result caching is explicitly deferred — added later only
   if Run becomes noticeably slow. Per-step ("개별 run") execution is NOT added:
   in a dataflow pipeline step N depends on steps 1..N-1, so "run this step"
   collapses to "run 1..N" and yields no real saving.
5. **Two independent delete axes — STEPS and RESULTS — each with all + one.**
   - Steps: delete-one (exists, row `✕`) + delete-all (new, header glyph).
   - Results: delete-one (new, one RESULTS item) + delete-all (new, panel glyph).
6. **Icons are monochrome line glyphs only** (the app's existing `+` `▶` `✎`
   `✕` / VS Code codicon language). No color emoji anywhere in UI or code.

## UI Specification

### PIPELINE sidebar (the recipe)

Unchanged:
- `+` add step (header)
- `✎` edit step on row hover
- drag-to-reorder
- per-step enable/disable checkbox
- `✕` delete-one step on row hover; Delete key on the focused list

Changed / new:
- **Header `▶` becomes a plain non-checkable Run button.** Click → run the full
  pipeline over the checked files and show results. It is no longer a toggle and
  has no clear-on-second-press behavior.
- **New header "clear all steps" glyph** (monochrome clear-all codicon-style
  icon, distinct from the per-row `✕`). Click → empty the entire pipeline.
  Confirm before wiping a non-empty pipeline.

Header order (left→right): `+`  ·  clear-all-steps glyph  ·  `▶` Run.

### Pre-Run view

When no Run has been performed for the current dataset, the main view shows only
the raw loaded signals. The preset-seeded derived signals / events / metrics are
NOT rendered until Run. (This replaces today's "panels show what the recipe
would produce" behavior for the derived items; raw data is unaffected.)

### RESULTS panel (generated output)

- **New "clear all results" glyph** in the RESULTS panel header (monochrome
  clear-all icon). Click → clear all generated results. This is the explicit,
  standalone replacement for the retired toggle-off behavior. After clearing,
  the view returns to raw (pre-Run) state. Scope mirrors the old toggle-off:
  clears results for all files, not just the current one.
- **New per-item delete:** each RESULTS item (a single signal / event / metric
  row) gets a hover `✕` that removes just that item. Events already expose a
  Delete affordance; extend the same to signal and metric rows for symmetry.

## Behavior Details

- Run with no loaded files / no checked files: keep the existing guard messages
  ("Load files…" / "Check files…"). Run does not toggle any state on failure
  (no toggle to revert anymore).
- Re-Run after editing/adding/removing steps: full recompute; a fresh Run
  regenerates all detected events (drops view-level event deletions), unchanged
  from today.
- Clearing all steps does not by itself clear existing results, and vice versa —
  the two axes are independent. (A subsequent Run on an empty pipeline produces
  no derived output, returning the view to raw.)
- "Clear all results" returns every file to the pre-Run (raw-only) state and
  drops cached run results so the metric/derived panels read empty.

## Touch Points (for the implementation plan)

- `AnalyzeTab._apply_preset` (`ui/analyze_tab.py:3249`) — already seed-only;
  confirm it never triggers a run and that derived rendering is gated on "has
  run".
- `show_btn` construction (`ui/analyze_tab.py:851`) and
  `_on_show_results_toggled` (`ui/analyze_tab.py:4187`) — convert toggle →
  momentary Run button wired to `_run_analysis`; remove the clear-on-toggle-off
  branch.
- Add header "clear all steps" action next to `+` (`ui/analyze_tab.py:843-877`),
  calling a new `_clear_pipeline` (empties `self.pipeline`, refresh).
- Project load auto-run path (`ui/analyze_tab.py:~4799-4807`) — drop the
  auto-`setChecked(True)` so loading no longer auto-runs.
- Gate pre-Run rendering so only raw signals show until a run exists for the
  dataset (derived signal / event / metric population keyed on run state).
- RESULTS panel header — add "clear all results" action (new
  `_clear_all_results`, generalizing the retired toggle-off body).
- RESULTS rows — add per-item hover `✕` delete (new `_delete_result_item`),
  extending the existing Events delete to signals + metrics.

## Out of Scope / Deferred

- Per-step ("개별 run") / run-to-here execution.
- Intermediate-result caching / incremental recompute.
- Any color-emoji iconography.
