-- =============================================================================
-- Migration 004: Neon Free-Tier Storage Optimization (Zero Data Loss)
--   1. Drops redundant staging indexes on raw.raw_product_snapshots (~36 MB).
--   2. Replaces full idx_mart_verdicts_parent_key (17 MB) with a partial index
--      covering ONLY multi-variant rows (`WHERE has_multiple_variants = TRUE`, ~3 MB).
--   3. Allows NULL in raw.raw_product_snapshots.attributes_json so empty objects
--      store NULL (0 bytes) instead of '{}'.
--
-- NEVER touches gold.fct_price_history and NEVER runs VACUUM FULL on
-- gold.mart_product_verdicts.
-- =============================================================================

-- 1. Drop redundant staging indexes (covered by PK & idx_raw_snapshots_date_store_cat)
DROP INDEX IF EXISTS raw.idx_raw_snapshots_store_cat_ext;
DROP INDEX IF EXISTS raw.idx_raw_snapshots_date;

DO $$
BEGIN
    IF to_regclass('raw.raw_product_snapshots') IS NOT NULL THEN
        ALTER TABLE raw.raw_product_snapshots
            ALTER COLUMN attributes_json DROP NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_raw_snapshots_date_store_cat
            ON raw.raw_product_snapshots (snapshot_date DESC, store_name, category);
    END IF;
END $$;

-- 2. Narrow gold.mart_product_verdicts parent_key index to multi-variant rows only
DO $$
BEGIN
    IF to_regclass('gold.mart_product_verdicts') IS NOT NULL THEN
        DROP INDEX IF EXISTS gold.idx_mart_verdicts_parent_key;
        CREATE INDEX IF NOT EXISTS idx_mart_verdicts_parent_key
            ON gold.mart_product_verdicts (parent_product_key)
            WHERE has_multiple_variants = TRUE;
    END IF;
END $$;
