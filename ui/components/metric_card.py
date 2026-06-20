"""Metric card widget for displaying KPI values."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from ui import style


class MetricCardWidget(QFrame):
    """
    A compact card displaying a single metric value.
    
    Usage:
        card = MetricCardWidget(label="RMS AP", value="4.2", unit="mm")
        layout.addWidget(card)
    """
    
    def __init__(self, label: str, value: str = "-", unit: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.label_text = label
        self.value_text = value
        self.unit_text = unit
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the metric card layout."""
        layout = QVBoxLayout()
        layout.setContentsMargins(
            int(style.SPACING_MD.rstrip("px")),
            int(style.SPACING_MD.rstrip("px")),
            int(style.SPACING_MD.rstrip("px")),
            int(style.SPACING_MD.rstrip("px")),
        )
        layout.setSpacing(int(style.SPACING_XS.rstrip("px")))
        
        # Label
        self.label = QLabel(self.label_text)
        self.label.setStyleSheet(f"""
            color: {style.TEXT_SECONDARY};
            font-size: {style.FONT_SIZE_SMALL};
            font-weight: {style.FONT_WEIGHT_NORMAL};
        """)
        layout.addWidget(self.label)
        
        # Value with unit
        self.value_label = QLabel(f"{self.value_text} {self.unit_text}".strip())
        self.value_label.setStyleSheet(f"""
            color: {style.TEXT_PRIMARY};
            font-size: {style.FONT_SIZE_LARGE};
            font-weight: {style.FONT_WEIGHT_BOLD};
        """)
        layout.addWidget(self.value_label)
        
        self.setLayout(layout)
        self._apply_style()
        self.setMinimumHeight(int(style.CARD_MIN_HEIGHT.rstrip("px")))
    
    def _apply_style(self):
        """Apply metric card styling."""
        self.setStyleSheet(f"""
            MetricCardWidget {{
                background-color: {style.BG_MID};
                border: 1px solid {style.BORDER_LIGHT};
                border-radius: {style.BORDER_RADIUS_MD};
            }}
        """)
    
    def setValue(self, value: str, unit: str = ""):
        """Update the metric value and unit."""
        self.value_text = value
        self.unit_text = unit
        self.value_label.setText(f"{value} {unit}".strip())
    
    def setLabel(self, label: str):
        """Update the metric label."""
        self.label_text = label
        self.label.setText(label)
