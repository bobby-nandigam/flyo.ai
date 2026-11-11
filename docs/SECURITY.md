# Security & Compliance

TravelRefund Intelligence handles financial and personal data for multiple
tenants. This document records the controls in place and the posture for a
production deployment under India's Digital Personal Data Protection Act (DPDP).

## Authentication & authorization
- **JWT** access tokens (15 min) + refresh tokens (14 d), each tagged with its
  type so a refresh token can never act as an access token (`app/core/security.py`).
- Passwords hashed with **PBKDF2-HMAC-SHA256** (200k rounds), constant-time verify.
  No plaintext or reversible storage.
- **RBAC**: OWNER / FINANCE / OPS / SUPPORT / READ_ONLY. Money-moving and
  reconciliation endpoints require OWNER or FINANCE (`require_roles`).

## Tenant isolation (invariant #7)
- Every tenant-owned table carries `tenant_id`.
- All data access goes through `app/services/scoping.py`, which injects the
  tenant filter; handlers cannot leak across tenants by omission.
- Defence in depth: `get_current_principal` re-checks that the token's tenant
  matches the stored user's tenant.
- Covered by `tests/test_tenant_isolation.py` and per-module isolation tests.

## Financial integrity
- Append-only `financial_ledger`; corrections are reversing entries, never edits.
- Idempotency on `external_ref` (DB unique + domain guard) prevents double counting.
- Every ledger entry requires `evidence_ref`.
- The AI investigation agent is **read-only** over financial data: it can create
  reports and draft messages, but cannot write the ledger, change an amount, or
  send a message.

## Transport & headers
- HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` on every response (`app/core/observability.py`).
- TLS is terminated at the platform edge (Vercel) in deployment.

## PII minimisation (DPDP-aligned)
- We never store card numbers, CVV, banking passwords, or unnecessary passenger
  data (spec §9). Customer records hold only name and optional contact.
- Access logs carry a request id and route, never request bodies or secrets.
- Documents are stored as text/evidence; in production, binary documents belong in
  object storage (S3-compatible) behind signed, time-limited URLs.

## Auditability
- Append-only `audit_logs` records every consequential action (registration,
  trip/booking creation, ledger append, status transition, reconciliation run,
  document verify, investigation, communication status) with actor and detail.

## Rate limiting & abuse
- Per-process request metrics are emitted; production rate limiting and bot
  management are delegated to the edge (Vercel Firewall / WAF), which is the
  correct place for cross-instance enforcement.

## Secrets
- All secrets (`JWT_SECRET`, `DATABASE_URL`, `OPENAI_API_KEY`) come from the
  environment; none are committed. `.env` is git-ignored; `.env.example` documents
  the keys. The demo deployment uses a non-production JWT secret over synthetic
  data only.

## Known limitations (demo deployment)
- The public demo runs on ephemeral per-instance SQLite and re-seeds synthetic
  data on cold start; it is **not** for real tenant data. Production uses managed
  PostgreSQL with migrations, backups and the controls above.
