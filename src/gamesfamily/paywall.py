"""Paywall decisioning: the only treatment surface in this prototype.

No email, push or in-app cards. Everything a seat experiences happens on a
paywall impression for a product the Games Family plan does not include.

Variants
--------
* ``bau``: the existing paywall (individual subscription offer).
* ``family_upgrade_owner``: owner sees "Upgrade your plan to All Access
  Family: all N seats get News, Cooking, The Athletic and Wirecutter", with
  the incremental price and a one-tap upgrade.
* ``family_upgrade_member``: member sees what the plan upgrade would unlock
  and a "Ask the person who manages your plan" button. Nothing about the
  member is shared unless they press it, and they preview what is sent.

Member requests reach the owner only as a banner on the owner's *next
paywall impression*, capped at one per 7 days and three per experiment.
In the cluster design this is internal to the plan. In a member-level
design it is exactly the interference channel: a treated member changes
what a control owner sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .assignment import Arm, FrozenAssignment, seat_is_treated
from .segments import Segment, UserContext, classify, is_target_paywall_hit

REQUEST_BANNER_MIN_GAP = timedelta(days=7)
REQUEST_BANNER_MAX_TOTAL = 3


@dataclass(frozen=True)
class PaywallDecision:
    variant: str
    segment: Segment
    arm: Arm | None
    plan_id: str | None
    show_request_button: bool = False
    pending_requests_shown: int = 0  # banner on owner paywall, 0 = no banner
    logged_exposure: bool = False  # True = counts as a treatment exposure in analysis


@dataclass
class _RequestState:
    pending: set[str] = field(default_factory=set)
    banners_shown: int = 0
    last_banner_at: datetime | None = None


class RequestStore:
    """Member → owner requests, delivered only through the owner's paywall."""

    def __init__(self) -> None:
        self._by_plan: dict[str, _RequestState] = {}

    def add(self, plan_id: str, member_id: str) -> None:
        self._by_plan.setdefault(plan_id, _RequestState()).pending.add(member_id)

    def take_banner(self, plan_id: str, now: datetime) -> int:
        """Return how many requests to show now (0 if none or capped)."""
        st = self._by_plan.get(plan_id)
        if st is None or not st.pending or st.banners_shown >= REQUEST_BANNER_MAX_TOTAL:
            return 0
        if st.last_banner_at is not None and now - st.last_banner_at < REQUEST_BANNER_MIN_GAP:
            return 0
        n = len(st.pending)
        st.pending.clear()
        st.banners_shown += 1
        st.last_banner_at = now
        return n


class PaywallService:
    def __init__(self, assignment: FrozenAssignment, requests: RequestStore | None = None):
        self.assignment = assignment
        self.requests = requests or RequestStore()

    def _arm(self, ctx: UserContext) -> Arm | None:
        if self.assignment.unit == "plan":
            return self.assignment.arm_for(ctx.family_plan_id or "")
        return self.assignment.arm_for(ctx.user_id or "")

    def decide(self, ctx: UserContext, product: str, now: datetime) -> PaywallDecision:
        seg = classify(ctx)
        if not is_target_paywall_hit(ctx, product):
            return PaywallDecision("bau", seg, None, ctx.family_plan_id)

        arm = self._arm(ctx)
        owner = seg is Segment.GAMES_FAMILY_OWNER
        if arm is None:  # not eligible at entry: BAU, outside the experiment
            return PaywallDecision("bau", seg, None, ctx.family_plan_id)

        if self.assignment.unit == "plan":
            treated = seat_is_treated(arm, owner)
        else:  # seat design: each seat's own draw, regardless of role
            treated = arm is Arm.WHOLE_PLAN

        banner = self.requests.take_banner(ctx.family_plan_id, now) if owner else 0

        if not treated:
            return PaywallDecision(
                "bau", seg, arm, ctx.family_plan_id,
                pending_requests_shown=banner, logged_exposure=True,
            )
        if owner:
            return PaywallDecision(
                "family_upgrade_owner", seg, arm, ctx.family_plan_id,
                pending_requests_shown=banner, logged_exposure=True,
            )
        return PaywallDecision(
            "family_upgrade_member", seg, arm, ctx.family_plan_id,
            show_request_button=True, logged_exposure=True,
        )

    def member_requests_upgrade(self, ctx: UserContext, decision: PaywallDecision) -> None:
        """Called when a member presses the request button on their paywall."""
        if not decision.show_request_button:
            raise PermissionError("request button was not shown to this seat")
        self.requests.add(ctx.family_plan_id, ctx.user_id)
