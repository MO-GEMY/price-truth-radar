"""FastAPI application entrypoint for the Asarak (أسعارك) serving backend."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import alerts, compare, health, highlights, products, radar, seo, stats, submissions

DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "https://asarak.com",
    "https://www.asarak.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def resolve_cors_origins(raw_env: str | None = None) -> list[str]:
    """Build CORS allow-list always including production Asarak origins + dev localhost."""
    val = (os.getenv("CORS_ORIGINS", "") if raw_env is None else raw_env).strip()
    if val == "*":
        return ["*"]
    origins: list[str] = list(DEFAULT_CORS_ORIGINS)
    for item in val.split(","):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


app = FastAPI(
    title="Asarak API",
    description="High-scale serving API for Asarak (أسعارك) querying the Neon PostgreSQL gold schema + price drop alerts.",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the browser read the public-form rate limit back-off (429 responses).
    expose_headers=["Retry-After"],
)

app.include_router(health.router)
app.include_router(stats.router)
app.include_router(radar.router)
app.include_router(highlights.router)
app.include_router(products.router)
app.include_router(compare.router)
app.include_router(alerts.router)
app.include_router(seo.router)
app.include_router(submissions.router)
