# Pipeline build plan — agents-meeting outcome (2026-06-24, autonomous)

4-agent meeting (researcher catalog · biomech flow · engine structure · ui UX) synthesized into the plan below. Companion ref: `docs/biomech-metric-catalog.md`. Goal: build ≥10 biomech metrics + restructure pipeline for clear use; every result must reach EXPORT + STATISTICS.

## Convergent decisions (all agents agree)
1. **`core/signal_ops.py`** (new, pure numpy, NaN-safe, UI-free): `derivative(y,t,order=1|2)` (np.gradient, non-uniform dt), `integral(y,t)` (scipy cumulative_trapezoid + scalar sum), `magnitude(*comps)` (√Σ). These 3 unlock most of the catalog.
2. **Two metric classes**: (a) signal-deriving → `ComputeStep` methods (derivative/integral/magnitude) make a NEW signal, then existing scalar reduce (max/mean) on top — "everything is a Signal", reuses SCALAR_OPS, graphable; (b) direct scalar ops needing time (integral/sum) or 2 inputs (symmetry).
3. **Time-axis plumbing is small** (RunContext already has t/fs): add `needs_time` to OP_INFO; `metrics_compute._window_value` slices `ctx.time[lo:hi+1]` for needs_time ops; `run._run_compute` passes `ctx.time` to signal_ops. **No signature changes.**
4. **MetricStep serialization additive** (back-compat): `input2=None` (binary/symmetry), new OP_INFO `input` kind `"event"` (spatiotemporal = event-frame time diffs, reuse segment/event fields). Old projects unaffected (get() defaults).
5. **Metric dialog reorder = [Signal → Window → Calculation]** (human mental model; currently op-first). Op list filtered by signal type (angle→ROM/velocity; COP→Prieto; force→impulse/RFD) — signal→valid-op map is biomech/core's responsibility. `value_at_event` folds in as a Window type ("at a single event"). Event dialog reorder to Signal→Method→Naming for consistency.
6. **Dead code to remove** (ui): `AnalysisRangeDialog` (~200 lines, unreferenced), `_build_events_section` + `_add_event` (unused), `metric_checks`/`angle_metric_checks` dummy dicts. `TrajectoryStepDialog`→`_FormGroup` for dialog-grade consistency.
7. **"normalize" name collision**: ComputeStep `normalize`(÷scalar=%BW) vs gait 0–100% time-normalize. Keep `normalize` working (back-compat); future time-normalize is a separate NormalizeStep (101-pt) — DEFERRED (bigger; needs ensemble curves).
8. **Dedup** (engine): 95% ellipse logic duplicated (metrics.py vs compute_ellipse_points) → shared `_cop_ellipse`; `compute_metrics` if-chain → fold toward registry (verify no direct UI callers first); SD ddof=1 in 3 places is intentional (keep).
9. **help-sync test → extend to OP_INFO** (currently only METRIC_KEYS/COP 17) so new ops can't drift silently.
10. **RESULTS-list vs cards overlap**: cards = Pinned metrics only (pin flag already tracked); RESULTS list = all. (ui, Round C.)

## Adopted defaults for OPEN questions (user away 8h — biomech sets clinical standard + documents; revisit if wrong):
- Derivative endpoints: `np.gradient` forward/backward (document; note V3D central-diff parity).
- Filter-before-derivative: use the filtered signal if a FilterStep produced one; document noise caveat in help.
- Impulse sign / braking-propulsive: `integral` gains a `sign` param (all/pos/neg); AP forward = + (FLAG: plate-local axis — biomech verify vs c3d).
- Symmetry index: Robinson SI = |L−R|/(0.5(L+R))·100 (%); needs L/R labels → may defer until L/R assignment (Phase E).
- Single-pass executor KEPT (metric-emitted-event-as-segment backward-ref deferred; not needed for P1–P3 metrics).

## Build rounds (sequential stages; parallel where files don't overlap)
- **Round A (parallel, non-overlapping): engine foundation (core/) ‖ ui cleanup (ui/).**
  - engine: signal_ops.py + ComputeStep derivative/integral/magnitude + needs_time plumbing + scalar ops integral/sum + "event" input-kind scaffold + unit-derivation table + tests. core only.
  - ui: remove dead code (#6) + Trajectory _FormGroup consistency + re-verify all dialogs. ui only.
- **Round B: biomech** builds ≥10 named metrics + clinical conventions + help docs + synthetic tests, on engine's foundation. Provides signal→valid-op map. (core/metrics, metrics_compute, help_dialog)
  Metric set: peak/mean angular velocity, peak angular acceleration, RFD, loading rate, vGRF impulse, braking impulse, propulsive impulse, jump height (flight-time + impulse-momentum), takeoff velocity, RSI, stride/step time, cadence, stance/swing %, contact/flight time, symmetry index. (≥10; pick the highest-value, document each.)
- **Round C: ui** Metric dialog reorder (Signal→Window→Calc, op-list filtered by signal type) + Event reorder + cards=pinned-only. (ui)
- **Round D: engine** dedup (#8) + help-sync test→OP_INFO (#9) + **EXPORT + STATISTICS connection**: every new metric flows into ExportDialog metric list + results_store/statistics_tab; verify analysis→results→export→statistics chain end-to-end. Full pytest + headless app build.

## Cross-cutting (every round)
- Keep 292+ pytest green; add synthetic-pinned tests per new op.
- Review existing parts to professional grade as you touch them (user directive).
- ALL results must reach export + statistics (user directive) — verified in Round D.
- Known issue (ui flagged): real-folder `_ingest` stalls headless — engine to check UI-thread blocking (Round D).
