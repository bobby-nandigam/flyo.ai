"""Refund lifecycle state machine (spec Module F).

A refund case moves through a controlled set of states. The spec is explicit:

    "A supplier refund must never be interpreted as a customer refund without
     evidence of the corresponding downstream transaction."

We encode that by keeping two parallel tracks — the *supplier* side and the
*customer* side — within one status enum, and by only permitting transitions on
an explicit allow-list. Any transition not in the allow-list raises
:class:`InvalidTransition`. There is no "force" path in the domain layer; forcing
a state belongs to an audited admin action at the service layer, never here.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class RefundStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REFUND_ELIGIBILITY_PENDING = "REFUND_ELIGIBILITY_PENDING"
    REFUND_EXPECTED = "REFUND_EXPECTED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUND_INITIATED = "REFUND_INITIATED"
    REFUND_PROCESSING = "REFUND_PROCESSING"
    SUPPLIER_REFUND_RECEIVED = "SUPPLIER_REFUND_RECEIVED"
    CUSTOMER_REFUND_PENDING = "CUSTOMER_REFUND_PENDING"
    CUSTOMER_PARTIALLY_REFUNDED = "CUSTOMER_PARTIALLY_REFUNDED"
    CUSTOMER_REFUNDED = "CUSTOMER_REFUNDED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    CLOSED = "CLOSED"


# States from which the case is considered terminal (no further auto-transitions).
TERMINAL_STATES: FrozenSet[RefundStatus] = frozenset(
    {RefundStatus.CUSTOMER_REFUNDED, RefundStatus.REJECTED, RefundStatus.CLOSED}
)

# States that require a human to act before the case can progress.
REVIEW_STATES: FrozenSet[RefundStatus] = frozenset(
    {RefundStatus.MANUAL_REVIEW_REQUIRED, RefundStatus.DISPUTED}
)

# The allow-list of valid transitions. Keyed by current state -> set of next states.
_ALLOWED: Dict[RefundStatus, FrozenSet[RefundStatus]] = {
    RefundStatus.BOOKED: frozenset(
        {RefundStatus.CANCEL_REQUESTED}
    ),
    RefundStatus.CANCEL_REQUESTED: frozenset(
        {RefundStatus.CANCELLED, RefundStatus.REJECTED}
    ),
    RefundStatus.CANCELLED: frozenset(
        {RefundStatus.REFUND_ELIGIBILITY_PENDING, RefundStatus.REJECTED}
    ),
    RefundStatus.REFUND_ELIGIBILITY_PENDING: frozenset(
        {
            RefundStatus.REFUND_EXPECTED,
            RefundStatus.REJECTED,
            RefundStatus.MANUAL_REVIEW_REQUIRED,
        }
    ),
    RefundStatus.REFUND_EXPECTED: frozenset(
        {RefundStatus.REFUND_REQUESTED, RefundStatus.MANUAL_REVIEW_REQUIRED}
    ),
    RefundStatus.REFUND_REQUESTED: frozenset(
        {RefundStatus.REFUND_INITIATED, RefundStatus.DISPUTED}
    ),
    RefundStatus.REFUND_INITIATED: frozenset(
        {RefundStatus.REFUND_PROCESSING, RefundStatus.DISPUTED}
    ),
    RefundStatus.REFUND_PROCESSING: frozenset(
        {RefundStatus.SUPPLIER_REFUND_RECEIVED, RefundStatus.DISPUTED}
    ),
    # Crossing the supplier -> customer boundary. Only moves to customer-pending;
    # it never jumps straight to CUSTOMER_REFUNDED.
    RefundStatus.SUPPLIER_REFUND_RECEIVED: frozenset(
        {RefundStatus.CUSTOMER_REFUND_PENDING, RefundStatus.DISPUTED}
    ),
    RefundStatus.CUSTOMER_REFUND_PENDING: frozenset(
        {
            RefundStatus.CUSTOMER_PARTIALLY_REFUNDED,
            RefundStatus.CUSTOMER_REFUNDED,
            RefundStatus.DISPUTED,
        }
    ),
    RefundStatus.CUSTOMER_PARTIALLY_REFUNDED: frozenset(
        {RefundStatus.CUSTOMER_REFUNDED, RefundStatus.DISPUTED}
    ),
    # Review/dispute states can be resolved back into the normal flow or closed.
    RefundStatus.DISPUTED: frozenset(
        {RefundStatus.MANUAL_REVIEW_REQUIRED, RefundStatus.REJECTED, RefundStatus.CLOSED}
    ),
    RefundStatus.MANUAL_REVIEW_REQUIRED: frozenset(
        {
            RefundStatus.REFUND_EXPECTED,
            RefundStatus.REFUND_REQUESTED,
            RefundStatus.SUPPLIER_REFUND_RECEIVED,
            RefundStatus.CUSTOMER_REFUND_PENDING,
            RefundStatus.REJECTED,
            RefundStatus.CLOSED,
        }
    ),
    # Terminal
    RefundStatus.CUSTOMER_REFUNDED: frozenset({RefundStatus.CLOSED}),
    RefundStatus.REJECTED: frozenset({RefundStatus.CLOSED}),
    RefundStatus.CLOSED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when a refund status transition is not permitted."""

    def __init__(self, src: RefundStatus, dst: RefundStatus) -> None:
        self.src = src
        self.dst = dst
        super().__init__(f"Illegal refund transition: {src.value} -> {dst.value}")


def allowed_transitions(src: RefundStatus) -> FrozenSet[RefundStatus]:
    return _ALLOWED[src]


def can_transition(src: RefundStatus, dst: RefundStatus) -> bool:
    return dst in _ALLOWED[src]


def assert_transition(src: RefundStatus, dst: RefundStatus) -> None:
    """Raise :class:`InvalidTransition` unless ``src -> dst`` is on the allow-list."""
    if not can_transition(src, dst):
        raise InvalidTransition(src, dst)
