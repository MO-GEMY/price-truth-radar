{{
    config(
        schema='gold',
        materialized='table',
        post_hook=[
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_fct_price_history_sk_date",
            "CREATE INDEX idx_fct_price_history_sk_date ON {{ this }} (product_sk, snapshot_date ASC)"
        ]
    )
}}

WITH daily_prices AS (
    SELECT
        product_sk,
        snapshot_date,
        current_price AS price,
        claimed_original_price,
        in_stock,
        available_sizes_count
    FROM {{ ref('stg_products') }}
),

-- Single window pass to separate 1-day SKUs (no join needed!) from multi-day SKUs.
daily_with_counts AS MATERIALIZED (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        COUNT(*) OVER (PARTITION BY product_sk) AS day_count
    FROM daily_prices
),

multi_day_series AS (
    SELECT
        product_sk,
        ARRAY_AGG(snapshot_date ORDER BY snapshot_date) AS all_dates,
        ARRAY_AGG(price ORDER BY snapshot_date) AS all_prices
    FROM daily_with_counts
    WHERE day_count > 1
    GROUP BY product_sk
),

single_day_results AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        price::NUMERIC(12,2) AS rolling_60d_median,
        in_stock,
        available_sizes_count
    FROM daily_with_counts
    WHERE day_count = 1
),

multi_day_results AS (
    SELECT
        d.product_sk,
        d.snapshot_date,
        d.price,
        d.claimed_original_price,
        ROUND(m.rolling_60d_median::NUMERIC, 2)::NUMERIC(12,2) AS rolling_60d_median,
        d.in_stock,
        d.available_sizes_count
    FROM daily_with_counts d
    INNER JOIN multi_day_series p
        ON d.product_sk = p.product_sk
    CROSS JOIN LATERAL (
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY u.hist_price) AS rolling_60d_median
        FROM UNNEST(p.all_dates, p.all_prices) AS u(hist_date, hist_price)
        WHERE u.hist_date BETWEEN (d.snapshot_date - INTERVAL '59 days')::DATE AND d.snapshot_date
    ) m
    WHERE d.day_count > 1
)

SELECT
    product_sk::VARCHAR AS product_sk,
    snapshot_date::DATE AS snapshot_date,
    price::NUMERIC(12,2) AS price,
    claimed_original_price::NUMERIC(12,2) AS claimed_original_price,
    rolling_60d_median::NUMERIC(12,2) AS rolling_60d_median,
    in_stock::BOOLEAN AS in_stock,
    available_sizes_count::INTEGER AS available_sizes_count
FROM (
    SELECT * FROM single_day_results
    UNION ALL
    SELECT * FROM multi_day_results
) combined_results
ORDER BY product_sk, snapshot_date
