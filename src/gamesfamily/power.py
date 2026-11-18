"""Two-proportion sample size, plan = unit (design effect 1 for the primary)."""

from __future__ import annotations

import math

Z_ALPHA = 1.959964  # two-sided 0.05
Z_BETA = 0.841621  # 80% power


def n_per_arm(p0: float, p1: float, z_alpha: float = Z_ALPHA, z_beta: float = Z_BETA) -> int:
    if not (0 < p0 < 1 and 0 < p1 < 1) or p0 == p1:
        raise ValueError("need 0 < p0, p1 < 1 and p0 != p1")
    k = (z_alpha + z_beta) ** 2
    return math.ceil(k * (p0 * (1 - p0) + p1 * (1 - p1)) / (p1 - p0) ** 2)


def mde(p_bar: float, n: int, z_alpha: float = Z_ALPHA, z_beta: float = Z_BETA) -> float:
    """Approximate minimum detectable difference with n plans per arm."""
    return (z_alpha + z_beta) * math.sqrt(2 * p_bar * (1 - p_bar) / n)


def design_effect(mean_cluster_size: float, icc: float) -> float:
    """For seat-level secondaries analysed with plan-clustered SEs."""
    return 1 + (mean_cluster_size - 1) * icc
