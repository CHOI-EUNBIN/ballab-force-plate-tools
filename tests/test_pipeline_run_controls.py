# tests/test_pipeline_run_controls.py
import os, sys
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


def test_run_button_is_plain_not_toggle(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert not tab.show_btn.isCheckable()          # plain momentary button
    assert hasattr(tab, "_on_run_clicked")
    assert not hasattr(tab, "_on_show_results_toggled")


def test_run_click_runs_without_clearing(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    calls = []
    tab._run_analysis = lambda: calls.append(1) or True
    tab._on_run_clicked()
    tab._on_run_clicked()
    assert calls == [1, 1]                          # every click runs; nothing clears
