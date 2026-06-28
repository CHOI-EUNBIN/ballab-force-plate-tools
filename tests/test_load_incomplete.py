"""Incomplete-data load handling: the app must NOTIFY/WARN, not silently accept
broken data. Covers (1) a fully-missing marker escalates the load dialog to a
warning, (2) a clean load stays an info dialog, (3) a CSV missing a required
column raises a clear message (not a raw KeyError)."""
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


def _capture_boxes(monkeypatch):
    """Patch ui.analyze_tab.QMessageBox so warning/information record their calls
    instead of opening a modal dialog. Returns the list of (kind, title, text)."""
    import ui.analyze_tab as at
    calls = []

    class _Stub:
        @staticmethod
        def warning(parent, title, text, *a, **k):
            calls.append(("warning", title, text))

        @staticmethod
        def information(parent, title, text, *a, **k):
            calls.append(("information", title, text))

    monkeypatch.setattr(at, "QMessageBox", _Stub)
    return calls


def _fake_dataset(name, marker_report):
    return {
        "path": f"/fake/{name}.c3d", "name": name, "folder": (),
        "time": np.arange(10) / 100.0, "fs": 100.0,
        "_clean_report": {"trimmed_head": 0, "trimmed_tail": 0, "filled": 0},
        "_marker_report": marker_report,
    }


def test_missing_marker_escalates_load_to_warning(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    calls = _capture_boxes(monkeypatch)
    monkeypatch.setattr(tab, "_read_dataset", lambda path, folder=(): _fake_dataset(
        "bad", {"markers_filled": 0, "markers_occluded": 30, "markers_missing": 1,
                "labels_missing": ["LASI"]}))
    tab._ingest([("/fake/bad.c3d", ())])
    kinds = [c[0] for c in calls]
    assert "warning" in kinds, f"expected a warning, got {calls}"
    warn = next(c for c in calls if c[0] == "warning")
    assert "incomplete" in warn[1].lower()
    assert "LASI" in warn[2]


def test_complete_markers_stay_info(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    calls = _capture_boxes(monkeypatch)
    monkeypatch.setattr(tab, "_read_dataset", lambda path, folder=(): _fake_dataset(
        "good", {"markers_filled": 0, "markers_occluded": 0, "markers_missing": 0,
                 "labels_missing": []}))
    tab._ingest([("/fake/good.c3d", ())])
    assert [c[0] for c in calls] == ["information"]


def test_csv_missing_required_column_clear_error(app, tmp_path):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    p = tmp_path / "bad.csv"
    # No "Fz" column.
    p.write_text("time_s,COP_AP,COP_ML\n0.0,1.0,2.0\n0.01,1.1,2.1\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        tab._read_csv_dataset(str(p))
    assert "Fz" in str(exc.value) and "required" in str(exc.value).lower()
