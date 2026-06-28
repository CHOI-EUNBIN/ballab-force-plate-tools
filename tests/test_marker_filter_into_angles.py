"""A marker FilterStep must flow into the KINEMATICS (joint angles / COM), not
only into the displayed marker-coordinate curves.

Regression for the bug where ``_marker_display_data`` filtered into a separate
``data_filt`` cache while ``model.apply`` kept reading the raw ``markers['data']``,
so a marker filter never reached the angles.
"""
import os
import sys
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication

EX = os.path.join(os.path.dirname(__file__), "..", "examples", "YA01")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _noisy_markers(n_markers=2, F=200, seed=0):
    rng = np.random.default_rng(seed)
    smooth = np.cumsum(rng.normal(size=(n_markers, F, 3)), axis=1)
    noisy = smooth + rng.normal(scale=2.0, size=(n_markers, F, 3))
    return {"labels": [f"M{i}" for i in range(n_markers)], "rate": 100.0,
            "time": np.arange(F) / 100.0, "data": noisy, "units": "mm"}


def _marker_filter_step():
    from core.pipeline import FilterStep
    from core.signals import FilterSpec
    return FilterStep(spec=FilterSpec(type="Butterworth", cutoff_hz=6, order=4),
                      targets=[], markers=True)


def test_markers_for_analysis_swaps_in_filtered_data(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    markers = _noisy_markers()
    raw_ref = markers["data"].copy()

    # No marker filter -> the analysis markers ARE the raw markers (unchanged).
    out = tab._markers_for_analysis(markers)
    assert out["data"] is markers["data"]

    # With a marker-targeting FilterStep -> data is the filtered array, raw kept.
    tab.pipeline.steps.append(_marker_filter_step())
    out2 = tab._markers_for_analysis(markers)
    assert out2["data"].shape == raw_ref.shape
    assert not np.allclose(out2["data"], raw_ref)          # filtering changed it
    assert np.allclose(markers["data"], raw_ref)           # raw preserved on the dict
    # filtered trajectories are smoother: smaller frame-to-frame jitter
    assert np.nanstd(np.diff(out2["data"], axis=1)) < np.nanstd(np.diff(raw_ref, axis=1))


@pytest.mark.skipif(not os.path.isdir(EX), reason="YA01 examples not present")
def test_marker_filter_flows_into_joint_angles(app):
    from ui.analyze_tab import AnalyzeTab
    from core.c3d_reader import read_c3d
    from core.marker_model import auto_build_model

    st = read_c3d(os.path.join(EX, "static.c3d"))["markers"]
    dyn = read_c3d(os.path.join(EX, "st_1.c3d"))["markers"]
    model = auto_build_model(st)
    raw_ref = dyn["data"].copy()

    tab = AnalyzeTab()
    static_ds = {"role": "static", "folder": (), "name": "st",
                 "markers": st, "model": model}
    dyn_ds = {"role": "dynamic", "folder": (), "name": "dyn", "markers": dyn}
    tab.datasets = [static_ds, dyn_ds]

    # Unfiltered angles.
    tab._ensure_model_result(dyn_ds)
    a0 = np.asarray(dyn_ds["model_result"]["angles"]["R_KNEE_angle_FE"], float).copy()

    # Add a marker filter -> recompute -> angles must change (filter reached them).
    tab.pipeline.steps.append(_marker_filter_step())
    tab._ensure_model_result(dyn_ds)
    a1 = np.asarray(dyn_ds["model_result"]["angles"]["R_KNEE_angle_FE"], float)

    assert not np.allclose(a0, a1, atol=1e-6), "marker filter did not reach the angles"
    # raw marker data preserved (filter is non-destructive on the source dict)
    assert np.allclose(dyn_ds["markers"]["data"], raw_ref, equal_nan=True)
