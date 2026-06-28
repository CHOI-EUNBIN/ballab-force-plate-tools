"""Contract tests for the cascading signal picker widget.

The picker replaces the single grouped signal combo in the step dialogs. Its
public contract is purely in CATALOG KEYS: feed it the ``[(key, label)]`` catalog
the old combo got, drill the cascade, and read/write the same keys via
``selected_key()`` / ``set_key()``. These tests pin that contract so a future
refactor of the cascade internals can't silently break the dialogs.

Headless (offscreen Qt); skipped cleanly if Qt is unavailable.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


CATALOG = [
    ("time", "Time (s)"),
    ("cop", "COP"), ("cop_ap", "COP X"), ("cop_ml", "COP Y"),
    ("fz", "Fz"), ("fx", "Fx"), ("fy", "Fy"),
    ("fp2:cop", "FP2 COP"), ("fp2:fz", "FP2 Fz"),
    ("angle:R_KNEE_angle_FE", "x"), ("angle:R_KNEE_angle_AB", "x"),
    ("angle:L_ANKLE_angle_FE", "x"), ("angle:L_ANKLE_angle_AB", "x"),
    ("marker:RHEEL:X", "x"), ("marker:RHEEL:Y", "x"), ("marker:RHEEL:Z", "x"),
    ("cop_ap:filt", "COP X (filtered)"),
    ("abs_fz", "abs_fz"),
]


def _picker(app, keys=CATALOG):
    from ui.components.cascading_signal_picker import CascadingSignalPicker
    return CascadingSignalPicker(keys=keys)


def _select_cat(p, text):
    for i in range(p.cat_combo.count()):
        if p.cat_combo.itemText(i) == text:
            p.cat_combo.setCurrentIndex(i)
            return
    raise AssertionError(f"category {text!r} not present")


def _select_sub(p, data):
    i = p._find_data(p.sub_combo, data)
    assert i >= 0, f"sub {data!r} not present"
    p.sub_combo.setCurrentIndex(i)


def _select_leaf(p, text):
    for i in range(p.leaf_combo.count()):
        if p.leaf_combo.itemText(i) == text:
            p.leaf_combo.setCurrentIndex(i)
            return
    raise AssertionError(f"leaf {text!r} not present")


def test_categories_in_clinical_order(app):
    p = _picker(app)
    cats = [p.cat_combo.itemText(i) for i in range(p.cat_combo.count())]
    assert cats == ["Force Plate 1", "Force Plate 2", "Joint angles",
                    "Markers", "Processed", "Derived"]


def test_force_plate_drilldown(app):
    p = _picker(app)
    _select_cat(p, "Force Plate 1")
    subs = [p.sub_combo.itemText(i) for i in range(p.sub_combo.count())]
    assert subs == ["COP", "COP X", "COP Y", "Fz", "Fx", "Fy"]
    _select_sub(p, "cop")
    assert p.selected_key() == "cop"
    _select_cat(p, "Force Plate 2")
    _select_sub(p, "fp2:fz")
    assert p.selected_key() == "fp2:fz"


def test_angle_drilldown_sided_and_planes(app):
    p = _picker(app)
    _select_cat(p, "Joint angles")
    subs = [p.sub_combo.itemText(i) for i in range(p.sub_combo.count())]
    assert "R Knee" in subs and "L Ankle" in subs
    _select_sub(p, "R_KNEE")
    planes = [p.leaf_combo.itemText(i) for i in range(p.leaf_combo.count())]
    assert planes == ["F/E", "AB/ADD"]
    _select_leaf(p, "AB/ADD")
    assert p.selected_key() == "angle:R_KNEE_angle_AB"
    # ankle uses Dorsi/Plantar + Inv/Ever wording
    _select_sub(p, "L_ANKLE")
    planes = [p.leaf_combo.itemText(i) for i in range(p.leaf_combo.count())]
    assert planes == ["Dorsi/Plantar", "Inv/Ever"]
    _select_leaf(p, "Inv/Ever")
    assert p.selected_key() == "angle:L_ANKLE_angle_AB"


def test_marker_drilldown_axes(app):
    p = _picker(app)
    _select_cat(p, "Markers")
    _select_sub(p, "RHEEL")
    axes = [p.leaf_combo.itemText(i) for i in range(p.leaf_combo.count())]
    assert axes == ["X", "Y", "Z"]
    _select_leaf(p, "Z")
    assert p.selected_key() == "marker:RHEEL:Z"


def test_processed_and_derived_are_flat(app):
    p = _picker(app)
    _select_cat(p, "Processed")
    assert p.selected_key() == "cop_ap:filt"
    _select_cat(p, "Derived")
    keys = [p.sub_combo.itemData(i) for i in range(p.sub_combo.count())]
    assert "abs_fz" in keys and "time" in keys


@pytest.mark.parametrize("key", [
    "cop", "fp2:fz", "angle:R_KNEE_angle_FE", "angle:L_ANKLE_angle_AB",
    "marker:RHEEL:Y", "cop_ap:filt", "abs_fz", "time",
])
def test_set_key_round_trips(app, key):
    p = _picker(app)
    p.set_key(key)
    assert p.selected_key() == key


def test_set_key_ignores_unknown(app):
    p = _picker(app)
    p.set_key("cop")
    p.set_key("not_a_real_key")   # stale/absent key -> no change, no crash
    assert p.selected_key() == "cop"


def test_changed_signal_fires(app):
    p = _picker(app)
    seen = []
    p.changed.connect(lambda s: seen.append(s))
    p.set_key("fp2:fz")
    assert seen and seen[-1] == "fp2:fz"


def test_empty_catalog_fallback(app):
    p = _picker(app, keys=[])
    assert p.selected_key() is None


def test_keys_returns_catalog_keys(app):
    p = _picker(app)
    assert p.keys() == [k for k, _ in CATALOG]
