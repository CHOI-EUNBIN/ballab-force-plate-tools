"""
C3D file reader for motion capture data.
Converts C3D force plate data to the format used by BalanceAnalyzer.
"""

import numpy as np
from typing import Dict, Optional, List
import logging

try:
    import ezc3d
    C3D_AVAILABLE = True
except ImportError:
    C3D_AVAILABLE = False

log = logging.getLogger(__name__)


def print_c3d_info(file_path: str):
    """
    Print detailed information about a C3D file structure.
    Useful for debugging and understanding channel names.
    """
    if not C3D_AVAILABLE:
        print("ezc3d is not installed")
        return
    
    try:
        c3d = ezc3d.c3d(file_path)
    except Exception as e:
        print(f"Failed to read C3D file: {e}")
        return
    
    analog = c3d["data"]["analogs"]
    try:
        analog_labels = c3d["parameters"]["ANALOG"]["LABELS"]["value"]
        if isinstance(analog_labels, str):
            analog_labels = [analog_labels]
    except (KeyError, TypeError):
        analog_labels = [f"CH{i}" for i in range(analog.shape[0])]
    
    print(f"\n=== C3D File Info: {file_path} ===")
    print(f"Analog data shape: {analog.shape}")
    print(f"Number of channels: {len(analog_labels)}")
    print(f"Sampling info:")
    try:
        header = c3d["header"]
        print(f"  Frame rate: {header['frame_rate']} Hz")
        print(f"  Number of frames: {header['nb_frames']}")
    except:
        pass
    
    print(f"\nChannel names (first 20):")
    for i, label in enumerate(analog_labels[:20]):
        print(f"  {i:2d}: {label}")
    
    if len(analog_labels) > 20:
        print(f"  ... and {len(analog_labels) - 20} more channels")
    print()


def _unit(v):
    """Return ``v`` scaled to unit length, or ``v`` unchanged if it is ~zero."""
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _extract_force_plates(c3d) -> Optional[List[Dict]]:
    """Extract force-plate geometry from the C3D ``FORCE_PLATFORMS`` group.

    This is what Visual3D draws on the floor of its 3D view: the rectangle is
    simply ``FORCE_PLATFORMS:CORNERS`` (the four plate corners in the lab/global
    frame, same units/space as the POINT markers).

    Returns a list of plate dicts ``{corners (4,3), origin (3,), R (3,3)}`` or
    ``None`` if the file has no ``CORNERS``. ``R`` is the plate-local -> global
    rotation, derived from the corner ordering, and is used to place the GRF
    vector (see :func:`build_grf`).
    """
    # The C3D group is "FORCE_PLATFORM" (singular) in practice; some exporters
    # use the plural "FORCE_PLATFORMS". Accept either.
    params = c3d["parameters"]
    fp = params.get("FORCE_PLATFORM") or params.get("FORCE_PLATFORMS")
    if fp is None:
        return None
    try:
        corners = np.asarray(fp["CORNERS"]["value"], dtype=float)
    except (KeyError, TypeError):
        return None
    if corners.size == 0:
        return None
    # ezc3d CORNERS shape: (3, 4, n_plates) -> rows X,Y,Z; 4 corners per plate.
    if corners.ndim == 2:
        corners = corners[:, :, None]
    if corners.ndim != 3 or corners.shape[0] < 3 or corners.shape[1] < 4:
        return None

    plates: List[Dict] = []
    for p in range(corners.shape[2]):
        c = corners[:3, :4, p].T  # (4, 3) corner coords in global frame
        if not np.isfinite(c).all():
            continue
        origin = c.mean(axis=0)
        # Plate-local axes from the C3D corner ordering (+x+y, -x+y, -x-y, +x-y).
        x_axis = _unit((c[0] + c[3]) - (c[1] + c[2]))
        y_axis = _unit((c[0] + c[1]) - (c[2] + c[3]))
        z_axis = _unit(np.cross(x_axis, y_axis))
        y_axis = np.cross(z_axis, x_axis)  # re-orthogonalise
        R = np.column_stack([x_axis, y_axis, z_axis])
        plates.append({"corners": c, "origin": origin, "R": R})
    return plates or None


def _cal_matrix_for_plate(cal, p):
    """The 6x6 calibration matrix for plate ``p`` from a FORCE_PLATFORM:CAL_MATRIX
    value, or ``None`` if it isn't a usable 6x6. ezc3d stores it as (6, 6, n_plates);
    a single-plate file may collapse to (6, 6)."""
    if cal is None:
        return None
    cal = np.asarray(cal, dtype=float)
    if cal.ndim == 3 and cal.shape[:2] == (6, 6) and p < cal.shape[2]:
        M = cal[:, :, p]
    elif cal.ndim == 2 and cal.shape == (6, 6) and p == 0:
        M = cal
    else:
        return None
    return M if np.isfinite(M).all() else None


def _plate_forces(c3d, channels: Dict, analog_labels) -> Optional[List[Dict]]:
    """Per-plate force/moment channels via ``FORCE_PLATFORM:CHANNEL``.

    Returns a list (one entry per plate) of ``{fx, fy, fz, mx, my}`` arrays (each
    on the original analog clock), or ``None`` if there is no channel mapping.
    This is what lets us read plate 2+ instead of only the first plate.

    For TYPE-4 plates (``FORCE_PLATFORM:TYPE == 4``) the mapped channels are RAW
    transducer signals (volts), not forces: the real F/M come from multiplying the
    6 raw channels by the plate's 6x6 ``CAL_MATRIX``. Skipping this calibration
    leaves Fz/moments ~order-of-magnitude wrong, and in particular the moment-
    derived COP (``M/Fz``) collapses to ~0 — pinning the 3D GRF arrow at the plate
    centre. TYPE 1/2 plates store F/M directly and are read verbatim.
    """
    params = c3d["parameters"]
    fp = params.get("FORCE_PLATFORM") or params.get("FORCE_PLATFORMS")
    if fp is None:
        return None
    try:
        chan = np.asarray(fp["CHANNEL"]["value"])    # (n_components, n_plates)
    except (KeyError, TypeError):
        return None
    if chan.ndim != 2 or chan.size == 0:
        return None
    n_comp, n_plates = chan.shape

    try:
        types = np.asarray(fp["TYPE"]["value"]).ravel().astype(int)
    except (KeyError, TypeError, ValueError):
        types = np.array([], dtype=int)
    try:
        cal = fp["CAL_MATRIX"]["value"]
    except (KeyError, TypeError):
        cal = None

    def _ch(ci):
        ci = int(ci)
        if ci < 1 or ci > len(analog_labels):
            return None
        return channels.get(str(analog_labels[ci - 1]).strip())

    out = []
    for p in range(n_plates):
        idx = chan[:, p]
        raw = [_ch(idx[k]) for k in range(n_comp)]   # CHANNEL order: Fx,Fy,Fz,Mx,My,Mz
        ptype = int(types[p]) if p < types.size else 0

        if ptype == 4 and n_comp >= 6 and all(r is not None for r in raw[:6]):
            M = _cal_matrix_for_plate(cal, p)
            if M is not None:
                fm = M @ np.vstack([np.asarray(r, dtype=float) for r in raw[:6]])
                out.append({"fx": fm[0], "fy": fm[1], "fz": fm[2],
                            "mx": fm[3], "my": fm[4]})
                continue
            log.warning("FORCE_PLATFORM plate %d is TYPE 4 but has no usable "
                        "CAL_MATRIX; forces/COP will be uncalibrated.", p + 1)

        out.append({
            "fx": raw[0] if n_comp > 0 else None,
            "fy": raw[1] if n_comp > 1 else None,
            "fz": raw[2] if n_comp > 2 else None,
            "mx": raw[3] if n_comp > 3 else None,
            "my": raw[4] if n_comp > 4 else None,
        })
    return out


def _plate_cop(fz, mx, my):
    """Plate-local COP (cop_ap, cop_ml) from vertical force + planar moments.

    Same definition used for the single-plate bare keys and the GRF overlay
    (:func:`build_grf`): cop_ap = -My/Fz, cop_ml = Mx/Fz, with Fz clamped away
    from zero so unloaded samples don't blow up. Inputs are 1-D arrays of equal
    length; returns ``(cop_ap, cop_ml)`` float arrays.
    """
    fz = np.asarray(fz, dtype=float)
    mx = np.asarray(mx, dtype=float)
    my = np.asarray(my, dtype=float)
    fz_safe = np.where(np.abs(fz) > 1, fz, 1)
    return -my / fz_safe, mx / fz_safe


def _plate_signals(fp_raw, n):
    """Materialize per-plate ``fp{p}:*`` signals from the raw plate channels.

    ``fp_raw`` is the list of per-plate ``{fx,fy,fz,mx,my}`` raw-analog channels
    from :func:`_plate_forces`; ``n`` is the master analog length to truncate to
    (so every plate signal matches ``data['fz']`` / ``data['time']``). Plates
    that have no Fz channel are skipped (no signal to derive). Returns
    ``(signals, keys)`` where ``signals`` maps flat keys ``"fp{p}:fx"`` … to
    arrays and ``keys`` is the ordered list of those keys (1-based plate index).
    Reuses :func:`_plate_cop` so per-plate COP matches the bare-key definition.
    """
    signals: Dict[str, np.ndarray] = {}
    keys: List[str] = []
    if not fp_raw:
        return signals, keys
    zeros = np.zeros(n, dtype=float)

    def _seg(v):
        return np.asarray(v, dtype=float)[:n] if v is not None else zeros.copy()

    for i, r in enumerate(fp_raw):
        if r is None or r.get("fz") is None:
            continue
        p = i + 1  # 1-based plate index
        fx, fy, fz = _seg(r.get("fx")), _seg(r.get("fy")), _seg(r.get("fz"))
        # Expose the RAW C3D channels verbatim — no sign flip. C3D stores Fz as
        # the force the subject applies to the plate (down = negative), and we
        # keep that faithful: the user controls sign explicitly via an abs()
        # ComputeStep when they want e.g. a positive vGRF impulse.
        cop_ap, cop_ml = _plate_cop(fz, _seg(r.get("mx")), _seg(r.get("my")))
        for comp, arr in (("fx", fx), ("fy", fy), ("fz", fz),
                          ("cop_ap", cop_ap), ("cop_ml", cop_ml)):
            key = f"fp{p}:{comp}"
            signals[key] = arr
            keys.append(key)
    return signals, keys


def ensure_fp1_from_bare(data: Dict) -> None:
    """Guarantee a single plate ``fp1:*`` built from the bare force/COP keys.

    Files without a ``FORCE_PLATFORM:CHANNEL`` mapping (named Fx/Fz channels, or
    a CSV with only bare columns) carry no per-plate signals, yet the UI is
    uniformly plate-grouped (FP1…FPn). This synthesizes FP1 from the bare keys —
    sharing the same arrays, so clean-up / save behave identically — and sets
    ``n_force_plates``/``force_signal_keys``. No-op if per-plate signals already
    exist or there is no force data (e.g. a marker-only trial)."""
    if data.get("force_signal_keys"):
        return
    fz = data.get("fz")
    if fz is None:
        return
    n = len(fz)
    zeros = np.zeros(n, dtype=float)
    keys = []
    for comp in ("fx", "fy", "fz", "cop_ap", "cop_ml"):
        arr = data.get(comp)
        data[f"fp1:{comp}"] = np.asarray(arr, dtype=float) if arr is not None else zeros.copy()
        keys.append(f"fp1:{comp}")
    data["force_signal_keys"] = keys
    data["n_force_plates"] = 1


def build_grf(data: Dict) -> Optional[List[Dict]]:
    """Build a global-frame GRF vector timeline for *every* force plate.

    For each plate, reads its own plate-local force/moment channels, derives the
    COP, and lifts both the application point and force vector into the lab frame
    using that plate's geometry — so the 3D view can draw one GRF arrow per plate.

    Call this *after* ``clean_dataset`` so the time axis matches ``data['time']``.
    Returns a list of ``{time, point (N,3), vector (N,3)}`` (one per loaded plate)
    or ``None`` when there is no plate geometry / force data.
    """
    plates = data.get("force_plates")
    raw = data.get("_fp_raw")
    if not plates or not raw:
        return None
    time = np.asarray(data.get("time", []), dtype=float)
    clen = time.size
    if clen == 0:
        return None
    # clean_dataset trimmed the head; slice raw channels to the same window.
    head = int((data.get("_clean_report") or {}).get("trimmed_head", 0))
    sl = slice(head, head + clen)

    out: List[Dict] = []
    for i, plate in enumerate(plates):
        if i >= len(raw):
            break
        r = raw[i]
        if r.get("fz") is None:
            continue
        fz = np.asarray(r["fz"], dtype=float)[sl]
        n = int(min(clen, fz.size))
        if n == 0:
            continue
        fz = fz[:n]

        def _seg(key):
            v = r.get(key)
            return np.asarray(v, dtype=float)[sl][:n] if v is not None else np.zeros(n)

        fx, fy, mx, my = _seg("fx"), _seg("fy"), _seg("mx"), _seg("my")
        fz_safe = np.where(np.abs(fz) > 1.0, fz, 1.0)
        # Plate-local COP: cop_x = -My/Fz, cop_y = Mx/Fz.
        cop_local = np.column_stack([-my / fz_safe, mx / fz_safe, np.zeros(n)])

        R = np.asarray(plate["R"], dtype=float)
        origin = np.asarray(plate["origin"], dtype=float)
        point = origin + cop_local @ R.T
        # GRF arrow: build the vector from the RAW plate-local Fz (subject-applied,
        # down = -). The plate-local +z axis (from the C3D corner ordering) points
        # DOWN into the lab (R[:,2] ~ [0,0,-1] for these plates), so raw-Fz @ R.T
        # already lifts to an UP-pointing ground-reaction arrow in the lab frame.
        # (We do NOT use the sign-flipped bare/fp Fz here — that flip is only for
        # the scalar vGRF metrics; the 3D arrow geometry was already correct.)
        vector = np.column_stack([fx, fy, fz]) @ R.T

        weak = np.abs(fz) < 20.0     # no meaningful load → hide arrow
        point[weak] = np.nan
        vector[weak] = np.nan
        out.append({"time": time[:n], "point": point, "vector": vector})
    return out or None


def _extract_markers(c3d) -> Optional[Dict]:
    """Extract motion-capture marker (POINT) trajectories from a C3D object.

    Returns a dict {labels, rate, time, data (n_markers, n_frames, 3), units}
    or None if the file contains no markers. Occluded samples (negative ezc3d
    residual) are set to NaN so they show as gaps.
    """
    try:
        points = c3d["data"]["points"]
    except (KeyError, TypeError):
        return None
    if points is None or getattr(points, "size", 0) == 0:
        return None
    # ezc3d points shape: (4, n_markers, n_frames) -> rows X, Y, Z, residual
    if points.ndim != 3 or points.shape[0] < 3 or points.shape[1] == 0:
        return None

    n_markers, n_frames = points.shape[1], points.shape[2]
    xyz = np.transpose(points[:3], (1, 2, 0)).astype(float)  # (M, F, 3)

    # Mark occlusions (residual < 0) as NaN.
    if points.shape[0] >= 4:
        residual = points[3]  # (M, F)
        occluded = ~np.isfinite(residual) | (residual < 0)
        xyz[occluded] = np.nan

    try:
        labels = c3d["parameters"]["POINT"]["LABELS"]["value"]
        if isinstance(labels, str):
            labels = [labels]
        labels = [str(l).strip() for l in labels][:n_markers]
    except (KeyError, TypeError):
        labels = []
    while len(labels) < n_markers:
        labels.append(f"M{len(labels) + 1}")

    try:
        rate = float(c3d["parameters"]["POINT"]["RATE"]["value"][0])
    except (KeyError, TypeError, IndexError):
        try:
            rate = float(c3d["header"]["points"]["frame_rate"])
        except (KeyError, TypeError):
            rate = 100.0
    if rate <= 0:
        rate = 100.0

    try:
        units = str(c3d["parameters"]["POINT"]["UNITS"]["value"][0])
    except (KeyError, TypeError, IndexError):
        units = "mm"

    return {
        "labels": labels,
        "rate": rate,
        "time": np.arange(n_frames) / rate,
        "data": xyz,
        "units": units,
    }


def read_c3d(file_path: str) -> Dict:
    """
    Read a C3D file and extract force plate data (and marker data if present).

    Args:
        file_path: Path to the C3D file

    Returns:
        Dictionary with keys: path, name, cop_ap, cop_ml, fz, fx, fy, time, fs,
                             analysis, events, range_start, range_end, [markers]
    """
    if not C3D_AVAILABLE:
        raise ImportError("ezc3d is not installed. Install it with: pip install ezc3d")

    try:
        c3d = ezc3d.c3d(file_path)
    except Exception as e:
        raise ValueError(f"Failed to read C3D file: {e}")

    name = file_path.split("\\")[-1].split("/")[-1].rsplit(".", 1)[0]
    markers = _extract_markers(c3d)
    force_plates = _extract_force_plates(c3d)

    # Extract force data from analog channels
    analog = c3d["data"]["analogs"]

    if analog.size == 0:
        if markers is None:
            raise ValueError("No analog (force plate) or marker data found in C3D file")
        # Marker-only file: synthesize an empty force timeline from the marker clock.
        n_frames = markers["data"].shape[1]
        fs = markers["rate"]
        time = markers["time"]
        zeros = np.zeros(n_frames, dtype=float)
        data = {
            "path": file_path, "name": name,
            "cop_ap": zeros.copy(), "cop_ml": zeros.copy(), "fz": zeros.copy(),
            "time": time, "fs": float(fs),
            "analysis": None, "events": [], "markers": markers,
            "force_plates": force_plates,
            "range_start": float(time[0]) if n_frames else 0.0,
            "range_end": float(time[-1]) if n_frames else 0.0,
        }
        log.info(f"Loaded marker-only C3D: {name}, {markers['data'].shape[0]} markers, "
                 f"rate={fs:.1f} Hz")
        return data
    
    # Get analog labels safely
    try:
        analog_labels = c3d["parameters"]["ANALOG"]["LABELS"]["value"]
        if isinstance(analog_labels, str):
            analog_labels = [analog_labels]
    except (KeyError, TypeError):
        analog_labels = [f"CH{i}" for i in range(analog.shape[0] if len(analog.shape) >= 1 else 1)]
    
    log.debug(f"C3D file: {file_path}")
    log.debug(f"Analog shape: {analog.shape}")
    log.debug(f"Analog labels count: {len(analog_labels)}")
    log.debug(f"First few labels: {analog_labels[:min(5, len(analog_labels))]}")
    
    # Handle different data shapes from ezc3d
    # Shape can be (channels, samples) or (subframes, channels, samples)
    channels = {}
    try:
        if len(analog.shape) == 2:
            # 2D: (channels, samples)
            num_channels = analog.shape[0]
            for i, label in enumerate(analog_labels):
                if i >= num_channels:
                    break
                channels[str(label).strip()] = analog[i, :].astype(np.float64)
                
        elif len(analog.shape) == 3:
            # 3D: Check if it's (subframes, channels, samples) or (channels, samples, subframes)
            # Usually it's (subframes, channels, samples)
            if analog.shape[0] == 1:
                # (1, channels, samples) - first dimension is subframe
                num_channels = analog.shape[1]
                for i, label in enumerate(analog_labels):
                    if i >= num_channels:
                        break
                    channels[str(label).strip()] = analog[0, i, :].astype(np.float64)
            elif analog.shape[2] == 1:
                # (channels, samples, 1) - last dimension is subframe
                num_channels = analog.shape[0]
                for i, label in enumerate(analog_labels):
                    if i >= num_channels:
                        break
                    channels[str(label).strip()] = analog[i, :, 0].astype(np.float64)
            else:
                # (channels, samples, subsamples) - third dimension is subsamples
                num_channels = analog.shape[0]
                for i, label in enumerate(analog_labels):
                    if i >= num_channels:
                        break
                    channels[str(label).strip()] = analog[i, :, 0].astype(np.float64)
        else:
            raise ValueError(f"Unexpected analog shape: {analog.shape}")
    except IndexError as e:
        log.error(f"Index error while extracting channels: {e}")
        raise ValueError(f"Mismatch between analog labels and data shape: {e}")
    
    log.debug(f"Successfully extracted {len(channels)} channels")

    # Per-plate raw force/moment channels (FORCE_PLATFORM:CHANNEL) — lets us read
    # plate 2+ for the multi-plate GRF, not just the first plate.
    fp_raw = _plate_forces(c3d, channels, analog_labels)

    # The bare keys mirror plate 1. When the file has a FORCE_PLATFORM:CHANNEL map
    # we take plate 1 straight from fp_raw — which is CALIBRATED for TYPE-4 plates
    # (see _plate_forces). Reading the bare Fx/Fz from the raw analog labels here
    # instead would leave the bare keys (and their moment-derived COP) uncalibrated
    # while fp1:* stays calibrated, so prefer fp_raw[0] whenever it is available.
    _p1 = fp_raw[0] if fp_raw else None
    if _p1 is not None and _p1.get("fz") is not None:
        fx, fy, fz = _p1.get("fx"), _p1.get("fy"), _p1.get("fz")
        cop_ap = cop_ml = None
        if _p1.get("mx") is not None and _p1.get("my") is not None:
            cop_ap, cop_ml = _plate_cop(fz, _p1["mx"], _p1["my"])
    else:
        # No channel map (named Fx/Fz columns, or a bare CSV-like c3d). Fall back to
        # label-based extraction exactly as before.
        fx = _extract_channel(channels, ["Fx", "Plate1Fx", "Force1X", "FX1", "Fx1", "FX", "Channel_01"])
        fy = _extract_channel(channels, ["Fy", "Plate1Fy", "Force1Y", "FY1", "Fy1", "FY", "Channel_02"])
        fz = _extract_channel(channels, ["Fz", "Plate1Fz", "Force1Z", "FZ1", "Fz1", "FZ", "Channel_03"])

        # Get COP (Center of Pressure) - direct values only
        cop_ap = _extract_channel(channels, ["COP_AP", "CoPX", "COPx", "Px", "COP_X"])
        cop_ml = _extract_channel(channels, ["COP_ML", "CoPY", "COPy", "Py", "COP_Y"])

        # If COP not found, calculate from Mx/My and Fz
        if (cop_ap is None or cop_ml is None) and fz is not None:
            mx = _extract_channel(channels, ["Mx", "Moment1X", "MX1", "Mx1", "MX", "Channel_04"])
            my = _extract_channel(channels, ["My", "Moment1Y", "MY1", "My1", "MY", "Channel_05"])

            if mx is not None and my is not None:
                # COP = Moment / Force; avoid division by zero.
                fz_safe = np.where(np.abs(fz) > 1, fz, 1)
                if cop_ap is None:
                    cop_ap = -my / fz_safe  # AP direction (negative of moment Y)
                if cop_ml is None:
                    cop_ml = mx / fz_safe   # ML direction
    
    if fz is None:
        raise ValueError("No Fz (vertical force) data found in C3D file")

    # Bare Fz is kept RAW (C3D-faithful): the file stores Fz as the force the
    # subject applies to the plate (down = negative), and we expose it verbatim.
    # Sign handling is left to the user via an abs() ComputeStep (e.g. to get a
    # positive vGRF impulse) — we never mutate the channel's sign globally.

    # Force/analog sampling rate. NB: the C3D header "frame_rate" is the POINT
    # (marker) rate; analog force is usually sampled faster (subframes), so we
    # must use the ANALOG rate or the force time axis is wrong (was 10x off).
    analog_rate = None
    try:
        analog_rate = float(c3d["parameters"]["ANALOG"]["RATE"]["value"][0])
    except (KeyError, TypeError, IndexError):
        pass
    if not analog_rate or analog_rate <= 0:
        try:
            analog_rate = float(c3d["header"]["analogs"]["frame_rate"])
        except (KeyError, TypeError):
            analog_rate = None
    if not analog_rate or analog_rate <= 0:
        # Derive from point rate x subframes if possible.
        try:
            prate = float(c3d["parameters"]["POINT"]["RATE"]["value"][0])
            pframes = c3d["data"]["points"].shape[2]
            analog_rate = prate * (len(fz) / pframes) if pframes else prate
        except Exception:
            analog_rate = 1000.0

    # Create time array based on actual data length
    actual_samples = len(fz)
    fs = float(analog_rate)
    time = np.arange(actual_samples) / fs
    
    # Ensure all arrays have the same length. NaN padding / dropouts are handled
    # centrally by core.data_quality.clean_dataset when the dataset is loaded.
    min_len = min(len(fz), len(time))
    fz = fz[:min_len]
    fx = fx[:min_len] if fx is not None else None
    fy = fy[:min_len] if fy is not None else None
    cop_ap = cop_ap[:min_len] if cop_ap is not None else None
    cop_ml = cop_ml[:min_len] if cop_ml is not None else None
    time = time[:min_len]
    
    # Build data dictionary in the format expected by BalanceAnalyzer
    data = {
        "path": file_path,
        "name": name,
        "cop_ap": cop_ap if cop_ap is not None else np.zeros_like(fz),
        "cop_ml": cop_ml if cop_ml is not None else np.zeros_like(fz),
        "fz": fz,
        "time": time,
        "fs": float(fs),
        "analysis": None,
        "events": [],
        "force_plates": force_plates,
        "_fp_raw": fp_raw,
    }
    if markers is not None:
        data["markers"] = markers

    # Add fx, fy if available
    if fx is not None:
        data["fx"] = fx
    if fy is not None:
        data["fy"] = fy

    # Per-plate signals: expose every force plate's force/COP as its own
    # ``fp{p}:*`` signal so the catalog / RAW SIGNALS section / events can show
    # and select each plate (not just the first). The bare keys above remain
    # plate-1's view for backward compatibility. We always materialize at least
    # one plate (FP1) — files without a FORCE_PLATFORM:CHANNEL mapping synthesize
    # it from the bare keys — so the UI is uniformly plate-grouped.
    plate_signals, plate_keys = _plate_signals(fp_raw, min_len)
    if plate_signals:
        data.update(plate_signals)
        data["force_signal_keys"] = plate_keys
        data["n_force_plates"] = len(plate_keys) // 5  # 5 comps per plate
    else:
        ensure_fp1_from_bare(data)

    data["range_start"] = float(time[0])
    data["range_end"] = float(time[-1])
    
    log.info(f"Loaded C3D file: {data['name']}, fs={fs:.1f} Hz, duration={time[-1]:.2f}s")
    
    return data


def _extract_channel(channels: Dict[str, np.ndarray],
                    possible_names: List[str]) -> Optional[np.ndarray]:
    """
    Extract a channel from the channels dict using possible names.
    
    Args:
        channels: Dictionary mapping channel names to data
        possible_names: List of possible channel names to try
        
    Returns:
        Channel data or None if not found
    """
    if not channels:
        return None
    
    for name in possible_names:
        # Try exact match (case-insensitive)
        for key in channels.keys():
            if str(key).upper() == str(name).upper():
                try:
                    return channels[key].astype(np.float64)
                except Exception as e:
                    log.warning(f"Failed to convert channel {key}: {e}")
                    continue
        
        # Try contains match
        for key in channels.keys():
            if str(name).upper() in str(key).upper():
                try:
                    return channels[key].astype(np.float64)
                except Exception as e:
                    log.warning(f"Failed to convert channel {key}: {e}")
                    continue
    
    return None
