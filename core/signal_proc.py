import numpy as np
from scipy.signal import butter, cheby1, bessel, filtfilt

FILTER_TYPES = ["Butterworth", "Chebyshev I", "Bessel"]


def apply_lowpass(data, cutoff_hz, fs_hz, order=4, filter_type="Butterworth", ripple_db=0.5):
    arr = np.array(data, dtype=float)
    min_len = order * 3 + 1
    if len(arr) < min_len:
        return arr

    nyq = 0.5 * float(fs_hz)
    # A missing / non-positive sample rate has no usable Nyquist frequency; rather
    # than divide by zero (or compute a negative Wn) just return the signal
    # unfiltered. The caller (Workspace / data_quality) defaults fs to a sane value,
    # so this only triggers on a genuinely broken clock.
    if nyq <= 0:
        return arr
    wn = min(float(cutoff_hz) / nyq, 0.99)
    if wn <= 0:
        return arr

    try:
        if filter_type == "Butterworth":
            b, a = butter(order, wn, btype="low")
        elif filter_type == "Chebyshev I":
            b, a = cheby1(order, float(ripple_db), wn, btype="low")
        elif filter_type == "Bessel":
            b, a = bessel(order, wn, btype="low", norm="phase")
        else:
            b, a = butter(order, wn, btype="low")
        return filtfilt(b, a, arr)
    except Exception:
        return arr


def filter_marker_data(data, fs_hz, cutoff_hz, order=4, filter_type="Butterworth"):
    """Low-pass each marker/axis of a (M, F, 3) array, NaN-safe.

    Occluded samples are NaN; filtering runs only over contiguous finite runs so
    gaps are preserved (never interpolated across). Returns a filtered copy.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim != 3 or data.size == 0:
        return data.copy()
    out = data.copy()
    M, F, _ = data.shape
    for m in range(M):
        for ax in range(3):
            col = out[m, :, ax]
            finite = np.isfinite(col)
            i = 0
            while i < F:
                if finite[i]:
                    j = i
                    while j < F and finite[j]:
                        j += 1
                    col[i:j] = apply_lowpass(col[i:j], cutoff_hz, fs_hz, order, filter_type)
                    i = j
                else:
                    i += 1
    return out
