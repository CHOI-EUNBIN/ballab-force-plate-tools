import os
import csv
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
    QFileDialog, QStackedWidget,
    QCheckBox, QMessageBox, QSlider,
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal

from core.axis_settings import AxisSettings
from core import qtm_client
from ui.style import (
    ACCENT_TEAL, ACCENT_RED, TEXT_PRIMARY, TEXT_SECONDARY,
    BORDER, GRAPH_BG, GRAPH_FG, BG_PANEL,
)

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
            os.path.expanduser("~"), "Documents", "BALLAB", "data"
        )
        os.makedirs(self.save_dir, exist_ok=True)

        self._build_ui()
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
        frame.setFixedWidth(205)

        vb = QVBoxLayout(frame)
        vb.setContentsMargins(14, 16, 14, 14)
        vb.setSpacing(10)
        vb.addWidget(self._sec("Connection"))

        ip_row = QHBoxLayout()
        self.ip_input = QLineEdit(self.qtm_ip)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("small-btn")
        self.connect_btn.setFixedWidth(62)
        self.connect_btn.clicked.connect(self._connect_qtm)
        ip_row.addWidget(self.ip_input)
        ip_row.addWidget(self.connect_btn)
        vb.addLayout(ip_row)

        self.qtm_status_lbl = QLabel("Disconnected")
        self.qtm_status_lbl.setStyleSheet(
            f"color: {ACCENT_RED}; font-size: 11px;"
        )
        self.qtm_status_lbl.setWordWrap(True)
        vb.addWidget(self.qtm_status_lbl)

        vb.addWidget(self._sep())
        vb.addWidget(self._sec("Recording time"))
        vb.addWidget(QLabel("Duration (sec)"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1, 600)
        self.duration_spin.setValue(30)
        self.duration_spin.setSingleStep(5)
        vb.addWidget(self.duration_spin)

        self.reset_btn = QPushButton("Reset live frames")
        self.reset_btn.setObjectName("small-btn")
        self.reset_btn.clicked.connect(self._reset_live_data)
        vb.addWidget(self.reset_btn)

        vb.addWidget(self._sep())
        vb.addWidget(self._sec("Panels"))
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
            vb.addWidget(cb)

        vb.addStretch()
        self.action_stack = QStackedWidget()
        self.action_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self.action_stack.setFixedHeight(132)
        p0 = QWidget()
        p0.setStyleSheet("background: transparent;")
        p0l = QVBoxLayout(p0)
        p0l.setContentsMargins(0, 0, 0, 0)
        p0l.setSpacing(4)
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setObjectName("record-btn-active")
        self.record_btn.clicked.connect(self._start_recording)
        self._set_button_role(self.record_btn, "record-btn-active")
        p0l.addWidget(self.record_btn)
        self.action_stack.addWidget(p0)
        p1 = QWidget()
        p1.setStyleSheet("background: transparent;")
        p1l = QVBoxLayout(p1)
        p1l.setContentsMargins(0, 0, 0, 0)
        p1l.setSpacing(4)
        self.rec_btn = QPushButton("Recording...")
        self.rec_btn.setObjectName("record-btn-active")
        self.rec_btn.setEnabled(False)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("clear-btn")
        self.stop_btn.clicked.connect(self._enter_review)
        p1l.addWidget(self.rec_btn)
        p1l.addWidget(self.stop_btn)
        self.action_stack.addWidget(p1)
        p2 = QWidget()
        p2.setStyleSheet("background: transparent;")
        p2l = QVBoxLayout(p2)
        p2l.setContentsMargins(0, 0, 0, 0)
        p2l.setSpacing(4)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("save-btn")
        self.save_btn.clicked.connect(self._save_data)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("clear-btn")
        self.clear_btn.clicked.connect(self._clear_data)
        p2l.addWidget(self.save_btn)
        p2l.addWidget(self.clear_btn)
        self.action_stack.addWidget(p2)

        vb.addWidget(self.action_stack)
        return frame

    def _build_main_area(self):
        widget = QWidget()
        vb = QVBoxLayout(widget)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(GRAPH_BG)
        vb.addWidget(self.glw, 1)
        vb.addWidget(self._build_review_timeline())
        vb.addWidget(self._build_statusbar())
        return widget

    def _build_review_timeline(self):
        frame = QFrame()
        frame.setStyleSheet("background: transparent; border: none;")
        frame.setFixedHeight(38)
        hb = QHBoxLayout(frame)
        hb.setContentsMargins(16, 4, 16, 4)
        hb.setSpacing(10)

        self.frame_lbl = QLabel("Frame -")
        self.frame_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self._set_review_frame)

        hb.addWidget(self.frame_lbl)
        hb.addWidget(self.frame_slider, 1)
        return frame

    def _build_statusbar(self):
        bar = QFrame()
        bar.setStyleSheet("background: transparent; border: none;")
        bar.setFixedHeight(32)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(16, 0, 16, 0)
        hb.setSpacing(24)

        def add_stat(name):
            n = QLabel(name)
            n.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")
            v = QLabel("-")
            v.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:11px;font-weight:500;")
            hb.addWidget(n)
            hb.addWidget(v)
            return v

        self.stat_status  = add_stat("Status")
        self.stat_fs      = add_stat("Fs")
        self.stat_samples = add_stat("Samples")
        self.stat_fz      = add_stat("Fz")
        hb.addStretch()
        return bar

    def _setup_plots(self):
        self.plot_defs = [
            ("fx", "Force X", "Fx (N)"),
            ("fy", "Force Y", "Fy (N)"),
            ("fz", "Force Z", "Fz (N)"),
            ("traj", "COP Trajectory", "AP (mm)"),
            ("ap", "COP AP", "AP (mm)"),
            ("ml", "COP ML", "ML (mm)"),
        ]
        self._rebuild_plot_layout()

    def _rebuild_plot_layout(self, *_args):
        if not hasattr(self, "glw"):
            return

        self.panel_visible = {
            key: cb.isChecked()
            for key, cb in self.panel_checks.items()
        }
        self.glw.clear()

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

        selected = [
            item for item in self.plot_defs
            if self.panel_visible.get(item[0], True)
        ]

        positions = {
            "fx": (0, 0),
            "fy": (1, 0),
            "fz": (2, 0),
            "ap": (0, 1),
            "ml": (1, 1),
            "traj": (2, 1),
        }

        for key, title, ylabel in selected:
            row, col = positions[key]
            p = self.glw.addPlot(row=row, col=col, title=title)
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setLabel("left", ylabel, color=GRAPH_FG, size="9pt")
            p.getAxis("left").setTextPen(pg.mkPen(GRAPH_FG))
            p.getAxis("bottom").setTextPen(pg.mkPen(GRAPH_FG))
            p.getAxis("top").setStyle(showValues=False)

            if key == "fx":
                self.p_fx = p
                self.c_fx = self.p_fx.plot(pen=pg.mkPen(C_FX, width=1.5))
                self._add_review_cursor(self.p_fx)
            elif key == "fy":
                self.p_fy = p
                self.c_fy = self.p_fy.plot(pen=pg.mkPen(C_FY, width=1.5))
                self._add_review_cursor(self.p_fy)
            elif key == "fz":
                self.p_fz = p
                self.p_fz.setYRange(0, 1200)
                self.c_fz = self.p_fz.plot(pen=pg.mkPen(C_FZ, width=1.5))
                self._add_review_cursor(self.p_fz)
            elif key == "traj":
                self.p_traj = p
                self.p_traj.setLabel("bottom", "ML (mm)", color=GRAPH_FG, size="9pt")
                self.p_traj.setAspectLocked(True)
                self.c_traj = self.p_traj.plot(pen=pg.mkPen(C_TRAJ, width=1))
                self.c_dot = pg.ScatterPlotItem(
                    size=8, brush=pg.mkBrush(C_DOT), pen=pg.mkPen(None)
                )
                self.p_traj.addItem(self.c_dot)
            elif key == "ap":
                self.p_ap = p
                self.c_ap = self.p_ap.plot(pen=pg.mkPen(C_AP, width=1.5))
                self._add_review_cursor(self.p_ap)
            elif key == "ml":
                self.p_ml = p
                self.c_ml = self.p_ml.plot(pen=pg.mkPen(C_ML, width=1.5))
                self._add_review_cursor(self.p_ml)

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
        t = list(self.t_buf)
        fx = list(self.fx_buf)
        fy = list(self.fy_buf)
        fz = list(self.fz_buf)
        ap = list(self.ap_buf)
        ml = list(self.ml_buf)

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

        if self.sample_count > BUFFER_SIZE:
            xmin = self.sample_count - BUFFER_SIZE
            xmax = self.sample_count
            for p in [self.p_fx, self.p_fy, self.p_fz, self.p_ap, self.p_ml]:
                if p is not None:
                    p.setXRange(xmin, xmax, padding=0)

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
                    self.stat_fs.setText(f"{self.fs_estimate} Hz")

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
                    self.rec_btn.setText(f"{remaining:.1f}s remaining")

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

        self.stat_samples.setText(f"{self.sample_count:,}")
        if fz:
            self.stat_fz.setText(f"{fz[-1]:.0f} N")

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
            self.stat_status.setText("Live")
        elif status.startswith("error:"):
            msg = status[6:].strip()
            self.qtm_status_lbl.setText(msg)
            self.qtm_status_lbl.setStyleSheet(f"color:{ACCENT_RED};font-size:11px;")
            self.stat_status.setText("Error")
        else:
            self.qtm_status_lbl.setText("Disconnected")
            self.qtm_status_lbl.setStyleSheet(f"color:{ACCENT_RED};font-size:11px;")
            self.stat_status.setText("Offline")

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
        self.action_stack.setCurrentIndex(1)
        self.rec_btn.setText(f"{self.rec_duration_s:.1f}s remaining")
        self.stat_status.setText("Recording")

    def _recording_elapsed(self):
        if self.rec_started_at is None:
            return 0.0
        return time.monotonic() - self.rec_started_at

    def _enter_review(self):
        self._stop_playback()
        self.state = State.REVIEW
        self.rec_started_at = None
        self.action_stack.setCurrentIndex(2)
        self.stat_status.setText("Review")
        self.stat_samples.setText(f"{self.rec_count:,}")

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
        self.play_btn.setText("Stop")
        self._set_button_role(self.play_btn, "record-btn-active")
        self._playback_step()
        self.play_timer.start(20)

    def _stop_playback(self):
        if hasattr(self, "play_timer") and self.play_timer.isActive():
            self.play_timer.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.setText("Play")
            self._set_button_role(self.play_btn, "record-btn")

    def _playback_step(self):
        if not self.rec_data:
            self._stop_playback()
            return

        step = max(1, int(round(self.rec_fs / 50)))
        self.play_index = min(len(self.rec_data) - 1, self.play_index + step)
        self.frame_slider.setValue(self.play_index)

        if self.play_index >= len(self.rec_data) - 1:
            self._stop_playback()
            self.stat_samples.setText(f"{len(self.rec_data):,}")

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
        self.stat_samples.setText(f"{index + 1:,} / {len(self.rec_data):,}")
        self.stat_fz.setText(f"{frame['Fz']:.0f} N")

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

        self.stat_status.setText("Saved")
        QMessageBox.information(self, "Saved", f"Saved recording:\n{raw_path}")
        print(f"[Saved] {raw_path}")

    def _clear_data(self):
        self._stop_playback()
        self.rec_data  = []
        self.rec_count = 0
        self.rec_duration_s = 0.0
        self.rec_started_at = None
        self.state     = State.IDLE
        self.action_stack.setCurrentIndex(0)
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
        self.action_stack.setCurrentIndex(0)
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

        self.stat_status.setText("Live")
        self.stat_samples.setText("0")
        self.stat_fz.setText("-")
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
