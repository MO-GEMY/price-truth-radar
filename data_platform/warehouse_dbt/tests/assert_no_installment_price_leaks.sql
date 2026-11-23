-- Singular dbt data test:
-- Fails if any live product in gold.mart_product_verdicts exhibits an obvious
-- monthly-installment price leak instead of a true cash price:
--   1. Non-accessory flagship phones / laptops / consoles priced below 2,000 EGP.
--   2. Non-accessory major appliances (fridges, washers, ACs, TVs, cookers, dishwashers)
--      priced below 1,500 EGP.
--   3. Big-ticket electronics/appliance titles explicitly advertising monthly
--      installment pricing ("قسط شهري", "تقسيط شهري", "monthly installment", "/mo")
--      while storing a price below 2,500 EGP.

SELECT
    product_sk,
    store_name,
    category,
    sub_category,
    current_price,
    product_title
FROM {{ ref('mart_product_verdicts') }}
WHERE
    (
        category IN ('electronics', 'home_appliances')
        AND (
            product_title ~* '(قسط\s*شهري|تقسيط\s*شهري|شهرياً|monthly\s+installment|/mo\M|per\s+month)'
            AND current_price < 2500
        )
    )
    OR (
        category IN ('electronics', 'home_appliances')
        AND sub_category NOT IN ('accessories', 'playstation_accessories', 'gaming_accessories', 'digital', 'ps5_new_game', 'ps5_used_game')
        AND LOWER(product_title) !~ '(case|cover|cable|charger|charging\s*station|dualsense|adapter|screen|protector|glass|strap|band|stand|holder|mount|remote|filter|bag|backpack|sleeve|mouse|pad|dock|hub|keyboard|earphone|headphone|earbud|speaker|grip|frame|grid|ice pack|ice cube|blade|shaft|pipe|lnb|switch|fan|socket|battery|hose|valve|shelf|drawer|tray|rack|basket|detergent|rinse|liquid|cleaner|brush|cloth|knob|button|hinge|seal|gasket|motor|pump|cap|lid|handle|thermostat|fuse|capacitor|bracket|antenna|splitter|receiver|power bank|card|memory|flash|usb|hdmi|vga|aux|mic|webcam|cooling|cooler|stylus|pen|ring|tripod|selfie|watch|skin|sticker|film|lens|controller|game|disc|voucher|digital|used|pre-?order|diffuser|stabilizer|barrier|pocket|tipper|lamp|mill|jug|radio|cleaning|kit|parts?|spare|لعبة|جراب|كفر|كابل|شاحن|اسكرين|ريموت|فلتر|شنطة|حقيبة|حامل|مروحة|قطعة غيار|قاعدة|سماعة|بطارية|شفاط|مصفاة|طبق|رف|درج|منظف|سائل|خرطوم|مقبض|غلاف|لاصق|مفرش|كيس)'
        AND (
            (
                LOWER(product_title) ~ '(iphone 1[2-7]|galaxy s2[2-6]|macbook (air|pro)|playstation 5|ps5 console|xbox series [xs])'
                AND current_price < 2000
            )
            OR (
                sub_category IN ('refrigerators', 'washing_machines', 'air_conditioners', 'cookers', 'dishwashers', 'deep_freezers')
                AND LOWER(product_title) ~ '(no frost|inverter|front load|top load|split air conditioner|ثلاجة|غسالة|تكييف|بوتاجاز|ديب فريزر)'
                AND current_price < 1500
            )
        )
    )
