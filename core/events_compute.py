"""Per-file event computation + the event catalog (auto + manual events).

This is the glue between the pure detection math (:mod:`core.events`), the
pipeline recipe (:class:`core.pipeline.DetectEventStep`) and a dataset. It is
kept *separate* from ``core.events`` so that module stays a pure value-in /
indices-out library (headless-testable with synthetic arrays), while this module
knows about datasets / Workspace / pipelines.

Two event sources, both surfaced through one catalog (C2, user-confirmed):
  - AUTO events: :class:`DetectEventStep` recipes shared across files, computed
    per file here. The signal each step reads is resolved through a
    :class:`core.signals.Workspace`, so a ``"cop_ap:filt"`` input picks up the
    pipeline's filtering (falling back to raw when no filter step targets it).
  - MANUAL events: the existing ``dataset["events"]`` list (single frame each,
    authored in the UI). Untouched here — natural backward-compat: an old project
    with no detect steps shows only its manual events.

Caching mirrors ``model_result``/``_model_token``: detected events are cached on
the dataset under ``_events_cache`` keyed by an ``_events_token`` derived from the
pipeline's detect-step recipe. Change the recipe -> token changes -> recompute.
Still UI-free; the UI just calls :func:`compute_detected_events` /
:func:`event_catalog` and reads the result.
"""

import json

import numpy as np

from core import events as ev
from core.pipeline import METRIC_PREFIX
from core.signals import Workspace


def _resolve_metric_value(value, metrics):
    """Resolve a step param that may be a ``"metric:<name>"`` reference.

    A threshold/hysteresis knob can be either a literal number OR a
    ``"metric:<name>"`` string that points at a value in the metric catalog
    (e.g. ``"metric:bodyweight"`` for "heel-strike at 5% body weight" recipes).
    ``metrics`` is the bare-name -> value dict the run seeds (subject mass /
    body weight / height, plus any earlier MetricStep results). Returns the
    resolved ``float`` or ``None`` when it can't be resolved (no metrics dict, or
    the referenced metric is missing) so the caller can skip the step gracefully
    rather than raising.
    """
    if isinstance(value, str) and value.startswith(METRIC_PREFIX):
        if not metrics:
            return None
        v = metrics.get(value[len(METRIC_PREFIX):])
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_min_distance_frames(params, fs):
    """A detect step's peak/crossing refractory, in master-clock FRAMES.

    G1: the refractory ("Min spacing") is authored in SECONDS via the new
    ``min_distance_s`` param so it means the same real time on every trial,
    regardless of the master clock (a force-plate trial's master fs is the force
    rate, e.g. 1000 Hz, even when markers/angles are 100 Hz). Seconds are
    converted to frames here with ``round(s * fs)``, clamped to >= 1 frame.

    Back-compat: a saved project stores ``min_distance`` in FRAMES. When
    ``min_distance_s`` is absent that legacy frame value is returned verbatim
    (clock-dependent, exactly as before) so old recipes are untouched. Returns
    ``None`` when neither key is present (refractory off).
    """
    md_s = params.get("min_distance_s")
    if md_s is not None:
        return max(1, round(float(md_s) * fs))
    return params.get("min_distance")


def _detect_token(pipeline, metrics=None):
    """A hashable token for the detect-event recipe (cache invalidation key).

    Only the :class:`DetectEventStep` steps matter for detected events (filter
    steps affect them only via the signals they read, which is captured because
    a step's ``input`` key like ``"fz:filt"`` is part of its dict). Built from the
    JSON of each step's ``to_dict`` so any field change flips the token — except
    ``color``, which is purely cosmetic and is dropped here so recolouring an
    event does not invalidate the per-file detection cache.

    ``metrics`` (optional) is folded in too: when a step's threshold is a
    ``metric:`` reference its *resolved value* depends on subject metadata, so the
    metric dict must invalidate the cache (changing subject mass must re-detect).
    Only the metrics actually referenced by a threshold/hysteresis knob are
    included, so unrelated metric changes don't churn the events cache.
    """
    if pipeline is None:
        return "[]"
    steps = []
    referenced = {}
    for s in pipeline.detect_event_steps():
        d = s.to_dict()
        d.pop("color", None)
        steps.append(d)
        for knob in ("threshold", "hysteresis"):
            ref = (s.params or {}).get(knob)
            if isinstance(ref, str) and ref.startswith(METRIC_PREFIX):
                name = ref[len(METRIC_PREFIX):]
                if metrics and name in metrics:
                    referenced[name] = metrics[name]
    # Keep the legacy plain-list token shape when no step references a metric
    # (the common case), so the format — and the no-step ``"[]"`` — is unchanged;
    # only fold metrics in when a threshold actually depends on them.
    if not referenced:
        return json.dumps(steps, sort_keys=True, default=str)
    return json.dumps({"steps": steps, "metrics": referenced},
                      sort_keys=True, default=str)


def _resolve_scope_bound(bound, detected_so_far, default, fs=1.0):
    """Resolve ONE scope bound to a frame index.

    ``{"type":"frame","frame":N}`` -> N. ``{"type":"time","seconds":s}`` ->
    ``round(s * fs)`` (the master clock makes a seconds window mean the same real
    time on every trial, exactly like the G1 refractory). ``{"type":"event",
    "label":L,"instance":i}`` -> the i-th frame of label ``L`` among events
    detected by EARLIER steps (1-based; negative counts from the end, -1 = last).
    Anything unresolvable (missing label/instance, bad shape) -> ``default``."""
    if not isinstance(bound, dict):
        return default
    t = bound.get("type")
    if t == "frame":
        try:
            return int(bound.get("frame", default))
        except (TypeError, ValueError):
            return default
    if t == "time":
        # Seconds -> master-clock frame: clock-independent search window.
        try:
            return int(round(float(bound.get("seconds")) * fs))
        except (TypeError, ValueError):
            return default
    if t == "event":
        label = bound.get("label")
        try:
            inst = int(bound.get("instance", 1) or 1)
        except (TypeError, ValueError):
            inst = 1
        frames = []
        for e in detected_so_far:
            if e.get("label") == label:
                frames.extend(int(f) for f in e.get("frames", []))
        frames = sorted(set(frames))
        if not frames:
            return default
        idx = len(frames) + inst if inst < 0 else inst - 1
        return frames[idx] if 0 <= idx < len(frames) else default
    return default


def _resolve_scope(step, detected_so_far, n_frames, fs=1.0):
    """A step's ``scope`` -> a ``(start, end)`` frame tuple, or ``None`` (whole
    trial). Legacy ``[start, end]`` frame windows pass through; a dict
    ``{"from": bound, "to": bound}`` resolves each bound (frame, time or event)
    against the events detected by earlier steps. ``fs`` (master clock) converts
    a ``time`` bound's seconds to frames. Unresolvable bounds fall back to the
    trial edges (start->0, end->n_frames); the pair is ordered low<=high."""
    sc = step.scope
    if not sc:
        return None
    if isinstance(sc, (list, tuple)):
        return (int(sc[0]), int(sc[1])) if len(sc) == 2 else None
    if not isinstance(sc, dict):
        return None
    start = _resolve_scope_bound(sc.get("from"), detected_so_far, 0, fs)
    end = _resolve_scope_bound(sc.get("to"), detected_so_far, n_frames, fs)
    if start > end:
        start, end = end, start
    return (int(start), int(end))


def _run_step(step, values, n_frames, metrics=None, scope=None, fs=1.0):
    """Run one :class:`DetectEventStep`'s detector on a value array -> indices.

    Pure dispatch over ``method``; unknown methods/params degrade to an empty
    result rather than raising, so one misconfigured step can't break a whole
    analysis. ``scope`` (already resolved to a ``(start, end)`` frame tuple by
    :func:`_resolve_scope`) and the selector are applied here. ``n_frames`` is the
    master-clock length, used by ``method="frame"`` (which ignores ``values``).
    ``metrics`` resolves any ``metric:`` references in the threshold/hysteresis
    knobs (see :func:`_resolve_metric_value`). ``fs`` is the master-clock rate,
    used to convert a ``min_distance_s`` (seconds) refractory to frames
    (see :func:`_resolve_min_distance_frames`).
    """
    p = step.params or {}
    method = step.method
    min_distance = _resolve_min_distance_frames(p, fs)
    if method == "frame":
        # Fixed-frame event: no signal, just the typed frame index (clamped).
        if "frame" not in p:
            return np.empty(0, dtype=int)
        return ev.detect_at_frame(n_frames, int(p["frame"]))
    if method == "threshold":
        if "threshold" not in p:
            return np.empty(0, dtype=int)
        # threshold (and hysteresis) may be a literal number or a "metric:<name>"
        # reference; resolve both, skip the step if a reference is unresolvable.
        thr = _resolve_metric_value(p["threshold"], metrics)
        if thr is None:
            return np.empty(0, dtype=int)
        hyst = p.get("hysteresis")
        if hyst is not None:
            hyst = _resolve_metric_value(hyst, metrics)
        idx = ev.detect_threshold_crossings(
            values,
            threshold=thr,
            direction=p.get("direction", "rising"),
            min_distance=min_distance,
            hysteresis=hyst,
            scope=scope,
        )
    elif method == "peak":
        idx = ev.detect_peaks(
            values,
            kind=p.get("kind", "max"),
            min_distance=min_distance,
            prominence=p.get("prominence"),
            scope=scope,
        )
    elif method == "zero":
        idx = ev.detect_zero_crossings(
            values, direction=p.get("direction", "both"), scope=scope)
    elif method in ("global_maximum", "global_minimum"):
        # The single global extremum in the (optionally scoped) window: one
        # frame for the overall max/min. The selector below is harmless (there
        # is exactly one instance), so "first"/"all"/"nth=1" all return it.
        kind = "max" if method == "global_maximum" else "min"
        idx = ev.detect_global_extreme(values, kind=kind, scope=scope)
    else:
        return np.empty(0, dtype=int)

    sel = step.selector or {"mode": "first"}
    return ev.select_instances(
        idx, mode=sel.get("mode", "first"),
        n=sel.get("n"), lo=sel.get("lo"), hi=sel.get("hi"))


def compute_detected_events(dataset, pipeline, marker_disp=None,
                            angle_result=None, use_cache=True, metrics=None):
    """Detected events for ``dataset`` under ``pipeline``'s detect steps.

    Returns a list of ``{"label", "frames", "times", "step_id"}`` (one entry per
    detect step), where ``frames`` is the list of selected frame indices and
    ``times`` the matching ``dataset["time"]`` values. ``step_id`` is the step's
    position in the detect-step list (stable handle for the UI).

    Signals are resolved through a :class:`Workspace`, so ``:filt`` inputs use the
    pipeline's filtering. A step whose input signal is unavailable (e.g. an angle
    input on a trial with no model) is skipped with an empty frame list rather
    than raising. Cached on the dataset keyed by the recipe token; pass
    ``use_cache=False`` to force a recompute.

    ``metrics`` (optional, bare-name -> value) resolves ``metric:`` references in
    a step's threshold (e.g. ``"metric:bodyweight"``). It is part of the cache
    token, so changing the subject's mass re-detects. A ``metric:`` threshold
    with no ``metrics`` dict (e.g. the UI's bare catalog calls) yields an empty
    frame list for that step — the authoritative detection runs via
    :func:`core.run.run_pipeline`, which always passes the seeded metrics.
    """
    if pipeline is None:
        return []
    steps = pipeline.detect_event_steps()
    if not steps:
        # Clear any stale cache so a removed last step doesn't linger.
        dataset.pop("_events_cache", None)
        dataset.pop("_events_token", None)
        return []

    token = _detect_token(pipeline, metrics)
    if use_cache and dataset.get("_events_token") == token \
            and dataset.get("_events_cache") is not None:
        return dataset["_events_cache"]

    if angle_result is None:
        angle_result = dataset.get("model_result")
    ws = Workspace(dataset, marker_disp=marker_disp,
                   angle_result=angle_result, pipeline=pipeline)
    time = np.asarray(dataset["time"], dtype=float)

    n_frames = len(time)
    # Master-clock rate: used to convert a step's seconds refractory
    # (``min_distance_s``) to frames. Prefer the stored fs; fall back to the
    # median sample spacing of the time vector when it's missing.
    fs = dataset.get("fs")
    if not fs:
        fs = (1.0 / float(np.median(np.diff(time)))) if len(time) > 1 else 1.0
    fs = float(fs)
    out = []
    for step_id, step in enumerate(steps):
        if step.method == "frame":
            # No signal needed — the fixed-frame event lives on the master clock
            # alone, so don't resolve (a possibly-empty) input.
            values = None
        else:
            try:
                values = ws.series(step.input)
            except (ValueError, KeyError):
                out.append({"label": step.label, "frames": [], "times": [],
                            "step_id": step_id})
                continue
        # Resolve this step's scope against events detected by EARLIER steps
        # (``out`` so far) so a "between events" window works per dataset.
        resolved_scope = _resolve_scope(step, out, n_frames, fs)
        frames = _run_step(step, values, n_frames, metrics,
                           scope=resolved_scope, fs=fs)
        frames = [int(i) for i in frames]
        times = [float(time[i]) for i in frames if 0 <= i < len(time)]
        out.append({"label": step.label, "frames": frames, "times": times,
                    "step_id": step_id})

    if use_cache:
        dataset["_events_cache"] = out
        dataset["_events_token"] = token
    return out


def event_catalog(dataset, pipeline=None, marker_disp=None, angle_result=None):
    """All event labels available for ``dataset`` (auto + manual), de-duplicated.

    Auto labels come from the pipeline's detect steps (computed here); manual
    labels are the ``name`` field of ``dataset["events"]``. Order: auto first (in
    step order), then any manual labels not already present. Returns a list of
    ``str`` — the UI uses this to populate range-endpoint / event pickers.
    """
    labels = []
    seen = set()
    for entry in compute_detected_events(dataset, pipeline, marker_disp,
                                         angle_result):
        lab = entry["label"]
        if lab and lab not in seen:
            seen.add(lab)
            labels.append(lab)
    for event in dataset.get("events", []):
        lab = event.get("name")
        if lab and lab not in seen:
            seen.add(lab)
            labels.append(lab)
    return labels


def event_frames(dataset, label, pipeline=None, marker_disp=None,
                 angle_result=None):
    """Frame indices for ``label`` (auto instances if any, else manual fallback).

    Auto detection wins when a detect step carries this label (it can yield many
    instances). Otherwise falls back to the single-frame manual event(s) of that
    name in ``dataset["events"]`` (backward-compat). Returns an ascending
    ``np.ndarray`` of ints.
    """
    frames = []
    for entry in compute_detected_events(dataset, pipeline, marker_disp,
                                         angle_result):
        if entry["label"] == label:
            frames.extend(entry["frames"])
    if frames:
        return np.unique(np.asarray(frames, dtype=int))
    manual = [int(e["index"]) for e in dataset.get("events", [])
              if e.get("name") == label and "index" in e]
    return np.unique(np.asarray(manual, dtype=int)) if manual else np.empty(0, dtype=int)


def resolve_endpoint_frame(dataset, label, mode="first", n=None, lo=None,
                           hi=None, pipeline=None, marker_disp=None,
                           angle_result=None):
    """One frame index for an event ``label``, picking instance via the selector.

    The multi-instance <-> single-frame reconciliation for range endpoints (C2):
    detect all instances of ``label`` then :func:`core.events.select_instances`
    picks one. Default ``mode="first"`` preserves the old single-frame behaviour
    (and matches a manual event, which has one instance). Returns an ``int`` frame
    index, or ``None`` when the label has no instances.
    """
    frames = event_frames(dataset, label, pipeline, marker_disp, angle_result)
    picked = ev.select_instances(frames, mode=mode, n=n, lo=lo, hi=hi)
    if len(picked) == 0:
        return None
    return int(picked[0])
