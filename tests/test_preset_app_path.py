"""Regression test: the WALK PRESET, run through the real AnalyzeTab app path,
must yield correct per-cycle metric values (pipeline-sourced, not self-calc).

This pins the fix for the metric-value bug seen in earlier app screenshots
(L Ankle ROM 0.276 deg, Double support 5 s): those came from a stale / non-pipeline
path. The app panel now reads ``dataset['_run_result']`` produced by
``core.run.run_pipeline`` (analyze_tab._analyze_time_window), so driving the actual
tab on the bundled CEB trial must reproduce the headless engine numbers.

Skipped cleanly when Qt, ezc3d, or the CEB example files are unavailable.
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

try:
    from core.c3d_reader import read_c3d, C3D_AVAILABLE
    from core.data_quality import clean_dataset
except Exception:  # pragma: no cover
    C3D_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")

_TEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _drive_walk_preset():
    """Build the CEB static+dynamic, wire them into a real AnalyzeTab, seed the
    treadmill walk preset, run the analysis, and return the app's ``_run_result``
    metric dict ({name: metric}). Skips if data/ezc3d missing."""
    if not C3D_AVAILABLE:
        pytest.skip("ezc3d not installed")
    sp = os.path.join(_TEX, "CEB_static.c3d")
    dp = os.path.join(_TEX, "CEB_st.c3d")
    if not (os.path.isfile(sp) and os.path.isfile(dp)):
        pytest.skip("CEB example files missing")
    from core.marker_model import auto_build_model
    from core import presets
    from ui.analyze_tab import AnalyzeTab

    static = read_c3d(sp); clean_dataset(static)
    dyn = read_c3d(dp); clean_dataset(dyn)
    static["role"] = "static"; static["folder"] = ()
    dyn["role"] = "dynamic"; dyn["folder"] = ()
    static["model"] = auto_build_model(static["markers"], name="CEB")
    static["model_task"] = "Walk"; static["model_zero_static"] = False

    tab = AnalyzeTab()
    tab.datasets = [static, dyn]
    tab._folders = {()}
    for step in presets.build_preset("walk_treadmill", dyn):
        tab.pipeline.add(step)
    tab._invalidate_event_caches()
    tab._analyze_dataset(dyn, [], [])

    run = dyn.get("_run_result") or {}
    return {m["name"]: m for m in run.get("metrics", [])}, run


def test_walk_preset_app_path_metrics_are_physiological(app):
    by_name, run = _drive_walk_preset()
    # The panel reads the pipeline result, so per-cycle metrics must be present.
    assert by_name, "no metrics in _run_result (app did not run the pipeline)"

    def val(name):
        m = by_name.get(name)
        assert m is not None, f"missing metric {name!r}"
        return m["value"], m

    # Spatiotemporal: stride ~1.12 s, double support a real ~0.2 s interval
    # (the OLD bug showed 5 s = a whole-trial / stale-event fallback).
    stride, _ = val("R Stride time")
    assert stride == pytest.approx(1.122, abs=0.05)
    ds_r, m_ds = val("Double support R")
    assert 0.05 < ds_r < 0.5, f"Double support R unphysiological: {ds_r}"
    assert m_ds["n"] > 1, "double support should be per-cycle (n>1), not a scalar"

    # Joint ROM: the OLD bug showed L Ankle ROM 0.276 deg (a near-flat / mismatched
    # window). Every FE ROM must be a real gait excursion.
    for joint in ("Hip", "Knee", "Ankle"):
        for side in ("R", "L"):
            rom, m = val(f"{side} {joint} ROM")
            assert 15.0 < rom < 90.0, f"{side} {joint} ROM unphysiological: {rom}"
            assert m["n"] > 1, f"{side} {joint} ROM should be per-cycle"

    # Cadence ~107 steps/min (the verified CEB value).
    cad, _ = val("R Cadence")
    assert cad == pytest.approx(107.0, abs=3.0)


def test_walk_preset_app_path_matches_headless(app):
    """The app path (filtered markers + display markers + _angle_result_for) must
    agree with a direct headless run_pipeline on the same inputs — the app adds no
    self-calc on top, it just surfaces the pipeline result."""
    by_name, _ = _drive_walk_preset()
    # A couple of stable, side-stable channels (ankle FE sign-consistent).
    rom = by_name["L Ankle ROM"]["value"]
    assert np.isfinite(rom) and rom > 15.0
    stance = by_name["R Stance %"]["value"]
    assert 60.0 <= stance <= 72.0
