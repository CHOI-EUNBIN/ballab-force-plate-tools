"""Pipeline executor — runs a flat step list against one dataset, accumulating
three catalogs (signal / event / metric) that later steps can reference.

This is the dataflow engine: the pipeline is a graph where every produced
artifact has a key and is reusable as a downstream input. A step reads its
inputs through the :class:`RunContext` (``ctx.signal/event/metric``) and writes
its outputs into the same context, so a ``Compute -> Detect -> Metric -> Metric``
recipe just runs top-to-bottom (eager, single pass).

Catalogs:
  * signal: raw + ``:filt`` (via :class:`core.signals.Workspace`) + ComputeStep
    outputs (e.g. ``fp1:fz_pctbw``) + model angles (``angle:*``).
  * event:  detect-step events (via ``events_compute``) + min/max metric events.
  * metric: subject metadata (``mass``/``height``/``bodyweight``) + MetricStep results.

Empty pipeline => raw (no metrics/derived signals), exactly as before.
"""

import numpy as np

from core import events_compute, signal_ops
from core.metrics_compute import compute_metric_step
from core.pipeline import ComputeStep, MetricStep, NormalizeStep, METRIC_PREFIX, EVENT_PREFIX
from core.signals import Workspace, unit_for

G = 9.80665  # m/s^2 — for body weight (N) from mass (kg)


def _strip(prefix, key):
    return key[len(prefix):] if key.startswith(prefix) else key


class RunContext:
    """Read/write access to the three catalogs during a run."""

    def __init__(self, workspace, time, fs):
        self.workspace = workspace
        self.time = np.asarray(time, dtype=float)
        self.fs = float(fs)
        self._signals = {}   # produced signal key -> array (ComputeStep outputs)
        self._units = {}     # produced signal key -> unit string (ComputeStep)
        self._events = {}    # bare label -> frame ndarray
        self._metrics = {}   # bare name -> value (scalar)
        self._metric_cycles = {}  # bare name -> per-cycle ndarray (for CV / refs)

    # -- reads -------------------------------------------------------------
    def signal(self, key):
        if key in self._signals:
            return self._signals[key]
        return self.workspace.series(key)   # raw / :filt / angle:* (may raise)

    def event(self, label):
        return self._events.get(_strip(EVENT_PREFIX, label))

    def metric(self, name):
        return self._metrics.get(_strip(METRIC_PREFIX, name))

    def metric_cycles(self, name):
        """Per-cycle value array of an earlier MetricStep (for CV), or ``None``."""
        return self._metric_cycles.get(_strip(METRIC_PREFIX, name))

    def unit(self, key):
        """Unit string for a signal ``key`` — a ComputeStep-produced unit if we
        tracked one, else the static catalog unit (``signals.unit_for``)."""
        if key in self._units:
            return self._units[key]
        return unit_for(key)

    # -- writes ------------------------------------------------------------
    def add_signal(self, key, arr, unit=None):
        self._signals[key] = np.asarray(arr, dtype=float)
        if unit is not None:
            self._units[key] = unit

    def add_event(self, label, frames):
        self._events[_strip(EVENT_PREFIX, label)] = np.asarray(frames, dtype=int)

    def add_metric(self, name, value):
        self._metrics[_strip(METRIC_PREFIX, name)] = value

    def add_metric_cycles(self, name, arr):
        if arr is not None:
            self._metric_cycles[_strip(METRIC_PREFIX, name)] = np.asarray(arr, dtype=float)


def _run_compute(ctx, step):
    """ComputeStep: produce a new signal from one (or more) inputs.

    Dispatches on ``step.method`` over the :mod:`core.signal_ops` library:
      * ``normalize``  — ``input / by`` (``by`` a constant or a ``metric:`` ref).
      * ``derivative`` — ``signal_ops.derivative`` (order from ``params``).
      * ``integral``   — cumulative ``signal_ops.integral`` (sign from ``params``).
      * ``magnitude``  — resultant of ``input`` + ``step.inputs`` components.
      * ``abs``        — element-wise ``|input|`` (unit preserved).

    The produced signal carries a derived unit (``signal_ops.derive_unit``) so a
    later Metric on it reports e.g. deg/s. Any unresolvable input/divisor is a
    silent no-op (the step just produces nothing), matching the old behaviour.
    """
    if not step.name or not step.input:
        return
    try:
        src = np.asarray(ctx.signal(step.input), dtype=float)
    except (KeyError, ValueError):
        return
    method = getattr(step, "method", "normalize")
    base_unit = ctx.unit(step.input)
    params = getattr(step, "params", {}) or {}

    if method == "normalize":
        by = step.by
        if isinstance(by, str):
            by = ctx.metric(by)
        try:
            by = float(by)
        except (TypeError, ValueError):
            return
        if by == 0:
            return
        ctx.add_signal(step.name, src / by,
                       unit=signal_ops.derive_unit(base_unit, "normalize"))
        return

    if method == "derivative":
        order = int(params.get("order", 1) or 1)
        out = signal_ops.derivative(src, ctx.time, order=order)
        ctx.add_signal(step.name, out,
                       unit=signal_ops.derive_unit(base_unit, "derivative", order=order))
        return

    if method == "integral":
        sign = params.get("sign", "all") or "all"
        out = signal_ops.integral(src, ctx.time, kind="cumulative", sign=sign)
        ctx.add_signal(step.name, out,
                       unit=signal_ops.derive_unit(base_unit, "integral"))
        return

    if method == "abs":
        # Rectify a bipolar channel: |input|, same length, unit preserved. Lets
        # the user turn the raw (down-negative) Fz into a positive vGRF / impulse
        # without any global sign flip.
        ctx.add_signal(step.name, signal_ops.absval(src),
                       unit=signal_ops.derive_unit(base_unit, "absval"))
        return

    if method == "magnitude":
        comps = [src]
        try:
            for key in getattr(step, "inputs", ()):
                if key:
                    comps.append(np.asarray(ctx.signal(key), dtype=float))
        except (KeyError, ValueError):
            return
        try:
            out = signal_ops.magnitude(*comps)
        except ValueError:
            return   # mismatched lengths / no components -> no-op
        ctx.add_signal(step.name, out,
                       unit=signal_ops.derive_unit(base_unit, "magnitude"))
        return


def _run_normalize(ctx, step):
    """NormalizeStep: extract the trial's 0-100% epoch matrix for one signal.

    Returns ``{"matrix", "meta", "label", "points", "mode"}`` or ``None`` when the
    step is incomplete or its input signal is unavailable.
    """
    from core.normalize import epoch_windows, extract_epochs
    if not step.name or not step.input:
        return None
    try:
        values = ctx.signal(step.input)
    except Exception:
        return None
    if values is None:
        return None
    if step.mode == "cycle":
        start_lab, end_lab = step.event, step.event
    elif step.mode == "window":
        start_lab, end_lab = step.start_event, step.end_event
    else:
        start_lab = end_lab = None
    events = {}
    for lab in (start_lab, end_lab):
        if lab:
            fr = ctx.event(lab)
            if fr is not None:
                events[lab] = fr
    windows = epoch_windows(ctx.time, events, step.mode,
                            start_event=start_lab, end_event=end_lab)
    matrix, meta = extract_epochs(np.asarray(values, float), windows, step.points)
    return {"matrix": matrix, "meta": meta, "label": step.input,
            "points": step.points, "mode": step.mode}


def run_pipeline(dataset, pipeline, marker_disp=None, angle_result=None,
                 subject=None):
    """Execute ``pipeline`` against ``dataset`` -> a result dict.

    ``subject`` (optional) = ``{"mass": kg, "height": m}``; injected as the
    metrics ``mass`` / ``height`` / ``bodyweight`` (N). Returns
    ``{"ctx", "metrics", "metric_values", "events"}`` where ``metric_values`` is
    ``{name: (value, unit)}`` (cards/summary/export format; cyclic = mean) and
    ``metrics`` the full per-step results (cycles / sd / n / event frames).
    """
    time = np.asarray(dataset.get("time", []), dtype=float)
    fs = float(dataset.get("fs", 1000.0)) or 1000.0
    if angle_result is None:
        angle_result = dataset.get("model_result")
    ws = Workspace(dataset, marker_disp=marker_disp, angle_result=angle_result,
                   pipeline=pipeline)
    ctx = RunContext(ws, time, fs)

    # Subject metadata -> metric catalog (referenceable, e.g. by a normalize step).
    subject = subject or {}
    mass = subject.get("mass")
    if mass:
        ctx.add_metric("mass", float(mass))
        ctx.add_metric("bodyweight", float(mass) * G)
    if subject.get("height"):
        ctx.add_metric("height", float(subject["height"]))

    # Seed events from detect steps (computed for the whole pipeline at once).
    # Pass the metrics seeded so far (subject mass / body weight / height) so a
    # detect step whose threshold is a ``metric:`` reference (e.g.
    # ``metric:bodyweight``) resolves against them. Only metrics available BEFORE
    # the step loop are visible here (events are computed up front, in one pass);
    # a threshold referencing a metric produced by a later MetricStep can't be
    # honoured by this single-pass model and yields no events.
    if pipeline is not None:
        for entry in events_compute.compute_detected_events(
                dataset, pipeline, marker_disp, angle_result,
                metrics=dict(ctx._metrics)):
            if entry["label"]:
                ctx.add_event(entry["label"], entry["frames"])

    # Walk the flat step list top-to-bottom; Compute/Metric steps read upstream
    # artifacts via ctx and write their own. Filter/Detect/Trajectory/ComputeAngle
    # are handled out-of-band (filt via Workspace, events pre-seeded, angles via
    # the injected ``angle_result``) and so are naturally skipped by the isinstance
    # dispatch below.
    metrics = []
    metric_values = {}
    normalized = {}
    if pipeline is not None:
        for step in pipeline.steps:
            if not getattr(step, "enabled", True):
                continue
            if isinstance(step, ComputeStep):
                _run_compute(ctx, step)
            elif isinstance(step, MetricStep):
                if not step.name:
                    continue
                res = compute_metric_step(ctx, step)
                metrics.append(res)
                metric_values[res["name"]] = (res["value"], res["unit"])
                ctx.add_metric(res["name"], res["value"])
                # Per-cycle array kept so a later CV op (or any reference op that
                # wants the stride-to-stride spread) can read it back.
                ctx.add_metric_cycles(res["name"], res.get("cycles"))
                if step.emits_event() and res["event_frames"]:
                    ctx.add_event(step.name, res["event_frames"])
            elif isinstance(step, NormalizeStep):
                res = _run_normalize(ctx, step)
                if res is not None and step.name:
                    normalized[step.name] = res

    return {"ctx": ctx, "metrics": metrics, "metric_values": metric_values,
            "events": ctx._events, "normalized": normalized}
