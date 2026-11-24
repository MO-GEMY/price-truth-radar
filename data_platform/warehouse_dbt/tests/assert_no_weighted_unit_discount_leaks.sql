-- Singular dbt data test:
-- Fails if any grocery product in gold.mart_product_verdicts leaks a 1 kg base unit price
-- as `claimed_original_price` for a fractional-weight selling step (e.g. 125g/200g/250g/500g).
--
-- Guards two high-signal patterns:
--   1. Variable-weight GS1 PLU barcodes (`attributes_json ->> 'ean' LIKE '20%'`) claiming >= 50% off.
--   2. Supermarket items (`gourmet`, `seoudi`, `hyperone`, `spinneys`, `metro_market`) whose
--      `claimed_original_price / current_price` hits an exact per-kg fraction multiplier
--      (4x = 250g, 5x = 200g, 6.25x = 160g, 8x = 125g, 10x = 100g), or exact 2x (500g/1kg)
--      when no packaged unit weight/volume is present.

SELECT
    product_sk,
    store_name,
    attributes_json ->> 'ean' AS ean,
    product_title,
    current_price,
    claimed_original_price,
    claimed_discount_pct,
    ROUND(claimed_original_price / NULLIF(current_price, 0), 4) AS orig_to_curr_ratio,
    attributes_json ->> 'net_weight_g' AS net_weight_g,
    variant_label
FROM {{ ref('mart_product_verdicts') }}
WHERE category = 'groceries'
  AND claimed_original_price IS NOT NULL
  AND current_price > 0
  AND claimed_original_price > current_price
  AND (
      -- Rule 1: Variable-weight deli/produce/butcher PLU barcode with impossible >= 50% claimed discount
      (
          COALESCE(attributes_json ->> 'ean', '') LIKE '20%'
          AND claimed_discount_pct >= 50
      )
      -- Rule 2: Exact fractional-kg multiplier leak on Egyptian supermarkets
      OR (
          store_name IN ('gourmet', 'seoudi', 'hyperone', 'spinneys', 'metro_market')
          AND (
              ABS((claimed_original_price / current_price) - 10.0) <= 0.015
              OR ABS((claimed_original_price / current_price) - 8.0) <= 0.015
              OR ABS((claimed_original_price / current_price) - 6.25) <= 0.015
              OR ABS((claimed_original_price / current_price) - 5.0) <= 0.015
              OR ABS((claimed_original_price / current_price) - 4.0) <= 0.015
              OR (
                  ABS((claimed_original_price / current_price) - 2.0) <= 0.005
                  AND NULLIF(TRIM(COALESCE(attributes_json ->> 'net_weight_g', '')), '') IS NULL
                  AND NULLIF(TRIM(COALESCE(attributes_json ->> 'net_volume_ml', '')), '') IS NULL
                  AND COALESCE(NULLIF(TRIM(attributes_json ->> 'pack_count'), ''), '1') = '1'
                  AND LOWER(product_title) NOT LIKE '%1+1%'
                  AND LOWER(product_title) NOT LIKE '%buy 1%'
                  AND LOWER(product_title) !~ '(pack\s+of\s+\d+|\d+\s*(wipes|tissues|sheets|pcs|pieces|pads|rolls))'
              )
          )
      )
  )
