"""Time-normalization of signal epochs to 0-100% phase (pure / NaN-safe).

An *epoch* is one movement segment (a gait cycle, a discrete rep, or a whole
trial). Each epoch is resampled onto evenly spaced 0-100% phase nodes so epochs
of different durations become comparable and poolable (see core.ensemble).
"""
import numpy as np


def resample_to_percent(values, points=101):
    """Resample a 1-D epoch to ``points`` evenly spaced 0-100% phase nodes.

    Interior NaNs bounded by finite samples are linearly interpolated across;
    nodes outside the finite span (leading/trailing NaN) stay NaN (no
    extrapolation). ``n < 2`` finite samples -> all-NaN row.
    """
    v = np.asarray(values, float)
    out = np.full(points, np.nan)
    if v.size < 2:
        return out
    finite = np.isfinite(v)
    if finite.sum() < 2:
        return out
    src_x = np.linspace(0.0, 1.0, v.size)
    dst_x = np.linspace(0.0, 1.0, points)
    out = np.interp(dst_x, src_x[finite], v[finite])
    lo, hi = src_x[finite][0], src_x[finite][-1]
    out[(dst_x < lo) | (dst_x > hi)] = np.nan
    return out
