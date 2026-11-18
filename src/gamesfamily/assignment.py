"""Deterministic, frozen assignment of plans (clusters) or seats (members) to arms.

Cluster design (the one to run): the unit is ``plan_id``. Every seat on a
plan inherits the plan's arm, including seats that join after assignment.

Member design (the comparison): the unit is ``user_id``. It is included to
show the bias, because one seat's treatment changes co-members' outcomes.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Hashable, Iterable, Mapping, Sequence


class Arm(str, Enum):
    HOLDOUT = "holdout"  # business-as-usual paywall for every seat
    OWNER_ONLY = "owner_only"  # personalized paywall for the owner; members BAU
    WHOLE_PLAN = "whole_plan"  # personalized paywall for owner and all members


CLUSTER_ARMS: tuple[Arm, ...] = (Arm.HOLDOUT, Arm.OWNER_ONLY, Arm.WHOLE_PLAN)


def hash_unit(unit_id: str, salt: str) -> float:
    """Map an id to a stable uniform number in [0, 1)."""
    digest = hashlib.sha256(f"{salt}|{unit_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass(frozen=True)
class FrozenAssignment:
    """Assignment table written once at entry and never recomputed."""

    salt: str
    unit: str  # "plan" or "seat"
    table: Mapping[str, Arm]

    def arm_for(self, unit_id: str) -> Arm | None:
        """None means the unit was not eligible at entry (gets BAU, not analysed)."""
        return self.table.get(unit_id)


def assign_plans(
    plan_ids: Sequence[str],
    strata: Sequence[Hashable] | None = None,
    arms: Sequence[Arm] = CLUSTER_ARMS,
    salt: str = "gf-paywall-v1",
) -> FrozenAssignment:
    """Stratified, balanced plan-level assignment.

    Within each stratum, plans are ordered by their salted hash and dealt to
    arms in turn. Arm sizes within a stratum therefore differ by at most one,
    and the result does not depend on input order.
    """
    if strata is None:
        strata = [0] * len(plan_ids)
    if len(strata) != len(plan_ids):
        raise ValueError("strata must align with plan_ids")
    if len(set(plan_ids)) != len(plan_ids):
        raise ValueError("duplicate plan_id")

    by_stratum: dict[Hashable, list[str]] = defaultdict(list)
    for pid, s in zip(plan_ids, strata):
        by_stratum[s].append(pid)

    table: dict[str, Arm] = {}
    for s, pids in by_stratum.items():
        ordered = sorted(pids, key=lambda p: hash_unit(p, salt))
        # Rotate the starting arm per stratum so leftovers don't all go to arm 0.
        offset = int(hash_unit(repr(s), salt + "|offset") * len(arms))
        for i, pid in enumerate(ordered):
            table[pid] = arms[(i + offset) % len(arms)]
    return FrozenAssignment(salt=salt, unit="plan", table=table)


def assign_seats_bernoulli(
    user_ids: Iterable[str], p_treat: float = 0.5, salt: str = "gf-paywall-seat-v1"
) -> FrozenAssignment:
    """Member-level design: each seat independently gets the personalized paywall."""
    table = {
        uid: (Arm.WHOLE_PLAN if hash_unit(uid, salt) < p_treat else Arm.HOLDOUT)
        for uid in user_ids
    }
    return FrozenAssignment(salt=salt, unit="seat", table=table)


def seat_is_treated(arm: Arm, is_owner: bool) -> bool:
    """Whether a seat on a plan in ``arm`` sees the personalized paywall."""
    if arm is Arm.WHOLE_PLAN:
        return True
    if arm is Arm.OWNER_ONLY:
        return is_owner
    return False
