# Pipeline — decisions & gaps (post-review consolidation)

Date: 2026-06-26. Source: 3-agent review (biomech / engine / ui) of the day's
work (CAST frames, detect bug, marker-filter wiring, time-normalization +
ensemble feature). Validated on CEB / KKM treadmill data + YA01/YA02.

## A. Resolved / proven today

- **Time-normalization + ensemble** works end-to-end on real treadmill gait
  (CEB: 177 right cycles, knee FE ROM 44°, swing peak at 83%, stride 1.122 s,
  cadence 107 steps/min — all physiologically valid).
- **"Can we recreate a project in code?" — YES.** The save logic was UI-bound
  (`save_project_state`); engine re-derived it in core only and round-tripped a
  CEB `.ballab` (build → reopen → headless run → real knee angles). So the
  design **is** code-reproducible. Schema documented (manifest v1–6 back-compat).
- **CAST / cross-talk fix** validated; ankle AB/IE ROM 95°/161° (impossible) →
  `angle_reliability` "low" tagging is correct.
- **[done 2026-06-26] G2 kinematic toe-off + stance/swing** shipped (see §F —
  now built). New `core/gait_events.py` (Zeni 2008 coordinate method) + `gait:*`
  progression signals in `core/signals.py`. CEB R-side: HS 179 / TO 178,
  178 cycles, stance 67.2 % ± 0.7 %, and the full chain through `run_pipeline`
  (HS/TO → stride/stance/swing time → stance%/swing% + cadence) gives stride
  1.123 s, stance 67.2 %, **cadence 106.9 ≈ 107** (matches the verified CEB
  spatiotemporals). The spatiotemporal metric ops (`time_between_events`,
  `stance_pct`/`swing_pct`, `cadence_stride`) already existed — G2 supplied the
  missing treadmill TO. Known: Zeni's coordinate TO reads slightly late so stance
  reads ~5–7 % high vs the 60 % overground textbook value (acceptable for a v1
  kinematic proxy; velocity method is a future refinement). Suite 512 / 30 skip.
- **[done 2026-06-26] G1 seconds-based refractory** shipped (see §B — now
  resolved). `min_distance_s` (seconds) → frames at run time via the master fs;
  legacy frame `min_distance` still read for back-compat. CEB: a 0.6 s refractory
  on `angle:R_HIP_angle_FE` peaks gives 178 HS / stride 1.122 s / CV 2.8 % and is
  identical at master fs 1000 Hz **and** 100 Hz (clock-independent). Suite 499
  passed / 30 skipped. Files: `core/events_compute.py`
  (`_resolve_min_distance_frames`), `ui/analyze_dialogs.py` (seconds spin +
  "master N Hz ≈ K frames" hint), `ui/analyze_tab.py` (passes `master_fs`).

## B. THE clock trap — RESOLVED by G1 (2026-06-26)

CEB markers are 100 Hz but the **master clock is 1000 Hz** (force plates). The
angle signal is resampled to 1000 Hz before event detection, so:

- `min_distance = 60` (intended 0.6 s) is read as **0.06 s** → R_HS over-detects
  (274 events, stride-CV 63.8% — garbage).
- `min_distance = 600` (0.6 s on the master clock) → 178 events, CV 2.80% (correct).

**Decision (shipped):** the refractory is now specified in **seconds**
(`min_distance_s`), converted to frames at run time using the dataset's master
fs; the DetectEvent dialog shows the active master fs and the `≈ K frames` it
resolves to. The legacy frame `min_distance` is still honoured (back-compat), so
saved projects are unchanged. See §A for the verification numbers.
NOTE: only the **refractory** is in seconds. The **scope/search-window** bounds
are still in frames — converting those to seconds is a remaining follow-up
(tracked under G1 leftovers; low priority since it's an explicit window, not the
silent clock trap).
The demo README's "60 frames" is only correct for marker-only (master = 100 Hz)
trials.

## C. Apply now (low-risk, agreed)

- [done] `ensemble_stats` empty-slice RuntimeWarning suppressed (numbers unchanged).
- [done] Ensemble panel: trials present but 0 epochs → orange
  "0 epochs — no segments matched (check the event)" instead of silent "0 epochs".
- [done 2026-06-27] HELP **Time-normalization & Ensemble** section — added to
  `ui/help_dialog.py` `METRIC_DOCS` as two non-metric entries
  ("Time-normalization (0–100% cycle)", "Ensemble average (mean ± SD)"), grounded
  in `core/normalize.py` + `core/ensemble.py`; Pataky 2010/2013 cited, Winter /
  Sadeghi 2000 marked [verify]; `test_help_docs_sync` exemptions updated.
- [done 2026-06-27] NormalizeStep popup validates `name` INSIDE the dialog
  (`NormalizeStepDialog.accept` shows a message + stays open), parity with the
  detect/metric dialogs.
- [done 2026-06-27] "Ensemble" disambiguated: the data/Export panel stays
  **"Ensemble"**; the RESULTS·Signals main-area toggle is now **"Ensemble
  overlay"** (labels only, behaviour unchanged).
- [n/a 2026-06-27] `set_title_suffix()` does not exist in code (only stale doc
  mentions) — the title API is already unified on `set_sources(title=)`. Nothing
  to remove.

## D. Tomorrow — pipeline gaps (organized, not yet built)

Priority order:

- **G1 (P0) seconds-based event windows** — `[done]` refractory `[2026-06-26]`
  + scope-window bounds `[2026-06-27]` both in seconds now. A scope bound accepts
  `{"type":"time","seconds":s}` (→ `round(s*fs)`), alongside the Frame/Event
  types, with a "Time" option in the DetectEvent dialog. Fully back-compat.
- **G2 (P0) toe-off detection + stance/swing split** — `[done 2026-06-26]`
  shipped (Zeni 2008 via `gait:*` signals; see §A/§F).
  Velocity-method refinement `[investigated 2026-06-27]`: `velocity_events()` /
  `gait_events(method=…)` added additively in `core/gait_events.py`, BUT on CEB it
  reads stance ~50 % (HS ~90 ms late + noisy, TO ~120 ms early) — it overshoots
  past 60 %, so it is NOT an improvement; **coordinate stays the default**.
  Remaining leftover: a "walk" preset to auto-seed the HS/TO/spatiotemporal steps
  (folds into G4).
- **G3 (P1) core.ensemble_from_runs() pure function** — cross-trial pool+mean±SD
  is currently UI-only; extract to core so code-only ensembles, group ensembles
  and SPM export are possible. (engine vulnerability B)
- **G4 (P1) gait spatiotemporal + angular-velocity presets** — the ops exist;
  wire a walk preset (stride/step time, cadence, peak angular velocity, ROM).
- **G5 (P1) L/R convention + bilateral overlay** — left/right curves on one graph.
- **G6 (P2) group (subject-equal-weight) ensemble + SPM export** — current pool is
  epoch-weighted; add a per-subject-then-group mode and an n×101 SPM1D export.
- **G7 (P2) `signals._resample` NaN policy** — `np.interp` can interpolate across
  marker occlusion (NaN) as if real; make it finite-only like
  `resample_to_percent`. Wide blast radius → regression tests required. (engine A)
- **G8 (P2) project_io.py** — extract the pure serialization
  (`build_project` / `open_project_headless`) out of the UI for a code API.
- **G9 (P3) cycle QC (drop outlier cycles), %stance/%swing dual normalization,
  terminology pass (Epoch→Segment, Points→Resolution) per beginner-first.**

## E. Open decision

- `run_pipeline` single-pass (events pre-computed once) — keep for simplicity;
  revisit only if a detector must threshold on a metric a later MetricStep
  produces.

## F. G2 — kinematic toe-off + stance/swing split

**STATUS: BUILT 2026-06-26.** Shipped via the §F.3 *preferred* path expressed as
signals (not the fallback helper): `core/gait_events.py` (pure Zeni math +
`split_stance_swing`) + `gait:<SIDE>_<heel|toe>_ap` signals resolved in
`core/signals.py` (listed in the catalog when heel/toe/pelvis markers exist).
HS = peak-max on `gait:R_heel_ap`, TO = peak-min on `gait:R_toe_ap`, reusing the
existing peak detector + the G1 seconds refractory. The spatiotemporal metric
ops already existed, so stance%/swing%/cadence work end-to-end through
`run_pipeline` with no new metric code. Tests: `tests/test_gait_events.py` (pure
+ signal-layer) and `tests/test_examples_events.py` (CEB counts, stance/swing,
end-to-end). Known offset + the auto-seed preset are noted in §A/§D. The design
below is retained as the rationale of record.

(Original design — P0, the next item after G1.) Goal: on treadmill gait
(no per-step force events) derive **HS and TO from marker kinematics**, then
split each gait cycle into **stance** and **swing** so we can report %stance /
%swing and build stance-only normalized epochs.

### F.1 Why kinematic (not force)
The CEB/KKM treadmill trials have a single continuously-loaded belt force signal
— no clean per-foot rising/falling GRF edges to threshold. So gait events must
come from the foot markers. Today's HS proxy (`angle:R_HIP_angle_FE` peak) gives
the right *count* (178) but is a coarse hip-flexion proxy and yields **no TO**,
so we can't separate stance from swing. G2 replaces/augments it with a validated
foot-marker method that gives **both** events on the same footing.

### F.2 Method — Zeni et al. 2008 "coordinate" algorithm  [verify citation]
Zeni JA, Richards JG, Higginson JS (2008), *Gait & Posture* 27(4):710–714 —
validated specifically for **treadmill** and overground walking. Per limb, in the
AP (anterior–posterior / progression) axis, relative to a pelvis reference:

- **HS** = the frame where the **heel** marker is at its **most-forward** AP
  position relative to the pelvis origin  → a **peak (max)**.
- **TO** = the frame where the **toe** marker is at its **most-backward** AP
  position relative to the pelvis origin  → a **peak (min) / valley**.

Subtracting the pelvis AP removes belt-frame drift, so the signal is a clean
per-cycle oscillation. Alternative (fallback): the O'Connor 2007 / Zeni
"velocity" foot-marker method (zero-crossings of foot AP velocity) — note as a
secondary option, do not build first.

Available CEB markers (confirmed): `RHEEL/RTOE/LHEEL/LTOE`; pelvis ref =
`RASIS/LASIS/RPSIS/LPSIS` (origin = their mean, or sacrum = mean of the two
PSIS). The model already reconstructs a pelvis frame, so the pelvis origin is
reusable.

### F.3 What the engine needs (prerequisite gap)
DetectEventStep already supports `peak`(max) and `peak`(min) — the detection
itself is covered. The **missing piece is the input signal**: a 1-D
"heel-AP-minus-pelvis-AP" (and toe) series. Two options:

- **(preferred) extend ComputeStep with a binary `subtract`** (ties into the
  planned signal-op framework) + expose marker components as signal keys
  (e.g. `marker:RHEEL:ap`, resolved in the trial's progression axis, not raw X/Y).
  Then the recipe is pure pipeline:
  `Compute subtract(marker:RHEEL:ap, marker:pelvis:ap) → R_heel_rel` →
  `Detect peak max on R_heel_rel → R_HS`;
  `Compute subtract(marker:RTOE:ap, marker:pelvis:ap) → R_toe_rel` →
  `Detect peak min on R_toe_rel → R_TO`.
- **(fallback) a dedicated `core/gait_events.py` helper** `zeni_events(model_result,
  markers, side) → {"HS": frames, "TO": frames}` if exposing marker-component
  signals is too invasive for v1. Less composable; revisit once signal-ops land.

Decision to make in build: progression-axis convention (which marker axis is AP
after the model's lab→pelvis transform) — must reuse the model's existing AP/ML
definition, NOT assume raw X/Y. **[verify against marker_model frame]**

### F.4 Stance / swing definition
Per limb, ascending events within a cycle:
- **cycle** = HS_i → HS_{i+1}
- **stance** = HS_i → TO_i      (foot on ground)
- **swing**  = TO_i → HS_{i+1}  (foot in air)
- **%stance** = (t_TO_i − t_HS_i) / (t_HS_{i+1} − t_HS_i) × 100, **%swing** = 100 − %stance.
Drop the first/last partial cycle (no bounding HS pair). Refractory uses
`min_distance_s` (G1) so a noisy marker can't double-fire HS or TO.

### F.5 Metrics / outputs
New MetricStep ops (design): `stance_time` (s), `swing_time` (s),
`stance_percent` (%), `swing_percent` (%) — computed per cycle then mean±SD/CV,
matching the existing per-cycle metric machinery. Bilateral metrics
(double-support %, step time L↔R) depend on **G5** (L/R) and are deferred there.
Stance-only normalized curves = a NormalizeStep over the HS→TO segment — this is
the %stance dual-normalization noted in **G9**; G2 unlocks it.

### F.6 Validation target (CEB)  [verify on data]
Normal adult walking: **stance ≈ 60 %, swing ≈ 40 %** of the cycle. With CEB
cadence 107 steps/min and stride 1.122 s, expect stance ≈ 0.67 s, swing ≈ 0.45 s.
TO must fall strictly between consecutive HS, and TO count ≈ HS count (≈178).
Acceptance: per-cycle %stance in ~58–64 % with low CV, HS from the Zeni method
agreeing with today's hip-peak HS within a few frames.

### F.7 Edge cases
- Foot-marker occlusion / NaN → ties to **G7** (`_resample` NaN policy); until G7,
  guard with finite-only detection and skip NaN gaps.
- Left and right detected **independently** (own marker pair) — no cross-limb
  assumption; bilateral interplay is G5.
- Non-gait / static trials → method yields few/no clean peaks; degrade to empty
  (graceful), never raise (match existing detect behaviour).

### F.8 Build order (when implemented — not now)
1. Engine: expose marker-AP signal keys (or the `gait_events` helper) + decide
   subtract-vs-helper; pin with synthetic + CEB tests (TDD, RED first).
2. Detect recipe wiring (HS peak-max, TO peak-min) — reuse existing dialog.
3. Metric ops `stance_percent`/`swing_percent` (+ times) in `metrics_compute`.
4. CEB regression test: ~178 HS/TO, %stance ≈ 60 %, TO between HS pairs.
5. (later, G4) a "walk" preset auto-seeds the HS/TO/stance-swing steps so
   beginners get it without manual recipe building.

### F.9 Open questions
- AP axis source: confirm the model's progression axis so `marker:*:ap` is
  unambiguous on treadmill (subject roughly stationary in lab AP).
- Keep the hip-flexion HS proxy as a fallback when foot markers are absent, or
  drop it once Zeni is in? (Lean: keep as a tagged fallback.)
- `stance_percent` as a first-class MetricStep op vs. a generic
  duration-ratio op — prefer first-class for beginner clarity.

Artifacts (scratchpad): `help_ensemble_draft.md`, `ceb_variables_report.md`,
`engine_review_report.md`, `project_schema_doc.md`, `build_ballab_recipe.py`,
`ui_review_report.md`.
