# Frontend hardening + polish report — 2026-06-27

Scope: `ui/` only (+ `tests/` for UI tests). No `core/` edits, no commits.

Test status: **581 passed, 30 skipped** (full suite, offscreen Qt). Passing count
not reduced; **+7 new UI tests** in `tests/test_ui_hardening.py`. The full app
(`ui.main_window.MainWindow`) builds and runs its event loop cleanly offscreen.

Files I changed:
- `ui/analyze_tab.py`
- `ui/ensemble_panel.py`
- `tests/test_ui_hardening.py` (new)

---

## (a) Bugs found + fixes

### BUG 1 — Derived-signal graph drew empty (axes, no curve) [FIXED]
Right-clicking a ComputeStep output that depends on a marker-derived signal
(`marker:*` / `gait:*`, e.g. the walk preset's `R_heel_vel`) and choosing "View
as graph" drew axes but **no line**.

Root cause: `AnalyzeTab._render_force_curves` built its `Workspace` **without**
`marker_disp`. The Workspace then raised `ValueError: channel unavailable:
gait:R_heel_ap_lab` while resolving the compute input, the exception was
swallowed (`raw_vals = None`), and the curve stayed empty. The value-table path
(`_show_signal_table`) and all the figure-building paths already passed
`marker_disp`, which is why the *table* worked but the *graph* did not.

Fix: pass `marker_disp=self._marker_display_data(dataset.get("markers"))` when
building the Workspace in `_render_force_curves`. Confirmed headless on CEB walk
preset: `R_heel_vel` curve now fills 200000 points; on a synthetic single-marker
trial the derivative-of-sine curve fills the full master clock.

I applied the same `marker_disp` fix defensively to `_render_trajectory`'s
Workspace (line ~3720) so a future marker-derived TrajectoryStep input can't hit
the identical silent-empty failure.

Tests: `test_derived_marker_signal_graph_has_curve`,
`test_render_force_curves_passes_marker_disp`.

### BUG 2 — Ensemble shown twice [FIXED — de-duped to one]
The mean ± SD ensemble curve appeared in two places at once: the bottom
"Ensemble" panel had its own pyqtgraph mini-plot AND the RESULTS·Signals
"Ensemble overlay" row drew the same curve in the main graph area.

Fix: `EnsemblePanel` got a `show_plot=True` constructor flag. The Analyze tab now
embeds it with `show_plot=False`, so the bottom panel is **export-only** (title +
pooled-epoch count + "Export CSV..." + a one-line hint pointing at the overlay).
The standalone `EnsemblePanel()` default keeps its plot, so the widget stays
reusable. All data methods (`set_sources` / `n_epochs` / `stats` / `export_csv`)
are unchanged, and the main-area overlay (`_build_ensemble_plot`) still reads the
panel's pooled stats — so the single remaining curve is unaffected. The section
header was renamed "Ensemble" → "Ensemble export" to match its new role.

Tests: `test_analyze_ensemble_panel_is_plotless`,
`test_standalone_ensemble_panel_still_has_plot`.

### BUG 3 — `_event_channel_options(None)` could raise [HARDENED]
`_event_channel_options` did `dataset.get("markers")` with no None-guard. Its
only current caller already guards `dataset is None`, so it wasn't reachable
today, but it's a latent crash for any future caller. Added an early
`if dataset is None: return []`.

Test: `test_event_channel_options_none_is_safe`.

### Documented "bugs" that are NOT bugs (verified against code)
- **Filtered `:filt` twins not in results after a FilterStep**: NOT a bug. The
  walk preset's FilterStep is **marker-only** (`markers=True`, no `targets`), so
  it filters the marker arrays in place and produces **no** `:filt` signal twins
  — exactly like a hand-built marker-only filter. A FilterStep that *targets a
  signal* (e.g. `fz`) DOES list `fz:filt` in RESULTS·Signals
  (`pipeline.filtered_keys()` → `results_model.build_results`). Preset and manual
  paths are already consistent. (Verified: marker-only `filtered_keys()` → `[]`;
  targeted → `['fz:filt', 'cop_ap:filt']`.)
- **Metric VALUES wrong (L Ankle ROM 0.276°, Double support 5 s)**: already
  resolved per `docs/walk-preset-uiux-direction.md` "RESOLVED 2026-06-27"; pinned
  by `tests/test_preset_app_path.py`. Re-confirmed it does not reproduce.

### Stability sweep (no further crashes found)
Drove the real `AnalyzeTab` headless through empty-state and loaded-state paths:
no dataset / no model / no markers / empty pipeline / 2 force plates /
single-epoch + zero-epoch ensemble / full pipeline (Filter+Detect+Metric+
Compute+Normalize) edit/toggle/delete/save / all step + help + settings dialogs.
Apart from BUG 3, every path returned cleanly.

---

## (b) UI/UX polish

### Clear empty-states in the RESULTS lists
Previously the Signals / Events / Metrics lists rendered as **blank boxes** when
empty. Each now shows one muted, non-selectable hint row:
- Signals: "No signals yet — add a step (+) to compute them."
- Events: "No events — add a Detect Events step (+)."
- Metrics: "Add a Metric step, then ▶ Run." OR (when a Metric step exists but no
  run yet) "Press ▶ Run to compute metrics."

Hint rows are tagged `("hint", None)` on UserRole; all three right-click menus
and the signal fold-click handler skip them, so a hint can't be acted on or
crash. New helper `_add_empty_hint`.

Tests: `test_results_lists_show_empty_state_hints`,
`test_results_menus_ignore_hint_rows`.

### Ensemble panel cleanup (also a polish win)
Removing the redundant mini-plot makes the RESULTS sidebar shorter and less
busy; the panel reads clearly as "export the pooled epochs", with a one-line
hint telling the user where the curve actually lives.

All on-screen text is English and Visual3D-aligned (project rule). Existing
`style.py` tokens were reused; no new design language introduced.

---

## (c) Deliberately left

- **Heavy refactor of `analyze_tab.py` (~6.6k lines)**: out of scope for a
  stability/polish pass; splitting panels risks the "quietly broken UI" the
  user warned about. Flagged as future work below.
- **`peak_angular_velocity` / `rfd` sign-cancellation** (R Knee peak ang.vel
  shows ~100 vs true ~255): this is a `core/metrics` definition issue
  (biomech/engine territory), not UI. Left per the existing "leave for now" note.
- **Dark-theme contrast audit of the new hint rows**: they use `TEXT_MUTED`
  which is theme-aware in both palettes, so they degrade sensibly, but I did not
  pixel-audit dark mode (headless can't render pixels).

---

## (d) Future frontend / UX direction

- **Decompose `analyze_tab.py` panel-by-panel** (Pipeline row, RESULTS lists,
  graph host, file tree) into `ui/components/` widgets, each with a smoke test,
  moving one panel at a time and re-launching after each. This is the single
  biggest maintainability lever.
- **Centralize the "is this row actionable?" check**: the `("group"|"hint",
  None)` guard is now duplicated across three menu handlers — extract a small
  `_row_key(item)` helper that returns `(kind, key)` or `None`.
- **Surface Workspace resolution failures** instead of swallowing them: a derived
  curve that can't resolve should show a small "could not compute" note on the
  plot, not silently blank — this class of bug (BUG 1) was invisible until
  reproduced headless.
- **Empty-state for the graph area itself**: when nothing is graphed, the main
  area could show an `EmptyStateWidget` ("Right-click a signal in RESULTS to
  graph it") rather than a bare panel.
- **Ensemble export discoverability**: now that the bottom panel is export-only,
  consider folding it into a right-click "Export ensemble CSV" on the
  "Ensemble overlay" Signals row, removing the standalone section entirely.
