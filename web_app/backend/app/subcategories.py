"""Deterministic bilingual (AR + EN) canonical subcategory taxonomy & SQL filter builder.

Maps noisy per-store `sub_category` slugs and bilingual product titles into
clean, shopper-friendly canonical subcategories across all 10 active Asarak
categories — with ZERO database schema changes and ZERO Neon storage overhead.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional


@dataclass(frozen=True)
class SubcategorySpec:
    slug: str
    label_en: str
    label_ar: str
    raw_subcategories: tuple[str, ...] = ()
    raw_sub_regex: Optional[str] = None
    title_regex: Optional[str] = None
    exclude_title_regex: Optional[str] = None


SUBCATEGORY_TAXONOMY: dict[str, tuple[SubcategorySpec, ...]] = {
    "groceries": (
        SubcategorySpec(
            slug="oils_ghee",
            label_en="Oils & Ghee",
            label_ar="زيوت وسمن",
            raw_subcategories=("oils_ghee", "oil", "oils", "ghee", "cooking_oil"),
            title_regex=r"\b(oil|ghee|sunflower|corn oil|olive oil|butter)\b|(زيت|سمن|سمنة|سمنه|زبدة|زبده)",
        ),
        SubcategorySpec(
            slug="dairy_cheese",
            label_en="Dairy & Cheese",
            label_ar="ألبان وأجبان",
            raw_subcategories=("dairy_cheese", "dairy", "cheese", "milk", "yogurt"),
            title_regex=r"\b(milk|cheese|yogurt|yoghurt|cheddar|mozzarella|feta|labneh|butter|cream cheese)\b|(لبن|حليب|جبن|جبنة|جبنه|زبادي|زبادى|قشطة|قشطه|رايب|شيدر|موتزاريلا|رومي)",
            exclude_title_regex=r"\b(chocolate|biscuit|biscuits|wafer|cookie|cookies|peanut butter)\b|(شوكولاتة|شوكولاته|شيكولاتة|شيكولاته|بسكويت|بسكوت|زبدة فول سوداني)",
        ),
        SubcategorySpec(
            slug="rice_pasta",
            label_en="Rice, Pasta & Grains",
            label_ar="أرز ومكرونة",
            raw_subcategories=("rice_pasta", "rice", "pasta", "grains", "flour", "pulses"),
            title_regex=r"\b(rice|pasta|macaroni|spaghetti|noodles|flour|lentils|beans|oats|indomie)\b|\b(ال)?(ارز|أرز|رز|فول)\b|(مكرونة|مكرونه|معكرونة|اسباجتي|شعرية|دقيق|عدس|شوفان|اندومي|إندومي)",
        ),
        SubcategorySpec(
            slug="tea_coffee",
            label_en="Tea & Coffee",
            label_ar="شاي وقهوة",
            raw_subcategories=("tea_coffee", "tea", "coffee", "hot_drinks"),
            title_regex=r"\b(coffee|espresso|nescafe|cappuccino|latte|tea|green tea|herbal|anise|chamomile)\b|\b(ال)?(شاي|شاى|بن)\b|(قهوة|قهوه|نسكافيه|كابتشينو|اسبريسو|ينسون|يانسون|نعناع|كركديه)",
        ),
        SubcategorySpec(
            slug="snacks_chocolate",
            label_en="Snacks & Chocolate",
            label_ar="سناكس وشوكولاتة",
            raw_subcategories=("snacks", "chocolate", "biscuits", "chips", "sweets", "candy", "nuts"),
            title_regex=r"\b(chocolate|biscuit|biscuits|cookie|cookies|wafer|chips|crisps|snack|snacks|candy|gum|popcorn|nuts|crackers|cake|brownie)\b|(شوكولاتة|شوكولاته|شيكولاتة|شيكولاته|بسكويت|بسكوت|ويفر|شيبسي|شيبس|سناكس|مقرمشات|مكسرات|لبان|كاندي|كيك|مولتو)",
        ),
        SubcategorySpec(
            slug="beverages",
            label_en="Beverages & Juices",
            label_ar="مشروبات وعصائر",
            raw_subcategories=("beverages", "drinks", "juices", "water", "soft_drinks", "soda"),
            title_regex=r"\b(juice|water|soda|cola|pepsi|sprite|fanta|schweppes|energy drink|red bull|iced tea|nectar|sparkling)\b|(عصير|مياه|مياة|بيبسي|كولا|سبرايت|فانتا|شويبس|مشروب|نكتار|صودا)",
        ),
        SubcategorySpec(
            slug="meat_poultry",
            label_en="Meat, Poultry & Tuna",
            label_ar="لحوم ودواجن وتونة",
            raw_subcategories=("meat_poultry", "meat", "poultry", "seafood", "tuna", "frozen_meat", "deli"),
            title_regex=r"\b(chicken|beef|meat|tuna|sardine|salmon|shrimp|sausage|burger|nuggets|kofta|luncheon|pastrami|hot dog|frankfurter|turkey|fillet)\b|(دجاج|فراخ|لحم|لحمة|لحمه|تونة|تونه|سردين|سلمون|جمبري|سجق|برجر|ناجتس|بانيه|كفتة|كفته|لانشون|بسطرمة|هوت دوج)",
        ),
        SubcategorySpec(
            slug="honey_jams",
            label_en="Honey, Jams & Spreads",
            label_ar="عسل ومربى",
            raw_subcategories=("honey_jams", "honey", "jam", "jams", "spreads"),
            title_regex=r"\b(honey|jam|marmalade|nutella|peanut butter|molasses|halawa|tahina|tahini)\b|(عسل|مربى|مربي|نوتيلا|زبدة فول سوداني|حلاوة طحينية|طحينة|طحينه|دبس)",
        ),
        SubcategorySpec(
            slug="canned_sauces",
            label_en="Canned & Sauces",
            label_ar="معلبات وصلصات",
            raw_subcategories=("canned_sauces", "sauces", "canned", "spices", "condiments", "pickles"),
            title_regex=r"\b(sauce|ketchup|mayonnaise|mustard|vinegar|tomato paste|olives|pickle|spices|seasoning|salt|pepper|sugar|soup|stock|broth|dressing|canned)\b|\b(ال)?(خل|ملح|سكر)\b|(صلصة|صلصه|كاتشب|مايونيز|مستردة|زيتون|مخلل|توابل|بهارات|فلفل|مرقة|شوربة)",
            exclude_title_regex=r"\b(chocolate|biscuit|chips|tuna|honey|jam)\b|(شوكولاتة|بسكويت|شيبسي|تونة|تونه|عسل|مربى|مربي)",
        ),
        SubcategorySpec(
            slug="detergents",
            label_en="Detergents & Cleaning",
            label_ar="منظفات",
            raw_subcategories=("detergents", "cleaning", "laundry", "household", "paper_products"),
            title_regex=r"\b(detergent|ariel|persil|tide|downy|comfort|pril|fairy|clorox|bleach|dishwash|fabric softener|tissue|tissues|paper towel|trash bag|cleaner|disinfectant)\b|(مسحوق|اريال|إريال|برسيل|تايد|داوني|بريل|فيري|كلوركس|كلور|منظف|مطهر|مناديل|صابون مواعين)",
        ),
    ),
    "electronics": (
        SubcategorySpec(
            slug="smartphones",
            label_en="Smartphones",
            label_ar="موبايلات",
            raw_subcategories=("smartphones", "mobile_phones", "mobiles", "phones", "iphones", "cell_phones"),
            title_regex=r"\b(iphone|galaxy s2|galaxy a[0-9]|galaxy z|redmi|poco|realme|oppo reno|oppo a[0-9]|xiaomi 1[0-9]|infinix|tecno|honor [0-9x]|pixel [0-9]|smartphone|mobile phone)\b|(موبايل|هاتف ذكي|ايفون|آيفون)",
            exclude_title_regex=r"\b(case|cover|screen protector|tempered glass|cable|charger|adapter|holder|stand|pouch|skin|strap|band|glass|lens protector)\b|(جراب|كفر|اسكرينة|شاحن|كابل|حامل|غطاء)",
        ),
        SubcategorySpec(
            slug="laptops",
            label_en="Laptops",
            label_ar="لابتوب",
            raw_subcategories=("laptops", "notebooks", "macbooks", "gaming_laptops", "ultrabooks"),
            title_regex=r"\b(laptop|macbook|notebook|thinkpad|ideapad|vivobook|zenbook|pavilion|victus|omen|inspiron|latitude|xps|legion|tuf gaming|rog strix|chromebook)\b|(لابتوب|لاب توب|ماك بوك)",
            exclude_title_regex=r"\b(bag|sleeve|backpack|cooling pad|stand|charger|adapter|battery|skin|sticker)\b|(شنطة|حقيبة|شاحن|حامل)",
        ),
        SubcategorySpec(
            slug="tablets",
            label_en="Tablets & iPads",
            label_ar="تابلت وآيباد",
            raw_subcategories=("tablets", "ipads", "e_readers"),
            title_regex=r"\b(ipad|tablet|galaxy tab|xiaomi pad|redmi pad|matepad|kindle)\b|(تابلت|ايباد|آيباد)",
            exclude_title_regex=r"\b(case|cover|screen protector|keyboard case|stylus|pen tip|sleeve)\b|(جراب|كفر|اسكرينة)",
        ),
        SubcategorySpec(
            slug="audio_headphones",
            label_en="Audio & Headphones",
            label_ar="سماعات وصوتيات",
            raw_subcategories=(
                "headphones",
                "earbuds",
                "audio",
                "speakers",
                "microphone",
                "microphones",
                "headsets",
                "soundbars",
                "earphones",
            ),
            raw_sub_regex=r"(headphone|earbud|earphone|headset|speaker|audio|soundbar|mic)",
            title_regex=r"\b(airpods|earbuds|headphone|headphones|headset|earphone|speaker|soundbar|subwoofer|microphone|galaxy buds|freebuds|jbl flip|jbl charge|jbl tune)\b|(سماعة|سماعه|سماعات|ايربودز|ميكروفون|سبيكر|صوتيات)",
        ),
        SubcategorySpec(
            slug="smartwatches",
            label_en="Smartwatches",
            label_ar="ساعات ذكية",
            raw_subcategories=("wearables", "smartwatches", "smart_watches", "fitness_trackers", "smart_bands"),
            raw_sub_regex=r"(smartwatch|wearable|smart_watch|smart_band)",
            title_regex=r"\b(apple watch|galaxy watch|smartwatch|smart watch|mi band|smart band|amazfit|huawei watch|garmin|fitbit)\b|(ساعة ذكية|ساعه ذكيه|ساعات ذكية|سمارت واتش)",
            exclude_title_regex=r"\b(strap|replacement band|screen protector|charger cable|case)\b|(سير|استراب|جراب)",
        ),
        SubcategorySpec(
            slug="gaming",
            label_en="Gaming & Consoles",
            label_ar="جيمنج وبلايستيشن",
            raw_subcategories=(
                "gaming",
                "gaming_consoles",
                "consoles",
                "video_games",
                "controllers",
                "gaming_chairs",
                "ps5",
                "xbox",
                "nintendo",
            ),
            raw_sub_regex=r"(gaming|console|playstation|xbox|nintendo|controller)",
            title_regex=r"\b(playstation|ps5|ps4|xbox|nintendo switch|dualsense|joystick|gamepad|controller|steam deck|gaming chair|meta quest)\b|(بلايستيشن|إكس بوكس|اكس بوكس|نينتندو|جيمنج|ذراع تحكم|كرسي جيمنج)",
        ),
        SubcategorySpec(
            slug="monitors_tvs",
            label_en="Monitors & TVs",
            label_ar="شاشات وتلفزيونات",
            raw_subcategories=("monitors", "tvs", "televisions", "displays", "projectors", "screens"),
            raw_sub_regex=r"(monitor|television|projector|display|^tvs?$)",
            title_regex=r"\b(monitor|smart tv|oled tv|qled|uhd tv|4k tv|projector|gaming monitor)\b|(شاشة كمبيوتر|شاشة جيمنج|شاشات|تلفزيون|بروجكتور)",
        ),
        SubcategorySpec(
            slug="pc_components",
            label_en="PC Parts & Storage",
            label_ar="قطع كمبيوتر وتخزين",
            raw_subcategories=(
                "cpus",
                "gpus",
                "motherboards",
                "memory",
                "ram",
                "storage",
                "ssd",
                "hdd",
                "cooling",
                "power_supplies",
                "pc_cases",
                "cases",
                "desktops",
                "workstations",
                "networking",
                "routers",
            ),
            raw_sub_regex=r"(cpu|gpu|motherboard|memory|ram|storage|ssd|hdd|cool|power_suppl|psu|desktop|router|network|graphics)",
            title_regex=r"\b(rtx|gtx|radeon|ryzen|core i[3579]|motherboard|ddr4|ddr5|nvme|ssd|hard drive|power supply|liquid cooler|pc case|router|mesh wifi|flash drive|memory card)\b|(كارت شاشة|معالج|بروسيسور|ماذربورد|رامات|هارد|باور سبلاي|راوتر|فلاشة)",
        ),
        SubcategorySpec(
            slug="accessories_chargers",
            label_en="Accessories & Chargers",
            label_ar="إكسسوارات وشواحن",
            raw_subcategories=(
                "accessories",
                "peripherals",
                "chargers",
                "cables",
                "power_banks",
                "mouse",
                "keyboards",
                "adapters",
                "mobile_accessories",
                "computer_accessories",
            ),
            raw_sub_regex=r"(accessor|peripheral|charger|cable|power_bank|powerbank|mouse|keyboard|adapter|hub|cover|protector|webcam)",
            title_regex=r"\b(power bank|powerbank|charger|cable|adapter|usb-c|type-c|keyboard|mouse|mousepad|webcam|phone case|screen protector|tripod|hub|dock|magsafe)\b|(شاحن|باور بانك|كابل|كيبورد|ماوس|جراب|اسكرينة|وصلة|محول|كاميرا ويب)",
        ),
    ),
    "home_appliances": (
        SubcategorySpec(
            slug="refrigerators",
            label_en="Refrigerators & Freezers",
            label_ar="ثلاجات وديب فريزر",
            raw_subcategories=("refrigerators", "freezers", "deep_freezers", "minibars", "water_dispensers"),
            raw_sub_regex=r"(fridge|refrigerator|freezer|dispenser|minibar)",
            title_regex=r"\b(refrigerator|fridge|freezer|minibar|water dispenser)\b|(ثلاجة|ثلاجه|تلاجة|تلاجه|ديب فريزر|فريزر|مبرد مياه|ديسبنسر)",
        ),
        SubcategorySpec(
            slug="washing_machines",
            label_en="Washers & Dryers",
            label_ar="غسالات ومجففات",
            raw_subcategories=("washing_machines", "washers", "dryers", "dishwashers", "washer_dryers"),
            raw_sub_regex=r"(wash|dryer|dishwasher)",
            title_regex=r"\b(washing machine|washer|dryer|dishwasher)\b|(غسالة|غساله|مجفف|غسالة أطباق|غسالة اطباق)",
        ),
        SubcategorySpec(
            slug="air_conditioners",
            label_en="Air Conditioners",
            label_ar="تكييفات",
            raw_subcategories=("air_conditioners", "acs", "air_coolers"),
            raw_sub_regex=r"(air_condition|air_cooler|^ac$)",
            title_regex=r"\b(air conditioner|split ac|inverter ac|air cooler)\b|(تكييف|مكيف|مبرد هواء)",
        ),
        SubcategorySpec(
            slug="cookers_ovens",
            label_en="Cookers & Ovens",
            label_ar="بوتاجازات وأفران",
            raw_subcategories=("cookers", "ovens", "microwaves", "built_in_appliances", "hobs", "hoods", "stoves"),
            raw_sub_regex=r"(cooker|oven|microwave|hob|hood|built_in|stove)",
            title_regex=r"\b(cooker|gas stove|oven|microwave|built-in hob|cooker hood|chimney hood)\b|(بوتاجاز|بوتجاز|فرن|ميكروويف|مسطح|شفاط مطبخ)",
        ),
        SubcategorySpec(
            slug="small_kitchen",
            label_en="Small Kitchen Appliances",
            label_ar="أجهزة مطبخ صغيرة",
            raw_subcategories=(
                "kitchen_appliances",
                "small_appliances",
                "coffee_makers",
                "blenders",
                "air_fryers",
                "kettles",
                "mixers",
                "food_processors",
                "toasters",
            ),
            raw_sub_regex=r"(kitchen|small_appliance|coffee|blender|fryer|kettle|mixer|toaster|juicer|grill)",
            title_regex=r"\b(air fryer|blender|kettle|coffee maker|espresso machine|hand mixer|stand mixer|food processor|chopper|toaster|sandwich maker|waffle|juicer|meat grinder|electric grill)\b|(اير فراير|قلاية هوائية|خلاط|كاتل|غلاية|ماكينة قهوة|مضرب بيض|كبة|محضر طعام|توستر|عصارة|مفرمة|شواية كهربائية)",
        ),
        SubcategorySpec(
            slug="tvs",
            label_en="Televisions",
            label_ar="تلفزيونات",
            raw_subcategories=("tvs", "televisions", "smart_tvs", "receivers"),
            raw_sub_regex=r"(tv|television|receiver)",
            title_regex=r"\b(smart tv|led tv|oled|qled|uhd|4k tv|television|android tv|google tv|receiver)\b|(تلفزيون|تليفزيون|شاشة سمارت|ريسيفر)",
        ),
        SubcategorySpec(
            slug="vacuums_heaters",
            label_en="Vacuums, Heaters & Fans",
            label_ar="مكانس وسخانات ومراوح",
            raw_subcategories=(
                "vacuums",
                "vacuum_cleaners",
                "water_heaters",
                "heaters",
                "fans",
                "irons",
                "garment_steamers",
                "air_purifiers",
            ),
            raw_sub_regex=r"(vacuum|heater|fan|iron|steamer|purifier)",
            title_regex=r"\b(vacuum|water heater|space heater|oil heater|fan|stand fan|ceiling fan|steam iron|garment steamer|air purifier)\b|(مكنسة|مكنسه|سخان|دفاية|دفايه|مروحة|مروحه|مكواة|مكواه|منقي هواء)",
        ),
    ),
    "fashion": (
        SubcategorySpec(
            slug="men",
            label_en="Men",
            label_ar="رجالي",
            raw_subcategories=("men", "mens", "mens_clothing", "men_clothing", "menswear", "men_fashion"),
            raw_sub_regex=r"(^|_)men(s|_|s_|$)",
            title_regex=r"\b(men|men's|mens|man|male)\b|(رجالي|رجالى|للرجال)",
            exclude_title_regex=r"\b(women|women's|womens|ladies|female)\b|(حريمي|حريمى|نسائي|بناتي)",
        ),
        SubcategorySpec(
            slug="women",
            label_en="Women",
            label_ar="حريمي",
            raw_subcategories=(
                "women",
                "womens",
                "womens_clothing",
                "women_clothing",
                "womenswear",
                "dresses",
                "skirts",
                "abayas",
                "galabeya",
                "bra",
                "lingerie",
                "hijab",
                "blouses",
            ),
            raw_sub_regex=r"(^|_)(women|ladies|dress|skirt|abaya|galabeya|bra|lingerie|hijab|blouse|kaftan)",
            title_regex=r"\b(women|women's|womens|ladies|dress|skirt|blouse|abaya|hijab|kaftan|cardigan|jumpsuit|leggings|maternity|bra|lingerie|tunic|kimono)\b|(حريمي|حريمى|نسائي|للنساء|فستان|دريس|بلوزة|بلوزه|جيبة|عباية|عبايه|طرحة|سكارف|كارديجان|جامبسوت)",
        ),
        SubcategorySpec(
            slug="tops_outerwear",
            label_en="Tops, Hoodies & Jackets",
            label_ar="تيشيرتات وهوديز وجواكت",
            raw_subcategories=(
                "shirts",
                "tees",
                "t_shirts",
                "polos",
                "knitwear",
                "hoodies",
                "sweaters",
                "sweatshirts",
                "jackets",
                "outerwear",
                "blazers",
                "coats",
                "tops",
                "vests",
            ),
            raw_sub_regex=r"(shirt|tee|polo|hoodie|sweater|sweatshirt|jacket|coat|blazer|knitwear|outerwear|pullover|cardigan|vest)",
            title_regex=r"\b(t-shirt|tshirt|tee|polo|shirt|hoodie|sweatshirt|sweater|pullover|jacket|coat|blazer|vest|puffer|windbreaker|bomber|flannel)\b|(تيشيرت|تي شيرت|قميص|بولو|هودي|سويت شيرت|سويتر|بلوفر|جاكيت|معطف|بليزر|فيست)",
        ),
        SubcategorySpec(
            slug="pants_jeans",
            label_en="Pants, Jeans & Shorts",
            label_ar="بنطلونات وجينز",
            raw_subcategories=("pants", "jeans", "trousers", "shorts", "denim", "joggers", "sweatpants", "chinos", "bottoms"),
            raw_sub_regex=r"(pant|jean|trouser|short|denim|jogger|chino|bottom|cargo|legging)",
            title_regex=r"\b(jeans|pants|trousers|chinos|cargo|joggers|sweatpants|shorts|denim|leggings)\b|(بنطلون|جينز|شورت|باجي|كارغو|كارجو|جوجر|ليجنز)",
        ),
        SubcategorySpec(
            slug="footwear",
            label_en="Footwear & Sneakers",
            label_ar="أحذية وسنيكرز",
            raw_subcategories=(
                "shoes",
                "footwear",
                "sneakers",
                "boots",
                "sandals",
                "slippers",
                "loafers",
                "heels",
                "slip_on",
                "slides",
                "flats",
            ),
            raw_sub_regex=r"(shoe|footwear|sneaker|boot|sandal|slipper|loafer|heel|slip_on|slide|mule|clog|flat)",
            title_regex=r"\b(sneaker|sneakers|shoe|shoes|boot|boots|sandal|sandals|loafer|loafers|slipper|slides|heels|moccasin|espadrille|oxfords|clog)\b|(حذاء|أحذية|احذية|سنيكرز|كوتشي|بوت|صندل|شبشب|سليبر|لوفر|كعب)",
        ),
        SubcategorySpec(
            slug="bags",
            label_en="Bags & Wallets",
            label_ar="شنط وحقائب",
            raw_subcategories=("bags", "handbags", "backpacks", "wallets", "luggage", "crossbody", "totes", "clutches", "pouches"),
            raw_sub_regex=r"(bag|backpack|wallet|luggage|suitcase|tote|clutch|pouch|purse|satchel|crossbody)",
            title_regex=r"\b(bag|handbag|backpack|tote|crossbody|shoulder bag|clutch|wallet|cardholder|purse|suitcase|duffle|belt bag)\b|(شنطة|شنطه|حقيبة|حقيبه|باك باك|محفظة|محفظه|كروس|توت باج|شنطة سفر)",
        ),
        SubcategorySpec(
            slug="activewear",
            label_en="Activewear & Homewear",
            label_ar="ملابس رياضية ومنزلية",
            raw_subcategories=("activewear", "sportswear", "pajama", "pajamas", "loungewear", "tracksuits", "swimwear"),
            raw_sub_regex=r"(activewear|sportswear|pajama|pyjama|lounge|tracksuit|swim|homewear|gym)",
            title_regex=r"\b(activewear|sportswear|tracksuit|pajama|pyjama|loungewear|gym|workout|running|training|swimwear|swimsuit)\b|(رياضي|رياضية|تريننج|بيجامة|بيجامه|مايوه|ملابس بيت)",
        ),
        SubcategorySpec(
            slug="accessories_watches",
            label_en="Accessories & Eyewear",
            label_ar="إكسسوارات وساعات ونظارات",
            raw_subcategories=("accessories", "watches_jewelry", "watches", "jewelry", "eyewear", "sunglasses", "belts", "hats", "caps", "socks", "scarves"),
            raw_sub_regex=r"(accessor|watch|jewel|eyewear|sunglass|belt|hat|cap|sock|scarf|tie|glove|ring|necklace|bracelet|earring)",
            title_regex=r"\b(watch|sunglasses|eyeglasses|belt|cap|hat|beanie|socks|necklace|bracelet|ring|earring|pendant|scarf|tie)\b|(ساعة يد|نظارة شمس|نضارة|حزام|كاب|شراب|إكسسوار|سلسلة|خاتم|اسورة|حلق)",
        ),
    ),
    "beauty": (
        SubcategorySpec(
            slug="skincare",
            label_en="Skincare",
            label_ar="عناية بالبشرة",
            raw_subcategories=(
                "skincare",
                "skin_care",
                "sunscreen",
                "face_serum",
                "face_cream",
                "face_wash",
                "cleanser",
                "moisturizer",
                "toner",
                "lip_balm",
                "eye_cream",
                "masks",
                "spf",
            ),
            raw_sub_regex=r"(skin|sunscreen|spf|serum|cleanser|moistur|toner|face_|facial|lip_balm|eye_cream|acne|exfoliat|mask|micellar)",
            title_regex=r"\b(serum|sunscreen|spf|cleanser|face wash|moisturizer|face cream|toner|retinol|niacinamide|hyaluronic|vitamin c|micellar|lip balm|eye cream|scrub|exfoliant|facial mask|sheet mask|acne)\b|(سيروم|واقي شمس|صن بلوك|غسول وجه|غسول للوجه|مرطب|كريم وجه|تونر|ريتينول|هيالورونيك|ماسك وجه|مرطب شفاه)",
        ),
        SubcategorySpec(
            slug="fragrances",
            label_en="Perfumes & Fragrances",
            label_ar="عطور وبرفانات",
            raw_subcategories=("perfumes", "perfume", "fragrances", "edp", "edt", "parfum", "body_mist", "cologne", "oud"),
            raw_sub_regex=r"(perfume|fragrance|parfum|edp|edt|mist|cologne|oud|scent)",
            title_regex=r"\b(perfume|parfum|eau de|edp|edt|cologne|body mist|fragrance|oud|musk|splash)\b|(عطر|برفان|برفيوم|بادي ميست|عود|مسك|معطر جسم)",
        ),
        SubcategorySpec(
            slug="haircare",
            label_en="Haircare",
            label_ar="عناية بالشعر",
            raw_subcategories=("haircare", "hair_care", "shampoo", "conditioner", "hair_mask", "hair_oil", "hair_serum", "hair_styling", "hair_color"),
            raw_sub_regex=r"(hair|shampoo|conditioner|scalp)",
            title_regex=r"\b(shampoo|conditioner|hair mask|hair oil|hair serum|leave-in|hair cream|keratin|hair spray|dry shampoo|hair dye|hair color|scalp|hair brush)\b|(شامبو|بلسم|حمام كريم|زيت شعر|سيروم شعر|كريم شعر|صبغة شعر|فرشاة شعر)",
        ),
        SubcategorySpec(
            slug="makeup",
            label_en="Makeup & Nails",
            label_ar="مكياج وأظافر",
            raw_subcategories=(
                "makeup",
                "cosmetics",
                "lipstick",
                "mascara",
                "foundation",
                "concealer",
                "eyeliner",
                "blush",
                "nail_polish",
                "lip_oil",
                "lip_gloss",
                "eyeshadow",
                "powder",
            ),
            raw_sub_regex=r"(makeup|cosmetic|lip|mascara|foundation|concealer|eyeliner|blush|nail|eyeshadow|bronzer|highlighter|primer|brow|powder)",
            title_regex=r"\b(lipstick|lip gloss|lip oil|lip tint|lip liner|mascara|foundation|concealer|eyeliner|eyeshadow|blush|blusher|bronzer|highlighter|setting spray|primer|compact powder|loose powder|nail polish|eyebrow|bb cream|cc cream)\b|(مكياج|روج|أحمر شفاه|ماسكارا|فاونديشن|كريم أساس|كونسيلر|ايلاينر|بلاشر|مانيكير|طلاء أظافر|ليب جلوس|تنت)",
        ),
        SubcategorySpec(
            slug="body_care",
            label_en="Body Care & Bath",
            label_ar="عناية بالجسم",
            raw_subcategories=("body_care", "bath_body", "body_lotion", "body_wash", "shower_gel", "dry_oil", "roll_on", "deodorants", "hand_cream", "soap"),
            raw_sub_regex=r"(body|bath|shower|soap|deodorant|roll_on|hand_cream|foot|scrub|butter|wax|shav)",
            title_regex=r"\b(body lotion|body butter|body scrub|body wash|shower gel|body oil|dry oil|deodorant|antiperspirant|roll-on|roll on|hand cream|foot cream|soap)\b|(بادي لوشن|لوشن جسم|شاور جل|زبدة جسم|سكراب|مقشر جسم|مزيل عرق|رول أون|كريم يد|صابون استحمام)",
        ),
    ),
    "home_furniture": (
        SubcategorySpec(
            slug="sofas_living",
            label_en="Sofas & Living Rooms",
            label_ar="كنب وغرف معيشة",
            raw_subcategories=("sofas", "living_rooms", "l_shapes", "living_room_sets", "couches", "recliners", "sectionals", "armchairs", "poufs", "tv_units"),
            raw_sub_regex=r"(sofa|living|l_shape|couch|recliner|sectional|armchair|pouf|bean_bag|tv_unit)",
            title_regex=r"\b(sofa|l-shape|l shape|couch|sectional|recliner|armchair|living room|loveseat|chaise|bean bag|ottoman|pouf|tv unit|tv stand)\b|(كنبة|كنبه|أنتريه|انتريه|ركنة|ركنه|ليفينج|غرفة معيشة|ليزي بوي|وحدة تلفزيون)",
        ),
        SubcategorySpec(
            slug="beds_mattresses",
            label_en="Beds & Mattresses",
            label_ar="سراير ومراتب",
            raw_subcategories=("beds", "bedrooms", "bedroom_sets", "bed_and_2_nightstands", "mattresses", "wardrobes", "dressers", "nightstands"),
            raw_sub_regex=r"(bed|mattress|wardrobe|dresser|nightstand|closet|headboard)",
            title_regex=r"\b(bed|bedroom|mattress|wardrobe|closet|dresser|nightstand|bedside|bunk bed|headboard|memory foam)\b|(سرير|غرفة نوم|مرتبة|مرتبه|دولاب|كومود|تسريحة)",
            exclude_title_regex=r"\b(bedsheet|bed sheet|duvet|comforter|pillowcase|quilt|blanket)\b|(ملاية|لحاف|كوفرتة|بطانية)",
        ),
        SubcategorySpec(
            slug="tables_chairs",
            label_en="Tables & Chairs",
            label_ar="ترابيزات وكراسي",
            raw_subcategories=("tables", "dining_rooms", "chairs", "dining_chairs", "desks", "office_chairs", "coffee_tables", "side_tables", "bar_stools", "consoles"),
            raw_sub_regex=r"(table|dining|chair|desk|stool|console|bench|office)",
            title_regex=r"\b(table|dining|chair|desk|office chair|coffee table|side table|console|bar stool|bench|bookshelf|bookcase)\b|(ترابيزة|ترابيزه|طاولة|سفرة|كرسي|مكتب|كراسي|كونسول)",
        ),
        SubcategorySpec(
            slug="cookware",
            label_en="Cookware & Kitchen",
            label_ar="أدوات مطبخ وحلل",
            raw_subcategories=("cookware", "kitchenware", "dinnerware", "bakeware", "drinkware", "cutlery", "knives", "food_storage"),
            raw_sub_regex=r"(cookware|kitchen|dinnerware|bakeware|drinkware|cutlery|knife|pan|pot|mug|glass|plate)",
            title_regex=r"\b(cookware|frying pan|saucepan|pot set|granite|tefal|non-stick|pressure cooker|casserole|dinnerware|plates|cutlery|knives|knife set|mug|thermos|flask|lunch box|glassware|baking tray)\b|(طقم حلل|حلة|حله|طاسة|طاسه|مقلاة|جرانيت|تيفال|ستانلس|صينية|أطباق|طقم سفرة|كوبايات|مج|ترمس|سكاكين)",
        ),
        SubcategorySpec(
            slug="bedding_rugs",
            label_en="Bedding & Rugs",
            label_ar="مفروشات وسجاد",
            raw_subcategories=("bedding_linens", "bedding", "linens", "rugs", "carpets", "curtains", "towels", "pillows", "blankets", "cushions"),
            raw_sub_regex=r"(bedding|linen|rug|carpet|curtain|towel|pillow|blanket|duvet|comforter|sheet|cushion|quilt|mat)",
            title_regex=r"\b(bedding|bedsheet|bed sheet|duvet|comforter|quilt|blanket|pillow|cushion|towel|bathrobe|curtain|rug|carpet|runner|doormat)\b|(ملاية|ملايات|لحاف|كوفرتة|بطانية|مخدة|وسادة|فوطة|بشكير|برنس|ستارة|ستائر|سجادة|سجاد|مشاية)",
        ),
        SubcategorySpec(
            slug="decor_lighting",
            label_en="Decor & Lighting",
            label_ar="ديكور وإضاءة",
            raw_subcategories=("home_decor", "decor", "artwork", "lighting", "pendants", "lamps", "mirrors", "vases", "clocks", "candles", "frames", "wall_art"),
            raw_sub_regex=r"(decor|art|light|lamp|pendant|chandelier|mirror|vase|clock|candle|frame|plant)",
            title_regex=r"\b(lamp|chandelier|pendant|floor lamp|table lamp|wall light|led strip|mirror|vase|painting|wall art|tableau|canvas|clock|candle|diffuser|photo frame)\b|(نجفة|نجفه|أباجورة|اباجورة|لمبة|إضاءة|اضاءة|مراية|مرآة|فازة|تابلوه|لوحة|ساعة حائط|شمعة|ديكور)",
        ),
        SubcategorySpec(
            slug="storage_outdoor",
            label_en="Storage & Garden",
            label_ar="وحدات تخزين وحدائق",
            raw_subcategories=("storage", "buffets", "cabinets", "shelving", "shoe_racks", "garden_furniture", "outdoor", "patio", "organizers"),
            raw_sub_regex=r"(storage|buffet|cabinet|shelf|shelving|rack|garden|outdoor|patio|organiz)",
            title_regex=r"\b(cabinet|buffet|sideboard|shelf|shelves|shoe rack|storage box|organizer|laundry basket|garden|outdoor|patio|swing chair|hammock)\b|(وحدة تخزين|بوفيه|جزامة|جزامه|أرفف|ارفف|منظم|أثاث حدائق|مرجيحة)",
        ),
    ),
    "health": (
        SubcategorySpec(
            slug="supplements",
            label_en="Supplements & Protein",
            label_ar="مكملات وبروتين",
            raw_subcategories=("supplements", "sports_nutrition", "protein", "creatine", "amino_acids", "pre_workout", "weight_loss", "herbal_supplements"),
            raw_sub_regex=r"(supplement|nutrition|protein|creatine|amino|bcaa|workout|collagen|omega|probiotic|weight)",
            title_regex=r"\b(whey|protein|creatine|bcaa|amino|pre-workout|mass gainer|collagen|omega|fish oil|magnesium|zinc|ashwagandha|probiotic|glutamine|l-carnitine|melatonin|supplement|electrolyte)\b|(بروتين|واي بروتين|كرياتين|أمينو|كولاجين|أوميجا|ماغنسيوم|زنك|أشواجندا|مكمل غذائي)",
        ),
        SubcategorySpec(
            slug="vitamins",
            label_en="Vitamins & Minerals",
            label_ar="فيتامينات ومعادن",
            raw_subcategories=("vitamins", "multivitamins", "minerals"),
            raw_sub_regex=r"(vitamin|mineral)",
            title_regex=r"\b(vitamin|multivitamin|vit d|vit c|vit b|b12|calcium|iron|folic acid|biotin|centrum|limitless)\b|(فيتامين|ملتي فيتامين|كالسيوم|حديد|بيوتين|فوليك)",
        ),
        SubcategorySpec(
            slug="pharmacy",
            label_en="Pharmacy & Devices",
            label_ar="صيدلية وأجهزة طبية",
            raw_subcategories=("pharmacy", "wellness", "first_aid", "medical_devices", "otc", "pain_relief", "allergy", "digestive", "diagnostics", "thermometers"),
            raw_sub_regex=r"(pharmacy|wellness|first_aid|medical|diagnostic|device|thermometer|blood_pressure|glucose|nebulizer|otc)",
            title_regex=r"\b(blood pressure|glucometer|oximeter|thermometer|nebulizer|bandage|antiseptic|first aid|syringe|sanitizer|eye drops|nasal spray|lozenges|pain relief|inhaler|support brace)\b|(جهاز ضغط|جهاز سكر|ترمومتر|نيبولايزر|إسعافات|قطرة|بخاخ أنف|معقم|مطهر|كمامة|دعامة)",
        ),
        SubcategorySpec(
            slug="dermo_skincare",
            label_en="Dermo Skin & Hair",
            label_ar="عناية طبية بالبشرة والشعر",
            raw_subcategories=("skin_care", "skincare", "sunscreen", "hair_care", "haircare", "dermocosmetics", "acne_care"),
            raw_sub_regex=r"(skin|sunscreen|hair|dermo|acne|shampoo|serum|lotion|cream)",
            title_regex=r"\b(la roche|vichy|cerave|eucerin|bioderma|avene|uriage|cetaphil|sunscreen|spf|serum|cleanser|shampoo|minoxidil|moisturizer|panthenol|bepanthen)\b|(لاروش|فيشي|سيرافي|بيوديرما|أفين|يورياج|واقي شمس|غسول|شامبو طبي|سيروم|كريم مرطب)",
        ),
        SubcategorySpec(
            slug="personal_baby",
            label_en="Personal & Mom/Baby",
            label_ar="عناية شخصية وأمومة",
            raw_subcategories=(
                "personal_care",
                "oral_care",
                "bath_body_care",
                "feminine_care",
                "shaving_grooming",
                "mother_baby_care",
                "baby_care",
                "nursing_feeding",
                "diapering_potty",
                "makeup",
                "perfumes_fragrances",
            ),
            raw_sub_regex=r"(personal|oral|tooth|dental|bath|feminine|shav|groom|baby|mother|diaper|nursing|deodorant)",
            title_regex=r"\b(toothpaste|toothbrush|mouthwash|floss|razor|shaving|deodorant|sanitary|pads|diaper|pampers|baby wipes|baby formula|pacifier|feeding bottle|breast pump)\b|(معجون أسنان|فرشاة أسنان|غسول فم|ماكينة حلاقة|شفرات|فوط صحية|حفاضات|مناديل مبللة|ببرونة|لبن أطفال)",
        ),
    ),
    "sports": (
        SubcategorySpec(
            slug="sports_shoes",
            label_en="Sports Shoes",
            label_ar="أحذية رياضية",
            raw_subcategories=("sports_shoes", "footwear", "running_shoes", "football_boots", "slides", "sandals", "training_shoes", "basketball_shoes"),
            raw_sub_regex=r"(shoe|footwear|boot|cleat|slide|sandal|sneaker|running)",
            title_regex=r"\b(running shoe|training shoe|football boot|cleats|sneaker|slides|adilette|ultraboost|pegasus|air max|metcon|court shoe|padel shoe|tennis shoe)\b|(حذاء رياضي|كوتشي رياضي|حذاء جري|حذاء كرة قدم|ستارز|سليبر رياضي)",
        ),
        SubcategorySpec(
            slug="sportswear",
            label_en="Sportswear",
            label_ar="ملابس رياضية",
            raw_subcategories=(
                "sportswear",
                "activewear",
                "pants",
                "knitwear",
                "tees",
                "jackets",
                "matching_set",
                "swimwear",
                "shirts",
                "shorts",
                "hoodies",
                "leggings",
                "jerseys",
                "tracksuits",
            ),
            raw_sub_regex=r"(sportswear|activewear|apparel|clothing|pant|tee|shirt|jacket|hoodie|short|legging|jersey|tracksuit|swim|set|bra|knitwear)",
            title_regex=r"\b(tracksuit|jersey|training tee|sports bra|leggings|joggers|gym shorts|running shorts|swimwear|swimsuit|rash guard|hoodie|windbreaker|compression|polo|t-shirt|sweatshirt)\b|(تريننج|تيشيرت رياضي|شورت رياضي|بنطلون رياضي|مايوه|ملابس سباحة|ملابس رياضية|طقم رياضي)",
        ),
        SubcategorySpec(
            slug="fitness_gear",
            label_en="Gym & Fitness Gear",
            label_ar="معدات جيم ولياقة",
            raw_subcategories=(
                "sports_gear",
                "fitness_equipment",
                "weights",
                "dumbbells",
                "cardio",
                "treadmills",
                "yoga",
                "pilates",
                "benches",
                "resistance_bands",
                "combat_sports",
                "boxing",
            ),
            raw_sub_regex=r"(fitness|gym|weight|dumbbell|barbell|cardio|treadmill|bike|yoga|pilates|equipment|gear|combat|box|bench)",
            title_regex=r"\b(dumbbell|barbell|kettlebell|treadmill|exercise bike|elliptical|yoga mat|resistance band|pull up bar|weight bench|jump rope|skipping rope|foam roller|boxing gloves|punching bag|ab wheel|home gym)\b|(دمبل|دامبل|بار حديد|مشاية كهربائية|عجلة رياضية|سجادة يوجا|مات يوجا|حبل نط|قفازات ملاكمة|بنش|أستك مقاومة|عقلة)",
        ),
        SubcategorySpec(
            slug="rackets_outdoor",
            label_en="Padel, Tennis & Outdoor",
            label_ar="بادل وتنس وكرة وسباحة",
            raw_subcategories=("padel_racket", "tennis_racket", "rackets", "balls", "football", "basketball", "swimming", "cycling", "camping", "outdoor"),
            raw_sub_regex=r"(padel|tennis|racket|ball|football|soccer|basketball|volleyball|swim|goggle|cycl|bicycle|camp|outdoor|ping_pong|squash)",
            title_regex=r"\b(padel|tennis|squash|racket|racquet|football|soccer ball|basketball|volleyball|goggles|swim cap|fins|snorkel|bicycle|bike|helmet|tent|sleeping bag|table tennis|ping pong)\b|(بادل|تنس|اسكواش|مضرب|كرة قدم|كرة سلة|نظارة سباحة|زعانف|دراجة|عجلة|خيمة|تخييم)",
        ),
        SubcategorySpec(
            slug="sports_bags",
            label_en="Sports Bags & Accessories",
            label_ar="شنط وإكسسوارات رياضية",
            raw_subcategories=("bags", "backpack", "pouch", "duffle_bag", "lunch_bag", "accessories", "cap", "sunglasses", "goggles", "bottles", "shakers", "socks", "gloves"),
            raw_sub_regex=r"(bag|backpack|duffle|pouch|accessor|cap|hat|bottle|shaker|sock|glove|wristband|sleeve|sunglass)",
            title_regex=r"\b(gym bag|duffle bag|backpack|water bottle|shaker|sports cap|gym gloves|knee sleeve|wrist wrap|ankle support|sports socks|headband|shoe bag)\b|(شنطة جيم|شنطة رياضية|زمزمية|شيكر|جوانتي جيم|كاب رياضي|شراب رياضي|رباط ركبة)",
        ),
    ),
    "baby_kids": (
        SubcategorySpec(
            slug="toys",
            label_en="Toys & Games",
            label_ar="ألعاب أطفال",
            raw_subcategories=(
                "toys",
                "blocks",
                "puzzle",
                "art_craft_toys",
                "pretend_play",
                "doll",
                "die_cast",
                "action_figures",
                "board_games",
                "rc_toys",
                "outdoor_toys",
                "plush",
                "educational_toys",
            ),
            raw_sub_regex=r"(toy|block|lego|puzzle|doll|die_cast|figure|game|plush|craft|pretend|rc_|play|scooter)",
            title_regex=r"\b(lego|toy|toys|puzzle|doll|barbie|hot wheels|nerf|play-doh|playdoh|plush|teddy|board game|rc car|action figure|blocks|slime|scooter|tricycle|ride-on|playset)\b|(لعبة|لعبه|ألعاب|العاب|ليجو|بازل|عروسة|عروسه|دمية|عربية ألعاب|صلصال|اسكوتر|مكعبات)",
        ),
        SubcategorySpec(
            slug="baby_gear",
            label_en="Baby Gear & Feeding",
            label_ar="مستلزمات رضّع",
            raw_subcategories=("baby_gear", "baby", "baby_essentials", "strollers", "car_seats", "feeding", "diapering", "cribs", "carriers", "bouncers", "monitors"),
            raw_sub_regex=r"(baby|stroller|car_seat|feeding|diaper|crib|carrier|bouncer|nursery|nursing|bath)",
            title_regex=r"\b(stroller|car seat|high chair|baby carrier|bouncer|rocker|crib|playpen|feeding bottle|pacifier|sterilizer|breast pump|diaper bag|diapers|baby monitor|baby walker|potty|bib|sippy cup|teether)\b|(عربية أطفال|عربية بيبي|كار سيت|كرسي أكل|شيالة أطفال|سرير أطفال|ببرونة|تيتينة|لهاية|شنطة بيبي|حفاضات|مشاية أطفال)",
        ),
        SubcategorySpec(
            slug="kids_clothing",
            label_en="Kids Clothing & Shoes",
            label_ar="ملابس وأحذية أطفال",
            raw_subcategories=("kids_clothing", "kids", "boys", "girls", "baby_clothing", "kids_shoes", "toddler"),
            raw_sub_regex=r"(cloth|apparel|boy|girl|kid|toddler|shoe|footwear|dress|pajama|romper|onesie)",
            title_regex=r"\b(boys|girls|kids|toddler|romper|onesie|bodysuit|jumpsuit|pajama|pyjama|t-shirt|dress|jacket|hoodie|jeans|shorts|sneakers|sandals|socks|swimsuit)\b|(ملابس أطفال|أولادي|بناتي|سالوبيت|بيجامة أطفال|فستان أطفال|تيشيرت أطفال|جاكيت أطفال|حذاء أطفال)",
        ),
        SubcategorySpec(
            slug="school_books",
            label_en="School & Books",
            label_ar="مدرسة وشنط وكتب",
            raw_subcategories=("school", "backpacks", "lunch_bags_boxes", "stationary", "stationery", "pencil_case", "books", "coloring"),
            raw_sub_regex=r"(school|backpack|lunch|station|pencil|book|story|color|notebook)",
            title_regex=r"\b(school bag|backpack|lunch box|lunch bag|pencil case|water bottle|stationery|notebook|crayons|markers|colored pencils|storybook|coloring book|activity book|flashcards)\b|(شنطة مدرسة|لانش بوكس|لانش باج|مقلمة|أدوات مكتبية|ألوان|كراسة|كتاب أطفال|قصة أطفال)",
        ),
        SubcategorySpec(
            slug="kids_furniture",
            label_en="Kids Room & Party",
            label_ar="غرف أطفال وحفلات",
            raw_subcategories=("kids_furniture", "party", "room_decor", "birthday"),
            raw_sub_regex=r"(furniture|party|birthday|decor|balloon|costume)",
            title_regex=r"\b(balloon|party|birthday|costume|kids bed|kids desk|kids chair|toy storage|play mat|teepee|night light)\b|(بالونات|عيد ميلاد|حفلات|زي تنكري|مكتب أطفال|تخزين ألعاب|سجادة لعب|خيمة أطفال)",
        ),
    ),
    "pet_care": (
        SubcategorySpec(
            slug="cat_food",
            label_en="Cat Food",
            label_ar="طعام قطط",
            raw_subcategories=("cat_food", "dry_cat_food", "wet_cat_food", "kitten_food"),
            raw_sub_regex=r"(cat_food|kitten)",
            title_regex=r"\b(cat food|kitten food|dry cat|wet cat|cat pouch|cat can|whiskas|felix|friskies|leonardo)\b|(طعام قطط|أكل قطط|اكل قطط|دراي فود قطط|ويت فود قطط|كيتن)",
        ),
        SubcategorySpec(
            slug="dog_food",
            label_en="Dog Food",
            label_ar="طعام كلاب",
            raw_subcategories=("dog_food", "dry_dog_food", "wet_dog_food", "puppy_food"),
            raw_sub_regex=r"(dog_food|puppy)",
            title_regex=r"\b(dog food|puppy food|dry dog|wet dog|pedigree|belcando)\b|(طعام كلاب|أكل كلاب|اكل كلاب|دراي فود كلاب|جرو)",
        ),
        SubcategorySpec(
            slug="cat_litter",
            label_en="Cat Litter & Boxes",
            label_ar="رمل قطط",
            raw_subcategories=("cat_litter", "litter", "litter_boxes"),
            raw_sub_regex=r"(litter)",
            title_regex=r"\b(cat litter|bentonite|silica litter|litter box|litter tray|scoop)\b|(رمل قطط|رمل للقطط|ليتر بوكس|صندوق فضلات)",
        ),
        SubcategorySpec(
            slug="pet_treats",
            label_en="Treats & Grooming",
            label_ar="مكافآت وعناية",
            raw_subcategories=("pet_treats", "treats", "cat_treats", "dog_treats", "grooming", "pet_health", "shampoo"),
            raw_sub_regex=r"(treat|snack|groom|shampoo|health|vitamin|flea|tick)",
            title_regex=r"\b(treat|treats|snack|chew|catnip|malt paste|pet shampoo|flea|tick|deworm|nail clipper)\b|(مكافآت|تريتس|شامبو قطط|شامبو كلاب|مالت|براغيث)",
        ),
        SubcategorySpec(
            slug="pet_accessories",
            label_en="Accessories & Toys",
            label_ar="مستلزمات وألعاب",
            raw_subcategories=(
                "pet_supplies",
                "pet_accessories",
                "harness",
                "accessory",
                "feeder",
                "bowls",
                "carriers",
                "beds",
                "toys",
                "collars",
                "leashes",
                "scratchers",
            ),
            raw_sub_regex=r"(suppl|accessor|harness|collar|leash|feeder|bowl|carrier|crate|bed|toy|scratch|cage)",
            title_regex=r"\b(collar|leash|harness|bowl|feeder|water fountain|carrier|crate|pet bed|scratching post|scratcher|cat tree|pet toy|cage|muzzle)\b|(طوق|ليش|حزام|طبق أكل|بوكس نقل|حاملة قطط|سرير قطط|خراشة|ألعاب قطط|ألعاب كلاب)",
        ),
    ),
}

_SPEC_LOOKUP: dict[tuple[str, str], SubcategorySpec] = {
    (cat, spec.slug): spec
    for cat, specs in SUBCATEGORY_TAXONOMY.items()
    for spec in specs
}


def _to_pg_regex(pattern: str) -> str:
    """Convert Python `\\b` word boundaries into PostgreSQL POSIX `\\y`."""
    return pattern.replace(r"\b", r"\y")


def get_category_subcategories(category: str) -> tuple[SubcategorySpec, ...]:
    return SUBCATEGORY_TAXONOMY.get(category.strip().lower(), ())


def get_subcategory_spec(category: str, subcategory: str) -> Optional[SubcategorySpec]:
    return _SPEC_LOOKUP.get((category.strip().lower(), subcategory.strip().lower()))


def normalize_subcategory_slug(subcategory: Optional[str]) -> str:
    if not subcategory:
        return ""
    return subcategory.strip().lower().replace("-", "_").replace(" ", "_")


def build_subcategory_sql_filter(
    category: Optional[str],
    subcategory: Optional[str],
    *,
    alias: str = "",
    param_prefix: str = "sub",
) -> tuple[Optional[str], dict[str, Any]]:
    """Build a parameterized PostgreSQL boolean predicate for `(category, subcategory)`.

    Supports both canonical slugs from `SUBCATEGORY_TAXONOMY` and raw `sub_category`
    fallback slugs. Returns `(None, {})` when `subcategory` is empty.
    """
    norm_sub = normalize_subcategory_slug(subcategory)
    if not norm_sub:
        return None, {}

    prefix = f"{alias}." if alias else ""
    sub_col = f"LOWER(COALESCE({prefix}sub_category, ''))"
    title_col = f"COALESCE({prefix}product_title, '')"

    norm_cat = (category or "").strip().lower()
    spec = _SPEC_LOOKUP.get((norm_cat, norm_sub)) if norm_cat and norm_cat != "all" else None

    # Allow lookup across all categories if category == 'all' and slug is unique
    if spec is None and (not norm_cat or norm_cat == "all"):
        matches = [s for (_, slug), s in _SPEC_LOOKUP.items() if slug == norm_sub]
        if len(matches) == 1:
            spec = matches[0]

    if spec is None:
        key = f"{param_prefix}_exact"
        return f"{sub_col} = :{key}", {key: norm_sub}

    params: dict[str, Any] = {}
    positive_parts: list[str] = []

    if spec.raw_subcategories:
        raw_key = f"{param_prefix}_raw_list"
        params[raw_key] = list(spec.raw_subcategories)
        positive_parts.append(f"{sub_col} = ANY(:{raw_key})")

    if spec.raw_sub_regex:
        raw_re_key = f"{param_prefix}_raw_re"
        params[raw_re_key] = _to_pg_regex(spec.raw_sub_regex)
        positive_parts.append(f"{sub_col} ~* :{raw_re_key}")

    if spec.title_regex:
        title_re_key = f"{param_prefix}_title_re"
        params[title_re_key] = _to_pg_regex(spec.title_regex)
        positive_parts.append(f"{title_col} ~* :{title_re_key}")

    if not positive_parts:
        key = f"{param_prefix}_exact"
        return f"{sub_col} = :{key}", {key: norm_sub}

    predicate = "(" + " OR ".join(positive_parts) + ")"
    if spec.exclude_title_regex:
        excl_key = f"{param_prefix}_excl_re"
        params[excl_key] = _to_pg_regex(spec.exclude_title_regex)
        predicate = f"({predicate} AND NOT ({title_col} ~* :{excl_key}))"

    return predicate, params


def classify_product_subcategory(
    category: str,
    raw_sub_category: Optional[str],
    product_title: str = "",
) -> Optional[str]:
    """Deterministic pure-Python canonical subcategory classifier."""
    specs = get_category_subcategories(category)
    if not specs:
        return None

    raw_norm = normalize_subcategory_slug(raw_sub_category)
    title = product_title or ""

    # Pass 1: exact raw_subcategories match (unless excluded by title)
    for spec in specs:
        if spec.exclude_title_regex and re.search(spec.exclude_title_regex, title, re.IGNORECASE):
            continue
        if raw_norm and raw_norm in spec.raw_subcategories:
            return spec.slug

    # Pass 2: raw_sub_regex or title_regex match
    for spec in specs:
        if spec.exclude_title_regex and re.search(spec.exclude_title_regex, title, re.IGNORECASE):
            continue
        if raw_norm and spec.raw_sub_regex and re.search(spec.raw_sub_regex, raw_norm, re.IGNORECASE):
            return spec.slug
        if title and spec.title_regex and re.search(spec.title_regex, title, re.IGNORECASE):
            return spec.slug

    return None
