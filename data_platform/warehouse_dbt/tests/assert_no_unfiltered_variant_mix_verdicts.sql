-- Singular dbt data test:
-- Fails if any product in gold.mart_product_verdicts:
--   1. Emits a non-NORMAL_PRICE discount verdict despite extreme historical price
--      oscillation (max_historical_price / min_historical_price >= 1.8) on the same product_sk.
--   2. Emits a non-NORMAL_PRICE discount verdict despite conflicting variant_id or
--      variant_label values across historical snapshots of the same product_sk.
--   3. Violates variant rollup invariants (variant_count < 1, inconsistent
--      has_multiple_variants flag, or min_variant_price / max_variant_price out of order).

WITH variant_conflicts AS (
    SELECT
        product_sk
    FROM {{ ref('stg_products') }}
    GROUP BY product_sk
    HAVING COUNT(DISTINCT variant_id) > 1
        OR COUNT(DISTINCT LOWER(TRIM(variant_label))) > 1
)

SELECT
    v.product_sk,
    v.store_name,
    v.product_title,
    v.current_price,
    v.min_historical_price,
    v.max_historical_price,
    v.discount_verdict,
    v.variant_count,
    v.has_multiple_variants,
    v.min_variant_price,
    v.max_variant_price
FROM {{ ref('mart_product_verdicts') }} v
LEFT JOIN variant_conflicts vc
    ON v.product_sk = vc.product_sk
WHERE
    (
        v.min_historical_price > 0
        AND (v.max_historical_price / v.min_historical_price) >= 1.8
        AND v.discount_verdict <> 'NORMAL_PRICE'
    )
    OR (
        vc.product_sk IS NOT NULL
        AND v.discount_verdict <> 'NORMAL_PRICE'
    )
    OR v.variant_count < 1
    OR v.has_multiple_variants <> (v.variant_count > 1)
    OR v.min_variant_price > v.max_variant_price
    OR v.min_variant_price > v.current_price
    OR v.max_variant_price < v.current_price
