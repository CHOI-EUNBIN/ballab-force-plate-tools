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
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(m, axis=0)
        sd = np.nanstd(m, axis=0, ddof=1) if m.shape[0] > 1 else np.zeros(p)
    return {"mean": mean, "sd": sd, "n": int(m.shape[0]),
            "x": np.linspace(0.0, 100.0, p)}
