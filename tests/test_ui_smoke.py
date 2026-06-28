"""Headless UI smoke tests for the Analyze tab + its dialogs.

These don't render pixels (GL output can't be checked headless), but they DO
build the real widgets under the offscreen Qt platform and assert structural
properties: the pipeline rows exist at the pinned uniform height, the metric-card
strip is gone, the Add-step picker is grouped, the Filter dialog's tree auto-fits,
and the wheel-guard blocks value changes. Skipped cleanly if Qt is unavailable.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication, QDoubleSpinBox
    from PyQt6.QtCore import Qt, QPointF, QPoint
    from PyQt6.QtGui import QWheelEvent
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    return a


# --------------------------------------------------------------------------- #
# AnalyzeTab structural checks
# --------------------------------------------------------------------------- #
def test_analyze_tab_builds_and_card_strip_removed(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    # The top metric-card strip + its pin machinery are gone.
    assert not hasattr(tab, "cards_scroll")
    assert not hasattr(tab, "cards_hb")
    assert not hasattr(tab, "_update_cards")
    assert not hasattr(tab, "_pinned_metrics")
    # _set_placeholder is now a safe no-op (still callable).
    tab._set_placeholder("x")


def test_pipeline_rows_uniform_dense_height(app):
    from ui.analyze_tab import AnalyzeTab, PipelineStepRow
    from core.pipeline import FilterStep, DetectEventStep
    from core.signals import FilterSpec
    tab = AnalyzeTab()
    tab.pipeline.steps.append(FilterStep(
        spec=FilterSpec(type="Butterworth", cutoff_hz=10, order=4),
        targets=["fz"], markers=False))
    tab.pipeline.steps.append(DetectEventStep(
        input="fz", label="HS", method="threshold",
        params={"threshold": 20, "direction": "rising"}, color="#F97316"))
    tab._refresh_pipeline_list()
    assert tab.step_list.count() == 2
    for i in range(tab.step_list.count()):
        w = tab.step_list.itemWidget(tab.step_list.item(i))
        assert w.objectName() == "pipeline-row"
        assert w.height() == PipelineStepRow.ROW_HEIGHT
    # The dense single-line row is shorter than the old 2-line card (42 px).
    assert PipelineStepRow.ROW_HEIGHT <= 30


def test_angle_direction_pair(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert tab._angle_direction_pair(["R_KNEE_angle_FE"]) == ("Flexion", "Extension")
    assert tab._angle_direction_pair(["R_ANKLE_angle_AB"]) == ("Inversion", "Eversion")
    # Mixed planes => no single direction pair.
    assert tab._angle_direction_pair(
        ["R_KNEE_angle_FE", "R_KNEE_angle_AB"]) is None


def test_force_plot_has_zero_baseline(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    fz = tab._build_time_plot("fz", is_last=True)
    cop = tab._build_time_plot("cop_ap", is_last=True)
    assert getattr(fz, "_y_baseline", None) == 0.0   # force → include 0
    assert getattr(cop, "_y_baseline", "x") is None  # COP → data-range


# --------------------------------------------------------------------------- #
# Dialogs
# --------------------------------------------------------------------------- #
def test_all_dialogs_build(app):
    from ui.analyze_dialogs import (
        FilterStepDialog, DetectEventStepDialog, TrajectoryStepDialog,
        ComputeAngleStepDialog, ComputeStepDialog, MetricStepDialog, AddStepDialog,
        SubjectInfoDialog, ExportDialog)
    FilterStepDialog(None, [("fz", "FP1 Fz")])
    DetectEventStepDialog(None, [("fz", "FP1 Fz")], frame_max=100)
    TrajectoryStepDialog(None, [("cop_ap", "COP X"), ("cop_ml", "COP Y")])
    ComputeAngleStepDialog(None, ["R_KNEE_angle_FE"])
    ComputeStepDialog(None, [("fz", "FP1 Fz"), ("fx", "FP1 Fx")],
                      metric_refs=["bodyweight"])
    MetricStepDialog(None, [("fz", "FP1 Fz")], ["HS"])
    AddStepDialog(None, {})
    SubjectInfoDialog(None)
    ExportDialog(None, [("Peak Fz", "N")], files=[(0, "trial1")])


def test_detect_search_window_variant_b(app):
    """DetectEventStepDialog's Search window is From/To bounds, each Frame OR an
    earlier Event. values()[5] is the scope dict (or None); restore handles
    None / legacy [start,end] list / dict."""
    from ui.analyze_dialogs import DetectEventStepDialog

    inputs = [("fz", "FP1 Fz")]
    labels = ["HS", "TO"]

    d = DetectEventStepDialog(None, inputs, frame_max=500, event_labels=labels)
    d.method_combo.setCurrentIndex(d.method_combo.findData("threshold"))
    assert d.values()[5] is None                       # checkbox off -> None

    d.scope_check.setChecked(True)
    d._scope_from["frame_spin"].setValue(50)
    d._scope_to["frame_spin"].setValue(300)
    assert d.values()[5] == {"from": {"type": "frame", "frame": 50},
                             "to": {"type": "frame", "frame": 300}}

    # From -> Event bound; event combo carries the earlier labels.
    d._scope_from["type_combo"].setCurrentIndex(
        d._scope_from["type_combo"].findData("event"))
    assert d._scope_from["event_combo"].count() == 2
    d._scope_from["event_combo"].setCurrentIndex(
        d._scope_from["event_combo"].findData("TO"))
    d._scope_from["instance_spin"].setValue(-1)
    assert d.values()[5]["from"] == {"type": "event", "label": "TO",
                                     "instance": -1}

    class _Step:
        def __init__(self, scope):
            self.scope = scope; self.params = {}; self.input = "fz"
            self.label = "X"; self.method = "threshold"
            self.selector = {"mode": "all"}; self.color = None

    assert not DetectEventStepDialog(
        None, inputs, frame_max=500, step=_Step(None)).scope_check.isChecked()
    leg = DetectEventStepDialog(None, inputs, frame_max=500, step=_Step([10, 200]))
    assert leg.scope_check.isChecked()
    assert leg.values()[5] == {"from": {"type": "frame", "frame": 10},
                               "to": {"type": "frame", "frame": 200}}
    dd = {"from": {"type": "event", "label": "HS", "instance": 3},
          "to": {"type": "frame", "frame": 480}}
    rt = DetectEventStepDialog(None, inputs, frame_max=500, step=_Step(dd),
                               event_labels=labels)
    assert rt.values()[5] == dd


def test_detect_search_window_time_bound(app):
    """A Search-window bound can be a TIME bound: its Type combo offers Time
    alongside Frame / Event, a seconds spin (suffix ' s') feeds values()'s scope
    dict as {"type":"time","seconds":...}, and a saved time bound round-trips."""
    from ui.analyze_dialogs import DetectEventStepDialog

    inputs = [("fz", "FP1 Fz")]
    labels = ["HS", "TO"]

    d = DetectEventStepDialog(None, inputs, frame_max=500, event_labels=labels,
                              master_fs=1000.0)
    d.method_combo.setCurrentIndex(d.method_combo.findData("threshold"))
    d.scope_check.setChecked(True)

    # The Type combo carries a Time option backed by a seconds spin (" s").
    assert d._scope_from["type_combo"].findData("time") >= 0
    d._scope_from["type_combo"].setCurrentIndex(
        d._scope_from["type_combo"].findData("time"))
    assert d._scope_from["time_spin"].suffix() == " s"
    d._scope_from["time_spin"].setValue(0.5)
    assert d.values()[5]["from"] == {"type": "time", "seconds": 0.5}

    # A saved time bound restores its Type + seconds value.
    class _Step:
        def __init__(self, scope):
            self.scope = scope; self.params = {}; self.input = "fz"
            self.label = "X"; self.method = "threshold"
            self.selector = {"mode": "all"}; self.color = None

    dd = {"from": {"type": "time", "seconds": 0.25},
          "to": {"type": "frame", "frame": 480}}
    rt = DetectEventStepDialog(None, inputs, frame_max=500, step=_Step(dd),
                               event_labels=labels, master_fs=1000.0)
    assert rt.scope_check.isChecked()
    assert rt._scope_from["type_combo"].currentData() == "time"
    assert rt._scope_from["time_spin"].value() == pytest.approx(0.25)
    assert rt.values()[5] == dd


def test_detect_min_distance_in_seconds(app):
    """G1: the Min-spacing refractory is authored in SECONDS. A new/edited step
    writes params['min_distance_s'] (not the legacy frame 'min_distance'); the
    master-fs hint shows the seconds→frames conversion; and a legacy frame value
    loads as the equivalent seconds via the passed master fs."""
    from ui.analyze_dialogs import DetectEventStepDialog

    inputs = [("sig", "Signal")]

    # New peak step: 0.3 s refractory -> params carry min_distance_s only.
    d = DetectEventStepDialog(None, inputs, frame_max=500, master_fs=1000.0)
    d.method_combo.setCurrentIndex(d.method_combo.findData("peak"))
    assert d.min_distance_spin.suffix() == " s"
    d.min_distance_spin.setValue(0.3)
    params = d.values()[3]
    assert params["min_distance_s"] == 0.3
    assert "min_distance" not in params               # legacy frame key dropped
    # The muted hint resolves seconds -> frames at the master clock.
    d.min_distance_spin.setValue(0.6)
    assert "600 frames" in d.min_distance_hint.text()

    # Same 0.6 s at a 100 Hz master clock = 60 frames (clock shown, not baked in).
    d100 = DetectEventStepDialog(None, inputs, frame_max=500, master_fs=100.0)
    d100.method_combo.setCurrentIndex(d100.method_combo.findData("peak"))
    d100.min_distance_spin.setValue(0.6)
    assert "60 frames" in d100.min_distance_hint.text()

    class _Step:
        def __init__(self, params):
            self.scope = None; self.params = params; self.input = "sig"
            self.label = "PK"; self.method = "peak"
            self.selector = {"mode": "all"}; self.color = None

    # Legacy frame value (saved pre-G1) loads as the equivalent seconds and is
    # re-emitted as min_distance_s — never silently reset to 0.
    leg = DetectEventStepDialog(None, inputs, frame_max=500,
                                step=_Step({"kind": "max", "min_distance": 600}),
                                master_fs=1000.0)
    assert leg.min_distance_spin.value() == pytest.approx(0.6)
    assert leg.values()[3]["min_distance_s"] == pytest.approx(0.6)
    assert "min_distance" not in leg.values()[3]


def test_help_hint_widget_basics(app):
    """The HelpHint badge is a true circle (square + half-radius), carries its
    section paragraph as click text (NOT a tooltip), and pops a SectionHintPopup
    on click. op_hint / metric_hint are still reused live from help_dialog."""
    from ui.components.help_hint import (
        HelpHint, SectionHintPopup, section_hint, op_hint, metric_hint)
    hh = HelpHint("Knee velocity = d(angle)/dt")
    # True circle: width == height (a square the radius can round into a disc).
    assert hh.width() == hh.height()
    # Click text lives on the badge, not as the (definitional) tooltip.
    assert hh.hintText() == "Knee velocity = d(angle)/dt"
    # Clicking builds a popup widget that shows the same paragraph.
    hh._show_popup()
    assert isinstance(hh._popup, SectionHintPopup)
    assert "Knee velocity" in hh._popup._label.text()
    hh._popup.close()
    # Section copy resolves; live reuse of existing op/metric copy still works.
    assert "Cutoff" in section_hint("Filter.Filter") or section_hint("Filter.Filter")
    assert metric_hint("RMS AP") and op_hint("impulse")


def test_step_dialogs_carry_section_hints(app):
    """Hints are now SECTION-level: each step dialog carries only a SMALL number
    of "?" badges (one per explained section header), not one per field. Each
    badge must pop a SectionHintPopup with text on click."""
    from ui.components.help_hint import HelpHint, SectionHintPopup
    from ui.analyze_dialogs import (
        FilterStepDialog, DetectEventStepDialog, MetricStepDialog,
        ComputeStepDialog, TrajectoryStepDialog)
    inputs = [("fz", "FP1 Fz"), ("cop_ap", "FP1 COP AP"), ("cop_ml", "FP1 COP ML")]
    cases = [
        FilterStepDialog(None, inputs),                       # 1 section: Filter
        DetectEventStepDialog(None, inputs, frame_max=100),   # 3: Detection/Guard/Result
        MetricStepDialog(None, inputs, ["HS"]),               # 3: Input/Window/Calculation
        ComputeStepDialog(None, inputs, metric_refs=["m"]),   # 1: Calculation
        TrajectoryStepDialog(None, inputs),                   # 1: Signals
    ]
    for d in cases:
        hints = d.findChildren(HelpHint)
        # Section-level => few (>=1, and well under the old per-field count).
        assert 1 <= len(hints) <= 5, (type(d).__name__, len(hints))
        for hh in hints:
            assert hh.hintText()                  # every badge explains something
            hh._show_popup()
            assert isinstance(hh._popup, SectionHintPopup)
            assert hh._popup._label.text()
            hh._popup.close()


def test_compute_dialog_offers_all_methods(app):
    """The Calculation combo is built from COMPUTE_METHODS (data-driven, not
    hardcoded) — every engine method is selectable."""
    from ui.analyze_dialogs import ComputeStepDialog
    from core.pipeline import COMPUTE_METHODS
    d = ComputeStepDialog(None, [("fz", "FP1 Fz")])
    offered = {d.method_combo.itemData(i) for i in range(d.method_combo.count())}
    assert offered == set(COMPUTE_METHODS)


def test_xcom_length_row_is_explained(app):
    """The XCOM pendulum-length row guides the user: a tooltip explaining L (the
    standing COM height, in metres) and a clear 'not set' label at 0 so an unset
    length (which yields NaN — never a guess) doesn't read as a real '0.000 m'."""
    from ui.analyze_dialogs import ComputeStepDialog
    d = ComputeStepDialog(None, [("com:x", "COM X")])
    tip = d.length_spin.toolTip().lower()
    assert tip                                   # has a tooltip at all
    assert "metre" in tip or "meter" in tip      # states the unit explicitly
    assert "com height" in tip or "pendulum" in tip
    # 0 (unset) shows a clear special label, not "0.000 m".
    assert d.length_spin.specialValueText().strip() != ""
    assert d.length_label.toolTip()              # the label carries help too


def test_suggested_pendulum_length_from_height():
    """Pure helper: a standing COM height ≈ 0.55 × stature, or None when no
    usable height is known (so the dialog never invents one)."""
    from ui.analyze_dialogs import suggested_pendulum_length_m
    assert suggested_pendulum_length_m(1.73) == pytest.approx(0.55 * 1.73)
    assert suggested_pendulum_length_m(None) is None
    assert suggested_pendulum_length_m(0.0) is None
    assert suggested_pendulum_length_m(-1.0) is None


def test_xcom_length_hint_shows_suggestion_without_autofilling(app):
    """A height-based L suggestion appears in the row's tooltip as guidance, but
    the spin is NOT auto-filled — it stays 'not set' so the user must enter a
    real value (their own marker-measured length, or the suggestion). Preserves
    the 'never guess a pendulum length' rule."""
    from ui.analyze_dialogs import ComputeStepDialog
    d = ComputeStepDialog(None, [("com:x", "COM X")], suggested_length_m=0.95)
    assert d.length_spin.value() == 0.0                 # not auto-filled
    assert d.length_spin.specialValueText().strip() != ""   # still "not set"
    assert "0.95" in d.length_spin.toolTip()            # suggestion is shown


def test_ensemble_menu_has_average_radio_and_export(app):
    """The 'Ensemble overlay' right-click menu consolidates ensemble controls:
    a per-cycle / per-subject weighting choice (checkable radio) and Export CSV —
    the old separate plot-less panel's button + toggle moved here."""
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    menu = tab._ensemble_menu("ensemble:knee_cycle")
    texts = [a.text() for a in menu.actions()]
    assert any("Export CSV" in t for t in texts), texts
    avg = [a.menu() for a in menu.actions() if a.text() == "Average" and a.menu()]
    assert avg, f"Average submenu missing: {texts}"
    sub = avg[0].actions()
    sub_texts = [a.text() for a in sub]
    assert "per cycle" in sub_texts and "per subject" in sub_texts
    assert all(a.isCheckable() for a in sub)
    # exactly one checked, matching the current mode (default per cycle)
    checked = [a.text() for a in sub if a.isChecked()]
    assert checked == ["per cycle"]


def test_set_ensemble_weight_updates_mode(app):
    """Choosing a weighting mode updates the tab's ensemble weight (which the
    pooling then honours)."""
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert tab._ensemble_weight == "cycle"          # default preserves behaviour
    tab._set_ensemble_weight("subject")
    assert tab._ensemble_weight == "subject"


def test_add_step_dialog_has_compute_command(app):
    """The unified Add popup now exposes a Compute-signal command (was missing —
    derivative/integral/magnitude/abs were unreachable from the UI)."""
    from ui.analyze_dialogs import AddStepDialog
    d = AddStepDialog(None, {"compute_inputs": [("fz", "FP1 Fz")]})
    kinds = {d.cmd_list.item(i).data(Qt.ItemDataRole.UserRole)
             for i in range(d.cmd_list.count())}
    assert "compute" in kinds
    assert "compute" in d.forms


def test_compute_dialog_to_step_e2e_abs_impulse(app):
    """E2E: build |fz| via ComputeStepDialog -> ComputeStep -> run_pipeline, then
    integrate it -> a POSITIVE impulse even from a down-negative raw Fz."""
    import numpy as np
    from ui.analyze_dialogs import ComputeStepDialog
    from core.pipeline import ComputeStep, MetricStep, Pipeline
    from core.run import run_pipeline

    # abs dialog -> step values
    d = ComputeStepDialog(None, [("fp1:fz", "FP1 Fz")])
    d.input_combo.set_key("fp1:fz")
    d.method_combo.setCurrentIndex(d.method_combo.findData("abs"))
    d.name_input.setText("|Fz|")
    vals = d.values()
    assert vals["method"] == "abs" and vals["name"] == "|Fz|"
    step = ComputeStep(**vals)

    n, fs = 200, 100.0
    t = np.arange(n) / fs
    fz = -700.0 * np.ones(n)  # raw down-negative vertical GRF
    ds = {"time": t, "fs": fs, "fp1:fz": fz, "cop_ap": np.zeros(n),
          "cop_ml": np.zeros(n)}
    p = Pipeline()
    p.add(step)
    p.add(MetricStep(input="|Fz|", op="integral", name="Impulse"))
    out = run_pipeline(ds, p)
    # produced signal exists and is rectified (all positive)
    sig = out["ctx"].signal("|Fz|")
    assert np.all(sig > 0)
    assert out["metric_values"]["Impulse"][0] > 0   # positive impulse


def test_results_signals_joint_angles_foldable(app):
    """RESULTS·Signals folds the Joint angles group by default (▸ + count) and
    unfolds it on a header click — so a many-angle model stays tidy."""
    from ui.analyze_tab import AnalyzeTab
    from core.results_model import ResultEntry
    from PyQt6.QtCore import Qt
    tab = AnalyzeTab()
    entries = [
        ResultEntry("angle:R_KNEE_angle_FE", "R Knee F/E", "deg", "signal",
                    "Joint angles", "model"),
        ResultEntry("angle:L_KNEE_angle_FE", "L Knee F/E", "deg", "signal",
                    "Joint angles", "model"),
        ResultEntry("fz:filt", "Fz (filtered)", "N", "signal",
                    "Processed signals", "processed"),
    ]
    tab._populate_signals_list(None, entries)
    texts = [tab.signals_list.item(i).text()
             for i in range(tab.signals_list.count())]
    # Joint angles header is collapsed by default (▸ + count), its 2 children hidden.
    assert any("Joint angles" in t and "(2)" in t for t in texts)
    assert not any("Knee" in t for t in texts)
    # The Processed group is open, so its child shows.
    assert any("Fz" in t for t in texts)

    # Header rows are tagged ("group", <name>) on UserRole so a click can toggle.
    header = next(tab.signals_list.item(i)
                  for i in range(tab.signals_list.count())
                  if (tab.signals_list.item(i).data(Qt.ItemDataRole.UserRole) or
                      (None,))[0] == "group"
                  and "Joint angles" in tab.signals_list.item(i).text())
    assert header.data(Qt.ItemDataRole.UserRole) == ("group", "Joint angles")
    # Unfold (the click handler flips the collapse set; re-render with the same
    # entries to show the now-visible angle rows).
    tab._collapsed_sig_groups.discard("Joint angles")
    tab._populate_signals_list(None, entries)
    texts2 = [tab.signals_list.item(i).text()
              for i in range(tab.signals_list.count())]
    assert any("R Knee F/E" in t for t in texts2)
    assert any("L Knee F/E" in t for t in texts2)


def test_compute_angle_dialog_shows_abbrev_labels(app):
    """ComputeAngle checklist leaves use the angle_label shorthand (F/E, Inv/Ever,
    Dorsi/Plantar), NOT the internal key or verbose plane name."""
    from ui.analyze_dialogs import ComputeAngleStepDialog
    d = ComputeAngleStepDialog(
        None, ["R_KNEE_angle_FE", "L_ANKLE_angle_AB", "L_ANKLE_angle_FE"])
    leaf_texts = [it.text(0) for it in d._leaves.values()]
    # No raw internal keys leak into the UI.
    assert all("angle_" not in t for t in leaf_texts)
    blob = " | ".join(leaf_texts)
    assert "F/E" in blob          # knee sagittal abbreviation
    assert "Inv/Ever" in blob     # ankle frontal abbreviation
    assert "Dorsi/Plantar" in blob  # ankle sagittal abbreviation


def test_compute_dialog_derivative_params(app):
    """Derivative dialog -> step carries order in params (UI no-hardcode path)."""
    from ui.analyze_dialogs import ComputeStepDialog
    d = ComputeStepDialog(None, [("angle:Knee", "Knee")])
    d.method_combo.setCurrentIndex(d.method_combo.findData("derivative"))
    d.order_combo.setCurrentIndex(d.order_combo.findData(2))
    d.name_input.setText("Knee accel")
    vals = d.values()
    assert vals["method"] == "derivative" and vals["params"] == {"order": 2}


def test_add_step_dialog_is_grouped(app):
    from ui.analyze_dialogs import AddStepDialog
    d = AddStepDialog(None, {})
    headers = [d.cmd_list.item(i).text() for i in range(d.cmd_list.count())
               if d.cmd_list.item(i).data(Qt.ItemDataRole.UserRole) is None]
    # Quick start is now the first group; the original three remain.
    assert "QUICK START" in headers
    assert "PROCESS" in headers and "DETECT" in headers and "MEASURE" in headers
    # Header rows are not selectable; the first real command auto-selects.
    # (Quick start is first, so first selectable is a preset kind.)
    assert d.selected_kind() in {k for k, _ in AddStepDialog.COMMANDS}
    assert d.selected_kind() != ""
    # Switching rows maps to the right form page.
    for row in range(d.cmd_list.count()):
        item = d.cmd_list.item(row)
        kind = item.data(Qt.ItemDataRole.UserRole)
        if kind is None:
            assert not (item.flags() & Qt.ItemFlag.ItemIsSelectable)
        else:
            d.cmd_list.setCurrentRow(row)
            assert d.selected_kind() == kind
            assert d.stack.currentIndex() == d._page_for_kind[kind]


def test_filter_dialog_tree_autofits(app):
    from ui.analyze_dialogs import FilterStepDialog
    targets = [("fz", "FP1 Fz"), ("fx", "FP1 Fx"), ("fy", "FP1 Fy"),
               ("cop_ap", "FP1 COP X"), ("cop_ml", "FP1 COP Y")]
    d = FilterStepDialog(None, targets)
    collapsed = d.tree.height()
    d.tree.topLevelItem(1).setExpanded(True)
    d._fit_tree_height()
    expanded = d.tree.height()
    # Auto-fit: collapsed box is short (no 190 px dead area) and grows on expand.
    assert collapsed < 190
    assert expanded > collapsed


# --------------------------------------------------------------------------- #
# Wheel guard
# --------------------------------------------------------------------------- #
def test_wheel_guard_blocks_value_change(app):
    from ui.components.wheel_guard import app_guard, install_wheel_guard
    guard = app_guard()
    sp = QDoubleSpinBox()
    sp.setRange(0, 100)
    sp.setValue(5)
    sp.installEventFilter(guard)
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    before = sp.value()
    handled = guard.eventFilter(sp, ev)
    assert handled is True          # wheel swallowed
    assert sp.value() == before     # value unchanged
    # install_wheel_guard walks a tree without error.
    from PyQt6.QtWidgets import QWidget, QVBoxLayout, QComboBox
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.addWidget(QComboBox())
    lay.addWidget(QDoubleSpinBox())
    install_wheel_guard(w)


# --------------------------------------------------------------------------- #
# Preset picker
# --------------------------------------------------------------------------- #
def test_apply_preset_seeds_pipeline(app, monkeypatch):
    import numpy as np
    from ui.analyze_tab import AnalyzeTab
    from core import presets
    tab = AnalyzeTab()
    # Provide a minimal dataset so downstream refresh calls (event controls,
    # filter-changed) don't crash when they probe for "time" / "fs".
    _ds = {"n_force_plates": 0, "time": np.linspace(0, 1, 100), "fs": 100.0}
    monkeypatch.setattr(tab, "_current_dataset", lambda: _ds)
    pipe = tab.pipeline          # real pipeline attribute name
    before = len(pipe.steps)
    tab._apply_preset("walk_treadmill")
    after = len(pipe.steps)
    assert after - before == len(presets.build_preset("walk_treadmill", {}))


# --------------------------------------------------------------------------- #
# Walk-preset popup integration
# --------------------------------------------------------------------------- #
def test_add_step_dialog_has_quick_start_presets(app):
    """AddStepDialog.COMMANDS includes both walk presets and constructing the
    dialog (which builds info pages for them) does not raise."""
    from ui.analyze_dialogs import AddStepDialog

    kinds = [k for k, _ in AddStepDialog.COMMANDS]
    assert "preset_walk_treadmill" in kinds
    assert "preset_walk_overground" in kinds

    # Building the dialog must not raise (info pages for the preset kinds build).
    d = AddStepDialog(None, {})
    # Both preset kinds have a page in the stack.
    assert "preset_walk_treadmill" in d._page_for_kind
    assert "preset_walk_overground" in d._page_for_kind
    # The Quick start group is present as a header.
    headers = [d.cmd_list.item(i).text() for i in range(d.cmd_list.count())
               if d.cmd_list.item(i).data(Qt.ItemDataRole.UserRole) is None]
    assert "QUICK START" in headers


def test_add_step_dialog_preset_dispatch(app, monkeypatch):
    """When AddStepDialog returns a preset kind, the '+' handler calls
    _apply_preset with the preset name (strip 'preset_' prefix) and returns."""
    import numpy as np
    from ui.analyze_tab import AnalyzeTab

    tab = AnalyzeTab()
    _ds = {"n_force_plates": 0, "time": np.linspace(0, 1, 100), "fs": 100.0}
    monkeypatch.setattr(tab, "_current_dataset", lambda: _ds)

    called_with = []
    monkeypatch.setattr(tab, "_apply_preset", lambda name: called_with.append(name))

    # Simulate what _append_step does for a preset kind:
    tab._append_step("preset_walk_treadmill", {})
    assert called_with == ["walk_treadmill"]


def test_preset_combo_removed(app):
    """The outside _preset_combo QComboBox must no longer exist on AnalyzeTab."""
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert not hasattr(tab, "_preset_combo"), (
        "_preset_combo should have been removed; the preset is now in the popup"
    )


# --------------------------------------------------------------------------- #
# RESULTS·Metrics — failure-feedback markers (status from the run result)
# --------------------------------------------------------------------------- #
def test_metrics_list_marks_unavailable_and_partial(app):
    """A metric whose run result is UNAVAILABLE shows a ⚠ marker + reason tooltip;
    a PARTIAL one shows ◐ + its 'computed N of M' message; an OK one shows neither
    marker (just the value). Mirrors the angle ⚠ inline-feedback pattern."""
    import numpy as np
    from ui.analyze_tab import AnalyzeTab
    from core.results_model import ResultEntry
    import core.diagnostics as diag

    tab = AnalyzeTab()
    tab._last_run_result = {"metrics": [
        {"name": "Bad", "value": float("nan"), "unit": "deg", "n": 0,
         "status": diag.UNAVAILABLE, "reason": diag.NO_SIGNAL,
         "message": "Input signal 'angle:Missing' is not available."},
        {"name": "Half", "value": 1.0, "unit": "s", "n": 2,
         "status": diag.PARTIAL, "reason": diag.PARTIAL_CYCLES,
         "message": "Computed 2 of 3 cycles."},
        {"name": "Good", "value": 40.0, "unit": "deg", "n": 1,
         "status": diag.OK, "reason": "", "message": ""},
    ]}
    entries = [
        ResultEntry("metric:Bad", "Bad", "deg", "metric", "Metrics", "metric"),
        ResultEntry("metric:Half", "Half", "s", "metric", "Metrics", "metric"),
        ResultEntry("metric:Good", "Good", "deg", "metric", "Metrics", "metric"),
    ]
    tab._populate_metrics_list(entries)

    items = {tab.metrics_list.item(i).text(): tab.metrics_list.item(i)
             for i in range(tab.metrics_list.count())}
    bad = next(it for t, it in items.items() if t.startswith("Bad"))
    half = next(it for t, it in items.items() if t.startswith("Half"))
    good = next(it for t, it in items.items() if t.startswith("Good"))

    # Unavailable -> ⚠ marker + the reason message in the tooltip.
    assert "⚠" in bad.text()
    assert "not available" in bad.toolTip()
    # Partial -> ◐ marker + the 'computed N of M' message, value still shown.
    assert "◐" in half.text()
    assert "2 of 3" in half.toolTip()
    # OK -> no status marker; the value is rendered.
    assert "⚠" not in good.text() and "◐" not in good.text()
    assert "40" in good.text()
