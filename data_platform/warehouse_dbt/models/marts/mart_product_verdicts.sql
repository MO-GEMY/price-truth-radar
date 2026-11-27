{{
    config(
        schema='gold',
        materialized='incremental',
        unique_key='product_sk',
        incremental_strategy='delete+insert',
        on_schema_change='sync_all_columns',
        post_hook=[
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mart_verdicts_product_sk ON {{ this }} (product_sk)",
            "CREATE INDEX IF NOT EXISTS idx_mart_verdicts_canonical_key ON {{ this }} (canonical_product_key) WHERE canonical_product_key IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_mart_verdicts_parent_key ON {{ this }} (parent_product_key) WHERE has_multiple_variants = TRUE",
            "CREATE INDEX IF NOT EXISTS idx_mart_verdicts_search_doc_trgm ON {{ this }} USING GIN (search_document gin_trgm_ops)",
            "CREATE INDEX IF NOT EXISTS idx_mart_verdicts_store_name ON {{ this }} (store_name)",
            "DROP INDEX IF EXISTS gold.idx_mart_verdicts_non_normal_verdict",
            "CREATE INDEX IF NOT EXISTS idx_mart_verdicts_actionable_verdict ON {{ this }} (discount_verdict, category) WHERE discount_verdict NOT IN ('NORMAL_PRICE', 'NEWLY_TRACKED')",
            "DELETE FROM {{ this }} v WHERE (v.last_updated_at < (NOW() AT TIME ZONE 'UTC') - INTERVAL '45 days' OR (v.in_stock = FALSE AND COALESCE((SELECT MAX(h.snapshot_date) FROM {{ ref('fct_price_history') }} h WHERE h.product_sk = v.product_sk), v.last_updated_at::DATE) < (CURRENT_DATE - INTERVAL '45 days')::DATE)) AND NOT EXISTS (SELECT 1 FROM public.price_alerts pa WHERE pa.product_key = v.product_sk AND pa.is_active = TRUE)"
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

current_products_all AS (
    SELECT DISTINCT ON (product_sk)
        *
    FROM staged_base
    ORDER BY product_sk, snapshot_date DESC, scraped_at DESC
),

-- Never re-ingest brand-new archived out-of-stock unmatched SKUs into the serving catalog.
-- Preserves 100% of:
--   1. In-stock products (`in_stock = TRUE`)
--   2. Cross-store matched products (`canonical_product_key IS NOT NULL`)
--   3. Already-tracked serving catalog rows (during incremental runs)
--   4. Products ever observed in stock in `gold.fct_price_history`
current_products_eligible AS (
    SELECT cp.*
    FROM current_products_all cp
    {% if is_incremental() %}
    LEFT JOIN {{ this }} existing
        ON existing.product_sk = cp.product_sk
    {% endif %}
    WHERE cp.in_stock = TRUE
       OR cp.canonical_product_key IS NOT NULL
       {% if is_incremental() %}
       OR existing.product_sk IS NOT NULL
       {% endif %}
       OR EXISTS (
           SELECT 1
           FROM {{ ref('fct_price_history') }} h
           WHERE h.product_sk = cp.product_sk
             AND h.in_stock = TRUE
       )
),

{% if is_incremental() %}
-- Detect SKUs with new snapshots, price/stock/title changes, or changed canonical_product_key,
-- then expand to sibling SKUs sharing the same parent_product_key so sibling variant rollups
-- (`sibling_count`, `min/max_variant_price`, `is_primary_variant`) stay 100% consistent.
changed_parents AS MATERIALIZED (
    SELECT DISTINCT cp.parent_product_key
    FROM current_products_eligible cp
    LEFT JOIN {{ this }} t
        ON t.product_sk = cp.product_sk
    WHERE t.product_sk IS NULL
       OR cp.scraped_at > t.last_updated_at
       OR cp.canonical_product_key IS DISTINCT FROM t.canonical_product_key
       OR cp.sub_category IS DISTINCT FROM t.sub_category
       OR cp.current_price IS DISTINCT FROM t.current_price
       OR cp.claimed_original_price IS DISTINCT FROM t.claimed_original_price
       OR cp.in_stock IS DISTINCT FROM t.in_stock
       OR cp.product_title IS DISTINCT FROM t.product_title
),

current_products_base AS MATERIALIZED (
    SELECT cp.*
    FROM current_products_eligible cp
    INNER JOIN changed_parents ap
        ON cp.parent_product_key = ap.parent_product_key
),
{% else %}
current_products_base AS (
    SELECT *
    FROM current_products_eligible
),
{% endif %}

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
        sb.product_sk,
        (
            COUNT(DISTINCT sb.variant_id) > 1
            OR COUNT(DISTINCT LOWER(TRIM(sb.variant_label))) > 1
            OR COUNT(
                DISTINCT NULLIF(
                    REGEXP_REPLACE(
                        COALESCE(
                            (REGEXP_MATCH(LOWER(sb.product_title), '([0-9]{2,3}\s*[x*×]\s*[0-9]{2,3})'))[1],
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
    FROM staged_base sb
    {% if is_incremental() %}
    INNER JOIN current_products_base cp
        ON sb.product_sk = cp.product_sk
    {% endif %}
    GROUP BY sb.product_sk
),

product_latest_dates AS (
    SELECT
        h.product_sk,
        MAX(h.snapshot_date) AS latest_date
    FROM {{ ref('fct_price_history') }} h
    {% if is_incremental() %}
    INNER JOIN current_products_base cp
        ON h.product_sk = cp.product_sk
    {% endif %}
    GROUP BY h.product_sk
),

history_stats AS (
    SELECT
        h.product_sk,
        COUNT(DISTINCT h.snapshot_date)::INTEGER AS history_days,
        MIN(h.snapshot_date)::DATE AS first_seen_date,
        MAX(h.snapshot_date)::DATE AS latest_hist_date,
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

metrics_base AS (
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
        LEAST(
            COALESCE(hs.first_seen_date, cp.snapshot_date),
            cp.snapshot_date
        )::DATE AS first_seen_date,
        GREATEST(
            COALESCE(hs.history_days, 1),
            (
                GREATEST(cp.snapshot_date, COALESCE(hs.latest_hist_date, cp.snapshot_date))
                - LEAST(COALESCE(hs.first_seen_date, cp.snapshot_date), cp.snapshot_date)
            ) + 1
        )::INTEGER AS tracked_days_count,
        hs.prior_45d_median,
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
),

metrics AS (
    SELECT
        mb.*,
        CASE
            WHEN mb.tracked_days_count < 7 THEN 'EARLY'
            WHEN mb.tracked_days_count < 60 THEN 'GROWING'
            ELSE 'MATURE'
        END::VARCHAR AS history_maturity,
        -- Cold-start honesty: NEVER expose a verified historical median or historical
        -- real_discount_pct when tracked_days_count < 7 (EARLY maturity).
        CASE
            WHEN mb.tracked_days_count >= 7 THEN mb.rolling_60d_median
            ELSE NULL::NUMERIC(12,2)
        END AS verified_historical_median,
        CASE
            WHEN mb.tracked_days_count >= 7 AND mb.rolling_60d_median > 0
                THEN GREATEST(
                    -999.99,
                    LEAST(
                        999.99,
                        ROUND(
                            ((mb.rolling_60d_median - mb.current_price) / mb.rolling_60d_median) * 100.0,
                            2
                        )
                    )
                )::NUMERIC(5,2)
            ELSE 0.00::NUMERIC(5,2)
        END AS real_discount_pct
    FROM metrics_base mb
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
    -- Compact serving attributes_json: store ONLY UI/API/test keys and NULL instead of '{}'
    -- when empty (promoted variant columns & store breadcrumbs are never duplicated here).
    NULLIF(
        jsonb_strip_nulls(
            jsonb_build_object(
                'available_sizes', CASE WHEN category = 'fashion' THEN attributes_json -> 'available_sizes' END,
                'total_sizes', CASE WHEN category = 'fashion' THEN attributes_json -> 'total_sizes' END,
                'pack_size', attributes_json -> 'pack_size',
                'net_weight_g', attributes_json -> 'net_weight_g',
                'net_volume_ml', attributes_json -> 'net_volume_ml',
                'pack_count', CASE
                    WHEN (attributes_json ->> 'pack_count') ~ '^[0-9]+$'
                         AND (attributes_json ->> 'pack_count')::INTEGER > 1
                    THEN attributes_json -> 'pack_count'
                END,
                'ean', CASE WHEN category = 'groceries' THEN attributes_json -> 'ean' END,
                'ram_gb', attributes_json -> 'ram_gb',
                'storage_gb', attributes_json -> 'storage_gb',
                'screen_size_inch', attributes_json -> 'screen_size_inch',
                'screen_inches', attributes_json -> 'screen_inches',
                'refresh_hz', attributes_json -> 'refresh_hz',
                'refresh_rate_hz', attributes_json -> 'refresh_rate_hz',
                'panel', attributes_json -> 'panel',
                'anc', attributes_json -> 'anc',
                'battery_hours', attributes_json -> 'battery_hours',
                'warranty', attributes_json -> 'warranty',
                'is_estimated_price', CASE
                    WHEN COALESCE((attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE)
                    THEN to_jsonb(TRUE)
                END,
                'source_currency', attributes_json -> 'source_currency',
                'source_price', attributes_json -> 'source_price'
            )
        ),
        '{}'::jsonb
    )::JSONB AS attributes_json,
    current_price::NUMERIC(12,2) AS current_price,
    claimed_original_price::NUMERIC(12,2) AS claimed_original_price,
    rolling_60d_median::NUMERIC(12,2) AS rolling_60d_median,
    min_historical_price::NUMERIC(12,2) AS min_historical_price,
    max_historical_price::NUMERIC(12,2) AS max_historical_price,
    claimed_discount_pct::NUMERIC(5,2) AS claimed_discount_pct,
    real_discount_pct::NUMERIC(5,2) AS real_discount_pct,
    CASE
        WHEN variant_anomaly_flag THEN
            CASE WHEN tracked_days_count < 7 THEN 'NEWLY_TRACKED' ELSE 'NORMAL_PRICE' END
        WHEN tracked_days_count < 7 THEN
            CASE
                WHEN history_days >= 2
                     AND max_historical_price > 0
                     AND current_price < max_historical_price
                     AND ((max_historical_price - current_price) / max_historical_price) * 100.0 >= 5.0
                    THEN 'RECENT_DROP'
                WHEN history_days >= 2
                     AND min_historical_price > 0
                     AND current_price > min_historical_price
                     AND ((current_price - min_historical_price) / min_historical_price) * 100.0 >= 8.0
                    THEN 'RECENT_HIKE'
                ELSE 'NEWLY_TRACKED'
            END
        WHEN claimed_discount_pct >= 10 AND real_discount_pct < 3
            THEN 'FAKE_DISCOUNT'
        WHEN current_price <= min_historical_price
             AND tracked_days_count >= 14
             AND real_discount_pct >= 5
            THEN 'ALL_TIME_LOW'
        WHEN real_discount_pct >= 10
            THEN 'GENUINE_DEAL'
        WHEN (
            prior_45d_median IS NOT NULL
            AND prior_45d_median > 0
            AND ((current_price - prior_45d_median) / prior_45d_median) * 100.0 >= 12
        ) OR (
            prior_45d_median IS NULL
            AND verified_historical_median IS NOT NULL
            AND verified_historical_median > 0
            AND history_days >= 2
            AND ((current_price - verified_historical_median) / verified_historical_median) * 100.0 >= 12
        )
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
    is_primary_variant::BOOLEAN AS is_primary_variant,
    first_seen_date::DATE AS first_seen_date,
    tracked_days_count::INTEGER AS tracked_days_count,
    history_maturity::VARCHAR AS history_maturity,
    verified_historical_median::NUMERIC(12,2) AS verified_historical_median,
    COALESCE((attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE)::BOOLEAN AS is_estimated_price,
    NULLIF(UPPER(TRIM(attributes_json ->> 'source_currency')), '')::VARCHAR AS source_currency,
    CASE
        WHEN (attributes_json ->> 'source_price') ~ '^[0-9]+(\.[0-9]+)?$'
        THEN (attributes_json ->> 'source_price')::NUMERIC(12,2)
    END AS source_price,
    CASE
        WHEN COALESCE((attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE)
        THEN ROUND(
            current_price * COALESCE(
                (
                    SELECT LEAST(1.45, GREATEST(1.00,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY loc.current_price / NULLIF(metrics.current_price, 0)
                        )::NUMERIC
                    ))
                    FROM {{ ref('stg_products') }} loc
                    WHERE loc.canonical_product_key IS NOT NULL
                      AND LOWER(loc.brand) = LOWER(metrics.brand)
                      AND COALESCE((loc.attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE) = FALSE
                      AND loc.in_stock = TRUE
                      AND loc.current_price > 0
                ),
                1.15
            ),
            2
        )::NUMERIC(12,2)
    END AS estimated_egp_price,
    COALESCE(
        (
            SELECT COUNT(DISTINCT loc.store_name)::INTEGER
            FROM {{ ref('stg_products') }} loc
            WHERE metrics.canonical_product_key IS NOT NULL
              AND loc.canonical_product_key = metrics.canonical_product_key
              AND COALESCE((loc.attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE) = FALSE
              AND loc.in_stock = TRUE
        ),
        0
    )::INTEGER AS local_sellers_count,
    (
        SELECT MIN(loc.current_price)::NUMERIC(12,2)
        FROM {{ ref('stg_products') }} loc
        WHERE metrics.canonical_product_key IS NOT NULL
          AND loc.canonical_product_key = metrics.canonical_product_key
          AND COALESCE((loc.attributes_json ->> 'is_estimated_price')::BOOLEAN, FALSE) = FALSE
          AND loc.in_stock = TRUE
    ) AS local_min_price_egp
FROM metrics
