{% macro bilingual_search_document(title_col, brand_col, category_col, sub_category_col, store_col, canonical_col) %}
    LOWER(
        TRIM(
            REGEXP_REPLACE(
                REGEXP_REPLACE(TRANSLATE(
                    COALESCE({{ title_col }}, '') || ' ' ||
                    COALESCE({{ brand_col }}, '') || ' ' ||
                    REPLACE(COALESCE({{ sub_category_col }}, ''), '_', ' ') || ' ' ||
                    REPLACE(COALESCE({{ category_col }}, ''), '_', ' ') || ' ' ||
                    COALESCE({{ store_col }}, '') || ' ' ||
                    REPLACE(COALESCE({{ canonical_col }}, ''), '_', ' ') || ' ' ||
                    CASE LOWER(COALESCE({{ sub_category_col }}, ''))
                        WHEN 'refrigerators' THEN 'تلاجة ثلاجة تلاجه ثلاجه fridge refrigerator'
                        WHEN 'freezers' THEN 'ديب فريزر فريزر freezer'
                        WHEN 'washing_machines' THEN 'غسالة غساله washing machine washer'
                        WHEN 'dishwashers' THEN 'غسالة اطباق غساله اطباق dishwasher'
                        WHEN 'air_conditioners' THEN 'تكييف مكيف حصان air conditioner ac hp'
                        WHEN 'tvs' THEN 'شاشة شاشه تلفزيون تليفزيون بوصة tv smart tv inch'
                        WHEN 'cookers' THEN 'بوتاجاز بوتجاز موقد شعلة cooker stove'
                        WHEN 'microwaves' THEN 'ميكروويف مايكروويف microwave'
                        WHEN 'water_heaters' THEN 'سخان water heater'
                        WHEN 'vacuums' THEN 'مكنسة مكنسه vacuum'
                        WHEN 'smartphones' THEN 'موبايل هاتف تليفون ايفون جيجا smartphone mobile phone gb'
                        WHEN 'laptops' THEN 'لابتوب لاب توب laptop notebook'
                        WHEN 'monitors' THEN 'شاشة كمبيوتر شاشه monitor inch'
                        WHEN 'headphones' THEN 'سماعة سماعات headphones earbuds'
                        WHEN 'oils_ghee' THEN 'زيت سمن سمنه oil ghee'
                        WHEN 'rice_pasta' THEN 'رز ارز مكرونة مكرونه سكر دقيق rice pasta sugar flour'
                        WHEN 'dairy_cheese' THEN 'لبن حليب جبنة جبنه زبدة milk cheese butter'
                        WHEN 'tea_coffee' THEN 'شاي قهوة قهوه بن tea coffee'
                        WHEN 'detergents' THEN 'مسحوق غسيل منظف detergent'
                        ELSE ''
                    END,
                    'أإآٱةىؤئ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹',
                    'ااااهيوي01234567890123456789'
                ), '[\u0610-\u061A\u0640\u064B-\u065F\u0670\u06D6-\u06ED]', '', 'g'),
                '[[:space:]\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF®™]+',
                ' ',
                'g'
            )
        )
    )
{% endmacro %}
