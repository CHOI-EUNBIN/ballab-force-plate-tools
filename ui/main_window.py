import os
import sys

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QFileDialog, QMessageBox, QDockWidget
from core.axis_settings import AxisSettings
from core.project import save_project, load_project, PROJECT_FILTER, PROJECT_EXT
from ui.collect_tab import CollectTab
from ui.analyze_tab import AnalyzeTab
from ui.statistics_tab import StatisticsTab
from core.results_store import ResultsStore
from ui.settings_dialogs import NormalizeDialog, RecordingAxisDialog
from ui.style import LIGHT_PALETTE, DARK_PALETTE, use_theme


class MainWindow(QMainWindow):

    def __init__(self, qtm_ip: str = "127.0.0.1"):
        super().__init__()
        self.setWindowTitle("Balancelab")
        self.setWindowIcon(QIcon(resource_path("assets/ballab_icon_master_1024_transparent.png")))
        self.resize(1340, 820)
        self.setMinimumSize(960, 620)

        self.axis_settings = AxisSettings()
        from core.appearance import Appearance
        self.appearance = Appearance()

        # Resolve the theme before building tabs so plots/labels build with the
        # right colours from the start.
        self._qsettings = QSettings("Balancelab", "Balancelab")
        self._theme = self._qsettings.value("theme", "light") or "light"
        self._palette = use_theme(self._theme)

        # Shared metrics interchange between Analyze and Statistics.
        self.results_store  = ResultsStore()

        self.stack          = QStackedWidget()
        self.collect_tab    = CollectTab(qtm_ip=qtm_ip, axis_settings=self.axis_settings)
        self.analyze_tab    = AnalyzeTab(axis_settings=self.axis_settings, appearance=self.appearance)
        self.statistics_tab = StatisticsTab()
        self.analyze_tab.set_results_store(self.results_store)
        self.statistics_tab.set_results_store(self.results_store)

        self.stack.addWidget(self.collect_tab)
        self.stack.addWidget(self.analyze_tab)
        self.stack.addWidget(self.statistics_tab)

        self.setCentralWidget(self.stack)
        self.current_project_path = None

        self._build_menubar()
        self._build_ai_dock()
        self.setStyleSheet(self._style())
        # The app starts from loading a C3D, so open on Analyze (Record stays
        # available in the nav).
        self._switch_view(self.analyze_tab)

    def _build_menubar(self):
        menubar = self.menuBar()
        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)

        def show_action(menu, text, widget):
            action = QAction(text, self)
            action.setCheckable(True)
            action._widget = widget
            action.triggered.connect(lambda _=False, w=widget: self._switch_view(w))
            self._view_group.addAction(action)
            menu.addAction(action)
            return action

        def act(menu, text, slot, shortcut=None):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            menu.addAction(action)
            return action

        # --- Analyze (primary): per-trial C3D analysis + its file ops ---
        analyze_menu = menubar.addMenu("Analyze")
        show_action(analyze_menu, "Show Analyze", self.analyze_tab)
        analyze_menu.addSeparator()
        act(analyze_menu, "New Project", self._new_project, "Ctrl+N")
        act(analyze_menu, "Open Project...", self._open_project, "Ctrl+O")
        act(analyze_menu, "Save Project", self._save_project, "Ctrl+S")
        act(analyze_menu, "Save Project As...", self._save_project_as, "Ctrl+Shift+S")
        analyze_menu.addSeparator()
        act(analyze_menu, "Save Pipeline...", self._save_pipeline)
        act(analyze_menu, "Load Pipeline...", self._load_pipeline)
        analyze_menu.addSeparator()
        self._load_file_action = act(analyze_menu, "Load C3D...", self._load_file, "Ctrl+L")
        self._load_folder_action = act(analyze_menu, "Load folder...", self._load_folder)
        self._export_action = act(analyze_menu, "Export results (Excel)...", self._export, "Ctrl+E")
        act(analyze_menu, "Send results → Statistics", self._send_results_to_statistics)

        # --- Statistics: aggregate results across trials ---
        stats_menu = menubar.addMenu("Statistics")
        show_action(stats_menu, "Show Statistics", self.statistics_tab)
        stats_menu.addSeparator()
        act(stats_menu, "Import results (Excel)...", self._import_results_excel)
        act(stats_menu, "Clear results", self._clear_results)

        # --- Record: live mocap capture + its file ops ---
        record_menu = menubar.addMenu("Record")
        show_action(record_menu, "Show Record", self.collect_tab)
        record_menu.addSeparator()
        act(record_menu, "New Project", lambda: self._mode_action(self.collect_tab, self._new_project))
        act(record_menu, "Save Project", lambda: self._mode_action(self.collect_tab, self._save_project))
        act(record_menu, "Export CSV...", lambda: self._mode_action(self.collect_tab, self._export))
        record_menu.addSeparator()
        act(record_menu, "Recording axis...", self._open_recording_axis_settings)

        settings_menu = menubar.addMenu("Settings")
        normalize_action = QAction("Normalize...", self)
        normalize_action.triggered.connect(self._open_normalize_settings)
        settings_menu.addAction(normalize_action)
        appearance_action = QAction("Appearance...", self)
        appearance_action.triggered.connect(self._open_appearance_settings)
        settings_menu.addAction(appearance_action)
        view_action = QAction("View...", self)
        view_action.triggered.connect(self._open_view_settings)
        settings_menu.addAction(view_action)
        rag_action = QAction("AI 도우미 (RAG)...", self)
        rag_action.triggered.connect(self._open_rag_settings)
        settings_menu.addAction(rag_action)
        settings_menu.addSeparator()

        theme_menu = settings_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for label, name in [("Light", "light"), ("Dark", "dark")]:
            theme_act = QAction(label, self)
            theme_act.setCheckable(True)
            theme_act.setChecked(self._theme == name)
            theme_act.triggered.connect(lambda _=False, n=name: self.apply_theme(n))
            self._theme_group.addAction(theme_act)
            theme_menu.addAction(theme_act)

        settings_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        settings_menu.addAction(exit_action)

        self._help_menu = help_menu = menubar.addMenu("Help")
        metrics_help = QAction("Metrics Reference", self)
        metrics_help.triggered.connect(self._open_metrics_help)
        help_menu.addAction(metrics_help)
        markers_help = QAction("Markers & 3D", self)
        markers_help.triggered.connect(self._open_markers_help)
        help_menu.addAction(markers_help)
        marker_manual = QAction("Marker Set Manual", self)
        marker_manual.triggered.connect(self._open_marker_manual)
        help_menu.addAction(marker_manual)
        timenorm_help = QAction("Time-normalization & Ensemble", self)
        timenorm_help.triggered.connect(self._open_timenorm_help)
        help_menu.addAction(timenorm_help)

        self._update_menu_state()

    def _build_ai_dock(self):
        """RAG AI 도우미 패널을 우측 QDockWidget으로 붙인다. 시작 시 숨김,
        Help 메뉴 토글로 표시/숨김. URL은 설정(QSettings)에서 읽는다."""
        from ui.ai_assistant_panel import AiAssistantPanel
        url = self._qsettings.value("rag/service_url", "http://localhost:8000", type=str)
        self.ai_panel = AiAssistantPanel(self, base_url=url)
        self.ai_dock = QDockWidget("AI 도우미", self)
        self.ai_dock.setObjectName("aiDock")
        self.ai_dock.setWidget(self.ai_panel)
        # 드래그로 떼어내거나(floating) 다른 영역에 끼우다(split) 사라지는 혼란을 막기 위해
        # 이동/플로팅을 끄고 닫기만 허용 — 우측 고정. 여닫기는 Help 토글 또는 X로만.
        self.ai_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.ai_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_dock)
        self.resizeDocks([self.ai_dock], [360], Qt.Orientation.Horizontal)
        self.ai_dock.hide()  # 시작 시 숨김 — 토글로 표시
        toggle = self.ai_dock.toggleViewAction()
        toggle.setText("AI 도우미 (문헌·사용법 질문)")
        self._help_menu.addAction(toggle)

    def _open_metrics_help(self):
        from ui.help_dialog import MetricsHelpDialog
        old = getattr(self, "_metrics_help", None)
        if old is not None:
            old.close()
        # Recreate so the dialog picks up the current theme colours.
        self._metrics_help = MetricsHelpDialog(self)
        self._metrics_help.show()
        self._metrics_help.raise_()
        self._metrics_help.activateWindow()

    def _open_markers_help(self):
        from ui.help_dialog import MarkersHelpDialog
        old = getattr(self, "_markers_help", None)
        if old is not None:
            old.close()
        self._markers_help = MarkersHelpDialog(self)
        self._markers_help.show()
        self._markers_help.raise_()
        self._markers_help.activateWindow()

    def _open_marker_manual(self):
        from ui.help_dialog import MarkerSetManualDialog
        old = getattr(self, "_marker_manual", None)
        if old is not None:
            old.close()
        # Recreate so the dialog picks up the current theme colours.
        self._marker_manual = MarkerSetManualDialog(self)
        self._marker_manual.show()
        self._marker_manual.raise_()
        self._marker_manual.activateWindow()

    def _open_timenorm_help(self):
        from ui.help_dialog import TimeNormHelpDialog
        old = getattr(self, "_timenorm_help", None)
        if old is not None:
            old.close()
        # Recreate so the dialog picks up the current theme colours.
        self._timenorm_help = TimeNormHelpDialog(self)
        self._timenorm_help.show()
        self._timenorm_help.raise_()
        self._timenorm_help.activateWindow()

    def _open_recording_axis_settings(self):
        RecordingAxisDialog(self, self.axis_settings).exec()

    def _open_normalize_settings(self):
        NormalizeDialog(self, self.axis_settings).exec()

    def _open_rag_settings(self):
        from ui.settings_dialogs import RagServiceDialog
        RagServiceDialog(self).exec()

    def _open_appearance_settings(self):
        from ui.settings_dialogs import AppearanceDialog
        AppearanceDialog(self, self.appearance).exec()

    def _open_view_settings(self):
        from ui.settings_dialogs import ViewDialog
        ViewDialog(self, self.analyze_tab).exec()

    def apply_theme(self, name):
        self._theme = "dark" if name == "dark" else "light"
        self._palette = use_theme(self._theme)
        self._qsettings.setValue("theme", self._theme)
        self.setStyleSheet(self._style())
        for tab in (self.collect_tab, self.analyze_tab, self.statistics_tab):
            if hasattr(tab, "apply_theme"):
                tab.apply_theme()

    def _switch_view(self, widget):
        self.stack.setCurrentWidget(widget)
        for action in self._view_group.actions():
            if getattr(action, "_widget", None) is widget:
                action.setChecked(True)
        self._update_menu_state()

    def _update_menu_state(self, *_):
        tab = self.stack.currentWidget()
        self._load_file_action.setEnabled(bool(getattr(tab, "supports_load_file", False)))
        self._export_action.setEnabled(hasattr(tab, "export_data"))

    def _new_project(self):
        tab = self.stack.currentWidget()
        if not hasattr(tab, "new_project"):
            return
        has_content = getattr(tab, "has_content", lambda: False)()
        if has_content:
            resp = QMessageBox.question(
                self, "New Project",
                "Save the current project before starting a new one?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if resp == QMessageBox.StandardButton.Cancel:
                return
            if resp == QMessageBox.StandardButton.Save:
                self._save_project()
        tab.new_project()
        self.current_project_path = None
        self.setWindowTitle("Balancelab")

    def _load_file(self):
        tab = self.stack.currentWidget()
        if hasattr(tab, "load_file"):
            tab.load_file()

    def _load_folder(self):
        self._switch_view(self.analyze_tab)
        self.analyze_tab.load_folder()

    def _export(self):
        tab = self.stack.currentWidget()
        if hasattr(tab, "export_data"):
            tab.export_data()

    def _mode_action(self, widget, slot):
        """Switch to a mode, then run a file action against it (used by the
        Record menu so its items target Record regardless of the current view)."""
        self._switch_view(widget)
        slot()

    def _send_results_to_statistics(self):
        n = self.analyze_tab.send_results_to_store()
        if n:
            self._switch_view(self.statistics_tab)

    def _import_results_excel(self):
        self.statistics_tab.import_results_excel()
        self._switch_view(self.statistics_tab)

    def _clear_results(self):
        self.statistics_tab.clear_results()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", PROJECT_FILTER)
        if not path:
            return
        self.open_project_path(path)

    def open_project_path(self, path):
        try:
            manifest, datadir = load_project(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", f"Could not read project:\n{exc}")
            return
        kind = manifest.get("tab")
        target = {"analyze": self.analyze_tab, "record": self.collect_tab}.get(kind)
        if target is None or not hasattr(target, "load_project_state"):
            QMessageBox.warning(self, "Open failed", "Unrecognized project type.")
            return
        self._switch_view(target)
        try:
            target.load_project_state(manifest, datadir)
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", f"Could not restore project:\n{exc}")
            return
        self.current_project_path = path
        self.setWindowTitle(f"Balancelab — {os.path.basename(path)}")

    def _save_pipeline(self):
        tab = self.stack.currentWidget()
        if not hasattr(tab, "export_pipeline"):
            QMessageBox.information(self, "Save Pipeline", "This tab has no pipeline.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Pipeline", "pipeline.json", "Balancelab pipeline (*.json)")
        if not path:
            return
        try:
            tab.export_pipeline(path)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save pipeline:\n{exc}")
            return
        QMessageBox.information(self, "Saved", f"Pipeline saved:\n{path}")

    def _load_pipeline(self):
        tab = self.stack.currentWidget()
        if not hasattr(tab, "import_pipeline"):
            QMessageBox.information(self, "Load Pipeline", "This tab has no pipeline.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Pipeline", "",
            "Balancelab pipeline (*.json);;All files (*)")
        if not path:
            return
        try:
            tab.import_pipeline(path)
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", f"Could not load pipeline:\n{exc}")

    def _save_project(self):
        if self.current_project_path:
            self._write_project(self.current_project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        tab = self.stack.currentWidget()
        if not hasattr(tab, "save_project_state"):
            QMessageBox.information(self, "Save Project", "This tab has nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "project" + PROJECT_EXT, PROJECT_FILTER
        )
        if not path:
            return
        self._write_project(path)

    def _write_project(self, path):
        tab = self.stack.currentWidget()
        if not hasattr(tab, "save_project_state"):
            QMessageBox.information(self, "Save Project", "This tab has nothing to save.")
            return
        try:
            manifest, files = tab.save_project_state()
            saved = save_project(path, manifest, files)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save project:\n{exc}")
            return
        self.current_project_path = saved
        self.setWindowTitle(f"Balancelab — {os.path.basename(saved)}")
        QMessageBox.information(self, "Saved", f"Project saved:\n{saved}")

    def closeEvent(self, event):
        """Guard against losing unsaved work: if the current tab has content,
        ask Save / Don't Save / Cancel before the window closes (mirrors the
        New Project prompt). Cancel — or cancelling the Save-As dialog on a
        never-saved project — aborts the close."""
        tab = self.stack.currentWidget()
        has_content = getattr(tab, "has_content", lambda: False)()
        if has_content:
            resp = QMessageBox.question(
                self, "Quit Balancelab",
                "Save the current project before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if resp == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if resp == QMessageBox.StandardButton.Save:
                self._save_project()
                # Save-As cancelled on a never-saved project -> don't lose the work.
                if self.current_project_path is None:
                    event.ignore()
                    return
        # 닫기가 확정된 시점에 RAG 패널 워커를 정리(떠도는 스레드 크래시 방지).
        panel = getattr(self, "ai_panel", None)
        if panel is not None:
            panel.shutdown()
        event.accept()

    def _style(self):
        p = self._palette
        BG_DARK = p["BG_DARK"]
        BG_MID = p["BG_MID"]
        BG_PANEL = p["BG_PANEL"]
        BG_INPUT = p["BG_INPUT"]
        BG_HOVER = p["BG_HOVER"]
        BG_DISABLED = p["BG_DISABLED"]
        ACCENT_TEAL = p["ACCENT_TEAL"]
        ACCENT_PURPLE = p["ACCENT_PURPLE"]
        ACCENT_RED = p["ACCENT_RED"]
        TEXT_PRIMARY = p["TEXT_PRIMARY"]
        TEXT_SECONDARY = p["TEXT_SECONDARY"]
        TEXT_MUTED = p["TEXT_MUTED"]
        BORDER = p["BORDER"]
        BORDER_LIGHT = p.get("BORDER_LIGHT", p["BORDER"])
        # Selection / checkbox indicator tokens (theme-aware, centralised in
        # ui.style). One green-dot language for every checkbox & list indicator:
        # a faint ring when idle, a filled green dot when checked.
        SEL_GREEN = p.get("SEL_GREEN", "#3FC08D")      # checked = green text
        CHECK_DOT = p.get("CHECK_DOT", "rgba(63, 192, 141, 0.90)")
        CHECK_DOT_PARTLY = p.get("CHECK_DOT_PARTLY", "rgba(63, 192, 141, 0.35)")
        CHECK_RING = p.get("CHECK_RING", "#C4D0DD")
        CHECK_RING_HOVER = p.get("CHECK_RING_HOVER", "#94A7BF")
        RING = CHECK_DOT   # back-compat alias used by file-tree indicator rules
        return f"""
        QMainWindow, QWidget {{
            background-color: {BG_MID};
            color: {TEXT_PRIMARY};
            font-size: 12px;
        }}
        QTabWidget::pane {{
            border: none;
            background: transparent;
        }}
        QTabBar::tab {{
            background: {BG_PANEL};
            color: {TEXT_SECONDARY};
            padding: 10px 22px;
            border: 1px solid {BORDER};
            border-bottom: none;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            margin-right: 4px;
            font-size: 13px;
        }}
        QTabBar::tab:selected {{
            background: {BG_MID};
            color: {TEXT_PRIMARY};
            border-color: {BORDER};
            border-bottom-color: {BG_MID};
        }}
        QTabBar::tab:hover:!selected {{
            color: {TEXT_PRIMARY};
            background: {BG_INPUT};
        }}

        QMenuBar {{
            background-color: {BG_PANEL};
            color: {TEXT_SECONDARY};
            border-bottom: 1px solid {BORDER};
            padding: 2px 6px;
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 6px 12px;
            border-radius: 6px;
        }}
        QMenuBar::item:selected {{ background: {BG_INPUT}; color: {TEXT_PRIMARY}; }}
        QMenuBar::item:checked {{ color: {ACCENT_TEAL}; font-weight: 700; }}
        QMenu {{
            background-color: {BG_PANEL};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{ padding: 7px 24px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {ACCENT_TEAL}; color: #fff; }}
        QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

        QToolTip {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 3px 6px;
            font-size: 11px;
        }}

        QFrame#accordion-sep {{
            background-color: {BORDER};
            border: none;
            max-height: 1px;
            min-height: 1px;
        }}

        QFrame#sidebar {{
            background-color: {BG_PANEL};
            border: none;
            border-right: 1px solid {BORDER};
        }}
        QFrame#statusbar {{
            background-color: transparent;
            border: none;
        }}

        QPushButton#section-toggle {{
            background: transparent;
            border: none;
            color: {TEXT_PRIMARY};
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.3px;
            text-align: left;
            padding: 6px 0;
        }}
        QPushButton#section-toggle:hover {{ color: {ACCENT_TEAL}; }}

        QPushButton#subsection-toggle {{
            background: transparent;
            border: none;
            color: {TEXT_SECONDARY};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.2px;
            text-align: left;
            padding: 3px 0;
        }}
        QPushButton#subsection-toggle:hover {{ color: {ACCENT_TEAL}; }}

        QListWidget#marker-list {{
            background: transparent;
            border: none;
            outline: none;
            font-size: 11px;
        }}
        QListWidget#marker-list::item {{ padding: 1px 2px 1px 4px; min-height: 22px; color: {TEXT_PRIMARY}; }}
        /* RAW-signal toggles (per-plate FX/FY/FZ/COP…) match the marker list rows:
           same font size, left padding and row height — style-only, structure as is. */
        QCheckBox#signal-toggle {{ font-size: 11px; min-height: 22px; padding: 0px 2px 0px 4px; }}
        QListWidget#marker-list::item:selected {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}
        QListWidget#marker-list::indicator {{ margin-right: 6px; }}

        /* Generic list/table theming (covers dialog widgets without objectName) */
        QListWidget {{
            background: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER};
            border-radius: 4px;
            outline: none;
        }}
        QListWidget::item {{ padding: 4px 6px; min-height: 22px; }}
        QListWidget::item:selected {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}
        QTableWidget {{
            background: {BG_PANEL};
            alternate-background-color: {BG_MID};
            color: {TEXT_PRIMARY};
            gridline-color: {BORDER_LIGHT};
            border: 1px solid {BORDER};
            selection-background-color: {BG_HOVER};
            selection-color: {TEXT_PRIMARY};
        }}
        QTableWidget QHeaderView::section {{
            background: {BG_INPUT};
            color: {TEXT_SECONDARY};
            padding: 3px 6px;
            border: none;
            border-right: 1px solid {BORDER_LIGHT};
            border-bottom: 1px solid {BORDER};
            font-weight: 600;
        }}
        QTableWidget::item {{ padding: 2px 6px; }}

        QTableWidget#results-table {{
            background: {BG_PANEL};
            alternate-background-color: {BG_MID};
            color: {TEXT_PRIMARY};
            gridline-color: {BORDER_LIGHT};
            border: 1px solid {BORDER};
        }}
        QTableWidget#results-table QHeaderView::section {{
            background: {BG_INPUT};
            color: {TEXT_SECONDARY};
            padding: 4px 6px;
            border: none;
            border-right: 1px solid {BORDER_LIGHT};
            border-bottom: 1px solid {BORDER};
            font-weight: 600;
        }}
        QTableWidget#results-table::item {{ padding: 2px 6px; }}

        QGroupBox#model-group {{
            border: 1px solid {BORDER};
            border-radius: 6px;
            margin-top: 14px;
            padding: 10px 6px 6px 6px;
            font-weight: 600;
            color: {TEXT_SECONDARY};
        }}
        QGroupBox#model-group::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 4px;
            font-size: 12px;
            font-weight: 700;
            color: {TEXT_PRIMARY};
        }}
        QLabel#model-group-desc {{ color: {TEXT_MUTED}; font-size: 11px; }}

        QLabel#field-label {{
            color: {TEXT_SECONDARY};
            font-size: 11px;
        }}

        QSplitter#sidebar-splitter::handle, QSplitter#plot-splitter::handle {{
            background: transparent;
        }}
        QSplitter#sidebar-splitter::handle:hover, QSplitter#plot-splitter::handle:hover {{
            background: {BORDER};
        }}

        QLabel#section-label {{
            color: {TEXT_SECONDARY};
            font-size: 10px;
            letter-spacing: 1.2px;
        }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {BG_INPUT};
            border: none;
            border-radius: 5px;
            padding: 3px 8px;
            color: {TEXT_PRIMARY};
            min-height: 22px;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            background-color: {BG_HOVER};
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background-color: {BG_PANEL};
            border: 1px solid {BORDER};
            color: {TEXT_PRIMARY};
            selection-background-color: {ACCENT_TEAL};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 16px;
            border: none;
        }}

        QCheckBox {{
            color: {TEXT_PRIMARY};
            spacing: 7px;
            font-size: 12px;
        }}
        /* Unified selection indicator everywhere (sidebar toggles, lists, dialogs):
           a faint hollow ring when idle, a crisp filled green dot when checked.
           One round 12px indicator with a 1px ring gives the dot a visible target
           even before it's checked, so checkboxes never read as plain text. */
        QCheckBox::indicator,
        QListWidget::indicator, QTableWidget::indicator {{
            width: 12px; height: 12px;
            border: 1px solid {CHECK_RING};
            border-radius: 6px;
            background: transparent;
        }}
        QCheckBox::indicator:unchecked:hover,
        QListWidget::indicator:unchecked:hover,
        QTableWidget::indicator:unchecked:hover {{
            border-color: {CHECK_RING_HOVER};
        }}
        QCheckBox::indicator:checked,
        QListWidget::indicator:checked, QTableWidget::indicator:checked {{
            background: {CHECK_DOT};
            border: 1px solid {CHECK_DOT};
        }}
        QCheckBox::indicator:checked:hover,
        QListWidget::indicator:checked:hover,
        QTableWidget::indicator:checked:hover {{
            background: {SEL_GREEN};
            border: 1px solid {SEL_GREEN};
        }}
        QCheckBox::indicator:indeterminate,
        QListWidget::indicator:indeterminate, QTableWidget::indicator:indeterminate {{
            background: {CHECK_DOT_PARTLY};
            border: 1px solid {CHECK_DOT_PARTLY};
        }}
        QCheckBox::indicator:disabled {{
            border-color: {BORDER};
            background: {BG_DISABLED};
        }}
        QCheckBox:checked {{ color: {SEL_GREEN}; }}
        QCheckBox:disabled {{ color: {TEXT_MUTED}; }}

        /* Ultra-thin overlay scrollbars: 4px, transparent track, faint handle
           that brightens + thickens to 6px while hovered. */
        QScrollBar:vertical {{
            background: transparent;
            width: 4px;
            border: none;
            margin: 0;
        }}
        QScrollBar:vertical:hover {{ width: 6px; }}
        QScrollBar::handle:vertical {{
            background: rgba(138, 147, 160, 0.25);
            border-radius: 2px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(138, 147, 160, 0.80); }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{ background: transparent; }}

        QScrollBar:horizontal {{
            background: transparent;
            height: 4px;
            border: none;
            margin: 0;
        }}
        QScrollBar:horizontal:hover {{ height: 6px; }}
        QScrollBar::handle:horizontal {{
            background: rgba(138, 147, 160, 0.25);
            border-radius: 2px;
            min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: rgba(138, 147, 160, 0.80); }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{ width: 0; }}
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{ background: transparent; }}

        QScrollArea {{ border: none; background: transparent; }}

        QPushButton#record-btn {{
            background-color: {ACCENT_TEAL};
            color: #fff;
            border: none;
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#record-btn:hover  {{ background-color: #26B075; }}
        QPushButton#record-btn:disabled {{ background-color: {BG_INPUT}; color: {TEXT_SECONDARY}; }}

        QPushButton#record-btn-active {{
            background-color: {ACCENT_RED};
            color: #fff;
            border: none;
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 12px;
            font-weight: 600;
        }}

        QPushButton#save-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-radius: 4px;
            padding: 1px 4px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#save-btn:hover {{ background-color: {BG_HOVER}; color: {TEXT_PRIMARY}; }}

        QPushButton#clear-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-radius: 4px;
            padding: 1px 4px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#clear-btn:hover {{
            background-color: {BG_HOVER};
            color: {ACCENT_RED};
        }}

        QPushButton#run-btn {{
            background-color: {ACCENT_PURPLE};
            color: #fff;
            border: none;
            border-radius: 7px;
            padding: 6px 10px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#run-btn:hover {{ background-color: #7489FF; }}

        QPushButton#analysis-btn {{
            background-color: #3B82F6;
            color: #fff;
            border: none;
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 600;
        }}
        QPushButton#analysis-btn:hover {{ background-color: #2563EB; }}
        QPushButton#analysis-btn:disabled {{ background-color: {BG_INPUT}; color: {TEXT_SECONDARY}; }}

        QPushButton#load-btn {{
            background-color: {ACCENT_TEAL};
            color: #fff;
            border: none;
            border-radius: 7px;
            padding: 5px 10px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#load-btn:hover {{ background-color: #1C8E5B; }}
        QPushButton#load-btn:pressed {{ background-color: #18794D; }}

        QPushButton#small-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-radius: 4px;
            padding: 1px 4px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton#small-btn:hover {{ color: {TEXT_PRIMARY}; background-color: {BG_HOVER}; }}

        QPushButton#toggle-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-radius: 4px;
            padding: 2px 5px;
            font-size: 11px;
            font-weight: 600;
        }}
        QPushButton#toggle-btn:hover {{ color: {TEXT_PRIMARY}; background-color: {BG_HOVER}; }}
        QPushButton#toggle-btn:checked {{
            background-color: rgba(34, 162, 106, 0.14);
            color: {ACCENT_TEAL};
        }}

        QPushButton#icon-btn, QPushButton#play-btn, QPushButton#play-btn-active {{
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            padding: 0;
        }}
        QPushButton#icon-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
        }}
        QPushButton#icon-btn:hover {{ color: {TEXT_PRIMARY}; background-color: {BG_HOVER}; }}
        QPushButton#icon-btn:disabled {{ color: {TEXT_MUTED}; background-color: {BG_DISABLED}; }}

        QPushButton#play-btn {{
            background-color: transparent;
            color: {ACCENT_TEAL};
            border: none;
            font-size: 15px;
        }}
        QPushButton#play-btn:hover {{ background-color: {BG_HOVER}; }}
        QPushButton#play-btn:disabled {{ background-color: transparent; color: {TEXT_MUTED}; }}
        QPushButton#play-btn-active {{
            background-color: transparent;
            color: {ACCENT_TEAL};
            border: none;
            font-size: 13px;
        }}

        QLineEdit#search-input {{
            background-color: {BG_PANEL};
            border: 1px solid {BORDER};
            border-radius: 5px;
            padding: 3px 8px;
            min-height: 22px;
        }}
        QSpinBox#frame-field, QDoubleSpinBox#frame-field {{
            background-color: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 2px;
            padding: 0px 2px;
            min-height: 20px;
            font-size: 11px;
        }}
        QLineEdit#search-input:focus {{
            border: 1px solid {ACCENT_TEAL};
            background-color: {BG_PANEL};
        }}

        QListWidget#file-list {{
            background-color: {BG_INPUT};
            border: none;
            border-radius: 5px;
            padding: 2px;
            outline: none;
        }}
        QListWidget#file-list::item {{
            border-radius: 3px;
            padding: 3px 5px;
            margin: 0;
            color: {TEXT_PRIMARY};
        }}
        QListWidget#file-list::item:hover {{ background-color: {BG_HOVER}; }}
        QListWidget#file-list::item:selected {{
            background-color: {BG_HOVER};
            color: {TEXT_PRIMARY};
        }}
        /* PIPELINE step rows are transparent so the list item's hover/selected
           background reads through them (VSCode-style uniform row highlight). */
        QWidget#pipeline-row {{ background: transparent; }}
        QListWidget#file-list::indicator {{
            width: 13px;
            height: 13px;
            border: 1px solid {BORDER};
            border-radius: 7px;
            background: {BG_PANEL};
        }}
        QListWidget#file-list::indicator:checked {{
            background: {ACCENT_TEAL};
            border: 1px solid {ACCENT_TEAL};
            border-radius: 7px;
        }}
        QListWidget#file-list::indicator:unchecked:hover {{ border-color: #94A7BF; }}

        QTreeWidget#file-list {{
            background-color: {BG_INPUT};
            border: none;
            border-radius: 5px;
            padding: 2px;
            outline: none;
        }}
        QTreeWidget#file-list::item {{
            border-radius: 3px;
            padding: 1px 3px;
            color: {TEXT_PRIMARY};
        }}
        QTreeWidget#file-list::item:hover {{ background-color: {BG_HOVER}; border-radius: 0; }}
        QTreeWidget#file-list::item:selected {{ background-color: {BG_HOVER}; color: {TEXT_PRIMARY}; border-radius: 0; }}
        QTreeWidget#file-list::branch {{ background: transparent; image: none; border-image: none; }}
        QTreeWidget#file-list::indicator {{
            width: 12px; height: 12px;
            border: 1px solid {CHECK_RING};
            border-radius: 6px;
            background: transparent;
            margin-left: 3px;
        }}
        QTreeWidget#file-list::indicator:unchecked:hover {{
            border-color: {CHECK_RING_HOVER};
        }}
        QTreeWidget#file-list::indicator:checked {{
            background: {CHECK_DOT};
            border: 1px solid {CHECK_DOT};
        }}
        QTreeWidget#file-list::indicator:indeterminate {{
            background: {CHECK_DOT_PARTLY};
            border: 1px solid {CHECK_DOT_PARTLY};
        }}

        QLabel#count-chip {{
            background-color: {BG_PANEL};
            color: {TEXT_SECONDARY};
            border-radius: 8px;
            min-width: 16px;
            padding: 0px 5px;
            margin-left: 4px;
            font-size: 10px;
            font-weight: 600;
        }}
        QLabel#model-icon {{
            background: {ACCENT_TEAL};
            border: 1px solid {ACCENT_TEAL};
            border-radius: 6px;
        }}
        QLabel#model-icon-empty {{
            background: transparent;
            border: 1px solid {TEXT_MUTED};
            border-radius: 6px;
        }}
        QLabel#group-tag {{
            font-size: 10px;
            font-weight: 600;
            background: transparent;
        }}
        QPushButton#run-icon {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: none;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        QPushButton#run-icon:hover {{ color: {TEXT_PRIMARY}; background-color: {BG_HOVER}; }}
        QPushButton#run-icon:checked {{
            background-color: {ACCENT_TEAL};
            color: #FFFFFF;
        }}

        QFrame#metric-card {{
            background-color: transparent;
            border: none;
            border-radius: 0;
            padding: 4px;
        }}
        """


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)
