import os
import csv
import io
import queue
import threading
import time
from collections import deque
from enum import Enum, auto
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox,
    QFileDialog, QStackedWidget, QSplitter, QSizePolicy, QScrollArea,
    QCheckBox, QMessageBox, QSlider,
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction

from core.axis_settings import AxisSettings
from core import qtm_client
from ui.style import (
    ACCENT_TEAL, ACCENT_RED, TEXT_PRIMARY, TEXT_SECONDARY,
    BORDER, GRAPH_BG, GRAPH_FG, BG_PANEL, BG_MID, BG_INPUT,
    SPACING_SM, SPACING_MD, SPACING_LG, BORDER_RADIUS_LG,
    FONT_SIZE_LARGE, FONT_SIZE_SMALL, FONT_WEIGHT_SEMI, TEXT_MUTED,
)
from ui.components import MetricCardWidget
from ui import style as S

BUFFER_SIZE = 10000

C_FZ    = "#1D9E75"
C_FX    = "#D86A3A"
C_FY    = "#3B8FD9"
C_AP    = "#7F77DD"
C_ML    = "#D4537E"
C_TRAJ  = "#AAAAAA"
C_DOT   = "#FFFF00"


class State(Enum):
    IDLE      = auto()
    RECORDING = auto()
    REVIEW    = auto()


class _LiveStat:
    """Lightweight stand-in for the old metric cards: pushes a value into an
    optional QLabel (or silently ignores it when there is no label)."""

    def __init__(self, label=None, template="{v}"):
        self._label = label
        self._template = template

    def setValue(self, value, unit=""):
        if self._label is not None:
            self._label.setText(self._template.format(v=value, u=unit).strip())


class CollectTab(QWidget):

    _qtm_signal = pyqtSignal(str)

    def __init__(self, qtm_ip: str = "127.0.0.1", axis_settings=None):
        super().__init__()
        self.qtm_ip       = qtm_ip
        self.axis_settings = axis_settings or AxisSettings()
        self.state        = State.IDLE
        self.data_queue   = queue.Queue(maxsize=100000)
        self.qtm_thread   = None

        self.sample_count = 0
        self.t_buf   = deque(maxlen=BUFFER_SIZE)
        self.fx_buf  = deque(maxlen=BUFFER_SIZE)
        self.fy_buf  = deque(maxlen=BUFFER_SIZE)
        self.fz_buf  = deque(maxlen=BUFFER_SIZE)
        self.ap_buf  = deque(maxlen=BUFFER_SIZE)
        self.ml_buf  = deque(maxlen=BUFFER_SIZE)

        self.rec_data   = []
        self.rec_count  = 0
        self.rec_target = 0
        self.rec_duration_s = 0.0
        self.rec_started_at = None
        self.rec_fs = 1000
        self.play_index = 0
        self.review_cursor_lines = []

        self.fs_estimate    = 1000
        self._fs_last_time  = None
        self._fs_last_count = 0

        self._auto_reconnect = False   # True after first Connect attempt
        self.panel_checks = {}
        self.panel_visible = {}

        self.save_dir = os.path.join(
            os.path.expanduser("~"), "Documents", "Balancelab", "data"
        )
        os.makedirs(self.save_dir, exist_ok=True)

        self._build_ui()
        # Live readouts (sampling rate / samples) now live in the sidebar;
        # status/Fz no longer have a card, so they route to a no-op stand-in.
        self.stat_fs = _LiveStat(self._fs_lbl, "Sampling rate:  {v} {u}")
        self.stat_samples = _LiveStat(self._samples_lbl, "Samples:  {v}")
        self.stat_status = _LiveStat(None)
        self.stat_fz = _LiveStat(None)
        self._update_record_controls()
        self._setup_plots()
        self._setup_timer()
        self._setup_shortcuts()
        self._qtm_signal.connect(self._on_qtm_status)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main_area(), 1)

    def _build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(360)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        vb = QVBoxLayout(frame)
        vb.setContentsMargins(8, 8, 8, 8)
        vb.setSpacing(4)

        # Accordion: sections stacked in a scroll area. Collapsing a section
        # reclaims its space and everything below slides up.
        scroll = QScrollArea()
        scroll.setObjectName("sidebar-scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        # --- Connection ---
        conn = QWidget()
        cl = QVBoxLayout(conn)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        ip_row = QHBoxLayout()
        ip_row.setSpacing(4)
        self.ip_input = QLineEdit(self.qtm_ip)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("small-btn")
        self.connect_btn.setFixedHeight(22)
        self.connect_btn.clicked.connect(self._connect_qtm)
        ip_row.addWidget(self.ip_input)
        ip_row.addWidget(self.connect_btn)
        cl.addLayout(ip_row)
        self.qtm_status_lbl = QLabel("Disconnected")
        self.qtm_status_lbl.setStyleSheet(
            f"color: {ACCENT_RED}; font-size: {FONT_SIZE_SMALL};"
        )
        self.qtm_status_lbl.setWordWrap(True)
        cl.addWidget(self.qtm_status_lbl)
        cl.addStretch()
        col.addWidget(self._make_section("Connection", conn, expanded=True))
        col.addWidget(self._hsep())

        # --- Recording ---
        rec = QWidget()
        rl = QVBoxLayout(rec)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        dur_label = QLabel("Duration (seconds)")
        dur_label.setObjectName("field-label")
        rl.addWidget(dur_label)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1, 600)
        self.duration_spin.setValue(30)
        self.duration_spin.setSingleStep(5)
        rl.addWidget(self.duration_spin)
        self._fs_lbl = QLabel("Sampling rate:  – Hz")
        self._fs_lbl.setObjectName("field-label")
        rl.addWidget(self._fs_lbl)
        self._samples_lbl = QLabel("Samples:  –")
        self._samples_lbl.setObjectName("field-label")
        rl.addWidget(self._samples_lbl)
        rl.addStretch()
        col.addWidget(self._make_section("Recording", rec, expanded=False))
        col.addWidget(self._hsep())

        # --- Graph ---
        panels_container = QWidget()
        panels_layout = QVBoxLayout(panels_container)
        panels_layout.setContentsMargins(0, 0, 0, 0)
        panels_layout.setSpacing(2)
        for key, label in [
            ("fx", "Force X"),
            ("fy", "Force Y"),
            ("fz", "Force Z"),
            ("traj", "COP Trajectory"),
            ("ap", "COP AP"),
            ("ml", "COP ML"),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(self._rebuild_plot_layout)
            self.panel_checks[key] = cb
            self.panel_visible[key] = True
            panels_layout.addWidget(cb)
        panels_layout.addStretch()
        col.addWidget(self._make_section("Graph", panels_container, expanded=False))

        col.addStretch(1)
        scroll.setWidget(inner)
        vb.addWidget(scroll, 1)

        # Save / Clear appear only after a recording (review state). The primary
        # Record / Stop control lives in the bottom bar.
        actions = QHBoxLayout()
        actions.setSpacing(2)
        self.save_btn = QPushButton("S")
        self.save_btn.setObjectName("save-btn")
        self.save_btn.setFixedSize(24, 22)
        self.save_btn.setToolTip("Save recording")
        self.save_btn.clicked.connect(self._save_data)
        self.clear_btn = QPushButton("X")
        self.clear_btn.setObjectName("clear-btn")
        self.clear_btn.setFixedSize(24, 22)
        self.clear_btn.setToolTip("Clear recording")
        self.clear_btn.clicked.connect(self._clear_data)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.clear_btn)
        vb.addLayout(actions)
        return frame

    def _hsep(self):
        line = QFrame()
        line.setObjectName("accordion-sep")
        line.setFixedHeight(1)
        return line

    def _build_main_area(self):
        widget = QWidget()
        vb = QVBoxLayout(widget)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)

        # Plot area (resizable splitters built in _rebuild_plot_layout)
        self.plot_container = QWidget()
        self.plot_container_layout = QVBoxLayout(self.plot_container)
        self.plot_container_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_container_layout.setSpacing(0)
        vb.addWidget(self.plot_container, 1)

        vb.addWidget(self._build_bottom_bar())
        return widget

    def _build_bottom_bar(self):
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(46)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(12, 6, 12, 6)
        hb.setSpacing(8)

        # Primary record / stop control.
        self.record_toggle_btn = QPushButton("REC")
        self.record_toggle_btn.setObjectName("record-btn")
        self.record_toggle_btn.setMinimumWidth(72)
        self.record_toggle_btn.setFixedHeight(26)
        self.record_toggle_btn.clicked.connect(self._on_record_toggle)

        self.frame_lbl = QLabel("Frame -")
        self.frame_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")

        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self._set_review_frame)

        hb.addWidget(self.record_toggle_btn)
        hb.addWidget(self.frame_lbl)
        hb.addWidget(self.frame_slider, 1)
        return bar

    def _on_record_toggle(self):
        if self.state == State.RECORDING:
            self._enter_review()
        else:
            self._start_recording()

    def _update_record_controls(self):
        recording = self.state == State.RECORDING
        review = self.state == State.REVIEW
        if recording:
            self.record_toggle_btn.setObjectName("record-btn-active")
            remaining = max(0.0, self.rec_duration_s - self._recording_elapsed())
            self.record_toggle_btn.setText(f"STOP  {remaining:.1f}s")
        else:
            self.record_toggle_btn.setObjectName("record-btn")
            self.record_toggle_btn.setText("NEW REC" if review else "REC")
        self.record_toggle_btn.style().unpolish(self.record_toggle_btn)
        self.record_toggle_btn.style().polish(self.record_toggle_btn)
        self.save_btn.setVisible(review)
        self.clear_btn.setVisible(review)

    def _setup_plots(self):
        self._rebuild_plot_layout()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _new_plot_widget(self, title):
        p = pg.PlotWidget(background=S.GRAPH_BG)
        p.setTitle(title, color=S.TEXT_SECONDARY, size="10pt")
        p.showGrid(x=True, y=True, alpha=0.25)
        p.getAxis("left").setTextPen(pg.mkPen(S.GRAPH_FG))
        p.getAxis("bottom").setTextPen(pg.mkPen(S.GRAPH_FG))
        return p

    def apply_theme(self):
        if hasattr(self, "frame_lbl"):
            self.frame_lbl.setStyleSheet(f"color:{S.TEXT_SECONDARY};font-size:11px;")
        # _fs_lbl / _samples_lbl use the themed #field-label QSS rule.
        self._rebuild_plot_layout()

    def _add_graph_context_menu(self, plot, key):
        """Add a 'Hide this graph' entry to the plot's right-click menu."""
        vb = plot.getPlotItem().getViewBox()
        vb.menu.addSeparator()
        action = QAction("Hide this graph", plot)
        action.triggered.connect(lambda _=False, k=key: self._hide_graph(k))
        vb.menu.addAction(action)

    def _hide_graph(self, key):
        cb = self.panel_checks.get(key)
        if cb is not None:
            cb.setChecked(False)

    def _build_traj_plot(self):
        p = self._new_plot_widget("COP Trajectory")
        p.setLabel("left", "AP (mm)", color=GRAPH_FG, size="9pt")
        p.setLabel("bottom", "ML (mm)", color=GRAPH_FG, size="9pt")
        p.setAspectLocked(True)
        self.p_traj = p
        self.c_traj = p.plot(pen=pg.mkPen(C_TRAJ, width=1))
        self.c_dot = pg.ScatterPlotItem(size=8, brush=pg.mkBrush(C_DOT), pen=pg.mkPen(None))
        p.addItem(self.c_dot)
        self._add_graph_context_menu(p, "traj")
        return p

    def _build_time_plot(self, key, is_last):
        spec = {
            "fx": ("Force X", "Fx (N)", C_FX),
            "fy": ("Force Y", "Fy (N)", C_FY),
            "fz": ("Force Z", "Fz (N)", C_FZ),
            "ap": ("COP AP", "AP (mm)", C_AP),
            "ml": ("COP ML", "ML (mm)", C_ML),
        }
        title, ylabel, color = spec[key]
        p = self._new_plot_widget(title)
        p.setLabel("left", ylabel, color=GRAPH_FG, size="9pt")
        curve = p.plot(pen=pg.mkPen(color, width=1.5))
        if key == "fx":
            self.p_fx, self.c_fx = p, curve
        elif key == "fy":
            self.p_fy, self.c_fy = p, curve
        elif key == "fz":
            self.p_fz, self.c_fz = p, curve
            p.setYRange(0, 1200)
        elif key == "ap":
            self.p_ap, self.c_ap = p, curve
        else:
            self.p_ml, self.c_ml = p, curve
        if is_last:
            p.setLabel("bottom", "Sample", color=GRAPH_FG, size="9pt")
        self._add_review_cursor(p)
        self._add_graph_context_menu(p, key)
        return p

    def _rebuild_plot_layout(self, *_args):
        if not hasattr(self, "plot_container"):
            return

        self.panel_visible = {
            key: cb.isChecked()
            for key, cb in self.panel_checks.items()
        }
        self._clear_layout(self.plot_container_layout)

        self.p_fx = None
        self.p_fy = None
        self.p_fz = None
        self.p_traj = None
        self.p_ap = None
        self.p_ml = None
        self.c_fx = None
        self.c_fy = None
        self.c_fz = None
        self.c_ap = None
        self.c_ml = None
        self.c_traj = None
        self.c_dot = None
        self.review_cursor_lines = []

        time_keys = [k for k in ("fx", "fy", "fz", "ap", "ml") if self.panel_visible.get(k, True)]
        has_traj = self.panel_visible.get("traj", True)

        time_stack = None
        if time_keys:
            time_stack = QSplitter(Qt.Orientation.Vertical)
            time_stack.setObjectName("plot-splitter")
            time_stack.setChildrenCollapsible(False)
            time_stack.setHandleWidth(6)
            for i, key in enumerate(time_keys):
                time_stack.addWidget(self._build_time_plot(key, is_last=(i == len(time_keys) - 1)))
            time_stack.setSizes([1000] * len(time_keys))

        traj = self._build_traj_plot() if has_traj else None

        if traj is not None and time_stack is not None:
            hsplit = QSplitter(Qt.Orientation.Horizontal)
            hsplit.setObjectName("plot-splitter")
            hsplit.setChildrenCollapsible(False)
            hsplit.setHandleWidth(6)
            hsplit.addWidget(traj)
            hsplit.addWidget(time_stack)
            hsplit.setStretchFactor(0, 0)
            hsplit.setStretchFactor(1, 1)
            hsplit.setSizes([360, 940])
            self.plot_container_layout.addWidget(hsplit)
        elif traj is not None:
            self.plot_container_layout.addWidget(traj)
        elif time_stack is not None:
            self.plot_container_layout.addWidget(time_stack)

        # Each plot zooms/pans independently (no x-axis linking).

        if self.state == State.REVIEW and self.rec_data:
            self._show_recording_review()
        else:
            self._refresh_plot_data()

    def _add_review_cursor(self, plot):
        line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(ACCENT_TEAL, width=1),
        )
        line.setVisible(self.state == State.REVIEW and bool(self.rec_data))
        plot.addItem(line)
        self.review_cursor_lines.append(line)

    def _refresh_plot_data(self):
        fx = list(self.fx_buf)
        fy = list(self.fy_buf)
        fz = list(self.fz_buf)
        ap = list(self.ap_buf)
        ml = list(self.ml_buf)
        # Live view is a rolling realtime window: x is the position within the
        # buffer (0..N), so frames never pile up and no reset is needed.
        n = len(fx)
        x = list(range(n))

        if self.c_fx is not None:
            self.c_fx.setData(x, fx)
        if self.c_fy is not None:
            self.c_fy.setData(x, fy)
        if self.c_fz is not None:
            self.c_fz.setData(x, fz)
        if self.c_ap is not None:
            self.c_ap.setData(x, ap)
        if self.c_ml is not None:
            self.c_ml.setData(x, ml)
        if self.c_traj is not None:
            self.c_traj.setData(ml, ap)
        if self.c_dot is not None and ml:
            self.c_dot.setData([ml[-1]], [ap[-1]])

        for p in [self.p_fx, self.p_fy, self.p_fz, self.p_ap, self.p_ml]:
            if p is not None:
                p.setXRange(0, max(1, n), padding=0)

    def _setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._update)
        self.timer.start(20)   # 50 Hz display

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._playback_step)

        self._reconnect_timer = QTimer()
        self._reconnect_timer.timeout.connect(self._try_reconnect)

    def _setup_shortcuts(self):
        pass

    def _update(self):
        if self.state == State.RECORDING and self._recording_elapsed() >= self.rec_duration_s:
            self._enter_review()
            return

        if self.state == State.REVIEW:
            # drain but don't display
            try:
                while True:
                    self.data_queue.get_nowait()
            except queue.Empty:
                pass
            return

        updated = False

        try:
            while True:
                fx, fy, fz, cop_ap, cop_ml, mx, my, mz = \
                    self.data_queue.get_nowait()
                fx, fy, fz, cop_ap, cop_ml, mx, my, mz = \
                    self.axis_settings.transform_live(
                        fx, fy, fz, cop_ap, cop_ml, mx, my, mz
                    )

                self.t_buf.append(self.sample_count)
                self.fx_buf.append(fx)
                self.fy_buf.append(fy)
                self.fz_buf.append(fz)
                self.ap_buf.append(cop_ap)
                self.ml_buf.append(cop_ml)

                # fs estimation
                now = time.monotonic()
                if self._fs_last_time is None:
                    self._fs_last_time  = now
                    self._fs_last_count = self.sample_count
                elif now - self._fs_last_time >= 1.0:
                    diff = self.sample_count - self._fs_last_count
                    elapsed = now - self._fs_last_time
                    self.fs_estimate    = max(1, int(round(diff / elapsed)))
                    self._fs_last_time  = now
                    self._fs_last_count = self.sample_count
                    self.stat_fs.setValue(str(self.fs_estimate), "Hz")

                # recording
                if self.state == State.RECORDING:
                    self.rec_data.append({
                        "sample": self.rec_count,
                        "time_s": self.rec_count / max(1, self.rec_fs),
                        "Fx": fx, "Fy": fy, "Fz": fz,
                        "Mx": mx, "My": my, "Mz": mz,
                        "COP_AP": cop_ap, "COP_ML": cop_ml,
                        "fs": self.rec_fs,
                    })
                    self.rec_count += 1
                    remaining = max(0.0, self.rec_duration_s - self._recording_elapsed())
                    self.record_toggle_btn.setText(f"STOP {remaining:.1f}s")

                    if self._recording_elapsed() >= self.rec_duration_s:
                        self._enter_review()
                        return

                self.sample_count += 1
                updated = True

        except queue.Empty:
            pass

        if not updated:
            return

        fz = list(self.fz_buf)
        self._refresh_plot_data()

        self.stat_samples.setValue(f"{self.sample_count:,}", "")
        if fz:
            self.stat_fz.setValue(f"{fz[-1]:.0f}", "N")

    def _connect_qtm(self):
        self._auto_reconnect = True
        if self.qtm_thread and self.qtm_thread.is_alive():
            return
        ip = self.ip_input.text().strip() or "127.0.0.1"
        self.qtm_status_lbl.setText("Connecting...")
        self.qtm_status_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")
        self.qtm_thread = threading.Thread(
            target=qtm_client.run_qtm,
            args=(ip, self.data_queue,
                  lambda s: self._qtm_signal.emit(s)),
            daemon=True,
        )
        self.qtm_thread.start()

    def _try_reconnect(self):
        return

    def _on_qtm_status(self, status):
        if status == "connected":
            self.qtm_status_lbl.setText("Connected")
            self.qtm_status_lbl.setStyleSheet(f"color:{ACCENT_TEAL};font-size:11px;")
            self.stat_status.setValue("Live", "")
        elif status.startswith("error:"):
            msg = status[6:].strip()
            self.qtm_status_lbl.setText(msg)
            self.qtm_status_lbl.setStyleSheet(f"color:{ACCENT_RED};font-size:11px;")
            self.stat_status.setValue("Error", "")
        else:
            self.qtm_status_lbl.setText("Disconnected")
            self.qtm_status_lbl.setStyleSheet(f"color:{ACCENT_RED};font-size:11px;")
            self.stat_status.setValue("Offline", "")

    def _start_recording(self):
        self._stop_playback()
        while True:
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        self.rec_data   = []
        self.rec_count  = 0
        self.rec_duration_s = float(self.duration_spin.value())
        self.rec_started_at = time.monotonic()
        self.rec_fs = max(1, self.fs_estimate)
        self.rec_target = int(round(self.rec_duration_s * self.rec_fs))
        self.state      = State.RECORDING
        self._update_record_controls()
        self.stat_status.setValue("Recording", "")

    def _recording_elapsed(self):
        if self.rec_started_at is None:
            return 0.0
        return time.monotonic() - self.rec_started_at

    def _enter_review(self):
        self._stop_playback()
        self.state = State.REVIEW
        self.rec_started_at = None
        self._update_record_controls()
        self.stat_status.setValue("Review", "")
        self.stat_samples.setValue(f"{self.rec_count:,}", "")

        if not self.rec_data:
            return

        self._show_recording_review()

    def _show_recording_review(self):
        if not self.rec_data:
            return

        fx = [d["Fx"] for d in self.rec_data]
        fy = [d["Fy"] for d in self.rec_data]
        ap = [d["COP_AP"] for d in self.rec_data]
        ml = [d["COP_ML"] for d in self.rec_data]
        fz = [d["Fz"]     for d in self.rec_data]
        t  = list(range(len(ap)))

        if self.c_fx is not None:
            self.c_fx.setData(t, fx)
        if self.c_fy is not None:
            self.c_fy.setData(t, fy)
        if self.c_fz is not None:
            self.c_fz.setData(t, fz)
        if self.c_ap is not None:
            self.c_ap.setData(t, ap)
        if self.c_ml is not None:
            self.c_ml.setData(t, ml)
        if self.c_traj is not None:
            self.c_traj.setData(ml, ap)
        if self.c_dot is not None and ml:
            self.c_dot.setData([ml[-1]], [ap[-1]])

        for p in [self.p_fx, self.p_fy, self.p_fz, self.p_ap, self.p_ml]:
            if p is not None:
                p.setXRange(0, len(t), padding=0.02)
                p.enableAutoRange(axis="y")

        self.frame_slider.blockSignals(True)
        self.frame_slider.setEnabled(True)
        self.frame_slider.setRange(0, max(0, len(self.rec_data) - 1))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)
        self._set_review_frame(0)

    def _toggle_playback(self):
        if not hasattr(self, "play_btn"):
            return
        if not self.rec_data:
            return
        if self.state != State.REVIEW:
            return
        if self.play_timer.isActive():
            self._stop_playback()
            return

        self.play_index = self.frame_slider.value()
        if self.play_index >= len(self.rec_data) - 1:
            self.play_index = 0
            self.frame_slider.setValue(0)
        self.play_btn.setText("❚❚")
        self.play_btn.setObjectName("play-btn-active")
        self.play_btn.style().unpolish(self.play_btn)
        self.play_btn.style().polish(self.play_btn)
        self._playback_step()
        self.play_timer.start(20)

    def _stop_playback(self):
        if hasattr(self, "play_timer") and self.play_timer.isActive():
            self.play_timer.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.setText("▶")
            self.play_btn.setObjectName("play-btn")
            self.play_btn.style().unpolish(self.play_btn)
            self.play_btn.style().polish(self.play_btn)

    def _playback_step(self):
        if not self.rec_data:
            self._stop_playback()
            return

        step = max(1, int(round(self.rec_fs / 50)))
        self.play_index = min(len(self.rec_data) - 1, self.play_index + step)
        self.frame_slider.setValue(self.play_index)

        if self.play_index >= len(self.rec_data) - 1:
            self._stop_playback()
            self.stat_samples.setValue(f"{len(self.rec_data):,}", "")

    def _set_review_frame(self, index):
        if not self.rec_data:
            self.frame_lbl.setText("Frame -")
            return

        index = max(0, min(int(index), len(self.rec_data) - 1))
        self.play_index = index
        frame = self.rec_data[index]

        for line in self.review_cursor_lines:
            line.setPos(index)
            line.setVisible(self.state == State.REVIEW)

        if self.c_dot is not None:
            self.c_dot.setData([frame["COP_ML"]], [frame["COP_AP"]])

        t = float(frame.get("time_s", 0.0))
        self.frame_lbl.setText(f"Frame {index + 1:,}/{len(self.rec_data):,}  {t:.2f}s")
        self.stat_samples.setValue(f"{index + 1:,} / {len(self.rec_data):,}", "")
        self.stat_fz.setValue(f"{frame['Fz']:.0f}", "N")

    def _set_button_role(self, button, object_name):
        button.setObjectName(object_name)
        if object_name == "record-btn":
            button.setStyleSheet(
                f"background-color:{ACCENT_TEAL};color:#fff;border:none;"
                "border-radius:6px;padding:10px;font-size:13px;font-weight:500;"
            )
        elif object_name == "record-btn-active":
            button.setStyleSheet(
                f"background-color:{ACCENT_RED};color:#fff;border:none;"
                "border-radius:6px;padding:10px;font-size:13px;"
            )
        else:
            button.setStyleSheet("")
        button.style().unpolish(button)
        button.style().polish(button)

    def _save_data(self):
        if not self.rec_data:
            return
        self._stop_playback()

        fields = ["sample", "time_s", "Fx", "Fy", "Fz",
                  "Mx", "My", "Mz", "COP_AP", "COP_ML", "fs"]

        default_name = datetime.now().strftime("trial_%Y%m%d_%H%M%S_raw.csv")
        default_path = os.path.join(self.save_dir, default_name)
        raw_path, _ = QFileDialog.getSaveFileName(
            self, "Save recording", default_path, "CSV Files (*.csv)"
        )
        if not raw_path:
            return
        if not raw_path.lower().endswith(".csv"):
            raw_path += ".csv"
        self.save_dir = os.path.dirname(raw_path)

        with open(raw_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(self.rec_data)

        self.stat_status.setValue("Saved", "")
        QMessageBox.information(self, "Saved", f"Saved recording:\n{raw_path}")
        print(f"[Saved] {raw_path}")

    def _clear_data(self):
        self._stop_playback()
        self.rec_data  = []
        self.rec_count = 0
        self.rec_duration_s = 0.0
        self.rec_started_at = None
        self.state     = State.IDLE
        self._update_record_controls()
        self._reset_live_data()

    def _reset_live_data(self):
        if self.state == State.RECORDING:
            return

        while True:
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        self.sample_count = 0
        self._fs_last_time = None
        self._fs_last_count = 0
        self.state = State.IDLE
        self._update_record_controls()
        for line in self.review_cursor_lines:
            line.setVisible(False)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, 0)
        self.frame_slider.setValue(0)
        self.frame_slider.setEnabled(False)
        self.frame_slider.blockSignals(False)
        self.frame_lbl.setText("Frame -")
        for buf in [self.t_buf, self.fx_buf, self.fy_buf, self.fz_buf, self.ap_buf, self.ml_buf]:
            buf.clear()

        self.stat_status.setValue("Live", "")
        self.stat_samples.setValue("0", "")
        self.stat_fz.setValue("-", "")
        self._refresh_plot_data()

    def _sec(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("section-label")
        return lbl

    def _sep(self):
        s = QFrame()
        s.setFrameShape(QFrame.Shape.HLine)
        s.setStyleSheet(f"color:{BORDER};")
        return s

    def _make_section(self, title, content, expanded=True):
        """A flat collapsible section: collapsing it lets the sections below
        slide up automatically (accordion behaviour)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        header = QPushButton(("▾  " if expanded else "▸  ") + title)
        header.setObjectName("section-toggle")
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_toggle(checked, h=header, c=content, t=title):
            c.setVisible(checked)
            h.setText(("▾  " if checked else "▸  ") + t)

        header.toggled.connect(_on_toggle)
        content.setVisible(expanded)
        lay.addWidget(header)
        lay.addWidget(content)
        return box

    # ----- Project (.ballab) integration -----
    project_kind = "record"
    supports_load_file = False

    REC_FIELDS = ["sample", "time_s", "Fx", "Fy", "Fz",
                  "Mx", "My", "Mz", "COP_AP", "COP_ML", "fs"]

    def new_project(self):
        self._clear_data()

    def has_content(self):
        return bool(self.rec_data)

    def load_file(self):
        QMessageBox.information(
            self, "Not available",
            "The Record tab works with live recordings and projects, not loaded files.",
        )

    def export_data(self):
        if not self.rec_data:
            QMessageBox.information(
                self, "No recording", "Record or open a recording before exporting."
            )
            return
        self._save_data()

    def _rec_data_to_csv_bytes(self):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self.REC_FIELDS)
        writer.writeheader()
        writer.writerows(self.rec_data)
        return buf.getvalue().encode("utf-8-sig")

    def save_project_state(self):
        manifest = {
            "tab": self.project_kind,
            "version": 1,
            "duration": float(self.duration_spin.value()),
            "rec_fs": int(self.rec_fs),
            "panel_visible": {k: cb.isChecked() for k, cb in self.panel_checks.items()},
            "has_recording": bool(self.rec_data),
        }
        files = {}
        if self.rec_data:
            manifest["recording_file"] = "data/recording.csv"
            files["data/recording.csv"] = self._rec_data_to_csv_bytes()
        return manifest, files

    def load_project_state(self, manifest, datadir):
        self._clear_data()
        self.duration_spin.setValue(float(manifest.get("duration", 30)))
        pv = manifest.get("panel_visible", {})
        for key, cb in self.panel_checks.items():
            if key in pv:
                cb.blockSignals(True)
                cb.setChecked(bool(pv[key]))
                cb.blockSignals(False)
                self.panel_visible[key] = bool(pv[key])

        rec_file = manifest.get("recording_file")
        if rec_file and datadir:
            path = os.path.join(datadir, rec_file)
            rec_data = []
            with open(path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rec_data.append({
                        "sample": int(float(row.get("sample", 0))),
                        "time_s": float(row.get("time_s", 0.0)),
                        "Fx": float(row.get("Fx", 0.0) or 0.0),
                        "Fy": float(row.get("Fy", 0.0) or 0.0),
                        "Fz": float(row.get("Fz", 0.0) or 0.0),
                        "Mx": float(row.get("Mx", 0.0) or 0.0),
                        "My": float(row.get("My", 0.0) or 0.0),
                        "Mz": float(row.get("Mz", 0.0) or 0.0),
                        "COP_AP": float(row.get("COP_AP", 0.0) or 0.0),
                        "COP_ML": float(row.get("COP_ML", 0.0) or 0.0),
                        "fs": float(row.get("fs", 1000.0) or 1000.0),
                    })
            self.rec_data = rec_data
            self.rec_count = len(rec_data)
            self.rec_fs = int(manifest.get("rec_fs", 1000)) or 1000
            self.state = State.REVIEW
            self._update_record_controls()
            self.stat_status.setValue("Review", "")
            self.stat_samples.setValue(f"{self.rec_count:,}", "")
            self._rebuild_plot_layout()
            self._show_recording_review()
        else:
            self._update_record_controls()
            self._rebuild_plot_layout()
