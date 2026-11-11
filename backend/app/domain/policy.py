"""Cancellation policy engine (spec Module C).

Pure and deterministic. A policy is a set of time-based tiers: the closer to
travel the cancellation happens, the larger the penalty. Given a policy, the
original amount, and how many days before travel the cancellation occurred, the
engine produces the deduction line items the refund calculation engine consumes —
each tagged with the policy version as evidence (spec: "Every calculated expected
refund must reference the applicable policy version and its evidence").

A penalty tier may be a fixed amount, a percentage of the original, or whichever
is greater — the three shapes Indian airline/hotel policies actually use.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import List, Sequence

from .calculation import LineItem, LineKind
from .money import Money


class PenaltyBasis(str, Enum):
    FIXED = "FIXED"              # a fixed money amount
    PERCENT = "PERCENT"         # a percentage of the original amount
    GREATER_OF = "GREATER_OF"   # max(fixed, percent) — common for airlines


@dataclass(frozen=True, slots=True)
class PolicyTier:
    """Applies when ``min_days_before <= days_before_travel`` and it is the most
    specific (highest ``min_days_before``) tier that qualifies... see
    :func:`select_tier` for the exact rule."""

    min_days_before: int           # inclusive lower bound on days-before-travel
    basis: PenaltyBasis
    fixed_amount: str = "0"        # decimal string, in the policy currency
    percent: str = "0"             # decimal string, e.g. "25" for 25%
    label: str = "Cancellation penalty"


@dataclass(frozen=True, slots=True)
class CancellationPolicy:
    version: str                   # e.g. "indigo-domestic-v3"
    currency: str
    tiers: Sequence[PolicyTier]
    non_refundable_fixed: str = "0"   # always-withheld fee (e.g. convenience fee)
    non_refundable_label: str = "Non-refundable fee"


class PolicyError(Exception):
    pass


def select_tier(policy: CancellationPolicy, days_before_travel: int) -> PolicyTier:
    """Pick the applicable tier.

    Tiers are thresholds on how *early* the cancellation is. The applicable tier is
    the one with the largest ``min_days_before`` that is still <= the actual
    days-before-travel. (More days before travel = earlier = lower penalty tier.)
    A no-show (negative days) falls into the lowest/most-penal tier.
    """
    if not policy.tiers:
        raise PolicyError("policy has no tiers")
    eligible = [t for t in policy.tiers if days_before_travel >= t.min_days_before]
    if not eligible:
        # Cancelled later than the most penal threshold -> most penal tier
        # (the one with the smallest min_days_before).
        return min(policy.tiers, key=lambda t: t.min_days_before)
    return max(eligible, key=lambda t: t.min_days_before)


def _penalty_amount(tier: PolicyTier, original: Money) -> Money:
    fixed = Money.from_decimal(tier.fixed_amount, original.currency)
    pct = original.multiply_ratio(Decimal(tier.percent) / Decimal(100))
    if tier.basis is PenaltyBasis.FIXED:
        return fixed
    if tier.basis is PenaltyBasis.PERCENT:
        return pct
    return fixed if fixed >= pct else pct  # GREATER_OF


def deduction_lines(
    policy: CancellationPolicy, original: Money, days_before_travel: int
) -> List[LineItem]:
    """Build the deduction line items implied by the policy for this cancellation.

    Returns CANCELLATION_DEDUCTION (and NON_REFUNDABLE, if any) lines, each
    referencing the policy version as evidence. The caller passes these — plus the
    ORIGINAL line — to ``compute_supplier_refund``.
    """
    if original.currency != policy.currency:
        raise PolicyError("policy currency does not match the booking currency")

    tier = select_tier(policy, days_before_travel)
    lines: list[LineItem] = []
    penalty = _penalty_amount(tier, original)
    # A penalty can never exceed the original amount.
    if penalty > original:
        penalty = original
    lines.append(LineItem(LineKind.CANCELLATION_DEDUCTION, tier.label, penalty,
                          evidence_ref=f"policy:{policy.version}"))

    non_ref = Money.from_decimal(policy.non_refundable_fixed, policy.currency)
    if non_ref.is_positive:
        lines.append(LineItem(LineKind.NON_REFUNDABLE, policy.non_refundable_label, non_ref,
                              evidence_ref=f"policy:{policy.version}"))
    return lines
