# ADR-0001: Modular monolith over microservices

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

TravelRefund Intelligence spans many modules (trips, documents, reconciliation,
AI investigation, communications). A microservice-per-module design is tempting
but, at this stage, there is a single team, a single deployment target, and
strong transactional coupling around the financial ledger: a refund case, its
ledger entries, and its reconciliation matches must update atomically.

## Decision

Build a **modular monolith** (FastAPI) with hard internal boundaries:

- `app/domain` is a pure library with no I/O — importable and testable alone.
- `app/services` holds use-cases and is the only layer allowed to touch the DB
  session and enforce tenant scoping.
- `app/api` are thin controllers.
- Background work (OCR, reconciliation, AI) runs in Celery workers that import
  the same modules — same code, different process, no network boundary to cross.

Message passing uses Redis initially, behind a thin broker abstraction so a
future move to SQS/Kafka does not touch business code.

## Consequences

**Positive:** atomic financial transactions; one codebase to test and deploy;
no premature network boundaries; the domain core stays dependency-free and
portable.

**Negative:** the whole app scales as one unit. Acceptable now; revisit if a
single module (likely OCR or AI) develops independent scaling or isolation needs.

**Revisit when:** a module needs separate scaling, a separate security blast
radius, or a different runtime (e.g. GPU inference). Extract that module then,
not speculatively.
