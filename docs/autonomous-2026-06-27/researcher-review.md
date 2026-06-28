# BalanceAnalyzer — Biomechanics Calculation Review (2026-06-27)

READ-ONLY scientific review of every calculation method currently in `core/`.
Verdicts: correct / acceptable / questionable / wrong.
Priorities: P1 = scientifically wrong (must fix), P2 = questionable, P3 = enhancement.
Files reviewed: core/gait_events.py, metrics.py, metrics_compute.py, signal_ops.py,
com.py, normalize.py, ensemble.py, signals.py, signal_proc.py, events.py,
marker_model.py, presets.py, run.py.
Methods reviewed: 41. Tally: correct/acceptable 35, questionable 5, wrong 1.

> NOTE (orchestrator): the single P1 below (peak-velocity sign cancellation) was
> explicitly DEFERRED by the user on 2026-06-27 ("일단 그대로 둬" / leave as-is for
> now). It is documented here and in the future-direction doc as the top pending
> correctness fix — do NOT change `_peak_abs` semantics until the user confirms.

## P1 — SCIENTIFICALLY WRONG (must fix) [DEFERRED by user]

### P1-1. Peak angular velocity/acceleration sign-cancellation across cycles
Where: core/metrics.py:234 `_peak_abs`, :246 `_op_peak_angular_velocity`,
:253 `_op_peak_angular_acceleration`; aggregated in
core/metrics_compute.py:269-291 (`compute_metric_step` does `np.mean` over cycles).
Now: per cycle `_peak_abs` returns the SIGNED sample of largest |·|; cross-cycle
mean is plain `np.mean(finite)`. For bidirectional joints (knee/hip/ankle FE) the
dominant extremum can be +flexion in one cycle and −extension in another → the mean
PARTIALLY CANCELS (e.g. +450 and −430 → +10 deg/s; observed R Knee 100 vs true ~255).
Standard: peak angular velocity is reported per DIRECTION (peak flexion vs peak
extension velocity) or as a MAGNITUDE max(|v|), never a signed cross-cycle mean
(Visual3D Metric_Maximum/Minimum are per-direction).
VERDICT: WRONG.
Fix (choose one, both valid):
 1. Magnitude (recommended default): `_peak_abs` returns abs(a[idx]) for the
    peak-velocity/accel/rfd ops → per-cycle values ≥0 → mean = mean peak speed.
 2. Direction-split: add `peak_velocity_pos` (max(v)) and `peak_velocity_neg`
    (min(v)) so flexion/extension peaks are separate, sign-consistent metrics.
 Ship (1) as the fix to existing ops; add (2) as new optional ops. loading_rate
 ((F_end−F_start)/T) is sign-consistent and unaffected. rfd is safe in presets
 (Fz rectified by `abs` first) but the magnitude fix is the safe default.

## P2 — QUESTIONABLE

P2-1. 95% COP ellipse uses chi-square (metrics.py:78,148,764): area =
π·χ²(0.95,2)·sqrt(λ1λ2), χ²≈5.991. Prieto 1996: 2π·F_{0.05[2,n−2]}·sqrt(λ1λ2);
large-n limit 2F≈6.00 (agrees <0.2%); short trials slightly under-estimated.
VERDICT: ACCEPTABLE; document. P3: switch to 2*f.ppf(0.95,2,n-2) for exact parity.
Geometry/eigen-decomposition correct.

P2-2. COP spectral (metrics.py:196-213): rfft of mean-centred COP, rectangular
window, DC excluded. Median (50%) power freq via cumulative-power = correct; MPF
centroid = correct. Rectangular window leaks on short records. VERDICT: ACCEPTABLE;
P3 optional Hann.

P2-3. Treadmill gait speed (presets.py:84; gait_events.py:120): mean(|d/dt heel_AP
_lab|) over [HS,TO] stance as belt-speed proxy, stride length = speed × stride time.
During stance the planted foot's lab AP velocity ≈ belt speed — recognised proxy;
median/mid-stance plateau cleaner than mean of rectified signal. Overground variant
(displacement_between_events heel AP HS→HS) is CORRECT and preferred when a lab
frame exists. VERDICT: ACCEPTABLE (clearly proxy-labelled).

P2-4. Foot AP velocity events (gait_events.py:181): HS & TO both = AP-velocity
minima (O'Connor/Zeni velocity variant). Defensible surrogate; coordinate method
(default) is the force-validated one. VERDICT: ACCEPTABLE; keep coordinate default.

P2-5. progression_axis geometric auto-detect (gait_events.py:74). Robust for
straight steady gait; can misfire on turns / stepping-in-place / large sway.
VERDICT: ACCEPTABLE; P3 let preset pin AP axis when lab frame known.

## Section verdicts (remaining 35 methods)

GAIT EVENTS: coordinate HS/TO (Zeni) correct; pelvis_origin correct;
foot_progression_series correct; split_stance_swing (HS→HS cycle, HS→TO stance,
drop cycles w/o interior TO) correct; seconds refractory correct; _fill_nan correct.

SPATIOTEMPORAL: stride/stance/swing time correct; stance%/swing% correct; cadence
60/step & 120/stride correct; symmetry_index (Robinson) correct; symmetry_ratio
correct; CV (SD/|mean|×100, ddof=1, ≥2) correct; cycles_from_events correct.
Double support = HS→contralateral TO is ONE of two DS intervals; clinical total DS
sums both (P3-A).

JOINT KINEMATICS: ROM=range correct; value_at_event correct; JCS Cardan xyz
Grood-Suntay FE/AB/IE correct (engine does TRUE 3-component JCS now — memory stale);
L/R sign unification correct; angle_reliability (ANKLE _AB/_IE low, KNEE _IE
moderate w/ CAST, else high) correct & well-justified; SD ddof=1 consistent.
Peak ang vel/accel = WRONG (P1-1).

SPATIAL: overground stride length (displacement HS→HS) correct; overground gait
speed = length/time correct; foot_lab_series correct; treadmill proxy acceptable
(P2-3); step-width ML building block correct (not yet in preset, P3-F).

COP/POSTUROGRAPHY: cop_resultant RD correct; RMS AP/ML correct; MDIST correct;
Range correct; sway path (Prieto total excursion) correct; mean velocity correct;
directional MVELO correct; AREA-SW triangle method correct (verified vs
Hufschmidt/Prieto eq.19); ellipse acceptable (P2-1); MPF/median freq acceptable
(P2-2); plate-local COP X/Y labelling correct/honest.

COM: de Leva BSP table correct (verified); sex-neutral average acceptable;
segment_com correct; mass-weighted whole-body COM correct; PELVIS excluded
(anti-double-count, TRUNK=mid-shoulder→mid-hip) correct & important; coverage/
partial/missing safe-only correct; mass_from_grf (|mean Fz|/g, STATIC-only,
multi-plate sum) correct. COM-COP/MOS ops MISSING (P3-C).

NORMALIZE/ENSEMBLE: resample_to_percent (np.interp, 101 nodes, interior-NaN interp,
no extrapolation) correct; epoch_windows cycle/window/trial correct; ensemble_stats
nanmean±nanstd(ddof=1) correct; epoch-weighted pooling correct (subject-weighted is
a different valid choice, P3-B).

SIGNAL-OPS: derivative (np.gradient central/one-sided, actual t) correct; integral
(trapezoidal, cumulative/total, pos/neg gating) correct (forward=+ assumption
flagged); magnitude Euclidean NaN-propagating correct; absval/power correct;
derive_unit correct; jump_height_impulse (∫(Fz−BW)/m → v²/2g) correct; flight-time
g·t²/8 correct (equal-height assumption documented); RSI correct.

EVENTS: threshold-CROSSING (edge not level, hysteresis + refractory; standing→no
crossing) correct & well-reasoned; detect_peaks correct; detect_global_extreme
(V3D Event_Global_Maximum) correct; zero-crossings correct; select_instances
first/nth/range/all correct.

FILTERING: apply_lowpass zero-lag filtfilt (Butter/Cheby1/Bessel); marker filtering
per contiguous finite run (NaN gaps preserved, not interpolated across) correct;
6 Hz default standard for gait. VERDICT: correct.

## P3 — ENHANCEMENTS
P3-A total double-support % (both intervals); P3-B subject- vs cycle-weighted group
stats option; P3-C COM-COP / MOS / XCOM ops (COM engine exists, no metric consumes
it); P3-D Prieto F-stat ellipse; P3-E Hann spectral window; P3-F wire step-width/
step-length into a preset; P3-G pin progression axis when lab frame known.

## HELP-DOC SEEDS (beginner, 3–5 sentences each)
Top gaps order: (1) Gait events, (2) Ensemble curves, (3) Signal operations,
(4) Per-cycle/reference metrics, (5) COM partial/coverage.
(Full beginner text for all 7 features is carried into the help-docs task.)

## Sources
- Zeni/O'Connor 2008 coordinate method (validated vs force plates, 75% within 1
  frame): https://pubmed.ncbi.nlm.nih.gov/17723303/ ,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC2384115/
- Prieto et al. 1996 COP measures (IEEE TBME 43:956); review:
  https://physoc.onlinelibrary.wiley.com/doi/10.14814/phy2.15067
- de Leva 1996 BSP: J Biomech 29(9):1223-1230.
- ISB conventions: Wu et al. 2002 (lower limb), 2005 (upper limb).

## MEMORY CORRECTION
The angle engine is no longer "vector angles only": core/marker_model.py now
computes full ISB Grood-Suntay JCS Cardan 3-component angles (FE/AB/IE). The
`event-pipeline-redesign.md` / memory note describing vector angles is STALE.
