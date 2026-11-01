"""Brick 8: confidence intervals for punctuality rates."""

from math import sqrt
from statistics import NormalDist


def confidence_interval(successes, total, level=0.95):
    """Wilson confidence interval for a proportion successes / total.

    Wilson is used instead of the simple "p +/- z * sqrt(p(1-p)/n)" interval
    because it stays between 0 and 1 and works when p is close to 0 or 1.
    Returns (rate, low, high), all between 0 and 1.
    """
    if total <= 0:
        raise ValueError("total must be greater than 0")
    if successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")

    z = NormalDist().inv_cdf(1 - (1 - level) / 2)  # 1.96 for 95%
    p = successes / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return p, max(0.0, center - margin), min(1.0, center + margin)
