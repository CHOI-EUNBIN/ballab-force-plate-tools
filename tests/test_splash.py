import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEasingCurve


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _make(app):
    from ui.splash import AnimatedSplash
    pm = QPixmap(1024, 1024)
    pm.fill()
    return AnimatedSplash(pm)


def test_initial_state_is_transparent_and_small(app):
    from ui import splash as s
    w = _make(app)
    assert w.opacity == 0.0
    assert w.scale == s.SCALE_FROM
    assert w.width() == s.WIDGET_SIZE and w.height() == s.WIDGET_SIZE


def test_setters_store_value(app):
    w = _make(app)
    w.opacity = 0.5
    w.scale = 1.0
    assert w.opacity == 0.5
    assert w.scale == 1.0


def test_target_rect_scales_and_centers(app):
    from ui import splash as s
    w = _make(app)
    w.scale = 1.0
    r = w.target_rect()
    assert round(r.width()) == s.BASE_SIZE
    assert round(r.center().x()) == s.WIDGET_SIZE // 2
    assert round(r.center().y()) == s.WIDGET_SIZE // 2
    w.scale = s.SCALE_FROM
    assert round(w.target_rect().width()) == round(s.BASE_SIZE * s.SCALE_FROM)


def test_start_builds_intro_anims_with_correct_params(app):
    from ui import splash as s
    w = _make(app)
    w.start()
    assert w._fade.startValue() == 0.0 and w._fade.endValue() == 1.0
    assert w._fade.duration() == s.INTRO_FADE_MS
    assert w._fade.easingCurve().type() == QEasingCurve.Type.OutCubic
    assert w._scale_anim.startValue() == s.SCALE_FROM
    assert w._scale_anim.endValue() == 1.0
    assert w._scale_anim.duration() == s.INTRO_SCALE_MS
    assert w._scale_anim.easingCurve().type() == QEasingCurve.Type.OutCubic


def test_finish_delay_respects_minimum(app):
    from ui import splash as s
    w = _make(app)
    assert w.finish_delay_ms(0) == s.MIN_DISPLAY_MS
    assert w.finish_delay_ms(s.MIN_DISPLAY_MS + 500) == 0
    assert w.finish_delay_ms(300) == s.MIN_DISPLAY_MS - 300


def test_outro_starts_fade_to_zero_and_reveals_window(app):
    from ui import splash as s
    w = _make(app)
    w.start()
    w._opacity = 1.0

    class _FakeWin:
        def __init__(self):
            self.raised = False
            self.activated = False
        def raise_(self):
            self.raised = True
        def activateWindow(self):
            self.activated = True

    fw = _FakeWin()
    w._win = fw
    w._outro()
    assert fw.raised and fw.activated
    assert w._fade_out.endValue() == 0.0
    assert w._fade_out.duration() == s.OUTRO_FADE_MS
