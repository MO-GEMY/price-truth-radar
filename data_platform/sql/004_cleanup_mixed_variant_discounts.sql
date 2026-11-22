-- =============================================================================
-- 004_cleanup_mixed_variant_discounts.sql
-- Safe, non-destructive cleanup for historical Shopify/WooCommerce rows whose
-- `claimed_original_price` was inflated (>80% claimed discount) by the old
-- cross-variant `min(price)` vs `max(compare_at_price)` mixing bug.
--
-- IMPORTANT:
--   1. Does NOT delete any rows — only clears `claimed_original_price = NULL`
--      so valid `current_price` history is preserved until the next fixed scrape.
--   2. Review Step 1 (read-only preview) before running Step 2 inside a
--      transaction, then run `python data_platform/run_dbt.py run && test`.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- STEP 1: Read-only audit preview (safe to run anytime)
-- ---------------------------------------------------------------------------
SELECT
    store_name,
    COUNT(*) AS affected_rows,
    COUNT(DISTINCT external_id) AS affected_products,
    ROUND(MAX(((claimed_original_price - current_price) / claimed_original_price) * 100.0), 1) AS max_claimed_disc_pct
FROM raw.raw_product_snapshots
WHERE claimed_original_price IS NOT NULL
  AND claimed_original_price > current_price
  AND current_price > 0
  AND ((claimed_original_price - current_price) / claimed_original_price) > 0.80
  AND store_name IN (
      'athlete_home', 'bednhome', 'dream2000', 'ennap', 'happet',
      'jadeite_coffee', 'kabbani', 'lokal_eg', 'nile_home',
      'smart_furniture', 'source_beauty', 'town_team', 'zynah'
  )
GROUP BY store_name
ORDER BY affected_rows DESC;

-- ---------------------------------------------------------------------------
-- STEP 2: Non-destructive cleanup (clear corrupted strikethrough prices only)
--         Run this BEFORE `dbt run` so `gold.mart_product_verdicts` & highlights
--         immediately drop all cross-variant >80% ghost discounts.
-- ---------------------------------------------------------------------------
BEGIN;

UPDATE raw.raw_product_snapshots
SET claimed_original_price = NULL
WHERE claimed_original_price IS NOT NULL
  AND claimed_original_price > current_price
  AND current_price > 0
  AND ((claimed_original_price - current_price) / claimed_original_price) > 0.80
  AND store_name IN (
      'athlete_home', 'bednhome', 'dream2000', 'ennap', 'happet',
      'jadeite_coffee', 'kabbani', 'lokal_eg', 'nile_home',
      'smart_furniture', 'source_beauty', 'town_team', 'zynah'
  );

-- Optional: also clear the 4 mixed-weight Gourmet cheese outliers (>80% claimed)
-- UPDATE raw.raw_product_snapshots
-- SET claimed_original_price = NULL
-- WHERE store_name = 'gourmet'
--   AND claimed_original_price IS NOT NULL
--   AND claimed_original_price > current_price
--   AND ((claimed_original_price - current_price) / claimed_original_price) > 0.80;

COMMIT;
