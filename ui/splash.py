"""Animated startup splash: fades the logo in while scaling it up, holds for a
minimum time, then fades out. A frameless, translucent, always-on-top widget so
only the transparent-PNG logo is visible over the brief pre-paint flash."""

from PyQt6.QtCore import Qt, QRectF, pyqtProperty
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QWidget

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
        screen = self.screen() or (self.windowHandle() and self.windowHandle().screen())
        geo = (screen.availableGeometry() if screen else None)
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
