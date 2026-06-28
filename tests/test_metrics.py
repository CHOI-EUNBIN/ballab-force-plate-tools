"""Regression tests for core.metrics (COP posturography + joint-angle stats).

Synthetic signals with known analytic answers pin the current behaviour so
future refactors cannot silently change a computed number.
"""

import numpy as np
import pytest

from core.metrics import (
    METRIC_KEYS,
    ANGLE_STATS,
    compute_metrics,
    compute_angle_metrics,
    compute_ellipse_points,
)


@pytest.fixture
def sine_cop():
    """COP where AP is a 0.5 Hz, 10 mm-amplitude sine and ML is flat zero."""
    fs = 100.0
    t = np.arange(1000) / fs
    ap = 10.0 * np.sin(2 * np.pi * 0.5 * t)
    ml = np.zeros_like(t)
    return ap, ml, fs


def test_compute_metrics_returns_all_keys(sine_cop):
    ap, ml, fs = sine_cop
    res = compute_metrics(ap, ml, fs, METRIC_KEYS)
    assert set(res.keys()) == set(METRIC_KEYS)
    # every value is a (number, unit) pair
    for key, (val, unit) in res.items():
        assert isinstance(val, float)
        assert isinstance(unit, str)


def test_compute_metrics_known_values(sine_cop):
    ap, ml, fs = sine_cop
    res = compute_metrics(ap, ml, fs, METRIC_KEYS)
    # RMS of a centred sine = amplitude / sqrt(2)
    assert res["RMS AP"][0] == pytest.approx(10.0 / np.sqrt(2), rel=1e-3)
    assert res["RMS AP"][1] == "mm"
    assert res["RMS ML"][0] == pytest.approx(0.0, abs=1e-9)
    # peak-to-peak range of the sine
    assert res["Range AP"][0] == pytest.approx(20.0, rel=1e-3)
    assert res["Range ML"][0] == pytest.approx(0.0, abs=1e-9)
    # mean of a full-period sine ~ 0
    assert res["Mean AP"][0] == pytest.approx(0.0, abs=1e-6)
    # dominant frequency is 0.5 Hz
    assert res["Mean power freq AP"][0] == pytest.approx(0.5, abs=0.05)
    assert res["Median freq AP"][0] == pytest.approx(0.5, abs=0.05)


def test_compute_metrics_velocity_is_pathlen_over_duration(sine_cop):
    ap, ml, fs = sine_cop
    res = compute_metrics(ap, ml, fs, METRIC_KEYS)
    n = len(ap)
    duration = (n - 1) / fs
    assert res["Mean velocity"][0] == pytest.approx(
        res["Sway path length"][0] / duration, rel=1e-9
    )
    assert res["Mean velocity"][1] == "mm/s"


def test_compute_metrics_too_short_returns_empty():
    assert compute_metrics([1.0], [1.0], 100.0, METRIC_KEYS) == {}


def test_sway_path_is_nan_safe():
    """A single occluded (NaN) COP sample must not poison the whole path.

    The inter-sample step that touches the gap is dropped (nansum); the kept
    steps still sum. Here AP = [0,1,2, NaN, 4,5]: the finite steps are
    1+1 (frames 0->1->2) and 1 (4->5) = 3 mm; the two steps touching the NaN
    (2->NaN, NaN->4) are NaN and skipped. ML flat.
    """
    ap = [0.0, 1.0, 2.0, float("nan"), 4.0, 5.0]
    ml = [0.0] * 6
    res = compute_metrics(ap, ml, 10.0, ["Sway path length", "Mean velocity"])
    assert res["Sway path length"][0] == pytest.approx(3.0)
    # duration = (6-1)/10 = 0.5 s -> velocity = 3 / 0.5
    assert res["Mean velocity"][0] == pytest.approx(6.0)


@pytest.fixture
def circular_cop():
    """COP on a circle of radius R=10 mm at f=0.5 Hz: AP=R sin, ML=R cos.

    A circular orbit has closed-form Prieto values, so every COP metric has an
    exact analytic answer: RD is constant = R, so MDIST = R; the 2-D path per
    cycle is the circumference 2*pi*R; each 1-D (AP or ML) excursion per cycle is
    4*R; the area enclosed per cycle is pi*R^2 -> swept per second = pi*R^2*f.
    """
    R, f, fs = 10.0, 0.5, 1000.0
    t = np.arange(0, 4.0, 1.0 / fs)        # 4 s = exactly 2 cycles
    ap = R * np.sin(2 * np.pi * f * t)
    ml = R * np.cos(2 * np.pi * f * t)
    return ap, ml, fs, R, f


def test_mean_distance_equals_radius(circular_cop):
    """MDIST of a circular orbit = its radius R (RD is constant)."""
    ap, ml, fs, R, _ = circular_cop
    res = compute_metrics(ap, ml, fs, ["Mean distance"])
    assert res["Mean distance"][0] == pytest.approx(R, rel=1e-6)
    assert res["Mean distance"][1] == "mm"


def test_mean_distance_le_rms_of_rd():
    """MDIST is the arithmetic mean of RD; the RMS of the same RD = sqrt(RMS_AP^2
    + RMS_ML^2). By the power-mean inequality MDIST <= RMS_of_RD."""
    rng = np.random.default_rng(3)
    ap = rng.normal(0.0, 3.0, 20000)
    ml = rng.normal(0.0, 2.0, 20000)
    res = compute_metrics(ap, ml, 100.0, ["Mean distance", "RMS AP", "RMS ML"])
    rd_rms = np.sqrt(res["RMS AP"][0] ** 2 + res["RMS ML"][0] ** 2)
    assert res["Mean distance"][0] <= rd_rms + 1e-9


def test_directional_mean_velocity(circular_cop):
    """MVELO_AP / MVELO_ML of a circular orbit = 4*R*f each (per-axis 1-D path
    per cycle is 4R; over T this is 4*R*f); resultant Mean velocity = 2*pi*R*f."""
    ap, ml, fs, R, f = circular_cop
    res = compute_metrics(ap, ml, fs,
                          ["Mean velocity", "Mean velocity AP", "Mean velocity ML"])
    assert res["Mean velocity AP"][0] == pytest.approx(4 * R * f, rel=1e-3)
    assert res["Mean velocity ML"][0] == pytest.approx(4 * R * f, rel=1e-3)
    assert res["Mean velocity AP"][1] == "mm/s"
    assert res["Mean velocity"][0] == pytest.approx(2 * np.pi * R * f, rel=1e-3)


def test_sway_area_circle(circular_cop):
    """AREA-SW of a circular orbit = pi*R^2 * f (it sweeps its full area each
    cycle, so the area swept per second is the area times the frequency)."""
    ap, ml, fs, R, f = circular_cop
    res = compute_metrics(ap, ml, fs, ["Sway area"])
    assert res["Sway area"][0] == pytest.approx(np.pi * R ** 2 * f, rel=1e-3)
    assert res["Sway area"][1] == "mm^2/s"


def test_new_prieto_metrics_nan_safe(sine_cop):
    """MDIST / MVELO_AP / MVELO_ML / AREA-SW all stay finite through a gap."""
    ap, ml, fs = sine_cop
    ap_gap = ap.copy()
    ap_gap[321] = np.nan
    keys = ["Mean distance", "Mean velocity AP", "Mean velocity ML", "Sway area"]
    res = compute_metrics(ap_gap, ml, fs, keys)
    for k in keys:
        assert np.isfinite(res[k][0])


def test_rms_mean_range_are_nan_safe(sine_cop):
    """NaN-safe centring: with a NaN inserted, RMS/Mean/Range ignore the gap
    rather than returning NaN, and with NO NaN the values are unchanged."""
    ap, ml, fs = sine_cop
    base = compute_metrics(ap, ml, fs, ["RMS AP", "Mean AP", "Range AP"])
    ap_gap = ap.copy()
    ap_gap[123] = np.nan
    gap = compute_metrics(ap_gap, ml, fs, ["RMS AP", "Mean AP", "Range AP"])
    for k in ("RMS AP", "Mean AP", "Range AP"):
        assert np.isfinite(gap[k][0])
        # one missing sample out of 1000 barely moves the metric
        assert gap[k][0] == pytest.approx(base[k][0], abs=0.1)


def test_cop_op_registry_exposes_new_prieto_ops():
    """The pipeline MetricStep op registry must expose the new Prieto ops and map
    them to their METRIC_KEYS; cop_op then routes through compute_metrics so the
    pipeline value equals the panel value."""
    from core.metrics import COP_OPS, available_metric_ops, cop_op
    for op in ("mean_distance", "mean_velocity_ap", "mean_velocity_ml", "sway_area"):
        assert op in COP_OPS, f"{op} missing from COP_OPS"
        assert op in available_metric_ops(), f"{op} not offered by the Add-step form"
        assert COP_OPS[op] in METRIC_KEYS, f"{op} maps to a non-existent metric key"
    # cop_op == compute_metrics for one of the new ops (circular orbit, MDIST=R)
    R, fs = 10.0, 100.0
    t = np.arange(0, 4.0, 1.0 / fs)
    ap = R * np.sin(2 * np.pi * 0.5 * t)
    ml = R * np.cos(2 * np.pi * 0.5 * t)
    val, unit = cop_op("mean_distance", ap, ml, fs)
    assert val == pytest.approx(R, rel=1e-3) and unit == "mm"


def test_compute_metrics_only_selected_keys(sine_cop):
    ap, ml, fs = sine_cop
    res = compute_metrics(ap, ml, fs, ["RMS AP", "Range ML"])
    assert set(res.keys()) == {"RMS AP", "Range ML"}


def test_ellipse_area_matches_circle():
    """For an isotropic 2-D Gaussian cloud the 95% ellipse is a circle whose
    area equals pi * chi2(0.95, df=2) * variance."""
    rng = np.random.default_rng(0)
    var = 4.0
    ap = rng.normal(0.0, np.sqrt(var), 20000)
    ml = rng.normal(0.0, np.sqrt(var), 20000)
    res = compute_metrics(ap, ml, 100.0, ["95% Ellipse area"])
    from scipy.stats import chi2

    expected = np.pi * chi2.ppf(0.95, df=2) * var
    assert res["95% Ellipse area"][0] == pytest.approx(expected, rel=0.05)


def test_compute_ellipse_points_closed_curve():
    rng = np.random.default_rng(1)
    ap = rng.normal(0.0, 2.0, 5000)
    ml = rng.normal(0.0, 1.0, 5000)
    ex, ey = compute_ellipse_points(ap, ml, n_pts=120)
    assert ex.shape == ey.shape == (120,)
    # centred on the data means
    assert float(np.mean(ex)) == pytest.approx(np.mean(ml), abs=0.2)
    assert float(np.mean(ey)) == pytest.approx(np.mean(ap), abs=0.2)


def test_compute_ellipse_points_nan_safe():
    """REGRESSION: a single occluded (NaN) COP sample must not collapse the whole
    ellipse to NaN. The ellipse drops NaN frames (like the nanmean-based
    "95% Ellipse area" metric) and stays a finite closed curve."""
    rng = np.random.default_rng(2)
    ap = rng.normal(0.0, 2.0, 500)
    ml = rng.normal(0.0, 1.0, 500)
    ap[10] = np.nan        # one occluded frame in each channel
    ml[200] = np.nan
    ex, ey = compute_ellipse_points(ap, ml, n_pts=64)
    assert ex.shape == ey.shape == (64,)
    assert np.isfinite(ex).all() and np.isfinite(ey).all()


def test_compute_ellipse_points_too_few_samples_empty():
    """Fewer than 2 finite paired samples -> empty arrays (nothing to draw),
    never a crash or NaN cloud."""
    ex, ey = compute_ellipse_points([np.nan, 1.0], [2.0, np.nan])
    assert ex.size == 0 and ey.size == 0
    ex, ey = compute_ellipse_points([], [])
    assert ex.size == 0 and ey.size == 0


# --- joint-angle stats -----------------------------------------------------

def test_compute_angle_metrics_known_values():
    time = np.arange(10) / 100.0          # 0 .. 0.09 s
    angles = {"KNEE": np.array([0.0, 10, 20, 30, 40, 50, 60, 70, 80, 90])}
    res = compute_angle_metrics(angles, time, 0.0, 0.09, ANGLE_STATS)
    assert res["KNEE ROM"] == (90.0, "deg")
    assert res["KNEE Min"] == (0.0, "deg")
    assert res["KNEE Max"] == (90.0, "deg")
    assert res["KNEE Mean"][0] == pytest.approx(45.0)
    assert res["KNEE Start"] == (0.0, "deg")
    assert res["KNEE End"] == (90.0, "deg")


def test_compute_angle_metrics_window_clips():
    time = np.arange(10) / 100.0
    angles = {"KNEE": np.arange(10, dtype=float) * 10.0}
    # window covers only frames 0.02 .. 0.05 -> values 20,30,40,50
    res = compute_angle_metrics(angles, time, 0.02, 0.05, ["Min", "Max"])
    assert res["KNEE Min"] == (20.0, "deg")
    assert res["KNEE Max"] == (50.0, "deg")


def test_compute_angle_metrics_nan_safe():
    time = np.arange(5) / 100.0
    angles = {"HIP": np.array([np.nan, 10.0, np.nan, 30.0, np.nan])}
    res = compute_angle_metrics(angles, time, 0.0, 0.04, ["Min", "Max", "Start", "End"])
    assert res["HIP Min"] == (10.0, "deg")
    assert res["HIP Max"] == (30.0, "deg")
    # Start/End use the first/last *finite* sample
    assert res["HIP Start"] == (10.0, "deg")
    assert res["HIP End"] == (30.0, "deg")


def test_angle_sd_is_sample_sd_and_matches_scalar_op():
    """compute_angle_metrics 'SD' uses ddof=1 (sample SD), the SAME definition as
    SCALAR_OPS['std'] and the per-cycle SD in metrics_compute, so 'SD' means one
    thing across every code path. Pins the 2026 ddof=0 -> ddof=1 unification."""
    from core.metrics import scalar_op
    time = np.arange(5) / 100.0
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    res = compute_angle_metrics({"K": vals}, time, 0.0, 0.04, ["SD"])
    expected = float(np.std(vals, ddof=1))   # sample SD = 1.5811...
    assert res["K SD"][0] == pytest.approx(expected)
    assert scalar_op("std", vals)[0] == pytest.approx(expected)


def test_compute_angle_metrics_empty_inputs():
    time = np.arange(5) / 100.0
    assert compute_angle_metrics({}, time, 0.0, 0.04, ["Min"]) == {}
    assert compute_angle_metrics({"A": np.zeros(5)}, time, 0.0, 0.04, []) == {}
    # window entirely outside the data -> nothing
    assert compute_angle_metrics({"A": np.zeros(5)}, time, 9.0, 9.5, ["Min"]) == {}


# --- Round B1: derivative/integral named clinical ops ----------------------
# Each is pinned against a synthetic signal with a closed-form answer, so a
# regression in the underlying derivative/integral surfaces here as a wrong
# clinical number (e.g. a sine angle's peak angular velocity = A*w).

from core.metrics import scalar_op, op_unit  # noqa: E402


def test_peak_angular_velocity_of_sine():
    """theta = A*sin(w t) -> d theta/dt = A*w*cos(w t); peak |angular velocity|
    = A*w (deg/s). The classic kinematics check."""
    A, f = 30.0, 1.5                 # 30 deg amplitude, 1.5 Hz
    w = 2 * np.pi * f
    t = np.linspace(0, 2.0, 8000)
    theta = A * np.sin(w * t)
    val, frame = scalar_op("peak_angular_velocity", theta, t=t)
    assert abs(val) == pytest.approx(A * w, rel=1e-3)
    assert frame is not None        # emits an event at the extremum frame
    assert op_unit("peak_angular_velocity", "deg") == "deg/s"


def test_peak_abs_returns_signed_extremum_documented():
    """DOCUMENTED CURRENT BEHAVIOUR (intentionally not changed): the peak ops use
    a SIGNED 'largest-|.|' reducer (``metrics._peak_abs``). It returns the value
    farthest from zero WITH its sign, so a window whose dominant excursion is
    negative reports a NEGATIVE peak. This is why, when per-cycle peaks alternate
    sign, their mean can cancel — a known semantics the user asked to leave as-is.
    This test pins that behaviour so a future change is a conscious, reviewed one."""
    from core.metrics import _peak_abs
    # dominant excursion is negative -> signed peak is negative.
    val, idx = _peak_abs(np.array([-9.0, 2.0, 5.0]))
    assert val == -9.0 and idx == 0
    # NaN-safe: ignores NaN, still signed.
    val, idx = _peak_abs(np.array([np.nan, 3.0, -7.0, np.nan]))
    assert val == -7.0 and idx == 2
    # all-NaN -> (nan, None)
    val, idx = _peak_abs(np.array([np.nan, np.nan]))
    assert np.isnan(val) and idx is None
    # Consequence: two cycles with equal-magnitude opposite-sign peaks average to 0.
    assert np.mean([_peak_abs(np.array([-8.0, 1.0]))[0],
                    _peak_abs(np.array([8.0, -1.0]))[0]]) == 0.0


def test_peak_angular_acceleration_of_sine():
    """theta = A*sin(w t) -> d2/dt2 = -A*w^2 sin(w t); peak |angular accel| =
    A*w^2 (deg/s^2)."""
    A, f = 20.0, 1.0
    w = 2 * np.pi * f
    t = np.linspace(0, 2.0, 10000)
    theta = A * np.sin(w * t)
    val, frame = scalar_op("peak_angular_acceleration", theta, t=t)
    assert abs(val) == pytest.approx(A * w ** 2, rel=2e-2)
    assert frame is not None
    assert op_unit("peak_angular_acceleration", "deg") == "deg/s^2"


def test_rfd_of_ramp_force_is_the_slope():
    """A ramp force F = k*t has a constant slope k everywhere, so peak RFD = k
    (N/s). The dominant rate of force development."""
    k, fs = 800.0, 1000.0
    t = np.arange(0, 0.5, 1.0 / fs)
    F = k * t
    val, frame = scalar_op("rfd", F, t=t)
    assert val == pytest.approx(k, rel=1e-3)
    assert frame is not None
    assert op_unit("rfd", "N") == "N/s"


def test_rfd_picks_the_steepest_signed_slope():
    """RFD is the peak of |dF/dt| keeping sign: a force that rises then falls
    steeper returns the (negative) steeper slope."""
    fs = 1000.0
    t = np.arange(0, 1.0, 1.0 / fs)
    # rise at +100 N/s for 0.5 s, then fall at -300 N/s
    F = np.where(t < 0.5, 100.0 * t, 50.0 - 300.0 * (t - 0.5))
    val, _ = scalar_op("rfd", F, t=t)
    assert val == pytest.approx(-300.0, rel=2e-2)


def test_loading_rate_is_mean_slope_over_window():
    """Loading rate = (F_end - F_start)/T, the average slope across the window
    (the window IS the loading interval). For F=k*t over [0,T] this equals k."""
    k = 500.0
    t = np.linspace(0, 0.2, 400)
    F = k * t
    val, frame = scalar_op("loading_rate", F, t=t)
    assert val == pytest.approx(k, rel=1e-6)
    assert frame is None            # an average, not an instant -> no event
    assert op_unit("loading_rate", "N") == "N/s"


def test_loading_rate_nonlinear_uses_endpoints():
    """Loading rate uses only the first/last sample (endpoint-to-endpoint mean
    slope), so a curved rise from 0 to 100 N over 0.5 s gives 200 N/s regardless
    of curvature."""
    t = np.linspace(0, 0.5, 600)
    F = 100.0 * (t / 0.5) ** 2       # curved 0 -> 100 N
    val, _ = scalar_op("loading_rate", F, t=t)
    assert val == pytest.approx(200.0, rel=1e-6)


def test_impulse_of_rectangular_force_is_force_times_time():
    """A constant force F over [0,T] has impulse = F*T (N*s)."""
    F0, T = 200.0, 0.3
    t = np.linspace(0, T, 600)
    F = np.full_like(t, F0)
    val, frame = scalar_op("impulse", F, t=t)
    assert val == pytest.approx(F0 * T, rel=1e-6)
    assert frame is None
    assert op_unit("impulse", "N") == "N*s"


def test_impulse_sign_follows_channel_sign():
    """The impulse op faithfully carries the input channel's sign — it does NOT
    rectify. A positive (upward) vertical GRF gives a POSITIVE impulse; a raw
    force-plate Fz that stores the downward load-on-plate (Fz < 0) gives a
    NEGATIVE impulse. This pins the convention: a negative vertical impulse in the
    app means the channel is downward-signed (load-on-plate), not a math bug — the
    fix is to point the metric at an upward-positive vGRF channel."""
    F0, T = 500.0, 0.4
    t = np.linspace(0, T, 800)
    vgrf_up = np.full_like(t, F0)          # upward ground reaction (standard vGRF)
    load_on_plate = -vgrf_up               # raw plate convention (downward)
    up_imp, _ = scalar_op("impulse", vgrf_up, t=t)
    down_imp, _ = scalar_op("impulse", load_on_plate, t=t)
    assert up_imp == pytest.approx(F0 * T, rel=1e-6) and up_imp > 0
    assert down_imp == pytest.approx(-F0 * T, rel=1e-6) and down_imp < 0


def test_braking_and_propulsive_impulse_split_AP_force():
    """AP GRF that brakes (negative) then propels (positive): braking impulse is
    the negative-area integral (<=0), propulsive the positive (>=0), and the two
    sum to the total impulse. Anterior (forward) = + convention."""
    fs = 1000.0
    t = np.arange(0, 0.6, 1.0 / fs)
    # -100 N for the first 0.3 s (braking), +150 N for the next 0.3 s (propulsive)
    F = np.where(t < 0.3, -100.0, 150.0)
    brake, _ = scalar_op("braking_impulse", F, t=t)
    prop, _ = scalar_op("propulsive_impulse", F, t=t)
    total, _ = scalar_op("impulse", F, t=t)
    assert brake == pytest.approx(-100.0 * 0.3, rel=2e-3)
    assert prop == pytest.approx(150.0 * 0.3, rel=2e-3)
    assert brake <= 0.0 <= prop
    assert (brake + prop) == pytest.approx(total, rel=2e-3)
    assert op_unit("braking_impulse", "N") == "N*s"
    assert op_unit("propulsive_impulse", "N") == "N*s"


def test_new_named_ops_registered_and_filtered_by_signal_kind():
    """Every Round B1 op is in SCALAR_OPS, exposed by the Add-step form with a
    human label + needs_time + signal_kind hint."""
    from core.metrics import SCALAR_OPS, available_metric_ops
    ops = available_metric_ops()
    expect = {
        "peak_angular_velocity": "angle", "peak_angular_acceleration": "angle",
        "rfd": "force", "loading_rate": "force", "impulse": "force",
        "braking_impulse": "force", "propulsive_impulse": "force",
    }
    for op, kind in expect.items():
        assert op in SCALAR_OPS
        assert op in ops and ops[op]["needs_time"] is True
        assert ops[op]["signal_kind"] == kind
        assert ops[op]["label"] and ops[op]["label"][0].isupper()
    # peak (derivative) ops emit an extremum event; impulses/loading rate do not
    assert ops["peak_angular_velocity"]["emits_event"] is True
    assert ops["impulse"]["emits_event"] is False
    assert ops["loading_rate"]["emits_event"] is False


def test_new_ops_nan_safe():
    """A single occluded sample is interpolated through, not propagated."""
    t = np.linspace(0, 1.0, 1001)
    theta = 10.0 * np.sin(2 * np.pi * t)
    theta[500] = np.nan
    v, _ = scalar_op("peak_angular_velocity", theta, t=t)
    assert np.isfinite(v)
    F = np.full_like(t, 50.0)
    F[200] = np.nan
    imp, _ = scalar_op("impulse", F, t=t)
    assert np.isfinite(imp) and imp == pytest.approx(50.0 * 1.0, rel=1e-3)


# --- Round B2: binary reference ops (product and quotient) ---

from core.metrics import REFERENCE_OPS


def test_product_and_quotient_reference_ops():
    pfn, pn, _ = REFERENCE_OPS["product"]
    qfn, qn, _ = REFERENCE_OPS["quotient"]
    assert pn == 2 and qn == 2
    assert pfn(1.2, 0.8) == pytest.approx(0.96)
    assert qfn(1.28, 1.12) == pytest.approx(1.142857, rel=1e-4)
    import math
    assert math.isnan(qfn(1.0, 0.0))            # divide by zero -> NaN
    assert math.isnan(pfn(float("nan"), 2.0))
