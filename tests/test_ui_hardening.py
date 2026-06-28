"""Offscreen-Qt hardening tests for the Analyze tab + ensemble panel.

These pin the bugs found in the 2026-06-27 frontend hardening pass:

  1. Derived-signal graph EMPTY — right-clicking a ComputeStep output that
     depends on a marker-derived signal (``marker:* / gait:*``) drew axes but no
     curve, because ``_render_force_curves`` built its Workspace WITHOUT
     ``marker_disp`` (so the Workspace raised "channel unavailable" for those
     inputs and the curve silently stayed empty).
  2. Ensemble shown TWICE — the bottom "Ensemble" panel had its own mean ± SD
     mini-plot AND the RESULTS·Signals "Ensemble overlay" drew the same curve in
     the main area. The bottom panel is now plot-less (export only).
  3. ``_event_channel_options(None)`` must not raise (defensive empty-state).

Skipped cleanly if Qt is unavailable.
"""

import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _marker_dataset(n=300, fs=100.0):
    """A tiny single-marker dynamic dataset. Marker ``data`` is laid out
    ``(n_markers, n_frames, 3)`` to match the c3d reader; HEEL Z is a clean sine
    so a derivative ComputeStep produces a non-flat curve."""
    t = np.arange(n) / fs
    data = np.zeros((1, n, 3))
    data[0, :, 2] = np.sin(2 * np.pi * t)
    markers = {"labels": ["HEEL"], "data": data, "rate": fs,
               "units": "mm", "time": t}
    return {"name": "t", "role": "dynamic", "folder": (), "time": t, "fs": fs,
            "n_force_plates": 0, "markers": markers, "force_signal_keys": []}


# --------------------------------------------------------------------------- #
# Bug 1: derived-signal graph fills its curve
# --------------------------------------------------------------------------- #
def test_derived_marker_signal_graph_has_curve(app):
    """A ComputeStep output reading a ``marker:*`` input must DRAW (curve data
    filled), not just show empty axes. Regression for the marker-derived
    derived-signal empty-graph bug."""
    from ui.analyze_tab import AnalyzeTab
    from core.pipeline import ComputeStep

    ds = _marker_dataset()
    tab = AnalyzeTab()
    tab.datasets = [ds]
    tab._folders = {()}
    tab._current_dataset = lambda: ds
    tab.pipeline.add(ComputeStep(input="marker:HEEL:Z", name="heel_z_vel",
                                 method="derivative", params={"order": 1}))
    tab._refresh_pipeline_list()
    tab._signal_to_new_figure("heel_z_vel")           # right-click → View as graph

    assert "heel_z_vel" in tab._raw_curves, "derived signal got no plot curve"
    raw_curve, _filt = tab._raw_curves["heel_z_vel"]
    xdata, ydata = raw_curve.getData()
    assert xdata is not None and ydata is not None, "curve data never filled"
    assert len(xdata) == len(ds["time"]), "curve length must match the master clock"
    # The derivative of a sine is non-constant: the curve actually carries signal.
    assert float(np.nanmax(ydata) - np.nanmin(ydata)) > 0.0


def test_render_force_curves_passes_marker_disp(app):
    """Source-level guard: ``_render_force_curves`` must build its Workspace WITH
    ``marker_disp`` so marker-derived ComputeStep outputs resolve there too."""
    import inspect
    from ui.analyze_tab import AnalyzeTab
    src = inspect.getsource(AnalyzeTab._render_force_curves)
    assert "marker_disp=" in src, (
        "_render_force_curves must pass marker_disp or derived marker signals "
        "silently render empty")


# --------------------------------------------------------------------------- #
# #6: an unresolvable derived curve surfaces a "could not compute" note
# --------------------------------------------------------------------------- #
def test_unresolvable_signal_shows_plot_note(app):
    """A visible derived curve that can't resolve (its input doesn't exist) must
    show a small 'could not compute' note on its plot — the silent empty-axes
    failure (UI BUG 1 class) is now visible."""
    from ui.analyze_tab import AnalyzeTab
    from core.pipeline import ComputeStep

    ds = _marker_dataset()
    tab = AnalyzeTab()
    tab.datasets = [ds]
    tab._folders = {()}
    tab._current_dataset = lambda: ds
    # Input marker GHOST does not exist -> Workspace.series raises -> can't resolve.
    tab.pipeline.add(ComputeStep(input="marker:GHOST:Z", name="ghost_vel",
                                 method="derivative", params={"order": 1}))
    tab._refresh_pipeline_list()
    tab._signal_to_new_figure("ghost_vel")            # right-click → View as graph

    plot = tab._raw_plots.get("ghost_vel")
    assert plot is not None, "derived signal got no plot"
    assert getattr(plot, "_note_text", "") == "could not compute"


def test_resolvable_signal_has_no_plot_note(app):
    """A healthy derived curve must NOT carry the note (the note is failure-only,
    not an always-on label)."""
    from ui.analyze_tab import AnalyzeTab
    from core.pipeline import ComputeStep

    ds = _marker_dataset()
    tab = AnalyzeTab()
    tab.datasets = [ds]
    tab._folders = {()}
    tab._current_dataset = lambda: ds
    tab.pipeline.add(ComputeStep(input="marker:HEEL:Z", name="heel_z_vel",
                                 method="derivative", params={"order": 1}))
    tab._refresh_pipeline_list()
    tab._signal_to_new_figure("heel_z_vel")

    plot = tab._raw_plots.get("heel_z_vel")
    assert plot is not None
    assert getattr(plot, "_note_text", "") == ""


# --------------------------------------------------------------------------- #
# Bug 2: ensemble shown once (bottom panel is plot-less)
# --------------------------------------------------------------------------- #
def test_analyze_ensemble_panel_is_plotless(app):
    """The bottom Ensemble panel the Analyze tab embeds must NOT carry a plot —
    the mean ± SD curve is drawn once in the main area (Signals → Ensemble
    overlay). Pinning the de-dup."""
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    panel = tab._ensemble_panel
    assert panel._has_plot is False
    assert not hasattr(panel, "_plot"), "embedded ensemble panel must have no plot"


def test_standalone_ensemble_panel_still_has_plot(app):
    """A standalone EnsemblePanel (default) keeps its plot — only the Analyze-tab
    embedding opts out, so the panel stays reusable elsewhere."""
    from ui.ensemble_panel import EnsemblePanel
    panel = EnsemblePanel()
    assert panel._has_plot is True
    assert hasattr(panel, "_plot")
    # Plot-less panel still pools + reports + exports (data path unaffected).
    pl = EnsemblePanel(show_plot=False)
    pl.set_sources([("a", {"matrix": np.ones((3, 101)), "label": "fz"})])
    assert pl.n_epochs() == 3
    assert np.isclose(pl.stats()["mean"][0], 1.0)


# --------------------------------------------------------------------------- #
# Bug 3: empty-state guard
# --------------------------------------------------------------------------- #
def test_event_channel_options_none_is_safe(app):
    """``_event_channel_options(None)`` must return [] rather than raise — a
    defensive guard so no caller can trip an AttributeError on a missing
    dataset."""
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert tab._event_channel_options(None) == []


# --------------------------------------------------------------------------- #
# Polish: empty-state hints in the RESULTS lists
# --------------------------------------------------------------------------- #
def test_results_lists_show_empty_state_hints(app):
    """With no dataset and an empty pipeline, each RESULTS list shows ONE muted,
    non-selectable hint row (tagged ("hint", None)) rather than a blank box."""
    from PyQt6.QtCore import Qt
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    tab._refresh_results_panels()

    def only_hint(lst, needle):
        # The list carries a hint row whose UserRole is ("hint", None).
        rows = [(lst.item(i).text(), lst.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(lst.count())]
        hints = [t for t, role in rows if role == ("hint", None)]
        assert any(needle in t for t in hints), (needle, rows)

    only_hint(tab.signals_list, "add a step")
    only_hint(tab.results_events_list, "Detect Events")
    only_hint(tab.metrics_list, "Metric step")


def test_results_menus_ignore_hint_rows(app):
    """Right-clicking an empty-state hint row must not raise (the menu handlers
    skip non-data rows). Pins the menu guard so a hint can't crash the app."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    from ui.analyze_tab import AnalyzeTab

    tab = AnalyzeTab()
    tab._refresh_results_panels()
    # Stub exec so the menus don't block; the guard must short-circuit before it.
    orig = QMenu.exec
    QMenu.exec = lambda *a, **k: None
    try:
        tab._show_results_signals_menu(QPoint(2, 2))
        tab._show_results_events_menu(QPoint(2, 2))
        tab._show_results_metrics_menu(QPoint(2, 2))
    finally:
        QMenu.exec = orig
