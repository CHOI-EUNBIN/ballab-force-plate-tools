"""Dialogs used by the Analyze tab.

These were split out of ``ui/analyze_tab.py`` to keep that module smaller. The
dialogs are largely self-contained: they take the AnalyzeTab as ``parent`` and
call a couple of its helper methods (``_event_channel_options`` / ``_range_label``)
plus core metric constants, but they do not depend on the tab's internal state.
"""

import os

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QCheckBox,
    QScrollArea, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem,
    QMessageBox, QLineEdit, QComboBox,
    QDoubleSpinBox, QColorDialog, QDialog, QDialogButtonBox, QFormLayout,
    QSpinBox, QGroupBox, QFileDialog, QLayout,
)
from PyQt6.QtCore import Qt

from PyQt6.QtWidgets import QStackedWidget  # noqa: F401 (used in AddStepDialog)
from core.signal_proc import FILTER_TYPES
from core.signals import FILT_SUFFIX, unit_for
from ui.style import BORDER, TEXT_MUTED
from ui.components.wheel_guard import install_wheel_guard
from ui.components.cascading_signal_picker import CascadingSignalPicker
from ui.components.help_hint import attach_group_hint, section_hint


def _signal_group_of(key):
    """Category header a signal key belongs under in the pickers — mirrors the
    RESULTS▸Signals grouping so the combo reads the same way: per force plate,
    joint angles, markers, COP path, else a derived/compute output."""
    base = key[: -len(FILT_SUFFIX)] if key.endswith(FILT_SUFFIX) else key
    if base.startswith("angle:"):
        return "Joint angles"
    if base.startswith("marker:"):
        return "Markers"
    if base.startswith("trajectory:"):
        return "COP trajectory"
    if base.startswith("fp"):
        num = base.split(":", 1)[0][2:]
        if num.isdigit():
            return f"Force Plate {num}"
    if base in ("cop", "cop_ap", "cop_ml", "fz", "fx", "fy"):
        return "Force Plate 1"
    return "Derived signals"


def _fill_signal_combo(combo, items, current_key=None):
    """Fill a signal-picker combo GROUPED by category (Force Plate 1/2, Joint
    angles, Markers, Derived…) under non-selectable header rows — not one long flat
    list. ``items`` = ``[(key, label), ...]`` from ``signal_catalog`` (already
    plate-labelled). Within a "Force Plate N" group the redundant "FPn " prefix is
    stripped (the header already names the plate); a filtered twin keeps its
    "(filtered)" tag. Selectable rows carry their ``key`` as ``itemData`` and are
    indented; group order follows first appearance in ``items``.

    Returns the model index to make current (-1 if ``current_key`` absent)."""
    import re
    from PyQt6.QtGui import QStandardItem

    groups = {}
    order = []
    for key, label in items:
        g = _signal_group_of(key)
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append((key, label))

    def _add_header(text):
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # non-selectable separator row
        combo.model().appendRow(item)

    combo.clear()
    current_index = -1
    first_real = -1
    for g in order:
        _add_header(f"— {g} —")
        plate_group = g.startswith("Force Plate ")
        for key, label in groups[g]:
            short = re.sub(r"^FP\d+\s+", "", label) if plate_group else label
            combo.addItem(f"  {short}", key)
            if first_real < 0:
                first_real = combo.count() - 1
            if key == current_key:
                current_index = combo.count() - 1
    # Never leave a non-selectable header as the active row.
    return current_index if current_index >= 0 else first_real


def _pair_row(label_a, widget_a, label_b, widget_b, spacing=8):
    """Lay two ``label + widget`` pairs side-by-side on ONE row.

    Used to compact the step dialogs: paired/range fields (Search from / to,
    Instance From # / To #, From event / To event …) that used to stack as two
    full-height form rows now sit on a single line, halving that block's height.

    Returns a plain ``QWidget`` (with a tight QHBoxLayout) you drop into a form
    as a full-width row via ``_FormGroup.addWidget``. The four passed widgets stay
    independent objects, so the existing per-widget show/hide logic
    (``_set_row_visible``) keeps working on the labels/inputs unchanged."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(label_a)
    row.addWidget(widget_a, 1)
    row.addSpacing(spacing)
    row.addWidget(label_b)
    row.addWidget(widget_b, 1)
    return holder


class _FormGroup:
    """A titled QGroupBox + its QFormLayout, addRow-forwarding.

    Reuses the existing ``model-group`` QSS (rounded border + title) so grouped
    dialogs look like the rest of the app. Expose ``.box`` (the QGroupBox to add
    to a layout) and ``.addRow(...)`` (forwards to the inner form). Shared by the
    Filter and Detect-Event step dialogs so both read at the same visual grade.

    Pass ``hint_key`` (a ``"<Dialog>.<section>"`` key into ``SECTION_HINTS``) to
    float a single "?" badge at the top-right of the title bar; clicking it pops
    a bubble that explains the whole section. The badge is a child of the box
    (not in the form layout), so the rows are untouched.

    Spacing is kept TIGHT (small vertical/horizontal gaps + slim content margins)
    so a multi-section dialog stays compact rather than spreading out vertically.
    The badge is a child of the box (not in the form layout), so the rows are
    untouched."""

    def __init__(self, title, hint_key=None):
        self.box = QGroupBox(title)
        self.box.setObjectName("model-group")
        self.form = QFormLayout(self.box)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        # Tighter than the Qt defaults: small gaps between rows / label↔field so
        # stacked sections do not balloon the dialog height.
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(5)
        self.form.setContentsMargins(2, 2, 2, 2)
        self.hint = None
        if hint_key:
            self.hint = attach_group_hint(self.box, section_hint(hint_key))

    def addRow(self, *args):
        self.form.addRow(*args)

    def addWidget(self, widget):
        """Add a full-width widget row (no label column)."""
        self.form.addRow(widget)

    def addPairRow(self, label_a, widget_a, label_b, widget_b):
        """Add two ``label + widget`` pairs on a single full-width row (see
        :func:`_pair_row`). Returns the row holder so the caller can show/hide it."""
        holder = _pair_row(label_a, widget_a, label_b, widget_b)
        self.form.addRow(holder)
        return holder


class FilterStepDialog(QDialog):
    """Edit one pipeline FilterStep: its FilterSpec (type/cutoff/order) plus the
    set of signals it low-passes (scalar targets + an "also markers" flag).

    ``targets`` is offered as a checkable list of the available raw scalar signal
    keys (COP/force/joint angles) for the current dataset, sourced from the
    parent tab's ``_filterable_targets`` so the dialog stays dumb. Selecting a
    target makes the step produce a "(filtered)" twin of that signal."""

    def __init__(self, parent, targets, spec=None, selected=None, markers=False):
        super().__init__(parent)
        self.setWindowTitle("Edit Filter Step" if spec else "Add Filter Step")
        self.setModal(True)
        self.setMinimumWidth(340)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 12, 14, 12)
        vb.setSpacing(8)

        # ---- group 1: Filter (type / cutoff / order) -----------------------
        # Promoted from a flat QFormLayout to the same grouped (QGroupBox)
        # presentation as DetectEventStepDialog, so both step editors read at the
        # same grade.
        self.type_combo = QComboBox()
        self.type_combo.addItems(FILTER_TYPES)
        if spec is not None and spec.type in FILTER_TYPES:
            self.type_combo.setCurrentText(spec.type)

        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.5, 100.0)
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.5)
        self.cutoff_spin.setSuffix(" Hz")
        self.cutoff_spin.setValue(float(spec.cutoff_hz) if spec else 10.0)

        self.order_spin = QSpinBox()
        self.order_spin.setRange(1, 8)
        self.order_spin.setValue(int(spec.order) if spec else 4)
        # Cutoff + Order are both small numeric inputs -> cap their width so they
        # share a single row instead of stacking.
        self.cutoff_spin.setMaximumWidth(110)
        self.order_spin.setMaximumWidth(70)

        filt = _FormGroup("Filter", hint_key="Filter.Filter")
        filt.addRow("Type", self.type_combo)
        # "Cutoff [ Hz]   Order [ ]" on one row.
        filt.addPairRow(QLabel("Cutoff"), self.cutoff_spin,
                       QLabel("Order"), self.order_spin)
        vb.addWidget(filt.box)

        # ---- group 2: Signals to filter -----------------------------------
        # A checkable TREE grouped by Force Plate / Joint angles, plus a top-level
        # "Markers (3D)" leaf. Group rows are auto-tristate: checking a group toggles
        # all its signals (partial selection shows a dash). Groups start collapsed —
        # the common case is "filter a whole plate / all markers" in one click; the
        # user expands only to fine-tune individual axes.
        sel = set(selected or ())
        signals = _FormGroup("Signals to filter")

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("marker-list")
        self.tree.setRootIsDecorated(True)
        # Height tracks the visible rows (no fixed 190 px box that left a big
        # empty area above the content). Recomputed whenever a group expands.
        self.tree.expanded.connect(self._fit_tree_height)
        self.tree.collapsed.connect(self._fit_tree_height)

        flag_check = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled

        # Markers (3D) — one leaf at the top (was a separate checkbox).
        self.marker_item = QTreeWidgetItem(self.tree, ["Markers (3D)"])
        self.marker_item.setFlags(flag_check)
        self.marker_item.setCheckState(
            0, Qt.CheckState.Checked if markers else Qt.CheckState.Unchecked)

        # Group the scalar targets (preserving the catalog order they arrive in).
        self.target_items = {}
        groups = {}
        order = []
        for key, label in targets:
            g = self._group_of(key)
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append((key, label))
        for g in order:
            parent = QTreeWidgetItem(self.tree, [g])
            # Auto-tristate: Qt keeps the parent's check in sync with its children
            # and toggles all children when the parent is clicked.
            parent.setFlags(flag_check | Qt.ItemFlag.ItemIsAutoTristate)
            any_checked = False
            for key, label in groups[g]:
                child = QTreeWidgetItem(parent, [self._child_label(label)])
                child.setFlags(flag_check)
                checked = key in sel
                child.setCheckState(
                    0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                self.target_items[key] = child
                any_checked = any_checked or checked
            # Expand a group only if it already has a selected signal (editing an
            # existing step); otherwise keep it tidy and collapsed.
            parent.setExpanded(any_checked)
        signals.addWidget(self.tree)
        vb.addWidget(signals.box)
        self._fit_tree_height()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        install_wheel_guard(self)

    def _fit_tree_height(self, *_):
        """Size the "Signals to filter" tree to its currently-visible rows (group
        headers + the children of expanded groups), capped so a fully-expanded set
        scrolls instead of making the dialog huge. Replaces the fixed 190 px box
        that left a large empty area above the (mostly collapsed) groups."""
        rows = self.tree.topLevelItemCount()   # Markers leaf + each group header
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.isExpanded():
                rows += top.childCount()
        row_h = max(20, self.tree.sizeHintForRow(0) if rows else 22)
        h = min(rows, 11) * row_h + 6
        self.tree.setFixedHeight(max(row_h + 6, h))
        if self.isWindow():
            lay = self.layout()
            if lay is not None:
                lay.activate()
            self.adjustSize()

    @staticmethod
    def _group_of(key):
        """Sidebar group for a filter target key (mirrors the RESULTS grouping)."""
        if key.startswith("angle:"):
            return "Joint angles"
        if key.startswith("fp"):
            num = key.split(":", 1)[0][2:]
            if num.isdigit():
                return f"Force Plate {num}"
        if key in ("cop", "cop_ap", "cop_ml", "fz", "fx", "fy"):
            return "Force Plate 1"
        return "Other"

    @staticmethod
    def _child_label(label):
        """Strip a leading "FP<n> " prefix — the group header already names the
        plate, so the child row reads just "COP" / "Fz" under it."""
        import re
        return re.sub(r"^FP\d+\s+", "", label)

    def values(self):
        """Return ``(spec_dict, targets_list, markers_bool)``."""
        spec_dict = {
            "type": self.type_combo.currentText(),
            "cutoff_hz": float(self.cutoff_spin.value()),
            "order": int(self.order_spin.value()),
        }
        targets = [key for key, item in self.target_items.items()
                   if item.checkState(0) == Qt.CheckState.Checked]
        markers = self.marker_item.checkState(0) == Qt.CheckState.Checked
        return spec_dict, targets, markers


class DetectEventStepDialog(QDialog):
    """Edit one pipeline DetectEventStep: a *repeated* auto-detection recipe.

    Parallel to :class:`FilterStepDialog`. Where the (manual) :class:`EventDialog`
    pins a single frame on a file via a level/operator rule, this describes a
    detector that runs on a chosen catalog signal and can mark *many* instances
    (e.g. every heel-strike). The math lives in ``core.events`` — this dialog only
    gathers ``{input, label, method, params, selector, scope}`` and hands it back
    via :meth:`values`.

    ``inputs`` is ``[(key, label), ...]`` of selectable catalog signals (raw +
    processed "(filtered)" + joint angles), sourced from the parent tab so the
    dialog stays dumb. ``frame_max`` bounds the optional search-window spins.

    The unified event dialog (2026-06-23): this single dialog replaces the old
    ``EventDialog`` too. ``method="frame"`` is the manual "Fixed frame" pin — when
    chosen, only a Name + Frame-number field show (Signal/threshold/selector/scope
    are hidden) and ``values()`` returns ``params={"frame": <0-based>}``. A Color
    button is kept (the old EventDialog had one) so the user can still pick the
    line colour; it is returned by ``values()`` as its own value (the
    DetectEventStep.color field), kept out of ``params`` so recolouring never
    invalidates the detection cache."""

    METHODS = [("Fixed frame", "frame"),
               ("Threshold crossing", "threshold"),
               ("Peak / valley", "peak"),
               ("Zero crossing", "zero"),
               ("Global maximum", "global_maximum"),
               ("Global minimum", "global_minimum")]

    def __init__(self, parent, inputs, frame_max=0, step=None, color=None,
                 event_labels=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Event" if step else "Add Event")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._frame_max = max(0, int(frame_max))
        # Labels of OTHER detect steps defined earlier in the pipeline — offered
        # as the "Event" search-window bound type. Empty -> the Event type has no
        # selectable labels (the user just uses Frame bounds).
        self._event_labels = list(event_labels or [])

        p = dict(step.params) if step is not None else {}
        # Colour: the step's own ``color`` field (params["color"] for very old
        # steps loaded before the field existed), else the caller default.
        step_color = getattr(step, "color", None) if step is not None else None
        self.event_color = step_color or p.get("color") or color or "#F97316"

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 12, 14, 12)
        vb.setSpacing(8)

        # ---- widgets (built first, placed into groups afterwards) ----------
        # --- input signal + label ---
        # Grouped RAW / PROCESSED so the user sees raw vs filtered signals.
        self.input_combo = CascadingSignalPicker(keys=inputs)
        current = step.input if step is not None else None
        if current:
            self.input_combo.set_key(current)
        else:
            # New step: prefer a filtered twin so an active filter flows in.
            self.input_combo.prefer_filtered_default()
        # When the signal changes, value spin-box unit suffixes follow it.
        self.input_combo.changed.connect(self._sync_units)

        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Event name (e.g. HS, TO)")
        if step is not None:
            self.label_input.setText(step.label)

        # --- colour (line colour on the graph; from the old EventDialog) ---
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(42)
        self.color_btn.setToolTip("Line colour for this event on the graph.")
        self.color_btn.clicked.connect(self._choose_color)
        self._sync_color_button()

        # --- method ---
        self.method_combo = QComboBox()
        for label, key in self.METHODS:
            self.method_combo.addItem(label, key)
        if step is not None:
            idx = self.method_combo.findData(step.method)
            if idx >= 0:
                self.method_combo.setCurrentIndex(idx)
        self.method_combo.currentIndexChanged.connect(self._sync_method_fields)

        # --- fixed-frame number (1-based display -> 0-based param) ---
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(1, max(1, self._frame_max + 1))
        self.frame_spin.setToolTip("Frame number to pin the event at (e.g. 473).")
        if step is not None and step.method == "frame" and "frame" in p:
            self.frame_spin.setValue(int(p["frame"]) + 1)

        # threshold params
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1000000.0, 1000000.0)
        self.threshold_spin.setDecimals(3)
        self.threshold_spin.setValue(float(p.get("threshold", 20.0)))
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Rising (below → above)", "rising")
        self.direction_combo.addItem("Falling (above → below)", "falling")
        di = self.direction_combo.findData(p.get("direction", "rising"))
        if di >= 0:
            self.direction_combo.setCurrentIndex(di)
        self.hysteresis_spin = QDoubleSpinBox()
        self.hysteresis_spin.setRange(0.0, 1000000.0)
        self.hysteresis_spin.setDecimals(3)
        self.hysteresis_spin.setValue(float(p.get("hysteresis") or 0.0))
        self.hysteresis_spin.setToolTip(
            "0 = off. After one detection, ignore re-crossings until the signal "
            "swings back past this margin — stops a noisy signal triggering twice.")

        # peak params
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Maxima (peaks)", "max")
        self.kind_combo.addItem("Minima (valleys)", "min")
        ki = self.kind_combo.findData(p.get("kind", "max"))
        if ki >= 0:
            self.kind_combo.setCurrentIndex(ki)
        self.prominence_spin = QDoubleSpinBox()
        self.prominence_spin.setRange(0.0, 1000000.0)
        self.prominence_spin.setDecimals(3)
        self.prominence_spin.setValue(float(p.get("prominence") or 0.0))
        self.prominence_spin.setToolTip(
            "0 = off. How tall a peak must stand above its surroundings to count "
            "(ignores small bumps).")

        # zero params (reuse a 3-way direction)
        self.zero_dir_combo = QComboBox()
        self.zero_dir_combo.addItem("Both directions", "both")
        self.zero_dir_combo.addItem("Upward (− → +)", "up")
        self.zero_dir_combo.addItem("Downward (+ → −)", "down")
        zi = self.zero_dir_combo.findData(p.get("direction", "both"))
        if zi >= 0:
            self.zero_dir_combo.setCurrentIndex(zi)
        self.zero_dir_combo.setToolTip(
            "Where the signal value passes through 0 (a sign change). For "
            "velocity/acceleration turning points, apply this to a differentiated "
            "signal.")

        # shared noise guard
        self.min_distance_spin = QSpinBox()
        self.min_distance_spin.setRange(0, 1000000)
        self.min_distance_spin.setValue(int(p.get("min_distance") or 0))
        self.min_distance_spin.setSuffix(" frames")
        self.min_distance_spin.setToolTip(
            "0 = off. Smallest gap (in frames) allowed between two detected "
            "instances — drops events that fire too close together.")

        # --- instance selector (which of the detected occurrences to keep) ---
        self.selector_combo = QComboBox()
        self.selector_combo.addItem("All", "all")
        self.selector_combo.addItem("(n)th", "nth")
        self.selector_combo.addItem("(n)th – (n)th", "range")
        sel = dict(step.selector) if step is not None else {"mode": "all"}
        sel_mode = sel.get("mode", "all")
        nth_default = int(sel.get("n") or 1)
        # Back-compat: the retired "First only" mode is just the 1st occurrence.
        if sel_mode == "first":
            sel_mode, nth_default = "nth", 1
        si = self.selector_combo.findData(sel_mode)
        if si >= 0:
            self.selector_combo.setCurrentIndex(si)
        self.selector_combo.currentIndexChanged.connect(self._sync_selector_fields)

        self.nth_spin = QSpinBox()
        self.nth_spin.setRange(-1000000, 1000000)
        self.nth_spin.setValue(nth_default)
        self.nth_spin.setToolTip("1-based. Negative counts from the end (-1 = last).")
        self.lo_spin = QSpinBox()
        self.lo_spin.setRange(1, 1000000)
        self.lo_spin.setValue(int(sel.get("lo") or 1))
        self.hi_spin = QSpinBox()
        self.hi_spin.setRange(1, 1000000)
        self.hi_spin.setValue(int(sel.get("hi") or 1))
        # The From #/To # spins share one row — cap their width so the two fit on
        # a single line with room for both labels (instead of each grabbing half
        # the dialog).
        for _s in (self.lo_spin, self.hi_spin):
            _s.setMaximumWidth(90)

        # --- optional scope (search window) — Variant B: From/To, each either a
        #     fixed Frame number OR an earlier event (label + instance) ----------
        # The window is bounded by two BOUNDS. Each bound has a Type (Frame |
        # Event); switching Type swaps that row's value widget between a frame
        # spin and an (event-label combo + instance spin). values() returns a
        # ``{"from": bound, "to": bound}`` dict the engine resolves.
        self.scope_check = QCheckBox("Limit search window")
        self.scope_check.toggled.connect(self._sync_scope_fields)

        self._scope_from = self._build_scope_bound_row("Search from", default_frame=0)
        self._scope_to = self._build_scope_bound_row("to", default_frame=self._frame_max)

        # Restore from the step's stored scope (None / legacy list / dict).
        self._restore_scope(getattr(step, "scope", None) if step is not None else None)

        # ---- group 1: Detection (Signal → method → method-specific knobs) --
        # Reordered to the same [signal → method/knobs → naming] flow as the
        # Metric dialog: the user picks WHAT signal + HOW to detect first, and
        # names/colours the event last. Method (+ the fixed-frame number) live at
        # the top of this group so they show even when the signal/knob rows hide.
        detect = self._form_group("Detection", hint_key="Detect.Detection")
        self.signal_label = QLabel("Signal")
        detect.addRow(self.signal_label, self.input_combo)
        detect.addRow("Detection method", self.method_combo)
        self.frame_label = QLabel("Frame")
        detect.addRow(self.frame_label, self.frame_spin)
        self.threshold_label = QLabel("Threshold")
        detect.addRow(self.threshold_label, self.threshold_spin)
        self.direction_label = QLabel("Direction")
        detect.addRow(self.direction_label, self.direction_combo)
        self.kind_label = QLabel("Peak type")
        detect.addRow(self.kind_label, self.kind_combo)
        self.prominence_label = QLabel("Min peak height")
        detect.addRow(self.prominence_label, self.prominence_spin)
        self.zero_dir_label = QLabel("Direction")
        detect.addRow(self.zero_dir_label, self.zero_dir_combo)
        self.detect_group = detect.box
        vb.addWidget(detect.box)

        # ---- group 3: Noise guard (Min spacing / Re-trigger guard) ---------
        guard = self._form_group("Noise guard", hint_key="Detect.Noise guard")
        self.min_distance_label = QLabel("Min spacing")
        guard.addRow(self.min_distance_label, self.min_distance_spin)
        self.hysteresis_label = QLabel("Re-trigger guard")
        guard.addRow(self.hysteresis_label, self.hysteresis_spin)
        self.guard_group = guard.box
        vb.addWidget(guard.box)

        # ---- group 4: Search window (WHERE to look) -------------------------
        # Comes BEFORE Instance: you first set where to search, then pick which
        # of the found occurrences to keep. (Frame window now; "between events"
        # is added on top of this same section.)
        search = self._form_group("Search window", hint_key="Detect.Search window")
        search.addRow("", self.scope_check)
        # Two bound rows: From / To. Each = [ label | Type combo | value widget ].
        # The value widget is itself a small holder that shows a frame-spin OR an
        # (event-combo + instance-spin) depending on the row's Type.
        search.addRow(self._scope_from["label"], self._scope_from["row"])
        search.addRow(self._scope_to["label"], self._scope_to["row"])
        self.search_group = search.box
        vb.addWidget(search.box)

        # ---- group 5: Instance (WHICH of the detected occurrences to keep) --
        # All / (n)th / (n)th–(n)th. These are OCCURRENCE ordinals (1st, 2nd…),
        # NOT frames/time — labelled with "#" to keep that distinct from the
        # Search window's frame fields above.
        instance = self._form_group("Instance", hint_key="Detect.Instance")
        self.selector_label = QLabel("Keep")
        instance.addRow(self.selector_label, self.selector_combo)
        self.nth_label = QLabel("Instance #")
        instance.addRow(self.nth_label, self.nth_spin)
        # "From # [ ]   To # [ ]" on ONE row (was two stacked rows).
        self.lo_label = QLabel("From #")
        self.hi_label = QLabel("To #")
        self.range_row = instance.addPairRow(
            self.lo_label, self.lo_spin, self.hi_label, self.hi_spin)
        self.instance_group = instance.box
        vb.addWidget(instance.box)

        # ---- group (last): Naming (event name + line colour) ----------------
        # Last in the flow — you name the thing you just defined how to detect.
        # Simple section: no "?" (the field names are self-explanatory).
        naming = self._form_group("Naming")
        naming.addRow("Name", self.label_input)
        naming.addRow("Color", self.color_btn)
        vb.addWidget(naming.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)

        # Let the dialog grow/shrink to fit whichever method's fields are shown
        # (each method reveals a different set of rows). Without this the window
        # keeps its first size and taller methods overflow → labels overlap.
        vb.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self._sync_units()
        self._sync_method_fields()
        self._sync_selector_fields()
        self._sync_scope_fields()
        self._relayout()
        install_wheel_guard(self)

    def _relayout(self):
        """Resize to fit currently-visible rows so switching detection method never
        overlaps text. When embedded in AddStepDialog (a child widget, not a window)
        the SetMinimumSize layout constraint propagates the new size to the host, so
        we only adjustSize on the standalone (top-level) dialog."""
        if self.isWindow():
            self.adjustSize()

    def _form_group(self, title, hint_key=None):
        """A titled QGroupBox + QFormLayout (shared :class:`_FormGroup`).

        Kept as a thin instance method for call-site compatibility; the actual
        helper is now module-level so :class:`FilterStepDialog` shares it.
        ``hint_key`` floats a section "?" on the title bar."""
        return _FormGroup(title, hint_key)

    def _build_scope_bound_row(self, label_text, default_frame=0):
        """Build ONE search-window bound (From or To) as a dict of widgets.

        Variant B: a [Type combo: Frame | Event] + a value area that swaps
        between a frame QSpinBox and an (event-label combo + instance spin). The
        whole thing sits on one row holder so it drops into the form as a single
        field. Returns ``{label, row, type_combo, frame_spin, event_combo,
        instance_spin}`` so the caller (layout + show/hide + values) can reach
        each piece."""
        label = QLabel(label_text)

        type_combo = QComboBox()
        type_combo.addItem("Frame", "frame")
        type_combo.addItem("Event", "event")
        type_combo.setMaximumWidth(80)

        frame_spin = QSpinBox()
        frame_spin.setRange(0, self._frame_max)
        # Default: From -> 0, To -> last frame, so a freshly-enabled window spans
        # the whole trial (not a 0..0 empty window).
        frame_spin.setValue(max(0, min(int(default_frame), self._frame_max)))
        frame_spin.setMaximumWidth(110)

        event_combo = QComboBox()
        for lab in self._event_labels:
            event_combo.addItem(lab, lab)

        instance_spin = QSpinBox()
        instance_spin.setRange(-1000000, 1000000)
        instance_spin.setValue(1)
        instance_spin.setMaximumWidth(70)
        instance_spin.setToolTip(
            "Which occurrence of that event (1-based). Negative counts from the "
            "end (-1 = last).")

        # Holder: Type combo + value area on one line. The value area is a stacked
        # pair (frame-spin) / (event-combo + instance-spin); we show/hide rather
        # than use QStackedWidget so the row keeps a tight, single-line height.
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(type_combo)
        hl.addWidget(frame_spin)
        hl.addWidget(event_combo, 1)
        hl.addWidget(instance_spin)

        type_combo.currentIndexChanged.connect(self._sync_scope_fields)

        return {
            "label": label,
            "row": row,
            "type_combo": type_combo,
            "frame_spin": frame_spin,
            "event_combo": event_combo,
            "instance_spin": instance_spin,
        }

    def _restore_scope(self, scope):
        """Populate the From/To bound widgets from a stored ``step.scope``.

        ``None`` -> checkbox off (whole trial). Legacy ``[start, end]`` list ->
        on, both bounds Frame (From=start, To=end). Dict ``{"from":b,"to":b}`` ->
        on, restore each bound's Type/value."""
        if not scope:
            self.scope_check.setChecked(False)
            return
        self.scope_check.setChecked(True)
        if isinstance(scope, (list, tuple)) and len(scope) == 2:
            self._apply_bound(self._scope_from,
                              {"type": "frame", "frame": int(scope[0])})
            self._apply_bound(self._scope_to,
                              {"type": "frame", "frame": int(scope[1])})
            return
        if isinstance(scope, dict):
            self._apply_bound(self._scope_from, scope.get("from"))
            self._apply_bound(self._scope_to, scope.get("to"))

    def _apply_bound(self, bound_row, bound):
        """Set one bound row's Type combo + value widgets from a bound dict."""
        if not isinstance(bound, dict):
            return
        btype = bound.get("type", "frame")
        idx = bound_row["type_combo"].findData(btype)
        if idx >= 0:
            bound_row["type_combo"].setCurrentIndex(idx)
        if btype == "frame":
            try:
                fv = int(bound.get("frame", 0))
            except (TypeError, ValueError):
                fv = 0
            bound_row["frame_spin"].setValue(max(0, min(fv, self._frame_max)))
        elif btype == "event":
            li = bound_row["event_combo"].findData(bound.get("label"))
            if li >= 0:
                bound_row["event_combo"].setCurrentIndex(li)
            try:
                bound_row["instance_spin"].setValue(int(bound.get("instance", 1) or 1))
            except (TypeError, ValueError):
                bound_row["instance_spin"].setValue(1)

    def _scope_bound_value(self, bound_row):
        """Read one bound row -> a scope-bound dict the engine resolves:
        ``{"type":"frame","frame":N}`` or ``{"type":"event","label":L,
        "instance":i}``."""
        btype = bound_row["type_combo"].currentData()
        if btype == "event":
            return {
                "type": "event",
                "label": bound_row["event_combo"].currentData(),
                "instance": int(bound_row["instance_spin"].value()),
            }
        return {"type": "frame", "frame": int(bound_row["frame_spin"].value())}

    def _sync_units(self):
        """Set value spin-box unit suffixes from the selected input signal.

        Threshold / min-peak-height are in the signal's own physical unit
        (force→N, COP/marker→mm, angle→deg) so the user reads e.g. "20 N", not a
        bare number. Re-runs whenever the signal picker changes. The hysteresis
        ("re-trigger guard") shares the same unit as the threshold."""
        key = self.input_combo.selected_key()
        unit = unit_for(key) if key else ""
        suffix = (" " + unit) if unit else ""
        self.threshold_spin.setSuffix(suffix)
        self.hysteresis_spin.setSuffix(suffix)
        self.prominence_spin.setSuffix(suffix)

    def _set_row_visible(self, label, widget, visible):
        label.setVisible(visible)
        widget.setVisible(visible)

    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self.event_color), self, "Event color")
        if color.isValid():
            self.event_color = color.name()
            self._sync_color_button()

    def _sync_color_button(self):
        self.color_btn.setStyleSheet(
            f"background-color:{self.event_color};border:1px solid {BORDER};border-radius:4px;"
        )

    def _sync_method_fields(self):
        method = self.method_combo.currentData()
        is_frame = method == "frame"
        is_thr = method == "threshold"
        is_peak = method == "peak"
        is_zero = method == "zero"
        # Global max/min = the single extreme frame in the (optional) window: needs
        # only the input signal (+ scope). No threshold/peak/zero knobs, no noise
        # guard, and the instance selector is meaningless (there is exactly one).
        is_global = method in ("global_maximum", "global_minimum")
        # Fixed frame = pure manual pin: only the Frame row (+ method) and Name
        # matter. The Detection group STAYS visible (it now holds method + frame),
        # but its Signal + knob rows hide; Noise guard / Result selection hide too.
        self._set_row_visible(self.frame_label, self.frame_spin, is_frame)
        self._set_row_visible(self.signal_label, self.input_combo, not is_frame)
        self.guard_group.setVisible(not is_frame)
        self.search_group.setVisible(not is_frame)
        self.instance_group.setVisible(not is_frame)
        if is_frame:
            for lbl, w in ((self.threshold_label, self.threshold_spin),
                           (self.direction_label, self.direction_combo),
                           (self.kind_label, self.kind_combo),
                           (self.prominence_label, self.prominence_spin),
                           (self.zero_dir_label, self.zero_dir_combo)):
                self._set_row_visible(lbl, w, False)
            self._relayout()
            return
        # Within the Detection group, show only the rows for the chosen method.
        self._set_row_visible(self.signal_label, self.input_combo, True)
        self._set_row_visible(self.threshold_label, self.threshold_spin, is_thr)
        self._set_row_visible(self.direction_label, self.direction_combo, is_thr)
        self._set_row_visible(self.kind_label, self.kind_combo, is_peak)
        self._set_row_visible(self.prominence_label, self.prominence_spin, is_peak)
        self._set_row_visible(self.zero_dir_label, self.zero_dir_combo, is_zero)
        # Re-trigger guard (hysteresis) applies to threshold only; min spacing to
        # threshold + peak. Hide the whole Noise guard group when neither applies.
        self._set_row_visible(self.hysteresis_label, self.hysteresis_spin, is_thr)
        self._set_row_visible(self.min_distance_label, self.min_distance_spin,
                              is_thr or is_peak)
        self.guard_group.setVisible(is_thr or is_peak)
        # Global max/min has a single instance -> hide the whole Instance group
        # (the Search window stays so the user can still window the search).
        self.instance_group.setVisible(not is_global)
        self._sync_selector_fields()
        self._sync_scope_fields()

    def _sync_selector_fields(self):
        method = self.method_combo.currentData()
        if method in ("frame", "global_maximum", "global_minimum"):
            self._set_row_visible(self.nth_label, self.nth_spin, False)
            self.range_row.setVisible(False)
            return
        mode = self.selector_combo.currentData()
        self._set_row_visible(self.nth_label, self.nth_spin, mode == "nth")
        # From #/To # share one row holder — show/hide it together.
        self.range_row.setVisible(mode == "range")
        self._relayout()

    def _sync_scope_fields(self):
        """Show/hide the From/To bound rows together (driven by the checkbox), and
        within each shown row swap the value widget between a frame-spin and an
        (event-combo + instance-spin) by its Type combo. The whole Search window
        is hidden for the manual "Fixed frame" method (handled in
        :meth:`_sync_method_fields`, which hides ``search_group``)."""
        if self.method_combo.currentData() == "frame":
            self._set_scope_row_visible(self._scope_from, False)
            self._set_scope_row_visible(self._scope_to, False)
            self._relayout()
            return
        on = self.scope_check.isChecked()
        self._set_scope_row_visible(self._scope_from, on)
        self._set_scope_row_visible(self._scope_to, on)
        self._relayout()

    def _set_scope_row_visible(self, bound_row, visible):
        """Show/hide one bound row + (when shown) toggle its value widgets to match
        the row's Type (Frame -> frame-spin; Event -> event-combo + instance)."""
        bound_row["label"].setVisible(visible)
        bound_row["row"].setVisible(visible)
        is_event = bound_row["type_combo"].currentData() == "event"
        bound_row["frame_spin"].setVisible(visible and not is_event)
        bound_row["event_combo"].setVisible(visible and is_event)
        bound_row["instance_spin"].setVisible(visible and is_event)

    def values(self):
        """Return ``(input, label, method, params, selector, scope, color)``.

        ``color`` is the line colour, returned as its own value (a real
        DetectEventStep field now, not a detection knob — keeps it out of the
        detection cache token). ``params`` carries only detection knobs. For
        ``method="frame"`` ``params`` carries ``"frame"`` (0-based index) and the
        returned ``input``/``selector``/``scope`` are inert."""
        method = self.method_combo.currentData()
        color = self.event_color
        params = {}
        if method == "frame":
            # 1-based display -> 0-based stored index.
            params["frame"] = int(self.frame_spin.value()) - 1
            return ("", self.label_input.text().strip(),
                    method, params, {"mode": "first"}, None, color)
        if method == "threshold":
            params["threshold"] = float(self.threshold_spin.value())
            params["direction"] = self.direction_combo.currentData()
            if self.hysteresis_spin.value() > 0:
                params["hysteresis"] = float(self.hysteresis_spin.value())
            if self.min_distance_spin.value() > 0:
                params["min_distance"] = int(self.min_distance_spin.value())
        elif method == "peak":
            params["kind"] = self.kind_combo.currentData()
            if self.prominence_spin.value() > 0:
                params["prominence"] = float(self.prominence_spin.value())
            if self.min_distance_spin.value() > 0:
                params["min_distance"] = int(self.min_distance_spin.value())
        elif method == "zero":
            params["direction"] = self.zero_dir_combo.currentData()

        mode = self.selector_combo.currentData()
        selector = {"mode": mode}
        if mode == "nth":
            selector["n"] = int(self.nth_spin.value())
        elif mode == "range":
            selector["lo"] = int(self.lo_spin.value())
            selector["hi"] = int(self.hi_spin.value())

        scope = None
        if self.scope_check.isChecked():
            scope = {"from": self._scope_bound_value(self._scope_from),
                     "to": self._scope_bound_value(self._scope_to)}

        return (self.input_combo.selected_key(),
                self.label_input.text().strip(),
                method, params, selector, scope, color)

    def accept(self):
        """Validate before closing: a missing signal or event name shows a
        message and keeps the dialog OPEN (so the user can fix it) instead of
        dismissing everything they entered."""
        inp, label, method = self.values()[:3]
        if method != "frame" and not inp:
            QMessageBox.information(self, "No signal", "Select a signal to detect on.")
            return
        if not label:
            QMessageBox.information(self, "Event name", "Enter an event name.")
            return
        super().accept()


class TrajectoryStepDialog(QDialog):
    """Edit one pipeline TrajectoryStep: pick the AP (front-back) and ML
    (left-right) COP signals whose 2-D mean-centred path is the statokinesigram.

    ``inputs`` is the offered catalog signal list ``[(key, label), ...]`` (raw +
    processed COP/force, sourced from the parent tab). Defaults to raw COP
    (``cop_ap`` / ``cop_ml``); a ``:filt`` COP key uses the pipeline's filtering.
    Kept deliberately simple — only the two axis pickers — to match the biomech
    "mean-centred COP path" definition."""

    def __init__(self, parent, inputs, step=None):
        super().__init__(parent)
        self.setWindowTitle("Edit COP trajectory" if step else "Add COP trajectory")
        self.setModal(True)
        self.setMinimumWidth(340)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 12, 14, 12)
        vb.setSpacing(8)

        info = QLabel("Draws the COP path (statokinesigram): the left-right (ML) "
                      "vs front-back (AP) sway about its own centre, with a 95% "
                      "ellipse. Pick the COP signals to use.")
        info.setWordWrap(True)
        vb.addWidget(info)

        ap_default = getattr(step, "ap", "cop_ap") if step else "cop_ap"
        ml_default = getattr(step, "ml", "cop_ml") if step else "cop_ml"

        self.ap_combo = CascadingSignalPicker(keys=inputs)
        self.ap_combo.set_key(ap_default)
        self.ml_combo = CascadingSignalPicker(keys=inputs)
        self.ml_combo.set_key(ml_default)
        if step is None:
            # New step: prefer the filtered COP twins so an active filter flows in.
            self.ap_combo.prefer_filtered_default()
            self.ml_combo.prefer_filtered_default()

        # Same titled QGroupBox#model-group chrome as the other step dialogs.
        # AP and ML each get their OWN row: each is a CascadingSignalPicker (two
        # combos), so pairing them onto one row crammed four tiny combos together.
        signals = _FormGroup("Signals", hint_key="Trajectory.Signals")
        signals.addRow(QLabel("AP (front-back)"), self.ap_combo)
        signals.addRow(QLabel("ML (left-right)"), self.ml_combo)
        vb.addWidget(signals.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        install_wheel_guard(self)

    def values(self):
        """Return ``(ap_key, ml_key)`` for the TrajectoryStep."""
        ap = self.ap_combo.selected_key() or "cop_ap"
        ml = self.ml_combo.selected_key() or "cop_ml"
        return ap, ml


#: Joint-angle plane suffix -> biomechanics term. Frontal/transverse names are
#: joint-specific (ankle sagittal = dorsi/plantarflexion, frontal = inversion/
#: eversion — NOT flex/ext or ab/adduction).
_ANGLE_PLANE = {"FE": "Flexion / Extension", "AB": "Ab / Adduction",
                "IE": "Internal / External rotation"}
_ANGLE_PLANE_ANKLE = {"FE": "Dorsi / Plantarflexion",
                      "AB": "Inversion / Eversion",
                      "IE": "Internal / External rotation"}

#: Stable display order for the three planes (sagittal, frontal, transverse).
_PLANE_ORDER = {"FE": 0, "AB": 1, "IE": 2}
#: Stable display order for sides (midline first, then Left, then Right).
_SIDE_ORDER = {None: 0, "Left": 1, "Right": 2}


def _parse_angle(name):
    """Decompose a model angle key into ``(side, joint, plane)``.

    Keys look like ``"R_KNEE_angle_FE"`` -> ``("Right", "Knee", "FE")`` or a
    side-less / plane-less vector angle like ``"TRUNK"`` -> ``(None, "Trunk",
    None)``. ``side`` is ``"Left"``/``"Right"``/``None``; ``plane`` is one of
    ``"FE"``/``"AB"``/``"IE"`` or ``None``."""
    parts = [p for p in str(name).split("_") if p]
    side = None
    if parts and parts[0].upper() in ("L", "R", "LEFT", "RIGHT"):
        side = "Left" if parts[0].upper().startswith("L") else "Right"
        parts = parts[1:]
    plane = None
    if parts and parts[-1].upper() in _PLANE_ORDER:
        plane = parts[-1].upper()
        parts = parts[:-1]
    parts = [p for p in parts if p.lower() != "angle"]
    joint = " ".join(p.title() if len(p) > 1 else p.upper() for p in parts)
    return side, joint, plane


def _plane_label(joint, plane):
    """Joint-specific clinical name for a plane suffix (ankle frontal = inv/ev)."""
    if plane is None:
        return "Angle"
    p = plane.upper()
    if "ankle" in joint.lower():
        return _ANGLE_PLANE_ANKLE.get(p) or _ANGLE_PLANE.get(p, p)
    return _ANGLE_PLANE.get(p, p)


class ComputeAngleStepDialog(QDialog):
    """Edit one pipeline ComputeAngleStep: the step that *makes joint angles exist*.

    Joint angles are no longer auto-computed — they appear only when this step is
    in the recipe (redesign principle: the pipeline is the sole source of derived
    data). The actual angle math + which markers/model lives in the assigned
    kinematic model (built on the static); this step just records "produce angles".

    ``available`` is the list of joint-angle names the resolved model yields (e.g.
    ``["R_KNEE_angle_FE", "L_KNEE_angle_FE", ...]``), supplied by the parent tab.

    Presentation mirrors :class:`FilterStepDialog`: a checkable ``QTreeWidget``
    grouped **Joint -> Side (Left/Right) -> Plane** with auto-tristate parents (so
    one click selects a whole joint or a whole side). Joints are expanded so each
    shows its Left/Right rows; sides start collapsed. Nothing is checked by default
    — the user picks the angles they want. An empty selection (or no model yet)
    means "all angles the model produces"."""

    def __init__(self, parent, available=None, step=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Compute Joint Angles" if step else "Add Compute Joint Angles")
        self.setModal(True)
        self.setMinimumWidth(340)

        # All angle names the model can produce.
        self._available = list(available or [])
        # Pre-selected leaves. Add (step is None) -> nothing checked, the user
        # picks. Editing a step: its own subset; an empty subset means "all" so we
        # show every angle checked (honest about what that step computes).
        if step is None:
            preselect = set()
        else:
            js = set(getattr(step, "joints", None) or [])
            preselect = js if js else set(self._available)

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        info = QLabel(
            "Computes joint angles from the marker model (e.g. hip / knee / ankle "
            "flexion). Only the joints you tick are produced.")
        info.setWordWrap(True)
        info.setObjectName("field-label")
        vb.addWidget(info)

        # One titled group ("Joint angles"), same QGroupBox#model-group chrome as
        # FilterStepDialog. Inside it we stack with a TIGHT QVBoxLayout (not the
        # _FormGroup QFormLayout) so the "All" toggle hugs the tree — the old form
        # layout's label column + row spacing was what opened the big empty gaps.
        self.group_box = QGroupBox("Joint angles")
        self.group_box.setObjectName("model-group")
        gv = QVBoxLayout(self.group_box)
        gv.setContentsMargins(8, 4, 8, 8)
        gv.setSpacing(6)

        # Maps an angle key -> its checkable leaf item (the selection source).
        self._leaves = {}
        if self._available:
            self.all_check = QCheckBox("All")
            self.all_check.setTristate(True)
            self.all_check.clicked.connect(self._on_all_clicked)
            gv.addWidget(self.all_check)

            self.tree = QTreeWidget()
            self.tree.setHeaderHidden(True)
            self.tree.setObjectName("marker-list")
            self.tree.setRootIsDecorated(True)
            # Tighter rows so the (now 2-level) tree reads compact.
            self.tree.setIndentation(14)
            self._build_tree(preselect)
            # Size the tree to its own content (collapsed = a handful of joint rows)
            # instead of a tall fixed box, so there is no dead space below. Capped so
            # a fully-expanded model still scrolls inside a sane height.
            self._fit_tree_height()
            self.tree.itemChanged.connect(self._sync_all_check)
            self.tree.itemExpanded.connect(self._fit_tree_height)
            self.tree.itemCollapsed.connect(self._fit_tree_height)
            gv.addWidget(self.tree)
            self._sync_all_check()
        else:
            need_model = QLabel("Assign a model to this trial's static first "
                                "(double-click the static).")
            need_model.setWordWrap(True)
            need_model.setObjectName("field-label")
            gv.addWidget(need_model)
        # Pin All + tree to the TOP of the group: when this page is embedded in
        # AddStepDialog's tall fixed viewport the group box gets extra height, and
        # without this stretch Qt would spread "All" and the tree apart vertically
        # (the big gap the user saw). The stretch soaks up the slack at the bottom.
        gv.addStretch(1)
        vb.addWidget(self.group_box)
        # Likewise pin the whole group to the top of the page (embedded case).
        vb.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        install_wheel_guard(self)

    def _build_tree(self, preselect):
        """Build a compact 2-level checkable tree from ``self._available``.

        Structure mirrors :class:`FilterStepDialog` (group -> leaves): the JOINT is
        the auto-tristate parent (one click toggles the whole joint), and each child
        leaf is a single ``side + plane`` line, e.g. "Left · Flexion / Extension".
        Folding the Left/Right tier into the leaf label kills the old 3-level depth
        (which made Hip alone span 7 deeply-indented rows). Joints start COLLAPSED
        like the filter dialog — expanded only when they already hold a selection."""
        flag_check = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        auto = flag_check | Qt.ItemFlag.ItemIsAutoTristate

        # Group keys: joints[joint][side] = [(plane, key), ...], order preserved.
        joints = {}
        for name in self._available:
            side, joint, plane = _parse_angle(name)
            joints.setdefault(joint, {}).setdefault(side, []).append((plane, name))

        def _set(item, key):
            item.setFlags(flag_check)
            item.setCheckState(0, Qt.CheckState.Checked if key in preselect
                               else Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self._leaves[key] = item

        for joint, sides in joints.items():
            entries = [(s, p, k) for s, lst in sides.items() for (p, k) in lst]
            # A lone vector angle (no side, no plane) -> the joint itself is a leaf.
            if len(entries) == 1 and entries[0][0] is None and entries[0][1] is None:
                _set(QTreeWidgetItem(self.tree, [joint]), entries[0][2])
                continue

            jitem = QTreeWidgetItem(self.tree, [joint])
            jitem.setFlags(auto)
            any_pre = False
            # Flatten (side, plane) into one leaf each: side first, then plane
            # (so Left's three planes group before Right's). The leaf text is the
            # shared abbreviation from core.marker_model.angle_label (e.g. "R Knee
            # F/E") so the checklist reads the same shorthand as the graph legend /
            # RESULTS, NOT the internal key. The joint word (already the parent
            # header) is trimmed off the leaf so it reads e.g. "Left · F/E".
            for side in sorted(sides, key=lambda s: _SIDE_ORDER.get(s, 9)):
                planes = sorted(sides[side],
                                key=lambda pk: _PLANE_ORDER.get(pk[0], 9))
                for plane, key in planes:
                    leaf_txt = self._leaf_label(key, joint, side, plane)
                    _set(QTreeWidgetItem(jitem, [leaf_txt]), key)
                    any_pre = any_pre or key in preselect
            # Collapsed by default (the common "pick a whole joint" case is one
            # click on the parent); expand only when editing a partial selection.
            jitem.setExpanded(any_pre)

    @staticmethod
    def _leaf_label(key, joint, side, plane):
        """Leaf text for an angle ``key`` — the shared ``angle_label`` shorthand
        with the (parent) joint word trimmed off.

        ``angle_label("R_KNEE_angle_FE")`` -> "R Knee F/E"; the parent row already
        shows "Knee", so the leaf reads "R · F/E" (or just "F/E" when the joint is
        single-sided). Falls back to the local plane name if angle_label can't
        parse the key (keeps the dialog robust to non-JCS keys)."""
        try:
            from core.marker_model import angle_label
            full = angle_label(key)
        except Exception:
            full = None
        plane_txt = None
        if full and full != str(key):
            # Drop the joint token (case-insensitive) so the leaf isn't redundant.
            words = full.split()
            jl = joint.lower()
            plane_txt = " ".join(w for w in words
                                 if w.lower() != jl and w.upper() not in ("R", "L"))
        if not plane_txt:
            plane_txt = _plane_label(joint, plane)
        return f"{side} · {plane_txt}" if side else plane_txt

    def _fit_tree_height(self, *_):
        """Size the tree to the height of its currently-visible rows, capped.

        Collapsed (the default) the tree is just a few joint rows tall, so there is
        no dead space below it; expanding a joint grows it up to a cap, past which it
        scrolls. Replaces the old fixed 220 px box that left a large empty area."""
        rows = self._visible_row_count()
        row_h = max(20, self.tree.sizeHintForRow(0) if rows else 22)
        # +2 for the tiny frame inset; cap at ~10 rows so a fully expanded model
        # scrolls instead of making the dialog enormous.
        h = min(rows, 10) * row_h + 6
        self.tree.setFixedHeight(max(row_h + 6, h))
        # Standalone window: grow/shrink to fit the tree (no effect when embedded as
        # a fixed-size page inside AddStepDialog's scroll viewport). Re-activate the
        # layout first so the group box adopts the tree's new height before we ask
        # the window to fit its content.
        if self.isWindow():
            lay = self.layout()
            if lay is not None:
                lay.activate()
            self.adjustSize()

    def _visible_row_count(self):
        """Count rows the tree currently shows (top-level + expanded children)."""
        n = 0
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            n += 1
            if top.isExpanded():
                n += top.childCount()
        return n

    def _on_all_clicked(self):
        """Master "All" toggled -> set every angle leaf checked/unchecked."""
        checked = self.all_check.checkState() != Qt.CheckState.Unchecked
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for it in self._leaves.values():
            it.setCheckState(0, state)
        self.tree.blockSignals(False)
        self._sync_all_check()

    def _sync_all_check(self, *_):
        """Reflect the leaf checks as the "All" tri-state (all/none/partial)."""
        if not self._leaves:
            return
        n = sum(it.checkState(0) == Qt.CheckState.Checked
                for it in self._leaves.values())
        state = (Qt.CheckState.Checked if n == len(self._leaves)
                 else Qt.CheckState.Unchecked if n == 0
                 else Qt.CheckState.PartiallyChecked)
        self.all_check.blockSignals(True)
        self.all_check.setCheckState(state)
        self.all_check.blockSignals(False)

    def values(self):
        """Return ``{"joints": [...]}`` for the ComputeAngleStep. The selected
        subset; if every available angle is checked (or none are listed) returns an
        empty list, which the step treats as "all angles the model produces"."""
        if not self._leaves:
            return {"joints": []}
        chosen = [k for k, it in self._leaves.items()
                  if it.checkState(0) == Qt.CheckState.Checked]
        # All checked == "all" -> store empty (so adding more model angles later is
        # automatically included); a true subset is stored explicitly.
        if len(chosen) == len(self._leaves):
            return {"joints": []}
        return {"joints": chosen}


def _signal_kind(key):
    """Biomech kind of a catalog signal ``key`` ('angle' / 'force' / 'cop' / None).

    Mirrors :func:`core.signals.unit_for`'s key shapes so the Metric dialog can
    filter the op list to the ops that make sense for the chosen signal (a knee
    angle offers angular velocity/ROM/min/max; a COP plate offers the Prieto
    family; a force offers impulse/RFD …). ``None`` = a generic 1-D signal
    (markers etc.): only the universal scalar ops apply. The ``:filt`` twin keeps
    its base kind (filtering does not change the physical quantity)."""
    if key.endswith(FILT_SUFFIX):
        key = key[: -len(FILT_SUFFIX)]
    if key.startswith("angle:"):
        return "angle"
    # plate-qualified or bare COP / force keys.
    base = key.split(":", 1)[1] if key.startswith("fp") and ":" in key else key
    if base in ("cop", "cop_ap", "cop_ml"):
        return "cop"
    if base in ("fx", "fy", "fz"):
        return "force"
    return None


class MetricStepDialog(QDialog):
    """Edit one pipeline MetricStep, authored in the human order **[input → window
    → calculation]**.

    Reads at the same grade as :class:`DetectEventStepDialog` — grouped
    ``_FormGroup`` chrome, the shared signal picker, and field show/hide driven by
    the current selection. The first choice is *what kind of thing to measure*
    (the op's ``input`` kind in :data:`core.metrics.OP_INFO`):

      * **Signal** — a 1-D signal (angle/force/COP/marker). Pick the signal first;
        the Calculation list is then **filtered by that signal's kind** (angle →
        angular velocity/ROM/…; COP → Prieto family; force → impulse/RFD/…) so a
        meaningless pairing can't be chosen. The Window groups Whole-trial /
        per-cycle / "At a single event" (the latter folds in ``value_at_event``).
      * **Event timing** — a duration between two event labels per cycle (stride/
        step/stance/swing/contact/flight + flight-time jump height). No signal.
      * **Derived from metrics** — a value computed from one or two already-defined
        metrics (cadence, symmetry, CV, RSI, phase %). Picks metric references.

    ``inputs`` = catalog signal list ``[(key, label), ...]``; ``event_labels`` =
    available event names; ``metric_refs`` = names of metrics already defined
    earlier in the pipeline (for the derived ops' references)."""

    #: The three top-level "what to measure" modes, mapped to the OP_INFO input
    #: kinds they cover. ``signal`` also covers ``sample`` (value-at-event) and
    #: ``cop`` ops, which are signal-based; ``jump`` ops are force signals so they
    #: live under signal too. ``event`` and ``metric`` get their own modes.
    MEASURE_MODES = [
        ("Signal", "signal"),
        ("Event timing", "event"),
        ("Derived from metrics", "metric"),
    ]

    def __init__(self, parent, inputs, event_labels, step=None, metric_refs=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Metric Step" if step else "Add Metric Step")
        self.setModal(True)
        self.setMinimumWidth(360)
        from core.metrics import OP_INFO
        try:
            from ui.help_dialog import OP_TOOLTIPS
        except Exception:
            OP_TOOLTIPS = {}
        self._op_info = dict(OP_INFO)
        self._op_tips = dict(OP_TOOLTIPS)
        self._metric_refs = list(metric_refs or [])

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 12, 14, 12)
        vb.setSpacing(8)

        cur_op = getattr(step, "op", "max") if step else "max"
        self._mode = self._mode_for_op(cur_op)

        # ---- group 1: What to measure (mode + its input picker) -------------
        # The mode selector decides which kind of input the metric reads; the
        # input row(s) below it adapt (a signal combo, a pair of event pickers,
        # or metric references). Signal-first: when "Signal" is the mode the very
        # next thing the user touches is the signal, which then filters the ops.
        inp = _FormGroup("Input", hint_key="Metric.Input")
        self.mode_combo = QComboBox()
        for label, key in self.MEASURE_MODES:
            self.mode_combo.addItem(label, key)
        mi = self.mode_combo.findData(self._mode)
        if mi >= 0:
            self.mode_combo.setCurrentIndex(mi)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        inp.addRow("Measure", self.mode_combo)

        # -- signal mode: a single 1-D signal --
        self.input_combo = CascadingSignalPicker(keys=inputs)
        cur_sig = getattr(step, "input", None) if step else None
        if cur_sig:
            self.input_combo.set_key(cur_sig)
        else:
            # New step: prefer a filtered twin so an active filter flows in.
            self.input_combo.prefer_filtered_default()
        # When the signal changes the Calculation list re-filters by signal kind.
        self.input_combo.changed.connect(self._on_signal_changed)
        self.signal_label = QLabel("Signal")
        inp.addRow(self.signal_label, self.input_combo)

        # -- event mode: the pair of events whose spacing IS the metric --
        seg = getattr(step, "segment", None) if step else None
        self.ev_start_combo = QComboBox()
        self.ev_end_combo = QComboBox()
        for c in (self.ev_start_combo, self.ev_end_combo):
            for lbl in event_labels:
                c.addItem(lbl, lbl)
        if seg and len(seg) == 2:
            self._set_combo_data(self.ev_start_combo, seg[0])
            self._set_combo_data(self.ev_end_combo, seg[1])
        # "From [event]  To [event]" on ONE row (was two stacked rows).
        self.ev_start_label = QLabel("From")
        self.ev_end_label = QLabel("To")
        self.ev_row = inp.addPairRow(self.ev_start_label, self.ev_start_combo,
                                     self.ev_end_label, self.ev_end_combo)

        # -- metric mode: 1-2 references to already-defined metrics --
        self.ref1_combo = QComboBox()
        self.ref2_combo = QComboBox()
        for c in (self.ref1_combo, self.ref2_combo):
            for nm in self._metric_refs:
                c.addItem(nm, nm)
        if step:
            self._set_combo_data(self.ref1_combo, getattr(step, "input", ""))
            self._set_combo_data(self.ref2_combo, getattr(step, "input2", ""))
        self.ref1_label = QLabel("Metric")
        inp.addRow(self.ref1_label, self.ref1_combo)
        self.ref2_label = QLabel("Other / divisor")
        inp.addRow(self.ref2_label, self.ref2_combo)
        vb.addWidget(inp.box)

        # ---- group 2: Window (segment) — signal mode only ------------------
        win = _FormGroup("Window", hint_key="Metric.Window")
        self.window_combo = QComboBox()
        self.window_combo.addItem("Whole trial", "whole")
        self.window_combo.addItem("Per cycle (event → event)", "cycle")
        self.window_combo.addItem("At a single event", "at_event")
        # Restore the window mode from the step (value-at-event -> "at a single
        # event"; a segment -> per-cycle; else whole trial).
        if step and getattr(step, "op", "") == "value_at_event":
            self._set_combo_data(self.window_combo, "at_event")
        elif seg:
            self._set_combo_data(self.window_combo, "cycle")
        self.window_combo.currentIndexChanged.connect(self._sync_fields)
        win.addRow("Window", self.window_combo)
        self.seg_start_combo = QComboBox()
        self.seg_end_combo = QComboBox()
        for c in (self.seg_start_combo, self.seg_end_combo):
            for lbl in event_labels:
                c.addItem(lbl, lbl)
        if seg and len(seg) == 2:
            self._set_combo_data(self.seg_start_combo, seg[0])
            self._set_combo_data(self.seg_end_combo, seg[1])
        # "From [event]  To [event]" on ONE row (was two stacked rows).
        self.seg_start_label = QLabel("From")
        self.seg_end_label = QLabel("To")
        self.seg_row = win.addPairRow(self.seg_start_label, self.seg_start_combo,
                                      self.seg_end_label, self.seg_end_combo)
        # single-event picker (value_at_event)
        self.at_event_combo = QComboBox()
        for lbl in event_labels:
            self.at_event_combo.addItem(lbl, lbl)
        if step and getattr(step, "event", None):
            self._set_combo_data(self.at_event_combo, step.event)
        self.at_event_label = QLabel("At event")
        win.addRow(self.at_event_label, self.at_event_combo)
        self.window_group = win.box
        vb.addWidget(win.box)

        # ---- group 3: Calculation (the op) + Name --------------------------
        calc = _FormGroup("Calculation", hint_key="Metric.Calculation")
        self.op_combo = QComboBox()
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        self.op_label = QLabel("Calculation")
        calc.addRow(self.op_label, self.op_combo)
        self.name_input = QLineEdit(getattr(step, "name", "") if step else "")
        self.name_input.setPlaceholderText("e.g. Knee ROM")
        calc.addRow("Name", self.name_input)
        vb.addWidget(calc.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)

        # Resize with the op-specific rows so text never overlaps (Event-dialog
        # pattern). Build the op list for the starting mode/signal, then show rows.
        vb.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._rebuild_op_list(preferred=cur_op)
        self._sync_fields()
        install_wheel_guard(self)

    # -- small helpers --------------------------------------------------------
    def _set_combo_data(self, combo, data):
        if data is None:
            return
        j = combo.findData(data)
        if j >= 0:
            combo.setCurrentIndex(j)

    def _set_row_visible(self, label, widget, visible):
        label.setVisible(visible)
        widget.setVisible(visible)

    def _relayout(self):
        if self.isWindow():
            self.adjustSize()

    def _mode_for_op(self, op):
        """Which top-level mode an op belongs to (from its OP_INFO input kind)."""
        kind = self._op_info.get(op, {}).get("input")
        if kind == "event":
            return "event"
        if kind == "metric":
            return "metric"
        return "signal"   # signal / cop / sample / jump

    def _ops_for_mode(self, mode, signal_kind=None):
        """``[(op, info)]`` valid for the current mode (+ signal kind for signal
        mode). Signal mode keeps only ops whose ``signal_kind`` matches the chosen
        signal, plus the universal ops (no ``signal_kind``); cop ops show only for
        a COP signal, jump ops only for a force signal."""
        out = []
        for op, info in self._op_info.items():
            if self._mode_for_op(op) != mode:
                continue
            if mode == "signal":
                ik = info.get("input")
                sk = info.get("signal_kind")
                # value_at_event is not a "calculation" — it is the implicit op of
                # the Window = "At a single event" choice, so keep it OUT of the op
                # list (handled by the Window picker instead).
                if ik == "sample":
                    continue
                if ik == "cop":
                    ok = signal_kind == "cop"
                elif ik == "jump":
                    ok = signal_kind == "force"
                elif sk is None:             # universal scalar (min/max/mean/…)
                    ok = True
                else:                        # named clinical op: match its kind
                    ok = sk == signal_kind
                if not ok:
                    continue
            out.append((op, info))
        return out

    # -- list builders --------------------------------------------------------
    def _rebuild_op_list(self, preferred=None):
        """Repopulate the Calculation combo for the current mode + signal kind,
        keeping ``preferred`` selected when it is still valid (else first op)."""
        mode = self.mode_combo.currentData()
        sk = _signal_kind(self.input_combo.selected_key() or "") if mode == "signal" else None
        ops = self._ops_for_mode(mode, sk)
        self.op_combo.blockSignals(True)
        self.op_combo.clear()
        for op, info in ops:
            self.op_combo.addItem(f"  {info['label']}", op)
            tip = self._op_tips.get(op)
            if tip:
                self.op_combo.setItemData(self.op_combo.count() - 1, tip,
                                          Qt.ItemDataRole.ToolTipRole)
        want = preferred if preferred is not None else self.op_combo.currentData()
        idx = self.op_combo.findData(want)
        self.op_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.op_combo.blockSignals(False)

    # -- signal/slot ----------------------------------------------------------
    def _on_mode_changed(self):
        self._rebuild_op_list()
        self._sync_fields()

    def _on_signal_changed(self):
        # re-filter the op list to the new signal's kind, keeping the current op
        # if it is still valid.
        self._rebuild_op_list(preferred=self.op_combo.currentData())
        self._sync_fields()

    def _on_op_changed(self):
        # value_at_event is the only op that flips the Window picker indirectly;
        # just re-sync which Window rows show.
        self._sync_fields()

    def _sync_fields(self):
        mode = self.mode_combo.currentData()
        is_signal = mode == "signal"
        is_event = mode == "event"
        is_metric = mode == "metric"
        op = self.op_combo.currentData()

        # Input group rows.
        self._set_row_visible(self.signal_label, self.input_combo, is_signal)
        # From/To events share one row holder — toggle it as a whole.
        self.ev_row.setVisible(is_event)
        self._set_row_visible(self.ref1_label, self.ref1_combo, is_metric)
        # second metric ref only for binary derived ops (n_inputs == 2).
        n_in = self._op_info.get(op, {}).get("n_inputs", 1) if is_metric else 1
        self._set_row_visible(self.ref2_label, self.ref2_combo, is_metric and n_in == 2)

        # Window group: signal mode only.
        self.window_group.setVisible(is_signal)
        win = self.window_combo.currentData() if is_signal else None
        # From/To cycle events share one row holder — toggle it as a whole.
        self.seg_row.setVisible(win == "cycle")
        self._set_row_visible(self.at_event_label, self.at_event_combo, win == "at_event")
        # "At a single event" IS the calculation (value_at_event) — hide the op
        # picker then; otherwise the op is the reduction over the window.
        self._set_row_visible(self.op_label, self.op_combo,
                              not (is_signal and win == "at_event"))
        self._relayout()

    def values(self):
        """Return a dict of MetricStep fields (name/op/input/input2/segment/event).

        Adapts to the mode: signal mode picks ``input`` (+ window → segment or
        value_at_event); event mode stores the event pair as ``segment``; metric
        mode stores the metric reference(s) in ``input``/``input2``."""
        op = self.op_combo.currentData() or "max"
        mode = self.mode_combo.currentData()
        name = self.name_input.text().strip()
        out = {"name": name, "op": op, "input": "", "input2": None,
               "segment": None, "event": None}

        if mode == "event":
            a = self.ev_start_combo.currentData()
            b = self.ev_end_combo.currentData()
            if a and b:
                out["segment"] = [a, b]
            return out

        if mode == "metric":
            out["input"] = self.ref1_combo.currentData() or ""
            n_in = self._op_info.get(op, {}).get("n_inputs", 1)
            if n_in == 2:
                out["input2"] = self.ref2_combo.currentData() or None
            return out

        # signal mode
        out["input"] = self.input_combo.selected_key() or ""
        win = self.window_combo.currentData()
        if win == "at_event":
            # "At a single event" is the value_at_event op (read the raw sample
            # at that event's frame) — the op picker is hidden in this window.
            out["op"] = "value_at_event"
            out["event"] = self.at_event_combo.currentData()
            return out
        if win == "cycle":
            a = self.seg_start_combo.currentData()
            b = self.seg_end_combo.currentData()
            if a and b:
                out["segment"] = [a, b]
        return out

    def accept(self):
        """Validate before closing so a missing name/signal/event keeps the
        dialog OPEN instead of dismissing the user's work (delegates to the
        parent tab's mode-aware validator, which shows the message)."""
        parent = self.parent()
        if parent is not None and hasattr(parent, "_validate_metric_vals"):
            if not parent._validate_metric_vals(self.values()):
                return
        super().accept()


#: Human label for each ComputeStep method (the "Calculation" combo text). Built
#: as a table (NOT hardcoded) keyed off :data:`core.pipeline.COMPUTE_METHODS` so the
#: combo always covers exactly the methods the engine supports — adding a method to
#: COMPUTE_METHODS surfaces here automatically (falling back to a title-cased name).
_COMPUTE_METHOD_LABELS = {
    "normalize": "Normalize (÷ value)",
    "derivative": "Derivative (rate of change)",
    "integral": "Integral (accumulate over time)",
    "magnitude": "Magnitude (resultant of axes)",
    "abs": "Absolute value |x|",
}


class ComputeStepDialog(QDialog):
    """Edit one pipeline :class:`core.pipeline.ComputeStep`: derive a NEW signal
    from one (or, for magnitude, several) existing signal(s).

    Reads at the same grade as the other step dialogs — grouped ``_FormGroup``
    chrome, the shared RAW/PROCESSED signal picker, and method-specific rows that
    show/hide as the Calculation changes (the ``_sync`` pattern from
    :class:`DetectEventStepDialog`).

    Flow (signal-first): pick the **Input signal**, choose the **Calculation**
    (Normalize / Derivative / Integral / Magnitude / Absolute value), tune that
    method's parameters, then **Name** the output signal. The Calculation list is
    built from :data:`core.pipeline.COMPUTE_METHODS` (data-driven, not hardcoded).

    ``inputs`` = catalog signal list ``[(key, label), ...]`` (raw + processed +
    angles); ``metric_refs`` = names of metrics already defined earlier (for the
    Normalize "÷ a metric" option, e.g. body mass)."""

    def __init__(self, parent, inputs, step=None, metric_refs=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Compute Signal" if step else "Add Compute Signal")
        self.setModal(True)
        self.setMinimumWidth(360)
        from core.pipeline import COMPUTE_METHODS, METRIC_PREFIX
        self._methods = list(COMPUTE_METHODS)
        self._metric_prefix = METRIC_PREFIX
        self._metric_refs = list(metric_refs or [])
        self._all_inputs = list(inputs or [])

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 12, 14, 12)
        vb.setSpacing(8)

        # ---- group 1: Input (primary signal + magnitude's extra axes) -------
        inp = _FormGroup("Input")
        self.input_combo = CascadingSignalPicker(keys=self._all_inputs)
        cur_in = getattr(step, "input", None) if step else None
        if cur_in:
            self.input_combo.set_key(cur_in)
        else:
            # New step: prefer a filtered twin so an active filter flows in.
            self.input_combo.prefer_filtered_default()
        inp.addRow("Signal", self.input_combo)

        # magnitude's extra component axes: a small checkable list of the OTHER
        # signals to combine with the primary into a Euclidean resultant.
        self.extra_list = QListWidget()
        self.extra_list.setObjectName("marker-list")
        self.extra_list.setFixedHeight(96)
        preselect = set(getattr(step, "inputs", None) or [])
        for key, label in self._all_inputs:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if key in preselect
                             else Qt.CheckState.Unchecked)
            self.extra_list.addItem(it)
        self.extra_label = QLabel("Extra axes")
        inp.addRow(self.extra_label, self.extra_list)
        self.input_group = inp.box
        vb.addWidget(inp.box)

        # ---- group 2: Calculation (method + its parameters) -----------------
        calc = _FormGroup("Calculation", hint_key="Compute.Calculation")
        self.method_combo = QComboBox()
        for m in self._methods:
            self.method_combo.addItem(_COMPUTE_METHOD_LABELS.get(m, m.title()), m)
        cur_method = getattr(step, "method", "normalize") if step else "normalize"
        mi = self.method_combo.findData(cur_method)
        if mi >= 0:
            self.method_combo.setCurrentIndex(mi)
        self.method_combo.currentIndexChanged.connect(self._sync_method_fields)
        calc.addRow("Calculation", self.method_combo)

        params = dict(getattr(step, "params", None) or {})

        # normalize: by = constant OR a metric reference (two modes).
        self.by_mode_combo = QComboBox()
        self.by_mode_combo.addItem("A constant value", "const")
        self.by_mode_combo.addItem("A metric / subject value", "metric")
        # NB: _sync_method_fields is connected AFTER the restore block below — the
        # restore changes this index, and the sync touches order/sign/kind widgets
        # created further down, so firing it mid-construction crashes.
        self.by_mode_label = QLabel("Divide by")
        calc.addRow(self.by_mode_label, self.by_mode_combo)

        self.by_const_spin = QDoubleSpinBox()
        self.by_const_spin.setRange(-1000000.0, 1000000.0)
        self.by_const_spin.setDecimals(4)
        self.by_const_spin.setValue(1.0)
        self.by_const_label = QLabel("Value")
        calc.addRow(self.by_const_label, self.by_const_spin)

        # Divisor = a built-in SUBJECT quantity (body weight / mass / height — the
        # engine seeds these from the static trial's subject; mass auto-estimates
        # from the GRF) OR a metric defined earlier in the pipeline. Body weight is
        # first so a force → %BW normalisation is one click.
        self.by_metric_combo = QComboBox()
        for _label, _key in (("Body weight (N)", "bodyweight"),
                             ("Body mass (kg)", "mass"),
                             ("Height (m)", "height")):
            self.by_metric_combo.addItem(_label, _key)
        if self._metric_refs:
            self.by_metric_combo.insertSeparator(self.by_metric_combo.count())
            for nm in self._metric_refs:
                self.by_metric_combo.addItem(nm, nm)
        self.by_metric_label = QLabel("Divisor")
        calc.addRow(self.by_metric_label, self.by_metric_combo)

        # Restore normalize ``by`` (a metric ref or a constant) when editing.
        cur_by = getattr(step, "by", 1.0) if step else 1.0
        if isinstance(cur_by, str) and cur_by.startswith(self._metric_prefix):
            self._set_combo_data(self.by_mode_combo, "metric")
            self._set_combo_data(self.by_metric_combo,
                                 cur_by[len(self._metric_prefix):])
        else:
            self._set_combo_data(self.by_mode_combo, "const")
            try:
                self.by_const_spin.setValue(float(cur_by))
            except (TypeError, ValueError):
                pass
        # Safe to connect now: restore is done and the sync's target widgets are
        # built just below (the final _sync_method_fields() call does initial sync).
        self.by_mode_combo.currentIndexChanged.connect(self._sync_method_fields)

        # derivative: order 1 (velocity) / 2 (acceleration).
        self.order_combo = QComboBox()
        self.order_combo.addItem("1st — rate (velocity)", 1)
        self.order_combo.addItem("2nd — rate of rate (acceleration)", 2)
        self._set_combo_data(self.order_combo, int(params.get("order", 1) or 1))
        self.order_label = QLabel("Order")
        calc.addRow(self.order_label, self.order_combo)

        # integral: sign gate + cumulative/total kind.
        self.sign_combo = QComboBox()
        self.sign_combo.addItem("All (signed area)", "all")
        self.sign_combo.addItem("Positive part only", "pos")
        self.sign_combo.addItem("Negative part only", "neg")
        self._set_combo_data(self.sign_combo, params.get("sign", "all"))
        self.sign_label = QLabel("Part")
        calc.addRow(self.sign_label, self.sign_combo)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Cumulative (running total)", "cumulative")
        self.kind_combo.addItem("Total (single value over trial)", "total")
        self._set_combo_data(self.kind_combo, params.get("kind", "cumulative"))
        self.kind_label = QLabel("Accumulation")
        calc.addRow(self.kind_label, self.kind_combo)

        self.calc_group = calc.box
        vb.addWidget(calc.box)

        # ---- group 3: Naming (output signal key) ----------------------------
        naming = _FormGroup("Naming")
        self.name_input = QLineEdit(getattr(step, "name", "") if step else "")
        self.name_input.setPlaceholderText("e.g. Knee velocity, |Fz|, GRF")
        naming.addRow("Output name", self.name_input)
        vb.addWidget(naming.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)

        # Resize with the method-specific rows so switching method never overlaps
        # text (same pattern as the Event / Metric dialogs).
        vb.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._sync_method_fields()
        install_wheel_guard(self)

    # -- small helpers --------------------------------------------------------
    def _set_combo_data(self, combo, data):
        if data is None:
            return
        j = combo.findData(data)
        if j >= 0:
            combo.setCurrentIndex(j)

    def _set_row_visible(self, label, widget, visible):
        label.setVisible(visible)
        widget.setVisible(visible)

    def _relayout(self):
        if self.isWindow():
            self.adjustSize()

    def _sync_method_fields(self):
        """Show only the rows the current Calculation needs (the ``_sync`` pattern).

        normalize → divide-by (constant OR metric); derivative → order; integral →
        part + accumulation; magnitude → extra-axes list; abs → nothing extra."""
        method = self.method_combo.currentData()
        is_norm = method == "normalize"
        is_deriv = method == "derivative"
        is_integ = method == "integral"
        is_mag = method == "magnitude"

        # normalize: the by-mode picker, plus the constant OR metric row.
        self._set_row_visible(self.by_mode_label, self.by_mode_combo, is_norm)
        by_mode = self.by_mode_combo.currentData()
        self._set_row_visible(self.by_const_label, self.by_const_spin,
                              is_norm and by_mode == "const")
        self._set_row_visible(self.by_metric_label, self.by_metric_combo,
                              is_norm and by_mode == "metric")
        # derivative
        self._set_row_visible(self.order_label, self.order_combo, is_deriv)
        # integral
        self._set_row_visible(self.sign_label, self.sign_combo, is_integ)
        self._set_row_visible(self.kind_label, self.kind_combo, is_integ)
        # magnitude: extra component axes (the OTHER signals to combine).
        self._set_row_visible(self.extra_label, self.extra_list, is_mag)
        self._relayout()

    def _checked_extra(self):
        """Keys of the checked extra-axis items (excluding the primary input)."""
        primary = self.input_combo.selected_key()
        out = []
        for i in range(self.extra_list.count()):
            it = self.extra_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                key = it.data(Qt.ItemDataRole.UserRole)
                if key and key != primary:
                    out.append(key)
        return out

    def values(self):
        """Return a dict of :class:`ComputeStep` fields.

        ``{input, name, method, by, params, inputs}`` — built for the chosen
        method so the tab can do ``ComputeStep(**vals)``. Irrelevant fields are
        left at their harmless defaults (the engine ignores them per method)."""
        method = self.method_combo.currentData() or "normalize"
        out = {
            "input": self.input_combo.selected_key() or "",
            "name": self.name_input.text().strip(),
            "method": method,
            "by": 1.0,
            "params": {},
            "inputs": [],
        }
        if method == "normalize":
            if self.by_mode_combo.currentData() == "metric":
                ref = self.by_metric_combo.currentData()
                out["by"] = f"{self._metric_prefix}{ref}" if ref else 1.0
            else:
                out["by"] = float(self.by_const_spin.value())
        elif method == "derivative":
            out["params"] = {"order": int(self.order_combo.currentData() or 1)}
        elif method == "integral":
            out["params"] = {"sign": self.sign_combo.currentData() or "all",
                             "kind": self.kind_combo.currentData() or "cumulative"}
        elif method == "magnitude":
            out["inputs"] = self._checked_extra()
        return out

    def accept(self):
        """Validate before closing so a missing output name/input keeps the
        dialog OPEN instead of dismissing the user's work (delegates to the
        parent tab's validator, which shows the message)."""
        parent = self.parent()
        if parent is not None and hasattr(parent, "_validate_compute_vals"):
            if not parent._validate_compute_vals(self.values()):
                return
        super().accept()


class AddStepDialog(QDialog):
    """Unified "Add step" popup (Visual3D-style Add-Command) — opened by the
    PIPELINE ``+`` button (NOT a context menu).

    Left = a list of every command you can add (Filter · Detect Event · Metric ·
    Compute trajectory); right = that command's parameter form. The forms are the
    existing per-step dialogs, embedded as pages (their own OK/Cancel hidden) so
    there is one place to author any step. ``OK`` returns ``(kind, values)`` for
    the selected command, which the tab turns into the matching pipeline step.

    ``ctx`` supplies the per-command constructor inputs (so this dialog stays dumb):
    ``filter_targets``, ``event_inputs``, ``frame_max``, ``event_color``,
    ``metric_inputs``, ``event_labels``, ``traj_inputs``."""

    #: (kind, display label) in list order. Edit reuses the per-step dialogs.
    COMMANDS = [
        ("filter", "Filter"),
        ("compute_angle", "Compute joint angles"),
        ("compute", "Compute signal"),
        ("trajectory", "COP trajectory"),
        ("detect_event", "Detect Event"),
        ("metric", "Metric"),
        ("normalize", "Normalize (% cycle)"),
    ]

    #: Commands grouped by what they DO (Visual3D-style command grouping), so the
    #: picker reads as a tidy menu instead of a flat list: Process makes/derives
    #: signals, Detect marks events, Measure produces metric numbers.
    GROUPS = [
        ("Process", ["filter", "compute_angle", "compute", "trajectory"]),
        ("Detect",  ["detect_event"]),
        ("Measure", ["metric", "normalize"]),
    ]

    #: One comfortable fixed size for the whole popup. The right-side form area is
    #: a fixed-height scroll viewport (see below), so switching command OR a
    #: Detect-method that reveals/hides rows NEVER resizes this window.
    DIALOG_W = 600
    DIALOG_H = 540

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.setWindowTitle("Add Pipeline Step")
        self.setModal(True)
        # Fixed footprint: the dialog can neither grow nor shrink with its content.
        self.setFixedSize(self.DIALOG_W, self.DIALOG_H)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # left: command list, grouped (Process / Detect / Measure) with muted,
        # non-selectable header rows so the picker reads as a tidy menu.
        self.cmd_list = QListWidget()
        self.cmd_list.setObjectName("marker-list")
        self.cmd_list.setFixedWidth(180)
        labels = dict(self.COMMANDS)
        first_cmd_row = None
        for gi, (group, kinds) in enumerate(self.GROUPS):
            header = QListWidgetItem(group.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)   # not selectable
            f = header.font()
            f.setPointSize(max(7, f.pointSize() - 1))
            f.setBold(True)
            header.setFont(f)
            header.setForeground(QColor(TEXT_MUTED))
            self.cmd_list.addItem(header)
            for kind in kinds:
                item = QListWidgetItem("   " + labels.get(kind, kind))
                item.setData(Qt.ItemDataRole.UserRole, kind)
                self.cmd_list.addItem(item)
                if first_cmd_row is None:
                    first_cmd_row = self.cmd_list.row(item)
        body.addWidget(self.cmd_list)

        # right: the per-command forms live inside a fixed-size QScrollArea. A
        # form taller than the viewport scrolls; a short one just leaves empty
        # space below — either way the dialog itself keeps one stable size.
        self._form_scroll = QScrollArea()
        self._form_scroll.setObjectName("addstep-form-scroll")
        self._form_scroll.setWidgetResizable(True)
        self._form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self._form_scroll, 1)

        # one embedded form page per command (inside the scroll viewport)
        from PyQt6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self._form_scroll.setWidget(self.stack)

        self.forms = {}
        self.forms["filter"] = FilterStepDialog(self, ctx.get("filter_targets", []))
        self.forms["compute_angle"] = ComputeAngleStepDialog(
            self, ctx.get("compute_angle_joints", []))
        self.forms["compute"] = ComputeStepDialog(
            self, ctx.get("compute_inputs", []),
            metric_refs=ctx.get("metric_refs", []))
        self.forms["detect_event"] = DetectEventStepDialog(
            self, ctx.get("event_inputs", []), frame_max=ctx.get("frame_max", 0),
            color=ctx.get("event_color"),
            event_labels=ctx.get("event_labels"))
        self.forms["metric"] = MetricStepDialog(
            self, ctx.get("metric_inputs", []), ctx.get("event_labels", []),
            metric_refs=ctx.get("metric_refs", []))
        self.forms["trajectory"] = TrajectoryStepDialog(self, ctx.get("traj_inputs", []))
        from ui.ensemble_panel import NormalizeStepDialog
        self.forms["normalize"] = NormalizeStepDialog(
            self, ctx.get("event_inputs", []), ctx.get("event_labels", []))
        # Stack page index per command kind (pages added in COMMANDS order).
        self._page_for_kind = {}
        for kind, _label in self.COMMANDS:
            form = self.forms[kind]
            # Embed the existing dialog as a plain page; hide its own buttons +
            # make it a child widget (not a top-level window).
            form.setWindowFlags(Qt.WindowType.Widget)
            bb = form.findChild(QDialogButtonBox)
            if bb is not None:
                bb.hide()
            self._page_for_kind[kind] = self.stack.addWidget(form)

        # Selecting a command row shows its form page; header rows aren't
        # selectable, so currentItemChanged only ever lands on a real command.
        self.cmd_list.currentItemChanged.connect(self._on_command_changed)
        if first_cmd_row is not None:
            self.cmd_list.setCurrentRow(first_cmd_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        # NB: no SetMinimumSize constraint here — the dialog is a fixed size and
        # the embedded forms scroll inside the viewport instead of resizing it.
        # Block wheel-scroll value edits on every embedded spin/combo (a form
        # may scroll inside its viewport — the wheel must scroll, not edit).
        install_wheel_guard(self)

    def _on_command_changed(self, current, _previous):
        """Show the form page for the selected command row (ignore header rows)."""
        if current is None:
            return
        kind = current.data(Qt.ItemDataRole.UserRole)
        if kind is None:   # a (non-selectable) header — should not happen
            return
        self.stack.setCurrentIndex(self._page_for_kind[kind])

    def selected_kind(self):
        item = self.cmd_list.currentItem()
        kind = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return kind or self.COMMANDS[0][0]

    def values(self):
        """``(kind, form_values)`` for the selected command."""
        kind = self.selected_kind()
        return kind, self.forms[kind].values()

    def accept(self):
        """Validate the selected command's form before closing so a missing
        required field keeps THIS popup open (instead of closing and then
        showing the error). Delegates to the parent tab's validators for
        compute/metric and checks the detect essentials inline; the other
        commands have no required free-text field."""
        kind, vals = self.values()
        tab = self.parent()
        if kind == "detect_event":
            inp, label, method = vals[0], vals[1], vals[2]
            if method != "frame" and not inp:
                QMessageBox.information(self, "No signal", "Select a signal to detect on.")
                return
            if not label:
                QMessageBox.information(self, "Event name", "Enter an event name.")
                return
        elif kind == "compute" and tab is not None and hasattr(tab, "_validate_compute_vals"):
            if not tab._validate_compute_vals(vals):
                return
        elif kind == "metric" and tab is not None and hasattr(tab, "_validate_metric_vals"):
            if not tab._validate_metric_vals(vals):
                return
        super().accept()


class SubjectInfoDialog(QDialog):
    """Per-subject info entered ON a static trial (1 static = 1 subject).

    Mass auto-fills from the static's vertical GRF (``mass = mean(Fz)/g``) — the
    user can override; Height and Sex are manual. The static's dynamic trials
    inherit these via the nearest-ancestor static (see ``AnalyzeTab._subject_for``).
    Only the three values the app actually computes with: Mass (%BW normalize +
    COM), Height (length scaling), Sex (de Leva COM mass fractions)."""

    def __init__(self, parent, subject=None, mass_estimate=None):
        super().__init__(parent)
        self.setWindowTitle("Subject info")
        self.setModal(True)
        self.setMinimumWidth(300)
        subject = subject or {}

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        form = _FormGroup("Subject")
        self.mass_spin = QDoubleSpinBox()
        self.mass_spin.setRange(0.0, 300.0)
        self.mass_spin.setDecimals(1)
        self.mass_spin.setSuffix(" kg")
        self.mass_spin.setSpecialValueText("— (auto)")
        mass = subject.get("mass")
        if mass:
            self.mass_spin.setValue(float(mass))
        elif mass_estimate:
            self.mass_spin.setValue(float(mass_estimate))
        form.addRow("Mass", self.mass_spin)
        if mass_estimate:
            hint = QLabel(f"auto from static force ≈ {float(mass_estimate):.1f} kg")
            hint.setObjectName("field-label")
            form.addWidget(hint)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(0.0, 2.5)
        self.height_spin.setDecimals(2)
        self.height_spin.setSuffix(" m")
        self.height_spin.setSpecialValueText("—")
        if subject.get("height"):
            self.height_spin.setValue(float(subject["height"]))
        form.addRow("Height", self.height_spin)

        self.sex_combo = QComboBox()
        for label, data in (("—", ""), ("Male", "M"), ("Female", "F")):
            self.sex_combo.addItem(label, data)
        j = self.sex_combo.findData(subject.get("sex", ""))
        if j >= 0:
            self.sex_combo.setCurrentIndex(j)
        form.addRow("Sex", self.sex_combo)
        vb.addWidget(form.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        install_wheel_guard(self)

    def values(self):
        """``{mass, height, sex}`` — 0/'' means unset."""
        return {
            "mass": float(self.mass_spin.value()) or None,
            "height": float(self.height_spin.value()) or None,
            "sex": self.sex_combo.currentData() or "",
        }


class ExportDialog(QDialog):
    """Dedicated EXPORT popup (Excel/SPSS/Visual3D-style export wizard).

    The result-panel checkboxes in the Analyze tab are for VIEWING only — this
    popup is the single place where the user chooses *what to export* (which
    metrics, optionally which files), *where* (filename + folder) and *which
    format* (Excel / CSV). It owns the save path entirely; the old
    ``QFileDialog.getSaveFileName`` flow is gone.

    Inputs (so the dialog stays dumb — all data is computed by the tab first):
      - ``metrics`` = ``[(name, unit), ...]`` — the union of metric names
        produced across the checked files (deduplicated, in first-seen order).
      - ``files``   = ``[(index, label), ...]`` — the checked files, so the user
        can narrow the file set. ``None``/empty hides the files section.

    :meth:`values` returns
    ``{selected_metrics: set, selected_files: list|None, path: str,
    format: str}`` where ``format`` is ``"xlsx"`` or ``"csv"`` and ``path`` is
    the full save path (folder + filename + extension). ``selected_files`` is a
    list of dataset indexes, or ``None`` when no files section is shown."""

    FORMATS = [("Excel (.xlsx)", "xlsx"), ("CSV (.csv)", "csv")]

    def __init__(self, parent, metrics, files=None, default_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Export Results")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._metrics = list(metrics or [])
        self._files = list(files or [])

        vb = QVBoxLayout(self)
        vb.setContentsMargins(14, 14, 14, 14)
        vb.setSpacing(10)

        # ---- Data selection: which metrics (variables) to export -----------
        data_group = _FormGroup("Data to export")
        all_row = QHBoxLayout()
        all_row.addWidget(QLabel("Variables"))
        all_row.addStretch()
        self.metrics_all_check = QCheckBox("All")
        self.metrics_all_check.setChecked(True)
        self.metrics_all_check.stateChanged.connect(self._toggle_all_metrics)
        all_row.addWidget(self.metrics_all_check)
        all_row_w = QWidget()
        all_row_w.setLayout(all_row)
        data_group.addWidget(all_row_w)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(160)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(4)
        self.metric_checks = {}
        if self._metrics:
            for name, unit in self._metrics:
                label = f"{name} ({unit})" if unit else name
                cb = QCheckBox(label)
                cb.setChecked(True)
                cb.stateChanged.connect(self._sync_metrics_all_check)
                self.metric_checks[name] = cb
                il.addWidget(cb)
        else:
            empty = QLabel("No metrics available. Add Metric steps to the "
                           "pipeline first.")
            empty.setObjectName("field-label")
            empty.setWordWrap(True)
            il.addWidget(empty)
        il.addStretch()
        scroll.setWidget(inner)
        data_group.addWidget(scroll)
        vb.addWidget(data_group.box)

        # ---- optional Files selection --------------------------------------
        self.file_checks = {}
        if self._files:
            files_group = _FormGroup("Files")
            fscroll = QScrollArea()
            fscroll.setWidgetResizable(True)
            fscroll.setFixedHeight(110)
            finner = QWidget()
            fl = QVBoxLayout(finner)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(4)
            for index, label in self._files:
                cb = QCheckBox(label)
                cb.setChecked(True)
                self.file_checks[int(index)] = cb
                fl.addWidget(cb)
            fl.addStretch()
            fscroll.setWidget(finner)
            files_group.addWidget(fscroll)
            vb.addWidget(files_group.box)

        # ---- Destination: filename / location / format ---------------------
        dest = _FormGroup("Destination")
        self.name_input = QLineEdit("analysis_results")
        self.name_input.setPlaceholderText("File name (no extension)")
        dest.addRow("File name", self.name_input)

        loc_row = QHBoxLayout()
        loc_row.setContentsMargins(0, 0, 0, 0)
        loc_row.setSpacing(6)
        self.dir_input = QLineEdit(default_dir or os.getcwd())
        loc_row.addWidget(self.dir_input, 1)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._choose_dir)
        loc_row.addWidget(self.browse_btn)
        loc_w = QWidget()
        loc_w.setLayout(loc_row)
        dest.addRow("Location", loc_w)

        self.format_combo = QComboBox()
        for label, key in self.FORMATS:
            self.format_combo.addItem(label, key)
        dest.addRow("Format", self.format_combo)
        vb.addWidget(dest.box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        vb.addWidget(buttons)
        install_wheel_guard(self)

    # -- destination helpers --------------------------------------------------
    def _choose_dir(self):
        start = self.dir_input.text().strip() or os.getcwd()
        path = QFileDialog.getExistingDirectory(self, "Export location", start)
        if path:
            self.dir_input.setText(path)

    def _ext(self):
        return self.format_combo.currentData() or "xlsx"

    def _path(self):
        name = self.name_input.text().strip() or "analysis_results"
        ext = self._ext()
        if name.lower().endswith("." + ext):
            name = name[: -(len(ext) + 1)]
        folder = self.dir_input.text().strip() or os.getcwd()
        return os.path.join(folder, f"{name}.{ext}")

    # -- metric "All" sync ----------------------------------------------------
    def _toggle_all_metrics(self, state):
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        for cb in self.metric_checks.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)

    def _sync_metrics_all_check(self):
        if not self.metric_checks:
            return
        all_checked = all(cb.isChecked() for cb in self.metric_checks.values())
        self.metrics_all_check.blockSignals(True)
        self.metrics_all_check.setChecked(all_checked)
        self.metrics_all_check.blockSignals(False)

    # -- accept guard ---------------------------------------------------------
    def _on_accept(self):
        if self.metric_checks and not any(
                cb.isChecked() for cb in self.metric_checks.values()):
            QMessageBox.information(self, "No variables",
                                    "Select at least one variable to export.")
            return
        if self.file_checks and not any(
                cb.isChecked() for cb in self.file_checks.values()):
            QMessageBox.information(self, "No files",
                                    "Select at least one file to export.")
            return
        if not self.dir_input.text().strip():
            QMessageBox.information(self, "No location",
                                    "Choose a folder to save into.")
            return
        self.accept()

    def values(self):
        """``{selected_metrics, selected_files, path, format}``.

        ``selected_metrics`` is a set of metric names; ``selected_files`` is a
        list of dataset indexes (or ``None`` if no files section was shown);
        ``path`` is the full save path; ``format`` is ``"xlsx"``/``"csv"``."""
        selected_metrics = {
            name for name, cb in self.metric_checks.items() if cb.isChecked()
        }
        if self.file_checks:
            selected_files = [
                idx for idx, cb in self.file_checks.items() if cb.isChecked()
            ]
        else:
            selected_files = None
        return {
            "selected_metrics": selected_metrics,
            "selected_files": selected_files,
            "path": self._path(),
            "format": self._ext(),
        }
