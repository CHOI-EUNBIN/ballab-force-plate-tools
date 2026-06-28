"""File tree widget + row separator delegate used by the Analyze tab sidebar.

Split out of ``ui/analyze_tab.py``. The tree is a Windows-style folder view of
loaded files; the actual move logic lives in the tab (it rebuilds the tree from
the data model), the widget only reports drops via ``itemDropped``.
"""

from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import QTreeWidget, QStyledItemDelegate
from PyQt6.QtCore import Qt, pyqtSignal


# Tree item-data roles: a folder node carries its path (tuple of names) in
# FOLDER_PATH_ROLE; dataset (file) leaves carry their dataset index in UserRole.
FOLDER_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class FileTreeWidget(QTreeWidget):
    """A Windows-style folder tree of files. Files/folders can be dragged into
    another folder; the move is handled by the parent tab (which rebuilds the
    tree from the data model) rather than by Qt's default item move.
    """

    itemDropped = pyqtSignal(object, object)   # (dragged_item, drop_target_item)

    def dropEvent(self, event):
        src = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        # Don't let Qt physically move the row — we rebuild from the data model.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        self.itemDropped.emit(src, target)
        event.accept()


class TreeRowSeparator(QStyledItemDelegate):
    """Draws a thin separator line under each top-level (subject/group) row so the
    file tree reads as distinct folders."""

    LINE = QColor(120, 130, 140, 70)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not index.parent().isValid():   # top-level row → full-width underline
            painter.save()
            painter.setPen(QPen(self.LINE, 1))
            y = option.rect.bottom()
            painter.drawLine(option.rect.left(), y, option.rect.right(), y)
            painter.restore()
