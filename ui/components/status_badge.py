"""Status badge widget for displaying connection and recording state."""

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from ui import style


class StatusBadgeWidget(QFrame):
    """
    A small badge showing status (Connected, Recording, Disconnected, etc).
    
    Usage:
        badge = StatusBadgeWidget(status="Connected", status_type="success")
        layout.addWidget(badge)
    """
    
    def __init__(self, status: str = "Idle", status_type: str = "neutral", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.status_text = status
        self.status_type = status_type  # success, warning, error, neutral
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the badge layout."""
        layout = QHBoxLayout()
        layout.setContentsMargins(
            int(style.SPACING_SM.rstrip("px")),
            int(style.SPACING_XS.rstrip("px")),
            int(style.SPACING_SM.rstrip("px")),
            int(style.SPACING_XS.rstrip("px")),
        )
        layout.setSpacing(int(style.SPACING_XS.rstrip("px")))
        
        # Status label
        self.label = QLabel(self.status_text)
        self.label.setStyleSheet(f"""
            color: {style.TEXT_PRIMARY};
            font-size: {style.FONT_SIZE_SMALL};
            font-weight: {style.FONT_WEIGHT_SEMI};
        """)
        layout.addWidget(self.label)
        
        self.setLayout(layout)
        self._apply_style()
    
    def _apply_style(self):
        """Apply badge styling based on status type."""
        if self.status_type == "success":
            bg_color = "#E8F5E9"
            border_color = ACCENT_GREEN = "#2ECC71"
            text_color = "#1B5E20"
        elif self.status_type == "warning":
            bg_color = "#FFF3E0"
            border_color = "#F39C12"
            text_color = "#E65100"
        elif self.status_type == "error":
            bg_color = "#FFEBEE"
            border_color = style.ACCENT_RED
            text_color = "#B71C1C"
        else:  # neutral
            bg_color = style.BG_MID
            border_color = style.BORDER_LIGHT
            text_color = style.TEXT_SECONDARY
        
        self.setStyleSheet(f"""
            StatusBadgeWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: {style.BORDER_RADIUS_MD};
            }}
            QLabel {{
                color: {text_color};
            }}
        """)
    
    def setStatus(self, status: str, status_type: str = None):
        """Update the badge status and optionally the type."""
        self.status_text = status
        if status_type:
            self.status_type = status_type
        self.label.setText(status)
        self._apply_style()
