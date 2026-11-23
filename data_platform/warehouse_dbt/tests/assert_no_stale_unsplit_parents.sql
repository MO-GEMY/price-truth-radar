-- Singular dbt data test:
-- Fails if any parent_product_key in gold.mart_product_verdicts still retains a stale
-- legacy unsplit row (external_id without `__v`) alongside split variant rows (`__v...`).

WITH staged_keys AS (
    SELECT
        product_sk,
        store_name,
        parent_product_key,
        external_id,
        BOOL_OR(external_id LIKE '%\_\_v%' ESCAPE '\') OVER (
            PARTITION BY store_name, parent_product_key
        ) AS parent_has_splits
    FROM (
        SELECT DISTINCT
            product_sk,
            store_name,
            parent_product_key,
            external_id
        FROM {{ ref('stg_products') }}
    ) s
)

SELECT
    v.product_sk,
    v.store_name,
    v.parent_product_key,
    sk.external_id,
    v.product_title
FROM {{ ref('mart_product_verdicts') }} v
INNER JOIN staged_keys sk
    ON v.product_sk = sk.product_sk
WHERE sk.parent_has_splits
  AND sk.external_id NOT LIKE '%\_\_v%' ESCAPE '\'
