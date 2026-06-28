"""Time-normalization of signal epochs to 0-100% phase (pure / NaN-safe).

An *epoch* is one movement segment (a gait cycle, a discrete rep, or a whole
trial). Each epoch is resampled onto evenly spaced 0-100% phase nodes so epochs
of different durations become comparable and poolable (see core.ensemble).
"""
import numpy as np
from core.metrics_compute import cycles_from_events


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


def epoch_windows(time, events, mode, start_event=None, end_event=None):
    """Frame-index windows ``[(i0, i1), ...]`` for the chosen epoch mode.

    ``events`` = ``{label: frame ndarray}``.
      "cycle"  -> consecutive same event: pairs of ``events[start_event]``.
      "window" -> ``events[start_event][k]`` to the next ``events[end_event]`` after it.
      "trial"  -> one whole-trial window ``[0, len(time)-1]``.
    Empty / short inputs -> ``[]``.
    """
    n = len(np.asarray(time))
    if mode == "trial":
        return [(0, n - 1)] if n >= 2 else []
    if mode == "cycle":
        f = events.get(start_event)
        if f is None or len(f) < 2:
            return []
        return cycles_from_events(f, f)
    if mode == "window":
        s = events.get(start_event)
        e = events.get(end_event)
        if s is None or e is None or len(s) == 0 or len(e) == 0:
            return []
        return cycles_from_events(s, e)
    return []


def extract_epochs(values, windows, points=101):
    """``(matrix[N, points], meta)`` resampling ``values[i0:i1+1]`` per window.

    Windows shorter than 2 samples are skipped. ``meta`` = list of
    ``{"start": i0, "end": i1}`` aligned with the matrix rows.
    """
    v = np.asarray(values, float)
    rows, meta = [], []
    for (i0, i1) in windows:
        seg = v[i0:i1 + 1]
        if seg.size < 2:
            continue
        # A window end past the array is silently clipped by the slice; report the
        # REAL last index (i0 + seg.size - 1), not the requested i1, so downstream
        # labels can't mismatch the actual data.
        real_end = int(i0) + int(seg.size) - 1
        rows.append(resample_to_percent(seg, points))
        meta.append({"start": int(i0), "end": real_end})
    matrix = np.vstack(rows) if rows else np.empty((0, points))
    return matrix, meta
