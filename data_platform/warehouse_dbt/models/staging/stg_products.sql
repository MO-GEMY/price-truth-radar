{{
    config(
        schema='silver',
        materialized='view'
    )
}}

{% set home_furniture_stores = [
    'hub_furniture', 'kabbani', 'chichomz', 'ariika', 'el_malek_furniture',
    'bed_janssen', 'family_bed', 'habitat_eg', 'janssen_stores', 'manzzeli', 'mffco',
    'bednhome', 'elbadrawi_home', 'grand_style', 'heba_linens', 'nile_home', 'smart_furniture',
    'elzenouki', 'elzenouki_cookware', 'neoflam_eg', 'nouval_eg', 'zinox_elzenouki',
    'ikea_eg', 'homzmart', 'efreshli', 'in_and_out', 'mobica', 'taki_eg',
    'linen_house_eg', 'oriental_weavers', 'rich_home', 'zahran_stores'
] %}

{% set beauty_stores = [
    'bashrety', 'biostream', 'bless_eg', 'bobana', 'braes_eg', 'catwa_store',
    'cybele_eg', 'dermaelle', 'diwan_fragrances', 'eparkville', 'eva_cosmetics',
    'hayah_labs', 'infinity_clinic', 'malak_eg', 'melano_pharma', 'mood_eg',
    'mood_fragrances', 'neuth_eg', 'norshek', 'raw_african', 'soul_and_more',
    'source_beauty', 'the_hair_addict', 'zynah',
    'faces_eg', 'mazaya_eg', 'amanda_milano', 'telofill_eg', 'cleo_labs'
] %}

{% set home_appliances_stores = [
    'ehab_center', 'kaufen_eg', 'elalfy_eg', 'sokany_eg', 'unionaire_eg', 'zanussi_eg'
] %}

{% set health_stores = [
    'beseha', 'bloom_pharmacy', 'egysupps', 'house_of_supplements', 'ifit_eg',
    'limitless_naturals', 'max_muscle_eg', 'nowfoods_eg', 'organic_nation',
    'el_ezaby', 'seif_pharmacies', 'misr_pharmacies', 'roshdy_pharmacies',
    'delmar_attalla', 'fouda_pharmacy', 'tarshouby', 'chefaa', 'yodawy',
    'soukare_eg', 'tdawi', 'super_supplements',
    'gofit_eg', 'mfsupps_eg', 'powerstore_eg', 'mr_vitamins_eg', 'protein_house_eg'
] %}

{% set sports_stores = [
    'alnasser_eg', 'athlete_home', 'entercise', 'gosport_eg',
    'intersport_eg', 'union_sport', 'wayup_sports', 'decathlon_eg', 'puma_eg'
] %}

{% set pet_care_stores = [
    'happet', 'amin_pet_shop', 'pets_egypt', 'egypuppy'
] %}

{% set baby_kids_stores = [
    'eftekassat', 'kassem_store', 'le3ab_store', 'ourkids_eg',
    'bingo_toys', 'hedeya', 'diwan_books', 'samir_and_aly',
    'bernasos', 'shorouk_books'
] %}

WITH normalized_source AS (
    SELECT
        MD5(LOWER(TRIM(store_name)) || '|' || TRIM(external_id))::VARCHAR AS product_sk,
        NULLIF(LOWER(TRIM(canonical_product_key)), '')::VARCHAR AS canonical_product_key,
        LOWER(TRIM(store_name))::VARCHAR AS store_name,
        TRIM(external_id)::VARCHAR AS external_id,
        -- Reclassify single-vertical specialty stores into their true canonical top-level
        -- category so existing Neon snapshots immediately move out of legacy 4-category buckets.
        CASE
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ pet_care_stores | join("', '") ~ "'" }})
                THEN 'pet_care'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ beauty_stores | join("', '") ~ "'" }})
                THEN 'beauty'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ home_appliances_stores | join("', '") ~ "'" }})
                THEN 'home_appliances'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ home_furniture_stores | join("', '") ~ "'" }})
                THEN 'home_furniture'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ health_stores | join("', '") ~ "'" }})
                THEN 'health'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ sports_stores | join("', '") ~ "'" }})
                THEN 'sports'
            WHEN LOWER(TRIM(store_name)) IN ({{ "'" ~ baby_kids_stores | join("', '") ~ "'" }})
                THEN 'baby_kids'
            WHEN LOWER(TRIM(category)) = 'kitchen' THEN 'home_furniture'
            WHEN LOWER(TRIM(category)) = 'pharmacy' THEN 'health'
            WHEN LOWER(TRIM(category)) IN ('optics', 'watches', 'lifestyle') THEN 'fashion'
            WHEN LOWER(TRIM(category)) = 'books' THEN 'baby_kids'
            WHEN LOWER(TRIM(category)) IN (
                'electronics', 'home_appliances', 'home_furniture', 'fashion',
                'beauty', 'groceries', 'health', 'sports', 'pet_care', 'baby_kids'
            ) THEN LOWER(TRIM(category))
            ELSE 'electronics'
        END::VARCHAR AS norm_category,
        LOWER(TRIM(sub_category))::VARCHAR AS raw_sub_category,
        brand,
        product_title,
        product_url,
        image_url,
        attributes_json,
        current_price,
        claimed_original_price,
        in_stock,
        snapshot_date,
        scraped_at
    FROM {{ source('raw', 'raw_product_snapshots') }}
    WHERE current_price IS NOT NULL
      AND current_price > 0
),

cleaned AS (
    SELECT
        product_sk,
        canonical_product_key,
        store_name,
        external_id,
        norm_category AS category,
        -- Clean up legacy squeezed sub-category labels (e.g. pet_care/health items stamped
        -- with grocery 'canned_sauces' / 'canned_goods', or beauty/furniture stamped 'apparel'/'accessories').
        CASE
            WHEN norm_category = 'pet_care'
                 AND raw_sub_category IN (
                     'canned_sauces', 'canned_goods', 'oils_ghee', 'rice_pasta',
                     'dairy_cheese', 'tea_coffee', 'beverages', 'detergents', 'other', 'accessories'
                 )
                THEN CASE
                    WHEN LOWER(product_title) ~ '(litter|رمل)' THEN 'cat_litter'
                    WHEN LOWER(product_title) ~ '(cat|kitten|feline|قطط|قط)' THEN 'cat_food'
                    WHEN LOWER(product_title) ~ '(dog|puppy|canine|كلاب|كلب)' THEN 'dog_food'
                    WHEN LOWER(product_title) ~ '(treat|snack|biscuit|مكافآت)' THEN 'pet_treats'
                    WHEN LOWER(product_title) ~ '(collar|leash|bowl|bed|toy|carrier|shampoo|brush)' THEN 'pet_accessories'
                    ELSE 'pet_supplies'
                END
            WHEN norm_category = 'health'
                 AND raw_sub_category IN (
                     'canned_sauces', 'canned_goods', 'oils_ghee', 'rice_pasta',
                     'dairy_cheese', 'tea_coffee', 'beverages', 'detergents', 'other', 'accessories'
                 )
                THEN CASE
                    WHEN LOWER(product_title) ~ '(protein|whey|creatine|bcaa|pre-?workout|amino|gainer|بروتين|كرياتين)' THEN 'sports_nutrition'
                    WHEN LOWER(product_title) ~ '(vitamin|magnesium|zinc|omega|ashwagandha|collagen|probiotic|iron|فيتامين)' THEN 'vitamins'
                    WHEN LOWER(product_title) ~ '(pharmacy|medical|wash|cream|gel|spray|drop|powder)' THEN 'pharmacy'
                    ELSE 'supplements'
                END
            WHEN norm_category = 'beauty'
                 AND raw_sub_category IN (
                     'apparel', 'clothing', 'accessories', 'canned_sauces', 'canned_goods', 'other'
                 )
                THEN CASE
                    WHEN LOWER(product_title) ~ '(perfume|parfum|eau de|fragrance|splash|mist|oud|musk|عطر|برفيوم)' THEN 'perfumes'
                    WHEN LOWER(product_title) ~ '(shampoo|conditioner|hair|scalp|henna|keratin|curl|شعر|شامبو)' THEN 'haircare'
                    WHEN LOWER(product_title) ~ '(lipstick|lip |mascara|blush|foundation|concealer|eyeliner|powder|makeup|palette|مكياج)' THEN 'makeup'
                    WHEN LOWER(product_title) ~ '(sunscreen|sunblock|spf|sun shield|واقي شمس)' THEN 'sunscreen'
                    WHEN LOWER(product_title) ~ '(body wash|body butter|lotion|deodorant|soap|shower|جسم)' THEN 'body_care'
                    ELSE 'skincare'
                END
            WHEN norm_category = 'home_furniture'
                 AND raw_sub_category IN ('accessories', 'other', 'kitchen_appliances')
                THEN CASE
                    WHEN LOWER(product_title) ~ '(mattress|مرتبة|مرتبه|سوست)' THEN 'mattresses'
                    WHEN LOWER(product_title) ~ '(sheet|pillow|duvet|bedspread|comforter|towel|linen|bedding|ملاية|مخدة|لحاف|فوط)' THEN 'bedding_linens'
                    WHEN LOWER(product_title) ~ '(cookware|pot|pan|frying|granite|stainless|حلة|طقم حلل|مقلاة|طاسة)' THEN 'cookware'
                    WHEN LOWER(product_title) ~ '(sofa|couch|sectional|كنبة|انتريه|ركنة)' THEN 'sofas'
                    WHEN LOWER(product_title) ~ '(bed|bedroom|wardrobe|سرير|نوم|دولاب)' THEN 'beds'
                    WHEN LOWER(product_title) ~ '(table|desk|dining|ترابيزة|مكتب|سفرة)' THEN 'tables'
                    WHEN LOWER(product_title) ~ '(chair|stool|bean bag|pouf|كرسي)' THEN 'chairs'
                    WHEN LOWER(product_title) ~ '(lamp|light|chandelier|إضاءة|اضاءة|نجفة)' THEN 'lighting'
                    ELSE 'furniture'
                END
            WHEN norm_category = 'sports'
                 AND raw_sub_category IN ('apparel', 'clothing', 'accessories', 'other')
                THEN CASE
                    WHEN LOWER(product_title) ~ '(treadmill|bike|elliptical|dumbbell|barbell|weight|bench|kettlebell|gym|مشاية|عجلة)' THEN 'fitness_equipment'
                    WHEN LOWER(product_title) ~ '(boxing|punching|mma|gloves|ملاكمة)' THEN 'combat_sports'
                    WHEN LOWER(product_title) ~ '(shoe|sneaker|running|cleat|boot|حذاء)' THEN 'sports_shoes'
                    WHEN LOWER(product_title) ~ '(short|shirt|jersey|legging|hoodie|sock|tracksuit|top|jacket)' THEN 'sportswear'
                    ELSE 'sports_gear'
                END
            WHEN norm_category = 'baby_kids'
                 AND raw_sub_category IN ('apparel', 'clothing', 'accessories', 'other')
                THEN CASE
                    WHEN LOWER(product_title) ~ '(puzzle|toy|lego|doll|game|plush|لعبة|ألعاب|العاب)' THEN 'toys'
                    WHEN LOWER(product_title) ~ '(stroller|car seat|crib|cot|high chair|walker|swaddle|blanket)' THEN 'baby_gear'
                    WHEN LOWER(product_title) ~ '(desk|bed|bunk|room|furniture|kids bundle)' THEN 'kids_furniture'
                    ELSE 'kids'
                END
            ELSE raw_sub_category
        END::VARCHAR AS sub_category,
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
        COALESCE(
            NULLIF(TRIM(attributes_json::JSONB ->> 'parent_product_key'), ''),
            store_name || '::' || REGEXP_REPLACE(external_id, '__v.*$', '')
        )::VARCHAR AS parent_product_key,
        NULLIF(TRIM(attributes_json::JSONB ->> 'variant_id'), '')::VARCHAR AS variant_id,
        NULLIF(TRIM(attributes_json::JSONB ->> 'variant_label'), '')::VARCHAR AS variant_label,
        CASE
            WHEN (attributes_json::JSONB ->> 'variant_count') ~ '^[0-9]+$'
                 AND (attributes_json::JSONB ->> 'variant_count')::INTEGER > 0
                THEN (attributes_json::JSONB ->> 'variant_count')::INTEGER
            ELSE NULL::INTEGER
        END AS attr_variant_count,
        CASE
            WHEN (attributes_json::JSONB ->> 'variant_min_price') ~ '^[0-9]+(\.[0-9]+)?$'
                 AND (attributes_json::JSONB ->> 'variant_min_price')::NUMERIC > 0
                THEN (attributes_json::JSONB ->> 'variant_min_price')::NUMERIC(12,2)
            ELSE NULL::NUMERIC(12,2)
        END AS attr_variant_min_price,
        CASE
            WHEN (attributes_json::JSONB ->> 'variant_max_price') ~ '^[0-9]+(\.[0-9]+)?$'
                 AND (attributes_json::JSONB ->> 'variant_max_price')::NUMERIC > 0
                THEN (attributes_json::JSONB ->> 'variant_max_price')::NUMERIC(12,2)
            ELSE NULL::NUMERIC(12,2)
        END AS attr_variant_max_price,
        current_price::NUMERIC(12,2) AS current_price,
        CASE
            WHEN claimed_original_price IS NOT NULL
                 AND claimed_original_price > current_price
                THEN claimed_original_price::NUMERIC(12,2)
            ELSE NULL::NUMERIC(12,2)
        END AS claimed_original_price,
        COALESCE(in_stock, FALSE)::BOOLEAN AS in_stock,
        CASE
            WHEN norm_category = 'fashion'
                 AND jsonb_typeof(attributes_json::JSONB -> 'available_sizes') = 'array'
                THEN jsonb_array_length(attributes_json::JSONB -> 'available_sizes')::INTEGER
            ELSE NULL::INTEGER
        END AS available_sizes_count,
        CASE
            WHEN norm_category = 'fashion'
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
        scraped_at::TIMESTAMP AS scraped_at
    FROM normalized_source
),

-- Deduplicate to latest scrape per (product_sk, snapshot_date) using DISTINCT ON
-- so PostgreSQL keeps accurate row-count estimates (avoiding ROW_NUMBER() rn=1 underestimates
-- that trigger O(N^2) nested-loop joins in downstream marts).
deduped AS (
    SELECT DISTINCT ON (product_sk, snapshot_date)
        *
    FROM cleaned
    ORDER BY product_sk, snapshot_date, scraped_at DESC
),

-- Single-pass O(N log N) window check: if any split variant row (`external_id` containing `__v`)
-- exists for a `(store_name, parent_product_key)`, suppress older pre-split legacy rows for that
-- same parent without a correlated EXISTS or self-join.
with_split_flag AS (
    SELECT
        *,
        BOOL_OR(external_id LIKE '%\_\_v%' ESCAPE '\') OVER (
            PARTITION BY store_name, parent_product_key
        ) AS parent_has_split_variants
    FROM deduped
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
    net_weight_g,
    net_volume_ml,
    pack_count,
    pack_size,
    ean,
    unit_price_egp,
    snapshot_date,
    scraped_at
FROM with_split_flag
WHERE NOT (
    parent_has_split_variants
    AND external_id NOT LIKE '%\_\_v%' ESCAPE '\'
)
