# TravelRefund Intelligence

**Every rupee accounted for. Every refund traceable.**

An AI-powered, multi-supplier travel refund intelligence platform for Indian
travel businesses. When a trip is cancelled, the financial consequences scatter
across airlines, hotels, transport, payment gateways and the agency. This system
reconstructs the **one financial truth** of a cancelled trip:

> ONE TRIP → MULTIPLE SUPPLIERS → ONE FINANCIAL TRUTH

## Status

This repository is being built **incrementally and test-first**, starting with the
financial core (the part that must be provably correct) rather than a broad,
shallow skeleton. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §8 for the
honest phase-by-phase status.

**Working today — 57 passing tests**
- Pure financial domain core: exact money, deterministic refund engine, refund
  state machine, append-only ledger — including the seven financial invariants.
- Multi-tenant FastAPI backend: JWT auth + RBAC, strict tenant isolation
  (invariant #7, tested), customers/suppliers/trips/bookings, refund cases that
  compute expected refunds from persisted bookings, ledger posting with
  idempotency, settlement positions, validated status transitions, audit trail.
- Alembic migrations for all 9 tables + a synthetic Indian demo dataset.

No fake integrations are presented as real; unfinished modules (reconciliation,
OCR, AI investigation, the Next.js UI) are simply not wired up yet. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §8 for the phase-by-phase status.

## Tech stack

- **Backend:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic
- **Data:** PostgreSQL (+pgvector), Redis
- **Background:** Celery
- **Frontend (Phase 6):** Next.js, TypeScript, Tailwind, shadcn/ui, TanStack Query
- **Infra:** Docker Compose; AWS/S3-ready

## Quick start (backend + tests)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the full test suite (domain + API + tenant isolation)
pytest -q                     # -> 57 passed

# (optional) load the synthetic Indian demo dataset into a local SQLite db
DATABASE_URL="sqlite:///$(pwd)/demo.db" python -m scripts.seed_demo
# login: demo-owner@flyo.test / demopassword1

# Run the API (point it at the seeded db to explore real data)
DATABASE_URL="sqlite:///$(pwd)/demo.db" uvicorn app.main:app --reload
# -> http://localhost:8000/docs
```

Database migrations (PostgreSQL in production):

```bash
alembic upgrade head
```

Try the engine over HTTP:

```bash
curl -s localhost:8000/api/v1/calculations/refund \
  -H 'content-type: application/json' \
  -d '{"currency":"INR","scope":"supplier","lines":[
        {"kind":"ORIGINAL","label":"Base fare","amount":"10000.00","evidence_ref":"doc:1"},
        {"kind":"CANCELLATION_DEDUCTION","label":"Penalty","amount":"2000.00","evidence_ref":"pol:1"},
        {"kind":"REFUNDABLE_TAX","label":"Refundable GST","amount":"300.00","evidence_ref":"doc:1"}
      ]}'
# -> {"scope":"supplier","total":"8300.00", ... itemised, auditable lines ...}
```

## Full stack (Docker)

```bash
cp .env.example .env     # edit secrets
docker compose up --build
```

## Repository layout

```
backend/
  app/
    domain/     ← pure financial core (money, calculation, status, ledger)
    api/        ← FastAPI routes
    schemas/    ← Pydantic request/response models
    core/       ← config, (auth/db to come)
    services/   ← use-cases, tenant scoping (Phase 2)
    models/     ← SQLAlchemy ORM (Phase 2)
  tests/        ← 40 tests: money, engine, state machine, invariants, API
docs/
  ARCHITECTURE.md
  adr/0001-modular-monolith.md
docker-compose.yml
```

## Design rules (non-negotiable)

- Never floating-point arithmetic for money — exact Decimal/integer only.
- Supplier refunds and customer refunds are always distinct.
- Every financial figure is traceable to source evidence.
- The AI never writes the ledger, initiates refunds, or claims money arrived
  without a transaction.
- Strict tenant isolation; no cross-tenant access.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full picture.
