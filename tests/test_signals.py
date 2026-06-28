"""Regression tests for core.signals (the signal registry).

Pins the stable key scheme and the resampling-onto-master-clock behaviour that
events and the future pipeline rely on.
"""

import numpy as np
import pytest

from core.signals import label_for, signal_catalog, signal_series, unit_for


def _dataset(n=10):
    t = np.arange(n) / 100.0
    return {
        "time": t,
        "cop_ap": np.arange(n, dtype=float),
        "cop_ml": np.zeros(n),
        "fz": np.ones(n),
        "fx": np.full(n, 2.0),
        "fy": np.full(n, 3.0),
    }


def _multi_plate_dataset(n=10):
    """A two-force-plate dataset: bare keys = plate 1, plus fp1/fp2 signals."""
    ds = _dataset(n)
    ds["n_force_plates"] = 2
    keys = []
    for p, scale in ((1, 1.0), (2, 2.0)):
        for comp, base in (("fx", 2.0), ("fy", 3.0), ("fz", 1.0),
                           ("cop_ap", 0.0), ("cop_ml", 0.0)):
            key = f"fp{p}:{comp}"
            ds[key] = np.full(n, base * scale)
            keys.append(key)
    ds["fp1:cop_ap"] = np.arange(n, dtype=float)      # match bare cop_ap
    ds["fp2:cop_ap"] = np.arange(n, dtype=float) * 2
    ds["force_signal_keys"] = keys
    return ds


def test_catalog_force_only_keys():
    ds = _dataset()
    keys = [k for k, _ in signal_catalog(ds)]
    assert keys == ["time", "cop", "cop_ap", "cop_ml", "fz", "fx", "fy"]


def test_single_plate_has_no_fp_keys():
    """A normal (single-plate) dataset never grows fp:* clutter — no regression."""
    ds = _dataset()
    keys = [k for k, _ in signal_catalog(ds)]
    assert not any(k.startswith("fp") for k in keys)


def test_catalog_lists_per_plate_signals():
    ds = _multi_plate_dataset()
    keys = [k for k, _ in signal_catalog(ds)]
    # Bare keys still come first; per-plate groups follow (COP resultant first).
    for k in ("fp1:cop", "fp1:cop_ap", "fp1:fz", "fp2:cop", "fp2:cop_ap", "fp2:fz"):
        assert k in keys
    assert keys.index("fz") < keys.index("fp1:cop")


def test_per_plate_labels_and_units():
    assert label_for("fp2:cop_ap") == "FP2 COP X"
    assert label_for("fp2:cop_ml") == "FP2 COP Y"
    assert label_for("fp1:fz") == "FP1 Fz"
    assert label_for("fp2:cop") == "FP2 COP"
    assert unit_for("fp2:fz") == "N"
    assert unit_for("fp2:cop_ap") == "mm"
    assert unit_for("fp2:cop") == "mm"


def test_per_plate_series_and_resultant():
    ds = _multi_plate_dataset()
    np.testing.assert_array_equal(signal_series(ds, "fp2:fz"), ds["fp2:fz"])
    # fp{n}:cop is the mean-subtracted resultant of that plate's AP/ML.
    out = signal_series(ds, "fp2:cop")
    ap = ds["fp2:cop_ap"]; ml = ds["fp2:cop_ml"]
    exp = np.sqrt((ap - ap.mean()) ** 2 + (ml - ml.mean()) ** 2)
    np.testing.assert_allclose(out, exp)


def test_catalog_includes_markers_and_angles():
    ds = _dataset()
    md = np.zeros((1, 2, 3))
    ds["markers"] = {"labels": ["A"], "data": md, "time": np.array([0.0, 0.09])}
    angle_result = {"angles": {"KNEE": np.zeros(10)}, "time": ds["time"]}
    keys = [k for k, _ in signal_catalog(ds, marker_disp=md, angle_result=angle_result)]
    assert "angle:KNEE" in keys
    assert "marker:A:X" in keys
    assert "marker:A:Y" in keys
    assert "marker:A:Z" in keys


def test_series_basic_channels():
    ds = _dataset()
    np.testing.assert_array_equal(signal_series(ds, "time"), ds["time"])
    np.testing.assert_array_equal(signal_series(ds, "cop_ap"), ds["cop_ap"])
    np.testing.assert_array_equal(signal_series(ds, "fx"), ds["fx"])


def test_series_cop_resultant_is_mean_subtracted():
    """Resultant COP = distance from the MEAN COP (posturography standard, RD),
    not from the force-plate origin. Prieto et al. 1996 (IEEE TBME)."""
    ds = _dataset()
    ds["cop_ap"] = np.array([3.0, 0.0])   # mean 1.5 -> centred [+1.5, -1.5]
    ds["cop_ml"] = np.array([4.0, 0.0])   # mean 2.0 -> centred [+2.0, -2.0]
    ds["time"] = np.array([0.0, 0.01])
    out = signal_series(ds, "cop")
    # sqrt(1.5^2 + 2.0^2) = 2.5 at both samples (symmetric about the mean)
    np.testing.assert_allclose(out, [2.5, 2.5])


def test_series_cop_resultant_origin_invariant():
    """RD must be invariant to a constant COP offset (origin shift): a pure
    translation of the platform origin must not change the sway measure."""
    ds = _dataset()
    ds["cop_ap"] = np.array([0.0, 1.0, 2.0, 1.0])
    ds["cop_ml"] = np.array([0.0, 1.0, 0.0, -1.0])
    ds["time"] = np.arange(4) / 100.0
    base = signal_series(ds, "cop")
    ds2 = dict(ds)
    ds2["cop_ap"] = ds["cop_ap"] + 500.0   # shift platform origin 500 mm
    ds2["cop_ml"] = ds["cop_ml"] - 300.0
    shifted = signal_series(ds2, "cop")
    np.testing.assert_allclose(shifted, base)


def test_series_cop_resultant_sine_amplitude():
    """Synthetic circular sway of radius A about the mean -> RD == A constant."""
    n = 2000
    t = np.arange(n) / 100.0
    A = 7.0
    ds = _dataset(n)
    ds["time"] = t
    ds["cop_ap"] = 10.0 + A * np.cos(2 * np.pi * 0.5 * t)   # mean offset 10
    ds["cop_ml"] = -4.0 + A * np.sin(2 * np.pi * 0.5 * t)   # mean offset -4
    out = signal_series(ds, "cop")
    np.testing.assert_allclose(out, np.full(n, A), atol=1e-6)


def test_series_marker_resampled_onto_master_clock():
    ds = _dataset()
    md = np.zeros((1, 2, 3))
    md[0, 0] = [0, 0, 0]
    md[0, 1] = [9, 0, 0]          # X ramps 0 -> 9 over the master-clock span
    ds["markers"] = {"labels": ["A"], "data": md, "time": np.array([0.0, 0.09])}
    out = signal_series(ds, "marker:A:X", marker_disp=md)
    assert out.shape == ds["time"].shape       # resampled to 10 master frames
    np.testing.assert_allclose(out, np.arange(10, dtype=float))


def test_series_angle_resampled():
    ds = _dataset()
    angle_result = {
        "angles": {"KNEE": np.array([0.0, 90.0])},
        "time": np.array([0.0, 0.09]),
    }
    out = signal_series(ds, "angle:KNEE", angle_result=angle_result)
    assert out.shape == ds["time"].shape
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(90.0)


def test_series_unknown_key_raises():
    ds = _dataset()
    with pytest.raises(ValueError):
        signal_series(ds, "nonexistent")


def test_series_marker_without_disp_raises():
    ds = _dataset()
    ds["markers"] = {"labels": ["A"], "data": np.zeros((1, 2, 3)),
                     "time": np.array([0.0, 0.09])}
    with pytest.raises(ValueError):
        signal_series(ds, "marker:A:X", marker_disp=None)


# -- unit_for / label_for (UI professionalization helpers) -------------------

def test_unit_for_representative_keys():
    assert unit_for("time") == "s"
    assert unit_for("cop") == "mm"
    assert unit_for("cop_ap") == "mm"
    assert unit_for("cop_ml") == "mm"
    assert unit_for("fx") == "N"
    assert unit_for("fy") == "N"
    assert unit_for("fz") == "N"
    assert unit_for("angle:Knee") == "deg"
    assert unit_for("marker:HEEL:Z") == "mm"
    assert unit_for("nonsense") == ""


def test_unit_for_filt_keeps_base_unit():
    # A :filt derivative has the same physical unit as its base key.
    assert unit_for("cop_ap:filt") == "mm"
    assert unit_for("fz:filt") == "N"
    assert unit_for("angle:Knee:filt") == "deg"


def test_label_for_representative_keys():
    assert label_for("cop_ap") == "COP X"
    assert label_for("cop_ml") == "COP Y"
    assert label_for("cop") == "COP"
    assert label_for("fx") == "Fx"
    assert label_for("fz") == "Fz"
    assert label_for("angle:Knee") == "∠ Knee"
    assert label_for("marker:HEEL:Z") == "HEEL Z"


def test_label_for_jcs_angle_abbreviations():
    """JCS angle channels render the compact clinical plane abbreviations the
    user asked for (internal channel names like R_KNEE_angle_FE are unchanged).
    Plane shorthand: F/E, AB/ADD, IR/ER; ankle uses Dorsi/Plantar and Inv/Ever;
    L/R kept as a single side letter."""
    assert label_for("angle:R_KNEE_angle_FE") == "∠ R Knee F/E"
    assert label_for("angle:L_KNEE_angle_AB") == "∠ L Knee AB/ADD"
    assert label_for("angle:R_KNEE_angle_IE") == "∠ R Knee IR/ER"
    assert label_for("angle:R_HIP_angle_FE") == "∠ R Hip F/E"
    assert label_for("angle:L_HIP_angle_AB") == "∠ L Hip AB/ADD"
    # Ankle planes are dorsi/plantar (sagittal) and inversion/eversion (frontal)
    assert label_for("angle:R_ANKLE_angle_FE") == "∠ R Ankle Dorsi/Plantar"
    assert label_for("angle:L_ANKLE_angle_AB") == "∠ L Ankle Inv/Ever"
    assert label_for("angle:R_ANKLE_angle_IE") == "∠ R Ankle IR/ER"
    assert label_for("angle:R_SHOULDER_angle_FE") == "∠ R Shoulder F/E"
    # A non-JCS angle name (no FE/AB/IE suffix) falls back to the bare name.
    assert label_for("angle:Knee") == "∠ Knee"


def test_label_for_filt_appends_filtered():
    assert label_for("cop_ap:filt") == "COP X (filtered)"
    assert label_for("fz:filt") == "Fz (filtered)"


def test_label_for_matches_catalog():
    """label_for must agree 1:1 with signal_catalog's labels (single source)."""
    ds = _dataset()
    md = np.zeros((1, 2, 3))
    ds["markers"] = {"labels": ["A"], "data": md, "time": np.array([0.0, 0.09])}
    angle_result = {"angles": {"KNEE": np.zeros(10)}, "time": ds["time"]}
    for key, label in signal_catalog(ds, marker_disp=md, angle_result=angle_result):
        assert label_for(key) == label
