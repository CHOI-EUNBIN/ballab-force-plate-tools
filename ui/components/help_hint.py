"""A tiny grey circular "?" hint marker — the app's offline, free alternative
to an LLM helper.

The hint now lives at the **section** level, not on every field: a single
muted "?" circle rides beside a section header (a GroupBox title or a bold
label). Clicking it pops a small framed bubble that explains the whole section
in one paragraph (what it does + the main choices/examples). Click outside or
press Esc to dismiss. This keeps the form clean (one "?" per section) instead
of peppering a "?" on every label.

Public helpers
--------------
* :class:`HelpHint` — the round "?" badge. Click -> popup (no longer a tooltip).
* :class:`SectionHintPopup` — the small framed bubble the badge shows.
* :func:`section_header_with_hint` — ``[bold QLabel][HelpHint]`` row for a
  section header that is a plain (non-GroupBox) bold label.
* :func:`attach_group_hint` — float a :class:`HelpHint` at the top-right of a
  ``QGroupBox`` title bar (used by the step dialogs' ``_FormGroup``).
* :func:`label_with_hint` — kept for back-compat (a few call-sites / tests) but
  no longer the recommended per-field pattern.

The hint *strings* live in :data:`SECTION_HINTS` (section-level paragraphs) and
the older per-field :data:`HINTS`. Op/metric definitions are NOT copied here —
they are reused live from ``ui.help_dialog`` via :func:`op_hint` /
:func:`metric_hint` so they cannot drift.
"""

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QLabel, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QGroupBox,
)


def _title_hint_pos(group_box, hint):
    """(x, y) to park ``hint`` right after a ``model-group`` box's TITLE text.

    Anchored to the heading (left side), NOT the right corner, so the mark reads
    as part of the section title and never crowds the content rows below or jams
    into a corner. Title width is measured with the QSS title font (12px bold)."""
    f = QFont(group_box.font())
    f.setBold(True)
    f.setPixelSize(12)
    title_w = QFontMetrics(f).horizontalAdvance(group_box.title() or "")
    # QSS '::title { left: 10px }' + measured title width + a small gap.
    return (10 + title_w + 8, 1)

from ui import style


class SectionHintPopup(QFrame):
    """A small framed bubble that shows one section's help paragraph.

    Uses the ``Qt.Popup`` window flag so Qt auto-grabs input: clicking anywhere
    outside the bubble (or pressing Esc) closes it, exactly like a context menu.
    Width-capped + word-wrapped + padded, themed from ``style.py`` tokens."""

    _MAX_WIDTH = 260

    def __init__(self, text, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("help-popup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(0)
        self._label = QLabel(self._render_html(text))
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setObjectName("help-popup-text")
        self._label.setMaximumWidth(self._MAX_WIDTH)
        lay.addWidget(self._label)
        self.setMaximumWidth(self._MAX_WIDTH + 22)
        self.setStyleSheet(
            f"""
            QFrame#help-popup {{
                background: {style.BG_PANEL};
                border: 1px solid {style.BORDER};
                border-radius: {style.BORDER_RADIUS_MD};
            }}
            QLabel#help-popup-text {{
                color: {style.TEXT_SECONDARY};
                font-size: {style.FONT_SIZE_SMALL};
                background: transparent;
            }}
            """
        )

    @staticmethod
    def _render_html(text):
        """Render a section hint as spaced rich text: a bold first line (the
        summary), then each following line as its own block with a little gap so
        the bullets are easy to read instead of cramped line-to-line."""
        import html as _html
        lines = [ln for ln in (text or "").split("\n")]
        if not lines or not any(ln.strip() for ln in lines):
            return ""
        head, body = lines[0], lines[1:]
        parts = [f"<div style='margin-bottom:6px'><b>{_html.escape(head)}</b></div>"]
        for ln in body:
            if ln.strip():
                parts.append(
                    f"<div style='margin-bottom:4px; line-height:135%'>"
                    f"{_html.escape(ln)}</div>"
                )
        return "".join(parts)

    def keyPressEvent(self, event):
        # Esc closes the bubble (Qt.Popup already closes on outside-click).
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def show_near(self, anchor):
        """Pop just below-right of the ``anchor`` widget (the "?" badge),
        nudged left if it would run off the right screen edge."""
        self.adjustSize()
        if anchor is not None:
            global_pt = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
            screen = anchor.screen()
            if screen is not None:
                avail = screen.availableGeometry()
                x = min(global_pt.x(), avail.right() - self.width() - 4)
                x = max(avail.left() + 4, x)
                y = global_pt.y()
                if y + self.height() > avail.bottom():
                    # No room below — flip above the badge.
                    y = anchor.mapToGlobal(QPoint(0, -self.height() - 4)).y()
                global_pt = QPoint(x, y)
            self.move(global_pt)
        self.show()


class HelpHint(QLabel):
    """A small grey circular "?" badge. **Click** pops a section-help bubble.

    A true circle: a fixed square (~16 px) with ``border-radius = size / 2``,
    a muted grey ring + grey "?" glyph, brightening one tone on hover. QLabel
    based; the click is handled in :meth:`mouseReleaseEvent` (no QPushButton
    chrome). ``text`` is the section paragraph the bubble will show."""

    _DIAMETER = 14

    def __init__(self, text="", parent=None):
        super().__init__("?", parent)
        self.setObjectName("help-hint")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(self._DIAMETER, self._DIAMETER)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hint_text = ""
        self._popup = None
        self.setHintText(text)
        self._apply_style()

    def setHintText(self, text):
        """Set/replace the help paragraph this badge pops on click. Also mirrored
        to the tooltip as a tiny affordance ("click for help")."""
        self._hint_text = text or ""
        self.setToolTip("Click for help" if self._hint_text else "")

    def hintText(self):
        """Return the current help paragraph."""
        return self._hint_text

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._hint_text:
            self._show_popup()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _show_popup(self):
        # One live popup at a time; rebuild so text edits are reflected.
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
        self._popup = SectionHintPopup(self._hint_text, self)
        self._popup.show_near(self)

    def _apply_style(self):
        # Borderless — just a faint "?" glyph (NO ring), sitting inside the group
        # box. Brightens one tone on hover. (Was a ringed circle; the user wanted
        # the ring gone and the mark pulled inside the frame.)
        self.setStyleSheet(
            f"""
            QLabel#help-hint {{
                color: {style.TEXT_MUTED};
                border: none;
                background: transparent;
                font-size: {style.FONT_SIZE_SMALL};
                font-weight: {style.FONT_WEIGHT_BOLD};
                padding: 0px;
            }}
            QLabel#help-hint:hover {{
                color: {style.TEXT_SECONDARY};
            }}
            """
        )


def section_header_with_hint(title, hint_text, bold=True):
    """Return a ``[QLabel(title)] [HelpHint]`` row for a section header that is a
    plain bold label (not a GroupBox). The label keeps the app's section-header
    look; the "?" trails it with a small gap. The returned widget exposes
    ``.label`` and ``.hint`` for callers that want to tweak them."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    lbl = QLabel(title)
    if bold:
        lbl.setObjectName("section-header")
        font = lbl.font()
        font.setBold(True)
        lbl.setFont(font)
    row.addWidget(lbl)
    hh = HelpHint(hint_text)
    row.addWidget(hh)
    row.addStretch()
    holder.label = lbl
    holder.hint = hh
    return holder


class HintGroupBox(QGroupBox):
    """A ``QGroupBox`` that floats a :class:`HelpHint` at the top-right of its
    title bar. The badge is a child of the box (so it scrolls/moves with it) and
    is repositioned on resize — it does NOT live in the form layout, so the
    grouped rows are untouched (layout stays exactly as before)."""

    def __init__(self, title, hint_text="", parent=None):
        super().__init__(title, parent)
        self._hint = HelpHint(hint_text, self) if hint_text else None
        if self._hint is not None:
            self._hint.show()
            self._position_hint()

    def setHintText(self, text):
        if text and self._hint is None:
            self._hint = HelpHint(text, self)
            self._hint.show()
        elif self._hint is not None:
            self._hint.setHintText(text or "")
        self._position_hint()

    def _position_hint(self):
        if self._hint is None:
            return
        # Right after the title text (heading affix) — see _title_hint_pos.
        x, y = _title_hint_pos(self, self._hint)
        self._hint.move(x, y)
        self._hint.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_hint()


def attach_group_hint(group_box, hint_text):
    """Float a :class:`HelpHint` at the top-right of an existing ``QGroupBox``
    title bar. Returns the badge. Use when the box is already a plain QGroupBox
    (e.g. the step dialogs' ``_FormGroup.box``); the badge reparents to the box
    and tracks its size."""
    if not hint_text:
        return None
    hh = HelpHint(hint_text, group_box)

    def _place():
        # Right after the title text (heading affix) — see _title_hint_pos.
        x, y = _title_hint_pos(group_box, hh)
        hh.move(x, y)
        hh.raise_()

    # Reposition whenever the box resizes (wrap its resizeEvent once).
    orig_resize = group_box.resizeEvent

    def _resize(event):
        orig_resize(event)
        _place()

    group_box.resizeEvent = _resize  # type: ignore[assignment]
    hh.show()
    _place()
    return hh


def label_with_hint(text_label, hint_text):
    """Back-compat: ``[QLabel(text_label)] [HelpHint(hint_text)]`` for a form's
    label column. Retained for the handful of call-sites/tests that still use a
    per-field hint; prefer :func:`section_header_with_hint` /
    :func:`attach_group_hint` for new code."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    lbl = QLabel(text_label)
    row.addWidget(lbl)
    row.addWidget(HelpHint(hint_text))
    row.addStretch()
    holder.label = lbl
    holder.hint_text = hint_text
    return holder


# ---------------------------------------------------------------------------
# Live re-use of existing help copy (no duplication / drift)
# ---------------------------------------------------------------------------
def op_hint(op_key):
    """One-line hover text for a metric *operation* key, reused verbatim from
    ``ui.help_dialog.OP_TOOLTIPS`` so the two surfaces never diverge. Empty
    string if the op has no entry."""
    from ui.help_dialog import OP_TOOLTIPS
    return OP_TOOLTIPS.get(op_key, "")


def metric_hint(metric_name):
    """One-line hover text for a COP metric name, reused from
    ``ui.help_dialog.METRIC_TOOLTIPS``. Empty string if absent."""
    from ui.help_dialog import METRIC_TOOLTIPS
    return METRIC_TOOLTIPS.get(metric_name, "")


# ---------------------------------------------------------------------------
# Section-level hint copy — ONE paragraph per section, merged from the old
# per-field hints (what the section does + main choices/examples). Keyed by
# "<Dialog>.<section>".
# ---------------------------------------------------------------------------
SECTION_HINTS = {
    # ---- ComputeStepDialog --------------------------------------------------
    "Compute.Calculation": (
        "How to turn the signal into a new variable.\n"
        "• Normalize — divide by a constant or metric (e.g. ÷ 700 N body weight → %BW)\n"
        "• Derivative — differentiate (position → velocity → acceleration; Order sets how many times)\n"
        "• Integral — integrate (force → impulse; choose sign and cumulative/total)\n"
        "• Magnitude — resultant of several axes, √(x² + y² + z²)\n"
        "• Absolute — absolute value (drop the sign)\n"
        "The fields below adapt to the calculation you pick."
    ),
    # ---- DetectEventStepDialog ---------------------------------------------
    "Detect.Detection": (
        "Where and how to find an event (a specific instant).\n"
        "• Signal — the signal to search (e.g. vertical force Fz)\n"
        "• Fixed frame — pick a frame directly\n"
        "• Threshold — the moment the signal crosses a level (e.g. 20 N = contact; Rising / Falling = going up / down)\n"
        "• Peak / valley — local maxima / minima. ‘Min peak height’ is prominence "
        "(how much a peak stands out from its surroundings), not absolute height; raise it to ignore small ripples\n"
        "• Zero crossing — the moment the value passes through 0."
    ),
    "Detect.Noise guard": (
        "Prevents over-detection caused by noise.\n"
        "• Min spacing — minimum gap between events (frames); drops duplicates that sit too close together\n"
        "• Re-trigger guard (hysteresis) — a margin that stops repeated triggers from jitter near the threshold; "
        "raise it for noisy signals. Set both to 0 to disable."
    ),
    "Detect.Search window": (
        "WHERE to search for the event — set this before picking instances.\n"
        "• Off = search the whole trial\n"
        "• ‘Limit to a time window’ = search only inside a frame range (Search from / to, in frames)."
    ),
    "Detect.Instance": (
        "WHICH of the detected occurrences to keep — these are ordinals (1st, 2nd…), NOT frames/time.\n"
        "• All = every occurrence found in the search window\n"
        "• (n)th = a single one (Instance #; negative counts from the end, -1 = last)\n"
        "• (n)th – (n)th = a range, From # to To #."
    ),
    # ---- MetricStepDialog ---------------------------------------------------
    "Metric.Input": (
        "What to measure.\n"
        "• Measure — the broad category (signal statistic / time between events / metric-on-metric, etc.)\n"
        "• Depending on the category, a single signal, an event pair, or a reference to an existing metric appears below."
    ),
    "Metric.Window": (
        "Over what range the value is computed.\n"
        "• Whole trial — one value across the whole trial\n"
        "• Per cycle — repeated for each event pair (e.g. contact → next contact)\n"
        "• At a single event — the value at one instant (e.g. knee angle at contact)."
    ),
    "Metric.Calculation": (
        "Pick the calculation for the chosen signal (hover an item for its definition). "
        "e.g. angle → ROM / peak, force → impulse / RFD. The name is shown as-is on the result card."
    ),
    # ---- FilterStepDialog ---------------------------------------------------
    "Filter.Filter": (
        "Smooths high-frequency noise (jitter) out of the signal.\n"
        "• Type — filter type (Low-pass is the most common)\n"
        "• Cutoff — cutoff frequency (Hz); wobble faster than this is removed, lower = smoother (e.g. gait 6–10 Hz)\n"
        "• Order — filter order; higher cuts more sharply (typically 2–4)."
    ),
    # ---- TrajectoryStepDialog -----------------------------------------------
    "Trajectory.Signals": (
        "Builds the path the COP (centre of pressure) traced on the floor — the base signal for balance / sway analysis.\n"
        "• AP — anterior–posterior (front–back) signal\n"
        "• ML — medial–lateral (side–side) signal."
    ),
}


def section_hint(key):
    """Look up a section-level hint paragraph by ``"<Dialog>.<section>"``; empty
    if missing."""
    return SECTION_HINTS.get(key, "")


# ---------------------------------------------------------------------------
# Legacy per-field hint copy — kept for back-compat (``hint(...)`` callers /
# tests). New code should use SECTION_HINTS via :func:`section_hint`.
# ---------------------------------------------------------------------------
HINTS = {
    "Filter.type": "Filter type. Low-pass (removes high-frequency jitter) is the most common.",
    "Filter.cutoff": (
        "Cutoff frequency (Hz). Wobble faster than this is removed; "
        "lower = smoother. e.g. gait 6–10 Hz."
    ),
    "Filter.order": "Filter order. Higher cuts more sharply. Typically 2–4.",
}


def hint(key):
    """Look up a legacy per-field hint string by key; empty if missing."""
    return HINTS.get(key, "")
