# gamesFamilyConvert

A prototype of **Plan 1** from the [NYT interference audit](https://github.com/jsheen/interferenceAudit/blob/main/examples/nyt/report.md), using **only a personalized paywall**: no email, push or in-app cards. The goal is to convert **Games Family** plans to **All Access Family**, with the plan (the cluster) as the unit of treatment.

**Scope.** Other routes to All Access Family exist, such as a single subscriber upgrading. This prototype focuses on the case where **cluster interference must be corrected for**: the owner who pays is often not the member who wants News, and one upgrade changes every seat's access.

## The idea

**1. Correct the "registered user" bucket.** At a News, Cooking or Athletic paywall, a Games Family seat looks exactly like a free registered user: logged in, but without that product. `segments.classify()` separates out the target subgroup, **registered users on a Games Family plan but not All Access Family**, and tags each one with `plan_id` and role (owner or member). That subgroup can then get its own offer and its own conversion baseline.

**2. Treat with a personalized paywall** (`paywall.py`).

- **Owner:** an offer to upgrade the whole plan to All Access Family, showing the price difference, with a one-tap upgrade.
- **Member:** what the upgrade would unlock, plus an **"Ask the person who manages your plan"** button.
- **Requests** reach the owner only as a banner on the owner's next paywall, at most once a week and three times in total.
- **Everyone else** sees the normal paywall (BAU, business as usual).

**3. Randomize by plan, not by seat** (`assignment.py`). Plans are hashed and frozen at entry, stratified by number of seats and prior paywall hits.

| Arm | Owner | Members |
|---|---|---|
| `holdout` | BAU | BAU |
| `owner_only` | Personalized | BAU |
| `whole_plan` | Personalized | Personalized + request button |

`whole_plan − holdout` is the total effect: the number to decide on. `owner_only − holdout` isolates the payer, and `whole_plan − owner_only` measures the member channel.

**Why seat-level randomization fails.** A treated member's request can upgrade a plan whose owner is in control, and an upgrade gives access to every seat. Control seats therefore inherit the treatment's effect, which biases the estimate toward zero.

## Results from the simulator

All behavioural parameters are assumptions, not NYT data. Run on 51k synthetic plans:

| Design | Estimate (95% CI) | True effect |
|---|---|---|
| Plan-randomized, `whole_plan` vs `holdout`, upgrade | +2.36 pp (+1.98 to +2.75) | +2.57 pp |
| Plan-randomized, `owner_only` vs `holdout`, upgrade | +1.05 pp (+0.70 to +1.40) | +1.22 pp |
| Seat-randomized, seat access | +0.90 pp (+0.71 to +1.09) | +2.74 pp |

Seat-level randomization recovers only about a third of the true effect. Clustered standard errors don't fix that, because it's bias, not noise.

## Probing spillover first

`spillover.py` measures how much one seat's paywall changes outcomes for the others on its plan.

- **Probe 1, free:** reuse NYT's existing always-on paywall experiment. If it randomizes Games Family seats individually, compare untreated seats by how many co-members happened to be treated. Two things are unverified: whether these seats are in that experiment, and whether `user_id` can be joined to `plan_id`.
- **Probe 2, pilot:** randomize plans to 0%, 50% or 100% of seats treated. This separates direct, spillover and total effects.

In the simulator, an untreated member's access rises about 1 pp per treated co-member, about as much as a seat's own treatment. With real data, measure daily outcomes too (reads, requests, plays) for faster answers.

**Pilot size: about 2,000 to 9,000 plans** (0% vs 50%, 80% power):

| Measured on | Spillover to detect | Plans |
|---|---|---|
| Daily outcomes | 0.10 SD | ~2,000 |
| Daily outcomes | 0.05 SD | ~8,200 |
| Plan upgrade (~2% baseline) | 1.0 pp | ~8,800 |

Pilot plans come out of the main test's pool, so run probe 1 first, or re-randomize all plans after the pilot.

## Size of the main test and the family base

Assuming a 2% baseline upgrade rate and a +0.5 pp minimum detectable effect (MDE), the main test needs **~17k plans per arm, ~51k eligible Games Family plans** in total.

| NYT metric (quarterly data) | Value |
|---|---|
| Total subscribers, Q3 2026 | 13.76M ([8-K](https://www.sec.gov/Archives/edgar/data/0000071691/000007169126000039/pressrelease9302026.htm)) |
| Digital-only subscribers, Q3 2026 | 13.22M |
| Company target | 15M by end of 2027 ([E&P](https://www.editorandpublisher.com/stories/the-new-york-times-adds-420000-digital-subscribers,264340)) |
| **Family subscriptions** | **~300,000**: working estimate, *not disclosed by NYT* |

**What ~300k family subscriptions would mean:**

- **~2.2% of all subscriptions:** small today.
- **~600k reported subscribers:** NYT counts each family plan as two.
- **Base possibly too small:** the number of Games Family plans with ≥2 seats is unknown, so the 51k may not exist. Fall back to two arms or rolling enrolment.

**Prices are unverified.** The prototype assumes Games Family $120/yr and All Access Family $442/yr. If owners get the $8 intro price, year-1 revenue from an upgrade turns negative.

## Path to production

| # | Stage | Question | Plans | Length |
|---|---|---|---|---|
| 1 | Offline | Is there a plausible effect, and how big must the test be? | 0 | 1–3 wk |
| 2 | Small live pilot | Does it work as built, and is there spillover? | ~2k–9k | 2–4 wk |
| 3 | Full-power test | Should we ship it? | ~51k | 8 wk, plus a 26-wk read |
| 4 | Ramp to everyone | Is it safe at scale? | All, in steps | 2–4 wk |
| 5 | Long-term holdout | Does the effect last? | ~5% | 6–12 mo |

1. **Offline:** verify the eligible base, prices and the `user_id`→`plan_id` join, and run probe 1.
2. **Pilot:** run probe 2, and check logging and arm sizes.
3. **Full test:** pre-register the 8-week upgrade outcome. Ship if upgrades and 26-week net revenue rise without breaching guardrails (cancellations, members removed by owners).
4. **Ramp:** 10%, then 25%, 50% and 100% of plans, with fast rollback.
5. **Holdout:** measure fading and churn. Expect a smaller effect than in stage 3.

## Running it

```
pip install -e '.[dev]'
python -m gamesfamily simulate     # main designs vs ground truth
python -m gamesfamily spillover    # probes 1 and 2
python -m gamesfamily power        # sample sizes
pytest
```

Code lives in `src/gamesfamily/`: `segments`, `assignment`, `paywall`, `simulate`, `analysis`, `spillover`, `power`.
