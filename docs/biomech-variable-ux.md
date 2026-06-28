# Biomechanics-variable extraction — UX flow (Visual3D-aligned)

The mental model every user follows, and how it maps to the pipeline steps. This
is the "how do I get variable X out of a c3d" flow. Source: researcher review of
Visual3D Event/Metric command model + the current `core/pipeline.py` steps.

## The 4-beat model

```
   RAW c3d ─▶ ① SIGNAL ─▶ ② EVENT ─▶ (③ SEGMENT) ─▶ ④ METRIC ─▶ Export / Statistics
```

| Beat | Question the user asks | Pipeline step | Notes |
|---|---|---|---|
| ① Signal | "what signal do I measure?" | `FilterStep`, `ComputeStep` (derivative / integral / magnitude / abs / normalize), `ComputeAngleStep`, `TrajectoryStep` | Make/clean the signal you'll measure. Pipeline is the SOLE source — a signal only exists if a step produces it. |
| ② Event | "at what instants?" | `DetectEventStep` | threshold / peak·valley / zero-cross / global max·min / fixed frame. **Search window** (From/To = Frame \| Event+instance) limits *where* to look; **Instance** (All / (n)th / (n)th–(n)th) picks *which* of the hits to keep. |
| ③ Segment | "over which interval / cycle?" | (today) `MetricStep.segment=[startEvent,endEvent]`; (future) a dedicated `SegmentStep` for per-cycle | "between two events" = a cycle/phase. Per-cycle repetition lives here, NOT in detection (V3D `EVENT_SEQUENCE`). |
| ④ Metric | "what number?" | `MetricStep` (max/min/mean/range/impulse/RFD/value_at_event/symmetry/…) | The output number(s). Auto-flow to Export + Statistics. |

V3D parallel: **Signal → Event → (Sequence) → Metric**. Our steps are 1:1 with
V3D's Compute / Event_* / EVENT_SEQUENCE / Metric_* commands (validated).

## Where the new "Search window" fits (② Event)

Inside a Detect step, *after* picking the detection method:

- **Search window** (where to look): `Off` = whole trial; or **From / To**, each a
  bound = **Frame** (a number) **or Event** (a label detected by an earlier step +
  which instance #). Single window. Example: detect a knee-flexion peak only
  *between* `HS #1` and `TO #1`.
- **Instance** (which to keep): `All` / `(n)th` / `(n)th – (n)th` (occurrence
  ordinals, not frames).
- Compose: `Search window = HS#1 → HS#3` + `Instance = All` → every hit in that
  window. `Instance = (1)th` → just the first.

Engine resolves event bounds per-trial from earlier steps' events; unresolvable
bounds fall back to the trial edge (graceful, verified on real data).

## Recipe cheat-sheet (variable → steps)

| Variable | Steps |
|---|---|
| **Joint ROM** | `ComputeAngle` → `Metric(op=range, input=angle:Knee, segment=[HS,HS])` |
| **Peak vGRF** | `Compute(abs, fp1:fz)` → `Metric(op=max, input=AbsFz)` |
| **Loading rate / RFD** | `Metric(op=rfd / loading_rate, input=AbsFz)` |
| **Impulse** | `Metric(op=impulse, input=AbsFz)` (or `Compute(integral)` then mean) |
| **Spatiotemporal** (cadence, stance %) | `Detect(HS/TO via threshold on vGRF)` → `Metric(event ops, segment=[HS,TO])` |
| **Angle / force at an event** | `Detect(event)` → `Metric(window = At a single event)` |
| **Symmetry** | left & right `Metric`s → `Metric(input2=metric:other, op=symmetry_index)` |
| **COP sway / 95% ellipse** | `Trajectory(cop_ap, cop_ml)` → `Metric(op=cop_* )` |

## Beginner flow (target)

Task preset (보행 / 러닝 / 점프 / 균형) **auto-seeds** the Signal→Event→Metric steps
so the user starts from a working pipeline, then tweaks. No blank screen; jargon
stays but raw parameters hide behind the preset (see `beginner-first-ux`).

## Deferred (decided, with rationale)

- **Per-cycle repeated detection** → a future `SegmentStep` (cycle = `EVENT_SEQUENCE`
  of 2 labels), not the Detect step — keeps cycle definition in one place.
- **Offset bounds** (e.g. `HS − 10 frames`) → 1-line add in `events_compute`
  `_resolve_scope_bound` when needed (common in V3D, low effort).
- **% of cycle bound** → only meaningful after SegmentStep exists.
- **Signal-threshold-as-bound** → not a new type: make a threshold event first, then
  reference it (flat pipeline already supports this).
- **One-click gait HS/TO** (`Automatic_Gait_Events`) → a 보행-preset helper later.
