"""Unit tests for the signal-math building blocks (``core.signal_ops``).

Synthetic, analytic-solution driven: a sine wave has a known derivative/integral,
a 3-4-5 triangle has magnitude 5, etc. These pin the operators biomech's named
metrics (Round B) are built on, so a regression in the math surfaces here first.
"""

import numpy as np

from core.signal_ops import (absval, derivative, derive_unit, integral,
                             magnitude, power)


def test_derivative_of_sine_matches_analytic():
    """d/dt sin(wt) = w*cos(wt). Interior points hit the analytic value tightly
    (central difference, dense grid); endpoints relax (one-sided)."""
    w = 2 * np.pi * 1.5
    t = np.linspace(0, 2, 4000)
    y = np.sin(w * t)
    dy = derivative(y, t, order=1)
    expected = w * np.cos(w * t)
    # interior (drop the two one-sided endpoints) is essentially exact
    assert np.allclose(dy[2:-2], expected[2:-2], atol=1e-3)


def test_second_derivative_of_sine():
    """d2/dt2 sin(wt) = -w^2 sin(wt)."""
    w = 2 * np.pi * 1.0
    t = np.linspace(0, 2, 5000)
    y = np.sin(w * t)
    d2 = derivative(y, t, order=2)
    expected = -(w ** 2) * np.sin(w * t)
    assert np.allclose(d2[5:-5], expected[5:-5], atol=5e-2)


def test_derivative_non_uniform_dt():
    """A constant-slope ramp differentiates to its slope even on a jittered clock.
    y = 3t -> dy/dt = 3 everywhere (central + one-sided are both exact for a line)."""
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 5, 200))
    t = np.unique(t)
    y = 3.0 * t
    dy = derivative(y, t)
    assert np.allclose(dy, 3.0, atol=1e-6)


def test_derivative_nan_safe():
    """A single interior NaN is interpolated through, not propagated: the slope of
    a clean ramp is recovered (no NaN in the output interior)."""
    t = np.linspace(0, 1, 101)
    y = 2.0 * t
    y[50] = np.nan
    dy = derivative(y, t)
    assert np.isfinite(dy).all()
    assert np.allclose(dy[2:-2], 2.0, atol=1e-6)


def test_integral_total_of_sine_over_full_period_is_zero():
    """Definite integral of sin over a whole period = 0."""
    t = np.linspace(0, 1, 10001)            # one full period of sin(2*pi*t)
    y = np.sin(2 * np.pi * t)
    area = integral(y, t, kind="total")
    assert abs(area) < 1e-4


def test_integral_total_of_constant_is_value_times_span():
    """Integral of a constant c over [0,T] = c*T."""
    t = np.linspace(0, 4, 500)
    y = np.full_like(t, 2.5)
    assert abs(integral(y, t, kind="total") - 2.5 * 4.0) < 1e-9


def test_integral_cumulative_of_constant_is_a_ramp():
    """Cumulative integral of c over t = c*t (running area), starting at 0."""
    t = np.linspace(0, 3, 301)
    y = np.full_like(t, 4.0)
    cum = integral(y, t, kind="cumulative")
    assert cum.shape == y.shape
    assert cum[0] == 0.0
    assert np.allclose(cum, 4.0 * t, atol=1e-9)


def test_integral_sign_gating_pos_neg():
    """sign='pos' keeps only positive area, 'neg' only negative; together they
    reconstruct the 'all' integral. A symmetric sine over a half period: positive
    lobe = +A, with the next half subtracting it."""
    t = np.linspace(0, 1, 20001)
    y = np.sin(2 * np.pi * t)               # +lobe [0,0.5], -lobe [0.5,1]
    pos = integral(y, t, kind="total", sign="pos")
    neg = integral(y, t, kind="total", sign="neg")
    allv = integral(y, t, kind="total", sign="all")
    assert pos > 0 and neg < 0
    assert abs(pos + neg - allv) < 1e-4
    # the two lobes are equal and opposite
    assert abs(pos + neg) < 1e-4


def test_magnitude_3_4_5():
    """sqrt(3^2 + 4^2) = 5 element-wise (the classic triangle)."""
    x = np.full(10, 3.0)
    y = np.full(10, 4.0)
    assert np.allclose(magnitude(x, y), 5.0)


def test_magnitude_three_components():
    """sqrt(1+4+4) = 3 for (1,2,2)."""
    a = np.array([1.0, 2.0])
    b = np.array([2.0, 0.0])
    c = np.array([2.0, 0.0])
    assert np.allclose(magnitude(a, b, c), [3.0, 2.0])


def test_magnitude_nan_propagates_per_sample():
    """A NaN component makes only that sample's magnitude NaN (others fine)."""
    x = np.array([3.0, np.nan, 3.0])
    y = np.array([4.0, 4.0, 4.0])
    m = magnitude(x, y)
    assert m[0] == 5.0 and m[2] == 5.0 and np.isnan(m[1])


def test_absval_and_power():
    assert np.allclose(absval(np.array([-1.0, 2.0, -3.0])), [1.0, 2.0, 3.0])
    assert np.allclose(power(np.array([4.0, 9.0]), 0.5), [2.0, 3.0])


def test_derive_unit_table():
    assert derive_unit("deg", "derivative") == "deg/s"
    assert derive_unit("deg", "derivative", order=2) == "deg/s^2"
    assert derive_unit("N", "integral") == "N*s"
    assert derive_unit("N", "magnitude") == "N"
    assert derive_unit("N", "normalize") == ""        # ratio is dimensionless
    assert derive_unit("", "integral") == "s"         # dimensionless -> seconds
    assert derive_unit("mm", "unknown_method") == "mm"  # safe passthrough
