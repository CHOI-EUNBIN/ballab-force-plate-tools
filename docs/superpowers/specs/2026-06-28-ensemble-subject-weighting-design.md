# Ensemble: subject-weighted pooling + consolidate controls into the overlay right-click

Design spec (brainstormed 2026-06-28). Scope is **"기능 ①" only** — the ensemble
side. The cross-cutting **cycle quality filter** (drop first N / last M cycles,
"all analysis common") is **deferred** — its UI home is undecided (see Out of
scope). Nothing here is committed (project convention: working tree only).

## Problem

Two issues with the current cross-trial ensemble:

1. **Count-imbalance bias.** `core.ensemble.pool` pools *every* cycle from every
   checked trial with equal weight ("cycle-weighted"). A subject with 100 cycles
   dominates the group mean over one with 40. The biomechanics standard for a
   group ensemble is **subject-weighted**: average each subject to one
   representative curve first, then average across subjects (each subject = one
   vote). This removes the bias and means cycle counts need NOT be equalised.

2. **Inconsistent controls.** Every RESULTS·Signals row is driven by a right-click
   menu, but the ensemble is special-cased: the "Ensemble overlay" row's menu only
   offers *View as graph*, while **Export CSV lives on a separate plot-less
   "Ensemble export" panel** (`EnsemblePanel(show_plot=False)`), and the proposed
   per-cycle/per-subject control was a panel toggle. This split is the source of
   user confusion.

## Current state (verified)

- `core/ensemble.py`: `pool(matrices)` stacks all rows; `pool_sources(sources)`
  flattens `(label, norm_dict)` → matrices → `pool`; `ensemble_csv` writes the
  pooled epochs. All epoch-weighted.
- `ui/analyze_tab.py`:
  - `_refresh_ensemble_panel` builds `sources = [(ds.name, norm_dict), ...]` from
    each checked dataset's `_run_result["normalized"][norm_name]`. **No subject
    identity carried.**
  - The "Ensemble overlay" RESULTS row (`_append_ensemble_signal_row`, key
    `ensemble:<name>`); its right-click menu (`_show_results_signals_menu`) only
    has View / Remove-from-view.
  - The plot-less `EnsemblePanel` is embedded as the "Ensemble export" section
    (title + "N epochs" + Export CSV + hint). The real mean±SD curve is the
    main-area "Ensemble overlay" (`_set_ensemble_view` / `_build_ensemble_plot`).
- Subject identity = the dataset's `folder` tuple (`ds["folder"]`); subject
  metadata is keyed by it.

## Design

### A. Subject-weighted pooling (engine)

`core/ensemble.py`:

- `pool(matrices)` stays the row-pooling primitive — **unchanged**.
- The new **mode** lives at the `pool_sources` level (it needs per-source subject
  identity, which `pool` doesn't see):
  - `pool_sources(sources, mode="cycle")` — current behaviour: concatenate all
    rows, mean±SD over rows.
  - `mode="subject"` — group sources by `subject` key; within each subject
    concatenate its rows and take the **NaN-aware column mean → one (P,) curve per
    subject**; stack those per-subject curves; mean±SD over them. `n` = number of
    subjects; also report `n_cycles` = total rows used.
- Sources gain an optional subject id. Shape becomes
  `(label, norm_dict, subject_key)`; a missing `subject_key` falls back to
  `label` (each trial = its own "subject", so `mode="subject"` degrades to
  per-trial — safe).
- `ensemble_stats` result dict gains `n_subjects` and `n_cycles` so the UI can
  label either mode. `ensemble_csv` writes whichever pooled matrix the active
  mode produced (per-subject curves, or all cycles).

Math note: subject-weighting is *mean of per-subject means*, NaN-aware at every
step (a subject whose column is all-NaN contributes NaN there; an absent subject
simply isn't in the stack). For a single subject, `mode="subject"` yields n=1 and
an undefined/zero SD — which is why the default stays `cycle` (below).

### B. Consolidate ensemble controls into the overlay right-click (UI)

`ui/analyze_tab.py`, `_show_results_signals_menu`, the `ensemble:` branch:

```
Ensemble overlay  (right-click)
  View as graph            (or "Remove from view")
  ──────────────────────────
  Average ▸  ● per cycle        ← checkable radio (QActionGroup)
             ○ per subject
  ──────────────────────────
  Export CSV…              ← was the panel button
```

- `Average` submenu: two checkable, mutually-exclusive actions. Selecting one sets
  the ensemble pooling mode (stored on the tab, e.g. `self._ensemble_weight`),
  re-pools, and refreshes the main-area overlay curve + its title.
- `Export CSV…` moves here (reuses the existing export path / `ensemble_csv`).
- The pooled **count** moves to the **overlay graph title** in the main area, mode
  aware: `"Ensemble — angle:R_KNEE_FE  ·  3 subjects (200 cycles)"` for subject
  mode, `"… · 200 cycles"` for cycle mode.
- The separate plot-less **"Ensemble export" panel is removed** (its two jobs —
  count + export — now live in the title and the right-click). `EnsemblePanel`
  itself (the standalone, with plot) stays for any other caller; only the embedded
  plot-less section is dropped.

### Data flow

```
checked datasets → _refresh_ensemble (build sources WITH subject_key=ds["folder"])
   → pool_sources(sources, mode=self._ensemble_weight)
   → ensemble_stats {mean, sd, n_subjects, n_cycles}
   → main-area overlay curve + title   (+ Export CSV on demand)
```

### Defaults

- **Default mode = `cycle`** (current behaviour). Rationale: a single-subject
  analysis needs within-subject (cycle) SD; subject mode would give n=1. The user
  switches to `per subject` for group comparisons. (A future "auto: subject when
  >1 subject" is possible but out of scope — YAGNI.)

## Testing (TDD)

Engine (`tests/test_ensemble.py`):
- `pool_sources(mode="subject")`: two subjects with **unequal** cycle counts
  (e.g. 3 and 1 rows) → mean == unweighted mean of the two per-subject means (NOT
  the 4-row mean); `n_subjects == 2`, `n_cycles == 4`.
- `mode="cycle"` unchanged (regression): equals the all-rows mean.
- subject_key fallback to label when omitted.
- NaN-aware: an all-NaN column in one subject doesn't crash; degrades to the other.

UI (`tests/test_ui_*`):
- The `ensemble:` right-click menu contains "Average" (per cycle / per subject,
  checkable) and "Export CSV…".
- Switching mode updates `self._ensemble_weight` and re-pools (smoke).
- The embedded "Ensemble export" panel is gone (no `_ensemble_panel` section), or
  asserted absent.

## Implementation notes / deviations (2026-06-28, IMPLEMENTED)

Done, TDD, all green (671 passed, 30 skipped). Deviations from the spec above:

- **`n_subjects`/`n_cycles` live on the `pool_sources` return dict**, not on
  `ensemble_stats` (which is a pure matrix→stats fn that can't see subjects).
  Same outcome: the UI reads them for the title.
- **The plot-less `EnsemblePanel` object is kept as a headless pooling/stats/
  export helper** (`self._ensemble_panel`, NOT added to any visible layout) rather
  than deleted — the main-area overlay (`_build_ensemble_plot`) already reads its
  pooled stats, so keeping it is the lowest-risk way to remove the *visible*
  "Ensemble export" section while preserving that data path. The visible section
  is gone; fully retiring the widget is a future cleanup.
- **Help added** (user request): the existing "Ensemble average (mean ± SD)" entry
  (`ui/help_dialog.py`) now teaches per-cycle vs per-subject + a worked numeric
  example + when-to-use, en/kr. Pinned by
  `tests/test_help_docs_sync.py::test_ensemble_doc_explains_per_cycle_vs_per_subject`.
- Files: `core/ensemble.py`, `ui/ensemble_panel.py`, `ui/analyze_tab.py`,
  `ui/help_dialog.py`; tests `test_ensemble.py` (+5), `test_ui_smoke.py` (+2),
  `test_help_docs_sync.py` (+1).

## Out of scope (deferred)

- **Cycle quality filter** (drop first N / last M cycles, applied to ALL analysis
  via `cycles_from_events`): agreed in principle but its UI location is undecided
  (PIPELINE header was rejected; options floated: a step, a Run-options control, a
  RESULTS-top control, or a more general event/time analysis-range). Revisit after
  this lands.
- "From end" scope bound; absolute cycle range [from,to]; auto-mode default.
