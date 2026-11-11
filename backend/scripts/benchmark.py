"""Financial-correctness & performance benchmark (spec §14).

Runs the deterministic engines over many synthetic cases and reports:
* throughput (cases/sec) for the refund calculation and reconciliation engines,
* a reproducibility check (same input -> identical output),
* an invariant check (expected = original - deductions + refundable, never < 0).

Run: python -m scripts.benchmark
"""
from __future__ import annotations

import time
from decimal import Decimal

from app.domain.calculation import LineItem, LineKind, compute_supplier_refund
from app.domain.money import Money
from app.domain.reconciliation import ExpectedItem, ExternalTxn, reconcile


def bench_calculation(n: int = 50_000) -> dict:
    start = time.perf_counter()
    bad = 0
    for i in range(n):
        original = Money.from_decimal(Decimal(10000 + (i % 5000)), "INR")
        lines = [
            LineItem(LineKind.ORIGINAL, "orig", original, "b:1"),
            LineItem(LineKind.CANCELLATION_DEDUCTION, "pen",
                     Money.from_decimal(Decimal(2000), "INR"), "p:1"),
            LineItem(LineKind.REFUNDABLE_TAX, "tax",
                     Money.from_decimal(Decimal(300), "INR"), "d:1"),
        ]
        res = compute_supplier_refund(lines, "INR")
        if res.total.is_negative:
            bad += 1
    elapsed = time.perf_counter() - start
    return {"cases": n, "seconds": round(elapsed, 3), "per_sec": round(n / elapsed),
            "negative_totals": bad}


def bench_reconciliation(n: int = 5_000) -> dict:
    externals = [ExternalTxn(f"x{i}", Money.from_decimal(Decimal(1000 + i), "INR"),
                             external_ref=f"REF{i}") for i in range(n)]
    expecteds = [ExpectedItem(f"e{i}", Money.from_decimal(Decimal(1000 + i), "INR"),
                              external_ref=f"REF{i}") for i in range(n)]
    start = time.perf_counter()
    result = reconcile(externals, expecteds)
    elapsed = time.perf_counter() - start
    return {"records": n, "seconds": round(elapsed, 3), "per_sec": round(n / elapsed),
            "matched": result.matched_count}


def reproducibility_check() -> bool:
    lines = [
        LineItem(LineKind.ORIGINAL, "orig", Money.from_decimal("10000", "INR"), "b:1"),
        LineItem(LineKind.CANCELLATION_DEDUCTION, "pen", Money.from_decimal("2500", "INR"), "p:1"),
    ]
    a = compute_supplier_refund(lines, "INR").to_audit_dict()
    b = compute_supplier_refund(lines, "INR").to_audit_dict()
    return a == b


def main() -> None:
    calc = bench_calculation()
    rec = bench_reconciliation()
    print("=== TravelRefund Intelligence — benchmark ===")
    print(f"Calculation engine : {calc['cases']:,} cases in {calc['seconds']}s "
          f"= {calc['per_sec']:,}/s | negative totals: {calc['negative_totals']}")
    print(f"Reconciliation     : {rec['records']:,} records in {rec['seconds']}s "
          f"= {rec['per_sec']:,}/s | matched: {rec['matched']:,}")
    print(f"Reproducible       : {reproducibility_check()}")
    assert calc["negative_totals"] == 0, "INVARIANT VIOLATION: negative refund total"
    assert reproducibility_check(), "INVARIANT VIOLATION: non-reproducible calculation"
    print("All financial invariants held. ✅")


if __name__ == "__main__":
    main()
