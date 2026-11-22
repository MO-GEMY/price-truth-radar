{{
    config(
        schema='gold',
        materialized='table'
    )
}}

WITH candidates AS (
    SELECT
        -- Strict grocery matching guard (defense-in-depth at SQL layer):
        -- 1. Preserve multi-store EAN/GTIN barcode keys (`grocery_gtin_*`).
        -- 2. Otherwise enforce exact net_weight_g / net_volume_ml / pack_count
        --    so different package sizes (e.g. 700ml vs 1L) can NEVER group together.
        CASE
            WHEN category = 'groceries' THEN
                CASE
                    WHEN canonical_product_key LIKE 'grocery_gtin_%'
                        THEN canonical_product_key
                    WHEN canonical_product_key IS NOT NULL
                         AND (
                             ((attributes_json ->> 'net_weight_g') ~ '^[0-9]+$' AND (attributes_json ->> 'net_weight_g')::INTEGER > 0)
                             OR ((attributes_json ->> 'net_volume_ml') ~ '^[0-9]+$' AND (attributes_json ->> 'net_volume_ml')::INTEGER > 0)
                         )
                        THEN CASE
                            WHEN canonical_product_key ~ ('_(w' || COALESCE(CASE WHEN (attributes_json ->> 'net_weight_g') ~ '^[0-9]+$' THEN (attributes_json ->> 'net_weight_g') END, '0') || 'g|v' || COALESCE(CASE WHEN (attributes_json ->> 'net_volume_ml') ~ '^[0-9]+$' THEN (attributes_json ->> 'net_volume_ml') END, '0') || 'ml)_x' || COALESCE(CASE WHEN (attributes_json ->> 'pack_count') ~ '^[0-9]+$' THEN (attributes_json ->> 'pack_count') END, '1') || '$')
                                THEN canonical_product_key
                            ELSE canonical_product_key
                                 || '__w' || COALESCE(CASE WHEN (attributes_json ->> 'net_weight_g') ~ '^[0-9]+$' THEN (attributes_json ->> 'net_weight_g') END, '0')
                                 || '_v' || COALESCE(CASE WHEN (attributes_json ->> 'net_volume_ml') ~ '^[0-9]+$' THEN (attributes_json ->> 'net_volume_ml') END, '0')
                                 || '_x' || COALESCE(CASE WHEN (attributes_json ->> 'pack_count') ~ '^[0-9]+$' THEN (attributes_json ->> 'pack_count') END, '1')
                        END
                    ELSE NULL
                END
            ELSE canonical_product_key
        END AS effective_match_key,
        canonical_product_key,
        TRIM(
            REGEXP_REPLACE(
                REGEXP_REPLACE(product_title, '\s*-\s*Official Warranty$', '', 'i'),
                '\s*\(Egypt\)$',
                '',
                'i'
            )
        ) AS clean_title_candidate,
        category,
        brand,
        product_sk,
        store_name,
        current_price,
        unit_price_egp,
        CASE
            WHEN (attributes_json ->> 'net_weight_g') ~ '^[0-9]+$'
                 AND (attributes_json ->> 'net_weight_g')::INTEGER > 0
                THEN 'kg'
            WHEN (attributes_json ->> 'net_volume_ml') ~ '^[0-9]+$'
                 AND (attributes_json ->> 'net_volume_ml')::INTEGER > 0
                THEN 'L'
            ELSE NULL
        END::VARCHAR AS unit_price_unit,
        in_stock,
        product_url,
        discount_verdict
    FROM {{ ref('mart_product_verdicts') }}
),

matched_raw AS (
    SELECT
        COALESCE(canonical_product_key, effective_match_key) AS canonical_product_key,
        effective_match_key,
        clean_title_candidate,
        category,
        brand,
        product_sk,
        store_name,
        current_price,
        unit_price_egp,
        unit_price_unit,
        in_stock,
        product_url,
        discount_verdict,
        ROW_NUMBER() OVER (
            PARTITION BY effective_match_key, store_name
            ORDER BY in_stock DESC, current_price ASC, product_sk ASC
        ) AS store_rn
    FROM candidates
    WHERE effective_match_key IS NOT NULL
),

-- Keep one representative (cheapest in-stock) listing per store per canonical product
-- so multi-color variants at the same store never duplicate rows in listings_json.
matched_base AS (
    SELECT
        canonical_product_key,
        effective_match_key,
        clean_title_candidate,
        category,
        brand,
        product_sk,
        store_name,
        current_price,
        unit_price_egp,
        unit_price_unit,
        in_stock,
        product_url,
        discount_verdict
    FROM matched_raw
    WHERE store_rn = 1
),

lowest_ranked AS (
    SELECT
        effective_match_key,
        store_name AS lowest_price_store,
        clean_title_candidate AS product_title_clean,
        ROW_NUMBER() OVER (
            PARTITION BY effective_match_key
            ORDER BY current_price ASC, in_stock DESC, store_name ASC
        ) AS rn
    FROM matched_base
),

aggregated AS (
    SELECT
        effective_match_key,
        MIN(canonical_product_key) AS canonical_product_key,
        MIN(category) AS category,
        MIN(brand) AS brand,
        COUNT(DISTINCT store_name)::INTEGER AS stores_count,
        MIN(current_price)::NUMERIC(12,2) AS lowest_price,
        MAX(current_price)::NUMERIC(12,2) AS highest_price,
        JSONB_AGG(
            JSONB_BUILD_OBJECT(
                'product_sk', product_sk,
                'store_name', store_name,
                'price', current_price,
                'unit_price_egp', unit_price_egp,
                'unit_price_unit', unit_price_unit,
                'in_stock', in_stock,
                'product_url', product_url,
                'discount_verdict', discount_verdict
            )
            ORDER BY current_price ASC, store_name ASC
        )::JSONB AS listings_json
    FROM matched_base
    GROUP BY effective_match_key
    HAVING COUNT(DISTINCT store_name) >= 2
)

SELECT
    a.effective_match_key::VARCHAR AS canonical_product_key,
    lr.product_title_clean::TEXT AS product_title_clean,
    a.category::VARCHAR AS category,
    a.brand::VARCHAR AS brand,
    a.stores_count::INTEGER AS stores_count,
    a.lowest_price::NUMERIC(12,2) AS lowest_price,
    lr.lowest_price_store::VARCHAR AS lowest_price_store,
    a.highest_price::NUMERIC(12,2) AS highest_price,
    (a.highest_price - a.lowest_price)::NUMERIC(12,2) AS price_spread_egp,
    COALESCE(
        LEAST(
            999.99,
            ROUND(
                ((a.highest_price - a.lowest_price) / NULLIF(a.lowest_price, 0)) * 100.0,
                2
            )
        ),
        0.00
    )::NUMERIC(5,2) AS price_spread_pct,
    a.listings_json::JSONB AS listings_json
FROM aggregated a
INNER JOIN lowest_ranked lr
    ON a.effective_match_key = lr.effective_match_key
   AND lr.rn = 1
ORDER BY price_spread_pct DESC, a.canonical_product_key ASC
