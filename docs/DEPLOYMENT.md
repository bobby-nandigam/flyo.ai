# Deployment & Operations

## Local development

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # 103 tests
DATABASE_URL="sqlite:///$(pwd)/demo.db" python -m scripts.seed_demo
DATABASE_URL="sqlite:///$(pwd)/demo.db" uvicorn app.main:app --reload
# UI at http://localhost:8000  ·  API docs at /docs  ·  metrics at /metrics
```

## Full stack (Docker Compose)

```bash
cp .env.example .env            # set JWT_SECRET, DATABASE_URL, REDIS_URL
docker compose up --build       # postgres + redis + backend
```

## Database migrations (production = PostgreSQL)

```bash
export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/flyo"
export ENVIRONMENT=production   # disables dev-time create_all
alembic upgrade head
```

Three migrations ship: initial schema, reconciliation tables, and
documents/policies/investigation/communications.

## Serverless demo (Vercel)

The live demo is deployed from `backend/` with `vercel --prod`:
- `api/index.py` exports the ASGI `app` and seeds synthetic data on cold start.
- `api/requirements.txt` is the slim runtime set (SQLite + stdlib crypto).
- Because serverless storage is ephemeral, the demo uses SQLite in `/tmp` and is
  for demonstration only. **For real persistence**, provision a managed Postgres
  (e.g. Neon via the Vercel Marketplace), set `DATABASE_URL` and remove the seed
  block from `api/index.py`.

```bash
cd backend && vercel --prod
```

## Observability
- `GET /health` — liveness.
- `GET /metrics` — Prometheus text (request counts + durations per route).
- Structured JSON access logs on stdout (ingest into any log backend).
- Ready to export to OpenTelemetry / Prometheus / Grafana in production.

## Backup & recovery
- **PostgreSQL**: schedule `pg_dump` (daily full + WAL archiving for PITR):
  ```bash
  pg_dump "$DATABASE_URL" --format=custom --file=flyo-$(date +%F).dump
  # restore: pg_restore --clean --dbname "$DATABASE_URL" flyo-YYYY-MM-DD.dump
  ```
- The `financial_ledger` and `audit_logs` tables are append-only; retain per the
  DPDP retention policy before any purge.
- Object storage (documents) uses the provider's native versioning/backup.

## CI
`.github/workflows/ci.yml` runs on every push/PR: installs deps, runs the test
suite, runs the financial-correctness benchmark, and verifies migrations apply.

## Performance (local benchmark)
`python -m scripts.benchmark` — calculation engine ~140k cases/sec, reconciliation
~30k records/sec, with zero negative totals and reproducible output. See
`docs/BENCHMARK.md`.
