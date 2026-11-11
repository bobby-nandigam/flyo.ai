"""Deterministic reconciliation engine (spec Module E + Module G).

Pure and reproducible: given the same external records and expected items it
always produces the same matches, discrepancies and confidence scores — no I/O,
no clock, no LLM. Matching is **deterministic-first** (exact reference, then
amount+date, then booking reference, then fuzzy), and low-confidence matches are
surfaced, never silently finalised (spec: "Never automatically finalize a
low-confidence financial match").

Two record sets are compared:

* ``ExternalTxn`` — a normalised row from a bank statement / gateway / supplier
  report (what the outside world says happened).
* ``ExpectedItem`` — a figure the platform already holds, typically a ledger
  entry (what we recorded).

The output pairs them up, flags what could not be paired, and derives typed
discrepancies with their financial exposure.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional, Sequence

from .money import Money


class MatchStrategy(str, Enum):
    EXACT_REF = "EXACT_REF"          # external_ref == expected.external_ref
    AMOUNT_DATE = "AMOUNT_DATE"      # same amount within a date window
    BOOKING_REF = "BOOKING_REF"      # same booking reference + amount
    FUZZY_REF = "FUZZY_REF"          # similar reference + amount


class DiscrepancyType(str, Enum):
    UNMATCHED_BANK_CREDIT = "UNMATCHED_BANK_CREDIT"      # money seen, not recorded
    MISSING_SUPPLIER_REFUND = "MISSING_SUPPLIER_REFUND"  # recorded/expected, not seen
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"                  # matched by ref, amounts differ
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"      # same external row twice


# Confidence per strategy (deterministic, documented, auditable).
_CONFIDENCE = {
    MatchStrategy.EXACT_REF: Decimal("1.00"),
    MatchStrategy.AMOUNT_DATE: Decimal("0.80"),
    MatchStrategy.BOOKING_REF: Decimal("0.75"),
    MatchStrategy.FUZZY_REF: Decimal("0.55"),
}
AUTO_FINALIZE_THRESHOLD = Decimal("0.80")


@dataclass(frozen=True, slots=True)
class ExternalTxn:
    row_id: str
    amount: Money
    external_ref: Optional[str] = None
    value_date: Optional[_dt.date] = None
    counterparty: Optional[str] = None
    booking_ref: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ExpectedItem:
    item_id: str
    amount: Money
    external_ref: Optional[str] = None
    value_date: Optional[_dt.date] = None
    counterparty: Optional[str] = None
    booking_ref: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Match:
    external_row_id: str
    expected_item_id: str
    strategy: MatchStrategy
    confidence: Decimal
    auto_finalizable: bool


@dataclass(frozen=True, slots=True)
class Discrepancy:
    kind: DiscrepancyType
    external_row_id: Optional[str]
    expected_item_id: Optional[str]
    expected_amount: Optional[Money]
    observed_amount: Optional[Money]
    difference: Optional[Money]
    detail: str


@dataclass(frozen=True, slots=True)
class ReconResult:
    matches: Sequence[Match]
    discrepancies: Sequence[Discrepancy]
    unmatched_external: Sequence[str]
    unmatched_expected: Sequence[str]

    @property
    def matched_count(self) -> int:
        return len(self.matches)

    def accuracy(self) -> Decimal:
        """Fraction of expected items that were matched (0..1), 2dp."""
        total = len(self.matches) + len(self.unmatched_expected)
        if total == 0:
            return Decimal("1.00")
        return (Decimal(len(self.matches)) / Decimal(total)).quantize(Decimal("0.01"))


def _norm(ref: Optional[str]) -> str:
    return (ref or "").strip().upper().replace(" ", "").replace("-", "")


def _similar(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _within_days(d1: Optional[_dt.date], d2: Optional[_dt.date], days: int) -> bool:
    if d1 is None or d2 is None:
        return True  # cannot disprove on date alone
    return abs((d1 - d2).days) <= days


def _detect_duplicates(externals: Sequence[ExternalTxn]) -> tuple[list[str], list[Discrepancy]]:
    """Flag external rows that repeat the same reference, or the same
    (amount, date, counterparty) signature."""
    seen_ref: dict[str, str] = {}
    seen_sig: dict[tuple, str] = {}
    dups: list[str] = []
    discs: list[Discrepancy] = []
    for tx in sorted(externals, key=lambda t: t.row_id):
        if tx.external_ref:
            key = _norm(tx.external_ref)
            if key in seen_ref:
                dups.append(tx.row_id)
                discs.append(Discrepancy(
                    DiscrepancyType.DUPLICATE_TRANSACTION, tx.row_id, None,
                    None, tx.amount, None,
                    f"Duplicate of row {seen_ref[key]} (same reference {tx.external_ref})",
                ))
                continue
            seen_ref[key] = tx.row_id
        sig = (tx.amount.minor_units, tx.amount.currency, tx.value_date,
               _norm(tx.counterparty))
        if sig in seen_sig and tx.row_id not in dups:
            dups.append(tx.row_id)
            discs.append(Discrepancy(
                DiscrepancyType.DUPLICATE_TRANSACTION, tx.row_id, None,
                None, tx.amount, None,
                f"Possible duplicate of row {seen_sig[sig]} (same amount/date/party)",
            ))
            continue
        seen_sig[sig] = tx.row_id
    return dups, discs


def reconcile(
    externals: Sequence[ExternalTxn],
    expecteds: Sequence[ExpectedItem],
    *,
    date_window_days: int = 5,
) -> ReconResult:
    # Stable ordering makes the whole pass reproducible (invariant #5).
    externals = sorted(externals, key=lambda t: t.row_id)
    expecteds = sorted(expecteds, key=lambda e: e.item_id)

    dup_ids, discrepancies = _detect_duplicates(externals)
    dup_set = set(dup_ids)

    used_ext: set[str] = set(dup_set)
    used_exp: set[str] = set()
    matches: list[Match] = []

    def _try_match(strategy: MatchStrategy, predicate) -> None:
        for ex in externals:
            if ex.row_id in used_ext:
                continue
            best: ExpectedItem | None = None
            for item in expecteds:
                if item.item_id in used_exp:
                    continue
                if predicate(ex, item):
                    best = item
                    break
            if best is not None:
                conf = _CONFIDENCE[strategy]
                matches.append(Match(ex.row_id, best.item_id, strategy, conf,
                                     conf >= AUTO_FINALIZE_THRESHOLD))
                used_ext.add(ex.row_id)
                used_exp.add(best.item_id)
                # Amounts can differ on an exact-ref match -> flag the gap.
                if strategy is MatchStrategy.EXACT_REF and ex.amount != best.amount:
                    diff = ex.amount - best.amount
                    discrepancies.append(Discrepancy(
                        DiscrepancyType.AMOUNT_MISMATCH, ex.row_id, best.item_id,
                        best.amount, ex.amount, diff,
                        f"Reference matched but amounts differ by {diff}",
                    ))

    # 1) Exact reference (amount may still differ -> AMOUNT_MISMATCH).
    _try_match(MatchStrategy.EXACT_REF,
               lambda ex, it: bool(ex.external_ref) and bool(it.external_ref)
               and _norm(ex.external_ref) == _norm(it.external_ref))
    # 2) Same amount within the date window.
    _try_match(MatchStrategy.AMOUNT_DATE,
               lambda ex, it: ex.amount == it.amount
               and _within_days(ex.value_date, it.value_date, date_window_days))
    # 3) Booking reference + amount.
    _try_match(MatchStrategy.BOOKING_REF,
               lambda ex, it: bool(ex.booking_ref) and bool(it.booking_ref)
               and _norm(ex.booking_ref) == _norm(it.booking_ref)
               and ex.amount == it.amount)
    # 4) Fuzzy reference (>=0.85 similarity) + amount.
    _try_match(MatchStrategy.FUZZY_REF,
               lambda ex, it: ex.amount == it.amount
               and _similar(ex.external_ref, it.external_ref) >= 0.85)

    unmatched_external = [t.row_id for t in externals if t.row_id not in used_ext]
    unmatched_expected = [e.item_id for e in expecteds if e.item_id not in used_exp]

    ext_by_id = {t.row_id: t for t in externals}
    exp_by_id = {e.item_id: e for e in expecteds}
    for rid in unmatched_external:
        tx = ext_by_id[rid]
        discrepancies.append(Discrepancy(
            DiscrepancyType.UNMATCHED_BANK_CREDIT, rid, None, None, tx.amount, None,
            "Bank/gateway credit with no matching recorded refund",
        ))
    for iid in unmatched_expected:
        it = exp_by_id[iid]
        discrepancies.append(Discrepancy(
            DiscrepancyType.MISSING_SUPPLIER_REFUND, None, iid, it.amount, None, None,
            "Recorded/expected refund not found in the imported records",
        ))

    return ReconResult(
        matches=tuple(matches),
        discrepancies=tuple(discrepancies),
        unmatched_external=tuple(unmatched_external),
        unmatched_expected=tuple(unmatched_expected),
    )
