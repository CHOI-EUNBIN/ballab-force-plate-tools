"""Signal-math building blocks — pure-numpy, NaN-safe operators that turn one
signal (1-D over time) into another signal or a scalar.

This is the "Signal Math" layer of the Visual3D-style two-layer model (the other
layer being Metric = signal->scalar, in :mod:`core.metrics`). A :class:`ComputeStep`
with ``method`` in {derivative, integral, magnitude} dispatches into here; the
glue passes the time axis where a method needs it (``needs_time``). Everything is
UI-free numpy (scipy is allowed — :mod:`core.metrics` already uses it).

Conventions shared with the rest of ``core``:
  * NaN-safe: an occluded/gap sample (NaN) must not poison the whole signal. Each
    op documents how it treats NaN (interpolate-through vs propagate-locally).
  * Vectorized: numpy operations, no Python ``for`` loops over samples.
  * Non-uniform time: every op takes the actual ``t`` array (seconds), never an
    assumed constant dt, so a variable-rate clock is handled correctly.

BIOMECH-VERIFY FLAGS (conventions biomech must confirm in Round B — see
``docs/biomech-metric-catalog.md`` open decisions):
  * Derivative endpoint rule (forward/backward vs central) — see :func:`derivative`.
  * Integral sign gating for braking/propulsive (AP forward = +) — see :func:`integral`.
  * Unit-derivation table (deg->deg/s, N->N*s) — see :func:`derive_unit`.
"""

import numpy as np
from scipy.integrate import cumulative_trapezoid, trapezoid


def _as_float(arr):
    """View ``arr`` as a contiguous float64 ndarray (copy only if needed)."""
    return np.asarray(arr, dtype=float)


def _interp_nan(y):
    """Linearly interpolate over interior NaNs so a gradient/integral isn't
    poisoned by one gap. Leading/trailing NaNs (no two finite neighbours to
    bridge) are left as-is. Returns a copy; the original is untouched.

    With no NaN this returns an unchanged copy (the math below is then identical
    to operating on the raw array).
    """
    y = _as_float(y).copy()
    finite = np.isfinite(y)
    if finite.all() or not finite.any():
        return y
    idx = np.arange(y.size)
    # np.interp clamps to the first/last finite value outside the finite span;
    # that is acceptable here (a derivative/integral over a clamped edge is the
    # most graceful fallback and matches "ignore the gap" intent).
    y[~finite] = np.interp(idx[~finite], idx[finite], y[finite])
    return y


def derivative(y, t, order=1):
    """Time derivative of signal ``y`` sampled at times ``t`` (seconds).

    Uses :func:`numpy.gradient`, which applies a **second-order central
    difference in the interior** and a **first-order one-sided (forward at the
    start / backward at the end) difference at the endpoints**, on the *actual*
    (possibly non-uniform) ``t`` spacing. ``order=2`` differentiates twice
    (=> acceleration). NaN-safe: interior gaps are linearly interpolated before
    differencing (a derivative is meaningless across a raw NaN).

    Parameters
    ----------
    y : array_like, shape (N,)
        The signal samples.
    t : array_like, shape (N,)
        Sample times in seconds (need not be uniformly spaced).
    order : int, default 1
        1 = velocity (dy/dt), 2 = acceleration (d2y/dt2). Applied by repeated
        first-derivative passes, so order>=2 inherits the same endpoint rule.

    Returns
    -------
    ndarray, shape (N,)
        The derivative, same length as ``y``.

    Endpoint note (BIOMECH-VERIFY): Visual3D's First_Derivative is a pure central
    difference; ``np.gradient`` matches it in the interior and adds a documented
    one-sided rule at the two endpoints (V3D's endpoint handling is undocumented).
    For peak angular velocity/acceleration the extremum is essentially never at a
    raw endpoint, so this difference is immaterial in practice.
    """
    t = _as_float(t)
    out = _interp_nan(y)
    if out.size < 2:
        return np.zeros_like(out)
    for _ in range(max(1, int(order))):
        out = np.gradient(out, t)
    return out


def integral(y, t, kind="cumulative", sign="all"):
    """Time integral of ``y`` over ``t`` (seconds) — trapezoidal.

    Two shapes, selected by ``kind``:
      * ``"cumulative"`` -> a *signal* (running integral, same length as ``y``,
        first sample 0) via SciPy ``cumulative_trapezoid``. This is the
        "indefinite integral" / curve form (e.g. impulse-so-far).
      * ``"total"`` -> a *scalar* (the definite integral over the whole span),
        the trapezoidal area. This is the impulse / area form used by a
        scalar Metric op.

    ``sign`` gates which part of the signal contributes (for braking vs
    propulsive impulse): ``"all"`` (everything), ``"pos"`` (only ``y>0``), or
    ``"neg"`` (only ``y<0``). Gating zeroes the excluded samples *before*
    integrating, so a sample of the wrong sign contributes nothing.

    NaN-safe: interior gaps are interpolated before integrating.

    Sign convention (BIOMECH-VERIFY): the pos/neg split assumes the signal's
    physical positive direction is the one you want as "propulsive" (for AP GRF,
    forward = +). The AP axis is plate-local here; biomech must verify the sign
    against the c3d force convention before naming braking/propulsive metrics.
    """
    t = _as_float(t)
    y = _interp_nan(y)
    if sign == "pos":
        y = np.where(y > 0, y, 0.0)
    elif sign == "neg":
        y = np.where(y < 0, y, 0.0)
    if y.size < 2:
        return (np.zeros_like(y) if kind == "cumulative" else 0.0)
    if kind == "total":
        return float(trapezoid(y, t))
    # cumulative: prepend 0 so the running integral starts at 0 and keeps length N.
    return cumulative_trapezoid(y, t, initial=0.0)


def magnitude(*comps):
    """Euclidean magnitude (resultant) of 2 or 3 component signals.

    ``magnitude(x, y)`` -> ``sqrt(x^2 + y^2)``; ``magnitude(x, y, z)`` ->
    ``sqrt(x^2 + y^2 + z^2)``. All components must share a length. Element-wise,
    so the result is a signal of the same length. NaN-safe per element: any NaN
    component at a sample makes that sample's magnitude NaN (a missing component
    means an undefined resultant there — we do NOT silently treat it as 0).

    Use for resultant GRF ``magnitude(fx, fy, fz)``, marker speed from velocity
    components, stride length from AP/ML displacement, etc.
    """
    if not comps:
        raise ValueError("magnitude needs at least one component")
    arrs = [_as_float(c) for c in comps]
    n = arrs[0].size
    for a in arrs:
        if a.size != n:
            raise ValueError("magnitude components must be the same length")
    sq = np.zeros(n, dtype=float)
    for a in arrs:
        sq = sq + a * a
    return np.sqrt(sq)


def absval(y):
    """Element-wise absolute value (NaN passes through). A signal->signal op,
    e.g. for rectifying a bipolar signal before a magnitude/integral. (P4 helper.)
    """
    return np.abs(_as_float(y))


#: Standard gravity (m/s^2) — for the XCOM inverted-pendulum constant. Matches
#: ``core.metrics.G`` / ``core.run.G`` so every g in the app is the same.
G = 9.80665


def xcom(y, t, length_m=None, g=G):
    """Extrapolated centre of mass (XCOM, Hof et al. 2005) of a COM position axis.

    XCOM(t) = y(t) + v(t) / w0, with the inverted-pendulum eigenfrequency
    w0 = sqrt(g / L); equivalently XCOM = y + v * sqrt(L / g). ``y`` is one COM
    position axis (any length unit — typically mm), ``v`` is its time derivative
    (computed internally via :func:`derivative`, so the SAME, possibly non-uniform,
    time axis is honoured and NaN gaps are interpolated). ``length_m`` is the
    pendulum length L in METRES (typically the COM height); ``g`` defaults to
    standard gravity.

    The XCOM keeps ``y``'s unit (a velocity ÷ w0 has the dimension of length:
    [L/T] / [1/T] = [L]). Returns an all-NaN array (never a guessed value) when
    ``length_m`` is missing or non-positive — the pendulum length is a physical
    input the caller must supply, not something to invent.

    Reference: Hof AL, Gazendam MGJ, Sinke WE (2005) "The condition for dynamic
    stability." J Biomech 38(1):1-8 — the XCOM/Margin-of-Stability framework.
    """
    y = _as_float(y)
    if length_m is None or not np.isfinite(length_m) or float(length_m) <= 0 \
            or g is None or float(g) <= 0:
        return np.full(y.shape, np.nan)
    v = derivative(y, t, order=1)
    return y + v * np.sqrt(float(length_m) / float(g))


def power(y, exponent=2.0):
    """Element-wise power ``y**exponent`` (NaN passes through). ``exponent=0.5``
    = square root. A signal->signal op for shaping a signal. (P4 helper.)
    """
    return np.power(_as_float(y), float(exponent))


# ---------------------------------------------------------------------------
# Unit tracking — when a ComputeStep derives a new signal, its unit changes in a
# known way (a time derivative divides by seconds, a time integral multiplies by
# seconds, a magnitude preserves the component unit). This small table lets the
# produced signal carry a correct unit string instead of an empty/guessed one.

#: Per-method unit transform applied to the base (input) unit string. Each entry
#: is a callable ``base_unit -> derived_unit``. BIOMECH-VERIFY: the exact unit
#: spelling/convention (e.g. "deg/s" vs "deg.s^-1", "N*s" vs "N.s") is biomech's
#: to confirm; the *transform* (per-time, times-time, preserve) is what matters.
_UNIT_TRANSFORMS = {
    "normalize": lambda u: "",          # ratio (e.g. %BW) is dimensionless
    "magnitude": lambda u: u,           # resultant keeps the component unit
    "absval": lambda u: u,
    "xcom": lambda u: u,                # XCOM keeps the COM position unit (mm)
    "derivative": lambda u: _per_time(u, 1),
    "derivative2": lambda u: _per_time(u, 2),
    "integral": lambda u: _times_time(u),
}


def _per_time(unit, order=1):
    """``unit`` divided by seconds ``order`` times: "deg" -> "deg/s" -> "deg/s^2".

    An empty/unknown base unit yields "" (we don't invent a unit from nothing).
    """
    if not unit:
        return ""
    if order <= 0:
        return unit
    return f"{unit}/s" if order == 1 else f"{unit}/s^{order}"


def _times_time(unit):
    """``unit`` multiplied by seconds: "N" -> "N*s" (impulse), "" -> "s".

    An empty base unit becomes "s" (the integral of a dimensionless signal over
    time has units of seconds).
    """
    return f"{unit}*s" if unit else "s"


def derive_unit(base_unit, method, order=1):
    """Unit string a ComputeStep output carries, given its input ``base_unit``
    and ``method``. ``order`` selects derivative vs 2nd derivative for
    ``method="derivative"``. Unknown methods preserve the base unit (safe default).

    Examples: ``derive_unit("deg", "derivative")`` -> "deg/s";
    ``derive_unit("deg", "derivative", order=2)`` -> "deg/s^2";
    ``derive_unit("N", "integral")`` -> "N*s"; ``derive_unit("N", "magnitude")``
    -> "N". See :data:`_UNIT_TRANSFORMS` for the table (BIOMECH-VERIFY spelling).
    """
    base_unit = base_unit or ""
    if method == "derivative" and int(order) >= 2:
        return _UNIT_TRANSFORMS["derivative2"](base_unit)
    fn = _UNIT_TRANSFORMS.get(method)
    if fn is None:
        return base_unit
    return fn(base_unit)
