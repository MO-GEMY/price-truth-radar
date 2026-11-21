{{
    config(
        schema='gold',
        materialized='table'
    )
}}

WITH matched_base AS (
    SELECT
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
        in_stock,
        product_url,
        discount_verdict
    FROM {{ ref('mart_product_verdicts') }}
    WHERE canonical_product_key IS NOT NULL
),

lowest_ranked AS (
    SELECT
        canonical_product_key,
        store_name AS lowest_price_store,
        clean_title_candidate AS product_title_clean,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_product_key
            ORDER BY current_price ASC, in_stock DESC, store_name ASC
        ) AS rn
    FROM matched_base
),

aggregated AS (
    SELECT
        canonical_product_key,
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
                'in_stock', in_stock,
                'product_url', product_url,
                'discount_verdict', discount_verdict
            )
            ORDER BY current_price ASC, store_name ASC
        )::JSONB AS listings_json
    FROM matched_base
    GROUP BY canonical_product_key
    HAVING COUNT(DISTINCT store_name) >= 2
)

SELECT
    a.canonical_product_key::VARCHAR AS canonical_product_key,
    lr.product_title_clean::TEXT AS product_title_clean,
    a.category::VARCHAR AS category,
    a.brand::VARCHAR AS brand,
    a.stores_count::INTEGER AS stores_count,
    a.lowest_price::NUMERIC(12,2) AS lowest_price,
    lr.lowest_price_store::VARCHAR AS lowest_price_store,
    a.highest_price::NUMERIC(12,2) AS highest_price,
    (a.highest_price - a.lowest_price)::NUMERIC(12,2) AS price_spread_egp,
    ROUND(
        ((a.highest_price - a.lowest_price) / NULLIF(a.lowest_price, 0)) * 100.0,
        2
    )::NUMERIC(5,2) AS price_spread_pct,
    a.listings_json::JSONB AS listings_json
FROM aggregated a
INNER JOIN lowest_ranked lr
    ON a.canonical_product_key = lr.canonical_product_key
   AND lr.rn = 1
ORDER BY price_spread_pct DESC, a.canonical_product_key ASC
