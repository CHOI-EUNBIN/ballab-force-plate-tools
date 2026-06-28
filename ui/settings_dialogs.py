"""Modal dialogs reached from the Settings menu (Axis, Normalize, Appearance)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialogButtonBox,
    QColorDialog, QCheckBox, QDoubleSpinBox, QComboBox, QGridLayout, QWidget,
    QScrollArea, QFrame, QLineEdit,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QSettings
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush

from core.axis_settings import AXIS_KEYS
from core.appearance import DEFAULTS
# Read colours through the module (not `from ui.style import …`) so they reflect
# the active theme: use_theme() rebinds ui.style.* at runtime, but a direct
# import would freeze the light-theme values at import time (dark-mode text bug).
from ui import style


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
        desc.setStyleSheet(style.label_style(style.TEXT_SECONDARY, 12))
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
        label.setStyleSheet(style.label_style(style.TEXT_PRIMARY, 12))

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
        fg = style.ACCENT_TEAL if checked else style.TEXT_SECONDARY
        button.setStyleSheet(
            f"background:{bg}; color:{fg}; border:none;"
            "border-radius:4px; padding:1px 6px; font-size:11px; font-weight:600;"
        )


class RecordingAxisDialog(_SettingsDialog):
    """Record ▸ Recording axis — per-channel sign/polarity correction applied to
    the live QTM stream before display and CSV recording. Use when a force
    plate's axis is physically mounted the opposite way. Does not affect already
    recorded / loaded files."""

    def __init__(self, parent, axis_settings):
        super().__init__(
            parent, "Recording axis",
            "Flips the sign (+/−) of each channel on the live QTM stream before "
            "display and CSV recording — for force plates mounted with a reversed "
            "axis. Only affects new recordings, not loaded files.",
        )
        self.axis_settings = axis_settings
        for axis in AXIS_KEYS:
            self._toggle_row(
                axis, "Normal", "Inverted",
                axis_settings.live_signs[axis] < 0,
                lambda checked, a=axis: axis_settings.set_live_sign(a, -1 if checked else 1),
            )
        self._finish()


class RagServiceDialog(_SettingsDialog):
    """Settings ▸ AI 도우미(RAG) — RAG 서비스 URL 설정. 저장 시 떠 있는 패널에
    즉시 반영(재시작 불필요)."""

    def __init__(self, parent):
        super().__init__(
            parent, "AI Assistant (RAG) Settings",
            "Address of the RAG service (serve.py). Usually http://localhost:8000. "
            "Point it to a shared server if you use one.",
        )
        self._qsettings = QSettings("Balancelab", "Balancelab")
        row = QHBoxLayout()
        row.setSpacing(12)
        label = QLabel("Service URL")
        label.setStyleSheet(style.label_style(style.TEXT_PRIMARY, 12))
        self._url_edit = QLineEdit(
            self._qsettings.value("rag/service_url", "http://localhost:8000", type=str))
        # 기존 설정 다이얼로그처럼 즉시 적용: 편집 끝나면(포커스 이동/Enter) 저장.
        self._url_edit.editingFinished.connect(self._save)
        row.addWidget(label)
        row.addWidget(self._url_edit, 1)
        self._vb.addLayout(row)
        self._finish()

    def _save(self):
        url = self._url_edit.text().strip() or "http://localhost:8000"
        self._qsettings.setValue("rag/service_url", url)
        panel = getattr(self.parent(), "ai_panel", None)
        if panel is not None:
            panel.set_base_url(url)

    def reject(self):
        # Close 버튼(RejectRole)으로 닫을 때도 저장 보장.
        self._save()
        super().reject()


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


class ViewDialog(_SettingsDialog):
    """Choose which views are shown (currently the 3D view; extensible)."""

    def __init__(self, parent, analyze_tab):
        super().__init__(parent, "View", "Choose which views are shown in Analyze.")
        self.analyze_tab = analyze_tab
        self._toggle_row(
            "Show 3D view", "Off", "On",
            analyze_tab.is_3d_view_on(),
            analyze_tab.set_3d_view_on,
        )
        self._finish()


# ----- Appearance (graph + 3D colours) with live preview, commit on Apply -----

# normalized skeleton (front view, y down) for the preview
_SK = {
    "RASIS": (0.62, 0.10), "LASIS": (0.38, 0.10),
    "RPSIS": (0.56, 0.15), "LPSIS": (0.44, 0.15),
    "R_HIP": (0.58, 0.19), "L_HIP": (0.42, 0.19),
    "R_KNEE": (0.585, 0.52), "L_KNEE": (0.415, 0.52),
    "R_ANKLE": (0.58, 0.84), "L_ANKLE": (0.42, 0.84),
    "RHEEL": (0.56, 0.90), "LHEEL": (0.44, 0.90),
    "RTOE": (0.63, 0.90), "LTOE": (0.37, 0.90),
}
_SK_BONES = [("R_HIP", "R_KNEE"), ("R_KNEE", "R_ANKLE"), ("RHEEL", "RTOE"),
             ("L_HIP", "L_KNEE"), ("L_KNEE", "L_ANKLE"), ("LHEEL", "LTOE")]
_SK_PELVIS = [("RASIS", "LASIS"), ("LASIS", "LPSIS"), ("LPSIS", "RPSIS"),
              ("RPSIS", "RASIS"), ("R_HIP", "RASIS"), ("L_HIP", "LASIS")]
_SK_JOINTS = ["R_HIP", "L_HIP", "R_KNEE", "L_KNEE", "R_ANKLE", "L_ANKLE"]


class _AppearancePreview(QWidget):
    """QPainter preview of the skeleton overlay + a mini graph (no live apply)."""

    def __init__(self, values):
        super().__init__()
        self._v = dict(values)
        self.setMinimumSize(300, 320)

    def set_values(self, values):
        self._v = dict(values)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#15181B"))
        gap = 8
        sk_rect = QRectF(gap, gap, w - 2 * gap, h * 0.62 - gap)
        gr_rect = QRectF(gap, h * 0.62 + gap, w - 2 * gap, h * 0.38 - 2 * gap)
        self._paint_skeleton(p, sk_rect)
        self._paint_graph(p, gr_rect)
        p.end()

    def _pt(self, name, rect):
        x, y = _SK[name]
        return QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())

    def _paint_skeleton(self, p, rect):
        lw = float(self._v.get("line_width", 1.5))
        bone = QColor(self._v.get("overlay/bones", "#E8EEF2"))
        joint = QColor(self._v.get("overlay/joints", "#2FB8A8"))
        pelvis = QColor(self._v.get("overlay/pelvis", "#5BC0EB"))
        p.setPen(QPen(pelvis, max(1.4, lw)))
        for a, b in _SK_PELVIS:
            p.drawLine(self._pt(a, rect), self._pt(b, rect))
        p.setPen(QPen(bone, max(2.5, lw + 1.5), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for a, b in _SK_BONES:
            p.drawLine(self._pt(a, rect), self._pt(b, rect))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(joint))
        for nm in _SK_JOINTS:
            c = self._pt(nm, rect)
            p.drawEllipse(c, 4.0, 4.0)

    def _paint_graph(self, p, rect):
        import math
        lw = float(self._v.get("line_width", 1.5))
        p.fillRect(rect, QColor(style.GRAPH_BG))
        if self._v.get("grid_default", True):
            p.setPen(QPen(QColor(255, 255, 255, 26), 1))
            for i in range(1, 4):
                x = rect.x() + rect.width() * i / 4.0
                p.drawLine(QPointF(x, rect.y()), QPointF(x, rect.bottom()))
                y = rect.y() + rect.height() * i / 4.0
                p.drawLine(QPointF(rect.x(), y), QPointF(rect.right(), y))
        for key, phase in (("curve/cop", 0.0), ("curve/ap", 1.0), ("curve/ml", 2.0)):
            p.setPen(QPen(QColor(self._v.get(key, "#888888")), max(1.0, lw)))
            prev = None
            n = 60
            for i in range(n + 1):
                t = i / n
                x = rect.x() + t * rect.width()
                y = rect.center().y() - math.sin(t * 6.28 + phase) * rect.height() * 0.28
                cur = QPointF(x, y)
                if prev is not None:
                    p.drawLine(prev, cur)
                prev = cur


class AppearanceDialog(QDialog):
    """Edit graph/3D colours on a local copy with a live preview; commit on Apply."""

    _COLOR_SECTIONS = [
        ("3D overlay", [("overlay/bones", "Bones"), ("overlay/joints", "Joint centres"),
                        ("overlay/pelvis", "Pelvis")]),
        ("Graph curves", [("curve/cop", "COP"), ("curve/ap", "AP"), ("curve/ml", "ML"),
                          ("curve/raw", "Raw"), ("curve/fx", "Force X"),
                          ("curve/fy", "Force Y"), ("curve/fz", "Force Z")]),
        ("3D markers", [("marker/color", "Marker"), ("marker/highlight", "Highlight")]),
    ]

    def __init__(self, parent, appearance):
        super().__init__(parent)
        self.appearance = appearance
        self._pending = appearance.all()
        self._swatches = {}
        self.setWindowTitle("Appearance")
        self.setModal(True)
        self.resize(720, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        desc = QLabel("Pick colours; the preview updates live. Nothing changes in the "
                      "app until you press Apply.")
        desc.setWordWrap(True)
        desc.setStyleSheet(style.label_style(style.TEXT_SECONDARY, 12))
        root.addWidget(desc)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # left: scrollable controls
        ctrl = QWidget()
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)
        for title, rows in self._COLOR_SECTIONS:
            cl.addWidget(self._section_label(title))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(6)
            for r, (key, label) in enumerate(rows):
                grid.addWidget(self._mk_label(label), r, 0)
                grid.addWidget(self._color_swatch(key), r, 1)
            cl.addLayout(grid)
        # graph geometry
        cl.addWidget(self._section_label("Graph"))
        geo = QGridLayout()
        geo.setHorizontalSpacing(10)
        geo.setVerticalSpacing(6)
        geo.addWidget(self._mk_label("Grid (default)"), 0, 0)
        self._grid_cb = QCheckBox()
        self._grid_cb.setChecked(bool(self._pending.get("grid_default", True)))
        self._grid_cb.toggled.connect(self._on_grid)
        geo.addWidget(self._grid_cb, 0, 1)
        geo.addWidget(self._mk_label("Line width"), 1, 0)
        self._lw_spin = QDoubleSpinBox()
        self._lw_spin.setRange(0.5, 4.0)
        self._lw_spin.setSingleStep(0.5)
        self._lw_spin.setValue(float(self._pending.get("line_width", 1.5)))
        self._lw_spin.valueChanged.connect(self._on_lw)
        geo.addWidget(self._lw_spin, 1, 1)
        geo.addWidget(self._mk_label("3D marker size"), 2, 0)
        self._size_combo = QComboBox()
        self._size_combo.addItems(["S", "M", "L"])
        self._size_combo.setCurrentText(str(self._pending.get("marker/size", "M")))
        self._size_combo.currentTextChanged.connect(self._on_size)
        geo.addWidget(self._size_combo, 2, 1)
        cl.addLayout(geo)
        cl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(ctrl)
        body.addWidget(scroll, 1)

        self._preview = _AppearancePreview(self._pending)
        body.addWidget(self._preview, 1)

        # buttons
        btns = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        btns.addWidget(reset)
        btns.addStretch(1)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        btns.addWidget(bb)
        root.addLayout(btns)

    # ----- helpers -----
    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(style.label_style(style.TEXT_PRIMARY, 13, 600))
        return lbl

    def _mk_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(style.label_style(style.TEXT_PRIMARY, 12))
        return lbl

    def _color_swatch(self, key):
        btn = QPushButton()
        btn.setFixedSize(54, 22)
        self._swatches[key] = btn
        self._style_swatch(key)
        btn.clicked.connect(lambda _c=False, k=key: self._pick_color(k))
        return btn

    def _style_swatch(self, key):
        col = self._pending.get(key, DEFAULTS.get(key, "#000000"))
        self._swatches[key].setStyleSheet(
            f"background:{col}; border:1px solid {style.BORDER}; border-radius:4px;")

    def _pick_color(self, key):
        cur = QColor(self._pending.get(key, "#000000"))
        col = QColorDialog.getColor(cur, self, "Pick colour")
        if col.isValid():
            self._pending[key] = col.name()
            self._style_swatch(key)
            self._preview.set_values(self._pending)

    def _on_grid(self, checked):
        self._pending["grid_default"] = bool(checked)
        self._preview.set_values(self._pending)

    def _on_lw(self, value):
        self._pending["line_width"] = float(value)
        self._preview.set_values(self._pending)

    def _on_size(self, text):
        self._pending["marker/size"] = str(text)

    def _reset(self):
        self._pending = dict(DEFAULTS)
        for key in self._swatches:
            self._style_swatch(key)
        self._grid_cb.setChecked(bool(self._pending["grid_default"]))
        self._lw_spin.setValue(float(self._pending["line_width"]))
        self._size_combo.setCurrentText(str(self._pending["marker/size"]))
        self._preview.set_values(self._pending)

    def _apply(self):
        self.appearance.apply(self._pending)

    def _ok(self):
        self._apply()
        self.accept()
