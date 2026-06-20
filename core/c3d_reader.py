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


def read_c3d(file_path: str) -> Dict:
    """
    Read a C3D file and extract force plate data.
    
    Args:
        file_path: Path to the C3D file
        
    Returns:
        Dictionary with keys: path, name, cop_ap, cop_ml, fz, fx, fy, time, fs,
                             analysis, events, range_start, range_end
    """
    if not C3D_AVAILABLE:
        raise ImportError("ezc3d is not installed. Install it with: pip install ezc3d")
    
    try:
        c3d = ezc3d.c3d(file_path)
    except Exception as e:
        raise ValueError(f"Failed to read C3D file: {e}")
    
    # Extract force data from analog channels
    analog = c3d["data"]["analogs"]
    
    if analog.size == 0:
        raise ValueError("No analog data (force plate) found in C3D file")
    
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
    
    # Get force data - look for common naming patterns
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
            # COP = Moment / Force
            # Avoid division by zero
            fz_safe = np.where(np.abs(fz) > 1, fz, 1)
            if cop_ap is None:
                cop_ap = -my / fz_safe  # AP direction (negative of moment Y)
            if cop_ml is None:
                cop_ml = mx / fz_safe   # ML direction
    
    if fz is None:
        raise ValueError("No Fz (vertical force) data found in C3D file")
    
    # Get frame rate
    try:
        header = c3d["header"]
        frame_rate = float(header["frame_rate"])
        num_frames = int(header["nb_frames"])
    except (KeyError, TypeError):
        frame_rate = 100.0
        num_frames = len(fz)
    
    # Create time array based on actual data length
    actual_samples = len(fz)
    time = np.arange(actual_samples) / frame_rate
    fs = frame_rate
    
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
        "name": file_path.split("\\")[-1].split("/")[-1].rsplit(".", 1)[0],
        "cop_ap": cop_ap if cop_ap is not None else np.zeros_like(fz),
        "cop_ml": cop_ml if cop_ml is not None else np.zeros_like(fz),
        "fz": fz,
        "time": time,
        "fs": float(fs),
        "analysis": None,
        "events": [],
    }
    
    # Add fx, fy if available
    if fx is not None:
        data["fx"] = fx
    if fy is not None:
        data["fy"] = fy
    
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
