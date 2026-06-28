"""COP trajectory (statokinesigram) computation — the 2-D mean-centred COP path.

The companion to :func:`core.events_compute.compute_detected_events`: where that
turns the pipeline's :class:`~core.pipeline.DetectEventStep`s into events, this
turns a :class:`~core.pipeline.TrajectoryStep` into the 2-D COP path the UI draws
in its PROCESSED section.

Definition (biomech, 2026-06-23): the statokinesigram is the ML(x)-AP(y) path of
the COP about its own mean — i.e. ``(ml - mean(ml), ap - mean(ap))`` — plus the
mean point. Mean-centring matches :func:`core.signals.cop_resultant` (the COP
"sway about the centre" convention, Prieto et al. 1996) so the resultant curve
and the trajectory tell the same story. The 95% confidence ellipse is *not*
computed here: the UI reuses :func:`core.metrics.compute_ellipse_points` on the
same AP/ML so there is one ellipse definition. This module only supplies the
mean-centred path data.

Kept separate from ``core.signals`` because a trajectory is a 2-D derived product
(a path), not a 1-D signal that fits the catalog / ``:filt`` scheme. Pure / UI-free
/ numpy: it takes a :class:`core.signals.Workspace` so a ``:filt`` COP input picks
up the pipeline's filtering (falling back to raw when no filter step targets it).
"""

import numpy as np


def compute_trajectory(workspace, step=None, ap_key="cop_ap", ml_key="cop_ml"):
    """Mean-centred COP path for ``workspace``, per a :class:`TrajectoryStep`.

    Resolves the AP/ML signals through the workspace (so ``"cop_ap:filt"`` uses
    the pipeline's filtering), centres each on its own NaN-aware mean, and returns

        ``{"x": ml - mean(ml), "y": ap - mean(ap), "mean": (mean(ml), mean(ap))}``

    where ``x`` is the ML axis and ``y`` the AP axis (matching the plot axes and
    :func:`core.metrics.compute_ellipse_points`). ``mean`` is the COP centre in
    the *original* (un-centred) coordinates, so the UI can label it.

    ``step`` (a :class:`core.pipeline.TrajectoryStep`) supplies the AP/ML keys
    when given; otherwise the ``ap_key`` / ``ml_key`` arguments are used (default
    raw COP). Returns ``None`` if either signal is unavailable (e.g. a trial with
    no COP), so the caller can simply skip drawing.
    """
    if step is not None:
        ap_key = getattr(step, "ap", ap_key)
        ml_key = getattr(step, "ml", ml_key)
    try:
        ap = np.asarray(workspace.series(ap_key), dtype=float)
        ml = np.asarray(workspace.series(ml_key), dtype=float)
    except (ValueError, KeyError):
        return None
    if ap.size == 0 or ml.size == 0:
        return None
    ap_mean = float(np.nanmean(ap))
    ml_mean = float(np.nanmean(ml))
    return {
        "x": ml - ml_mean,
        "y": ap - ap_mean,
        "mean": (ml_mean, ap_mean),
    }


def first_trajectory(workspace, pipeline):
    """The path for the pipeline's first :class:`TrajectoryStep`, or ``None``.

    A convenience entry point for the common "does this recipe ask for a COP
    path?" case: returns :func:`compute_trajectory` for the first trajectory step
    in ``pipeline``, or ``None`` when the recipe has none. Multiple trajectory
    steps are allowed (the UI can iterate :meth:`Pipeline.trajectory_steps`); this
    just handles the single-path shortcut.
    """
    if pipeline is None:
        return None
    steps = pipeline.trajectory_steps()
    if not steps:
        return None
    return compute_trajectory(workspace, step=steps[0])
