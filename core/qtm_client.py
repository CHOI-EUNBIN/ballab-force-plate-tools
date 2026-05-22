import asyncio
import math
import queue
import random
import time
import threading
import logging
from typing import Optional, Callable

try:
    import qtm_rt
    QTM_AVAILABLE = True
except ImportError:
    QTM_AVAILABLE = False

log = logging.getLogger(__name__)


# ── Real QTM client ──────────────────────────────────────────────────────────

class QTMClient:

    def __init__(self, host: str, data_queue: queue.Queue,
                 on_status: Callable[[str], None]):
        self.host = host
        self.data_queue = data_queue
        self.on_status = on_status

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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._stream())
        except Exception as e:
            self.on_status(f"error: {e}")
        finally:
            loop.close()

    async def _stream(self):
        if not QTM_AVAILABLE:
            self.on_status("error: qtm_rt not installed")
            return

        connection = await qtm_rt.connect(self.host)

        if connection is None:
            self.on_status("error: QTM not reachable")
            return

        self.on_status("connected")

        def on_packet(packet):
            try:
                force_data = packet.get_force()[1]
                if len(force_data) == 0:
                    return

                _fp_info, samples = force_data[0]
                for f in samples:
                    try:
                        self.data_queue.put_nowait((
                            float(f.x), float(f.y), float(f.z),
                            float(f.y_a), float(f.x_a),
                            float(f.x_m), float(f.y_m), float(f.z_m),
                        ))
                    except queue.Full:
                        pass
            except Exception as e:
                log.exception("Failed to parse QTM force packet")
                self.on_status(f"error: force parse failed: {e}")

        await connection.stream_frames(components=["force"], on_packet=on_packet)

        while True:
            await asyncio.sleep(1)

    def _iter_force_samples(self, packet):
        for getter_name in ("get_force_single", "get_force"):
            getter = getattr(packet, getter_name, None)
            if getter is None:
                continue
            force = getter()
            if not force:
                continue

            plates = force[1] if isinstance(force, tuple) and len(force) > 1 else force
            for plate in plates or []:
                sample_or_samples = plate[-1] if isinstance(plate, tuple) else plate

                if self._looks_like_force_sample(sample_or_samples):
                    yield sample_or_samples
                    continue

                for sample in sample_or_samples or []:
                    yield sample

    @staticmethod
    def _looks_like_force_sample(value):
        if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
            return True
        if isinstance(value, (list, tuple)) and len(value) >= 9:
            return all(isinstance(v, (int, float)) for v in value[:9])
        return False

    @staticmethod
    def _force_sample_values(sample):
        if hasattr(sample, "x") and hasattr(sample, "y") and hasattr(sample, "z"):
            return (
                float(sample.x), float(sample.y), float(sample.z),
                float(sample.x_m), float(sample.y_m), float(sample.z_m),
                float(sample.x_a), float(sample.y_a), float(sample.z_a),
            )

        if isinstance(sample, (list, tuple)) and len(sample) >= 9:
            return tuple(float(v) for v in sample[:9])

        return None


# ── Dummy client ─────────────────────────────────────────────────────────────

class DummyClient:

    def __init__(self, data_queue: queue.Queue,
                 on_status: Callable[[str], None]):
        self.data_queue = data_queue
        self.on_status = on_status

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._generate, daemon=True)
        self._thread.start()
        self.on_status("connected")

    def stop(self):
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _generate(self):
        t = 0.0
        dt = 1 / 1000
        cop_ap, cop_ml = 0.0, 0.0

        while not self._stop_event.is_set():
            cop_ap += (random.gauss(0, 0.3)
                       + 3.0 * math.sin(2 * math.pi * 0.25 * t)
                       + 1.2 * math.sin(2 * math.pi * 1.1 * t))
            cop_ml += (random.gauss(0, 0.2)
                       + 1.5 * math.sin(2 * math.pi * 0.18 * t)
                       + 0.8 * math.sin(2 * math.pi * 0.9 * t))
            cop_ap = max(-60.0, min(60.0, cop_ap))
            cop_ml = max(-35.0, min(35.0, cop_ml))

            fz = 750.0 + random.gauss(0, 4)
            mx = cop_ap * fz
            my = -cop_ml * fz

            try:
                self.data_queue.put_nowait((0.0, 0.0, fz, cop_ap, cop_ml, mx, my, 0.0))
            except queue.Full:
                pass

            time.sleep(dt)
            t += dt


# ── Legacy function wrappers (used by collect_tab) ───────────────────────────

def run_qtm(ip: str, data_queue: queue.Queue, status_cb: Callable[[str], None]):
    client = QTMClient(ip, data_queue, status_cb)
    client.start()
    client._thread.join()


def run_dummy(data_queue: queue.Queue, status_cb: Callable[[str], None]):
    client = DummyClient(data_queue, status_cb)
    client.start()
    client._thread.join()
