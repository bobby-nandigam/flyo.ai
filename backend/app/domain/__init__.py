"""Pure financial domain layer: Money, refund calculation, status machine.

No I/O, no database, no network, no LLM. Everything here is deterministic and
unit-testable in isolation, which is exactly what the spec demands of the
financial core (§3, §13).
"""
from .money import (
    Money,
    MoneyError,
    CurrencyMismatch,
    UnknownCurrency,
    money_sum,
)
from .calculation import (
    LineKind,
    LineItem,
    RefundBreakdown,
    SettlementPosition,
    CalculationError,
    compute_supplier_refund,
    compute_customer_refund,
)
from .refund_status import (
    RefundStatus,
    InvalidTransition,
    assert_transition,
    can_transition,
    allowed_transitions,
    TERMINAL_STATES,
    REVIEW_STATES,
)

__all__ = [
    "Money",
    "MoneyError",
    "CurrencyMismatch",
    "UnknownCurrency",
    "money_sum",
    "LineKind",
    "LineItem",
    "RefundBreakdown",
    "SettlementPosition",
    "CalculationError",
    "compute_supplier_refund",
    "compute_customer_refund",
    "RefundStatus",
    "InvalidTransition",
    "assert_transition",
    "can_transition",
    "allowed_transitions",
    "TERMINAL_STATES",
    "REVIEW_STATES",
]
