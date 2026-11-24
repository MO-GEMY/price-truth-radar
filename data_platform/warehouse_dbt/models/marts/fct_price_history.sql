{{
    config(
        schema='gold',
        materialized='incremental',
        unique_key=['product_sk', 'snapshot_date'],
        incremental_strategy='delete+insert',
        on_schema_change='sync_all_columns',
        post_hook=[
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_fct_price_history_sk_date ON {{ this }} (product_sk, snapshot_date ASC)"
        ]
    )
}}

WITH staged_prices AS (
    SELECT
        product_sk,
        snapshot_date,
        current_price AS price,
        claimed_original_price,
        in_stock,
        available_sizes_count
    FROM {{ ref('stg_products') }}
),

{% if is_incremental() %}
-- Identify only SKUs that have new snapshot dates or modified price/stock/size fields.
-- For each touched SKU, record the earliest modified/new date so every rolling 60-day
-- window from that date forward is recomputed with 100% accuracy.
touched_sks AS MATERIALIZED (
    SELECT
        s.product_sk,
        MIN(s.snapshot_date) AS min_touched_date
    FROM staged_prices s
    LEFT JOIN {{ this }} t
        ON t.product_sk = s.product_sk
       AND t.snapshot_date = s.snapshot_date
    WHERE t.product_sk IS NULL
       OR t.price IS DISTINCT FROM s.price
       OR t.claimed_original_price IS DISTINCT FROM s.claimed_original_price
       OR t.in_stock IS DISTINCT FROM s.in_stock
       OR t.available_sizes_count IS DISTINCT FROM s.available_sizes_count
    GROUP BY s.product_sk
),

daily_prices AS (
    SELECT
        s.product_sk,
        s.snapshot_date,
        s.price,
        s.claimed_original_price,
        s.in_stock,
        s.available_sizes_count,
        ts.min_touched_date
    FROM staged_prices s
    INNER JOIN touched_sks ts
        ON s.product_sk = ts.product_sk
),
{% else %}
daily_prices AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        DATE '1900-01-01' AS min_touched_date
    FROM staged_prices
),
{% endif %}

-- Single window pass to separate 1-day SKUs (no join needed!) from multi-day SKUs.
daily_with_counts AS MATERIALIZED (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        min_touched_date,
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
      AND snapshot_date >= min_touched_date
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
      AND d.snapshot_date >= d.min_touched_date
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
