"""Help dialogs reached from the Help menu (metric reference)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
    QFrame, QPushButton, QDialogButtonBox,
)
from PyQt6.QtCore import Qt

from ui import style as S

# Each metric folds AP/ML into one entry. Text is bilingual (en/kr); the math
# formula (rich-text) is shared. AP/ML are noted in the "axes" line.
METRIC_DOCS = [
    {
        "cat": {"en": "Position & Excursion", "kr": "위치 · 변위"},
        "metrics": [
            {
                "name": "RMS", "unit": "mm",
                "desc": {
                    "en": "Root-mean-square of COP displacement around its mean — the typical sway amplitude. Larger means more sway.",
                    "kr": "평균 위치를 기준으로 한 COP 변위의 제곱평균제곱근 — 전형적인 흔들림 크기. 클수록 흔들림이 큽니다.",
                },
                "axes": {
                    "en": "AP: anterior–posterior axis · ML: medial–lateral axis",
                    "kr": "AP: 전후(앞뒤) 축 · ML: 좌우 축",
                },
                "formula": "RMS = &radic;( (1/n) &Sigma; (x &minus; x&#772;)<sup>2</sup> )",
            },
            {
                "name": "Range", "unit": "mm",
                "desc": {
                    "en": "Peak-to-peak COP excursion (max − min) within the window. Sensitive to brief outliers.",
                    "kr": "구간 내 최대−최소 COP 변위(peak-to-peak). 순간적인 이상치에 민감합니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "Range = max(x) &minus; min(x)",
            },
            {
                "name": "Mean position", "unit": "mm",
                "desc": {
                    "en": "Average COP location in the window — describes posture / offset, not sway magnitude. Sign depends on the axis convention.",
                    "kr": "구간 내 평균 COP 위치 — 자세/오프셋을 나타내며 흔들림 크기는 아닙니다. 부호는 축 설정에 따라 달라집니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "x&#772; = (1/n) &Sigma; x",
            },
        ],
    },
    {
        "cat": {"en": "Spatial distribution", "kr": "공간 분포"},
        "metrics": [
            {
                "name": "95% Ellipse area", "unit": "mm²",
                "desc": {
                    "en": "Area of the 95% confidence ellipse fitted to the COP scatter — a compact 2-D measure of how widely the COP is distributed.",
                    "kr": "COP 산포에 맞춘 95% 신뢰 타원의 면적 — COP가 얼마나 넓게 분포하는지를 나타내는 2차원 지표.",
                },
                "axes": {
                    "en": "λ₁, λ₂ = eigenvalues of the AP–ML covariance · χ²(df=2, 0.95) ≈ 5.99",
                    "kr": "λ₁, λ₂ = AP–ML 공분산의 고유값 · χ²(df=2, 0.95) ≈ 5.99",
                },
                "formula": "A = &pi; &middot; &chi;<sup>2</sup><sub>0.95</sub> &middot; &radic;(&lambda;<sub>1</sub> &lambda;<sub>2</sub>)",
            },
        ],
    },
    {
        "cat": {"en": "Path & Velocity", "kr": "경로 · 속도"},
        "metrics": [
            {
                "name": "Sway path length", "unit": "mm",
                "desc": {
                    "en": "Total distance the COP traveled along its trajectory — accounts for the whole path, not just min-to-max.",
                    "kr": "COP가 궤적을 따라 이동한 총 거리 — 최소-최대 거리가 아닌 전체 경로를 반영합니다.",
                },
                "axes": {"en": "", "kr": ""},
                "formula": "L = &Sigma; &radic;( &Delta;AP<sup>2</sup> + &Delta;ML<sup>2</sup> )",
            },
            {
                "name": "Mean velocity", "unit": "mm/s",
                "desc": {
                    "en": "Average COP speed (path length ÷ duration). Can be high even when the range is small, if the COP moves frequently.",
                    "kr": "평균 COP 속도(경로 길이 ÷ 시간). 범위가 작아도 COP가 자주 움직이면 커질 수 있습니다.",
                },
                "axes": {"en": "T = (n − 1) / fs", "kr": "T = (n − 1) / fs (분석 구간 길이)"},
                "formula": "v = L / T",
            },
        ],
    },
    {
        "cat": {"en": "Frequency", "kr": "주파수"},
        "metrics": [
            {
                "name": "Mean power frequency", "unit": "Hz",
                "desc": {
                    "en": "Power-weighted average sway frequency from the COP power spectrum. Higher means more sway power at higher frequencies.",
                    "kr": "COP 파워 스펙트럼의 파워 가중 평균 주파수. 클수록 고주파 흔들림 성분이 많습니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "f&#772; = &Sigma;( f &middot; P(f) ) / &Sigma; P(f)",
            },
            {
                "name": "Median frequency", "unit": "Hz",
                "desc": {
                    "en": "Frequency that splits the spectral power in half: 50% of the power lies below it and 50% above.",
                    "kr": "스펙트럼 파워를 절반으로 나누는 주파수 — 50%는 아래, 50%는 위에 있습니다.",
                },
                "axes": {"en": "Computed per axis (AP, ML)", "kr": "AP, ML 축별로 계산"},
                "formula": "&Sigma;<sub>f &le; f<sub>med</sub></sub> P  =  &frac12; &Sigma; P",
            },
        ],
    },
]

_TEXT = {
    "title": {"en": "COP Metrics Reference", "kr": "COP 지표 설명서"},
    "unit": {"en": "Unit", "kr": "단위"},
}

# Short hover descriptions for the sidebar metric checkboxes (per METRIC_KEYS).
METRIC_TOOLTIPS = {
    "RMS AP": "Typical AP sway amplitude (RMS around the mean).",
    "RMS ML": "Typical ML sway amplitude (RMS around the mean).",
    "Range AP": "Peak-to-peak AP excursion (max − min).",
    "Range ML": "Peak-to-peak ML excursion (max − min).",
    "Mean AP": "Average AP COP position (offset, not sway magnitude).",
    "Mean ML": "Average ML COP position (offset, not sway magnitude).",
    "95% Ellipse area": "Area of the 95% COP confidence ellipse (sway dispersion).",
    "Sway path length": "Total distance the COP traveled along its path.",
    "Mean velocity": "Average COP speed (path length ÷ duration).",
    "Mean power freq AP": "Power-weighted mean AP sway frequency.",
    "Mean power freq ML": "Power-weighted mean ML sway frequency.",
    "Median freq AP": "AP frequency splitting spectral power 50/50.",
    "Median freq ML": "ML frequency splitting spectral power 50/50.",
}


class _Collapsible(QWidget):
    """A disclosure-triangle section: click the header to show/hide its body."""

    def __init__(self, title, header_style, indent=0):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        self._title = title
        self.header = QPushButton("▸  " + title)
        self.header.setCheckable(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setStyleSheet(
            "QPushButton { background: transparent; border: none; text-align: left;"
            f"padding: 3px 2px; {header_style} }}"
            "QPushButton:hover { color: " + S.ACCENT_TEAL + "; }"
        )
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(indent, 2, 0, 4)
        self.body_layout.setSpacing(3)
        self.body.setVisible(False)
        self.header.toggled.connect(self._on_toggle)
        v.addWidget(self.header)
        v.addWidget(self.body)

    def _on_toggle(self, checked):
        self.body.setVisible(checked)
        self.header.setText(("▾  " if checked else "▸  ") + self._title)

    def add(self, widget):
        self.body_layout.addWidget(widget)


class MetricsHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metrics Reference")
        self.setModal(False)
        self.resize(500, 600)
        self._lang = "en"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:16px;font-weight:700;")
        head.addWidget(self._title_lbl)
        head.addStretch()
        self._lang_btn = QPushButton()
        self._lang_btn.setObjectName("toggle-btn")
        self._lang_btn.setFixedHeight(22)
        self._lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lang_btn.clicked.connect(self._toggle_lang)
        head.addWidget(self._lang_btn)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        scroll.setWidget(self._inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._populate()

    def _toggle_lang(self):
        self._lang = "kr" if self._lang == "en" else "en"
        self._populate()

    def _populate(self):
        lang = self._lang
        self._title_lbl.setText(_TEXT["title"][lang])
        self._lang_btn.setText("KOR" if lang == "en" else "EN")

        while self._col.count():
            item = self._col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cat_style = f"color:{S.TEXT_PRIMARY};font-size:13px;font-weight:700;"
        metric_style = f"color:{S.TEXT_SECONDARY};font-size:12px;font-weight:600;"
        for entry in METRIC_DOCS:
            cat = _Collapsible(entry["cat"][lang], cat_style, indent=10)
            for m in entry["metrics"]:
                metric = _Collapsible(m["name"], metric_style, indent=14)
                metric.add(self._content(m, lang))
                cat.add(metric)
            self._col.addWidget(cat)
        self._col.addStretch(1)

    def _content(self, m, lang):
        # Single outer border, no inner boxes (object-name scoped so the border
        # does not cascade onto the child labels).
        card = QFrame()
        card.setObjectName("help-card")
        card.setStyleSheet(
            f"QFrame#help-card {{ background:{S.BG_PANEL}; border:1px solid {S.BORDER};"
            " border-radius:6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        unit_lbl = QLabel(f"{_TEXT['unit'][lang]}: {m['unit']}")
        unit_lbl.setStyleSheet(f"color:{S.ACCENT_TEAL};font-size:11px;font-weight:600;border:none;")
        lay.addWidget(unit_lbl)

        # One sentence per line for readability.
        desc = m["desc"][lang].replace(". ", ".\n")
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{S.TEXT_PRIMARY};font-size:12px;border:none;line-height:150%;")
        lay.addWidget(desc_lbl)

        axes = m["axes"][lang]
        if axes:
            axes_lbl = QLabel(axes)
            axes_lbl.setWordWrap(True)
            axes_lbl.setStyleSheet(f"color:{S.TEXT_SECONDARY};font-size:11px;border:none;")
            lay.addWidget(axes_lbl)

        formula_lbl = QLabel(m["formula"])
        formula_lbl.setTextFormat(Qt.TextFormat.RichText)
        formula_lbl.setWordWrap(True)
        formula_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        formula_lbl.setStyleSheet(
            f"color:{S.TEXT_PRIMARY};font-size:16px;font-style:italic;border:none;"
            "background:transparent;padding:4px 0 0 0;"
            "font-family:'Cambria Math','Cambria','Times New Roman',serif;"
        )
        lay.addWidget(formula_lbl)
        return card
