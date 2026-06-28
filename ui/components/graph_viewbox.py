"""Custom pyqtgraph ViewBox for the Analyze tab plots.

Split out of ``ui/analyze_tab.py``. It keeps a back-reference to the owning tab
(``owner``) so right-click / double-click delegate to the tab's graph helpers.
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt


class GraphViewBox(pg.ViewBox):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.plot_widget = None
        self.graph_key = None
        self.is_time_plot = False

    def wheelEvent(self, event, axis=None):
        delta = event.delta() if hasattr(event, "delta") else event.angleDelta().y()
        if delta == 0:
            event.accept()
            return
        factor = 0.85 if delta > 0 else 1.0 / 0.85
        center = self.mapSceneToView(event.scenePos())
        modifiers = event.modifiers()
        if self.is_time_plot and not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.scaleBy(x=factor, y=1.0, center=center)
        elif self.is_time_plot:
            self.scaleBy(x=1.0, y=factor, center=center)
        else:
            self.scaleBy(x=factor, y=factor, center=center)
        event.accept()

    def mouseClickEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.plot_widget is not None:
            self.owner._show_graph_context_menu(
                self.plot_widget,
                self.graph_key,
                event.screenPos().toPoint(),
            )
            event.accept()
            return
        super().mouseClickEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.plot_widget is not None:
            self.owner._fit_graph_view(self.plot_widget)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def raiseContextMenu(self, event):
        if self.plot_widget is None:
            return
        self.owner._show_graph_context_menu(
            self.plot_widget,
            self.graph_key,
            event.screenPos().toPoint(),
        )
        event.accept()
