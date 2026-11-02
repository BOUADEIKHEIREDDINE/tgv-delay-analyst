"""Tests for stats.py: the Wilson confidence interval (R2, used by brick 8).

The expected values do not come from running stats.py: they are a published
value, formulas worked out by hand for the edge cases, and the simple
"p +/- 1.96 * sqrt(p(1-p)/n)" interval, which Wilson matches when n is large.
"""

from math import sqrt

import pytest

from tgv_analyst.stats import confidence_interval

Z95 = 1.959964  # z for a 95% interval


# --- Known values -----------------------------------------------------------

def test_textbook_value_50_out_of_100():
    """Published Wilson 95% interval for 50 / 100: [0.4038, 0.5962]."""
    rate, low, high = confidence_interval(50, 100)
    assert rate == 0.5
    assert low == pytest.approx(0.4038, abs=1e-4)
    assert high == pytest.approx(0.5962, abs=1e-4)


def test_paris_lyon_marseille_2024():
    """The benchmark question: 640 late trains out of 6704 -> 9.5 %, [8.9 %, 10.3 %]."""
    rate, low, high = confidence_interval(640, 6704)
    assert rate == pytest.approx(0.0955, abs=1e-4)
    assert low == pytest.approx(0.0887, abs=1e-4)
    assert high == pytest.approx(0.1027, abs=1e-4)


def test_large_sample_matches_the_simple_interval():
    """With 1,000,000 trains, Wilson and p +/- z*sqrt(p(1-p)/n) give the same bounds."""
    n, late = 1_000_000, 500_000
    p = late / n
    margin = Z95 * sqrt(p * (1 - p) / n)
    rate, low, high = confidence_interval(late, n)
    assert low == pytest.approx(p - margin, abs=1e-6)
    assert high == pytest.approx(p + margin, abs=1e-6)


# --- Edge cases (spec section 8: empty, missing, single value) --------------

def test_no_late_train():
    """0 late out of 10: the rate is 0 but the interval is not [0, 0].

    By hand, for 0 successes the upper bound is z^2 / (n + z^2).
    """
    rate, low, high = confidence_interval(0, 10)
    assert rate == 0.0
    assert low == 0.0  # was 2.8e-17 (float rounding) before the min(p, ...) fix in stats.py
    assert high == pytest.approx(Z95**2 / (10 + Z95**2), abs=1e-6)  # 0.2775


def test_all_trains_late():
    """10 late out of 10: the upper bound is exactly 1, never above."""
    rate, low, high = confidence_interval(10, 10)
    assert rate == 1.0
    assert high == 1.0
    assert low == pytest.approx(10 / (10 + Z95**2), abs=1e-6)  # 0.7225, mirror of the case above


def test_single_train_late():
    """A single train, and it was late: the interval is very wide.

    By hand, for 1 success out of 1 the lower bound is 1 / (1 + z^2).
    """
    rate, low, high = confidence_interval(1, 1)
    assert rate == 1.0
    assert low == pytest.approx(1 / (1 + Z95**2), abs=1e-6)  # 0.2065
    assert high == 1.0


def test_single_train_on_time():
    rate, low, high = confidence_interval(0, 1)
    assert rate == 0.0
    assert low == 0.0
    assert high == pytest.approx(Z95**2 / (1 + Z95**2), abs=1e-6)  # 0.7935


@pytest.mark.parametrize("late, total", [(0, 1), (1, 1), (0, 10), (3, 10), (10, 10), (640, 6704), (1, 1_000_000)])
def test_bounds_always_contain_the_rate_and_stay_between_0_and_1(late, total):
    rate, low, high = confidence_interval(late, total)
    assert 0.0 <= low <= rate <= high <= 1.0


# --- Behaviour ----------------------------------------------------------------

def test_more_trains_give_a_narrower_interval():
    """Same rate (10 %), 100 times more trains -> narrower interval."""
    _, low_small, high_small = confidence_interval(10, 100)
    _, low_big, high_big = confidence_interval(1000, 10000)
    assert (high_big - low_big) < (high_small - low_small)


def test_99_percent_interval_is_wider_than_95():
    _, low95, high95 = confidence_interval(50, 100, level=0.95)
    _, low99, high99 = confidence_interval(50, 100, level=0.99)
    assert low99 < low95 and high99 > high95
    assert low99 == pytest.approx(0.3753, abs=1e-4)  # published 99% value for 50 / 100
    assert high99 == pytest.approx(0.6247, abs=1e-4)


# --- Wrong input: an error, not a wrong number ----------------------------------

@pytest.mark.parametrize(
    "late, total",
    [
        (0, 0),  # edge case: no train ran (e.g. a COVID month)
        (5, 0),
        (3, -10),
        (11, 10),  # more late trains than trains
        (-1, 10),
    ],
)
def test_impossible_counts_raise_an_error(late, total):
    with pytest.raises(ValueError):
        confidence_interval(late, total)
