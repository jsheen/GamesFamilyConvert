"""Command line: ``python -m gamesfamily simulate`` / ``python -m gamesfamily power``."""

from __future__ import annotations

import argparse
from dataclasses import replace

from .analysis import Estimate, analyse_cluster, analyse_member
from .assignment import assign_plans, assign_seats_bernoulli
from .power import mde, n_per_arm
from .simulate import Params, make_population, outcomes, registered_user_report, true_effects


def _pp(x: float) -> str:
    return f"{100 * x:+.2f} pp"


def _fmt(e: Estimate, pct: bool = True) -> str:
    lo, hi = e.ci
    if pct:
        return f"{_pp(e.est)}  (95% CI {100 * lo:+.2f} to {100 * hi:+.2f})"
    return f"${e.est:+.2f}  (95% CI {lo:+.2f} to {hi:+.2f})"


def cmd_simulate(args: argparse.Namespace) -> None:
    pop = make_population(replace(Params(), n_plans=args.plans), seed=args.seed)
    truth = true_effects(pop)
    reg = registered_user_report(pop)

    print(f"Synthetic population: {pop.n_plans:,} Games Family plans, {pop.n_seats:,} seats (seed {args.seed})")
    print("All behavioural parameters are assumptions, not NYT data.\n")

    print("1. Registered-user correction (BAU paywall, users with >= 1 non-Games paywall hit)")
    print(f"   Games Family seats inside the 'registered' bucket: {reg['share_that_are_games_family_seats']:.1%}")
    print(f"   Naive 'registered' standalone conversion:          {reg['naive_registered_conversion']:.3%}")
    print(f"   Corrected: free registered users only:            {reg['corrected_free_registered_conversion']:.3%}")
    print(f"   Corrected: Games Family seats only:                {reg['games_family_seat_standalone_conversion']:.3%}")
    print(f"   Games Family plan -> All Access Family (8 wk):     {reg['games_family_plan_upgrade_rate']:.2%}\n")

    print("2. Ground truth (each policy applied to every plan)")
    print(f"   Baseline plan upgrade rate:   {truth['baseline_upgrade']:.2%}")
    print(f"   Owner-only paywall effect:    {_pp(truth['owner_only_upgrade'])}")
    print(f"   Whole-plan paywall effect:    {_pp(truth['whole_plan_upgrade'])}   (seat access {_pp(truth['whole_plan_seat_access'])})")
    print(f"   Whole-plan net revenue/plan:  ${truth['whole_plan_net_revenue']:+.2f} per year\n")

    c = analyse_cluster(pop, assign_plans(pop.plan_ids, pop.strata().tolist(), salt=f"s{args.seed}"))
    print("3. Cluster design (unit = plan_id; holdout / owner-only / whole-plan, stratified)")
    print(f"   Whole-plan vs holdout, upgrade:      {_fmt(c['whole_plan_vs_holdout_upgrade'])}")
    print(f"   Owner-only vs holdout, upgrade:      {_fmt(c['owner_only_vs_holdout_upgrade'])}")
    print(f"   Whole-plan vs owner-only, upgrade:   {_fmt(c['whole_plan_vs_owner_only_upgrade'])}")
    print(f"   Whole-plan vs holdout, seat access:  {_fmt(c['whole_plan_vs_holdout_seat_access'])}")
    print(f"   Whole-plan vs holdout, net $/plan/yr: {_fmt(c['whole_plan_vs_holdout_net_revenue'], pct=False)}\n")

    m = analyse_member(pop, assign_seats_bernoulli(pop.user_ids, salt=f"m{args.seed}"))
    naive = m["naive_seat_access_clustered"]
    print("4. Member design (unit = user_id, Bernoulli 0.5). Shown to quantify the interference bias.")
    print(f"   Naive treated-vs-control seat access: {_fmt(m['naive_seat_access_iid'])}  [iid SE]")
    print(f"                                         {_fmt(naive)}  [plan-clustered SE]")
    print(f"   Truth for the whole-plan policy:      {_pp(truth['whole_plan_seat_access'])}")
    print(f"   Bias: {_pp(naive.est - truth['whole_plan_seat_access'])} "
          f"({naive.est / truth['whole_plan_seat_access']:.0%} of the true effect recovered)")
    print(f"   Control seats with >= 1 treated co-member: {m['control_seats_with_treated_comember_share']:.0%}")
    print(f"   Control seat access, no treated co-member:  {m['control_access_no_treated_comember']:.2%}")
    print(f"   Control seat access, some treated co-member: {m['control_access_some_treated_comember']:.2%}  <- spillover")


def cmd_spillover(args: argparse.Namespace) -> None:
    import numpy as np

    from . import spillover as sp

    pop = make_population(replace(Params(), n_plans=args.plans), seed=args.seed)
    print(f"Synthetic population: {pop.n_plans:,} plans, {pop.n_seats:,} seats (seed {args.seed}). "
          "Parameters are assumptions.\n")

    # Probe 1: seat-randomized data, as the always-on RCT would produce.
    asg = assign_seats_bernoulli(pop.user_ids, salt=f"m{args.seed}")
    treated = np.array([asg.arm_for(u).value == "whole_plan" for u in pop.user_ids])
    o = outcomes(pop, treated)
    access = o.seat_access.astype(float)
    print("PROBE 1: exposure analysis on seat-randomized data (Bernoulli 0.5 per seat)")
    print("  Untreated seats: change in All Access (via plan) vs 0 treated co-members")
    for role in ("owner", "member"):
        c = sp.spillover_curve(pop, treated, access, role)
        cells = "   ".join(f"k={k}: {_pp(e.est)} ±{196 * e.se:.2f}" for k, e in c.by_k.items())
        print(f"    untreated {role + 's':<7} (base {c.control_mean:.2%}, n={c.n_seats:,}): {cells}")
    reg = sp.share_regression(pop, treated, access)
    print(f"  Regression, seat access: own treatment {_fmt(reg['direct_none'])}")
    print(f"                           all co-members treated (spillover) {_fmt(reg['spillover_full'])}")
    sa = sp.share_regression(pop, treated, o.standalone.astype(float))
    print(f"  Regression, standalone purchase: own {_fmt(sa['direct_none'])}")
    print(f"                                   spillover {_fmt(sa['spillover_full'])}")
    dose = sp.plan_dose_response(pop, treated, o.upgraded.astype(float))
    print("  Plan upgrade vs # seats treated (vs 0): "
          + "   ".join(f"{k}: {_pp(e.est)} ±{196 * e.se:.2f}" for k, e in dose.items()))

    # Probe 2: randomized saturation pilot.
    plan_arm = sp.assign_saturation(pop, salt=f"s{args.seed}")
    half = sp.half_vector(pop, salt=f"h{args.seed}")
    est = sp.analyse_saturation(pop, plan_arm, half)
    truth = sp.saturation_truth(pop, half)
    print("\nPROBE 2: randomized saturation pilot (plans: 0% / 50% / 100% of seats treated)")
    print(f"  {'estimand':<28}{'estimate (95% CI)':<40}truth")
    for key, e in est.items():
        print(f"  {key:<28}{_fmt(e):<40}{_pp(truth[key])}")
    print("\n  Seat access is shared by the plan, so the within-plan 'direct' contrast is ~0:")
    print("  for a shared outcome, almost all of the effect shows up as spillover.")


def cmd_power(args: argparse.Namespace) -> None:
    p0, d = args.p0, args.mde
    print(f"Plans per arm, p0={p0:.3f}, MDE={_pp(d)}: {n_per_arm(p0, p0 + d):,}")
    print(f"Plans per arm, whole-plan vs owner-only ({p0 + d:.3f} vs {p0 + 2 * d:.3f}): {n_per_arm(p0 + d, p0 + 2 * d):,}")
    for n in (5_000, 10_000, 17_000, 50_000):
        print(f"  MDE with {n:>6,} plans/arm: {_pp(mde(p0, n))}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gamesfamily")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate", help="run both designs on a synthetic population")
    s.add_argument("--plans", type=int, default=51_000)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_simulate)
    sp_ = sub.add_parser("spillover", help="probe cluster-level spillover (exposure analysis + saturation pilot)")
    sp_.add_argument("--plans", type=int, default=51_000)
    sp_.add_argument("--seed", type=int, default=0)
    sp_.set_defaults(func=cmd_spillover)
    p = sub.add_parser("power", help="plan-level sample size")
    p.add_argument("--p0", type=float, default=0.02)
    p.add_argument("--mde", type=float, default=0.005)
    p.set_defaults(func=cmd_power)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
