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

    # Bare keys plus any per-plate force/COP signals (multi-plate files) — all on
    # the same analog clock, so the same slice / fill applies.
    keys = tuple(SIGNAL_KEYS) + tuple(data.get("force_signal_keys", []))

    if (first, last) != (0, total):
        sl = slice(first, last)
        for key in keys:
            if key in data and data[key] is not None:
                data[key] = np.asarray(data[key], dtype=float)[sl]
        fs = float(data.get("fs", 1000.0)) or 1000.0
        data["time"] = np.arange(last - first) / fs

    # Count and repair any remaining interior dropouts.
    span = len(data["time"])
    bad_any = np.zeros(span, dtype=bool)
    for key in keys:
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


def clean_markers(markers, max_gap_frames=10):
    """Repair short marker dropouts (in place). Interpolates NaN runs up to
    ``max_gap_frames`` per marker/axis; leaves longer occlusions as gaps.
    Returns a report dict.

    Vectorized over all marker/axis series at once (a mocap file is
    M markers x F frames x 3 axes; the old per-column Python while-loop ran
    3*M scans of F frames and dominated folder-load time — ~3.7 s for a single
    40-marker, 60 k-frame trial). Here every (marker, axis) series is stacked
    into one ``(3M, F)`` matrix, all NaN *runs* are found with a single padded
    row-wise ``diff`` (start/end columns), and only the runs that are short
    enough AND bounded by finite samples on both sides are linearly
    interpolated. Same definition as before — an edge-touching run (open head /
    tail) or a run longer than ``max_gap_frames`` is left as a true occlusion —
    and bit-for-bit identical fills/report counts (pinned in
    ``tests/test_data_quality.py``). ~30x faster on the case above.
    """
    data = markers.get("data")
    if data is None or data.size == 0:
        return {"n_markers": 0, "markers_filled": 0, "markers_occluded": 0,
                "markers_missing": 0, "labels_missing": []}
    M, F, _ = data.shape
    # A frame is "bad" for a marker if ANY of its 3 axes is non-finite.
    before_bad = ~np.isfinite(data).all(axis=2)   # (M, F)

    # Stack every (marker, axis) series row-wise -> (3M, F). transpose(0,2,1)
    # puts axis before frame so the reshape keeps each series contiguous; a
    # write-back through the same view updates ``data`` in place.
    cols = data.transpose(0, 2, 1).reshape(M * 3, F)
    bad = ~np.isfinite(cols)
    if bad.any():
        # Find NaN runs per row: pad each row with a 0 on both ends and diff, so
        # a +1 marks a run start column and a -1 the (exclusive) end column. The
        # two ``where`` calls return rows/columns in the same row-major order, so
        # ``starts[k]``/``ends[k]`` are the k-th run's bounds on row ``rows[k]``.
        b = bad.astype(np.int8)
        pad = np.zeros((cols.shape[0], 1), dtype=np.int8)
        d = np.diff(np.concatenate([pad, b, pad], axis=1), axis=1)
        rows, starts = np.where(d == 1)
        ends = np.where(d == -1)[1]
        for r, s, e in zip(rows, starts, ends):
            left, right = s - 1, e        # finite neighbours bracketing the run
            if left >= 0 and right < F and (e - s) <= max_gap_frames:
                cols[r, s:e] = np.interp(
                    np.arange(s, e), [left, right], [cols[r, left], cols[r, right]]
                )
        # Reflect the (possibly copied) matrix back into ``data`` so callers that
        # kept the original array reference still see the repaired values.
        data[...] = cols.reshape(M, 3, F).transpose(0, 2, 1)

    after_bad = ~np.isfinite(data).all(axis=2)
    # A marker is "fully missing" when EVERY frame is occluded after repair — its
    # trajectory is unusable, so any segment/joint that needs it yields NaN. These
    # are the incomplete-data cases worth WARNING the user about (a few short gaps
    # are normal and silently filled; a wholly absent marker breaks the model).
    fully_missing = after_bad.all(axis=1)               # (M,)
    labels = markers.get("labels") or []
    labels_missing = [labels[m] for m in range(M)
                      if fully_missing[m] and m < len(labels)]
    return {
        "n_markers": int(M),
        "markers_filled": int((before_bad & ~after_bad).sum()),
        "markers_occluded": int(after_bad.sum()),
        "markers_missing": int(fully_missing.sum()),
        "labels_missing": labels_missing,
    }


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


def summarize_marker_reports(named_reports):
    """Human-readable note from (name, marker-report) pairs, or '' if all markers
    were complete. Reports filled gaps (info), remaining occlusion (info) and —
    most importantly — fully MISSING markers, the incomplete-data case that
    silently breaks joint-angle/segment computation."""
    lines = []
    for name, rep in named_reports:
        if not rep:
            continue
        filled = rep.get("markers_filled", 0)
        occluded = rep.get("markers_occluded", 0)
        missing = rep.get("markers_missing", 0)
        parts = []
        if missing:
            labs = rep.get("labels_missing") or []
            shown = ", ".join(labs[:6]) + ("…" if len(labs) > 6 else "")
            parts.append(f"{missing} marker(s) fully missing"
                         + (f" ({shown})" if shown else ""))
        if filled:
            parts.append(f"filled {filled} marker gap(s)")
        if occluded and not missing:
            parts.append(f"{occluded} occluded marker-sample(s) remain")
        if parts:
            lines.append(f"  • {name}: {', '.join(parts)}")
    if not lines:
        return ""
    return "Marker data quality:\n" + "\n".join(lines)


def any_markers_missing(named_reports):
    """True if ANY (name, marker-report) pair has a fully-missing marker — the UI
    escalates the load notification to a warning in that case."""
    return any((rep or {}).get("markers_missing") for _, rep in named_reports)
