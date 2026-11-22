{{
    config(
        schema='gold',
        materialized='table'
    )
}}

WITH latest_staged AS (
    SELECT
        product_sk,
        canonical_product_key,
        store_name,
        category,
        sub_category,
        brand,
        product_title,
        product_url,
        image_url,
        attributes_json,
        current_price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        total_sizes,
        unit_price_egp,
        snapshot_date,
        scraped_at,
        ROW_NUMBER() OVER (
            PARTITION BY product_sk
            ORDER BY snapshot_date DESC, scraped_at DESC
        ) AS rn
    FROM {{ ref('stg_products') }}
),

current_products AS (
    SELECT *
    FROM latest_staged
    WHERE rn = 1
),

product_latest_dates AS (
    SELECT
        product_sk,
        MAX(snapshot_date) AS latest_date
    FROM {{ ref('fct_price_history') }}
    GROUP BY product_sk
),

history_stats AS (
    SELECT
        h.product_sk,
        COUNT(DISTINCT h.snapshot_date)::INTEGER AS history_days,
        MIN(h.price)::NUMERIC(12,2) AS min_historical_price,
        MAX(h.price)::NUMERIC(12,2) AS max_historical_price,
        MAX(CASE WHEN h.snapshot_date = ld.latest_date THEN h.rolling_60d_median END)::NUMERIC(12,2) AS rolling_60d_median,
        ROUND(
            (
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.price)
                FILTER (
                    WHERE h.snapshot_date BETWEEN (ld.latest_date - INTERVAL '59 days')::DATE
                                              AND (ld.latest_date - INTERVAL '14 days')::DATE
                )
            )::NUMERIC,
            2
        )::NUMERIC(12,2) AS prior_45d_median
    FROM {{ ref('fct_price_history') }} h
    INNER JOIN product_latest_dates ld
        ON h.product_sk = ld.product_sk
    GROUP BY h.product_sk
),

metrics AS (
    SELECT
        cp.product_sk,
        cp.canonical_product_key,
        cp.store_name,
        cp.category,
        cp.sub_category,
        cp.brand,
        cp.product_title,
        cp.product_url,
        cp.image_url,
        cp.attributes_json,
        cp.current_price,
        cp.claimed_original_price,
        COALESCE(hs.rolling_60d_median, cp.current_price)::NUMERIC(12,2) AS rolling_60d_median,
        COALESCE(hs.min_historical_price, cp.current_price)::NUMERIC(12,2) AS min_historical_price,
        COALESCE(hs.max_historical_price, cp.current_price)::NUMERIC(12,2) AS max_historical_price,
        COALESCE(hs.history_days, 1)::INTEGER AS history_days,
        hs.prior_45d_median,
        CASE
            WHEN cp.claimed_original_price IS NOT NULL
                 AND cp.claimed_original_price > cp.current_price
                THEN GREATEST(
                    0.00,
                    LEAST(
                        999.99,
                        ROUND(
                            ((cp.claimed_original_price - cp.current_price) / cp.claimed_original_price) * 100.0,
                            2
                        )
                    )
                )::NUMERIC(5,2)
            ELSE 0.00::NUMERIC(5,2)
        END AS claimed_discount_pct,
        CASE
            WHEN COALESCE(hs.rolling_60d_median, cp.current_price) > 0
                THEN GREATEST(
                    -999.99,
                    LEAST(
                        999.99,
                        ROUND(
                            (
                                (COALESCE(hs.rolling_60d_median, cp.current_price) - cp.current_price)
                                / COALESCE(hs.rolling_60d_median, cp.current_price)
                            ) * 100.0,
                            2
                        )
                    )
                )::NUMERIC(5,2)
            ELSE 0.00::NUMERIC(5,2)
        END AS real_discount_pct,
        CASE
            WHEN cp.category = 'fashion'
                 AND cp.total_sizes IS NOT NULL
                 AND cp.total_sizes > 0
                 AND (COALESCE(cp.available_sizes_count, 0)::NUMERIC / cp.total_sizes::NUMERIC) < 0.25
                THEN TRUE
            ELSE FALSE
        END::BOOLEAN AS scarcity_flag,
        cp.in_stock,
        cp.scraped_at AS last_updated_at,
        cp.unit_price_egp
    FROM current_products cp
    LEFT JOIN history_stats hs
        ON cp.product_sk = hs.product_sk
)

SELECT
    product_sk::VARCHAR AS product_sk,
    canonical_product_key::VARCHAR AS canonical_product_key,
    store_name::VARCHAR AS store_name,
    category::VARCHAR AS category,
    sub_category::VARCHAR AS sub_category,
    brand::VARCHAR AS brand,
    product_title::TEXT AS product_title,
    product_url::TEXT AS product_url,
    image_url::TEXT AS image_url,
    attributes_json::JSONB AS attributes_json,
    current_price::NUMERIC(12,2) AS current_price,
    claimed_original_price::NUMERIC(12,2) AS claimed_original_price,
    rolling_60d_median::NUMERIC(12,2) AS rolling_60d_median,
    min_historical_price::NUMERIC(12,2) AS min_historical_price,
    max_historical_price::NUMERIC(12,2) AS max_historical_price,
    claimed_discount_pct::NUMERIC(5,2) AS claimed_discount_pct,
    real_discount_pct::NUMERIC(5,2) AS real_discount_pct,
    CASE
        WHEN claimed_discount_pct >= 10 AND real_discount_pct < 3
            THEN 'FAKE_DISCOUNT'
        WHEN current_price <= min_historical_price
             AND history_days >= 14
             AND real_discount_pct >= 5
            THEN 'ALL_TIME_LOW'
        WHEN real_discount_pct >= 10
            THEN 'GENUINE_DEAL'
        WHEN prior_45d_median IS NOT NULL
             AND prior_45d_median > 0
             AND ((current_price - prior_45d_median) / prior_45d_median) * 100.0 >= 12
            THEN 'PRESALE_HIKE'
        ELSE 'NORMAL_PRICE'
    END::VARCHAR AS discount_verdict,
    scarcity_flag::BOOLEAN AS scarcity_flag,
    in_stock::BOOLEAN AS in_stock,
    last_updated_at::TIMESTAMP AS last_updated_at,
    unit_price_egp::NUMERIC(12,2) AS unit_price_egp
FROM metrics
