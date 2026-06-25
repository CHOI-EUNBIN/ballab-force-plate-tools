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
    vals = d.values()
    step = NormalizeStep(**vals)               # must construct without error
    assert step.kind == "normalize"
