"""Cascading (multi-level) signal picker — replaces the single grouped combo.

The old signal pickers put every channel of a dataset into ONE combo box,
grouped under non-selectable header rows. With many markers + per-plate force +
both-sided joint angles that list grows to dozens of rows, and the user has to
scroll past headers to find a channel. This widget breaks that one combo into a
short CASCADE of dependent combos — the same idea Visual3D / EMG tools use:

    Category  ->  (Channel)  ->  (Axis / Plane)

Level 1 (always shown) = Category:
    Markers / Force Plate 1 / Force Plate 2 … / Joint angles /
    Processed (filtered twins) / Derived (Compute outputs, COP path, …).

Level 2 (depends on category):
    Force Plate N  -> COP, COP X, COP Y, Fz, Fx, Fy   (the comps that exist)
    Markers        -> the marker labels
    Joint angles   -> the (sided) joint, e.g. "L Knee" / "R Knee" / "Ankle"
    Processed      -> the filtered signals (flat — already specific)
    Derived        -> the derived signals (flat)

Level 3 (only Markers / Joint angles):
    Markers        -> axis X / Y / Z
    Joint angles   -> plane (F/E, AB/ADD, IR/ER; ankle = Dorsi/Plantar, Inv/Ever)

The widget is fed exactly the same ``[(key, label)]`` catalog the old combo got
(already plate-labelled by ``signal_catalog``); it parses those keys to build the
cascade, and its public contract is purely in CATALOG KEYS:

    selected_key()  -> the catalog key the user has drilled down to (or None)
    set_key(key)    -> restore the cascade to show an existing key (step edit)
    keys()          -> the flat list of selectable keys it was given

So callers (the step dialogs) never deal with the cascade internals — they read
and write the very keys they already used with the flat combo, e.g. ``"cop"``,
``"fp2:fz"``, ``"angle:R_KNEE_angle_FE"``, ``"marker:RHEEL:X"``,
``"cop_ap:filt"``, or a ComputeStep output name.

L/R handling (design choice): joint angles are listed in level 2 as SIDED
joints ("L Knee", "R Knee", "L Ankle" …). This mirrors ``angle_label`` (which
already prints the side as a leading letter), keeps the cascade to three combos
(no extra side toggle to wire), and lets an unsided/vector angle simply appear
as its own level-2 row. The level-3 plane combo then offers only the planes that
actually exist for the chosen sided joint.

Pure-Qt, headless-constructible (no dataset, no parent tab needed) so the
selection contract is unit-testable without a running app.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from core.signals import FILT_SUFFIX, label_for
from ui.components.wheel_guard import guard_widget

# --- category identifiers (internal; never shown verbatim) -------------------
_CAT_MARKERS = "markers"
_CAT_ANGLES = "angles"
_CAT_PROCESSED = "processed"
_CAT_DERIVED = "derived"
# Force plates are dynamic: ``("fp", n)``.

#: Order force/COP comps appear in a plate's level-2 combo, with their labels.
_PLATE_COMP_ORDER = [
    ("cop", "COP"),
    ("cop_ap", "COP X"),
    ("cop_ml", "COP Y"),
    ("fz", "Fz"),
    ("fx", "Fx"),
    ("fy", "Fy"),
]
_PLATE_BARE = {"cop", "cop_ap", "cop_ml", "fz", "fx", "fy"}

#: JCS angle component suffix -> the two plane labels (general vs ankle). The
#: ankle reads sagittal as Dorsi/Plantar and frontal as Inv/Ever; everything
#: else uses the generic clinical planes. Matches ``core.marker_model``.
_PLANE_LABELS = {
    "FE": ("F/E", "Dorsi/Plantar"),     # (generic, ankle)
    "AB": ("AB/ADD", "Inv/Ever"),
    "IE": ("IR/ER", "IR/ER"),
}
_PLANE_ORDER = ("FE", "AB", "IE")


def _is_plate_key(key):
    """``(plate:int, comp:str)`` for a force/COP key, else ``(None, None)``.

    Bare ``cop``/``fz``/… count as plate 1 (mirrors ``_signal_group_of``).
    """
    if key.startswith("fp"):
        head, _, comp = key.partition(":")
        num = head[2:]
        if comp in _PLATE_BARE and num.isdigit():
            return int(num), comp
        return None, None
    if key in _PLATE_BARE:
        return 1, key
    return None, None


def _parse_angle(name):
    """Split a JCS angle channel ``name`` into ``(sided_joint, plane_suffix)``.

    ``R_KNEE_angle_FE`` -> ``("R_KNEE", "FE")``. Returns ``(name, None)`` for a
    name that is not a JCS component (no ``_angle_<FE|AB|IE>`` suffix) — that
    angle then has no plane level (it is selected at level 2 alone).
    """
    for suf in _PLANE_ORDER:
        tail = f"_angle_{suf}"
        if name.endswith(tail):
            return name[: -len(tail)], suf
    return name, None


def _sided_joint_label(joint_token):
    """Human label for an angle's sided-joint token, e.g. ``R_KNEE`` -> "R Knee".

    Side letter kept (self-evident, per the angle_label convention); joint
    title-cased. A token with no recognisable side just title-cases through.
    """
    up = joint_token.upper()
    if up[:2] in ("R_", "L_"):
        return f"{up[0]} {joint_token[2:].replace('_', ' ').title()}"
    return joint_token.replace("_", " ").title()


def _is_ankle(joint_token):
    return "ANKLE" in joint_token.upper()


class CascadingSignalPicker(QWidget):
    """A row of dependent combos that resolves to one catalog signal key.

    Drop-in for the old single grouped combo: build it, call :meth:`set_keys`
    with the ``[(key,label)]`` catalog (or pass ``keys=`` to the constructor),
    then read :meth:`selected_key` / write :meth:`set_key`. Emits
    :data:`changed` whenever the resolved key changes (so a dialog can re-sync
    units / op lists exactly like it did on the combo's ``currentIndexChanged``).
    """

    #: Emitted with the new catalog key (str or "") after any sub-combo changes.
    changed = pyqtSignal(str)

    def __init__(self, parent=None, keys=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.cat_combo = QComboBox()
        self.sub_combo = QComboBox()      # level 2 (channel / marker / joint)
        self.leaf_combo = QComboBox()     # level 3 (axis / plane)
        for c in (self.cat_combo, self.sub_combo, self.leaf_combo):
            c.setObjectName("signal-combo")
            guard_widget(c)
            lay.addWidget(c, 1)

        # Re-entrancy guard: rebuilding child combos fires their signals, which
        # would otherwise emit half-built selections. We emit once at the end.
        self._building = False

        self.cat_combo.currentIndexChanged.connect(self._on_category_changed)
        self.sub_combo.currentIndexChanged.connect(self._on_sub_changed)
        self.leaf_combo.currentIndexChanged.connect(self._on_leaf_changed)

        # Whether level 3 currently carries the resolved key. Tracked explicitly
        # (not via leaf_combo.isVisible(), which is False until the whole window
        # is shown — that broke selected_key() headless and before first paint).
        self._leaf_active = False

        # Internal parsed model, built by set_keys():
        #   self._keys        = ordered flat list of catalog keys (the contract)
        #   self._cats        = ordered [(cat_id, label)]
        #   self._subs[cat]   = ordered [(sub_id, label)]
        #   self._leaves[(cat, sub)] = ordered [(key, leaf_label)]
        #   flat cats (Processed/Derived) store the key as the sub_id and have
        #   no leaves; plate/marker/angle cats drill to a leaf key.
        self._keys = []
        self.set_keys(keys or [])

    # -- public contract ------------------------------------------------------
    def keys(self):
        """The flat list of selectable catalog keys this picker was given."""
        return list(self._keys)

    def set_keys(self, items):
        """(Re)build the cascade from a ``[(key, label)]`` catalog list.

        ``label`` is ignored for parsing (labels are re-derived for a clean,
        cascade-appropriate form); it is accepted so the call site can pass the
        exact list it gave the old combo. Empty/None -> an empty picker whose
        :meth:`selected_key` is ``None`` (the no-dataset fallback)."""
        self._keys = [k for k, _ in (items or [])]
        self._build_model(items or [])
        self._building = True
        self.cat_combo.clear()
        for cat_id, label in self._cats:
            self.cat_combo.addItem(label, cat_id)
        self._building = False
        # Select the first category (rebuilds sub/leaf) and emit once.
        if self._cats:
            self.cat_combo.setCurrentIndex(0)
            self._rebuild_sub(emit=False)
        else:
            self.sub_combo.clear()
            self.leaf_combo.clear()
            self.sub_combo.setVisible(False)
            self.leaf_combo.setVisible(False)
        self.changed.emit(self.selected_key() or "")

    def selected_key(self):
        """The catalog key the cascade currently resolves to, or ``None``.

        For a flat category (Processed/Derived/an angle/marker with no leaf) the
        key is the level-2 ``itemData``; for a plate/marker/angle with a leaf the
        key is the level-3 ``itemData``. ``None`` when the picker is empty."""
        cat = self.cat_combo.currentData()
        if cat is None:
            return None
        if self._leaf_active and self.leaf_combo.count():
            return self.leaf_combo.currentData()
        return self.sub_combo.currentData()

    def prefer_filtered_default(self):
        """If the currently-selected key has a ``:filt`` twin in the catalog,
        select the twin instead. Call this when authoring a NEW step so an active
        marker/COP/force FilterStep flows in by default rather than being silently
        ignored on the raw key. No-op when already filtered or no twin exists; the
        user can still pick the raw key manually."""
        cur = self.selected_key()
        if cur and not cur.endswith(":filt"):
            twin = cur + ":filt"
            if twin in self._keys:
                self.set_key(twin)

    def set_key(self, key):
        """Drive the cascade to display catalog ``key`` (step-edit restore).

        Walks category -> sub -> leaf to the combo entries carrying ``key``. A
        key not present in the current catalog is ignored (cascade unchanged), so
        restoring a stale saved key fails soft. Signals are blocked during the
        walk and a single :data:`changed` is emitted at the end."""
        if not key or key not in self._keys:
            return
        target_cat, target_sub = self._locate(key)
        if target_cat is None:
            return
        self._building = True
        ci = self._find_data(self.cat_combo, target_cat)
        if ci >= 0:
            self.cat_combo.setCurrentIndex(ci)
        self._rebuild_sub(emit=False)
        si = self._find_data(self.sub_combo, target_sub)
        if si >= 0:
            self.sub_combo.setCurrentIndex(si)
        self._rebuild_leaf(emit=False)
        if self._leaf_active and self.leaf_combo.count():
            li = self._find_data(self.leaf_combo, key)
            if li >= 0:
                self.leaf_combo.setCurrentIndex(li)
        self._building = False
        self.changed.emit(self.selected_key() or "")

    @staticmethod
    def _find_data(combo, data):
        """Index of the combo entry whose itemData equals ``data``, else -1.

        ``QComboBox.findData`` is unreliable for non-primitive itemData (a tuple
        category id like ``("fp", 1)`` does not round-trip through Qt's QVariant
        comparison), so we compare in Python."""
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                return i
        return -1

    # -- model building -------------------------------------------------------
    def _build_model(self, items):
        """Parse the catalog into the cascade model (cats / subs / leaves)."""
        self._cats = []
        self._subs = {}
        self._leaves = {}
        cat_order = []

        def _ensure_cat(cat_id, label):
            if cat_id not in self._subs:
                self._subs[cat_id] = []
                cat_order.append((cat_id, label))

        def _ensure_sub(cat_id, sub_id, label):
            subs = self._subs[cat_id]
            if not any(s == sub_id for s, _ in subs):
                subs.append((sub_id, label))

        for key, _label in items:
            if key.endswith(FILT_SUFFIX):
                _ensure_cat(_CAT_PROCESSED, "Processed")
                _ensure_sub(_CAT_PROCESSED, key, label_for(key))
                continue
            plate, comp = _is_plate_key(key)
            if plate is not None:
                cat_id = ("fp", plate)
                _ensure_cat(cat_id, f"Force Plate {plate}")
                lbl = dict(_PLATE_COMP_ORDER).get(comp, comp)
                _ensure_sub(cat_id, key, lbl)
                continue
            if key.startswith("angle:"):
                _ensure_cat(_CAT_ANGLES, "Joint angles")
                name = key.split(":", 1)[1]
                joint, plane = _parse_angle(name)
                _ensure_sub(_CAT_ANGLES, joint, _sided_joint_label(joint))
                self._leaves.setdefault((_CAT_ANGLES, joint), [])
                if plane is not None:
                    generic, ankle = _PLANE_LABELS[plane]
                    leaf_label = ankle if _is_ankle(joint) else generic
                    self._leaves[(_CAT_ANGLES, joint)].append((key, leaf_label))
                else:
                    # vector / unsided angle: the joint row IS the leaf.
                    self._leaves[(_CAT_ANGLES, joint)].append((key, "Angle"))
                continue
            if key.startswith("marker:"):
                _ensure_cat(_CAT_MARKERS, "Markers")
                body = key[len("marker:"):]
                mlabel, axis = body.rsplit(":", 1)
                _ensure_sub(_CAT_MARKERS, mlabel, mlabel)
                self._leaves.setdefault((_CAT_MARKERS, mlabel), [])
                self._leaves[(_CAT_MARKERS, mlabel)].append((key, axis))
                continue
            # Anything else (Compute outputs, COP path, time, unknown) -> Derived.
            _ensure_cat(_CAT_DERIVED, "Derived")
            _ensure_sub(_CAT_DERIVED, key, label_for(key))

        # Category display order: force plates (by number) first, then angles,
        # markers, processed, derived — a fixed clinical priority, NOT the order
        # categories happened to first appear in the catalog (otherwise "time"
        # landing in Derived would push Derived to the front).
        def _cat_rank(item):
            cat_id, _label = item
            if isinstance(cat_id, tuple) and cat_id[0] == "fp":
                return (0, cat_id[1])
            return ({_CAT_ANGLES: 1, _CAT_MARKERS: 2,
                     _CAT_PROCESSED: 3, _CAT_DERIVED: 4}.get(cat_id, 5), 0)
        cat_order.sort(key=_cat_rank)

        # Plate comps come out of the catalog already in a sensible order; for a
        # plate we re-sort its subs to the canonical COP→force order so the combo
        # always reads the same way regardless of file storage order.
        order_idx = {c: i for i, (c, _) in enumerate(_PLATE_COMP_ORDER)}
        for cat_id, subs in self._subs.items():
            if isinstance(cat_id, tuple) and cat_id[0] == "fp":
                def _rank(item):
                    _, comp = _is_plate_key(item[0])
                    return order_idx.get(comp, 99)
                subs.sort(key=_rank)
        self._cats = cat_order

    def _locate(self, key):
        """``(cat_id, sub_id)`` whose drill-down contains catalog ``key``."""
        if key.endswith(FILT_SUFFIX):
            return _CAT_PROCESSED, key
        plate, _comp = _is_plate_key(key)
        if plate is not None:
            return ("fp", plate), key
        if key.startswith("angle:"):
            joint, _plane = _parse_angle(key.split(":", 1)[1])
            return _CAT_ANGLES, joint
        if key.startswith("marker:"):
            body = key[len("marker:"):]
            mlabel, _axis = body.rsplit(":", 1)
            return _CAT_MARKERS, mlabel
        return _CAT_DERIVED, key

    # -- cascade rebuild on selection -----------------------------------------
    def _has_leaves(self, cat_id):
        """True if this category drills to a level-3 leaf (markers / angles)."""
        return cat_id in (_CAT_MARKERS, _CAT_ANGLES)

    def _rebuild_sub(self, emit=True):
        """Repopulate level-2 for the current category, then rebuild level-3."""
        cat = self.cat_combo.currentData()
        was_building = self._building
        self._building = True
        self.sub_combo.clear()
        subs = self._subs.get(cat, [])
        for sub_id, label in subs:
            self.sub_combo.addItem(label, sub_id)
        # Level 2 is hidden only when a category has a single anonymous entry —
        # but we always keep it shown for clarity; only hide if there are none.
        self.sub_combo.setVisible(bool(subs))
        if subs:
            self.sub_combo.setCurrentIndex(0)
        self._building = was_building
        self._rebuild_leaf(emit=emit)

    def _rebuild_leaf(self, emit=True):
        """Repopulate level-3 for the current (category, sub); hide if none."""
        cat = self.cat_combo.currentData()
        sub = self.sub_combo.currentData()
        was_building = self._building
        self._building = True
        self.leaf_combo.clear()
        leaves = []
        if self._has_leaves(cat):
            leaves = self._leaves.get((cat, sub), [])
        # A single "Angle" leaf (vector/unsided joint) carries the key but adds no
        # information — still show it so selected_key resolves, but it reads fine.
        for key, label in leaves:
            self.leaf_combo.addItem(label, key)
        self._leaf_active = bool(leaves)
        self.leaf_combo.setVisible(bool(leaves))
        if leaves:
            self.leaf_combo.setCurrentIndex(0)
        self._building = was_building
        if emit and not self._building:
            self.changed.emit(self.selected_key() or "")

    # -- slots ----------------------------------------------------------------
    def _on_category_changed(self):
        if self._building:
            return
        self._rebuild_sub(emit=True)

    def _on_sub_changed(self):
        if self._building:
            return
        self._rebuild_leaf(emit=True)

    def _on_leaf_changed(self):
        if self._building:
            return
        self.changed.emit(self.selected_key() or "")
