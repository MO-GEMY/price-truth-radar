{{
    config(
        schema='gold',
        materialized='table',
        post_hook=[
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_product_sk",
            "CREATE UNIQUE INDEX idx_mart_verdicts_product_sk ON {{ this }} (product_sk)",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_canonical_key",
            "CREATE INDEX idx_mart_verdicts_canonical_key ON {{ this }} (canonical_product_key) WHERE canonical_product_key IS NOT NULL",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_parent_key",
            "CREATE INDEX idx_mart_verdicts_parent_key ON {{ this }} (parent_product_key)",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_search_doc_trgm",
            "CREATE INDEX idx_mart_verdicts_search_doc_trgm ON {{ this }} USING GIN (search_document gin_trgm_ops)",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_title_trgm",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_store_name",
            "CREATE INDEX idx_mart_verdicts_store_name ON {{ this }} (store_name)",
            "DROP INDEX IF EXISTS {{ this.schema }}.idx_mart_verdicts_non_normal_verdict",
            "CREATE INDEX idx_mart_verdicts_non_normal_verdict ON {{ this }} (discount_verdict, category) WHERE discount_verdict <> 'NORMAL_PRICE'"
        ]
    )
}}

-- Evaluate the silver.stg_products view ONCE into a materialized CTE so both
-- latest_staged and variant_conflict_signals share a single scan.
WITH staged_base AS MATERIALIZED (
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
        parent_product_key,
        variant_id,
        variant_label,
        attr_variant_count,
        attr_variant_min_price,
        attr_variant_max_price,
        current_price,
        claimed_original_price,
        in_stock,
        available_sizes_count,
        total_sizes,
        unit_price_egp,
        snapshot_date,
        scraped_at
    FROM {{ ref('stg_products') }}
),

current_products_base AS (
    SELECT DISTINCT ON (product_sk)
        *
    FROM staged_base
    ORDER BY product_sk, snapshot_date DESC, scraped_at DESC
),

-- Compute sibling variant rollup inline via window functions (O(N log N), zero self-join).
current_products AS (
    SELECT
        *,
        COUNT(*) OVER (PARTITION BY store_name, parent_product_key)::INTEGER AS sibling_count,
        MIN(current_price) OVER (PARTITION BY store_name, parent_product_key)::NUMERIC(12,2) AS sibling_min_price,
        MAX(current_price) OVER (PARTITION BY store_name, parent_product_key)::NUMERIC(12,2) AS sibling_max_price,
        (
            ROW_NUMBER() OVER (
                PARTITION BY parent_product_key
                ORDER BY in_stock DESC, current_price ASC, product_sk ASC
            ) = 1
        )::BOOLEAN AS is_primary_variant
    FROM current_products_base
),

-- Detect legacy unsplit variant mixing across historical snapshots of the same product_sk:
-- conflicting variant_id, variant_label, or dimension token (e.g. 120x180 vs 200x300).
variant_conflict_signals AS (
    SELECT
        product_sk,
        (
            COUNT(DISTINCT variant_id) > 1
            OR COUNT(DISTINCT LOWER(TRIM(variant_label))) > 1
            OR COUNT(
                DISTINCT NULLIF(
                    REGEXP_REPLACE(
                        COALESCE(
                            (REGEXP_MATCH(LOWER(product_title), '([0-9]{2,3}\s*[x*×]\s*[0-9]{2,3})'))[1],
                            ''
                        ),
                        '\s+',
                        '',
                        'g'
                    ),
                    ''
                )
            ) > 1
        )::BOOLEAN AS has_variant_label_conflict
    FROM staged_base
    GROUP BY product_sk
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
        cp.external_id,
        cp.category,
        cp.sub_category,
        cp.brand,
        cp.product_title,
        cp.product_url,
        cp.image_url,
        cp.attributes_json,
        cp.parent_product_key,
        cp.variant_id,
        cp.variant_label,
        GREATEST(
            1,
            COALESCE(cp.attr_variant_count, 1),
            COALESCE(cp.sibling_count, 1)
        )::INTEGER AS variant_count,
        (
            GREATEST(
                1,
                COALESCE(cp.attr_variant_count, 1),
                COALESCE(cp.sibling_count, 1)
            ) > 1
        )::BOOLEAN AS has_multiple_variants,
        LEAST(
            cp.current_price,
            COALESCE(cp.attr_variant_min_price, cp.current_price),
            COALESCE(cp.sibling_min_price, cp.current_price)
        )::NUMERIC(12,2) AS min_variant_price,
        GREATEST(
            cp.current_price,
            COALESCE(cp.attr_variant_max_price, cp.current_price),
            COALESCE(cp.sibling_max_price, cp.current_price)
        )::NUMERIC(12,2) AS max_variant_price,
        cp.current_price,
        cp.claimed_original_price,
        COALESCE(hs.rolling_60d_median, cp.current_price)::NUMERIC(12,2) AS rolling_60d_median,
        COALESCE(hs.min_historical_price, cp.current_price)::NUMERIC(12,2) AS min_historical_price,
        COALESCE(hs.max_historical_price, cp.current_price)::NUMERIC(12,2) AS max_historical_price,
        COALESCE(hs.history_days, 1)::INTEGER AS history_days,
        hs.prior_45d_median,
        -- Minimum historical evidence gate:
        -- Require at least 3 distinct snapshot dates OR an observed price change across >= 2 dates
        -- before emitting any historical verdict (FAKE_DISCOUNT, GENUINE_DEAL, ALL_TIME_LOW, PRESALE_HIKE).
        (
            COALESCE(hs.history_days, 1) >= 3
            OR (
                COALESCE(hs.history_days, 1) >= 2
                AND COALESCE(hs.min_historical_price, cp.current_price)
                    <> COALESCE(hs.max_historical_price, cp.current_price)
            )
        )::BOOLEAN AS has_sufficient_history,
        -- Automated variant-mixing anomaly guardrail:
        -- Suppresses false discount verdicts on legacy unsplit multi-variant SKUs exhibiting:
        --   1) Extreme historical price oscillation on the same product_sk (max/min >= 1.8), OR
        --   2) Conflicting variant_id / variant_label / size dimensions across snapshots, OR
        --   3) Legacy unsplit cross-variant strikethrough leak (>= 3.0x claimed/current) in
        --      size-tiered home_furniture / pet_care categories before variant-keyed re-ingestion.
        (
            (
                COALESCE(hs.history_days, 1) >= 2
                AND COALESCE(hs.min_historical_price, cp.current_price) > 0
                AND (
                    COALESCE(hs.max_historical_price, cp.current_price)
                    / NULLIF(COALESCE(hs.min_historical_price, cp.current_price), 0)
                ) >= 1.8
            )
            OR COALESCE(vcs.has_variant_label_conflict, FALSE)
            OR (
                cp.variant_id IS NULL
                AND cp.external_id NOT LIKE '%\_\_v%' ESCAPE '\'
                AND cp.category IN ('home_furniture', 'pet_care')
                AND cp.claimed_original_price IS NOT NULL
                AND cp.current_price > 0
                AND (cp.claimed_original_price / cp.current_price) >= 3.0
            )
        )::BOOLEAN AS variant_anomaly_flag,
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
        cp.unit_price_egp,
        cp.is_primary_variant
    FROM current_products cp
    LEFT JOIN history_stats hs
        ON cp.product_sk = hs.product_sk
    LEFT JOIN variant_conflict_signals vcs
        ON cp.product_sk = vcs.product_sk
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
        WHEN variant_anomaly_flag OR NOT has_sufficient_history
            THEN 'NORMAL_PRICE'
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
    unit_price_egp::NUMERIC(12,2) AS unit_price_egp,
    {{ bilingual_search_document('product_title', 'brand', 'category', 'sub_category', 'store_name', 'canonical_product_key') }}::TEXT AS search_document,
    parent_product_key::VARCHAR AS parent_product_key,
    variant_label::VARCHAR AS variant_label,
    variant_count::INTEGER AS variant_count,
    has_multiple_variants::BOOLEAN AS has_multiple_variants,
    min_variant_price::NUMERIC(12,2) AS min_variant_price,
    max_variant_price::NUMERIC(12,2) AS max_variant_price,
    is_primary_variant::BOOLEAN AS is_primary_variant
FROM metrics
