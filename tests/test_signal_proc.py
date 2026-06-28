"""Edge-case regression tests for core.signal_proc (low-pass filtering).

These pin the graceful-degrade contracts at the module boundary: a broken /
missing sample rate or a too-short signal must never raise — the filter just
returns the input unchanged so one bad clock can't crash an analysis.
"""

import numpy as np
import pytest

from core.signal_proc import apply_lowpass, filter_marker_data


def test_apply_lowpass_zero_fs_returns_input_unchanged():
    """REGRESSION: fs=0 used to raise ZeroDivisionError (0.5*0 -> divide). It now
    degrades gracefully: no usable Nyquist -> return the signal as-is."""
    x = np.random.default_rng(0).normal(size=200)
    out = apply_lowpass(x, 10.0, 0.0)
    assert np.array_equal(out, x)


def test_apply_lowpass_negative_fs_returns_input_unchanged():
    x = np.random.default_rng(1).normal(size=200)
    out = apply_lowpass(x, 10.0, -100.0)
    assert np.array_equal(out, x)


def test_apply_lowpass_short_signal_returns_input_unchanged():
    """A signal shorter than the filter's padding length is returned unchanged
    (filtfilt would otherwise error)."""
    x = np.arange(5.0)
    out = apply_lowpass(x, 10.0, 100.0, order=4)
    assert np.array_equal(out, x)


def test_apply_lowpass_passes_a_normal_signal():
    """Sanity: a valid call still filters (a clean sine survives a above-cutoff
    low-pass roughly intact) and returns a finite same-length array."""
    fs = 100.0
    t = np.arange(500) / fs
    x = np.sin(2 * np.pi * 1.0 * t)        # 1 Hz, well under a 10 Hz cutoff
    out = apply_lowpass(x, 10.0, fs)
    assert out.shape == x.shape
    assert np.isfinite(out).all()
    assert np.std(out - x) < 0.05          # barely changed


def test_filter_marker_data_zero_fs_does_not_raise():
    """Marker filtering with a broken rate degrades per-run to unchanged data
    (each contiguous run is passed through apply_lowpass, which now no-ops)."""
    data = np.random.default_rng(2).normal(size=(2, 300, 3))
    out = filter_marker_data(data, 0.0, 6.0)
    assert out.shape == data.shape
    np.testing.assert_array_equal(out, data)


def test_filter_marker_data_preserves_nan_gaps():
    """An occluded run (NaN) stays NaN — filtering never bridges a gap."""
    data = np.zeros((1, 100, 3))
    data[0, 40:50, :] = np.nan
    out = filter_marker_data(data, 100.0, 6.0)
    assert np.isnan(out[0, 40:50, :]).all()
    assert np.isfinite(out[0, :40, :]).all()
