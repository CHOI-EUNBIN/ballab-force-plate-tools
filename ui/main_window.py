import os
import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QFileDialog, QMessageBox
from core.axis_settings import AxisSettings
from core.project import save_project, load_project, PROJECT_FILTER, PROJECT_EXT
from ui.collect_tab import CollectTab
from ui.analyze_tab import AnalyzeTab
from ui.settings_dialogs import AxisDialog, NormalizeDialog
from ui.style import LIGHT_PALETTE, DARK_PALETTE, use_theme


class MainWindow(QMainWindow):

    def __init__(self, qtm_ip: str = "127.0.0.1"):
        super().__init__()
        self.setWindowTitle("Balancelab")
        self.setWindowIcon(QIcon(resource_path("assets/ballab_icon_master_1024_transparent.png")))
        self.resize(1340, 820)
        self.setMinimumSize(960, 620)

        self.axis_settings = AxisSettings()

        # Resolve the theme before building tabs so plots/labels build with the
        # right colours from the start.
        self._qsettings = QSettings("Balancelab", "Balancelab")
        self._theme = self._qsettings.value("theme", "light") or "light"
        self._palette = use_theme(self._theme)

        self.stack         = QStackedWidget()
        self.collect_tab   = CollectTab(qtm_ip=qtm_ip, axis_settings=self.axis_settings)
        self.analyze_tab   = AnalyzeTab(axis_settings=self.axis_settings)

        self.stack.addWidget(self.collect_tab)
        self.stack.addWidget(self.analyze_tab)

        self.setCentralWidget(self.stack)
        self.current_project_path = None

        self._build_menubar()
        self.setStyleSheet(self._style())
        self._switch_view(self.collect_tab)

    def _build_menubar(self):
        menubar = self.menuBar()
        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)

        def view_action(text, widget):
            action = QAction(text, self)
            action.setCheckable(True)
            action._widget = widget
            action.triggered.connect(lambda _=False, w=widget: self._switch_view(w))
            self._view_group.addAction(action)
            menubar.addAction(action)
            return action

        view_action("Record", self.collect_tab)
        view_action("Analyze", self.analyze_tab)

        file_menu = menubar.addMenu("File")

        def file_action(text, slot, shortcut=None):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            file_menu.addAction(action)
            return action

        file_action("New Project", self._new_project, "Ctrl+N")
        file_action("Open Project...", self._open_project, "Ctrl+O")
        file_action("Save Project", self._save_project, "Ctrl+S")
        file_action("Save Project As...", self._save_project_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._load_file_action = file_action("Load File...", self._load_file, "Ctrl+L")
        self._export_action = file_action("Export...", self._export, "Ctrl+E")
        file_menu.addSeparator()
        file_action("Exit", self.close)

        settings_menu = menubar.addMenu("Settings")
        axis_action = QAction("Axis...", self)
        axis_action.triggered.connect(self._open_axis_settings)
        settings_menu.addAction(axis_action)
        normalize_action = QAction("Normalize...", self)
        normalize_action.triggered.connect(self._open_normalize_settings)
        settings_menu.addAction(normalize_action)
        settings_menu.addSeparator()

        theme_menu = settings_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for label, name in [("Light", "light"), ("Dark", "dark")]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self._theme == name)
            act.triggered.connect(lambda _=False, n=name: self.apply_theme(n))
            self._theme_group.addAction(act)
            theme_menu.addAction(act)

        help_menu = menubar.addMenu("Help")
        metrics_help = QAction("Metrics Reference", self)
        metrics_help.triggered.connect(self._open_metrics_help)
        help_menu.addAction(metrics_help)

        self._update_menu_state()

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

    def _open_axis_settings(self):
        AxisDialog(self, self.axis_settings).exec()

    def _open_normalize_settings(self):
        NormalizeDialog(self, self.axis_settings).exec()

    def apply_theme(self, name):
        self._theme = "dark" if name == "dark" else "light"
        self._palette = use_theme(self._theme)
        self._qsettings.setValue("theme", self._theme)
        self.setStyleSheet(self._style())
        for tab in (self.collect_tab, self.analyze_tab):
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

    def _export(self):
        tab = self.stack.currentWidget()
        if hasattr(tab, "export_data"):
            tab.export_data()

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
            text-align: left;
            padding: 4px 0;
        }}
        QPushButton#section-toggle:hover {{ color: {ACCENT_TEAL}; }}

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
            spacing: 6px;
            font-size: 12px;
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
            border: 1px solid {BORDER};
            border-radius: 3px;
            background: {BG_INPUT};
        }}
        QCheckBox::indicator:checked {{
            background: {ACCENT_TEAL};
            border-color: {ACCENT_TEAL};
        }}

        QScrollBar:vertical {{
            background: {BG_MID};
            width: 8px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #A5B5C8;
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0; }}

        QScrollBar:horizontal {{
            background: {BG_MID};
            height: 8px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: #A5B5C8;
            border-radius: 4px;
            min-width: 20px;
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{ width: 0; }}

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
            background-color: {ACCENT_TEAL};
            color: #fff;
            border: none;
        }}
        QPushButton#play-btn:hover {{ background-color: #1C8E5B; }}
        QPushButton#play-btn:disabled {{ background-color: {BG_INPUT}; color: {TEXT_MUTED}; }}
        QPushButton#play-btn-active {{
            background-color: {ACCENT_RED};
            color: #fff;
            border: none;
        }}

        QLineEdit#search-input {{
            border-radius: 5px;
            padding: 3px 8px;
            min-height: 22px;
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
