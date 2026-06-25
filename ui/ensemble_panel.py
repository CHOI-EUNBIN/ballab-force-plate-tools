"""Cross-trial ensemble: pool per-trial normalized epoch matrices, plot mean +/-
SD over 0-100% phase, and export CSV. Plus the add/edit NormalizeStep dialog.

UI-thin: all math is in core.ensemble / core.normalize. The panel is fed
``(file_label, norm_dict)`` sources by the Analyze tab (one per checked trial
that produced the chosen NormalizeStep output).
"""
import re
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QDialog, QLineEdit, QSpinBox, QFormLayout, QDialogButtonBox,
)

from core.ensemble import pool, ensemble_stats, ensemble_csv
from ui.components.cascading_signal_picker import CascadingSignalPicker


class EnsemblePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources = []          # list of (label, norm_dict)
        self._stats = ensemble_stats(np.empty((0, 0)))
        self._cols = []

        v = QVBoxLayout(self)
        head = QHBoxLayout()
        self._title = QLabel("Ensemble (% cycle)")
        self._n_label = QLabel("0 epochs")
        self._export_btn = QPushButton("Export CSV...")
        self._export_btn.clicked.connect(self._on_export)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._n_label)
        head.addWidget(self._export_btn)
        v.addLayout(head)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "% cycle")
        self._mean_curve = self._plot.plot(pen=pg.mkPen("#3B8FD9", width=2))
        # lo/hi invisible boundary curves for the ±SD fill band; must be created
        # before FillBetweenItem (pyqtgraph 0.14 requires curve1/curve2 upfront).
        self._lo = self._plot.plot(pen=pg.mkPen(None))
        self._hi = self._plot.plot(pen=pg.mkPen(None))
        self._band = pg.FillBetweenItem(self._lo, self._hi,
                                        brush=pg.mkBrush(59, 143, 217, 60))
        self._plot.addItem(self._band)
        v.addWidget(self._plot, 1)

    def set_sources(self, sources, title=None):
        """``sources`` = list of ``(file_label, norm_dict)`` where ``norm_dict`` has
        ``matrix`` (N_i x P). Pools, recomputes stats, redraws.

        Optional ``title`` kwarg sets the panel title (e.g. including the step name)."""
        if title is not None:
            self._title.setText(title)
        self._sources = list(sources or [])
        mats, cols = [], []
        for label, nd in self._sources:
            m = np.asarray(nd.get("matrix"), float)
            if m.ndim == 2 and m.shape[0] > 0:
                mats.append(m)
                cols.extend(f"{label}#{i+1}" for i in range(m.shape[0]))
        matrix = pool(mats) if mats else np.empty((0, 0))
        self._matrix = matrix
        self._cols = cols
        self._stats = ensemble_stats(matrix)
        self._n_label.setText(f"{self._stats['n']} epochs")
        self._redraw()

    def set_title_suffix(self, text):
        """Update the panel title to include ``text`` as a suffix, e.g. the step name."""
        base = "Ensemble (% cycle)"
        self._title.setText(f"{base} — {text}" if text else base)

    def n_epochs(self):
        return int(self._stats.get("n", 0))

    def stats(self):
        return self._stats

    def export_csv(self, path):
        text = ensemble_csv(getattr(self, "_matrix", np.empty((0, 0))),
                            self._stats, columns=self._cols)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def _redraw(self):
        x = self._stats.get("x")
        mean = self._stats.get("mean")
        sd = self._stats.get("sd")
        if x is None or len(x) == 0:
            self._mean_curve.setData([], [])
            self._lo.setData([], [])
            self._hi.setData([], [])
            return
        self._mean_curve.setData(x, mean)
        self._lo.setData(x, mean - sd)
        self._hi.setData(x, mean + sd)

    def _on_export(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export ensemble CSV",
                                              "ensemble.csv", "CSV (*.csv)")
        if path:
            self.export_csv(path)


class NormalizeStepDialog(QDialog):
    """Add/edit a NormalizeStep: pick a signal, an epoch mode + its event(s),
    and the phase resolution. ``values()`` returns kwargs for ``NormalizeStep``."""

    MODES = [("Consecutive event (cycle)", "cycle"),
             ("Start to end event (window)", "window"),
             ("Whole trial", "trial")]

    def __init__(self, parent, inputs, event_labels, step=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Normalize" if step else "Add Normalize")
        self.setModal(True)
        form = QFormLayout(self)

        self.input_combo = CascadingSignalPicker(keys=inputs)
        cur_in = getattr(step, "input", None) if step else None
        if cur_in:
            self.input_combo.set_key(cur_in)
        else:
            self.input_combo.prefer_filtered_default()
        form.addRow("Signal", self.input_combo)

        self.name_edit = QLineEdit(getattr(step, "name", "") if step else "")
        self.name_edit.setPlaceholderText("Output name (e.g. knee_cycle)")
        form.addRow("Name", self.name_edit)

        self.mode_combo = QComboBox()
        for label, key in self.MODES:
            self.mode_combo.addItem(label, key)
        if step is not None:
            i = self.mode_combo.findData(getattr(step, "mode", "cycle"))
            if i >= 0:
                self.mode_combo.setCurrentIndex(i)
        form.addRow("Epoch", self.mode_combo)

        labels = list(event_labels or [])
        self.event_combo = QComboBox()
        self.event_combo.addItems(labels)
        self.start_combo = QComboBox()
        self.start_combo.addItems(labels)
        self.end_combo = QComboBox()
        self.end_combo.addItems(labels)
        if step is not None:
            for combo, val in ((self.event_combo, getattr(step, "event", "")),
                               (self.start_combo, getattr(step, "start_event", "")),
                               (self.end_combo, getattr(step, "end_event", ""))):
                j = combo.findText(val)
                if j >= 0:
                    combo.setCurrentIndex(j)
        # Store label widgets explicitly so we can show/hide them per mode.
        self._event_label = QLabel("Event (cycle)")
        self._start_label = QLabel("Start event")
        self._end_label = QLabel("End event")
        form.addRow(self._event_label, self.event_combo)
        form.addRow(self._start_label, self.start_combo)
        form.addRow(self._end_label, self.end_combo)

        self.points_spin = QSpinBox()
        self.points_spin.setRange(2, 1001)
        self.points_spin.setValue(getattr(step, "points", 101) if step else 101)
        form.addRow("Points", self.points_spin)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

        # Wire mode → event-row visibility and set initial state.
        self.mode_combo.currentIndexChanged.connect(self._sync_event_rows)
        self._sync_event_rows()

    def _sync_event_rows(self, _index=None):
        """Show only the event rows relevant to the current epoch mode.

        cycle  → "Event (cycle)" only
        window → "Start event" + "End event" only
        trial  → none of the three rows
        """
        mode = self.mode_combo.currentData()
        is_cycle = mode == "cycle"
        is_window = mode == "window"
        self._event_label.setVisible(is_cycle)
        self.event_combo.setVisible(is_cycle)
        self._start_label.setVisible(is_window)
        self.start_combo.setVisible(is_window)
        self._end_label.setVisible(is_window)
        self.end_combo.setVisible(is_window)

    def values(self):
        raw_name = self.name_edit.text().strip()
        # Sanitize: spaces and colons become underscores so the key "norm:<name>"
        # is always well-formed (no embedded colons or whitespace).
        safe_name = re.sub(r"[\s:]+", "_", raw_name)
        return {
            "input": self.input_combo.selected_key() or "",
            "name": safe_name,
            "mode": self.mode_combo.currentData(),
            "event": self.event_combo.currentText(),
            "start_event": self.start_combo.currentText(),
            "end_event": self.end_combo.currentText(),
            "points": int(self.points_spin.value()),
        }
