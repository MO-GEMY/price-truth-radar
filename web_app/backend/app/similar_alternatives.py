"""Dynamic, zero-storage-bloat "Similar Alternatives in the Same Price Bracket" engine.

Runs ONLY when a product has 0 exact cross-store matches (`alternatives == []`).
Uses existing GIN `pg_trgm` indexes on `gold.mart_product_verdicts` (`search_document`
and `LOWER(product_title)`) in a single fast SQL round-trip (< 80ms target), then
enforces strict functional subtype equivalence, accessory-vs-main-product isolation,
price-bracket preference (±20%, widening to ±30% only if < 3 strong matches), and
per-store diversity (1 top candidate per other store, returning 2..6 or empty list).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.bilingual_search import canonicalize_bilingual_text, normalize_arabic_text
from app.schemas import ProductVerdictItem, SimilarAlternativeItem


@dataclass(frozen=True)
class SubtypeSpec:
    code: str
    label_en: str
    label_ar: str
    match_re: re.Pattern[str]
    # Compact search_document LIKE patterns (matched via GIN pg_trgm index!)
    sql_like_patterns: tuple[str, ...]
    # Sub-categories that strongly confirm this subtype when title is terse
    sub_categories: frozenset[str] = frozenset()


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


# Ordered from most specific to more general so compound subtypes win
# (e.g. "gaming mouse" before "gaming", "air fryer" before "air conditioner",
# "hand blender" before "blender", "deep freezer" before "refrigerator").
_SUBTYPE_SPECS: tuple[SubtypeSpec, ...] = (
    # --- HOME APPLIANCES ---
    SubtypeSpec(
        "air_fryer",
        "Air Fryer",
        "قلاية هوائية",
        _rx(r"(?:\bair\s*fryer\b|\bfryer\b|قلايه\s*هوائيه|قلايه\s*بدون\s*زيت|اير\s*فراير)"),
        ("%air fryer%", "%قلايه%", "%fryer%"),
    ),
    SubtypeSpec(
        "air_conditioner",
        "Air Conditioner",
        "تكييف هواء",
        _rx(r"(?:\bair\s*conditioner\b|\bsplit\s*ac\b|\binverter\s*ac\b|\b\d(?:\.\d+)?\s*hp\b|تكييف)"),
        ("%air conditioner%", "%تكييف%", "%split%"),
        frozenset({"air_conditioners", "split_air_conditioners"}),
    ),
    SubtypeSpec(
        "dishwasher",
        "Dishwasher",
        "غسالة أطباق",
        _rx(r"(?:\bdishwasher\b|\bdish\s*washer\b|غساله\s*اطباق|غساله\s*صحون)"),
        ("%dishwasher%", "%غساله اطباق%", "%غساله صحون%"),
        frozenset({"dishwashers"}),
    ),
    SubtypeSpec(
        "washing_machine",
        "Washing Machine",
        "غسالة ملابس",
        _rx(r"(?:\bwashing\s*machine\b|\bwasher\b|\bfront\s*load\b|\btop\s*load\b|غساله\s*ملابس|غساله\s*اوتوماتيك|غساله\s*فوق|غساله)"),
        ("%washing machine%", "%غساله%", "%washer%"),
        frozenset({"washing_machines"}),
    ),
    SubtypeSpec(
        "deep_freezer",
        "Deep Freezer",
        "ديب فريزر",
        _rx(r"(?:\bdeep\s*freezer\b|\bchest\s*freezer\b|\bupright\s*freezer\b|ديب\s*فريزر|فريزر)"),
        ("%freezer%", "%فريزر%"),
        frozenset({"deep_freezers", "freezers"}),
    ),
    SubtypeSpec(
        "refrigerator",
        "Refrigerator",
        "ثلاجة",
        _rx(r"(?:\brefrigerator\b|\bfridge\b|\bno\s*frost\b|ثلاجه|تلاجه)"),
        ("%refrigerator%", "%fridge%", "%ثلاجه%", "%تلاجه%"),
        frozenset({"refrigerators"}),
    ),
    SubtypeSpec(
        "microwave",
        "Microwave",
        "ميكروويف",
        _rx(r"(?:\bmicrowave\b|ميكروويف|ميكرويف|مايكروويف)"),
        ("%microwave%", "%ميكروويف%", "%ميكرويف%"),
        frozenset({"microwaves"}),
    ),
    SubtypeSpec(
        "built_in_hob",
        "Built-in Hob",
        "مسطح بلت إن",
        _rx(r"(?:\bbuilt[\s-]?in\s*(?:gas\s*|electric\s*|ceramic\s*)?hob\b|\bgas\s*hob\b|\bceramic\s*hob\b|مسطح\s*بلت|مسطح\s*غاز)"),
        ("%hob%", "%مسطح%"),
    ),
    SubtypeSpec(
        "built_in_oven",
        "Oven",
        "فرن",
        _rx(r"(?:\bbuilt[\s-]?in\s*oven\b|\belectric\s*oven\b|\bgas\s*oven\b|\btoaster\s*oven\b|\boven\b|فرن\s*بلت|فرن\s*كهربائ|فرن)"),
        ("%oven%", "%فرن%"),
        frozenset({"ovens"}),
    ),
    SubtypeSpec(
        "gas_cooker",
        "Cooker",
        "بوتاجاز",
        _rx(r"(?:\bgas\s*cooker\b|\bcooker\b|\b\d\s*burners?\b|بوتاجاز|بوتجاز)"),
        ("%cooker%", "%بوتاجاز%", "%بوتجاز%"),
        frozenset({"cookers"}),
    ),
    SubtypeSpec(
        "water_heater",
        "Water Heater",
        "سخان مياه",
        _rx(r"(?:\bwater\s*heater\b|سخان\s*مياه|سخان\s*غاز|سخان\s*كهربا|سخان)"),
        ("%water heater%", "%سخان%"),
        frozenset({"water_heaters"}),
    ),
    SubtypeSpec(
        "water_cooler",
        "Water Dispenser",
        "مبرد مياه",
        _rx(r"(?:\bwater\s*cooler\b|\bwater\s*dispenser\b|مبرد\s*مياه|ديسبنسر)"),
        ("%water cooler%", "%water dispenser%", "%مبرد مياه%"),
    ),
    SubtypeSpec(
        "vacuum_cleaner",
        "Vacuum Cleaner",
        "مكنسة كهربائية",
        _rx(r"(?:\bvacuum\s*cleaner\b|\bcanister\s*vacuum\b|\bstick\s*vacuum\b|\brobot\s*vacuum\b|\bvacuum\b|مكنسه)"),
        ("%vacuum%", "%مكنسه%"),
        frozenset({"vacuums"}),
    ),
    SubtypeSpec(
        "espresso_coffee_maker",
        "Coffee Maker",
        "ماكينة قهوة",
        _rx(r"(?:\bespresso\s*machine\b|\bcoffee\s*maker\b|\bcoffee\s*machine\b|\bturkish\s*coffee\s*maker\b|ماكينه\s*قهوه|صانعه\s*قهوه|كنكه\s*كهربا)"),
        ("%coffee maker%", "%espresso%", "%coffee machine%", "%قهوه%"),
    ),
    SubtypeSpec(
        "kettle",
        "Electric Kettle",
        "غلاية مياه",
        _rx(r"(?:\bkettle\b|غلايه|كاتل)"),
        ("%kettle%", "%غلايه%", "%كاتل%"),
    ),
    SubtypeSpec(
        "hand_blender",
        "Hand Blender",
        "هاند بلندر",
        _rx(r"(?:\bhand\s*blender\b|\bimmersion\s*blender\b|هاند\s*بلندر)"),
        ("%hand blender%", "%هاند بلندر%"),
    ),
    SubtypeSpec(
        "food_processor",
        "Food Processor",
        "محضر طعام",
        _rx(r"(?:\bfood\s*processor\b|محضر\s*طعام|كيتشن\s*ماشين)"),
        ("%food processor%", "%محضر طعام%"),
    ),
    SubtypeSpec(
        "blender",
        "Blender",
        "خلاط",
        _rx(r"(?:\bblender\b|خلاط)"),
        ("%blender%", "%خلاط%"),
        frozenset({"blenders"}),
    ),
    SubtypeSpec(
        "chopper",
        "Food Chopper",
        "كبة",
        _rx(r"(?:\bchopper\b|\bmincer\b|كبه|مفرمه)"),
        ("%chopper%", "%كبه%", "%مفرمه%"),
    ),
    SubtypeSpec(
        "stand_mixer",
        "Mixer",
        "عجان / مضرب",
        _rx(r"(?:\bstand\s*mixer\b|\bhand\s*mixer\b|\bmixer\b|عجان|مضرب\s*بيض)"),
        ("%mixer%", "%عجان%", "%مضرب%"),
        frozenset({"mixers"}),
    ),
    SubtypeSpec(
        "toaster_sandwich",
        "Toaster & Grill",
        "توستر / ساندوتش ميكر",
        _rx(r"(?:\bsandwich\s*maker\b|\bwaffle\s*maker\b|\btoaster\b|\bgrill\b|توستر|ساندوتش\s*ميكر|شوايه)"),
        ("%sandwich maker%", "%toaster%", "%waffle%", "%توستر%"),
        frozenset({"toasters"}),
    ),
    SubtypeSpec(
        "iron",
        "Steam Iron",
        "مكواة",
        _rx(r"(?:\bsteam\s*iron\b|\bgarment\s*steamer\b|\biron\b|مكواه)"),
        ("%iron%", "%steamer%", "%مكواه%"),
    ),
    SubtypeSpec(
        "fan",
        "Electric Fan",
        "مروحة",
        _rx(r"(?:\bstand\s*fan\b|\bceiling\s*fan\b|\bwall\s*fan\b|\bbox\s*fan\b|\btable\s*fan\b|مروحه)"),
        ("%stand fan%", "%ceiling fan%", "%wall fan%", "%مروحه%"),
    ),
    # --- ELECTRONICS ---
    SubtypeSpec(
        "tv",
        "Smart TV",
        "تلفزيون",
        _rx(r"(?:\bsmart\s*tv\b|\bled\s*tv\b|\bqled\s*tv\b|\boled\s*tv\b|\b4k\s*tv\b|\buhd\s*tv\b|\btelevision\b|تلفزيون|شاشه\s*\d{2}\s*بوصه)"),
        ("%smart tv%", "%tv%", "%تلفزيون%"),
        frozenset({"tvs", "smart_tvs"}),
    ),
    SubtypeSpec(
        "monitor",
        "Monitor",
        "شاشة كمبيوتر",
        _rx(r"(?:\bgaming\s*monitor\b|\bips\s*monitor\b|\bcurved\s*monitor\b|\bmonitor\b|شاشه\s*كمبيوتر|شاشه\s*جيمنج)"),
        ("%monitor%", "%شاشه%"),
        frozenset({"monitors"}),
    ),
    SubtypeSpec(
        "laptop",
        "Laptop",
        "لابتوب",
        _rx(r"(?:\blaptop\b|\bnotebook\b|\bmacbook\b|\bthinkpad\b|\bideapad\b|\bvivobook\b|\bzenbook\b|\bvictus\b|\blegion\b|لابتوب|لاب\s*توب)"),
        ("%laptop%", "%notebook%", "%macbook%", "%لابتوب%"),
        frozenset({"laptops", "notebooks"}),
    ),
    SubtypeSpec(
        "tablet",
        "Tablet",
        "تابلت",
        _rx(r"(?:\btablet\b|\bipad\b|\bgalaxy\s*tab\b|\bpad\s*[a-z0-9]|تابلت|ايباد)"),
        ("%tablet%", "%ipad%", "%تابلت%"),
        frozenset({"tablets"}),
    ),
    SubtypeSpec(
        "smartphone",
        "Smartphone",
        "موبايل",
        _rx(r"(?:\bsmartphone\b|\bmobile\s*phone\b|\biphone\b|\bgalaxy\s+[asmz]\d|\bredmi\b|\bpoco\b|\bhonor\s+x\d|\boppo\b|\brealme\b|\binfinix\b|\btecno\b|موبايل|هاتف\s*ذكي|تليفون)"),
        ("%smartphone%", "%mobile%", "%iphone%", "%galaxy%", "%redmi%", "%موبايل%"),
        frozenset({"smartphones", "mobiles", "mobile_phones", "phones"}),
    ),
    SubtypeSpec(
        "smartwatch",
        "Smartwatch",
        "ساعة ذكية",
        _rx(r"(?:\bsmart\s*watch\b|\bsmartwatch\b|\bapple\s*watch\b|\bgalaxy\s*watch\b|\bfitness\s*tracker\b|ساعه\s*ذكيه|سمارت\s*ووتش)"),
        ("%smartwatch%", "%smart watch%", "%watch%", "%ساعه ذكيه%"),
        frozenset({"wearables", "smart_watches"}),
    ),
    SubtypeSpec(
        "earbuds",
        "Wireless Earbuds",
        "سماعة أذن لاسلكية",
        _rx(r"(?:\bearbuds?\b|\bairpods?\b|\bbuds\b|\btws\b|\bin[\s-]?ear\b|ايربودز|سماعه\s*اذن)"),
        ("%earbuds%", "%buds%", "%airpods%", "%tws%"),
        frozenset({"earbuds", "earphones"}),
    ),
    SubtypeSpec(
        "headphones",
        "Headphones / Headset",
        "سماعة رأس",
        _rx(r"(?:\bheadset\b|\bheadphones?\b|\bover[\s-]?ear\b|\bon[\s-]?ear\b|سماعه\s*راس|هيدسيت)"),
        ("%headset%", "%headphone%", "%سماعه%"),
        frozenset({"headphones"}),
    ),
    SubtypeSpec(
        "speaker",
        "Speaker",
        "سماعة سبيكر",
        _rx(r"(?:\bspeaker\b|\bsoundbar\b|\bsubwoofer\b|سبيكر|مكبر\s*صوت)"),
        ("%speaker%", "%soundbar%", "%سبيكر%"),
        frozenset({"speakers", "soundbars"}),
    ),
    SubtypeSpec(
        "keyboard",
        "Keyboard",
        "كيبورد",
        _rx(r"(?:\bkeyboard\b|كيبورد|لوحه\s*مفاتيح)"),
        ("%keyboard%", "%كيبورد%"),
        frozenset({"keyboards"}),
    ),
    SubtypeSpec(
        "mouse",
        "Mouse",
        "ماوس",
        _rx(r"(?:\bgaming\s*mouse\b|\bwireless\s*mouse\b|\bwired\s*mouse\b|\boptical\s*mouse\b|\bmouse\b|ماوس)"),
        ("%mouse%", "%ماوس%"),
        frozenset({"mouse", "mice"}),
    ),
    SubtypeSpec(
        "microphone",
        "Microphone",
        "ميكروفون",
        _rx(r"(?:\bmicrophone\b|\bcondenser\s*mic\b|\bmic\b|ميكروفون|مايك)"),
        ("%microphone%", "%ميكروفون%"),
    ),
    SubtypeSpec(
        "power_bank",
        "Power Bank",
        "باور بانك",
        _rx(r"(?:\bpower\s*bank\b|\bpowerbank\b|\bpowercore\b|باور\s*بانك)"),
        ("%power bank%", "%powerbank%", "%باور بانك%"),
    ),
    SubtypeSpec(
        "router_networking",
        "Router / Networking",
        "راوتر / شبكة",
        _rx(r"(?:\brouter\b|\baccess\s*point\b|\brange\s*extender\b|\bmesh\s*wi-?fi\b|\bnetwork\s*switch\b|\bgigabit\s*switch\b|راوتر|مقوي\s*واي)"),
        ("%router%", "%extender%", "%switch%", "%access point%", "%راوتر%"),
        frozenset({"networking", "routers"}),
    ),
    SubtypeSpec(
        "printer",
        "Printer",
        "طابعة",
        _rx(r"(?:\bprinter\b|\blaserjet\b|\bdeskjet\b|\becotank\b|\bscanner\b|طابعه)"),
        ("%printer%", "%laserjet%", "%طابعه%"),
        frozenset({"printers", "printer", "scanners"}),
    ),
    SubtypeSpec(
        "ssd_storage",
        "SSD / Storage",
        "وحدة تخزين SSD",
        _rx(r"(?:\bssd\b|\bnvme\b|\bhard\s*drive\b|\bhdd\b|\bflash\s*drive\b|\bmicrosd\b|هارد|فلاشه)"),
        ("%ssd%", "%nvme%", "%hard drive%", "%hdd%"),
        frozenset({"storage"}),
    ),
    SubtypeSpec(
        "ram_memory",
        "RAM Memory",
        "رامات",
        _rx(r"(?:\bddr[345]\b.*\bram\b|\bram\b.*\bddr[345]\b|\bdesktop\s*memory\b|\bnotebook\s*ram\b|\bdimm\b|\bsodimm\b)"),
        ("%ddr4%", "%ddr5%", "%ram%"),
        frozenset({"ram", "memory"}),
    ),
    SubtypeSpec(
        "gpu",
        "Graphics Card",
        "كارت شاشة",
        _rx(r"(?:\bgraphics\s*card\b|\bvideo\s*card\b|\bgeforce\s*rtx\b|\bradeon\s*rx\b|كارت\s*شاشه)"),
        ("%rtx%", "%radeon%", "%graphics card%"),
        frozenset({"gpus", "graphics_cards"}),
    ),
    SubtypeSpec(
        "motherboard",
        "Motherboard",
        "لوحة أم",
        _rx(r"(?:\bmotherboard\b|\bmainboard\b|ماذربورد|لوحه\s*ام)"),
        ("%motherboard%", "%mainboard%"),
        frozenset({"motherboards"}),
    ),
    SubtypeSpec(
        "psu",
        "Power Supply",
        "باور سبلاي",
        _rx(r"(?:\bpower\s*supply\b|\bpsu\b|\b80\s*plus\b|باور\s*سبلاي)"),
        ("%power supply%", "%80 plus%", "%psu%"),
        frozenset({"psus", "power_supplies"}),
    ),
    SubtypeSpec(
        "pc_case",
        "PC Case",
        "كيسة كمبيوتر",
        _rx(r"(?:\bmid\s*tower\b|\bfull\s*tower\b|\bpc\s*case\b|\bgaming\s*case\b|\batx\s*case\b|كيسه)"),
        ("%mid tower%", "%pc case%", "%gaming case%", "%tower%"),
        frozenset({"cases"}),
    ),
    SubtypeSpec(
        "cpu_cooler",
        "CPU Cooler",
        "مبرد معالج",
        _rx(r"(?:\bcpu\s*cooler\b|\bliquid\s*cooler\b|\baio\s*cooler\b|\bair\s*cooler\b|مبرد\s*معالج)"),
        ("%cooler%", "%aio%", "%liquid%"),
        frozenset({"cooling"}),
    ),
    SubtypeSpec(
        "gamepad",
        "Gaming Controller",
        "ذراع تحكم",
        _rx(r"(?:\bgamepad\b|\bcontroller\b|\bdualsense\b|\bjoystick\b|ذراع\s*تحكم|دراع)"),
        ("%gamepad%", "%controller%", "%dualsense%"),
    ),
    # --- HEALTH & SUPPLEMENTS ---
    SubtypeSpec(
        "protein_bar",
        "Protein Bar",
        "بروتين بار",
        _rx(r"(?:\bprotein\s*bar\b|\benergy\s*bar\b|بروتين\s*بار)"),
        ("%protein bar%", "%energy bar%", "%بروتين بار%"),
    ),
    SubtypeSpec(
        "mass_gainer",
        "Mass Gainer",
        "ماس جينر",
        _rx(r"(?:\bmass\s*gainer\b|\bserious\s*mass\b|\bweight\s*gainer\b|\bgainer\b|ماس\s*جينر)"),
        ("%gainer%", "%mass%", "%ماس جينر%"),
    ),
    SubtypeSpec(
        "whey_protein",
        "Whey Protein",
        "واي بروتين",
        _rx(r"(?:\bwhey\b|\bprotein\s*isolate\b|\biso[\s-]?100\b|\bcasein\b|\bplant\s*protein\b|\bprotein\s*powder\b|واي\s*بروتين|بروتين\s*ايزوليت)"),
        ("%whey%", "%protein%", "%isolate%", "%بروتين%"),
    ),
    SubtypeSpec(
        "creatine",
        "Creatine",
        "كرياتين",
        _rx(r"(?:\bcreatine\b|كرياتين)"),
        ("%creatine%", "%كرياتين%"),
    ),
    SubtypeSpec(
        "pre_workout",
        "Pre-Workout",
        "بري وورك أوت",
        _rx(r"(?:\bpre[\s-]?workout\b|\bc4\b|بري\s*وورك)"),
        ("%pre-workout%", "%pre workout%", "%preworkout%"),
    ),
    SubtypeSpec(
        "amino_bcaa",
        "Amino / BCAA / EAA",
        "أحماض أمينية",
        _rx(r"(?:\bbcaa\b|\beaa\b|\bamino\b|\bglutamine\b|\bl[\s-]?carnitine\b|\bcla\b|امينو|جلوتامين|كارنيتين)"),
        ("%bcaa%", "%eaa%", "%amino%", "%glutamine%", "%carnitine%"),
    ),
    SubtypeSpec(
        "collagen",
        "Collagen",
        "كولاجين",
        _rx(r"(?:\bcollagen\b|كولاجين)"),
        ("%collagen%", "%كولاجين%"),
    ),
    SubtypeSpec(
        "omega_3",
        "Omega-3",
        "أوميجا 3",
        _rx(r"(?:\bomega[\s-]?3\b|\bfish\s*oil\b|اوميجا\s*3)"),
        ("%omega%", "%fish oil%", "%اوميجا%"),
    ),
    SubtypeSpec(
        "magnesium",
        "Magnesium",
        "مغنيسيوم",
        _rx(r"(?:\bmagnesium\b|مغنيسيوم|ماغنيسيوم)"),
        ("%magnesium%", "%مغنيسيوم%", "%ماغنيسيوم%"),
    ),
    SubtypeSpec(
        "vitamin_d",
        "Vitamin D",
        "فيتامين د",
        _rx(r"(?:\bvitamin\s*d3?\b|فيتامين\s*د)"),
        ("%vitamin d%", "%فيتامين د%"),
    ),
    SubtypeSpec(
        "vitamin_c",
        "Vitamin C",
        "فيتامين سي",
        _rx(r"(?:\bvitamin\s*c\b|فيتامين\s*سي|فيتامين\s*c)"),
        ("%vitamin c%", "%فيتامين سي%"),
    ),
    SubtypeSpec(
        "multivitamin",
        "Multivitamin",
        "مالتي فيتامين",
        _rx(r"(?:\bmulti[\s-]?vitamin\b|مالتي\s*فيتامين)"),
        ("%multivitamin%", "%multi vitamin%", "%مالتي فيتامين%"),
    ),
    SubtypeSpec(
        "zinc",
        "Zinc",
        "زنك",
        _rx(r"(?:\bzinc\b|زنك)"),
        ("%zinc%", "%زنك%"),
    ),
    SubtypeSpec(
        "ashwagandha",
        "Ashwagandha",
        "أشواجندا",
        _rx(r"(?:\bashwagandha\b|اشواجندا)"),
        ("%ashwagandha%", "%اشواجندا%"),
    ),
    SubtypeSpec(
        "biotin",
        "Biotin",
        "بيوتين",
        _rx(r"(?:\bbiotin\b|بيوتين)"),
        ("%biotin%", "%بيوتين%"),
    ),
    SubtypeSpec(
        "melatonin",
        "Melatonin",
        "ميلاتونين",
        _rx(r"(?:\bmelatonin\b|ميلاتونين)"),
        ("%melatonin%", "%ميلاتونين%"),
    ),
    # --- BEAUTY & SKINCARE ---
    SubtypeSpec(
        "sunscreen",
        "Sunscreen",
        "واقي شمس",
        _rx(r"(?:\bsunscreen\b|\bsunblock\b|\bspf\s*\d{2}\b|\bsun\s*shield\b|\banthelios\b|\bsolaire\b|واقي\s*شمس|صن\s*بلوك|صن\s*سكرين)"),
        ("%sunscreen%", "%sunblock%", "%spf%", "%واقي شمس%"),
        frozenset({"sunscreen"}),
    ),
    SubtypeSpec(
        "perfume",
        "Perfume",
        "عطر",
        _rx(r"(?:\beau\s*de\s*parfum\b|\beau\s*de\s*toilette\b|\bedp\b|\bedt\b|\bparfum\b|\bperfume\b|\bfragrance\b|\bcologne\b|\bextrait\b|برفيوم|عطر)"),
        ("%perfume%", "%parfum%", "%edp%", "%edt%", "%عطر%", "%برفيوم%"),
        frozenset({"perfumes"}),
    ),
    SubtypeSpec(
        "body_mist",
        "Body Mist / Splash",
        "بادي ميست / سبلاش",
        _rx(r"(?:\bbody\s*mist\b|\bbody\s*splash\b|\bhair\s*mist\b|\bsplash\b|\bmist\b|بادي\s*سبلاش|بادي\s*ميست)"),
        ("%mist%", "%splash%", "%سبلاش%"),
    ),
    SubtypeSpec(
        "deodorant",
        "Deodorant",
        "مزيل عرق",
        _rx(r"(?:\bdeodorant\b|\bantiperspirant\b|\banti[\s-]?perspirant\b|\broll[\s-]?on\b|مزيل\s*عرق|مضاد\s*تعرق)"),
        ("%deodorant%", "%antiperspirant%", "%roll%", "%مزيل عرق%"),
    ),
    SubtypeSpec(
        "cleanser",
        "Facial Cleanser",
        "غسول للوجه",
        _rx(r"(?:\bcleanser\b|\bface\s*wash\b|\bfacial\s*wash\b|\bcleansing\s*gel\b|\bmicellar\b|غسول|ميسيلار)"),
        ("%cleanser%", "%face wash%", "%cleansing%", "%غسول%"),
    ),
    SubtypeSpec(
        "serum",
        "Face Serum",
        "سيروم",
        _rx(r"(?:\bserum\b|سيروم)"),
        ("%serum%", "%سيروم%"),
    ),
    SubtypeSpec(
        "shampoo",
        "Shampoo",
        "شامبو",
        _rx(r"(?:\bshampoo\b|شامبو)"),
        ("%shampoo%", "%شامبو%"),
    ),
    SubtypeSpec(
        "conditioner",
        "Hair Conditioner",
        "بلسم شعر",
        _rx(r"(?:\bconditioner\b|\bleave[\s-]?in\b|بلسم)"),
        ("%conditioner%", "%leave-in%", "%بلسم%"),
    ),
    SubtypeSpec(
        "shower_gel",
        "Shower Gel",
        "شاور جل",
        _rx(r"(?:\bshower\s*gel\b|\bbody\s*wash\b|شاور\s*جل|غسول\s*جسم)"),
        ("%shower gel%", "%body wash%", "%شاور جل%"),
    ),
    SubtypeSpec(
        "lotion_cream",
        "Moisturizer / Cream",
        "كريم / لوشن",
        _rx(r"(?:\bmoisturizer\b|\bmoisturizing\b|\bnight\s*cream\b|\bday\s*cream\b|\beye\s*cream\b|\bhand\s*cream\b|\bbody\s*lotion\b|\blotion\b|\bcream\b|مرطب|لوشن|كريم)"),
        ("%cream%", "%lotion%", "%moistur%", "%كريم%", "%لوشن%"),
    ),
    # --- GROCERIES ---
    SubtypeSpec(
        "coffee",
        "Coffee",
        "قهوة / بن",
        _rx(r"(?:\bcoffee\b|\bespresso\b|\bcappuccino\b|\bnescafe\b|قهوه|نسكافيه|(?:^|\s)بن(?:\s|$))"),
        ("%coffee%", "%espresso%", "%nescafe%", "%قهوه%", "%بن %"),
    ),
    SubtypeSpec(
        "tea",
        "Tea",
        "شاي",
        _rx(r"(?:\btea\b|\bgreen\s*tea\b|\bblack\s*tea\b|شاي)"),
        ("%tea%", "%شاي%"),
    ),
    SubtypeSpec(
        "tuna",
        "Tuna",
        "تونة",
        _rx(r"(?:\btuna\b|تونه)"),
        ("%tuna%", "%تونه%"),
    ),
    SubtypeSpec(
        "olive_oil",
        "Olive Oil",
        "زيت زيتون",
        _rx(r"(?:\bolive\s*oil\b|زيت\s*زيتون)"),
        ("%olive oil%", "%زيت زيتون%"),
    ),
    SubtypeSpec(
        "cooking_oil",
        "Cooking Oil",
        "زيت طعام",
        _rx(r"(?:\bsunflower\s*oil\b|\bcorn\s*oil\b|\bcooking\s*oil\b|\bvegetable\s*oil\b|\bcanola\s*oil\b|\bfrying\s*oil\b|زيت\s*عباد|زيت\s*ذره|زيت\s*طعام|زيت\s*قلي)"),
        ("%sunflower oil%", "%corn oil%", "%cooking oil%", "%oil%", "%زيت%"),
    ),
    SubtypeSpec(
        "ghee",
        "Ghee",
        "سمن",
        _rx(r"(?:\bghee\b|\bsamna\b|سمنه|سمن)"),
        ("%ghee%", "%سمن%"),
    ),
    SubtypeSpec(
        "milk",
        "Milk",
        "لبن / حليب",
        _rx(r"(?:\bmilk\b|حليب|لبن)"),
        ("%milk%", "%حليب%", "%لبن%"),
    ),
    SubtypeSpec(
        "cheese",
        "Cheese",
        "جبنة",
        _rx(r"(?:\bcheese\b|\bfeta\b|\bcheddar\b|\bmozzarella\b|جبنه|جبن)"),
        ("%cheese%", "%feta%", "%cheddar%", "%جبن%"),
    ),
    SubtypeSpec(
        "juice",
        "Juice",
        "عصير",
        _rx(r"(?:\bjuice\b|\bnectar\b|عصير)"),
        ("%juice%", "%nectar%", "%عصير%"),
    ),
    SubtypeSpec(
        "water",
        "Water",
        "مياه",
        _rx(r"(?:\bmineral\s*water\b|\bsparkling\s*water\b|\bdrinking\s*water\b|\bwater\b|مياه)"),
        ("%water%", "%مياه%"),
    ),
    SubtypeSpec(
        "pasta",
        "Pasta",
        "مكرونة",
        _rx(r"(?:\bpasta\b|\bspaghetti\b|\bpenne\b|\bmacaroni\b|\bfusilli\b|\bnoodles\b|مكرونه)"),
        ("%pasta%", "%spaghetti%", "%penne%", "%مكرونه%"),
    ),
    SubtypeSpec(
        "rice",
        "Rice",
        "أرز",
        _rx(r"(?:\brice\b|\bbasmati\b|ارز|رز)"),
        ("%rice%", "%basmati%", "%ارز%"),
    ),
    SubtypeSpec(
        "honey",
        "Honey",
        "عسل",
        _rx(r"(?:\bhoney\b|عسل)"),
        ("%honey%", "%عسل%"),
    ),
    SubtypeSpec(
        "detergent",
        "Laundry Detergent",
        "مسحوق غسيل",
        _rx(r"(?:\bdetergent\b|\bwashing\s*powder\b|\bwashing\s*gel\b|\blaundry\b|مسحوق\s*غسيل|برسيل|اريال)"),
        ("%detergent%", "%washing%", "%laundry%", "%مسحوق%"),
        frozenset({"detergents"}),
    ),
    # --- FOOTWEAR & FASHION ---
    SubtypeSpec(
        "football_boots",
        "Football Boots",
        "حذاء كرة قدم",
        _rx(r"(?:\bfootball\s*boots?\b|\bsoccer\s*cleats?\b|\bcleats?\b|\bfg/ag\b|\bag/fg\b|\bturf\b|حذاء\s*كره)"),
        ("%football%", "%cleat%", "%fg/ag%", "%boots%"),
    ),
    SubtypeSpec(
        "running_shoes",
        "Running Shoes",
        "حذاء جري",
        _rx(r"(?:\brunning\s*shoes?\b|\broad\s*shoes?\b|\btrail\s*running\b|\bmarathon\b|حذاء\s*جري)"),
        ("%running%", "%shoe%", "%sneaker%"),
    ),
    SubtypeSpec(
        "sandals_slides",
        "Sandals & Slides",
        "صندل / شبشب",
        _rx(r"(?:\bsandals?\b|\bslides?\b|\bslippers?\b|\bflip[\s-]?flops?\b|\bclogs?\b|صندل|شبشب)"),
        ("%sandal%", "%slide%", "%slipper%", "%flip%", "%clog%"),
    ),
    SubtypeSpec(
        "boots",
        "Boots",
        "بوت",
        _rx(r"(?:\bboots?\b|\bchelsea\s*boot\b|\bankle\s*boot\b|بوت)"),
        ("%boot%", "%بوت%"),
    ),
    SubtypeSpec(
        "heels",
        "Heels",
        "حذاء كعب",
        _rx(r"(?:\bheels?\b|\bpumps?\b|\bslingback\b|\bstiletto\b|كعب)"),
        ("%heel%", "%pump%", "%slingback%"),
    ),
    SubtypeSpec(
        "sneakers",
        "Sneakers & Shoes",
        "حذاء رياضي / سنيكرز",
        _rx(r"(?:\bsneakers?\b|\btrainers?\b|\bshoes?\b|\bslip[\s-]?ins?\b|\bloafer\b|كوتشي|سنيكرز|حذاء)"),
        ("%sneaker%", "%shoe%", "%trainer%", "%حذاء%"),
        frozenset({"sports_shoes", "shoes", "sneakers", "footwear"}),
    ),
    # --- HOME FURNITURE ---
    SubtypeSpec(
        "mattress",
        "Mattress",
        "مرتبة",
        _rx(r"(?:\bmattress\b|مرتبه|سوست)"),
        ("%mattress%", "%مرتبه%"),
        frozenset({"mattresses"}),
    ),
    SubtypeSpec(
        "bedding",
        "Bedding & Linens",
        "مفروشات سرير",
        _rx(r"(?:\bbedsheet\b|\bbed\s*sheet\b|\bduvet\b|\bcomforter\b|\bbedspread\b|\bquilt\b|ملايه|لحاف|كوفرته)"),
        ("%sheet%", "%duvet%", "%comforter%", "%ملايه%", "%لحاف%"),
        frozenset({"bedding_linens"}),
    ),
    SubtypeSpec(
        "rug_carpet",
        "Rug / Carpet",
        "سجادة",
        _rx(r"(?:\brug\b|\bcarpet\b|\bkilim\b|سجاده|سجاد|مشايه)"),
        ("%rug%", "%carpet%", "%سجاد%"),
    ),
    SubtypeSpec(
        "cookware",
        "Cookware",
        "أدوات طهي",
        _rx(r"(?:\bcookware\b|\bfrying\s*pan\b|\bcasserole\b|\bpot\s*set\b|\bgranite\s*set\b|طقم\s*حلل|حله|مقلاه|طاسه)"),
        ("%cookware%", "%pan%", "%pot%", "%حلل%", "%طاسه%"),
        frozenset({"cookware"}),
    ),
    # --- PET CARE ---
    SubtypeSpec(
        "cat_litter",
        "Cat Litter",
        "رمل قطط",
        _rx(r"(?:\blitter\b|رمل)"),
        ("%litter%", "%رمل%"),
        frozenset({"cat_litter"}),
    ),
    SubtypeSpec(
        "cat_food",
        "Cat Food",
        "طعام قطط",
        _rx(r"(?:\bcat\s*food\b|\bkitten\b|\bfeline\b|طعام\s*قطط|دراي\s*فود\s*قطط|قطط)"),
        ("%cat%", "%kitten%", "%قطط%"),
        frozenset({"cat_food"}),
    ),
    SubtypeSpec(
        "dog_food",
        "Dog Food",
        "طعام كلاب",
        _rx(r"(?:\bdog\s*food\b|\bpuppy\b|\bcanine\b|طعام\s*كلاب|كلاب)"),
        ("%dog%", "%puppy%", "%كلاب%"),
        frozenset({"dog_food"}),
    ),
)

_EXPLICIT_ACCESSORY_RE = re.compile(
    r"(?:"
    r"\b(?:case|cover|pouch|sleeve|bag|backpack|folio|bumper|protector|glass|film|sticker|"
    r"cable|charger|adapter|adaptor|remote|strap|band|stand|holder|mount|bracket|hose|filter|"
    r"gasket|seal|hinge|knob|blade|shaft|jug\s*base|frame|grid|barrier|pocket|tipper|"
    r"replacement|spare\s*part|battery|ink|toner|cartridge)\s+(?:for|compatible\s+with)\b|"
    r"\b(?:screen\s*protector|tempered\s*glass|privacy\s*glass|phone\s*case|silicone\s*case|"
    r"leather\s*case|clear\s*case|magsafe\s*case|laptop\s*bag|laptop\s*sleeve|laptop\s*backpack|"
    r"laptop\s*stand|laptop\s*cooler|cooling\s*pad|phone\s*stand|phone\s*holder|car\s*holder|"
    r"car\s*mount|wall\s*mount|watch\s*strap|watch\s*band|replacement\s*remote|cleaning\s*kit|"
    r"charging\s*station|eggs\s*pocket|meat\s*tipper|ice\s*pack|ice\s*cube|chopper\s*blade|"
    r"shaft\s*assembly|jug\s*base|pipe\s*ceiling|lnb|diseqc|freezer\s*door\s*barrier|"
    r"bottles\s*barrier|medicines\s*barrier|shaker\s*bottle|pill\s*box|tote\s*bag|shoelaces?|insoles?)\b|"
    r"(?:جراب|كفر|اسكرين|سكرين|قطعه\s*غيار|رف\s*ثلاجه|درج\s*ثلاجه|شنطه\s*لابتوب|حقيبه\s*لابتوب|"
    r"لاصق\s*حمايه|سير\s*ساعه|استراب|شاحن\s*لابتوب|شاحن\s*موبايل|شيكر)"
    r")",
    re.I,
)

_MAIN_PRODUCT_RE = re.compile(
    r"(?:\b(?:vacuum\s*cleaner|air\s*conditioner|washing\s*machine|refrigerator|fridge|freezer|"
    r"dishwasher|microwave|water\s*heater|gas\s*cooker|smart\s*tv|monitor|laptop|notebook|macbook|"
    r"smartphone|tablet|ipad|projector|kettle|blender|food\s*processor|air\s*fryer|coffee\s*maker|"
    r"espresso\s*machine|stand\s*fan|stand\s*mixer|toaster|power\s*supply|motherboard|graphics\s*card|"
    r"gaming\s*mouse|wireless\s*mouse|keyboard|headset|headphones|earbuds|gamepad|controller|router|printer)\b|"
    r"(?:مكنسه|تكييف|غساله|ثلاجه|تلاجه|فريزر|بوتاجاز|سخان|ميكروويف|تلفزيون|غلايه|خلاط|مروحه|قلايه|لابتوب|موبايل))",
    re.I,
)

_TOKEN_RE = re.compile(r"[a-z0-9\u0621-\u064a]+", re.I)
_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "with", "for", "from", "by", "in", "on", "of", "to", "a", "an", "or",
    "new", "original", "official", "warranty", "egypt", "version", "global", "local",
    "black", "white", "grey", "gray", "blue", "red", "green", "silver", "gold", "pink",
    "beige", "brown", "yellow", "orange", "purple", "navy", "dark", "light", "color",
    "men", "women", "unisex", "size", "pack", "piece", "pieces", "pcs", "model",
    "في", "من", "مع", "على", "الى", "او", "عن", "لل", "اسود", "ابيض", "ازرق", "احمر",
    "رمادي", "فضي", "ذهبي", "موديل", "اصلي", "ضمان", "جديد",
})


def _norm(value: str) -> str:
    clean = unicodedata.normalize("NFKC", value or "")
    return normalize_arabic_text(clean)


def _is_accessory(title: str, sub_category: str, category: str) -> bool:
    if category in ("groceries", "pet_care"):
        return False
    norm = _norm(title)
    if _EXPLICIT_ACCESSORY_RE.search(norm):
        return True
    if _MAIN_PRODUCT_RE.search(norm):
        return False
    sub = (sub_category or "").strip().lower()
    if sub in ("accessories", "cables", "chargers", "cases", "bags", "spare_parts", "playstation_accessories"):
        return True
    return False


_NON_FOOTWEAR_APPAREL_RE = re.compile(
    r"(?:\b(?:t[\s-]?shirt|tee|shirt|polo|jersey|short|shorts|pant|pants|trouser|trousers|"
    r"jogger|joggers|legging|leggings|tight|tights|hoodie|sweatshirt|jacket|coat|vest|"
    r"tracksuit|bra|sock|socks|cap|hat|bag|backpack|gloves|towel|dress|skirt|tank\s*top)\b|"
    r"(?:تيشيرت|قميص|شورت|بنطلون|جاكيت|هودي|شراب|شنطه|فستان))",
    re.I,
)
_FOOTWEAR_SUBTYPES: frozenset[str] = frozenset({
    "football_boots", "running_shoes", "sandals_slides", "boots", "heels", "sneakers",
})
_BUNDLE_RE = re.compile(r"(?:\b(?:bundle|combo|routine|starter\s*pack|gift\s*set|2\s*in\s*1|3\s*in\s*1)\b|باقه|مجموعه|روتين)", re.I)


_KIDS_FOOTWEAR_RE = re.compile(r"(?:\b(?:kids?|boys?|girls?|youth|junior|jr|infant|toddler|children)\b|اطفال|ولادي|بناتي)", re.I)
_WOMEN_FOOTWEAR_RE = re.compile(r"(?:\b(?:women'?s?|woman|ladies|female|wmn|wmns)\b|حريمي|نسائي|للسيدات|للنساء)", re.I)
_MEN_FOOTWEAR_RE = re.compile(r"(?:\b(?:men'?s?|man|male)\b|رجالي|للرجال)", re.I)
_WOMEN_ONLY_STORES: frozenset[str] = frozenset({"dalydress", "carina", "dejavu", "emeli_eg", "palma_eg", "okhtein"})


def _fw_gender(norm_title: str, store_name: str) -> str:
    if _KIDS_FOOTWEAR_RE.search(norm_title):
        return "kids"
    has_w = bool(_WOMEN_FOOTWEAR_RE.search(norm_title)) or store_name.lower() in _WOMEN_ONLY_STORES
    has_m = bool(_MEN_FOOTWEAR_RE.search(norm_title))
    if has_w and not has_m:
        return "women"
    if has_m and not has_w:
        return "men"
    return "unisex"


def _detect_subtype(title: str, sub_category: str) -> Optional[SubtypeSpec]:
    norm = _norm(title)
    sub = (sub_category or "").strip().lower()
    is_apparel = bool(_NON_FOOTWEAR_APPAREL_RE.search(norm))
    for spec in _SUBTYPE_SPECS:
        if spec.code in _FOOTWEAR_SUBTYPES and is_apparel:
            continue
        if spec.match_re.search(norm):
            return spec
    for spec in _SUBTYPE_SPECS:
        if spec.code in _FOOTWEAR_SUBTYPES and is_apparel:
            continue
        if sub and sub in spec.sub_categories:
            return spec
    return None


def _trigrams(text_val: str) -> set[str]:
    s = f"  {text_val} "
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _trgm_sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _tokens(title: str, brand: str = "") -> set[str]:
    """Bilingual canonical tokens (translates AR -> EN concepts/units so AR and EN titles align)."""
    canon = canonicalize_bilingual_text(f"{brand} {title}")
    raw = _TOKEN_RE.findall(canon)
    return {t for t in raw if len(t) >= 2 and t not in _STOPWORDS}


def _spec_tokens(title: str) -> set[str]:
    """Extract coarse technical/size cues (e.g. `55`, `1.5hp`, `8kg`, `256gb`, `50ml`, `1kg`) for bonus ranking."""
    norm = _norm(title)
    return set(
        re.findall(
            r"\b\d+(?:\.\d+)?\s*(?:gb|tb|inch|hp|kg|l|ml|g|w|watt|hz|caps?|tabs?|spf)\b",
            norm,
        )
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _verdict_boost(verdict: str) -> float:
    if verdict in ("ALL_TIME_LOW", "GENUINE_DEAL"):
        return 1.0
    if verdict == "NORMAL_PRICE":
        return 0.35
    return -0.35


def _build_reason(
    subtype: Optional[SubtypeSpec],
    price_diff_pct: float,
    same_brand: bool,
) -> str:
    parts: list[str] = []
    if subtype is not None:
        parts.append(subtype.label_en)
    if same_brand:
        parts.append("Same brand")
    if abs(price_diff_pct) <= 5.0:
        parts.append("Very close price")
    elif price_diff_pct < 0:
        parts.append(f"{abs(price_diff_pct):.0f}% cheaper")
    else:
        parts.append(f"{price_diff_pct:.0f}% higher")
    return " · ".join(parts) if parts else "Same category & price range"


def find_similar_alternatives(
    db: Connection,
    product: ProductVerdictItem,
    *,
    max_results: int = 6,
) -> list[SimilarAlternativeItem]:
    """Dynamically find up to `max_results` (default 6) smart similar alternatives.

    Strictly enforces:
    - Same `sub_category` (when non-empty & non-generic) and same `category`
    - Same `is_accessory` status (never recommends accessories for main devices or vice versa)
    - Within `±30%` price range (preferring `±20%` first)
    - Excludes the exact same product, sibling variants (`parent_product_key`), and exact cross-store cluster (`canonical_product_key`)
    - Ranked by bilingual title/brand token similarity, favoring distinct stores first
    """
    target_price = float(product.current_price or 0.0)
    if target_price <= 0:
        return []

    target_acc = _is_accessory(product.product_title, product.sub_category, product.category)
    target_subtype = _detect_subtype(product.product_title, product.sub_category)
    target_tokens = _tokens(product.product_title, product.brand)
    target_specs = _spec_tokens(product.product_title)
    target_brand = _norm(product.brand or "")
    target_title_norm = _norm(product.product_title or "")
    target_sub = (product.sub_category or "").strip().lower()
    strict_sub = bool(target_sub and target_sub not in ("other", "general", "all", "unknown"))

    target_trgms = _trigrams(canonicalize_bilingual_text(product.product_title or ""))
    target_is_bundle = bool(_BUNDLE_RE.search(target_title_norm))
    target_fw_gender = (
        _fw_gender(target_title_norm, product.store_name)
        if (target_subtype is not None and target_subtype.code in _FOOTWEAR_SUBTYPES)
        else ""
    )

    min_30 = round(target_price * 0.70, 2)
    max_30 = round(target_price * 1.30, 2)
    min_20 = target_price * 0.80
    max_20 = target_price * 1.20

    params: dict[str, Any] = {
        "category": product.category,
        "sub_cat": target_sub,
        "target_sk": product.product_sk,
        "target_store": product.store_name,
        "target_parent": product.parent_product_key or "",
        "target_canon": product.canonical_product_key or "",
        "min_p": min_30,
        "max_p": max_30,
        "cand_limit": 250,
    }

    if target_subtype is not None:
        like_clauses: list[str] = []
        for i, pat in enumerate(target_subtype.sql_like_patterns):
            key = f"lp_{i}"
            params[key] = pat
            like_clauses.append(f"search_document LIKE :{key}")
        trgm_filter = "(" + " OR ".join(like_clauses) + ")"
    else:
        long_words = sorted((t for t in target_tokens if len(t) >= 4), key=len, reverse=True)[:3]
        if long_words:
            like_clauses = []
            for i, word in enumerate(long_words):
                key = f"lp_{i}"
                params[key] = f"%{word}%"
                like_clauses.append(f"search_document LIKE :{key}")
            trgm_filter = "(" + " OR ".join(like_clauses) + ")"
        else:
            trgm_filter = "TRUE"

    sub_clause = "AND LOWER(sub_category) = :sub_cat" if strict_sub else ""

    sql = text(
        f"""
        SELECT
            product_sk,
            product_title,
            store_name,
            brand,
            category,
            sub_category,
            current_price,
            discount_verdict,
            in_stock,
            image_url,
            product_url,
            parent_product_key,
            canonical_product_key
        FROM gold.mart_product_verdicts
        WHERE category = :category
          {sub_clause}
          AND current_price BETWEEN :min_p AND :max_p
          AND in_stock = TRUE
          AND product_sk <> :target_sk
          AND (:target_parent = '' OR parent_product_key <> :target_parent)
          AND (:target_canon = '' OR canonical_product_key IS DISTINCT FROM :target_canon)
          AND {trgm_filter}
        LIMIT :cand_limit
        """
    )

    try:
        rows = db.execute(sql, params).mappings().all()
    except DBAPIError:
        return []

    if not rows:
        return []

    scored_20: list[tuple[float, bool, dict[str, Any], Optional[SubtypeSpec], bool]] = []
    scored_30: list[tuple[float, bool, dict[str, Any], Optional[SubtypeSpec], bool]] = []

    for row in rows:
        cand_sk = str(row["product_sk"] or "")
        if cand_sk == product.product_sk:
            continue
        cand_canon = row.get("canonical_product_key")
        if product.canonical_product_key and cand_canon == product.canonical_product_key:
            continue
        cand_parent = row.get("parent_product_key")
        if product.parent_product_key and cand_parent == product.parent_product_key:
            continue

        cand_title = str(row["product_title"] or "")
        cand_sub = str(row["sub_category"] or "").strip().lower()
        cand_cat = str(row["category"] or "")
        cand_price = float(row["current_price"] or 0.0)
        if cand_price <= 0 or cand_price < min_30 or cand_price > max_30:
            continue

        # Mandatory Guard 0: Strict same sub_category when target sub_category is concrete
        if strict_sub and cand_sub != target_sub:
            continue

        cand_title_norm = _norm(cand_title)
        if not target_is_bundle and _BUNDLE_RE.search(cand_title_norm):
            continue

        # Mandatory Guard 1: Accessory vs. Main Product separation
        cand_acc = _is_accessory(cand_title, cand_sub, cand_cat)
        if cand_acc != target_acc:
            continue

        # Mandatory Guard 2: Functional Subtype Equivalence
        cand_subtype = _detect_subtype(cand_title, cand_sub)
        cand_canon_title = canonicalize_bilingual_text(cand_title)
        trgm_sim = _trgm_sim(target_trgms, _trigrams(cand_canon_title))
        if target_subtype is not None:
            compatible = cand_subtype is not None and (
                cand_subtype.code == target_subtype.code
                or {cand_subtype.code, target_subtype.code} == {"running_shoes", "sneakers"}
            )
            if not compatible:
                continue
            if target_subtype.code in _FOOTWEAR_SUBTYPES:
                cand_fw_gender = _fw_gender(cand_title_norm, str(row.get("store_name") or ""))
                if (target_fw_gender == "kids") != (cand_fw_gender == "kids"):
                    continue
                if {target_fw_gender, cand_fw_gender} == {"men", "women"}:
                    continue
        elif cand_subtype is not None:
            if trgm_sim < 0.28:
                continue

        # Compute bilingual token + brand + trigram relevance score
        cand_brand_norm = _norm(str(row.get("brand") or ""))
        same_brand = bool(target_brand and target_brand != "unknown" and cand_brand_norm == target_brand)
        cand_tokens = _tokens(cand_title, str(row.get("brand") or ""))
        tok_sim = _jaccard(target_tokens, cand_tokens)
        spec_bonus = 0.08 if (target_specs and (target_specs & _spec_tokens(cand_title))) else 0.0
        brand_bonus = 0.08 if same_brand else 0.0
        subtype_bonus = 0.18 if (target_subtype is not None and cand_subtype is not None) else 0.0
        combined_sim = min(1.0, 0.45 * trgm_sim + 0.55 * tok_sim + subtype_bonus + spec_bonus + brand_bonus)

        min_threshold = 0.24 if target_subtype is not None else 0.30
        if combined_sim < min_threshold:
            continue

        is_other_store = str(row["store_name"]) != product.store_name
        price_closeness = max(0.0, 1.0 - abs(cand_price - target_price) / (target_price * 0.30))
        v_boost = _verdict_boost(str(row.get("discount_verdict") or "NORMAL_PRICE"))
        stock_boost = 1.0 if row.get("in_stock") else 0.0
        store_diversity_boost = 0.06 if is_other_store else 0.0

        final_score = (
            0.58 * combined_sim
            + 0.26 * price_closeness
            + 0.06 * v_boost
            + 0.04 * stock_boost
            + store_diversity_boost
        )

        entry = (final_score, is_other_store, dict(row), target_subtype or cand_subtype, same_brand)
        if min_20 <= cand_price <= max_20:
            scored_20.append(entry)
        else:
            scored_30.append(entry)

    # Deduplicate favoring distinct other stores first (1 per store), then distinct clusters/products up to max_results
    def _pick_diverse(
        pool: list[tuple[float, bool, dict[str, Any], Optional[SubtypeSpec], bool]],
        used_stores: set[str],
        used_sks: set[str],
        used_canons: set[str],
        limit: int,
        *,
        other_stores_only: bool,
    ) -> list[tuple[float, bool, dict[str, Any], Optional[SubtypeSpec], bool]]:
        picked: list[tuple[float, bool, dict[str, Any], Optional[SubtypeSpec], bool]] = []
        ordered = sorted(
            pool,
            key=lambda x: (not x[1], -x[0], abs(float(x[2]["current_price"]) - target_price)),
        )
        for item in ordered:
            _, is_other, row, _, _ = item
            if other_stores_only and not is_other:
                continue
            sk = str(row["product_sk"])
            st = str(row["store_name"])
            canon = str(row.get("canonical_product_key") or "")
            if sk in used_sks:
                continue
            if canon and canon in used_canons:
                continue
            if other_stores_only and st in used_stores:
                continue
            used_sks.add(sk)
            if other_stores_only:
                used_stores.add(st)
            if canon:
                used_canons.add(canon)
            picked.append(item)
            if len(picked) >= limit:
                break
        return picked

    used_stores: set[str] = set()
    used_sks: set[str] = set()
    used_canons: set[str] = set()

    # Pass A: 1 top candidate per distinct other store in ±20%, then ±30%
    chosen = _pick_diverse(scored_20, used_stores, used_sks, used_canons, max_results, other_stores_only=True)
    if len(chosen) < max_results and scored_30:
        chosen.extend(
            _pick_diverse(scored_30, used_stores, used_sks, used_canons, max_results - len(chosen), other_stores_only=True)
        )
    # Pass B: if fewer than 3 distinct-store alternatives exist, fill remaining slots with best distinct SKUs
    if len(chosen) < 3:
        chosen.extend(
            _pick_diverse(scored_20 + scored_30, used_stores, used_sks, used_canons, max_results - len(chosen), other_stores_only=False)
        )

    if not chosen:
        return []

    results: list[SimilarAlternativeItem] = []
    for _, _, row, sub_spec, same_brand in chosen[:max_results]:
        cand_price = round(float(row["current_price"]), 2)
        diff_egp = round(cand_price - target_price, 2)
        diff_pct = round((diff_egp / target_price) * 100.0, 2)
        results.append(
            SimilarAlternativeItem(
                product_sk=str(row["product_sk"]),
                title=str(row["product_title"]),
                store_name=str(row["store_name"]),
                current_price=cand_price,
                price_diff_egp=diff_egp,
                price_diff_pct=diff_pct,
                verdict=row["discount_verdict"],
                in_stock=bool(row["in_stock"]),
                image_url=row.get("image_url"),
                product_url=str(row["product_url"]),
                similarity_reason=_build_reason(sub_spec, diff_pct, same_brand),
                is_exact_match=False,
            )
        )
    return results
