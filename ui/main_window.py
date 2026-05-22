import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QTabWidget
from core.axis_settings import AxisSettings
from ui.collect_tab import CollectTab
from ui.analyze_tab import AnalyzeTab
from ui.settings_tab import SettingsTab
from ui.style import (
    BG_DARK, BG_MID, BG_PANEL, BG_INPUT,
    ACCENT_TEAL, ACCENT_PURPLE, ACCENT_RED,
    TEXT_PRIMARY, TEXT_SECONDARY, BORDER,
)


class MainWindow(QMainWindow):

    def __init__(self, qtm_ip: str = "127.0.0.1"):
        super().__init__()
        self.setWindowTitle("BALLAB")
        self.setWindowIcon(QIcon(resource_path("assets/ballab_icon_master_1024_transparent.png")))
        self.resize(1340, 820)
        self.setMinimumSize(960, 620)

        self.axis_settings = AxisSettings()
        self.tabs          = QTabWidget()
        self.collect_tab   = CollectTab(qtm_ip=qtm_ip, axis_settings=self.axis_settings)
        self.analyze_tab   = AnalyzeTab(axis_settings=self.axis_settings)
        self.settings_tab  = SettingsTab(self.axis_settings)

        self.tabs.addTab(self.collect_tab, "  Record  ")
        self.tabs.addTab(self.analyze_tab, "  Analyze  ")
        self.tabs.addTab(self.settings_tab, "  Settings  ")

        self.setCentralWidget(self.tabs)
        self.setStyleSheet(self._style())

    def _style(self):
        return f"""
        QMainWindow, QWidget {{
            background-color: {BG_MID};
            color: {TEXT_PRIMARY};
            font-size: 13px;
        }}
        QTabWidget::pane {{
            border: none;
        }}
        QTabBar::tab {{
            background: {BG_DARK};
            color: {TEXT_SECONDARY};
            padding: 9px 22px;
            border: none;
            border-right: 1px solid {BORDER};
            font-size: 13px;
        }}
        QTabBar::tab:selected {{
            background: {BG_MID};
            color: {TEXT_PRIMARY};
            border-bottom: 2px solid {ACCENT_TEAL};
        }}
        QTabBar::tab:hover:!selected {{
            color: {TEXT_PRIMARY};
            background: #1F1F1F;
        }}

        QFrame#sidebar {{
            background-color: {BG_DARK};
            border-right: 1px solid {BORDER};
        }}
        QFrame#statusbar {{
            background-color: {BG_DARK};
            border-top: 1px solid {BORDER};
        }}

        QLabel#section-label {{
            color: {TEXT_SECONDARY};
            font-size: 10px;
            letter-spacing: 1.2px;
        }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 3px 8px;
            color: {TEXT_PRIMARY};
            min-height: 26px;
            max-height: 26px;
        }}
        QLineEdit:focus {{ border-color: {ACCENT_TEAL}; }}
        QComboBox::drop-down {{ border: none; width: 16px; }}
        QComboBox QAbstractItemView {{
            background-color: {BG_INPUT};
            border: 1px solid {BORDER};
            color: {TEXT_PRIMARY};
            selection-background-color: {ACCENT_TEAL};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 14px;
            border: none;
        }}

        QCheckBox {{
            color: {TEXT_PRIMARY};
            spacing: 7px;
            font-size: 12px;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {BORDER};
            border-radius: 3px;
            background: {BG_INPUT};
        }}
        QCheckBox::indicator:checked {{
            background: {ACCENT_TEAL};
            border-color: {ACCENT_TEAL};
        }}

        QScrollBar:vertical {{
            background: {BG_DARK};
            width: 5px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: #3A3A3A;
            border-radius: 2px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0; }}

        QScrollBar:horizontal {{
            background: {BG_DARK};
            height: 5px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: #3A3A3A;
            border-radius: 2px;
            min-width: 20px;
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{ width: 0; }}

        QScrollArea {{ border: none; background: transparent; }}

        QPushButton#record-btn {{
            background-color: {ACCENT_TEAL};
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 10px;
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton#record-btn:hover  {{ background-color: #22B585; }}
        QPushButton#record-btn:disabled {{ background-color: #2A2A2A; color: #555; }}

        QPushButton#record-btn-active {{
            background-color: {ACCENT_RED};
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 10px;
            font-size: 13px;
        }}

        QPushButton#save-btn {{
            background-color: {ACCENT_TEAL};
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 9px;
            font-size: 13px;
        }}
        QPushButton#save-btn:hover {{ background-color: #22B585; }}

        QPushButton#clear-btn {{
            background-color: transparent;
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 9px;
            font-size: 13px;
        }}
        QPushButton#clear-btn:hover {{
            color: {TEXT_PRIMARY};
            border-color: #555;
        }}

        QPushButton#run-btn {{
            background-color: {ACCENT_PURPLE};
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 10px;
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton#run-btn:hover {{ background-color: #6059CC; }}

        QPushButton#analysis-btn {{
            background-color: #2563EB;
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 12px;
            font-weight: 500;
        }}
        QPushButton#analysis-btn:hover {{ background-color: #1D4ED8; }}
        QPushButton#analysis-btn:disabled {{ background-color: #2A2A2A; color: #555; }}

        QPushButton#load-btn {{
            background-color: {BG_PANEL};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 8px;
            font-size: 13px;
        }}
        QPushButton#load-btn:hover {{ border-color: #555; }}

        QPushButton#small-btn {{
            background-color: {BG_PANEL};
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER};
            border-radius: 4px;
            padding: 3px 8px;
            font-size: 11px;
        }}
        QPushButton#small-btn:hover {{ color: {TEXT_PRIMARY}; }}

        QFrame#metric-card {{
            background-color: {BG_PANEL};
            border: 1px solid {BORDER};
            border-radius: 6px;
        }}
        """


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)
