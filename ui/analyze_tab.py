import os
import csv

import numpy as np
import pyqtgraph as pg
from PyQt6.QtGui import QPainter, QColor, QBrush, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QPushButton, QLabel, QCheckBox,
    QScrollArea, QFileDialog, QListWidget, QListWidgetItem, QListView,
    QMessageBox, QAbstractItemView, QScroller, QLineEdit, QComboBox,
    QDoubleSpinBox, QColorDialog, QDialog, QDialogButtonBox, QFormLayout,
    QSplitter, QSizePolicy, QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent

from core.axis_settings import AxisSettings
from core.signal_proc import apply_lowpass
from core.metrics import METRIC_KEYS, compute_metrics, compute_ellipse_points
from ui.style import (
    ACCENT_TEAL, TEXT_PRIMARY, TEXT_SECONDARY,
    BORDER, GRAPH_BG, GRAPH_FG, BG_DARK,
)

C_RAW = "#555550"
C_FILT_AP = "#7F77DD"
C_FILT_ML = "#D4537E"
C_ELL = "#534AB7"
C_COP = "#42A5F5"
C_FX = "#D86A3A"
C_FY = "#3B8FD9"
C_FZ = "#1D9E75"


class EventDialog(QDialog):

    def __init__(self, parent, dataset, color, event=None):
        super().__init__(parent)
        self.dataset = dataset
        self.event_color = event.get("color", color) if event else color
        self.event = event
        self.setWindowTitle("Edit Event" if event else "Add Event")
        self.setModal(True)
        self.setMinimumWidth(320)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Event name")
        if event:
            self.name_input.setText(event.get("name", ""))

        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(42)
        self.color_btn.clicked.connect(self._choose_color)
        self._sync_color_button()

        self.channel_combo = QComboBox()
        for label, key in parent._event_channel_options(dataset):
            self.channel_combo.addItem(label, key)
        if event:
            index = self.channel_combo.findData(event.get("channel"))
            if index >= 0:
                self.channel_combo.setCurrentIndex(index)

        self.operator_combo = QComboBox()
        self.operator_combo.addItems([">=", ">", "<=", "<", "Min", "Max"])
        self.operator_combo.currentTextChanged.connect(self._sync_condition_fields)
        if event:
            index = self.operator_combo.findText(event.get("operator", ">="))
            if index >= 0:
                self.operator_combo.setCurrentIndex(index)

        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(-1000000.0, 1000000.0)
        self.value_spin.setDecimals(3)
        self.value_spin.setSingleStep(1.0)
        if event:
            self.value_spin.setValue(float(event.get("threshold", 0.0)))

        self.start_combo = QComboBox()
        self.start_combo.addItem("Start", {"type": "start"})
        self.start_combo.addItem("Frame", {"type": "frame"})
        self.start_combo.addItem("Time", {"type": "time"})
        for existing_event in dataset.get("events", []):
            self.start_combo.addItem(f"Event: {existing_event['name']}", {
                "type": "event", "name": existing_event["name"]
            })
        self.start_combo.currentIndexChanged.connect(self._sync_range_fields)

        self.end_combo = QComboBox()
        self.end_combo.addItem("End", {"type": "end"})
        self.end_combo.addItem("Frame", {"type": "frame"})
        self.end_combo.addItem("Time", {"type": "time"})
        for existing_event in dataset.get("events", []):
            self.end_combo.addItem(f"Event: {existing_event['name']}", {
                "type": "event", "name": existing_event["name"]
            })
        self.end_combo.currentIndexChanged.connect(self._sync_range_fields)

        self.start_frame_spin = QSpinBox()
        self.start_frame_spin.setRange(0, max(0, len(dataset["time"]) - 1))
        self.start_frame_spin.setValue(int(event.get("search_start_frame", 0)) if event else 0)
        self.end_frame_spin = QSpinBox()
        self.end_frame_spin.setRange(0, max(0, len(dataset["time"]) - 1))
        self.end_frame_spin.setValue(
            int(event.get("search_end_frame", max(0, len(dataset["time"]) - 1)))
            if event else max(0, len(dataset["time"]) - 1)
        )

        t_min = float(dataset["time"][0])
        t_max = float(dataset["time"][-1])
        self.start_time_spin = QDoubleSpinBox()
        self.start_time_spin.setRange(t_min, t_max)
        self.start_time_spin.setDecimals(3)
        self.start_time_spin.setValue(float(event.get("search_start_time", t_min)) if event else t_min)
        self.end_time_spin = QDoubleSpinBox()
        self.end_time_spin.setRange(t_min, t_max)
        self.end_time_spin.setDecimals(3)
        self.end_time_spin.setValue(float(event.get("search_end_time", t_max)) if event else t_max)

        form.addRow("Name", self.name_input)
        form.addRow("Color", self.color_btn)
        form.addRow("Data", self.channel_combo)
        form.addRow("Condition", self.operator_combo)
        form.addRow("Value", self.value_spin)
        form.addRow("Search start", self.start_combo)
        self.start_frame_label = QLabel("Start frame")
        form.addRow(self.start_frame_label, self.start_frame_spin)
        self.start_time_label = QLabel("Start time")
        form.addRow(self.start_time_label, self.start_time_spin)
        form.addRow("Search end", self.end_combo)
        self.end_frame_label = QLabel("End frame")
        form.addRow(self.end_frame_label, self.end_frame_spin)
        self.end_time_label = QLabel("End time")
        form.addRow(self.end_time_label, self.end_time_spin)
        vb.addLayout(form)

        if event:
            self._restore_endpoint(self.start_combo, event.get("search_start"))
            self._restore_endpoint(self.end_combo, event.get("search_end"))
        self._sync_range_fields()
        self._sync_condition_fields()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)

    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self.event_color), self, "Event color")
        if color.isValid():
            self.event_color = color.name()
            self._sync_color_button()

    def _sync_color_button(self):
        self.color_btn.setStyleSheet(
            f"background-color:{self.event_color};border:1px solid {BORDER};border-radius:4px;"
        )

    def values(self):
        return {
            "name": self.name_input.text().strip(),
            "color": self.event_color,
            "channel": self.channel_combo.currentData(),
            "operator": self.operator_combo.currentText(),
            "threshold": float(self.value_spin.value()),
            "search_start": self.start_combo.currentData(),
            "search_end": self.end_combo.currentData(),
            "search_start_frame": int(self.start_frame_spin.value()),
            "search_end_frame": int(self.end_frame_spin.value()),
            "search_start_time": float(self.start_time_spin.value()),
            "search_end_time": float(self.end_time_spin.value()),
        }

    def _restore_endpoint(self, combo, endpoint):
        if not endpoint:
            return
        for index in range(combo.count()):
            if combo.itemData(index) == endpoint:
                combo.setCurrentIndex(index)
                return

    def _sync_range_fields(self):
        start_type = self.start_combo.currentData().get("type")
        end_type = self.end_combo.currentData().get("type")
        self.start_frame_label.setVisible(start_type == "frame")
        self.start_frame_spin.setVisible(start_type == "frame")
        self.start_time_label.setVisible(start_type == "time")
        self.start_time_spin.setVisible(start_type == "time")
        self.end_frame_label.setVisible(end_type == "frame")
        self.end_frame_spin.setVisible(end_type == "frame")
        self.end_time_label.setVisible(end_type == "time")
        self.end_time_spin.setVisible(end_type == "time")

    def _sync_condition_fields(self):
        uses_threshold = self.operator_combo.currentText() not in ("Min", "Max")
        self.value_spin.setVisible(uses_threshold)


class AnalysisRangeDialog(QDialog):

    def __init__(self, parent, dataset, config=None):
        super().__init__(parent)
        self.dataset = dataset
        self.config = config or {}
        self.setWindowTitle("Edit Analysis" if config else "Add Analysis")
        self.setModal(True)
        self.setMinimumWidth(360)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Range name")
        self.name_input.setText(self.config.get("name", ""))

        self.start_combo = QComboBox()
        self.start_combo.addItem("Frame", {"type": "frame"})
        for event in dataset.get("events", []):
            self.start_combo.addItem(f"Event: {event['name']}", {
                "type": "event", "name": event["name"]
            })
        self.start_combo.currentIndexChanged.connect(self._sync_frame_fields)

        self.end_combo = QComboBox()
        self.end_combo.addItem("End", {"type": "end"})
        self.end_combo.addItem("Frame", {"type": "frame"})
        for event in dataset.get("events", []):
            self.end_combo.addItem(f"Event: {event['name']}", {
                "type": "event", "name": event["name"]
            })
        self.end_combo.currentIndexChanged.connect(self._sync_frame_fields)

        self.start_frame_spin = QSpinBox()
        self.start_frame_spin.setRange(0, max(0, len(dataset["time"]) - 1))
        self.start_frame_spin.setValue(int(self.config.get("start_frame", 0)))

        self.end_frame_spin = QSpinBox()
        self.end_frame_spin.setRange(0, max(0, len(dataset["time"]) - 1))
        self.end_frame_spin.setValue(int(self.config.get("end_frame", max(0, len(dataset["time"]) - 1))))

        form.addRow("Name", self.name_input)
        form.addRow("Start", self.start_combo)
        self.start_frame_label = QLabel("Start frame")
        form.addRow(self.start_frame_label, self.start_frame_spin)
        form.addRow("End", self.end_combo)
        self.end_frame_label = QLabel("End frame")
        form.addRow(self.end_frame_label, self.end_frame_spin)
        vb.addLayout(form)

        metrics_header = QHBoxLayout()
        metrics_header.addWidget(QLabel("Metrics"))
        metrics_header.addStretch()
        self.metrics_all_check = QCheckBox("All")
        self.metrics_all_check.setChecked(True)
        self.metrics_all_check.stateChanged.connect(self._toggle_all_metrics)
        metrics_header.addWidget(self.metrics_all_check)
        vb.addLayout(metrics_header)

        metrics_scroll = QScrollArea()
        metrics_scroll.setWidgetResizable(True)
        metrics_scroll.setFixedHeight(170)
        metrics_widget = QWidget()
        metrics_layout = QVBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(5)
        selected_metrics = set(self.config.get("metrics", METRIC_KEYS))
        self.metric_checks = {}
        for key in METRIC_KEYS:
            cb = QCheckBox(key)
            cb.setChecked(key in selected_metrics)
            cb.stateChanged.connect(self._sync_metrics_all_check)
            self.metric_checks[key] = cb
            metrics_layout.addWidget(cb)
        metrics_layout.addStretch()
        metrics_scroll.setWidget(metrics_widget)
        vb.addWidget(metrics_scroll)

        self._restore_endpoint(self.start_combo, self.config.get("start"))
        self._restore_endpoint(self.end_combo, self.config.get("end"))
        self._sync_frame_fields()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        self._sync_metrics_all_check()

    def _restore_endpoint(self, combo, endpoint):
        if not endpoint:
            return
        for index in range(combo.count()):
            data = combo.itemData(index)
            if data == endpoint:
                combo.setCurrentIndex(index)
                return

    def values(self):
        return {
            "name": self.name_input.text().strip(),
            "start": self.start_combo.currentData(),
            "end": self.end_combo.currentData(),
            "start_frame": int(self.start_frame_spin.value()),
            "end_frame": int(self.end_frame_spin.value()),
            "metrics": [
                key for key, cb in self.metric_checks.items()
                if cb.isChecked()
            ],
            "enabled": self.config.get("enabled", True),
        }

    def _sync_frame_fields(self):
        start_is_frame = self.start_combo.currentData().get("type") == "frame"
        end_is_frame = self.end_combo.currentData().get("type") == "frame"
        self.start_frame_label.setVisible(start_is_frame)
        self.start_frame_spin.setVisible(start_is_frame)
        self.end_frame_label.setVisible(end_is_frame)
        self.end_frame_spin.setVisible(end_is_frame)

    def _toggle_all_metrics(self, state):
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        for cb in self.metric_checks.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)

    def _sync_metrics_all_check(self):
        if not hasattr(self, "metrics_all_check"):
            return
        all_checked = all(cb.isChecked() for cb in self.metric_checks.values())
        self.metrics_all_check.blockSignals(True)
        self.metrics_all_check.setChecked(all_checked)
        self.metrics_all_check.blockSignals(False)


class ExportDialog(QDialog):

    def __init__(self, parent, dataset, configs):
        super().__init__(parent)
        self.parent_tab = parent
        self.dataset = dataset
        self.configs = [dict(config) for config in configs]
        self.setWindowTitle("Export Analysis")
        self.setModal(True)
        self.setMinimumWidth(460)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Range")
        self.add_btn.setObjectName("small-btn")
        self.add_btn.clicked.connect(self._add_range)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setObjectName("small-btn")
        self.edit_btn.clicked.connect(self._edit_range)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("small-btn")
        self.delete_btn.clicked.connect(self._delete_checked_ranges)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        vb.addLayout(btn_row)

        self.range_list = QListWidget()
        self.range_list.setMinimumHeight(210)
        self.range_list.itemChanged.connect(self._on_item_changed)
        self.range_list.itemDoubleClicked.connect(self._edit_range)
        vb.addWidget(self.range_list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)

        self._refresh_list()

    def _add_range(self):
        dialog = AnalysisRangeDialog(self.parent_tab, self.dataset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config = dialog.values()
        if not self._validate_config(config):
            return
        self.configs.append(config)
        self._refresh_list()

    def _edit_range(self, item=None):
        index = self._current_index(item)
        if index is None:
            return
        dialog = AnalysisRangeDialog(self.parent_tab, self.dataset, self.configs[index])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config = dialog.values()
        if not self._validate_config(config):
            return
        self.configs[index] = config
        self._refresh_list()

    def _delete_checked_ranges(self):
        kept = [config for config in self.configs if not config.get("enabled", True)]
        if len(kept) == len(self.configs):
            QMessageBox.information(self, "No ranges selected", "Check ranges before deleting.")
            return
        self.configs = kept
        self._refresh_list()

    def _validate_config(self, config):
        if not config["name"]:
            QMessageBox.information(self, "Range name", "Enter a range name.")
            return False
        if not config["metrics"]:
            QMessageBox.information(self, "No metrics", "Select at least one metric.")
            return False
        return True

    def _refresh_list(self):
        self.range_list.blockSignals(True)
        self.range_list.clear()
        for index, config in enumerate(self.configs):
            item = QListWidgetItem(self.parent_tab._range_label(config))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if config.get("enabled", True) else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(", ".join(config.get("metrics", [])))
            self.range_list.addItem(item)
        self.range_list.blockSignals(False)

    def _on_item_changed(self, item):
        index = self._current_index(item)
        if index is not None:
            self.configs[index]["enabled"] = item.checkState() == Qt.CheckState.Checked

    def _current_index(self, item=None):
        item = item or self.range_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return None
        index = int(index)
        if not 0 <= index < len(self.configs):
            return None
        return index

    def values(self):
        return [dict(config) for config in self.configs]


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
        painter.setBrush(QColor("#3A3A3A"))
        painter.drawRoundedRect(x0, y - 3, x1 - x0, 6, 3, 3)
        painter.setBrush(QColor(59, 130, 246, 160))
        painter.drawRoundedRect(xs, y - 4, max(1, xe - xs), 8, 4, 4)
        painter.setBrush(QColor("#E8E8E8"))
        painter.drawEllipse(xs - 6, y - 6, 12, 12)
        painter.drawEllipse(xe - 6, y - 6, 12, 12)
        painter.setBrush(QColor("#1D9E75"))
        painter.drawRect(xc - 1, y - 11, 2, 22)

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


class AnalyzeTab(QWidget):

    def __init__(self, axis_settings=None):
        super().__init__()
        self.axis_settings = axis_settings or AxisSettings()
        self.datasets = []
        self.current_index = None
        self.analysis_results = []
        self.summary_rows = []
        self.panel_checks = {}
        self.panel_visible = {}
        self.analysis_ranges = []
        self.review_region = None
        self.review_cursor_lines = []
        self.event_lines = []
        self.event_color = "#F97316"
        self.graph_expanded = True
        self.metrics_expanded = False
        self.events_expanded = False
        self.view_mode = "review"
        self.play_index = 0
        self._updating_range_slider = False
        self._build_ui()
        self._setup_playback()
        self._refresh_review_controls(None)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(5)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_main())
        splitter.setSizes([205, 1135])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setMinimumWidth(205)
        frame.setMaximumWidth(360)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        vb = QVBoxLayout(frame)
        vb.setContentsMargins(14, 16, 14, 14)
        vb.setSpacing(10)

        btn_row = QHBoxLayout()
        self.load_btn = QPushButton("Load")
        self.load_btn.setObjectName("load-btn")
        self.load_btn.clicked.connect(self._load_files)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("small-btn")
        self.load_btn.setFixedHeight(32)
        self.clear_btn.setFixedHeight(32)
        self.clear_btn.clicked.connect(self._clear_analysis)
        btn_row.addWidget(self.load_btn, 1)
        btn_row.addWidget(self.clear_btn, 1)
        vb.addLayout(btn_row)

        vb.addWidget(self._sep())
        self.graph_toggle_btn = QPushButton("Graph")
        self.graph_toggle_btn.setObjectName("small-btn")
        self.graph_toggle_btn.clicked.connect(self._toggle_graph_panel)
        vb.addWidget(self.graph_toggle_btn)

        self.graph_panel = QWidget()
        graph_panel_layout = QVBoxLayout(self.graph_panel)
        graph_panel_layout.setContentsMargins(0, 0, 0, 0)
        graph_panel_layout.setSpacing(5)
        for key, label in [
            ("traj", "COP Trajectory"),
            ("cop", "COP"),
            ("ap", "COP AP"),
            ("ml", "COP ML"),
            ("fx", "Force X"),
            ("fy", "Force Y"),
            ("fz", "Force Z"),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(key in ("traj", "cop", "ap", "ml"))
            cb.stateChanged.connect(self._rebuild_plot_layout)
            self.panel_checks[key] = cb
            self.panel_visible[key] = cb.isChecked()
            graph_panel_layout.addWidget(cb)
        vb.addWidget(self.graph_panel)

        vb.addWidget(self._sep())
        metrics_header = QHBoxLayout()
        self.metrics_toggle_btn = QPushButton("Metrics")
        self.metrics_toggle_btn.setObjectName("small-btn")
        self.metrics_toggle_btn.clicked.connect(self._toggle_metrics_panel)
        metrics_header.addWidget(self.metrics_toggle_btn, 1)
        self.metrics_all_check = QCheckBox("All")
        self.metrics_all_check.setChecked(True)
        self.metrics_all_check.stateChanged.connect(self._toggle_all_metrics)
        metrics_header.addWidget(self.metrics_all_check)
        vb.addLayout(metrics_header)

        self.metrics_panel = QWidget()
        metrics_panel_layout = QVBoxLayout(self.metrics_panel)
        metrics_panel_layout.setContentsMargins(0, 0, 0, 0)
        metrics_panel_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(96)
        cb_w = QWidget()
        cb_l = QVBoxLayout(cb_w)
        cb_l.setContentsMargins(0, 0, 0, 0)
        cb_l.setSpacing(5)

        self.metric_checks = {}
        for key in METRIC_KEYS:
            cb = QCheckBox(key)
            cb.setChecked(True)
            cb.stateChanged.connect(self._sync_metrics_all_check)
            self.metric_checks[key] = cb
            cb_l.addWidget(cb)
        cb_l.addStretch()
        scroll.setWidget(cb_w)
        metrics_panel_layout.addWidget(scroll)
        metrics_panel_layout.addSpacing(7)
        run_row = QHBoxLayout()
        self.run_btn = QPushButton("Run Analysis")
        self.run_btn.setObjectName("analysis-btn")
        self.run_btn.clicked.connect(self._run_analysis)
        self.run_btn.setFixedHeight(28)
        run_row.addWidget(self.run_btn, 1)
        metrics_panel_layout.addLayout(run_row)
        vb.addWidget(self.metrics_panel)

        vb.addWidget(self._sep())
        event_header = QHBoxLayout()
        self.events_toggle_btn = QPushButton("Event")
        self.events_toggle_btn.setObjectName("small-btn")
        self.events_toggle_btn.clicked.connect(self._toggle_events_panel)
        event_header.addWidget(self.events_toggle_btn, 1)
        self.add_event_btn = QPushButton("Add")
        self.add_event_btn.setObjectName("small-btn")
        self.add_event_btn.clicked.connect(self._add_event)
        self.delete_event_btn = QPushButton("Delete")
        self.delete_event_btn.setObjectName("small-btn")
        self.delete_event_btn.clicked.connect(self._delete_checked_events)
        event_header.addWidget(self.add_event_btn)
        event_header.addWidget(self.delete_event_btn)
        vb.addLayout(event_header)

        self.events_panel = QWidget()
        events_panel_layout = QVBoxLayout(self.events_panel)
        events_panel_layout.setContentsMargins(0, 0, 0, 0)
        events_panel_layout.setSpacing(5)
        self.event_list = QListWidget()
        self.event_list.setMinimumHeight(92)
        self.event_list.setMaximumHeight(180)
        self.event_list.itemChanged.connect(self._on_event_item_changed)
        self.event_list.itemDoubleClicked.connect(self._edit_event)
        events_panel_layout.addWidget(self.event_list)
        vb.addWidget(self.events_panel)

        self.export_btn = QPushButton("Export")
        self.export_btn.setObjectName("save-btn")
        self.export_btn.clicked.connect(self._save_results)
        vb.addStretch(1)
        vb.addWidget(self.export_btn)

        self._sync_collapsible_panels()
        self._refresh_event_controls(None)

        return frame

    def _build_main(self):
        widget = QWidget()
        vb = QVBoxLayout(widget)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)

        files_bar = QFrame()
        files_bar.setObjectName("statusbar")
        files_bar.setFixedHeight(82)
        files_layout = QVBoxLayout(files_bar)
        files_layout.setContentsMargins(12, 8, 12, 8)
        files_layout.setSpacing(6)

        self.file_lbl = QLabel("No files loaded")
        self.file_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:10px;")
        files_layout.addWidget(self.file_lbl)

        self.file_list = QListWidget()
        self.file_list.setFixedHeight(42)
        self.file_list.setFlow(QListView.Flow.LeftToRight)
        self.file_list.setWrapping(False)
        self.file_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list.itemClicked.connect(self._on_file_clicked)
        self.file_list.horizontalScrollBar().setSingleStep(24)
        QScroller.grabGesture(
            self.file_list.viewport(),
            QScroller.ScrollerGestureType.LeftMouseButtonGesture,
        )
        files_layout.addWidget(self.file_list)
        vb.addWidget(files_bar)

        range_bar = QFrame()
        range_bar.setObjectName("statusbar")
        range_bar.setFixedHeight(42)
        range_layout = QHBoxLayout(range_bar)
        range_layout.setContentsMargins(12, 4, 12, 4)
        range_layout.setSpacing(8)

        self.frame_lbl = QLabel("Frame -")
        self.frame_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")
        self.frame_slider = TimeRangeSlider()
        self.frame_slider.setEnabled(False)
        self.frame_slider.rangeChanged.connect(self._on_slider_range_changed)
        self.frame_slider.currentChanged.connect(self._set_review_time)
        self.full_range_btn = QPushButton("Full")
        self.full_range_btn.setObjectName("small-btn")
        self.full_range_btn.clicked.connect(self._set_current_full_range)
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("record-btn")
        self.play_btn.clicked.connect(self._toggle_playback)

        range_layout.addWidget(self.frame_lbl)
        range_layout.addWidget(self.frame_slider, 1)
        range_layout.addWidget(self.full_range_btn)
        range_layout.addWidget(self.play_btn)
        vb.addWidget(range_bar)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFixedHeight(118)
        self.cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.cards_scroll.setStyleSheet(f"background:{BG_DARK};border:none;")
        self.cards_scroll.horizontalScrollBar().setSingleStep(24)
        QScroller.grabGesture(
            self.cards_scroll.viewport(),
            QScroller.ScrollerGestureType.LeftMouseButtonGesture,
        )

        self.cards_widget = QWidget()
        self.cards_widget.setStyleSheet(f"background:{BG_DARK};")
        self.cards_hb = QHBoxLayout(self.cards_widget)
        self.cards_hb.setContentsMargins(12, 10, 12, 10)
        self.cards_hb.setSpacing(8)
        self._set_placeholder("Load files and run analysis")
        self.cards_scroll.setWidget(self.cards_widget)
        vb.addWidget(self.cards_scroll)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        vb.addWidget(sep)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(GRAPH_BG)
        vb.addWidget(self.glw, 1)

        self._setup_plots()
        return widget

    def _setup_playback(self):
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._playback_step)
        self.play_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.play_shortcut.activated.connect(self._toggle_playback)
        self.file_list.installEventFilter(self)
        self.file_list.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        file_list = getattr(self, "file_list", None)
        file_viewport = file_list.viewport() if file_list is not None else None
        if (
            watched in (file_list, file_viewport)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
        ):
            self._toggle_playback()
            return True
        return super().eventFilter(watched, event)

    def _setup_plots(self):
        self._rebuild_plot_layout()

    def _rebuild_plot_layout(self, *_args):
        if not hasattr(self, "glw"):
            return

        self.panel_visible = {
            key: cb.isChecked()
            for key, cb in self.panel_checks.items()
        }
        self.glw.clear()

        self.p_traj = None
        self.p_ap = None
        self.p_ml = None
        self.p_cop = None
        self.p_fx = None
        self.p_fy = None
        self.p_fz = None
        self.c_traj = None
        self.c_ellipse = None
        self.c_mean = None
        self.c_cop_raw = None
        self.c_cop_filt = None
        self.c_ap_raw = None
        self.c_ap_filt = None
        self.c_ml_raw = None
        self.c_ml_filt = None
        self.c_fx = None
        self.c_fy = None
        self.c_fz = None
        self.review_region = None
        self.review_cursor_lines = []
        self._clear_event_lines()

        selected = [
            key for key in ("traj", "cop", "ap", "ml", "fx", "fy", "fz")
            if self.panel_visible.get(key, True)
        ]
        if not selected:
            return

        has_traj = "traj" in selected
        time_plots = [key for key in ("cop", "ap", "ml", "fx", "fy", "fz") if key in selected]

        if has_traj:
            plot = self.glw.addPlot(row=0, col=0, rowspan=max(1, len(time_plots)), title="COP Trajectory - 95% Ellipse")
            plot.setLabel("left", "AP (mm)", color=GRAPH_FG, size="9pt")
            plot.setLabel("bottom", "ML (mm)", color=GRAPH_FG, size="9pt")
            plot.setAspectLocked(True)
            self.p_traj = plot
            self.c_traj = plot.plot(pen=pg.mkPen("#888880", width=1))
            self.c_ellipse = plot.plot(
                pen=pg.mkPen(C_ELL, width=2, style=Qt.PenStyle.DashLine)
            )
            self.c_mean = pg.ScatterPlotItem(
                size=10,
                symbol="+",
                brush=pg.mkBrush(ACCENT_TEAL),
                pen=pg.mkPen(ACCENT_TEAL, width=2),
            )
            plot.addItem(self.c_mean)
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.getAxis("left").setTextPen(pg.mkPen(GRAPH_FG))
            plot.getAxis("bottom").setTextPen(pg.mkPen(GRAPH_FG))

        for row, key in enumerate(time_plots):
            col = 1 if has_traj else 0
            if key == "cop":
                plot = self.glw.addPlot(row=row, col=col, title="COP")
                plot.setLabel("left", "COP (mm)", color=GRAPH_FG, size="9pt")
                self.p_cop = plot
                self.c_cop_raw = plot.plot(pen=pg.mkPen(C_COP, width=1))
                self.c_cop_filt = plot.plot(pen=pg.mkPen("#90CAF9", width=1.5))
                self._add_review_cursor(plot)
            elif key == "ap":
                plot = self.glw.addPlot(row=row, col=col, title="COP AP")
                plot.setLabel("left", "AP (mm)", color=GRAPH_FG, size="9pt")
                self.p_ap = plot
                self.c_ap_raw = plot.plot(pen=pg.mkPen(C_RAW, width=1))
                self.c_ap_filt = plot.plot(pen=pg.mkPen(C_FILT_AP, width=1.5))
                self._add_review_cursor(plot)
            elif key == "ml":
                plot = self.glw.addPlot(row=row, col=col, title="COP ML")
                plot.setLabel("left", "ML (mm)", color=GRAPH_FG, size="9pt")
                plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
                self.p_ml = plot
                self.c_ml_raw = plot.plot(pen=pg.mkPen(C_RAW, width=1))
                self.c_ml_filt = plot.plot(pen=pg.mkPen(C_FILT_ML, width=1.5))
                self._add_review_cursor(plot)
            elif key == "fx":
                plot = self.glw.addPlot(row=row, col=col, title="Force X")
                plot.setLabel("left", "Fx (N)", color=GRAPH_FG, size="9pt")
                self.p_fx = plot
                self.c_fx = plot.plot(pen=pg.mkPen(C_FX, width=1.2))
                self._add_review_cursor(plot)
            elif key == "fy":
                plot = self.glw.addPlot(row=row, col=col, title="Force Y")
                plot.setLabel("left", "Fy (N)", color=GRAPH_FG, size="9pt")
                self.p_fy = plot
                self.c_fy = plot.plot(pen=pg.mkPen(C_FY, width=1.2))
                self._add_review_cursor(plot)
            else:
                plot = self.glw.addPlot(row=row, col=col, title="Force Z")
                plot.setLabel("left", "Fz (N)", color=GRAPH_FG, size="9pt")
                plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
                self.p_fz = plot
                self.c_fz = plot.plot(pen=pg.mkPen(C_FZ, width=1.2))
                self._add_review_cursor(plot)

            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.getAxis("left").setTextPen(pg.mkPen(GRAPH_FG))
            plot.getAxis("bottom").setTextPen(pg.mkPen(GRAPH_FG))

        if self.p_ap is not None and self.p_ml is not None:
            self.p_ml.setXLink(self.p_ap)
        if self.p_cop is not None and self.p_ap is not None:
            self.p_ap.setXLink(self.p_cop)
        if self.p_cop is not None and self.p_ml is not None:
            self.p_ml.setXLink(self.p_cop)
        link_source = self.p_cop or self.p_ap or self.p_ml or self.p_fx or self.p_fy or self.p_fz
        for plot in (self.p_fx, self.p_fy, self.p_fz):
            if plot is not None and link_source is not None and plot is not link_source:
                plot.setXLink(link_source)

        dataset = self._current_dataset()
        if dataset is not None:
            if dataset.get("analysis") and self.view_mode == "analysis":
                self._show_analysis(dataset)
            else:
                self._plot_dataset(dataset)

    def _add_review_cursor(self, plot):
        line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(ACCENT_TEAL, width=1),
        )
        line.setVisible(False)
        plot.addItem(line)
        self.review_cursor_lines.append(line)

    def _toggle_all_metrics(self, state):
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        for cb in self.metric_checks.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)

    def _sync_metrics_all_check(self):
        all_checked = all(cb.isChecked() for cb in self.metric_checks.values())
        self.metrics_all_check.blockSignals(True)
        self.metrics_all_check.setChecked(all_checked)
        self.metrics_all_check.blockSignals(False)

    def _toggle_metrics_panel(self):
        self.metrics_expanded = not self.metrics_expanded
        self._sync_collapsible_panels()

    def _toggle_graph_panel(self):
        self.graph_expanded = not self.graph_expanded
        self._sync_collapsible_panels()

    def _toggle_events_panel(self):
        self.events_expanded = not self.events_expanded
        self._sync_collapsible_panels()

    def _sync_collapsible_panels(self):
        if hasattr(self, "graph_panel"):
            self.graph_panel.setVisible(self.graph_expanded)
            self.graph_toggle_btn.setText(("v " if self.graph_expanded else "> ") + "Graph")
        if hasattr(self, "metrics_panel"):
            self.metrics_panel.setVisible(self.metrics_expanded)
            self.metrics_toggle_btn.setText(("v " if self.metrics_expanded else "> ") + "Metrics")
            self.metrics_all_check.setVisible(self.metrics_expanded)
        if hasattr(self, "events_panel"):
            self.events_panel.setVisible(self.events_expanded)
            self.events_toggle_btn.setText(("v " if self.events_expanded else "> ") + "Event")

    def _load_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load files", "", "CSV Files (*.csv)"
        )
        if not paths:
            return

        loaded = 0
        errors = []
        for path in paths:
            if any(d["path"] == path for d in self.datasets):
                continue
            try:
                self.datasets.append(self._read_dataset(path))
                loaded += 1
            except Exception as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")

        self._refresh_file_list()
        if self.datasets and self.current_index is None:
            self.current_index = 0
            self.file_list.setCurrentRow(0)
            self._plot_dataset(self.datasets[0])
        self._refresh_event_controls(self._current_dataset())
        self._refresh_range_controls()

        self.file_lbl.setText(f"{len(self.datasets)} file(s) loaded")
        if errors:
            QMessageBox.warning(self, "Load errors", "\n".join(errors[:8]))
        elif loaded:
            QMessageBox.information(self, "Loaded", f"Loaded {loaded} file(s).")

    def _clear_analysis(self):
        self._stop_playback()
        self.datasets = []
        self.current_index = None
        self.analysis_results = []
        self.summary_rows = []
        self.analysis_ranges = []
        self.file_list.clear()
        self.file_lbl.setText("No files loaded")
        self.file_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:10px;")
        self._refresh_review_controls(None)
        self._refresh_event_controls(None)
        self._refresh_range_controls()
        self._clear_event_lines()
        self._set_placeholder("Load files and run analysis")
        self._rebuild_plot_layout()

    def _read_dataset(self, path):
        rows = []
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append(row)

        if not rows:
            raise ValueError("empty CSV")

        data = {
            "path": path,
            "name": os.path.splitext(os.path.basename(path))[0],
            "cop_ap": np.array([float(r["COP_AP"]) for r in rows]),
            "cop_ml": np.array([float(r["COP_ML"]) for r in rows]),
            "fz": np.array([float(r["Fz"]) for r in rows]),
            "time": np.array([float(r["time_s"]) for r in rows]),
            "fs": 1000.0,
            "analysis": None,
            "events": [],
        }
        for key, column in [("fx", "Fx"), ("fy", "Fy")]:
            if column in rows[0]:
                data[key] = np.array([float(r[column]) for r in rows])
        data["range_start"] = float(data["time"][0])
        data["range_end"] = float(data["time"][-1])

        if "fs" in rows[0] and rows[0]["fs"]:
            data["fs"] = float(rows[0]["fs"])
        else:
            dt = float(np.mean(np.diff(data["time"])))
            data["fs"] = 1.0 / dt if dt > 0 else 1000.0

        return data

    def _refresh_file_list(self):
        self.file_list.clear()
        for index, dataset in enumerate(self.datasets):
            item = QListWidgetItem(dataset["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(dataset["path"])
            self.file_list.addItem(item)
        self._highlight_current_file()

    def _checked_dataset_indexes(self):
        indexes = []
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                indexes.append(item.data(Qt.ItemDataRole.UserRole))
        return indexes

    def _current_dataset(self):
        if self.current_index is None:
            return None
        if not 0 <= self.current_index < len(self.datasets):
            return None
        return self.datasets[self.current_index]

    def _on_file_clicked(self, item):
        self._stop_playback()
        self.current_index = item.data(Qt.ItemDataRole.UserRole)
        dataset = self.datasets[self.current_index]
        self._highlight_current_file()
        self._refresh_event_controls(dataset)
        self._refresh_range_controls()
        if dataset.get("analysis"):
            self.view_mode = "analysis"
            self._show_analysis(dataset)
        else:
            self._plot_dataset(dataset)
            self._set_placeholder("Run analysis to see metrics")

    def _refresh_review_controls(self, dataset=None):
        if dataset is None:
            dataset = self._current_dataset()
        enabled = dataset is not None
        self.frame_slider.setEnabled(enabled)
        self.full_range_btn.setEnabled(enabled)
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(enabled)
        if not enabled:
            self.frame_lbl.setText("Frame -")
            self.frame_slider.setEnabled(False)
            return

        self.frame_slider.setEnabled(True)
        t_min = float(dataset["time"][0])
        t_max = float(dataset["time"][-1])
        self._updating_range_slider = True
        self.frame_slider.set_bounds(t_min, t_max)
        self.frame_slider.set_range(
            float(dataset.get("range_start", t_min)),
            float(dataset.get("range_end", t_max)),
            emit=False,
        )
        self.frame_slider.set_current(t_min, emit=False)
        self._updating_range_slider = False
        self._set_review_time(t_min)

    def _toggle_playback(self):
        dataset = self._current_dataset()
        if dataset is None or len(dataset["time"]) == 0:
            return
        if self.play_timer.isActive():
            self._stop_playback()
            return

        if self.view_mode != "review":
            self._plot_dataset(dataset)

        _, _, current_time = self.frame_slider.values()
        self.play_index = int(np.argmin(np.abs(dataset["time"] - float(current_time))))
        if self.play_index >= len(dataset["time"]) - 1:
            self.play_index = 0
            self.frame_slider.set_current(float(dataset["time"][0]))

        self.play_btn.setText("Stop")
        self.play_btn.setObjectName("record-btn-active")
        self.play_btn.style().unpolish(self.play_btn)
        self.play_btn.style().polish(self.play_btn)
        self._playback_step()
        self.play_timer.start(20)

    def _stop_playback(self):
        if hasattr(self, "play_timer") and self.play_timer.isActive():
            self.play_timer.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.setText("Play")
            self.play_btn.setObjectName("record-btn")
            self.play_btn.style().unpolish(self.play_btn)
            self.play_btn.style().polish(self.play_btn)

    def _playback_step(self):
        dataset = self._current_dataset()
        if dataset is None or len(dataset["time"]) == 0:
            self._stop_playback()
            return

        step = max(1, int(round(float(dataset.get("fs", 1000.0)) / 50.0)))
        self.play_index = min(len(dataset["time"]) - 1, self.play_index + step)
        self.frame_slider.set_current(float(dataset["time"][self.play_index]))

        if self.play_index >= len(dataset["time"]) - 1:
            self._stop_playback()

    def _on_slider_range_changed(self, start, end):
        dataset = self._current_dataset()
        if dataset is None or self._updating_range_slider:
            return
        self._apply_range_to_checked_files(start, end, include_current=True)
        self._update_cop_region(dataset)
        self._set_placeholder("Run analysis to see metrics")

    def _set_current_full_range(self):
        dataset = self._current_dataset()
        if dataset is None:
            return
        start = float(dataset["time"][0])
        end = float(dataset["time"][-1])
        self._apply_range_to_checked_files(start, end, include_current=True)
        self._plot_dataset(dataset)
        self._set_placeholder("Run analysis to see metrics")

    def _apply_range_to_checked_files(self, start, end, include_current=True):
        target_indexes = set(self._checked_dataset_indexes())
        if include_current and self.current_index is not None:
            target_indexes.add(self.current_index)
        for index in target_indexes:
            if not 0 <= index < len(self.datasets):
                continue
            target = self.datasets[index]
            t_min = float(target["time"][0])
            t_max = float(target["time"][-1])
            target["range_start"] = max(t_min, min(t_max, float(start)))
            target["range_end"] = max(t_min, min(t_max, float(end)))
            if target["range_end"] < target["range_start"]:
                target["range_start"], target["range_end"] = target["range_end"], target["range_start"]
            target["analysis"] = None

    def _plot_dataset(self, dataset):
        self.view_mode = "review"
        self._highlight_current_file()
        t = dataset["time"]
        ap = dataset["cop_ap"]
        ml = dataset["cop_ml"]
        if self.c_ap_raw is not None:
            self.c_ap_raw.setData(t, ap)
        if self.c_ml_raw is not None:
            self.c_ml_raw.setData(t, ml)
        cop = self._cop_series(ap, ml)
        if self.c_cop_raw is not None:
            self.c_cop_raw.setData(t, cop)
        if self.c_cop_filt is not None:
            self.c_cop_filt.setData([], [])
        if self.c_ap_filt is not None:
            self.c_ap_filt.setData([], [])
        if self.c_ml_filt is not None:
            self.c_ml_filt.setData([], [])
        if self.c_traj is not None:
            self.c_traj.setData(ml, ap)
        if self.c_ellipse is not None:
            self.c_ellipse.setData([], [])
        if self.c_mean is not None:
            self.c_mean.setData([], [])
        self._plot_force_series(dataset)
        self._show_cop_region(dataset)
        self._draw_events(dataset)
        self._refresh_event_list(dataset)
        self._refresh_review_controls(dataset)

    def _plot_force_series(self, dataset, start=None, end=None):
        t = dataset["time"]
        mask = None
        if start is not None and end is not None:
            mask = (t >= float(start)) & (t <= float(end))
            t = t[mask]
        for curve_name, data_key in [
            ("c_fx", "fx"),
            ("c_fy", "fy"),
            ("c_fz", "fz"),
        ]:
            curve = getattr(self, curve_name, None)
            if curve is None:
                continue
            if data_key in dataset:
                values = dataset[data_key][mask] if mask is not None else dataset[data_key]
                curve.setData(t, values)
            else:
                curve.setData([], [])

    def _show_cop_region(self, dataset):
        if self.review_region is not None:
            try:
                self.review_region.getViewBox().removeItem(self.review_region)
            except Exception:
                pass
            self.review_region = None

        plot = self.p_cop
        if plot is None:
            return

        t_min = float(dataset["time"][0])
        t_max = float(dataset["time"][-1])
        start = float(dataset.get("range_start", t_min))
        end = float(dataset.get("range_end", t_max))
        self.review_region = pg.LinearRegionItem(
            values=(start, end),
            orientation=pg.LinearRegionItem.Vertical,
            brush=pg.mkBrush(60, 130, 255, 55),
            pen=pg.mkPen("#3B82F6", width=1),
            movable=False,
        )
        self.review_region.setBounds((t_min, t_max))
        plot.addItem(self.review_region)

        for line in self.review_cursor_lines:
            line.setVisible(True)

    def _update_cop_region(self, dataset):
        if self.review_region is None:
            self._show_cop_region(dataset)
            return
        self.review_region.setRegion((
            float(dataset["range_start"]),
            float(dataset["range_end"]),
        ))

    def _hide_review_marks(self):
        if self.review_region is not None:
            try:
                self.review_region.getViewBox().removeItem(self.review_region)
            except Exception:
                pass
            self.review_region = None
        for line in self.review_cursor_lines:
            line.setVisible(False)

    def _set_review_time(self, value):
        dataset = self._current_dataset()
        if dataset is None:
            self.frame_lbl.setText("Frame -")
            return

        index = int(np.argmin(np.abs(dataset["time"] - float(value))))
        t = float(dataset["time"][index])
        for line in self.review_cursor_lines:
            line.setPos(t)
            line.setVisible(self.view_mode == "review")
        if self.c_mean is not None:
            self.c_mean.setData([float(dataset["cop_ml"][index])], [float(dataset["cop_ap"][index])])
        self.frame_lbl.setText(f"Frame {index + 1:,}/{len(dataset['time']):,}  {t:.2f}s")

    def _cop_series(self, ap, ml):
        ap = np.asarray(ap, dtype=float)
        ml = np.asarray(ml, dtype=float)
        return np.sqrt((ap - np.mean(ap)) ** 2 + (ml - np.mean(ml)) ** 2)

    def _run_analysis(self):
        if not self.datasets:
            QMessageBox.information(self, "No files", "Load files before analysis.")
            return

        checked_indexes = self._checked_dataset_indexes()
        if not checked_indexes:
            QMessageBox.information(self, "No files selected", "Check files to include in analysis.")
            return

        selected = [k for k, cb in self.metric_checks.items() if cb.isChecked()]
        if not selected:
            QMessageBox.information(self, "No metrics", "Select at least one metric.")
            return

        self.analysis_results = []
        for dataset in self.datasets:
            dataset["analysis"] = None

        errors = []
        for index in checked_indexes:
            dataset = self.datasets[index]
            try:
                analysis = self._analyze_dataset(dataset, selected)
                dataset["analysis"] = analysis
                self.analysis_results.append(analysis)
            except Exception as exc:
                errors.append(f"{dataset['name']}: {exc}")

        if not self.analysis_results:
            QMessageBox.warning(self, "Analysis failed", "\n".join(errors[:8]))
            return

        self.summary_rows = self._compute_summary_rows(self.analysis_results)

        if self.current_index not in checked_indexes:
            self.current_index = checked_indexes[0]
        self.file_list.setCurrentRow(self.current_index)
        self.view_mode = "analysis"
        self._show_analysis(self.datasets[self.current_index])
        if errors:
            QMessageBox.warning(self, "Some files skipped", "\n".join(errors[:8]))
        QMessageBox.information(self, "Analysis complete", f"Analyzed {len(self.analysis_results)} file(s).")

    def _analyze_dataset(self, dataset, selected):
        start = float(dataset.get("range_start", dataset["time"][0]))
        end = float(dataset.get("range_end", dataset["time"][-1]))
        return self._analyze_time_window(dataset, start, end, selected, "Selected range")

    def _analyze_dataset_range(self, dataset, config):
        start_index = self._resolve_range_endpoint(dataset, config["start"], config["start_frame"])
        end_index = self._resolve_range_endpoint(dataset, config["end"], config["end_frame"])
        if end_index < start_index:
            start_index, end_index = end_index, start_index
        start = float(dataset["time"][start_index])
        end = float(dataset["time"][end_index])
        return self._analyze_time_window(dataset, start, end, config["metrics"], config["name"])

    def _resolve_range_endpoint(self, dataset, endpoint, frame_value):
        endpoint_type = endpoint.get("type")
        if endpoint_type == "end":
            return len(dataset["time"]) - 1
        if endpoint_type == "frame":
            return max(0, min(int(frame_value), len(dataset["time"]) - 1))
        if endpoint_type == "event":
            event_name = endpoint.get("name")
            for event in dataset.get("events", []):
                if event.get("name") == event_name:
                    return max(0, min(int(event["index"]), len(dataset["time"]) - 1))
            raise ValueError(f"event not found: {event_name}")
        raise ValueError("invalid range endpoint")

    def _analyze_time_window(self, dataset, start, end, selected, range_name):
        mask = (dataset["time"] >= start) & (dataset["time"] <= end)
        if int(np.sum(mask)) < 2:
            raise ValueError("selected range has fewer than 2 samples")

        frame_indexes = np.flatnonzero(mask)
        ap_raw = dataset["cop_ap"][mask]
        ml_raw = dataset["cop_ml"][mask]
        t = dataset["time"][mask]
        fs = dataset["fs"]

        if self.axis_settings.filter_enabled:
            ap = apply_lowpass(
                ap_raw,
                self.axis_settings.filter_cutoff_hz,
                fs,
                self.axis_settings.filter_order,
                self.axis_settings.filter_type,
            )
            ml = apply_lowpass(
                ml_raw,
                self.axis_settings.filter_cutoff_hz,
                fs,
                self.axis_settings.filter_order,
                self.axis_settings.filter_type,
            )
        else:
            ap = ap_raw
            ml = ml_raw

        metrics = compute_metrics(ap, ml, fs, selected)
        enabled_events = [
            dict(event)
            for event in dataset.get("events", [])
            if event.get("enabled", True)
        ]
        return {
            "file": dataset["name"],
            "path": dataset["path"],
            "range": range_name,
            "fs": fs,
            "range_start": start,
            "range_end": end,
            "total_frame": int(len(dataset["time"])),
            "analyzed_frame": int(len(t)),
            "analyzed_frame_range": f"{int(frame_indexes[0]) + 1}-{int(frame_indexes[-1]) + 1}",
            "time": t,
            "ap_raw": ap_raw,
            "ml_raw": ml_raw,
            "ap_filtered": ap,
            "ml_filtered": ml,
            "metrics": metrics,
            "events": enabled_events,
        }

    def _show_analysis(self, dataset):
        analysis = dataset.get("analysis")
        if not analysis:
            self._plot_dataset(dataset)
            return
        self.view_mode = "analysis"
        self._highlight_current_file()
        self._hide_review_marks()

        t = analysis["time"]
        ap = analysis["ap_filtered"]
        ml = analysis["ml_filtered"]
        cop_raw = self._cop_series(analysis["ap_raw"], analysis["ml_raw"])
        cop = self._cop_series(ap, ml)

        if self.c_ap_raw is not None:
            self.c_ap_raw.setData(t, analysis["ap_raw"])
        if self.c_ml_raw is not None:
            self.c_ml_raw.setData(t, analysis["ml_raw"])
        if self.c_cop_raw is not None:
            self.c_cop_raw.setData(t, cop_raw)
        if self.axis_settings.filter_enabled and self.c_cop_filt is not None:
            self.c_cop_filt.setData(t, cop)
        elif self.c_cop_filt is not None:
            self.c_cop_filt.setData([], [])
        if self.axis_settings.filter_enabled and self.c_ap_filt is not None:
            self.c_ap_filt.setData(t, ap)
        elif self.c_ap_filt is not None:
            self.c_ap_filt.setData([], [])
        if self.axis_settings.filter_enabled and self.c_ml_filt is not None:
            self.c_ml_filt.setData(t, ml)
        elif self.c_ml_filt is not None:
            self.c_ml_filt.setData([], [])

        if self.c_traj is not None:
            self.c_traj.setData(ml, ap)
        if self.c_ellipse is not None:
            self.c_ellipse.setData([], [])
        if self.c_mean is not None:
            self.c_mean.setData([], [])
        if len(ap) > 10:
            try:
                ell_ml, ell_ap = compute_ellipse_points(ap, ml)
                if self.c_ellipse is not None:
                    self.c_ellipse.setData(ell_ml, ell_ap)
                if self.c_mean is not None:
                    self.c_mean.setData([float(np.mean(ml))], [float(np.mean(ap))])
            except Exception:
                pass

        self._plot_force_series(dataset, analysis["range_start"], analysis["range_end"])
        self._draw_events(dataset)
        self._refresh_event_list(dataset)
        self._update_cards(analysis["metrics"])

    def _refresh_event_controls(self, dataset=None):
        enabled = dataset is not None
        for widget in [
            getattr(self, "add_event_btn", None),
            getattr(self, "delete_event_btn", None),
        ]:
            if widget is not None:
                widget.setEnabled(enabled)
        self._refresh_event_list(dataset)

    def _refresh_range_controls(self):
        enabled = self._current_dataset() is not None
        for widget in [
            getattr(self, "add_range_btn", None),
            getattr(self, "delete_range_btn", None),
        ]:
            if widget is not None:
                widget.setEnabled(enabled)
        self._refresh_range_list()

    def _event_channel_options(self, dataset):
        options = [
            ("Time (s)", "time"),
            ("COP", "cop"),
            ("COP AP", "cop_ap"),
            ("COP ML", "cop_ml"),
            ("Fz", "fz"),
        ]
        if "fx" in dataset:
            options.append(("Fx", "fx"))
        if "fy" in dataset:
            options.append(("Fy", "fy"))
        return options

    def _add_event(self):
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "No file", "Load a file before adding events.")
            return

        target_indexes = self._checked_dataset_indexes()
        if not target_indexes:
            QMessageBox.information(self, "No files selected", "Check files before adding events.")
            return

        dialog = EventDialog(self, dataset, self.event_color)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.event_color = values["color"]

        if not values["name"]:
            QMessageBox.information(self, "Event name", "Enter an event name.")
            return

        if not values["channel"]:
            QMessageBox.information(self, "Event channel", "Select an event channel.")
            return

        added = 0
        errors = []
        for index in target_indexes:
            target = self.datasets[index]
            try:
                event = self._detect_event(
                    target,
                    name=values["name"],
                    color=values["color"],
                    channel=values["channel"],
                    operator_text=values["operator"],
                    threshold=values["threshold"],
                    search_start=values["search_start"],
                    search_end=values["search_end"],
                    search_start_frame=values["search_start_frame"],
                    search_end_frame=values["search_end_frame"],
                    search_start_time=values["search_start_time"],
                    search_end_time=values["search_end_time"],
                )
            except ValueError as exc:
                errors.append(f"{target['name']}: {exc}")
                continue

            target.setdefault("events", []).append(event)
            target["events"].sort(key=lambda item: item["time"])
            target["analysis"] = None
            added += 1

        self._draw_events(dataset)
        self._refresh_event_list(dataset)
        if errors:
            QMessageBox.warning(
                self,
                "Some events not found",
                f"Added event to {added} file(s).\n\n" + "\n".join(errors[:8]),
            )
        elif added:
            QMessageBox.information(self, "Event added", f"Added event to {added} file(s).")

    def _edit_event(self, item):
        dataset = self._current_dataset()
        if dataset is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        events = dataset.get("events", [])
        index = int(index)
        if not 0 <= index < len(events):
            return

        current_event = events[index]
        dialog = EventDialog(self, dataset, self.event_color, current_event)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.event_color = values["color"]

        if not values["name"]:
            QMessageBox.information(self, "Event name", "Enter an event name.")
            return

        try:
            updated_event = self._detect_event(
                dataset,
                name=values["name"],
                color=values["color"],
                channel=values["channel"],
                operator_text=values["operator"],
                threshold=values["threshold"],
                search_start=values["search_start"],
                search_end=values["search_end"],
                search_start_frame=values["search_start_frame"],
                search_end_frame=values["search_end_frame"],
                search_start_time=values["search_start_time"],
                search_end_time=values["search_end_time"],
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Event not found", str(exc))
            return

        updated_event["enabled"] = current_event.get("enabled", True)
        events[index] = updated_event
        events.sort(key=lambda event: event["time"])
        self._draw_events(dataset)
        self._refresh_event_list(dataset)

    def _detect_event(
        self,
        dataset,
        name,
        color,
        channel,
        operator_text,
        threshold,
        search_start=None,
        search_end=None,
        search_start_frame=0,
        search_end_frame=0,
        search_start_time=None,
        search_end_time=None,
    ):
        time_values = np.asarray(dataset["time"], dtype=float)
        start_index = self._resolve_event_search_endpoint(
            dataset,
            search_start or {"type": "start"},
            search_start_frame,
            search_start_time,
        )
        end_index = self._resolve_event_search_endpoint(
            dataset,
            search_end or {"type": "end"},
            search_end_frame,
            search_end_time,
        )
        if end_index < start_index:
            start_index, end_index = end_index, start_index
        scope_mask = np.zeros(len(time_values), dtype=bool)
        scope_mask[start_index:end_index + 1] = True

        if channel == "time":
            scoped_indexes = np.flatnonzero(scope_mask)
            if len(scoped_indexes) == 0:
                raise ValueError("selected range is empty")
            if operator_text == "Min":
                local = 0
            elif operator_text == "Max":
                local = len(scoped_indexes) - 1
            else:
                local = int(np.argmin(np.abs(time_values[scoped_indexes] - threshold)))
            index = int(scoped_indexes[local])
            value = float(time_values[index])
            rule = f"time {operator_text}" if operator_text in ("Min", "Max") else f"time = {threshold:g}s"
        else:
            values = self._series_for_event_channel(dataset, channel)
            scoped_indexes = np.flatnonzero(scope_mask)
            if len(scoped_indexes) == 0:
                raise ValueError("selected range is empty")
            if operator_text == "Min":
                local = int(np.argmin(values[scoped_indexes]))
                index = int(scoped_indexes[local])
            elif operator_text == "Max":
                local = int(np.argmax(values[scoped_indexes]))
                index = int(scoped_indexes[local])
            else:
                if operator_text == ">=":
                    mask = values >= threshold
                elif operator_text == ">":
                    mask = values > threshold
                elif operator_text == "<=":
                    mask = values <= threshold
                else:
                    mask = values < threshold
                indexes = np.flatnonzero(mask & scope_mask)
                if len(indexes) == 0:
                    label = self._event_channel_label(dataset, channel)
                    raise ValueError(f"No sample matches {label} {operator_text} {threshold:g}.")
                index = int(indexes[0])
            value = float(values[index])
            if operator_text in ("Min", "Max"):
                rule = f"{self._event_channel_label(dataset, channel)} {operator_text}"
            else:
                rule = f"{self._event_channel_label(dataset, channel)} {operator_text} {threshold:g}"

        return {
            "name": name,
            "color": color,
            "channel": channel,
            "operator": operator_text,
            "threshold": float(threshold),
            "frame": int(index + 1),
            "index": int(index),
            "time": float(time_values[index]),
            "value": value,
            "rule": rule,
            "scope": self._event_search_label(search_start or {"type": "start"}, search_end or {"type": "end"}),
            "search_start": search_start or {"type": "start"},
            "search_end": search_end or {"type": "end"},
            "search_start_frame": int(search_start_frame),
            "search_end_frame": int(search_end_frame),
            "search_start_time": float(search_start_time if search_start_time is not None else time_values[0]),
            "search_end_time": float(search_end_time if search_end_time is not None else time_values[-1]),
            "enabled": True,
        }

    def _resolve_event_search_endpoint(self, dataset, endpoint, frame_value, time_value):
        endpoint_type = endpoint.get("type")
        if endpoint_type == "start":
            return 0
        if endpoint_type == "end":
            return len(dataset["time"]) - 1
        if endpoint_type == "frame":
            return max(0, min(int(frame_value), len(dataset["time"]) - 1))
        if endpoint_type == "time":
            return int(np.argmin(np.abs(dataset["time"] - float(time_value))))
        if endpoint_type == "event":
            event_name = endpoint.get("name")
            for event in dataset.get("events", []):
                if event.get("name") == event_name:
                    return max(0, min(int(event["index"]), len(dataset["time"]) - 1))
            raise ValueError(f"event not found: {event_name}")
        raise ValueError("invalid event search endpoint")

    def _event_search_label(self, start, end):
        return f"{self._event_endpoint_label(start)}-{self._event_endpoint_label(end)}"

    def _event_endpoint_label(self, endpoint):
        endpoint_type = endpoint.get("type")
        if endpoint_type in ("start", "end"):
            return endpoint_type
        if endpoint_type == "event":
            return endpoint.get("name", "event")
        return endpoint_type

    def _series_for_event_channel(self, dataset, channel):
        if channel == "cop":
            return self._cop_series(dataset["cop_ap"], dataset["cop_ml"])
        if channel in dataset:
            return np.asarray(dataset[channel], dtype=float)
        raise ValueError(f"channel unavailable: {channel}")

    def _event_channel_label(self, dataset, channel):
        for label, key in self._event_channel_options(dataset):
            if key == channel:
                return label
        return channel

    def _time_plots(self):
        return [
            p for p in [
                self.p_cop, self.p_ap, self.p_ml,
                self.p_fx, self.p_fy, self.p_fz,
            ]
            if p is not None
        ]

    def _clear_event_lines(self):
        for line in self.event_lines:
            try:
                line.getViewBox().removeItem(line)
            except Exception:
                pass
        self.event_lines = []

    def _draw_events(self, dataset):
        self._clear_event_lines()
        if dataset is None:
            return
        for event in dataset.get("events", []):
            if not event.get("enabled", True):
                continue
            for plot in self._time_plots():
                line = pg.InfiniteLine(
                    pos=float(event["time"]),
                    angle=90,
                    movable=False,
                    pen=pg.mkPen(event.get("color", "#F97316"), width=2),
                )
                line.setZValue(20)
                try:
                    line.setToolTip(
                        f"{event['name']}\nFrame {event['frame']}\n{event['time']:.3f}s"
                    )
                except Exception:
                    pass
                plot.addItem(line)
                self.event_lines.append(line)

    def _refresh_event_list(self, dataset=None):
        if not hasattr(self, "event_list"):
            return
        self.event_list.blockSignals(True)
        self.event_list.clear()
        if dataset is None:
            self.event_list.blockSignals(False)
            return
        for index, event in enumerate(dataset.get("events", [])):
            item = QListWidgetItem(
                f"{event['name']}  F{event['frame']}  {event['time']:.2f}s"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if event.get("enabled", True) else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setForeground(QBrush(QColor(event.get("color", TEXT_PRIMARY))))
            item.setToolTip(event.get("rule", ""))
            self.event_list.addItem(item)
        self.event_list.blockSignals(False)

    def _on_event_item_changed(self, item):
        dataset = self._current_dataset()
        if dataset is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        events = dataset.get("events", [])
        if 0 <= int(index) < len(events):
            events[int(index)]["enabled"] = item.checkState() == Qt.CheckState.Checked
            self._draw_events(dataset)

    def _delete_checked_events(self):
        dataset = self._current_dataset()
        if dataset is None:
            return
        events = dataset.get("events", [])
        kept = [event for event in events if not event.get("enabled", True)]
        if len(kept) == len(events):
            QMessageBox.information(self, "No events selected", "Check events before deleting.")
            return
        dataset["events"] = kept
        self._draw_events(dataset)
        self._refresh_event_list(dataset)

    def _add_analysis_range(self):
        dataset = self._current_dataset()
        if dataset is None:
            QMessageBox.information(self, "No file", "Load a file before adding analysis ranges.")
            return
        dialog = AnalysisRangeDialog(self, dataset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config = dialog.values()
        if not config["name"]:
            QMessageBox.information(self, "Range name", "Enter a range name.")
            return
        if not config["metrics"]:
            QMessageBox.information(self, "No metrics", "Select at least one metric.")
            return
        self.analysis_ranges.append(config)
        self._refresh_range_list()

    def _edit_analysis_range(self, item):
        dataset = self._current_dataset()
        if dataset is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        index = int(index)
        if not 0 <= index < len(self.analysis_ranges):
            return
        current = self.analysis_ranges[index]
        dialog = AnalysisRangeDialog(self, dataset, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config = dialog.values()
        if not config["name"]:
            QMessageBox.information(self, "Range name", "Enter a range name.")
            return
        if not config["metrics"]:
            QMessageBox.information(self, "No metrics", "Select at least one metric.")
            return
        self.analysis_ranges[index] = config
        self._refresh_range_list()

    def _refresh_range_list(self):
        if not hasattr(self, "range_list"):
            return
        self.range_list.blockSignals(True)
        self.range_list.clear()
        for index, config in enumerate(self.analysis_ranges):
            item = QListWidgetItem(self._range_label(config))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if config.get("enabled", True) else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(", ".join(config.get("metrics", [])))
            self.range_list.addItem(item)
        self.range_list.blockSignals(False)

    def _range_label(self, config):
        return f"{config['name']}  {self._endpoint_label(config['start'], config['start_frame'])}-{self._endpoint_label(config['end'], config['end_frame'])}"

    def _endpoint_label(self, endpoint, frame):
        if endpoint.get("type") == "event":
            return endpoint.get("name", "Event")
        if endpoint.get("type") == "end":
            return "End"
        return f"F{int(frame)}"

    def _on_range_item_changed(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        index = int(index)
        if 0 <= index < len(self.analysis_ranges):
            self.analysis_ranges[index]["enabled"] = item.checkState() == Qt.CheckState.Checked

    def _delete_checked_ranges(self):
        kept = [config for config in self.analysis_ranges if not config.get("enabled", True)]
        if len(kept) == len(self.analysis_ranges):
            QMessageBox.information(self, "No ranges selected", "Check ranges before deleting.")
            return
        self.analysis_ranges = kept
        self._refresh_range_list()

    def _save_events(self):
        dataset = self._current_dataset()
        if dataset is None or not dataset.get("events"):
            QMessageBox.information(self, "No events", "Add events before saving.")
            return

        default_name = f"{dataset['name']}_events.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save events", default_name, "CSV Files (*.csv)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        fields = [
            "file", "name", "color", "frame", "time_s", "channel",
            "operator", "threshold", "value", "scope", "rule",
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for event in dataset.get("events", []):
                if not event.get("enabled", True):
                    continue
                writer.writerow({
                    "file": dataset["name"],
                    "name": event["name"],
                    "color": event["color"],
                    "frame": event["frame"],
                    "time_s": event["time"],
                    "channel": event["channel"],
                    "operator": event["operator"],
                    "threshold": event["threshold"],
                    "value": event["value"],
                    "scope": event["scope"],
                    "rule": event["rule"],
                })
        QMessageBox.information(self, "Saved", f"Saved events:\n{path}")

    def _compute_summary_rows(self, results):
        grouped = {}
        for result in results:
            for metric, (value, unit) in result["metrics"].items():
                grouped.setdefault((result.get("range", ""), metric, unit), []).append(float(value))

        rows = []
        for (range_name, metric, unit), values in sorted(grouped.items()):
            arr = np.array(values, dtype=float)
            rows.append({
                "range": range_name,
                "variable": metric,
                "n": int(len(arr)),
                "mean": float(np.mean(arr)),
                "sd": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
                "se": float(np.std(arr, ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0,
                "unit": unit,
            })
        return rows

    def _save_results(self):
        if not self.datasets:
            QMessageBox.information(self, "No files", "Load files before export.")
            return
        checked_indexes = self._checked_dataset_indexes()
        if not checked_indexes:
            QMessageBox.information(self, "No files selected", "Check analyzed files to save.")
            return

        dataset = self._current_dataset() or self.datasets[checked_indexes[0]]
        dialog = ExportDialog(self, dataset, self.analysis_ranges)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.analysis_ranges = dialog.values()
        active_ranges = [
            config for config in self.analysis_ranges
            if config.get("enabled", True)
        ]
        if not active_ranges:
            QMessageBox.information(self, "No ranges", "Add or check at least one export range.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save results", "analysis_results.xlsx", "Excel Files (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        export_results = []
        errors = []
        for index in checked_indexes:
            target = self.datasets[index]
            for config in active_ranges:
                try:
                    export_results.append(self._analyze_dataset_range(target, config))
                except Exception as exc:
                    errors.append(f"{target['name']} / {config['name']}: {exc}")
        if not export_results:
            QMessageBox.warning(self, "Export failed", "\n".join(errors[:8]))
            return

        summary_rows = self._compute_summary_rows(export_results)
        try:
            self._write_results_workbook(path, export_results, summary_rows)
        except ModuleNotFoundError:
            QMessageBox.critical(
                self,
                "Missing package",
                "openpyxl is required to save Excel files.\nRun setup_dev.bat again.",
            )
            return
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Saved",
            f"Saved results:\n{path}",
        )
        if errors:
            QMessageBox.warning(self, "Some ranges skipped", "\n".join(errors[:8]))

    def _checked_analysis_results(self):
        checked_paths = set()
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                index = item.data(Qt.ItemDataRole.UserRole)
                checked_paths.add(self.datasets[index]["path"])
        return [
            result for result in self.analysis_results
            if result["path"] in checked_paths
        ]

    def _write_results_workbook(self, path, results, summary_rows):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        wb = Workbook()
        ws_files = wb.active
        ws_files.title = "included_files"
        ws_stats = wb.create_sheet("descriptive_statistics")
        ws_results = wb.create_sheet("analysis_results")
        ws_events = wb.create_sheet("events")

        ws_files.append(["file", "total frame", "analyzed frame"])
        for result in results:
            ws_files.append([
                result["file"],
                result["total_frame"],
                result["analyzed_frame_range"],
            ])

        ws_stats.append(["range", "variable", "mean", "sd", "se", "unit"])
        for row in summary_rows:
            ws_stats.append([
                row["range"],
                row["variable"],
                row["mean"],
                row["sd"],
                row["se"],
                row["unit"],
            ])

        ws_results.append(["file", "range", "metric", "value", "unit"])
        for result in results:
            for metric, (value, unit) in result["metrics"].items():
                ws_results.append([
                    result["file"],
                    result.get("range", ""),
                    metric,
                    float(value),
                    unit,
                ])

        ws_events.append(["file", "event", "frame"])
        written_events = set()
        for result in results:
            for event in result.get("events", []):
                key = (result["file"], event["name"], event["frame"])
                if key in written_events:
                    continue
                written_events.add(key)
                ws_events.append([result["file"], event["name"], event["frame"]])

        header_fill = PatternFill("solid", fgColor="D9EAF7")
        for ws in (ws_files, ws_stats, ws_results, ws_events):
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = header_fill
            ws.freeze_panes = "A2"
            for column in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in column)
                ws.column_dimensions[column[0].column_letter].width = min(max(max_len + 2, 12), 36)

        wb.save(path)

    def _set_placeholder(self, text):
        self._clear_cards()
        ph = QLabel(text)
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:12px;")
        self.cards_hb.addWidget(ph)
        self.cards_hb.addStretch()

    def _highlight_current_file(self):
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            is_current = item.data(Qt.ItemDataRole.UserRole) == self.current_index
            item.setForeground(QBrush(QColor(ACCENT_TEAL if is_current else TEXT_PRIMARY)))

    def _update_cards(self, results):
        self._clear_cards()
        if not results:
            self._set_placeholder("No metrics selected")
            return
        for key, (value, unit) in results.items():
            self.cards_hb.addWidget(self._make_card(key, value, unit))
        self.cards_hb.addStretch()

    def _clear_cards(self):
        while self.cards_hb.count():
            item = self.cards_hb.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _make_card(self, name, value, unit):
        card = QFrame()
        card.setObjectName("metric-card")
        card.setFixedSize(128, 92)

        vb = QVBoxLayout(card)
        vb.setContentsMargins(10, 8, 10, 6)
        vb.setSpacing(1)

        n_lbl = QLabel(name)
        n_lbl.setWordWrap(True)
        n_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:10px;")
        v_lbl = QLabel(self._fmt(value))
        v_lbl.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:22px;font-weight:500;")
        u_lbl = QLabel(unit)
        u_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")

        vb.addWidget(n_lbl)
        vb.addWidget(v_lbl)
        vb.addWidget(u_lbl)
        return card

    def _fmt(self, value):
        value = float(value)
        if abs(value) >= 10000:
            return f"{value:.0f}"
        if abs(value) >= 100:
            return f"{value:.1f}"
        if abs(value) >= 1:
            return f"{value:.2f}"
        return f"{value:.3f}"

    def _sec(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("section-label")
        return lbl

    def _sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        return sep
