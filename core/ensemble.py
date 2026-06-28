"""Cross-trial ensemble of time-normalized epochs (pure / NaN-safe).

Pools epoch matrices (each ``(N_i, P)`` from core.normalize.extract_epochs) from
the user's selected trials and reduces them to an epoch-weighted mean +/- SD
curve over the 0-100% phase nodes.
"""
import numpy as np


def pool(matrices):
    """Vertically stack compatible ``(N_i, P)`` epoch matrices into ``(sum N_i, P)``.

    Skips empties; raises ``ValueError`` on a column-count (P) mismatch.
    """
    mats = []
    for m in matrices:
        m = np.asarray(m, float)
        if m.ndim == 2 and m.shape[0] > 0:
            mats.append(m)
    if not mats:
        return np.empty((0, 0))
    p = mats[0].shape[1]
    for m in mats:
        if m.shape[1] != p:
            raise ValueError(f"epoch width mismatch: {m.shape[1]} != {p}")
    return np.vstack(mats)


def ensemble_stats(matrix):
    """Epoch-weighted, NaN-aware mean/SD over a ``(N, P)`` pooled matrix.

    Returns ``{"mean": (P,), "sd": (P,), "n": N, "x": (P,)}`` where ``x`` is the
    0-100 percent axis. SD is sample SD (ddof=1); 0 when N=1; empty when N=0.
    """
    m = np.asarray(matrix, float)
    if m.ndim != 2 or m.shape[0] == 0:
        empty = np.array([])
        return {"mean": empty, "sd": empty, "n": 0, "x": empty}
    p = m.shape[1]
    # A phase node where EVERY epoch is NaN (e.g. a leading/trailing node outside
    # one short epoch's finite span) makes np.nanmean operate on an empty slice,
    # which emits a "Mean of empty slice" RuntimeWarning even though the NaN result
    # is correct. errstate only silences floating-point flags (invalid/divide), not
    # this warning, so we suppress the warnings category explicitly. The numbers are
    # unchanged — an all-NaN column still yields NaN mean/SD.
    import warnings
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(m, axis=0)
        sd = np.nanstd(m, axis=0, ddof=1) if m.shape[0] > 1 else np.zeros(p)
    return {"mean": mean, "sd": sd, "n": int(m.shape[0]),
            "x": np.linspace(0.0, 100.0, p)}


def pool_sources(sources, mode="cycle"):
    """Pool per-trial normalized epochs into a single ensemble.

    ``sources`` = iterable of ``(label, norm_dict)`` or
    ``(label, norm_dict, subject)`` where ``norm_dict`` has a ``matrix``
    (``(N_i, P)`` from a NormalizeStep) and ``subject`` is an optional subject
    identity (e.g. a folder tuple). A missing/``None`` subject falls back to the
    ``label`` (each trial = its own subject). Sources with an absent or zero-row
    matrix are skipped.

    ``mode``:
      * ``"cycle"``   — every cycle (row) weighted equally: all rows stacked, then
        mean/SD over rows. The default; preserves the long-standing behaviour and
        keeps within-subject (cycle) SD meaningful for a single subject.
      * ``"subject"`` — each subject's cycles are first reduced to ONE
        representative curve (NaN-aware column mean over that subject's rows), then
        those per-subject curves are pooled (each subject = one vote). Removes the
        cycle-count imbalance bias; SD is the between-subject SD.

    Returns ``{"matrix": (rows, P), "columns": [...], "stats": <ensemble_stats>,
    "n": int, "n_subjects": int, "n_cycles": int, "mode": str}`` where ``matrix``
    holds the pooled rows (cycles in ``"cycle"`` mode, per-subject curves in
    ``"subject"`` mode). Raises ``ValueError`` on a column-count (P) mismatch.
    """
    import warnings
    entries = []   # (label, subject, matrix) for non-empty sources
    for src in sources:
        label, nd = src[0], src[1]
        subject = src[2] if len(src) >= 3 else None
        if subject is None:
            subject = label
        m = np.asarray((nd or {}).get("matrix"), float)
        if m.ndim == 2 and m.shape[0] > 0:
            entries.append((label, subject, m))

    n_cycles = sum(m.shape[0] for _, _, m in entries)
    subj_order = []                      # distinct subjects, first-seen order
    for _, s, _ in entries:
        if s not in subj_order:
            subj_order.append(s)
    n_subjects = len(subj_order)

    if mode == "subject":
        rep_rows, cols = [], []
        for s in subj_order:
            stacked = pool([m for _, sub, m in entries if sub == s])
            if stacked.shape[0] == 0:
                continue
            with np.errstate(invalid="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                rep_rows.append(np.nanmean(stacked, axis=0))
            cols.append(str(s))
        matrix = np.vstack(rep_rows) if rep_rows else np.empty((0, 0))
    else:
        mats, cols = [], []
        for label, _, m in entries:
            mats.append(m)
            cols.extend(f"{label}#{i+1}" for i in range(m.shape[0]))
        matrix = pool(mats) if mats else np.empty((0, 0))

    stats = ensemble_stats(matrix)
    return {"matrix": matrix, "columns": cols, "stats": stats,
            "n": int(stats["n"]), "n_subjects": int(n_subjects),
            "n_cycles": int(n_cycles), "mode": mode}


def ensemble_from_runs(runs, key):
    """Headless code-only ensemble across run_pipeline outputs.

    ``runs`` = iterable of ``(label, run_result)`` where ``run_result`` is a
    :func:`core.run.run_pipeline` output dict; ``key`` = a NormalizeStep ``name``.
    Pulls ``run_result["normalized"][key]`` from each run, skipping runs that lack
    it, then delegates to :func:`pool_sources`. Returns the same dict shape.
    """
    sources = []
    for label, run_result in runs:
        nd = (run_result or {}).get("normalized", {}).get(key)
        if nd is not None:
            sources.append((label, nd))
    return pool_sources(sources)


def ensemble_csv(matrix, stats, columns=None):
    """CSV text for a pooled ensemble: rows = phase nodes (0-100%), columns =
    each epoch + mean + sd. ``columns`` labels the K epoch columns (defaults to
    ``epoch_1..epoch_K``). One node per row; values are the transpose of
    ``matrix`` (which is epochs x nodes)."""
    m = np.asarray(matrix, float)
    k = m.shape[0] if m.ndim == 2 else 0
    cols = list(columns) if columns is not None else [f"epoch_{i+1}" for i in range(k)]
    x = stats.get("x")
    mean = stats.get("mean")
    sd = stats.get("sd")
    header = ",".join(["percent", *cols, "mean", "sd"])
    out = [header]
    p = len(x) if x is not None else 0
    for node in range(p):
        cells = [f"{x[node]}"]
        for e in range(k):
            cells.append(f"{m[e, node]}")
        cells.append(f"{mean[node]}")
        cells.append(f"{sd[node]}")
        out.append(",".join(cells))
    return "\n".join(out) + "\n"
