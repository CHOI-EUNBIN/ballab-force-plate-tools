import logging

import numpy as np
from scipy.stats import chi2 as chi2_dist
from scipy.fft import rfft, rfftfreq

from core import signal_ops

log = logging.getLogger(__name__)

#: Standard gravity (m/s^2) — used by the jump-height / takeoff-velocity ops.
#: Matches ``core.run.G`` (the body-weight conversion constant) so a body weight
#: and a jump height computed in the same run rest on the same g.
G = 9.80665

METRIC_KEYS = [
    "RMS AP",
    "RMS ML",
    "Range AP",
    "Range ML",
    "Mean AP",
    "Mean ML",
    "Mean distance",
    "95% Ellipse area",
    "Sway path length",
    "Mean velocity",
    "Mean velocity AP",
    "Mean velocity ML",
    "Sway area",
    "Mean power freq AP",
    "Mean power freq ML",
    "Median freq AP",
    "Median freq ML",
]


ANGLE_STATS = ["ROM", "Min", "Max", "Mean", "SD", "Start", "End"]


def compute_angle_metrics(angles, time, start_s, end_s, stats):
    """Per-angle stats over the [start_s, end_s] window (marker-clock seconds).

    angles: {name: (F,) degrees}; time: (F,) seconds. Returns
    {"<angle> <stat>": (value, "deg")}. NaN-safe; occluded frames ignored.
    """
    out = {}
    if not stats or not angles:
        return out
    time = np.asarray(time, dtype=float)
    mask = (time >= start_s) & (time <= end_s)
    if not mask.any():
        return out
    for name, arr in angles.items():
        a = np.asarray(arr, dtype=float)[mask]
        finite = a[np.isfinite(a)]
        if finite.size < 1:
            continue
        for stat in stats:
            if stat == "ROM":
                v = float(np.nanmax(a) - np.nanmin(a))
            elif stat == "Min":
                v = float(np.nanmin(a))
            elif stat == "Max":
                v = float(np.nanmax(a))
            elif stat == "Mean":
                v = float(np.nanmean(a))
            elif stat == "SD":
                # Sample SD (ddof=1), matching SCALAR_OPS["std"] and the per-cycle
                # SD in metrics_compute so "SD" means the same thing on every path.
                finite_a = a[np.isfinite(a)]
                v = float(np.std(finite_a, ddof=1)) if finite_a.size > 1 else 0.0
            elif stat == "Start":
                v = float(finite[0])
            elif stat == "End":
                v = float(finite[-1])
            else:
                continue
            out[f"{name} {stat}"] = (v, "deg")
    return out


def _cop_ellipse(ap_c, ml_c, confidence=0.95):
    """Shared 95% (or ``confidence``) COP confidence-ellipse geometry.

    The single source of truth for BOTH the ellipse *area* (in
    :func:`compute_metrics`) and the ellipse *outline points* (in
    :func:`compute_ellipse_points`), so the two cannot drift apart.

    ``ap_c`` / ``ml_c`` are the mean-CENTRED COP components (AP and ML). The
    covariance is built in **[ML, AP]** order (x=ML, y=AP) to match the plot
    axes, then eigen-decomposed (``np.linalg.eigh`` -> ascending eigenvalues,
    matching orthonormal eigenvectors). Returns ``(eigvals, eigvecs, chi2_val)``
    where:

      * ``eigvals``  — (2,) variances along the principal axes, ascending,
        clipped to >= 0 (a tiny negative from round-off would break the sqrt).
        The product is the squared geometric mean of the semi-axes -> area is
        ``pi * chi2_val * sqrt(prod(eigvals))`` (axis-order independent).
      * ``eigvecs``  — (2,2) columns are the principal-axis directions in
        [ML, AP] space (column ``i`` matches ``eigvals[i]``); used to rotate the
        outline. ``eigvecs[:, 1]`` is the MAJOR axis (largest eigenvalue).
      * ``chi2_val`` — the chi-square critical value at ``confidence`` (df=2),
        ~= 5.991 at 0.95.

    Mirrors the legacy math exactly (area used ``[ap, ml]`` order; the product of
    the two eigenvalues is identical either way, so the area is bit-for-bit
    unchanged). NaN-free input assumed (callers centre first); a degenerate /
    all-zero cloud yields zero eigenvalues -> zero area, a point ellipse.
    """
    cov = np.cov(np.vstack([ml_c, ap_c]))
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(np.abs(eigvals), 0.0, None)   # ascending, non-negative
    chi2_val = chi2_dist.ppf(confidence, df=2)
    return eigvals, eigvecs, chi2_val


def compute_metrics(cop_ap, cop_ml, fs, selected_keys):
    results = {}
    n = len(cop_ap)
    if n < 2:
        return results

    ap = np.array(cop_ap, dtype=float)
    ml = np.array(cop_ml, dtype=float)
    # NaN-safe centring: an occluded/gap sample is ignored rather than poisoning
    # the whole window. With no NaN every metric below is bit-for-bit identical
    # to the old non-nan-safe version (nanmean == mean, etc.).
    ap_c = ap - np.nanmean(ap)
    ml_c = ml - np.nanmean(ml)
    duration = (n - 1) / fs

    for key in selected_keys:
        try:
            if key == "RMS AP":
                results[key] = (float(np.sqrt(np.nanmean(ap_c ** 2))), "mm")

            elif key == "RMS ML":
                results[key] = (float(np.sqrt(np.nanmean(ml_c ** 2))), "mm")

            elif key == "Range AP":
                results[key] = (float(np.nanmax(ap) - np.nanmin(ap)), "mm")

            elif key == "Range ML":
                results[key] = (float(np.nanmax(ml) - np.nanmin(ml)), "mm")

            elif key == "Mean AP":
                results[key] = (float(np.nanmean(ap)), "mm")

            elif key == "Mean ML":
                results[key] = (float(np.nanmean(ml)), "mm")

            elif key == "95% Ellipse area":
                # Shared geometry (see _cop_ellipse). Area = pi * chi2 * (product
                # of the two principal-axis sqrt-variances); the eigenvalue product
                # is axis-order independent so this equals the old [ap, ml] math.
                eigvals, _, chi2_val = _cop_ellipse(ap_c, ml_c, 0.95)  # chi2 ~= 5.991
                area = np.pi * chi2_val * np.sqrt(eigvals[0] * eigvals[1])
                results[key] = (float(area), "mm^2")

            elif key == "Sway path length":
                step = np.sqrt(np.diff(ap) ** 2 + np.diff(ml) ** 2)
                # NaN-safe: a single occluded/gap sample makes one inter-sample
                # step NaN; skip those steps (nansum) so the whole path is not
                # poisoned by one missing frame. With no NaN this is identical
                # to np.sum (Prieto 1996 total excursion).
                path = float(np.nansum(step))
                results[key] = (path, "mm")

            elif key == "Mean velocity":
                step = np.sqrt(np.diff(ap) ** 2 + np.diff(ml) ** 2)
                path = float(np.nansum(step))
                results[key] = (path / duration if duration > 0 else 0.0, "mm/s")

            elif key == "Mean distance":
                # MDIST (Prieto 1996): mean resultant distance of the COP from its
                # own mean — the average radius of sway. RD = sqrt((AP-AP̄)² +
                # (ML-ML̄)²); MDIST = mean(RD). Companion to RMS (which is the
                # quadratic mean of the SAME RD). NaN-safe.
                rd = np.sqrt(ap_c ** 2 + ml_c ** 2)
                results[key] = (float(np.nanmean(rd)), "mm")

            elif key in ("Mean velocity AP", "Mean velocity ML"):
                # Directional mean velocity (Prieto 1996, MVELO_AP / MVELO_ML):
                # the 1-D path length along that axis ÷ duration. Same NaN-safe
                # rule as the resultant Mean velocity (a gap step is skipped).
                comp = ap if key.endswith("AP") else ml
                path1d = float(np.nansum(np.abs(np.diff(comp))))
                results[key] = (path1d / duration if duration > 0 else 0.0, "mm/s")

            elif key == "Sway area":
                # AREA-SW (Prieto 1996): area swept by the COP per unit time. Using
                # the shoelace/triangle formula about the mean COP, the area of each
                # triangle (mean, point[n], point[n+1]) summed and divided by T:
                #   AREA-SW = (1/2T) Σ |AP_c[n+1]·ML_c[n] − AP_c[n]·ML_c[n+1]|.
                # mm²/s. NaN-safe (a gap triangle contributes NaN -> skipped).
                tri = np.abs(ap_c[1:] * ml_c[:-1] - ap_c[:-1] * ml_c[1:])
                area = float(np.nansum(tri)) / (2.0 * duration) if duration > 0 else 0.0
                results[key] = (area, "mm^2/s")

            elif key in ("Mean power freq AP", "Mean power freq ML",
                         "Median freq AP", "Median freq ML"):
                sig = ap_c if key.endswith("AP") else ml_c
                freqs = rfftfreq(n, 1.0 / fs)
                psd = np.abs(rfft(sig)) ** 2
                pos = freqs > 0
                f, p = freqs[pos], psd[pos]
                total = np.sum(p)
                if total > 0 and len(f) > 0:
                    if key.startswith("Mean power"):
                        val = float(np.sum(f * p) / total)
                    else:
                        cumsum = np.cumsum(p)
                        idx = min(np.searchsorted(cumsum, total * 0.5), len(f) - 1)
                        val = float(f[idx])
                else:
                    val = 0.0
                results[key] = (val, "Hz")

        except Exception:
            # Degrade gracefully — one bad key must not drop the others — but
            # leave a trace so a genuine bug isn't silently invisible. The
            # missing key simply won't appear in ``results`` (the caller treats
            # an absent key as "not computed").
            log.warning("compute_metrics: key %r failed", key, exc_info=True)

    return results


# ---------------------------------------------------------------------------
# Op registry — the pipeline MetricStep reduces one signal (over a window) to a
# scalar via a named ``op``. This wraps the math above as ``op -> function`` so a
# step just stores the op name. Three families:
#   * scalar  : reduce a 1-D windowed array -> value (+ frame for argmax/argmin)
#   * cop      : multivariate COP metrics (need a plate's AP & ML together)
#   * reference: read another artifact (value_at_event)
# ``compute_*`` above stay as-is (used until the UI is rewired); these reuse them.

#: scalar op -> (fn(arr[, t])->(value, arg_frame|None)). arg_frame is the index
#: WITHIN the window of the extremum (so max/min can also emit an event); None
#: otherwise. A ``needs_time`` op (see :data:`OP_INFO`) takes the window's time
#: axis ``t`` as a second positional arg; the others ignore it.
def _peak_abs(a):
    """Signed value of the largest-|·| sample (the clinical 'peak' of a signal
    that may swing both ways): returns the extremum farthest from 0, keeping its
    sign, and its index. e.g. [-9, 2, 5] -> (-9.0, 0). NaN-safe."""
    a = np.asarray(a, dtype=float)
    fin = np.isfinite(a)
    if not fin.any():
        return float("nan"), None
    idx = int(np.nanargmax(np.where(fin, np.abs(a), -np.inf)))
    return float(a[idx]), idx


def _op_peak_angular_velocity(a, t=None):
    """Angle (deg) -> angular velocity (d/dt, deg/s) -> peak |angular velocity|,
    signed. The dominant joint-angular-velocity magnitude in the window."""
    v = signal_ops.derivative(a, t, order=1)
    return _peak_abs(v)


def _op_peak_angular_acceleration(a, t=None):
    """Angle (deg) -> angular acceleration (d2/dt2, deg/s^2) -> peak |·|, signed."""
    acc = signal_ops.derivative(a, t, order=2)
    return _peak_abs(acc)


def _op_rfd(a, t=None):
    """Force (N) -> rate of force development (d/dt, N/s) -> peak |·|, signed.
    The single steepest instantaneous slope of the force in the window."""
    r = signal_ops.derivative(a, t, order=1)
    return _peak_abs(r)


def _op_loading_rate(a, t=None):
    """Force (N) -> average loading rate over the window = (F_end - F_start)/T
    (N/s): the mean slope from the first to the last sample of the window. The
    window IS the loading interval (the user/segment defines it, e.g. IC->peak)."""
    a = np.asarray(a, dtype=float)
    t = np.asarray(t, dtype=float)
    fin = np.isfinite(a) & np.isfinite(t)
    if np.count_nonzero(fin) < 2:
        return float("nan"), None
    af, tf = a[fin], t[fin]
    dt = tf[-1] - tf[0]
    if dt == 0:
        return float("nan"), None
    return float((af[-1] - af[0]) / dt), None


def _op_impulse(a, t=None):
    """Force (N) -> impulse = integral of force over the window (N*s), all signs."""
    return float(signal_ops.integral(a, t, kind="total", sign="all")), None


def _op_braking_impulse(a, t=None):
    """AP force (N) -> braking impulse = integral of the NEGATIVE (decelerating)
    portion over the window (N*s, <=0). Assumes anterior (forward) = +."""
    return float(signal_ops.integral(a, t, kind="total", sign="neg")), None


def _op_propulsive_impulse(a, t=None):
    """AP force (N) -> propulsive impulse = integral of the POSITIVE (accelerating)
    portion over the window (N*s, >=0). Assumes anterior (forward) = +."""
    return float(signal_ops.integral(a, t, kind="total", sign="pos")), None


SCALAR_OPS = {
    "min":   lambda a, t=None: (float(np.nanmin(a)), int(np.nanargmin(a))),
    "max":   lambda a, t=None: (float(np.nanmax(a)), int(np.nanargmax(a))),
    "mean":  lambda a, t=None: (float(np.nanmean(a)), None),
    "range": lambda a, t=None: (float(np.nanmax(a) - np.nanmin(a)), None),
    "std":   lambda a, t=None: (float(np.nanstd(a, ddof=1)) if np.sum(np.isfinite(a)) > 1 else 0.0, None),
    "rms":   lambda a, t=None: (float(np.sqrt(np.nanmean(np.asarray(a, float) ** 2))), None),
    # needs_time: definite time-integral over the window (impulse / area). ``t``
    # is the window's seconds axis; trapezoidal, NaN-safe (signal_ops.integral).
    "integral": lambda a, t=None: (signal_ops.integral(a, t, kind="total"), None),
    # plain accumulation of the windowed samples (no time weighting), e.g. a
    # total count/sum; keeps the base unit. ``t`` ignored.
    "sum":   lambda a, t=None: (float(np.nansum(a)), None),
    # --- Round B1: named derivative/integral clinical ops (all needs_time) ----
    # Each takes the RAW windowed signal + its time axis, differentiates or
    # integrates internally, then reduces to a scalar. See the helper docstrings
    # for the math and the unit each carries (tracked in _OP_UNIT_TRANSFORM).
    "peak_angular_velocity":     _op_peak_angular_velocity,
    "peak_angular_acceleration": _op_peak_angular_acceleration,
    "rfd":                       _op_rfd,
    "loading_rate":              _op_loading_rate,
    "impulse":                   _op_impulse,
    "braking_impulse":           _op_braking_impulse,
    "propulsive_impulse":        _op_propulsive_impulse,
}

#: Scalar ops that need the window's time axis passed in (the glue slices
#: ``ctx.time[lo:hi+1]`` for these). Mirrors how ``cop_op`` receives ``fs``.
#: All the Round B1 derivative/integral ops differentiate/integrate over time,
#: so they all need ``t``.
_NEEDS_TIME = {
    "integral",
    "peak_angular_velocity", "peak_angular_acceleration",
    "rfd", "loading_rate",
    "impulse", "braking_impulse", "propulsive_impulse",
}

#: How each scalar op transforms its input signal's unit. ``signal_ops`` method
#: name ("derivative"/"derivative2"/"integral") drives :func:`signal_ops.derive_unit`
#: (deg->deg/s, deg->deg/s^2, N->N*s); ``None`` keeps the base unit. Used by
#: :func:`core.metrics_compute._op_unit` so e.g. a peak_angular_velocity reads
#: "deg/s" instead of the angle's "deg".
_OP_UNIT_TRANSFORM = {
    "integral": "integral",
    "impulse": "integral",
    "braking_impulse": "integral",
    "propulsive_impulse": "integral",
    "peak_angular_velocity": "derivative",
    "rfd": "derivative",
    "loading_rate": "derivative",
    "peak_angular_acceleration": "derivative2",
}


def op_unit(op, base_unit):
    """Unit a scalar ``op`` produces from a signal of unit ``base_unit``.

    Drives :func:`core.signal_ops.derive_unit` via :data:`_OP_UNIT_TRANSFORM`
    (e.g. ``peak_angular_velocity`` on "deg" -> "deg/s"; ``impulse`` on "N" ->
    "N*s"). Ops not in the table keep the base unit.
    """
    method = _OP_UNIT_TRANSFORM.get(op)
    if method is None:
        return base_unit
    if method == "derivative2":
        return signal_ops.derive_unit(base_unit, "derivative", order=2)
    return signal_ops.derive_unit(base_unit, method)


# ---------------------------------------------------------------------------
# Round B2 — spatiotemporal (event-pair) ops, jump ops, symmetry/variability.
#
# Three NEW families layered on top of the scalar/cop/sample ops above:
#   * event     : a metric over a PAIR of event labels (segment=[start,end]). Per
#                 cycle the glue pairs each ``start`` frame with the next ``end``
#                 frame -> a window [lo, hi]; the op reduces that window's
#                 *duration* (time/frames) to a scalar. No signal input. This one
#                 op (``time_between_events``) is the building block for ALL gait
#                 spatiotemporals (stride/step/stance/swing/contact/flight): the
#                 clinical NAME is the user's metric name + which two event labels
#                 they pick. ``jump_height_flight_time`` is an event op too: it
#                 takes the flight-phase duration t and returns g*t^2/8.
#   * jump      : impulse-momentum jump ops over a FORCE signal that also need the
#                 subject MASS (read from the metric catalog, like a normalize ref).
#   * reference : a metric DERIVED from one or two already-computed metric values
#                 (cadence from a step/stride time; symmetry/ratio from L & R;
#                 CV from a per-cycle metric). These read ``input``/``input2`` as
#                 ``metric:<name>`` references, so they must sit AFTER the metrics
#                 they cite (single-pass executor, top-to-bottom).
# All math here is pure/NaN-safe; the glue (metrics_compute) routes by OP_INFO
# ``input`` kind and hands over the frames / fs / time / metric values needed.

def event_duration(lo, hi, fs, t=None, kind="time"):
    """Duration of the event window ``[lo, hi]`` (inclusive frames).

    ``kind="time"`` -> seconds. Uses the actual time axis ``t[hi] - t[lo]`` when
    given (correct for a non-uniform clock), else falls back to ``(hi - lo)/fs``.
    ``kind="frames"`` -> integer frame count ``hi - lo``. NaN/empty-safe (a
    non-positive or missing window -> NaN).
    """
    if lo is None or hi is None or hi < lo:
        return float("nan")
    if kind == "frames":
        return float(int(hi) - int(lo))
    if t is not None:
        t = np.asarray(t, dtype=float)
        if 0 <= lo < t.size and 0 <= hi < t.size:
            return float(t[int(hi)] - t[int(lo)])
    if fs and fs > 0:
        return float((int(hi) - int(lo)) / fs)
    return float("nan")


def jump_height_flight_time(t_flight):
    """Jump height from flight time (the time-of-flight method): ``h = g t^2 / 8``.

    Derivation: in free flight the body rises for t_flight/2 then falls for
    t_flight/2; with takeoff speed v = g (t_flight/2), the apex height is
    v^2/(2g) = g t_flight^2 / 8. Assumes takeoff and landing at the SAME height
    (true for a CMJ off a force plate, NOT for a drop jump landing lower than
    takeoff). Robust because it needs only two event times, but it can
    over-estimate if the athlete tucks the legs in flight (lengthens t_flight).
    """
    t = float(t_flight)
    if not np.isfinite(t) or t <= 0:
        return float("nan")
    return G * t * t / 8.0


def jump_height_impulse(fz, t, mass, weight=None):
    """Jump height from the impulse-momentum (net-impulse) method.

    The takeoff (vertical) velocity is v = J_net / m, where
    J_net = integral of (Fz - body weight) dt over the window (the propulsion
    phase up to takeoff); h = v^2 / (2 g). ``mass`` (kg) is the subject mass;
    ``weight`` (N) defaults to ``mass * g``. Considered the gold-standard CMJ
    height because it does not assume equal takeoff/landing height; it is
    sensitive to the integration window and to an accurate body weight
    (best taken from a quiet-standing baseline). Returns ``(height_m, v_takeoff)``.
    NaN-safe.
    """
    if not mass or mass <= 0:
        return float("nan"), float("nan")
    w = float(weight) if weight is not None else float(mass) * G
    j_net = signal_ops.integral(np.asarray(fz, dtype=float) - w, t,
                                kind="total", sign="all")
    v = j_net / float(mass)
    if not np.isfinite(v):
        return float("nan"), float("nan")
    h = v * v / (2.0 * G) if v > 0 else 0.0
    return float(h), float(v)


def symmetry_index(left, right):
    """Robinson Symmetry Index (%): ``|L - R| / (0.5 (L + R)) * 100``.

    A normalised absolute asymmetry: 0% = perfectly symmetric, larger = more
    asymmetric. The denominator is the mean of the two limbs so the index is
    independent of the metric's scale. Sign is dropped (always >= 0); use
    :func:`symmetry_ratio` if direction matters. (Robinson et al. 1987;
    Herzog et al. 1989.) NaN-safe; a zero mean -> NaN.
    """
    l, r = float(left), float(right)
    denom = 0.5 * (l + r)
    if not np.isfinite(denom) or denom == 0:
        return float("nan")
    return abs(l - r) / denom * 100.0


def symmetry_ratio(left, right):
    """Symmetry ratio ``L / R`` (dimensionless; 1.0 = symmetric).

    Keeps direction (>1 = left larger, <1 = right larger). NaN-safe; a zero
    right side -> NaN.
    """
    l, r = float(left), float(right)
    if not np.isfinite(r) or r == 0:
        return float("nan")
    return l / r


def coefficient_of_variation(values):
    """Coefficient of variation (%) of a per-cycle value array: ``SD/mean*100``.

    Stride-to-stride variability normalised by the mean (so it is comparable
    across metrics of different magnitude). SD is the sample SD (ddof=1), matching
    the per-cycle SD reported elsewhere. Uses ``|mean|`` in the denominator so a
    metric that can be negative still yields a positive CV. NaN-safe; needs >= 2
    finite values, else NaN.
    """
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 2:
        return float("nan")
    m = np.mean(a)
    if m == 0:
        return float("nan")
    return float(np.std(a, ddof=1) / abs(m) * 100.0)


#: Event-pair op -> (kind, post). The glue (metrics_compute) turns segment
#: endpoints into per-cycle windows; here the op only says how to read a window's
#: duration (``"time"`` seconds / ``"frames"``) and an optional post-transform of
#: that duration into the named metric (e.g. flight time -> g t^2/8).
EVENT_OPS = {
    "time_between_events":   ("time",   None,                     "s"),
    "frames_between_events": ("frames", None,                     ""),
    "jump_height_flight_time": ("time", jump_height_flight_time,  "m"),
}

#: Impulse-momentum jump ops -> the value index returned by
#: :func:`jump_height_impulse` (0 = height m, 1 = takeoff velocity m/s) + unit.
#: These read a FORCE signal over the window AND the subject ``mass`` metric.
JUMP_OPS = {
    "jump_height_impulse": (0, "m"),
    "takeoff_velocity":    (1, "m/s"),
}

#: Reference ops -> (fn, n_inputs, unit). They derive a scalar from already
#: computed metric VALUES (cited via ``input``/``input2`` as ``metric:`` refs),
#: not from a signal. ``n_inputs`` = how many metric refs the op consumes.
#: ``cadence`` converts a step/stride TIME (s) to steps/min; the caller passes the
#: per-step convention via ``input2`` ("stride" doubles it). ``rsi`` = jump height
#: / contact time. ``stance_pct``/``swing_pct`` = phase time / stride time * 100.
def _cadence_from_step_time(step_time):
    """Cadence (steps/min) from a single STEP time (s): ``60 / step_time``.

    A step = one foot contact to the next (opposite) foot contact; cadence counts
    those steps per minute. From a STRIDE time (one full gait cycle = two steps)
    use ``120 / stride_time`` (see :func:`_cadence_from_stride_time`). NaN-safe.
    """
    t = float(step_time)
    if not np.isfinite(t) or t <= 0:
        return float("nan")
    return 60.0 / t


def _cadence_from_stride_time(stride_time):
    """Cadence (steps/min) from a STRIDE time (s): ``120 / stride_time``."""
    t = float(stride_time)
    if not np.isfinite(t) or t <= 0:
        return float("nan")
    return 120.0 / t


def _phase_pct(phase_time, stride_time):
    """Phase as a percent of the gait cycle: ``phase / stride * 100`` (%).

    e.g. stance% = stance time / stride time * 100; swing% = swing/stride*100.
    NaN-safe; a non-positive stride -> NaN.
    """
    p, s = float(phase_time), float(stride_time)
    if not np.isfinite(s) or s <= 0:
        return float("nan")
    return p / s * 100.0


def _rsi(jump_height, contact_time):
    """Reactive Strength Index (m/s): jump height (m) / ground-contact time (s).

    The drop-jump RSI: how high you rebound per second of contact. Higher = more
    reactive/elastic. NaN-safe; a non-positive contact time -> NaN.
    """
    h, c = float(jump_height), float(contact_time)
    if not np.isfinite(c) or c <= 0:
        return float("nan")
    return h / c


def _product(a, b):
    """Binary product (a × b): multiply two metric values.

    NaN-safe: if either input is NaN or non-finite, return NaN.
    """
    a, b = float(a), float(b)
    return a * b if (np.isfinite(a) and np.isfinite(b)) else float("nan")


def _sum_pair(a, b):
    """Binary sum (a + b): add two metric values.

    The building block for a *total* of two phase times — e.g. the two
    double-support intervals of a gait cycle (R_HS→L_TO + L_HS→R_TO) into one
    total double-support time. NaN-safe: a non-finite input -> NaN.
    """
    a, b = float(a), float(b)
    return a + b if (np.isfinite(a) and np.isfinite(b)) else float("nan")


def _double_support_pct(double_support_time, stride_time):
    """Total double-support as a percent of the gait cycle: ``ds / stride * 100``.

    The clinical single-value double-support metric: the time both feet are on
    the ground (the SUM of the two double-support intervals, R_HS→L_TO and
    L_HS→R_TO) divided by the stride (gait-cycle) time. Normal adult walking is
    ~20 % (~10 % per interval); it rises with slower / less stable gait (it is a
    sensitive marker of balance impairment) and falls toward 0 % at running
    (no double support). Identical math to :func:`_phase_pct` (phase/stride*100),
    kept as its own named op so the metric reads clearly. NaN-safe; a
    non-positive stride -> NaN. (Perry & Burnfield 2010; Whittle 2007.)
    """
    return _phase_pct(double_support_time, stride_time)


def _quotient(a, b):
    """Binary quotient (a ÷ b): divide two metric values.

    NaN-safe: if either input is NaN, non-finite, or divisor is zero, return NaN.
    """
    a, b = float(a), float(b)
    if not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return float("nan")
    return a / b


REFERENCE_OPS = {
    "cadence":         (_cadence_from_step_time, 1, "steps/min"),
    "cadence_stride":  (_cadence_from_stride_time, 1, "steps/min"),
    "stance_pct":      (_phase_pct, 2, "%"),
    "swing_pct":       (_phase_pct, 2, "%"),
    "rsi":             (_rsi, 2, "m/s"),
    "symmetry_index":  (symmetry_index, 2, "%"),
    "symmetry_ratio":  (symmetry_ratio, 2, ""),
    "cv":              (coefficient_of_variation, 1, "%"),  # per-cycle array, not a ref
    "product":         (_product, 2, ""),
    "quotient":        (_quotient, 2, ""),
    "add":             (_sum_pair, 2, ""),
    "double_support_pct": (_double_support_pct, 2, "%"),
}

#: COP composite op -> the METRIC_KEYS label it computes (reuses compute_metrics).
#: These need a plate's COP *pair* (AP & ML), passed by the glue.
COP_OPS = {
    "rms_ap": "RMS AP", "rms_ml": "RMS ML",
    "range_ap": "Range AP", "range_ml": "Range ML",
    "mean_ap": "Mean AP", "mean_ml": "Mean ML",
    "mean_distance": "Mean distance",
    "ellipse_area": "95% Ellipse area", "sway_path": "Sway path length",
    "mean_velocity": "Mean velocity",
    "mean_velocity_ap": "Mean velocity AP", "mean_velocity_ml": "Mean velocity ML",
    "sway_area": "Sway area",
    "mpf_ap": "Mean power freq AP", "mpf_ml": "Mean power freq ML",
    "mdf_ap": "Median freq AP", "mdf_ml": "Median freq ML",
}

#: Human labels + the input kind each op expects, for the Add-step form.
#: input kinds: "signal" (any 1-D signal), "cop" (a plate COP), "sample" (a
#: signal + an event to read it at), "event" (event-frame time differences — the
#: spatiotemporal family; SCAFFOLD only, the concrete time_between_events op is
#: biomech's Round B). ``needs_time`` flags an op the glue must hand the window's
#: time axis (mirrors ``cop_op`` receiving ``fs``).
#: Op-label spellings: "Integral"/"Sum" are generic; biomech wraps these as named
#: clinical metrics (e.g. "vGRF impulse") in Round B.
#: Human labels + intended input signal type for the named clinical ops (so the
#: Add-step form shows "Peak angular velocity", not "Peak_angular_velocity", and
#: can filter the op list by signal kind). ``signal_kind`` is a HINT for the UI's
#: signal->valid-op map (Round C); the math itself accepts any 1-D signal. The
#: peak (derivative-based) ops emit an event at the extremum frame.
_NAMED_SCALAR_LABELS = {
    "peak_angular_velocity":     ("Peak angular velocity",     "angle", True),
    "peak_angular_acceleration": ("Peak angular acceleration", "angle", True),
    "rfd":                       ("Rate of force development (RFD)", "force", True),
    "loading_rate":              ("Loading rate",              "force", False),
    "impulse":                   ("Impulse",                   "force", False),
    "braking_impulse":           ("Braking impulse",           "force", False),
    "propulsive_impulse":        ("Propulsive impulse",        "force", False),
}


def _scalar_info(k):
    """OP_INFO entry for a scalar op ``k`` (named clinical op or generic)."""
    label, kind, emits = _NAMED_SCALAR_LABELS.get(
        k, (k.capitalize(), None, k in ("min", "max")))
    info = {"label": label, "category": "scalar", "input": "signal",
            "emits_event": emits, "needs_time": k in _NEEDS_TIME}
    if kind is not None:
        info["signal_kind"] = kind
    return info


#: Round B2 op metadata: (label, signal_kind hint for the UI's signal->valid-op
#: filter, Round C). ``event``-kind ops consume a pair of event labels (segment);
#: ``jump`` ops a force signal + the subject mass; ``reference`` ops one/two metric
#: values. ``signal_kind`` "event" = the spatiotemporal family (no signal input);
#: "force"+"event" jump ops; "metric" = derived-from-metrics.
_EVENT_LABELS = {
    "time_between_events":   ("Time between events",   "event"),
    "frames_between_events": ("Frames between events", "event"),
    "jump_height_flight_time": ("Jump height (flight time)", "event"),
}
_JUMP_LABELS = {
    "jump_height_impulse": ("Jump height (impulse-momentum)", "force"),
    "takeoff_velocity":    ("Takeoff velocity",               "force"),
}
_REFERENCE_LABELS = {
    "cadence":        ("Cadence (from step time)",   "metric"),
    "cadence_stride": ("Cadence (from stride time)", "metric"),
    "stance_pct":     ("Stance %",                   "metric"),
    "swing_pct":      ("Swing %",                    "metric"),
    "rsi":            ("Reactive Strength Index (RSI)", "metric"),
    "symmetry_index": ("Symmetry index (Robinson SI)", "metric"),
    "symmetry_ratio": ("Symmetry ratio (L/R)",       "metric"),
    "cv":             ("Coefficient of variation (CV)", "metric"),
    "product":        ("Product (a x b)",             "metric"),
    "quotient":       ("Quotient (a / b)",            "metric"),
    "add":            ("Sum (a + b)",                 "metric"),
    "double_support_pct": ("Double support %",        "metric"),
}


def _event_info(k):
    label, kind = _EVENT_LABELS[k]
    return {"label": label, "category": "event", "input": "event",
            "emits_event": False, "needs_time": False, "signal_kind": kind}


def _jump_info(k):
    label, kind = _JUMP_LABELS[k]
    # jump ops read a force window over a [takeoff/landing] segment + subject mass;
    # they need the time axis (impulse integration). signal_kind "force".
    return {"label": label, "category": "jump", "input": "jump",
            "emits_event": False, "needs_time": True, "signal_kind": kind}


def _reference_info(k):
    label, kind = _REFERENCE_LABELS[k]
    # ``cv`` reads a per-cycle array of ONE metric; the others read 1-2 metric refs.
    return {"label": label, "category": "reference", "input": "metric",
            "emits_event": False, "needs_time": False, "signal_kind": kind,
            "n_inputs": REFERENCE_OPS[k][1]}


# ---------------------------------------------------------------------------
# Spatial displacement ops — per-cycle signal[hi] - signal[lo] over the
# event-pair window [lo, hi]. The building block for overground stride length
# (foot AP displacement between consecutive HS) and step width (ML).
_DISPLACEMENT_OPS = {
    "displacement_between_events": ("Displacement between events", "signal"),
}


def _displacement_info(k):
    label, kind = _DISPLACEMENT_OPS[k]
    return {"label": label, "category": "displacement", "input": "displacement",
            "emits_event": False, "needs_time": False, "signal_kind": kind}


OP_INFO = {
    **{k: _scalar_info(k) for k in SCALAR_OPS},
    **{k: {"label": v, "category": "cop", "input": "cop", "emits_event": False,
           "needs_time": False, "signal_kind": "cop"} for k, v in COP_OPS.items()},
    "value_at_event": {"label": "Value at event", "category": "reference",
                       "input": "sample", "emits_event": False,
                       "needs_time": False},
    **{k: _event_info(k) for k in EVENT_OPS},
    **{k: _jump_info(k) for k in JUMP_OPS},
    **{k: _reference_info(k) for k in REFERENCE_OPS},
    **{k: _displacement_info(k) for k in _DISPLACEMENT_OPS},
}


def available_metric_ops():
    """``{op: info}`` catalog of metric operations the Add-step form offers."""
    return dict(OP_INFO)


def scalar_op(op, arr, t=None):
    """Reduce a 1-D array ``arr`` by scalar ``op`` -> ``(value, arg_frame|None)``.

    ``arg_frame`` is the index within ``arr`` of the extremum for min/max (so the
    caller can emit an event), else ``None``. Empty/all-NaN input -> ``(nan, None)``.

    ``t`` is the matching time axis (seconds), required by a ``needs_time`` op
    (e.g. ``integral``) and ignored by the others; the glue
    (:func:`core.metrics_compute._window_value`) slices it from ``ctx.time``.
    """
    a = np.asarray(arr, dtype=float)
    if a.size == 0 or not np.isfinite(a).any():
        return float("nan"), None
    return SCALAR_OPS[op](a, t)


def cop_op(op, cop_ap, cop_ml, fs):
    """Compute a COP composite ``op`` from a plate's AP/ML over a window.

    Reuses :func:`compute_metrics` (one key) so the math is identical to the old
    panel. Returns ``(value, unit)``; ``(nan, "")`` if the op/key is unknown.
    """
    key = COP_OPS.get(op)
    if key is None:
        return float("nan"), ""
    res = compute_metrics(cop_ap, cop_ml, fs, [key])
    return res.get(key, (float("nan"), ""))


def compute_ellipse_points(cop_ap, cop_ml, confidence=0.95, n_pts=300):
    """Returns (ell_ml, ell_ap) arrays for plotting (x=ML, y=AP).

    NaN-safe: occluded/gap samples are dropped before the covariance so a single
    missing frame does not collapse the whole ellipse to NaN (this matches the
    nanmean-based "95% Ellipse area" metric in :func:`compute_metrics`). With no
    NaN the result is bit-for-bit identical to the old version. An empty / single
    finite sample yields an empty pair (nothing to draw)."""
    ap = np.array(cop_ap, dtype=float)
    ml = np.array(cop_ml, dtype=float)
    # Keep only frames finite in BOTH channels so the covariance is well-defined.
    good = np.isfinite(ap) & np.isfinite(ml)
    if int(good.sum()) < 2:
        return np.empty(0), np.empty(0)
    ap = ap[good]
    ml = ml[good]
    ap_c = ap - np.mean(ap)
    ml_c = ml - np.mean(ml)

    # Shared geometry (see _cop_ellipse): eigvals ascending in [ML, AP] space,
    # eigvecs columns are the matching principal-axis directions, chi2 critical.
    eigvals, eigvecs, chi2_val = _cop_ellipse(ap_c, ml_c, confidence)
    a = np.sqrt(chi2_val * eigvals[1])   # major semi-axis
    b = np.sqrt(chi2_val * eigvals[0])   # minor semi-axis

    # Rotation angle of major eigenvector from ML-axis
    angle = np.arctan2(eigvecs[1, 1], eigvecs[0, 1])

    theta = np.linspace(0, 2 * np.pi, n_pts)
    x = a * np.cos(theta)
    y = b * np.sin(theta)

    cos_a, sin_a = np.cos(angle), np.sin(angle)
    x_rot = cos_a * x - sin_a * y
    y_rot = sin_a * x + cos_a * y

    return x_rot + np.mean(ml), y_rot + np.mean(ap)
