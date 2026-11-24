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

-- Change-only deduplicated price history:
--   * Inserts a new daily row ONLY when (price, claimed_original_price, in_stock)
--     actually changed compared to the product's latest recorded history row,
--     or when it is the product's first-ever snapshot (or a same-date correction).
--   * Preserves all prior rows in {{ this }} when recomputing rolling_60d_median so
--     3-day rolling raw snapshot retention NEVER loses historical context.
--   * Computes duration-weighted 60-day rolling medians over step intervals so
--     deduplicated plateaus yield the exact same median as daily repeated rows.

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
existing_latest AS MATERIALIZED (
    SELECT DISTINCT ON (product_sk)
        product_sk,
        snapshot_date AS latest_snapshot_date,
        price AS latest_price,
        claimed_original_price AS latest_claimed_original_price,
        in_stock AS latest_in_stock
    FROM {{ this }}
    ORDER BY product_sk, snapshot_date DESC
),

-- Evaluate incoming staged rows chronologically against both prior staged rows
-- (for multi-day batches / brand-new SKUs) and existing_latest in {{ this }}.
staged_with_prev AS (
    SELECT
        s.product_sk,
        s.snapshot_date,
        s.price,
        s.claimed_original_price,
        s.in_stock,
        s.available_sizes_count,
        el.latest_snapshot_date,
        el.latest_price,
        el.latest_claimed_original_price,
        el.latest_in_stock,
        ROW_NUMBER() OVER (PARTITION BY s.product_sk ORDER BY s.snapshot_date ASC) AS staged_rn,
        LAG(s.price) OVER (PARTITION BY s.product_sk ORDER BY s.snapshot_date ASC) AS prev_staged_price,
        LAG(s.claimed_original_price) OVER (PARTITION BY s.product_sk ORDER BY s.snapshot_date ASC) AS prev_staged_orig,
        LAG(s.in_stock) OVER (PARTITION BY s.product_sk ORDER BY s.snapshot_date ASC) AS prev_staged_in_stock,
        (t_same.product_sk IS NOT NULL) AS exists_same_date,
        (
            t_same.product_sk IS NOT NULL
            AND (
                t_same.price IS DISTINCT FROM s.price
                OR t_same.claimed_original_price IS DISTINCT FROM s.claimed_original_price
                OR t_same.in_stock IS DISTINCT FROM s.in_stock
                OR t_same.available_sizes_count IS DISTINCT FROM s.available_sizes_count
            )
        ) AS changed_same_date
    FROM staged_prices s
    LEFT JOIN existing_latest el
        ON el.product_sk = s.product_sk
    LEFT JOIN {{ this }} t_same
        ON t_same.product_sk = s.product_sk
       AND t_same.snapshot_date = s.snapshot_date
),

-- Keep only:
--   1) First-ever snapshot for a brand-new SKU (latest_snapshot_date IS NULL, staged_rn = 1)
--      plus any state transitions within its initial staged dates.
--   2) Same-date corrections for rows already stored in {{ this }}.
--   3) Newer dates (> latest_snapshot_date) ONLY when (price, claimed_original_price, in_stock)
--      actually changed vs. the immediately preceding state (either prior newer staged row
--      or existing_latest). Flat unchanged days are skipped (~85% less storage growth),
--      leaving the product's latest recorded snapshot_date anchor intact.
accepted_staged AS MATERIALIZED (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count
    FROM (
        SELECT
            sp.*,
            LAG(sp.price) OVER (
                PARTITION BY sp.product_sk, (sp.snapshot_date > sp.latest_snapshot_date)
                ORDER BY sp.snapshot_date ASC
            ) AS prev_newer_price,
            LAG(sp.claimed_original_price) OVER (
                PARTITION BY sp.product_sk, (sp.snapshot_date > sp.latest_snapshot_date)
                ORDER BY sp.snapshot_date ASC
            ) AS prev_newer_orig,
            LAG(sp.in_stock) OVER (
                PARTITION BY sp.product_sk, (sp.snapshot_date > sp.latest_snapshot_date)
                ORDER BY sp.snapshot_date ASC
            ) AS prev_newer_in_stock,
            ROW_NUMBER() OVER (
                PARTITION BY sp.product_sk, (sp.snapshot_date > sp.latest_snapshot_date)
                ORDER BY sp.snapshot_date ASC
            ) AS newer_rn
        FROM staged_with_prev sp
        WHERE sp.latest_snapshot_date IS NULL
           OR sp.changed_same_date
           OR sp.snapshot_date > sp.latest_snapshot_date
    ) cand
    WHERE
        -- Same-date correction on an already persisted row
        cand.changed_same_date
        -- Brand-new SKU: always keep first-ever snapshot + subsequent state changes
        OR (
            cand.latest_snapshot_date IS NULL
            AND (
                cand.staged_rn = 1
                OR cand.price IS DISTINCT FROM cand.prev_staged_price
                OR cand.claimed_original_price IS DISTINCT FROM cand.prev_staged_orig
                OR cand.in_stock IS DISTINCT FROM cand.prev_staged_in_stock
            )
        )
        -- Existing SKU with newer date: insert ONLY on (price, claimed_original_price, in_stock) change
        OR (
            cand.latest_snapshot_date IS NOT NULL
            AND cand.snapshot_date > cand.latest_snapshot_date
            AND (
                CASE
                    WHEN cand.newer_rn = 1 THEN (
                        cand.price IS DISTINCT FROM cand.latest_price
                        OR cand.claimed_original_price IS DISTINCT FROM cand.latest_claimed_original_price
                        OR cand.in_stock IS DISTINCT FROM cand.latest_in_stock
                    )
                    ELSE (
                        cand.price IS DISTINCT FROM cand.prev_newer_price
                        OR cand.claimed_original_price IS DISTINCT FROM cand.prev_newer_orig
                        OR cand.in_stock IS DISTINCT FROM cand.prev_newer_in_stock
                    )
                END
            )
        )
),

touched_sks AS MATERIALIZED (
    SELECT
        product_sk,
        MIN(snapshot_date) AS min_touched_date
    FROM accepted_staged
    GROUP BY product_sk
),

-- Reconstruct full chronological series for touched SKUs by unioning preserved
-- rows from {{ this }} with newly accepted staged rows (survives 3-day raw pruning).
daily_prices AS (
    SELECT
        t.product_sk,
        t.snapshot_date,
        t.price,
        t.claimed_original_price,
        t.in_stock,
        t.available_sizes_count,
        ts.min_touched_date
    FROM {{ this }} t
    INNER JOIN touched_sks ts
        ON t.product_sk = ts.product_sk
    LEFT JOIN accepted_staged a
        ON a.product_sk = t.product_sk
       AND a.snapshot_date = t.snapshot_date
    WHERE a.product_sk IS NULL

    UNION ALL

    SELECT
        a.product_sk,
        a.snapshot_date,
        a.price,
        a.claimed_original_price,
        a.in_stock,
        a.available_sizes_count,
        ts.min_touched_date
    FROM accepted_staged a
    INNER JOIN touched_sks ts
        ON a.product_sk = ts.product_sk
),
{% else %}
-- Full refresh: keep first-ever snapshot, every (price, claimed_original_price, in_stock)
-- transition, and the latest snapshot_date anchor per product.
staged_ranked AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        ROW_NUMBER() OVER (PARTITION BY product_sk ORDER BY snapshot_date ASC) AS rn_asc,
        ROW_NUMBER() OVER (PARTITION BY product_sk ORDER BY snapshot_date DESC) AS rn_desc,
        LAG(price) OVER (PARTITION BY product_sk ORDER BY snapshot_date ASC) AS prev_price,
        LAG(claimed_original_price) OVER (PARTITION BY product_sk ORDER BY snapshot_date ASC) AS prev_orig,
        LAG(in_stock) OVER (PARTITION BY product_sk ORDER BY snapshot_date ASC) AS prev_in_stock
    FROM staged_prices
),

daily_prices AS (
    SELECT
        product_sk,
        snapshot_date,
        price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        DATE '1900-01-01' AS min_touched_date
    FROM staged_ranked
    WHERE rn_asc = 1
       OR rn_desc = 1
       OR price IS DISTINCT FROM prev_price
       OR claimed_original_price IS DISTINCT FROM prev_orig
       OR in_stock IS DISTINCT FROM prev_in_stock
),
{% endif %}

-- Single window pass to attach next_snapshot_date and separate 1-row SKUs from multi-row SKUs.
daily_with_counts AS MATERIALIZED (
    SELECT
        product_sk,
        snapshot_date,
        LEAD(snapshot_date) OVER (PARTITION BY product_sk ORDER BY snapshot_date ASC) AS next_snapshot_date,
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
        ARRAY_AGG(next_snapshot_date ORDER BY snapshot_date) AS all_next_dates,
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
        WITH intervals AS (
            SELECT
                u.hist_price,
                GREATEST(
                    1,
                    (
                        LEAST(
                            COALESCE((u.next_date - INTERVAL '1 day')::DATE, d.snapshot_date),
                            d.snapshot_date
                        )
                        - GREATEST(u.hist_date, (d.snapshot_date - INTERVAL '59 days')::DATE)
                    ) + 1
                )::BIGINT AS w
            FROM UNNEST(p.all_dates, p.all_next_dates, p.all_prices) AS u(hist_date, next_date, hist_price)
            WHERE u.hist_date <= d.snapshot_date
              AND COALESCE((u.next_date - INTERVAL '1 day')::DATE, d.snapshot_date)
                  >= (d.snapshot_date - INTERVAL '59 days')::DATE
        ),
        ordered AS (
            SELECT
                hist_price,
                SUM(w) OVER (ORDER BY hist_price ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_w,
                SUM(w) OVER () AS total_w
            FROM intervals
        )
        SELECT
            (
                (SELECT hist_price FROM ordered WHERE cum_w >= ((total_w + 1) / 2) ORDER BY cum_w ASC LIMIT 1)
                +
                (SELECT hist_price FROM ordered WHERE cum_w >= ((total_w + 2) / 2) ORDER BY cum_w ASC LIMIT 1)
            ) / 2.0 AS rolling_60d_median
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
