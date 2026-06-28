"""Kinematic gait events (G2) — heel-strike / toe-off from foot markers.

Treadmill trials have no clean per-foot ground-reaction edges to threshold, so
gait events come from the foot markers instead. This module implements the
Zeni et al. (2008) *coordinate* method (Gait & Posture 27(4):710-714), validated
for treadmill and overground walking:

  - Project a foot marker onto the AP (anterior-posterior / progression) axis,
    **relative to the pelvis origin** (removes belt-frame / body translation).
  - **HS** (heel strike) = the heel's most-ANTERIOR frame  -> a local MAXIMUM of
    the heel AP-relative series.
  - **TO** (toe off)      = the toe's most-POSTERIOR frame  -> a local MINIMUM of
    the toe AP-relative series.

This module is pure (NumPy only, no Qt, no dataset coupling): it takes a markers
dict (``{"labels", "data" (M,F,3), "time", "rate"}``) and returns plain arrays,
so the actual peak picking reuses :mod:`core.events` and the pipeline exposes the
projected series as ``gait:<SIDE>_<heel|toe>_ap`` signals (see
:func:`core.signals.signal_series`). :func:`split_stance_swing` turns detected
HS/TO frames into per-cycle stance/swing durations and percentages.

Design source: docs/pipeline-tomorrow-gaps.md §F.
"""

import numpy as np
from scipy.signal import find_peaks

#: Pelvis landmarks whose mean is the pelvis origin (Zeni's "sacrum" surrogate).
#: Any subset that is actually present is used; order is irrelevant to the mean.
PELVIS_MARKERS = ("RASIS", "LASIS", "RPSIS", "LPSIS", "SACR", "SACRUM")


def _marker_index(markers, label, label_map=None):
    """Index of ``label`` in the markers' label list, or ``None`` if absent.

    ``label_map`` (optional) maps a needed name -> the trial's actual label, so a
    model's reconstructed naming can be honoured; without it the label is matched
    directly (the common case for raw c3d labels like ``RHEEL``)."""
    actual = label_map.get(label, label) if label_map else label
    labels = markers["labels"]
    if actual in labels:
        return labels.index(actual)
    return None


def foot_marker_label(side, point):
    """The marker label for a side ("R"/"L") and point ("heel"/"toe").

    ``("R", "heel") -> "RHEEL"``, ``("L", "toe") -> "LTOE"``. The side prefix
    matches the bundled c3d convention; callers with other naming pass a
    ``label_map``."""
    side = str(side).upper()[:1]
    seg = "HEEL" if str(point).lower().startswith("h") else "TOE"
    return f"{side}{seg}"


def pelvis_origin(markers, label_map=None):
    """Pelvis origin trajectory ``(F, 3)`` = mean of the present pelvis markers.

    NaN-safe (a momentarily-occluded landmark is ignored for that frame via
    ``nanmean``). Raises ``ValueError`` when no pelvis marker is present (the
    method needs a body reference)."""
    data = markers["data"]
    pts = []
    for name in PELVIS_MARKERS:
        idx = _marker_index(markers, name, label_map)
        if idx is not None:
            pts.append(np.asarray(data[idx], dtype=float))
    if not pts:
        raise ValueError("no pelvis markers for gait progression reference")
    return np.nanmean(np.stack(pts, axis=0), axis=0)


def progression_axis(markers, side, label_map=None):
    """Auto-detect the (AP axis index, anterior sign) for ``side``.

    Heuristic grounded in the marker geometry (no lab-frame assumption):
      * The **vertical** axis is the one where the foot sits farthest from the
        pelvis (largest ``|mean(foot - pelvis)|`` — feet are well below the
        pelvis), and is excluded.
      * The **AP** axis is whichever of the remaining (horizontal) axes shows the
        largest foot excursion (range), since the foot swings fore-aft far more
        than side-to-side.
      * The **anterior sign** (+1/-1) is chosen so the TOE is on average ahead of
        the HEEL along +AP, making the series anterior-positive regardless of how
        the lab's axes are oriented.

    Returns ``(axis:int, sign:int)``."""
    heel_i = _marker_index(markers, foot_marker_label(side, "heel"), label_map)
    toe_i = _marker_index(markers, foot_marker_label(side, "toe"), label_map)
    if heel_i is None or toe_i is None:
        raise ValueError(f"missing heel/toe marker for side {side!r}")
    origin = pelvis_origin(markers, label_map)
    heel_rel = np.asarray(markers["data"][heel_i], dtype=float) - origin
    toe_rel = np.asarray(markers["data"][toe_i], dtype=float) - origin
    foot_rel = 0.5 * (heel_rel + toe_rel)
    vertical = int(np.argmax(np.abs(np.nanmean(foot_rel, axis=0))))
    rng = np.nanmax(foot_rel, axis=0) - np.nanmin(foot_rel, axis=0)
    horiz = [a for a in range(3) if a != vertical]
    ap = horiz[0] if rng[horiz[0]] >= rng[horiz[1]] else horiz[1]
    # Anterior-positive: orient so the toe leads the heel along +AP.
    sign = 1 if np.nanmean(toe_rel[:, ap]) >= np.nanmean(heel_rel[:, ap]) else -1
    return ap, sign


def foot_progression_series(markers, side, point="heel", label_map=None):
    """The AP-relative-to-pelvis series ``(F,)`` for one foot marker.

    Anterior-positive (see :func:`progression_axis`), so the HEEL series' maxima
    are heel-strikes and the TOE series' minima are toe-offs."""
    idx = _marker_index(markers, foot_marker_label(side, point), label_map)
    if idx is None:
        raise ValueError(f"missing {point} marker for side {side!r}")
    ap, sign = progression_axis(markers, side, label_map)
    origin = pelvis_origin(markers, label_map)
    rel = np.asarray(markers["data"][idx], dtype=float)[:, ap] - origin[:, ap]
    return sign * rel


def foot_lab_series(markers, side, point="heel", axis="ap", label_map=None):
    """A foot marker's LAB-frame coordinate (NOT pelvis-relative), (F,).

    ``axis="ap"`` = the progression axis, anterior-positive (so forward travel is
    positive); ``axis="ml"`` = the remaining horizontal (medio-lateral) axis,
    oriented by the same sign. Used for spatial gait variables (stride/step
    length, step width, and treadmill belt speed = its time-derivative)."""
    idx = _marker_index(markers, foot_marker_label(side, point), label_map)
    if idx is None:
        raise ValueError(f"missing {point} marker for side {side!r}")
    ap, sign = progression_axis(markers, side, label_map)
    if axis == "ap":
        col = ap
    elif axis == "ml":
        vertical = int(np.argmax(np.abs(np.nanmean(
            np.asarray(markers["data"][idx], dtype=float)
            - pelvis_origin(markers, label_map), axis=0))))
        col = [a for a in range(3) if a not in (ap, vertical)][0]
    else:
        raise ValueError(f"unknown axis: {axis!r}")
    return sign * np.asarray(markers["data"][idx], dtype=float)[:, col]


def _fill_nan(x):
    """Linearly interpolate interior NaNs (short occlusions) so a derivative is
    well-defined; leading/trailing NaNs are held at the nearest finite value.

    Differentiating across an occlusion gap would otherwise inject a spurious
    spike; gait markers are continuous, so a straight-line fill is the standard,
    conservative repair for the brief gaps this method tolerates."""
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    if m.all() or not m.any():
        return x
    idx = np.flatnonzero(m)
    out = x.copy()
    out[~m] = np.interp(np.flatnonzero(~m), idx, x[idx])
    return out


def _foot_ap_velocity(markers, side, point, time=None, label_map=None):
    """AP-relative-to-pelvis *velocity* (mm/s) of a foot marker, anterior-positive.

    Differentiates :func:`foot_progression_series` w.r.t. the marker clock
    (``markers['time']``, or an explicit ``time``). NaN-safe: brief occlusions are
    interpolated (:func:`_fill_nan`) before differentiation so a gap doesn't fake
    an event. Pure NumPy via :func:`numpy.gradient` (centred difference)."""
    series = _fill_nan(foot_progression_series(markers, side, point, label_map))
    if time is None:
        time = markers.get("time")
    if time is None:
        rate = float(markers.get("rate") or 0.0)
        if rate <= 0:
            raise ValueError("velocity method needs markers['time'] or 'rate'")
        time = np.arange(len(series)) / rate
    time = np.asarray(time, dtype=float)
    if len(time) != len(series):                      # master-clock mismatch
        time = np.linspace(time[0], time[-1], len(series))
    return np.gradient(series, time)


def velocity_events(markers, side, time=None, label_map=None,
                    min_distance_s=0.6, prominence_frac=0.3):
    """Heel-strike / toe-off frames from the foot-marker AP **velocity** (O'Connor
    et al. 2007; Zeni et al. 2008 velocity variant).

    Differentiates the anterior-positive AP-relative foot position
    (:func:`foot_progression_series`) and reads events off its velocity:

      - **HS** = local **minima** of the HEEL AP velocity — the heel's AP velocity
        is most negative (decelerating / belt-dragged) at foot contact.
      - **TO** = local **minima** of the TOE AP velocity — the toe's AP velocity is
        most negative just before it reverses forward into swing.

    ``min_distance_s`` (seconds, refractory) suppresses double-counts within a
    stride and is clock-independent (converted to frames via the marker rate).
    ``prominence_frac`` gates the velocity minima at ``prominence_frac * std(v)``
    so a light marker jitter doesn't add spurious events without needing a
    low-pass filter. NaN-safe (occlusions interpolated before differentiation).

    Returns ``{"HS": ndarray, "TO": ndarray}`` of integer frame indices on the
    marker clock (one row per marker frame), sign-/clock-independent.
    """
    vh = _foot_ap_velocity(markers, side, "heel", time, label_map)
    vt = _foot_ap_velocity(markers, side, "toe", time, label_map)
    rate = float(markers.get("rate") or 0.0)
    if rate <= 0 and markers.get("time") is not None:
        tt = np.asarray(markers["time"], dtype=float)
        rate = (len(tt) - 1) / (tt[-1] - tt[0]) if tt[-1] > tt[0] else 0.0
    dist = max(1, int(round(min_distance_s * rate))) if rate > 0 else None

    def _minima(v):
        prom = prominence_frac * float(np.nanstd(v)) if prominence_frac else None
        idx, _ = find_peaks(-v, distance=dist, prominence=prom)
        return idx.astype(int)

    return {"HS": _minima(vh), "TO": _minima(vt)}


def gait_events(markers, side, method="coordinate", time=None, label_map=None,
                min_distance_s=0.6, prominence_frac=0.3):
    """Shared entry point: detect HS/TO by the ``coordinate`` or ``velocity`` method.

    ``method="coordinate"`` (default, Zeni 2008 coordinate method): HS = maxima of
    the heel AP-relative series, TO = minima of the toe AP-relative series — the
    same picking the pipeline does on the ``gait:<SIDE>_<point>_ap`` signals.
    ``method="velocity"`` delegates to :func:`velocity_events`.

    Both return ``{"HS": ndarray, "TO": ndarray}`` of marker-clock frame indices,
    so :func:`split_stance_swing` can consume either."""
    if method == "velocity":
        return velocity_events(markers, side, time=time, label_map=label_map,
                               min_distance_s=min_distance_s,
                               prominence_frac=prominence_frac)
    if method != "coordinate":
        raise ValueError(f"unknown gait-event method: {method!r}")
    rate = float(markers.get("rate") or 0.0)
    dist = max(1, int(round(min_distance_s * rate))) if rate > 0 else None
    heel = foot_progression_series(markers, side, "heel", label_map)
    toe = foot_progression_series(markers, side, "toe", label_map)
    hs, _ = find_peaks(heel, distance=dist)
    to, _ = find_peaks(-toe, distance=dist)
    return {"HS": hs.astype(int), "TO": to.astype(int)}


def split_stance_swing(hs_frames, to_frames, time):
    """Per-cycle stance/swing split from heel-strike + toe-off frame lists.

    A gait cycle is HS_i -> HS_{i+1}; the toe-off that falls strictly inside that
    window splits it into stance (HS_i -> TO) and swing (TO -> HS_{i+1}). A cycle
    with no TO inside is dropped (not guessed). Returns a list of dicts, one per
    valid cycle::

        {"hs", "to", "next_hs",            # frame indices
         "cycle_s", "stance_s", "swing_s", # durations (seconds)
         "stance_pct", "swing_pct"}        # % of the cycle

    ``time`` is the master clock (seconds per frame index)."""
    time = np.asarray(time, dtype=float)
    hs = sorted(int(f) for f in hs_frames)
    tos = sorted(int(f) for f in to_frames)
    out = []
    for i in range(len(hs) - 1):
        h0, h1 = hs[i], hs[i + 1]
        inside = [f for f in tos if h0 < f < h1]
        if not inside:
            continue
        to = inside[0]
        t0, t_to, t1 = time[h0], time[to], time[h1]
        cycle = float(t1 - t0)
        if cycle <= 0:
            continue
        stance = float(t_to - t0)
        swing = float(t1 - t_to)
        out.append({
            "hs": h0, "to": to, "next_hs": h1,
            "cycle_s": cycle, "stance_s": stance, "swing_s": swing,
            "stance_pct": 100.0 * stance / cycle,
            "swing_pct": 100.0 * swing / cycle,
        })
    return out
