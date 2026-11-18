"""Estimators for the cluster (plan) design and the member (seat) design."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .assignment import Arm, FrozenAssignment, seat_is_treated
from .simulate import Outcomes, Population, outcomes

Z95 = 1.959964


@dataclass(frozen=True)
class Estimate:
    est: float
    se: float

    @property
    def ci(self) -> tuple[float, float]:
        return self.est - Z95 * self.se, self.est + Z95 * self.se

    def covers(self, truth: float) -> bool:
        lo, hi = self.ci
        return lo <= truth <= hi


def stratified_diff(y: np.ndarray, treat: np.ndarray, ctrl: np.ndarray, strata: np.ndarray) -> Estimate:
    """Σ_s w_s (ȳ_s,t − ȳ_s,c) with Neyman variance. Unit = row (a plan)."""
    est = var = 0.0
    keep = treat | ctrl
    total = keep.sum()
    for s in np.unique(strata[keep]):
        m = strata == s
        yt, yc = y[m & treat], y[m & ctrl]
        if len(yt) < 2 or len(yc) < 2:
            continue  # merge sparse cells upstream in production
        w = (m & keep).sum() / total
        est += w * (yt.mean() - yc.mean())
        var += w**2 * (yt.var(ddof=1) / len(yt) + yc.var(ddof=1) / len(yc))
    return Estimate(est, var**0.5)


def ols_clustered(y: np.ndarray, X: np.ndarray, cluster: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and CR1 covariance clustered on ``cluster``."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    _, g = np.unique(cluster, return_inverse=True)
    G = g.max() + 1
    scores = np.column_stack([np.bincount(g, weights=e * X[:, j], minlength=G) for j in range(k)])
    V = XtX_inv @ (scores.T @ scores) @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k))
    return beta, V


def clustered_diff(y: np.ndarray, d: np.ndarray, cluster: np.ndarray) -> Estimate:
    """OLS of y on [1, d] with CR1 standard errors clustered on ``cluster``."""
    X = np.column_stack([np.ones(len(y)), np.asarray(d, dtype=float)])
    beta, V = ols_clustered(y, X, cluster)
    return Estimate(beta[1], V[1, 1] ** 0.5)


def iid_diff(y: np.ndarray, d: np.ndarray) -> Estimate:
    """Unclustered difference in means: what a seat-level A/B dashboard reports."""
    yt, yc = y[d], y[~d]
    return Estimate(yt.mean() - yc.mean(), (yt.var(ddof=1) / len(yt) + yc.var(ddof=1) / len(yc)) ** 0.5)


# ---------------------------------------------------------------------------
# Experiment runners


ARM_CODE = {Arm.HOLDOUT: 0, Arm.OWNER_ONLY: 1, Arm.WHOLE_PLAN: 2}


def cluster_treatment(pop: Population, asg: FrozenAssignment) -> tuple[np.ndarray, np.ndarray]:
    """Plan arm codes (0 holdout, 1 owner-only, 2 whole-plan) and seat treatment."""
    arms = [asg.arm_for(pid) for pid in pop.plan_ids]
    plan_arm = np.array([ARM_CODE[a] for a in arms])
    seat_arms = [arms[i] for i in pop.seat_plan]
    treated = np.array([seat_is_treated(a, o) for a, o in zip(seat_arms, pop.seat_is_owner)])
    return plan_arm, treated


def analyse_cluster(pop: Population, asg: FrozenAssignment) -> dict[str, Estimate]:
    plan_arm, treated = cluster_treatment(pop, asg)
    o = outcomes(pop, treated)
    strata = pop.strata()
    h, a, w = plan_arm == 0, plan_arm == 1, plan_arm == 2
    up = o.upgraded.astype(float)
    seat_w = pop.seat_plan
    return {
        "whole_plan_vs_holdout_upgrade": stratified_diff(up, w, h, strata),
        "owner_only_vs_holdout_upgrade": stratified_diff(up, a, h, strata),
        "whole_plan_vs_owner_only_upgrade": stratified_diff(up, w, a, strata),
        "whole_plan_vs_holdout_net_revenue": stratified_diff(o.net_revenue, w, h, strata),
        "owner_only_vs_holdout_net_revenue": stratified_diff(o.net_revenue, a, h, strata),
        # Seat-level outcome, analysed correctly with plan-clustered SEs.
        "whole_plan_vs_holdout_seat_access": clustered_diff(
            o.seat_access[(w | h)[seat_w]],
            w[seat_w][(w | h)[seat_w]],
            seat_w[(w | h)[seat_w]],
        ),
    }


def analyse_member(pop: Population, asg: FrozenAssignment) -> dict[str, Estimate | float]:
    """Seat-randomized design. Outcome: does the seat have All Access via the plan.

    The naive contrast compares treated seats to control seats. Control seats
    share plans with treated seats, so they inherit upgrades caused by those
    co-members (a positive spillover onto the control group), which pulls the
    estimate toward zero relative to the whole-plan policy effect.
    """
    treated = np.array([asg.arm_for(u) is Arm.WHOLE_PLAN for u in pop.user_ids])
    o = outcomes(pop, treated)
    y = o.seat_access.astype(float)
    n_t_on_plan = np.bincount(pop.seat_plan, weights=treated, minlength=pop.n_plans)
    others_treated = n_t_on_plan[pop.seat_plan] - treated
    ctrl = ~treated
    return {
        "naive_seat_access_iid": iid_diff(y, treated),
        "naive_seat_access_clustered": clustered_diff(y, treated, pop.seat_plan),
        "control_seats_with_treated_comember_share": float((others_treated[ctrl] > 0).mean()),
        "control_access_no_treated_comember": float(y[ctrl & (others_treated == 0)].mean()),
        "control_access_some_treated_comember": float(y[ctrl & (others_treated > 0)].mean()),
    }
