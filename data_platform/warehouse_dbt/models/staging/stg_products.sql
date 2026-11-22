{{
    config(
        schema='silver',
        materialized='view'
    )
}}

WITH cleaned AS (
    SELECT
        MD5(LOWER(TRIM(store_name)) || '|' || TRIM(external_id))::VARCHAR AS product_sk,
        NULLIF(LOWER(TRIM(canonical_product_key)), '')::VARCHAR AS canonical_product_key,
        LOWER(TRIM(store_name))::VARCHAR AS store_name,
        TRIM(external_id)::VARCHAR AS external_id,
        LOWER(TRIM(category))::VARCHAR AS category,
        LOWER(TRIM(sub_category))::VARCHAR AS sub_category,
        CASE UPPER(TRIM(brand))
            WHEN 'LG' THEN 'LG'
            WHEN 'HP' THEN 'HP'
            WHEN 'ASUS' THEN 'ASUS'
            WHEN 'MSI' THEN 'MSI'
            WHEN 'AOC' THEN 'AOC'
            WHEN 'OPPO' THEN 'OPPO'
            WHEN 'URBAN EG' THEN 'Urban EG'
            ELSE REGEXP_REPLACE(TRIM(brand), '\s+', ' ', 'g')
        END::VARCHAR AS brand,
        REGEXP_REPLACE(TRIM(product_title), '\s+', ' ', 'g')::TEXT AS product_title,
        TRIM(product_url)::TEXT AS product_url,
        NULLIF(TRIM(image_url), '')::TEXT AS image_url,
        attributes_json::JSONB AS attributes_json,
        current_price::NUMERIC(12,2) AS current_price,
        CASE
            WHEN claimed_original_price IS NOT NULL
                 AND claimed_original_price > current_price
                THEN claimed_original_price::NUMERIC(12,2)
            ELSE NULL::NUMERIC(12,2)
        END AS claimed_original_price,
        COALESCE(in_stock, FALSE)::BOOLEAN AS in_stock,
        CASE
            WHEN LOWER(TRIM(category)) = 'fashion'
                 AND jsonb_typeof(attributes_json::JSONB -> 'available_sizes') = 'array'
                THEN jsonb_array_length(attributes_json::JSONB -> 'available_sizes')::INTEGER
            ELSE NULL::INTEGER
        END AS available_sizes_count,
        CASE
            WHEN LOWER(TRIM(category)) = 'fashion'
                 AND (attributes_json::JSONB ->> 'total_sizes') IS NOT NULL
                THEN (attributes_json::JSONB ->> 'total_sizes')::INTEGER
            ELSE NULL::INTEGER
        END AS total_sizes,
        CASE
            WHEN (attributes_json::JSONB ->> 'net_weight_g') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'net_weight_g')::INTEGER > 0
                THEN (attributes_json::JSONB ->> 'net_weight_g')::INTEGER
            ELSE NULL::INTEGER
        END AS net_weight_g,
        CASE
            WHEN (attributes_json::JSONB ->> 'net_volume_ml') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'net_volume_ml')::INTEGER > 0
                THEN (attributes_json::JSONB ->> 'net_volume_ml')::INTEGER
            ELSE NULL::INTEGER
        END AS net_volume_ml,
        CASE
            WHEN (attributes_json::JSONB ->> 'pack_count') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'pack_count')::INTEGER > 0
                THEN (attributes_json::JSONB ->> 'pack_count')::INTEGER
            ELSE 1::INTEGER
        END AS pack_count,
        NULLIF(TRIM(attributes_json::JSONB ->> 'pack_size'), '')::VARCHAR AS pack_size,
        NULLIF(
            REGEXP_REPLACE(
                COALESCE(
                    attributes_json::JSONB ->> 'ean',
                    attributes_json::JSONB ->> 'gtin',
                    ''
                ),
                '[^0-9]',
                '',
                'g'
            ),
            ''
        )::VARCHAR AS ean,
        CASE
            WHEN (attributes_json::JSONB ->> 'net_weight_g') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'net_weight_g')::INTEGER > 0
                THEN ROUND(
                    (current_price::NUMERIC * 1000.0)
                    / (attributes_json::JSONB ->> 'net_weight_g')::NUMERIC,
                    2
                )::NUMERIC(12,2)
            WHEN (attributes_json::JSONB ->> 'net_volume_ml') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'net_volume_ml')::INTEGER > 0
                THEN ROUND(
                    (current_price::NUMERIC * 1000.0)
                    / (attributes_json::JSONB ->> 'net_volume_ml')::NUMERIC,
                    2
                )::NUMERIC(12,2)
            ELSE NULL::NUMERIC(12,2)
        END AS unit_price_egp,
        snapshot_date::DATE AS snapshot_date,
        scraped_at::TIMESTAMP AS scraped_at,
        ROW_NUMBER() OVER (
            PARTITION BY MD5(LOWER(TRIM(store_name)) || '|' || TRIM(external_id)), snapshot_date::DATE
            ORDER BY scraped_at DESC
        ) AS rn
    FROM {{ source('raw', 'raw_product_snapshots') }}
    WHERE current_price IS NOT NULL
      AND current_price > 0
)

SELECT
    product_sk,
    canonical_product_key,
    store_name,
    external_id,
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
    net_weight_g,
    net_volume_ml,
    pack_count,
    pack_size,
    ean,
    unit_price_egp,
    snapshot_date,
    scraped_at
FROM cleaned
WHERE rn = 1
