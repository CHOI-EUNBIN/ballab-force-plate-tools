import numpy as np
from scipy.signal import butter, cheby1, bessel, filtfilt

FILTER_TYPES = ["Butterworth", "Chebyshev I", "Bessel"]


def apply_lowpass(data, cutoff_hz, fs_hz, order=4, filter_type="Butterworth", ripple_db=0.5):
    arr = np.array(data, dtype=float)
    min_len = order * 3 + 1
    if len(arr) < min_len:
        return arr

    nyq = 0.5 * fs_hz
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
