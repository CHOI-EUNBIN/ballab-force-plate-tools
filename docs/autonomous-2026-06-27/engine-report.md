# Backend hardening report — 2026-06-27 (autonomous session)

Scope: `core/` calculation engine + persistence only. UI untouched. Nothing
committed (left in the working tree). Test command kept green throughout:

```
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q
```

Baseline at start: **561 passed, 30 skipped**.
Final: **574 passed, 30 skipped** (+13 tests, no passing test removed).

---

## (a) Bugs found + how fixed (TDD: failing test first, then fix, then green)

### Bug 1 — `value_at_event` ignored the per-cycle window  *(correctness)*
`core/metrics_compute.py::_window_value` (`kind == "sample"`) always read the
input at `frames[0]` — the FIRST global instance of the cited event. With a
per-cycle segment (e.g. `value_at_event(angle:Knee, event=TO, segment=[HS,TO])`)
every stride therefore reported the SAME value instead of the per-cycle one.

Fix: when the step has a `segment`, pick the event instance that falls inside
that cycle's `[lo, hi]` window (NaN if none). Whole-trial (no segment) keeps the
first-instance behaviour, so nothing existing changes.

Tests: `tests/test_run.py::test_value_at_event_reads_event_inside_each_cycle`,
`::test_value_at_event_whole_trial_keeps_first_instance`.

### Bug 2 — COP confidence ellipse collapsed to NaN on one occluded sample  *(robustness)*
`core/metrics.py::compute_ellipse_points` used `np.mean` (not `np.nanmean`) and
fed NaN straight into the covariance, so a single gap frame made the WHOLE
plotted ellipse NaN — even though the companion `"95% Ellipse area"` metric in
`compute_metrics` is NaN-safe. The drawn ellipse would silently vanish.

Fix: drop frames non-finite in either channel before the covariance (matching the
nanmean-based metric); `< 2` finite paired samples → empty arrays (nothing to
draw) instead of a NaN cloud. Bit-for-bit identical with no NaN present.

Tests: `tests/test_metrics.py::test_compute_ellipse_points_nan_safe`,
`::test_compute_ellipse_points_too_few_samples_empty`.

### Bug 3 — `apply_lowpass` raised `ZeroDivisionError` on `fs = 0`  *(robustness)*
`core/signal_proc.py::apply_lowpass` computed `cutoff / (0.5*fs)` before checking
the Wn sign, so a missing / zero sample rate crashed. (`fs < 0` was already
caught by the later `wn <= 0` guard.)

Fix: bail out (return the signal unchanged) when the Nyquist `0.5*fs <= 0`.

Tests: `tests/test_signal_proc.py` (new file) —
`test_apply_lowpass_zero_fs_returns_input_unchanged`, plus negative-fs,
short-signal, marker-filter zero-fs and NaN-gap-preservation cases.

### Bug 4 — `MarkerModel.reconstruct` crashed when a cluster marker was absent  *(robustness)*
If a marker used in a joint's calibrated tracking cluster was missing from a
dynamic trial (different label set, or occluded the whole trial),
`reconstruct` raised `KeyError` via `_index`, aborting the ENTIRE model
computation in `apply()` (joint centres / segments / angles, all lost). Only the
COM block was wrapped.

Fix: new `_gather_cluster` stacks each cluster marker's `(F,3)` trajectory and
substitutes an all-NaN slab for a missing label. `_reconstruct_joint` already
degrades a frame with `< 3` visible cluster markers to NaN, so a missing marker
now just lowers the visible count (graceful) — and with a redundant cluster
(≥4 markers, 1 missing) the joint still solves and matches the full-cluster
result for a rigid cluster.

Tests: `tests/test_marker_model.py::test_reconstruct_missing_cluster_marker_degrades_to_nan`,
`::test_reconstruct_missing_one_of_four_cluster_markers_still_solves`.

---

## (b) Robustness / cleanup changes (no behaviour change)

- **`core/metrics.py::compute_metrics`** — the broad `except Exception: pass`
  per-metric-key guard now logs a `WARNING` with traceback
  (`logging.getLogger("core.metrics")`) before continuing. The graceful-degrade
  contract is unchanged (a failing key is still simply absent from the result),
  but a genuine bug now leaves a trace in the app log instead of being invisible.
  This matches the project's documented intent in `core/logging_setup.py`.

- Added module docstring / inline comments where the new branches live, matching
  the surrounding comment density.

---

## (c) Risky things deliberately NOT changed

- **`metrics._peak_abs` signed-peak semantics** — `peak_angular_velocity` /
  `peak_angular_acceleration` / `rfd` return a SIGNED "largest-|·|" value, so when
  per-cycle peaks alternate sign their mean can cancel. The user explicitly asked
  to leave this as-is. I only ADDED a documenting regression test
  (`test_metrics.py::test_peak_abs_returns_signed_extremum_documented`) that pins
  the current behaviour so any future change is a conscious, reviewed one.

- **Detected-events cache token (`events_compute._detect_token`)** does not fold
  in `marker_disp` / `angle_result` CONTENT — only the detect-step recipe (+
  referenced metrics). In practice marker/angle filtering flows through pipeline
  `FilterStep`s, which ARE in the token, so the realistic invalidation paths are
  covered. A UI that fed a *different* display array for the *same* pipeline could
  in principle get a stale cache. I left this alone: widening the token risks
  cache churn / perf regressions and there is no failing case today. Flagged as a
  remaining risk.

- **`metrics_compute.compute_metric_step` whole-trial fallback** — a cyclic
  metric whose segment yields NO cycles silently falls back to a single
  whole-trial value (for scalar/cop ops). This is existing, documented behaviour;
  changing it (e.g. to NaN) could surprise existing recipes, so untouched.

- **`core/c3d_reader.py`** — large I/O boundary requiring real `.c3d` fixtures
  (those tests skip in this environment). Not safe to refactor blind; left as-is.

---

## (d) Future backend direction (suggested, not done)

- **Tighten the events cache token**: include a cheap hash of the resolved input
  signal (or at least a `marker_disp` identity/version stamp) so a display-array
  change can never serve stale detected events. Pairs with a small unit test that
  changes `marker_disp` and asserts re-detection.
- **Replace remaining broad `except Exception`** in `core/run.py::_run_normalize`
  and `marker_model.apply`'s COM block with narrowed exception types + a debug log
  (same pattern just applied to `compute_metrics`), so "silently empty" results
  always leave a breadcrumb.
- **Make `extract_epochs` meta honest**: a window whose `i1` exceeds the array
  length is silently clipped but `meta["end"]` still reports the requested index.
  Clamp `meta` to the real slice end so downstream labels match the data.
- **Centralise NaN-safe centring**: `compute_metrics`, `compute_ellipse_points`,
  `cop_resultant` and `trajectory` all re-implement mean-centring; a single
  `_centre_nan(ap, ml)` helper would remove the drift risk that caused Bug 2.
- **Property-based tests** (Hypothesis) on the pure ops (`signal_ops`,
  `events`, `normalize`) for "never raises / never returns wrong-length" — the
  edge cases here (empty / single-sample / all-NaN / non-uniform clock) are
  exactly what property tests cover well.
- **Validate inputs at module boundaries**: `Workspace.__init__` and
  `run_pipeline` assume `dataset["time"]` exists and is 1-D; a tiny guard
  (length, finiteness, monotonicity warning) would localise broken-clock bugs
  instead of letting them surface deep in a detector.
