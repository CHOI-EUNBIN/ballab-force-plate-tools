"""Animated startup splash: fades the logo in while scaling it up, holds for a
minimum time, then fades out. A frameless, translucent, always-on-top widget so
only the transparent-PNG logo is visible over the brief pre-paint flash."""

from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QElapsedTimer, QPropertyAnimation, QEasingCurve,
    pyqtProperty,
)
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QWidget

BASE_SIZE = 300        # logo side length (px) at scale 1.0
WIDGET_SIZE = 360      # widget side; padding so the scaled logo never clips
INTRO_FADE_MS = 700
INTRO_SCALE_MS = 800
MIN_DISPLAY_MS = 800
OUTRO_FADE_MS = 350
SCALE_FROM = 0.92


class AnimatedSplash(QWidget):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = 0.0
        self._scale = SCALE_FROM
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else None
        if geo is not None:
            self.move(geo.center().x() - WIDGET_SIZE // 2,
                      geo.center().y() - WIDGET_SIZE // 2)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _get_scale(self):
        return self._scale

    def _set_scale(self, value):
        self._scale = float(value)
        self.update()

    scale = pyqtProperty(float, _get_scale, _set_scale)

    def target_rect(self):
        side = BASE_SIZE * self._scale
        x = (self.width() - side) / 2.0
        y = (self.height() - side) / 2.0
        return QRectF(x, y, side, side)

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))
        painter.drawPixmap(self.target_rect(), self._pixmap,
                           QRectF(self._pixmap.rect()))
        painter.end()

    def start(self):
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._fade = QPropertyAnimation(self, b"opacity", self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setDuration(INTRO_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scale_anim = QPropertyAnimation(self, b"scale", self)
        self._scale_anim.setStartValue(SCALE_FROM)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.setDuration(INTRO_SCALE_MS)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()
        self._scale_anim.start()

    def finish_delay_ms(self, elapsed):
        return max(0, MIN_DISPLAY_MS - int(elapsed))

    def finish(self, win):
        self._win = win
        elapsed = self._elapsed.elapsed() if hasattr(self, "_elapsed") else 0
        QTimer.singleShot(self.finish_delay_ms(elapsed), self._outro)

    def _outro(self):
        if getattr(self, "_win", None) is not None:
            self._win.raise_()
            self._win.activateWindow()
        self._fade_out = QPropertyAnimation(self, b"opacity", self)
        self._fade_out.setStartValue(self._opacity)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setDuration(OUTRO_FADE_MS)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.close)
        self._fade_out.start()
