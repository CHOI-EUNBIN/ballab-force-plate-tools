# Help-docs report (2026-06-27)

Beginner-facing HELP documentation for BalanceAnalyzer's newly-added features.
All additions live on the existing help surface (`ui/help_dialog.py` `METRIC_DOCS`)
and follow the established bilingual schema (`name`/`unit`/`desc{en,kr}`/
`axes{en,kr}`/`formula`). The strict sync test stays green.

## What was added

### 1. New category: "Signal operations (building blocks)"
Documents the five `ComputeStep` methods (`core/pipeline.py` `COMPUTE_METHODS`,
implemented in `core/signal_ops.py`). Each is a full bilingual entry with a
beginner desc, the unit transform, and a formula:

- **Derivative (rate of change)** — `deg → deg/s → deg/s²`; order 1/2; actual time
  axis; "filter first, it amplifies noise"; interior-NaN interpolation.
- **Integral (accumulate over time)** — `N → N·s`; cumulative-curve vs total-scalar;
  the sign gate (all/pos/neg) for braking vs propulsive impulse.
- **Magnitude (resultant of axes)** — Euclidean `√(x²+y²+z²)`; resultant GRF / marker
  speed / stride length; NaN-propagating (missing axis ⇒ undefined, not zero).
- **Absolute value |x| (rectify)** — drop sign; the `|Fz|` rectify-before-measure
  use-case (explicit sign control, no hidden global flip).
- **Normalize (÷ constant or ÷ metric)** — ÷ constant (mm→m) or ÷ metric (body
  weight → %BW); the between-subject comparability rationale; divisor chosen in the
  step dialog, not a global setting.

Unit transforms and NaN behaviour are taken verbatim from `core/signal_ops.py`
docstrings; all five ops are verdict "correct" in `researcher-review.md`
(SIGNAL-OPS section).

### 2. New category: "Quick start — task presets"
One explanatory entry, **"Walk preset (seeds a full pipeline)"**, describing how the
Walk (treadmill) / Walk (overground) presets (`core/presets.py`) seed a complete,
ordered, fully-editable pipeline from the "+" Add-step popup's first group ("Quick
start", per `ui/analyze_dialogs.py` `GROUPS`). Lists the seeded sequence in the real
build order from `walk_treadmill`/`walk_overground`: filter → angles → HS/TO events
→ spatiotemporal → spatial → kinematics → normalize → ensemble (+ double-support,
symmetry, and overground kinetics when force is loaded). Reinforces the
"pipeline is the sole source of derived data" + "every seeded step is editable"
principles. Cites Zeni 2008.

### 3. Thin-entry enrichment
NOT done — by design. The existing "Gait events on a treadmill" and
"Time-normalization & Ensemble" entries are already deep (full
Literature→Method→Results→Comparison sections; Zeni 2008, O'Connor 2007, Pataky
2010/2013, SPM1D citations). Per the task rule "do not rewrite good entries", they
were left untouched.

### 4. ComputeStep method hover surface
NO new wiring added — the surface already exists and is already complete. The
"Compute signal" Add-step dialog floats a section hint via
`SECTION_HINTS["Compute.Calculation"]` (`ui/components/help_hint.py`), which already
lists all five methods (Normalize / Derivative / Integral / Magnitude / Absolute)
with one-line beginner descriptions. The task said to add hover text ONLY if such a
surface lacked the signal-op methods; it does not, so nothing was invented.

## Sync-test bookkeeping
The six new entries are explanatory (not metric keys / not named ops), so their
exact `name`s were added to `_NON_METRIC_DOCS` in `tests/test_help_docs_sync.py`
(Signal-op block + Walk-preset block). Without this, `test_docs_cover_every_metric_key`
would flag them as orphan docs. Each new entry carries all `_REQUIRED_FIELDS` with
bilingual en/kr `desc`+`axes`, so the parametrized `test_doc_entry_has_required_fields`
covers them automatically.

## Files touched
- `ui/help_dialog.py` — +2 `METRIC_DOCS` categories (6 entries total).
- `tests/test_help_docs_sync.py` — +6 names in `_NON_METRIC_DOCS`.
- `docs/autonomous-2026-06-27/help-docs-report.md` — this report.

(No `core/` or non-help UI files modified.)

## Verification
- `pytest tests/test_help_docs_sync.py` → 49 passed (was 43; +6 new field-check params).
- Full suite → **587 passed, 30 skipped** (baseline 581/30; passing count +6, none lost).
- Headless smoke: `MetricsHelpDialog()` builds, `_populate()` + EN↔KR `_toggle_lang()`
  run clean (16 categories rendered).

## Remaining help gaps (for a future pass)
- **COM (centre of mass)** — `core/com.py` exists (de Leva BSP) but no help entry;
  flagged #5 in the researcher HELP-DOC SEEDS list. Deferred with the COM UI
  (memory `com-feature.md`: exposure deferred until DATA-section reorg).
- **Per-cycle / reference metrics concept** — researcher seed #4; the mechanics are
  described per-metric but there is no single "what does per-cycle mean ± SD vs a
  whole-trial value mean" primer.
- **Double-support clinical total** — current help/preset documents ONE DS interval
  (HS→contralateral TO); clinical total DS sums both (researcher P3-A). Add when the
  engine ships the second interval.
- **`power` / 2nd-derivative-as-its-own-method** — `core/signal_ops.power` is a P4
  helper not yet surfaced as a `COMPUTE_METHODS` entry, so intentionally undocumented
  here until it has a UI.
