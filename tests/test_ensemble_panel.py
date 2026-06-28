import os
import sys
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_panel_pools_sources_and_reports_n(app):
    from ui.ensemble_panel import EnsemblePanel
    panel = EnsemblePanel(None)
    src = [
        ("c3d_1", {"matrix": np.zeros((3, 101)), "label": "angle:R_KNEE_FE"}),
        ("c3d_2", {"matrix": np.ones((2, 101)),  "label": "angle:R_KNEE_FE"}),
    ]
    panel.set_sources(src)
    assert panel.n_epochs() == 5            # 3 + 2 pooled
    # mean at node 0 = (0*3 + 1*2)/5 = 0.4
    assert np.isclose(panel.stats()["mean"][0], 0.4)


def test_panel_export_csv_writes_file(app, tmp_path):
    from ui.ensemble_panel import EnsemblePanel
    panel = EnsemblePanel(None)
    panel.set_sources([("t", {"matrix": np.arange(202.0).reshape(2, 101),
                              "label": "fz"})])
    out = tmp_path / "ens.csv"
    panel.export_csv(str(out))
    text = out.read_text()
    assert text.splitlines()[0].startswith("percent,")
    assert "mean,sd" in text.splitlines()[0]


def test_normalize_dialog_values_roundtrip(app):
    from ui.ensemble_panel import NormalizeStepDialog
    from core.pipeline import NormalizeStep
    d = NormalizeStepDialog(None, [("fz", "Fz"), ("fz:filt", "Fz (filtered)")],
                            ["HS", "TO"])
    d.name_edit.setText("knee_cycle")          # accept() now requires a name
    vals = d.values()
    step = NormalizeStep(**vals)               # must construct without error
    assert step.kind == "normalize"


def test_normalize_dialog_empty_name_keeps_dialog_open(app, monkeypatch):
    """Item 2: an empty-name accept() validates INSIDE the dialog — it shows a
    message and does NOT close (so the user can fix it), matching the parity
    pattern of DetectEventStepDialog.accept."""
    from ui.ensemble_panel import NormalizeStepDialog
    from PyQt6.QtWidgets import QDialog, QMessageBox

    # Stub the modal so the test never blocks on a real message box.
    shown = {"n": 0}
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.__setitem__("n", shown["n"] + 1))

    d = NormalizeStepDialog(None, [("fz", "Fz")], ["HS", "TO"])
    d.name_edit.setText("")                     # empty / whitespace-only name
    d.accept()
    assert shown["n"] == 1                       # the warning was shown
    assert d.result() != QDialog.DialogCode.Accepted   # dialog did NOT accept/close


def test_normalize_dialog_valid_name_accepts(app):
    """Item 2: a valid name lets accept() through (dialog closes as accepted)."""
    from ui.ensemble_panel import NormalizeStepDialog
    from PyQt6.QtWidgets import QDialog

    d = NormalizeStepDialog(None, [("fz", "Fz")], ["HS", "TO"])
    d.name_edit.setText("knee_cycle")
    d.accept()
    assert d.result() == QDialog.DialogCode.Accepted
    assert d.values()["name"] == "knee_cycle"


def test_ensemble_overlay_row_relabelled():
    """Item 3: the MAIN-area RESULTS·Signals toggle is relabelled "Ensemble
    overlay" so it can't be confused with the "Ensemble" data/export panel.
    Asserted at source level (building the full AnalyzeTab is too heavy here)."""
    import inspect
    from ui.analyze_tab import AnalyzeTab
    src = inspect.getsource(AnalyzeTab._append_ensemble_signal_row)
    assert "Ensemble overlay" in src
    # The old bare "▾ Ensemble" header (no "overlay") must be gone.
    assert '"▾ Ensemble"' not in src
