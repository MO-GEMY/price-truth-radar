"""FastAPI application entrypoint for Price Truth Radar read-only backend."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import compare, health, products, radar, stats

app = FastAPI(
    title="Price Truth Radar API",
    description="Read-only serving API querying the Neon PostgreSQL gold schema.",
    version="1.0.0",
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
app.include_router(products.router)
app.include_router(compare.router)
