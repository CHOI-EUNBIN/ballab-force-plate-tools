"""Joint-angle model builder dialog.

Opens on a STATIC calibration trial, auto-maps a suggested model
(joints/segments/angles) by naming convention, and lets the user review/edit it
via dropdown/checklist selection (no free-typing of marker names). The
joint-centre accuracy (calibration self-check) updates automatically. Save/Load
the model template as JSON.
"""

import json
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QComboBox, QHeaderView, QFileDialog, QMessageBox,
    QDialogButtonBox, QGroupBox, QScrollArea, QWidget, QListWidget,
    QListWidgetItem, QCheckBox,
)
from PyQt6.QtCore import Qt

from core.marker_model import MarkerModel, auto_build_model, task_preset


# --------------------------------------------------------------------------
# Korean task labels  <->  engine task keys.
#
# The engine only speaks English keys ("walk"/"run"/...). The display labels the
# user actually sees live ONLY here in the UI layer -- the engine never imports
# these. "General"(generic) is first/default so the dialog opens on the
# previous (backward-compatible) behaviour.
# --------------------------------------------------------------------------
TASK_CHOICES = [
    ("General",  "generic"),
    ("Gait",     "walk"),
    ("Running",  "run"),
    ("Jump",     "jump"),
    ("Balance",  "balance"),
]
_KEY_TO_LABEL = {key: label for label, key in TASK_CHOICES}
DEFAULT_TASK = "generic"


class NoWheelComboBox(QComboBox):
    """Combo box that ignores mouse-wheel scrolling so values only change on an
    explicit click/selection (avoids silently changing a marker mapping while the
    user scrolls the dialog)."""

    def wheelEvent(self, event):
        event.ignore()


class _MarkerCheckDialog(QDialog):
    """Checklist popup to pick a set of marker labels (cluster)."""

    def __init__(self, parent, labels, selected):
        super().__init__(parent)
        self.setWindowTitle("Select cluster markers (≥3)")
        self.resize(240, 320)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        for lab in labels:
            it = QListWidgetItem(lab)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if lab in selected else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class _ClusterButton(QPushButton):
    """Cell button holding a list of cluster labels, edited via a checklist."""

    def __init__(self, labels, current, on_change):
        super().__init__()
        self._labels = labels
        self._selected = list(current)
        self._on_change = on_change
        self._refresh_text()
        self.clicked.connect(self._pick)

    def _refresh_text(self):
        self.setText(", ".join(self._selected) if self._selected else "(pick…)")

    def _pick(self):
        dlg = _MarkerCheckDialog(self, self._labels, self._selected)
        if dlg.exec():
            self._selected = dlg.selected()
            self._refresh_text()
            self._on_change()

    def value(self):
        return list(self._selected)


class ModelDialog(QDialog):
    def __init__(self, parent, static_markers, model=None,
                 task=DEFAULT_TASK, zero_to_static=None):
        super().__init__(parent)
        from ui import style
        self.setWindowTitle("Build Joint-Angle Model")
        self.resize(720, 720)
        self._labels = list(static_markers["labels"])
        self._static = static_markers
        self.result_model = None
        # What the user picked (read by analyze_tab after the dialog closes).
        self.result_task = task or DEFAULT_TASK
        self.result_zero_to_static = None  # set on OK
        self._loading = False
        # If the caller didn't pin a zero-to-static choice, follow the task's
        # recommended default (walk/run -> on, others -> off).
        if zero_to_static is None:
            zero_to_static = bool(task_preset(self.result_task).get("static_offset"))
        self._zero_to_static = bool(zero_to_static)

        root = QVBoxLayout(self)

        # --- "motion" picker (display labels only; engine sees English keys) ---
        root.addLayout(self._build_task_row())

        top = QHBoxLayout()
        # Calibration markers: show the count, click to expand the full list
        # (avoids an awkward mid-list "…" truncation).
        self.markers_btn = QPushButton(f"▸ Calibration markers: {len(self._labels)}")
        self.markers_btn.setCheckable(True)
        self.markers_btn.setFlat(True)
        self.markers_btn.setStyleSheet(
            f"QPushButton{{text-align:left;color:{style.TEXT_SECONDARY};border:none;"
            f"padding:2px 0;}}")
        self.markers_btn.toggled.connect(self._on_markers_toggled)
        top.addWidget(self.markers_btn)
        top.addStretch(1)
        auto_btn = QPushButton("Auto-map")
        auto_btn.setToolTip("Re-guess joints/segments/angles from marker names")
        auto_btn.clicked.connect(self._auto_map)
        top.addWidget(auto_btn)
        root.addLayout(top)

        self.markers_lbl = QLabel(", ".join(self._labels))
        self.markers_lbl.setWordWrap(True)
        self.markers_lbl.setVisible(False)
        self.markers_lbl.setStyleSheet(
            f"color:{style.TEXT_MUTED};font-size:11px;padding:0 0 4px 12px;")
        root.addWidget(self.markers_lbl)

        # scrollable group boxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        col = QVBoxLayout(inner)

        self.joints_tbl = self._make_table(["Name", "Medial", "Lateral", "Cluster (≥3)"])
        col.addWidget(self._group("JOINTS", "Joint centre = midpoint(medial, lateral), tracked by a cluster of ≥3 markers.",
                                  self.joints_tbl, self._add_joint))
        self.segs_tbl = self._make_table(["Name", "Proximal", "Distal"])
        col.addWidget(self._group("SEGMENTS", "Vector from the proximal to the distal point (a joint centre or a marker).",
                                  self.segs_tbl, self._add_segment))
        self.angles_tbl = self._make_table(["Name", "Segment A", "Segment B"])
        col.addWidget(self._group("ANGLES", "Angle between two segments.",
                                  self.angles_tbl, self._add_angle,
                                  extra=self._make_zero_check()))
        col.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # advanced settings (collapsible, hidden by default)
        self._build_advanced()
        root.addWidget(self.adv_btn)
        root.addWidget(self.adv_box)

        # footer (JSON load/save live in the sidebar Model panel, not here)
        self.check_lbl = QLabel("")
        root.addWidget(self.check_lbl)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._on_ok)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # name edits re-wire dependent dropdowns + re-check
        self.joints_tbl.itemChanged.connect(self._on_joint_names_changed)
        self.segs_tbl.itemChanged.connect(self._on_segment_names_changed)
        self.angles_tbl.itemChanged.connect(lambda *_: self._self_check())

        self._populate(model if model is not None
                       else auto_build_model(static_markers, task=self.result_task))
        self._refresh_advanced()

    # ----- builders -----
    def _make_table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setMaximumHeight(150)
        return t

    def _group(self, title, description, table, add_slot, extra=None):
        box = QGroupBox(title)
        box.setObjectName("model-group")
        lay = QVBoxLayout(box)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setObjectName("model-group-desc")
        lay.addWidget(desc)
        if extra is not None:
            lay.addWidget(extra)
        lay.addWidget(table)
        row = QHBoxLayout()
        row.addStretch(1)
        add = QPushButton("+"); add.setFixedWidth(32); add.clicked.connect(add_slot)
        rem = QPushButton("−"); rem.setFixedWidth(32); rem.clicked.connect(lambda: self._del_rows(table))
        row.addWidget(add); row.addWidget(rem)
        lay.addLayout(row)
        return box

    def _combo(self, options, current=""):
        c = NoWheelComboBox()
        c.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        c.addItems([o for o in options if o])
        if current and current not in options:
            c.addItem(current)
        c.setCurrentIndex(c.findText(current) if current else -1)
        c.currentIndexChanged.connect(lambda *_: self._self_check())
        return c

    # ----- option sources -----
    def _joint_names(self):
        return [self._cell_text(self.joints_tbl, r, 0) for r in range(self.joints_tbl.rowCount())]

    def _segment_names(self):
        return [self._cell_text(self.segs_tbl, r, 0) for r in range(self.segs_tbl.rowCount())]

    def _point_options(self):
        return self._joint_names() + self._labels

    @staticmethod
    def _cell_text(table, r, c):
        w = table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, _ClusterButton):
            return ", ".join(w.value())
        it = table.item(r, c)
        return it.text().strip() if it else ""

    # ----- populate / collect -----
    def _populate(self, model):
        self._loading = True
        self.joints_tbl.setRowCount(0)
        for j in model.joints:
            self._add_joint(j)
        self.segs_tbl.setRowCount(0)
        for s in model.segments:
            self._add_segment(s)
        self.angles_tbl.setRowCount(0)
        for a in model.angles:
            self._add_angle(a)
        self._loading = False
        self._self_check()

    def _add_joint(self, j=None):
        j = j or {}
        r = self.joints_tbl.rowCount()
        self.joints_tbl.insertRow(r)
        name_item = QTableWidgetItem(j.get("name", f"JOINT{r+1}"))
        method = j.get("method")
        # Non-midpoint joints (hip regression; single "marker" landmark like the
        # SHOULDER acromion) have no editable medial/lateral cells: stash the
        # source dict so _collect can round-trip them unchanged.
        special = method in ("hip", "marker")
        if special:
            name_item.setData(Qt.ItemDataRole.UserRole, dict(j))
        self.joints_tbl.setItem(r, 0, name_item)
        if special:
            tag = "— (hip)" if method == "hip" else "— (marker)"
            for c in (1, 2):
                it = QTableWidgetItem(tag)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.joints_tbl.setItem(r, c, it)
        else:
            self.joints_tbl.setCellWidget(r, 1, self._combo(self._labels, j.get("medial", "")))
            self.joints_tbl.setCellWidget(r, 2, self._combo(self._labels, j.get("lateral", "")))
        self.joints_tbl.setCellWidget(r, 3, _ClusterButton(self._labels, j.get("cluster", []), self._self_check))

    def _add_segment(self, s=None):
        s = s or {}
        r = self.segs_tbl.rowCount()
        self.segs_tbl.insertRow(r)
        name_item = QTableWidgetItem(s.get("name", f"SEG{r+1}"))
        # Preserve the segment coordinate-system ``frame`` (for JCS angles) on the
        # row so a review/OK round-trip through the dialog keeps it.
        if s.get("frame"):
            name_item.setData(Qt.ItemDataRole.UserRole, dict(s))
        self.segs_tbl.setItem(r, 0, name_item)
        self.segs_tbl.setCellWidget(r, 1, self._combo(self._point_options(), s.get("proximal", "")))
        self.segs_tbl.setCellWidget(r, 2, self._combo(self._point_options(), s.get("distal", "")))

    def _add_angle(self, a=None):
        a = a or {}
        r = self.angles_tbl.rowCount()
        self.angles_tbl.insertRow(r)
        name_item = QTableWidgetItem(a.get("name", f"ANGLE{r+1}"))
        # Preserve ``mode``/``sequence`` (JCS) on the row so they survive a
        # review/OK round-trip.
        if a.get("mode"):
            name_item.setData(Qt.ItemDataRole.UserRole, dict(a))
        self.angles_tbl.setItem(r, 0, name_item)
        self.angles_tbl.setCellWidget(r, 1, self._combo(self._segment_names(), a.get("segment_a", "")))
        self.angles_tbl.setCellWidget(r, 2, self._combo(self._segment_names(), a.get("segment_b", "")))

    def _del_rows(self, table):
        for r in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(r)
        self._refresh_point_cells()
        self._refresh_segment_cells()
        self._self_check()

    # ----- auto-refresh dependent dropdowns -----
    def _on_joint_names_changed(self, *_):
        if self._loading:
            return
        self._refresh_point_cells()
        self._self_check()

    def _on_segment_names_changed(self, *_):
        if self._loading:
            return
        self._refresh_segment_cells()
        self._self_check()

    def _refresh_point_cells(self):
        pts = self._point_options()
        for r in range(self.segs_tbl.rowCount()):
            for c in (1, 2):
                cur = self._cell_text(self.segs_tbl, r, c)
                self.segs_tbl.setCellWidget(r, c, self._combo(pts, cur))

    def _refresh_segment_cells(self):
        segs = self._segment_names()
        for r in range(self.angles_tbl.rowCount()):
            for c in (1, 2):
                cur = self._cell_text(self.angles_tbl, r, c)
                self.angles_tbl.setCellWidget(r, c, self._combo(segs, cur))

    def _collect(self):
        joints = []
        for r in range(self.joints_tbl.rowCount()):
            name = self._cell_text(self.joints_tbl, r, 0)
            if not name:
                continue
            w = self.joints_tbl.cellWidget(r, 3)
            cluster = w.value() if isinstance(w, _ClusterButton) else []
            name_item = self.joints_tbl.item(r, 0)
            src = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
            # Preserve any non-midpoint joint method (hip regression, single
            # "marker" landmark like the SHOULDER acromion) from the source
            # model -- only midpoint joints expose editable medial/lateral cells.
            if src and src.get("method") in ("hip", "marker"):
                kept = dict(src)
                kept["name"], kept["cluster"] = name, cluster
                joints.append(kept)
            else:
                joints.append({"name": name, "method": "midpoint",
                               "medial": self._cell_text(self.joints_tbl, r, 1),
                               "lateral": self._cell_text(self.joints_tbl, r, 2),
                               "cluster": cluster})
        segments = []
        for r in range(self.segs_tbl.rowCount()):
            name = self._cell_text(self.segs_tbl, r, 0)
            if not name:
                continue
            seg = {"name": name,
                   "proximal": self._cell_text(self.segs_tbl, r, 1),
                   "distal": self._cell_text(self.segs_tbl, r, 2)}
            item = self.segs_tbl.item(r, 0)
            src = item.data(Qt.ItemDataRole.UserRole) if item else None
            if src and src.get("frame"):           # keep the SCS for JCS angles
                seg["frame"] = src["frame"]
            segments.append(seg)
        angles = []
        for r in range(self.angles_tbl.rowCount()):
            name = self._cell_text(self.angles_tbl, r, 0)
            if not name:
                continue
            ang = {"name": name,
                   "segment_a": self._cell_text(self.angles_tbl, r, 1),
                   "segment_b": self._cell_text(self.angles_tbl, r, 2)}
            item = self.angles_tbl.item(r, 0)
            src = item.data(Qt.ItemDataRole.UserRole) if item else None
            if src and src.get("mode"):             # keep JCS mode/sequence
                ang["mode"] = src["mode"]
                if src.get("sequence"):
                    ang["sequence"] = src["sequence"]
            angles.append(ang)
        return MarkerModel(joints=joints, segments=segments, angles=angles)

    # ----- task ("what motion?") picker -----
    def _build_task_row(self):
        """Top row: the 'Motion' picker. Internal parameters (Cardan sequence,
        per-joint offsets) are not exposed here -- the motion drives them. The left
        edge is aligned with the JOINTS/SEGMENTS/ANGLES group titles below."""
        from ui import style
        line = QHBoxLayout()
        # Match the JOINTS/SEGMENTS/ANGLES group-title x (group inset + title
        # left:10px) so "Motion" lines up with those headers.
        line.setContentsMargins(28, 0, 0, 0)
        prompt = QLabel("Motion")
        prompt.setStyleSheet(
            f"color:{style.TEXT_PRIMARY};font-weight:700;font-size:12px;")
        line.addWidget(prompt)
        self.task_combo = NoWheelComboBox()
        self.task_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for label, _key in TASK_CHOICES:
            self.task_combo.addItem(label)
        # Select the current task's label.
        cur_label = _KEY_TO_LABEL.get(self.result_task, _KEY_TO_LABEL[DEFAULT_TASK])
        self.task_combo.setCurrentIndex(max(0, self.task_combo.findText(cur_label)))
        self.task_combo.currentIndexChanged.connect(self._on_task_changed)
        line.addWidget(self.task_combo)
        line.addStretch(1)
        return line

    def _make_zero_check(self):
        """The 'Normalize to static pose' control: design A (checkmark checkbox),
        16px, teal. Placed under the ANGLES group title."""
        from ui import style
        chk = QCheckBox("Normalize to static pose")
        chk.setChecked(self._zero_to_static)
        check_img = os.path.join(
            os.path.dirname(__file__), "assets", "check_white.png").replace("\\", "/")
        # Override the app-wide minimal "tiny dot" indicator with a clearly visible
        # box + white checkmark, so the checked/unchecked state is obvious.
        chk.setStyleSheet(
            f"QCheckBox{{color:{style.TEXT_PRIMARY};spacing:7px;font-size:12px;}}"
            f"QCheckBox::indicator{{width:14px;height:14px;border-radius:0;"
            f"border:1.5px solid {style.BORDER};background:{style.BG_PANEL};}}"
            f"QCheckBox::indicator:hover{{border-color:{style.ACCENT_TEAL};}}"
            f"QCheckBox::indicator:checked{{background:{style.ACCENT_TEAL};"
            f"border-color:{style.ACCENT_TEAL};image:url({check_img});}}")
        chk.setToolTip(
            "Subtracts the joint angles measured during the static (neutral) pose, "
            "so dynamic angles are expressed relative to the subject's standing baseline.")
        chk.toggled.connect(self._on_zero_toggled)
        self.zero_check = chk
        return chk

    def _on_markers_toggled(self, checked):
        self.markers_btn.setText(
            ("▾ " if checked else "▸ ") + f"Calibration markers: {len(self._labels)}")
        self.markers_lbl.setVisible(bool(checked))

    def _current_task_key(self):
        idx = self.task_combo.currentIndex() if hasattr(self, "task_combo") else 0
        if 0 <= idx < len(TASK_CHOICES):
            return TASK_CHOICES[idx][1]
        return DEFAULT_TASK

    def _on_task_changed(self, *_):
        """Picking a new motion re-guesses the model with that task's rotation
        orders and resets the zero-to-standing checkbox to the task's default."""
        self.result_task = self._current_task_key()
        # Follow the new task's recommended zero default (walk/run on, else off).
        self._zero_to_static = bool(task_preset(self.result_task).get("static_offset"))
        self.zero_check.blockSignals(True)
        self.zero_check.setChecked(self._zero_to_static)
        self.zero_check.blockSignals(False)
        self._populate(auto_build_model(self._static, task=self.result_task))
        self._refresh_advanced()

    def _on_zero_toggled(self, checked):
        self._zero_to_static = bool(checked)

    # ----- advanced (collapsible, hidden by default) -----
    def _build_advanced(self):
        """A collapsed 'advanced settings' area. Beginners never open it; experts
        can peek at (and later override) the per-joint rotation order the task
        chose. Kept minimal on purpose."""
        from ui import style
        self.adv_btn = QPushButton("▸ Advanced")
        self.adv_btn.setCheckable(True)
        self.adv_btn.setChecked(False)
        self.adv_btn.setFlat(True)
        self.adv_btn.setStyleSheet(
            f"QPushButton{{text-align:left;color:{style.TEXT_MUTED};border:none;"
            f"padding:4px 0;font-size:11px;}}")
        self.adv_btn.toggled.connect(self._on_advanced_toggled)

        self.adv_box = QWidget()
        self.adv_box.setVisible(False)
        adv_lay = QVBoxLayout(self.adv_box)
        adv_lay.setContentsMargins(12, 0, 0, 0)
        adv_lay.setSpacing(8)
        self.adv_seq_lbl = QLabel("")
        self.adv_seq_lbl.setWordWrap(True)
        self.adv_seq_lbl.setStyleSheet(f"color:{style.TEXT_MUTED};font-size:11px;")
        adv_lay.addWidget(self.adv_seq_lbl)

        # Per-joint / per-angle construction detail (method + precision). Read-only,
        # generated generically from the model's own metadata so any joint type
        # (lower OR upper limb) added later shows up without hard-coding.
        self.adv_detail_lbl = QLabel("")
        self.adv_detail_lbl.setWordWrap(True)
        self.adv_detail_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.adv_detail_lbl.setStyleSheet(
            f"color:{style.TEXT_MUTED};font-size:11px;")
        adv_lay.addWidget(self.adv_detail_lbl)

    def _on_advanced_toggled(self, checked):
        self.adv_btn.setText(("▾ " if checked else "▸ ") + "Advanced")
        self.adv_box.setVisible(bool(checked))

    def _refresh_advanced(self):
        """Show, read-only, the rotation order the chosen task applied per joint
        plus a per-joint/per-angle construction breakdown (method + precision).
        This is the only 'jargon' in the dialog and it is buried under Advanced."""
        if not hasattr(self, "adv_seq_lbl"):
            return
        preset = task_preset(self.result_task)
        seq = preset.get("sequence", {})
        parts = [f"{base}: {seq.get(base, 'xyz')}" for base in ("HIP", "KNEE", "ANKLE")]
        self.adv_seq_lbl.setText(
            "Cardan sequence (per joint): " + ",  ".join(parts)
            + "\nSet automatically by motion.")
        self._refresh_advanced_detail()

    # --- per-joint / per-angle construction detail (read-only, generic) -------
    @staticmethod
    def _joint_method_desc(j):
        """Human-readable construction method for one joint dict. Reads the
        engine's ``method`` field (hip / midpoint / marker) generically and falls
        back to '—' when the metadata is missing."""
        method = j.get("method")
        if method == "hip":
            # Harrington (2007) pelvis-width/-depth regression off the ASIS pair
            # + PSIS/sacrum.
            post = "PSIS pair" if (j.get("psis_l") and j.get("psis_r")) else (
                "sacrum" if j.get("sacrum") else "—")
            return f"Harrington hip regression (ASIS pair + {post})"
        if method == "marker":
            land = j.get("landmark") or "—"
            return f"single marker landmark ({land})"
        if method == "midpoint":
            med = j.get("medial") or "—"
            lat = j.get("lateral") or "—"
            return f"midpoint(medial={med}, lateral={lat})"
        return "—"

    @staticmethod
    def _angle_mode_desc(a):
        """Human-readable angle computation for one angle dict. Reads ``mode`` /
        ``sequence`` generically; missing metadata -> graceful fallback."""
        mode = a.get("mode", "vector")
        if mode == "jcs":
            seq = a.get("sequence", "xyz")
            return f"JCS 3-component (Cardan/Grood-Suntay, sequence {seq})"
        return "vector angle (unsigned, single component)"

    def _refresh_advanced_detail(self):
        """Rebuild the per-joint/per-angle construction summary from the model the
        dialog currently holds. Built by collecting the live tables, so it tracks
        edits and task-driven rebuilds. Generic over joint/segment/angle type:
        upper-limb joints added elsewhere appear automatically."""
        if not hasattr(self, "adv_detail_lbl"):
            return
        try:
            model = self._collect()
        except Exception:
            model = None

        if model is None or (not model.joints and not model.angles):
            self.adv_detail_lbl.setText(
                "Construction detail: (no joints/angles defined yet)")
            return

        lines = ["Construction detail (auto-generated method · precision):"]

        if model.joints:
            lines.append("\nJoint centres:")
            for j in model.joints:
                name = j.get("name") or "—"
                lines.append(f"  • {name}: {self._joint_method_desc(j)}")

        # Map segment name -> whether it carries a coordinate-system frame, so the
        # angle lines can note which segments support a signed JCS angle.
        framed = {s.get("name"): bool(s.get("frame")) for s in model.segments}

        if model.angles:
            lines.append("\nJoint angles:")
            for a in model.angles:
                name = a.get("name") or "—"
                detail = self._angle_mode_desc(a)
                sa, sb = a.get("segment_a"), a.get("segment_b")
                # Note when a JCS angle's segments lack frames (would fall back to
                # a vector angle at compute time) so the precision is honest.
                if a.get("mode") == "jcs" and not (framed.get(sa) and framed.get(sb)):
                    detail += " — segment frame(s) missing"
                lines.append(f"  • {name} ({sa} → {sb}): {detail}")

        self.adv_detail_lbl.setText("\n".join(lines))

    # ----- actions -----
    def _auto_map(self):
        self._populate(auto_build_model(self._static, task=self.result_task))
        self._refresh_advanced()

    def _self_check(self):
        if self._loading:
            return
        try:
            model = self._collect()
            if not model.joints:
                self.check_lbl.setText("Joint-centre accuracy: — (no joints defined)")
                self.check_lbl.setStyleSheet("color:#7A8591;")
                return
            model.calibrate(self._static)
            err = model.calibration_selfcheck(self._static)
            ok = err < 10.0
            self.check_lbl.setText(
                f"Joint-centre accuracy: {err:.2f} mm  "
                f"{'✓ good (lower is better)' if ok else '⚠ high — check cluster / medial-lateral'}")
            self.check_lbl.setStyleSheet("color:#2ECC71;" if ok else "color:#F39C12;")
        except Exception as exc:
            self.check_lbl.setText(f"Joint-centre accuracy: — ({exc})")
            self.check_lbl.setStyleSheet("color:#EF5B5B;")

    def _on_ok(self):
        model = self._collect()
        if not model.joints:
            QMessageBox.information(self, "No joints", "Define at least one joint.")
            return
        try:
            model.calibrate(self._static)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid model", f"Calibration failed:\n{exc}")
            return
        self.result_model = model
        self.result_task = self._current_task_key()
        self.result_zero_to_static = bool(self.zero_check.isChecked())
        self.accept()
