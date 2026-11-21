{% snapshot snp_product_history %}

{{
    config(
        target_schema='silver',
        unique_key='product_sk',
        strategy='check',
        check_cols=[
            'current_price',
            'claimed_original_price',
            'in_stock',
            'available_sizes_count',
        ],
        invalidate_hard_deletes=False,
    )
}}

WITH latest_per_product AS (
    SELECT
        MD5(LOWER(TRIM(store_name)) || '|' || TRIM(external_id))::VARCHAR AS product_sk,
        LOWER(TRIM(store_name))::VARCHAR AS store_name,
        TRIM(external_id)::VARCHAR AS external_id,
        NULLIF(LOWER(TRIM(canonical_product_key)), '')::VARCHAR AS canonical_product_key,
        LOWER(TRIM(category))::VARCHAR AS category,
        LOWER(TRIM(sub_category))::VARCHAR AS sub_category,
        REGEXP_REPLACE(TRIM(brand), '\s+', ' ', 'g')::VARCHAR AS brand,
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
        snapshot_date::DATE AS snapshot_date,
        scraped_at::TIMESTAMP AS scraped_at,
        ROW_NUMBER() OVER (
            PARTITION BY MD5(LOWER(TRIM(store_name)) || '|' || TRIM(external_id))
            ORDER BY snapshot_date DESC, scraped_at DESC
        ) AS rn
    FROM {{ source('raw', 'raw_product_snapshots') }}
    WHERE current_price IS NOT NULL
      AND current_price > 0
)

SELECT
    product_sk,
    store_name,
    external_id,
    canonical_product_key,
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
    snapshot_date,
    scraped_at
FROM latest_per_product
WHERE rn = 1

{% endsnapshot %}
