"""Regression tests for core.data_quality (NaN trimming / gap filling).

Synthetic signals with deliberate NaN padding and dropouts pin the trim and
interpolation behaviour and the report counts the UI shows the user.
"""

import numpy as np
import pytest

from core.data_quality import (
    any_markers_missing,
    clean_dataset,
    clean_markers,
    summarize_marker_reports,
    summarize_reports,
)


def test_clean_dataset_trims_padding_and_fills_interior():
    fs = 100.0
    n = 20
    fz = np.ones(n)
    fz[:3] = np.nan        # head padding
    fz[-2:] = np.nan       # tail padding
    fz[10] = np.nan        # one interior dropout
    data = {
        "time": np.arange(n) / fs,
        "fz": fz.copy(),
        "cop_ap": np.arange(n, dtype=float),
        "cop_ml": np.zeros(n),
        "fs": fs,
    }
    rep = clean_dataset(data)
    assert rep["ok"] is True
    assert rep["trimmed_head"] == 3
    assert rep["trimmed_tail"] == 2
    assert rep["filled"] == 1
    # 20 - 3 - 2 = 15 surviving samples
    assert len(data["time"]) == 15
    # interior NaN was interpolated away -> all finite now
    assert np.isfinite(data["fz"]).all()
    # range bounds follow the trimmed clock
    assert data["range_start"] == pytest.approx(0.0)
    assert data["range_end"] == pytest.approx(14 / fs)


def test_clean_dataset_trims_per_plate_signals():
    """Per-plate force signals (force_signal_keys) are trimmed/filled with the
    same slice as the bare keys so all plates stay aligned to the master clock."""
    fs = 100.0
    n = 20
    fz = np.ones(n)
    fz[:3] = np.nan        # head padding (drives the trim span)
    fz[-2:] = np.nan       # tail padding
    fp2_fz = np.full(n, 5.0)
    fp2_fz[11] = np.nan    # interior dropout on plate 2 only
    data = {
        "time": np.arange(n) / fs,
        "fz": fz.copy(),
        "cop_ap": np.arange(n, dtype=float),
        "cop_ml": np.zeros(n),
        "fp2:fz": fp2_fz.copy(),
        "fp2:cop_ap": np.arange(n, dtype=float),
        "force_signal_keys": ["fp2:fz", "fp2:cop_ap"],
        "n_force_plates": 2,
        "fs": fs,
    }
    clean_dataset(data)
    # Per-plate arrays follow the same 3-head / 2-tail trim -> 15 samples.
    assert len(data["fp2:fz"]) == 15
    assert len(data["fp2:cop_ap"]) == 15
    # Plate-2 interior dropout was interpolated away too.
    assert np.isfinite(data["fp2:fz"]).all()


def test_clean_dataset_clean_signal_is_untouched():
    fs = 100.0
    n = 10
    data = {
        "time": np.arange(n) / fs,
        "fz": np.ones(n),
        "cop_ap": np.zeros(n),
        "cop_ml": np.zeros(n),
        "fs": fs,
    }
    rep = clean_dataset(data)
    assert rep == {"trimmed_head": 0, "trimmed_tail": 0, "filled": 0,
                   "total": n, "ok": True}
    assert len(data["time"]) == n


def test_clean_dataset_all_nan_not_ok():
    n = 5
    data = {
        "time": np.arange(n) / 100.0,
        "fz": np.full(n, np.nan),
        "cop_ap": np.zeros(n),
        "cop_ml": np.zeros(n),
        "fs": 100.0,
    }
    rep = clean_dataset(data)
    assert rep["ok"] is False


def test_clean_dataset_empty():
    rep = clean_dataset({"time": np.array([])})
    assert rep["total"] == 0
    assert rep["ok"] is True


def test_clean_markers_fills_short_gap_keeps_long_gap():
    M, F = 1, 30
    arr = np.zeros((M, F, 3))
    arr[0, :, 0] = np.arange(F)
    arr[0, 5:8, 0] = np.nan        # short gap (len 3) with both neighbours -> filled
    arr[0, 20:, 0] = np.nan        # long open-ended gap -> stays occluded
    markers = {"data": arr.copy(), "labels": ["A"], "time": np.arange(F) / 100.0}
    rep = clean_markers(markers, max_gap_frames=10)
    assert rep["n_markers"] == 1
    assert rep["markers_filled"] == 3
    # short gap interpolated back to the linear ramp
    assert markers["data"][0, 5, 0] == pytest.approx(5.0)
    assert markers["data"][0, 6, 0] == pytest.approx(6.0)
    # long gap left as NaN (true occlusion)
    assert np.isnan(markers["data"][0, 25, 0])
    assert rep["markers_occluded"] == 10


def test_clean_markers_long_gap_not_filled():
    M, F = 1, 30
    arr = np.zeros((M, F, 3))
    arr[0, :, 0] = np.arange(F)
    arr[0, 5:20, 0] = np.nan        # gap len 15 > max_gap_frames -> not filled
    markers = {"data": arr.copy(), "labels": ["A"], "time": np.arange(F) / 100.0}
    rep = clean_markers(markers, max_gap_frames=10)
    assert rep["markers_filled"] == 0
    assert np.isnan(markers["data"][0, 10, 0])


def test_clean_markers_empty():
    rep = clean_markers({"data": np.zeros((0, 0, 0)), "labels": []})
    assert rep["n_markers"] == 0


def test_clean_markers_multi_marker_axis_independent():
    """The vectorized fill must treat each (marker, axis) series independently:
    a short gap on one marker/axis is filled, an edge-touching gap on another is
    left, and a long gap is left — all in the same call. Pins the (3M, F) run
    detector against per-column semantics."""
    M, F = 3, 40
    arr = np.zeros((M, F, 3))
    for m in range(M):
        for ax in range(3):
            arr[m, :, ax] = np.arange(F) + 100 * m + 10 * ax  # distinct ramps
    # marker0 axis0: short interior gap (len 3) -> filled
    arr[0, 5:8, 0] = np.nan
    # marker1 axis2: head-edge gap (no left neighbour) -> left as occlusion
    arr[1, 0:4, 2] = np.nan
    # marker2 axis1: long gap (len 15 > 10) -> left
    arr[2, 10:25, 1] = np.nan
    markers = {"data": arr.copy()}
    rep = clean_markers(markers, max_gap_frames=10)
    d = markers["data"]
    # marker0 axis0 short gap interpolated back to its ramp
    assert d[0, 5, 0] == pytest.approx(5.0)
    assert d[0, 7, 0] == pytest.approx(7.0)
    # marker1 axis2 head gap NOT filled (its frames are still "bad")
    assert np.isnan(d[1, 0, 2])
    # marker2 axis1 long gap NOT filled
    assert np.isnan(d[2, 15, 1])
    # only the 3 short-gap frames were repaired (a frame is bad if ANY axis NaN):
    # marker0 had 3 frames repaired; marker1's 4 + marker2's 15 stay occluded.
    assert rep["markers_filled"] == 3
    assert rep["markers_occluded"] == 4 + 15


def test_clean_markers_clean_input_untouched():
    """A fully finite marker block is returned unchanged with a zero report."""
    arr = np.random.default_rng(0).normal(0, 1, (5, 50, 3))
    markers = {"data": arr.copy()}
    rep = clean_markers(markers)
    assert rep == {"n_markers": 5, "markers_filled": 0, "markers_occluded": 0,
                   "markers_missing": 0, "labels_missing": []}
    assert np.array_equal(markers["data"], arr)


def test_clean_markers_reports_fully_missing_marker_by_label():
    """A marker that is occluded for the WHOLE trial is flagged as fully missing
    (it silently breaks any segment/joint that needs it) and named by label."""
    M, F = 3, 20
    arr = np.zeros((M, F, 3))
    for m in range(M):
        arr[m, :, 0] = np.arange(F) + 10 * m
    arr[1, :, :] = np.nan        # marker "B" absent the entire trial
    markers = {"data": arr.copy(), "labels": ["A", "B", "C"],
               "time": np.arange(F) / 100.0}
    rep = clean_markers(markers)
    assert rep["markers_missing"] == 1
    assert rep["labels_missing"] == ["B"]


def test_clean_markers_partial_gap_is_not_fully_missing():
    """A long but partial occlusion is NOT 'fully missing' (some frames survive),
    so it stays an info-level gap, not a missing-marker warning."""
    M, F = 1, 30
    arr = np.zeros((M, F, 3))
    arr[0, :, 0] = np.arange(F)
    arr[0, 5:25, 0] = np.nan      # 20-frame gap (> max), but frames 0-4 / 25-29 ok
    markers = {"data": arr.copy(), "labels": ["A"], "time": np.arange(F) / 100.0}
    rep = clean_markers(markers, max_gap_frames=10)
    assert rep["markers_missing"] == 0
    assert rep["markers_occluded"] > 0


def test_summarize_marker_reports_and_severity():
    reports = [
        ("trialA", {"markers_filled": 4, "markers_occluded": 4,
                    "markers_missing": 0, "labels_missing": []}),
        ("trialB", {"markers_filled": 0, "markers_occluded": 60,
                    "markers_missing": 2, "labels_missing": ["LASI", "RASI"]}),
    ]
    text = summarize_marker_reports(reports)
    assert "trialA" in text and "filled 4 marker gap(s)" in text
    assert "trialB" in text and "2 marker(s) fully missing" in text
    assert "LASI" in text and "RASI" in text
    assert any_markers_missing(reports) is True
    # all-complete -> empty note, not severe
    clean = [("t", {"markers_filled": 0, "markers_occluded": 0,
                    "markers_missing": 0, "labels_missing": []})]
    assert summarize_marker_reports(clean) == ""
    assert any_markers_missing(clean) is False


def test_summarize_reports_text():
    reports = [
        ("trialA", {"trimmed_head": 3, "trimmed_tail": 2, "filled": 1}),
        ("trialB", {"trimmed_head": 0, "trimmed_tail": 0, "filled": 0}),
    ]
    text = summarize_reports(reports)
    assert "trialA" in text
    assert "trialB" not in text       # nothing repaired -> omitted
    assert summarize_reports([]) == ""
