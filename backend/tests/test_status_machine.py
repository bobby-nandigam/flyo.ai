"""Tests for the refund status state machine (spec Module F)."""
import pytest

from app.domain.refund_status import (
    RefundStatus as S,
    InvalidTransition,
    assert_transition,
    can_transition,
    TERMINAL_STATES,
)


def test_happy_path_full_lifecycle():
    path = [
        S.BOOKED,
        S.CANCEL_REQUESTED,
        S.CANCELLED,
        S.REFUND_ELIGIBILITY_PENDING,
        S.REFUND_EXPECTED,
        S.REFUND_REQUESTED,
        S.REFUND_INITIATED,
        S.REFUND_PROCESSING,
        S.SUPPLIER_REFUND_RECEIVED,
        S.CUSTOMER_REFUND_PENDING,
        S.CUSTOMER_REFUNDED,
        S.CLOSED,
    ]
    for src, dst in zip(path, path[1:]):
        assert_transition(src, dst)  # must not raise


def test_supplier_received_cannot_jump_to_customer_refunded():
    # The core spec invariant: supplier refund != customer refund.
    assert not can_transition(S.SUPPLIER_REFUND_RECEIVED, S.CUSTOMER_REFUNDED)
    with pytest.raises(InvalidTransition):
        assert_transition(S.SUPPLIER_REFUND_RECEIVED, S.CUSTOMER_REFUNDED)


def test_cannot_skip_from_booked_to_refunded():
    with pytest.raises(InvalidTransition):
        assert_transition(S.BOOKED, S.CUSTOMER_REFUNDED)


def test_partial_then_full_customer_refund():
    assert_transition(S.CUSTOMER_REFUND_PENDING, S.CUSTOMER_PARTIALLY_REFUNDED)
    assert_transition(S.CUSTOMER_PARTIALLY_REFUNDED, S.CUSTOMER_REFUNDED)


def test_terminal_states_have_no_forward_path_except_close():
    assert can_transition(S.CUSTOMER_REFUNDED, S.CLOSED)
    assert not can_transition(S.CLOSED, S.BOOKED)
    for term in TERMINAL_STATES:
        # No terminal state can go back to an active refund state.
        assert not can_transition(term, S.REFUND_EXPECTED)


def test_dispute_and_manual_review_reachable_from_processing():
    assert can_transition(S.REFUND_PROCESSING, S.DISPUTED)
    assert can_transition(S.REFUND_EXPECTED, S.MANUAL_REVIEW_REQUIRED)


def test_invalid_transition_message_is_informative():
    with pytest.raises(InvalidTransition) as exc:
        assert_transition(S.BOOKED, S.CLOSED)
    assert "BOOKED" in str(exc.value) and "CLOSED" in str(exc.value)
