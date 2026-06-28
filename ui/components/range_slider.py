"""Time range slider used by the Analyze tab playback bar.

Split out of ``ui/analyze_tab.py``. Draws a flat track with start/end handles
plus a current-position marker and reports drags via ``rangeChanged`` /
``currentChanged``.
"""

from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal


class TimeRangeSlider(QWidget):
    rangeChanged = pyqtSignal(float, float)
    currentChanged = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self._min = 0.0
        self._max = 1.0
        self._start = 0.0
        self._end = 1.0
        self._current = 0.0
        self._drag = None
        self.setMinimumHeight(30)
        self.setMouseTracking(True)

    def set_bounds(self, min_value, max_value):
        self._min = float(min_value)
        self._max = max(float(max_value), self._min + 1e-9)
        self.set_range(self._min, self._max, emit=False)
        self.set_current(self._min, emit=False)

    def set_range(self, start, end, emit=True):
        start = self._clamp(float(start))
        end = self._clamp(float(end))
        if end < start:
            start, end = end, start
        self._start = start
        self._end = end
        if emit:
            self.rangeChanged.emit(self._start, self._end)
        self.update()

    def set_current(self, value, emit=True):
        self._current = self._clamp(float(value))
        if emit:
            self.currentChanged.emit(self._current)
        self.update()

    def values(self):
        return self._start, self._end, self._current

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() // 2
        x0 = 14
        x1 = self.width() - 14
        xs = self._x_for_value(self._start)
        xe = self._x_for_value(self._end)
        xc = self._x_for_value(self._current)

        painter.setPen(Qt.PenStyle.NoPen)
        # Flat (square) track, range and handles — no rounded ends.
        painter.setBrush(QColor("#3A3A3A"))
        painter.drawRect(x0, y - 2, x1 - x0, 4)
        painter.setBrush(QColor(59, 130, 246, 160))
        painter.drawRect(int(xs), y - 3, max(1, int(xe - xs)), 6)
        painter.setBrush(QColor("#E8E8E8"))
        painter.drawRect(int(xs) - 3, y - 7, 6, 14)
        painter.drawRect(int(xe) - 3, y - 7, 6, 14)
        painter.setBrush(QColor("#1D9E75"))
        painter.drawRect(int(xc) - 1, y - 12, 3, 24)

    def mousePressEvent(self, event):
        value = self._value_for_x(event.position().x())
        distances = {
            "start": abs(value - self._start),
            "end": abs(value - self._end),
            "current": abs(value - self._current),
        }
        self._drag = min(distances, key=distances.get)
        self._apply_drag(value)

    def mouseMoveEvent(self, event):
        if self._drag:
            self._apply_drag(self._value_for_x(event.position().x()))

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def _apply_drag(self, value):
        value = self._clamp(value)
        if self._drag == "start":
            self.set_range(value, self._end)
        elif self._drag == "end":
            self.set_range(self._start, value)
        else:
            self.set_current(value)

    def _x_for_value(self, value):
        x0 = 14
        x1 = self.width() - 14
        ratio = (self._clamp(value) - self._min) / (self._max - self._min)
        return int(x0 + ratio * (x1 - x0))

    def _value_for_x(self, x):
        x0 = 14
        x1 = self.width() - 14
        ratio = (float(x) - x0) / max(1, x1 - x0)
        return self._min + max(0.0, min(1.0, ratio)) * (self._max - self._min)

    def _clamp(self, value):
        return max(self._min, min(self._max, value))
