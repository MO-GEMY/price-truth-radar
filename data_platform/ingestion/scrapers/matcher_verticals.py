"""Category-specific precision-first cross-store matchers for:
- `health` (supplements, vitamins, sports nutrition, pharmacy)
- `beauty` (skincare, haircare, makeup, perfumes)
- `footwear` (`fashion` & `sports` shoes, sneakers, boots, sandals)
- Shared effective category resolution (matching `silver.stg_products` store map)
- Shared anti-false-positive guards (accessory blocker, collapsed-variant blocker)
"""

from __future__ import annotations

import re
from typing import Optional

from .base import RawProductSnapshot, normalize_snake_slug
from .units import UnitSpec, normalize_unit_text, parse_unit_spec

# ---------------------------------------------------------------------------
# Effective Gold Category Map (mirrors `warehouse_dbt/models/staging/stg_products.sql`)
# Ensures `--match-db` sees the true vertical for all 19.5k reclassified store rows
# without mutating `raw.raw_product_snapshots.category`.
# ---------------------------------------------------------------------------
_BEAUTY_STORES: frozenset[str] = frozenset({
    "bashrety", "biostream", "bless_eg", "bobana", "braes_eg", "catwa_store",
    "cybele_eg", "dermaelle", "diwan_fragrances", "eparkville", "eva_cosmetics",
    "hayah_labs", "infinity_clinic", "malak_eg", "melano_pharma", "mood_eg",
    "mood_fragrances", "neuth_eg", "norshek", "raw_african", "soul_and_more",
    "source_beauty", "the_hair_addict", "zynah",
    "faces_eg", "mazaya_eg", "amanda_milano", "telofill_eg", "cleo_labs",
})

_HEALTH_STORES: frozenset[str] = frozenset({
    "beseha", "bloom_pharmacy", "egysupps", "house_of_supplements", "ifit_eg",
    "limitless_naturals", "max_muscle_eg", "nowfoods_eg", "organic_nation",
    "el_ezaby", "seif_pharmacies", "misr_pharmacies", "roshdy_pharmacies",
    "delmar_attalla", "fouda_pharmacy", "tarshouby", "chefaa", "yodawy",
    "soukare_eg", "tdawi", "super_supplements",
    "gofit_eg", "mfsupps_eg", "powerstore_eg", "mr_vitamins_eg", "protein_house_eg",
})

_HOME_APPLIANCES_STORES: frozenset[str] = frozenset({
    "ehab_center", "kaufen_eg", "elalfy_eg", "sokany_eg", "unionaire_eg", "zanussi_eg",
})

_HOME_FURNITURE_STORES: frozenset[str] = frozenset({
    "hub_furniture", "kabbani", "chichomz", "ariika", "el_malek_furniture",
    "bed_janssen", "family_bed", "habitat_eg", "janssen_stores", "manzzeli", "mffco",
    "bednhome", "elbadrawi_home", "grand_style", "heba_linens", "nile_home", "smart_furniture",
    "elzenouki", "elzenouki_cookware", "neoflam_eg", "nouval_eg", "zinox_elzenouki",
    "ikea_eg", "homzmart", "efreshli", "in_and_out", "mobica", "taki_eg",
    "linen_house_eg", "oriental_weavers", "rich_home", "zahran_stores",
})

_SPORTS_STORES: frozenset[str] = frozenset({
    "alnasser_eg", "athlete_home", "entercise", "gosport_eg",
    "intersport_eg", "union_sport", "wayup_sports", "decathlon_eg", "puma_eg",
})

_PET_CARE_STORES: frozenset[str] = frozenset({
    "happet", "amin_pet_shop", "pets_egypt", "egypuppy",
})

_BABY_KIDS_STORES: frozenset[str] = frozenset({
    "eftekassat", "kassem_store", "le3ab_store", "ourkids_eg",
    "bingo_toys", "hedeya", "diwan_books", "samir_and_aly",
    "bernasos", "shorouk_books",
})


def effective_category(record: RawProductSnapshot) -> str:
    """Resolve canonical gold category for matching (mirrors `stg_products.sql`)."""
    store = (record.store_name or "").strip().lower()
    if store in _PET_CARE_STORES:
        return "pet_care"
    if store in _BEAUTY_STORES:
        return "beauty"
    if store in _HOME_APPLIANCES_STORES:
        return "home_appliances"
    if store in _HOME_FURNITURE_STORES:
        return "home_furniture"
    if store in _HEALTH_STORES:
        return "health"
    if store in _SPORTS_STORES:
        return "sports"
    if store in _BABY_KIDS_STORES:
        return "baby_kids"
    cat = (record.category or "").strip().lower()
    if cat == "pharmacy":
        return "health"
    if cat == "kitchen":
        return "home_furniture"
    if cat in ("optics", "watches", "lifestyle"):
        return "fashion"
    if cat == "books":
        return "baby_kids"
    return cat or "electronics"


# ---------------------------------------------------------------------------
# Shared Anti-False-Positive Guards
# ---------------------------------------------------------------------------
_ACCESSORY_SIGNAL_RE = re.compile(
    r"(?:"
    r"\b(?:case|cases|cover|covers|pouch|sleeve|bag|backpack|folio|bumper|"
    r"screen\s*protector|tempered\s*glass|privacy\s*glass|protector|film|"
    r"phone\s*skin|laptop\s*skin|vinyl\s*skin|decal\s*skin|sticker|"
    r"cable|cables|cord|wire|charger|adapter|adaptor|dongle|hub|dock|converter|splitter|"
    r"replacement\s*remote|remote\s*control\s+for|strap|watch\s*band|bracelet|"
    r"stand|holder|mount|bracket|tripod|selfie\s*stick|grip|ring\s*light|stylus|"
    r"cooling\s*pad|laptop\s*cooler|cleaning\s*kit|dust\s*cover|"
    r"cartridge|toner|ink\s*bottle|drum\s*unit|ribbon|"
    r"spare\s*part|spare|replacement|hose|valve|filter|gasket|seal|hinge|knob|"
    r"barrier|eggs\s*pocket|meat\s*tipper|ice\s*pack|ice\s*cube|grid|"
    r"chopper\s*blade|shaft\s*assembly|jug\s*base|pipe\s*ceiling|lnb|diseqc|"
    r"detergent|rinse\s*aid|shaker\s*bottle|shaker|pill\s*box|tote|totes|keychain|"
    r"insole|insoles|shoelace|shoelaces|shoe\s*lace|shoe\s*tree|shoe\s*cleaner)\b|"
    r"(?:جراب|كفر|اسكرين|سكرين|شاحن|كابل|وصلة|محول|ريموت|فلتر|حامل|قاعدة|قطعة\s*غيار|"
    r"شنطة|حقيبة|غلاف|لاصق|استيكر|سير\s*ساعة|استراب|مفرش|خرطوم|مقبض|مصفاة|شفاط|"
    r"رف\s*ثلاجة|درج\s*ثلاجة|شيكر)"
    r")",
    re.I,
)

_HB_ACCESSORY_RE = re.compile(
    r"(?:\b(?:shaker\s*bottle|shaker|pill\s*box|pill\s*organizer|tote\s*bag|totes?|keychain|"
    r"makeup\s*bag|cosmetic\s*bag|travel\s*bottle|empty\s*bottle|applicator\s*sponge)\b|"
    r"(?:شيكر|شنطة\s*مكياج|منظم\s*حبوب))",
    re.I,
)

_MAIN_DEVICE_WITH_INCLUDED_ACC_RE = re.compile(
    r"\b(?:with\s+(?:flip\s+)?cover|with\s+(?:magic\s+)?remote|with\s+adapter|with\s+charger|"
    r"with\s+(?:an\s+)?electric\s+charger|with\s+stand|with\s+accessories|with\s+bag|"
    r"with\s+(?:magsafe\s+)?charging\s+case|stand\s+fan|stand\s+mixer|vacuum\s+cleaner|"
    r"steam\s+cleaner|air\s+cleaner|the\s+frame|frameless|mid\s*tower|full\s*tower|"
    r"pc\s*case|gaming\s*case|atx\s*case|cpu\s*cooler|liquid\s*cooler|aio\s*cooler|"
    r"water\s*cooler|air\s*cooler|filter\s+coffee|water\s+filter\s+\d+\s*stages?)\b",
    re.I,
)


_EXPLICIT_ACCESSORY_PHRASE_RE = re.compile(
    r"(?:"
    r"\b(?:case|cover|pouch|sleeve|bag|backpack|folio|bumper|protector|glass|film|skin|sticker|"
    r"cable|charger|adapter|adaptor|remote|strap|band|stand|holder|mount|bracket|hose|filter|"
    r"gasket|seal|hinge|knob|blade|shaft|jug\s*base|frame|grid|barrier|pocket|tipper|"
    r"replacement|spare\s*part|battery|ink|toner|cartridge)\s+(?:for|compatible\s+with)\b|"
    r"\b(?:screen\s*protector|tempered\s*glass|privacy\s*glass|phone\s*case|silicone\s*case|"
    r"leather\s*case|clear\s*case|magsafe\s*case|laptop\s*bag|laptop\s*sleeve|laptop\s*backpack|"
    r"laptop\s*stand|laptop\s*cooler|cooling\s*pad|phone\s*stand|phone\s*holder|car\s*holder|"
    r"car\s*mount|wall\s*mount|watch\s*strap|watch\s*band|replacement\s*remote|cleaning\s*kit|"
    r"eggs\s*pocket|meat\s*tipper|ice\s*pack|ice\s*cube|chopper\s*blade|shaft\s*assembly|"
    r"jug\s*base|pipe\s*ceiling|lnb|diseqc|freezer\s*door\s*barrier|bottles\s*barrier|"
    r"medicines\s*barrier|cabinet\s*door\s*barrier|frame\s+(?:tornado|toshiba|sharp)|"
    r"grid\s+(?:tornado|toshiba|sharp)|shaker\s*bottle|pill\s*box|tote\s*bag|shoelaces?|insoles?)\b|"
    r"(?:جراب|كفر|اسكرين|سكرين|قطعة\s*غيار|رف\s*ثلاجة|درج\s*ثلاجة|شنطة\s*لابتوب|حقيبة\s*لابتوب|"
    r"لاصق\s*حماية|سير\s*ساعة|استراب|ريموت\s*كنترول\s*ل|شاحن\s*لابتوب|شاحن\s*موبايل)"
    r")",
    re.I,
)

_MAIN_PRODUCT_IDENTITY_RE = re.compile(
    r"(?:"
    r"\b(?:vacuum\s*cleaner|canister\s*vacuum|stick\s*vacuum|robot\s*vacuum|"
    r"air\s*conditioner|split\s*air|washing\s*machine|washer|refrigerator|fridge|freezer|"
    r"dishwasher|microwave|water\s*heater|gas\s*cooker|electric\s*cooker|cooker|built[\s-]?in\s*(?:oven|hob)|"
    r"smart\s*tv|led\s*tv|qled\s*tv|oled\s*tv|uhd\s*tv|4k\s*tv|the\s*frame|"
    r"gaming\s*monitor|ips\s*monitor|proart|curved\s*monitor|led\s*monitor|"
    r"gaming\s*laptop|laptop|notebook|macbook|smartphone|mobile\s*phone|tablet|ipad|"
    r"projector|kettle|blender|hand\s*blender|food\s*processor|air\s*fryer|coffee\s*maker|"
    r"espresso\s*machine|stand\s*fan|ceiling\s*fan|wall\s*fan|box\s*fan|stand\s*mixer|toaster|iron|"
    r"case\s*fan|pwm\s*fan|argb\s*fan|cpu\s*cooler|liquid\s*cooler|aio\s*cooler|water\s*cooler|"
    r"mid\s*tower|full\s*tower|pc\s*case|gaming\s*case|power\s*supply|motherboard|graphics\s*card|"
    r"gaming\s*mouse|wireless\s*mouse|wired\s*mouse|optical\s*mouse|gaming\s*keyboard|mechanical\s*keyboard|"
    r"gaming\s*headset|wireless\s*headphone|headphones|earbuds|airpods|gamepad|gaming\s*controller|"
    r"microphone|webcam|range\s*extender|wifi\s*extender|router|access\s*point|network\s*switch|"
    r"printer|laserjet|scanner|smartwatch|smart\s*watch|water\s*filter\s+\d+\s*stages?)\b|"
    r"(?:مكنسة|تكييف|غسالة|ثلاجة|تلاجة|ديب\s*فريزر|بوتاجاز|سخان|ميكروويف|شاشة|تلفزيون|"
    r"غلاية|غلايه|خلاط|هاند\s*بلندر|مروحة|كبة|محضر\s*طعام|قلاية|ماكينة|ماكينه|بروجيكتور|سماعة|طابعة)"
    r")",
    re.I,
)


def is_accessory_listing(record: RawProductSnapshot) -> bool:
    """Return True if a listing is an accessory, spare part, or consumable — without
    false-firing on main devices that mention included accessories/features (e.g.
    `Vacuum Cleaner with Dust Bag & HEPA Filter`, `Monitor with Ergonomic Stand`,
    `Case Fan`, `TV with Magic Remote`, `Tablet with Flip Cover`)."""
    cat = effective_category(record)
    title = record.product_title or ""
    if cat in ("health", "beauty"):
        return bool(_HB_ACCESSORY_RE.search(title))

    # 1. Explicit spare-part / "X for Y" accessory phrases always win
    if _EXPLICIT_ACCESSORY_PHRASE_RE.search(title):
        return True

    # 2. If the title clearly identifies a main product/appliance/peripheral, it is NOT a spare accessory
    if _MAIN_PRODUCT_IDENTITY_RE.search(title):
        return False

    sub = (record.sub_category or "").strip().lower()
    if sub in ("accessories", "cables", "chargers", "cases", "bags", "spare_parts"):
        return True

    if not _ACCESSORY_SIGNAL_RE.search(title):
        return False

    stripped = _MAIN_DEVICE_WITH_INCLUDED_ACC_RE.sub(" ", title)
    if not _ACCESSORY_SIGNAL_RE.search(stripped):
        return False

    return True


def is_collapsed_multiprice_variant(record: RawProductSnapshot) -> bool:
    """Return True if a WooCommerce variable product has collapsed multiple sizes
    into 1 row storing only the minimum price (without a disambiguating `variant_label`).

    Prevents matching a collapsed 1lb-5lb parent row (priced at 1lb) against
    a specific-size 5lb or 2lb SKU at another store.
    """
    attrs = record.attributes_json or {}
    vcount = attrs.get("variant_count")
    vmin = attrs.get("variant_min_price")
    vmax = attrs.get("variant_max_price")
    vlabel = (attrs.get("variant_label") or "").strip() if isinstance(attrs.get("variant_label"), str) else ""
    try:
        vc = int(vcount) if vcount is not None else 1
        lo = float(vmin) if vmin is not None else 0.0
        hi = float(vmax) if vmax is not None else 0.0
    except (TypeError, ValueError):
        return False

    if vc > 1 and lo > 0 and hi > lo * 1.22:
        # If variant_label explicitly provides a concrete size/weight/count, it IS disambiguated!
        if vlabel:
            vspec = parse_unit_spec(vlabel)
            if vspec.has_package_size():
                return False
        return True
    return False


_BUNDLE_SIGNAL_RE = re.compile(
    r"(?:"
    r"\b(?:bundle|routine|combo|kit|set\s+of|duo|trio|promo\s*pack|value\s*pack|gift\s*set|"
    r"buy\s*\d+\s*get\s*\d+|1\s*\+\s*1|2\s*\+\s*1|\+\s*free|free\s+gift|with\s+free|"
    r"collection|box\s+set|travel\s+set|starter\s+kit)\b|"
    r"(?:باقه|مجموعه|روتين|عرض\s*خاص|عرض\s*التوفير|مجانا|هديه|طقم|\d\s*\+\s*\d)"
    r")",
    re.I,
)


def _is_bundle_or_promo(norm_text: str) -> bool:
    if _BUNDLE_SIGNAL_RE.search(norm_text):
        return True
    # Only flag " + " when joining two separate products (e.g. "Shampoo + Conditioner",
    # "Whey + Creatine", "Cleanser + Serum"), NOT active ingredient pairs like
    # "Tranexamic Acid + Glutathione" or "Pore + Dark Spot" or "D3 + K2".
    if re.search(
        r"\b(?:shampoo|conditioner|serum|cleanser|cream|lotion|wash|toner|whey|protein|creatine|gainer|perfume|splash|mist)\b\s*\+\s*\b(?:shampoo|conditioner|serum|cleanser|cream|lotion|wash|toner|whey|protein|creatine|gainer|perfume|splash|mist|free|gift)\b",
        norm_text,
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# HEALTH & BEAUTY SHARED BRAND NORMALIZATION (EN + AR)
# ---------------------------------------------------------------------------
_HB_BRAND_ALIASES: tuple[tuple[str, str], ...] = (
    # Sports Nutrition & Supplements
    ("optimum nutrition", "optimum_nutrition"),
    ("اوبتيمم نيوترشن", "optimum_nutrition"),
    ("اوبتيمم", "optimum_nutrition"),
    ("muscletech", "muscletech"),
    ("muscle tech", "muscletech"),
    ("ماسل تك", "muscletech"),
    ("muscle add", "muscle_add"),
    ("ماسل اد", "muscle_add"),
    ("big ramy labs", "big_ramy_labs"),
    ("big ramy", "big_ramy_labs"),
    ("بيج رامي", "big_ramy_labs"),
    ("kevin levrone", "kevin_levrone"),
    ("كيفين ليفرون", "kevin_levrone"),
    ("كيفن ليفرون", "kevin_levrone"),
    ("dymatize", "dymatize"),
    ("دايماتيز", "dymatize"),
    ("cellucor", "cellucor"),
    ("سيلوكور", "cellucor"),
    ("nutrex research", "nutrex"),
    ("nutrex", "nutrex"),
    ("نيوتركس", "nutrex"),
    ("applied nutrition", "applied_nutrition"),
    ("ابلايد نيوترشن", "applied_nutrition"),
    ("nutriversum", "nutriversum"),
    ("نيوتريفرسم", "nutriversum"),
    ("organic nation", "organic_nation"),
    ("اورجانيك نيشن", "organic_nation"),
    ("marvelous nutrition", "marvelous_nutrition"),
    ("marvelous", "marvelous_nutrition"),
    ("novogen", "novogen"),
    ("نوفوجين", "novogen"),
    ("neocell", "neocell"),
    ("نيوسيل", "neocell"),
    ("now foods", "now_foods"),
    ("now sports", "now_foods"),
    ("ناو فودز", "now_foods"),
    ("solgar", "solgar"),
    ("سولجار", "solgar"),
    ("puritan's pride", "puritans_pride"),
    ("puritans pride", "puritans_pride"),
    ("بيوريتانز برايد", "puritans_pride"),
    ("بيورتان برايد", "puritans_pride"),
    ("doctor's best", "doctors_best"),
    ("doctors best", "doctors_best"),
    ("دكتورز بيست", "doctors_best"),
    ("solaray", "solaray"),
    ("سولاراي", "solaray"),
    ("nature's bounty", "natures_bounty"),
    ("natures bounty", "natures_bounty"),
    ("نيتشرز باونتي", "natures_bounty"),
    ("nature's way", "natures_way"),
    ("natures way", "natures_way"),
    ("nature made", "nature_made"),
    ("limitless naturals", "limitless"),
    ("limitless", "limitless"),
    ("ليمتلس", "limitless"),
    ("centrum", "centrum"),
    ("سنترم", "centrum"),
    ("yava labs", "yava_labs"),
    ("quamtrax", "quamtrax"),
    ("nutrabolics", "nutrabolics"),
    ("universal nutrition", "universal_nutrition"),
    ("bsn", "bsn"),
    ("usn", "usn"),
    ("allmax", "allmax"),
    ("mutant", "mutant"),
    ("rule 1", "rule_1"),
    ("rule one", "rule_1"),
    ("pureganic", "pureganic"),
    ("max muscle", "max_muscle"),
    ("ماكس ماسل", "max_muscle"),
    ("powerstore", "powerstore"),
    ("california gold nutrition", "california_gold"),
    ("life extension", "life_extension"),
    ("jarrow formulas", "jarrow_formulas"),
    ("natrol", "natrol"),
    ("swanson", "swanson"),
    ("21st century", "21st_century"),
    ("jamieson", "jamieson"),
    ("webber naturals", "webber_naturals"),
    ("vitabiotics", "vitabiotics"),
    ("nordic naturals", "nordic_naturals"),
    ("carlson", "carlson"),
    ("grasberg", "grasberg"),
    ("جراسبرج", "grasberg"),
    ("gnc", "gnc"),
    ("biotech usa", "biotech_usa"),
    ("biotechusa", "biotech_usa"),
    ("scitec nutrition", "scitec_nutrition"),
    ("scitec", "scitec_nutrition"),
    ("bad ass", "bad_ass"),
    ("fa nutrition", "fa_nutrition"),
    ("skull labs", "skull_labs"),
    ("olimp", "olimp"),
    ("ostrovit", "ostrovit"),
    ("challenger nutrition", "challenger"),
    ("red rex", "red_rex"),
    ("evolve", "evolve"),
    # Dermocosmetics, Skincare, Haircare (shared across Beauty & Pharmacy!)
    ("la roche-posay", "la_roche_posay"),
    ("la roche posay", "la_roche_posay"),
    ("لاروش بوزيه", "la_roche_posay"),
    ("لا روش بوزيه", "la_roche_posay"),
    ("cerave", "cerave"),
    ("سيرافي", "cerave"),
    ("vichy", "vichy"),
    ("فيشي", "vichy"),
    ("bioderma", "bioderma"),
    ("بيوديرما", "bioderma"),
    ("eucerin", "eucerin"),
    ("يوسيرين", "eucerin"),
    ("avene", "avene"),
    ("افين", "avene"),
    ("uriage", "uriage"),
    ("يورياج", "uriage"),
    ("cetaphil", "cetaphil"),
    ("سيتافيل", "cetaphil"),
    ("isispharma", "isispharma"),
    ("isis pharma", "isispharma"),
    ("isdin", "isdin"),
    ("ايسدين", "isdin"),
    ("svr", "svr"),
    ("ducray", "ducray"),
    ("دوكراي", "ducray"),
    ("acm", "acm"),
    ("noreva", "noreva"),
    ("filorga", "filorga"),
    ("nuxe", "nuxe"),
    ("caudalie", "caudalie"),
    ("the ordinary", "the_ordinary"),
    ("ذا اورديناري", "the_ordinary"),
    ("cosrx", "cosrx"),
    ("anua", "anua"),
    ("beauty of joseon", "beauty_of_joseon"),
    ("axis-y", "axis_y"),
    ("axis y", "axis_y"),
    ("skin1004", "skin1004"),
    ("some by mi", "some_by_mi"),
    ("starville", "starville"),
    ("ستارفيل", "starville"),
    ("kolagra", "kolagra"),
    ("كولاجرا", "kolagra"),
    ("shaan", "shaan"),
    ("شان", "shaan"),
    ("bobana", "bobana"),
    ("بوبانا", "bobana"),
    ("infinity clinic", "infinity"),
    ("infinity naturals", "infinity"),
    ("infinity", "infinity"),
    ("انفينيتي", "infinity"),
    ("eva cosmetics", "eva"),
    ("eva skin care", "eva"),
    ("eva hair", "eva"),
    ("eva", "eva"),
    ("ايفا", "eva"),
    ("dermaelle", "dermaelle"),
    ("ديرمايل", "dermaelle"),
    ("telofill", "telofill"),
    ("تيلوفيل", "telofill"),
    ("braes", "braes"),
    ("بريس", "braes"),
    ("seropipe", "seropipe"),
    ("سيروبايب", "seropipe"),
    ("hayah laboratories", "hayah"),
    ("hayah labs", "hayah"),
    ("hayah", "hayah"),
    ("حياة", "hayah"),
    ("cleo laboratories", "cleo"),
    ("cleo labs", "cleo"),
    ("cleo", "cleo"),
    ("كليو", "cleo"),
    ("melano pharma", "melano"),
    ("melano", "melano"),
    ("ميلانو", "melano"),
    ("norshek", "norshek"),
    ("نورشك", "norshek"),
    ("neuth", "neuth"),
    ("نيوث", "neuth"),
    ("raw african", "raw_african"),
    ("رو افريكان", "raw_african"),
    ("the hair addict", "the_hair_addict"),
    ("hair addict", "the_hair_addict"),
    ("bless", "bless"),
    ("بليس", "bless"),
    ("bubblzz", "bubblzz"),
    ("بابلز", "bubblzz"),
    ("soul and more", "soul_and_more"),
    ("soul & more", "soul_and_more"),
    ("eparkville", "eparkville"),
    ("parkville", "eparkville"),
    ("باركفيل", "eparkville"),
    ("aleph", "aleph"),
    ("lit up", "lit_up"),
    ("drakon", "drakon"),
    ("glamy lab", "glamy_lab"),
    ("dermactive", "dermactive"),
    ("ديرماكتيف", "dermactive"),
    ("dermatique", "dermatique"),
    ("ديرماتيك", "dermatique"),
    ("argento", "argento"),
    ("ارجنتو", "argento"),
    ("toba", "toba"),
    ("tota", "tota"),
    ("kesh king", "kesh_king"),
    ("strongville", "strongville"),
    ("سترونجفيل", "strongville"),
    ("penduline", "penduline"),
    ("بندولين", "penduline"),
    ("sanosen", "sanosan"),
    ("sanosan", "sanosan"),
    ("mustela", "mustela"),
    ("موستيلا", "mustela"),
    ("sebamed", "sebamed"),
    ("سيباميد", "sebamed"),
    ("vaseline", "vaseline"),
    ("فازلين", "vaseline"),
    ("nivea", "nivea"),
    ("نيفيا", "nivea"),
    ("garnier", "garnier"),
    ("غارنييه", "garnier"),
    ("جارنييه", "garnier"),
    ("l'oreal", "loreal"),
    ("loreal", "loreal"),
    ("لوريال", "loreal"),
    ("maybelline", "maybelline"),
    ("ميبيلين", "maybelline"),
    ("nyx", "nyx"),
    ("essence", "essence"),
    ("catrice", "catrice"),
    ("bourjois", "bourjois"),
    ("flormar", "flormar"),
    ("cybele", "cybele"),
    ("amanda milano", "amanda_milano"),
    ("amanda", "amanda_milano"),
    ("sheglam", "sheglam"),
    ("kiko", "kiko"),
    ("revlon", "revlon"),
    ("rimmel", "rimmel"),
    ("dove", "dove"),
    ("دوف", "dove"),
    ("pantene", "pantene"),
    ("بانتين", "pantene"),
    ("tresemme", "tresemme"),
    ("olaplex", "olaplex"),
    ("kerastase", "kerastase"),
    ("milk shake", "milk_shake"),
    ("milk_shake", "milk_shake"),
    ("chi", "chi"),
    ("bepanthen", "bepanthen"),
    ("بيبانثين", "bepanthen"),
    ("sudocrem", "sudocrem"),
    ("سودوكريم", "sudocrem"),
    ("johnson's", "johnsons"),
    ("johnsons", "johnsons"),
    ("جونسون", "johnsons"),
    # Perfumes & Fragrances
    ("giorgio armani", "giorgio_armani"),
    ("armani", "giorgio_armani"),
    ("ارماني", "giorgio_armani"),
    ("calvin klein", "calvin_klein"),
    ("كالفن كلاين", "calvin_klein"),
    ("jean paul gaultier", "jean_paul_gaultier"),
    ("yves saint laurent", "ysl"),
    ("ysl", "ysl"),
    ("burberry", "burberry"),
    ("بربري", "burberry"),
    ("bvlgari", "bvlgari"),
    ("bulgari", "bvlgari"),
    ("بولغاري", "bvlgari"),
    ("versace", "versace"),
    ("فرزاتشي", "versace"),
    ("christian dior", "dior"),
    ("dior", "dior"),
    ("ديور", "dior"),
    ("chanel", "chanel"),
    ("شانيل", "chanel"),
    ("dolce & gabbana", "dolce_gabbana"),
    ("dolce and gabbana", "dolce_gabbana"),
    ("dolce gabbana", "dolce_gabbana"),
    ("carolina herrera", "carolina_herrera"),
    ("paco rabanne", "paco_rabanne"),
    ("rabanne", "paco_rabanne"),
    ("narciso rodriguez", "narciso_rodriguez"),
    ("givenchy", "givenchy"),
    ("جيفنشي", "givenchy"),
    ("prada", "prada"),
    ("برادا", "prada"),
    ("gucci", "gucci"),
    ("جوتشي", "gucci"),
    ("tom ford", "tom_ford"),
    ("hugo boss", "hugo_boss"),
    ("montblanc", "montblanc"),
    ("mont blanc", "montblanc"),
    ("lancome", "lancome"),
    ("لانكوم", "lancome"),
    ("valentino", "valentino"),
    ("mugler", "mugler"),
    ("thierry mugler", "mugler"),
    ("guess", "guess"),
    ("جيس", "guess"),
    ("lattafa", "lattafa"),
    ("لطافة", "lattafa"),
    ("armaf", "armaf"),
    ("afnan", "afnan"),
    ("rasasi", "rasasi"),
    ("رصاصي", "rasasi"),
    ("assaf", "assaf"),
    ("عساف", "assaf"),
    ("mood fragrances", "mood"),
    ("mood", "mood"),
    ("bath & body works", "bath_and_body_works"),
    ("bath and body works", "bath_and_body_works"),
    ("victoria's secret", "victorias_secret"),
    ("victorias secret", "victorias_secret"),
    ("queen by lord", "queen_by_lord"),
    ("fragrance & fabric", "fragrance_and_fabric"),
)

# Pre-compile boundary-safe patterns for short brands (<=4 chars) to avoid false substring hits
_HB_SHORT_BRAND_PATTERNS: dict[str, re.Pattern[str]] = {
    needle: re.compile(rf"(?:^|[^a-z\u0621-\u064a]){re.escape(needle)}(?=$|[^a-z\u0621-\u064a])", re.I)
    for needle, _ in _HB_BRAND_ALIASES
    if len(needle) <= 4
}

_GENERIC_STORE_BRANDS: frozenset[str] = frozenset({
    "unknown", "other", "generic", "none", "null", "brand", "unbranded",
    "my store", "eva shop", "beseha", "bloom pharmacy", "source beauty",
    "bashrety", "ifit", "mfsupps", "mr vitamins", "protein house",
    "egysupps", "house of supplements", "gofit", "catwa", "zynah",
})

# Bilingual Arabic -> English retail/ingredient glossary for Health & Beauty matching
_HB_AR_TO_EN: tuple[tuple[str, str], ...] = (
    ("واقي شمس", "sunscreen"),
    ("صن بلوك", "sunscreen"),
    ("صن سكرين", "sunscreen"),
    ("غسول للوجه", "facial cleanser"),
    ("غسول وجه", "facial cleanser"),
    ("غسول للبشره", "cleanser"),
    ("غسول", "cleanser"),
    ("مزيل عرق", "deodorant"),
    ("مضاد تعرق", "antiperspirant"),
    ("واي بروتين ايزوليت", "whey protein isolate"),
    ("واي بروتين", "whey protein"),
    ("بروتين ايزوليت", "protein isolate"),
    ("ماس جينر", "mass gainer"),
    ("بري وورك اوت", "pre workout"),
    ("كرياتين مونوهيدرات", "creatine monohydrate"),
    ("كرياتين", "creatine"),
    ("كولاجين بحري", "marine collagen"),
    ("سوبر كولاجين", "super collagen"),
    ("كولاجين", "collagen"),
    ("ماغنيسيوم بيسجليسينات", "magnesium bisglycinate"),
    ("مغنيسيوم بيسجليسينات", "magnesium bisglycinate"),
    ("ماغنيسيوم جليسينات", "magnesium glycinate"),
    ("مغنيسيوم جليسينات", "magnesium glycinate"),
    ("ماغنيسيوم", "magnesium"),
    ("مغنيسيوم", "magnesium"),
    ("اوميجا 3", "omega 3"),
    ("فيتامين د3", "vitamin d3"),
    ("فيتامين سي", "vitamin c"),
    ("فيتامين ب12", "vitamin b12"),
    ("فيتامين", "vitamin"),
    ("مالتي فيتامين", "multivitamin"),
    ("اشواجندا", "ashwagandha"),
    ("بيوتين", "biotin"),
    ("ميلاتونين", "melatonin"),
    ("زنك", "zinc"),
    ("حديد", "iron"),
    ("كالسيوم", "calcium"),
    ("جلوتامين", "glutamine"),
    ("كارنيتين", "carnitine"),
    ("امينو", "amino"),
    ("بروبوليس", "propolis"),
    ("ريتينول", "retinol"),
    ("نياسيناميد", "niacinamide"),
    ("هيالورونيك اسيد", "hyaluronic acid"),
    ("هيالورونيك", "hyaluronic"),
    ("ساليسيليك", "salicylic"),
    ("جليكوليك", "glycolic"),
    ("بانثينول", "panthenol"),
    ("سيراميد", "ceramide"),
    ("سيروم", "serum"),
    ("كريم ليلي", "night cream"),
    ("كريم نهاري", "day cream"),
    ("كريم مرطب", "moisturizing cream"),
    ("مرطب", "moisturizer"),
    ("كريم", "cream"),
    ("لوشن للجسم", "body lotion"),
    ("لوشن", "lotion"),
    ("شامبو ضد القشره", "anti dandruff shampoo"),
    ("شامبو", "shampoo"),
    ("بلسم", "conditioner"),
    ("ماسك للشعر", "hair mask"),
    ("ماسك", "mask"),
    ("تونر", "toner"),
    ("سكراب", "scrub"),
    ("مقشر", "exfoliating"),
    ("ماء ميسيلار", "micellar water"),
    ("ميسيلار", "micellar"),
    ("زيت شعر", "hair oil"),
    ("زيت", "oil"),
    ("صابون", "soap"),
    ("بادي سبلاش", "body splash"),
    ("بادي ميست", "body mist"),
    ("سبراي", "spray"),
    ("رول اون", "roll on"),
    ("او دي بارفيوم", "edp"),
    ("او دي تواليت", "edt"),
    ("برفيوم", "perfume"),
    ("عطر", "perfume"),
    ("تفتيح", "whitening"),
    ("مضاد للتجاعيد", "anti aging"),
    ("للشعر", "hair"),
    ("للبشره الدهنيه", "oily skin"),
    ("للبشره الجافه", "dry skin"),
    ("للبشره الحساسه", "sensitive skin"),
    ("للوجه", "face"),
    ("للجسم", "body"),
    ("للعيون", "eye"),
    ("للعين", "eye"),
    ("للنساء", "women"),
    ("للرجال", "men"),
    ("للاطفال", "kids"),
)

_HB_BASE_STOPWORDS: frozenset[str] = frozenset({
    "the", "with", "and", "for", "from", "by", "in", "on", "of", "to", "a", "an",
    "new", "original", "official", "egypt", "authentic", "imported", "usa", "uk",
    "best", "price", "benefits", "ingredients", "support", "supports", "healthy",
    "health", "daily", "care", "formula", "advanced", "extra", "strength", "plus",
    "high", "quality", "natural", "pure", "organic", "free", "size", "bottle", "jar",
    "tube", "box", "pack", "pouch", "sachet", "sachets", "tabs", "tab", "tablet",
    "tablets", "cap", "caps", "capsule", "capsules", "vegcaps", "softgels", "softgel",
    "serv", "serving", "servings", "scoop", "scoops", "ml", "gm", "gms", "g", "kg",
    "lb", "lbs", "oz", "fl", "mg", "mcg", "iu", "liter", "litre", "l",
    "supplement", "dietary", "nutrition", "nutritional", "pharma", "laboratories",
    "labs", "lab", "cosmetics", "skincare", "skin", "personal",
})

# Flavor tokens stripped ONLY on sports-nutrition supplements (e.g. Whey Protein
# Chocolate vs Vanilla), NEVER on beauty/body care where scent is the SKU!
_SUPPLEMENT_FLAVOR_STOPWORDS: frozenset[str] = frozenset({
    "unflavored", "unflavoured", "chocolate", "vanilla", "strawberry", "banana",
    "mango", "watermelon", "pineapple", "peach", "berry", "berries", "cherry",
    "orange", "lemon", "lime", "apple", "grape", "coconut", "caramel", "mocha",
    "coffee", "cookies", "fruit", "punch", "raspberry", "blueberry", "pink", "lemonade",
    "tropical", "iced", "milkshake", "double", "rich", "extreme", "milk",
})

_SUPPLEMENT_CONTEXT_RE = re.compile(
    r"\b(?:whey|protein|isolate|casein|creatine|gainer|pre[\s-]?workout|bcaa|eaa|amino|"
    r"glutamine|carnitine|collagen|electrolyte|hydration|citrulline|arginine|beta[\s-]?alanine)\b",
    re.I,
)

# Product form tokens that MUST remain distinct in Health (bar != powder != liquid != gummies)
_HEALTH_FORM_RE = re.compile(
    r"\b(powder|liquid|drops|syrup|gummies|gummy|bar|bars|shot|shots|effervescent|chewable|lozenges|spray|gel|cream|lotion|serum|shampoo|conditioner|oil|soap|cleanser|wash|toner|scrub|mask|sunscreen|deodorant|mist|splash)\b",
    re.I,
)

# Perfume concentration markers that MUST remain distinct (EDP != EDT != Parfum != Mist)
_PERFUME_CONC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("extrait", re.compile(r"\b(?:extrait\s+de\s+parfum|elixir)\b", re.I)),
    ("edp", re.compile(r"\b(?:eau\s+de\s+parfum|e\.?d\.?p\.?)\b", re.I)),
    ("edt", re.compile(r"\b(?:eau\s+de\s+toilette|e\.?d\.?t\.?)\b", re.I)),
    ("edc", re.compile(r"\b(?:eau\s+de\s+cologne|e\.?d\.?c\.?|cologne)\b", re.I)),
    ("mist", re.compile(r"\b(?:body\s+mist|body\s+splash|hair\s+mist|fragrance\s+mist|mist|splash)\b", re.I)),
    ("parfum", re.compile(r"\b(?:parfum|intense\s+parfum)\b", re.I)),
)


def resolve_hb_brand(record: RawProductSnapshot) -> Optional[str]:
    """Resolve canonical Health/Beauty brand from brand field or title (EN & AR)."""
    raw_brand = normalize_unit_text(record.brand or "").strip()
    norm_title = normalize_unit_text(record.product_title or "")

    for haystack in (raw_brand, norm_title):
        if not haystack:
            continue
        for needle, canonical in _HB_BRAND_ALIASES:
            if needle in _HB_SHORT_BRAND_PATTERNS:
                if _HB_SHORT_BRAND_PATTERNS[needle].search(haystack):
                    return canonical
            elif needle in haystack:
                return canonical

    if raw_brand and raw_brand not in _GENERIC_STORE_BRANDS:
        # Clean trailing punctuation (e.g. "Solaray,")
        cleaned = re.sub(r"[^a-z0-9\s&'-]", " ", raw_brand).strip()
        if cleaned and len(cleaned) >= 3 and cleaned not in _GENERIC_STORE_BRANDS:
            slug = normalize_snake_slug(cleaned, max_len=28)
            if slug and slug != "unknown":
                return slug
    return None


def _translate_hb_title(title: str) -> str:
    s = normalize_unit_text(title)
    # Strip trailing Arabic SEO pipe/dash explanations (e.g. "سعر + مكونات + فوائد | ...")
    s = re.sub(r"سعر\s*\+\s*مكونات\s*\+\s*فوائد", " ", s)
    # Cut after " – " long Arabic benefit descriptions (>35 chars after em/en-dash)
    if " – " in s:
        head, tail = s.split(" – ", 1)
        if len(head.strip()) >= 12 and len(tail.strip()) >= 25 and re.search(r"[\u0621-\u064a]", tail):
            # Preserve any size/count mentioned in tail before dropping prose
            size_tail = " ".join(
                re.findall(r"\d+(?:\.\d+)?\s*(?:ml|g|kg|lb|lbs|l|mg|mcg|iu|caps?|tabs?|قرص|اقراص|كبسوله|كبسولات|مل|جم|جرام|لتر)", tail)
            )
            s = f"{head} {size_tail}"
    for ar, en in _HB_AR_TO_EN:
        if ar in s:
            s = s.replace(ar, f" {en} ")
    return re.sub(r"\s+", " ", s).strip()


def _hb_quantized_size_token(uspec: UnitSpec) -> Optional[str]:
    """Canonical size token for Health/Beauty with 10g rounding on tubs >= 900g
    so `2 lbs` (907g) / `908g` / `900g` and `5 lbs` (2268g) / `2.27 kg` (2270g) align,
    while exact smaller sizes (`30ml` vs `50ml`, `200ml` vs `250ml`, `300g` vs `500g`,
    `60 caps` vs `120 caps`) stay strictly isolated.
    """
    if uspec.weight_g is not None and uspec.weight_g > 0:
        wg = uspec.weight_g
        if wg >= 890:
            # Map common lb tubs cleanly: 2lb (~907g), 5lb (~2268g), 10lb (~4536g)
            if 895 <= wg <= 920:
                wg = 907
            elif 2240 <= wg <= 2290:
                wg = 2270
            else:
                wg = int(round(wg / 10.0) * 10)
        tok = f"w{wg}g"
    elif uspec.volume_ml is not None and uspec.volume_ml > 0:
        tok = f"v{uspec.volume_ml}ml"
    elif uspec.unit_count is not None and uspec.unit_count > 0:
        kind = uspec.unit_kind or "cnt"
        tok = f"c{uspec.unit_count}{kind}"
    else:
        return None
    if uspec.pack_count > 1:
        tok = f"{tok}_x{uspec.pack_count}"
    return tok


def extract_health_beauty_features(
    record: RawProductSnapshot,
) -> Optional[tuple[Optional[str], Optional[str], Optional[str], list[str]]]:
    """Extract `(exact_sized_key, sizeless_line_key, strict_block_id, core_tokens)` for Health & Beauty.

    - `exact_sized_key`: Present when exact package size (`weight_g`/`volume_ml`/`unit_count`) is found.
    - `sizeless_line_key`: High-specificity `(brand, sorted_core_tokens[>=3], conc, gender, dosage)`
      for stores that omit `ml`/`caps` on standard single-SKU products (guarded by tight <= 1.65x
      price ratio + `units_conflict` blocker + no <=25ml travel decants!).
    - `strict_block_id`: Present when exact size is found, for Pass 2 similarity matching.
    """
    if is_collapsed_multiprice_variant(record) or is_accessory_listing(record):
        return None

    brand = resolve_hb_brand(record)
    if not brand:
        return None

    attrs = record.attributes_json or {}
    vlabel = attrs.get("variant_label") if isinstance(attrs.get("variant_label"), str) else None
    norm_raw = normalize_unit_text(record.product_title or "")
    if _is_bundle_or_promo(norm_raw):
        return None

    uspec: UnitSpec = parse_unit_spec(record.product_title, variant_label=vlabel, attributes=attrs)
    if uspec.has_ambiguous_multi_size:
        return None

    size_tok = _hb_quantized_size_token(uspec)

    translated = _translate_hb_title(record.product_title)
    if "|" in translated:
        segs = [seg.strip() for seg in translated.split("|") if seg.strip()]
        best_seg = segs[0]
        if len(segs) > 1 and len(segs[0].split()) <= 2:
            best_seg = segs[1]
        translated = best_seg

    perfume_conc: Optional[str] = None
    for conc_name, pat in _PERFUME_CONC_PATTERNS:
        if pat.search(translated):
            perfume_conc = conc_name
            break

    form_tag = ""
    if fm := _HEALTH_FORM_RE.search(translated):
        form_tag = fm.group(1).lower()

    gender_tag: Optional[str] = None
    if re.search(r"\b(?:for\s+women|women'?s?|pour\s+femme|femme|her|ladies)\b", translated):
        gender_tag = "women"
    elif re.search(r"\b(?:for\s+men|men'?s?|pour\s+homme|homme|him)\b", translated):
        gender_tag = "men"

    brand_words = set(brand.split("_"))
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:ml|mls|l|liter|litre|g|gm|gms|grams?|kg|kgs|lb|lbs|oz|mg|mcg|iu|caps?|capsules?|vegcaps?|softgels?|tabs?|tablets?|serv\.?|servings?|scoops?|pcs?|pieces?|sachets?|bags?)\b",
        " ",
        translated,
    )
    raw_tokens = re.findall(r"[a-z0-9]+", cleaned)

    is_supp = bool(_SUPPLEMENT_CONTEXT_RE.search(translated))
    active_stopwords = (_HB_BASE_STOPWORDS | _SUPPLEMENT_FLAVOR_STOPWORDS) if is_supp else _HB_BASE_STOPWORDS

    core_tokens: list[str] = []
    for tok in raw_tokens:
        if tok in brand_words or tok in active_stopwords:
            continue
        if tok in ("men", "women", "homme", "femme", "pour", "eau", "parfum", "toilette", "edp", "edt", "edc"):
            continue
        if len(tok) == 1 and tok not in ("c", "d", "e", "a", "b", "k"):
            continue
        if tok.isdigit() and 1900 < int(tok) < 2030:
            continue
        if tok not in core_tokens:
            core_tokens.append(tok)

    if len(core_tokens) == 0:
        return None
    if len(core_tokens) == 1 and not uspec.dosage_tag and not perfume_conc:
        if core_tokens[0] in {
            "shampoo", "conditioner", "cream", "serum", "lotion", "cleanser", "gel",
            "soap", "oil", "mask", "toner", "scrub", "sunscreen", "deodorant",
            "perfume", "mist", "splash", "whey", "protein", "creatine", "collagen",
            "vitamin", "magnesium", "zinc", "omega", "biotin", "iron", "calcium",
            "amino", "glutamine", "bcaa", "pre", "workout", "gainer",
        }:
            return None

    selected_tokens = sorted(core_tokens[:5])
    base_parts = ["hb", brand]
    base_parts.extend(selected_tokens)
    if perfume_conc:
        base_parts.append(perfume_conc)
    if gender_tag and (perfume_conc or "deodorant" in selected_tokens or "antiperspirant" in selected_tokens):
        base_parts.append(gender_tag)
    if uspec.dosage_tag:
        base_parts.append(uspec.dosage_tag)

    exact_key: Optional[str] = None
    block_id: Optional[str] = None
    if size_tok:
        exact_key = normalize_snake_slug("_".join(base_parts + [size_tok]), max_len=160)
        block_id = f"{brand}|{size_tok}|{uspec.dosage_tag or ''}|{perfume_conc or ''}|{form_tag}|{gender_tag or ''}"

    # High-specificity sizeless key: requires >= 3 core tokens (or >= 2 + perfume_conc/dosage),
    # and NEVER emitted for tiny travel decants (<= 25ml) or multi-packs (pack_count > 1).
    sizeless_key: Optional[str] = None
    is_tiny_decant = (uspec.volume_ml is not None and uspec.volume_ml <= 25 and perfume_conc is not None)
    if not is_tiny_decant and uspec.pack_count == 1:
        if len(selected_tokens) >= 3 or (len(selected_tokens) >= 2 and (perfume_conc or uspec.dosage_tag)):
            sizeless_key = normalize_snake_slug("hbl_" + "_".join(base_parts[1:]), max_len=160)

    if not exact_key and not sizeless_key:
        return None
    return exact_key, sizeless_key, block_id, core_tokens


def compute_health_beauty_key(record: RawProductSnapshot) -> Optional[str]:
    """Compute a high-precision canonical key for `health` & `beauty` products."""
    feats = extract_health_beauty_features(record)
    if not feats:
        return None
    return feats[0] or feats[1]


# ---------------------------------------------------------------------------
# FOOTWEAR MATCHER (Parent-level model matching across fashion & sports)
# ---------------------------------------------------------------------------
_FOOTWEAR_BRANDS: tuple[tuple[str, str], ...] = (
    ("under armour", "under_armour"),
    ("underarmor", "under_armour"),
    ("اندر ارمر", "under_armour"),
    ("new balance", "new_balance"),
    ("نيو بالانس", "new_balance"),
    ("skechers", "skechers"),
    ("سكيتشرز", "skechers"),
    ("adidas", "adidas"),
    ("اديداس", "adidas"),
    ("nike", "nike"),
    ("نايك", "nike"),
    ("نايكي", "nike"),
    ("jordan", "jordan"),
    ("جوردان", "jordan"),
    ("puma", "puma"),
    ("بوما", "puma"),
    ("reebok", "reebok"),
    ("ريبوك", "reebok"),
    ("asics", "asics"),
    ("اسيكس", "asics"),
    ("converse", "converse"),
    ("كونفرس", "converse"),
    ("vans", "vans"),
    ("فانز", "vans"),
    ("fila", "fila"),
    ("فيلا", "fila"),
    ("umbro", "umbro"),
    ("kappa", "kappa"),
    ("lotto", "lotto"),
    ("anta", "anta"),
    ("salomon", "salomon"),
    ("hoka", "hoka"),
    ("brooks", "brooks"),
    ("saucony", "saucony"),
    ("mizuno", "mizuno"),
    ("crocs", "crocs"),
    ("كروكس", "crocs"),
    ("birkenstock", "birkenstock"),
    ("timberland", "timberland"),
    ("clarks", "clarks"),
    ("geox", "geox"),
    ("ecco", "ecco"),
    ("aldo", "aldo"),
    ("الدو", "aldo"),
    ("lacoste", "lacoste"),
    ("tommy hilfiger", "tommy_hilfiger"),
    ("calvin klein", "calvin_klein"),
    ("zaxy", "zaxy"),
    ("ipanema", "ipanema"),
    ("rider", "rider"),
    ("havaianas", "havaianas"),
    ("dejavu", "dejavu"),
    ("activ", "activ"),
    ("achilles", "achilles"),
    ("diadora", "diadora"),
    ("joma", "joma"),
    ("kelme", "kelme"),
    ("mizuno", "mizuno"),
    ("on running", "on_running"),
)

_FOOTWEAR_POSITIVE_RE = re.compile(
    r"(?:"
    r"\b(?:shoe|shoes|sneaker|sneakers|trainer|trainers|boot|boots|sandal|sandals|"
    r"slipper|slippers|slide|slides|loafer|loafers|cleat|cleats|clog|clogs|"
    r"flip[\s-]?flop|flip[\s-]?flops|espadrille|moccasin|heel|heels|pump|pumps|"
    r"slip[\s-]?ins?|running\s+shoe|football\s+boot|turf|fg/ag|ag/fg|tf|ic|"
    r"court\s+vision|downshifter|air\s+force|air\s+max|dunk|pegasus|revolution\s+\d|"
    r"ultraboost|superstar|stan\s+smith|gazelle|samba|campus|grand\s+court|duramo|runfalcon|"
    r"response\s+runner|ultimashow|gamecourt|urban\s+court|vl\s+court|breaknet|"
    r"glide[\s-]?step|arch\s+fit|go\s+walk|go\s+run|uno\s+stand|bounder|bobs\s+squad|d'?lites|"
    r"suede\s+classic|smash\s+\d|ca\s+pro|rs[\s-]?x|vitoria|solarstrike|velocity\s+nitro|court\s+classic|"
    r"gel[\s-]?kayano|gel[\s-]?nimbus|gel[\s-]?cumulus|gel[\s-]?contend|gel[\s-]?excite|dynablast|novablast|superblast|gt[\s-]?1000|gt[\s-]?2000|"
    r"club\s+c|chuck\s+taylor|old\s+skool|classic\s+clog)\b|"
    r"(?:حذاء|احذيه|كوتشي|سنيكرز|صندل|شبشب|بوت|شوز)"
    r")",
    re.I,
)

_FOOTWEAR_NON_SHOE_RE = re.compile(
    r"(?:"
    r"\b(?:t[\s-]?shirt|tee|polo|shirt|jersey|short|shorts|pant|pants|trouser|trousers|"
    r"jogger|joggers|legging|leggings|tight|tights|hoodie|sweatshirt|jacket|coat|vest|"
    r"tracksuit|track\s+suit|swimwear|swimsuit|bra|sports\s+bra|sock|socks|cap|hat|beanie|"
    r"bag|backpack|duffel|duffle|gym\s+sack|sack|wallet|belt|glove|gloves|shin\s+guard|"
    r"football|basketball|volleyball|racket|racquet|bottle|shaker|towel|wristband|"
    r"headband|lace|laces|shoelace|insole|insoles|cleaner|spray|kit|set|dress|skirt|"
    r"top|tank|tank\s+top|pullover|cardigan|sweater|brief|boxer|underwear)\b|"
    r"(?:تيشيرت|قميص|شورت|بنطلون|جاكيت|سويت\s*شيرت|هودي|تريننج|شراب|جوارب|شنطه|حقيبه|"
    r"كاب|قبعه|فستان|جيبه|بلوزه|كره|قفازات|رباط)"
    r")",
    re.I,
)

# Manufacturer footwear style codes (e.g. Nike DH2987-100 / FQ8112, Adidas ID3690 / GX0709,
# Skechers 232040 / 220885, Puma 395205-01, New Balance MR530SG)
_FOOTWEAR_STYLE_CODE_RE = re.compile(
    r"(?:^|[^a-z0-9])("
    r"[a-z]{2}\d{4}(?:-\d{3})?|"       # Nike/Adidas: DH2987, FQ8112-001, ID3690, GX0709
    r"[a-z]{1,2}\d{3,4}[a-z]{1,2}|"   # NB/Asics: MR530SG, 1011B547
    r"\d{6}(?:-\d{2})?"               # Skechers/Puma 6-digit style: 232040, 395205-01
    r")(?=$|[^a-z0-9])",
    re.I,
)

_FOOTWEAR_COLORS: frozenset[str] = frozenset({
    "black", "white", "grey", "gray", "blue", "navy", "red", "green", "yellow", "orange",
    "pink", "purple", "violet", "brown", "beige", "tan", "khaki", "cream", "ivory",
    "silver", "gold", "bronze", "maroon", "burgundy", "olive", "teal", "cyan", "mint",
    "coral", "peach", "lilac", "lavender", "charcoal", "offwhite", "multicolor", "multi",
    "blk", "wht", "nvy", "gry", "blu", "grn", "pnk", "brn", "bge", "slv", "gld",
    "dark", "light", "bright", "neon", "pastel", "metallic", "triple", "core", "cloud",
    "chalk", "sand", "stone", "taupe", "camel", "cognac", "espresso", "chocolate", "nude",
    "leopard", "zebra", "camo", "patent", "suede", "leather", "satin", "mesh", "canvas",
})

_FOOTWEAR_STOPWORDS: frozenset[str] = frozenset({
    "the", "with", "and", "for", "from", "by", "in", "on", "of", "to", "a", "an",
    "shoe", "shoes", "sneaker", "sneakers", "trainer", "trainers", "footwear",
    "running", "road", "training", "walking", "sport", "sports", "athletic", "casual",
    "lifestyle", "outdoor", "indoor", "basketball", "football", "tennis", "handball",
    "men", "mens", "man", "women", "womens", "woman", "ladies", "lady", "unisex",
    "kids", "kid", "boys", "boy", "girls", "girl", "youth", "junior", "jr", "child",
    "adult", "originals", "original", "official", "new", "egypt", "eg", "eu", "uk", "us",
    "size", "cm", "mm", "pair", "comfortable", "comfort", "lightweight", "breathable",
    "slip", "ins", "hands", "free", "memory", "foam", "air", "cooled",
    "faux", "side", "logo", "perforated", "upper", "lace", "laced", "laceup", "velcro",
    "strap", "cushioned", "cushioning", "padded", "knit", "knitted", "woven", "synthetic",
    "rubber", "sole", "outsole", "midsole", "insole", "waterproof", "fashion", "everyday",
    "mn", "nn", "wmns", "wmn", "gs", "ps", "td", "nk", "df", "unisexs", "mens", "womens",
}) | _FOOTWEAR_COLORS


def is_footwear_record(record: RawProductSnapshot) -> bool:
    """Return True if record is a confirmed footwear product in `fashion` or `sports`."""
    cat = effective_category(record)
    if cat not in ("fashion", "sports"):
        return False
    title = normalize_unit_text(record.product_title or "")
    sub = (record.sub_category or "").strip().lower()
    if _FOOTWEAR_NON_SHOE_RE.search(title):
        return False
    if any(k in sub for k in ("shoe", "sneaker", "footwear", "boot", "sandal", "slipper")):
        return True
    return bool(_FOOTWEAR_POSITIVE_RE.search(title))


def resolve_footwear_brand(record: RawProductSnapshot) -> Optional[str]:
    raw_brand = normalize_unit_text(record.brand or "").strip()
    norm_title = normalize_unit_text(record.product_title or "")
    for haystack in (raw_brand, norm_title):
        if not haystack:
            continue
        for needle, canonical in _FOOTWEAR_BRANDS:
            if needle in haystack:
                return canonical
    return None


def _footwear_gender_bucket(norm_title: str, sub_category: str, variant_label: str = "") -> str:
    combined = f"{norm_title} {sub_category.lower()} {normalize_unit_text(variant_label)}"
    if re.search(r"\b(?:kids?|boys?|girls?|youth|junior|jr|infant|toddler|children|اطفال|ولادي|بناتي)\b", combined):
        return "kids"
    has_women = bool(
        re.search(r"\b(?:women'?s?|woman|ladies|female|wmn|wmns|حريمي|نسائي|للسيدات|للنساء)\b", combined)
        or re.search(r"(?:^|\s)w\s+(?:nike|adidas|puma|reebok|asics|skechers|new\s+balance)\b", norm_title)
    )
    has_men = bool(
        re.search(r"\b(?:men'?s?|man|male|رجالي|للرجال)\b", combined)
        or re.search(r"(?:^|\s)m\s+(?:nike|adidas|puma|reebok|asics|skechers|new\s+balance)\b", norm_title)
    )
    if has_women and not has_men:
        return "women"
    if has_men and not has_women:
        return "men"
    return "adult"


def extract_footwear_features(
    record: RawProductSnapshot,
) -> Optional[tuple[Optional[str], Optional[str], Optional[str], str, str, list[str]]]:
    """Return `(style_code_key, exact_gender_model_key, adult_neutral_model_key, gender, block_id, core_tokens)`."""
    if not is_footwear_record(record):
        return None

    brand = resolve_footwear_brand(record)
    if not brand:
        return None

    raw_title = record.product_title or ""
    clean_raw = re.split(r"\s+—\s+", raw_title, maxsplit=1)[0]
    norm = normalize_unit_text(clean_raw)
    attrs = record.attributes_json or {}
    vlabel = attrs.get("variant_label") if isinstance(attrs.get("variant_label"), str) else ""
    gender = _footwear_gender_bucket(norm, record.sub_category or "", vlabel)
    age_guard = "kids" if gender == "kids" else "adult"

    style_key: Optional[str] = None
    no_store_sku = re.sub(r"\|\s*jo\d+-\d+", " ", norm)
    for m in _FOOTWEAR_STYLE_CODE_RE.finditer(no_store_sku):
        code = m.group(1).lower().split("-")[0]
        if code.isdigit():
            if brand not in ("skechers", "puma"):
                continue
            if code.startswith(("19", "20", "00")):
                continue
        if len(code) >= 5:
            style_key = normalize_snake_slug(f"fw_sku_{brand}_{age_guard}_{code}", max_len=120)
            break

    model_text = re.split(r"[|]", norm, maxsplit=1)[0]
    model_text = re.sub(r"\b(?:eu|uk|us|size)\s*\d{1,2}(?:\.\d)?\b", " ", model_text)
    model_text = re.sub(r"\b(?:3[5-9]|4[0-8])(?:\.5)?\b", " ", model_text)
    model_text = re.sub(r"[^a-z0-9\s]", " ", model_text)

    if re.search(r"\b(?:boot|boots|fg|ag|tf|cleat|cleats)\b", model_text):
        ftype = "boot"
    elif re.search(r"\b(?:sandal|sandals|slide|slides|slipper|slippers|flip|flop|clog|clogs)\b", model_text):
        ftype = "sandal"
    elif re.search(r"\b(?:heel|heels|pump|pumps|loafer|loafers|moccasin)\b", model_text):
        ftype = "dress"
    else:
        ftype = "sneaker"

    brand_parts = set(brand.split("_"))
    tokens: list[str] = []
    for tok in model_text.split():
        if tok in brand_parts or tok in _FOOTWEAR_STOPWORDS:
            continue
        if tok in ("boot", "boots", "sandal", "sandals", "slide", "slides", "slipper", "slippers", "flip", "flop", "clog", "clogs", "heel", "heels", "loafer", "loafers"):
            continue
        if len(tok) == 1 and not tok.isdigit():
            continue
        if tok not in tokens:
            tokens.append(tok)

    exact_model_key: Optional[str] = None
    neutral_model_key: Optional[str] = None
    has_strong_single = len(tokens) == 1 and bool(re.fullmatch(r"(?:[a-z]{0,3}\d{3,4}[a-z]?|\d{3,4}[a-z]?)", tokens[0]))
    if len(tokens) >= 2 or has_strong_single:
        core = tokens[:4]
        exact_model_key = normalize_snake_slug(
            f"fw_mod_{brand}_{gender}_{ftype}_{'_'.join(core)}",
            max_len=140,
        )
        # Neutral adult key lets `adult` (gender-unstated) match `men`/`women` cleanly
        # while `matcher.py` explicitly blocks `men` vs `women` conflict!
        if age_guard == "adult":
            neutral_model_key = normalize_snake_slug(
                f"fw_mod_{brand}_adult_{ftype}_{'_'.join(core)}",
                max_len=140,
            )

    block_id = f"{brand}|{age_guard}|{ftype}"
    return style_key, exact_model_key, neutral_model_key, gender, block_id, tokens


def compute_footwear_keys(record: RawProductSnapshot) -> tuple[Optional[str], Optional[str]]:
    """Return `(style_code_key, model_name_key)` for parent-level footwear matching."""
    feats = extract_footwear_features(record)
    if not feats:
        return None, None
    return feats[0], feats[1]
