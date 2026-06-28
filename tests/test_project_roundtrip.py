"""Regression test for the P1 fix: a saved project must preserve markers and the
kinematic model so reopening it does not lose marker arrays / joint angles.

This exercises the *real* serialisation path:
  * ``AnalyzeTab._markers_to_npz_bytes`` / ``_markers_from_npz_path`` (the static,
    UI-free marker (de)serialisers), and
  * ``core.project.save_project`` / ``load_project`` (the .ballab zip), and
  * ``MarkerModel.to_dict`` / ``from_dict`` + a calibrate/apply recompute.

It does not launch the GUI: AnalyzeTab is imported only for its two static
helpers, under the offscreen Qt platform. If Qt cannot be imported the test
skips rather than fails.
"""

import os
import tempfile

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.project import save_project, load_project
from core.marker_model import MarkerModel

try:
    from ui.analyze_tab import AnalyzeTab
    _HAVE_TAB = True
except Exception:                       # pragma: no cover - environment guard
    _HAVE_TAB = False

pytestmark = pytest.mark.skipif(not _HAVE_TAB, reason="Qt/AnalyzeTab unavailable")


def _synthetic_markers(F=12):
    """Static-style trial with a knee + ankle medial/lateral pair and a cluster."""
    labels = ["RMKNEE", "RLKNEE", "RMANK", "RLANK", "RC1", "RC2", "RC3"]
    data = np.zeros((7, F, 3))
    data[0] = [0, 0, 0]
    data[1] = [2, 0, 0]            # knee midpoint = (1, 0, 0)
    data[2] = [0, -5, 0]
    data[3] = [2, -5, 0]          # ankle midpoint = (1, -5, 0)
    data[4] = [0, 1, 0]
    data[5] = [1, 1, 0]
    data[6] = [0, 0, 1]
    return {"labels": labels, "data": data, "time": np.arange(F) / 100.0,
            "rate": 100.0, "units": "mm"}


def _model():
    return MarkerModel(
        joints=[
            {"name": "R_KNEE", "method": "midpoint", "medial": "RMKNEE",
             "lateral": "RLKNEE", "cluster": ["RC1", "RC2", "RC3"]},
            {"name": "R_ANKLE", "method": "midpoint", "medial": "RMANK",
             "lateral": "RLANK", "cluster": ["RC1", "RC2", "RC3"]},
        ],
        segments=[
            {"name": "SHANK", "proximal": "R_KNEE", "distal": "R_ANKLE"},
            {"name": "REF", "proximal": "RC1", "distal": "RC2"},
        ],
        angles=[{"name": "R_KNEE_angle", "segment_a": "SHANK", "segment_b": "REF"}],
        name="demo",
    )


def test_markers_npz_roundtrip_preserves_array():
    markers = _synthetic_markers()
    blob = AnalyzeTab._markers_to_npz_bytes(markers)
    assert blob is not None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.npz")
        with open(p, "wb") as f:
            f.write(blob)
        restored = AnalyzeTab._markers_from_npz_path(p)
    assert restored is not None
    np.testing.assert_array_equal(restored["data"], markers["data"])
    assert restored["labels"] == markers["labels"]
    assert restored["rate"] == pytest.approx(100.0)
    assert restored["units"] == "mm"


def test_markers_to_npz_empty_returns_none():
    assert AnalyzeTab._markers_to_npz_bytes(None) is None
    assert AnalyzeTab._markers_to_npz_bytes({"data": np.zeros((0, 0, 0))}) is None


def test_project_roundtrip_preserves_markers_and_model():
    markers = _synthetic_markers()
    model = _model()

    manifest = {
        "tab": "analyze", "version": 2,
        "datasets": [{
            "name": "s", "data_file": "data/0.csv",
            "markers_file": "data/0_markers.npz",
            "model": model.to_dict(),
        }],
    }
    files = {
        "data/0.csv": b"sample,time_s,Fz,COP_AP,COP_ML,fs\n0,0,0,0,0,100\n",
        "data/0_markers.npz": AnalyzeTab._markers_to_npz_bytes(markers),
    }

    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "demo.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)

    entry = m2["datasets"][0]
    # markers restored
    mk = AnalyzeTab._markers_from_npz_path(os.path.join(datadir, entry["markers_file"]))
    np.testing.assert_array_equal(mk["data"], markers["data"])
    # model restored and structurally identical
    mdl = MarkerModel.from_dict(entry["model"])
    assert mdl.joints == model.joints
    assert mdl.segments == model.segments
    assert mdl.angles == model.angles
    # model_result recompute path works on the restored data
    mdl.calibrate(mk)
    res = mdl.apply(mk)
    assert "R_KNEE_angle" in res["angles"]
    # SHANK = ankle(1,-5,0) - knee(1,0,0) = (0,-5,0); REF = (1,0,0) -> 90 deg
    assert res["angles"]["R_KNEE_angle"][0] == pytest.approx(90.0, abs=1e-4)


def test_old_project_without_markers_still_loads():
    """A v1-style manifest (no markers_file / model) must round-trip unchanged —
    the loader simply has nothing extra to restore (backward compatibility)."""
    manifest = {
        "tab": "analyze", "version": 1,
        "datasets": [{"name": "old", "data_file": "data/0.csv"}],
    }
    files = {"data/0.csv": b"sample,time_s,Fz,COP_AP,COP_ML,fs\n0,0.0,1,2,3,1000\n"}
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "old.ballab")
        save_project(proj, manifest, files)
        m2, _ = load_project(proj)
    entry = m2["datasets"][0]
    assert "markers_file" not in entry
    assert "model" not in entry


# --------------------------------------------------------------------------- #
# v5 fix: reopening a project restores the pipeline AND its computed RESULTS.
# The bug was that load restored the pipeline steps but never re-ran them, so
# RESULTS (metrics / events) came back empty. These tests drive the REAL
# AnalyzeTab.save_project_state / load_project_state roundtrip headless.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    import sys
    return QApplication.instance() or QApplication(sys.argv)


def _force_dataset(name="trialA"):
    """A force-only synthetic trial with a clear vertical-GRF peak."""
    from core.c3d_reader import ensure_fp1_from_bare
    fs, n = 100.0, 400
    t = np.arange(n) / fs
    fz = np.clip(700 + 300 * np.sin(2 * np.pi * 1.0 * t), 0, None)
    ds = {
        "path": name + ".csv", "name": name, "time": t, "fs": fs,
        "fz": fz, "cop_ap": 5 * np.sin(2 * np.pi * 0.5 * t),
        "cop_ml": 3 * np.cos(2 * np.pi * 0.5 * t),
        "analysis": None, "events": [], "folder": (), "role": "dynamic",
        "trial": name, "range_start": float(t[0]), "range_end": float(t[-1]),
        "_checked": True,
    }
    ensure_fp1_from_bare(ds)
    return ds


def _run_save_reopen(tab_factory):
    """Build a tab via ``tab_factory`` with a run pipeline, run it, save, then
    reopen into a fresh tab. Returns (saved_tab, manifest, reopened_tab)."""
    from core.pipeline import ComputeStep, MetricStep, DetectEventStep

    tab = tab_factory()
    tab.datasets = [_force_dataset()]
    tab.current_index = 0
    tab.pipeline.add(ComputeStep(input="fp1:fz", method="abs", name="AbsFz"))
    tab.pipeline.add(DetectEventStep(
        input="fp1:fz", label="HS", method="threshold",
        params={"threshold": 800, "direction": "rising"}, color="#F97316"))
    tab.pipeline.add(MetricStep(input="fp1:fz", op="max", name="PeakFz"))
    tab._refresh_file_list()
    tab._select_dataset_item(0)
    tab._refresh_pipeline_list()
    tab.show_btn.setChecked(True)            # ▶Run -> compute RESULTS

    manifest, files = tab.save_project_state()
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "demo.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)
        tab2 = tab_factory()
        tab2.load_project_state(m2, datadir)
    return tab, m2, tab2


def test_reopen_restores_pipeline_and_results(app):
    """The core regression: a saved+reopened project must restore the pipeline
    steps AND its computed RESULTS (not just the recipe with empty results)."""
    from ui.analyze_tab import AnalyzeTab
    saved, manifest, reopened = _run_save_reopen(AnalyzeTab)

    # New manifest carries the run state + version bump (back-compat additive).
    assert manifest.get("version") >= 5
    assert manifest.get("results_shown") is True

    # Pipeline step count + kinds match.
    saved_kinds = [type(s).__name__ for s in saved.pipeline.steps]
    reopened_kinds = [type(s).__name__ for s in reopened.pipeline.steps]
    assert reopened_kinds == saved_kinds
    assert len(reopened_kinds) == 3

    # RESULTS are NOT empty after reopen (the bug): the run re-fired.
    assert reopened.show_btn.isChecked() is True
    assert reopened.view_mode == "analysis"
    assert len(reopened.analysis_results) == 1
    ds = reopened.datasets[0]
    assert ds.get("analysis") is not None
    metrics = ds["analysis"]["metrics"]
    assert "PeakFz" in metrics
    # PeakFz of the synthetic GRF is the 1000 N crest (CSV float roundtrip tol).
    assert metrics["PeakFz"][0] == pytest.approx(1000.0, abs=1.0)


def test_reopen_restores_statistics_rows(app):
    """Rows the user sent to Statistics are persisted with the project and
    restored into the shared store on reopen."""
    from core.results_store import ResultsStore

    store1 = ResultsStore()
    # saved tab uses store1 (and we push a row to it before save)
    saved, manifest, _ = _run_save_reopen(lambda: _tab_with_store(store1))
    store1.add_rows([{"File": "trialA", "Range": "Selected range",
                      "PeakFz (N)": 1000.0}], source="Analyze")
    # re-save now that the store has a row
    manifest, files = saved.save_project_state()
    assert manifest.get("statistics_rows") == [
        {"File": "trialA", "Range": "Selected range", "PeakFz (N)": 1000.0}]

    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "demo.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)
        store2 = ResultsStore()
        tab2 = _tab_with_store(store2)
        tab2.load_project_state(m2, datadir)
    assert store2.rows() == [
        {"File": "trialA", "Range": "Selected range", "PeakFz (N)": 1000.0}]


def _tab_with_store(store):
    from ui.analyze_tab import AnalyzeTab
    t = AnalyzeTab()
    t.set_results_store(store)
    return t


def test_v4_project_loads_unrun(app):
    """A pre-v5 project (no results_shown / statistics_rows) must still open and
    simply stay un-run — the loader has nothing extra to do (backward compat)."""
    from ui.analyze_tab import AnalyzeTab
    manifest = {
        "tab": "analyze", "version": 4, "current_index": 0,
        "panel_visible": {}, "analysis_ranges": [], "folders": [],
        "pipeline": {"steps": []},
        "datasets": [{"name": "old", "data_file": "data/0.csv",
                      "fs": 1000.0, "role": "dynamic"}],
    }
    files = {"data/0.csv":
             b"sample,time_s,Fz,COP_AP,COP_ML,fs\n0,0.0,1,2,3,1000\n"
             b"1,0.001,2,3,4,1000\n"}
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "old.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)
        tab = AnalyzeTab()
        tab.load_project_state(m2, datadir)
    assert tab.view_mode == "review"
    assert tab.show_btn.isChecked() is False
    assert len(tab.datasets) == 1


def test_reopen_restores_signal_graph_views(app):
    """A derived-signal 'View as graph' selection (e.g. an |Fz| compute output)
    and a RAW force-plate toggle must both survive save+reopen. The bug: load
    restored only ':filt' views into _signal_views, so derived-signal graphs were
    silently dropped (force-plate / derived graphs vanished on reopen)."""
    from ui.analyze_tab import AnalyzeTab
    from core.pipeline import ComputeStep

    tab = AnalyzeTab()
    tab.datasets = [_force_dataset()]
    tab.current_index = 0
    tab.pipeline.add(ComputeStep(input="fp1:fz", method="abs", name="AbsFz"))
    tab._refresh_file_list()
    tab._select_dataset_item(0)
    tab._refresh_pipeline_list()
    tab._refresh_force_controls(tab.datasets[0])
    tab.panel_checks["fp1:fz"].setChecked(True)   # RAW force graph ON
    tab._view_signal("AbsFz")                      # derived "View as graph" ON

    manifest, files = tab.save_project_state()
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "demo.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)
        tab2 = AnalyzeTab()
        tab2.load_project_state(m2, datadir)

    assert "AbsFz" in tab2._signal_views          # derived view restored
    assert tab2.panel_visible.get("fp1:fz") is True  # raw force toggle restored
    assert bool(tab2.datasets[0].get("force_signal_keys"))  # force plate present


def test_reopen_restores_force_plates_and_grf(app):
    """A reopened project must restore the force-plate GEOMETRY (for the 3D plate
    squares) and rebuild the GRF VECTOR arrow. The bug: geometry + raw moments
    come from the c3d, not the saved CSV, so build_grf returned None on reload and
    both the plates and the vector vanished."""
    from ui.analyze_tab import AnalyzeTab
    from core.c3d_reader import build_grf

    ds = _force_dataset()
    zeros = ds["fz"] * 0.0
    ds["force_plates"] = [{"corners": np.zeros((4, 3)), "origin": np.zeros(3),
                           "R": np.eye(3)}]
    ds["_fp_raw"] = [{"fx": zeros, "fy": zeros, "fz": ds["fz"],
                      "mx": zeros, "my": zeros}]
    ds["_clean_report"] = {"trimmed_head": 0}
    ds["grf"] = build_grf(ds)
    assert ds["grf"], "sanity: GRF should build from geometry + raw"

    tab = AnalyzeTab()
    tab.datasets = [ds]
    tab.current_index = 0
    tab._refresh_file_list()
    tab._select_dataset_item(0)

    manifest, files = tab.save_project_state()
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "demo.ballab")
        save_project(proj, manifest, files)
        m2, datadir = load_project(proj)
        tab2 = AnalyzeTab()
        tab2.load_project_state(m2, datadir)

    cur = tab2.datasets[0]
    assert cur.get("force_plates")    # 3D force-plate geometry restored
    assert cur.get("grf")             # GRF vector arrow rebuilt
