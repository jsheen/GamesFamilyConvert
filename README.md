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

## Running it

```
pip install -e '.[dev]'           # or: export PYTHONPATH=src
python -m gamesfamily simulate --plans 51000 --seed 0
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

## Next steps toward a real test

1. Verify the eligible base (Games Family plans with ≥2 seats), prices, intro eligibility, and whether app-store-billed owners can upgrade.
2. Wire `PaywallService.decide()` into the paywall decision point, behind a feature flag keyed on the frozen plan-assignment table.
3. Log every target paywall impression, including `holdout` ones as BAU exposures, with `plan_id`, role and arm.
4. Pre-register the primary outcome (8-week plan upgrade) and the fixed-sequence tests (`whole_plan > holdout` → `owner_only > holdout` → `whole_plan > owner_only`). Count net revenue across every standalone subscription in the cluster.
5. Guardrails: Games Family cancellations, members removed by owners, standalone cancellations in the cluster, and request-banner dismissals.
