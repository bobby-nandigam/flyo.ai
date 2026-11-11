# TravelRefund Intelligence — Architecture

> Every rupee accounted for. Every refund traceable.

This document is the engineering source of truth: the domain model, the financial
invariants, the security boundaries, and an honest status of what is built versus
planned. It is written so another engineer can audit, extend, and deploy the
system.

## 1. Guiding principle

**Financial correctness outranks everything, including the AI.** The platform
distinguishes, at every layer, five things that naive tools conflate:

> *expected* refund → *initiated* → *processing* → *supplier-received* → *customer-credited*

A supplier refund landing in the agency's account is **not** a customer refund.
The system refuses to claim otherwise without a downstream transaction as evidence.

## 2. Component map

```
┌────────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js, Phase 6)                                         │
│   dashboard · trips · refund cases · reconciliation · investigation │
└───────────────┬────────────────────────────────────────────────────┘
                │ REST (/api/v1), JWT, per-tenant
┌───────────────▼────────────────────────────────────────────────────┐
│ Backend — modular monolith (FastAPI)                                │
│                                                                      │
│  app/api        HTTP layer (thin controllers)                        │
│  app/services   use-cases / orchestration, tenant scoping            │
│  app/domain  ◄─ PURE financial core (no I/O) ─────────────┐          │
│     money.py         exact Decimal/int money, ISO-4217     │ tested  │
│     calculation.py   deterministic refund engine (Mod. D)  │ 40      │
│     refund_status.py state machine (Mod. F)                │ tests   │
│     ledger.py        append-only ledger + invariants       │ green   │
│  app/models     SQLAlchemy ORM (persistence)   ◄───────────┘          │
└───────┬───────────────────────┬─────────────────────┬───────────────┘
        │                       │                     │
   ┌────▼────┐            ┌──────▼─────┐        ┌──────▼──────┐
   │Postgres │            │   Redis    │        │ Object store │
   │ +pgvector│           │ cache/queue│        │  (S3-compat) │
   └─────────┘            └────────────┘        └─────────────┘
                                │
                         ┌──────▼──────┐
                         │Celery workers│  OCR, reconciliation, AI jobs
                         └─────────────┘
```

We start as a **modular monolith** (ADR-0001), not microservices. Each module has
a clear boundary so it can be extracted later only if an operational need appears.

## 3. The financial core (`app/domain`) — built & tested

This layer is pure: no database, clock, network, or LLM. It is the part that must
be provably correct, so it is where the test coverage concentrates.

| File | Responsibility | Key guarantee |
|------|----------------|---------------|
| `money.py` | `Money` value object | Integer minor-units + Decimal; **never float**; currency-mismatch raises; frozen/hashable |
| `calculation.py` | Refund engine (Module D) | `original − deductions − non_refundable + refundable_tax = expected`; supplier and customer tracks separated; every line carries `evidence_ref`; itemised `to_audit_dict()` |
| `refund_status.py` | Lifecycle (Module F) | 16 states, allow-list transitions only; no supplier→customer-refunded shortcut; no "force" path in the domain |
| `ledger.py` | Append-only ledger (Module D, §8) | Idempotent on `external_ref`; evidence required; corrections are reversing entries, never mutations |

### The spec's formula, in code

```
Expected supplier refund =
      Σ ORIGINAL
    − Σ CANCELLATION_DEDUCTION
    − Σ NON_REFUNDABLE
    + Σ REFUNDABLE_TAX
```

Customer refund is a **separate** calculation whose inputs are the supplier
refunds actually received, net of the agency's own retained fees.

## 4. Financial invariants (spec §11) — enforced & tested

`backend/tests/test_invariants.py` encodes these as acceptance tests:

1. **No transaction counted twice** — ledger dedupes on `external_ref`.
2. **Every refund has traceable evidence** — an entry without `evidence_ref` is rejected at construction.
3. **Supplier ≠ customer refunds** — separate ledger accounts; the two totals are independent.
4. **Every amount reconciles to its entries** — `TripLedger.reconciles()`.
5. **Calculations are reproducible** — pure functions; same input → same output.
6. **Every adjustment is audited** — corrections are new `REVERSAL`/`ADJUSTMENT` entries; the original is never edited.
7. **Tenant isolation** — enforced at the data-access/service layer (Phase 2); covered by the security test suite, not the pure domain.

Run them: `cd backend && pytest -q` → **40 passing**.

## 5. Security & tenancy (design)

- **AuthN**: JWT access (15 min) + refresh (14 d), rotation on refresh.
- **AuthZ**: RBAC (owner / finance / ops / support / read-only).
- **Tenant isolation**: every tenant-owned table carries `tenant_id`; all queries
  go through a session-scoped repository that injects the current tenant's id —
  no raw cross-tenant query is possible from a request handler.
- **PII minimisation**: never store full card numbers, CVV, banking passwords, or
  unneeded passenger data (spec §9). Documents are stored in object storage with
  signed, time-limited access URLs.
- **Audit**: append-only `audit_logs` + the immutable `financial_ledger`.
- **Compliance posture**: DPDP Act-aware retention and deletion (documented per
  table before any real-tenant deployment).

## 6. Data model (spec §8)

Normalised schema planned around: `tenants, users, roles, permissions, customers,
trips, bookings, suppliers, supplier_contracts, cancellation_policies, payments,
payment_allocations, refund_cases, refund_transactions, financial_ledger,
reconciliation_batches, reconciliation_records, reconciliation_matches,
discrepancies, documents, document_extractions, supplier_communications,
investigation_reports, audit_logs, webhook_events, background_jobs`.

The `financial_ledger` table persists exactly the fields in `domain/ledger.py`
as immutable rows (append-only; no `UPDATE`/`DELETE` grant for the app role).

## 7. AI investigation agent (design, Module H)

- Tool-calling with **strict schemas**; tools are read-only over trip/ledger/
  policy/reconciliation data plus a draft-writer.
- The agent **cannot** write ledger entries, initiate refunds, or claim money was
  received without a transaction. Consequential actions require human approval.
- RAG over documents/policies via pgvector for evidence retrieval.
- Runs fully simulated when `AI_ENABLED=false` (no external calls, no cost).

## 8. Roadmap — honest status

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Architecture, domain model, financial invariants | ✅ **done** |
| 2 | Auth/JWT + RBAC, tenants, trips/bookings, refund cases, ledger persistence, Alembic, demo seed | ✅ **done** |
| 3 | CSV import, normalisation, deterministic matching, discrepancies | ⬜ planned |
| 4 | Document intake, OCR, extraction, human verification, policy engine | ⬜ planned |
| 5 | AI investigation: retrieval, tool-calling, evidence-grounded answers, evals | ⬜ planned |
| 6 | Next.js enterprise UI (15 screens) | ⬜ planned |
| 7 | Security/perf/integration testing, observability, deploy, backup/restore | ⬜ planned |

**What runs today** (57 passing tests): a multi-tenant FastAPI backend with
- `POST /api/v1/auth/{register,login,refresh}` + `GET /auth/me` — JWT access/refresh, PBKDF2 passwords.
- Customers, suppliers, trips, bookings — all tenant-scoped.
- `POST /api/v1/refund-cases` — opens a case, computing the expected refund via the
  Phase-1 engine from the **persisted** booking amount.
- Supplier/customer refund posting to the append-only ledger (idempotent on
  `external_ref`), settlement positions, validated status transitions, audit trail.
- Alembic migration for all 9 tables; `scripts/seed_demo.py` loads the synthetic
  Indian scenarios (IndiGo settled, Taj partial/outstanding, Air India not received).

No fake integrations are presented as real; unfinished modules (reconciliation,
OCR, AI) are simply not wired into the router yet (spec §13).

### Tenant isolation, concretely

Every tenant-owned table carries `tenant_id`; all reads/writes go through
`app/services/scoping.py`, which injects it into the query. `app/core/deps.py`
additionally re-checks that the JWT's tenant matches the stored user's tenant
(defence in depth). `tests/test_tenant_isolation.py` proves cross-tenant reads,
list leakage, and cross-tenant writes all fail — **invariant #7, now covered.**

## 9. Running it

See `README.md`. TL;DR: `cd backend && python -m venv .venv && source .venv/bin/activate
&& pip install -r requirements.txt && pytest -q && uvicorn app.main:app --reload`.
