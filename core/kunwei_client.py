"""Kunwei 3D force-plate live source.

Wraps the vendor SDK (``kw-c-libd.dll``) over UDP and pushes the SAME 8-tuple
stream the CollectTab pipeline already consumes from QTM/Dummy:

    (fx, fy, fz, cop_ap, cop_ml, mx, my, mz)

The SDK delivers six floats per frame -- Fx, Fy, Fz, Mx, My, Mz (forces AND
moments; confirmed by the vendor C/C++ demo). COP is not streamed, so it is
derived from the moments here, matching ``core/c3d_reader._plate_cop`` so a
recorded Kunwei trial is processed consistently with file-loaded trials. If the
COP axes look mirrored for a given plate orientation, flip them in the existing
axis settings (``core/axis_settings.transform_live``) rather than here.

This module imports cleanly on any platform and without the DLL present:
``KW_AVAILABLE`` reports whether a live capture can actually run.
"""

import ctypes
import logging
import os
import queue
import sys
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ── DLL location / availability ──────────────────────────────────────────────

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "kunwei")
# Prefer the RELEASE build: the debug build (kw-c-libd.dll) depends on debug VC
# runtimes that are absent on normal machines, so it fails to load there.
_DLL_CANDIDATES = ("kw-c-lib.dll", "kw-c-libd.dll")

# SensorConfig.linkMode / decodeMode values (see vendor demo)
_LINK_UDP = 2
# decodeMode picks the wire frame size: 0 = 28-byte, 1 = 12-byte, 2 = 30-byte.
# This plate (KWFP6050) streams 28-byte frames -- confirmed empirically: mode 2
# yielded "CRC failed" with 0 parsed frames while mode 0 parsed real Fx..Mz
# values. Using the wrong mode looks like "Connected but no data".
_DECODE_28B = 0


def _dll_path():
    """Path to the first available vendor DLL, or None."""
    for name in _DLL_CANDIDATES:
        p = os.path.join(_VENDOR_DIR, name)
        if os.path.exists(p):
            return p
    return None


KW_AVAILABLE = sys.platform.startswith("win") and _dll_path() is not None


class SensorConfig(ctypes.Structure):
    """Mirror of the SDK ``SensorConfig`` struct (from demo/python/test.py)."""

    _fields_ = [
        ("linkMode", ctypes.c_int),
        ("decodeMode", ctypes.c_int),
        ("paras", ctypes.POINTER(ctypes.c_float)),
        ("sensorIp", ctypes.c_char_p),
        ("sensorPort", ctypes.c_ushort),
        ("localIp", ctypes.c_char_p),
        ("localPort", ctypes.c_ushort),
        ("serialPortName", ctypes.c_char_p),
        ("baudRate", ctypes.c_int),
    ]


def _load_dll():
    """Load the Kunwei capture DLL with proper signatures, or return None."""
    if not sys.platform.startswith("win"):
        return None
    dll_path = _dll_path()
    if dll_path is None:
        return None
    try:
        if sys.version_info >= (3, 8):
            os.add_dll_directory(_VENDOR_DIR)
        dll = ctypes.windll.LoadLibrary(dll_path)
        dll.kwSetConfig.argtypes = [ctypes.c_int, ctypes.POINTER(SensorConfig)]
        dll.kwSetConfig.restype = ctypes.c_int
        dll.kwStartCapture.argtypes = [ctypes.c_int]
        dll.kwStartCapture.restype = ctypes.c_int
        dll.kwStopCapture.argtypes = [ctypes.c_int]
        dll.kwStopCapture.restype = ctypes.c_int
        dll.kwResetConfig.argtypes = [ctypes.c_int]
        dll.kwResetConfig.restype = ctypes.c_int
        dll.kwGetForceDataF.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        dll.kwGetForceDataF.restype = ctypes.c_int
        return dll
    except Exception:
        log.exception("Failed to load Kunwei DLL at %s", dll_path)
        return None


def _cop_from_moments(fx, fy, fz, mx, my, mz):
    """COP from plate moments, matching core/c3d_reader._plate_cop.

    cop_ap = -My / Fz, cop_ml = Mx / Fz, with Fz clamped to +-1 when |Fz| < 1
    to avoid a division blow-up while the plate is unloaded.
    """
    if abs(fz) >= 1.0:
        fz_safe = fz
    else:
        fz_safe = 1.0 if fz >= 0.0 else -1.0
    return (-my / fz_safe, mx / fz_safe)


# ── Live client ──────────────────────────────────────────────────────────────

class KunweiClient:
    """Streams a Kunwei force plate into ``data_queue`` as 8-tuples.

    Interface mirrors ``core.qtm_client.QTMClient`` (start/stop/is_alive) so
    CollectTab can drive it identically. Defaults are the real device values
    confirmed from the vendor's KWinForce app (UDP, plate 192.168.1.28:5152,
    PC 192.168.1.100:8828).
    """

    # Consecutive empty polls before assuming the plate went quiet and backing
    # off. While streaming at 1 kHz we poll far faster, so this is reached only
    # after the plate actually stops (~tenths of a second), never mid-stream.
    _IDLE_BACKOFF_MISSES = 500_000

    def __init__(self, sensor_ip: str = "192.168.1.28",
                 data_queue: Optional[queue.Queue] = None,
                 on_status: Optional[Callable[[str], None]] = None,
                 *, local_ip: str = "192.168.1.100",
                 sensor_port: int = 5152, local_port: int = 8828,
                 device_idx: int = 0, decode_mode: int = _DECODE_28B):
        self.sensor_ip = sensor_ip
        self.data_queue = data_queue
        self.on_status = on_status or (lambda s: None)
        self.local_ip = local_ip
        self.sensor_port = sensor_port
        self.local_port = local_port
        self.device_idx = device_idx
        self.decode_mode = decode_mode

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        dll = _load_dll()
        if dll is None:
            self.on_status("error: Kunwei SDK(DLL) not found")
            return

        idx = self.device_idx
        cfg = SensorConfig()
        cfg.linkMode = _LINK_UDP
        cfg.decodeMode = self.decode_mode
        cfg.sensorIp = self.sensor_ip.encode("ascii")
        cfg.sensorPort = self.sensor_port
        cfg.localIp = self.local_ip.encode("ascii")
        cfg.localPort = self.local_port
        cfg.paras = (ctypes.c_float * 6)(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

        started = False
        try:
            if dll.kwSetConfig(idx, ctypes.byref(cfg)) != 0:
                self.on_status("error: config failed (IP/port 확인)")
                return
            if dll.kwStartCapture(idx) != 0:
                self.on_status("error: cannot start capture (장비/네트워크 확인)")
                return
            started = True
            self.on_status("connected")

            data = (ctypes.c_float * 6)()
            frame_num = ctypes.c_uint64(0)
            total_bytes = ctypes.c_size_t(0)

            # kwGetForceDataF is non-blocking: it returns 0 with a fresh frame or
            # non-zero when none is ready yet. The plate streams up to 1000 Hz
            # (one sample/ms), so we must poll TIGHTLY -- a real sleep on a miss
            # costs ~15 ms on Windows (timer granularity) and would crater the
            # rate to ~30 Hz. We only back off once the plate has clearly gone
            # quiet, so an idle/disconnected plate doesn't peg a CPU core.
            idle_misses = 0
            while not self._stop_event.is_set():
                ret = dll.kwGetForceDataF(
                    idx, data, ctypes.byref(frame_num), ctypes.byref(total_bytes)
                )
                if ret == 0:
                    fx, fy, fz = float(data[0]), float(data[1]), float(data[2])
                    mx, my, mz = float(data[3]), float(data[4]), float(data[5])
                    cop_ap, cop_ml = _cop_from_moments(fx, fy, fz, mx, my, mz)
                    try:
                        self.data_queue.put_nowait(
                            (fx, fy, fz, cop_ap, cop_ml, mx, my, mz)
                        )
                    except queue.Full:
                        pass
                    idle_misses = 0
                else:
                    # Far more misses than samples are normal while streaming
                    # (we poll much faster than 1 kHz). Only a long unbroken run
                    # of misses means the plate stopped sending -> back off then.
                    idle_misses += 1
                    if idle_misses >= self._IDLE_BACKOFF_MISSES:
                        self._stop_event.wait(0.003)
        except Exception as e:  # pragma: no cover - hardware/runtime faults
            log.exception("Kunwei capture loop failed")
            self.on_status(f"error: {e}")
        finally:
            if started:
                try:
                    dll.kwStopCapture(idx)
                    dll.kwResetConfig(idx)
                except Exception:  # pragma: no cover
                    log.exception("Kunwei teardown failed")


# ── Legacy thread-target wrapper (matches collect_tab's run_qtm pattern) ──────

def run_kunwei(sensor_ip: str, local_ip: str, data_queue: queue.Queue,
               status_cb: Callable[[str], None], *,
               sensor_port: int = 5152, local_port: int = 8828):
    client = KunweiClient(sensor_ip, data_queue, status_cb, local_ip=local_ip,
                          sensor_port=sensor_port, local_port=local_port)
    client.start()
    client._thread.join()
