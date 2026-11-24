-- Idempotent migration for checkpointed catalog expansion state in Neon.
-- Safe to run repeatedly; preserves all existing rows and schemas.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.scraper_discovery_state (
    store_id                  VARCHAR(120) PRIMARY KEY,
    last_cursor               TEXT,
    last_page                 INTEGER NOT NULL DEFAULT 0,
    products_discovered_total INTEGER NOT NULL DEFAULT 0,
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
