# BalanceAnalyzer — Future development direction (consolidated 2026-06-27)

Self-contained roadmap written at the end of an autonomous hardening session.
Pulls together everything found + fixed and everything deliberately deferred, so a
fresh chat can pick up with a clear, prioritized backlog. Sources:
`docs/autonomous-2026-06-27/{engine,ui,help-docs}-report.md` and
`researcher-review.md`. Repo: `…\BalanceAnalyzer\BalanceAnalyzer`. Tests:
`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q`.
Nothing is committed (user branches/commits later).

## Session outcome (2026-06-27)
- Start: 559 → end: **593 passed, 30 skipped** (skips = missing example c3d, harmless).
- Incomplete-data load handling: marker occlusion/missing was detected internally
  but NEVER surfaced — now `clean_markers` reports `markers_missing`/`labels_missing`,
  `summarize_marker_reports`/`any_markers_missing` build the note, and `_ingest`
  escalates the load dialog to a WARNING naming the absent markers; CSV missing a
  required column now raises a clear message (not a raw KeyError). +6 tests
  (`tests/test_data_quality.py`, `tests/test_load_incomplete.py`).
- Engine (`core/`): 4 bugs fixed + robustness/logging + 13 tests.
- UI (`ui/`): 3 bugs fixed + empty-state polish + ensemble de-dup + 7 tests.
- Help docs: +6 entries — new "Signal operations (building blocks)" + "Quick start —
  task presets" categories (`ui/help_dialog.py`), sync test kept green (+6 tests).
- Researcher: 41 calc methods reviewed — engine is scientifically sound; 1 P1
  (deferred by user), 5 P2 (acceptable/document), several P3 enhancements.
- Task #1 (preset metric values L Ankle ROM 0.276° / Double support 5 s):
  **NOT reproducible — already fixed**; pinned by `tests/test_preset_app_path.py`.
- Engine round-2 (safe P2 robustness: epoch-meta honesty / narrowed excepts /
  boundary guards): the agent **STALLED mid-stream and its changes did NOT land**
  (core tests still intact). Those items remain open below as P2 #3–#6 — pick them
  up next session.

## Priority backlog

### P1 — Correctness (one item, user-DEFERRED)
1. **Peak velocity/acceleration sign cancellation.** `metrics._peak_abs` returns a
   SIGNED per-cycle peak; `compute_metric_step` then averages signed peaks across
   cycles, so bidirectional joints (knee/hip/ankle FE) cancel (R Knee peak ang.vel
   shows ~100 vs true magnitude ~255 deg/s). Affects `peak_angular_velocity`,
   `peak_angular_acceleration` (`rfd` safe in presets — Fz pre-rectified).
   **User said "leave for now" — do NOT change until confirmed.** When greenlit,
   the clean fix: make `_peak_abs` return magnitude `|a[idx]|` for these ops
   (per-cycle ≥0 → meaningful mean), and/or add direction-split ops
   `peak_velocity_pos`/`peak_velocity_neg` (Visual3D Max/Min pattern). Current
   behaviour is pinned by `test_metrics.py::test_peak_abs_returns_signed_extremum_documented`.

### P2 — Robustness (low risk, high value)
> **Status update 2026-06-28:** the working tree is ahead of this doc. #3, #4, #5
> and #6 are DONE + pinned (see notes inline below). Only #2 remains open. The
> metric calculation-failure-feedback mechanism (a separate planned task) is also
> already built + tested (`core/diagnostics.py`, `tests/test_diagnostics.py`,
> `tests/test_metric_feedback.py`; UI ⚠/◐ at `analyze_tab.py::_populate_metrics_list`).

2. **Tighten the detected-events cache token** (`events_compute._detect_token`):
   fold in a cheap `marker_disp`/`angle_result` identity stamp so a different
   display array for the same recipe can never serve stale events. Add a test that
   changes `marker_disp` and asserts re-detection. (Realistic paths are safe today
   because marker/angle filtering flows through FilterSteps that ARE in the token —
   so this is a belt-and-braces fix, not an active bug.)
3. **[DONE]** Make `extract_epochs` meta honest (`core/normalize.py`): a window
   whose end index exceeds the array length is silently clipped but `meta["end"]`
   still reports the requested index → downstream labels can mismatch the data.
   `meta["end"]` now clamps to the real slice end (`i0 + seg.size - 1`); pinned by
   `tests/test_normalize.py::test_extract_epochs_meta_end_clamped_to_real_slice`.
4. **[DONE 2026-06-28]** Replace remaining broad `except Exception`:
   `core/run.py::_run_normalize` now narrows to `(KeyError, ValueError)` + a debug
   log (an unexpected error propagates as a genuine bug). `marker_model.apply`'s
   COM block stays broad (the additive COM channel must NEVER break the legacy
   angle/segment outputs — narrowing+propagating would violate that) but now logs
   a breadcrumb (`exc_info`) instead of a bare `pass`, mirroring
   `core.metrics.compute_metrics`. Pinned by
   `tests/test_run.py::test_run_normalize_surfaces_unexpected_error` /
   `…_degrades_on_unresolvable_signal` and
   `tests/test_com.py::test_apply_com_failure_leaves_breadcrumb`.
5. **[DONE]** Validate inputs at module boundaries: `core/signals.py::_validate_time`
   (called by `Workspace.__init__`, so `run_pipeline` too) raises a clear ValueError
   for a missing / multi-D / non-monotonic `dataset["time"]`; empty/1-sample clocks
   pass. Pinned by `tests/test_time_guard.py` (6 tests).
6. **[DONE 2026-06-28]** Surface UI Workspace-resolution failures instead of
   swallowing: `_render_force_curves` now puts a small "could not compute" note on
   the plot (via `_set_plot_note`) when a *visible* derived curve can't resolve,
   plus a log breadcrumb — the silent empty-axes failure (UI BUG 1 class) is now
   visible. Pinned by `tests/test_ui_hardening.py::test_unresolvable_signal_shows_plot_note`
   / `…_resolvable_signal_has_no_plot_note`.

### P3 — Scientific enhancements (from researcher review)
7. **[DONE 2026-06-28]** Total double-support %: added reusable reference ops
   `add` (a+b) and `double_support_pct` (ds/stride*100); the walk presets now seed
   `Total double support time` (= DS R + DS L) and `Total double support %`
   (÷ R Stride time, ~20% normal). Pinned by `tests/test_double_support.py` (10).
8. **[PARTIAL 2026-06-28]** COM ops + `com:*` signals.
   DONE: `com:x`/`com:y`/`com:z` world-frame signals exposed (pipeline-gated —
   resolves from `model_result["com"]`, clear ValueError otherwise) + an **XCOM**
   ComputeStep method (`signal_ops.xcom`, Hof 2005; `length_m`=COM-height pendulum
   param, all-NaN if absent — never a guessed length). Pinned by
   `tests/test_com_signals.py` (8) + `tests/test_xcom.py` (7).
   STILL DEFERRED (don't guess wrong numbers): **MoS** (needs a reliable
   base-of-support boundary from foot markers), **COM–COP separation** (COM is
   world-frame, COP is plate-local X/Y — frame alignment not guaranteed), and
   **`com:ap`/`com:ml`** (needs the progression axis, P3 #13). XCOM is the
   building block MoS sits on once BoS is defined.
9. **Exact Prieto F-statistic ellipse** (`2·F_{0.05[2,n-2]}` vs current χ²≈5.991;
   agree <0.2% for large n, slight under-estimate on short trials).
10. **Optional Hann window** for COP spectral metrics (reduce leakage on short
    records).
11. **Wire step-width / step-length building blocks into a preset** (ML/AP foot
    displacement ops already exist).
12. **Subject- vs cycle-weighted group statistics** option for ensemble pooling.
13. **Pin progression axis** when a lab frame is known (avoid geometric
    auto-detect misfires on turns / stepping-in-place).

### P4 — Maintainability / architecture
14. **Decompose `ui/analyze_tab.py` (~6.6k lines)** panel-by-panel into
    `ui/components/` widgets (Pipeline row, RESULTS lists, graph host, file tree),
    one panel at a time with a smoke test + relaunch after each. Single biggest
    maintainability lever. HIGH RISK to do blindly — move incrementally.
15. **Centralise NaN-safe mean-centring** (`_centre_nan(ap, ml)`) — `compute_metrics`,
    `compute_ellipse_points`, `cop_resultant`, trajectory all re-implement it (the
    drift that caused engine Bug 2).
16. **Extract a `_row_key(item)` helper** in the UI — the `("group"|"hint", None)`
    actionability guard is now duplicated across three menu handlers.
17. **Property-based tests (Hypothesis)** on pure ops (`signal_ops`, `events`,
    `normalize`): "never raises / never returns wrong length" over empty /
    single-sample / all-NaN / non-uniform-clock inputs.
18. **Graph-area empty-state widget** ("Right-click a signal in RESULTS to graph
    it") + fold the export-only Ensemble panel into a right-click on the overlay row.

## Memory corrections discovered this session
- The angle engine now computes **full ISB Grood-Suntay JCS Cardan 3-component
  angles** (FE/AB/IE), NOT vector angles. The `event-pipeline-redesign` memory note
  describing vector angles is STALE.
- The metric-value bug in `walk-preset-uiux-direction.md`'s screenshots is RESOLVED
  (does not reproduce); that doc's "RUNNING-APP findings" UI items (derived-signal
  empty graph, duplicate ensemble) are now FIXED too. The `:filt`-not-in-results
  item was NOT a bug (marker-only FilterStep produces no signal twins by design).

## What is NOT a bug (verified — don't re-investigate)
- Filtered `:filt` twins absent after the walk preset's FilterStep: the preset
  filter is marker-only (`markers=True`), so it produces no signal `:filt` twins —
  identical to a hand-built marker-only filter. A signal-targeting FilterStep DOES
  list `<key>:filt`.
- Preset metric values: app reads `dataset["_run_result"]` (pipeline); legacy
  self-calc is disabled (`selected=[]`, `angle_stats=[]`). Physiological + pinned.
