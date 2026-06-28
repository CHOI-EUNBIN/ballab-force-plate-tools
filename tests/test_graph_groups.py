"""Figure-group logic for the Analyze tab's combine-target feature.

Signals (joint angles and produced force/COP/derived views) can be combined into
a chosen figure, within their own type. These headless tests pin the grouping
math: new-vs-add gives the right ids, same-type isolation, legacy migration,
deletion, and save/load round-trip. They drive the pure helpers (no rendering).
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


@pytest.fixture
def tab(app):
    from ui.analyze_tab import AnalyzeTab
    return AnalyzeTab()


# --- angle figures ---------------------------------------------------------

def test_angle_new_figures_get_unique_ids(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    tab._angle_to_new_figure("L_KNEE_angle_FE")
    g1 = tab._angle_plots["R_KNEE_angle_FE"]
    g2 = tab._angle_plots["L_KNEE_angle_FE"]
    assert isinstance(g1, int) and isinstance(g2, int) and g1 != g2


def test_angle_add_to_group_shares_one_figure(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    gid = tab._angle_plots["R_KNEE_angle_FE"]
    tab._angle_to_group("L_KNEE_angle_FE", gid)
    avail = {"R_KNEE_angle_FE": 1, "L_KNEE_angle_FE": 1}
    figs = tab._angle_figures(avail)
    assert figs == [(gid, ["L_KNEE_angle_FE", "R_KNEE_angle_FE"])]   # one figure


def test_angle_figures_respect_avail(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    tab._angle_to_new_figure("R_HIP_angle_FE")
    # only the available channel surfaces as a figure
    figs = tab._angle_figures({"R_KNEE_angle_FE": 1})
    assert [names for _g, names in figs] == [["R_KNEE_angle_FE"]]


# --- signal figures --------------------------------------------------------

def test_signal_view_figures_group_by_id(tab):
    from core.signals import FILT_SUFFIX
    tab._signal_views = {"fp1:fz", f"fp1:fz{FILT_SUFFIX}", "cop_ap"}
    tab._signal_groups = {"fp1:fz": 5, "cop_ap": 5}
    tab._next_group_id = 6
    figs = tab._signal_view_figures()
    assert figs == [(5, ["cop_ap", "fp1:fz"])]   # ":filt" reduced to parent, grouped


def test_signal_group_id_defaults_to_own_figure(tab):
    tab._signal_views = {"a", "b"}
    figs = tab._signal_view_figures()
    gids = [g for g, _ in figs]
    assert len(figs) == 2 and len(set(gids)) == 2   # each its own figure by default


# --- same-type isolation ---------------------------------------------------

def test_angle_and_signal_groups_are_separate(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    tab._signal_views = {"fp1:fz"}
    angle_figs = tab._angle_figures({"R_KNEE_angle_FE": 1})
    sig_figs = tab._signal_view_figures()
    # an angle figure never contains a signal key and vice-versa
    assert all("fp" not in n for _g, names in angle_figs for n in names)
    assert all(k.startswith("fp") for _g, keys in sig_figs for k in keys)


# --- legacy migration ------------------------------------------------------

def test_legacy_string_modes_migrate_to_ids(tab):
    tab._angle_plots = {"a": "combined", "b": "combined", "c": "separate"}
    figs = tab._angle_figures()        # triggers migration
    by_id = {g: names for g, names in figs}
    # the two "combined" share one figure; "separate" stands alone
    combined = [names for names in by_id.values() if names == ["a", "b"]]
    assert combined == [["a", "b"]]
    assert ["c"] in by_id.values()
    assert all(isinstance(v, int) for v in tab._angle_plots.values())


# --- deletion --------------------------------------------------------------

def test_delete_all_clears_every_group(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    tab._signal_views = {"fp1:fz"}
    tab._signal_groups = {"fp1:fz": 9}
    tab._delete_all_graphs()
    assert tab._angle_plots == {} and tab._signal_views == set()
    assert tab._signal_groups == {}


# --- persistence -----------------------------------------------------------

def test_figure_groups_round_trip(tab):
    tab._angle_to_new_figure("R_KNEE_angle_FE")
    tab._angle_to_group("L_KNEE_angle_FE", tab._angle_plots["R_KNEE_angle_FE"])
    tab._signal_views = {"fp1:fz"}
    tab._signal_groups = {"fp1:fz": 7}
    tab._next_group_id = 50
    saved = tab._figure_groups_for_save()

    from ui.analyze_tab import AnalyzeTab
    other = AnalyzeTab()
    other._restore_figure_groups(saved)
    assert other._angle_plots == tab._angle_plots
    assert other._signal_groups == {"fp1:fz": 7}
    # next id stays above every restored id so new figures never collide
    assert other._next_group_id > max(list(other._angle_plots.values()) + [7])
