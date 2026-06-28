"""Numeric time-series table viewer.

Any plottable time series (COP, force, marker X/Y/Z, joint angles) can be shown
as a raw numbers table via right-click → "View data table". Backed by a
QAbstractTableModel over numpy arrays so even minute-long, multi-kHz trials
render instantly (only visible rows are formatted).
"""

import numpy as np
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtWidgets import (
    QDialog, QTableView, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QApplication, QHeaderView,
)


class _TimeSeriesModel(QAbstractTableModel):
    """Column 0 = Time (s); remaining columns = the named series."""

    def __init__(self, time, columns):
        super().__init__()
        self._time = np.asarray(time, dtype=float)
        self._names = [name for name, _ in columns]
        self._cols = [np.asarray(arr, dtype=float) for _, arr in columns]
        self._n = len(self._time)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._n

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 1 + len(self._cols)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            r, c = index.row(), index.column()
            v = self._time[r] if c == 0 else self._cols[c - 1][r]
            if not np.isfinite(v):
                return "—"
            return f"{v:.4f}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return "Time (s)" if section == 0 else self._names[section - 1]
        return str(section + 1)

    # --- export helpers ---
    def to_rows(self):
        header = ["Time (s)"] + self._names
        yield header
        for r in range(self._n):
            row = [f"{self._time[r]:.6f}"]
            row += [("" if not np.isfinite(a[r]) else f"{a[r]:.6f}") for a in self._cols]
            yield row


class DataTableDialog(QDialog):
    def __init__(self, parent, title, time, columns):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(440, 520)
        self._model = _TimeSeriesModel(time, columns)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(QLabel(f"{self._model.rowCount():,} samples"))

        self.view = QTableView()
        self.view.setModel(self._model)
        self.view.setAlternatingRowColors(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.view.verticalHeader().setDefaultSectionSize(18)
        lay.addWidget(self.view, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy)
        csv_btn = QPushButton("Export CSV…")
        csv_btn.clicked.connect(self._export_csv)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        for b in (copy_btn, csv_btn, close_btn):
            btns.addWidget(b)
        lay.addLayout(btns)

    def _copy(self):
        text = "\n".join("\t".join(row) for row in self._model.to_rows())
        QApplication.clipboard().setText(text)

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", self.windowTitle().replace(":", "").strip() + ".csv",
            "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as f:
            for row in self._model.to_rows():
                f.write(",".join(row) + "\n")
