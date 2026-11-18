# gamesFamilyConvert

A prototype of **Plan 1** from the [interference audit of The New York Times](https://github.com/jsheen/interferenceAudit/blob/main/examples/nyt/report.md) ("Plan-level upgrade"), with one change: the **only mechanism is a personalized paywall**. There is no email, no push and no in-app card. Everything a seat experiences happens on a paywall impression.

**Goal:** convert **Games Family** plans to **All Access Family**, treating the plan (the cluster) as the unit.

## Scope

There are other ways to reach All Access Family. For example:

- a single subscriber (individual All Access or News) can upgrade to the family plan;
- a new subscriber can buy it directly.

This prototype **deliberately ignores those paths**. Its focus is the case where **cluster interference has to be corrected for**: a Games Family plan already links up to four people. The person who pays (the owner) is not always the person who wants News, Cooking or The Athletic (a member). One upgrade also changes every seat's access.

## The idea in three steps

### 1. Correct the "registered user" bucket

At a News, Cooking or Athletic paywall, a Games Family seat looks exactly like a free registered user: logged in, no entitlement for that product. The uncorrected funnel pools the two groups and shows both the individual-subscription offer.

`segments.classify()` splits that bucket. It identifies the target subgroup:

> **registered users who are on a Games Family plan but not on All Access Family**

Each user in the subgroup is tagged with their `plan_id` and role (owner or member). This has two effects:

- **Treatment:** the subgroup can get a different offer, an upgrade of the plan they already share, instead of a second individual subscription.
- **Measurement:** "registered-user conversion" stops mixing people who already pay with people who don't. Each group gets its own baseline.

### 2. Treat with a personalized paywall (`paywall.py`)

| Seat | Business-as-usual (BAU) paywall | Personalized paywall |
|---|---|---|
| **Owner** (payer) | Individual subscription offer | "Upgrade your plan to All Access Family: all N seats get News, Cooking, The Athletic and Wirecutter", with the price difference and a one-tap upgrade |
| **Member** | Individual subscription offer | Shows what the plan upgrade would unlock, plus an **"Ask the person who manages your plan"** button. Nothing is shared unless the member presses it, and they preview what is sent |

- Member requests reach the owner **only as a banner on the owner's next paywall impression**, so the channel stays paywall-only.
- Banners are capped at **1 per 7 days** and **3 per experiment**.
- Free registered users, All Access Family seats, and paywalls for Games itself always get BAU.

### 3. Randomize by plan, not by seat (`assignment.py`)

The design is stratified and assigns each plan to one of three arms:

| Arm | Owner sees | Members see |
|---|---|---|
| `holdout` | BAU | BAU |
| `owner_only` | Personalized | BAU |
| `whole_plan` | Personalized | Personalized + request button |

- Each plan is assigned by `hash(salt | plan_id)`. Assignment is balanced within strata (seats 2/3/4 × prior paywall hits 0 / 1–4 / 5+) and frozen at entry.
- Seats that join later inherit their plan's arm.
- Plans that join after entry are outside the experiment and get BAU.

The three arms give three contrasts:

- `owner_only − holdout` is the **direct** effect on the payer.
- `whole_plan − holdout` is the **total** effect of treating the cluster. This is the decision quantity.
- `whole_plan − owner_only` is what the member channel adds.

#### Why randomizing by seat goes wrong

If seats are randomized independently:

- A treated member's request can upgrade a plan whose owner is in control.
- An upgrade gives access to every seat, including the control seats.

So control seats inherit the treatment's effect, and the seat-level contrast is **biased toward zero**. The simulator puts both designs on the same population to show this.

## Example run

```
$ python -m gamesfamily simulate          # 51,000 synthetic plans, seed 0
1. Registered-user correction
   Games Family seats inside the 'registered' bucket: 12.7%
   Naive 'registered' standalone conversion:          1.544%
   Corrected: free registered users only:            1.577%
   Corrected: Games Family seats only:                1.321%
   Games Family plan -> All Access Family (8 wk):     2.13%
2. Ground truth (each policy applied to every plan)
   Owner-only paywall effect:    +1.22 pp
   Whole-plan paywall effect:    +2.57 pp   (seat access +2.74 pp)
3. Cluster design (unit = plan_id)
   Whole-plan vs holdout, upgrade:      +2.36 pp  (95% CI +1.98 to +2.75)
   Owner-only vs holdout, upgrade:      +1.05 pp  (95% CI +0.70 to +1.40)
   Whole-plan vs owner-only, upgrade:   +1.31 pp  (95% CI +0.90 to +1.72)
4. Member design (unit = user_id)
   Naive treated-vs-control seat access: +0.90 pp  (95% CI +0.71 to +1.09)
   Truth for the whole-plan policy:      +2.74 pp
   Bias: -1.84 pp (33% of the true effect recovered)
   Control seats with >= 1 treated co-member: 71%
```

- **The cluster design works.** Its 95% intervals cover the true effects.
- **The seat-randomized design does not.** It recovers about a third of the true effect, and its interval excludes the truth. Clustered standard errors do not fix this: the problem is bias, not variance.
- **Every behavioural parameter in `simulate.Params` is an assumption.** The run shows how the estimators behave; it does not forecast NYT results.

## Probing spillover first (`python -m gamesfamily spillover`)

Before building any family-level paywall model, measure how much one seat's paywall changes outcomes for the other seats on the plan. Two probes do this (`spillover.py`):

1. **Probe 1, exposure analysis on seat-randomized data.** If the always-on paywall experiment already randomizes Games Family seats independently, then how many co-members were treated is random within each plan. Compare untreated seats with 0, 1, 2 or 3 treated co-members, within plan size and with plan-clustered SEs. This needs no new experiment. Two things are **unverified**: whether Games Family seats are in that experiment, and whether `user_id` can be joined to `plan_id` in the logs.
2. **Probe 2, randomized-saturation pilot.** Randomize plans to 0%, 50% or 100% of seats treated. Within 50% plans, also randomize which seats are treated. This separates direct, spillover and total effects with known assignment probabilities.

Seed 0, 51k synthetic plans:

```
PROBE 1  untreated members, change in access vs 0 treated co-members:
           k=1: +0.92 pp ±0.48   k=2: +1.94 pp ±0.65   k=3: +3.02 pp ±1.05
         seat access regression: own treatment +0.83 pp, all co-members treated +1.43 pp
         standalone purchase:    own −0.31 pp (the family offer displaces it)
PROBE 2  estimand                 estimate (95% CI)            truth
         spillover_at_half        +1.62 pp (+1.25 to +2.00)    +1.24 pp
         total_at_all             +2.67 pp (+2.27 to +3.07)    +2.74 pp
         plan_upgrade_all_vs_none +2.49 pp (+2.11 to +2.87)    +2.57 pp
         direct_at_half           +0.03 pp (−0.07 to +0.12)    +0.01 pp
```

- **Spillover is large here.** An untreated member's access rises by about 1 pp for each treated co-member. It's roughly the same size as the effect of the seat's own treatment.
- **For a shared outcome, a "direct effect" within the plan means nothing.** All seats on a plan get access together, so treated and untreated seats on the same plan can't differ. All of the effect shows up as spillover. This is why per-seat models trained on per-seat randomization miss it.
- **The estimators are reliable.** Over 40 seeds, the probe-2 estimates are unbiased and their 95% intervals cover the truth about 95% of the time. Seed 0's `spillover_at_half` interval just misses its truth by chance.
- **Use frequent outcomes on real data.** In the simulator, the only spillover channel is the plan upgrade. With real data, run both probes on outcomes that happen daily as well (paywall hits, reads, requests, Games plays). They answer in weeks, before upgrades accumulate.

**Decision rule.**

- **Spillover close to zero:** an equivalence test bounds it near zero. Then an individual-level model plus a plan-level upgrade outcome is probably enough.
- **Spillover clearly non-zero:** randomize by plan, and model the plan on every seat's paywall or meter.

### How many plans a spillover pilot needs: about 2,000 to 9,000

Sizing assumes 80% power and a two-sided 5% test. Standard errors are read off the simulator at 6k–51k plans; they scale as 1/√n.

| Pilot measured on | Spillover to detect | Plans per arm | **Pilot size (0% vs 50%, 2 arms)** |
|---|---|---|---|
| Daily outcomes (reads, paywall hits, requests, plays) | 0.10 SD | ~1,000 | **~2,000** |
| Daily outcomes | 0.05 SD | ~4,100 | ~8,200 |
| Seat access / plan upgrade (~2% baseline) | 1.0 pp | ~4,400 | **~8,800** |

For the rare outcomes in the last row, the rule is: plans per arm ≈ 17,000 × (0.51 / spillover in pp)². The spillover in the simulator is about 1.1–1.3 pp, so a pilot of about 9k plans would detect it.

**Assumptions behind the daily-outcome rows:** 2.8 seats per plan, a within-plan correlation of 0.3, and about 55% of seats untreated in 50% plans.

**If you add a 100% arm,** multiply the pilot size by 1.5 (for example ~13k plans at 1 pp).

**Pilot plans come out of the ~51k the main test needs.** Ways to keep the main test intact:

1. **Run probe 1 on the existing paywall experiment first.** It costs zero plans. Two things are unverified: whether Games Family seats are in that experiment, and whether `user_id` can be joined to `plan_id` in the logs.
2. **Run a ~2k-plan pilot on daily outcomes, then re-randomize every plan for the main test.** Leave a washout gap, and stratify on pilot arm.
3. **Fold the pilot into the main test.** The `owner_only` arm already measures spillover from owner to members. Adding a members-only arm would measure spillover from members to the owner.

## Running it

```
pip install -e '.[dev]'           # or: export PYTHONPATH=src
python -m gamesfamily simulate --plans 51000 --seed 0
python -m gamesfamily spillover --plans 51000 --seed 0
python -m gamesfamily power --p0 0.02 --mde 0.005
pytest
```

| File | Contents |
|---|---|
| `src/gamesfamily/segments.py` | Registered-user correction and target-subgroup classifier |
| `src/gamesfamily/assignment.py` | Frozen, stratified plan assignment; seat-level Bernoulli assignment for comparison |
| `src/gamesfamily/paywall.py` | Paywall decision service, member-request store, banner caps |
| `src/gamesfamily/simulate.py` | Synthetic plans and potential outcomes (common random numbers, so the truth is exact) |
| `src/gamesfamily/analysis.py` | Stratified difference in means with Neyman SEs; plan-clustered (CR1) seat-level regression; member-design diagnostics |
| `src/gamesfamily/spillover.py` | Spillover probes: exposure analysis on seat-randomized data; randomized-saturation pilot with truths |
| `src/gamesfamily/power.py` | Two-proportion sample size, MDE and design effect |

## Size needed

The source report assumed a 2% baseline 8-week upgrade rate and a +0.5 pp minimum detectable effect (MDE). Under those assumptions:

- `whole_plan` vs `holdout` needs about **13.8k plans per arm**.
- `whole_plan` vs `owner_only` needs about **16.8k per arm**.
- Sizing every arm at 17k gives **about 51k eligible Games Family plans** for three arms.

`python -m gamesfamily power` reproduces these numbers.

## How big is the family base? (NYT quarterly data)

| Metric | Value | Source |
|---|---|---|
| Total subscribers, Q3 2026 | **13.76M** | [NYT Q3 2026 results, 8-K](https://www.sec.gov/Archives/edgar/data/0000071691/000007169126000039/pressrelease9302026.htm) |
| Digital-only subscribers, Q3 2026 | **13.22M** (12.80M in Q2, 12.52M in Q1) | same |
| Net digital-only additions, Q3 2026 | ~420k | same |
| Company target | **15M** subscribers by end of 2027 | [Editor & Publisher](https://www.editorandpublisher.com/stories/the-new-york-times-adds-420000-digital-subscribers,264340) |
| Family plans launched | Sept 2025: All Access Family $30, Games Family $10 | [Nieman Lab](https://www.niemanlab.org/2025/09/the-new-york-times-launches-a-family-subscription-with-separate-wordles-for-everyone/) |
| **Family subscriptions** | **~300,000** (working estimate, *not disclosed by NYT*) | see note |

**Note on the family figure.** NYT's quarterly releases do **not** break out the number of family subscriptions. The Q3 2026 8-K says only that digital-only subscribers include "subscribers related to family subscriptions". It adds that each family subscription "is counted as one billed subscriber and one additional subscriber."

The ~300,000 figure is this project's working assumption, not a reported number. Taken at face value:

- **300k family subscriptions ≈ 2.2%** of 13.76M subscriptions (or 2% of the 15M target): a small share of the business today.
- Under NYT's counting rule, 300k family subscriptions would show up as **~600k reported subscribers (~4.4%)**.
- NYT also does not disclose how many of these are Games Family rather than All Access Family, or how many have ≥2 seats filled. The 51k eligible plans this design needs (above) may not exist yet. If the eligible base is smaller, fall back to two arms (`holdout` vs `whole_plan`) or rolling enrolment, as the source report pre-registers.

## Prices (unverified, from the source report)

| Plan | Price assumed in this prototype | What the report found |
|---|---|---|
| Games Family | $120/yr | $10/mo at launch |
| All Access Family | $442/yr ($34 per 4 weeks) | Oct 2026 third-party snapshot; $30 at launch |
| Standalone individual offer | $325/yr ($25 per 4 weeks) | Assumption |

The intro-price policy matters. If Games Family owners are eligible for an $8-per-4-weeks intro on All Access Family, year-1 revenue from an upgrade turns **negative**. Confirm this before reading any revenue result.

## Path to production

There are five stages. Each answers a different question, and each has a rule for moving on. Pilots are not simply enlarged until something reaches significance: one test, sized in advance, makes the decision (stage 3).

| # | Stage | Question it answers | Plans | Typical length |
|---|---|---|---|---|
| 1 | Offline | Is there a plausible effect, and what size of test does it need? | 0 (existing data) | 1–3 weeks |
| 2 | Live small pilot | Does it work as built, and is there spillover? | ~2,000–9,000 | 2–4 weeks |
| 3 | Full-power test | Should we ship it? | ~51,000 (17k per arm) | 8 weeks, plus a 26-week read |
| 4 | Ramp to everyone | Is it safe at scale? | All eligible plans, in steps | 2–4 weeks |
| 5 | Long-term holdout | Does the effect last, and what does it do to churn? | ~5% of plans, untreated | 6–12 months |

### 1. Offline

- **Verify the facts:**
  - the eligible base (Games Family plans with ≥2 seats);
  - prices and whether owners are eligible for the intro price;
  - whether owners billed through Apple or Google can upgrade;
  - whether `user_id` can be joined to `plan_id`.
- **Probe 1:** run the exposure analysis (`spillover.py`) on the always-on paywall experiment's existing data, if Games Family seats are in it.
- **Use past experiments** to set the baseline upgrade rate p₀ and a realistic MDE, then re-run `python -m gamesfamily power`.
- **Wire up the service:** connect `PaywallService.decide()` to the paywall decision point, behind a feature flag keyed on the frozen plan-assignment table.
- **Move on when:** the facts are verified, the eligible base is large enough for the chosen design (see "Size needed"), and the plumbing works in staging.

### 2. Live small pilot

- **Design:** randomized saturation, 0% vs 50% of seats (probe 2). Measure on daily outcomes: reads, paywall hits, requests, plays.
- **Instrumentation checks:**
  - every target paywall impression is logged with `plan_id`, role and arm, including `holdout` impressions as BAU exposures;
  - arm sizes match the design (sample-ratio-mismatch test);
  - pre-period balance holds (A/A check);
  - request-banner caps are enforced.
- **Move on when:** nothing is broken and no guardrail is breached.
- **The spillover estimate picks the main design:**
  - clearly non-zero → randomize by plan (the default here);
  - bounded near zero by an equivalence test → a simpler design that randomizes seats individually may be enough.
- **Before stage 3,** leave a washout gap, then re-randomize every plan, stratifying on pilot arm.

### 3. Full-power test (the decision)

- **Design:** plan-randomized `holdout` / `owner_only` / `whole_plan`, stratified and frozen.
- **Pre-register before launch:**
  - the primary outcome: plan upgrade within 8 weeks;
  - the fixed sequence of tests: `whole_plan > holdout`, then `owner_only > holdout`, then `whole_plan > owner_only`;
  - the analysis notebook.
- **Net revenue** counts every standalone subscription held by anyone on the plan.
- **Guardrails:**
  - Games Family cancellations (non-inferiority margin +0.5 pp);
  - members removed by owners;
  - standalone cancellations within the plan;
  - dismissals of the request banner;
  - support tickets and app-store refunds.

  Monitor them weekly, with stopping boundaries for harm only.
- **Decision rule:** ship `whole_plan` if three things hold:
  - the upgrade effect is greater than zero;
  - 26-week net revenue is positive under the verified price policy;
  - the guardrails pass.

  Ship `owner_only` if the member channel adds nothing measurable. Iterate if upgrades rise but net revenue does not.

### 4. Ramp to everyone

- **Steps:** expose eligible plans at 10%, then 25%, then 50%, then 100%. Hold each step for at least a week, and check guardrails before each increase.
- **Roll back** if any guardrail is breached. The feature flag must turn the policy off within minutes.
- **The ramp is for risk, not measurement.** It catches bugs and effects that appear only at scale, for example when every owner gets requests at once.

### 5. Long-term holdout

- **Keep ~5% of eligible plans on the BAU paywall** for 6–12 months. Add new plans to it at the same rate.
- **It measures what an 8-week test can't:**
  - novelty effects wearing off;
  - plan cancellation and churn;
  - revenue over 12 months, once intro prices end;
  - cannibalization of standalone subscriptions.
- **Expect a smaller effect than in stage 3** (winner's curse, novelty). The holdout tells you how much smaller. Use it to check the stage-3 estimate and to set p₀ and the MDE for the next iteration, which then starts again at stage 1.
