"""Health check endpoints: zero-DB `/health` for keep-alives and `/health/db` for DB readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import get_db
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_class=PlainTextResponse)
def health_check() -> PlainTextResponse:
    """Zero-DB liveness probe returning HTTP 200 with 'OK' strictly in memory."""
    return PlainTextResponse("OK", status_code=200)


@router.get("/health/db", response_model=HealthResponse)
def health_db_check(db: Connection = Depends(get_db)) -> HealthResponse:
    """Explicit database readiness check for ops/monitoring."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return HealthResponse(status="ok", database="connected")
