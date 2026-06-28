"""Results model — one uniform, by-type listing of everything a pipeline produces.

This is the data side of the RESULT panels (Signals / Events / Metrics). It does
NOT recompute anything: it *composes* the existing catalogs into one shape the UI
renders as three lists. Pure (no Qt), headless-testable.

  - signals: ONLY what the pipeline produces — FilterStep ``:filt`` twins,
    ComputeAngleStep ``angle:*``, ComputeStep outputs, TrajectoryStep
    ``trajectory:*``. Raw inputs (bare ``fz/cop_*``, ``fp{n}:*``, ``marker:*``,
    un-stepped angles) are deliberately excluded — those live in the RAW SIGNALS
    panel. An empty pipeline → empty signal list (the correct "nothing computed
    yet" state). Each entry carries a ``group`` for the UI's sub-sections.
  - events:  :func:`core.events_compute.event_catalog`.
  - metrics: the ``run_pipeline`` result's ``metrics`` list.

NB: distinct from :mod:`core.results_store` (the Statistics/Excel flat table) —
different concept, do not conflate.
"""

import json
from dataclasses import dataclass

from core import events_compute
from core.pipeline import ComputeStep, MetricStep, TrajectoryStep
from core.signals import FILT_SUFFIX, label_for, unit_for


@dataclass(frozen=True)
class ResultEntry:
    """One produced artifact in a result list.

    ``key`` is the stable catalog key (also how the UI pulls its data); ``kind``
    is ``"signal" | "event" | "metric"``; ``group`` is the sidebar sub-group
    label; ``origin`` is ``raw | processed | model | derived | event | metric``
    (used to indent ``:filt`` twins under their parent, V3D ORIGINAL/PROCESSED).
    """

    key: str
    label: str
    unit: str
    kind: str
    group: str
    origin: str


def _joint_of(angle_name):
    """Group label for an ``angle:<NAME>`` signal — the joint, plane kept in label.

    ``RKNEE_FE`` -> ``"RKNEE"``; ``Knee`` -> ``"Knee"``. Splits the trailing plane
    suffix (``_FE`` / ``_AB`` / ``_IE``) so all three planes of a joint group
    together (biomech: joint -> plane)."""
    for plane in ("_FE", "_AB", "_IE"):
        if angle_name.endswith(plane):
            return angle_name[: -len(plane)]
    return angle_name


def _metric_group(src):
    """Sub-group for a metric, by its source signal key.

    Unlike signals (coarse "Joint angles" / "Force Plate n"), metrics group by
    the *specific* source so a long metric list stays findable: an ``angle:*``
    source → its joint (``Knee``), a force/COP source → its plate, otherwise the
    generic "Metrics" bucket."""
    if not src:
        return "Metrics"
    if src.endswith(FILT_SUFFIX):
        src = src[: -len(FILT_SUFFIX)]
    if src.startswith("angle:"):
        return _joint_of(src.split(":", 1)[1])
    if src.startswith("fp"):
        num = src.split(":", 1)[0][2:]
        if num.isdigit():
            return f"Force Plate {num}"
    if src in ("fz", "fx", "fy", "cop", "cop_ap", "cop_ml"):
        return "Force Plate 1"
    return "Metrics"


def build_results(dataset, pipeline, *, marker_disp=None, angle_result=None,
                  run_result=None):
    """Compose the by-type result lists for ``dataset`` under ``pipeline``.

    Returns ``{"signal": [ResultEntry...], "event": [...], "metric": [...]}``.
    ``run_result`` is the dict from :func:`core.run.run_pipeline` (or ``None``
    before the first ▶Run — then ``metric`` is empty, which is correct: nothing
    has been computed yet).
    """
    if angle_result is None:
        angle_result = dataset.get("model_result")

    # -- signals: ONLY what the pipeline actually produces ---------------------
    # Raw inputs (bare fz/cop, fp{n}:*, marker:*, un-stepped angle:*) belong to
    # the RAW SIGNALS panel, NOT here. With no steps this list is empty — that's
    # the correct "I haven't computed anything yet" state. We enumerate the four
    # product families: FilterStep ":filt" twins, ComputeAngleStep "angle:*",
    # ComputeStep outputs, and TrajectoryStep "trajectory:*".
    # The group is fixed by which product family the key belongs to (NOT by the
    # raw-key heuristics in _classify_signal) so an arbitrarily-named ComputeStep
    # output (e.g. "fp1:fz_pctbw") still lands under "Derived signals".
    sig = []
    seen = set()

    def _add_sig(key, group, origin):
        if key in seen or key == "time":
            return
        seen.add(key)
        sig.append(ResultEntry(key, label_for(key), unit_for(key), "signal",
                               group, origin))

    if pipeline is not None:
        # Processed signals: every ":filt" key a FilterStep emits.
        for key in pipeline.filtered_keys():
            _add_sig(key, "Processed signals", "processed")
        # Joint angles: only when a ComputeAngleStep asked for them (no auto-
        # compute fallback — the pipeline is the sole source). An empty joints
        # list on the step means "all angles the model produced".
        if pipeline.has_angle_step() and angle_result and angle_result.get("angles"):
            wanted = set()
            for step in pipeline.compute_angle_steps():
                wanted.update(step.joints or [])
            for name in angle_result["angles"]:
                if not wanted or name in wanted:
                    _add_sig(f"angle:{name}", "Joint angles", "model")
        # Centre of mass: com:x/y/z world-frame signals. A model product like
        # Joint angles — gated on a ComputeAngleStep (so model_result exists) AND
        # a non-empty COM trajectory in that result (the pipeline is the sole
        # source; no step / no COM => nothing listed).
        if pipeline.has_angle_step() and angle_result:
            com_arr = (angle_result.get("com") or {}).get("com")
            if com_arr is not None and len(com_arr) > 0:
                for ax in ("x", "y", "z"):
                    _add_sig(f"com:{ax}", "Centre of mass", "model")
        # Derived signals: ComputeStep named outputs.
        for step in pipeline.compute_steps():
            if step.name:
                _add_sig(step.name, "Derived signals", "derived")
        # COP trajectory: TrajectoryStep products.
        for step in pipeline.trajectory_steps():
            for key in step.produces():
                _add_sig(key, "COP trajectory", "derived")

    # -- events ----------------------------------------------------------------
    ev = []
    for label in events_compute.event_catalog(dataset, pipeline, marker_disp,
                                              angle_result):
        ev.append(ResultEntry(f"event:{label}", label, "", "event", "Events", "event"))

    # -- metrics (only after a run) -------------------------------------------
    met = []
    metric_input = {}
    if pipeline is not None:
        for step in pipeline.steps:
            if isinstance(step, MetricStep) and step.name:
                metric_input[step.name] = step.input
    if run_result:
        for m in run_result.get("metrics", []):
            name = m.get("name", "")
            src = metric_input.get(name, "")
            group = _metric_group(src)
            met.append(ResultEntry(f"metric:{name}", name, m.get("unit", ""),
                                   "metric", group, "metric"))
    return {"signal": sig, "event": ev, "metric": met}


def results_token(pipeline, subject=None):
    """Hashable token for cache invalidation: the recipe + subject metadata.

    The whole pipeline recipe is hashed (signals AND metrics depend on it) plus
    the subject (mass/height feed normalize). ▶Run is explicit, so a coarse token
    is fine. Same pattern as ``events_compute._detect_token``."""
    recipe = pipeline.to_dict() if pipeline is not None else None
    return json.dumps({"pipeline": recipe, "subject": subject or {}},
                      sort_keys=True, default=str)
