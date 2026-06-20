"""Reusable card container for plots, content, and metrics."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt
from ui import style


class CardWidget(QFrame):
    """
    A styled card container with optional title and content.
    
    Usage:
        card = CardWidget(title="Force X")
        layout = card.contentLayout()
        layout.addWidget(plot_widget)
    """
    
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.title_text = title
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the card layout."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(
            int(style.SPACING_LG.rstrip("px")),
            int(style.SPACING_LG.rstrip("px")),
            int(style.SPACING_LG.rstrip("px")),
            int(style.SPACING_LG.rstrip("px")),
        )
        main_layout.setSpacing(int(style.SPACING_MD.rstrip("px")))
        
        # Title
        if self.title_text:
            self.title_label = QLabel(self.title_text)
            self.title_label.setStyleSheet(f"""
                color: {style.TEXT_PRIMARY};
                font-size: {style.FONT_SIZE_LARGE};
                font-weight: {style.FONT_WEIGHT_SEMI};
            """)
            main_layout.addWidget(self.title_label)
        
        # Content area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self.content_widget.setLayout(self.content_layout)
        main_layout.addWidget(self.content_widget, 1)
        
        self.setLayout(main_layout)
        self._apply_style()
    
    def _apply_style(self):
        """Apply card styling."""
        self.setStyleSheet(f"""
            CardWidget {{
                background-color: {style.BG_PANEL};
                border: 1px solid {style.BORDER_LIGHT};
                border-radius: {style.BORDER_RADIUS_LG};
            }}
        """)
    
    def contentLayout(self):
        """Get the content area layout for adding widgets."""
        return self.content_layout
    
    def setTitle(self, title: str):
        """Update the card title."""
        if hasattr(self, 'title_label'):
            self.title_label.setText(title)
        self.title_text = title
