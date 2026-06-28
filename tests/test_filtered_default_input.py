"""When authoring a NEW pipeline step, the signal picker should default to the
``:filt`` twin of its otherwise-default key when one exists, so an active filter
flows into events/metrics instead of being silently ignored on the raw key.
Editing an existing step must keep that step's saved input untouched.
"""
import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_picker_prefers_filtered_twin(app):
    from ui.components.cascading_signal_picker import CascadingSignalPicker
    p = CascadingSignalPicker(keys=[("fz", "Fz"), ("fz:filt", "Fz (filtered)"),
                                    ("cop_ap", "COP AP")])
    p.set_key("fz")
    p.prefer_filtered_default()
    assert p.selected_key() == "fz:filt"          # swapped to the filtered twin
    # no twin -> unchanged
    p.set_key("cop_ap")
    p.prefer_filtered_default()
    assert p.selected_key() == "cop_ap"
    # already filtered -> unchanged (no double suffix)
    p.set_key("fz:filt")
    p.prefer_filtered_default()
    assert p.selected_key() == "fz:filt"


def test_detect_dialog_new_step_defaults_to_filtered(app):
    from ui.analyze_dialogs import DetectEventStepDialog
    inputs = [("fz", "Fz"), ("fz:filt", "Fz (filtered)")]
    d = DetectEventStepDialog(None, inputs)            # new step (step=None)
    assert d.input_combo.selected_key() == "fz:filt"


def test_detect_dialog_edit_keeps_saved_input(app):
    from ui.analyze_dialogs import DetectEventStepDialog
    from core.pipeline import DetectEventStep
    inputs = [("fz", "Fz"), ("fz:filt", "Fz (filtered)")]
    step = DetectEventStep(input="fz", label="HS", method="threshold",
                           params={"threshold": 20, "direction": "rising"})
    d = DetectEventStepDialog(None, inputs, step=step)  # editing
    assert d.input_combo.selected_key() == "fz"        # saved raw input preserved


def test_metric_dialog_new_step_defaults_to_filtered(app):
    from ui.analyze_dialogs import MetricStepDialog
    inputs = [("fz", "Fz"), ("fz:filt", "Fz (filtered)")]
    d = MetricStepDialog(None, inputs, [])             # inputs, event_labels=[]
    assert d.input_combo.selected_key() == "fz:filt"
