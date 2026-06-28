import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication


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
