# Walk preset — comprehensive gait pipeline (overground / treadmill) — design

Date: 2026-06-27. Status: design approved, pre-implementation.
Context: G4. First instance of the preset system. Builds on G2 (kinematic gait
events via `gait:*` signals), G1 (seconds refractory), and the existing op
registry (`core/metrics.py` OP_INFO).

## 1. Goal
A user picks a **task preset** and the app auto-seeds a **complete, editable
pipeline** that computes *every gait variable extractable from the data* — so a
beginner is never staring at a blank pipeline, and an expert can freely trim,
edit, or extend it (the pipeline remains the single source of all derived data).

The walk preset ships in **two explicit variants** the user chooses between:
- **보행 (지면)** — overground walking.
- **보행 (트레드밀)** — treadmill walking.

The variants seed the *same comprehensive metric set*; they differ only in how
**gait events** and **spatial variables (speed / length / width)** are computed,
because the underlying physics differ (see §4).

## 2. Architecture
- **`core/presets.py`** (new, pure/headless): a registry `PRESETS = {name: fn}`
  where each `fn(dataset) -> list[PipelineStep]`. A preset function may inspect
  the dataset (e.g. "are the force plates actually loaded?") to adapt the steps
  it returns. No Qt; unit-testable by asserting the returned step list.
- **UI**: a "Preset" entry point in the Analyze tab. Selecting a preset calls the
  registry function with the current dataset and appends/sets the returned steps
  on the pipeline. Pure thin-UI: it only seeds; everything afterwards is the
  normal (editable) pipeline.
- Rationale: matches the project rule "core owns the logic, UI is thin, the
  pipeline is the sole source of derived data." Extensible to running / jump /
  balance presets later by adding registry entries.

## 3. What the walk preset seeds (both variants, bilateral L+R)
Grouped by category. Unless marked **[NEW]**, the op already exists in
`core/metrics.py` OP_INFO and the preset only *assembles* it.

**① Events** — HS, TO for each side (R, L). Detection method per variant (§4).

**② Spatiotemporal**
- stride time, step time, cadence (`time_between_events`, `cadence*`)
- stance time/%, swing time/% (`time_between_events`, `stance_pct`, `swing_pct`)
- double support (assemble: `time_between_events` across the contralateral
  labels, e.g. RHS→LTO + LHS→RTO)
- **[NEW] spatial:** gait speed, stride length, step length, step width (§5)

**③ Joint kinematics** — hip / knee / ankle, each available plane (FE, AB, IE)
- ROM (`range`), peak flexion/extension (`max`/`min`), angle at HS
  (`value_at_event`), peak angular velocity / acceleration
  (`peak_angular_velocity`, `peak_angular_acceleration`)

**④ Kinetics** — **overground + loaded force plates only** (treadmill has no
usable per-foot GRF; the treadmill variant omits this group)
- peak vGRF (`max`), vGRF impulse (`impulse`), loading rate (`loading_rate`),
  braking / propulsive impulse (`braking_impulse`, `propulsive_impulse`)

**⑤ Symmetry / variability**
- L/R symmetry index (`symmetry_index`) and CV (`cv`) for the key metrics
  (stride time, stance%, stride length, peak joint angles)

This is intentionally a large pipeline (~bilateral × all categories). That is the
point ("all variables"); the user trims what they don't need.

## 4. Where the two variants differ — event detection
- **트레드밀**: kinematic Zeni coordinate method on `gait:<SIDE>_<heel|toe>_ap`
  (HS = heel-AP peak max, TO = toe-AP peak min), with the `min_distance_s`
  refractory. (Already built in G2.)
- **지면 (adaptive)**: if the dataset has **loaded** force plates, use
  force-based events (Fz rising = HS, falling = TO — gold standard); otherwise
  fall back to the same kinematic Zeni method (valid overground too, Zeni 2008).
  The preset function inspects the data (e.g. fraction of Fz above a load
  threshold) to choose.

## 5. The only genuinely new engine work — spatial gait metrics
Every other metric is existing-op assembly. The spatial variables (speed,
stride length, step length, step width) do not exist yet and are exactly the
mode-dependent part.

- **트레드밀**: the body is ~stationary and the belt carries the stance foot
  backward at belt speed, so **gait speed = belt speed = the stance-phase
  horizontal speed of the planted foot** (a foot-AP velocity in the LAB frame,
  averaged over HS→TO). **stride length = gait speed × stride time.** (Validated
  this session: CEB ≈ 1.15 m/s, KKM ≈ 0.89 m/s.)
- **지면**: the body translates, so **stride length = displacement of the foot
  marker between consecutive HS** (lab-frame AP); **step length** = contralateral
  HS displacement; **step width** = ML distance between feet at contact;
  **gait speed = stride length / stride time.**

Implementation approach (to be detailed in the plan):
- expose a LAB-frame foot AP signal (the existing `gait:*` are pelvis-relative;
  belt speed needs the lab-frame velocity) — small addition alongside
  `core/gait_events.py` / `core/signals.py`;
- a **[NEW] `displacement_between_events`** op (position difference of a marker
  signal between the two segment events, projected on AP or ML) for overground
  lengths/width;
- gait speed as a ratio (overground: length/time) or product (treadmill:
  speed×time) — reuse a ratio op or add a minimal `gait_speed` op.
Units tracked to m and m/s (markers are mm → ÷1000).

## 6. Out of scope (v1)
- Running / jump / balance presets (later registry entries; this design makes
  them easy but does not build them).
- Auto-detecting overground vs treadmill (decided: explicit two presets).
- Inverse-dynamics kinetics (joint moments/power) — per catalog, dropped.
- Group ensembles / SPM export (G3/G6 territory).

## 7. Testing
- `core/presets.py`: headless tests asserting each variant returns the expected
  step set, that the overground variant adapts (force-loaded → force events;
  no/empty force → kinematic), and that the treadmill variant omits kinetics.
- New spatial ops: synthetic-signal unit tests (known displacement → known
  length/speed) + a CEB/KKM characterization (gait speed ≈ recovered belt
  speed; stride length = speed × stride time) following the existing
  `tests/test_examples_events.py` pattern (skip-guarded).
- End-to-end: seed a preset onto a CEB/KKM dataset, `run_pipeline`, assert the
  comprehensive metric set is produced with finite, physiological values.

## 8. Open decisions (inherited from docs/biomech-metric-catalog.md §"열린 결정")
- L/R event label convention (R_HS / L_HS / R_TO / L_TO) — fix in the preset.
- AP-positive = anterior (already the `gait_events` convention).
- Symmetry formula default = Robinson symmetry index (`symmetry_index`).
- Derivative endpoint / pre-derivative filtering policy for angular velocity.
- Step-width sign / which markers define ML separation.
These are resolved during implementation; none blocks the architecture.
