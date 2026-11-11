"""Vercel serverless entrypoint.

Vercel's Python runtime serves the ASGI ``app`` object exported here. Because a
serverless filesystem is ephemeral, the demo runs on SQLite under /tmp and seeds
the synthetic dataset on cold start, so the live link always has data to show.
For real persistence, point DATABASE_URL at a managed Postgres and remove the
seeding block.
"""
import os

# Configure the runtime BEFORE importing the app (settings are read on first use).
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/flyo_demo.db")
os.environ.setdefault("ENVIRONMENT", "demo")
os.environ.setdefault("JWT_SECRET", "flyo-demo-secret-synthetic-data-only-change-me-123")

from app.main import app  # noqa: E402  (exported for Vercel's ASGI handler)

try:
    from scripts.seed_demo import seed_if_empty

    seed_if_empty()
except Exception as exc:  # pragma: no cover - never fail the cold start on seed
    print(f"[startup] demo seed skipped: {exc}")
