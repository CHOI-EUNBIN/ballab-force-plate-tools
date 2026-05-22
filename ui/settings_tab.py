from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QComboBox, QScrollArea, QScroller,
)
from PyQt6.QtCore import Qt

from core.axis_settings import AXIS_KEYS
from core.signal_proc import FILTER_TYPES
from ui.style import (
    ACCENT_TEAL, BG_DARK, BG_INPUT, BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
)


class SettingsTab(QWidget):

    def __init__(self, axis_settings):
        super().__init__()
        self.axis_settings = axis_settings
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 24, 24, 24)
        body_layout.setSpacing(18)

        title = QLabel("Settings")
        title.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:20px;font-weight:600;")
        body_layout.addWidget(title)

        subtitle = QLabel("Configure how incoming data is converted before recording.")
        subtitle.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:12px;")
        body_layout.addWidget(subtitle)

        body_layout.addWidget(self._axis_section())
        body_layout.addWidget(self._filter_section())
        body_layout.addWidget(self._normalization_section())
        body_layout.addStretch()
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(body)
        QScroller.grabGesture(
            scroll.viewport(),
            QScroller.ScrollerGestureType.LeftMouseButtonGesture,
        )
        root.addWidget(scroll)

    def _axis_section(self):
        frame, content = self._setting_panel(
            "Recording axis",
            "Applied to QTM streaming data before display and CSV recording.",
        )

        for axis in AXIS_KEYS:
            content.addLayout(self._toggle_row(
                axis,
                "Normal",
                "Inverted",
                self.axis_settings.live_signs[axis] < 0,
                lambda checked, a=axis: self.axis_settings.set_live_sign(
                    a, -1 if checked else 1
                ),
            ))

        return frame

    def _normalization_section(self):
        frame, content = self._setting_panel(
            "Foot displacement normalized",
            "Reserved for COP displacement normalization by foot position and size.",
        )
        content.addLayout(self._toggle_row(
            "Normalized",
            "Off",
            "On",
            self.axis_settings.foot_displacement_normalized,
            self.axis_settings.set_foot_displacement_normalized,
        ))
        return frame

    def _filter_section(self):
        frame, content = self._setting_panel(
            "Analysis filter",
            "Applied only when Run Analysis is executed.",
        )
        content.addLayout(self._toggle_row(
            "Enabled",
            "Off",
            "On",
            self.axis_settings.filter_enabled,
            self.axis_settings.set_filter_enabled,
        ))
        content.addLayout(self._combo_row(
            "Type",
            FILTER_TYPES,
            self.axis_settings.filter_type,
            self.axis_settings.set_filter_type,
        ))
        content.addLayout(self._double_spin_row(
            "Cutoff",
            0.5,
            100.0,
            self.axis_settings.filter_cutoff_hz,
            " Hz",
            self.axis_settings.set_filter_cutoff_hz,
        ))
        content.addLayout(self._spin_row(
            "Order",
            1,
            8,
            self.axis_settings.filter_order,
            self.axis_settings.set_filter_order,
        ))
        return frame

    def _setting_panel(self, title, description):
        frame = QFrame()
        frame.setFixedWidth(560)
        frame.setStyleSheet(
            f"QFrame {{ background:{BG_DARK}; border:1px solid {BORDER}; border-radius:6px; }}"
            "QLabel { border:none; background:transparent; }"
        )
        vb = QVBoxLayout(frame)
        vb.setContentsMargins(16, 14, 16, 16)
        vb.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:14px;font-weight:600;")
        arrow_btn = QPushButton("v")
        arrow_btn.setFixedSize(24, 22)
        arrow_btn.setCheckable(True)
        arrow_btn.setChecked(False)
        arrow_btn.setStyleSheet(
            f"background:{BG_INPUT}; color:{TEXT_SECONDARY}; border:1px solid {BORDER};"
            "border-radius:4px; padding:0; font-size:11px;"
        )

        header.addWidget(title_lbl, 1)
        header.addWidget(arrow_btn)
        vb.addLayout(header)

        content = QWidget()
        content.setStyleSheet("background:transparent; border:none;")
        content_vb = QVBoxLayout(content)
        content_vb.setContentsMargins(0, 0, 0, 0)
        content_vb.setSpacing(10)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:11px;")
        content_vb.addWidget(desc_lbl)
        vb.addWidget(content)
        content.setVisible(False)
        arrow_btn.setText(">")

        arrow_btn.clicked.connect(
            lambda checked, w=content, b=arrow_btn: self._toggle_panel(w, b, checked)
        )
        return frame, content_vb

    def _toggle_panel(self, content, button, expanded):
        content.setVisible(expanded)
        button.setText("v" if expanded else ">")

    def _toggle_row(self, label_text, off_text, on_text, checked, callback):
        row = QHBoxLayout()
        row.setSpacing(12)

        label = QLabel(label_text)
        label.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:12px;")

        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setChecked(bool(checked))
        toggle.setFixedWidth(116)
        toggle.clicked.connect(callback)
        toggle.clicked.connect(lambda _checked, b=toggle, off=off_text, on=on_text: self._style_toggle(b, off, on))
        self._style_toggle(toggle, off_text, on_text)

        row.addWidget(label, 1)
        row.addWidget(toggle)
        return row

    def _combo_row(self, label_text, items, current, callback):
        row = self._control_row(label_text)
        combo = QComboBox()
        combo.addItems(items)
        if current in items:
            combo.setCurrentText(current)
        combo.currentTextChanged.connect(callback)
        row.addWidget(combo)
        return row

    def _double_spin_row(self, label_text, minimum, maximum, value, suffix, callback):
        row = self._control_row(label_text)
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(0.5)
        spin.setValue(float(value))
        spin.setSuffix(suffix)
        spin.valueChanged.connect(callback)
        row.addWidget(spin)
        return row

    def _spin_row(self, label_text, minimum, maximum, value, callback):
        row = self._control_row(label_text)
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(int(value))
        spin.valueChanged.connect(callback)
        row.addWidget(spin)
        return row

    def _control_row(self, label_text):
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel(label_text)
        label.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:12px;")
        row.addWidget(label, 1)
        return row

    def _style_toggle(self, button, off_text, on_text):
        checked = button.isChecked()
        button.setText(on_text if checked else off_text)
        bg = ACCENT_TEAL if checked else BG_INPUT
        fg = "#FFFFFF" if checked else TEXT_SECONDARY
        border = ACCENT_TEAL if checked else BORDER
        button.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {border};"
            "border-radius:13px; padding:4px 12px; font-size:12px;"
        )
