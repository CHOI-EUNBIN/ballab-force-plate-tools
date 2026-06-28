"""Record-tab controls: Zero (tare) and live Pause/Resume.

Pure offset math is tested directly; the tab-level behaviour (Zero captures a
baseline then subtracts it; Pause stops the client but keeps settings; Record
auto-resumes) is exercised headless under the offscreen Qt platform.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── pure offset math ─────────────────────────────────────────────────────────

def test_tare_offset_is_per_channel_mean():
    from ui.collect_tab import _tare_offset
    samples = [[2, 4, 6, 8, 10, 12, 14, 16],
               [4, 6, 8, 10, 12, 14, 16, 18]]
    assert _tare_offset(samples) == [3, 5, 7, 9, 11, 13, 15, 17]
    assert _tare_offset([]) is None


def test_apply_offset_subtracts_and_passes_through_none():
    from ui.collect_tab import _apply_offset
    vals = [10, 20, 30, 40, 50, 60, 70, 80]
    off = [1, 2, 3, 4, 5, 6, 7, 8]
    assert _apply_offset(vals, off) == [9, 18, 27, 36, 45, 54, 63, 72]
    assert _apply_offset(vals, None) == vals


# ── tare through the tab's _update loop ──────────────────────────────────────

def test_zero_captures_baseline_and_subtracts(app):
    from ui.collect_tab import CollectTab, TARE_SAMPLES
    tab = CollectTab()
    baseline = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)  # fx,fy,fz,ap,ml,mx,my,mz

    tab._on_zero()
    assert tab._tare_collect == []           # collecting armed

    # Feed exactly enough identical samples to fill the baseline window.
    for _ in range(TARE_SAMPLES):
        tab.data_queue.put_nowait(baseline)
    tab._update()

    # Offset captured == the constant baseline; collection disarmed.
    assert tab._tare_collect is None
    assert tab.tare_offset == pytest.approx(list(baseline))

    # A further sample equal to the baseline is now tared to ~0 in the buffers.
    tab.data_queue.put_nowait(baseline)
    tab._update()
    assert tab.fz_buf[-1] == pytest.approx(0.0)   # fz channel (index 2) zeroed
    assert tab.ap_buf[-1] == pytest.approx(0.0)

    tab._on_clear_zero()
    assert tab.tare_offset is None and tab._tare_collect is None


# ── live pause / resume ──────────────────────────────────────────────────────

def test_pause_keeps_settings_resume_restarts(app):
    from ui.collect_tab import CollectTab, SRC_DEMO
    tab = CollectTab()
    tab.source_combo.setCurrentText(SRC_DEMO)

    tab._on_connect_clicked()                 # connect Demo
    assert tab.live_client is not None
    assert tab.pause_btn.isEnabled()
    assert tab.connect_btn.text() == "Disconnect"

    tab._on_pause_toggle()                    # pause
    assert tab.live_client is None            # polling thread stopped (CPU freed)
    assert tab.live_paused is True
    assert tab.pause_btn.text() == "Resume Live"
    assert tab.connect_btn.text() == "Disconnect"   # still "connected", just paused

    tab._on_pause_toggle()                    # resume
    assert tab.live_client is not None
    assert tab.live_paused is False
    assert tab.pause_btn.text() == "Pause Live"

    tab._disconnect_live()                    # cleanup thread


def test_record_auto_resumes_when_paused(app):
    from ui.collect_tab import CollectTab, SRC_DEMO
    tab = CollectTab()
    tab.source_combo.setCurrentText(SRC_DEMO)
    tab._on_connect_clicked()
    tab._on_pause_toggle()
    assert tab.live_paused is True

    tab._start_recording()
    assert tab.live_paused is False           # stream resumed for the recording
    assert tab.live_client is not None

    tab._disconnect_live()


def test_disconnect_resets_pause_ui(app):
    from ui.collect_tab import CollectTab, SRC_DEMO
    tab = CollectTab()
    tab.source_combo.setCurrentText(SRC_DEMO)
    tab._on_connect_clicked()
    assert tab.pause_btn.isEnabled()

    tab._on_connect_clicked()                 # toggle -> disconnect
    assert tab.live_client is None
    assert not tab.pause_btn.isEnabled()
    assert tab.connect_btn.text() == "Connect"
