"""Event detection — turn a signal's *values* into the frame indices where
something happens.

A :class:`FilterStep` (core.pipeline) makes processed *signals*; the parallel
:class:`DetectEventStep` (also core.pipeline) makes *events*. This module owns
the underlying detection MATH so it stays pure / UI-free / numpy and is
headless-testable: every detector takes a plain 1-D value array and returns an
``np.ndarray`` of integer frame indices — *all* matching instances, not just the
first (that single-instance pick was the old ``analyze_tab._detect_event``
behaviour).

Key design point (C2, user-confirmed 2026-06-23): detection is on the **edge**
(the moment a signal crosses a level), not the level itself. Standing on the
plate keeps Fz above threshold the whole time, so there is no crossing => zero
events — which is what we want for gait events. Use :func:`detect_threshold_crossings`
for that. ``min_distance`` (a refractory window, in frames) and ``hysteresis``
(a dual-threshold band) suppress chatter near the threshold.

The detectors find *every* instance; a separate :func:`select_instances` then
picks first / Nth / a range / all — "detect-all-then-pick", so the same detected
set can feed both a single range endpoint (pick instance N) and cycle
segmentation later.

Scope (limit the search to a sub-window): pass ``scope=(start_idx, end_idx)``
(inclusive). It is applied by slicing the values, then the returned indices are
shifted back to the full-array frame numbering, so callers always get absolute
frame indices regardless of scope.
"""

import numpy as np
from scipy.signal import find_peaks


def _resolve_scope(n, scope):
    """Clamp ``scope`` to ``[0, n-1]`` (inclusive). ``None`` => whole array.

    Returns ``(start, end)`` with ``start <= end``; swaps a reversed scope so
    callers don't have to pre-order the endpoints.
    """
    if scope is None:
        return 0, n - 1
    start, end = scope
    start = int(start)
    end = int(end)
    if end < start:
        start, end = end, start
    start = max(0, min(start, n - 1))
    end = max(0, min(end, n - 1))
    return start, end


def _enforce_min_distance(indices, min_distance):
    """Drop indices closer than ``min_distance`` frames to the kept previous one.

    Greedy left-to-right (the same model as a refractory period): the first
    instance is always kept, then any instance within ``min_distance`` of the
    last kept one is dropped. ``indices`` must be sorted ascending.
    """
    if min_distance is None or min_distance <= 0 or len(indices) == 0:
        return indices
    kept = [int(indices[0])]
    for idx in indices[1:]:
        if int(idx) - kept[-1] >= min_distance:
            kept.append(int(idx))
    return np.asarray(kept, dtype=int)


def detect_threshold_crossings(values, threshold, direction="rising",
                               min_distance=None, hysteresis=None, scope=None):
    """Frame indices where ``values`` *crosses* ``threshold`` (edge, not level).

    A rising crossing is a frame ``i`` where the signal was below the threshold
    at ``i-1`` and is at/above it at ``i`` (the index returned is the first frame
    on the new side). ``direction``:
      - ``"rising"``  — below -> at/above (e.g. heel-strike as Fz climbs past 20 N)
      - ``"falling"`` — above -> below (e.g. toe-off as Fz drops past 20 N)

    Because this looks for transitions, a signal that stays above the threshold
    the whole time (standing on the plate) yields **zero** crossings.

    ``min_distance`` (frames): a refractory window — crossings closer than this
    to the previous kept one are dropped (chatter from a single noisy crossing).
    ``hysteresis`` (same units as the signal): a dual-threshold band. A rising
    crossing only counts once the signal first dropped below ``threshold -
    hysteresis`` since the last crossing (and symmetrically for falling); this
    rejects wobble that re-crosses the line without a real excursion.

    ``scope=(start, end)`` limits the search (inclusive); returned indices are in
    full-array frame numbering. Returns an ascending ``np.ndarray`` of ints.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2:
        return np.empty(0, dtype=int)
    start, end = _resolve_scope(n, scope)
    if end - start < 1:
        return np.empty(0, dtype=int)
    seg = values[start:end + 1]

    if hysteresis is not None and hysteresis > 0:
        idx = _crossings_hysteresis(seg, float(threshold), direction, float(hysteresis))
    else:
        idx = _crossings_simple(seg, float(threshold), direction)
    idx = idx + start
    return _enforce_min_distance(idx, min_distance)


def _crossings_simple(seg, threshold, direction):
    """Vectorized edge detection on a contiguous segment (no hysteresis)."""
    above = seg >= threshold
    if direction == "rising":
        # i where above[i] and not above[i-1]
        edge = above[1:] & ~above[:-1]
    elif direction == "falling":
        edge = ~above[1:] & above[:-1]
    else:
        raise ValueError(f"unknown crossing direction: {direction!r}")
    return np.flatnonzero(edge) + 1


def _crossings_hysteresis(seg, threshold, direction, hysteresis):
    """Edge detection with a dual-threshold band (state machine, frame loop).

    Hysteresis is inherently sequential (the next valid crossing depends on
    whether the signal first re-armed past the opposite band), so this is the one
    detector that walks frames. The array is small (one trial), so it is cheap.
    """
    if direction == "rising":
        hi, lo = threshold, threshold - hysteresis
        out = []
        armed = seg[0] < lo  # ready to fire a rising crossing
        for i in range(1, len(seg)):
            if armed and seg[i] >= hi:
                out.append(i)
                armed = False
            elif not armed and seg[i] < lo:
                armed = True
        return np.asarray(out, dtype=int)
    if direction == "falling":
        hi, lo = threshold + hysteresis, threshold
        out = []
        armed = seg[0] > hi
        for i in range(1, len(seg)):
            if armed and seg[i] <= lo:
                out.append(i)
                armed = False
            elif not armed and seg[i] > hi:
                armed = True
        return np.asarray(out, dtype=int)
    raise ValueError(f"unknown crossing direction: {direction!r}")


def detect_peaks(values, kind="max", min_distance=None, prominence=None,
                 scope=None):
    """Frame indices of local extrema (``kind="max"`` peaks or ``"min"`` valleys).

    Thin wrapper over scipy ``find_peaks``: ``min_distance`` maps to its
    ``distance`` (frames between peaks) and ``prominence`` to its ``prominence``
    (how much a peak stands out). For ``kind="min"`` the signal is negated so
    valleys become peaks. ``scope`` works as in :func:`detect_threshold_crossings`.
    Returns an ascending ``np.ndarray`` of ints.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return np.empty(0, dtype=int)
    start, end = _resolve_scope(n, scope)
    seg = values[start:end + 1]
    if kind == "max":
        sig = seg
    elif kind == "min":
        sig = -seg
    else:
        raise ValueError(f"unknown peak kind: {kind!r}")
    kwargs = {}
    if min_distance is not None and min_distance > 0:
        # scipy requires distance >= 1.
        kwargs["distance"] = max(1, int(min_distance))
    if prominence is not None and prominence > 0:
        kwargs["prominence"] = float(prominence)
    peaks, _ = find_peaks(sig, **kwargs)
    return peaks.astype(int) + start


def detect_global_extreme(values, kind="max", scope=None):
    """Frame index of the single GLOBAL extremum (the one highest/lowest point).

    Unlike :func:`detect_peaks` (LOCAL extrema — every peak/valley, possibly
    many), this returns the *one* frame where the signal reaches its overall
    maximum (``kind="max"``) or minimum (``kind="min"``) within the optional
    ``scope`` window. Researcher-pinned to match Visual3D: ``Event_Maximum`` is
    local (our ``peak``), whereas the single global extreme is
    ``Event_Global_Maximum/Minimum`` — used for things like "the one
    peak-flexion frame" that a later Metric/Detect step references.

    NaN-safe: uses ``nanargmax``/``nanargmin`` so NaN gaps are ignored. Returns a
    length-1 ``np.ndarray`` of ints (the absolute frame index, in full-array
    numbering even under ``scope``), or an EMPTY array when there is nothing to
    pick (empty input, or every value in the window is NaN). ``scope`` works as in
    :func:`detect_threshold_crossings`.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return np.empty(0, dtype=int)
    start, end = _resolve_scope(n, scope)
    seg = values[start:end + 1]
    if seg.size == 0 or np.all(np.isnan(seg)):
        return np.empty(0, dtype=int)
    if kind == "max":
        rel = int(np.nanargmax(seg))
    elif kind == "min":
        rel = int(np.nanargmin(seg))
    else:
        raise ValueError(f"unknown extreme kind: {kind!r}")
    return np.asarray([rel + start], dtype=int)


def detect_zero_crossings(values, direction="both", scope=None):
    """Frame indices where ``values`` crosses zero.

    ``direction``: ``"up"`` (negative -> non-negative), ``"down"`` (positive ->
    non-positive), or ``"both"``. Convenience built on
    :func:`detect_threshold_crossings` with ``threshold=0``. Returns an ascending
    ``np.ndarray`` of ints.
    """
    if direction == "up":
        return detect_threshold_crossings(values, 0.0, "rising", scope=scope)
    if direction == "down":
        return detect_threshold_crossings(values, 0.0, "falling", scope=scope)
    if direction == "both":
        up = detect_threshold_crossings(values, 0.0, "rising", scope=scope)
        down = detect_threshold_crossings(values, 0.0, "falling", scope=scope)
        return np.unique(np.concatenate([up, down])).astype(int)
    raise ValueError(f"unknown zero-cross direction: {direction!r}")


def detect_at_frame(n_frames, frame):
    """A single, fixed-frame "event": the manual pin as a degenerate detector.

    The unified event model (2026-06-23, user-confirmed) treats a hand-placed
    "fixed frame" event as just another detection *method* — so the pipeline can
    carry it next to threshold/peak/zero. There is no signal to look at: the
    instance is the frame the user typed. ``frame`` is a 0-based index; it is
    clamped into ``[0, n_frames-1]`` so an out-of-range pin lands on the nearest
    valid frame rather than vanishing or erroring. ``n_frames <= 0`` (no clock)
    yields an empty result. Always returns an ``np.ndarray`` of ints (one
    instance, or empty), so callers treat it like every other detector.
    """
    n = int(n_frames)
    if n <= 0:
        return np.empty(0, dtype=int)
    f = max(0, min(int(frame), n - 1))
    return np.asarray([f], dtype=int)


def select_instances(indices, mode="first", n=None, lo=None, hi=None):
    """Pick a subset of detected instances.

    ``indices`` is a sorted array of detected frame indices. ``mode``:
      - ``"first"`` — the first instance (the old single-instance behaviour).
      - ``"nth"``   — the ``n``-th instance, **1-based** (n=1 == first). A
        negative ``n`` counts from the end (n=-1 == last). Out of range => empty.
      - ``"range"`` — instances ``lo..hi`` inclusive, **1-based** ordinals (not
        frame numbers); ``lo``/``hi`` clamp to the available count, ``None`` means
        open-ended.
      - ``"all"``   — every instance.
    Always returns an ``np.ndarray`` of ints (possibly empty), so callers can
    treat the result uniformly.
    """
    indices = np.asarray(indices, dtype=int)
    count = len(indices)
    if mode == "all":
        return indices
    if count == 0:
        return np.empty(0, dtype=int)
    if mode == "first":
        return indices[:1]
    if mode == "nth":
        if n is None:
            raise ValueError("mode 'nth' needs n")
        i = int(n)
        if i > 0:
            i -= 1  # 1-based -> 0-based
        # negative n already indexes from the end (n=-1 -> last); leave as-is.
        if -count <= i < count:
            i_abs = i + count if i < 0 else i  # normalise so the slice never wraps
            return indices[i_abs:i_abs + 1]
        return np.empty(0, dtype=int)
    if mode == "range":
        a = 1 if lo is None else int(lo)
        b = count if hi is None else int(hi)
        a = max(1, a)
        b = min(count, b)
        if a > b:
            return np.empty(0, dtype=int)
        return indices[a - 1:b]
    raise ValueError(f"unknown selector mode: {mode!r}")
