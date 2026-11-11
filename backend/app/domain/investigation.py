"""Evidence-grounded refund investigation reasoning (spec Module H).

Pure and deterministic. Given a factual dossier about a refund case — expected vs.
received, customer payout, status, and detected discrepancies — it produces an
investigation with findings, each citing the evidence it rests on, plus prioritised
recommended actions. It states only what the evidence supports and never claims
money was received without a corresponding figure (spec: "AI must not claim that
money was received without transaction evidence").

This is the default, cost-free reasoning path. An optional LLM pass (service layer,
gated by AI_ENABLED) can narrate on top of these findings, but the findings and the
numbers always come from here, so the financial conclusions are reproducible and
never hallucinated. The engine has no power to mutate the ledger or move money.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Sequence

from .money import Money


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


_ORDER = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    message: str
    severity: Severity
    evidence_refs: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DiscrepancyFact:
    kind: str
    amount: Money | None
    detail: str
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CaseDossier:
    case_id: str
    currency: str
    status: str
    expected_supplier: Money
    supplier_received: Money
    expected_customer: Money
    customer_paid: Money
    discrepancies: Sequence[DiscrepancyFact] = field(default_factory=tuple)
    has_documents: bool = False
    supplier_name: str | None = None


@dataclass(frozen=True, slots=True)
class Investigation:
    case_id: str
    summary: str
    findings: Sequence[Finding]
    recommended_actions: Sequence[str]
    severity: Severity
    evidence_complete: bool

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "summary": self.summary,
            "severity": self.severity.value,
            "evidence_complete": self.evidence_complete,
            "findings": [
                {"code": f.code, "message": f.message, "severity": f.severity.value,
                 "evidence_refs": list(f.evidence_refs)}
                for f in self.findings
            ],
            "recommended_actions": list(self.recommended_actions),
        }


def investigate(d: CaseDossier) -> Investigation:
    findings: list[Finding] = []
    actions: list[str] = []

    supplier_outstanding = d.expected_supplier - d.supplier_received
    if supplier_outstanding.is_positive:
        sev = Severity.HIGH if supplier_outstanding.minor_units >= 10000 * 100 else Severity.MEDIUM
        findings.append(Finding(
            "SUPPLIER_SHORTFALL",
            f"Supplier has refunded {d.supplier_received.amount} of an expected "
            f"{d.expected_supplier.amount} {d.currency}; "
            f"{supplier_outstanding.amount} is still outstanding.",
            sev, (f"case:{d.case_id}",),
        ))
        who = d.supplier_name or "the supplier"
        actions.append(f"Follow up with {who} for the outstanding "
                       f"{supplier_outstanding.amount} {d.currency}.")
    elif (d.supplier_received - d.expected_supplier).is_positive:
        over = d.supplier_received - d.expected_supplier
        findings.append(Finding(
            "SUPPLIER_OVERPAID",
            f"Supplier refunded {over.amount} {d.currency} more than expected; verify the policy "
            "and whether a reversal is due.",
            Severity.MEDIUM, (f"case:{d.case_id}",),
        ))
        actions.append("Reconcile the overpayment against the cancellation policy.")

    # Customer side — only reason about it once supplier money has actually arrived.
    if d.supplier_received.is_positive:
        customer_outstanding = d.supplier_received - d.customer_paid
        if customer_outstanding.is_positive:
            findings.append(Finding(
                "CUSTOMER_PAYOUT_PENDING",
                f"{d.customer_paid.amount} of {d.supplier_received.amount} {d.currency} received "
                f"from the supplier has been passed to the customer; "
                f"{customer_outstanding.amount} is still due to the customer.",
                Severity.MEDIUM, (f"case:{d.case_id}",),
            ))
            actions.append(f"Release {customer_outstanding.amount} {d.currency} to the customer "
                           "once internal approval is granted.")
    elif d.customer_paid.is_positive:
        # Paid the customer without recorded supplier funds — flag, do not assert receipt.
        findings.append(Finding(
            "CUSTOMER_PAID_BEFORE_SUPPLIER",
            f"{d.customer_paid.amount} {d.currency} was paid to the customer but no supplier "
            "refund is recorded yet; confirm the agency is not out of pocket.",
            Severity.MEDIUM, (f"case:{d.case_id}",),
        ))

    for disc in d.discrepancies:
        refs = (disc.evidence_ref,) if disc.evidence_ref else ()
        findings.append(Finding(
            f"DISCREPANCY_{disc.kind}",
            disc.detail + (f" (amount {disc.amount.amount} {d.currency})" if disc.amount else ""),
            Severity.MEDIUM, refs,
        ))

    if not d.has_documents:
        findings.append(Finding(
            "MISSING_EVIDENCE",
            "No supporting cancellation document is attached to corroborate the expected refund.",
            Severity.LOW, (),
        ))
        actions.append("Attach the supplier's cancellation confirmation to complete the evidence trail.")

    severity = max((f.severity for f in findings), key=lambda s: _ORDER[s], default=Severity.LOW)
    evidence_complete = d.has_documents and not any(
        f.code == "SUPPLIER_SHORTFALL" for f in findings)

    if not findings:
        summary = (f"Case {d.case_id} reconciles cleanly: expected and received supplier refunds "
                   f"match and the customer has been made whole.")
    else:
        summary = (f"Case {d.case_id}: {len(findings)} finding(s), highest severity "
                   f"{severity.value}. Expected supplier refund {d.expected_supplier.amount}, "
                   f"received {d.supplier_received.amount} {d.currency}.")

    return Investigation(d.case_id, summary, tuple(findings), tuple(actions),
                         severity, evidence_complete)


def supplier_followup_draft(d: CaseDossier) -> str:
    """A ready-to-review follow-up message for the supplier (spec Module I).

    Drafts only; sending requires explicit human approval. Contains no invented
    contact details.
    """
    outstanding = d.expected_supplier - d.supplier_received
    who = d.supplier_name or "Supplier Team"
    return (
        f"Subject: Pending refund follow-up — case {d.case_id}\n\n"
        f"Dear {who},\n\n"
        f"We are following up on the refund for the cancelled booking under case "
        f"{d.case_id}. Based on the applicable cancellation policy, the expected refund "
        f"is {d.expected_supplier.amount} {d.currency}. To date we have received "
        f"{d.supplier_received.amount} {d.currency}, leaving an outstanding amount of "
        f"{outstanding.amount if outstanding.is_positive else Money.zero(d.currency).amount} "
        f"{d.currency}.\n\n"
        f"Could you please confirm the status of the remaining refund and share the "
        f"settlement reference? We are happy to provide any supporting documentation.\n\n"
        f"Thank you,\nFinance Operations"
    )
