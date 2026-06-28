"""Per-file metric computation — the glue between a :class:`MetricStep` recipe
and a dataset's catalogs.

Kept separate from :mod:`core.metrics` (pure math / op registry) the same way
``events_compute`` is separate from ``events``: this module knows about the
execution context (signals/events catalogs, sampling rate) while ``metrics`` stays
a headless value-in / value-out library.

A metric step reduces one signal to a scalar via its ``op``, over a *segment*:
  * ``segment=None``  -> the whole trial (one value).
  * ``segment=[a,b]`` -> one value per cycle (each ``a`` event paired with the
    next ``b`` event after it), aggregated to mean ± SD over all cycles. This is
    what makes a 3-minute gait trial "per stride" without marking anything by hand.
"""

from collections import Counter

import numpy as np

from core import diagnostics
from core.metrics import (
    COP_OPS, EVENT_OPS, JUMP_OPS, OP_INFO, REFERENCE_OPS, SCALAR_OPS,
    cop_op, event_duration, jump_height_impulse, op_unit, scalar_op)
from core.pipeline import METRIC_PREFIX
from core.signals import unit_for

#: Scalar ops that differentiate over time and so need >= 2 valid samples in the
#: window; fewer -> :data:`core.diagnostics.WINDOW_TOO_SHORT` rather than a bogus
#: value. (``integral``/``impulse`` degrade to ~0 on a 1-sample window, which is
#: meaningful, so they are NOT here.)
_DERIV_OPS = {"peak_angular_velocity", "peak_angular_acceleration",
              "rfd", "loading_rate"}


def _unit(ctx, key):
    """Unit for a signal ``key`` — a ComputeStep-derived unit (tracked on the
    context) if present, else the static catalog unit. ``ctx.unit`` exists on the
    run context; older callers without it fall back to ``unit_for``."""
    fn = getattr(ctx, "unit", None)
    return fn(key) if fn is not None else unit_for(key)


def _op_unit(op, base_unit):
    """Unit a scalar op produces from a signal of unit ``base_unit``.

    Delegates to :func:`core.metrics.op_unit`, the single unit-transform table:
    ``impulse``/``integral`` multiply by time (N -> N*s); ``peak_angular_velocity``/
    ``rfd``/``loading_rate`` divide by time once (deg -> deg/s, N -> N/s);
    ``peak_angular_acceleration`` divides twice (deg -> deg/s^2); other ops keep
    the base unit.
    """
    return op_unit(op, base_unit)


def _cop_keys(input_key):
    """Map a plate COP key to its (ap_key, ml_key) pair.

    ``"fp1:cop"`` -> ``("fp1:cop_ap", "fp1:cop_ml")``; bare ``"cop"`` ->
    ``("cop_ap", "cop_ml")``. Returns ``None`` if ``input_key`` is not a COP key.
    """
    if input_key == "cop":
        return "cop_ap", "cop_ml"
    if input_key.endswith(":cop"):
        base = input_key[:-len(":cop")]
        return f"{base}:cop_ap", f"{base}:cop_ml"
    return None


def cycles_from_events(start_frames, end_frames):
    """Pair each ``start`` frame with the next ``end`` frame strictly after it.

    Returns a list of ``(start, end)`` index windows (ascending). Used for
    per-cycle segmentation: ``HS->HS`` (same label) gives consecutive strides,
    ``HS->TO`` gives each stance phase. NaN-safe / empty-safe.
    """
    s = np.unique(np.asarray(start_frames, dtype=int))
    e = np.sort(np.asarray(end_frames, dtype=int))
    out = []
    for st in s:
        after = e[e > st]
        if after.size:
            out.append((int(st), int(after[0])))
    return out


def _window_value(ctx, step, lo, hi):
    """Compute the op over the half-open frame window ``[lo, hi]`` (inclusive hi).

    Returns ``(value, unit, arg_frame|None, reason|None)`` where ``arg_frame`` is
    the absolute master-clock frame of a min/max extremum (else ``None``) and
    ``reason`` is a :mod:`core.diagnostics` code explaining a NaN result (``None``
    when the value is valid). A reason of ``NO_SIGNAL`` covers any unresolvable
    input (no model angle / no markers / absent plate / failed Compute output):
    every signal read is wrapped so one missing input can't crash the run."""
    op = step.op
    info = OP_INFO.get(op)
    if info is None:
        # Unknown op (a misconfigured / forward-version step): degrade to NaN with
        # a reason rather than raising, so one bad step can't break the whole run.
        # The UI only offers ops from OP_INFO, so this is purely a safety net for
        # hand-built / migrated recipes.
        return float("nan"), "", None, diagnostics.UNKNOWN_OP
    kind = info.get("input")
    try:
        if kind == "cop":
            keys = _cop_keys(step.input)
            if keys is None:
                return float("nan"), "", None, diagnostics.NOT_COP
            ap = np.asarray(ctx.signal(keys[0]), dtype=float)[lo:hi + 1]
            ml = np.asarray(ctx.signal(keys[1]), dtype=float)[lo:hi + 1]
            val, unit = cop_op(op, ap, ml, ctx.fs)
            reason = None
            if not np.isfinite(val):
                fin = np.isfinite(ap) & np.isfinite(ml)
                reason = (diagnostics.WINDOW_TOO_SHORT if fin.any()
                          else diagnostics.WINDOW_ALL_NAN)
            return val, unit, None, reason
        if kind == "sample":   # value_at_event: read input at the event frame
            sig = np.asarray(ctx.signal(step.input), dtype=float)
            unit = _unit(ctx, step.input)
            frames = ctx.event(step.event)
            if frames is None or len(frames) == 0:
                return float("nan"), unit, None, diagnostics.NO_EVENT_INSTANCES
            frames = np.asarray(frames, dtype=int)
            # Per-cycle segment: read the event INSTANCE inside THIS cycle's window
            # [lo, hi]. Without a segment (whole-trial) keep the first instance.
            if step.segment:
                inside = frames[(frames >= lo) & (frames <= hi)]
                if inside.size == 0:
                    return float("nan"), unit, None, diagnostics.NO_EVENT_INSTANCES
                f = int(inside[0])
            else:
                f = int(frames[0])
            if not (0 <= f < sig.size):
                return float("nan"), unit, None, diagnostics.NO_EVENT_INSTANCES
            v = float(sig[f])
            reason = None if np.isfinite(v) else diagnostics.WINDOW_ALL_NAN
            return v, unit, None, reason
        if kind == "event":
            # Spatiotemporal op: the metric is the DURATION of the per-cycle window
            # [lo, hi] (paired from the segment's two event labels). No signal input
            # — the segment IS the input — so a step with no segment is meaningless.
            dur_kind, post, unit = EVENT_OPS[op]
            if not step.segment:
                return float("nan"), unit, None, diagnostics.NO_SEGMENT
            dur = event_duration(lo, hi, ctx.fs, t=ctx.time, kind=dur_kind)
            val = float(post(dur) if post is not None else dur)
            reason = None if np.isfinite(val) else diagnostics.NO_CYCLES
            return val, unit, None, reason
        if kind == "jump":
            # Impulse-momentum jump op: integrate (Fz - body weight) over the
            # window and convert net impulse to height / takeoff velocity. Needs the
            # subject mass (from the metric catalog, like a normalize ref).
            idx, unit = JUMP_OPS[op]
            mass = ctx.metric("mass")
            if not mass:
                return float("nan"), unit, None, diagnostics.NO_MASS
            fz = np.asarray(ctx.signal(step.input), dtype=float)[lo:hi + 1]
            t = np.asarray(ctx.time, dtype=float)[lo:hi + 1]
            weight = ctx.metric("bodyweight")
            out = jump_height_impulse(fz, t, mass, weight=weight)
            val = float(out[idx])
            reason = None if np.isfinite(val) else diagnostics.WINDOW_TOO_SHORT
            return val, unit, None, reason
        if kind == "displacement":
            # signal[hi] - signal[lo] over the per-cycle event window. A whole-trial
            # fallback (no segment) is meaningless here.
            unit = _unit(ctx, step.input)
            if not step.segment:
                return float("nan"), unit, None, diagnostics.NO_SEGMENT
            sig = np.asarray(ctx.signal(step.input), dtype=float)
            if not (0 <= lo < sig.size and 0 <= hi < sig.size):
                return float("nan"), unit, None, diagnostics.NO_CYCLES
            val = float(sig[hi] - sig[lo])
            reason = None if np.isfinite(val) else diagnostics.WINDOW_ALL_NAN
            return val, unit, None, reason
        # scalar op (may also need the time axis for needs_time ops, e.g. integral)
        arr = np.asarray(ctx.signal(step.input), dtype=float)[lo:hi + 1]
        base_unit = _unit(ctx, step.input)
        finite = np.isfinite(arr)
        if not finite.any():
            return float("nan"), base_unit, None, diagnostics.WINDOW_ALL_NAN
        if op in _DERIV_OPS and int(np.count_nonzero(finite)) < 2:
            return float("nan"), base_unit, None, diagnostics.WINDOW_TOO_SHORT
        if info.get("needs_time"):
            t = np.asarray(ctx.time, dtype=float)[lo:hi + 1]
            val, arg = scalar_op(op, arr, t=t)
        else:
            val, arg = scalar_op(op, arr)
        frame = (lo + arg) if arg is not None else None
        reason = None if np.isfinite(val) else diagnostics.WINDOW_ALL_NAN
        return val, _op_unit(op, base_unit), frame, reason
    except ValueError:
        # Any unresolvable signal input (Workspace.series raises ValueError):
        # no model angle / no markers / absent force plate / failed Compute output.
        return float("nan"), _unit(ctx, step.input), None, diagnostics.NO_SIGNAL


def _metric_ref(ctx, ref):
    """Resolve a ``metric:<name>`` (or bare ``<name>``) reference to its scalar
    value via the context, or ``None`` if absent."""
    if not ref:
        return None
    name = ref[len(METRIC_PREFIX):] if ref.startswith(METRIC_PREFIX) else ref
    return ctx.metric(name)


def _finite_ref(ctx, ref):
    """A reference op input as a finite float, or ``None`` when the cited metric is
    absent OR present-but-not-finite (so the caller reports NO_REFERENCE)."""
    v = _metric_ref(ctx, ref)
    if v is None:
        return None
    v = float(v)
    return v if np.isfinite(v) else None


def _fmt_ctx(step, n_ok, m_total):
    """Format context for :func:`core.diagnostics.message_for` — the step's input/
    event/op plus the computed/total cycle counts."""
    seg = step.segment or []
    return {
        "input": step.input, "input2": getattr(step, "input2", "") or "",
        "event": getattr(step, "event", "") or "", "op": step.op,
        "n": int(n_ok), "m": int(m_total),
        "seg0": seg[0] if len(seg) > 0 else "",
        "seg1": seg[1] if len(seg) > 1 else "",
    }


def _dominant(reasons):
    """The most common reason code in ``reasons`` (first-seen on ties), or ``None``."""
    return Counter(reasons).most_common(1)[0][0] if reasons else None


def _status_block(step, n_ok, m_total, reasons, fell_back):
    """(status, reason, message) for a windowed metric from its per-window outcome.

      * ``n_ok == 0``      -> UNAVAILABLE, with the dominant failure reason.
      * whole-trial fallback (segment had no cycles, scalar op coped) -> PARTIAL.
      * some-but-not-all cycles computed -> PARTIAL ("computed N of M cycles" +
        the dominant per-cycle failure reason).
      * all cycles computed -> OK (empty reason/message).
    """
    fmt = _fmt_ctx(step, n_ok, m_total)
    if n_ok == 0:
        reason = _dominant(reasons) or diagnostics.NO_CYCLES
        return diagnostics.UNAVAILABLE, reason, diagnostics.message_for(reason, **fmt)
    if fell_back:
        r = diagnostics.WHOLE_TRIAL_FALLBACK
        return diagnostics.PARTIAL, r, diagnostics.message_for(r, **fmt)
    if n_ok < m_total:
        r = diagnostics.PARTIAL_CYCLES
        msg = diagnostics.message_for(r, **fmt)
        detail = diagnostics.message_for(_dominant(reasons), **fmt)
        if detail:
            msg = f"{msg} {detail}"
        return diagnostics.PARTIAL, r, msg
    return diagnostics.OK, "", ""


#: Reference ops with a per-STRIDE meaning: instead of one scalar from the input
#: METRICS' means, apply the op element-wise across the inputs' per-cycle arrays
#: so the result carries raw per-cycle values + mean±SD (user wants the raw data,
#: not just an average). ``cadence``/``cadence_stride`` map one per-cycle time
#: array; ``stance_pct``/``swing_pct``/``product``/``quotient`` map two aligned
#: per-cycle arrays. (``symmetry_*`` compare L vs R limbs — no per-stride pairing
#: here — and ``cv`` is already an array reducer, so both stay scalar.)
_PER_CYCLE_REFERENCE = {"cadence", "cadence_stride", "stance_pct", "swing_pct",
                        "product", "quotient"}


def _reference_cycle_arrays(ctx, step, n_inputs):
    """The per-cycle arrays of a reference op's input metric(s), or ``None``.

    Returns a tuple of equal-length float arrays (one per input) when every
    referenced metric has a per-cycle array AND, for binary ops, the two arrays
    align in length; otherwise ``None`` so the caller falls back to the scalar
    (mean-based) path."""
    def cyc(ref):
        if not ref:
            return None
        nm = ref[len(METRIC_PREFIX):] if ref.startswith(METRIC_PREFIX) else ref
        arr = ctx.metric_cycles(nm)
        return None if arr is None else np.asarray(arr, dtype=float)
    a = cyc(step.input)
    if a is None or a.size == 0:
        return None
    if n_inputs == 1:
        return (a,)
    b = cyc(step.input2)
    if b is None or b.shape != a.shape:
        return None
    return (a, b)


def _reference_value(ctx, step):
    """Compute a reference op (cadence / stance% / RSI / symmetry / ratio / CV).

    Reads metric VALUES (``step.input`` and, for binary ops, ``step.input2``) from
    the context. Spatiotemporal/derived ops with a per-stride meaning (see
    :data:`_PER_CYCLE_REFERENCE`) are computed PER CYCLE from the inputs' per-cycle
    arrays, returning a ``cycles`` array + mean±SD (so the UI shows the raw
    distribution, not just an average). ``cv`` reads the per-cycle ARRAY of the
    cited metric. The rest return a scalar (``n=1``, ``cycles=None``)."""
    fn, n_inputs, unit = REFERENCE_OPS[step.op]
    if step.op in _PER_CYCLE_REFERENCE:
        arrs = _reference_cycle_arrays(ctx, step, n_inputs)
        if arrs is not None:
            cyc = np.array([fn(*vals) for vals in zip(*arrs)], dtype=float)
            finite = cyc[np.isfinite(cyc)]
            if finite.size:
                mean = float(np.mean(finite))
                sd = float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0
                status, reason, message = _status_block(
                    step, finite.size, cyc.size, [], fell_back=False)
                return {"name": step.name, "unit": unit, "value": mean,
                        "cycles": cyc.tolist(), "mean": mean, "sd": sd,
                        "n": int(finite.size), "event_frames": [],
                        "status": status, "reason": reason, "message": message}
        # else: fall through to the scalar (mean-based) path below.
    reason = None
    if step.op == "cv":
        # CV needs the per-cycle array of the referenced metric, not its mean.
        name = step.input[len(METRIC_PREFIX):] if step.input.startswith(METRIC_PREFIX) else step.input
        arr = ctx.metric_cycles(name)
        if arr is None:
            val, reason = float("nan"), diagnostics.NO_REFERENCE
        elif int(np.count_nonzero(np.isfinite(np.asarray(arr, float)))) < 2:
            val, reason = float("nan"), diagnostics.NEEDS_TWO_CYCLES
        else:
            val = float(fn(arr))
            if not np.isfinite(val):       # zero mean -> CV undefined
                reason = diagnostics.DIVIDE_BY_ZERO
    elif n_inputs == 2:
        a = _finite_ref(ctx, step.input)
        b = _finite_ref(ctx, step.input2)
        if a is None or b is None:
            val, reason = float("nan"), diagnostics.NO_REFERENCE
        elif step.op == "quotient" and b == 0:
            val, reason = float("nan"), diagnostics.DIVIDE_BY_ZERO
        else:
            val = float(fn(a, b))
            if not np.isfinite(val):       # e.g. zero denominator in ratio/%/RSI
                reason = diagnostics.DIVIDE_BY_ZERO
    else:
        a = _finite_ref(ctx, step.input)
        if a is None:
            val, reason = float("nan"), diagnostics.NO_REFERENCE
        else:
            val = float(fn(a))
            if not np.isfinite(val):
                reason = diagnostics.NO_REFERENCE
    val = float(val)
    finite = np.isfinite(val)
    if reason is None and finite:
        status, reason_code, message = diagnostics.OK, "", ""
    else:
        reason_code = reason or diagnostics.NO_REFERENCE
        status = diagnostics.UNAVAILABLE
        message = diagnostics.message_for(reason_code, **_fmt_ctx(step, 0, 1))
    return {"name": step.name, "unit": unit, "value": val, "cycles": None,
            "mean": val, "sd": 0.0, "n": 1 if finite else 0, "event_frames": [],
            "status": status, "reason": reason_code, "message": message}


def compute_metric_step(ctx, step):
    """Compute one :class:`MetricStep` against ``ctx``.

    Returns ``{"name", "unit", "value", "cycles", "mean", "sd", "n",
    "event_frames"}``. For ``segment=None`` -> ``n=1``, ``value==mean``,
    ``cycles=None``. For a per-cycle segment -> ``value=mean`` (the headline),
    ``cycles`` the per-cycle array, ``sd`` the cycle SD (ddof=1). ``event_frames``
    are the extremum frames a min/max op emits (one per cycle / window).
    """
    # Reference ops (Round B2): derive a scalar from already-computed metric
    # VALUES (cited via ``input``/``input2`` as ``metric:`` refs), not from a
    # signal window. cadence/stance%/RSI/symmetry/ratio/CV all live here. They run
    # AFTER the metrics they cite (single-pass executor), so the values are present
    # in the context. A missing/unresolvable ref -> NaN (graceful, never raises).
    if OP_INFO.get(step.op, {}).get("input") == "metric":
        return _reference_value(ctx, step)

    n_frames = len(ctx.time)
    seg_requested = bool(step.segment)
    windows = []
    if step.segment:
        a = ctx.event(step.segment[0])
        b = ctx.event(step.segment[1])
        windows = cycles_from_events(a if a is not None else [],
                                     b if b is not None else [])
    fell_back = False
    if not windows:                       # whole trial (or no cycles found)
        windows = [(0, n_frames - 1)] if n_frames else []
        # A segment WAS requested but produced no cycles -> we fell back to the
        # whole trial. Acceptable for scalar/COP/sample ops (flagged PARTIAL), but
        # meaningless for event/displacement ops (they need a real event pair).
        fell_back = seg_requested and bool(windows)

    kind = OP_INFO.get(step.op, {}).get("input")
    if fell_back and kind in ("event", "displacement"):
        message = diagnostics.message_for(diagnostics.NO_CYCLES,
                                          **_fmt_ctx(step, 0, 0))
        return {"name": step.name, "unit": "", "value": float("nan"),
                "cycles": None, "mean": float("nan"), "sd": 0.0, "n": 0,
                "event_frames": [], "status": diagnostics.UNAVAILABLE,
                "reason": diagnostics.NO_CYCLES, "message": message}

    vals, unit, frames, reasons = [], "", [], []
    for lo, hi in windows:
        if hi < lo:
            continue
        v, u, fr, rsn = _window_value(ctx, step, lo, hi)
        vals.append(v)
        unit = u or unit
        if fr is not None:
            frames.append(fr)
        if rsn is not None:
            reasons.append(rsn)
    arr = np.asarray(vals, dtype=float)
    finite = arr[np.isfinite(arr)]
    n_ok, m_total = int(finite.size), len(vals)
    mean = float(np.mean(finite)) if finite.size else float("nan")
    sd = float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0
    cyclic = bool(step.segment) and len(windows) > 1
    status, reason, message = _status_block(step, n_ok, m_total, reasons, fell_back)
    return {
        "name": step.name,
        "unit": unit,
        "value": mean,
        "cycles": arr if cyclic else None,
        "mean": mean,
        "sd": sd if cyclic else 0.0,
        "n": n_ok,
        "event_frames": frames,
        "status": status,
        "reason": reason,
        "message": message,
    }
