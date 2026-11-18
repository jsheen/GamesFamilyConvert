"""The registered-user correction.

NYT's funnel treats anyone who is logged in but lacks an entitlement as a
"registered user" at that product's paywall. A Games Family seat (owner or
invited member) who opens a News, Cooking or Athletic story looks exactly
like a free registered user there: logged in, no entitlement, paywalled.

Pooling the two causes two problems:

1. **Treatment.** The default paywall pitches an *individual* subscription.
   For a Games Family seat the better offer is an upgrade of the plan they
   are already on, which unlocks every seat at once.
2. **Measurement.** "Registered-user paywall conversion" mixes free users
   with people who already pay, so baselines and lift estimates for both
   groups are biased.

The correction splits the registered-user bucket so the target subgroup,
*registered users who are on a Games Family plan but not on All Access
Family*, can be identified, measured and treated on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Products a Games Family seat does NOT have, so a paywall on these is the
# moment the personalized offer can appear.
BUNDLE_ONLY_PRODUCTS = frozenset({"news", "cooking", "athletic", "wirecutter", "audio"})


class Plan(str, Enum):
    NONE = "none"
    GAMES_FAMILY = "games_family"
    ALL_ACCESS_FAMILY = "all_access_family"


class Segment(str, Enum):
    ANONYMOUS = "anonymous"
    REGISTERED_FREE = "registered_free"  # logged in, no paid entitlement at all
    INDIVIDUAL_SUBSCRIBER = "individual_subscriber"  # standalone sub(s), no family plan
    GAMES_FAMILY_OWNER = "games_family_owner"  # target subgroup: payer
    GAMES_FAMILY_MEMBER = "games_family_member"  # target subgroup: invited seat
    ALL_ACCESS_FAMILY_SEAT = "all_access_family_seat"  # already converted; never targeted


TARGET_SEGMENTS = frozenset({Segment.GAMES_FAMILY_OWNER, Segment.GAMES_FAMILY_MEMBER})


@dataclass(frozen=True)
class UserContext:
    """What the paywall service knows about the viewer at request time."""

    user_id: str | None  # None = not logged in
    family_plan: Plan = Plan.NONE
    family_plan_id: str | None = None
    is_plan_owner: bool = False
    standalone_products: frozenset[str] = field(default_factory=frozenset)


def naive_segment(ctx: UserContext, product: str) -> str:
    """How the uncorrected funnel buckets a paywall hit (for comparison only)."""
    if ctx.user_id is None:
        return Segment.ANONYMOUS.value
    if product in ctx.standalone_products or ctx.family_plan is Plan.ALL_ACCESS_FAMILY:
        return "entitled"
    return "registered"  # free users and Games Family seats land here together


def classify(ctx: UserContext) -> Segment:
    """Corrected segment. All Access Family takes precedence over everything."""
    if ctx.user_id is None:
        return Segment.ANONYMOUS
    if ctx.family_plan is Plan.ALL_ACCESS_FAMILY:
        return Segment.ALL_ACCESS_FAMILY_SEAT
    if ctx.family_plan is Plan.GAMES_FAMILY:
        if ctx.family_plan_id is None:
            raise ValueError("Games Family seat without a plan_id: cannot cluster")
        return Segment.GAMES_FAMILY_OWNER if ctx.is_plan_owner else Segment.GAMES_FAMILY_MEMBER
    if ctx.standalone_products:
        return Segment.INDIVIDUAL_SUBSCRIBER
    return Segment.REGISTERED_FREE


def is_target_paywall_hit(ctx: UserContext, product: str) -> bool:
    """True when this paywall impression can carry the family-upgrade offer."""
    return (
        classify(ctx) in TARGET_SEGMENTS
        and product in BUNDLE_ONLY_PRODUCTS
        and product not in ctx.standalone_products
    )
