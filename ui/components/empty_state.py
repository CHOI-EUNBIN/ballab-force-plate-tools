"""Empty state widget for displaying when no data is available."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from ui import style


class EmptyStateWidget(QFrame):
    """
    A placeholder widget shown when no data is available.
    
    Usage:
        empty = EmptyStateWidget(
            title="No file loaded",
            message="Load a C3D file to start analysis"
        )
        layout.addWidget(empty)
    """
    
    def __init__(self, title: str = "No data", message: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.title_text = title
        self.message_text = message
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the empty state layout."""
        layout = QVBoxLayout()
        layout.setContentsMargins(
            int(style.SPACING_XL.rstrip("px")),
            int(style.SPACING_XL.rstrip("px")),
            int(style.SPACING_XL.rstrip("px")),
            int(style.SPACING_XL.rstrip("px")),
        )
        layout.setSpacing(int(style.SPACING_MD.rstrip("px")))
        layout.addStretch()
        
        # Title
        self.title_label = QLabel(self.title_text)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"""
            color: {style.TEXT_SECONDARY};
            font-size: {style.FONT_SIZE_LARGE};
            font-weight: {style.FONT_WEIGHT_SEMI};
        """)
        layout.addWidget(self.title_label)
        
        # Message
        if self.message_text:
            self.message_label = QLabel(self.message_text)
            self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.message_label.setWordWrap(True)
            self.message_label.setStyleSheet(f"""
                color: {style.TEXT_MUTED};
                font-size: {style.FONT_SIZE_BASE};
                font-weight: {style.FONT_WEIGHT_NORMAL};
            """)
            layout.addWidget(self.message_label)
        
        layout.addStretch()
        self.setLayout(layout)
        self._apply_style()
    
    def _apply_style(self):
        """Apply empty state styling."""
        self.setStyleSheet(f"""
            EmptyStateWidget {{
                background-color: {style.BG_PANEL};
                border: 1px dashed {style.BORDER_LIGHT};
                border-radius: {style.BORDER_RADIUS_LG};
            }}
        """)
    
    def setContent(self, title: str, message: str = ""):
        """Update the empty state content."""
        self.title_text = title
        self.message_text = message
        self.title_label.setText(title)
        if hasattr(self, 'message_label'):
            self.message_label.setText(message)
