# G1 — Event windows in SECONDS (not frames). Implementation handoff

> Self-contained brief for a **fresh chat** (no prior context). Repo:
> `C:\Users\eunbin\Desktop\BalanceAnalyzer\BalanceAnalyzer`. Python:
> `.venv\Scripts\python.exe`. Tests: `python -m pytest -q` (Qt headless can
> crash natively on this machine — run core tests; for UI use
> `QT_QPA_PLATFORM=offscreen`, retry on crash). Test data: `tests/examples/`
> (CEB_static.c3d / CEB_st.c3d — treadmill gait; YA01/ are also there).

## 1. The bug (VERIFIED on CEB)

A `DetectEventStep`'s **`min_distance`** (peak refractory / "Min spacing") is in
**frames = samples of the signal the detector runs on**. That signal is on the
trial's **master clock**, which for a force-plate trial is the **force rate
(1000 Hz)**, even though the markers/angles are 100 Hz. So the same number means
different real time depending on the trial:

Reproduced (CEB_st, markers 100 Hz, master 1000 Hz, detect peaks on
`angle:R_HIP_angle_FE`):

| min_distance | = seconds @1000Hz | HS detected | stride | stride-CV |
|---|---|---|---|---|
| 60  | 0.06 s | **274** | 0.728 s | **63.7 %** (garbage) |
| 600 | 0.60 s | **178** | 1.122 s | **2.8 %** (correct gait) |

(With `prominence=15` both give 177 — prominence accidentally masks the clock
error, which is why a `min_distance=60` demo once "looked fine".)

Synthetic confirmation: peaks placed 0.1 s apart →
`min_distance=60` keeps all (0.06 s refractory) at fs=1000, but the **same 60**
at fs=100 = 0.6 s refractory. The value is **clock-dependent**.

## 2. Root cause (code)

- `core/events.py` `detect_peaks` (L153) and `detect_threshold_crossings`:
  `min_distance` → scipy `find_peaks(distance=min_distance)` — **in samples**.
- `core/events_compute.py` dispatch (~L180–201): passes `p.get("min_distance")`
  straight through, in master-clock frames. `compute_detected_events(dataset,
  pipeline, …)` (L217) has `dataset["time"]` (L257) and `dataset["fs"]` — the
  master fs — available but **not** used to interpret `min_distance`.
- `ui/analyze_dialogs.py` `DetectEventStepDialog` (L477–481): `min_distance_spin`
  with literal suffix `" frames"`, so the user types frames with no idea of the
  master fs.

## 3. Design (backward-compatible — do NOT break saved projects)

Saved projects store `params["min_distance"]` as **frames**. Reinterpreting that
field as seconds would turn a saved `60` into 60 s. So:

**Add a new param `min_distance_s` (seconds, float).** Precedence at run time:
```
md_s = p.get("min_distance_s")
if md_s is not None:
    min_distance_frames = max(1, round(float(md_s) * fs))   # fs = master clock
else:
    min_distance_frames = p.get("min_distance")             # legacy frames, unchanged
```
- New / edited steps write `min_distance_s` (seconds); legacy steps (only
  `min_distance`) behave exactly as before.
- Apply the SAME treatment to the threshold path's `min_distance` (L187).
- Scope (search-window) frame bounds: out of scope for G1 v1 (note as follow-up);
  do the refractory first.

## 4. Files & edits

1. **`core/events_compute.py`** — thread the master fs into the detect dispatch.
   - `compute_detected_events` (L217): compute `fs = float(dataset.get("fs") or
     (1.0/np.median(np.diff(time))))` and pass it to the per-step dispatch
     function (the one containing L180–201).
   - In that dispatch, before `detect_peaks` (L192) and
     `detect_threshold_crossings` (L183): resolve `min_distance` via the
     precedence in §3 using `fs`. Keep `prominence`, `kind`, etc. unchanged.

2. **`ui/analyze_dialogs.py` `DetectEventStepDialog`**
   - Replace the frames `min_distance_spin` with a **seconds** input
     (`QDoubleSpinBox`, range e.g. 0.0–10.0 s, default 0.0 = off). Suffix `" s"`.
   - Load from `p.get("min_distance_s")`; if absent but legacy `min_distance`
     (frames) exists, show it converted using the passed master fs (see below)
     and/or leave 0 with a hint.
   - Show the **current master fs** near the field (e.g. a muted label
     "master 1000 Hz" / "≈ N frames") so the value is unambiguous.
   - `values()` returns `params["min_distance_s"]` (seconds). Drop writing
     `params["min_distance"]` for new steps (keep reading it for old).

3. **`ui/analyze_tab.py`** — where `DetectEventStepDialog(...)` is constructed
   (search `DetectEventStepDialog(`): pass the current dataset's master fs so the
   dialog can show it / convert. The dataset fs is `dataset.get("fs", 1000.0)`.

4. **`core/pipeline.py` `DetectEventStep`** — `params` is a free dict already
   serialized verbatim, so `min_distance_s` round-trips with no class change.
   Confirm `to_dict`/`from_dict` keep arbitrary param keys (they do).

## 5. Verification (must reproduce)

- Repro script (core only, no Qt): build model from `tests/examples/CEB_static.c3d`,
  apply to `CEB_st.c3d`, master clock `np.arange(round(dur*1000)+1)/1000`, fs=1000,
  run a `DetectEventStep` on `angle:R_HIP_angle_FE` (peak/max). Assert:
  - `min_distance_s = 0.6` → ~178 HS, stride ≈ 1.12 s, CV ≈ 2.8 % **regardless of
    whether master fs is 1000 or 100** (the whole point).
  - legacy `min_distance = 60` (frames) → still 274 (unchanged back-compat).
- Add pytest: a synthetic signal sampled at fs=100 and fs=1000 with peaks 0.6 s
  apart; `min_distance_s=0.4` keeps all at both fs (frame count differs, seconds
  don't). Pin the seconds→frames conversion (`round(0.6*1000)=600`,
  `round(0.6*100)=60`).
- Full suite stays green: `python -m pytest -q` (currently 490 passed, 30 skipped).

## 6. Out of scope (later gaps — see docs/pipeline-tomorrow-gaps.md)
G2 toe-off/stance-swing, G3 `core.ensemble_from_runs()`, G7 `signals._resample`
NaN policy, scope-window seconds. Do G1 (refractory seconds) cleanly first.
