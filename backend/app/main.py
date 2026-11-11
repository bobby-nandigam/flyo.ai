"""FastAPI application entrypoint.

Wires auth, trips/bookings, refund cases, and the stateless calculation API.
Reconciliation, document intelligence and the AI investigation agent are added as
their phases land (docs/ARCHITECTURE.md §Roadmap). Unfinished modules are not
stubbed into the router, so every advertised endpoint actually works (spec §13).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.database import Base, get_engine
import app.models  # noqa: F401  -- registers all tables on Base.metadata
from app.api.routes import auth, calculations, dashboard, refund_cases, trips

_WEB_DIR = Path(__file__).parent / "web"

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In development/CI we create tables directly for convenience. Production uses
    # Alembic migrations (see backend/alembic/) and this create_all is a no-op on
    # an already-migrated database.
    if settings.environment != "production":
        Base.metadata.create_all(bind=get_engine())
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Every rupee accounted for. Every refund traceable.",
    lifespan=lifespan,
)

_V1 = "/api/v1"
app.include_router(auth.router, prefix=_V1)
app.include_router(trips.router, prefix=_V1)
app.include_router(refund_cases.router, prefix=_V1)
app.include_router(dashboard.router, prefix=_V1)
app.include_router(calculations.router, prefix=_V1)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    """Serve the single-page login + dashboard UI."""
    return FileResponse(_WEB_DIR / "index.html")
