"""Analysis pipeline — the ordered recipe of processing steps applied to signals.

"Everything is a Signal." RAW signals always exist in the catalog. A
:class:`Pipeline` is the *container* of analysis functions you add, in order.
The first concrete step type is :class:`FilterStep`: it low-passes a chosen set
of signals and so *creates* processed ("<key>:filt") signals that then appear in
the catalog next to their raw originals. Later step types (event detection,
segmentation, normalization) will layer on top — this module only owns the
skeleton + the filter step for now (C1).

Order = execution. The step list runs strictly top-to-bottom (the physical
list order IS the execution order, Visual3D-style). A step's ``stage`` is only a
*display/classification* label (which badge + preset bucket it shows under) — it
does NOT constrain where the step may sit. The same kind of step may appear at
several positions, and stages may interleave freely (e.g. the user's real recipe
``Compute -> Detect -> Compute -> Metric -> Detect``). The only real constraint is
*data*: a step may only reference catalog keys that an earlier step (or the raw
dataset) already produced. That data constraint is what :meth:`Pipeline.requires`
/ :meth:`PipelineStep.produces` express and what
:meth:`Pipeline.data_dependency_warnings` lints (read-only, never raises).

Design (Visual3D-faithful, user-confirmed 2026-06-23):
  - One *shared* pipeline (a single recipe applied to whatever is analysed),
    mirroring how the old global filter and the events were shared.
  - A :class:`FilterStep` = one :class:`FilterSpec` + the targets it produces.
    Different cutoffs => *separate* steps (e.g. a COP 10 Hz step + a marker
    6 Hz step), exactly like Visual3D's per-signal low-pass blocks.
  - Pure / UI-free / numpy: no Qt import here. The UI owns one Pipeline and
    injects it (the same way it injects ``axis_settings``).

Persistence: :meth:`Pipeline.to_dict` / :meth:`from_dict` round-trip the recipe
into the project manifest. An old project with no pipeline key loads as an empty
pipeline (= raw, no filtering).
"""

from core.signals import FILT_SUFFIX, FilterSpec

#: Sentinel target meaning "apply this filter step to the marker arrays too".
#: Marker filtering happens on the marker clock (see Workspace.filtered_marker_data),
#: so it is tracked as a flag rather than as a scalar signal key.
MARKER_TARGET = "markers"

#: The canonical list of analysis *stages* (the role a step plays), Visual3D-faithful
#: (@researcher-confirmed 2026-06-23). A step's ``stage`` class attribute places it
#: in this list: ``derive`` makes signals, ``detect`` makes events, ``segment``
#: cuts cycles, ``metric`` reduces to values, ``normalize`` rescales to 0-100%.
#: Only ``derive`` and ``detect`` have concrete step classes today; the other three
#: are reserved here so the UI can show place-holder (disabled) menu entries
#: (segment/metric/normalize land in Phase C).
#:
#: IMPORTANT — this list is a DISPLAY / classification ordering hint only (badge
#: order, preset grouping). It is NOT an execution-order rule. Steps run in their
#: physical list order and stages may interleave freely (the user's real
#: ``Compute -> Detect -> Compute -> Metric -> Detect`` recipe is valid). The
#: 2nd-round Visual3D re-check (2026-06-23) retired the old
#: ``derive <= detect <= ... <= normalize`` rank constraint; the only enforced
#: relation is data dependency (see :meth:`Pipeline.data_dependency_warnings`).
STAGE_ORDER = ["derive", "detect", "segment", "metric", "normalize"]

#: Human-facing labels for each stage (English — Visual3D terminology). ``derive``
#: shows as "Compute" because Visual3D *computes* signals ("Derive" is not its
#: term); the internal key stays ``derive``. The UI renders these as stage badges.
STAGE_LABELS = {
    "derive": "Compute",
    "detect": "Detect Events",
    "segment": "Segment",
    "metric": "Metric",
    "normalize": "Normalize",
}

#: Catalog-key namespace prefix for detected events. Events live in a different
#: key space from signals (a signal "fz" and an event labelled "fz" must not
#: collide), so a :class:`DetectEventStep` producing label ``"HS"`` adds the key
#: ``"event:HS"`` to the dependency catalog. (The detected frames themselves are
#: computed elsewhere — this prefix is only for the produces/requires contract.)
EVENT_PREFIX = "event:"

#: Namespace prefixes that mark a catalog key as DERIVED — i.e. a key that can
#: only exist because some pipeline step produced it (never a raw dataset signal).
#: Used by :meth:`Pipeline.data_dependency_warnings` to decide, when the raw
#: catalog is unknown, which missing ``requires`` keys are *provably* missing
#: (a derived key) vs possibly-raw (a bare ``fz`` / ``angle:Knee`` / ``marker:*``).
_DERIVED_PREFIXES = (EVENT_PREFIX, "trajectory:", "metric:")


def _is_derived_key(key):
    """True if ``key`` is a pipeline-produced (derived) catalog key.

    Derived = ends with the filter suffix (``:filt``) or starts with a derived
    namespace prefix (``event:`` / ``trajectory:`` / ``metric:``). Everything
    else (``fz``, ``cop_ap``, ``angle:Knee``, ``marker:HEEL:Z``) is treated as a
    possibly-raw signal that the dataset may already provide.
    """
    return key.endswith(FILT_SUFFIX) or key.startswith(_DERIVED_PREFIXES)


class PipelineStep:
    """Base class for a pipeline step.

    Subclasses declare a ``kind`` string (persisted) and implement
    :meth:`to_dict` / :meth:`from_dict`. Keeping a tiny base lets the pipeline
    serialize/deserialize a heterogeneous list by dispatching on ``kind``.

    Two cross-cutting class/instance attributes live here:

    - ``stage`` (class attribute) — the role this step plays, one of
      :data:`STAGE_ORDER`. The UI badges/groups rows by stage. Subclasses
      override it (``FilterStep.stage = "derive"`` etc.); the base ``"derive"``
      is just a safe default.
    - ``enabled`` (instance attribute, default ``True``) — whether the step
      participates in *execution*. A disabled step is still shown in the recipe
      (so the user can re-enable it) but is skipped by every execution accessor
      (``filter_steps`` / ``detect_event_steps`` / ``trajectory_steps`` /
      ``filter_spec_for`` / ``marker_filter_spec``). It IS serialized and IS
      part of the cache token, so toggling it forces a recompute.
    """

    kind = "step"
    stage = "derive"

    enabled = True  # default; instances set their own in __init__

    # -- data-dependency contract ------------------------------------------
    #
    # Two catalog-key contracts every step declares (the base returns empty
    # sets; concrete steps override). They describe the step's *data* flow, the
    # only thing that constrains where a step may sit in the recipe (its
    # ``stage`` is purely cosmetic). ``produces`` = keys this step ADDS to the
    # catalog; ``requires`` = keys this step READS. The lint
    # :meth:`Pipeline.data_dependency_warnings` walks the list top-to-bottom,
    # accumulating produced keys, and flags a step whose ``requires`` aren't
    # available yet. Keys are plain strings in the catalog spaces:
    #   - signals:  "fz", "cop_ap:filt", "angle:Knee", "marker:HEEL:Z"
    #   - events:   "event:<label>"
    #   - metrics:  "metric:<name>"   (Phase C)
    # Both return a ``set`` so callers can union them cheaply.
    def produces(self):
        """Catalog keys this step adds (empty for a step that produces nothing)."""
        return set()

    def requires(self):
        """Catalog keys this step reads (empty for a step that reads nothing)."""
        return set()

    def to_dict(self):
        raise NotImplementedError

    @staticmethod
    def from_dict(data):
        kind = data.get("kind")
        cls = _STEP_TYPES.get(kind)
        if cls is None:
            raise ValueError(f"unknown pipeline step kind: {kind!r}")
        return cls.from_dict(data)


class FilterStep(PipelineStep):
    """A low-pass step: one :class:`FilterSpec` applied to chosen targets.

    ``targets`` is the set of scalar signal keys this step produces processed
    versions of (e.g. ``["cop_ap", "cop_ml", "fz"]``). Set ``markers=True`` to
    also low-pass the marker arrays with this step's spec. The step does not hold
    any data — it only describes *what* to produce; the :class:`Workspace`
    applies it lazily and caches the result.
    """

    kind = "filter"
    stage = "derive"

    def __init__(self, spec=None, targets=None, markers=False, enabled=True):
        self.spec = spec or FilterSpec()
        # Stored as a list to keep order stable for the UI / serialization, but
        # treated as a set for membership.
        self.targets = list(dict.fromkeys(targets or ()))
        self.markers = bool(markers)
        self.enabled = bool(enabled)

    def produces(self):
        """The processed scalar keys this step adds, e.g. ``{"cop_ap:filt", ...}``.

        One ``<target>:filt`` key per filtered target. (``MARKER_TARGET`` /
        ``markers=True`` filters the marker arrays in place on the marker clock,
        so it adds no new scalar catalog key and is not listed here.)
        """
        return {f"{key}{FILT_SUFFIX}" for key in self.targets}

    def requires(self):
        """The raw scalar keys this step reads — its filter targets themselves.

        e.g. a step filtering ``["cop_ap", "cop_ml"]`` requires those raw keys.
        They are part of the raw catalog so the lint never flags them, but
        declaring them keeps the contract honest (and lets a future derived
        target, e.g. filtering an ``angle:*`` signal, be checked).
        """
        return set(self.targets)

    def to_dict(self):
        return {
            "kind": self.kind,
            "spec": {
                "type": self.spec.type,
                "cutoff_hz": self.spec.cutoff_hz,
                "order": self.spec.order,
                "ripple_db": self.spec.ripple_db,
            },
            "targets": list(self.targets),
            "markers": self.markers,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data):
        s = data.get("spec", {})
        spec = FilterSpec(
            type=s.get("type", "Butterworth"),
            cutoff_hz=s.get("cutoff_hz", 10.0),
            order=s.get("order", 4),
            ripple_db=s.get("ripple_db", 0.5),
        )
        return cls(spec=spec, targets=data.get("targets", ()),
                   markers=bool(data.get("markers", False)),
                   enabled=bool(data.get("enabled", True)))


class DetectEventStep(PipelineStep):
    """An event-detection step: run a detector on one catalog signal -> events.

    Parallel to :class:`FilterStep`. Where FilterStep produces processed SIGNALS,
    this produces EVENTS — a label plus the *frame indices* (one or more) where
    the chosen signal does something. It only describes *what* to detect; the
    actual math lives in ``core.events`` and the per-file computation in
    :func:`core.events_compute.compute_detected_events` (which resolves ``input``
    through the Workspace, so ``"cop_ap:filt"`` works).

    Fields:
      - ``input``  — a catalog signal key (raw/processed/derived), e.g. ``"fz"``,
        ``"fz:filt"`` or ``"angle:Knee"``. The detector runs on this signal's
        values on the master clock. Ignored by ``method="frame"`` (a fixed-frame
        event needs no signal — ``input`` may be empty there).
      - ``label``  — the event name attached to every detected instance.
      - ``method`` — ``"threshold"`` | ``"peak"`` | ``"zero"`` | ``"frame"``.
      - ``params`` — method-specific knobs (a plain dict, persisted verbatim):
          threshold: {threshold, direction(rising|falling), min_distance_s, hysteresis}
          peak:      {kind(max|min), min_distance_s, prominence}
          zero:      {direction(both|up|down)}
          (``min_distance_s`` is the refractory in SECONDS, converted to frames at
          run time via the master clock; a legacy frame ``min_distance`` is still
          read for back-compat — see ``events_compute._resolve_min_distance_frames``)
          frame:     {frame(0-based index)}  -- a single fixed-frame event; the
                     manual "fixed frame" pin unified into the pipeline. No signal
                     is read, so ``input``/``scope``/``selector`` are irrelevant
                     (one instance => selector can't change the result).
      - ``selector`` — {mode(first|nth|range|all), n, lo, hi}; default ``first``
        keeps the old single-instance behaviour.
      - ``scope`` — optional ``[start_idx, end_idx]`` search window, or ``None``.
      - ``color`` — the line colour for this event's vertical lines, a hex
        string or ``None`` (a real field, NOT a detection knob): colour is purely
        cosmetic, so it must stay OUT of the detection cache token — recolouring
        an event must not force every file to re-detect. Older projects stored it
        in ``params["color"]``; :meth:`from_dict` migrates that into this field.
    """

    kind = "detect_event"
    stage = "detect"

    def __init__(self, input=None, label="", method="threshold", params=None,
                 selector=None, scope=None, color=None, enabled=True):
        self.input = input or ""
        self.label = label or ""
        self.method = method
        self.params = dict(params or {})
        self.selector = dict(selector or {"mode": "first"})
        # scope: None (whole trial), a legacy frame window [start, end], OR a dict
        # {"from": bound, "to": bound} where each bound is
        # {"type":"frame","frame":N} or {"type":"event","label":L,"instance":i}.
        self.scope = (dict(scope) if isinstance(scope, dict)
                      else (list(scope) if scope is not None else None))
        self.enabled = bool(enabled)
        # Backward-compat: an old step kept the colour inside params. Pull it out
        # so params holds detection knobs only (a clean cache token), preferring
        # an explicit ``color`` argument when both are present.
        legacy = self.params.pop("color", None)
        self.color = color if color is not None else legacy

    def produces(self):
        """The single event key this step adds: ``{"event:<label>"}``.

        Empty when the step has no label (an unfinished step adds nothing to the
        catalog). Events live in the ``event:`` namespace so they never collide
        with a same-named signal.
        """
        return {f"{EVENT_PREFIX}{self.label}"} if self.label else set()

    def requires(self):
        """The signal key this detector reads: ``{input}``.

        Empty for ``method="frame"`` (a fixed-frame event reads no signal — its
        ``input`` is irrelevant) or when ``input`` is blank. This is what lets
        the lint catch a detect step reading ``"fz:filt"`` before any filter step
        produced it.
        """
        if self.method == "frame" or not self.input:
            return set()
        return {self.input}

    def to_dict(self):
        return {
            "kind": self.kind,
            "input": self.input,
            "label": self.label,
            "method": self.method,
            "params": dict(self.params),
            "selector": dict(self.selector),
            "scope": (dict(self.scope) if isinstance(self.scope, dict)
                      else (list(self.scope) if self.scope is not None else None)),
            "color": self.color,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data):
        scope = data.get("scope")
        # ``color`` may be a top-level field (new) or buried in params (old): the
        # constructor's pop handles the params case, and an explicit top-level
        # ``color`` wins when present.
        return cls(
            input=data.get("input", ""),
            label=data.get("label", ""),
            method=data.get("method", "threshold"),
            params=data.get("params", {}),
            selector=data.get("selector", {"mode": "first"}),
            scope=scope,  # dict (event bounds) or legacy [start, end]; normalised in __init__
            color=data.get("color"),
            enabled=bool(data.get("enabled", True)),
        )


class TrajectoryStep(PipelineStep):
    """A COP-path step: produce the 2-D mean-centred statokinesigram.

    Where :class:`FilterStep` makes 1-D processed signals and
    :class:`DetectEventStep` makes events, this makes a 2-D *derived* product —
    the COP trajectory (statokinesigram): the ML(x)-AP(y) path of the COP about
    its own mean, plus the mean point. Because it is 2-D (a path, not a single
    series) it is NOT a ``:filt`` twin in the 1-D signal catalog; the UI exposes
    it as its own toggle in the PROCESSED section and draws it via
    :func:`core.trajectory.compute_trajectory`.

    Fields:
      - ``ap`` — the AP (y) signal key. Default ``"cop_ap"`` (a ``:filt`` key is
        fine — the Workspace resolves it through the pipeline's filtering).
      - ``ml`` — the ML (x) signal key. Default ``"cop_ml"``.

    Both default to raw COP, matching the biomech "mean-centred COP path"
    definition (2026-06-23).
    """

    kind = "trajectory"
    stage = "derive"

    def __init__(self, ap="cop_ap", ml="cop_ml", enabled=True):
        self.ap = ap or "cop_ap"
        self.ml = ml or "cop_ml"
        self.enabled = bool(enabled)

    def produces(self):
        """The 2-D derived product key: ``{"trajectory:<ml>x<ap>"}``.

        The trajectory is a 2-D path, not a 1-D ``:filt`` twin, so it gets its
        own ``trajectory:`` namespace key (built from its two source keys so two
        trajectory steps on different inputs don't collide). The UI exposes the
        path via its own toggle rather than this key, but declaring it keeps the
        dependency contract complete.
        """
        return {f"trajectory:{self.ml}x{self.ap}"}

    def requires(self):
        """The two COP signal keys this path is built from: ``{ap, ml}``."""
        return {self.ap, self.ml}

    def to_dict(self):
        return {"kind": self.kind, "ap": self.ap, "ml": self.ml,
                "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data):
        return cls(ap=data.get("ap", "cop_ap"), ml=data.get("ml", "cop_ml"),
                   enabled=bool(data.get("enabled", True)))


#: Catalog-key namespace prefix for computed scalar metrics.
METRIC_PREFIX = "metric:"


class MetricStep(PipelineStep):
    """A metric step: reduce one signal (over a window) to a scalar value.

    Where :class:`DetectEventStep` produces EVENTS, this produces a METRIC — a
    named scalar (or per-cycle array) added to the ``metric:`` catalog. The math
    lives in :mod:`core.metrics` (op registry) and the per-file computation in
    :func:`core.metrics_compute.compute_metric_step`.

    Fields:
      - ``input``  — a catalog signal key (``"angle:Knee"``, ``"fp1:cop"``,
        ``"fp1:fz"``, ``"fp1:fz:filt"`` …). For ``op="value_at_event"`` this is
        the signal sampled; for ``cop`` ops it is the plate COP key.
      - ``op``     — an op name from :data:`core.metrics.OP_INFO` (``max``/``min``/
        ``mean``/``range``/``std``/``rms`` · COP composites · ``value_at_event``).
      - ``name``   — the metric's display/catalog name (its identity, reusable).
      - ``segment``— ``None`` (whole trial) or ``[start_label, end_label]`` event
        labels: the metric is computed per cycle (each ``start`` paired with the
        next ``end``) and aggregated (mean ± SD over all cycles).
      - ``event``  — for ``op="value_at_event"``: the event key whose frame the
        signal is read at. Ignored otherwise.
      - ``input2`` — a SECOND input for binary ops (Round B2): a ``metric:<name>``
        reference for symmetry/ratio/phase-% / RSI ops (the "other limb" or the
        denominator metric). ``None`` for unary ops. Back-compat: defaults to
        ``None`` so an old project loads unchanged.
      - ``enabled``.

    An ``min``/``max`` metric also emits an event at its extremum frame (key
    ``event:<name>``) so a later step can reuse "the moment of the peak".
    """

    kind = "metric"
    stage = "metric"

    def __init__(self, input=None, op="max", name="", segment=None,
                 event=None, input2=None, enabled=True):
        self.input = input or ""
        self.op = op
        self.name = name or ""
        self.segment = list(segment) if segment else None
        self.event = event or None
        self.input2 = input2 or None
        self.enabled = bool(enabled)

    def emits_event(self):
        """True if this op also produces an ``event:<name>`` (argmax/argmin)."""
        from core.metrics import OP_INFO
        return bool(OP_INFO.get(self.op, {}).get("emits_event"))

    def produces(self):
        if not self.name:
            return set()
        out = {f"{METRIC_PREFIX}{self.name}"}
        if self.emits_event():
            out.add(f"{EVENT_PREFIX}{self.name}")
        return out

    def requires(self):
        req = set()
        # An event/reference op (spatiotemporal / symmetry / cadence) has no signal
        # input — its ``input`` is either unused (event op: the segment IS the
        # input) or a ``metric:`` reference, not a catalog signal. Only add
        # ``input`` to the data requirements when it is an actual signal key.
        from core.metrics import OP_INFO
        kind = OP_INFO.get(self.op, {}).get("input")
        if self.input and kind not in ("event", "metric"):
            req.add(self.input)
        if kind == "metric" and self.input:
            req.add(self.input if self.input.startswith(METRIC_PREFIX)
                    else f"{METRIC_PREFIX}{self.input}")
        if self.input2:
            req.add(self.input2 if self.input2.startswith(METRIC_PREFIX)
                    else f"{METRIC_PREFIX}{self.input2}")
        if self.op == "value_at_event" and self.event:
            req.add(f"{EVENT_PREFIX}{self.event}")
        if self.segment:
            req |= {f"{EVENT_PREFIX}{lbl}" for lbl in self.segment if lbl}
        return req

    def to_dict(self):
        return {"kind": self.kind, "input": self.input, "op": self.op,
                "name": self.name, "segment": list(self.segment) if self.segment else None,
                "event": self.event, "input2": self.input2, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data):
        seg = data.get("segment")
        return cls(input=data.get("input", ""), op=data.get("op", "max"),
                   name=data.get("name", ""),
                   segment=list(seg) if seg else None,
                   event=data.get("event"), input2=data.get("input2"),
                   enabled=bool(data.get("enabled", True)))


#: ComputeStep methods (the signal-math library). ``normalize`` is Phase 1
#: (kept for back-compat); the rest are the :mod:`core.signal_ops` building blocks.
#: Each maps to a transform of one (or, for magnitude, several) input signals into
#: a new derived signal. The UI's Add-step form offers these as the "Calculation".
COMPUTE_METHODS = ("normalize", "derivative", "integral", "magnitude", "abs",
                   "xcom")


class ComputeStep(PipelineStep):
    """A signal-deriving step: make a new signal from one (or more) signal(s).

    Methods (``method`` field):
      * ``normalize`` — ``output = input / by`` where ``by`` is a constant OR a
        ``metric:<name>`` reference (e.g. body mass for %BW). The original Phase-1
        method; kept working for back-compat.
      * ``derivative`` — time derivative of ``input`` (``params={"order": 1|2}``);
        order 1 = velocity (deg/s, etc.), order 2 = acceleration.
      * ``integral`` — running (cumulative) time integral of ``input``
        (``params={"sign": "all"|"pos"|"neg"}`` for braking/propulsive gating).
      * ``magnitude`` — Euclidean resultant of ``input`` and the extra
        ``inputs`` (2-3 component signals), e.g. resultant GRF from fx/fy/fz.
      * ``abs`` — element-wise absolute value ``|input|`` (unit preserved). Lets
        the user rectify a raw bipolar channel — e.g. ``|fp1:fz|`` to get a
        positive vertical GRF / impulse from the raw (down-negative) C3D Fz —
        without any global sign flip (the user controls sign explicitly).

    Fields:
      * ``input``  — the (primary) signal key.
      * ``by``     — normalize divisor: float constant OR ``"metric:<name>"`` ref.
        Ignored by non-normalize methods.
      * ``name``   — the output signal key (e.g. ``"fp1:fz_pctbw"``, ``"Knee_vel"``).
      * ``method`` — one of :data:`COMPUTE_METHODS`.
      * ``params`` — method-specific knobs (dict, persisted verbatim):
        derivative ``{"order": 1|2}``; integral ``{"sign": "all"|"pos"|"neg"}``.
      * ``inputs`` — extra input signal keys for ``magnitude`` (the components
        beyond ``input``). Empty for the single-input methods.
      * ``enabled``.

    Back-compat: ``params``/``inputs`` default to empty, so an old project saved
    with only ``input``/``by``/``name``/``method`` loads unchanged (method stays
    ``normalize``).
    """

    kind = "compute"
    stage = "derive"

    def __init__(self, input=None, by=1.0, name="", method="normalize",
                 params=None, inputs=None, enabled=True):
        self.input = input or ""
        self.by = by
        self.name = name or ""
        self.method = method
        self.params = dict(params or {})
        # Extra component inputs (magnitude); ordered + de-duplicated for stability.
        self.inputs = list(dict.fromkeys(inputs or ()))
        self.enabled = bool(enabled)

    def _by_is_ref(self):
        return isinstance(self.by, str) and self.by.startswith(METRIC_PREFIX)

    def produces(self):
        return {self.name} if self.name else set()

    def requires(self):
        req = {self.input} if self.input else set()
        # magnitude pulls in its extra component signals too.
        req |= {k for k in self.inputs if k}
        # ``by`` only matters for normalize (a metric reference there is a dep).
        if self.method == "normalize" and self._by_is_ref():
            req.add(self.by)
        return req

    def to_dict(self):
        return {"kind": self.kind, "input": self.input, "by": self.by,
                "name": self.name, "method": self.method,
                "params": dict(self.params), "inputs": list(self.inputs),
                "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data):
        return cls(input=data.get("input", ""), by=data.get("by", 1.0),
                   name=data.get("name", ""), method=data.get("method", "normalize"),
                   params=data.get("params", {}), inputs=data.get("inputs", ()),
                   enabled=bool(data.get("enabled", True)))


#: Catalog-key namespace prefix for joint-angle signals (model output).
ANGLE_PREFIX = "angle:"


class ComputeAngleStep(PipelineStep):
    """A joint-angle step: compute the assigned kinematic model's angles.

    This is the pipeline's way of saying "derive joint angles from markers" — the
    step that makes the ``angle:<JOINT>`` signals exist. Per the redesign
    principle *the pipeline is the sole source of all derived data*, joint angles
    are no longer auto-computed: they appear only when this step is in the recipe.

    SCOPE NOTE (engine vs UI split): the angle *math* and the *model resolution*
    (which model object, calibrated from which static, with which label map and
    zero-to-standing offsets) live in :mod:`core.marker_model` + the UI's model
    bookkeeping — NOT here. This step is the recipe *marker / plumbing*: it
    records that angles should be produced (and, optionally, the joint names the
    model yields, for an exact dependency lint). The executor reads the
    already-computed ``angle_result`` the UI injects; the UI gates that
    computation on the presence of this step (``Pipeline.has_angle_step``).

    Fields:
      - ``joints`` — optional list of joint-angle names the model produces (e.g.
        ``["RKNEE_FE", "LKNEE_FE"]``). Used only to make ``produces()`` exact for
        the dependency lint; may be empty (then bare ``angle:*`` keys are treated
        as possibly-present by the lint, which never false-warns on them).
      - ``enabled``.
    """

    kind = "compute_angle"
    stage = "derive"

    def __init__(self, joints=None, enabled=True):
        # Stored ordered + de-duplicated (stable for UI / serialization).
        self.joints = list(dict.fromkeys(joints or ()))
        self.enabled = bool(enabled)

    def produces(self):
        """The ``angle:<name>`` keys this step adds (only the declared joints).

        Empty when no joints are declared — the joint set is defined by the model
        the UI resolves, not by the recipe, so an undeclared step still "produces
        angles" conceptually; the lint just can't name them. Bare ``angle:*`` keys
        are non-derived (see :func:`_is_derived_key`), so a later step reading one
        is never false-flagged even without an explicit declaration here.
        """
        return {f"{ANGLE_PREFIX}{name}" for name in self.joints}

    def requires(self):
        """Reads no catalog signal — angles come from markers + the model, which
        the UI supplies out-of-band (not a catalog key)."""
        return set()

    def to_dict(self):
        return {"kind": self.kind, "joints": list(self.joints),
                "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data):
        return cls(joints=data.get("joints", ()),
                   enabled=bool(data.get("enabled", True)))


NORMALIZE_MODES = ("cycle", "window", "trial")


class NormalizeStep(PipelineStep):
    """Time-normalize one signal to 0-100% phase per epoch (the ``normalize``
    stage). Produces a per-trial epoch matrix consumed by the cross-trial
    ensemble panel; see core.normalize / core.ensemble.

    Fields:
      - ``input``       — a catalog signal key (``angle:R_KNEE_FE``, ``fz:filt``).
      - ``name``        — output name; the artifact is ``norm:<name>``.
      - ``mode``        — ``"cycle"`` (consecutive ``event``) | ``"window"``
                          (``start_event`` -> ``end_event``) | ``"trial"`` (whole).
      - ``event``       — start label for ``cycle`` mode.
      - ``start_event`` / ``end_event`` — labels for ``window`` mode.
      - ``points``      — phase nodes (default 101).
    """

    kind = "normalize"
    stage = "normalize"

    def __init__(self, input=None, name="", mode="cycle", event=None,
                 start_event=None, end_event=None, points=101, enabled=True):
        self.input = input or ""
        self.name = name or ""
        self.mode = mode if mode in NORMALIZE_MODES else "cycle"
        self.event = event or ""
        self.start_event = start_event or ""
        self.end_event = end_event or ""
        try:
            self.points = int(points)
        except (TypeError, ValueError):
            self.points = 101
        if self.points < 2:
            self.points = 101
        self.enabled = bool(enabled)

    def produces(self):
        return {f"norm:{self.name}"} if self.name else set()

    def requires(self):
        req = set()
        if self.input:
            req.add(self.input)
        if self.mode == "cycle" and self.event:
            req.add(f"{EVENT_PREFIX}{self.event}")
        if self.mode == "window":
            if self.start_event:
                req.add(f"{EVENT_PREFIX}{self.start_event}")
            if self.end_event:
                req.add(f"{EVENT_PREFIX}{self.end_event}")
        return req

    def to_dict(self):
        return {"kind": self.kind, "input": self.input, "name": self.name,
                "mode": self.mode, "event": self.event,
                "start_event": self.start_event, "end_event": self.end_event,
                "points": self.points, "enabled": self.enabled}

    @staticmethod
    def from_dict(data):
        return NormalizeStep(
            input=data.get("input"), name=data.get("name", ""),
            mode=data.get("mode", "cycle"), event=data.get("event"),
            start_event=data.get("start_event"), end_event=data.get("end_event"),
            points=data.get("points", 101), enabled=data.get("enabled", True))


#: kind -> step class, for from_dict dispatch. Extended as new step types land.
_STEP_TYPES = {FilterStep.kind: FilterStep, DetectEventStep.kind: DetectEventStep,
               TrajectoryStep.kind: TrajectoryStep, MetricStep.kind: MetricStep,
               ComputeStep.kind: ComputeStep,
               ComputeAngleStep.kind: ComputeAngleStep,
               NormalizeStep.kind: NormalizeStep}


class Pipeline:
    """An ordered, serializable list of analysis steps (the shared recipe).

    Empty by default = raw (no processing), which is the new default after the
    global filter toggle was retired. The UI holds one of these and injects it
    into the workspace / analysis paths.
    """

    def __init__(self, steps=None):
        self.steps = list(steps or ())

    # -- editing -----------------------------------------------------------
    def add(self, step):
        self.steps.append(step)
        return step

    def remove(self, index):
        del self.steps[index]

    def move(self, index, new_index):
        """Move the step at ``index`` to ``new_index`` (clamped, order-preserving)."""
        n = len(self.steps)
        if n == 0:
            return
        index = max(0, min(index, n - 1))
        new_index = max(0, min(new_index, n - 1))
        if index == new_index:
            return
        step = self.steps.pop(index)
        self.steps.insert(new_index, step)

    def clear(self):
        self.steps = []

    def __len__(self):
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    # -- derived views (used by catalog / workspace) -----------------------
    #
    # NOTE on enabled: the accessors below are the *execution* views — they feed
    # the catalog/workspace/event computation, so they DROP disabled steps (a
    # disabled step must not affect any numbers). The *display* view
    # :meth:`steps_by_stage` is the opposite: it KEEPS disabled steps so the UI
    # can render (and let the user re-enable) them.
    def filter_steps(self):
        """Enabled :class:`FilterStep` steps, in order (execution view)."""
        return [s for s in self.steps
                if isinstance(s, FilterStep) and s.enabled]

    def detect_event_steps(self):
        """Enabled :class:`DetectEventStep` steps, in order (execution view).

        Order matters for dependency: a detect step should sit after the filter
        step that produces its ``input`` signal (if it uses a ``:filt`` key); the
        Workspace falls back to raw when the filter step is absent, so an
        out-of-order recipe still resolves rather than crashing. Disabled steps
        are excluded so toggling one off removes its events (and flips the
        detection cache token via :func:`core.events_compute._detect_token`).
        """
        return [s for s in self.steps
                if isinstance(s, DetectEventStep) and s.enabled]

    def trajectory_steps(self):
        """Enabled :class:`TrajectoryStep` steps, in order (execution view).

        Order matters for dependency the same way as detect steps: a trajectory
        step on a ``:filt`` COP key should sit after the filter step that makes
        it (the Workspace falls back to raw if absent, so it still resolves).
        """
        return [s for s in self.steps
                if isinstance(s, TrajectoryStep) and s.enabled]

    def metric_steps(self):
        """Enabled :class:`MetricStep` steps, in order (execution view)."""
        return [s for s in self.steps
                if isinstance(s, MetricStep) and s.enabled]

    def compute_steps(self):
        """Enabled :class:`ComputeStep` steps, in order (execution view)."""
        return [s for s in self.steps
                if isinstance(s, ComputeStep) and s.enabled]

    def compute_angle_steps(self):
        """Enabled :class:`ComputeAngleStep` steps, in order (execution view)."""
        return [s for s in self.steps
                if isinstance(s, ComputeAngleStep) and s.enabled]

    def compute_step_for(self, name):
        """The enabled :class:`ComputeStep` whose output key is ``name``, or None.

        Lets the :class:`Workspace` resolve a ComputeStep-produced signal key
        on demand (the same way :meth:`filter_spec_for` resolves a ``:filt``
        key). When several enabled steps share an output name the *last* one
        wins (later steps override earlier ones — same rule as filters)."""
        out = None
        for step in self.compute_steps():
            if step.name == name:
                out = step
        return out

    def has_angle_step(self):
        """True if an enabled :class:`ComputeAngleStep` is in the recipe.

        The UI uses this to decide whether to compute the kinematic model's joint
        angles at all — "the pipeline is the sole source", so angles exist only
        when this returns True (no auto-compute fallback)."""
        return bool(self.compute_angle_steps())

    # -- stage views (used by the UI for badges / grouping) ----------------
    def steps_by_stage(self):
        """``{stage: [(index, step), ...]}`` for *display* — every stage key.

        Each step is paired with its original index in :attr:`steps` (so the UI
        can address the right row for edit/move/remove). Buckets follow
        :data:`STAGE_ORDER`, and *all* stage keys are present even when empty
        (so the UI can show place-holder, disabled menu entries for the
        not-yet-implemented stages).

        This is a DISPLAY / classification view only. The bucket order is NOT
        the execution order (execution = physical list order, and stages may
        interleave) and the bucketing is purely for badges/grouping. It also
        includes disabled steps (the execution accessors above are what drop
        them) so the UI can render and re-enable them.
        """
        out = {stage: [] for stage in STAGE_ORDER}
        for idx, step in enumerate(self.steps):
            stage = getattr(step, "stage", "derive")
            out.setdefault(stage, []).append((idx, step))
        return out

    def data_dependency_warnings(self, raw_keys=None):
        """``[(index, message), ...]`` for steps that read a not-yet-made key.

        Read-only lint (NEVER raises / never blocks execution — the pipeline
        always falls back to raw). It replaces the old ``stage_order_warnings``:
        the 2nd-round Visual3D re-check retired the stage-rank check (stages may
        interleave freely — a ``Compute -> Detect -> Compute -> Metric -> Detect``
        recipe is valid), leaving only the real constraint, **data dependency**.

        Algorithm — accumulate a catalog walking top-to-bottom:

          - ``available`` starts as the raw catalog keys (the original signals
            that always exist). ``raw_keys`` may be passed in (the dataset's raw
            catalog) for an exact check; when it is ``None`` we don't know the
            dataset, so we only flag keys that *must* come from a pipeline step
            (DERIVED keys — ``:filt`` / ``event:`` / ``trajectory:`` / ``metric:``
            etc.) and treat bare keys (``fz``, ``angle:Knee``, ``marker:*``) as
            possibly-raw to avoid false positives.
          - For each enabled step, top-to-bottom: any ``requires()`` key that is
            not in ``available`` (and, when ``raw_keys`` is None, is a derived
            key) is reported as ``(index, message)``. Then ``available`` gains
            that step's ``produces()`` — so a later step CAN depend on it.

        Disabled steps are ignored on both sides (they don't run, so they neither
        produce nor consume). Messages are English (UI shows them as ⚠ chips).
        """
        exact = raw_keys is not None
        available = set(raw_keys) if exact else set()
        warnings = []
        for idx, step in enumerate(self.steps):
            if not getattr(step, "enabled", True):
                continue
            for key in step.requires():
                if key in available:
                    continue
                # Without a known raw catalog, only derived keys (those a step
                # must have produced) are provably missing; bare keys might be raw.
                if not exact and not _is_derived_key(key):
                    continue
                warnings.append((idx, f"'{key}' is not produced before this step"))
            available |= step.produces()
        return warnings

    #: Back-compat alias for the old lint name. No live caller remains (the UI was
    #: migrated to ``data_dependency_warnings``); kept as a thin, test-pinned shim
    #: so any saved reference / external import to the old name still resolves.
    #: Same read-only contract, so the alias is safe.
    stage_order_warnings = data_dependency_warnings

    def filter_spec_for(self, key):
        """The :class:`FilterSpec` that produces ``<key>:filt``, or ``None``.

        ``key`` is a *raw* scalar key (e.g. ``"cop_ap"``). When several filter
        steps target the same key, the *last* one wins (later steps in the
        recipe override earlier ones — same mental model as re-running a stage).
        Returns ``None`` if no step targets ``key`` (=> that signal stays raw).
        """
        spec = None
        for step in self.filter_steps():
            if key in step.targets:
                spec = step.spec
        return spec

    def marker_filter_spec(self):
        """The :class:`FilterSpec` for marker arrays, or ``None`` if untargeted.

        Last marker-targeting filter step wins, mirroring :meth:`filter_spec_for`.
        """
        spec = None
        for step in self.filter_steps():
            if step.markers:
                spec = step.spec
        return spec

    def compute_keys(self):
        """All :class:`ComputeStep` output names this pipeline produces, in step
        order (deduplicated, first-seen). These are catalog signal keys the
        :class:`Workspace` can resolve on demand (graph / value table)."""
        out = []
        seen = set()
        for step in self.compute_steps():
            if step.name and step.name not in seen:
                seen.add(step.name)
                out.append(step.name)
        return out

    def filtered_keys(self):
        """All processed scalar keys this pipeline produces, in step order.

        Deduplicated while preserving first-seen order so the catalog lists each
        ``<key>:filt`` once even if multiple steps target it.
        """
        out = []
        seen = set()
        for step in self.filter_steps():
            # Iterate ``targets`` (ordered) rather than ``produces()`` (a set) so
            # the catalog lists each ``<key>:filt`` in a stable, first-seen order.
            for key in step.targets:
                fkey = f"{key}{FILT_SUFFIX}"
                if fkey not in seen:
                    seen.add(fkey)
                    out.append(fkey)
        return out

    # -- persistence -------------------------------------------------------
    def to_dict(self):
        return {"steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, data):
        """Rebuild from :meth:`to_dict`. ``None``/empty => empty pipeline (raw).

        Unknown step kinds (from a newer version) are skipped rather than
        crashing, so a forward-saved project still opens.
        """
        if not data:
            return cls()
        steps = []
        for sd in data.get("steps", []):
            try:
                steps.append(PipelineStep.from_dict(sd))
            except ValueError:
                continue
        return cls(steps)
