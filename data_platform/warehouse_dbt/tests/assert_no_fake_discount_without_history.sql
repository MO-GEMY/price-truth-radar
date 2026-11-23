-- Singular dbt data test:
-- Fails if any product in gold.mart_product_verdicts emits a historical verdict
-- (FAKE_DISCOUNT, GENUINE_DEAL, ALL_TIME_LOW, or PRESALE_HIKE) without real
-- historical evidence (fewer than 3 distinct snapshot dates AND no observed
-- price change across >= 2 distinct dates).

WITH history_depth AS (
    SELECT
        product_sk,
        COUNT(DISTINCT snapshot_date)::INTEGER AS days_tracked,
        (MIN(price) <> MAX(price))::BOOLEAN AS has_price_change
    FROM {{ ref('fct_price_history') }}
    GROUP BY product_sk
)

SELECT
    v.product_sk,
    v.store_name,
    v.product_title,
    v.current_price,
    v.claimed_original_price,
    v.discount_verdict,
    COALESCE(h.days_tracked, 1) AS days_tracked,
    COALESCE(h.has_price_change, FALSE) AS has_price_change
FROM {{ ref('mart_product_verdicts') }} v
LEFT JOIN history_depth h
    ON v.product_sk = h.product_sk
WHERE
    v.discount_verdict IN ('FAKE_DISCOUNT', 'GENUINE_DEAL', 'ALL_TIME_LOW', 'PRESALE_HIKE')
    AND COALESCE(h.days_tracked, 1) < 3
    AND NOT COALESCE(h.has_price_change, FALSE)
