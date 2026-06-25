import os
import re
import csv
import io
import time
import zlib

import numpy as np

from core.project import PROJECT_EXT
import pyqtgraph as pg
import pyqtgraph.exporters
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QKeySequence, QShortcut, QAction, QIcon,
    QDrag, QCursor, QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QPushButton, QLabel, QCheckBox,
    QScrollArea, QFileDialog, QListWidget, QListWidgetItem, QListView,
    QMessageBox, QAbstractItemView, QLineEdit, QComboBox,
    QDoubleSpinBox, QColorDialog, QDialog, QDialogButtonBox, QFormLayout,
    QSplitter, QSizePolicy, QSpinBox, QMenu, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QInputDialog, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent, QSettings, QMimeData

from core.axis_settings import AxisSettings
from core.signals import (
    FILT_SUFFIX, FilterSpec, Workspace, cop_resultant, label_for, unit_for,
)
from core.trajectory import compute_trajectory
from core.metrics import (
    METRIC_KEYS, ANGLE_STATS, compute_metrics, compute_angle_metrics,
    compute_ellipse_points,
)
from core.c3d_reader import read_c3d, build_grf
from core.data_quality import clean_dataset, clean_markers, summarize_reports
from ui.help_dialog import METRIC_TOOLTIPS
from ui.style import (
    ACCENT_TEAL, TEXT_PRIMARY, TEXT_SECONDARY,
    BORDER, GRAPH_BG, GRAPH_FG, BG_DARK, BG_MID, BG_PANEL, BG_INPUT,
    SPACING_SM, SPACING_MD, SPACING_LG, FONT_SIZE_SMALL, FONT_SIZE_LARGE,
    FONT_WEIGHT_SEMI, TEXT_MUTED, BORDER_RADIUS_LG,
)
from ui.data_table import DataTableDialog
from ui.analyze_dialogs import (
    ExportDialog, FilterStepDialog,
    DetectEventStepDialog, TrajectoryStepDialog, MetricStepDialog, AddStepDialog,
    ComputeStepDialog,
)
from core import events_compute
from ui.components.file_tree import FileTreeWidget, TreeRowSeparator, FOLDER_PATH_ROLE
from ui.components.resize_handle import VResizeHandle
from ui.components.graph_viewbox import GraphViewBox
from ui.components.range_slider import TimeRangeSlider
from ui import style as S

C_RAW = "#555550"
C_FILT_AP = "#7F77DD"
C_FILT_ML = "#D4537E"
C_ELL = "#534AB7"
C_COP = "#42A5F5"
C_FX = "#D86A3A"
C_FY = "#3B8FD9"
C_FZ = "#1D9E75"
SEL_GREEN = "#3FC08D"   # checked file-tree rows: green text


class PipelineStepRow(QWidget):
    """One row in the PIPELINE list (injected via ``QListWidget.setItemWidget``).

    Redesigned to read like a VSCode explorer/list row: dense, uniform-height,
    monochrome. Single line, left → right::

        [stage glyph]  Name  · summary (muted)            ⚠   [✎ ✕]   ☑

    The stage glyph is a tiny muted letter (C/D/S/M/N), not a big colour badge —
    the row's visual language is typography + one restrained green accent, never
    a wall of tinted pills. The summary (parameters) sits inline after the name in
    muted text, so the *what* and the *how* read on one line. ``✎`` / ``✕`` reveal
    on hover only (clean at rest); the enable toggle is always shown. A ⚠ glyph
    flags an out-of-order step. A disabled step renders dimmed.

    Detect steps still carry their event line-colour as a small swatch before the
    name (the one place colour is meaningful — it matches the graph line).

    All interaction is delegated up via the ``on_edit`` / ``on_delete`` /
    ``on_toggle`` callbacks (the tab owns the pipeline + re-render) — this widget
    holds no analysis state, only display.
    """

    #: Uniform pixel height — denser than the old 2-line card so the list reads as
    #: a clean grid of equal rows (VSCode list rhythm).
    ROW_HEIGHT = S.PIPELINE_ROW_HEIGHT

    #: One muted single-letter glyph per stage (Compute/Detect/Segment/Metric/
    #: Normalize) — replaces the old big colour badge. Forward-compatible default.
    _STAGE_GLYPH = {
        "derive": "C", "detect": "D", "segment": "S",
        "metric": "M", "normalize": "N",
    }

    def __init__(self, number, step, name, summary, swatch=None, warning=None,
                 on_edit=None, on_delete=None, on_toggle=None, parent=None):
        super().__init__(parent)
        enabled = bool(getattr(step, "enabled", True))
        stage = getattr(step, "stage", "derive")
        glyph = self._STAGE_GLYPH.get(stage, "•")

        self.setObjectName("pipeline-row")
        self.setFixedHeight(self.ROW_HEIGHT)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 6, 0)
        row.setSpacing(7)

        # --- stage glyph: a tiny muted letter (monochrome, no tinted pill) ---
        gl = QLabel(glyph)
        gl.setObjectName("pipeline-stage-glyph")
        gl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.setFixedWidth(14)
        gl.setToolTip({
            "derive": "Compute", "detect": "Detect", "segment": "Segment",
            "metric": "Metric", "normalize": "Normalize",
        }.get(stage, stage))
        gl.setStyleSheet(
            f"color:{S.TEXT_MUTED};font-size:10px;font-weight:600;")
        row.addWidget(gl, 0, Qt.AlignmentFlag.AlignVCenter)

        # --- detect-step colour swatch (only place colour is meaningful) ---
        if swatch is not None:
            sw = QLabel()
            sw.setPixmap(swatch)
            sw.setFixedSize(swatch.width(), swatch.height())
            row.addWidget(sw, 0, Qt.AlignmentFlag.AlignVCenter)

        # --- name (primary) ---
        name_lbl = QLabel(name)
        name_lbl.setObjectName("pipeline-name")
        name_lbl.setStyleSheet(
            f"color:{S.TEXT_PRIMARY};font-size:12px;font-weight:500;")
        row.addWidget(name_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        # --- summary (parameters, muted) inline after the name ---
        if summary:
            sum_lbl = QLabel(summary)
            sum_lbl.setObjectName("pipeline-summary")
            sum_lbl.setStyleSheet(f"color:{S.TEXT_MUTED};font-size:11px;")
            sum_lbl.setToolTip(summary)
            row.addWidget(sum_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        else:
            row.addStretch(1)

        # --- ⚠ order-warning glyph (tooltip carries the English message) ---
        if warning:
            warn = QLabel("⚠")
            warn.setToolTip(warning)
            warn.setStyleSheet(f"color:{S.ACCENT_ORANGE};font-size:11px;")
            row.addWidget(warn, 0, Qt.AlignmentFlag.AlignVCenter)

        # --- hover actions: edit (✎) + delete (✕) ---
        self._edit_btn = QPushButton("✎")
        self._edit_btn.setObjectName("small-btn")
        self._edit_btn.setFixedSize(18, 18)
        self._edit_btn.setToolTip("Edit this step")
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_edit is not None:
            self._edit_btn.clicked.connect(on_edit)
        row.addWidget(self._edit_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._del_btn = QPushButton("✕")
        self._del_btn.setObjectName("small-btn")
        self._del_btn.setFixedSize(18, 18)
        self._del_btn.setToolTip("Remove this step")
        self._del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_delete is not None:
            self._del_btn.clicked.connect(on_delete)
        row.addWidget(self._del_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        # Edit/delete only show on hover (keeps the row clean at rest).
        self._edit_btn.setVisible(False)
        self._del_btn.setVisible(False)

        # --- enable toggle (always visible, compact) ---
        toggle = QCheckBox()
        toggle.setChecked(enabled)
        toggle.setToolTip("On = used in analysis. Off = kept but skipped.")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_toggle is not None:
            toggle.toggled.connect(on_toggle)
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        # Dim the row when the step is disabled (kept-but-skipped).
        if not enabled:
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            for w in (gl, name_lbl):
                eff = QGraphicsOpacityEffect(w)
                eff.setOpacity(0.45)
                w.setGraphicsEffect(eff)

    def sizeHint(self):
        """Report the pinned :data:`ROW_HEIGHT` so every row's size-hint matches
        (the list grid stays uniform)."""
        hint = super().sizeHint()
        hint.setHeight(self.ROW_HEIGHT)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self.ROW_HEIGHT)
        return hint

    def enterEvent(self, event):
        self._edit_btn.setVisible(True)
        self._del_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._edit_btn.setVisible(False)
        self._del_btn.setVisible(False)
        super().leaveEvent(event)


class AnalyzeTab(QWidget):

    def __init__(self, axis_settings=None, appearance=None):
        super().__init__()
        self.axis_settings = axis_settings or AxisSettings()
        if appearance is None:
            from core.appearance import Appearance
            appearance = Appearance()
        self.appearance = appearance
        self.appearance.changed.connect(self._on_appearance_changed)
        # The shared analysis pipeline (the ordered recipe of processing steps).
        # Empty by default = raw; filtering now lives here as FilterStep(s), not
        # in the retired global filter toggle. Persisted in the project manifest.
        from core.pipeline import Pipeline
        self.pipeline = Pipeline()
        self.datasets = []
        self.current_index = None
        self.analysis_results = []
        self.summary_rows = []
        self.panel_checks = {}
        self.panel_visible = {}
        # Active force plate (1-based) for multi-plate files: drives which plate's
        # force/COP the DATA-section graphs, value cards and COP metrics use. The
        # bare keys (fp1) are plate 1, so the default 1 reproduces single-plate
        # behaviour. Per-plate signals (fp{n}:*) stay independently selectable as
        # event/filter channels via the signal catalog.
        self._active_plate = 1
        # Subject metadata (mass/height) per subject, keyed by folder tuple. Used
        # by the dataflow engine (normalize-by-bodyweight) via metric:mass. The
        # Subject panel writes here; empty until entered.
        self._subject_meta = {}
        self.analysis_ranges = []
        self.review_regions = []          # range-highlight items, one per time plot
        self._time_plots = []             # all time-series plots in the current layout
        self.review_cursor_lines = []
        self.event_lines = []
        self.event_color = "#F97316"
        self.review_region_visible = False   # range highlight is opt-in (default off)
        self.view_mode = "review"
        self.play_index = 0
        self._updating_range_slider = False
        self.marker_view = None          # lazily created 3D marker view
        self._marker_just_selected = False
        self._markers3d_side = "left"    # 3D view is the primary pane; graphs to its right
        self._main_split_user_sizes = None  # remembers a user-dragged 3D/graph divider
        self._split_sizes = {}           # remembers user-dragged sizes of rebuilt inner splitters
        self._coord_curves = {}          # idx -> (plot, curves) for current dataset
        self._qsettings = QSettings("Balancelab", "Balancelab")
        self.results_store = None        # shared ResultsStore (injected by MainWindow)
        self.marker_model = None         # active MarkerModel (joint-angle model)
        self.marker_model_task = None    # last built/loaded motion choice (UI-side)
        self.marker_model_zero = False   # last built/loaded zero-to-standing toggle
        self.jointangles_plot = None
        self.c_angles = {}
        # angle name -> int FIGURE-GROUP id. Angles sharing an id render in ONE
        # figure; a unique id per angle = its own figure. (Legacy projects stored
        # "combined"/"separate" strings; _migrate_plot_groups() converts them.)
        self._angle_plots = {}
        # RESULTS·Signals "View as graph" selections for 1-D force/COP/derived
        # signal keys (the angle/marker keys keep their own paths: _angle_plots /
        # coord markers). A key here is shown as a time plot on the next rebuild;
        # a "<key>:filt" entry shows the filtered twin on its parent's plot.
        self._signal_views = set()
        # signal key -> int FIGURE-GROUP id (parallel to _angle_plots, for the
        # produced signal-view keys). Keys sharing an id render in ONE figure; a
        # key with no entry defaults to its own fresh id (one plot per signal).
        self._signal_groups = {}
        self._next_group_id = 1           # monotonic allocator for figure-group ids
        self._show_traj = False           # COP-path (2-D trajectory) view toggle
        self._show_ellipse = True         # draw the 95% ellipse on the COP path (graph on/off)
        self._show_traj_events = True      # draw event points on the COP path (graph on/off)
        # RESULTS·Signals groups the user has collapsed (foldable sub-toggle). The
        # "Joint angles" group folds by default so a many-angle model doesn't flood
        # the panel; clicking its header expands it. Keyed by group label.
        self._collapsed_sig_groups = {"Joint angles"}
        # Events the user has hidden (view-level Delete in RESULTS·Events). Cleared
        # on every ▶Run so re-running regenerates the detected events.
        self._hidden_event_labels = set()
        self._last_run_result = None     # last run_pipeline() dict (for metric tables)
        # Windows-style file organization: a set of folder paths (tuples of names)
        # that exist — including empty ones the user creates. Each dataset has a
        # ["folder"] path tuple; static↔dynamic matching walks this folder tree.
        self._folders = set()
        self._collapsed_folders = set()   # folder paths the user collapsed
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
        # Block wheel-scroll value changes on every spin/combo in the tab (the
        # sidebar + playback bar live inside scroll areas — the wheel must scroll,
        # never silently edit a frame/time field). App-wide install in main.py
        # also covers dialogs; this one keeps the tab self-contained for tests.
        from ui.components.wheel_guard import install_wheel_guard
        install_wheel_guard(self)

    def _make_section(self, title, content, expanded=True, sub=False, header_widgets=None):
        """A flat collapsible accordion section: a borderless header that
        shows/hides its content; collapsing lets the sections below slide up.
        ``sub=True`` renders a smaller header for nested sub-sections.
        ``header_widgets`` are small action buttons placed at the right of the
        header row (e.g. add-files / run icons) — they don't toggle the section."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        header = QPushButton(("▾  " if expanded else "▸  ") + title)
        header.setObjectName("subsection-toggle" if sub else "section-toggle")
        header.setCheckable(True)
        header.setChecked(expanded)
        header.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_toggle(checked, h=header, c=content, t=title):
            c.setVisible(checked)
            h.setText(("▾  " if checked else "▸  ") + t)

        header.toggled.connect(_on_toggle)
        content.setVisible(expanded)
        if header_widgets:
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(2)
            header_row.addWidget(header, 1)
            for w in header_widgets:
                header_row.addWidget(w)
            lay.addLayout(header_row)
        else:
            lay.addWidget(header)
        lay.addWidget(content)
        box._header = header
        return box

    def _hsep(self):
        line = QFrame()
        line.setObjectName("accordion-sep")
        line.setFixedHeight(1)
        return line

    def _apply_section_order(self):
        col = self._sidebar_col
        while col.count():
            item = col.takeAt(0)
            w = item.widget()
            if w is not None and w.objectName() == "accordion-sep":
                w.deleteLater()
            elif w is not None:
                w.setParent(None)  # keep section widgets alive
        order = self._section_order
        for i, sid in enumerate(order):
            box = self._section_boxes.get(sid)
            if box is None:
                continue
            col.addWidget(box)
            if i < len(order) - 1:
                col.addWidget(self._hsep())
        col.addStretch(1)

    # --- Section reordering by dragging a header ---------------------------
    _SECTION_MIME = "application/x-balancelab-section"

    def _enable_section_drag(self, box, sid):
        """Make a section header draggable to reorder, and let the sidebar
        container accept the drop. Replaces the old Move up/down menu."""
        box._section_id = sid
        header = box._header
        header.setToolTip("Drag to reorder")
        header.installEventFilter(self)
        container = self._sidebar_col.parentWidget()
        if container is not None and not getattr(container, "_section_drop", False):
            container.setAcceptDrops(True)
            container.installEventFilter(self)
            container._section_drop = True

    def eventFilter(self, obj, event):
        et = event.type()
        # Space toggles playback when focus is in the file tree (instead of
        # the tree treating Space as a selection key).
        file_tree = getattr(self, "file_tree", None)
        file_viewport = file_tree.viewport() if file_tree is not None else None
        if (
            obj in (file_tree, file_viewport)
            and et == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
        ):
            self._toggle_playback()
            return True
        # Start a drag when a header is pressed and dragged past the threshold.
        if et == QEvent.Type.MouseButtonPress \
                and event.button() == Qt.MouseButton.LeftButton \
                and getattr(obj.parentWidget(), "_section_id", None) is not None:
            self._section_press_pos = event.position().toPoint()
            return False
        if et == QEvent.Type.MouseMove \
                and event.buttons() & Qt.MouseButton.LeftButton \
                and getattr(self, "_section_press_pos", None) is not None:
            box = obj.parentWidget()
            sid = getattr(box, "_section_id", None)
            if sid is not None and (event.position().toPoint() - self._section_press_pos) \
                    .manhattanLength() >= QApplication.startDragDistance():
                self._section_press_pos = None
                self._start_section_drag(sid)
                return True
            return False
        # Sidebar container accepts the section drop and reorders.
        if getattr(obj, "_section_drop", False):
            if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if event.mimeData().hasFormat(self._SECTION_MIME):
                    event.acceptProposedAction()
                    return True
            elif et == QEvent.Type.Drop:
                if event.mimeData().hasFormat(self._SECTION_MIME):
                    sid = bytes(event.mimeData().data(self._SECTION_MIME)).decode()
                    # Map via the global cursor so the y is in the container's
                    # coords regardless of which child the drop propagated through.
                    drop_y = obj.mapFromGlobal(QCursor.pos()).y()
                    self._drop_section(sid, drop_y)
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _start_section_drag(self, sid):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self._SECTION_MIME, sid.encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def _drop_section(self, sid, drop_y):
        """Reorder sections so `sid` lands at the position matching drop_y."""
        order = self._section_order
        if sid not in order:
            return
        # Target index = number of sections whose vertical midpoint is above drop_y.
        target = 0
        for other in order:
            if other == sid:
                continue
            box = self._section_boxes.get(other)
            if box is None:
                continue
            mid = box.y() + box.height() / 2
            if drop_y > mid:
                target += 1
        order.remove(sid)
        order.insert(min(target, len(order)), sid)
        self._qsettings.setValue("analyze/section_order_v5", order)
        self._apply_section_order()

    def _checkbox_group(self, items):
        """Build a small column of plot-toggle checkboxes; register each in
        panel_checks. items = [(key, label, checked), ...]."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        # Contiguous rows (no inter-row gap) + per-row min-height in QSS so these
        # signal toggles share the marker list's row rhythm (style-only match).
        lay.setSpacing(0)
        for key, label, checked in items:
            cb = QCheckBox(label)
            cb.setObjectName("signal-toggle")
            cb.setChecked(checked)
            cb.stateChanged.connect(self._rebuild_plot_layout)
            # Right-click a data series → numeric table (no need to plot it first).
            cb.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            cb.customContextMenuRequested.connect(
                lambda pos, k=key, w=cb: self._show_data_series_menu(k, w, pos))
            self.panel_checks[key] = cb
            self.panel_visible[key] = checked
            lay.addWidget(cb)
        return w

    def _show_data_series_menu(self, key, widget, pos):
        menu = QMenu(self)
        menu.addAction("View data table", lambda: self._show_data_series_table(key))
        menu.exec(widget.mapToGlobal(pos))

    def _build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(380)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        vb = QVBoxLayout(frame)
        vb.setContentsMargins(8, 8, 8, 8)
        vb.setSpacing(4)

        # Accordion: sections stacked in a scroll area. Collapsing a section
        # reclaims its space and the sections below slide up.
        scroll = QScrollArea()
        scroll.setObjectName("sidebar-scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet(S.transparent_bg())
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        # Each accordion section is built by its own helper so this method stays a
        # thin assembler. The helpers return the collapsible section widgets.
        sec_files = self._build_files_section()
        sec_data = self._build_data_section()
        sec_pipeline = self._build_pipeline_section()
        # RESULTS = the by-type listing of everything the pipeline produces
        # (Signals / Events / Metrics). Built AFTER the pipeline section so the
        # ▶Run button lives in the PIPELINE header. Replaces the retired PROCESSED
        # SIGNALS + Model variables + Metrics-input sections AND the standalone
        # Events panel (events now live in RESULTS ▸ Events; added via PIPELINE).
        sec_results = self._build_results_section()

        # Reorderable accordion: sections keyed by id; order persisted. Drag a
        # section header up/down to reorder (see _enable_section_drag).
        # Data flow order: Files -> RAW SIGNALS -> PIPELINE -> RESULTS.
        self._sidebar_col = col
        self._section_boxes = {
            "Files": sec_files, "Data": sec_data,
            "Pipeline": sec_pipeline, "Results": sec_results,
        }
        default_order = ["Files", "Data", "Pipeline", "Results"]
        # A saved order missing a section is repaired by the append loop below
        # (any missing section lands at the end), so old saves restore safely.
        saved = self._qsettings.value("analyze/section_order_v5", None)
        order = [s for s in saved if s in self._section_boxes] if saved else []
        for s in default_order:
            if s not in order:
                order.append(s)
        self._section_order = order
        for sid, box in self._section_boxes.items():
            self._enable_section_drag(box, sid)
        self._apply_section_order()
        scroll.setWidget(inner)
        vb.addWidget(scroll, 1)

        self._refresh_event_controls(None)
        return frame

    def _build_files_section(self):
        # --- Files ---
        files_content = QWidget()
        fc = QVBoxLayout(files_content)
        fc.setContentsMargins(0, 0, 0, 0)
        fc.setSpacing(4)
        # Compact VS-Code-style action icons — placed in the section header
        # (next to the "Files" title) via _make_section(header_widgets=…).
        # "Load files" + "Load folder" sit as header icons; group-by / remove-all
        # live in the "Files" title right-click menu (see _show_files_menu).
        add_files_btn = QPushButton("＋")
        add_files_btn.setObjectName("icon-btn")
        add_files_btn.setFixedSize(22, 20)
        add_files_btn.setToolTip("Load files…  (right-click the title for more)")
        add_files_btn.clicked.connect(self._load_files)
        add_folder_btn = QPushButton()
        add_folder_btn.setObjectName("icon-btn")
        add_folder_btn.setFixedSize(22, 20)
        add_folder_btn.setIcon(self._folder_icon())
        add_folder_btn.setToolTip("Load folder…")
        add_folder_btn.clicked.connect(self._load_folder)
        # Search row with a small count chip on the right (replaces the old
        # standalone "N files loaded" line).
        search_row = QHBoxLayout()
        search_row.setSpacing(0)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("search-input")
        self.search_input.setPlaceholderText("Search files...")
        self.search_input.setFixedHeight(24)
        self.search_input.textChanged.connect(self._filter_file_list)
        self.file_count_chip = QLabel("0")
        self.file_count_chip.setObjectName("count-chip")
        self.file_count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_count_chip.setToolTip("Files loaded")
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.file_count_chip)
        fc.addLayout(search_row)
        self.file_tree = FileTreeWidget()
        self.file_tree.setObjectName("file-list")
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setColumnCount(2)
        self.file_tree.header().setStretchLastSection(False)
        self.file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.file_tree.setColumnWidth(1, 96)
        self.file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Left-align: no expand arrows / branch guides; children indent slightly.
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setIndentation(12)
        self.file_tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Drag files/folders into another folder to reorganize them.
        self.file_tree.setDragEnabled(True)
        self.file_tree.setAcceptDrops(True)
        self.file_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.file_tree.itemClicked.connect(self._on_file_clicked)
        self.file_tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        self.file_tree.itemChanged.connect(self._on_file_item_changed)
        self.file_tree.itemDropped.connect(self._on_tree_item_dropped)
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._show_file_context_menu)
        self.file_tree.setItemDelegate(TreeRowSeparator(self.file_tree))
        fc.addWidget(self.file_tree)
        self._attach_resize_handle(fc, self.file_tree, "analyze/file_tree_height", 180, min_h=80)
        # Top-level section headers are upper-cased for a consistent IA rhythm
        # (FILES / RAW SIGNALS / PIPELINE / RESULTS). The section *id* stays
        # "Files" (see _section_boxes) — this only changes the visible label.
        sec_files = self._make_section(
            "FILES", files_content, expanded=True,
            header_widgets=[add_files_btn, add_folder_btn])
        sec_files._header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        sec_files._header.customContextMenuRequested.connect(
            lambda pos, h=sec_files._header: self._show_files_menu(h.mapToGlobal(pos)))
        return sec_files

    def _build_data_section(self):
        # --- RAW SIGNALS tree: one group per force plate (FP1…FPn) + Markers ---
        # These are the ORIGINAL (raw) signals straight from the file, shown
        # exactly as they came in (plate-local X/Y, not AP/ML). The per-plate
        # groups are built dynamically from the loaded dataset (see
        # _refresh_force_controls). Anything derived (filtered curves, COP
        # trajectory) lives in PROCESSED SIGNALS. Graphs are off by default — the
        # app opens on the 3D view.
        markers_inner = QWidget()
        mkl = QVBoxLayout(markers_inner)
        mkl.setContentsMargins(0, 0, 0, 0)
        mkl.setSpacing(2)
        # The 3D view toggle lives in Settings ▸ View (not Data). Keep the checkbox
        # as the logical on/off state (default on) but don't show it under Data.
        self.markers3d_cb = QCheckBox("3D view")
        self.markers3d_cb.setChecked(True)
        self.markers3d_cb.stateChanged.connect(self._rebuild_plot_layout)
        self.panel_checks["markers3d"] = self.markers3d_cb
        self.panel_visible["markers3d"] = True
        # Marker coordinate graphs are opt-in per marker (right-click a marker →
        # "Plot coordinates"); there is no separate master toggle.

        coord_row = QHBoxLayout()
        coord_row.setSpacing(2)
        self.marker_axis_btns = {}
        for ax_key in ("X", "Y", "Z"):
            btn = QPushButton(ax_key)
            btn.setObjectName("toggle-btn")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedSize(24, 22)
            btn.toggled.connect(lambda *_: self._on_marker_coord_changed())
            self.marker_axis_btns[ax_key] = btn
            coord_row.addWidget(btn)
        coord_row.addStretch(1)
        mkl.addLayout(coord_row)

        # The loaded markers list sits directly under the Markers dropdown.
        self.marker_list = QListWidget()
        self.marker_list.setObjectName("marker-list")
        self.marker_list.setUniformItemSizes(True)
        self.marker_list.itemChanged.connect(self._on_marker_item_changed)
        self.marker_list.currentRowChanged.connect(self._on_marker_selected)
        self.marker_list.itemClicked.connect(self._on_marker_list_clicked)
        self.marker_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.marker_list.customContextMenuRequested.connect(self._show_marker_list_menu)
        mkl.addWidget(self.marker_list)
        self._attach_resize_handle(mkl, self.marker_list, "analyze/marker_list_height", 120, min_h=40)

        # Model building/assignment lives entirely in the file tree (double-click
        # / right-click a static). Models apply automatically during analysis —
        # there is no separate Model section or Apply button.

        # Per-plate raw toggle groups (FP1…FPn) are (re)built here per dataset.
        # (No "analysis plate" selector anymore — a Metric step picks its own plate
        # via its input key, e.g. fp2:cop. Plate 1 is the default for any remaining
        # bare-key view path.)
        self.force_groups_holder = QVBoxLayout()
        self.force_groups_holder.setContentsMargins(0, 0, 0, 0)
        self.force_groups_holder.setSpacing(2)
        force_groups_w = QWidget()
        force_groups_w.setLayout(self.force_groups_holder)

        sec_mk = self._make_section("Markers", markers_inner, expanded=False, sub=True)
        data_inner = QWidget()
        di = QVBoxLayout(data_inner)
        di.setContentsMargins(8, 0, 0, 0)
        di.setSpacing(2)
        di.addWidget(force_groups_w)
        di.addWidget(sec_mk)
        sec_data = self._make_section("RAW SIGNALS", data_inner, expanded=False)
        return sec_data

    # ----- RESULTS: by-type listing of everything the pipeline produces -----
    def _build_results_section(self):
        """RESULTS = three lists (Signals / Events / Metrics) the pipeline
        produces. Adding a step does NOT auto-draw — the artifact is *listed*
        here and the user right-clicks an entry to view it (graph / value table).

        Each list is a ``marker-list`` QListWidget with a custom context menu,
        generalising the old joint-angle ``values_list`` pattern. Entries are
        grouped by ``ResultEntry.group`` (a non-selectable header row), and each
        item carries ``(kind, key)`` on its UserRole. Populated from
        :func:`core.results_model.build_results` on every pipeline change and after
        ▶Run (metrics stay empty until a run — by design)."""
        results_inner = QWidget()
        ri = QVBoxLayout(results_inner)
        ri.setContentsMargins(8, 0, 0, 0)
        ri.setSpacing(2)

        # -- Signals list ------------------------------------------------------
        self.signals_list = self._make_results_list(self._show_results_signals_menu)
        # Clicking a group header folds/unfolds that sub-group (Joint angles etc.).
        self.signals_list.itemClicked.connect(self._on_signal_item_clicked)
        sig_holder = self._wrap_results_list(
            self.signals_list, "analyze/signals_list_height", 120)
        ri.addWidget(self._make_section("Signals", sig_holder, expanded=True, sub=True))

        # -- Events list -------------------------------------------------------
        self.results_events_list = self._make_results_list(self._show_results_events_menu)
        ev_holder = self._wrap_results_list(
            self.results_events_list, "analyze/results_events_list_height", 90)
        ri.addWidget(self._make_section("Events", ev_holder, expanded=True, sub=True))

        # -- Metrics list ------------------------------------------------------
        self.metrics_list = self._make_results_list(self._show_results_metrics_menu)
        met_holder = self._wrap_results_list(
            self.metrics_list, "analyze/metrics_list_height", 90)
        ri.addWidget(self._make_section("Metrics", met_holder, expanded=True, sub=True))

        # -- Ensemble panel (cross-trial mean +/- SD after a NormalizeStep run) -
        from ui.ensemble_panel import EnsemblePanel
        self._ensemble_panel = EnsemblePanel()
        ri.addWidget(self._make_section("Ensemble", self._ensemble_panel,
                                        expanded=False, sub=True))

        sec_results = self._make_section("RESULTS", results_inner, expanded=False)
        self._refresh_results_panels()
        return sec_results

    def _make_results_list(self, menu_slot):
        """A small ``marker-list`` list widget with a custom right-click menu —
        the shared building block of the three RESULTS lists (and a twin of the
        old ``values_list``)."""
        lst = QListWidget()
        lst.setObjectName("marker-list")
        lst.setUniformItemSizes(True)
        lst.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lst.customContextMenuRequested.connect(menu_slot)
        return lst

    def _wrap_results_list(self, lst, settings_key, default_h):
        holder = QWidget()
        h = QVBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(lst)
        self._attach_resize_handle(h, lst, settings_key, default_h, min_h=40)
        return holder

    def _add_group_header(self, lst, text):
        """A non-selectable group sub-header row inside a RESULTS list."""
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QBrush(QColor(TEXT_MUTED)))
        lst.addItem(item)

    def _add_result_item(self, lst, entry, *, indent=False, suffix=""):
        """Add one ResultEntry row; stores ``(kind, key)`` on UserRole. A
        processed (``:filt``) twin is indented under its parent (V3D ORIGINAL/
        PROCESSED). ``suffix`` shows a small status tag (e.g. ● when graphed)."""
        text = ("    " if indent else "") + entry.label + suffix
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, (entry.kind, entry.key))
        if entry.unit:
            item.setToolTip(f"{entry.key}  ·  unit: {entry.unit}")
        else:
            item.setToolTip(entry.key)
        lst.addItem(item)
        return item

    def _build_pipeline_section(self):
        """The processing recipe: an ordered list of FilterStep(s).

        Replaces the old global Filter section. Each step low-passes a chosen set
        of signals and so *creates* "(filtered)" signals that then appear in the
        event/graph pickers. Editing the list re-renders the views via
        ``_on_filter_changed`` (the same re-render the old filter sliders used)."""
        self.pipeline_panel = QWidget()
        pp = QVBoxLayout(self.pipeline_panel)
        pp.setContentsMargins(0, 0, 0, 0)
        pp.setSpacing(4)
        # Header action button: a single "+" (▲▼✕ retired — reorder is now by
        # dragging a row, delete is the row's ✕ / Delete key, edit is the row ✎).
        self.add_step_btn = QPushButton("+")
        self.add_step_btn.setObjectName("small-btn")
        self.add_step_btn.setFixedSize(24, 22)
        self.add_step_btn.setToolTip("Add a step")
        self.add_step_btn.clicked.connect(self._open_add_step)

        # ▶Run now lives in the PIPELINE header (moved here from the retired Metrics
        # header): a pipeline is the recipe, Run executes it and fills RESULTS.
        self.show_btn = QPushButton("▶")
        self.show_btn.setObjectName("run-icon")
        self.show_btn.setCheckable(True)
        self.show_btn.setFixedSize(22, 20)
        self.show_btn.setToolTip("Run analysis (metrics, cards)")
        self.show_btn.toggled.connect(self._on_show_results_toggled)

        # The step list itself: a flat QListWidget where each row carries a
        # custom row widget (number badge + stage badge + 2-line text + hover
        # actions) injected via setItemWidget in _refresh_pipeline_list. Internal
        # drag reorders the recipe (drop -> _on_step_rows_reordered).
        self.step_list = QListWidget()
        self.step_list.setObjectName("file-list")
        self.step_list.itemDoubleClicked.connect(self._edit_pipeline_step)
        self.step_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.step_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.step_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.step_list.model().rowsMoved.connect(self._on_step_rows_reordered)
        # Delete key on the focused list removes the selected step.
        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.step_list)
        del_sc.activated.connect(self._delete_pipeline_step)
        pp.addWidget(self.step_list)
        self._attach_resize_handle(pp, self.step_list, "analyze/step_list_height", 110, min_h=60)

        sec_pipeline = self._make_section(
            "PIPELINE", self.pipeline_panel, expanded=False,
            header_widgets=[self.add_step_btn, self.show_btn],
        )
        self._refresh_pipeline_list()
        return sec_pipeline

    def _build_main(self):
        widget = QWidget()
        vb = QVBoxLayout(widget)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)

        # (The top metric-card strip was removed — computed metrics now live only
        # in RESULTS▸Metrics + the Export/Statistics flow, so the plot area gets
        # the full height. No cards_scroll / pin dashboard any more.)

        # Plot area (resizable splitters built in _rebuild_plot_layout)
        self.plot_container = QWidget()
        self.plot_container_layout = QVBoxLayout(self.plot_container)
        self.plot_container_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_container_layout.setSpacing(0)
        vb.addWidget(self.plot_container, 1)

        # Frame / playback bar pinned to the bottom
        range_bar = QFrame()
        range_bar.setObjectName("statusbar")
        range_bar.setFixedHeight(46)
        range_layout = QHBoxLayout(range_bar)
        range_layout.setContentsMargins(12, 6, 12, 6)
        range_layout.setSpacing(8)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("play-btn")
        self.play_btn.setFixedSize(34, 30)
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self._toggle_playback)

        # Playback rate: real-time (capture rate) vs every frame (slow / precise).
        self.playmode_btn = QPushButton("Capture rate")
        self.playmode_btn.setObjectName("toggle-btn")
        self.playmode_btn.setCheckable(True)
        self.playmode_btn.setFixedHeight(22)
        self.playmode_btn.setToolTip("Playback rate: Capture rate (real-time) / Every frame")
        self.playmode_btn.toggled.connect(self._on_playmode_toggled)
        self._play_every_frame = False

        # Editable current Frame / Time — typing jumps the cursor to that point.
        # Compact flat fields (no spin buttons, minimal width).
        self.frame_spin = QSpinBox()
        self.frame_spin.setObjectName("frame-field")
        self.frame_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.frame_spin.setMinimum(1)
        self.frame_spin.setMaximum(1)
        self.frame_spin.setFixedWidth(44)
        self.frame_spin.setToolTip("Current frame — type to jump")
        self.frame_spin.editingFinished.connect(self._jump_to_frame)
        self.frame_total_lbl = QLabel("/ -")
        self.frame_total_lbl.setStyleSheet(S.label_style(S.TEXT_SECONDARY, 11))
        self.time_spin = QDoubleSpinBox()
        self.time_spin.setObjectName("frame-field")
        self.time_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.time_spin.setDecimals(2)
        self.time_spin.setSuffix("s")
        self.time_spin.setRange(0.0, 0.0)
        self.time_spin.setFixedWidth(54)
        self.time_spin.setToolTip("Current time (s) — type to jump")
        self.time_spin.editingFinished.connect(self._jump_to_time)
        _frame_lbl = QLabel("Frame")
        _frame_lbl.setObjectName("field-label")

        self.frame_slider = TimeRangeSlider()
        self.frame_slider.setEnabled(False)
        self.frame_slider.rangeChanged.connect(self._on_slider_range_changed)
        self.frame_slider.currentChanged.connect(self._set_review_time)

        self.full_range_btn = QPushButton("↔")
        self.full_range_btn.setObjectName("icon-btn")
        self.full_range_btn.setFixedSize(34, 30)
        self.full_range_btn.setToolTip("Reset to full range")
        self.full_range_btn.clicked.connect(self._set_current_full_range)

        self.region_toggle_btn = QPushButton()
        self.region_toggle_btn.setCheckable(True)
        self.region_toggle_btn.setChecked(False)
        self.region_toggle_btn.setFixedSize(18, 18)
        self.region_toggle_btn.setToolTip("Highlight the selected range on all graphs")
        self.region_toggle_btn.toggled.connect(self._on_region_toggle_changed)
        self._style_region_toggle()

        range_layout.addWidget(self.play_btn)
        range_layout.addWidget(self.playmode_btn)
        range_layout.addWidget(_frame_lbl)
        range_layout.addWidget(self.frame_spin)
        range_layout.addWidget(self.frame_total_lbl)
        range_layout.addWidget(self.time_spin)
        range_layout.addWidget(self.frame_slider, 1)
        range_layout.addWidget(self.full_range_btn)
        range_layout.addWidget(self.region_toggle_btn)
        vb.addWidget(range_bar)

        # ←/→ step one frame (when not typing in a field).
        for key, delta in ((Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, +1)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=delta: self._step_frame(d))

        self._set_placeholder("Load files and run analysis")
        self._setup_plots()
        return widget

    def _setup_playback(self):
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._playback_step)
        self.play_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.play_shortcut.activated.connect(self._toggle_playback)
        self.file_tree.installEventFilter(self)
        self.file_tree.viewport().installEventFilter(self)

    def _setup_plots(self):
        self._rebuild_plot_layout()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            # The 3D marker view is persistent (GL context is expensive to
            # recreate); detach it instead of deleting it.
            if widget is not None and widget is self.marker_view:
                widget.setParent(None)
            elif widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _ensure_marker_view(self):
        if self.marker_view is None:
            from ui.marker_view import make_marker_view
            self.marker_view = make_marker_view()
            if hasattr(self.marker_view, "set_owner"):
                self.marker_view.set_owner(self)
            if hasattr(self.marker_view, "marker_picked"):
                self.marker_view.marker_picked.connect(self._on_marker_picked)
            self._apply_appearance_to_view()
        return self.marker_view

    def _ensure_main_split(self):
        """Persistent layout: a horizontal splitter holding the 3D marker view and
        a graph host. The 3D view is added once and never reparented (avoids the
        GL black-flash); each rebuild only swaps the graph host's contents."""
        if getattr(self, "_main_split", None) is not None:
            return
        self._graph_host = QWidget()
        ghl = QVBoxLayout(self._graph_host)
        ghl.setContentsMargins(0, 0, 0, 0)
        ghl.setSpacing(0)
        self._graph_host_layout = ghl
        self._ensure_marker_view()
        self._main_split = QSplitter(Qt.Orientation.Horizontal)
        self._main_split.setObjectName("plot-splitter")
        self._main_split.setChildrenCollapsible(False)
        self._main_split.setHandleWidth(6)
        self._main_split.splitterMoved.connect(self._on_main_split_moved)
        self._apply_split_order()
        self.plot_container_layout.addWidget(self._main_split)

    def _on_main_split_moved(self, *_args):
        """Remember the divider the user dragged so rebuilds don't reset it."""
        if getattr(self, "_main_split", None) is not None:
            self._main_split_user_sizes = self._main_split.sizes()

    def _apply_split_order(self):
        mv = self.marker_view
        if mv is None or getattr(self, "_main_split", None) is None:
            return
        order = [mv, self._graph_host] if self._markers3d_side == "left" \
            else [self._graph_host, mv]
        for i, w in enumerate(order):
            self._main_split.insertWidget(i, w)

    def _size_main_split(self, big_3d=True):
        if getattr(self, "_main_split", None) is None:
            return
        # Honour a user-dragged divider; only fall back to the default ratio
        # the first time (or after the 3D side is swapped).
        if self._main_split_user_sizes is not None \
                and len(self._main_split_user_sizes) == self._main_split.count():
            self._main_split.setSizes(self._main_split_user_sizes)
        else:
            self._main_split.setSizes([900, 600] if self._markers3d_side == "left" else [600, 900])

    def _apply_inner_split_sizes(self, splitter, key, default_sizes):
        """Inner splitters are rebuilt on every layout pass; restore the user's
        last drag for an identical structure (keyed by `key`) instead of resetting
        to the default each time, and keep tracking further drags."""
        saved = self._split_sizes.get(key)
        if saved is not None and len(saved) == len(default_sizes):
            splitter.setSizes(saved)
        else:
            splitter.setSizes(default_sizes)
        splitter.splitterMoved.connect(
            lambda *_a, s=splitter, k=key: self._split_sizes.__setitem__(k, s.sizes()))

    def _clear_graph_host(self):
        lay = getattr(self, "_graph_host_layout", None)
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _apply_appearance_to_view(self):
        """Push the current Appearance colours/size to the 3D marker view."""
        mv = self.marker_view
        if mv is None:
            return
        a = self.appearance
        mv.set_overlay_colors(a.color("overlay/bones"), a.color("overlay/joints"),
                              a.color("overlay/pelvis"))
        mv.set_marker_colors(a.color("marker/color"), a.color("marker/highlight"))
        mv.set_marker_size(a.marker_size())

    def _on_appearance_changed(self):
        """Appearance committed (Apply): re-render graphs with new colours and
        push 3D colours to the marker view."""
        self._apply_appearance_to_view()
        if self.marker_view is not None:
            self._update_model_overlay(self._current_dataset(),
                                       float(getattr(self, "_review_time", 0.0)))
        self._rebuild_plot_layout()

    def set_markers3d_side(self, side):
        side = "left" if side == "left" else "right"
        if side != self._markers3d_side:
            self._markers3d_side = side
            # Panes swap order — drop the remembered divider so the new side
            # gets the default ratio rather than an inverted one.
            self._main_split_user_sizes = None
            self._apply_split_order()
            self._size_main_split()

    # ----- View settings (Settings ▸ View) -----
    def is_3d_view_on(self):
        return self.markers3d_cb.isChecked()

    def set_3d_view_on(self, on):
        self.markers3d_cb.setChecked(bool(on))

    # ----- marker list / coordinate plots -----
    def _refresh_marker_controls(self, dataset):
        if not hasattr(self, "marker_list"):
            return
        markers = dataset.get("markers") if dataset else None
        self.marker_list.blockSignals(True)
        self.marker_list.clear()
        if markers:
            for label in markers["labels"]:
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setForeground(QBrush(QColor(SEL_GREEN)))   # checked = green text
                self.marker_list.addItem(item)
        self.marker_list.blockSignals(False)

    def _selected_marker_index(self):
        if not hasattr(self, "marker_list") or self.marker_list.count() == 0:
            return None
        row = self.marker_list.currentRow()
        if row < 0:
            row = 0
        return row

    def _marker_visible_mask(self):
        n = self.marker_list.count()
        return [self.marker_list.item(i).checkState() == Qt.CheckState.Checked for i in range(n)]

    def _on_marker_item_changed(self, item):
        checked = item.checkState() == Qt.CheckState.Checked
        item.setForeground(QBrush(QColor(SEL_GREEN if checked else TEXT_PRIMARY)))
        if self.marker_view is not None and self.panel_visible.get("markers3d"):
            self.marker_view.set_visible_mask(self._marker_visible_mask())

    def _on_marker_selected(self, row):
        # Selecting a row highlights it in 3D (coordinate graphs are added via
        # the row's right-click menu).
        self._marker_just_selected = True
        if self.marker_view is None:
            return
        if self.panel_visible.get("markers3d") and row >= 0:
            self.marker_view.set_highlight([row])
        elif row < 0:
            self.marker_view.set_highlight([])

    def _on_marker_list_clicked(self, item):
        # Re-clicking the already-selected marker clears the selection/highlight.
        # currentRowChanged fires before itemClicked when the selection changes,
        # so the flag tells "just selected" apart from "re-clicked".
        if self._marker_just_selected:
            self._marker_just_selected = False
            return
        if self.marker_list.row(item) == self.marker_list.currentRow():
            self.marker_list.setCurrentRow(-1)
            if self.marker_view is not None:
                self.marker_view.set_highlight([])

    def _on_marker_picked(self, idx, global_pos):
        """3D marker left-click: toggle orange highlight + offer graph/table."""
        if not hasattr(self, "marker_list") or idx < 0 or idx >= self.marker_list.count():
            return
        if idx == self.marker_list.currentRow():
            self.marker_list.setCurrentRow(-1)
            if self.marker_view is not None:
                self.marker_view.set_highlight([])
            return
        self.marker_list.setCurrentRow(idx)   # highlights via _on_marker_selected
        label = self.marker_list.item(idx).text()
        menu = QMenu(self)
        if label in self._coord_labels():
            menu.addAction("Remove coordinate graph",
                           lambda: self._toggle_coord_marker(label, False))
        else:
            menu.addAction("Plot coordinates",
                           lambda: self._toggle_coord_marker(label, True))
        menu.addAction("View data table", lambda: self._show_marker_table(label))
        menu.exec(global_pos)

    def _on_marker_coord_changed(self):
        self._update_marker_coord_plots()

    def _coord_labels(self, dataset=None):
        """The marker labels with a coordinate graph for a dataset (stored on the
        dataset so they persist per-file and across file switches)."""
        if dataset is None:
            dataset = self._current_dataset()
        if dataset is None:
            return []
        return dataset.setdefault("_coord_labels", [])

    def _show_marker_list_menu(self, pos):
        item = self.marker_list.itemAt(pos)
        if item is None:
            return
        label = item.text()
        coord = self._coord_labels()
        menu = QMenu(self)
        if label in coord:
            menu.addAction("Remove coordinate graph", lambda: self._toggle_coord_marker(label, False))
        else:
            menu.addAction("Plot coordinates", lambda: self._toggle_coord_marker(label, True))
        if coord:
            menu.addAction("Clear all coordinate graphs", self._clear_coord_markers)
        menu.addSeparator()
        menu.addAction("View data table", lambda: self._show_marker_table(label))
        menu.exec(self.marker_list.viewport().mapToGlobal(pos))

    # ----- numeric time-series tables (right-click any plottable data) -----
    def _open_data_table(self, title, time, columns):
        """Show a numbers table for a time series. Non-modal so playback/other
        windows keep working; we keep refs so the dialogs aren't GC'd."""
        cols = [(n, a) for n, a in columns if a is not None and len(a)]
        if time is None or not len(time) or not cols:
            return
        if not hasattr(self, "_data_table_dialogs"):
            self._data_table_dialogs = []
        dlg = DataTableDialog(self, title, time, cols)
        dlg.finished.connect(lambda *_: self._data_table_dialogs.remove(dlg)
                             if dlg in self._data_table_dialogs else None)
        self._data_table_dialogs.append(dlg)
        dlg.show()

    def _show_marker_table(self, label):
        dataset = self._current_dataset()
        markers = dataset.get("markers") if dataset else None
        if not markers or label not in markers["labels"]:
            return
        idx = markers["labels"].index(label)
        xyz = self._marker_display_data(markers)[idx]
        self._open_data_table(
            f"Marker: {label}", markers["time"],
            [("X (mm)", xyz[:, 0]), ("Y (mm)", xyz[:, 1]), ("Z (mm)", xyz[:, 2])])

    def _show_angle_table(self, name):
        dataset = self._current_dataset()
        res = dataset.get("model_result") if dataset else None
        angles = res.get("angles") if res else None
        if not angles or name not in angles:
            return
        self._open_data_table(f"Angle: {name}", res["time"], [(f"{name} (deg)", angles[name])])

    def _plate_count(self, dataset):
        """Number of force plates in ``dataset`` (>=2 means per-plate signals
        exist); 1 for ordinary single-plate / bare-key files."""
        if not dataset:
            return 1
        return int(dataset.get("n_force_plates", 1) or 1)

    def _active_force(self, dataset, comp):
        """The active plate's array for force/COP ``comp`` (fx/fy/fz/cop_ap/cop_ml).

        For multi-plate files this returns ``fp{active}:comp``; otherwise (single
        plate, or the key is missing) it falls back to the bare key — so single-
        plate files and a plate-1 selection behave exactly as before."""
        if dataset is None:
            return None
        if self._plate_count(dataset) >= 2:
            key = f"fp{self._active_plate}:{comp}"
            if key in dataset:
                return dataset[key]
        return dataset.get(comp)

    #: Per-plate raw channels shown in each FP group: (component, display label).
    #: COP X/Y are the raw plate-local channels (cop_ap/cop_ml stored keys); COP
    #: is their resultant. Built as catalog keys ``fp{p}:<component>``.
    _PLATE_CHANNELS = [
        ("fx", "FX"), ("fy", "FY"), ("fz", "FZ"),
        ("cop", "COP"), ("cop_ap", "COP X"), ("cop_ml", "COP Y"),
    ]

    def _refresh_force_controls(self, dataset):
        """(Re)build the per-plate RAW toggle groups + analysis-plate selector.

        One collapsible ``FP{p}`` group per force plate, each with FX/FY/FZ/COP/
        COP X/COP Y toggles keyed by the catalog signal keys (``fp{p}:fx`` …), so
        toggling one plots that plate's raw channel. The analysis-plate combo
        (shown only for multi-plate files) chooses which plate the analysis/metrics
        use. Mirrors :meth:`_refresh_marker_controls`; same call sites."""
        if not hasattr(self, "force_groups_holder"):
            return
        count = self._plate_count(dataset) if dataset else 0
        if dataset is None or not dataset.get("force_signal_keys"):
            count = 0
        if self._active_plate > max(count, 1):
            self._active_plate = 1

        # Drop the previous per-plate toggles (registrations + widgets), keeping
        # any check states so a re-select of the same file preserves them.
        prev = {k: cb.isChecked() for k, cb in self.panel_checks.items()
                if k in getattr(self, "_plate_toggle_keys", set())}
        for k in getattr(self, "_plate_toggle_keys", set()):
            self.panel_checks.pop(k, None)
            self.panel_visible.pop(k, None)
        while self.force_groups_holder.count():
            child = self.force_groups_holder.takeAt(0)
            w = child.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._plate_toggle_keys = set()

        for p in range(1, count + 1):
            items = []
            for comp, label in self._PLATE_CHANNELS:
                key = f"fp{p}:{comp}"
                items.append((key, label, prev.get(key, False)))
                self._plate_toggle_keys.add(key)
            group = self._checkbox_group(items)
            self.force_groups_holder.addWidget(
                self._make_section(f"FP{p}", group, expanded=False, sub=True))

    def _cop_ap_ml(self, dataset):
        """Plate-1 raw COP channels ``(x, y)`` for any remaining bare-key view path.

        ``cop_ap`` holds the plate-local X channel, ``cop_ml`` the Y, returned
        as-is (the global AP/ML swap was retired). Analysis no longer routes COP
        through here — a Metric step picks its plate via its input key (fp2:cop)."""
        if dataset is None:
            return None, None
        return (self._active_force(dataset, "cop_ap"),
                self._active_force(dataset, "cop_ml"))

    def _show_data_series_table(self, key):
        """Per-plate force/COP checkbox right-click → numeric table for that key."""
        dataset = self._current_dataset()
        if dataset is None or "time" not in dataset:
            return
        from core import signals
        try:
            vals = signals.signal_series(dataset, key)
        except (ValueError, KeyError):
            return
        label, unit = label_for(key), unit_for(key)
        col = f"{label} ({unit})" if unit else label
        self._open_data_table(label, dataset["time"], [(col, vals)])

    def _toggle_coord_marker(self, label, add):
        coord = self._coord_labels()
        if add and label not in coord:
            coord.append(label)
        elif not add and label in coord:
            coord.remove(label)
        self._rebuild_plot_layout()

    def _clear_coord_markers(self):
        dataset = self._current_dataset()
        if dataset is not None:
            dataset["_coord_labels"] = []
        self._rebuild_plot_layout()

    # ----- RESULTS panels (Signals / Events / Metrics) --------------------
    def _build_results(self, dataset):
        """Call the engine to compose the by-type result lists for ``dataset``.

        Cached on ``dataset["_results_model"]`` keyed by ``results_token`` (recipe
        + subject), the same cache pattern as ``model_result``/events. ▶Run is the
        trigger that supplies ``run_result`` (and thus the metric list); before a
        run the metric list is empty — correct, nothing computed yet."""
        from core import results_model
        if dataset is None:
            return {"signal": [], "event": [], "metric": []}
        markers = dataset.get("markers")
        disp = self._marker_display_data(markers) if markers else None
        angle_result = self._angle_result_for(dataset)
        run_result = self._last_run_result if dataset.get("analysis") else None
        token = results_model.results_token(self.pipeline, self._subject_for(dataset))
        # Re-use the cache only when the run_result identity also matches (the token
        # ignores run output), so a fresh ▶Run always repopulates metrics.
        cached = dataset.get("_results_model")
        if cached and cached.get("_token") == token and cached.get("_run") is run_result:
            return cached["data"]
        data = results_model.build_results(
            dataset, self.pipeline, marker_disp=disp,
            angle_result=angle_result, run_result=run_result)
        dataset["_results_model"] = {"_token": token, "_run": run_result, "data": data}
        return data

    def _refresh_results_panels(self, dataset=None):
        """(Re)populate the three RESULTS lists for the current dataset.

        Signals/Events are available even before a run (they list what the recipe
        *would* produce); Metrics fill in after ▶Run. Grouped by ResultEntry.group
        with a non-selectable header row; ``:filt`` twins indented under parents."""
        if not hasattr(self, "signals_list"):
            return
        if dataset is None:
            dataset = self._current_dataset()
        data = self._build_results(dataset)
        self._populate_signals_list(dataset, data["signal"])
        self._populate_events_list(data["event"])
        self._populate_metrics_list(data["metric"])
        self._refresh_ensemble_panel()

    def _populate_signals_list(self, dataset, entries):
        """Render RESULTS·Signals — only pipeline-produced signals, grouped.

        The engine's results_model now emits ONLY produced signals (raw lives in
        the RAW SIGNALS panel), in four groups: "Processed signals" / "Joint
        angles" / "Derived signals" / "COP trajectory". Each group gets a header
        row; a group in ``self._collapsed_sig_groups`` (Joint angles by default)
        folds its rows behind a ▸ toggle so a many-angle model stays tidy. An empty
        pipeline → empty list (the correct "nothing computed yet" state)."""
        self.signals_list.clear()
        if not entries:
            return
        rel = self._angle_reliability(dataset) if dataset else {}
        # Group, preserving catalog order.
        groups = {}
        order = []
        for e in entries:
            if e.group not in groups:
                groups[e.group] = []
                order.append(e.group)
            groups[e.group].append(e)
        for group in order:
            members = groups[group]
            collapsed = group in self._collapsed_sig_groups
            # Header: a ▸/▾ disclosure for foldable groups, with a count when folded
            # so the user knows how much is hidden. Clicking toggles (wired below).
            arrow = ("▸ " if collapsed else "▾ ")
            label = arrow + group + (f"   ({len(members)})" if collapsed else "")
            self._add_sig_group_header(self.signals_list, group, label)
            if collapsed:
                continue
            for e in members:
                indent = (e.origin == "processed")
                suffix = "   ●" if self._is_signal_graphed(e.key) else ""
                item = self._add_result_item(self.signals_list, e,
                                             indent=indent, suffix=suffix)
                # Low-confidence joint-angle channels get a ⚠ + muted text/tooltip.
                if e.key.startswith("angle:"):
                    name = e.key.split(":", 1)[1]
                    info = self._reliability_for_channel(rel, name)
                    if info.get("level") == "low":
                        item.setText(item.text() + "   ⚠")
                        item.setForeground(QBrush(QColor(TEXT_MUTED)))
                        item.setToolTip(self._low_confidence_tooltip(info))

    def _add_sig_group_header(self, lst, group, label):
        """A foldable group header row in RESULTS·Signals.

        Like :meth:`_add_group_header` but keeps the group name on the item's
        UserRole (tagged ``("group", group)``) so :meth:`_on_signal_item_clicked`
        can toggle its collapse state. The row itself stays unselectable for
        data actions but remains clickable for the fold."""
        item = QListWidgetItem(label)
        # Enabled (so a click registers) but not selectable as a data row.
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setForeground(QBrush(QColor(TEXT_MUTED)))
        item.setData(Qt.ItemDataRole.UserRole, ("group", group))
        lst.addItem(item)
        return item

    def _on_signal_item_clicked(self, item):
        """Clicking a RESULTS·Signals group header folds/unfolds that group."""
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or data[0] != "group":
            return
        group = data[1]
        if group in self._collapsed_sig_groups:
            self._collapsed_sig_groups.discard(group)
        else:
            self._collapsed_sig_groups.add(group)
        self._refresh_results_panels(self._current_dataset())

    def _populate_events_list(self, entries):
        self.results_events_list.clear()
        for e in entries:
            label = e.key.split(":", 1)[1] if e.key.startswith("event:") else e.key
            if label in self._hidden_event_labels:
                continue
            self._add_result_item(self.results_events_list, e)

    def _populate_metrics_list(self, entries):
        self.metrics_list.clear()
        if not entries:
            return
        run = self._last_run_result or {}
        by_name = {m.get("name"): m for m in run.get("metrics", [])}
        for e in entries:
            name = e.key.split(":", 1)[1] if e.key.startswith("metric:") else e.key
            m = by_name.get(name)
            suffix = ""
            if m is not None:
                val = m.get("value")
                if val is not None and np.isfinite(val):
                    suffix = f"   {val:.3g}" + (f" {e.unit}" if e.unit else "")
                if m.get("n", 1) and m.get("n") > 1:
                    suffix += f"   (n={m['n']})"
            item = self._add_result_item(self.metrics_list, e, suffix=suffix)
            item.setData(Qt.ItemDataRole.UserRole, ("metric", name))

    def _refresh_ensemble_panel(self):
        """Update the EnsemblePanel with normalized epoch data from all checked
        datasets that have a ``_run_result`` from the first NormalizeStep in the
        pipeline. Clears the panel when no NormalizeStep is present, no run data
        is available yet, or the file tree is not yet constructed."""
        panel = getattr(self, "_ensemble_panel", None)
        if panel is None:
            return
        if not hasattr(self, "file_tree"):
            panel.set_sources([])
            return
        from core.pipeline import NormalizeStep
        # Find the first enabled NormalizeStep in the pipeline.
        norm_step = next(
            (s for s in self.pipeline.steps
             if isinstance(s, NormalizeStep) and getattr(s, "enabled", True)),
            None)
        if norm_step is None or not norm_step.name:
            panel.set_sources([])
            return
        norm_name = norm_step.name
        sources = []
        for i in self._checked_dataset_indexes():
            ds = self.datasets[i]
            run = ds.get("_run_result")
            if run is None:
                continue
            normalized = run.get("normalized", {})
            nd = normalized.get(norm_name)
            if nd is not None:
                sources.append((ds.get("name", f"trial_{i}"), nd))
        # Show the step name in the panel title so it's clear which NormalizeStep
        # is being displayed (avoids silent "first step only" confusion).
        signal_key = getattr(norm_step, "input", "") or ""
        panel_title = f"Ensemble — {signal_key} [{norm_name}]" if signal_key else f"Ensemble — [{norm_name}]"
        panel.set_sources(sources, title=panel_title)

    # -- which signals are currently graphed (for the ● tag) ---------------
    def _is_signal_graphed(self, key):
        if key.startswith("angle:"):
            return key.split(":", 1)[1] in self._angle_plots
        if key.startswith("trajectory:"):
            return bool(self._show_traj)
        if key.endswith(FILT_SUFFIX):
            return key in self._signal_views
        return key in self._signal_views or bool(self.panel_visible.get(key))

    # -- right-click menus -------------------------------------------------
    def _show_results_signals_menu(self, pos):
        item = self.signals_list.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        _kind, key = data
        menu = QMenu(self)
        graphed = self._is_signal_graphed(key)
        if key.startswith("angle:"):
            self._add_angle_view_actions(menu, key.split(":", 1)[1])
        elif not key.startswith("trajectory:"):
            self._add_signal_view_actions(menu, key, graphed)
        else:
            # COP-path (2-D) — can't share a time figure; keep a plain toggle.
            if graphed:
                menu.addAction("Remove from view", lambda: self._unview_signal(key))
            else:
                menu.addAction("View as graph", lambda: self._view_signal(key))
        menu.addSeparator()
        menu.addAction("View as value table", lambda: self._show_signal_table(key))
        menu.exec(self.signals_list.viewport().mapToGlobal(pos))

    def _add_target_figure_submenu(self, menu, title, figures, on_pick):
        """Add a "<title> ▸" submenu listing each ``(group_id, member_keys)`` in
        ``figures`` as a row; picking a row calls ``on_pick(group_id)``. Skipped
        entirely when there is no compatible figure to join."""
        if not figures:
            return
        sub = menu.addMenu(title)
        for gid, members in figures:
            label = self._figure_label(members)
            sub.addAction(label, lambda checked=False, g=gid: on_pick(g))

    def _add_angle_view_actions(self, menu, name):
        """View/combine/move actions for a joint-angle channel ``name``. New angle
        figures and "add/move to <existing angle figure>" — angle figures only, so
        units never mix."""
        res = self._angle_result_for(self._current_dataset())
        avail = res.get("angles", {}) if res else {}
        figs = self._angle_figures(avail)
        cur = self._angle_plots.get(name)
        if cur is None:
            menu.addAction("View as graph (new figure)",
                           lambda: self._angle_to_new_figure(name))
            self._add_target_figure_submenu(
                menu, "View as graph — add to", figs,
                lambda gid: self._angle_to_group(name, gid))
        else:
            others = [(g, m) for g, m in figs if g != cur]
            self._add_target_figure_submenu(
                menu, "Move to graph", others,
                lambda gid: self._angle_to_group(name, gid))
            menu.addAction("Move to new figure",
                           lambda: self._angle_to_new_figure(name))
            menu.addAction("Remove from view",
                           lambda: self._set_angle_plot(name, None))

    def _add_signal_view_actions(self, menu, key, graphed):
        """View/combine/move actions for a produced 1-D signal ``key`` (processed/
        derived). Combine targets are other signal figures only."""
        base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
        figs = self._signal_view_figures()
        if graphed:
            cur = self._signal_groups.get(base)
            others = [(g, m) for g, m in figs if g != cur]
            self._add_target_figure_submenu(
                menu, "Move to graph", others,
                lambda gid: self._signal_to_group(key, gid))
            menu.addAction("Move to new figure",
                           lambda: self._signal_to_new_figure(key))
            menu.addAction("Remove from view", lambda: self._unview_signal(key))
        else:
            menu.addAction("View as graph (new figure)",
                           lambda: self._signal_to_new_figure(key))
            self._add_target_figure_submenu(
                menu, "View as graph — add to", figs,
                lambda gid: self._signal_to_group(key, gid))

    def _show_results_events_menu(self, pos):
        item = self.results_events_list.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        _kind, key = data
        label = key.split(":", 1)[1] if key.startswith("event:") else key
        menu = QMenu(self)
        # Delete = view-level removal (hide its lines + drop the list row). The
        # Detect step is kept; re-running ▶Run regenerates the event.
        menu.addAction("Delete (from graphs and list)",
                       lambda: self._delete_event_view(label))
        menu.addAction("View instances table",
                       lambda: self._show_event_instances_table(label))
        menu.exec(self.results_events_list.viewport().mapToGlobal(pos))

    def _show_results_metrics_menu(self, pos):
        item = self.metrics_list.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        _kind, name = data
        menu = QMenu(self)
        menu.addAction("View as value table",
                       lambda: self._show_metric_table(name))
        menu.exec(self.metrics_list.viewport().mapToGlobal(pos))

    # -- signal view actions ----------------------------------------------
    def _view_signal(self, key):
        """Show a 1-D force/COP/derived signal key as a time plot. A ``:filt``
        key also implies showing its parent plot so the twin curve has a host."""
        if key.startswith("trajectory:"):
            self._show_traj = True   # drives the 2-D COP-path plot
        else:
            self._signal_views.add(key)
            if key.endswith(FILT_SUFFIX):
                self._signal_views.add(key[: -len(FILT_SUFFIX)])
        self._rebuild_plot_layout()   # rebuild also refreshes the RESULTS lists

    def _unview_signal(self, key):
        if key.startswith("trajectory:"):
            self._show_traj = False
        else:
            self._signal_views.discard(key)
        self._rebuild_plot_layout()

    def _prune_signal_views(self):
        """Drop "View as graph" selections the current recipe no longer produces.

        A ``:filt`` view is only valid while a Filter step still targets that key;
        the COP-path view only while a Trajectory step exists. Raw signal views
        always survive (they're inputs). Called on every pipeline change."""
        valid_filt = set(self.pipeline.filtered_keys()) if self.pipeline else set()
        keep = set()
        for k in self._signal_views:
            if k.endswith(FILT_SUFFIX):
                if k in valid_filt:
                    keep.add(k)
            else:
                keep.add(k)
        self._signal_views = keep
        if self._show_traj and (self.pipeline is None
                                or not self.pipeline.trajectory_steps()):
            self._show_traj = False

    def _signal_view_plot_keys(self):
        """The 1-D signal keys that need a time plot built for them (from the
        RESULTS·Signals "View as graph" set). A ``:filt`` view reduces to its
        parent key (the twin draws on the parent's plot); angle/marker/trajectory
        keys have their own plot paths and are excluded here."""
        keys = []
        for k in self._signal_views:
            if k.startswith(("angle:", "marker:", "trajectory:")):
                continue
            base = k[: -len(FILT_SUFFIX)] if k.endswith(FILT_SUFFIX) else k
            if base not in keys:
                keys.append(base)
        return keys

    def _show_signal_table(self, key):
        """Right-click → numeric value table for any signal key (incl. ``:filt``,
        ``fp{n}:*``, ``angle:*``), resolved through a Workspace so processed twins
        work too."""
        dataset = self._current_dataset()
        if dataset is None or "time" not in dataset:
            return
        try:
            vals = Workspace(dataset, pipeline=self.pipeline,
                             marker_disp=self._marker_display_data(dataset.get("markers")),
                             angle_result=self._angle_result_for(dataset),
                             metrics=self._subject_metrics(dataset)).series(key)
        except Exception:
            import logging
            logging.getLogger("analysis").exception(
                "value table: could not resolve signal %r (no data shown)", key)
            return
        label, unit = label_for(key), unit_for(key)
        col = f"{label} ({unit})" if unit else label
        self._open_data_table(label, dataset["time"], [(col, vals)])

    # -- event view actions -----------------------------------------------
    def _delete_event_view(self, label):
        """Hide an event from the graphs and the RESULTS·Events list (view-level).

        Records the label as hidden so the lines + list row disappear; ▶Run clears
        the hidden set, so re-running regenerates the event (the Detect step is
        never touched)."""
        self._hidden_event_labels.add(label)
        self._rebuild_plot_layout()   # redraws events (hidden skipped) + RESULTS

    def _show_event_instances_table(self, label):
        """A frame/time table of every detected instance of ``label``."""
        dataset = self._current_dataset()
        if dataset is None:
            return
        frames = events_compute.event_frames(dataset, label, self.pipeline)
        if frames is None or not len(frames):
            QMessageBox.information(self, label, "No instances detected.")
            return
        t = np.asarray(dataset["time"], dtype=float)
        times = np.array([t[i] for i in frames if 0 <= i < len(t)], dtype=float)
        fr = np.array([i + 1 for i in frames if 0 <= i < len(t)], dtype=float)
        # DataTableDialog wants a "time" axis + named columns: use the instance
        # index as the row clock and show frame/time as columns.
        idx = np.arange(1, len(times) + 1, dtype=float)
        self._open_data_table(f"{label} — instances", idx,
                              [("Frame", fr), ("Time (s)", times)])

    # -- metric view actions ----------------------------------------------
    def _show_metric_table(self, name):
        """Per-cycle table for a metric (cycles + mean ± SD when cyclic), else its
        single value. Reads the last ▶Run's full metric dict."""
        run = self._last_run_result or {}
        m = next((x for x in run.get("metrics", []) if x.get("name") == name), None)
        if m is None:
            QMessageBox.information(self, name, "Run analysis (▶) first to compute this metric.")
            return
        unit = m.get("unit", "")
        cycles = m.get("cycles")
        if cycles is not None and len(cycles):
            arr = np.asarray(cycles, dtype=float)
            idx = np.arange(1, len(arr) + 1, dtype=float)
            self._open_data_table(
                f"{name} (per cycle)", idx,
                [(f"{name} ({unit})" if unit else name, arr)])
            mean, sd, n = m.get("mean"), m.get("sd"), m.get("n")
            QMessageBox.information(
                self, name,
                f"{name}\nmean ± SD: {mean:.4g} ± {sd:.4g} {unit}  (n={n})")
        else:
            val = m.get("value")
            txt = "—" if (val is None or not np.isfinite(val)) else f"{val:.6g} {unit}"
            QMessageBox.information(self, name, f"{name}\nvalue: {txt}")

    def _set_angle_plot(self, name, mode):
        """Remove (``mode=None``) or assign a figure-group id to an angle channel.
        ``mode`` may be an int group id, or None to drop it from view."""
        if mode is None:
            self._angle_plots.pop(name, None)
        else:
            self._angle_plots[name] = int(mode)
        self._rebuild_plot_layout()   # rebuild refreshes the ● "graphed" tag too

    def _clear_angle_graphs(self):
        self._angle_plots = {}
        self._rebuild_plot_layout()

    # ----- figure groups (which signals share one graph) -------------------
    def _alloc_group_id(self):
        gid = self._next_group_id
        self._next_group_id = gid + 1
        return gid

    def _migrate_plot_groups(self):
        """Convert any legacy string angle modes ("combined"/"separate") to int
        group ids: every "combined" angle shares ONE figure; each "separate" gets
        its own. Idempotent — a no-op once all values are ints."""
        if not any(isinstance(v, str) for v in self._angle_plots.values()):
            return
        combined_gid = None
        for name, mode in list(self._angle_plots.items()):
            if isinstance(mode, int):
                continue
            if mode == "combined":
                if combined_gid is None:
                    combined_gid = self._alloc_group_id()
                self._angle_plots[name] = combined_gid
            else:                       # "separate" / unknown -> own figure
                self._angle_plots[name] = self._alloc_group_id()

    def _angle_figures(self, avail=None):
        """Ordered ``[(group_id, [angle_names])]`` for graphed angle channels
        (limited to ``avail`` when given), grouped by figure id in first-seen
        order. Names within a figure are sorted for a stable display order."""
        self._migrate_plot_groups()
        figs, order = {}, []
        for name, gid in self._angle_plots.items():
            if avail is not None and name not in avail:
                continue
            if gid not in figs:
                figs[gid] = []
                order.append(gid)
            figs[gid].append(name)
        return [(gid, sorted(figs[gid])) for gid in order]

    def _signal_group_id(self, key):
        """Figure-group id for a signal-view key (its base, sans ``:filt``);
        assigns a fresh own-figure id on first use so an un-grouped signal keeps
        the default one-plot-per-signal behaviour."""
        base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
        gid = self._signal_groups.get(base)
        if gid is None:
            gid = self._alloc_group_id()
            self._signal_groups[base] = gid
        return gid

    def _signal_view_figures(self):
        """Ordered ``[(group_id, [base_keys])]`` for graphed signal-view keys
        (the same base keys as :meth:`_signal_view_plot_keys`), grouped by figure
        id in first-seen order, keys sorted within a figure."""
        figs, order = {}, []
        for key in self._signal_view_plot_keys():
            gid = self._signal_group_id(key)
            if gid not in figs:
                figs[gid] = []
                order.append(gid)
            figs[gid].append(key)
        return [(gid, sorted(figs[gid])) for gid in order]

    @staticmethod
    def _figure_label(member_keys):
        """Human label for a figure given its member signal keys: the members'
        labels joined with ' + ', trimmed if very long (for menu rows)."""
        labels = [label_for(k) for k in member_keys]
        text = " + ".join(labels)
        return text if len(text) <= 48 else text[:45] + "…"

    def _angle_to_group(self, name, gid):
        self._angle_plots[name] = int(gid)
        self._rebuild_plot_layout()

    def _angle_to_new_figure(self, name):
        self._angle_plots[name] = self._alloc_group_id()
        self._rebuild_plot_layout()

    def _signal_to_group(self, key, gid):
        """View ``key`` (if not already) and put it in figure ``gid``."""
        base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
        self._view_signal(key)            # ensures membership + rebuild
        self._signal_groups[base] = int(gid)
        self._rebuild_plot_layout()

    def _signal_to_new_figure(self, key):
        base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
        self._signal_groups[base] = self._alloc_group_id()
        self._view_signal(key)

    def _figure_groups_for_save(self):
        """Serialisable figure-group state (angle + signal group ids) for the
        project manifest. Migrates legacy angle modes to ids first."""
        self._migrate_plot_groups()
        return {"angles": {n: int(g) for n, g in self._angle_plots.items()},
                "signals": {k: int(g) for k, g in self._signal_groups.items()},
                "next": int(self._next_group_id)}

    def _restore_figure_groups(self, data):
        """Restore figure groups from a manifest. Back-compat: a project saved
        before figure groups existed has no block -> no angle graphs were ever
        persisted, and each restored signal view falls back to its own figure."""
        data = data or {}
        self._angle_plots = {n: int(g) for n, g in (data.get("angles") or {}).items()}
        self._signal_groups = {k: int(g) for k, g in (data.get("signals") or {}).items()}
        ids = list(self._angle_plots.values()) + list(self._signal_groups.values())
        self._next_group_id = max([int(data.get("next", 1))] + [i + 1 for i in ids])

    def _coord_marker_indexes(self, dataset=None):
        """Indices (in this dataset) of the markers the user chose to plot —
        resolved from the per-dataset coord labels (missing labels skipped)."""
        if dataset is None:
            dataset = self._current_dataset()
        markers = dataset.get("markers") if dataset else None
        if not markers:
            return []
        labels = markers["labels"]
        out = []
        for lab in self._coord_labels(dataset):
            if lab in labels:
                out.append(labels.index(lab))
        return out

    def _build_marker_coord_plot(self, dataset, idx):
        markers = dataset["markers"]
        label = markers["labels"][idx] if idx < len(markers["labels"]) else f"M{idx}"
        plot = self._new_plot_widget(f"Marker: {label}", key="markercoord", is_time_plot=True)
        plot._coord_label = label
        plot.setLabel("left", "mm", color=GRAPH_FG, size="9pt")
        plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
        curves = {
            "X": plot.plot(pen=pg.mkPen("#D86A3A", width=1.5)),
            "Y": plot.plot(pen=pg.mkPen("#3B8FD9", width=1.5)),
            "Z": plot.plot(pen=pg.mkPen("#1D9E75", width=1.5)),
        }
        self._coord_curves[idx] = (plot, curves)
        self._add_review_cursor(plot)
        self._fill_coord_curves(dataset, idx, curves)
        return plot

    def _force_filter_spec(self):
        """The COP/force FilterSpec from the pipeline, or None when none targets it.

        The global filter toggle no longer drives this: the FilterSpec comes from
        whichever pipeline FilterStep targets the COP signal (``cop_ap``). With no
        such step the COP/force signals are analysed and plotted raw."""
        return self.pipeline.filter_spec_for("cop_ap")

    def _marker_filter_spec(self):
        """The marker FilterSpec from the pipeline, or None when untargeted.

        Sourced from whichever pipeline FilterStep has its marker target set;
        no step => markers display/analyse raw."""
        return self.pipeline.marker_filter_spec()

    def _marker_display_data(self, markers):
        """Return the marker positions to display — filtered (per the Markers
        filter group) or raw. Cached on the markers dict; raw is preserved.

        Filtering now goes through FilterSpec.apply_marker (core.signals), but
        the on-dict cache (``_filt_sig`` / ``data_filt``) is unchanged so the
        invalidation/performance work from earlier rounds is preserved: the same
        settings yield the same cache key and skip recomputation."""
        if not markers:
            return None
        spec = self._marker_filter_spec()
        if spec is None:
            return markers["data"]
        sig = spec.cache_key()
        if markers.get("_filt_sig") != sig or markers.get("data_filt") is None:
            markers["data_filt"] = spec.apply_marker(markers["data"], markers["rate"])
            markers["_filt_sig"] = sig
        return markers["data_filt"]

    def _fill_coord_curves(self, dataset, idx, curves):
        markers = dataset["markers"]
        mt = markers["time"]
        xyz = self._marker_display_data(markers)[idx]
        for k, axis in (("X", 0), ("Y", 1), ("Z", 2)):
            if self.marker_axis_btns[k].isChecked():
                curves[k].setData(mt, xyz[:, axis])
            else:
                curves[k].setData([], [])

    def _update_marker_coord_plots(self):
        dataset = self._current_dataset()
        if not dataset or not dataset.get("markers"):
            return
        for idx, (_plot, curves) in getattr(self, "_coord_curves", {}).items():
            self._fill_coord_curves(dataset, idx, curves)

    # ----- joint-angle model (folder-based: a static calibrates trials in its
    # folder and all sub-folders; the nearest-ancestor static wins) -----
    def _nearest_static(self, folder):
        """The static dataset whose folder is the nearest ancestor of (or equal
        to) ``folder`` — i.e. the static that covers this folder subtree."""
        path = tuple(folder or ())
        while True:
            for d in self.datasets:
                if d.get("role") == "static" and tuple(d.get("folder") or ()) == path:
                    return d
            if not path:
                return None
            path = path[:-1]

    def _dataset_model(self, dataset):
        """The model that produced this dataset's model_result: its own model for
        a static, or its nearest-ancestor static's model for a dynamic trial."""
        if dataset is None:
            return None
        if dataset.get("role") == "static":
            return dataset.get("model")
        static = self._nearest_static(dataset.get("folder"))
        return static.get("model") if static else None

    def _current_static(self):
        """The static dataset that calibrates the current selection."""
        cur = self._current_dataset()
        if cur is None:
            return None
        if cur.get("role") == "static":
            return cur
        return self._nearest_static(cur.get("folder"))

    def _checked_static_datasets(self):
        return [self.datasets[i] for i in self._checked_static_indexes()]

    def _invalidate_models(self):
        """Drop all cached joint-angle results so they recompute (lazily) against
        the current folder layout / models. Cheap (recompute is cached)."""
        for d in self.datasets:
            d.pop("model_result", None)
            d.pop("model_label_map", None)
            d.pop("_model_token", None)

    def _angle_reliability(self, dataset):
        """Per-channel reliability of this dataset's joint-angle outputs.

        Static (data-independent) for a given model, so we compute it ONCE via
        ``core.marker_model.angle_reliability`` and cache it on the model object
        (``model._angle_reliability_cache``). Returns a dict
        ``{channel: {"level": "high"|"low", "reason": str}}`` or ``{}`` when no
        model is available -- callers then see every channel as "high"."""
        model = self._dataset_model(dataset)
        if model is None:
            return {}
        cached = getattr(model, "_angle_reliability_cache", None)
        if cached is not None:
            return cached
        try:
            from core.marker_model import angle_reliability
            cached = angle_reliability(model)
        except Exception:
            cached = {}
        try:
            model._angle_reliability_cache = cached
        except Exception:
            pass  # e.g. model with __slots__ — just recompute next time
        return cached

    @staticmethod
    def _reliability_for_channel(rel, channel):
        """Look up a channel's reliability, normalizing the channel identifier.

        Values/graph code may carry a bare channel name (``R_ANKLE_angle_AB``)
        or a signal-registry id (``angle:R_ANKLE_angle_AB``); ``angle_reliability``
        keys are bare names. Strip an ``angle:`` prefix, then default to "high"
        for anything not in the dict (graceful — unknown == trustworthy)."""
        if not rel or not channel:
            return {"level": "high", "reason": ""}
        key = channel[len("angle:"):] if channel.startswith("angle:") else channel
        return rel.get(key, {"level": "high", "reason": ""})

    @staticmethod
    def _low_confidence_tooltip(info):
        """User-facing tooltip for a low-confidence angle channel. Leads with a
        clear 'Low confidence' header, then a plain-but-correct explanation."""
        return (
            "Low confidence: inversion/eversion is unreliable without a "
            "medial/lateral foot marker (heel marker ML placement sensitive)."
        )

    def _static_zero_offsets(self, static, model):
        """Neutral-posture joint-angle offsets for "zero to standing pose".

        Returns a dict {angle_channel: degrees} to subtract, or None when the
        feature is off or unavailable. The static trial itself is the reference:
        we average each joint angle over the standing trial. The model is assumed
        already calibrated by the caller. Any failure returns None (raw angles),
        so a beginner who never sets a reference still gets working curves.

        NOTE (policy): the standing reference is the *whole* static trial, which
        assumes the static file is a quiet standing capture (the usual case). We
        do NOT yet auto-pick a 'stable window' of a dynamic trial when no static
        exists -- that lives behind future advanced settings. Without a static
        with markers, this returns None (no zeroing).
        """
        if not static or not static.get("model_zero_static"):
            return None
        if not static.get("markers"):
            return None
        try:
            from core.marker_model import suggest_label_map, static_angle_offsets
            mk = self._markers_for_analysis(static["markers"])
            slm = suggest_label_map(model.cluster_labels(), mk["labels"])
            return static_angle_offsets(model, mk, label_map=slm)
        except Exception:
            return None

    def _markers_for_analysis(self, markers):
        """Markers dict whose ``data`` is the pipeline-filtered marker trajectories
        when a marker FilterStep is active, else the raw markers unchanged.

        Joint angles and COM (via ``model.apply``) are computed from this, so a
        marker FilterStep flows into the KINEMATICS — not only the displayed
        coordinate curves. The raw ``data`` is preserved on the source dict; this
        returns a shallow copy with ``data`` swapped for the filtered array
        (reusing the ``_marker_display_data`` / ``data_filt`` cache)."""
        if not markers or self._marker_filter_spec() is None:
            return markers
        filt = self._marker_display_data(markers)
        if filt is None:
            return markers
        out = dict(markers)
        out["data"] = filt
        return out

    def _ensure_model_result(self, dataset):
        """Lazily calibrate the assigned model and apply it to this trial, caching
        the result. A static uses its own model (segments show in 3D too); a
        dynamic uses its nearest-ancestor static's model. Cheap on a cache hit."""
        if dataset is None or not dataset.get("markers"):
            return
        if dataset.get("role") == "static":
            static, model = dataset, dataset.get("model")
        else:
            static = self._nearest_static(dataset.get("folder"))
            model = static.get("model") if static else None
        if model is None or not static or not static.get("markers"):
            dataset.pop("model_result", None)
            dataset.pop("model_label_map", None)
            dataset.pop("_model_token", None)
            return
        # Cache token includes the zero-to-standing choice AND the marker-filter
        # signature so toggling either forces a recompute. A marker FilterStep must
        # flow into the kinematics (angles + COM), not just the displayed marker
        # curves, so we calibrate AND analyse on the pipeline-filtered marker data.
        mfs = self._marker_filter_spec()
        token = (id(model), bool(static.get("model_zero_static")),
                 mfs.cache_key() if mfs is not None else None)
        if dataset.get("model_result") is not None and dataset.get("_model_token") == token:
            return  # cache hit
        from core.marker_model import suggest_label_map, static_angle_offsets
        try:
            # Calibration is per-subject (cheap); the model object may be shared
            # across subjects, so recalibrate from this subject's static here.
            # Calibrate and analyse on the SAME marker data (filtered when a marker
            # FilterStep is active) so the filter is consistent end to end.
            static_mk = self._markers_for_analysis(static["markers"])
            mk = self._markers_for_analysis(dataset["markers"])
            model.calibrate(static_mk)
            lm = suggest_label_map(model.cluster_labels(), mk["labels"])
            # "Zero to standing pose": if the user turned it on for this static,
            # average the standing trial's joint angles and subtract them so the
            # dynamic curves start from the subject's own neutral. Falls back to
            # no offset (raw angles) on any problem so nothing breaks.
            offsets = self._static_zero_offsets(static, model)
            dataset["model_result"] = model.apply(
                mk, label_map=lm, offsets=offsets)
            dataset["model_label_map"] = lm
            dataset["_model_token"] = token
        except Exception:
            import logging
            logging.getLogger("analysis").exception(
                "joint-angle model failed for trial %r", dataset.get("name"))
            dataset.pop("model_result", None)
            dataset.pop("model_label_map", None)
            dataset.pop("_model_token", None)

    def _angle_result_for(self, dataset):
        """The joint-angle result to feed graphs / events / metrics / run.

        Returns ``model_result`` ONLY when a :class:`ComputeAngleStep` is in the
        recipe — the redesign principle that *the pipeline is the sole source of
        derived data*: angles exist as analysis signals only if a step asks for
        them. Returns ``None`` otherwise, so no angle:* signals appear and the
        joint-angle graphs stay empty. (The 3D segment/joint-centre overlay still
        reads ``dataset["model_result"]`` directly — it is the marker model's
        geometry, not a derived analysis signal, so it is never gated here.)

        When the ComputeAngle step(s) name a subset of joints, only those angles are
        exposed (an empty ``joints`` list = all). This is what makes the dialog's
        per-angle checkboxes actually restrict which ``angle:*`` signals appear."""
        if dataset is None or self.pipeline is None or not self.pipeline.has_angle_step():
            return None
        res = dataset.get("model_result")
        if not res:
            return res
        # Union of the joints named across ComputeAngle steps; empty -> all.
        wanted = set()
        for st in self.pipeline.compute_angle_steps():
            wanted.update(st.joints or [])
        angles = res.get("angles") or {}
        if wanted and angles:
            kept = {k: v for k, v in angles.items() if k in wanted}
            if kept:
                res = dict(res)
                res["angles"] = kept
        return res

    def _model_joint_names(self, dataset):
        """Joint-angle names the assigned model yields for ``dataset`` (e.g.
        ``["RKNEE_FE", ...]``) — for the ComputeAngle step's ``joints`` (exact
        dependency lint). Ensures the model result first; empty if no model."""
        if dataset is None:
            return []
        self._ensure_model_result(dataset)
        res = dataset.get("model_result")
        if not res:
            return []
        return list(res.get("angles", {}).keys())

    def _build_model(self, static=None):
        if static is None:
            static = self._current_static()
        if static is None or not static.get("markers"):
            QMessageBox.information(self, "No static", "Select a static (calibration) file with markers (in this folder or an ancestor).")
            return
        from ui.model_dialog import ModelDialog, DEFAULT_TASK
        dlg = ModelDialog(self, static["markers"], static.get("model"),
                          task=static.get("model_task", DEFAULT_TASK),
                          zero_to_static=static.get("model_zero_static"))
        if dlg.exec():
            static["model"] = dlg.result_model
            # Remember the beginner's motion choice + zero-to-standing toggle so
            # _ensure_model_result can apply the matching static offset. These are
            # UI-side metadata only (the engine model object stays task-agnostic).
            static["model_task"] = dlg.result_task
            static["model_zero_static"] = bool(dlg.result_zero_to_static)
            self.marker_model = dlg.result_model   # becomes the current model for "Assign"
            # Carry the motion choice with the "Assign to checked" default too.
            self.marker_model_task = dlg.result_task
            self.marker_model_zero = bool(dlg.result_zero_to_static)
            self._invalidate_models()
            self._refresh_file_list()              # icon shows assigned state
            self._rebuild_plot_layout()            # angle graph follows the new model

    def _load_model(self, static=None):
        import json
        from core.marker_model import MarkerModel
        if static is None:
            static = self._current_static()
        if static is None:
            QMessageBox.information(self, "No static", "Select a static (calibration) file first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load model", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                model = MarkerModel.from_dict(json.load(f))
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        static["model"] = model
        self.marker_model = model
        self._invalidate_models()
        self._refresh_file_list()
        self._rebuild_plot_layout()

    def _save_model(self, static=None):
        if static is None:
            static = self._current_static()
        model = static.get("model") if static else None
        if model is None:
            return
        import json
        path, _ = QFileDialog.getSaveFileName(self, "Save model", "model.json", "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(model.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _assign_model_to_checked(self, model=None):
        """Assign a model to every checked static (subjects sharing the same
        marker set reuse one model). Defaults to the last built/loaded model."""
        if model is None:
            model = self.marker_model
        if model is None:
            QMessageBox.information(self, "No model", "Build or load a model first.")
            return
        statics = self._checked_static_datasets()
        if not statics:
            QMessageBox.information(self, "No statics checked", "Check the static rows to assign the model to.")
            return
        for d in statics:
            d["model"] = model
            # Share the same motion choice / zero toggle (same marker set).
            if getattr(self, "marker_model_task", None):
                d["model_task"] = self.marker_model_task
                d["model_zero_static"] = bool(getattr(self, "marker_model_zero", False))
            self._invalidate_models()
        self.marker_model = model
        self._refresh_file_list()
        self._rebuild_plot_layout()

    def _build_jointangles_plot(self, dataset, angle_names, title="Joint angles"):
        res = dataset["model_result"]
        rel = self._angle_reliability(dataset)
        # Single-channel figure: the channel name IS the title, so flag a
        # low-confidence channel right in the plot header (no legend is drawn).
        if len(angle_names) == 1 and \
                self._reliability_for_channel(rel, angle_names[0]).get("level") == "low":
            title = f"{title} ⚠"
        plot = self._new_plot_widget(title, key="jointangles", is_time_plot=True)
        plot._angle_names = list(angle_names)
        plot.setLabel("left", "deg", color=GRAPH_FG, size="9pt")
        plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
        # Direction hint: when every plotted channel shares one plane, annotate the
        # y-axis with what +/- means (e.g. top "Flexion", bottom "Extension"), so
        # the angle's sign reads clinically. Mixed-plane figures skip it (ambiguous).
        self._add_angle_direction_labels(plot, angle_names)
        if len(angle_names) > 1:
            plot.addLegend(offset=(-10, 10))
        self.jointangles_plot = plot
        colors = ["#D86A3A", "#3B8FD9", "#1D9E75", "#A86ADE", "#E0A030", "#E05B5B"]
        t = res["time"]
        for i, name in enumerate(angle_names):
            arr = res["angles"].get(name)
            if arr is None:
                continue
            # Flag low-confidence channels (ankle inv/ev & rotation) in the legend
            # with a warning glyph so a plotted curve isn't over-trusted.
            low = self._reliability_for_channel(rel, name).get("level") == "low"
            legend_name = f"{name} ⚠" if low else name
            curve = plot.plot(pen=pg.mkPen(colors[i % len(colors)], width=1.5), name=legend_name)
            curve.setData(t, arr)
            self.c_angles[name] = curve
        self._add_review_cursor(plot)
        return plot

    #: ISB-aligned sign convention (see angle-sign-convention memory): positive
    #: direction is the first word, negative the second. Keyed by plane suffix;
    #: ankle frontal/sagittal differ from the generic joint, so it has its own row.
    _ANGLE_DIR = {
        "FE": ("Flexion", "Extension"),
        "AB": ("Abduction", "Adduction"),
        "IE": ("Internal rot.", "External rot."),
    }
    _ANGLE_DIR_ANKLE = {
        "FE": ("Dorsiflexion", "Plantarflexion"),
        "AB": ("Inversion", "Eversion"),
        "IE": ("Internal rot.", "External rot."),
    }

    def _angle_direction_pair(self, angle_names):
        """``(positive_label, negative_label)`` if every channel shares one plane,
        else ``None``. Joint-aware so the ankle frontal plane reads inv/ev."""
        from ui.analyze_dialogs import _parse_angle
        planes, joints = set(), []
        for name in angle_names:
            _side, joint, plane = _parse_angle(name)
            if plane is None:
                return None
            planes.add(plane)
            joints.append(joint)
        if len(planes) != 1:
            return None
        plane = next(iter(planes))
        ankle = all("ankle" in (j or "").lower() for j in joints)
        table = self._ANGLE_DIR_ANKLE if ankle else self._ANGLE_DIR
        return table.get(plane)

    def _add_angle_direction_labels(self, plot, angle_names):
        """Pin small muted +/- direction words to the top-left / bottom-left of an
        angle plot's view (e.g. top "Flexion", bottom "Extension"). They stay in
        the corner as the view pans/zooms via a range-change reposition slot."""
        pair = self._angle_direction_pair(angle_names)
        if pair is None:
            return
        pos_lbl, neg_lbl = pair
        vb = plot.getPlotItem().getViewBox()
        top = pg.TextItem(pos_lbl, color=S.TEXT_MUTED, anchor=(0, 0))
        bot = pg.TextItem(neg_lbl, color=S.TEXT_MUTED, anchor=(0, 1))
        for it in (top, bot):
            it.setZValue(50)
            f = it.textItem.font()
            f.setPointSize(8)
            it.textItem.setFont(f)
            vb.addItem(it, ignoreBounds=True)

        def _reposition(*_):
            (x0, _x1), (y0, y1) = vb.viewRange()
            top.setPos(x0, y1)
            bot.setPos(x0, y0)

        vb.sigRangeChanged.connect(_reposition)
        # Keep a reference on the plot so the slot/items aren't garbage-collected.
        plot._angle_dir_items = (top, bot, _reposition)
        _reposition()

    def _point_pos(self, name, jc, markers, disp, idx, lm):
        if name in jc:
            v = jc[name][idx]
            return v if np.isfinite(v).all() else None
        actual = lm.get(name, name)
        try:
            mi = markers["labels"].index(actual)
        except ValueError:
            return None
        v = disp[mi][idx]
        return v if np.isfinite(v).all() else None

    def _update_model_overlay(self, dataset, t, idx=None):
        if self.marker_view is None or not self.panel_visible.get("markers3d"):
            return
        res = dataset.get("model_result") if dataset else None
        markers = dataset.get("markers") if dataset else None
        if not res or markers is None:
            self.marker_view.set_overlay(None, None)
            return
        mt = markers["time"]
        if idx is None:
            idx = int(np.searchsorted(mt, float(t))) if len(mt) else 0
            idx = max(0, min(len(mt) - 1, idx))
        jc = res["joint_centers"]
        # Joint spheres: real joint centres only (skip the virtual pelvis points).
        pts = [arr[idx] for name, arr in jc.items()
               if not name.startswith("PELVIS_") and np.isfinite(arr[idx]).all()]
        bones, pelvis = [], []
        model = self._dataset_model(dataset)
        if model is not None:
            lm = dataset.get("model_label_map") or {}
            disp = self._marker_display_data(markers)
            for s in model.segments:
                p0 = self._point_pos(s["proximal"], jc, markers, disp, idx, lm)
                p1 = self._point_pos(s["distal"], jc, markers, disp, idx, lm)
                if p0 is not None and p1 is not None:
                    (pelvis if s["name"] == "PELVIS" else bones).extend([p0, p1])
            # Pelvis body: close a ring through the pelvis landmarks and link each
            # hip joint centre to its ASIS so the pelvis reads as a segment, not
            # one line. pelvis_labels() order = [RASIS, LASIS, LPSIS, RPSIS/sacrum].
            plabs = model.pelvis_labels()
            ring = [self._point_pos(lab, jc, markers, disp, idx, lm) for lab in plabs]
            ring = [p for p in ring if p is not None]
            if len(ring) >= 3:
                for a, b in zip(ring, ring[1:]):
                    pelvis.extend([a, b])
                pelvis.extend([ring[-1], ring[0]])   # close the ring
            for hipname, asis_lab in (("R_HIP", plabs[0] if len(plabs) > 0 else None),
                                      ("L_HIP", plabs[1] if len(plabs) > 1 else None)):
                hip = jc.get(hipname)
                hp = hip[idx] if hip is not None and np.isfinite(hip[idx]).all() else None
                ap = self._point_pos(asis_lab, jc, markers, disp, idx, lm) if asis_lab else None
                if hp is not None and ap is not None:
                    pelvis.extend([hp, ap])
        self.marker_view.set_overlay(np.array(pts) if pts else None,
                                     bones or None, pelvis or None)

    def _new_plot_widget(self, title, key=None, is_time_plot=False):
        view_box = GraphViewBox(self)
        plot = pg.PlotWidget(background=S.GRAPH_BG, viewBox=view_box)
        view_box.plot_widget = plot
        view_box.graph_key = key
        view_box.is_time_plot = is_time_plot
        plot._graph_key = key
        grid = self.appearance.grid_default()
        plot._grid_x = grid
        plot._grid_y = grid
        plot._is_time_plot = is_time_plot
        if hasattr(plot, "setMenuEnabled"):
            plot.setMenuEnabled(False)
        pi = plot.getPlotItem()
        pi.setMenuEnabled(False)
        if is_time_plot:
            # Long trials (minutes × kHz) make every cursor move re-render tens of
            # thousands of points. Peak-downsample + clip-to-view so each repaint
            # only draws ~widget-width visible points → cheap playback.
            pi.setClipToView(True)
            pi.setDownsampling(mode="peak", auto=True)
        plot.setTitle(title, color=S.TEXT_SECONDARY, size="10pt")
        plot.showGrid(x=grid, y=grid, alpha=0.25)
        plot.getAxis("left").setTextPen(pg.mkPen(S.GRAPH_FG))
        plot.getAxis("bottom").setTextPen(pg.mkPen(S.GRAPH_FG))
        return plot

    def _show_graph_context_menu(self, plot, key, global_pos):
        menu = QMenu(self)
        invert_menu = menu.addMenu("Invert Axis")
        vb = plot.getPlotItem().getViewBox()
        invert_x = invert_menu.addAction("X Axis")
        invert_x.setCheckable(True)
        invert_x.setChecked(bool(vb.state.get("xInverted", False)))
        invert_x.toggled.connect(lambda checked, p=plot: p.getPlotItem().getViewBox().invertX(checked))
        invert_y = invert_menu.addAction("Y Axis")
        invert_y.setCheckable(True)
        invert_y.setChecked(bool(vb.state.get("yInverted", False)))
        invert_y.toggled.connect(lambda checked, p=plot: p.getPlotItem().getViewBox().invertY(checked))

        grid_menu = menu.addMenu("Grid")
        grid_x = grid_menu.addAction("X Grid")
        grid_x.setCheckable(True)
        grid_x.setChecked(bool(getattr(plot, "_grid_x", True)))
        grid_x.toggled.connect(lambda checked, p=plot: self._set_graph_grid(p, x=checked))
        grid_y = grid_menu.addAction("Y Grid")
        grid_y.setCheckable(True)
        grid_y.setChecked(bool(getattr(plot, "_grid_y", True)))
        grid_y.toggled.connect(lambda checked, p=plot: self._set_graph_grid(p, y=checked))

        # COP-trajectory plot: toggle the 95% confidence ellipse overlay on/off.
        # (Its AREA is a separate Metric; this only controls the drawing.)
        if key == "traj":
            ell = menu.addAction("95% confidence ellipse")
            ell.setCheckable(True)
            ell.setChecked(getattr(self, "_show_ellipse", True))
            ell.toggled.connect(self._set_show_ellipse)
            evp = menu.addAction("Event markers")
            evp.setCheckable(True)
            evp.setChecked(getattr(self, "_show_traj_events", True))
            evp.toggled.connect(self._set_show_traj_events)

        menu.addAction("Export Image...", lambda: self._export_graph_image(plot))
        menu.addSeparator()
        menu.addAction("Delete Graph", lambda: self._delete_graph(key, plot))
        menu.addAction("Delete all graphs", self._delete_all_graphs)
        menu.exec(global_pos)

    def _set_show_ellipse(self, on):
        """Graph on/off for the 95% confidence ellipse on the COP path. The COP
        path + live marker stay; only the ellipse outline is shown/hidden. The
        ellipse AREA is a separate Metric (unaffected)."""
        self._show_ellipse = bool(on)
        self._render_trajectory(self._current_dataset())

    def _set_show_traj_events(self, on):
        """Graph on/off for event point markers on the COP path."""
        self._show_traj_events = bool(on)
        self._render_trajectory(self._current_dataset())

    def _set_graph_grid(self, plot, x=None, y=None):
        if x is not None:
            plot._grid_x = bool(x)
        if y is not None:
            plot._grid_y = bool(y)
        plot.showGrid(
            x=bool(getattr(plot, "_grid_x", True)),
            y=bool(getattr(plot, "_grid_y", True)),
            alpha=0.25,
        )

    def _delete_graph(self, key, plot=None):
        # On-demand graphs (marker coords / joint angles) have no checkbox — remove
        # them by their stored identifier instead.
        if key == "markercoord" and plot is not None and hasattr(plot, "_coord_label"):
            self._toggle_coord_marker(plot._coord_label, False)
            return
        if key == "jointangles" and plot is not None and getattr(plot, "_angle_names", None):
            for name in plot._angle_names:
                self._angle_plots.pop(name, None)
            self._rebuild_plot_layout()
            return
        # COP trajectory (statokinesigram) — driven by the _show_traj flag.
        if key == "traj" or key.startswith("trajectory:"):
            self._show_traj = False
            self._rebuild_plot_layout()
            return
        # RESULTS "View as graph" signals (raw / processed / derived pipeline
        # outputs) are driven by _signal_views, NOT a RAW SIGNALS checkbox — so the
        # checkbox path below never matched them and "Delete Graph" did nothing.
        # Drop the view (and its filtered twin) and clear any matching RAW toggle.
        # A COMBINED figure holds several members on one plot — remove them ALL so
        # "Delete Graph" clears the whole figure, not just the first member.
        members = [key]
        if plot is not None:
            members = [k for k, p in self._raw_plots.items() if p is plot] or [key]
        if any(k in self._signal_views or f"{k}{FILT_SUFFIX}" in self._signal_views
               for k in members):
            for mk in members:
                self._signal_views.discard(mk)
                self._signal_views.discard(f"{mk}{FILT_SUFFIX}")
                self._signal_groups.pop(mk, None)
                for k in (mk, f"{mk}{FILT_SUFFIX}"):
                    cb = self.panel_checks.get(k)
                    if cb is not None and cb.isChecked():
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
            self._rebuild_plot_layout()
            return
        cb = self.panel_checks.get(key)
        if cb is not None:
            cb.setChecked(False)
            dataset = self._current_dataset()
            if dataset is not None and self.view_mode == "review":
                self._show_range_region(dataset)

    def _delete_all_graphs(self):
        """Remove EVERY data graph, regardless of how it was added: per-plate
        force/COP RAW SIGNALS toggles (+ their filtered twins), the COP
        trajectory, on-demand marker/angle graphs, AND the RESULTS "View as
        graph" signal views (forces/derived outputs). These last live in
        ``_signal_views`` (not a checkbox), so they were previously left behind —
        making "Delete all" clear angles but strand force/derived graphs."""
        keys = ["traj"]
        keys += list(getattr(self, "_plate_toggle_keys", set()))
        keys += [f"{k}:filt" for k in getattr(self, "_plate_toggle_keys", set())]
        for key in keys:
            cb = self.panel_checks.get(key)
            if cb is not None and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
        dataset = self._current_dataset()
        if dataset is not None:
            dataset["_coord_labels"] = []
        self._angle_plots = {}
        self._signal_views = set()   # RESULTS "View as graph" (force/derived) views
        self._signal_groups = {}     # figure-group assignments (no graphs left)
        self._show_traj = False       # COP trajectory is flag-driven, not a checkbox
        self._rebuild_plot_layout()

    def _plot_data_bounds(self, plot, visible_x_only=False):
        x_values = []
        y_values = []
        x_min, x_max = plot.getPlotItem().getViewBox().viewRange()[0]
        for item in plot.getPlotItem().listDataItems():
            x, y = item.getData()
            if x is None or y is None or len(x) == 0 or len(y) == 0:
                continue
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            mask = np.isfinite(x) & np.isfinite(y)
            if visible_x_only:
                mask &= (x >= x_min) & (x <= x_max)
            if not np.any(mask):
                continue
            x_values.append(x[mask])
            y_values.append(y[mask])
        if not x_values or not y_values:
            return None
        xs = np.concatenate(x_values)
        ys = np.concatenate(y_values)
        return float(np.min(xs)), float(np.max(xs)), float(np.min(ys)), float(np.max(ys))

    def _fit_graph_view(self, plot):
        bounds = self._plot_data_bounds(plot)
        if bounds is None:
            plot.getPlotItem().getViewBox().autoRange(padding=0.04)
            return
        x_min, x_max, y_min, y_max = bounds
        self._set_graph_x_range(plot, x_min, x_max, padding=0.04)
        self._set_graph_y_range(plot, y_min, y_max, padding=0.08)

    def _fit_graph_x(self, plot):
        bounds = self._plot_data_bounds(plot)
        if bounds is None:
            return
        x_min, x_max, _, _ = bounds
        self._set_graph_x_range(plot, x_min, x_max, padding=0.02)

    def _fit_graph_y(self, plot):
        bounds = self._plot_data_bounds(plot, visible_x_only=True)
        if bounds is None:
            bounds = self._plot_data_bounds(plot)
        if bounds is None:
            return
        _, _, y_min, y_max = bounds
        self._set_graph_y_range(plot, y_min, y_max, padding=0.08)

    def _set_graph_x_range(self, plot, x_min, x_max, padding=0.02):
        if x_max == x_min:
            delta = abs(x_min) * 0.05 or 1.0
            x_min -= delta
            x_max += delta
        plot.setXRange(x_min, x_max, padding=padding)

    def _set_graph_y_range(self, plot, y_min, y_max, padding=0.08):
        # Force plots carry a y-baseline (0) that the range must always span, so a
        # "fit y" never zooms a flat-but-large signal down to its wobble.
        baseline = getattr(plot, "_y_baseline", None)
        if baseline is not None:
            y_min = min(y_min, baseline)
            y_max = max(y_max, baseline)
        if y_max == y_min:
            delta = abs(y_min) * 0.05 or 1.0
            y_min -= delta
            y_max += delta
        plot.setYRange(y_min, y_max, padding=padding)

    def _fit_time_y_to_visible_x(self):
        for plot in self._time_plots:
            self._fit_graph_y(plot)

    def _export_graph_image(self, plot):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export graph image", "graph.png", "PNG Images (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            exporter = pyqtgraph.exporters.ImageExporter(plot.getPlotItem())
            exporter.export(path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    # --- Pipeline (filter steps) -----------------------------------------
    @staticmethod
    def _plate_label_opts(opts):
        """Present force-plate signals as explicit FP1/FP2 in the step pickers
        (user choice 2026-06-24). The bare keys ``cop/cop_ap/cop_ml/fz/fx/fy`` ARE
        plate 1 (verified identical to ``fp1:*``), so we relabel them "FP1 ..." and
        drop the redundant ``fp1:*`` twins — keeping the bare KEY (canonical, so
        saved steps / defaults still resolve) while the label reads per-plate. Extra
        plates (``fp2:*``) and non-plate signals (angles/markers/time) pass through.
        Files with no per-plate keys (no ``fp1:*``) keep their plain labels."""
        from core.signals import FILT_SUFFIX
        plate_comps = {"cop", "cop_ap", "cop_ml", "fz", "fx", "fy"}

        def _split(k):
            return (k[:-len(FILT_SUFFIX)], True) if k.endswith(FILT_SUFFIX) else (k, False)

        fp1_label = {}
        for k, lbl in opts:
            base, filt = _split(k)
            if base.startswith("fp1:"):
                fp1_label[(base.split(":", 1)[1], filt)] = lbl
        out = []
        for k, lbl in opts:
            base, filt = _split(k)
            if base.startswith("fp1:"):
                continue  # redundant twin of the bare (plate-1) key
            if base in plate_comps and (base, filt) in fp1_label:
                out.append((k, fp1_label[(base, filt)]))
            else:
                out.append((k, lbl))
        return out

    def _filterable_targets(self):
        """``[(key, label), ...]`` of the raw scalar signals a FilterStep may
        low-pass for the current dataset (COP/force/joint angles). Markers are
        handled by the dialog's separate flag, and ``time``/already-filtered keys
        are excluded. Sourced from the shared signal registry so the list always
        matches what the pickers show."""
        from core import signals
        dataset = self._current_dataset()
        if dataset is None:
            # No file yet: offer the always-present COP/force scalar keys so the
            # user can still build a pipeline before loading.
            return [("cop", "COP"), ("cop_ap", "COP AP"), ("cop_ml", "COP ML")]
        res = self._angle_result_for(dataset)
        out = []
        for key, label in signals.signal_catalog(dataset, None, res):
            if key == "time" or key.startswith("marker:") or key.endswith(":filt"):
                continue
            out.append((key, label))
        return self._plate_label_opts(out)

    def _refresh_pipeline_list(self):
        """Redraw the step list from ``self.pipeline``.

        Each row is a custom :class:`PipelineStepRow` widget injected via
        ``setItemWidget``: number badge + stage badge + a two-line label (step
        name on top, parameter summary below) + hover edit/delete + an enable
        toggle. Disabled steps render dimmed. Stage-order problems become a ⚠
        chip on the offending row. The flat QListWidget is kept (its
        InternalMove drag reorders the recipe) — only the row paint changed."""
        if not hasattr(self, "step_list"):
            return
        # Map step index -> warning message (first one wins per row) for ⚠ chips.
        warnings = {}
        try:
            for idx, msg in self.pipeline.data_dependency_warnings():
                warnings.setdefault(idx, msg)
        except Exception:
            warnings = {}

        self.step_list.blockSignals(True)
        self.step_list.clear()
        for i, step in enumerate(self.pipeline.steps):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.step_list.addItem(item)
            row = PipelineStepRow(
                number=i + 1,
                step=step,
                name=self._pipeline_step_name(step),
                summary=self._pipeline_step_summary(step),
                swatch=self._pipeline_row_swatch(step),
                warning=warnings.get(i),
                on_edit=lambda _=False, idx=i: self._edit_step_at(idx),
                on_delete=lambda _=False, idx=i: self._delete_step_at(idx),
                on_toggle=lambda enabled, idx=i: self._toggle_step_at(idx, enabled),
            )
            # Pin the item height to the row's fixed footprint so the list grid
            # stays uniform regardless of summary length.
            hint = row.sizeHint()
            hint.setHeight(PipelineStepRow.ROW_HEIGHT)
            item.setSizeHint(hint)
            self.step_list.setItemWidget(item, row)
        self.step_list.blockSignals(False)

    def _pipeline_row_swatch(self, step):
        """Return a QPixmap colour swatch for a detect step's line colour, else None.

        Detect-event steps keep their leading colour swatch (the line colour used
        on the graph). Other step kinds have no colour, so no swatch."""
        from core.pipeline import DetectEventStep
        color = getattr(step, "color", None) if isinstance(step, DetectEventStep) else None
        if not color:
            return None
        return self._color_swatch(color, size=11).pixmap(11, 11)

    def _pipeline_step_name(self, step):
        """The step's primary (first-line) name — the *what*, no parameters.

        Split out from the old one-line label so the row can show the name on top
        and the parameter summary below (Visual3D-style 2-line rows). Human signal
        names only (``label_for``), never raw catalog keys."""
        from core.pipeline import (FilterStep, DetectEventStep, TrajectoryStep,
                                    MetricStep, ComputeStep, ComputeAngleStep)
        if isinstance(step, ComputeAngleStep):
            return "Joint angles"
        if isinstance(step, TrajectoryStep):
            return "COP trajectory"
        if isinstance(step, MetricStep):
            return step.name or "(unnamed metric)"
        if isinstance(step, ComputeStep):
            return step.name or "(unnamed signal)"
        if isinstance(step, FilterStep):
            bits = []
            if step.targets:
                bits.append(", ".join(label_for(t) for t in step.targets))
            if step.markers:
                bits.append("markers")
            return f"Filter {' + '.join(bits)}" if bits else "Filter"
        if isinstance(step, DetectEventStep):
            return step.label or "(unnamed)"
        return str(step)

    def _pipeline_step_summary(self, step):
        """The step's parameter summary (second-line, muted) — the *how*.

        e.g. ``"10 Hz · Butterworth · order 4"`` for a filter, or
        ``"Fz threshold ↑ 20 N"`` for a detect step. Empty string => no second
        line is drawn. Human signal names only."""
        from core.pipeline import (FilterStep, DetectEventStep, TrajectoryStep,
                                    MetricStep, ComputeStep, ComputeAngleStep)
        if isinstance(step, ComputeAngleStep):
            n = len(step.joints)
            return f"from kinematic model · {n} angles" if n else "from kinematic model"
        if isinstance(step, TrajectoryStep):
            return f"{label_for(step.ml)} (ML) × {label_for(step.ap)} (AP)"
        if isinstance(step, MetricStep):
            sig = label_for(step.input) if step.input else "(signal)"
            if step.op == "value_at_event":
                return f"{sig} at {step.event or '(event)'}"
            seg = f" over {step.segment[0]}→{step.segment[1]}" if step.segment else ""
            return f"{step.op}({sig}){seg}"
        if isinstance(step, ComputeStep):
            sig = label_for(step.input) if step.input else "(signal)"
            method = getattr(step, "method", "normalize")
            if method == "derivative":
                order = int((step.params or {}).get("order", 1) or 1)
                return f"d{order}/dt of {sig}"
            if method == "integral":
                sign = (step.params or {}).get("sign", "all")
                tag = {"pos": " (positive part)", "neg": " (negative part)"}.get(sign, "")
                return f"∫ {sig} dt{tag}"
            if method == "magnitude":
                extra = " + ".join(label_for(k) for k in (step.inputs or []))
                return f"|{sig}{(' + ' + extra) if extra else ''}|"
            if method == "abs":
                return f"|{sig}|"
            by = step.by
            by = label_for(by) if isinstance(by, str) and by.startswith("metric:") else by
            return f"{sig} ÷ {by}"
        if isinstance(step, FilterStep):
            bits = [f"{step.spec.cutoff_hz:g} Hz", step.spec.type]
            if getattr(step.spec, "order", None):
                bits.append(f"order {step.spec.order}")
            return " · ".join(bits)
        if isinstance(step, DetectEventStep):
            if step.method == "frame":
                frame = int(step.params.get("frame", 0)) + 1
                return f"Fixed frame F{frame}"
            sig = label_for(step.input) if step.input else "(signal)"
            if step.method == "threshold":
                direction = step.params.get("direction", "rising")
                arrow = "↑" if direction == "rising" else "↓"
                thr = step.params.get("threshold")
                tail = f" {thr:g}" if isinstance(thr, (int, float)) else ""
                return f"{sig} threshold {arrow}{tail}"
            if step.method == "peak":
                kind = "valley" if step.params.get("kind") == "min" else "peak"
                return f"{sig} {kind}"
            if step.method == "zero":
                return f"{sig} zero-crossing"
            return f"{sig} {step.method}"
        return ""

    def _selected_step_index(self):
        item = self.step_list.currentItem()
        if item is None:
            return None
        idx = item.data(Qt.ItemDataRole.UserRole)
        return int(idx) if idx is not None else None

    def _open_add_step(self):
        """PIPELINE ``+`` -> one unified Add-step popup (Visual3D-style): pick a
        command on the left, fill its form on the right, OK to append the step.
        Replaces the old dropdown menu (the popup IS the picker)."""
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)   # so angle inputs are offered
        frame_max = (len(dataset["time"]) - 1) if dataset is not None else 0
        ctx = {
            "filter_targets": self._filterable_targets(),
            "event_inputs": self._event_input_options(),
            "frame_max": frame_max,
            "event_color": self.event_color,
            "metric_inputs": self._event_input_options(),
            "event_labels": self._event_label_options(),
            "metric_refs": self._metric_ref_options(),
            "traj_inputs": self._trajectory_input_options(),
            "compute_inputs": self._event_input_options(),
            "compute_angle_joints": self._model_joint_names(dataset),
        }
        dialog = AddStepDialog(self, ctx)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        kind, vals = dialog.values()
        self._append_step(kind, vals)

    def _append_step(self, kind, vals):
        """Build + append the pipeline step for ``(kind, form values)`` from the
        unified Add dialog, reusing the same validation/wiring as before."""
        from core.pipeline import (FilterStep, DetectEventStep, TrajectoryStep,
                                    MetricStep, ComputeAngleStep, ComputeStep)
        if kind == "filter":
            spec_dict, targets, markers = vals
            if not targets and not markers:
                QMessageBox.information(self, "No signals",
                                        "Select at least one signal (or Markers) to filter.")
                return
            self.pipeline.add(FilterStep(spec=FilterSpec(**spec_dict),
                                         targets=targets, markers=markers))
        elif kind == "compute_angle":
            # Only one angle step makes sense (it produces all of the model's
            # angles). Adding a second is a no-op so the recipe stays clean.
            if self.pipeline.has_angle_step():
                QMessageBox.information(
                    self, "Already present",
                    "A Compute joint angles step is already in the pipeline.")
                return
            self.pipeline.add(ComputeAngleStep(joints=vals.get("joints")))
        elif kind == "detect_event":
            inp, label, method, params, selector, scope, color = vals
            if method != "frame" and not inp:
                QMessageBox.information(self, "No signal", "Select a signal to detect on.")
                return
            if not label:
                QMessageBox.information(self, "Event name", "Enter an event name.")
                return
            if color:
                self.event_color = color
            self.pipeline.add(DetectEventStep(input=inp, label=label, method=method,
                                              params=params, selector=selector,
                                              scope=scope, color=color))
            self._invalidate_event_caches()
        elif kind == "compute":
            if not self._validate_compute_vals(vals):
                return
            self.pipeline.add(ComputeStep(**vals))
        elif kind == "metric":
            if not self._validate_metric_vals(vals):
                return
            self.pipeline.add(MetricStep(**vals))
        elif kind == "trajectory":
            ap, ml = vals
            self.pipeline.add(TrajectoryStep(ap=ap, ml=ml))
        elif kind == "normalize":
            if not vals.get("name"):
                QMessageBox.information(self, "Output name",
                                        "Enter a name for the normalized output.")
                return
            from core.pipeline import NormalizeStep
            self.pipeline.add(NormalizeStep(**vals))
        else:
            return
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _event_input_options(self):
        """``[(key, label), ...]`` of catalog signals a DetectEventStep may read.

        Same source as the event-channel picker (raw + "(filtered)" + joint
        angles), minus ``time``, so a detector runs on a real signal value."""
        dataset = self._current_dataset()
        if dataset is None:
            # No file yet: offer the always-present force/COP scalar keys so a
            # detect step can be authored before loading (mirrors _filterable_targets).
            return [("fz", "Fz"), ("fx", "Fx"), ("fy", "Fy"),
                    ("cop_ap", "COP AP"), ("cop_ml", "COP ML"), ("cop", "COP")]
        return [(key, label) for label, key in self._event_channel_options(dataset)
                if key != "time"]

    def _add_filter_step(self):
        dialog = FilterStepDialog(self, self._filterable_targets())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec_dict, targets, markers = dialog.values()
        if not targets and not markers:
            QMessageBox.information(self, "No signals",
                                    "Select at least one signal (or Markers) to filter.")
            return
        from core.pipeline import FilterStep
        self.pipeline.add(FilterStep(spec=FilterSpec(**spec_dict),
                                     targets=targets, markers=markers))
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _add_detect_event_step(self):
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)  # so angle inputs are offered
        frame_max = (len(dataset["time"]) - 1) if dataset is not None else 0
        dialog = DetectEventStepDialog(self, self._event_input_options(),
                                       frame_max=frame_max, color=self.event_color,
                                       event_labels=self._event_label_options())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        inp, label, method, params, selector, scope, color = dialog.values()
        if method != "frame" and not inp:
            QMessageBox.information(self, "No signal", "Select a signal to detect on.")
            return
        if not label:
            QMessageBox.information(self, "Event name", "Enter an event name.")
            return
        if color:
            self.event_color = color
        from core.pipeline import DetectEventStep
        self.pipeline.add(DetectEventStep(input=inp, label=label, method=method,
                                          params=params, selector=selector,
                                          scope=scope, color=color))
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _estimate_mass(self, static):
        """Auto body-mass (kg) from a static trial's vertical GRF, or None.

        Sums per-plate Fz (subject may stand across plates) then ``mass=mean/g``
        via :func:`core.com.mass_from_grf`. Static (quiet-standing) trials only."""
        if static is None:
            return None
        from core.com import mass_from_grf
        keys = [k for k in static.get("force_signal_keys", []) if k.endswith(":fz")]
        fzs = [np.asarray(static[k], dtype=float) for k in keys if k in static]
        if fzs:
            return mass_from_grf(np.vstack(fzs))
        fz = static.get("fz")
        return mass_from_grf(fz) if fz is not None else None

    def _subject_static_for(self, dataset):
        """The static trial that holds ``dataset``'s subject info (self if static,
        else the nearest-ancestor static; falls back to the dataset itself)."""
        if dataset is None:
            return None
        if dataset.get("role") == "static":
            return dataset
        return self._nearest_static(dataset.get("folder")) or dataset

    def _subject_for(self, dataset):
        """Subject metadata ``{mass, height, sex}`` for ``dataset``.

        Stored ON the subject's static trial (``static["subject"]``); a dynamic
        inherits its nearest-ancestor static's values. Mass defaults to the static
        GRF auto-estimate when not entered (so normalize-by-bodyweight works with
        zero manual input on a force-bearing static)."""
        static = self._subject_static_for(dataset)
        if static is None:
            return {}
        info = dict(static.get("subject") or {})
        if not info.get("mass"):
            est = self._estimate_mass(static)
            if est:
                info["mass"] = est
        return info

    def _subject_metrics(self, dataset):
        """Subject quantities as a bare-name metric dict (``mass`` / ``bodyweight``
        = mass·g / ``height``), mirroring what :func:`core.run.run_pipeline` seeds.

        Passed to the Workspace used for graphing / value tables so a "÷ body
        weight" (``normalize`` by ``metric:bodyweight``) compute signal resolves
        OUTSIDE a full pipeline run — without it the Workspace raises and the
        graph/table come up empty. User-defined MetricStep refs stay run-only."""
        info = self._subject_for(dataset) or {}
        out = {}
        mass = info.get("mass")
        if mass:
            out["mass"] = float(mass)
            out["bodyweight"] = float(mass) * 9.80665   # g (matches core.run.G)
        if info.get("height"):
            out["height"] = float(info["height"])
        return out

    def _edit_subject_info(self, static):
        """Static right-click → "Subject info…": edit mass/height/sex on the static."""
        from ui.analyze_dialogs import SubjectInfoDialog
        dialog = SubjectInfoDialog(self, subject=static.get("subject"),
                                   mass_estimate=self._estimate_mass(static))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        static["subject"] = dialog.values()
        # Subject feeds analysis (normalize/COM) -> drop cached analysis so a
        # re-run picks up the new mass.
        for d in self.datasets:
            d["analysis"] = None

    def _event_label_options(self):
        """Available event names (for Metric segment / value-at-event pickers)."""
        dataset = self._current_dataset()
        if dataset is None:
            return []
        markers = dataset.get("markers")
        disp = self._marker_display_data(markers) if markers else None
        res = self._angle_result_for(dataset)
        return events_compute.event_catalog(dataset, self.pipeline, disp, res)

    def _metric_ref_options(self):
        """Names of metrics already defined in the pipeline (for the derived ops'
        references — cadence/symmetry/CV/RSI read another metric's value)."""
        from core.pipeline import MetricStep
        return [s.name for s in self.pipeline.steps
                if isinstance(s, MetricStep) and s.name]

    def _validate_metric_vals(self, vals):
        """Mode-aware validation of a MetricStepDialog ``values()`` dict.

        Every metric needs a name. A *signal* op needs an ``input`` signal; an
        *event* op needs a complete event pair (``segment``); a *derived* op needs
        the metric reference(s) it cites. Shows a message + returns False on a
        gap, else True."""
        from core.metrics import OP_INFO
        if not vals.get("name"):
            QMessageBox.information(self, "Metric name", "Enter a metric name.")
            return False
        kind = OP_INFO.get(vals.get("op", ""), {}).get("input")
        if kind == "event":
            if not vals.get("segment"):
                QMessageBox.information(self, "No events",
                                        "Pick the two events to measure between.")
                return False
        elif kind == "metric":
            if not vals.get("input"):
                QMessageBox.information(self, "No metric",
                                        "Pick the metric this is derived from.")
                return False
        else:  # signal / cop / sample / jump
            if not vals.get("input"):
                QMessageBox.information(self, "No signal",
                                        "Select a signal to measure.")
                return False
        return True

    def _validate_compute_vals(self, vals):
        """Validate a :class:`ComputeStepDialog` ``values()`` dict.

        Every compute step needs an output name + an input signal. A normalize-by
        a metric needs the metric chosen (not a stale empty ref). Shows a message
        + returns False on a gap, else True."""
        if not vals.get("name"):
            QMessageBox.information(self, "Output name",
                                    "Enter a name for the computed signal.")
            return False
        if not vals.get("input"):
            QMessageBox.information(self, "No signal",
                                    "Select an input signal to compute from.")
            return False
        if vals.get("method") == "normalize":
            by = vals.get("by")
            if isinstance(by, str) and by.startswith("metric:") and by == "metric:":
                QMessageBox.information(self, "No metric",
                                        "Pick the metric to divide by.")
                return False
        return True

    def _edit_compute_step(self, step):
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)   # so angle inputs are offered
        # A compute step can't reference its own (not-yet-produced) name; the
        # normalize-by-metric list is the pipeline's defined metrics anyway.
        dialog = ComputeStepDialog(self, self._event_input_options(), step=step,
                                   metric_refs=self._metric_ref_options())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        if not self._validate_compute_vals(vals):
            return
        step.input = vals["input"]
        step.name = vals["name"]
        step.method = vals["method"]
        step.by = vals["by"]
        step.params = dict(vals.get("params") or {})
        step.inputs = list(vals.get("inputs") or [])
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _add_metric_step(self):
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)   # so angle inputs are offered
        dialog = MetricStepDialog(self, self._event_input_options(),
                                  self._event_label_options(),
                                  metric_refs=self._metric_ref_options())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        if not self._validate_metric_vals(vals):
            return
        from core.pipeline import MetricStep
        self.pipeline.add(MetricStep(**vals))
        self._refresh_pipeline_list()
        self._on_filter_changed()

    def _edit_metric_step(self, step):
        # A derived metric can't reference itself -> drop this step's own name.
        refs = [n for n in self._metric_ref_options() if n != getattr(step, "name", "")]
        dialog = MetricStepDialog(self, self._event_input_options(),
                                  self._event_label_options(), step=step,
                                  metric_refs=refs)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        if not self._validate_metric_vals(vals):
            return
        step.name = vals["name"]
        step.op = vals["op"]
        step.input = vals["input"]
        step.input2 = vals.get("input2")
        step.segment = vals["segment"]
        step.event = vals["event"]
        self._refresh_pipeline_list()
        self._on_filter_changed()

    def _add_normalize_step(self):
        """Open NormalizeStepDialog, build a NormalizeStep and append it to the
        pipeline. Follows the same pattern as :meth:`_add_metric_step`."""
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)   # so angle inputs are offered
        from ui.ensemble_panel import NormalizeStepDialog
        dialog = NormalizeStepDialog(self, self._event_input_options(),
                                     self._event_label_options())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        if not vals.get("name"):
            QMessageBox.information(self, "Output name",
                                    "Enter a name for the normalized output.")
            return
        from core.pipeline import NormalizeStep
        self.pipeline.add(NormalizeStep(**vals))
        self._refresh_pipeline_list()
        self._on_filter_changed()

    def _edit_normalize_step(self, step):
        """Open NormalizeStepDialog in edit mode and apply the new values."""
        from ui.ensemble_panel import NormalizeStepDialog
        dialog = NormalizeStepDialog(self, self._event_input_options(),
                                     self._event_label_options(), step=step)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        if not vals.get("name"):
            QMessageBox.information(self, "Output name",
                                    "Enter a name for the normalized output.")
            return
        step.input = vals["input"]
        step.name = vals["name"]
        step.mode = vals["mode"]
        step.event = vals["event"]
        step.start_event = vals["start_event"]
        step.end_event = vals["end_event"]
        step.points = vals["points"]
        self._refresh_pipeline_list()
        self._on_filter_changed()

    def _trajectory_input_options(self):
        """``[(key, label), ...]`` of signals a TrajectoryStep may use as AP/ML.

        Same source as the event input picker (raw + "(filtered)" COP/force etc.),
        so a trajectory can be built on filtered COP. Defaults still land on raw
        ``cop_ap``/``cop_ml`` via the dialog."""
        return self._event_input_options()

    def _add_trajectory_step(self):
        dialog = TrajectoryStepDialog(self, self._trajectory_input_options())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ap, ml = dialog.values()
        from core.pipeline import TrajectoryStep
        self.pipeline.add(TrajectoryStep(ap=ap, ml=ml))
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _edit_trajectory_step(self, step):
        dialog = TrajectoryStepDialog(self, self._trajectory_input_options(), step=step)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ap, ml = dialog.values()
        step.ap = ap
        step.ml = ml
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _edit_pipeline_step(self, item=None):
        """Open the right editor for a step (double-click or row ✎).

        ``item`` is the clicked QListWidgetItem (double-click) or ``None``
        (called via the selected row). Dispatches by step type."""
        index = self._selected_step_index() if item is None else \
            int(item.data(Qt.ItemDataRole.UserRole))
        self._edit_step_at(index)

    def _edit_step_at(self, index):
        """Edit the step at pipeline ``index`` (used by the row ✎ button)."""
        from core.pipeline import (FilterStep, DetectEventStep, TrajectoryStep,
                                    MetricStep, ComputeAngleStep, ComputeStep,
                                    NormalizeStep)
        if index is None or not (0 <= index < len(self.pipeline.steps)):
            return
        step = self.pipeline.steps[index]
        if isinstance(step, FilterStep):
            self._edit_filter_step(step)
        elif isinstance(step, DetectEventStep):
            self._edit_detect_event_step(step)
        elif isinstance(step, TrajectoryStep):
            self._edit_trajectory_step(step)
        elif isinstance(step, MetricStep):
            self._edit_metric_step(step)
        elif isinstance(step, ComputeStep):
            self._edit_compute_step(step)
        elif isinstance(step, ComputeAngleStep):
            self._edit_compute_angle_step(step)
        elif isinstance(step, NormalizeStep):
            self._edit_normalize_step(step)

    def _edit_compute_angle_step(self, step):
        """Edit a ComputeAngle step: offer the model's joint names as a checkable
        list so the user can compute only the angles they want. Re-resolves the
        model's joints each time so the choices stay current if the model changed."""
        from ui.analyze_dialogs import ComputeAngleStepDialog
        joints = self._model_joint_names(self._current_dataset())
        dialog = ComputeAngleStepDialog(self, available=joints, step=step)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        step.joints = list(dialog.values().get("joints") or [])
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _delete_step_at(self, index):
        """Remove the step at pipeline ``index`` (used by the row ✕ button)."""
        if index is None or not (0 <= index < len(self.pipeline.steps)):
            return
        self.pipeline.remove(index)
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _toggle_step_at(self, index, enabled):
        """Enable/disable the step at ``index`` (used by the row toggle).

        Flips ``step.enabled`` only, then re-renders: every execution accessor
        in core.pipeline already drops disabled steps, so a re-render is all the
        UI must do. Disabling a detect step also flips the detection cache token,
        so we clear the per-file event caches for an immediate, predictable
        refresh (mirrors edit/delete)."""
        if index is None or not (0 <= index < len(self.pipeline.steps)):
            return
        self.pipeline.steps[index].enabled = bool(enabled)
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _on_step_rows_reordered(self, *args):
        """Reflect an InternalMove drag in the list back into ``self.pipeline``.

        The QListWidget has already moved the *visual* rows when this fires; we
        rebuild ``pipeline.steps`` from the rows' stored original indices (the
        UserRole int set in _refresh_pipeline_list), then re-render so the badges,
        numbers and warning chips reflect the new order. Section-header dragging
        (``_enable_section_drag``) is on the section's header button, not this
        list's viewport, so the two never collide."""
        new_order = []
        for row in range(self.step_list.count()):
            item = self.step_list.item(row)
            orig = item.data(Qt.ItemDataRole.UserRole)
            if orig is None or not (0 <= int(orig) < len(self.pipeline.steps)):
                # Indices out of sync — bail and just re-render from current state.
                self._refresh_pipeline_list()
                return
            new_order.append(int(orig))
        if sorted(new_order) != list(range(len(self.pipeline.steps))):
            # Not a clean permutation; don't risk a bad reorder.
            self._refresh_pipeline_list()
            return
        self.pipeline.steps = [self.pipeline.steps[i] for i in new_order]
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _edit_filter_step(self, step):
        dialog = FilterStepDialog(self, self._filterable_targets(),
                                  spec=step.spec, selected=step.targets,
                                  markers=step.markers)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec_dict, targets, markers = dialog.values()
        if not targets and not markers:
            QMessageBox.information(self, "No signals",
                                    "Select at least one signal (or Markers) to filter.")
            return
        step.spec = FilterSpec(**spec_dict)
        step.targets = list(dict.fromkeys(targets))
        step.markers = markers
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _edit_detect_event_step(self, step):
        dataset = self._current_dataset()
        if dataset is not None:
            self._ensure_model_result(dataset)
        frame_max = (len(dataset["time"]) - 1) if dataset is not None else 0
        # A search-window "Event" bound may reference any OTHER detect step's
        # label — drop this step's own label so it can't reference itself.
        own = getattr(step, "label", "")
        event_labels = [lab for lab in self._event_label_options() if lab != own]
        dialog = DetectEventStepDialog(self, self._event_input_options(),
                                       frame_max=frame_max, step=step,
                                       color=self.event_color,
                                       event_labels=event_labels)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        inp, label, method, params, selector, scope, color = dialog.values()
        if method != "frame" and not inp:
            QMessageBox.information(self, "No signal", "Select a signal to detect on.")
            return
        if not label:
            QMessageBox.information(self, "Event name", "Enter an event name.")
            return
        if color:
            self.event_color = color
        step.input = inp
        step.label = label
        step.method = method
        step.params = params
        step.selector = selector
        step.scope = scope
        step.color = color
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _invalidate_event_caches(self):
        """Drop the per-file detected-event caches so the next render recomputes.

        ``compute_detected_events`` already invalidates on a pipeline token change,
        but clearing here makes a re-render immediate and predictable across all
        loaded files (e.g. after editing/deleting a detect step)."""
        for ds in self.datasets:
            ds.pop("_events_cache", None)
            ds.pop("_events_token", None)

    def _delete_pipeline_step(self):
        """Delete the selected step (Delete key on the focused list)."""
        index = self._selected_step_index()
        if index is None or not (0 <= index < len(self.pipeline.steps)):
            return
        self._delete_step_at(index)

    def _on_filter_changed(self):
        # The pipeline changed (a step added/edited/removed/reordered) → the set of
        # produced signals/events may differ, so repopulate RESULTS. A signal the
        # recipe no longer produces is dropped from the "View as graph" set.
        self._prune_signal_views()
        # Re-apply the marker filter to the 3D view + coordinate plots live.
        dataset = self._current_dataset()
        markers = dataset.get("markers") if dataset else None
        if markers is not None:
            markers["_filt_sig"] = None  # force recompute on next access
            if self.marker_view is not None and self.panel_visible.get("markers3d"):
                self.marker_view.set_positions(self._marker_display_data(markers))
            self._update_marker_coord_plots()
        if getattr(self, "show_btn", None) is not None and self.show_btn.isChecked():
            self._run_analysis()
        else:
            if dataset is not None:
                self._plot_dataset(dataset)
            else:
                self._refresh_results_panels(None)

    def apply_theme(self):
        if hasattr(self, "frame_total_lbl"):
            self.frame_total_lbl.setStyleSheet(S.label_style(S.TEXT_SECONDARY, 11))
        if self.marker_view is not None:
            self.marker_view.apply_theme()
        # Rebuild plots (new graph colours) and re-render any visible cards.
        self._rebuild_plot_layout()

    def _build_traj_plot(self):
        plot = self._new_plot_widget("COP Trajectory - 95% Ellipse", key="traj")
        plot.setLabel("left", "AP (mm)", color=GRAPH_FG, size="9pt")
        plot.setLabel("bottom", "ML (mm)", color=GRAPH_FG, size="9pt")
        plot.setAspectLocked(True)
        self.p_traj = plot
        self.c_traj = plot.plot(pen=pg.mkPen("#888880", width=1))
        self.c_ellipse = plot.plot(
            pen=pg.mkPen(C_ELL, width=2, style=Qt.PenStyle.DashLine)
        )
        # Detected/manual events as points on the path (COP at each event frame),
        # coloured per event. Added BELOW the live marker so the marker stays on top.
        self.c_events = pg.ScatterPlotItem(size=9, pen=pg.mkPen("#11151b", width=0.5))
        plot.addItem(self.c_events)
        self.c_mean = pg.ScatterPlotItem(
            size=8,
            symbol="o",
            brush=pg.mkBrush(ACCENT_TEAL),
            pen=pg.mkPen(ACCENT_TEAL, width=2),
        )
        plot.addItem(self.c_mean)
        return plot

    def _render_trajectory(self, dataset):
        """Draw the COP trajectory (statokinesigram) for the pipeline's first
        TrajectoryStep into the traj plot, when that plot is shown.

        The path is the mean-centred ML(x)-AP(y) COP (computed by core), with a
        mean point at the origin and a 95% confidence ellipse (computed by core's
        compute_ellipse_points on the same AP/ML). No trajectory step / no plot =>
        nothing to draw. The plot only exists when the "COP trajectory" PROCESSED
        toggle is on (which only appears when a TrajectoryStep exists)."""
        if self.c_traj is None or dataset is None:
            return
        # The exact mean-centred (ML, AP) arrays drawn as the grey path; the live
        # playback marker indexes THESE (see _set_review_time) so the dot always
        # lies on the line. None until a path is drawn below.
        self._traj_centred = None
        steps = self.pipeline.trajectory_steps()
        if not steps:
            self.c_traj.setData([], [])
            if self.c_ellipse is not None:
                self.c_ellipse.setData([], [])
            if self.c_mean is not None:
                self.c_mean.setData([], [])
            if self.c_events is not None:
                self.c_events.setData([])
            return
        ws = Workspace(dataset, marker_disp=None,
                       angle_result=self._angle_result_for(dataset),
                       pipeline=self.pipeline,
                       metrics=self._subject_metrics(dataset))
        traj = compute_trajectory(ws, step=steps[0])
        if traj is None:
            self.c_traj.setData([], [])
            if self.c_ellipse is not None:
                self.c_ellipse.setData([], [])
            if self.c_mean is not None:
                self.c_mean.setData([], [])
            if self.c_events is not None:
                self.c_events.setData([])
            return
        # x = ML (mean-centred), y = AP (mean-centred); the centre is the origin.
        self.c_traj.setData(traj["x"], traj["y"])
        self._traj_centred = (np.asarray(traj["x"], dtype=float),
                              np.asarray(traj["y"], dtype=float))
        if self.c_ellipse is not None:
            self.c_ellipse.setData([], [])
        if self.c_mean is not None:
            self.c_mean.setData([], [])
        ml_c, ap_c = traj["x"], traj["y"]
        if self.c_mean is not None:
            # At-rest centre; the live COP marker (_set_review_time) moves it.
            self.c_mean.setData([0.0], [0.0])
        # 95% confidence ellipse — drawn only when toggled on (graph right-click).
        if len(ap_c) > 10 and getattr(self, "_show_ellipse", True):
            try:
                ell_ml, ell_ap = compute_ellipse_points(ap_c, ml_c)
                if self.c_ellipse is not None:
                    self.c_ellipse.setData(ell_ml, ell_ap)
            except Exception:
                pass
        # Event markers on the path (COP at each event frame), toggleable.
        if self.c_events is not None:
            self.c_events.setData(
                self._traj_event_spots(dataset)
                if getattr(self, "_show_traj_events", True) else [])

    def _traj_event_spots(self, dataset):
        """Scatter spots for detected + manual events placed ON the COP path.

        Each event frame -> the SAME mean-centred (ML, AP) point the path was drawn
        from (``_traj_centred``), so the dots sit exactly on the line. Coloured per
        event (the DetectEventStep colour, else the cycling palette / manual
        colour); hidden labels are skipped. Empty when there's no path."""
        xy = getattr(self, "_traj_centred", None)
        if xy is None:
            return []
        n = len(xy[0])
        spots = []

        def _add(frame, color):
            f = int(frame)
            if 0 <= f < n:
                spots.append({"pos": (float(xy[0][f]), float(xy[1][f])),
                              "brush": pg.mkBrush(color), "size": 9, "symbol": "o"})

        try:
            detected = events_compute.compute_detected_events(dataset, self.pipeline)
        except Exception:
            detected = []
        steps = self.pipeline.detect_event_steps() if self.pipeline else []
        for step_id, entry in enumerate(detected):
            if entry.get("label") in self._hidden_event_labels:
                continue
            color = steps[step_id].color if 0 <= step_id < len(steps) else None
            if not color:
                color = self._AUTO_EVENT_COLORS[step_id % len(self._AUTO_EVENT_COLORS)]
            for fr in entry.get("frames", []):
                _add(fr, color)
        for ev in dataset.get("events", []):
            if not ev.get("enabled", True) or ev.get("name") in self._hidden_event_labels:
                continue
            if ev.get("frame") is not None:
                _add(ev["frame"], ev.get("color", "#F97316"))
        return spots

    #: Map a force/COP component to its appearance colour key.
    _CURVE_COLOR = {"cop": "curve/cop", "cop_ap": "curve/ap", "cop_ml": "curve/ml",
                    "fx": "curve/fx", "fy": "curve/fy", "fz": "curve/fz"}

    def _curve_color_for(self, key, _seen=None):
        """Pen colour for a raw force/COP signal ``key`` (``fp{p}:comp`` or bare).
        Keyed off the component so a channel keeps one colour across all plates.

        A ComputeStep-derived signal (e.g. ``|fz|``) inherits its INPUT's colour so
        the derived curve matches the source data's line colour (recurses through
        chained computes, cycle-guarded)."""
        if self.pipeline is not None:
            step = self.pipeline.compute_step_for(key)
            if step is not None and step.input:
                _seen = _seen or set()
                if key not in _seen:
                    _seen.add(key)
                    return self._curve_color_for(step.input, _seen)
        # Strip a ":filt" twin suffix and match the component case-insensitively
        # so a derived input keyed "fp1:Fz" / "Fz" / "fp1:fz:filt" still maps to
        # its channel colour instead of falling through to the grey raw default.
        base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
        comp = base.rsplit(":", 1)[-1].lower()
        return self.appearance.color(self._CURVE_COLOR.get(comp, "curve/raw"))

    def _signal_unit(self, key, _seen=None):
        """Physical unit for ``key``, resolving ComputeStep-derived units that the
        static :func:`unit_for` doesn't know (e.g. ``|fz|`` → N, derivative → N/s).

        Needed so a derived FORCE signal (unit N) still gets the y-axis-0 baseline
        instead of auto-zooming to its tiny wobble — the same fix raw force plots
        already have. Recurses through chained compute inputs (cycle-guarded)."""
        unit = unit_for(key)
        if unit or self.pipeline is None:
            return unit
        step = self.pipeline.compute_step_for(key)
        if step is None:
            return unit
        _seen = _seen or set()
        if key in _seen:
            return unit
        _seen.add(key)
        from core import signal_ops
        base = self._signal_unit(step.input, _seen)
        order = int((getattr(step, "params", {}) or {}).get("order", 1) or 1)
        return signal_ops.derive_unit(base, getattr(step, "method", "normalize"),
                                      order=order)

    def _build_time_plot(self, key, is_last):
        """Build one time-series plot for a force/COP signal ``key``.

        Generic (key-driven): the title/axis come from the signal registry
        (``label_for``/``unit_for``) so any plate's channel (``fp2:cop_ap`` …)
        plots without a per-key branch. Holds a raw curve + a filtered twin curve
        (the twin is drawn only when the pipeline filters this key), stored in
        ``_raw_plots``/``_raw_curves`` keyed by the signal key."""
        label, unit = label_for(key), self._signal_unit(key)
        plot = self._new_plot_widget(label, key=key, is_time_plot=True)
        plot.setLabel("left", f"{label} ({unit})" if unit else label,
                      color=GRAPH_FG, size="9pt")
        # Y-range policy: force signals (N) read against an absolute baseline, so a
        # near-constant Fz (~450 N) must NOT auto-zoom to its tiny wobble — the
        # axis includes 0 so the bar height shows the real magnitude. COP/markers
        # (mm) and angles keep a tight data-range view (their zero is arbitrary).
        plot._y_baseline = 0.0 if unit == "N" else None
        lw = self.appearance.line_width()
        color = self._curve_color_for(key)
        # Both curves are drawn at the SAME width. Their colours are set per
        # refresh (see the force/COP draw loop): when a filtered twin is shown the
        # filtered curve keeps the channel colour and the raw curve drops to a
        # faint grey reference; a lone raw signal keeps its channel colour.
        raw_curve = plot.plot(pen=pg.mkPen(color, width=lw))
        filt_curve = plot.plot(pen=pg.mkPen(color, width=lw))
        self._raw_plots[key] = plot
        self._raw_curves[key] = (raw_curve, filt_curve)
        if is_last:
            plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
        self._add_review_cursor(plot)
        return plot

    def _build_signal_figure_plot(self, keys, is_last=False):
        """Build ONE time plot holding several signal-view ``keys`` (a combined
        figure). Single-key lists defer to :meth:`_build_time_plot`. Each key gets
        its own raw+filt curves registered in ``_raw_plots``/``_raw_curves`` (keyed
        by signal key), so the existing key-driven draw loop fills them unchanged.
        Members share a type/unit (enforced by the same-type combine rule)."""
        if len(keys) == 1:
            return self._build_time_plot(keys[0], is_last=is_last)
        unit = self._signal_unit(keys[0])
        title = self._figure_label(keys)
        plot = self._new_plot_widget(title, key=keys[0], is_time_plot=True)
        plot.setLabel("left", f"({unit})" if unit else "", color=GRAPH_FG, size="9pt")
        plot._y_baseline = 0.0 if unit == "N" else None
        lw = self.appearance.line_width()
        for key in keys:
            color = self._curve_color_for(key)
            raw_curve = plot.plot(pen=pg.mkPen(color, width=lw))
            filt_curve = plot.plot(pen=pg.mkPen(color, width=lw))
            self._raw_plots[key] = plot
            self._raw_curves[key] = (raw_curve, filt_curve)
        if is_last:
            plot.setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
        self._add_review_cursor(plot)
        return plot

    def _ordered_force_keys(self, dataset):
        """Per-plate force/COP signal keys in display order (plate, then channel),
        restricted to the toggles currently registered for this dataset."""
        count = self._plate_count(dataset) if dataset else 0
        if dataset is None or not dataset.get("force_signal_keys"):
            count = 0
        reg = getattr(self, "_plate_toggle_keys", set())
        keys = []
        for p in range(1, count + 1):
            for comp, _ in self._PLATE_CHANNELS:
                key = f"fp{p}:{comp}"
                if key in reg:
                    keys.append(key)
        return keys

    def _rebuild_plot_layout(self, *_args):
        if not hasattr(self, "plot_container"):
            return

        self.panel_visible = {
            key: cb.isChecked()
            for key, cb in self.panel_checks.items()
        }
        # RESULTS·Signals "View as graph" selections survive the checkbox rebuild:
        # a signal key the user chose to view (right-click) is forced visible here
        # (RAW SIGNALS checkboxes still drive their own keys independently).
        for key in self._signal_views:
            self.panel_visible[key] = True
        # COP-path (2-D trajectory) view has no checkbox either — driven by the
        # RESULTS·Signals "COP path" right-click.
        self.panel_visible["traj"] = bool(self._show_traj)
        # Joint angles never auto-graph: model_result is computed (metrics need it)
        # but the angle curves appear ONLY when chosen in RESULTS·Signals
        # (right-click → View as graph), tracked in self._angle_plots below.
        self._ensure_model_result(self._current_dataset())
        self._ensure_main_split()
        # Batch the rebuild so toggling a data graph doesn't visibly blank the
        # whole panel (clear + refill repaints once).
        self.plot_container.setUpdatesEnabled(False)
        self._clear_graph_host()
        self._reset_plot_handles()

        dataset = self._current_dataset()
        # A per-plate force/COP plot is shown when its RAW toggle OR its
        # "(filtered)" twin toggle (`<key>:filt`) is on (one plot, two curves
        # toggled independently). These RAW-panel plots stay one-per-toggle.
        plate_keys = [key for key in self._ordered_force_keys(dataset)
                      if self.panel_visible.get(key, False)
                      or self.panel_visible.get(f"{key}:filt", False)]
        # RESULTS·Signals "View as graph" keys are grouped into FIGURES (the user
        # can combine several into one). A figure whose keys are all already shown
        # as RAW plate plots is dropped (no double plot). ":filt" reduces to parent.
        signal_figs = []
        for gid, keys in self._signal_view_figures():
            keys = [k for k in keys if k not in plate_keys]
            if keys:
                signal_figs.append((gid, keys))
        # COP trajectory is a PROCESSED (pipeline) product: shown only when a
        # TrajectoryStep exists AND its toggle is on (defaults off — never auto).
        has_traj = bool(self.panel_visible.get("traj", False))
        self._refresh_results_panels(dataset)
        has_markers = bool(dataset and dataset.get("markers"))
        show_markers = bool(self.panel_visible.get("markers3d") and has_markers)
        coord_idxs = self._coord_marker_indexes(dataset) if has_markers else []
        show_coord = bool(has_markers and coord_idxs)
        # Joint-angle graphs are opt-in (RESULTS right-click): each angle belongs
        # to a FIGURE group (angles sharing a group id share one figure). Gated on
        # a ComputeAngle step — no step => no angle signals => no angle graphs.
        res = self._angle_result_for(dataset)
        avail = res.get("angles", {}) if res else {}
        angle_figs = self._angle_figures(avail)        # [(gid, [names])]
        show_angles = bool(angle_figs)
        self.panel_visible["jointangles"] = show_angles

        # Stack the time-series plots (plus the optional marker-coordinate plot)
        # in a vertical splitter so each row can be resized.
        time_plots = [self._build_time_plot(key, is_last=False) for key in plate_keys]
        for _gid, keys in signal_figs:
            time_plots.append(self._build_signal_figure_plot(keys))
        if show_coord:
            for idx in coord_idxs:
                time_plots.append(self._build_marker_coord_plot(dataset, idx))
        for _gid, names in angle_figs:
            title = "Joint angles" if len(names) > 1 else names[0]
            time_plots.append(self._build_jointangles_plot(dataset, names, title))
        self._time_plots = list(time_plots)   # range highlight spans all of them
        time_stack = None
        if time_plots:
            time_plots[-1].setLabel("bottom", "Time (s)", color=GRAPH_FG, size="9pt")
            time_stack = QSplitter(Qt.Orientation.Vertical)
            time_stack.setObjectName("plot-splitter")
            time_stack.setChildrenCollapsible(False)
            time_stack.setHandleWidth(6)
            for plot in time_plots:
                time_stack.addWidget(plot)
            time_sig = (("time",) + tuple(plate_keys)
                        + tuple(f"sig{g}" for g, _ in signal_figs)
                        + tuple(f"c{i}" for i in coord_idxs)
                        + tuple(f"ja{g}" for g, _ in angle_figs))
            self._apply_inner_split_sizes(time_stack, time_sig, [1000] * len(time_plots))

        traj = self._build_traj_plot() if has_traj else None

        self._place_graph_parts(traj, time_stack)
        self._update_marker_view_for_rebuild(dataset, show_markers)

        if dataset is not None:
            if dataset.get("analysis") and self.view_mode == "analysis":
                self._show_analysis(dataset)
            else:
                self._plot_dataset(dataset)
            if show_markers:
                try:
                    _, _, cur = self.frame_slider.values()
                except Exception:
                    cur = float(dataset["time"][0])
                self.marker_view.update_frame(float(cur))

        self.plot_container.setUpdatesEnabled(True)

    def _reset_plot_handles(self):
        """Drop all plot/curve references so a rebuild starts from a clean slate.
        Called at the top of ``_rebuild_plot_layout`` after the host is cleared."""
        self.p_traj = None
        self.c_traj = None
        self.c_ellipse = None
        self.c_mean = None
        self.c_events = None
        self._traj_centred = None   # mean-centred (ML, AP) arrays for the live marker
        # Per-plate force/COP plots + (raw, filt) curve pairs, keyed by signal key.
        self._raw_plots = {}
        self._raw_curves = {}
        self._coord_curves = {}
        self.jointangles_plot = None
        self.c_angles = {}
        self.review_regions = []
        self._time_plots = []
        self.review_cursor_lines = []
        self.event_lines = []

    def _place_graph_parts(self, traj, time_stack):
        """Place the trajectory plot and/or time-series stack into the persistent
        graph host (the side opposite the 3D view). The 3D view is never
        reparented — it keeps its GL context, so toggling graphs no longer
        flickers it black."""
        graph_parts = []
        if traj is not None:
            graph_parts.append(traj)
        if time_stack is not None:
            graph_parts.append(time_stack)
        if len(graph_parts) == 1:
            self._graph_host_layout.addWidget(graph_parts[0])
        elif len(graph_parts) >= 2:
            gsplit = QSplitter(Qt.Orientation.Horizontal)
            gsplit.setObjectName("plot-splitter")
            gsplit.setChildrenCollapsible(False)
            gsplit.setHandleWidth(6)
            for w in graph_parts:
                gsplit.addWidget(w)
            graph_sig = ("graph", traj is not None, time_stack is not None)
            self._apply_inner_split_sizes(
                gsplit, graph_sig, [360] + [940] * (len(graph_parts) - 1))
            self._graph_host_layout.addWidget(gsplit)
        self._graph_host.setVisible(bool(graph_parts))

    def _update_marker_view_for_rebuild(self, dataset, show_markers):
        """Show/hide the 3D marker view and refresh its data + model overlay to
        match the current dataset during a plot-layout rebuild."""
        mv = self.marker_view
        if show_markers:
            mv.setVisible(True)
            # Only reload (which re-centres the camera) when the dataset changed,
            # so toggling other graphs doesn't reset the user's 3D view.
            if getattr(self, "_marker_view_dataset", None) is not dataset:
                markers = dataset.get("markers")
                mv.set_markers(markers, self._marker_display_data(markers))
                mv.set_visible_mask(self._marker_visible_mask())
                mv.set_overlay(None, None)   # clear stale model overlay
                mv.set_force_plates(dataset.get("force_plates"))
                mv.set_grf(dataset.get("grf"))
                self._marker_view_dataset = dataset
            self._update_model_overlay(dataset, float(getattr(self, "_review_time", 0.0)))
        elif mv is not None:
            mv.setVisible(False)

        # Sizes: give the 3D view the larger share when both are shown.
        if mv is not None and self._graph_host.isVisible():
            self._size_main_split(big_3d=True)

    def _add_review_cursor(self, plot):
        line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(ACCENT_TEAL, width=2),
        )
        line.setVisible(False)
        plot.addItem(line)
        self.review_cursor_lines.append(line)

    def _on_show_results_toggled(self, checked):
        if checked:
            ok = self._run_analysis()
            if not ok:
                # Nothing to show (no files/metrics) -> pop the toggle back up.
                self.show_btn.blockSignals(True)
                self.show_btn.setChecked(False)
                self.show_btn.blockSignals(False)
        else:
            # Run is a global toggle: turning it off clears results for ALL files
            # (not just the current one) and returns every file to raw review.
            for d in self.datasets:
                d["analysis"] = None
            self.analysis_results = []
            self.summary_rows = []
            self._set_placeholder("Run analysis to see metrics")
            dataset = self._current_dataset()
            if dataset is not None:
                self.view_mode = "review"
                self._plot_dataset(dataset)

    def _load_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load files", "", "All Supported Files (*.csv *.c3d);;CSV Files (*.csv);;C3D Files (*.c3d)"
        )
        if not paths:
            return
        self._ingest([(p, ()) for p in paths])   # loose files → root folder

    def _scan_folder_tasks(self, root):
        """Mirror the on-disk folder tree: return (tasks, folders) where each task
        is (file_path, folder_path_tuple relative to root) and folders is the set
        of every folder path encountered (so empty dirs persist too)."""
        exts = (".c3d", ".csv")
        root = os.path.normpath(root)
        tasks, folders = [], set()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            rel = os.path.relpath(dirpath, root)
            parts = () if rel in (".", "") else tuple(rel.split(os.sep))
            for k in range(1, len(parts) + 1):
                folders.add(parts[:k])
            for f in sorted(filenames):
                if f.lower().endswith(exts):
                    tasks.append((os.path.join(dirpath, f), parts))
        return tasks, folders

    def _load_folder(self):
        """Import a folder, mirroring its sub-folder structure into the tree."""
        d = QFileDialog.getExistingDirectory(self, "Load folder")
        if not d:
            return
        tasks, folders = self._scan_folder_tasks(d)
        if not tasks and not folders:
            QMessageBox.information(self, "No files", "No .c3d/.csv files found in that folder.")
            return
        self._folders |= folders
        self._ingest(tasks)

    def _ingest(self, tasks):
        """Load (path, folder_tuple) tasks into the file tree."""
        self._sync_dataset_checked_state()
        loaded = 0
        errors = []
        reports = []
        for task in tasks:
            path = task[0]
            folder = tuple(task[1]) if len(task) > 1 and task[1] else ()
            if any(d["path"] == path for d in self.datasets):
                continue
            try:
                dataset = self._read_dataset(path, folder=folder)
                dataset["_checked"] = True
                self.datasets.append(dataset)
                reports.append((dataset["name"], dataset.get("_clean_report", {})))
                loaded += 1
            except Exception as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")

        self._invalidate_models()
        self._refresh_file_list()
        if self.datasets and self.current_index is None:
            self.current_index = 0
            self._select_dataset_item(0)
            self._plot_dataset(self.datasets[0])
        self._refresh_event_controls(self._current_dataset())

        self._set_file_count()
        if errors:
            QMessageBox.warning(self, "Load errors", "\n".join(errors[:8]))
        elif loaded:
            note = summarize_reports(reports)
            msg = f"Loaded {loaded} file(s)."
            if note:
                msg += "\n\n" + note
            QMessageBox.information(self, "Loaded", msg)

    def _clear_all_files(self):
        if not self.datasets:
            return
        if QMessageBox.question(
                self, "Remove all files",
                f"Remove all {len(self.datasets)} loaded file(s)?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._clear_analysis()

    def _clear_analysis(self):
        self._stop_playback()
        self.datasets = []
        self._folders = set()
        self._collapsed_folders = set()
        self.current_index = None
        self.analysis_results = []
        self.summary_rows = []
        self.analysis_ranges = []
        self.file_tree.clear()
        self._set_file_count()
        self._refresh_review_controls(None)
        self._refresh_event_controls(None)
        self._refresh_marker_controls(None)
        self._refresh_force_controls(None)
        self._marker_list_for = None
        self._marker_view_dataset = None
        self._clear_event_lines()
        self._set_placeholder("Load files and run analysis")
        self._rebuild_plot_layout()

    # ----- Project (.ballab) integration -----
    project_kind = "analyze"
    supports_load_file = True

    def new_project(self):
        # Full reset: _clear_analysis() drops the DATA, but the pipeline recipe and
        # the graph-view selections live outside it — clear them too so "New
        # Project" really starts blank (no lingering steps / graphs).
        from core.pipeline import Pipeline
        self.pipeline = Pipeline()
        self._signal_views = set()
        self._signal_groups = {}
        self._angle_plots = {}
        self._next_group_id = 1
        self._show_traj = False
        self._clear_analysis()
        self._refresh_pipeline_list()

    def has_content(self):
        return bool(self.datasets)

    def load_file(self):
        self._load_files()

    def load_folder(self):
        self._load_folder()

    # ----- Pipeline-only save / load (recipe, reusable across projects) -----
    def export_pipeline(self, path):
        """Write JUST the analysis pipeline (the recipe — no data/results) to a
        JSON file so the same steps can be reused on other projects/subjects."""
        import json
        data = {"kind": "balancelab_pipeline", "version": 1,
                "pipeline": self.pipeline.to_dict()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def import_pipeline(self, path):
        """Load a pipeline JSON (from :meth:`export_pipeline`) and make it the
        current pipeline. Replaces the existing recipe; results re-derive from the
        loaded data on the next run. Raises ValueError if the file isn't one."""
        import json
        from core.pipeline import Pipeline
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pl = data.get("pipeline") if isinstance(data, dict) else None
        if pl is None:
            raise ValueError("not a Balancelab pipeline file")
        self.pipeline = Pipeline.from_dict(pl)
        self._prune_signal_views()
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._refresh_event_controls(self._current_dataset())
        self._on_filter_changed()

    def _dataset_to_csv_bytes(self, dataset):
        """Serialize a dataset's signals to the CSV schema the reader expects.

        The canonical ``Fz/COP_AP/COP_ML`` (+ optional ``Fx/Fy``) columns are the
        bare plate-1 view (COP_AP/COP_ML hold the raw X/Y channels as stored —
        the old global axis swap was retired), independent of the active-plate
        selection so saving never depends on what the user is viewing. Every plate
        also gets one verbatim column per ``fp{p}:*`` signal so all plates round-
        trip through save/reload (see :meth:`_read_csv_dataset`)."""
        n = len(dataset["time"])
        fx = dataset.get("fx")
        fy = dataset.get("fy")
        fields = ["sample", "time_s", "Fz", "COP_AP", "COP_ML", "fs"]
        if fx is not None:
            fields.insert(2, "Fx")
        if fy is not None:
            fields.insert(3 if fx is not None else 2, "Fy")
        # Per-plate columns: appended after the bare schema.
        plate_keys = list(dataset.get("force_signal_keys", []))
        fields += plate_keys
        fs_val = float(dataset.get("fs", 1000.0))
        bare_ap, bare_ml = dataset.get("cop_ap"), dataset.get("cop_ml")
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(fields)
        for i in range(n):
            row = {
                "sample": i,
                "time_s": f"{float(dataset['time'][i]):.6f}",
                "Fz": f"{float(dataset['fz'][i]):.6f}",
                "COP_AP": f"{float(bare_ap[i]):.6f}",
                "COP_ML": f"{float(bare_ml[i]):.6f}",
                "fs": fs_val,
            }
            if fx is not None:
                row["Fx"] = f"{float(fx[i]):.6f}"
            if fy is not None:
                row["Fy"] = f"{float(fy[i]):.6f}"
            for key in plate_keys:
                row[key] = f"{float(dataset[key][i]):.6f}"
            writer.writerow([row[f] for f in fields])
        return buf.getvalue().encode("utf-8-sig")

    @staticmethod
    def _markers_to_npz_bytes(markers):
        """Serialize a marker container to compressed ``.npz`` bytes.

        The marker array (M, F, 3) is the heavy part of a project, so we store it
        with ``np.savez_compressed`` to keep the ``.ballab`` file small. Labels go
        in as an object array; rate/units are scalars. Returns ``None`` when there
        is nothing to save."""
        if not markers or markers.get("data") is None:
            return None
        data = np.asarray(markers["data"], dtype=float)
        if data.size == 0:
            return None
        time = np.asarray(markers.get("time", []), dtype=float)
        labels = np.asarray(list(markers.get("labels", [])), dtype=object)
        rate = float(markers.get("rate", 0.0) or 0.0)
        units = str(markers.get("units", "mm"))
        buf = io.BytesIO()
        np.savez_compressed(
            buf, data=data, time=time, labels=labels,
            rate=np.float64(rate), units=np.array(units),
        )
        return buf.getvalue()

    @staticmethod
    def _markers_from_npz_path(path):
        """Rebuild a marker container from a ``.npz`` file written by
        ``_markers_to_npz_bytes``. Returns ``None`` if it cannot be read."""
        try:
            with np.load(path, allow_pickle=True) as npz:
                return {
                    "labels": [str(x) for x in npz["labels"].tolist()],
                    "data": np.asarray(npz["data"], dtype=float),
                    "time": np.asarray(npz["time"], dtype=float),
                    "rate": float(npz["rate"]),
                    "units": str(npz["units"]),
                }
        except Exception:
            return None

    def _file_checked_map(self):
        checked = {}
        for item in self._iter_file_items():
            idx = self._item_index(item)
            if idx is not None:
                checked[idx] = item.checkState(0) == Qt.CheckState.Checked
        return checked

    def _statistics_rows_for_save(self):
        """Return the Statistics store's accumulated rows for persistence.

        The store is owned by MainWindow and injected via ``set_results_store``;
        when no store is wired (headless / older host) this is simply empty. Rows
        are plain JSON-friendly dicts (``{column: value}``) already, so they go
        straight into the manifest."""
        store = getattr(self, "results_store", None)
        if store is None:
            return []
        try:
            return [dict(r) for r in store.rows()]
        except Exception:
            return []

    @staticmethod
    def _plates_to_json(plates):
        """Force-plate geometry (corners/origin/R, all numpy) -> JSON-able lists."""
        out = []
        for p in plates or []:
            try:
                out.append({
                    "corners": np.asarray(p["corners"], dtype=float).tolist(),
                    "origin": np.asarray(p["origin"], dtype=float).tolist(),
                    "R": np.asarray(p["R"], dtype=float).tolist(),
                })
            except Exception:
                pass
        return out

    @staticmethod
    def _plates_from_json(data):
        out = []
        for p in data or []:
            try:
                out.append({
                    "corners": np.asarray(p["corners"], dtype=float),
                    "origin": np.asarray(p["origin"], dtype=float),
                    "R": np.asarray(p["R"], dtype=float),
                })
            except Exception:
                pass
        return out

    @staticmethod
    def _fp_raw_to_npz_bytes(fp_raw):
        """Per-plate RAW force/moment channels (fx/fy/fz/mx/my) -> compressed npz.
        These (esp. the moments mx/my) are what build_grf needs and the CSV omits."""
        if not fp_raw:
            return None
        arrays = {}
        for i, r in enumerate(fp_raw):
            for ch in ("fx", "fy", "fz", "mx", "my"):
                v = (r or {}).get(ch)
                if v is not None:
                    arrays[f"p{i}_{ch}"] = np.asarray(v, dtype=float)
        if not arrays:
            return None
        arrays["_count"] = np.array([len(fp_raw)])
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)
        return buf.getvalue()

    @staticmethod
    def _fp_raw_from_npz_path(path):
        try:
            z = np.load(path)
        except Exception:
            return None
        n = int(z["_count"][0]) if "_count" in z else 0
        out = []
        for i in range(n):
            r = {}
            for ch in ("fx", "fy", "fz", "mx", "my"):
                k = f"p{i}_{ch}"
                if k in z:
                    r[ch] = z[k]
            out.append(r)
        return out or None

    def save_project_state(self):
        checked = self._file_checked_map()
        manifest = {
            "tab": self.project_kind,
            # v5: the project now records whether RESULTS were being shown (the ▶Run
            # toggle was on) and the Statistics-store rows, so reopening restores not
            # just the pipeline recipe but its computed RESULTS too. v<5 projects lack
            # these keys -> they load as "not run" (old behaviour) and the user can
            # press ▶Run.
            # v4: joint angles became a pipeline step (ComputeAngleStep) — no more
            # auto-compute. A v<4 project that has a model but no angle step is
            # seeded one on load (back-compat), so old projects keep their angles.
            # v6: figure-group ids ("figure_groups") record which signals share one
            # graph (combine-target feature) AND finally persist angle graphs. v<6
            # projects lack the block -> no angle graphs restored, signals each own
            # figure (prior behaviour).
            "version": 6,
            "current_index": self.current_index,
            # Was the analysis (▶Run) toggle on when saved? If so, load re-runs the
            # pipeline so RESULTS (metrics / detected events / derived signals) come
            # back exactly as they were — they are deterministically recomputed from
            # pipeline + data, so we re-derive rather than persist the (large) arrays.
            "results_shown": bool(self.show_btn.isChecked())
            if hasattr(self, "show_btn") else False,
            # The Statistics tab's accumulated result rows (metrics the user sent
            # there). These are part of the project's analysis output, so they are
            # saved with it and restored on load. Empty if nothing was sent.
            "statistics_rows": self._statistics_rows_for_save(),
            # RAW-toggle states + the RESULTS·Signals "View as graph" selections
            # (processed/COP-path views have no checkbox; they're saved as plain
            # panel_visible keys so re-opening restores the same graphs).
            "panel_visible": {
                **{k: cb.isChecked() for k, cb in self.panel_checks.items()},
                **{k: True for k in self._signal_views},
                "traj": bool(self._show_traj),
            },
            # Figure-group assignments (which signals share one graph). Lets a
            # combined arrangement of angle/signal figures survive save → load.
            "figure_groups": self._figure_groups_for_save(),
            "analysis_ranges": self.analysis_ranges,
            # The shared analysis pipeline (v3+). Older projects have no
            # "pipeline" key and load as an empty pipeline (= raw) below.
            "pipeline": self.pipeline.to_dict(),
            "folders": [list(p) for p in sorted(self._folders)],
            "datasets": [],
        }
        files = {}
        for i, ds in enumerate(self.datasets):
            arcname = f"data/{i}.csv"
            files[arcname] = self._dataset_to_csv_bytes(ds)
            entry = {
                "name": ds.get("name", f"trial_{i}"),
                "orig_path": ds.get("path", ""),
                "fs": float(ds.get("fs", 1000.0)),
                "range_start": float(ds.get("range_start", ds["time"][0])),
                "range_end": float(ds.get("range_end", ds["time"][-1])),
                "events": ds.get("events", []),
                "checked": bool(checked.get(i, True)),
                "folder": list(ds.get("folder") or ()),
                "role": ds.get("role", "dynamic"),
                "trial": ds.get("trial", ""),
                "subject": ds.get("subject"),   # mass/height/sex on a static
                "data_file": arcname,
            }
            # Preserve markers (compressed .npz) and the kinematic model so that
            # markers / joint angles survive a save-and-reopen. model_result is
            # NOT stored: it is recomputed from model + static on load.
            npz = self._markers_to_npz_bytes(ds.get("markers"))
            if npz is not None:
                marker_arc = f"data/{i}_markers.npz"
                files[marker_arc] = npz
                entry["markers_file"] = marker_arc
            # Force-plate GEOMETRY + RAW channels — needed to redraw the 3D force
            # plates (set_force_plates) and rebuild the GRF vector (build_grf) on
            # reopen; neither survives the CSV, so persist them explicitly.
            plates = ds.get("force_plates")
            if plates:
                entry["force_plates"] = self._plates_to_json(plates)
            fpraw = self._fp_raw_to_npz_bytes(ds.get("_fp_raw"))
            if fpraw is not None:
                fpraw_arc = f"data/{i}_fpraw.npz"
                files[fpraw_arc] = fpraw
                entry["fp_raw_file"] = fpraw_arc
            model = ds.get("model")
            if model is not None:
                try:
                    entry["model"] = model.to_dict()
                except Exception:
                    pass
            # UI-side model metadata (motion choice + zero-to-standing toggle).
            if ds.get("model_task"):
                entry["model_task"] = ds.get("model_task")
            if ds.get("model_zero_static") is not None:
                entry["model_zero_static"] = bool(ds.get("model_zero_static"))
            manifest["datasets"].append(entry)
        return manifest, files

    def load_project_state(self, manifest, datadir):
        from core.marker_model import MarkerModel
        from core.pipeline import Pipeline
        self._clear_analysis()
        # Restore the analysis pipeline (v3+). Backward compatible: older
        # projects have no "pipeline" key -> empty pipeline = raw, and any legacy
        # axis_settings filter keys in the manifest are simply ignored.
        self.pipeline = Pipeline.from_dict(manifest.get("pipeline"))
        datasets = []
        for entry in manifest.get("datasets", []):
            path = os.path.join(datadir, entry["data_file"]) if datadir else entry["data_file"]
            ds = self._read_csv_dataset(path)
            ds["name"] = entry.get("name", ds["name"])
            ds["path"] = entry.get("orig_path", "") or path
            ds["events"] = entry.get("events", [])
            ds["range_start"] = float(entry.get("range_start", ds["time"][0]))
            ds["range_end"] = float(entry.get("range_end", ds["time"][-1]))
            ds["analysis"] = None
            ds["_checked"] = bool(entry.get("checked", True))
            ds["folder"] = tuple(entry.get("folder") or ())
            ds["role"] = entry.get("role", "dynamic")
            ds["trial"] = entry.get("trial", "") or ds["name"]
            if entry.get("subject"):
                ds["subject"] = entry["subject"]
            # Restore markers (v2+). Backward compatible: older projects have no
            # "markers_file", so this is simply skipped and the dataset stays
            # force-only exactly as before.
            marker_arc = entry.get("markers_file")
            if marker_arc and datadir:
                markers = self._markers_from_npz_path(os.path.join(datadir, marker_arc))
                if markers is not None:
                    ds["markers"] = markers
            # Restore the kinematic model (v2+). model_result is recomputed lazily
            # by _ensure_model_result from this model + the subject's static.
            model_dict = entry.get("model")
            if model_dict:
                try:
                    ds["model"] = MarkerModel.from_dict(model_dict)
                except Exception:
                    pass
            # Restore force-plate geometry + raw channels, then rebuild the GRF
            # vector. Without this a reopened project shows no 3D force plates and
            # no GRF arrow (the geometry/raw moments aren't in the CSV).
            if entry.get("force_plates"):
                ds["force_plates"] = self._plates_from_json(entry["force_plates"])
            fpraw_arc = entry.get("fp_raw_file")
            if fpraw_arc and datadir:
                raw = self._fp_raw_from_npz_path(os.path.join(datadir, fpraw_arc))
                if raw is not None:
                    ds["_fp_raw"] = raw
            ds.setdefault("_clean_report", {"trimmed_head": 0})
            if ds.get("force_plates") and ds.get("_fp_raw"):
                ds["grf"] = build_grf(ds)
            # Restore the UI-side motion choice + zero-to-standing toggle. Older
            # projects lack these keys -> default (generic, no zeroing) = old behaviour.
            if entry.get("model_task"):
                ds["model_task"] = entry["model_task"]
            if entry.get("model_zero_static") is not None:
                ds["model_zero_static"] = bool(entry["model_zero_static"])
            datasets.append(ds)
        self.datasets = datasets
        self._folders = {tuple(p) for p in manifest.get("folders", [])}

        # Back-compat: projects saved before v4 auto-computed joint angles whenever
        # a model was assigned. v4 makes angles a pipeline step (sole source), so a
        # pre-v4 project with a model but no angle step would silently lose its
        # angles. Seed one ComputeAngleStep so those projects keep working. New
        # (v4+) projects are respected as-is — an intentional "no angle step" stays.
        if manifest.get("version", 0) < 4 and not self.pipeline.has_angle_step():
            if any(d.get("model") for d in self.datasets):
                from core.pipeline import ComputeAngleStep
                # Prepend so angles are produced before steps that consume them.
                self.pipeline.steps.insert(0, ComputeAngleStep())

        # Build the per-plate RAW toggles for the soon-to-be-current dataset so the
        # saved panel_visible (graph on/off) can re-check them below — they are
        # dynamic now (one group per force plate), not static checkboxes.
        cur = manifest.get("current_index")
        cur_ds = self.datasets[cur] if (cur is not None and 0 <= cur < len(self.datasets)) \
            else (self.datasets[0] if self.datasets else None)
        self._refresh_force_controls(cur_ds)

        pv = manifest.get("panel_visible", {})
        for key, cb in self.panel_checks.items():
            if key in pv:
                cb.blockSignals(True)
                cb.setChecked(bool(pv[key]))
                cb.blockSignals(False)
                self.panel_visible[key] = bool(pv[key])
        # Processed signals no longer have checkboxes (they live in RESULTS·Signals
        # and are graphed via right-click) — restore every saved "View as graph"
        # key: that's any True panel_visible key that ISN'T a RAW-toggle checkbox
        # (those are restored above) and isn't the COP-path flag (handled next).
        # Previously this kept only ":filt" twins, so derived-signal views (e.g.
        # an |Fz| compute output) were silently dropped on reload.
        self._signal_views = {k for k, v in pv.items()
                              if v and k != "traj" and k not in self.panel_checks}
        self._show_traj = bool(pv.get("traj", False))
        # Figure groups (which signals share one graph) + restored angle graphs.
        # Must follow the _signal_views restore (it may lazily add own-figure ids).
        self._restore_figure_groups(manifest.get("figure_groups"))
        # Back-compat: older projects stored "metrics_selected"/"angle_metrics_selected"
        # for the retired metric-checkbox panel. Metrics now live in the pipeline,
        # so those keys are simply ignored on load (no panel to restore them into).
        self.analysis_ranges = manifest.get("analysis_ranges", [])
        self._invalidate_models()
        self._refresh_file_list()   # checkbox state comes from each dataset["_checked"]

        self._set_file_count()
        current = manifest.get("current_index")
        if current is not None and 0 <= current < len(self.datasets):
            self.current_index = current
            self._select_dataset_item(current)
        elif self.datasets:
            self.current_index = 0
            self._select_dataset_item(0)

        self._refresh_pipeline_list()   # draw the restored pipeline's filter steps
        self._rebuild_plot_layout()
        self._refresh_event_controls(self._current_dataset())

        # Restore the Statistics-store rows the user had accumulated (v5+). The
        # store is shared with the Statistics tab via MainWindow; replacing its
        # rows here repopulates that tab when the project reopens. Older projects
        # have no "statistics_rows" key -> nothing to restore (store left as-is).
        stat_rows = manifest.get("statistics_rows")
        store = getattr(self, "results_store", None)
        if store is not None and stat_rows is not None:
            try:
                store.set_rows(stat_rows, source="Project")
            except Exception:
                pass

        # Re-run the pipeline if RESULTS were being shown when the project was
        # saved (v5+). RESULTS (metrics / detected events / derived signals) are a
        # deterministic function of pipeline + data, so rather than persist the big
        # arrays we recompute them by flipping the ▶Run toggle on — the same path
        # the user would take. Driving it through show_btn keeps view_mode / the
        # toggle / RESULTS panels consistent. Older projects (no key) load un-run,
        # exactly as before. Guarded so a failed re-run never blocks opening.
        if manifest.get("results_shown") and hasattr(self, "show_btn"):
            try:
                # Force the toggled edge to fire even if the button was already
                # checked from a previously-open project: reset it quietly first,
                # then check it so _on_show_results_toggled(True) always runs.
                self.show_btn.blockSignals(True)
                self.show_btn.setChecked(False)
                self.show_btn.blockSignals(False)
                self.show_btn.setChecked(True)   # -> _on_show_results_toggled -> _run_analysis
            except Exception:
                import logging
                logging.getLogger("analysis").exception(
                    "auto-run after project load failed")

    def _parse_file_meta(self, path):
        """Derive (trial, role) from the file. trial = filename (no ext); role =
        static if 'static' is in the filename or its immediate folder name."""
        base = os.path.splitext(os.path.basename(path))[0]
        parent = os.path.basename(os.path.dirname(path)).lower()
        role = "static" if ("static" in base.lower() or "static" in parent) else "dynamic"
        return base, role

    def _read_dataset(self, path, folder=()):
        """Read a CSV/C3D file and run the shared data-quality cleanup."""
        file_ext = os.path.splitext(path)[1].lower()

        if file_ext == ".c3d":
            data = read_c3d(path)
        elif file_ext == ".csv":
            data = self._read_csv_dataset(path)
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")

        report = clean_dataset(data)
        if not report.get("ok", True):
            raise ValueError("file contains no valid samples")
        data["_clean_report"] = report
        data["range_start"] = float(data["time"][0])
        data["range_end"] = float(data["time"][-1])
        # GRF arrow is built on the cleaned clock so it stays in step with playback.
        data["grf"] = build_grf(data)
        if data.get("markers"):
            data["_marker_report"] = clean_markers(data["markers"])

        trial, role = self._parse_file_meta(path)
        # Role is name-based only (filename/folder contains "static"); everything
        # else is dynamic. The user designates any other static via the file-tree
        # "Mark as Static" menu. We do NOT auto-promote by medial markers — dynamic
        # trials can carry medial markers too, so that heuristic mislabels them.
        data["folder"] = tuple(folder)
        data["trial"] = trial
        data["role"] = role
        return data

    def _read_csv_dataset(self, path):
        """Read dataset from CSV file."""
        from core import signals
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
        # Per-plate signals saved by _dataset_to_csv_bytes: any "fp{p}:comp"
        # column restores its array, and the plate count/key list is rebuilt so
        # the catalog / DATA section see the same multi-plate signals as the
        # original c3d. Also works for a hand-authored multi-plate CSV.
        plate_keys = [c for c in rows[0]
                      if c.startswith("fp") and ":" in c and signals._split_plate(c)[0]]
        if plate_keys:
            for key in plate_keys:
                data[key] = np.array([float(r[key]) for r in rows])
            data["force_signal_keys"] = plate_keys
            data["n_force_plates"] = max(signals._split_plate(k)[0] for k in plate_keys)
        else:
            # Plain single-plate CSV: synthesize FP1 from the bare keys so the UI
            # is uniformly plate-grouped (same as c3d files).
            from core.c3d_reader import ensure_fp1_from_bare
            ensure_fp1_from_bare(data)
        data["range_start"] = float(data["time"][0])
        data["range_end"] = float(data["time"][-1])

        if "fs" in rows[0] and rows[0]["fs"]:
            data["fs"] = float(rows[0]["fs"])
        else:
            dt = float(np.mean(np.diff(data["time"])))
            data["fs"] = 1.0 / dt if dt > 0 else 1000.0

        # Build the GRF vector arrow here too. The c3d path does this in
        # _read_dataset, but project LOAD uses this reader directly — without it a
        # reopened project shows no force-plate vector (the data is present, the
        # arrow just was never built). Cheap + deterministic.
        data["grf"] = build_grf(data)
        return data

    # ----- file tree (Windows-style nested folders -> file leaves) -----
    def _iter_file_items(self):
        """Yield every tree item (top-level + nested)."""
        def rec(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                yield child
                yield from rec(child)
        yield from rec(self.file_tree.invisibleRootItem())

    def _item_index(self, item):
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        return int(idx) if idx is not None else None

    @staticmethod
    def _is_folder_item(item):
        """Folder nodes carry a path tuple in FOLDER_PATH_ROLE (no dataset index)."""
        return item is not None and item.data(0, FOLDER_PATH_ROLE) is not None

    @staticmethod
    def _folder_path(item):
        """The folder path tuple of a folder node, or None for a file leaf."""
        return item.data(0, FOLDER_PATH_ROLE) if item is not None else None

    def _set_file_count(self):
        if hasattr(self, "file_count_chip"):
            self.file_count_chip.setText(str(len(self.datasets)))

    def _attach_resize_handle(self, layout, widget, key, default, min_h=60):
        """Give a sidebar list/tree a draggable height: set its persisted fixed
        height and append a splitter-style resize handle below it (the scroll area
        absorbs the change so sections below just move down)."""
        h = int(self._qsettings.value(key, default) or default)
        widget.setMinimumHeight(min_h)
        widget.setMaximumHeight(16777215)
        widget.setFixedHeight(max(min_h, min(1200, h)))
        handle = VResizeHandle(widget)
        handle.resized.connect(
            lambda hh, w=widget, k=key, m=min_h: self._set_widget_height(w, k, hh, m))
        layout.addWidget(handle)

    def _set_widget_height(self, widget, key, h, min_h=60):
        h = max(min_h, min(1200, int(h)))
        widget.setFixedHeight(h)
        self._qsettings.setValue(key, h)

    def _show_files_menu(self, global_pos):
        """Right-click the 'Files' title → file/folder actions."""
        menu = QMenu(self)
        menu.addAction("Load file", self._load_files)
        menu.addAction("Load folder", self._load_folder)
        menu.addAction("New folder", lambda: self._new_folder(()))
        menu.addSeparator()
        rm = menu.addAction("Remove all files…")
        rm.setEnabled(bool(self.datasets) or bool(self._folders))
        rm.triggered.connect(self._clear_all_files)
        menu.exec(global_pos)

    def _make_tree_item(self, index):
        """A file (leaf) row. Label = trial name; static rows get a model badge."""
        d = self.datasets[index]
        label = d.get("trial") or d["name"]
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, index)
        # Files are checkable and draggable (into any folder); they don't accept drops.
        flags = (item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                 | Qt.ItemFlag.ItemIsDragEnabled) & ~Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)
        item.setCheckState(
            0, Qt.CheckState.Checked if d.get("_checked", True) else Qt.CheckState.Unchecked)
        item.setToolTip(0, d["path"])
        return item

    def _make_model_icon(self, index):
        """Column-1 widget for a static row: a fixed-size dot — filled when a
        model is assigned, an outline when not (equal sizes). Name in tooltip."""
        d = self.datasets[index]
        model = d.get("model")
        dot = QLabel()
        dot.setFixedSize(12, 12)
        if model is not None:
            dot.setObjectName("model-icon")
            tip = f"Model: {getattr(model, 'name', '') or 'model'} — double-click the static to edit"
        else:
            dot.setObjectName("model-icon-empty")
            tip = "No model — double-click the static to build one"
        dot.setToolTip(tip)
        # Centre the fixed-size dot within the column cell.
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addStretch(1)
        wl.addWidget(dot)
        wl.addStretch(1)
        wrap.setToolTip(tip)
        return wrap

    # ----- tree build (Windows-style folder tree) -----
    def _folder_icon(self):
        ic = getattr(self, "_folder_icon_cache", None)
        if ic is None:
            from ui.main_window import resource_path
            ic = QIcon(resource_path("assets/folder.svg"))
            self._folder_icon_cache = ic
        return ic

    @staticmethod
    def _natkey(s):
        """Natural sort key: '01' < '02' < '10' (digits compared numerically).
        Each token is (rank, num, text) so int/str never compare against each other."""
        out = []
        for t in re.split(r"(\d+)", str(s)):
            if t.isdigit():
                out.append((0, int(t), ""))
            elif t:
                out.append((1, 0, t.lower()))
        return tuple(out)

    def _make_folder_node(self, path):
        """A non-checkable folder node (chevron + icon + name); accepts drops, draggable."""
        node = QTreeWidgetItem([path[-1] if path else ""])
        node.setData(0, Qt.ItemDataRole.UserRole, None)
        node.setData(0, FOLDER_PATH_ROLE, tuple(path))
        node.setIcon(0, self._folder_icon())
        flags = (node.flags() | Qt.ItemFlag.ItemIsDropEnabled
                 | Qt.ItemFlag.ItemIsDragEnabled) & ~Qt.ItemFlag.ItemIsUserCheckable
        node.setFlags(flags)
        f = node.font(0)
        f.setBold(True)
        node.setFont(0, f)
        return node

    def _update_folder_chevron(self, node):
        """Prefix a folder label with ▾ (open) / ▸ (closed)."""
        path = self._folder_path(node) or ()
        name = path[-1] if path else ""
        node.setText(0, ("▾ " if node.isExpanded() else "▸ ") + name)

    def _all_folder_paths(self):
        """Every folder path to render = explicit folders (incl. empty) + every
        dataset's folder and all ancestors. Root () excluded (not a node)."""
        paths = set()
        for p in list(self._folders):
            p = tuple(p)
            for k in range(1, len(p) + 1):
                paths.add(p[:k])
        for d in self.datasets:
            f = tuple(d.get("folder") or ())
            for k in range(1, len(f) + 1):
                paths.add(f[:k])
        return paths

    def _refresh_file_list(self):
        self._refreshing_tree = True
        self.file_tree.clear()
        nat = self._natkey
        folder_key = lambda p: (len(p), tuple(nat(c) for c in p))   # siblings name-ordered
        # Folders first (parents before children, natural-sorted), then files.
        node_by_path = {(): None}
        folder_nodes = []
        for path in sorted(self._all_folder_paths(), key=folder_key):
            node = self._make_folder_node(path)
            parent = node_by_path.get(path[:-1])
            if parent is None:
                self.file_tree.addTopLevelItem(node)
            else:
                parent.addChild(node)
            node_by_path[path] = node
            folder_nodes.append((path, node))
        order = sorted(range(len(self.datasets)),
                       key=lambda i: (folder_key(tuple(self.datasets[i].get("folder") or ())),
                                      nat(self.datasets[i].get("trial") or self.datasets[i]["name"])))
        for i in order:
            f = tuple(self.datasets[i].get("folder") or ())
            leaf = self._make_tree_item(i)
            parent = node_by_path.get(f)
            if parent is None:
                self.file_tree.addTopLevelItem(leaf)
            else:
                parent.addChild(leaf)
        for p in range(self.file_tree.topLevelItemCount()):
            self._decorate_item(self.file_tree.topLevelItem(p))
        # Expand/collapse per remembered state (accordion), update chevrons.
        for path, node in folder_nodes:
            node.setExpanded(path not in self._collapsed_folders)
            self._update_folder_chevron(node)
        self._refreshing_tree = False
        self._highlight_current_file()
        self._filter_file_list(self.search_input.text() if hasattr(self, "search_input") else "")

    def _decorate_item(self, item):
        """Post-order: attach the model badge to static file rows."""
        for i in range(item.childCount()):
            self._decorate_item(item.child(i))
        idx = self._item_index(item)
        if idx is not None and self.datasets[idx].get("role") == "static":
            self.file_tree.setItemWidget(item, 1, self._make_model_icon(idx))

    # ----- folder operations (Windows-style) -----
    def _known_folders(self):
        """Sorted list of folder paths (for the 'Move to folder' menu)."""
        return sorted(self._all_folder_paths(), key=lambda p: (len(p), p))

    def _new_folder(self, parent_path):
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        name = name.strip() if ok else ""
        if not name:
            return
        self._folders.add(tuple(parent_path) + (name,))
        self._refresh_file_list()

    def _rename_folder(self, path):
        path = tuple(path)
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Rename folder", "New name:", text=path[-1])
        name = name.strip() if ok else ""
        if not name or name == path[-1]:
            return
        new_path = path[:-1] + (name,)
        self._reparent_paths(path, new_path)
        self._refresh_file_list()

    def _delete_folder(self, path):
        path = tuple(path)
        if not path:
            return
        n = sum(1 for d in self.datasets if tuple(d.get("folder") or ())[:len(path)] == path)
        if QMessageBox.question(
                self, "Delete folder",
                f"Delete folder '{'/'.join(path)}' and its {n} file(s)?") \
                != QMessageBox.StandardButton.Yes:
            return
        # Drop folders + files under this path.
        self._folders = {p for p in self._folders if tuple(p)[:len(path)] != path}
        keep = [d for d in self.datasets if tuple(d.get("folder") or ())[:len(path)] != path]
        if len(keep) != len(self.datasets):
            self._delete_loaded_files(
                [i for i, d in enumerate(self.datasets)
                 if tuple(d.get("folder") or ())[:len(path)] == path])
        else:
            self._invalidate_models()
            self._refresh_file_list()

    def _reparent_paths(self, old_path, new_path):
        """Rewrite a folder path prefix on `_folders` and dataset folders."""
        old, new, n = tuple(old_path), tuple(new_path), len(old_path)
        self._folders = {(new + tuple(p)[n:]) if tuple(p)[:n] == old else tuple(p)
                         for p in self._folders}
        self._folders.add(new)
        for d in self.datasets:
            f = tuple(d.get("folder") or ())
            if f[:n] == old:
                d["folder"] = new + f[n:]
        self._invalidate_models()

    def _move_to_folder(self, indices, folder):
        self._sync_dataset_checked_state()
        folder = tuple(folder)
        if folder:
            self._folders.add(folder)
        for i in indices:
            if 0 <= i < len(self.datasets):
                self.datasets[i]["folder"] = folder
        self._invalidate_models()
        self._refresh_file_list()

    def _add_move_to_folder_submenu(self, menu, index):
        sel = self._selected_leaf_indices()
        if index not in sel:
            sel = [index]
        sub = menu.addMenu("Move to folder")
        for path in self._known_folders():
            sub.addAction("/".join(path),
                          lambda _=False, p=path, idxs=list(sel): self._move_to_folder(idxs, p))
        sub.addSeparator()
        sub.addAction("New folder…", lambda idxs=list(sel): self._move_to_new_folder(idxs))

    def _move_to_new_folder(self, indices):
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        name = name.strip() if ok else ""
        if not name:
            return
        self._move_to_folder(indices, (name,))

    def _update_parent_check(self, parent):
        """Set a node's tri-state checkbox from its direct children's states."""
        n = parent.childCount()
        if n == 0:
            return
        states = [parent.child(i).checkState(0) for i in range(n)]
        if all(s == Qt.CheckState.Checked for s in states):
            state = Qt.CheckState.Checked
        elif all(s == Qt.CheckState.Unchecked for s in states):
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        parent.setCheckState(0, state)

    def _filter_file_list(self, text: str):
        text = text.strip().lower()

        def visit(item):
            """Return True if `item` (or any descendant) matches → keep visible."""
            idx = self._item_index(item)
            self_match = (not text) or (text in item.text(0).lower()) or (
                idx is not None and text in self.datasets[idx]["path"].lower())
            child_visible = False
            for c in range(item.childCount()):
                child_visible = visit(item.child(c)) or child_visible
            keep = self_match or child_visible
            item.setHidden(bool(text) and not keep)
            return keep

        root = self.file_tree.invisibleRootItem()
        for p in range(root.childCount()):
            visit(root.child(p))

    def _checked_dataset_indexes(self):
        indexes = []
        for item in self._iter_file_items():
            idx = self._item_index(item)
            if idx is not None and item.checkState(0) == Qt.CheckState.Checked:
                indexes.append(idx)
        return indexes

    def _checked_static_indexes(self):
        return [i for i in self._checked_dataset_indexes()
                if self.datasets[i].get("role") == "static"]

    def _sync_dataset_checked_state(self):
        if not hasattr(self, "file_tree"):
            return
        for item in self._iter_file_items():
            idx = self._item_index(item)
            if idx is not None and 0 <= idx < len(self.datasets):
                self.datasets[idx]["_checked"] = item.checkState(0) == Qt.CheckState.Checked

    def _active_dataset_indexes(self):
        return [
            index for index in self._checked_dataset_indexes()
            if 0 <= index < len(self.datasets)
        ]

    def _current_dataset(self):
        if self.current_index is None:
            return None
        if not 0 <= self.current_index < len(self.datasets):
            return None
        return self.datasets[self.current_index]

    def _show_file_context_menu(self, pos):
        item = self.file_tree.itemAt(pos)
        if item is None:
            return
        index = self._item_index(item)
        if index is None:
            # Folder node → folder ops + check-all.
            path = tuple(self._folder_path(item) or ())
            menu = QMenu(self)
            new_f = menu.addAction("New folder inside")
            rename_f = menu.addAction("Rename folder…")
            delete_f = menu.addAction("Delete folder")
            menu.addSeparator()
            check_all = menu.addAction("Check all files")
            uncheck_all = menu.addAction("Uncheck all files")
            chosen = menu.exec(self.file_tree.viewport().mapToGlobal(pos))
            if chosen is new_f:
                self._new_folder(path)
            elif chosen is rename_f:
                self._rename_folder(path)
            elif chosen is delete_f:
                self._delete_folder(path)
            elif chosen is check_all:
                self._set_folder_checked(item, True)
            elif chosen is uncheck_all:
                self._set_folder_checked(item, False)
            return
        d = self.datasets[index]
        role = d.get("role")
        menu = QMenu(self)
        acts = {}
        if role == "static":
            acts["subject"] = menu.addAction("Subject info…")
            menu.addSeparator()
            has_markers = bool(d.get("markers"))
            acts["build"] = menu.addAction(
                "Edit model…" if d.get("model") is not None else "Build model…")
            acts["build"].setEnabled(has_markers)
            acts["load"] = menu.addAction("Load model… (change)")
            if d.get("model") is not None:
                acts["save"] = menu.addAction("Save model…")
            acts["assign"] = menu.addAction("Assign model to checked statics")
            acts["assign"].setEnabled(d.get("model") is not None)
            if d.get("model") is not None:
                acts["clear"] = menu.addAction("Clear model")
            menu.addSeparator()
            acts["dyn"] = menu.addAction("Mark as Dynamic")
        else:
            acts["stat"] = menu.addAction("Mark as Static")
        self._add_move_to_folder_submenu(menu, index)
        menu.addSeparator()
        sel = self._selected_leaf_indices()
        if index not in sel:
            sel = [index]
        acts["del"] = menu.addAction(
            f"Delete {len(sel)} files" if len(sel) > 1 else "Delete file")
        action = menu.exec(self.file_tree.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action is acts.get("subject"):
            self._edit_subject_info(d)
        elif action is acts.get("build"):
            self._build_model(d)
        elif action is acts.get("load"):
            self._load_model(d)
        elif action is acts.get("save"):
            self._save_model(d)
        elif action is acts.get("assign"):
            self._assign_model_to_checked(d.get("model"))
        elif action is acts.get("clear"):
            d["model"] = None
            self._invalidate_models()
            self._refresh_file_list()
            self._rebuild_plot_layout()
        elif action is acts.get("stat"):
            d["role"] = "static"
            self._refresh_file_list()
        elif action is acts.get("dyn"):
            d["role"] = "dynamic"
            self._refresh_file_list()
        elif action is acts.get("del"):
            self._delete_loaded_files(sel)

    def _on_file_double_clicked(self, item, column=0):
        """Double-click a static row → build/edit its joint-angle model."""
        index = self._item_index(item)
        if index is None:
            return
        if self.datasets[index].get("role") == "static":
            self._build_model(self.datasets[index])

    def _ancestor_folder(self, item):
        """Folder path the drop target lives in (the folder node itself, or a
        leaf's containing folder); root () if dropped on the top level."""
        while item is not None:
            if self._is_folder_item(item):
                return tuple(self._folder_path(item) or ())
            item = item.parent()
        return ()

    def _on_tree_item_dropped(self, src, target):
        """Windows-style move: drag a file into a folder (or root), or drag a
        folder into another folder (reparent its whole subtree)."""
        if src is None:
            return
        dest = self._ancestor_folder(target)
        if self._is_folder_item(src):
            old = tuple(self._folder_path(src) or ())
            if not old or dest[:len(old)] == old:   # nothing / into itself or descendant
                return
            new = dest + (old[-1],)
            if new == old:
                return
            self._sync_dataset_checked_state()
            self._reparent_paths(old, new)
            self._refresh_file_list()
            return
        # File leaf → move it (and any co-selected files) into the destination folder.
        index = self._item_index(src)
        if index is None:
            return
        sel = self._selected_leaf_indices()
        if index not in sel:
            sel = [index]
        self._move_to_folder(sel, dest)

    def _select_dataset_item(self, index):
        for item in self._iter_file_items():
            if self._item_index(item) == index:
                self.file_tree.setCurrentItem(item)
                return

    def _set_subtree_checked(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_subtree_checked(child, state)

    def _update_ancestor_checks(self, item):
        parent = item.parent()
        while parent is not None:
            self._update_parent_check(parent)
            parent = parent.parent()

    def _on_file_item_changed(self, item, column):
        # Only leaf files are checkable (folders use the right-click "Check all").
        if getattr(self, "_refreshing_tree", False):
            return
        self._sync_dataset_checked_state()
        self._recolor_tree_items()

    def _set_folder_checked(self, folder_item, checked):
        """Right-click 'Check/Uncheck all files' on a folder (subject/group)."""
        self._refreshing_tree = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._set_subtree_checked(folder_item, state)
        self._refreshing_tree = False
        self._sync_dataset_checked_state()
        self._recolor_tree_items()

    def _delete_loaded_file(self, index):
        if not 0 <= index < len(self.datasets):
            return

        self._stop_playback()
        self._sync_dataset_checked_state()
        removed = self.datasets.pop(index)
        removed_path = removed.get("path")
        if removed_path:
            self.analysis_results = [
                result for result in self.analysis_results
                if result.get("path") != removed_path
            ]
            self.summary_rows = self._compute_summary_rows(self.analysis_results) if self.analysis_results else []

        if not self.datasets:
            self.current_index = None
            self._refresh_file_list()
            self._set_file_count()
            self._refresh_review_controls(None)
            self._refresh_event_controls(None)
            self._clear_event_lines()
            self._set_placeholder("Load files and run analysis")
            self._rebuild_plot_layout()
            return

        if self.current_index is None:
            self.current_index = 0
        elif self.current_index == index:
            self.current_index = min(index, len(self.datasets) - 1)
        elif self.current_index > index:
            self.current_index -= 1

        self._refresh_file_list()
        self._set_file_count()
        self._select_dataset_item(self.current_index)
        dataset = self.datasets[self.current_index]
        self._refresh_event_controls(dataset)
        if dataset.get("analysis"):
            self.view_mode = "analysis"
            self._show_analysis(dataset)
        else:
            self._plot_dataset(dataset)
            self._set_placeholder("Run analysis to see metrics")

    # ----- multi-select / subject management -----
    def _selected_leaf_indices(self):
        """Dataset indices of the currently selected file (leaf) rows."""
        out = []
        for item in self.file_tree.selectedItems():
            idx = self._item_index(item)
            if idx is not None and idx not in out:
                out.append(idx)
        return out

    def _delete_loaded_files(self, indices):
        for i in sorted({int(x) for x in indices}, reverse=True):
            self._delete_loaded_file(i)

    def _on_file_clicked(self, item, column=0):
        idx = self._item_index(item)
        if idx is None:   # folder node → toggle expand/collapse (accordion)
            if self._is_folder_item(item):
                path = tuple(self._folder_path(item) or ())
                expand = not item.isExpanded()
                item.setExpanded(expand)
                if expand:
                    self._collapsed_folders.discard(path)
                else:
                    self._collapsed_folders.add(path)
                self._update_folder_chevron(item)
            return
        self._stop_playback()
        self.current_index = idx
        dataset = self.datasets[self.current_index]
        self._highlight_current_file()
        self._refresh_event_controls(dataset)
        # Rebuild the plot layout so marker/coordinate/joint-angle panels follow
        # the newly selected dataset (COP/force alone would just re-setData).
        self.view_mode = "analysis" if dataset.get("analysis") else "review"
        self._rebuild_plot_layout()
        if not dataset.get("analysis"):
            self._set_placeholder("Run analysis to see metrics")

    def _refresh_review_controls(self, dataset=None):
        if dataset is None:
            dataset = self._current_dataset()
        enabled = dataset is not None
        self.frame_slider.setEnabled(enabled)
        self.full_range_btn.setEnabled(enabled)
        if hasattr(self, "region_toggle_btn"):
            self.region_toggle_btn.setEnabled(enabled)
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(enabled)
        for w in ("frame_spin", "time_spin", "playmode_btn"):
            if hasattr(self, w):
                getattr(self, w).setEnabled(enabled)
        if not enabled:
            self.frame_total_lbl.setText("/ -")
            self.frame_slider.setEnabled(False)
            return

        self.frame_slider.setEnabled(True)
        t_min = float(dataset["time"][0])
        t_max = float(dataset["time"][-1])
        n = len(dataset["time"])
        self.frame_spin.blockSignals(True)
        self.frame_spin.setMaximum(max(1, n))
        self.frame_spin.blockSignals(False)
        self.frame_total_lbl.setText(f"/ {n:,}")
        self.time_spin.blockSignals(True)
        self.time_spin.setRange(t_min, t_max)
        self.time_spin.blockSignals(False)
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
        self.play_index = int(np.searchsorted(dataset["time"], float(current_time)))
        self.play_index = max(0, min(len(dataset["time"]) - 1, self.play_index))
        if self.play_index >= len(dataset["time"]) - 1:
            self.play_index = 0
            self.frame_slider.set_current(float(dataset["time"][0]))

        # Anchor playback to the wall clock so a slow render drops frames instead
        # of backlogging the timer (keeps real-time speed for any data size).
        self._play_wall0 = time.perf_counter()
        self._play_t0 = float(dataset["time"][self.play_index])

        self.play_btn.setText("❚❚")
        self.play_btn.setObjectName("play-btn-active")
        self.play_btn.style().unpolish(self.play_btn)
        self.play_btn.style().polish(self.play_btn)
        self._playback_step()
        # ~60 FPS for smooth light-data playback; wall-clock targeting + Qt timer
        # coalescing drop frames on heavy data so it never backlogs.
        self.play_timer.start(16)

    def _stop_playback(self):
        if hasattr(self, "play_timer") and self.play_timer.isActive():
            self.play_timer.stop()
        if hasattr(self, "play_btn"):
            self.play_btn.setText("▶")
            self.play_btn.setObjectName("play-btn")
            self.play_btn.style().unpolish(self.play_btn)
            self.play_btn.style().polish(self.play_btn)

    def _playback_step(self):
        dataset = self._current_dataset()
        if dataset is None or len(dataset["time"]) == 0:
            self._stop_playback()
            return

        T = dataset["time"]
        n = len(T)
        if getattr(self, "_play_every_frame", False):
            # Precise mode: one sample per tick.
            self.play_index = min(n - 1, self.play_index + 1)
        else:
            # Real-time mode: jump to wherever the wall clock says we should be.
            # If rendering is slow the target moves further each tick → frames are
            # dropped rather than queued, so playback never falls behind.
            target = self._play_t0 + (time.perf_counter() - self._play_wall0)
            self.play_index = int(np.searchsorted(T, target))
            self.play_index = max(0, min(n - 1, self.play_index))
        self.frame_slider.set_current(float(T[self.play_index]))

        if self.play_index >= n - 1:
            self._stop_playback()

    def _on_slider_range_changed(self, start, end):
        dataset = self._current_dataset()
        if dataset is None or self._updating_range_slider:
            return
        self._apply_range_to_checked_files(start, end, include_current=True)
        self._update_range_region(dataset)
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
        if getattr(self, "_marker_list_for", None) is not dataset:
            self._refresh_marker_controls(dataset)
            self._refresh_force_controls(dataset)
            self._marker_list_for = dataset
        # Review (un-run) dataset → its cached run output if any, else none, so
        # RESULTS·Metrics reflects only what's actually been computed for it.
        self._last_run_result = dataset.get("_run_result") if dataset else None
        self._render_force_curves(dataset)
        self._render_trajectory(dataset)
        self._show_range_region(dataset)
        self._draw_events(dataset)
        self._refresh_event_list(dataset)
        self._refresh_results_panels(dataset)
        self._refresh_review_controls(dataset)

    def _render_force_curves(self, dataset, start=None, end=None):
        """Draw every built per-plate force/COP plot from the signal registry.

        Key-driven: for each plot in ``_raw_curves`` the raw curve = the signal's
        series and the filtered twin = its ``:filt`` derivative (drawn only when
        the pipeline filters that key and the twin toggle is on). ``start``/``end``
        window the curves to a range (analysis view); otherwise the full clock is
        shown. Signals resolve through one cached :class:`Workspace`."""
        if not self._raw_curves:
            return
        ws = Workspace(dataset, pipeline=self.pipeline,
                       angle_result=self._angle_result_for(dataset),
                       metrics=self._subject_metrics(dataset))
        t = np.asarray(dataset["time"], dtype=float)
        mask = None
        if start is not None and end is not None:
            mask = (t >= float(start)) & (t <= float(end))
            tt = t[mask]
        else:
            tt = t
        lw = self.appearance.line_width()
        # Faint grey for the raw curve when its filtered twin is also shown, so the
        # two are distinguishable (filtered = channel colour, raw = pale reference).
        raw_grey = "#9aa1ab"
        for key, (raw_curve, filt_curve) in self._raw_curves.items():
            try:
                raw_vals = ws.series(key)
            except Exception:
                raw_vals = None
            if raw_vals is not None and mask is not None:
                raw_vals = raw_vals[mask]
            spec = self.pipeline.filter_spec_for(key)
            filt_shown = spec is not None and self.panel_visible.get(f"{key}:filt", False)
            color = self._curve_color_for(key)
            # Filtered shown -> raw is the pale-grey reference, filtered is the
            # channel colour. Lone raw signal -> raw keeps the channel colour.
            raw_curve.setPen(pg.mkPen(raw_grey if filt_shown else color, width=lw))
            self._set_curve(raw_curve, tt, raw_vals, self.panel_visible.get(key, False))
            if filt_shown:
                filt_curve.setPen(pg.mkPen(color, width=lw))
                filt_vals = ws.series(f"{key}:filt")
                if mask is not None:
                    filt_vals = filt_vals[mask]
                self._set_curve(filt_curve, tt, filt_vals, True)
            else:
                self._set_curve(filt_curve, tt, None, False)
            # Force plots: pin the y-axis to include 0 so a flat-but-large signal
            # (e.g. Fz ~450 N) reads at its true height, not zoomed to its wobble.
            self._apply_y_baseline(self._raw_plots.get(key))

    def _apply_y_baseline(self, plot):
        """If ``plot`` has a ``_y_baseline`` (force plots → 0), set its y-range to
        span [min(baseline, data_min), max(baseline, data_max)] with a small pad,
        and disable y auto-range so the baseline sticks across playback re-renders.

        Plots without a baseline (COP/markers/angles) are left on their default
        data-range auto-zoom — their zero is arbitrary, so a tight view is right.
        """
        if plot is None:
            return
        baseline = getattr(plot, "_y_baseline", None)
        if baseline is None:
            return
        bounds = self._plot_data_bounds(plot)
        if bounds is None:
            return
        _, _, y_min, y_max = bounds
        lo = min(y_min, baseline)
        hi = max(y_max, baseline)
        if lo == hi:
            hi = lo + 1.0
        plot.getPlotItem().getViewBox().enableAutoRange(axis="y", enable=False)
        # A little headroom above the peak; the baseline edge sits flush at 0.
        pad = (hi - lo) * 0.06
        if baseline == lo:
            plot.setYRange(lo, hi + pad, padding=0)
        elif baseline == hi:
            plot.setYRange(lo - pad, hi, padding=0)
        else:
            plot.setYRange(lo - pad, hi + pad, padding=0)

    def _style_region_toggle(self):
        if not hasattr(self, "region_toggle_btn"):
            return
        self.region_toggle_btn.setStyleSheet(S.region_toggle_style())

    def _on_region_toggle_changed(self, checked):
        self.review_region_visible = bool(checked)
        dataset = self._current_dataset()
        if not checked:
            self._clear_review_region()
            return
        if dataset is not None and self.view_mode == "review":
            self._show_range_region(dataset)

    def _top_time_plot(self):
        for plot in self._raw_plots.values():
            if plot is not None:
                return plot
        return None

    def _clear_review_region(self):
        for region in self.review_regions:
            try:
                region.getViewBox().removeItem(region)
            except Exception:
                pass
        self.review_regions = []

    def _show_range_region(self, dataset):
        self._clear_review_region()

        if not self.review_region_visible:
            return
        if not self._time_plots:
            return

        t_min = float(dataset["time"][0])
        t_max = float(dataset["time"][-1])
        start = float(dataset.get("range_start", t_min))
        end = float(dataset.get("range_end", t_max))
        # One highlight region per visible time-series plot.
        for plot in self._time_plots:
            region = pg.LinearRegionItem(
                values=(start, end),
                orientation=pg.LinearRegionItem.Vertical,
                brush=pg.mkBrush(60, 130, 255, 55),
                pen=pg.mkPen("#3B82F6", width=1),
                movable=False,
            )
            region.setBounds((t_min, t_max))
            plot.addItem(region)
            self.review_regions.append(region)

        for line in self.review_cursor_lines:
            line.setVisible(True)

    def _update_range_region(self, dataset):
        if not self.review_region_visible:
            self._clear_review_region()
            return
        if not self.review_regions:
            self._show_range_region(dataset)
            return
        rng = (float(dataset["range_start"]), float(dataset["range_end"]))
        for region in self.review_regions:
            region.setRegion(rng)

    def _hide_review_marks(self):
        self._clear_review_region()
        for line in self.review_cursor_lines:
            line.setVisible(False)

    def _set_review_time(self, value):
        dataset = self._current_dataset()
        if dataset is None:
            self.frame_total_lbl.setText("/ -")
            return

        self._review_time = float(value)
        tarr = dataset["time"]
        # O(log N) index on the sorted time base (was argmin O(N), ×/tick).
        index = int(np.searchsorted(tarr, float(value)))
        if index >= len(tarr):
            index = len(tarr) - 1
        elif index > 0 and (float(value) - tarr[index - 1]) < (tarr[index] - float(value)):
            index -= 1
        t = float(tarr[index])
        for line in self.review_cursor_lines:
            line.setPos(t)
            line.setVisible(self.view_mode == "review")
        # The trajectory plot's marker tracks the live COP frame in review mode.
        # Index the SAME mean-centred arrays the grey path was drawn from
        # (_traj_centred) so the dot sits exactly on the line — computing it from a
        # different source/plate/mean here made the dot drift off the trajectory.
        if self.c_mean is not None and self.c_traj is not None:
            xy = getattr(self, "_traj_centred", None)
            if xy is not None and 0 <= index < len(xy[0]):
                self.c_mean.setData([float(xy[0][index])], [float(xy[1][index])])
        # Reflect the current frame/time in the editable fields (without re-jumping).
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(index + 1)
        self.frame_spin.blockSignals(False)
        self.time_spin.blockSignals(True)
        self.time_spin.setValue(t)
        self.time_spin.blockSignals(False)
        # Drive the 3D marker view (its own clock). Resolve the marker-frame index
        # once and share it with the overlay (avoids two more per-tick argmins).
        if (self.marker_view is not None and self.panel_visible.get("markers3d")
                and dataset.get("markers")):
            mt = dataset["markers"]["time"]
            midx = int(np.searchsorted(mt, t)) if len(mt) else 0
            midx = max(0, min(len(mt) - 1, midx))
            self.marker_view.update_frame(t, idx=midx)
            self._update_model_overlay(dataset, t, idx=midx)

    def _jump_to_frame(self):
        dataset = self._current_dataset()
        if dataset is None:
            return
        n = len(dataset["time"])
        idx = max(0, min(n - 1, self.frame_spin.value() - 1))
        self.frame_slider.set_current(float(dataset["time"][idx]))

    def _jump_to_time(self):
        dataset = self._current_dataset()
        if dataset is None:
            return
        t = float(self.time_spin.value())
        idx = int(np.argmin(np.abs(dataset["time"] - t)))
        self.frame_slider.set_current(float(dataset["time"][idx]))

    def _step_frame(self, delta):
        dataset = self._current_dataset()
        if dataset is None or self.play_timer.isActive():
            return
        n = len(dataset["time"])
        _, _, cur = self.frame_slider.values()
        idx = int(np.argmin(np.abs(dataset["time"] - float(cur))))
        idx = max(0, min(n - 1, idx + int(delta)))
        self.frame_slider.set_current(float(dataset["time"][idx]))

    def _on_playmode_toggled(self, checked):
        self._play_every_frame = bool(checked)
        self.playmode_btn.setText("Every frame" if checked else "Capture rate")

    def _cop_series(self, ap, ml):
        """Resultant COP distance about the mean (posturography standard).

        Thin wrapper over ``core.signals.cop_resultant`` so the graph/table
        "COP" curve uses the same single definition as the event-channel "cop"
        signal (mean-subtracted RD, per Prieto et al. 1996).
        """
        return cop_resultant(ap, ml)

    def _set_curve(self, curve, t, values, visible):
        """Set ``curve`` to ``(t, values)`` when ``visible`` else clear it.

        A tiny helper so the RAW / "(filtered)" Data toggles can each show or hide
        their own curve without duplicating the None-guard everywhere."""
        if curve is None:
            return
        if visible and values is not None:
            curve.setData(t, values)
        else:
            curve.setData([], [])

    def _run_analysis(self):
        """Run analysis on the checked files. Returns True if results were shown."""
        if not self.datasets:
            QMessageBox.information(self, "No files", "Load files before analysis.")
            return False

        checked_indexes = self._checked_dataset_indexes()
        if not checked_indexes:
            QMessageBox.information(self, "No files selected", "Check files to include in analysis.")
            return False

        # Metrics now come from the pipeline's Metric steps (computed in
        # _analyze_time_window via run_pipeline), not from removed checkbox panels.
        selected, angle_stats = [], []

        # A fresh run regenerates all detected events: drop any view-level
        # deletions (RESULTS·Events Delete is a temporary cleanup, not permanent).
        self._hidden_event_labels.clear()

        self.analysis_results = []
        for dataset in self.datasets:
            dataset["analysis"] = None

        errors = []
        for index in checked_indexes:
            dataset = self.datasets[index]
            try:
                analysis = self._analyze_dataset(dataset, selected, angle_stats)
                dataset["analysis"] = analysis
                self.analysis_results.append(analysis)
            except Exception as exc:
                errors.append(f"{dataset['name']}: {exc}")

        if not self.analysis_results:
            QMessageBox.warning(self, "Analysis failed", "\n".join(errors[:8]))
            return False

        self.summary_rows = self._compute_summary_rows(self.analysis_results)

        if self.current_index not in checked_indexes:
            self.current_index = checked_indexes[0]
        self._select_dataset_item(self.current_index)
        self.view_mode = "analysis"
        self._show_analysis(self.datasets[self.current_index])
        if errors:
            QMessageBox.warning(self, "Some files skipped", "\n".join(errors[:8]))
        return True

    def _analyze_dataset(self, dataset, selected, angle_stats=None):
        start = float(dataset.get("range_start", dataset["time"][0]))
        end = float(dataset.get("range_end", dataset["time"][-1]))
        return self._analyze_time_window(dataset, start, end, selected, "Selected range",
                                         angle_stats=angle_stats)

    def _analyze_time_window(self, dataset, start, end, selected, range_name, angle_stats=None):
        mask = (dataset["time"] >= start) & (dataset["time"] <= end)
        if int(np.sum(mask)) < 2:
            raise ValueError("selected range has fewer than 2 samples")

        frame_indexes = np.flatnonzero(mask)
        ap_all, ml_all = self._cop_ap_ml(dataset)
        ap_raw = ap_all[mask]
        ml_raw = ml_all[mask]
        t = dataset["time"][mask]
        fs = dataset["fs"]

        spec = self._force_filter_spec()
        if spec is not None:
            ap = spec.apply(ap_raw, fs)
            ml = spec.apply(ml_raw, fs)
        else:
            ap = ap_raw
            ml = ml_raw

        metrics = compute_metrics(ap, ml, fs, selected)
        # Angle metrics from the subject's joint-angle model. model_result is still
        # computed (the 3D segment overlay needs it), but joint angles only feed the
        # ANALYSIS when a ComputeAngle step is in the recipe (pipeline = sole source
        # of derived signals) — so use the gated _angle_result_for here.
        self._ensure_model_result(dataset)
        angle_result = self._angle_result_for(dataset)
        if angle_stats and angle_result and dataset.get("markers"):
            metrics.update(compute_angle_metrics(
                angle_result["angles"], dataset["markers"]["time"], start, end, angle_stats))
        # Pipeline MetricSteps (the new dataflow path): their results join the
        # cards/summary as ``{name: (value, unit)}``, computed over each step's own
        # segment (whole trial / per cycle). Failures degrade silently (one bad
        # step must not break the whole analysis).
        try:
            from core.run import run_pipeline
            markers = dataset.get("markers")
            disp = self._marker_display_data(markers) if markers else None
            res = run_pipeline(dataset, self.pipeline, marker_disp=disp,
                               angle_result=angle_result,
                               subject=self._subject_for(dataset))
            metrics.update(res["metric_values"])
            # Cache the full run result on the dataset (per-cycle values / SD / n)
            # so RESULTS·Metrics tables and the metric value tags can read it.
            dataset["_run_result"] = res
        except Exception:
            # Degrade gracefully (one bad step must not break the whole analysis),
            # but LOG the full traceback so the calculation error is diagnosable
            # instead of silently vanishing.
            import logging
            logging.getLogger("analysis").exception(
                "pipeline run failed for trial %r", dataset.get("name"))
        enabled_events = [
            dict(event)
            for event in dataset.get("events", [])
            if event.get("enabled", True)
        ]
        return {
            "file": dataset["name"],
            "folder": "/".join(dataset.get("folder") or ()),
            "condition": dataset.get("trial", ""),
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
        if getattr(self, "_marker_list_for", None) is not dataset:
            self._refresh_marker_controls(dataset)
            self._refresh_force_controls(dataset)
            self._marker_list_for = dataset
        self._highlight_current_file()
        self._hide_review_marks()

        # This file's last run output drives the RESULTS·Metrics list/value tables.
        self._last_run_result = dataset.get("_run_result")
        # The per-plate force/COP curves windowed to the analysed range (raw +
        # filtered twins resolve through the signal registry, same as review).
        self._render_force_curves(dataset, analysis["range_start"], analysis["range_end"])
        self._render_trajectory(dataset)
        self._draw_events(dataset)
        self._refresh_event_list(dataset)
        self._refresh_results_panels(dataset)
        # (Metrics formerly mirrored into a top card strip; they now live only in
        # RESULTS▸Metrics, refreshed by _refresh_results_panels above.)

    def _refresh_event_controls(self, dataset=None):
        enabled = dataset is not None
        for widget in [
            getattr(self, "add_event_btn", None),
            getattr(self, "delete_event_btn", None),
        ]:
            if widget is not None:
                widget.setEnabled(enabled)
        self._refresh_event_list(dataset)

    def _event_channel_options(self, dataset):
        # Every plottable signal (COP/force/markers/joint angles) can drive an
        # event — sourced from the shared signal registry (core/signals).
        from core import signals
        markers = dataset.get("markers")
        disp = self._marker_display_data(markers) if markers else None
        res = self._angle_result_for(dataset)
        # Pass the pipeline so processed "(filtered)" signals it produces also
        # become selectable event channels (right after their raw twins). Plate
        # signals are shown as explicit FP1/FP2 (see _plate_label_opts).
        opts = self._plate_label_opts(
            list(signals.signal_catalog(dataset, disp, res, pipeline=self.pipeline)))
        return [(label, key) for key, label in opts]

    def _edit_event(self, item):
        """Double-click an Events row to edit it.

        New events are pipeline :class:`DetectEventStep`s, so editing one opens the
        unified dialog (via :meth:`_edit_detect_event_step`). Legacy manual events
        from old projects (``dataset["events"]``) are read-only here — they still
        display and can be deleted, but the old rule editor is retired."""
        tag = item.data(Qt.ItemDataRole.UserRole)
        if not (isinstance(tag, (list, tuple)) and len(tag) == 2):
            return
        kind, index = tag[0], int(tag[1])
        from core.pipeline import DetectEventStep
        if kind == "step":
            steps = self.pipeline.detect_event_steps()
            if 0 <= index < len(steps):
                self._edit_detect_event_step(steps[index])
            return
        # Legacy manual event: read-only (the old rule editor is gone).
        QMessageBox.information(
            self, "Legacy event",
            "This event was made in an older version. It still shows and can be "
            "deleted, but to change it please delete it and add a new event.")

    def _clear_event_lines(self):
        for line in self.event_lines:
            try:
                line.getViewBox().removeItem(line)
            except Exception:
                pass
        self.event_lines = []

    #: Colours cycled across auto-detect event steps (drawn dashed to set them
    #: apart from the solid manual-event lines).
    _AUTO_EVENT_COLORS = ["#F59E0B", "#22C55E", "#06B6D4", "#A855F7",
                          "#EC4899", "#EAB308"]

    def _draw_events(self, dataset):
        self._clear_event_lines()
        if dataset is None:
            return
        # --- manual events (solid lines, from dataset["events"]) ---
        for event in dataset.get("events", []):
            if not event.get("enabled", True):
                continue
            if event.get("name") in self._hidden_event_labels:
                continue   # view-level Delete from RESULTS·Events
            for plot in self._time_plots:
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
        # --- auto-detected events (solid lines, all instances per step) ---
        self._draw_auto_events(dataset)

    def _draw_auto_events(self, dataset):
        """Draw every instance of each DetectEventStep as a solid vertical line.

        Pure display: the frames come from ``core.events_compute`` (which caches
        per file and resolves "(filtered)" inputs through the Workspace); the UI
        only turns them into lines. A standing trial (signal never crosses the
        threshold) yields no frames, so no lines — by design."""
        try:
            detected = events_compute.compute_detected_events(dataset, self.pipeline)
        except Exception:
            return
        steps = self.pipeline.detect_event_steps()
        for step_id, entry in enumerate(detected):
            # Prefer the user-chosen colour stored on the step; fall back to the
            # cycling palette for steps made before colours existed.
            color = None
            if 0 <= step_id < len(steps):
                color = steps[step_id].color
            if not color:
                color = self._AUTO_EVENT_COLORS[step_id % len(self._AUTO_EVENT_COLORS)]
            label = entry.get("label", "")
            if label in self._hidden_event_labels:
                continue   # view-level Delete from RESULTS·Events
            for frame, t in zip(entry.get("frames", []), entry.get("times", [])):
                for plot in self._time_plots:
                    line = pg.InfiniteLine(
                        pos=float(t),
                        angle=90,
                        movable=False,
                        pen=pg.mkPen(color, width=2),
                    )
                    line.setZValue(18)
                    try:
                        line.setToolTip(f"{label} (auto)\nFrame {int(frame) + 1}\n{t:.3f}s")
                    except Exception:
                        pass
                    plot.addItem(line)
                    self.event_lines.append(line)

    #: Method label shown in the Events list (one row per event).
    _EVENT_METHOD_LABEL = {"frame": "fixed frame", "threshold": "crossing",
                           "peak": "peak", "zero": "zero-cross"}

    def _color_swatch(self, color, size=10):
        """Return a small filled-square QIcon of ``color`` for list rows.

        Used as the leading icon of Events/Pipeline rows so each event's graph
        colour is visible at a glance. Purely decorative — the colour is a real
        field, so showing it never triggers re-detection."""
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(QColor(color)))
        painter.setPen(QPen(QColor(BORDER)))
        painter.drawRoundedRect(0, 0, size - 1, size - 1, 2, 2)
        painter.end()
        return QIcon(pm)

    def _refresh_event_list(self, dataset=None):
        """Redraw the Events list = pipeline DetectEventSteps + legacy manual events.

        Each row's checkbox means "selected for delete". Pipeline steps (the new,
        editable events) are tagged ``("step", i)``; legacy ``dataset["events"]``
        entries are tagged ``("manual", i)`` and are read-only (display + delete)."""
        if not hasattr(self, "event_list"):
            return
        self.event_list.blockSignals(True)
        self.event_list.clear()
        # --- pipeline detect-event steps (new events) ---
        for i, step in enumerate(self.pipeline.detect_event_steps()):
            method = self._EVENT_METHOD_LABEL.get(step.method, step.method)
            if step.method == "frame":
                frame = int(step.params.get("frame", 0)) + 1
                text = f"{step.label or '(unnamed)'}  ·  fixed frame F{frame}"
            else:
                # Human signal name ("COP AP"), not the raw key ("cop_ap").
                text = f"{step.label or '(unnamed)'}  ·  {label_for(step.input)} {method}"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, ("step", i))
            # A small colour swatch in front of the row (the step's line colour).
            if step.color:
                item.setIcon(self._color_swatch(step.color))
            item.setToolTip("Double-click to edit. Check + ✕ to delete.")
            self.event_list.addItem(item)
        # --- legacy manual events (read-only, kept for backward-compat) ---
        if dataset is not None:
            for index, event in enumerate(dataset.get("events", [])):
                item = QListWidgetItem(
                    f"{event['name']}  F{event['frame']}  {event['time']:.2f}s  (old)"
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, ("manual", index))
                item.setIcon(self._color_swatch(event.get("color", TEXT_PRIMARY)))
                item.setToolTip(event.get("rule", ""))
                self.event_list.addItem(item)
        self.event_list.blockSignals(False)

    def _on_event_item_changed(self, item):
        # The checkbox is only a delete-selection now (no per-event enable flag);
        # nothing to do on toggle. Kept connected so the signal has a slot.
        return

    def _delete_checked_events(self):
        """Delete every checked Events row (pipeline steps and/or legacy events)."""
        dataset = self._current_dataset()
        step_rows = []
        manual_rows = []
        for row in range(self.event_list.count()):
            item = self.event_list.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            tag = item.data(Qt.ItemDataRole.UserRole)
            if not (isinstance(tag, (list, tuple)) and len(tag) == 2):
                continue
            if tag[0] == "step":
                step_rows.append(int(tag[1]))
            elif tag[0] == "manual":
                manual_rows.append(int(tag[1]))
        if not step_rows and not manual_rows:
            QMessageBox.information(self, "No events selected", "Check events before deleting.")
            return

        # Remove the chosen pipeline detect-event steps (highest index first so the
        # earlier indices stay valid). Map detect-step index -> pipeline index.
        if step_rows:
            detect_steps = self.pipeline.detect_event_steps()
            to_remove = []
            for di in step_rows:
                if 0 <= di < len(detect_steps):
                    step = detect_steps[di]
                    if step in self.pipeline.steps:
                        to_remove.append(self.pipeline.steps.index(step))
            for pi in sorted(set(to_remove), reverse=True):
                self.pipeline.remove(pi)
            self._invalidate_event_caches()
            self._refresh_pipeline_list()

        # Remove the chosen legacy manual events by name across active files.
        if manual_rows and dataset is not None:
            events = dataset.get("events", [])
            names = {events[i].get("name") for i in manual_rows
                     if 0 <= i < len(events)}
            names.discard(None)
            for target_index in self._active_dataset_indexes():
                target = self.datasets[target_index]
                target["events"] = [
                    e for e in target.get("events", [])
                    if e.get("name") not in names
                ]
                target["analysis"] = None

        self._on_filter_changed()
        self._draw_events(dataset)
        self._refresh_event_list(dataset)

    def _range_label(self, config):
        return f"{config['name']}  {self._endpoint_label(config['start'], config['start_frame'])}-{self._endpoint_label(config['end'], config['end_frame'])}"

    def _endpoint_label(self, endpoint, frame):
        if endpoint.get("type") == "event":
            return endpoint.get("name", "Event")
        if endpoint.get("type") == "end":
            return "End"
        return f"F{int(frame)}"

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

    # Triggered by File > Export. Uses the ranges configured in the sidebar
    # ----- shared results store (Analyze -> Statistics hand-off) -----
    def set_results_store(self, store):
        self.results_store = store

    def _run_export_results(self, checked_indexes):
        """Analyze every checked dataset over the whole trial (one result per
        file). Each metric defines its own segment via pipeline Metric steps.
        Returns (results, errors). Shared by Excel export and the Statistics
        hand-off."""
        results, errors = [], []
        for index in checked_indexes:
            target = self.datasets[index]
            try:
                results.append(self._analyze_dataset(target, [], []))
            except Exception as exc:
                errors.append(f"{target['name']}: {exc}")
        return results, errors

    def _result_to_row(self, result, selected_metrics=None):
        """Flatten an analysis result into a ResultsStore row (matches the Excel
        'Results' sheet columns).

        ``selected_metrics`` (set of metric names) limits which metrics are
        flattened — used by the EXPORT popup and the Statistics hand-off so only
        the user-selected variables are written. ``None`` (default) keeps all
        metrics (back-compat)."""
        row = {"Folder": result.get("folder", ""),
               "Condition": result.get("condition", ""),
               "File": result["file"], "Range": result.get("range", "")}
        for metric, (value, unit) in result["metrics"].items():
            if selected_metrics is not None and metric not in selected_metrics:
                continue
            label = f"{metric} ({unit})" if unit else metric
            try:
                row[label] = float(value)
            except (TypeError, ValueError):
                row[label] = value
        return row

    def _metric_specs_for_results(self, results):
        """Union of metric ``(name, unit)`` across results, first-seen order —
        feeds the EXPORT popup's data-selection checklist."""
        specs, seen = [], set()
        for result in results:
            for metric, (_value, unit) in result["metrics"].items():
                if metric not in seen:
                    seen.add(metric)
                    specs.append((metric, unit))
        return specs

    def _filter_result_metrics(self, result, selected_metrics):
        """Return a shallow copy of ``result`` whose ``metrics`` keep only the
        selected names (``None`` = keep all)."""
        if selected_metrics is None:
            return result
        filtered = dict(result)
        filtered["metrics"] = {
            name: pair for name, pair in result["metrics"].items()
            if name in selected_metrics
        }
        return filtered

    def send_results_to_store(self):
        """Push the current analysis (checked files) into the shared Statistics
        store — but only the metrics the user selects in the EXPORT popup, so
        "통계도 선택한 것만". Returns the number of rows added (0 if cancelled
        or nothing to send)."""
        if self.results_store is None:
            return 0
        if not self.datasets:
            QMessageBox.information(self, "No files", "Load and analyze files first.")
            return 0
        checked_indexes = self._checked_dataset_indexes()
        if not checked_indexes:
            QMessageBox.information(self, "No files selected", "Check analyzed files first.")
            return 0
        results, errors = self._run_export_results(checked_indexes)
        if not results:
            QMessageBox.warning(self, "No results", "\n".join(errors[:8]))
            return 0

        selection = self._ask_metric_selection(results, "Send to Statistics")
        if selection is None:
            return 0
        selected_metrics, selected_paths = selection
        rows = [
            self._result_to_row(r, selected_metrics)
            for r in results
            if selected_paths is None or r["path"] in selected_paths
        ]
        self.results_store.add_rows(rows, source="Analyze")
        if errors:
            QMessageBox.warning(self, "Some files skipped", "\n".join(errors[:8]))
        return len(rows)

    def _ask_metric_selection(self, results, ok_title="Export"):
        """Open the EXPORT popup for a *selection only* (Statistics hand-off
        reuses the same data/file checklist, ignoring its destination fields).
        Returns ``(selected_metrics:set|None, selected_paths:set|None)`` or
        ``None`` if cancelled."""
        from ui.analyze_dialogs import ExportDialog
        specs = self._metric_specs_for_results(results)
        file_specs = [
            (i, self.datasets[i]["name"]) for i in self._checked_dataset_indexes()
        ]
        dialog = ExportDialog(self, specs, files=file_specs)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        vals = dialog.values()
        selected_metrics = vals["selected_metrics"] if specs else None
        selected_files = vals["selected_files"]
        selected_paths = None
        if selected_files is not None:
            selected_paths = {self.datasets[i]["path"] for i in selected_files}
        return selected_metrics, selected_paths

    # Dedicated EXPORT popup (File ▸ Export): the user chooses which metrics,
    # which files, the filename, the location and the format — all in one dialog.
    def export_data(self):
        if not self.datasets:
            QMessageBox.information(self, "No files", "Load files before export.")
            return
        checked_indexes = self._checked_dataset_indexes()
        if not checked_indexes:
            QMessageBox.information(self, "No files selected", "Check analyzed files to export.")
            return

        export_results, errors = self._run_export_results(checked_indexes)
        if not export_results:
            QMessageBox.warning(self, "Export failed", "\n".join(errors[:8]))
            return

        from ui.analyze_dialogs import ExportDialog
        specs = self._metric_specs_for_results(export_results)
        file_specs = [(i, self.datasets[i]["name"]) for i in checked_indexes]
        dialog = ExportDialog(self, specs, files=file_specs)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dialog.values()
        selected_metrics = vals["selected_metrics"] if specs else None
        path = vals["path"]
        fmt = vals["format"]

        # Narrow to the selected files, then filter each result's metrics.
        if vals["selected_files"] is not None:
            keep_paths = {self.datasets[i]["path"] for i in vals["selected_files"]}
            chosen = [r for r in export_results if r["path"] in keep_paths]
        else:
            chosen = list(export_results)
        chosen = [self._filter_result_metrics(r, selected_metrics) for r in chosen]
        if not chosen:
            QMessageBox.warning(self, "Export failed", "No files selected to export.")
            return

        summary_rows = self._compute_summary_rows(chosen)
        try:
            if fmt == "csv":
                self._write_results_csv(path, chosen)
            else:
                self._write_results_workbook(path, chosen, summary_rows)
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
            QMessageBox.warning(self, "Some files skipped", "\n".join(errors[:8]))

    def _write_results_csv(self, path, results):
        """Write the wide 'Results' table (one row per file) as CSV — the same
        columns the Excel 'Results' sheet uses, limited to the metrics already
        filtered into each result. Mirrors ``_write_results_workbook``'s metric
        ordering."""
        metric_order, units = [], {}
        for result in results:
            for metric, (_value, unit) in result["metrics"].items():
                if metric not in units:
                    metric_order.append(metric)
                units[metric] = unit

        header = ["Folder", "Condition", "File", "Range"] + [
            f"{m} ({units[m]})" if units[m] else m for m in metric_order
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for result in results:
                row = [result.get("folder", ""), result.get("condition", ""),
                       result["file"], result.get("range", "")]
                for metric in metric_order:
                    pair = result["metrics"].get(metric)
                    row.append(float(pair[0]) if pair is not None else "")
                writer.writerow(row)

    def _checked_analysis_results(self):
        checked_paths = {self.datasets[i]["path"] for i in self._checked_dataset_indexes()}
        return [
            result for result in self.analysis_results
            if result["path"] in checked_paths
        ]

    def _write_results_workbook(self, path, results, summary_rows):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment

        # Stable, de-duplicated metric order + unit lookup across all results.
        metric_order = []
        units = {}
        for result in results:
            for metric, (value, unit) in result["metrics"].items():
                if metric not in units:
                    metric_order.append(metric)
                units[metric] = unit

        wb = Workbook()

        # --- Results (wide: one row per file x range, metrics as columns) ---
        ws_results = wb.active
        ws_results.title = "Results"
        header = ["Folder", "Condition", "File", "Range"] + [
            f"{m} ({units[m]})" if units[m] else m for m in metric_order
        ]
        ws_results.append(header)
        for result in results:
            row = [result.get("folder", ""), result.get("condition", ""),
                   result["file"], result.get("range", "")]
            for metric in metric_order:
                pair = result["metrics"].get(metric)
                row.append(float(pair[0]) if pair is not None else None)
            ws_results.append(row)
        for r in range(2, ws_results.max_row + 1):
            for c in range(6, len(header) + 1):
                ws_results.cell(row=r, column=c).number_format = "0.000"

        # --- Summary (per range x metric statistics) ---
        ws_stats = wb.create_sheet("Summary")
        ws_stats.append(["Range", "Metric", "Unit", "N", "Mean", "SD", "SE"])
        for row in summary_rows:
            ws_stats.append([
                row["range"], row["variable"], row["unit"],
                row["n"], row["mean"], row["sd"], row["se"],
            ])
        for r in range(2, ws_stats.max_row + 1):
            for c in (5, 6, 7):
                ws_stats.cell(row=r, column=c).number_format = "0.000"

        # --- Files ---
        ws_files = wb.create_sheet("Files")
        ws_files.append(["File", "Total frames", "Analyzed range"])
        for result in results:
            ws_files.append([
                result["file"], result["total_frame"], result["analyzed_frame_range"],
            ])

        # --- Events ---
        ws_events = wb.create_sheet("Events")
        ws_events.append(["File", "Event", "Frame", "Time (s)"])
        written_events = set()
        for result in results:
            for event in result.get("events", []):
                key = (result["file"], event["name"], event["frame"])
                if key in written_events:
                    continue
                written_events.add(key)
                ws_events.append([
                    result["file"], event["name"], event["frame"],
                    round(float(event.get("time", 0.0)), 3),
                ])

        header_fill = PatternFill("solid", fgColor="D9EAF7")
        for ws in (ws_results, ws_stats, ws_files, ws_events):
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
            ws.freeze_panes = "E2" if ws is ws_results else "A2"
            for column in ws.columns:
                max_len = max(len(str(cell.value if cell.value is not None else "")) for cell in column)
                ws.column_dimensions[column[0].column_letter].width = min(max(max_len + 2, 12), 40)

        wb.save(path)

    def _set_placeholder(self, text):
        # The metric-card strip was removed; metrics now live in RESULTS▸Metrics.
        # Nothing to show here, kept as a no-op so call sites stay valid.
        pass

    def _recolor_tree_items(self):
        """Checked file rows get green text; unchecked stay the normal colour
        (folder nodes aren't checkable, so they're skipped)."""
        for item in self._iter_file_items():
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                continue
            checked = item.checkState(0) in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked)
            item.setForeground(0, QBrush(QColor(SEL_GREEN if checked else TEXT_PRIMARY)))

    def _highlight_current_file(self):
        self._recolor_tree_items()
        for item in self._iter_file_items():
            if self._item_index(item) == self.current_index and self.current_index is not None:
                self.file_tree.setCurrentItem(item)

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
        sep.setStyleSheet(S.separator_style())
        return sep
