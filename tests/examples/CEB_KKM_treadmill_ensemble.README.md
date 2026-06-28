# CEB / KKM Treadmill Ensemble — Demo Project

`CEB_KKM_treadmill_ensemble.ballab` — open in Balancelab via **Analyze ▸ Open Project**.
With the **▶ Run** toggle on (saved on), it recomputes everything and shows the
ensemble curve immediately.

## What's inside

**Data (4 trials, 2 subjects, folder-grouped):**

| Folder | Trial | Role | Notes |
|---|---|---|---|
| CEB | CEB_static | static | calibrates the CEB model |
| CEB | CEB_st | dynamic | ~200 s treadmill walk (20000 frames @100 Hz) |
| KKM | KKM_static | static | calibrates the KKM model (label typo `LTHIFG_B` auto-bridged) |
| KKM | KKM_st | dynamic | ~184 s treadmill walk |

Each static carries an auto-built CAST model (`task=walk`, zero-to-standing on).
The dynamic in the same folder inherits that model (nearest-static rule).

**Pipeline (the recipe that reproduces the ensemble):**

1. **Detect event** `R_HS` — `R Hip Flex/Ext (angle:R_HIP_angle_FE)`, method
   **Peak / max**, min distance **60** frames (≈0.6 s), selector **All**.
   (No force plates on a treadmill → heel strike is taken from the hip-flexion
   peak, a standard kinematic proxy for initial contact.)
2. **Normalize (% cycle)** ×3, each `mode=cycle`, `event=R_HS`, `points=101`:
   - `R_knee_FE`  ← `angle:R_KNEE_angle_FE`
   - `R_hip_FE`   ← `angle:R_HIP_angle_FE`
   - `R_ankle_FE` ← `angle:R_ANKLE_angle_FE`

## What you should see

- **R_HS:** ~178 events (CEB). Cycle duration ~1.12 s.
- **Ensemble panel** (RESULTS): the **R_knee_FE** mean ± SD curve over 0–100 %,
  pooled over ~177 cycles. Title shows `[R_knee_FE]`.
  - Knee FE: ROM ≈ 43°, swing-flexion peak ≈ 80 % of cycle, cycle-to-cycle SD ≈ 2°.
- **Export CSV…** writes the `cycles × 101 (+ mean, sd)` matrix — the SPM input.

The panel shows the **first** NormalizeStep (`R_knee_FE`) by default; `R_hip_FE`
and `R_ankle_FE` are also computed and export from the same cycle definition.

## Reproduce from scratch (any treadmill trial)

1. Load the static + dynamic into one folder; the static auto-builds the model.
2. Add **Detect event** on `R Hip FE`, Peak/max, min-distance ≈ 0.6 s, name `R_HS`.
3. Add **Normalize (% cycle)** on `R Knee FE`, Epoch = *Consecutive event*,
   Event = `R_HS`, Points = 101.
4. Check the trial(s) → read the Ensemble panel → **Export CSV**.

To add the left side, repeat with `L Hip FE` → `L_HS` and a Normalize on
`L Knee FE` cut by `L_HS`. For a single discrete movement (jump, sit-to-stand),
mark onset/offset events and set the Normalize Epoch to *Start → end event*.

> Heel strike here is a kinematic proxy (hip-flexion peak). If you add force
> plates or a dedicated foot-contact signal, detect `R_HS` on that instead — the
> ensemble normalizes whatever cycles it is given.
