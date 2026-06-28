"""KunweiClient: wraps the Kunwei force-plate SDK DLL and feeds the same
8-tuple stream the CollectTab pipeline already consumes from QTM/Dummy.

These tests run WITHOUT hardware or the real DLL: a FakeDLL stands in for the
loaded library (injected by monkeypatching ``_load_dll``), so the COP math,
queue tuple shape, lifecycle, and error handling are verified headlessly.
"""

import ctypes
import queue
import time

import pytest

from core import kunwei_client
from core.kunwei_client import KunweiClient, _cop_from_moments


class FakeDLL:
    """Minimal stand-in for kw-c-libd.dll.

    ``frames`` is a list of (fx, fy, fz, mx, my, mz) tuples handed out one per
    ``kwGetForceDataF`` call; once exhausted it reports "no new data" (ret != 0).
    """

    def __init__(self, frames, set_ret=0, start_ret=0):
        self._frames = list(frames)
        self._i = 0
        self.set_ret = set_ret
        self.start_ret = start_ret
        self.stopped = False
        self.reset = False

    def kwSetConfig(self, idx, cfg_ref):
        return self.set_ret

    def kwStartCapture(self, idx):
        return self.start_ret

    def kwGetForceDataF(self, idx, data, frame_ref, bytes_ref):
        if self._i >= len(self._frames):
            return 1  # no new frame available
        fr = self._frames[self._i]
        self._i += 1
        for k in range(6):
            data[k] = fr[k]
        return 0

    def kwStopCapture(self, idx):
        self.stopped = True
        return 0

    def kwResetConfig(self, idx):
        self.reset = True
        return 0


def _drain(q, n, timeout=2.0):
    """Collect up to n items from q, giving up after timeout seconds."""
    out = []
    deadline = time.time() + timeout
    while len(out) < n and time.time() < deadline:
        try:
            out.append(q.get(timeout=0.05))
        except queue.Empty:
            pass
    return out


# ── COP math ─────────────────────────────────────────────────────────────────

def test_cop_from_moments_matches_c3d_convention():
    # cop_ap = -My/Fz, cop_ml = Mx/Fz  (same as core/c3d_reader._plate_cop)
    cop_ap, cop_ml = _cop_from_moments(0.0, 0.0, 500.0, 50.0, -30.0, 0.0)
    assert cop_ap == pytest.approx(0.06)   # -(-30)/500
    assert cop_ml == pytest.approx(0.10)   # 50/500


def test_cop_clamps_near_zero_fz():
    # |Fz| < 1 must not divide-by-zero; clamps to +-1.
    cop_ap, cop_ml = _cop_from_moments(0.0, 0.0, 0.0, 5.0, -3.0, 0.0)
    assert cop_ap == pytest.approx(3.0)    # -(-3)/1
    assert cop_ml == pytest.approx(5.0)    # 5/1
    cop_ap_neg, _ = _cop_from_moments(0.0, 0.0, -0.2, 0.0, 4.0, 0.0)
    assert cop_ap_neg == pytest.approx(4.0)  # -(4)/-1


# ── Streaming -> queue ───────────────────────────────────────────────────────

def test_pushes_8_tuples_with_computed_cop(monkeypatch):
    frames = [
        (10.0, 20.0, 500.0, 50.0, -30.0, 5.0),
        (12.0, 22.0, 400.0, 40.0, -20.0, 4.0),
    ]
    fake = FakeDLL(frames)
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: fake)

    q = queue.Queue()
    status = []
    client = KunweiClient("192.168.1.28", q, status.append)
    client.start()
    got = _drain(q, len(frames))
    client.stop()

    assert "connected" in status
    assert len(got) == len(frames)
    for (fx, fy, fz, mx, my, mz), tup in zip(frames, got):
        gfx, gfy, gfz, cop_ap, cop_ml, gmx, gmy, gmz = tup
        assert (gfx, gfy, gfz) == pytest.approx((fx, fy, fz))
        assert (gmx, gmy, gmz) == pytest.approx((mx, my, mz))
        assert cop_ap == pytest.approx(-my / fz, rel=1e-4)
        assert cop_ml == pytest.approx(mx / fz, rel=1e-4)


def test_config_failure_reports_error(monkeypatch):
    fake = FakeDLL([(1, 2, 3, 4, 5, 6)], set_ret=1)
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: fake)
    q = queue.Queue()
    status = []
    client = KunweiClient("192.168.1.28", q, status.append)
    client.start()
    time.sleep(0.2)
    client.stop()
    assert any(s.startswith("error:") for s in status)
    assert "connected" not in status
    assert q.empty()


def test_start_capture_failure_reports_error(monkeypatch):
    fake = FakeDLL([(1, 2, 3, 4, 5, 6)], start_ret=1)
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: fake)
    q = queue.Queue()
    status = []
    client = KunweiClient("192.168.1.28", q, status.append)
    client.start()
    time.sleep(0.2)
    client.stop()
    assert any(s.startswith("error:") for s in status)
    assert q.empty()


def test_missing_dll_reports_error(monkeypatch):
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: None)
    q = queue.Queue()
    status = []
    client = KunweiClient("192.168.1.28", q, status.append)
    client.start()
    time.sleep(0.2)
    client.stop()
    assert any("not found" in s for s in status)


def test_queue_full_is_ignored(monkeypatch):
    frames = [(float(i), 0.0, 500.0, 0.0, 0.0, 0.0) for i in range(20)]
    fake = FakeDLL(frames)
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: fake)
    q = queue.Queue(maxsize=1)  # fills immediately; extra frames must not raise
    status = []
    client = KunweiClient("192.168.1.28", q, status.append)
    client.start()
    time.sleep(0.2)
    client.stop()
    time.sleep(0.1)
    # Survived without raising; capture was started and torn down cleanly.
    assert "connected" in status
    assert fake.stopped and fake.reset


def test_stop_tears_down_and_thread_exits(monkeypatch):
    fake = FakeDLL([(1, 2, 500, 0, 0, 0)])
    monkeypatch.setattr(kunwei_client, "_load_dll", lambda: fake)
    q = queue.Queue()
    client = KunweiClient("192.168.1.28", q, lambda s: None)
    assert not client.is_alive()
    client.start()
    _drain(q, 1)
    assert client.is_alive()
    client.stop()
    client._thread.join(timeout=2.0)
    assert not client.is_alive()
    assert fake.stopped and fake.reset
