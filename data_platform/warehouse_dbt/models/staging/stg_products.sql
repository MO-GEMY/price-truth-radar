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
    snapshot_date,
    scraped_at
FROM cleaned
WHERE rn = 1
