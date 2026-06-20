"""Modal dialogs reached from the Settings menu (Axis, Normalize)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialogButtonBox,
)
from PyQt6.QtCore import Qt

from core.axis_settings import AXIS_KEYS
from ui.style import ACCENT_TEAL, BG_INPUT, BORDER, TEXT_PRIMARY, TEXT_SECONDARY


class _SettingsDialog(QDialog):
    """Base dialog providing a vertical layout of labelled on/off toggles."""

    def __init__(self, parent, title, description):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)

        self._vb = QVBoxLayout(self)
        self._vb.setContentsMargins(18, 18, 18, 18)
        self._vb.setSpacing(12)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:12px;")
        self._vb.addWidget(desc)

    def _finish(self):
        self._vb.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        self._vb.addWidget(buttons)

    def _toggle_row(self, label_text, off_text, on_text, checked, callback):
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(label_text)
        label.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:12px;")

        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setChecked(bool(checked))
        toggle.setFixedHeight(22)
        toggle.setMinimumWidth(58)
        toggle.clicked.connect(callback)
        toggle.clicked.connect(
            lambda _c, b=toggle, off=off_text, on=on_text: self._style_toggle(b, off, on)
        )
        self._style_toggle(toggle, off_text, on_text)

        row.addWidget(label, 1)
        row.addWidget(toggle)
        self._vb.addLayout(row)

    def _style_toggle(self, button, off_text, on_text):
        checked = button.isChecked()
        button.setText(on_text if checked else off_text)
        bg = "rgba(34, 162, 106, 0.14)" if checked else "transparent"
        fg = ACCENT_TEAL if checked else TEXT_SECONDARY
        button.setStyleSheet(
            f"background:{bg}; color:{fg}; border:none;"
            "border-radius:4px; padding:1px 6px; font-size:11px; font-weight:600;"
        )


class AxisDialog(_SettingsDialog):
    def __init__(self, parent, axis_settings):
        super().__init__(
            parent, "Axis",
            "Applied to QTM streaming data before display and CSV recording.",
        )
        self.axis_settings = axis_settings
        for axis in AXIS_KEYS:
            self._toggle_row(
                axis, "Normal", "Inverted",
                axis_settings.live_signs[axis] < 0,
                lambda checked, a=axis: axis_settings.set_live_sign(a, -1 if checked else 1),
            )
        self._finish()


class NormalizeDialog(_SettingsDialog):
    def __init__(self, parent, axis_settings):
        super().__init__(
            parent, "Normalize",
            "Reserved for COP displacement normalization by foot position and size.",
        )
        self.axis_settings = axis_settings
        self._toggle_row(
            "Foot displacement normalized", "Off", "On",
            axis_settings.foot_displacement_normalized,
            axis_settings.set_foot_displacement_normalized,
        )
        self._finish()
