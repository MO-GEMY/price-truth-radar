{{
    config(
        schema='gold',
        materialized='table'
    )
}}

WITH staging_history AS (
    SELECT
        product_sk,
        snapshot_date,
        current_price AS price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        scraped_at,
        2 AS source_priority
    FROM {{ ref('stg_products') }}
),

scd_snapshot_history AS (
    SELECT
        product_sk::VARCHAR AS product_sk,
        snapshot_date::DATE AS snapshot_date,
        current_price::NUMERIC(12,2) AS price,
        claimed_original_price::NUMERIC(12,2) AS claimed_original_price,
        in_stock::BOOLEAN AS in_stock,
        available_sizes_count::INTEGER AS available_sizes_count,
        COALESCE(dbt_updated_at::TIMESTAMP, scraped_at::TIMESTAMP) AS scraped_at,
        1 AS source_priority
    FROM {{ ref('snp_product_history') }}
),

combined AS (
    SELECT * FROM staging_history
    UNION ALL
    SELECT * FROM scd_snapshot_history
),

deduped_daily AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        ROW_NUMBER() OVER (
            PARTITION BY product_sk, snapshot_date
            ORDER BY source_priority ASC, scraped_at DESC
        ) AS rn
    FROM combined
),

daily_prices AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count
    FROM deduped_daily
    WHERE rn = 1
)

SELECT
    d.product_sk::VARCHAR AS product_sk,
    d.snapshot_date::DATE AS snapshot_date,
    d.price::NUMERIC(12,2) AS price,
    d.claimed_original_price::NUMERIC(12,2) AS claimed_original_price,
    ROUND(m.rolling_60d_median::NUMERIC, 2)::NUMERIC(12,2) AS rolling_60d_median,
    d.in_stock::BOOLEAN AS in_stock,
    d.available_sizes_count::INTEGER AS available_sizes_count
FROM daily_prices d
CROSS JOIN LATERAL (
    SELECT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.price) AS rolling_60d_median
    FROM daily_prices h
    WHERE h.product_sk = d.product_sk
      AND h.snapshot_date BETWEEN (d.snapshot_date - INTERVAL '59 days')::DATE AND d.snapshot_date
) m
ORDER BY d.product_sk, d.snapshot_date
