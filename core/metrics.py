import numpy as np
from scipy.stats import chi2 as chi2_dist
from scipy.fft import rfft, rfftfreq

METRIC_KEYS = [
    "RMS AP",
    "RMS ML",
    "Range AP",
    "Range ML",
    "Mean AP",
    "Mean ML",
    "95% Ellipse area",
    "Sway path length",
    "Mean velocity",
    "Mean power freq AP",
    "Mean power freq ML",
    "Median freq AP",
    "Median freq ML",
]


def compute_metrics(cop_ap, cop_ml, fs, selected_keys):
    results = {}
    n = len(cop_ap)
    if n < 2:
        return results

    ap = np.array(cop_ap, dtype=float)
    ml = np.array(cop_ml, dtype=float)
    ap_c = ap - np.mean(ap)
    ml_c = ml - np.mean(ml)
    duration = (n - 1) / fs

    for key in selected_keys:
        try:
            if key == "RMS AP":
                results[key] = (float(np.sqrt(np.mean(ap_c ** 2))), "mm")

            elif key == "RMS ML":
                results[key] = (float(np.sqrt(np.mean(ml_c ** 2))), "mm")

            elif key == "Range AP":
                results[key] = (float(np.max(ap) - np.min(ap)), "mm")

            elif key == "Range ML":
                results[key] = (float(np.max(ml) - np.min(ml)), "mm")

            elif key == "Mean AP":
                results[key] = (float(np.mean(ap)), "mm")

            elif key == "Mean ML":
                results[key] = (float(np.mean(ml)), "mm")

            elif key == "95% Ellipse area":
                cov = np.cov(np.vstack([ap_c, ml_c]))
                eigvals = np.abs(np.linalg.eigvalsh(cov))
                chi2_val = chi2_dist.ppf(0.95, df=2)   # ~= 5.991
                area = np.pi * chi2_val * np.sqrt(eigvals[0] * eigvals[1])
                results[key] = (float(area), "mm^2")

            elif key == "Sway path length":
                path = float(np.sum(np.sqrt(np.diff(ap) ** 2 + np.diff(ml) ** 2)))
                results[key] = (path, "mm")

            elif key == "Mean velocity":
                path = float(np.sum(np.sqrt(np.diff(ap) ** 2 + np.diff(ml) ** 2)))
                results[key] = (path / duration if duration > 0 else 0.0, "mm/s")

            elif key in ("Mean power freq AP", "Mean power freq ML",
                         "Median freq AP", "Median freq ML"):
                sig = ap_c if key.endswith("AP") else ml_c
                freqs = rfftfreq(n, 1.0 / fs)
                psd = np.abs(rfft(sig)) ** 2
                pos = freqs > 0
                f, p = freqs[pos], psd[pos]
                total = np.sum(p)
                if total > 0 and len(f) > 0:
                    if key.startswith("Mean power"):
                        val = float(np.sum(f * p) / total)
                    else:
                        cumsum = np.cumsum(p)
                        idx = min(np.searchsorted(cumsum, total * 0.5), len(f) - 1)
                        val = float(f[idx])
                else:
                    val = 0.0
                results[key] = (val, "Hz")

        except Exception:
            pass

    return results


def compute_ellipse_points(cop_ap, cop_ml, confidence=0.95, n_pts=300):
    """Returns (ell_ml, ell_ap) arrays for plotting (x=ML, y=AP)."""
    ap = np.array(cop_ap, dtype=float)
    ml = np.array(cop_ml, dtype=float)
    ap_c = ap - np.mean(ap)
    ml_c = ml - np.mean(ml)

    # Covariance in [ml, ap] space to match plot axes (x=ML, y=AP)
    cov = np.cov(np.vstack([ml_c, ap_c]))
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.abs(eigvals)   # ascending order

    chi2_val = chi2_dist.ppf(confidence, df=2)
    a = np.sqrt(chi2_val * eigvals[1])   # major semi-axis
    b = np.sqrt(chi2_val * eigvals[0])   # minor semi-axis

    # Rotation angle of major eigenvector from ML-axis
    angle = np.arctan2(eigvecs[1, 1], eigvecs[0, 1])

    theta = np.linspace(0, 2 * np.pi, n_pts)
    x = a * np.cos(theta)
    y = b * np.sin(theta)

    cos_a, sin_a = np.cos(angle), np.sin(angle)
    x_rot = cos_a * x - sin_a * y
    y_rot = sin_a * x + cos_a * y

    return x_rot + np.mean(ml), y_rot + np.mean(ap)
