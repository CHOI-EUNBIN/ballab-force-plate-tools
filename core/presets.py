"""Task presets: build a complete, EDITABLE pipeline for a movement task.

A preset is a pure function ``fn(dataset) -> list[PipelineStep]``. The UI appends
the returned steps to the pipeline; everything after is the normal editable
pipeline (the preset is just a non-blank starting point). Builders may inspect
``dataset`` to adapt (e.g. force-vs-kinematic events for overground).

Public API (Tasks 5 and 7 depend on these exact names):
  PRESETS            — dict {name: builder_fn}
  build_preset(name, dataset) -> list[PipelineStep]
  walk_treadmill(dataset) -> list[PipelineStep]

Internal helpers (Task 5 reuses these exact names):
  _kinematic_events(side)
  _spatiotemporal(side)
  _kinematics(side)
  _double_support()
  _symmetry()
"""

import numpy as np
from core.pipeline import (DetectEventStep, ComputeStep, MetricStep,
                           FilterStep, ComputeAngleStep, NormalizeStep)
from core.signals import FilterSpec

_JOINTS = ("HIP", "KNEE", "ANKLE")

#: The joint-angle channels the walk presets compute, graph, and normalize
#: (flexion/extension of hip, knee, ankle, both sides).
_ANGLE_CHANNELS = [f"{s}_{j}_angle_FE" for s in ("R", "L") for j in _JOINTS]


def _filter_and_angles():
    """Low-pass the markers (so events/angles/curves are smooth) and emit the
    joint angles as graphable ``angle:*`` signals. The pipeline is the SOLE source
    of angles — without a ComputeAngleStep no angle curve is viewable at all."""
    return [
        FilterStep(spec=FilterSpec(cutoff_hz=6.0), markers=True),
        ComputeAngleStep(joints=list(_ANGLE_CHANNELS)),
    ]


def _normalize_curves(side):
    """0–100 % time-normalized joint-angle curves (per gait cycle from HS), so the
    Ensemble panel draws mean ± SD curves — the heart of a gait report."""
    return [NormalizeStep(input=f"angle:{side}_{j}_angle_FE",
                          name=f"{side} {j.title()} % cycle",
                          mode="cycle", event=f"{side}_HS", points=101)
            for j in _JOINTS]


def _kinematic_events(side):
    """Heel-strike and toe-off detection steps for one side (treadmill: AP peaks)."""
    s = side
    return [
        DetectEventStep(input=f"gait:{s}_heel_ap", label=f"{s}_HS", method="peak",
                        params={"kind": "max", "min_distance_s": 0.5},
                        selector={"mode": "all"}),
        DetectEventStep(input=f"gait:{s}_toe_ap", label=f"{s}_TO", method="peak",
                        params={"kind": "min", "min_distance_s": 0.5},
                        selector={"mode": "all"}),
    ]


def _spatiotemporal(side):
    """Stride/stance/swing time, phase percentages, and cadence for one side."""
    s = side
    return [
        MetricStep(op="time_between_events", name=f"{s} Stride time",
                   segment=[f"{s}_HS", f"{s}_HS"]),
        MetricStep(op="time_between_events", name=f"{s} Stance time",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(op="time_between_events", name=f"{s} Swing time",
                   segment=[f"{s}_TO", f"{s}_HS"]),
        MetricStep(op="stance_pct", name=f"{s} Stance %",
                   input=f"metric:{s} Stance time", input2=f"metric:{s} Stride time"),
        MetricStep(op="swing_pct", name=f"{s} Swing %",
                   input=f"metric:{s} Swing time", input2=f"metric:{s} Stride time"),
        MetricStep(op="cadence_stride", name=f"{s} Cadence",
                   input=f"metric:{s} Stride time"),
    ]


def _treadmill_spatial(side):
    """Gait speed and stride length via heel marker velocity (treadmill belt proxy)."""
    s = side
    return [
        ComputeStep(input=f"gait:{s}_heel_ap_lab", name=f"{s}_heel_vel",
                    method="derivative", params={"order": 1}),
        ComputeStep(input=f"{s}_heel_vel", name=f"{s}_heel_speed", method="abs"),
        ComputeStep(input=f"{s}_heel_speed", name=f"{s}_heel_speed_mps",
                    method="normalize", by=1000.0),
        MetricStep(input=f"{s}_heel_speed_mps", op="mean", name=f"{s} Gait speed",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(op="product", name=f"{s} Stride length",
                   input=f"metric:{s} Gait speed", input2=f"metric:{s} Stride time"),
    ]


def _kinematics(side):
    """ROM, peak angular velocity, and angle-at-HS for hip/knee/ankle — one side."""
    out = []
    for j in _JOINTS:
        ch = f"angle:{side}_{j}_angle_FE"
        out.append(MetricStep(input=ch, op="range", name=f"{side} {j.title()} ROM",
                              segment=[f"{side}_HS", f"{side}_HS"]))
        out.append(MetricStep(input=ch, op="peak_angular_velocity",
                              name=f"{side} {j.title()} peak ang.vel",
                              segment=[f"{side}_HS", f"{side}_HS"]))
        out.append(MetricStep(input=ch, op="value_at_event",
                              name=f"{side} {j.title()} angle@HS", event=f"{side}_HS"))
    return out


def _double_support():
    """Double-support intervals + the clinical total double-support %.

    Each gait cycle has two double-support phases (both feet down): R_HS→L_TO and
    L_HS→R_TO. We report each interval (time_between_events), their SUM (total
    double-support time per cycle), and that as a percent of the stride
    (gait-cycle) time — the standard single-value metric, normally ~20 % of the
    cycle. ``double_support_pct`` = total DS time / stride time * 100 (Perry &
    Burnfield 2010). The R stride is the reference cycle (one full gait cycle is
    the same duration whichever HS bounds it)."""
    return [
        MetricStep(op="time_between_events", name="Double support R",
                   segment=["R_HS", "L_TO"]),
        MetricStep(op="time_between_events", name="Double support L",
                   segment=["L_HS", "R_TO"]),
        MetricStep(op="add", name="Total double support time",
                   input="metric:Double support R",
                   input2="metric:Double support L"),
        MetricStep(op="double_support_pct", name="Total double support %",
                   input="metric:Total double support time",
                   input2="metric:R Stride time"),
    ]


def _symmetry():
    """Inter-limb symmetry indices and stride-time variability (CV)."""
    return [
        MetricStep(op="symmetry_index", name="Stride time symmetry",
                   input="metric:R Stride time", input2="metric:L Stride time"),
        MetricStep(op="symmetry_index", name="Stance % symmetry",
                   input="metric:R Stance %", input2="metric:L Stance %"),
        MetricStep(op="cv", name="R Stride time CV", input="metric:R Stride time"),
    ]


def walk_treadmill(dataset):
    """Build the treadmill walking preset pipeline (bilateral R + L).

    Covers: kinematic events (HS/TO), spatiotemporal parameters, treadmill
    spatial metrics (belt-speed-based gait speed + stride length), joint
    kinematics (hip/knee/ankle ROM + peak ang.vel + angle-at-HS), double
    support, and symmetry/CV.

    NO kinetics — treadmill force data is not reliably usable for impulse or
    loading-rate metrics.

    Parameters
    ----------
    dataset : dict
        The current dataset mapping (may be empty ``{}``). Reserved for future
        adaptation (e.g. detecting whether force plates are present to switch to
        force-based HS detection for overground walking).

    Returns
    -------
    list[PipelineStep]
        Ordered list of steps to append to the pipeline.
    """
    steps = list(_filter_and_angles())
    for side in ("R", "L"):
        steps += _kinematic_events(side)
    for side in ("R", "L"):
        steps += (_spatiotemporal(side) + _treadmill_spatial(side)
                  + _kinematics(side) + _normalize_curves(side))
    steps += _double_support() + _symmetry()
    return steps


def _force_is_loaded(dataset, thresh_n=50.0, frac=0.05):
    """True if any plate's |Fz| exceeds ``thresh_n`` for at least ``frac`` of the
    trial (a real overground contact), else False (flat/empty plates)."""
    n_p = int(dataset.get("n_force_plates", 0) or 0)
    keys = [f"fp{p}:fz" for p in range(1, n_p + 1)] or (["fz"] if "fz" in dataset else [])
    for k in keys:
        a = np.abs(np.asarray(dataset.get(k, []), dtype=float))
        if a.size and np.mean(a > thresh_n) >= frac:
            return True
    return False


def _force_events(side, plate):
    s = side
    # Intermediate signal name uses lowercase "fz" so that downstream steps
    # and tests can reliably detect force-based steps via ``"fz" in s.input``.
    return [
        ComputeStep(input=f"fp{plate}:fz", name=f"{s}_afz", method="abs"),
        DetectEventStep(input=f"{s}_afz", label=f"{s}_HS", method="threshold",
                        params={"threshold": 50.0, "direction": "rising",
                                "min_distance_s": 0.4}, selector={"mode": "all"}),
        DetectEventStep(input=f"{s}_afz", label=f"{s}_TO", method="threshold",
                        params={"threshold": 50.0, "direction": "falling",
                                "min_distance_s": 0.4}, selector={"mode": "all"}),
    ]


def _kinetics(side, plate):
    s = side
    return [
        MetricStep(input=f"{s}_afz", op="max", name=f"{s} Peak vGRF",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(input=f"{s}_afz", op="impulse", name=f"{s} vGRF impulse",
                   segment=[f"{s}_HS", f"{s}_TO"]),
        MetricStep(input=f"{s}_afz", op="loading_rate", name=f"{s} Loading rate",
                   segment=[f"{s}_HS", f"{s}_TO"]),
    ]


def _overground_spatial(side):
    s = side
    return [
        ComputeStep(input=f"gait:{s}_heel_ap_lab", name=f"{s}_heel_ap_m",
                    method="normalize", by=1000.0),
        MetricStep(input=f"{s}_heel_ap_m", op="displacement_between_events",
                   name=f"{s} Stride length", segment=[f"{s}_HS", f"{s}_HS"]),
        MetricStep(op="quotient", name=f"{s} Gait speed",
                   input=f"metric:{s} Stride length", input2=f"metric:{s} Stride time"),
    ]


def walk_overground(dataset):
    """Build the overground walking preset pipeline (bilateral R + L).

    Events use force-plate Fz threshold (rising/falling) when force plates
    are loaded (|Fz| > 50 N for >= 5 % of the trial), otherwise falls back
    to kinematic peak detection (same as treadmill). Kinetics group (peak
    vGRF, impulse, loading rate) is added only when force is loaded. Spatial
    metrics use real foot displacement and quotient-based gait speed.

    Parameters
    ----------
    dataset : dict
        The current dataset mapping. Must contain ``n_force_plates`` and
        ``fp{n}:fz`` keys for force detection to activate.

    Returns
    -------
    list[PipelineStep]
        Ordered list of steps to append to the pipeline.
    """
    loaded = _force_is_loaded(dataset)
    n_p = int(dataset.get("n_force_plates", 0) or 0)
    steps = list(_filter_and_angles())
    for i, side in enumerate(("R", "L")):
        if loaded and n_p >= 1:
            steps += _force_events(side, plate=min(i + 1, n_p))
        else:
            steps += _kinematic_events(side)
    for i, side in enumerate(("R", "L")):
        steps += (_spatiotemporal(side) + _overground_spatial(side)
                  + _kinematics(side) + _normalize_curves(side))
        if loaded and n_p >= 1:
            steps += _kinetics(side, plate=min(i + 1, n_p))
    steps += _double_support() + _symmetry()
    return steps


#: Registry mapping preset names to builder functions.
#: Tasks 5+ extend this dict with additional presets.
PRESETS = {"walk_treadmill": walk_treadmill}
PRESETS["walk_overground"] = walk_overground


def build_preset(name, dataset):
    """Call a named preset builder and return its step list.

    Parameters
    ----------
    name : str
        A key in :data:`PRESETS`.
    dataset : dict
        Forwarded to the builder (may be empty).

    Returns
    -------
    list[PipelineStep]
        The preset's steps, or ``[]`` if the name is unknown (safe fallback).
    """
    fn = PRESETS.get(name)
    return fn(dataset) if fn else []
