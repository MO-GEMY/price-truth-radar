-- =============================================================================
-- Migration 003: Bilingual Search (`pg_trgm` GIN Indexes) & Delta Snapshots
-- Idempotent PostgreSQL / Neon migration script.
-- Safe to re-run before or after dbt refreshes.
-- =============================================================================

-- 1. Enable pg_trgm extension for typo-tolerant bilingual AR/EN trigram search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Delta Snapshots column & composite index on raw.raw_product_snapshots
--    Tracks last_seen_at for unchanged listings without inserting redundant daily rows.
DO $$
BEGIN
    IF to_regclass('raw.raw_product_snapshots') IS NOT NULL THEN
        ALTER TABLE raw.raw_product_snapshots
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;

        -- Backfill NULL last_seen_at cleanly on existing rows (metadata only, non-destructive)
        UPDATE raw.raw_product_snapshots
        SET last_seen_at = scraped_at AT TIME ZONE 'UTC'
        WHERE last_seen_at IS NULL;

        -- Fast latest-snapshot-per-product lookup for Delta Snapshot diffing
        CREATE INDEX IF NOT EXISTS idx_raw_snapshots_store_ext_latest
            ON raw.raw_product_snapshots (store_name, external_id, snapshot_date DESC, scraped_at DESC);
    END IF;
END $$;

-- 3. Bilingual Arabic normalization SQL helper (immutable so it can back GIN trigram indexes)
CREATE OR REPLACE FUNCTION public.normalize_arabic_search(input_text TEXT)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
STRICT
AS $$
    SELECT LOWER(
        TRANSLATE(
            REGEXP_REPLACE(input_text, '[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', 'g'),
            'أإآٱةىؤئ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹',
            'ااااهيوي01234567890123456789'
        )
    );
$$;

-- 4. pg_trgm GIN indexes on gold.mart_product_verdicts for sub-50ms bilingual search
DO $$
BEGIN
    IF to_regclass('gold.mart_product_verdicts') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_title_trgm
            ON gold.mart_product_verdicts
            USING GIN (LOWER(product_title) gin_trgm_ops);

        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_brand_trgm
            ON gold.mart_product_verdicts
            USING GIN (LOWER(brand) gin_trgm_ops);

        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_norm_search_trgm
            ON gold.mart_product_verdicts
            USING GIN (
                public.normalize_arabic_search(
                    COALESCE(product_title, '') || ' ' ||
                    COALESCE(brand, '') || ' ' ||
                    COALESCE(sub_category, '') || ' ' ||
                    COALESCE(canonical_product_key, '')
                ) gin_trgm_ops
            );

        -- Index materialized search_document once dbt adds the column
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'gold'
              AND table_name = 'mart_product_verdicts'
              AND column_name = 'search_document'
        ) THEN
            CREATE INDEX IF NOT EXISTS idx_mart_verdicts_search_doc_trgm
                ON gold.mart_product_verdicts
                USING GIN (LOWER(search_document) gin_trgm_ops);
        END IF;
    END IF;
END $$;
