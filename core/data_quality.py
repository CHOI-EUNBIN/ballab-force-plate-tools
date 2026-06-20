"""Shared data-quality cleanup applied to every loaded dataset.

Force-plate / C3D exports commonly contain:
  * a block of all-NaN samples padded onto the end (or start) of the recording
    when it does not end on a frame-block boundary, and
  * occasional isolated NaN/Inf dropouts inside the signal.

Both make pyqtgraph's auto-range collapse and the plot look empty. This module
trims the padding and interpolates interior gaps, returning a short report so
the UI can tell the user what was repaired.
"""

import numpy as np

# Time-series channels that may carry NaN/Inf and need repair.
SIGNAL_KEYS = ("cop_ap", "cop_ml", "fz", "fx", "fy")


def _fill_nan(arr):
    """Linear-interpolate NaN/Inf samples over their valid neighbours."""
    arr = np.asarray(arr, dtype=float)
    bad = ~np.isfinite(arr)
    if not bad.any():
        return arr
    good = ~bad
    n_good = int(good.sum())
    arr = arr.copy()
    if n_good >= 2:
        idx = np.arange(arr.size)
        arr[bad] = np.interp(idx[bad], idx[good], arr[good])
    elif n_good == 1:
        arr[bad] = arr[good][0]
    else:
        arr[bad] = 0.0
    return arr


def clean_dataset(data):
    """Trim NaN padding and fill interior dropouts in ``data`` (in place).

    Returns a report dict: ``{"trimmed_head", "trimmed_tail", "filled",
    "total", "ok"}``. ``ok`` is False only if the recording had no usable
    samples at all.
    """
    time = np.asarray(data.get("time", []), dtype=float)
    total = int(time.size)
    report = {"trimmed_head": 0, "trimmed_tail": 0, "filled": 0,
              "total": total, "ok": True}
    if total == 0:
        return report

    # Use the primary force channel (always present) to find the valid span.
    primary = np.asarray(data.get("fz", time), dtype=float)
    if primary.size != total:
        primary = primary[:total]
    finite = np.isfinite(primary)
    if not finite.any():
        report["ok"] = False
        return report

    first = int(np.argmax(finite))
    last = total - int(np.argmax(finite[::-1]))  # exclusive
    report["trimmed_head"] = first
    report["trimmed_tail"] = total - last

    if (first, last) != (0, total):
        sl = slice(first, last)
        for key in SIGNAL_KEYS:
            if key in data and data[key] is not None:
                data[key] = np.asarray(data[key], dtype=float)[sl]
        fs = float(data.get("fs", 1000.0)) or 1000.0
        data["time"] = np.arange(last - first) / fs

    # Count and repair any remaining interior dropouts.
    span = len(data["time"])
    bad_any = np.zeros(span, dtype=bool)
    for key in SIGNAL_KEYS:
        if key in data and data[key] is not None:
            arr = np.asarray(data[key], dtype=float)
            bad = ~np.isfinite(arr)
            if bad.any():
                bad_any[:bad.size] |= bad[:span]
                data[key] = _fill_nan(arr)
    report["filled"] = int(bad_any.sum())

    if span:
        data["range_start"] = float(data["time"][0])
        data["range_end"] = float(data["time"][-1])
    return report


def summarize_reports(named_reports):
    """Build a short human-readable note from (name, report) pairs, or '' if
    nothing was repaired."""
    repaired = []
    for name, rep in named_reports:
        trimmed = rep.get("trimmed_head", 0) + rep.get("trimmed_tail", 0)
        filled = rep.get("filled", 0)
        if trimmed or filled:
            parts = []
            if trimmed:
                parts.append(f"trimmed {trimmed} padding sample(s)")
            if filled:
                parts.append(f"filled {filled} gap(s)")
            repaired.append(f"  • {name}: {', '.join(parts)}")
    if not repaired:
        return ""
    return "Repaired data quality issues:\n" + "\n".join(repaired)
