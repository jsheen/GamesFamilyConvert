from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest

from gamesfamily.analysis import analyse_cluster, analyse_member, cluster_treatment
from gamesfamily.assignment import Arm, assign_plans, assign_seats_bernoulli, hash_unit
from gamesfamily.paywall import PaywallService
from gamesfamily.power import mde, n_per_arm
from gamesfamily.segments import Plan, Segment, UserContext, classify, is_target_paywall_hit, naive_segment
from gamesfamily.simulate import Params, make_population, outcomes, true_effects

OWNER = UserContext("u-own", Plan.GAMES_FAMILY, "plan-1", is_plan_owner=True)
MEMBER = UserContext("u-mem", Plan.GAMES_FAMILY, "plan-1")
FREE = UserContext("u-free")
AAF = UserContext("u-aaf", Plan.ALL_ACCESS_FAMILY, "plan-9")
NOW = datetime(2026, 11, 18)


# --- segments ---------------------------------------------------------------

def test_correction_splits_registered_bucket():
    # Uncorrected funnel can't tell these apart at a News paywall...
    assert naive_segment(FREE, "news") == naive_segment(MEMBER, "news") == "registered"
    # ...the corrected classifier can.
    assert classify(FREE) is Segment.REGISTERED_FREE
    assert classify(MEMBER) is Segment.GAMES_FAMILY_MEMBER
    assert classify(OWNER) is Segment.GAMES_FAMILY_OWNER
    assert classify(AAF) is Segment.ALL_ACCESS_FAMILY_SEAT


def test_target_hits_only_on_bundle_products():
    assert is_target_paywall_hit(MEMBER, "news")
    assert not is_target_paywall_hit(MEMBER, "games")
    assert not is_target_paywall_hit(FREE, "news")
    assert not is_target_paywall_hit(AAF, "news")
    cooks = replace(MEMBER, standalone_products=frozenset({"cooking"}))
    assert not is_target_paywall_hit(cooks, "cooking") and is_target_paywall_hit(cooks, "news")


def test_games_family_without_plan_id_rejected():
    with pytest.raises(ValueError):
        classify(UserContext("x", Plan.GAMES_FAMILY, None))


# --- assignment -------------------------------------------------------------

def test_plan_assignment_balanced_deterministic_order_free():
    pids = [f"p{i}" for i in range(3001)]
    strata = [i % 7 for i in range(3001)]
    a1 = assign_plans(pids, strata)
    a2 = assign_plans(list(reversed(pids)), list(reversed(strata)))
    assert a1.table == a2.table
    for s in range(7):
        counts = [sum(a1.table[p] is arm for p, st in zip(pids, strata) if st == s) for arm in Arm]
        assert max(counts) - min(counts) <= 1


def test_hash_uniformish():
    u = np.array([hash_unit(str(i), "salt") for i in range(20000)])
    assert 0.49 < u.mean() < 0.51 and u.min() >= 0 and u.max() < 1


# --- paywall service --------------------------------------------------------

def _service(arm: Arm) -> PaywallService:
    return PaywallService(assign_plans(["plan-1"], arms=(arm,)))


def test_paywall_variants_by_arm():
    assert _service(Arm.HOLDOUT).decide(MEMBER, "news", NOW).variant == "bau"
    s = _service(Arm.OWNER_ONLY)
    assert s.decide(OWNER, "news", NOW).variant == "family_upgrade_owner"
    assert s.decide(MEMBER, "news", NOW).variant == "bau"
    s = _service(Arm.WHOLE_PLAN)
    d = s.decide(MEMBER, "news", NOW)
    assert d.variant == "family_upgrade_member" and d.show_request_button
    assert s.decide(FREE, "news", NOW).variant == "bau"
    assert s.decide(MEMBER, "games", NOW).variant == "bau"


def test_member_on_new_plan_after_entry_gets_bau():
    late = replace(MEMBER, family_plan_id="plan-late")
    d = _service(Arm.WHOLE_PLAN).decide(late, "news", NOW)
    assert d.variant == "bau" and d.arm is None


def test_request_reaches_owner_paywall_with_caps():
    s = _service(Arm.WHOLE_PLAN)
    s.member_requests_upgrade(MEMBER, s.decide(MEMBER, "news", NOW))
    assert s.decide(OWNER, "news", NOW).pending_requests_shown == 1
    assert s.decide(OWNER, "news", NOW).pending_requests_shown == 0  # consumed
    for k in range(1, 12):  # every 3 days for 33 days
        t = NOW + timedelta(days=3 * k)
        s.member_requests_upgrade(MEMBER, s.decide(MEMBER, "news", t))
        s.decide(OWNER, "news", t)
    assert s.requests._by_plan["plan-1"].banners_shown == 3  # 1 per 7 days, 3 max


def test_request_requires_button():
    s = _service(Arm.HOLDOUT)
    with pytest.raises(PermissionError):
        s.member_requests_upgrade(MEMBER, s.decide(MEMBER, "news", NOW))


# --- simulation + analysis --------------------------------------------------

@pytest.fixture(scope="module")
def pop():
    return make_population(replace(Params(), n_plans=40_000), seed=7)


def test_outcomes_deterministic_and_monotone(pop):
    none = outcomes(pop, np.zeros(pop.n_seats, bool))
    allt = outcomes(pop, np.ones(pop.n_seats, bool))
    assert np.array_equal(none.upgraded, outcomes(pop, np.zeros(pop.n_seats, bool)).upgraded)
    assert (allt.upgraded >= none.upgraded).all()  # treatment never prevents an upgrade
    assert 0.01 < none.upgraded.mean() < 0.03  # ~2% baseline assumption


def test_cluster_design_recovers_truth(pop):
    truth = true_effects(pop)
    asg = assign_plans(pop.plan_ids, pop.strata().tolist(), salt="t")
    plan_arm, treated = cluster_treatment(pop, asg)
    assert set(np.unique(plan_arm)) == {0, 1, 2}
    res = analyse_cluster(pop, asg)
    assert res["whole_plan_vs_holdout_upgrade"].covers(truth["whole_plan_upgrade"])
    assert res["owner_only_vs_holdout_upgrade"].covers(truth["owner_only_upgrade"])


def test_member_design_is_biased_toward_zero(pop):
    truth = true_effects(pop)["whole_plan_seat_access"]
    naive = analyse_member(pop, assign_seats_bernoulli(pop.user_ids, salt="t"))
    est = naive["naive_seat_access_clustered"]
    assert est.est > 0
    assert not est.covers(truth) and est.ci[1] < truth
    assert naive["control_access_some_treated_comember"] > naive["control_access_no_treated_comember"]


# --- power ------------------------------------------------------------------

def test_power_matches_report():
    assert abs(n_per_arm(0.020, 0.025) - 13_806) <= 2
    assert abs(n_per_arm(0.025, 0.030) - 16_790) <= 2
    assert abs(mde(0.02, 10_000) - 0.0055) < 0.0002
