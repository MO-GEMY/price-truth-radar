"""FastAPI application entrypoint for Price Truth Radar serving backend."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import alerts, compare, health, highlights, products, radar, seo, stats

app = FastAPI(
    title="Price Truth Radar API",
    description="High-scale serving API querying the Neon PostgreSQL gold schema + price drop alerts.",
    version="1.1.0",
)

cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
if cors_origins_raw == "*" or not cors_origins_raw:
    allow_origins = ["*"]
else:
    allow_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(stats.router)
app.include_router(radar.router)
app.include_router(highlights.router)
app.include_router(products.router)
app.include_router(compare.router)
app.include_router(alerts.router)
app.include_router(seo.router)
