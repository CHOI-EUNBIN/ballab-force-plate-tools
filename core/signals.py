"""Signal registry — one catalog of every plottable time series in a dataset.

This is the shared foundation for events, the (future) analysis pipeline, graphs
and data tables: each of them asks this module "what signals exist?" and "give me
this signal's values". Markers and joint angles live on the motion-capture clock,
so every signal is returned resampled onto the dataset's master clock
(``dataset["time"]``, usually the force-plate clock) — callers (e.g. event
detection) can then index all channels with the same frame numbers.

Pure functions, no Qt: the catalog/series take the already-computed display
arrays so this stays UI-free and headless-testable.

Key scheme (stable strings, safe to persist in saved events):
  - "time", "cop", "cop_ap", "cop_ml", "fx", "fy", "fz"   (force-clock channels)
  - "angle:<NAME>"            (joint angle, resampled)
  - "marker:<LABEL>:<AXIS>"   (AXIS 0/1/2 = X/Y/Z, resampled)

Filter (Phase A): a :class:`FilterSpec` turns the scattered low-pass parameters
into one object, and a :class:`Workspace` wraps a dataset to serve raw signals
*and* their filtered derivatives ("<key>:filt") through one cached interface, so
the figure / value-cards / stats consumers compute each signal once and share it.
"""

from dataclasses import dataclass

import numpy as np

from core import signal_ops
from core.marker_model import angle_label
from core.signal_proc import apply_lowpass, filter_marker_data

_AXES = (("X", 0), ("Y", 1), ("Z", 2))

#: Suffix that marks a filtered derivative of a raw key, e.g. "cop_ap:filt".
FILT_SUFFIX = ":filt"

#: Human display label for the fixed (non-parametric) raw keys. This is the
#: single source of truth for those labels: ``signal_catalog`` and
#: :func:`label_for` both read it, so the catalog and a step/axis label built
#: from a bare key always agree (UI professionalization: no internal keys leak).
_FIXED_LABELS = {
    "time": "Time (s)",
    "cop": "COP",
    # The raw COP channels are shown as plate-local X/Y (as they came from the
    # file), not AP/ML — plate orientation varies, so a global AP/ML mapping is
    # not meaningful. cop_ap holds the X channel (-My/Fz), cop_ml the Y (Mx/Fz).
    "cop_ap": "COP X",
    "cop_ml": "COP Y",
    "fz": "Fz",
    "fx": "Fx",
    "fy": "Fy",
}

#: Physical unit (string) for the fixed raw keys, per the biomech unit table
#: (2026-06-23). "" = dimensionless / unknown. The parametric families
#: (angle:* / marker:*) are handled in :func:`unit_for`.
_FIXED_UNITS = {
    "time": "s",
    "cop": "mm",
    "cop_ap": "mm",
    "cop_ml": "mm",
    "fz": "N",
    "fx": "N",
    "fy": "N",
}


#: Force/COP components a per-plate ``fp{n}:<comp>`` key may carry. ``cop`` is the
#: derived resultant; the rest are stored arrays. All are valid ``_FIXED_LABELS``
#: keys so a plate label reuses the bare label ("FP2 " + "COP AP").
_PLATE_COMPS = ("fx", "fy", "fz", "cop_ap", "cop_ml", "cop")


def _split_plate(key):
    """Split a per-plate key ``"fp{n}:<comp>"`` into ``(n:int, comp:str)``.

    Returns ``(None, None)`` for any key that is not a recognised per-plate
    force/COP key, so callers can fall through to their other branches.
    """
    if not key.startswith("fp"):
        return None, None
    head, _, comp = key.partition(":")
    num = head[2:]
    if comp in _PLATE_COMPS and num.isdigit():
        return int(num), comp
    return None, None


def _split_gait(key):
    """Split a gait key into ``(side, point, (axis, lab))`` or ``(None, None, None)``.

    Accepts both the original pelvis-relative form ``"gait:<SIDE>_<point>_ap"``
    and the new lab-frame form ``"gait:<SIDE>_<point>_<ap|ml>_lab"``.
    Returns a three-tuple:
      - ``side``: e.g. ``"R"`` or ``"L"``
      - ``point``: ``"heel"`` or ``"toe"``
      - ``(axis, lab)``: axis is ``"ap"`` or ``"ml"``; lab is ``True`` when the
        ``_lab`` suffix is present (absolute lab-frame), ``False`` for the
        original pelvis-relative series.
    Returns ``(None, None, None)`` for any unrecognised key so callers can
    fall through to their other branches."""
    if not key.startswith("gait:"):
        return None, None, None
    body = key[len("gait:"):]
    lab = body.endswith("_lab")
    if lab:
        body = body[: -len("_lab")]
    parts = body.split("_")
    if len(parts) == 3 and parts[1] in ("heel", "toe") and parts[2] in ("ap", "ml"):
        return parts[0], parts[1], (parts[2], lab)   # (side, point, (axis, lab))
    return None, None, None


def _base_label(key):
    """Human label for a *raw* (non-``:filt``) key — the catalog label rule.

    ``time``/``cop``/``fx`` … from :data:`_FIXED_LABELS`; ``angle:<NAME>`` ->
    the compact clinical label from :func:`core.marker_model.angle_label`
    (e.g. ``angle:R_KNEE_angle_FE`` -> ``"∠ R Knee F/E"``); a non-JCS angle name
    falls back to the name itself (``angle:Knee`` -> ``"∠ Knee"``).
    ``marker:<LABEL>:<AXIS>`` -> ``"<LABEL> <AXIS>"``. An unrecognised key falls
    back to itself so nothing crashes on a stray key.
    """
    if key in _FIXED_LABELS:
        return _FIXED_LABELS[key]
    plate, comp = _split_plate(key)
    if plate is not None:
        return f"FP{plate} {_FIXED_LABELS.get(comp, comp)}"
    if key.startswith("angle:"):
        return f"∠ {angle_label(key.split(':', 1)[1])}"
    if key.startswith("marker:"):
        body = key[len("marker:"):]
        label, ax_name = body.rsplit(":", 1)
        return f"{label} {ax_name}"
    if key.startswith("gait:"):
        side, point, proj = _split_gait(key)
        if side is not None:
            axis, lab = proj
            return f"{side} {point} ({axis.upper()}{', lab' if lab else ''})"
    if key.startswith("com:"):
        ax = key.split(":", 1)[1]
        return f"COM {ax.upper()}"
    return key


def label_for(key):
    """Human display name for any signal ``key`` (works without a dataset).

    Single source of truth shared with :func:`signal_catalog`: same labels, so a
    step/axis label built from a bare key matches the catalog entry. A ``:filt``
    key appends " (filtered)" to its base label, exactly like the catalog.
    Examples: ``cop_ap`` -> "COP AP", ``fx`` -> "Fx", ``angle:Knee`` -> "∠ Knee",
    ``marker:HEEL:Z`` -> "HEEL Z", ``cop_ap:filt`` -> "COP AP (filtered)".
    """
    if key.endswith(FILT_SUFFIX):
        base = key[: -len(FILT_SUFFIX)]
        return f"{_base_label(base)} (filtered)"
    return _base_label(key)


def unit_for(key):
    """Physical unit string for a signal ``key`` (biomech unit table).

    ``time`` -> "s"; ``cop``/``cop_ap``/``cop_ml`` and ``marker:*`` -> "mm";
    ``fx``/``fy``/``fz`` -> "N"; ``angle:*`` -> "deg". A ``:filt`` derivative
    keeps its base key's unit (filtering does not change units). Unknown keys
    return "" so a label can be built without a unit suffix.
    """
    if key.endswith(FILT_SUFFIX):
        key = key[: -len(FILT_SUFFIX)]
    if key in _FIXED_UNITS:
        return _FIXED_UNITS[key]
    plate, comp = _split_plate(key)
    if plate is not None:
        return "N" if comp in ("fx", "fy", "fz") else "mm"
    if key.startswith("angle:"):
        return "deg"
    if key.startswith("marker:"):
        return "mm"
    if key.startswith("gait:"):
        return "mm"
    if key.startswith("com:"):
        return "mm"
    return ""


def cop_resultant(ap, ml):
    """Resultant COP distance (RD) about the mean COP, the posturography standard.

    RD[n] = sqrt( (AP[n] - mean(AP))^2 + (ML[n] - mean(ML))^2 ): the instantaneous
    distance of the COP from its own mean ("sway centre"), in mm. The mean is
    subtracted so the series measures *sway about the centre*, not distance from
    the (arbitrary) force-plate origin — this is the definition used to derive
    Mean Distance / RMS Distance in Prieto et al. 1996 (IEEE TBME), and matches
    the AP/ML metrics in ``core.metrics`` which all centre on the mean.

    NaN-safe: the mean ignores NaN gaps. Operates on the full series; for a
    windowed analysis the caller passes the already-sliced AP/ML.
    """
    ap = np.asarray(ap, dtype=float)
    ml = np.asarray(ml, dtype=float)
    ap_c = ap - np.nanmean(ap)
    ml_c = ml - np.nanmean(ml)
    return np.sqrt(ap_c * ap_c + ml_c * ml_c)


# Backward-compatible alias (old private name); kept so any external import or
# saved reference keeps working. Same standard (mean-subtracted) definition now.
_cop_resultant = cop_resultant


def _com_world(angle_result):
    """The whole-body COM (F,3) world-frame trajectory from a model result, or a
    clear ValueError when it is unavailable.

    The COM lives at ``angle_result["com"]["com"]`` (de Leva 1996, written by
    :func:`core.marker_model.MarkerModel.apply` via :func:`core.com.body_com`).
    Raises when there is no model result, no COM block, or an empty (0,3) COM
    (a model with no mass-bearing segments) — the pipeline is the sole source, so
    the caller surfaces "no signal" rather than a wrong number / wrong shape.
    """
    if not angle_result:
        raise ValueError("no model result for com channel")
    com_block = angle_result.get("com")
    if not com_block:
        raise ValueError("no COM in model result")
    com = np.asarray(com_block.get("com"), dtype=float)
    if com.ndim != 2 or com.shape[0] == 0 or com.shape[1] != 3:
        raise ValueError("COM trajectory is empty / malformed")
    return com


def _resample(src_t, vals, dst_t):
    """Linear-interpolate ``vals`` (sampled at ``src_t``) onto ``dst_t``."""
    src_t = np.asarray(src_t, dtype=float)
    vals = np.asarray(vals, dtype=float)
    dst_t = np.asarray(dst_t, dtype=float)
    if src_t.shape == dst_t.shape and np.array_equal(src_t, dst_t):
        return vals
    if len(src_t) == 0:
        return np.full(dst_t.shape, np.nan)
    return np.interp(dst_t, src_t, vals)


@dataclass(frozen=True)
class FilterSpec:
    """One low-pass filter, as a single value object.

    Collects the parameters that used to be passed around loose (``cutoff_hz``,
    ``order``, ``filter_type``, ``ripple_db``) so a caller can hand "the filter"
    to the workspace as one thing. ``frozen=True`` makes it hashable, so it can
    serve as part of a cache key.

    - :meth:`apply` low-passes a 1-D scalar series (wraps ``apply_lowpass``).
    - :meth:`apply_marker` low-passes a ``(M, F, 3)`` marker array, NaN-safe
      (wraps ``filter_marker_data``).

    Both are thin wrappers: the actual filtering still lives in
    ``core.signal_proc`` and behaves bit-for-bit as before.
    """

    type: str = "Butterworth"
    cutoff_hz: float = 10.0
    order: int = 4
    ripple_db: float = 0.5

    def apply(self, vals, fs):
        """Low-pass a 1-D scalar series sampled at ``fs`` Hz."""
        return apply_lowpass(
            vals, self.cutoff_hz, fs, self.order, self.type, self.ripple_db
        )

    def apply_marker(self, data, fs):
        """Low-pass a ``(M, F, 3)`` marker array (NaN-safe gaps preserved)."""
        return filter_marker_data(
            data, fs, self.cutoff_hz, self.order, self.type
        )

    def cache_key(self):
        """Hashable tuple identifying this filter (rounded like the UI cache)."""
        return (self.type, round(float(self.cutoff_hz), 4), int(self.order),
                round(float(self.ripple_db), 4))


def _validate_time(dataset):
    """The master clock as a validated 1-D float array, or a clear ValueError.

    Catches broken-clock bugs at the module boundary (a missing / multi-dimensional
    / backwards ``time`` axis) instead of letting them surface as a cryptic KeyError
    or wrong numbers deep inside a detector. Empty / single-sample clocks are short,
    not broken, so they pass (monotonicity is vacuous below 2 samples).
    """
    if "time" not in dataset:
        raise ValueError("dataset is missing the 'time' axis (the master clock)")
    t = np.asarray(dataset["time"], dtype=float)
    if t.ndim != 1:
        raise ValueError(f"dataset 'time' must be 1-D, got {t.ndim}-D")
    if t.size >= 2 and np.any(np.diff(t) < 0):
        raise ValueError("dataset 'time' must be monotonic (non-decreasing); "
                         "the clock goes backwards")
    return t


class Workspace:
    """A dataset wrapped so every signal is served through one cached interface.

    Holds the master clock and the display arrays (markers / joint angles) once,
    and answers :meth:`series` for both raw keys and their filtered derivatives
    ("<key>:filt"). Results are cached per key, so the three analysis consumers
    (figure / value cards / stats) that ask for the same signal only pay for it
    once. UI-free — the UI builds a :class:`FilterSpec` from its settings and
    passes it in.

    Two ways to supply filtering, in priority order:
      - ``pipeline``: a ``core.pipeline.Pipeline`` whose FilterStep(s) decide,
        per signal key, which :class:`FilterSpec` (if any) produces "<key>:filt".
        Different keys can have different cutoffs (one step per cutoff). This is
        the C1 path — the single source of truth.
      - ``filter_spec``: a single legacy spec applied to *every* "<key>:filt"
        (the Phase A/B behaviour). Used only when ``pipeline`` is None.

    With neither (the default, and the case of a key no filter step targets),
    "<key>:filt" returns the raw series unchanged (same shape, same values).
    """

    def __init__(self, dataset, marker_disp=None, angle_result=None,
                 filter_spec=None, fs=None, pipeline=None, metrics=None):
        self.dataset = dataset
        self.marker_disp = marker_disp
        self.angle_result = angle_result
        self.filter_spec = filter_spec
        self.pipeline = pipeline
        # Bare-name -> value for resolving a ``metric:`` normalise divisor outside
        # a full pipeline run (e.g. graphing a "÷ body weight" signal). The UI
        # seeds the subject quantities mass/bodyweight/height here; a user-defined
        # MetricStep reference stays run-only (absent from this dict -> raises).
        self._metrics = dict(metrics or {})
        # Master clock + scalar sampling rate (for scalar filtering). Default
        # mirrors the old inline ``dataset.get("fs", 1000.0)``.
        self.time = _validate_time(dataset)
        if fs is None:
            fs = dataset.get("fs", 1000.0)
        self.fs = float(fs)
        self._cache = {}
        self._unit_cache = {}     # ComputeStep output key -> derived unit string
        self._resolving = set()   # keys currently being computed (cycle guard)

    # -- catalog passthrough (same content as the module function) ----------
    def catalog(self):
        return signal_catalog(self.dataset, self.marker_disp, self.angle_result,
                              self.pipeline)

    def _spec_for(self, base):
        """The FilterSpec that produces ``<base>:filt``, or None.

        Pipeline (per-key) takes priority; otherwise the legacy single spec.
        """
        if self.pipeline is not None:
            return self.pipeline.filter_spec_for(base)
        return self.filter_spec

    def _marker_spec(self):
        if self.pipeline is not None:
            return self.pipeline.marker_filter_spec()
        return self.filter_spec

    # -- series ------------------------------------------------------------
    def series(self, key):
        """Values for ``key`` on the master clock.

        Resolution order (first match wins):
          1. raw key / ``angle:*`` / ``marker:*`` — :func:`signal_series`;
          2. ``<key>:filt`` — the filtered derivative of the base key;
          3. a :class:`ComputeStep` output name in the pipeline — computed
             on demand from the step's input(s) via :mod:`core.signal_ops`
             (the same math :func:`core.run._run_compute` runs), so a Compute
             signal is plottable / tabulatable without a full pipeline run.

        A ComputeStep input may itself be a ``:filt`` key or another Compute
        output, so this method recurses through :meth:`series`; a cycle guard
        (``self._resolving``) turns a self/mutually-referencing recipe into a
        clean ``ValueError`` instead of a stack overflow. A ComputeStep that
        cannot be resolved here (e.g. ``normalize`` whose divisor is a
        ``metric:`` reference — metrics only exist during a pipeline run) raises
        ``ValueError`` so the caller can show it as empty/NaN rather than a wrong
        number. Results are cached per key.
        """
        if key in self._cache:
            return self._cache[key]
        if key.endswith(FILT_SUFFIX):
            base = key[: -len(FILT_SUFFIX)]
            out = self._filtered(base)
        else:
            try:
                out = signal_series(self.dataset, key, self.marker_disp,
                                    self.angle_result)
            except ValueError:
                # Not a raw/angle/marker signal — maybe a ComputeStep output.
                out = self._computed(key)
        self._cache[key] = out
        return out

    def _computed(self, key):
        """Compute a ComputeStep-produced signal ``key`` on demand, or raise.

        Mirrors :func:`core.run._run_compute` but resolves inputs through
        :meth:`series` (so chained Compute/``:filt`` inputs work) and tracks a
        derived unit (cached in ``self._unit_cache``). Raises ``ValueError`` when
        the pipeline has no such step, when an input is unresolvable, or when the
        method is run-only (``normalize`` by a ``metric:`` reference).
        """
        step = None
        if self.pipeline is not None:
            step = self.pipeline.compute_step_for(key)
        if step is None or not step.input:
            raise ValueError(f"channel unavailable: {key}")
        if key in self._resolving:
            raise ValueError(f"circular compute reference: {key}")
        self._resolving.add(key)
        try:
            src = np.asarray(self.series(step.input), dtype=float)
            method = getattr(step, "method", "normalize")
            base_unit = self.unit_for_key(step.input)
            params = getattr(step, "params", {}) or {}

            if method == "abs":
                out = signal_ops.absval(src)
                unit = signal_ops.derive_unit(base_unit, "absval")
            elif method == "derivative":
                order = int(params.get("order", 1) or 1)
                out = signal_ops.derivative(src, self.time, order=order)
                unit = signal_ops.derive_unit(base_unit, "derivative", order=order)
            elif method == "integral":
                sign = params.get("sign", "all") or "all"
                out = signal_ops.integral(src, self.time, kind="cumulative", sign=sign)
                unit = signal_ops.derive_unit(base_unit, "integral")
            elif method == "magnitude":
                comps = [src]
                for ik in getattr(step, "inputs", ()):
                    if ik:
                        comps.append(np.asarray(self.series(ik), dtype=float))
                out = signal_ops.magnitude(*comps)
                unit = signal_ops.derive_unit(base_unit, "magnitude")
            elif method == "xcom":
                out = signal_ops.xcom(src, self.time,
                                      length_m=params.get("length_m"))
                unit = signal_ops.derive_unit(base_unit, "xcom")
            elif method == "normalize":
                by = step.by
                if isinstance(by, str):
                    # A ``metric:`` divisor. Subject quantities (mass/bodyweight/
                    # height) are seeded into ``self._metrics`` by the UI and ARE
                    # resolvable here; a user-defined MetricStep reference is not
                    # (it only exists during a pipeline run).
                    name = by.split(":", 1)[1] if by.startswith("metric:") else by
                    val = self._metrics.get(name)
                    if val is None:
                        raise ValueError(
                            f"compute '{key}' normalises by a metric reference "
                            f"({by!r}); only resolvable in a pipeline run")
                    by = float(val)
                by = float(by)
                if by == 0:
                    raise ValueError(f"compute '{key}' divides by zero")
                out = src / by
                unit = signal_ops.derive_unit(base_unit, "normalize")
            else:
                raise ValueError(f"unknown compute method: {method!r}")
        finally:
            self._resolving.discard(key)
        self._unit_cache[key] = unit
        return out

    def unit_for_key(self, key):
        """Physical unit string for ``key`` — a ComputeStep-derived unit when we
        have computed one, else the static catalog unit (:func:`unit_for`).

        Computing a ComputeStep output first (via :meth:`series`) populates its
        derived unit; calling this before the series is computed falls back to
        :func:`unit_for` (which returns "" for an unknown derived key)."""
        if key in self._unit_cache:
            return self._unit_cache[key]
        return unit_for(key)

    def _filtered(self, base):
        raw = self.series(base)
        spec = self._spec_for(base)
        if spec is None:
            return raw
        # Markers/angles are already resampled onto the master clock by
        # signal_series; we low-pass the resulting scalar series at self.fs.
        return spec.apply(raw, self.fs)

    def filtered_marker_data(self):
        """The filtered ``(M, F, 3)`` marker array on the *marker* clock.

        Equivalent to the old ``_marker_display_data``: filters the raw marker
        array at the marker rate; returns the raw array unchanged when there is
        no filter spec. Cached.
        """
        markers = self.dataset.get("markers")
        if not markers:
            return None
        spec = self._marker_spec()
        if spec is None:
            return markers["data"]
        if "marker_data" in self._cache:
            return self._cache["marker_data"]
        out = spec.apply_marker(markers["data"], markers["rate"])
        self._cache["marker_data"] = out
        return out


def signal_catalog(dataset, marker_disp=None, angle_result=None, pipeline=None):
    """Ordered ``[(key, label), ...]`` of every signal available for ``dataset``.

    ``marker_disp`` = display marker array ``(M, F, 3)`` (filtered/raw, from the UI)
    or None; ``angle_result`` = ``dataset["model_result"]`` or None.

    ``pipeline`` (``core.pipeline.Pipeline`` or None) adds the processed signals
    its FilterStep(s) produce: for each targeted raw key a "<key>:filt" entry is
    listed *right after* its raw entry, labelled "... (filtered)". With no
    pipeline (or no filter step) only raw signals appear — same as before.
    """
    # Labels come from _base_label (shared with label_for) so the catalog and a
    # bare-key label never diverge.
    opts = [(k, _base_label(k)) for k in ("time", "cop", "cop_ap", "cop_ml")]
    for k in ("fz", "fx", "fy"):
        if k in dataset:
            opts.append((k, _base_label(k)))
    # Per-plate force/COP signals (multi-plate files). One group per plate, COP
    # resultant + AP/ML + the three force axes, listed after the bare keys so
    # plate 1's bare view stays first. Single-plate files carry no fp:* keys.
    n_plates = int(dataset.get("n_force_plates", 0) or 0)
    for p in range(1, n_plates + 1):
        for comp in ("cop", "cop_ap", "cop_ml", "fz", "fx", "fy"):
            key = f"fp{p}:{comp}"
            # cop is derived; the rest must actually be stored for this plate.
            if comp == "cop" or key in dataset:
                opts.append((key, _base_label(key)))
    if angle_result and angle_result.get("angles"):
        for name in angle_result["angles"]:
            key = f"angle:{name}"
            opts.append((key, _base_label(key)))
    # Whole-body COM trajectory (world axes only). Listed only when the model
    # result actually carries a non-empty COM block — the pipeline is the sole
    # source (a model with no mass-bearing segments has an empty COM and is not
    # listed). AP/ML decomposition is deferred (needs a progression axis).
    if angle_result:
        try:
            _com_world(angle_result)
        except ValueError:
            pass
        else:
            for ax in ("x", "y", "z"):
                key = f"com:{ax}"
                opts.append((key, _base_label(key)))
    markers = dataset.get("markers")
    if markers is not None and marker_disp is not None:
        for label in markers["labels"]:
            for ax_name, _ in _AXES:
                key = f"marker:{label}:{ax_name}"
                opts.append((key, _base_label(key)))
        # Gait progression signals (G2): for each side whose heel+toe markers and
        # a pelvis reference are present, the AP-relative-to-pelvis heel/toe
        # series whose peaks/valleys are heel-strike / toe-off (Zeni 2008).
        from core import gait_events as _ge
        labset = set(markers["labels"])
        if any(p in labset for p in _ge.PELVIS_MARKERS):
            for side in ("R", "L"):
                if (_ge.foot_marker_label(side, "heel") in labset
                        and _ge.foot_marker_label(side, "toe") in labset):
                    for point in ("heel", "toe"):
                        key = f"gait:{side}_{point}_ap"
                        opts.append((key, _base_label(key)))
    if pipeline is None:
        return opts
    produced = set(pipeline.filtered_keys())
    if produced:
        out = []
        for key, label in opts:
            out.append((key, label))
            fkey = f"{key}{FILT_SUFFIX}"
            if fkey in produced:
                out.append((fkey, f"{label} (filtered)"))
        opts = out
    # ComputeStep outputs (abs / derivative / integral / magnitude / normalize)
    # are catalog signals too — the Workspace resolves them on demand — so list
    # them after the raw/filtered entries. The output ``name`` is already the
    # human key the user chose, so it doubles as the label.
    compute_keys = getattr(pipeline, "compute_keys", lambda: [])()
    have = {k for k, _ in opts}
    for name in compute_keys:
        if name and name not in have:
            opts.append((name, name))
            have.add(name)
    return opts


def signal_series(dataset, key, marker_disp=None, angle_result=None):
    """Values for ``key`` on the dataset master clock (``dataset['time']``)."""
    t = np.asarray(dataset["time"], dtype=float)
    if key == "time":
        return t
    if key == "cop":
        return _cop_resultant(dataset["cop_ap"], dataset["cop_ml"])
    plate, comp = _split_plate(key)
    if plate is not None and comp == "cop":
        # Per-plate COP resultant — same mean-subtracted definition as bare cop.
        return _cop_resultant(dataset[f"fp{plate}:cop_ap"],
                              dataset[f"fp{plate}:cop_ml"])
    if key.startswith("angle:"):
        if not angle_result or not angle_result.get("angles"):
            raise ValueError("no model result for angle channel")
        name = key.split(":", 1)[1]
        arr = angle_result["angles"].get(name)
        if arr is None:
            raise ValueError(f"angle unavailable: {name}")
        return _resample(angle_result.get("time", t), arr, t)
    if key.startswith("com:"):
        # Whole-body COM trajectory (de Leva 1996, core.com.body_com) — world
        # axes only. The model result carries com["com"] as a (F,3) world-frame
        # array (mm) on the marker clock; resample onto the master clock like
        # angle:* / marker:*. AP/ML decomposition is deferred (needs a reliable
        # progression axis, P3 #13), so only x/y/z resolve here.
        com_arr = _com_world(angle_result)   # (F,3) or ValueError
        ax = key.split(":", 1)[1]
        if ax not in ("x", "y", "z"):
            raise ValueError(f"com axis unavailable: {ax} (only world x/y/z)")
        axis = {"x": 0, "y": 1, "z": 2}[ax]
        return _resample(angle_result.get("time", t), com_arr[:, axis], t)
    if key.startswith("marker:"):
        if marker_disp is None or dataset.get("markers") is None:
            raise ValueError("no markers for marker channel")
        body = key[len("marker:"):]
        label, ax_name = body.rsplit(":", 1)
        labels = dataset["markers"]["labels"]
        if label not in labels:
            raise ValueError(f"marker unavailable: {label}")
        axis = dict(_AXES)[ax_name]
        idx = labels.index(label)
        return _resample(dataset["markers"]["time"], marker_disp[idx][:, axis], t)
    if key.startswith("gait:"):
        # Zeni 2008 progression series: a foot marker's AP coordinate relative to
        # the pelvis origin (anterior-positive), or the absolute lab-frame
        # coordinate for ``_lab`` keys. Both are computed on the marker clock from
        # the display marker array (so a marker FilterStep flows in), then
        # resampled onto the master clock like marker:* / angle:*.
        side, point, proj = _split_gait(key)
        if side is None:
            raise ValueError(f"channel unavailable: {key}")
        if marker_disp is None or dataset.get("markers") is None:
            raise ValueError("no markers for gait channel")
        from core import gait_events
        mk = {"labels": dataset["markers"]["labels"], "data": marker_disp,
              "time": dataset["markers"]["time"]}
        axis, lab = proj
        if lab:
            series = gait_events.foot_lab_series(mk, side, point, axis=axis)
        else:
            series = gait_events.foot_progression_series(mk, side, point)
        return _resample(dataset["markers"]["time"], series, t)
    if key in dataset:
        return np.asarray(dataset[key], dtype=float)
    raise ValueError(f"channel unavailable: {key}")
