from dataclasses import replace

import numpy as np
import pytest

from gamesfamily import spillover as sp
from gamesfamily.assignment import assign_seats_bernoulli
from gamesfamily.simulate import Params, make_population, outcomes


@pytest.fixture(scope="module")
def pop():
    return make_population(replace(Params(), n_plans=40_000), seed=7)


def test_co_members_treated_counts(pop):
    treated = pop.seat_is_owner.copy()
    k = sp.co_members_treated(pop, treated)
    assert (k[pop.seat_is_owner] == 0).all()
    assert (k[~pop.seat_is_owner] == 1).all()


def test_half_vector_treats_floor_half(pop):
    half = sp.half_vector(pop)
    per_plan = np.bincount(pop.seat_plan, weights=half, minlength=pop.n_plans)
    assert np.array_equal(per_plan, pop.plan_seats // 2)
    assert 0.3 < half[pop.seat_is_owner].mean() < 0.6  # owner chosen at random


def test_saturation_arms_balanced(pop):
    arm = sp.assign_saturation(pop)
    counts = np.bincount(arm, minlength=3)
    assert counts.max() - counts.min() <= len(np.unique(pop.strata()))


def test_probe1_detects_spillover_onto_untreated_members(pop):
    asg = assign_seats_bernoulli(pop.user_ids, salt="t")
    treated = np.array([asg.arm_for(u).value == "whole_plan" for u in pop.user_ids])
    access = outcomes(pop, treated).seat_access.astype(float)
    curve = sp.spillover_curve(pop, treated, access, "member")
    assert curve.by_k[2].ci[0] > 0  # 2 treated co-members: significantly positive
    assert curve.by_k[2].est > curve.by_k[1].est
    assert sp.share_regression(pop, treated, access)["spillover_full"].ci[0] > 0


def test_probe2_recovers_truth(pop):
    arm = sp.assign_saturation(pop, salt="t")
    half = sp.half_vector(pop, salt="t")
    est = sp.analyse_saturation(pop, arm, half)
    truth = sp.saturation_truth(pop, half)
    for key in ("spillover_at_half", "total_at_all", "plan_upgrade_all_vs_none"):
        assert est[key].covers(truth[key]), key
    assert abs(est["direct_at_half"].est) < 0.002  # shared outcome: no within-plan contrast
