-- Singular dbt data test (Cold-Start Honesty):
-- Fails if ANY product in gold.mart_product_verdicts with tracked_days_count < 7
-- (history_maturity = 'EARLY') emits a historical median verdict
-- (FAKE_DISCOUNT, GENUINE_DEAL, ALL_TIME_LOW, or PRESALE_HIKE) OR exposes a
-- non-null verified_historical_median / non-zero historical real_discount_pct.

SELECT
    v.product_sk,
    v.store_name,
    v.product_title,
    v.current_price,
    v.claimed_original_price,
    v.discount_verdict,
    v.tracked_days_count,
    v.history_maturity,
    v.verified_historical_median,
    v.real_discount_pct
FROM {{ ref('mart_product_verdicts') }} v
WHERE
    (
        v.tracked_days_count < 7
        OR v.history_maturity = 'EARLY'
    )
    AND (
        v.discount_verdict IN ('FAKE_DISCOUNT', 'GENUINE_DEAL', 'ALL_TIME_LOW', 'PRESALE_HIKE')
        OR v.verified_historical_median IS NOT NULL
        OR v.real_discount_pct <> 0
    )
