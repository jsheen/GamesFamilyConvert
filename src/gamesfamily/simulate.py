"""Synthetic population and behaviour model for the personalized family paywall.

Every number in ``Params`` is an ASSUMPTION chosen to give a ~2% 8-week
baseline upgrade rate (the planning assumption in the source report). None
of these numbers are NYT data. The point of the simulator is to show *how*
the estimates behave under cluster interference, not to forecast a lift.

Potential outcomes use common random numbers: all random draws are made
once per seat or plan, and ``outcomes()`` maps any treatment vector to
outcomes deterministically. The true effect of a policy on this finite
population can therefore be computed exactly, by evaluating it on everyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Params:
    n_plans: int = 51_000  # Games Family plans with >= 2 seats filled
    seat_dist: tuple[float, float, float] = (0.45, 0.30, 0.25)  # P(2, 3, 4 seats)
    # 8-week count of paywall hits on News / Cooking / Athletic (gamma-Poisson).
    owner_hits_mean: float = 3.0
    member_hits_mean: float = 2.0
    hits_shape: float = 0.8
    # Owner upgrade to All Access Family.
    organic_upgrade: float = 0.010  # outside any paywall (account page, etc.)
    owner_per_hit_bau: float = 0.0035  # BAU paywall hit
    owner_per_hit_personal: float = 0.0075  # personalized family-upgrade paywall
    # Member request channel (personalized member paywall only).
    member_request_per_hit: float = 0.05
    request_delivery: float = 0.85  # owner has >= 1 paywall impression after it
    request_upgrade_boost: float = 0.10  # per delivered request
    # Standalone purchases by any seat, when the plan has not upgraded.
    standalone_per_hit_bau: float = 0.004
    standalone_per_hit_personal: float = 0.002  # family offer displaces it
    # Prices, $ per year (4-weekly billing x 13). See README "prices".
    games_family_annual: float = 120.0
    all_access_family_annual: float = 442.0  # $34 / 4 wk
    standalone_annual: float = 325.0  # $25 / 4 wk individual offer (assumption)
    # Registered-user correction report.
    free_users_per_seat: float = 8.0
    free_hits_mean: float = 1.5
    free_per_hit_convert: float = 0.006


@dataclass
class Population:
    params: Params
    plan_seats: np.ndarray  # (P,) seats per plan
    seat_plan: np.ndarray  # (S,) plan index of each seat
    seat_is_owner: np.ndarray  # (S,) bool
    owner_seat: np.ndarray  # (P,) seat index of each plan's owner
    hits: np.ndarray  # (S,) in-window paywall hits
    pre_hits: np.ndarray  # (S,) pre-period hits (for stratification)
    u_req: np.ndarray
    u_del: np.ndarray
    u_up: np.ndarray  # (P,)
    u_sa: np.ndarray
    plan_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)

    @property
    def n_plans(self) -> int:
        return len(self.plan_seats)

    @property
    def n_seats(self) -> int:
        return len(self.seat_plan)

    def strata(self) -> np.ndarray:
        """seats (2/3/4) x pre-period plan paywall hits (0 / 1-4 / 5+)."""
        plan_pre = np.bincount(self.seat_plan, weights=self.pre_hits, minlength=self.n_plans)
        bucket = np.digitize(plan_pre, [1, 5])
        return (self.plan_seats - 2) * 3 + bucket


def make_population(params: Params = Params(), seed: int = 0) -> Population:
    rng = np.random.default_rng(seed)
    P = params.n_plans
    plan_seats = rng.choice([2, 3, 4], size=P, p=params.seat_dist)
    seat_plan = np.repeat(np.arange(P), plan_seats)
    starts = np.concatenate([[0], np.cumsum(plan_seats)[:-1]])
    S = len(seat_plan)
    is_owner = np.zeros(S, dtype=bool)
    is_owner[starts] = True

    mean = np.where(is_owner, params.owner_hits_mean, params.member_hits_mean)
    lam = rng.gamma(params.hits_shape, mean / params.hits_shape)  # persistent propensity
    return Population(
        params=params,
        plan_seats=plan_seats,
        seat_plan=seat_plan,
        seat_is_owner=is_owner,
        owner_seat=starts,
        hits=rng.poisson(lam),
        pre_hits=rng.poisson(lam),
        u_req=rng.random(S),
        u_del=rng.random(S),
        u_up=rng.random(P),
        u_sa=rng.random(S),
        plan_ids=[f"plan-{i:07d}" for i in range(P)],
        user_ids=[f"user-{i:08d}" for i in range(S)],
    )


@dataclass
class Outcomes:
    upgraded: np.ndarray  # (P,) plan converted to All Access Family
    seat_access: np.ndarray  # (S,) seat has All Access via the plan
    standalone: np.ndarray  # (S,) seat bought a standalone sub instead
    requests_delivered: np.ndarray  # (P,)
    net_revenue: np.ndarray  # (P,) annualized $ change vs staying on Games Family


def outcomes(pop: Population, seat_treated: np.ndarray) -> Outcomes:
    """Deterministic outcomes for a given seat-level treatment vector.

    Interference: a member's treatment can raise the plan's upgrade
    probability through a request, and an upgrade gives *every* seat access.
    """
    p = pop.params
    seat_treated = np.asarray(seat_treated, dtype=bool)
    owner_t = seat_treated[pop.owner_seat]
    owner_hits = pop.hits[pop.owner_seat]

    p_req = 1 - (1 - p.member_request_per_hit) ** pop.hits
    requested = (~pop.seat_is_owner) & seat_treated & (pop.u_req < p_req)
    delivered = requested & (pop.u_del < p.request_delivery)
    n_req = np.bincount(pop.seat_plan, weights=delivered, minlength=pop.n_plans)

    q = np.where(owner_t, p.owner_per_hit_personal, p.owner_per_hit_bau)
    p_up = 1 - (1 - p.organic_upgrade) * (1 - q) ** owner_hits * (1 - p.request_upgrade_boost) ** n_req
    upgraded = pop.u_up < p_up

    c = np.where(seat_treated, p.standalone_per_hit_personal, p.standalone_per_hit_bau)
    standalone = (pop.u_sa < 1 - (1 - c) ** pop.hits) & ~upgraded[pop.seat_plan]

    delta_plan = p.all_access_family_annual - p.games_family_annual
    sa_per_plan = np.bincount(pop.seat_plan, weights=standalone, minlength=pop.n_plans)
    net = upgraded * delta_plan + sa_per_plan * p.standalone_annual
    return Outcomes(upgraded, upgraded[pop.seat_plan], standalone, n_req, net)


def treatment_for_policy(pop: Population, policy: str) -> np.ndarray:
    if policy == "holdout":
        return np.zeros(pop.n_seats, dtype=bool)
    if policy == "owner_only":
        return pop.seat_is_owner.copy()
    if policy == "whole_plan":
        return np.ones(pop.n_seats, dtype=bool)
    raise ValueError(policy)


def true_effects(pop: Population) -> dict[str, float]:
    """Finite-population effects of each policy applied to every plan."""
    base = outcomes(pop, treatment_for_policy(pop, "holdout"))
    out = {"baseline_upgrade": base.upgraded.mean()}
    for pol in ("owner_only", "whole_plan"):
        o = outcomes(pop, treatment_for_policy(pop, pol))
        out[f"{pol}_upgrade"] = o.upgraded.mean() - base.upgraded.mean()
        out[f"{pol}_seat_access"] = o.seat_access.mean() - base.seat_access.mean()
        out[f"{pol}_net_revenue"] = o.net_revenue.mean() - base.net_revenue.mean()
    return out


def registered_user_report(pop: Population, seed: int = 1) -> dict[str, float]:
    """Show how pooling Games Family seats into 'registered' biases the baseline.

    Conversion = bought a standalone subscription at a non-Games paywall
    during the window, among users with >= 1 hit, under BAU.
    """
    p = pop.params
    rng = np.random.default_rng(seed)
    n_free = int(p.free_users_per_seat * pop.n_seats)
    free_hits = rng.poisson(rng.gamma(p.hits_shape, p.free_hits_mean / p.hits_shape, n_free))
    free_conv = rng.random(n_free) < 1 - (1 - p.free_per_hit_convert) ** free_hits

    base = outcomes(pop, treatment_for_policy(pop, "holdout"))
    gf_hit = pop.hits > 0
    fr_hit = free_hits > 0
    n_gf, n_fr = gf_hit.sum(), fr_hit.sum()
    conv_gf = base.standalone[gf_hit].sum()
    conv_fr = free_conv[fr_hit].sum()
    return {
        "registered_users_hitting_paywall": float(n_gf + n_fr),
        "share_that_are_games_family_seats": n_gf / (n_gf + n_fr),
        "naive_registered_conversion": (conv_gf + conv_fr) / (n_gf + n_fr),
        "corrected_free_registered_conversion": conv_fr / n_fr,
        "games_family_seat_standalone_conversion": conv_gf / n_gf,
        "games_family_plan_upgrade_rate": base.upgraded.mean(),
    }
