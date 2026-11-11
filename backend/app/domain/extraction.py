"""Deterministic document field extraction (spec Module B).

Pure and testable: given document *text* it extracts structured financial fields
— amounts, booking references, dates, and a supplier guess — each with a
confidence score, and never invents a value it cannot find. Image/PDF OCR is a
separate, pluggable front-end that turns pixels into text; this module operates
on the resulting text and is what actually understands the content.

Confidence is label-driven: an amount sitting next to the word "refund" or "total"
scores higher than a bare number. Nothing here is authoritative on its own — the
service layer requires human verification before an extracted value is used in a
financial calculation (spec: "Never trust extracted financial values without
validation").
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from .money import Money

# ₹ 7,800.00  |  INR 7800  |  Rs. 7,800.50
_AMOUNT_RE = re.compile(
    r"(?:₹|INR|Rs\.?)\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
# PNR: ABC123 | 6E-ABC123 | Booking Ref: TAJ-99 | 6-char alnum tokens
_BOOKING_RE = re.compile(
    r"(?:PNR|booking\s*(?:ref(?:erence)?|id)?|ref(?:erence)?)[:\s#]*([A-Z0-9][A-Z0-9\-]{3,15})",
    re.IGNORECASE,
)
_PNR_TOKEN_RE = re.compile(r"\b([0-9A-Z]{2}-?[A-Z0-9]{5,8})\b")
_DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b"), "%d %b %Y"),
]
_LABEL_WORDS = ("refund", "total", "amount", "payable", "credited", "deduction", "charge")


@dataclass(frozen=True, slots=True)
class Candidate:
    value: str
    confidence: Decimal
    context: str = ""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    amounts: List[Candidate] = field(default_factory=list)
    booking_refs: List[Candidate] = field(default_factory=list)
    dates: List[Candidate] = field(default_factory=list)
    supplier: Optional[Candidate] = None
    currency: str = "INR"

    def best_amount(self) -> Optional[Candidate]:
        return self.amounts[0] if self.amounts else None

    def best_booking_ref(self) -> Optional[Candidate]:
        return self.booking_refs[0] if self.booking_refs else None

    def to_dict(self) -> dict:
        def _c(c: Candidate | None):
            return None if c is None else {"value": c.value, "confidence": str(c.confidence),
                                           "context": c.context}
        return {
            "currency": self.currency,
            "amounts": [_c(c) for c in self.amounts],
            "booking_refs": [_c(c) for c in self.booking_refs],
            "dates": [_c(c) for c in self.dates],
            "supplier": _c(self.supplier),
        }


def _context(text: str, start: int, end: int, width: int = 30) -> str:
    return text[max(0, start - width):min(len(text), end + width)].replace("\n", " ").strip()


def _amount_to_money(raw: str, currency: str) -> Optional[Money]:
    try:
        return Money.from_decimal(Decimal(raw.replace(",", "")), currency)
    except (InvalidOperation, Exception):
        return None


def extract(text: str, *, currency: str = "INR",
            known_suppliers: Optional[List[str]] = None) -> ExtractionResult:
    text = text or ""
    lower = text.lower()

    # --- amounts (label-weighted confidence) ---
    amounts: list[Candidate] = []
    for m in _AMOUNT_RE.finditer(text):
        raw = m.group(1)
        if _amount_to_money(raw, currency) is None:
            continue
        ctx = _context(text, m.start(), m.end())
        # The describing label precedes the amount ("Refund payable: ₹9,500"), so
        # score from the text *before* the match to avoid catching the next line.
        preceding = text[max(0, m.start() - 25):m.start()].lower()
        conf = Decimal("0.6")
        if any(w in preceding for w in ("refund", "payable", "credited")):
            conf = Decimal("0.9")
        elif any(w in preceding for w in _LABEL_WORDS):
            conf = Decimal("0.75")
        amounts.append(Candidate(raw.replace(",", ""), conf, ctx))
    # Highest confidence first, then largest value as a tiebreak.
    amounts.sort(key=lambda c: (c.confidence, Decimal(c.value)), reverse=True)

    # --- booking references ---
    refs: list[Candidate] = []
    seen: set[str] = set()
    for m in _BOOKING_RE.finditer(text):
        ref = m.group(1).upper().rstrip("-")
        if ref not in seen:
            seen.add(ref)
            refs.append(Candidate(ref, Decimal("0.85"), _context(text, m.start(), m.end())))
    for m in _PNR_TOKEN_RE.finditer(text):
        ref = m.group(1).upper()
        if ref not in seen and not ref.isdigit():
            seen.add(ref)
            refs.append(Candidate(ref, Decimal("0.6"), _context(text, m.start(), m.end())))
    refs.sort(key=lambda c: c.confidence, reverse=True)

    # --- dates ---
    dates: list[Candidate] = []
    for rx, fmt in _DATE_RES:
        for m in rx.finditer(text):
            iso = _normalise_date(m.group(0), fmt)
            if iso:
                dates.append(Candidate(iso, Decimal("0.8"), _context(text, m.start(), m.end())))

    # --- supplier guess ---
    supplier: Optional[Candidate] = None
    for name in (known_suppliers or []):
        if name and name.lower() in lower:
            supplier = Candidate(name, Decimal("0.9"))
            break

    return ExtractionResult(amounts=amounts, booking_refs=refs, dates=dates,
                            supplier=supplier, currency=currency)


def _normalise_date(raw: str, fmt: str) -> Optional[str]:
    for f in (fmt, "%d %B %Y"):
        try:
            return _dt.datetime.strptime(raw, f).date().isoformat()
        except ValueError:
            continue
    return None
