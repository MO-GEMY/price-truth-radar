-- =============================================================================
-- Migration 002: Scale Indexes (25k+ SKUs) & Price Drop Alerts Table
-- Idempotent PostgreSQL / Neon migration script.
-- Safe to re-run after dbt refreshes or fresh deployments.
-- =============================================================================

-- 1. Price Drop Alerts Table (public.price_alerts)
CREATE TABLE IF NOT EXISTS public.price_alerts (
    id            SERIAL PRIMARY KEY,
    product_key   TEXT NOT NULL,
    product_title TEXT,
    store_name    TEXT,
    target_price  NUMERIC(12,2) NOT NULL CHECK (target_price > 0),
    channel       TEXT NOT NULL CHECK (channel IN ('telegram', 'email')),
    destination   TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    triggered_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast active alert lookups by product_key (for alert checker job)
CREATE INDEX IF NOT EXISTS idx_price_alerts_active_product
    ON public.price_alerts (product_key)
    WHERE is_active = TRUE AND triggered_at IS NULL;

-- Fast duplicate check per destination + product_key (rate-limit / dedup)
CREATE INDEX IF NOT EXISTS idx_price_alerts_active_dest_product
    ON public.price_alerts (LOWER(destination), product_key)
    WHERE is_active = TRUE;

-- Chronological inspection / cleanup
CREATE INDEX IF NOT EXISTS idx_price_alerts_created_at
    ON public.price_alerts (created_at DESC);

-- 2. Raw Ingestion Layer Indexes (raw.raw_product_snapshots)
-- Keep only the composite date/store/category index alongside the PK (store_name, external_id, snapshot_date).
-- Redundant idx_raw_snapshots_store_cat_ext & idx_raw_snapshots_date are dropped to save ~36 MB.
DO $$
BEGIN
    IF to_regclass('raw.raw_product_snapshots') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_raw_snapshots_date_store_cat
            ON raw.raw_product_snapshots (snapshot_date DESC, store_name, category);

        DROP INDEX IF EXISTS raw.idx_raw_snapshots_store_cat_ext;
        DROP INDEX IF EXISTS raw.idx_raw_snapshots_date;
    END IF;
END $$;

-- 3. Gold Serving Layer Indexes (gold.mart_product_verdicts, fct_price_history, mart_cross_store_matches)
-- Guarded with to_regclass so migration stays idempotent before/after dbt runs.
DO $$
BEGIN
    IF to_regclass('gold.mart_product_verdicts') IS NOT NULL THEN
        -- Direct product detail & alert lookup
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_product_sk
            ON gold.mart_product_verdicts (product_sk);

        -- Cross-store canonical key joins & alert matching
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_canonical_key
            ON gold.mart_product_verdicts (canonical_product_key)
            WHERE canonical_product_key IS NOT NULL;

        -- Hot radar feed & biggest scandals filter/sort
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_cat_verdict_gap
            ON gold.mart_product_verdicts (
                category,
                discount_verdict,
                ((claimed_discount_pct - real_discount_pct)) DESC,
                product_sk ASC
            );

        -- Hot best real deals filter/sort
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_cat_verdict_real_drop
            ON gold.mart_product_verdicts (
                category,
                discount_verdict,
                real_discount_pct DESC,
                product_sk ASC
            );

        -- Store + category + price filter/sort
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_store_cat_price
            ON gold.mart_product_verdicts (store_name, category, current_price ASC, product_sk ASC);

        -- Sitemap & freshness ordering
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_last_updated
            ON gold.mart_product_verdicts (last_updated_at DESC);
    END IF;

    IF to_regclass('gold.fct_price_history') IS NOT NULL THEN
        -- Product detail price chart lookup
        CREATE INDEX IF NOT EXISTS idx_fct_price_history_sk_date
            ON gold.fct_price_history (product_sk, snapshot_date ASC);

        -- Recent snapshot range scans
        CREATE INDEX IF NOT EXISTS idx_fct_price_history_date_sk
            ON gold.fct_price_history (snapshot_date DESC, product_sk);
    END IF;

    IF to_regclass('gold.mart_cross_store_matches') IS NOT NULL THEN
        -- Direct canonical key lookup (product detail alternatives)
        CREATE INDEX IF NOT EXISTS idx_mart_compare_canonical_key
            ON gold.mart_cross_store_matches (canonical_product_key);

        -- /api/v1/compare default sort & category filter
        CREATE INDEX IF NOT EXISTS idx_mart_compare_cat_spread
            ON gold.mart_cross_store_matches (category, price_spread_pct DESC, canonical_product_key ASC);
    END IF;
END $$;
