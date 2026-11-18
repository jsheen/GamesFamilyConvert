"""Probe how much outcomes change at the cluster level, before building a family model.

Probe 1, exposure analysis on seat-randomized data (free if the always-on
paywall RCT already randomizes Games Family seats independently). Within a
plan, how many co-members were treated is random, so an untreated seat's
outcome can be compared across plans whose co-members got 0, 1, 2 or 3
treatments. Any difference is spillover.

Probe 2, randomized-saturation pilot (Hudgens & Halloran 2008). Plans are
randomized to 0%, 50% or 100% of seats treated; within 50% plans, which seats
are treated is randomized too. That gives direct, spillover and total effects
with known assignment probabilities.

In the simulator the only spillover channel is the plan upgrade, so the
outcomes here are seat access and plan upgrade. With real data, also run the
probes on frequent outcomes (paywall hits, reads, requests, Games plays):
they answer in weeks rather than months.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .analysis import Estimate, clustered_diff, ols_clustered
from .assignment import hash_unit
from .simulate import Population, outcomes

SATURATIONS = ("none", "half", "all")


# ---------------------------------------------------------------------------
# Exposure bookkeeping


def co_members_treated(pop: Population, treated: np.ndarray) -> np.ndarray:
    """Number of *other* seats on the same plan that are treated."""
    per_plan = np.bincount(pop.seat_plan, weights=treated, minlength=pop.n_plans)
    return (per_plan[pop.seat_plan] - treated).astype(int)


def _k_dummies(k: np.ndarray, m: np.ndarray, kmax: int) -> np.ndarray:
    """Columns: intercept, plan-size FE (3, 4 seats), 1{k=j} for j=1..kmax."""
    cols = [np.ones(len(k)), (m == 3).astype(float), (m == 4).astype(float)]
    cols += [(k == j).astype(float) for j in range(1, kmax + 1)]
    return np.column_stack(cols)


@dataclass(frozen=True)
class SpilloverCurve:
    """E[Y(own=0, k treated co-members)] - E[Y(own=0, k=0)], for k = 1..kmax."""

    role: str
    by_k: dict[int, Estimate]
    n_seats: int
    control_mean: float


def spillover_curve(
    pop: Population, treated: np.ndarray, y: np.ndarray, role: str = "any"
) -> SpilloverCurve:
    """Probe 1 on untreated seats: outcome vs number of treated co-members.

    Plan-size fixed effects make the comparison within plan size, where k is
    randomly assigned. Standard errors are clustered on plan_id.
    """
    k = co_members_treated(pop, treated)
    m = pop.plan_seats[pop.seat_plan]
    keep = ~treated
    if role == "owner":
        keep &= pop.seat_is_owner
    elif role == "member":
        keep &= ~pop.seat_is_owner
    kmax = int(k[keep].max())
    X = _k_dummies(k[keep], m[keep], kmax)
    beta, V = ols_clustered(y[keep], X, pop.seat_plan[keep])
    by_k = {j: Estimate(beta[2 + j], V[2 + j, 2 + j] ** 0.5) for j in range(1, kmax + 1)}
    return SpilloverCurve(role, by_k, int(keep.sum()), float(y[keep & (k == 0)].mean()))


def share_regression(pop: Population, treated: np.ndarray, y: np.ndarray) -> dict[str, Estimate]:
    """y ~ own + share of co-members treated + own x share + plan-size FE.

    ``spillover_full``: untreated seat, all co-members treated vs none.
    ``direct_none``: own treatment with no co-members treated.
    """
    k = co_members_treated(pop, treated)
    m = pop.plan_seats[pop.seat_plan]
    share = k / (m - 1)
    d = treated.astype(float)
    X = np.column_stack([np.ones(len(y)), (m == 3), (m == 4), d, share, d * share]).astype(float)
    beta, V = ols_clustered(y, X, pop.seat_plan)
    se = np.sqrt(np.diag(V))
    return {
        "direct_none": Estimate(beta[3], se[3]),
        "spillover_full": Estimate(beta[4], se[4]),
        "interaction": Estimate(beta[5], se[5]),
    }


def plan_dose_response(pop: Population, treated: np.ndarray, plan_y: np.ndarray) -> dict[int, Estimate]:
    """Plan upgrade vs number of treated seats, within plan size (plan = unit)."""
    n_t = np.bincount(pop.seat_plan, weights=treated, minlength=pop.n_plans).astype(int)
    m = pop.plan_seats
    X = _k_dummies(n_t, m, int(n_t.max()))
    beta, V = ols_clustered(plan_y, X, np.arange(pop.n_plans))
    return {j: Estimate(beta[2 + j], V[2 + j, 2 + j] ** 0.5) for j in range(1, int(n_t.max()) + 1)}


# ---------------------------------------------------------------------------
# Probe 2: randomized saturation


def assign_saturation(pop: Population, salt: str = "gf-sat-v1") -> np.ndarray:
    """Plan arm codes 0 = none, 1 = half, 2 = all; balanced within strata."""
    strata = pop.strata()
    arm = np.empty(pop.n_plans, dtype=int)
    for s in np.unique(strata):
        idx = np.flatnonzero(strata == s)
        order = idx[np.argsort([hash_unit(pop.plan_ids[i], salt) for i in idx])]
        offset = int(hash_unit(f"stratum-{s}", salt) * 3)
        arm[order] = (np.arange(len(order)) + offset) % 3
    return arm


def half_vector(pop: Population, salt: str = "gf-sat-seat-v1") -> np.ndarray:
    """Treat floor(m/2) randomly chosen seats on every plan (owner included at random)."""
    u = np.array([hash_unit(uid, salt) for uid in pop.user_ids])
    # Rank seats within plan by hash; seats are contiguous per plan.
    starts = pop.owner_seat
    treated = np.zeros(pop.n_seats, dtype=bool)
    for p, (s0, m) in enumerate(zip(starts, pop.plan_seats)):
        r = np.argsort(u[s0 : s0 + m])
        treated[s0 + r[: m // 2]] = True
    return treated


def saturation_treatment(pop: Population, plan_arm: np.ndarray, half: np.ndarray) -> np.ndarray:
    seat_arm = plan_arm[pop.seat_plan]
    return (seat_arm == 2) | ((seat_arm == 1) & half)


def analyse_saturation(pop: Population, plan_arm: np.ndarray, half: np.ndarray) -> dict[str, Estimate]:
    """Seat-level direct / spillover / total, plan-clustered SEs; plan-level upgrade."""
    treated = saturation_treatment(pop, plan_arm, half)
    o = outcomes(pop, treated)
    y = o.seat_access.astype(float)
    seat_arm = plan_arm[pop.seat_plan]
    cl = pop.seat_plan

    def contrast(a: np.ndarray, b: np.ndarray) -> Estimate:
        m = a | b
        return clustered_diff(y[m], a[m], cl[m])

    none_ = seat_arm == 0
    half_t = (seat_arm == 1) & treated
    half_u = (seat_arm == 1) & ~treated
    all_ = seat_arm == 2
    up = o.upgraded.astype(float)
    plan_ids = np.arange(pop.n_plans)

    def plan_contrast(a: int, b: int) -> Estimate:
        m = (plan_arm == a) | (plan_arm == b)
        return clustered_diff(up[m], (plan_arm == a)[m], plan_ids[m])

    return {
        "direct_at_half": contrast(half_t, half_u),
        "spillover_at_half": contrast(half_u, none_),
        "total_at_half": contrast(seat_arm == 1, none_),
        "total_at_all": contrast(all_, none_),
        "plan_upgrade_half_vs_none": plan_contrast(1, 0),
        "plan_upgrade_all_vs_none": plan_contrast(2, 0),
    }


def saturation_truth(pop: Population, half: np.ndarray) -> dict[str, float]:
    """Finite-population truths for the saturation estimands (seat-weighted)."""
    y0 = outcomes(pop, np.zeros(pop.n_seats, bool))
    yh = outcomes(pop, half)
    y1 = outcomes(pop, np.ones(pop.n_seats, bool))
    a0, ah, a1 = (o.seat_access.astype(float) for o in (y0, yh, y1))
    return {
        "direct_at_half": ah[half].mean() - ah[~half].mean(),
        "spillover_at_half": (ah - a0)[~half].mean(),
        "total_at_half": (ah - a0).mean(),
        "total_at_all": (a1 - a0).mean(),
        "plan_upgrade_half_vs_none": yh.upgraded.mean() - y0.upgraded.mean(),
        "plan_upgrade_all_vs_none": y1.upgraded.mean() - y0.upgraded.mean(),
    }
