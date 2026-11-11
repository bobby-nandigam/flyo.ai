"""Append-only financial ledger (spec Module D, §8).

The ledger is the single source of financial truth for a trip. Rules:

* Entries are **append-only**. There is no update or delete. A correction is a
  new, explicitly-typed reversing entry that references the original — the spec:
  "Never silently modify an existing financial transaction."
* Every entry is idempotent on ``external_ref`` within a (tenant, trip) scope, so
  importing the same bank/gateway row twice cannot double-count it (invariant #1).
* Every entry carries ``evidence_ref``; an entry with no evidence is rejected
  (invariant #2: "Every refund has traceable source evidence").
* Supplier-side and customer-side movements live on separate accounts so they can
  never be conflated (invariant #3).

This in-memory implementation is the authoritative model; the SQLAlchemy
`financial_ledger` table persists exactly these fields as immutable rows.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .money import Money, money_sum


class Account(str, Enum):
    """Which side of the world a movement belongs to."""

    SUPPLIER = "SUPPLIER"      # money between agency and supplier
    CUSTOMER = "CUSTOMER"      # money between agency and customer


class EntryType(str, Enum):
    ORIGINAL_CHARGE = "ORIGINAL_CHARGE"          # customer paid for the booking
    SUPPLIER_REFUND = "SUPPLIER_REFUND"          # supplier returned money to agency
    CUSTOMER_REFUND = "CUSTOMER_REFUND"          # agency returned money to customer
    REVERSAL = "REVERSAL"                        # explicit reversal of a prior entry
    ADJUSTMENT = "ADJUSTMENT"                    # audited manual correction


class LedgerError(Exception):
    pass


class DuplicateEntry(LedgerError):
    pass


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    account: Account
    entry_type: EntryType
    amount: Money                 # signed: + into the account, - out of it
    evidence_ref: str             # required; links to a document/transaction
    external_ref: Optional[str] = None   # dedup key (bank txn id, gateway id, …)
    reverses: Optional[str] = None       # entry_id this one reverses
    created_at: _dt.datetime = field(
        default_factory=lambda: _dt.datetime.now(_dt.timezone.utc)
    )
    memo: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_ref:
            raise LedgerError(
                f"Entry {self.entry_id} has no evidence_ref; refusing (invariant #2)"
            )
        if self.entry_type is EntryType.REVERSAL and not self.reverses:
            raise LedgerError("A REVERSAL entry must reference the entry it reverses")


class TripLedger:
    """Append-only ledger for a single trip."""

    def __init__(self, trip_id: str, currency: str) -> None:
        self.trip_id = trip_id
        self.currency = currency
        self._entries: List[LedgerEntry] = []
        self._external_refs: set[str] = set()
        self._ids: set[str] = set()

    # -- append-only API -- #
    def append(self, entry: LedgerEntry) -> LedgerEntry:
        if entry.amount.currency != self.currency:
            raise LedgerError(
                f"Entry currency {entry.amount.currency} != ledger {self.currency}"
            )
        if entry.entry_id in self._ids:
            raise DuplicateEntry(f"Entry id {entry.entry_id} already posted")
        if entry.external_ref is not None:
            if entry.external_ref in self._external_refs:
                raise DuplicateEntry(
                    f"external_ref {entry.external_ref!r} already posted "
                    "(invariant #1: no transaction counted twice)"
                )
            self._external_refs.add(entry.external_ref)
        if entry.reverses is not None and entry.reverses not in self._ids:
            raise LedgerError(f"Cannot reverse unknown entry {entry.reverses}")
        self._entries.append(entry)
        self._ids.add(entry.entry_id)
        return entry

    # -- read-only projections -- #
    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def balance(self, account: Account) -> Money:
        return money_sum(
            (e.amount for e in self._entries if e.account is account), self.currency
        )

    def supplier_refund_total(self) -> Money:
        return self.balance(Account.SUPPLIER)

    def customer_refund_total(self) -> Money:
        # Customer refunds leave the agency, so they are posted as negative on the
        # CUSTOMER account; expose the magnitude paid out.
        return self.balance(Account.CUSTOMER).abs()

    def reconciles(self) -> bool:
        """Invariant #4: every account balance equals the sum of its entries.

        Trivially true for this projection, but asserting it guards against a
        future refactor that caches balances separately from the entry list.
        """
        for acct in Account:
            recomputed = money_sum(
                (e.amount for e in self._entries if e.account is acct), self.currency
            )
            if recomputed != self.balance(acct):
                return False
        return True
