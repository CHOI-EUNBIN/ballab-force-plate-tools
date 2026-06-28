"""A draggable vertical resize handle. Split out of ``ui/analyze_tab.py``."""

from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal


class VResizeHandle(QWidget):
    """A draggable bar that resizes the ``target`` widget's height like a real
    splitter handle: it anchors the target height + cursor at press, then emits
    an *absolute* requested height each move (anchor + total drag) — no per-event
    accumulation, so it never drifts/jitters. Grabs the mouse so the drag stays
    smooth even if the cursor leaves the thin strip."""

    resized = pyqtSignal(int)   # requested absolute height (px) for the target

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self._target = target
        self.setObjectName("tree-resize")
        self.setFixedHeight(8)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._press_y = None
        self._press_h = 0
        self._hover = False

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_y = e.globalPosition().y()
            self._press_h = self._target.height()
            self.grabMouse()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._press_y is not None:
            target = self._press_h + (e.globalPosition().y() - self._press_y)
            self.resized.emit(int(round(target)))
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._press_y is not None:
            self._press_y = None
            self.releaseMouse()
            e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(120, 130, 140, 150 if self._hover else 75))
        cx = self.width() // 2
        p.drawRect(cx - 16, 3, 32, 2)
        p.end()


# Backwards-compatible alias (the class was previously named ``_VResizeHandle``).
_VResizeHandle = VResizeHandle
