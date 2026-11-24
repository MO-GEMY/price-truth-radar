"""Unified Python Arabic + English brand extraction & normalization engine.

Runs 100% in Python BEFORE database ingestion (invoked automatically by
`RawProductSnapshot` validation and offline staging) with zero SQL overhead.

Handles:
  1. Official single-brand stores (e.g. `zanussi_eg -> Zanussi`, `eva_cosmetics -> Eva`,
     `puma_eg -> Puma`, `aldo_eg -> Aldo`, `timberland_eg -> Timberland`, etc.).
  2. Placeholder & multi-brand retailer-as-brand stripping (`Unknown`, `Generic`,
     `My Store`, `Kaufen Egypt Online Store`, `Dubai Phone`, `Kimo Store`, etc.).
  3. Bilingual Arabic + English brand alias dictionary across all 10 verticals
     (Electronics, Home Appliances, Fashion, Footwear, Sports, Beauty, Health/Pharmacy,
     Groceries, Home/Furniture, Baby/Kids, Pet Care).
  4. Compatibility-clause guard so third-party accessories (e.g. `Silicone Case for Canon R10`,
     `Cover for iPhone 15`) are NOT misattributed to the target device's brand.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

_AR_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_AR_NORM_TRANS = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
    }
)

# Strip "for <device>" / "compatible with <device>" / "لـ <device>" clauses before title brand extraction
_COMPAT_TAIL_RE = re.compile(
    r"(?:\b(?:for|compatible\s+with|fits|suitable\s+for|designed\s+for)\b|مناسب\s+ل|متوافق\s+مع|لجهاز|لهاتف).*$",
    re.I,
)

# Placeholder strings & multi-brand retailer names that should trigger title/URL brand extraction
PLACEHOLDER_BRANDS: frozenset[str] = frozenset(
    {
        "",
        "unknown",
        "generic",
        "other",
        "none",
        "null",
        "n/a",
        "na",
        "n_a",
        "brand",
        "unbranded",
        "default",
        "various",
        "no brand",
        "no_brand",
        "my store",
        "my_store",
        "store",
        "vendor",
        # Multi-brand Egyptian retailers/marketplaces that sometimes populate vendor=store_name
        "amazon",
        "amazon eg",
        "amazon_eg",
        "amazon egypt",
        "noon",
        "noon egypt",
        "jumia",
        "jumia_eg",
        "jumia egypt",
        "btech",
        "b.tech",
        "b tech",
        "raneen",
        "rayashop",
        "raya shop",
        "2b",
        "2b egypt",
        "sigma",
        "sigma computer",
        "compumarts",
        "compuscience",
        "elbadr",
        "el badr",
        "el badr group",
        "egyptlaptop",
        "egypt laptop",
        "cairosales",
        "cairo sales",
        "dubaiphone",
        "dubai phone",
        "dream2000",
        "dream 2000",
        "elaraby",
        "el araby",
        "el araby group",
        "elarabygroup",
        "kaufen",
        "kaufen_eg",
        "kaufen egypt",
        "kaufen egypt online store",
        "ehab center",
        "ehab_center",
        "kimostore",
        "kimo store",
        "icamstore",
        "icam store",
        "ahw store",
        "ahw_store",
        "alfrensia",
        "smartkoshk",
        "shamy stores",
        "shamystores",
        "ennap",
        "myxprs",
        "hardware market",
        "hardware_market",
        "up to date",
        "up_to_date_eg",
        "baraka computer",
        "baraka_computer",
        "hyper techno",
        "hyper_techno",
        "gc hardware",
        "hankerz",
        "three egypt",
        "gamesworldegypt",
        "games world egypt",
        "elnekhely",
        "maximum hardware",
        "mobilaty",
        "mobilaty_eg",
        "carrefour",
        "carrefour_eg",
        "carrefour egypt",
        "spinneys",
        "hyperone",
        "hyper one",
        "seoudi",
        "seoudi supermarket",
        "gourmet",
        "gourmet egypt",
        "metro market",
        "metro_market",
        "espresso egypt",
        "espresso_egypt",
        "el ezaby",
        "el_ezaby",
        "seif pharmacies",
        "seif_pharmacies",
        "misr pharmacies",
        "misr_pharmacies",
        "bloom pharmacy",
        "bloom_pharmacy",
        "chefaa",
        "beseha",
        "tdawi",
        "source beauty",
        "source_beauty",
        "bashrety",
        "faces",
        "faces_eg",
        "mazaya",
        "mazaya_eg",
        "kayanek",
        "kayanek_eg",
        "homzmart",
        "el sallab",
        "el_sallab_eg",
        "wayup sports",
        "wayup_sports",
        "intersport",
        "intersport_eg",
        "gosport",
        "gosport_eg",
        "athlete home",
        "athlete_home",
        "union sport",
        "union_sport",
        "runner",
        "runner_eg",
        "dstore",
        "dstore_eg",
        "dstore egypt",
        "hedeya",
        "ourkids",
        "ourkids_eg",
        "le3ab store",
        "happet",
        "amin pet shop",
        "amin_pet_shop",
        "pets egypt",
        "pets_egypt",
        "egysupps",
        "house of supplements",
        "ifit",
        "gofit",
        "mfsupps",
        "powerstore",
        "mr vitamins",
        "protein house",
    }
)

# Multi-brand retailers/marketplaces where `brand == store_name` is a placeholder
MULTI_BRAND_RETAILERS: frozenset[str] = frozenset(
    {
        "amazon_eg", "noon", "jumia", "btech", "raneen", "rayashop", "2b", "sigma",
        "compumarts", "compuscience", "elbadr", "egyptlaptop", "cairosales", "dubaiphone",
        "dream2000", "elaraby", "kaufen_eg", "ehab_center", "kimostore", "icamstore",
        "ahw_store", "alfrensia", "smartkoshk", "shamystores", "ennap", "myxprs",
        "hardware_market", "up_to_date_eg", "baraka_computer", "hyper_techno", "gc_hardware",
        "hankerz", "three_egypt", "gamesworldegypt", "elnekhely", "maximum_hardware",
        "mobilaty_eg", "carrefour_eg", "spinneys", "hyperone", "seoudi", "gourmet",
        "metro_market", "el_ezaby", "seif_pharmacies", "misr_pharmacies", "bloom_pharmacy",
        "chefaa", "beseha", "tdawi", "source_beauty", "bashrety", "faces_eg", "mazaya_eg",
        "kayanek_eg", "homzmart", "el_sallab_eg", "wayup_sports", "intersport_eg",
        "gosport_eg", "union_sport", "runner_eg", "dstore_eg", "hedeya", "le3ab_store",
        "happet", "amin_pet_shop", "pets_egypt", "egysupps", "house_of_supplements",
        "ifit_eg", "gofit_eg", "mfsupps_eg", "powerstore_eg", "mr_vitamins_eg",
        "protein_house_eg", "biostream", "eparkville",
    }
)

# Official single-brand & private-label stores where store_name itself guarantees the canonical brand
SINGLE_BRAND_STORES: dict[str, str] = {
    # Appliances & Electronics official brand stores
    "zanussi_eg": "Zanussi",
    "unionaire_eg": "Unionaire",
    "fresh_eg": "Fresh",
    "sokany_eg": "Sokany",
    "tank_eg": "Tank",
    "olympic_electric": "Olympic Electric",
    "logitech_eg": "Logitech",
    # Fashion, Footwear, Sports & Luggage official brand stores
    "adidas_eg": "Adidas",
    "puma_eg": "Puma",
    "skechers_shop_eg": "Skechers",
    "aldo_eg": "Aldo",
    "timberland_eg": "Timberland",
    "samsonite_eg": "Samsonite",
    "decathlon_eg": "Decathlon",
    "lc_waikiki_eg": "LC Waikiki",
    "defacto_eg": "DeFacto",
    "town_team": "Town Team",
    "concrete": "Concrete",
    "mobaco": "Mobaco",
    "dalydress": "Dalydress",
    "dejavu": "Dejavu",
    "carina": "Carina",
    "activ": "Activ",
    "khotwh": "Khotwh",
    "cottonil_eg": "Cottonil",
    "dice_sportswear": "Dice",
    "ravin": "Ravin",
    "andora_eg": "Andora",
    "tie_house_eg": "Tie House",
    "tie_shop_eg": "Tie Shop",
    "dott_jeans_eg": "Dott Jeans",
    "tomato_eg": "Tomato",
    "caesar_eg": "Caesar",
    "stabraq": "Stabraq",
    "sigma_fit": "Sigma Fit",
    "azzafahmy": "Azza Fahmy",
    "azza_fahmy": "Azza Fahmy",
    "okhtein": "Okhtein",
    "athlete_home": "Athlete Home",
    "ourkids_eg": "Ourkids",
    # Beauty, Skincare & Health official brand stores
    "eva_cosmetics": "Eva",
    "luna_eg": "Luna",
    "bobana": "Bobana",
    "bless_eg": "Bless",
    "cybele_eg": "Cybele",
    "raw_african": "Raw African",
    "the_hair_addict": "The Hair Addict",
    "hayah_labs": "Hayah",
    "cleo_labs": "Cleo",
    "melano_pharma": "Melano",
    "dermaelle": "Dermaelle",
    "telofill_eg": "Telofill",
    "neuth_eg": "Neuth",
    "norshek": "Norshek",
    "infinity_clinic": "Infinity",
    "cherry_and_berry": "Cherry & Berry",
    "nowfoods_eg": "NOW Foods",
    "organic_nation": "Organic Nation",
    "limitless_naturals": "Limitless",
    "max_muscle_eg": "Max Muscle",
    # Home, Furniture, Baby & Food official brand stores
    "ikea_eg": "IKEA",
    "tupperware_eg": "Tupperware",
    "chicco_eg": "Chicco",
    "mintra_eg": "Mintra",
    "kabbani": "Kabbani",
    "ariika": "Ariika",
    "chichomz": "Chichomz",
    "neoflam_eg": "Neoflam",
    "nouval_eg": "Nouval",
    "elzenouki": "El Zenouki",
    "elzenouki_cookware": "El Zenouki",
    "zinox_elzenouki": "Zinox",
    "oriental_weavers": "Oriental Weavers",
    "bed_janssen": "Janssen",
    "janssen_stores": "Janssen",
    "habitat_eg": "Habitat",
    "bednhome": "BedNHome",
    "family_bed": "Family Bed",
    "elbadrawi_home": "Elbadrawi Home",
    "smart_furniture": "Smart Furniture",
    "cocyta": "Cocyta",
    "espresso_egypt": "Espresso Egypt",
    "abu_auf": "Abu Auf",
    "imtenan": "Imtenan",
}

# Canonical display brand -> tuple of lowercase English & Arabic aliases
# Longest alias matches first inside word boundaries.
CANONICAL_BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    # --- Electronics, Mobile, Audio, PC Hardware ---
    "Apple": ("apple", "iphone", "ipad", "macbook", "airpods", "ابل", "أبل", "ايفون", "آيفون", "ايباد", "ماك بوك", "ايربودز"),
    "Samsung": ("samsung", "galaxy", "سامسونج", "سامسونغ", "جالاكسي", "جالكسي"),
    "Xiaomi": ("xiaomi", "redmi", "poco", "شاومي", "ريدمي", "بوكو"),
    "OPPO": ("oppo", "اوبو", "أوبو"),
    "Realme": ("realme", "ريلمي"),
    "Infinix": ("infinix", "انفينكس", "انفنكس", "إنفينيكس"),
    "Tecno": ("tecno", "تكنو"),
    "Huawei": ("huawei", "هواوي"),
    "Honor": ("honor", "هونر", "اونر"),
    "Vivo": ("vivo", "فيفو"),
    "Nokia": ("nokia", "نوكيا"),
    "HMD": ("hmd",),
    "Motorola": ("motorola", "موتورولا"),
    "OnePlus": ("oneplus", "one plus", "ون بلس"),
    "Nothing": ("nothing phone", "cmf by nothing"),
    "Google": ("google pixel", "جوجل بيكسل"),
    "Sony": ("sony", "playstation", "dualsense", "سوني", "بلايستيشن"),
    "LG": ("lg", "ال جي", "إل جي"),
    "Lenovo": ("lenovo", "ideapad", "thinkpad", "legion", "لينوفو"),
    "HP": ("hp", "hewlett packard", "victus", "omen", "اتش بي", "إتش بي"),
    "Dell": ("dell", "alienware", "inspiron", "latitude", "ديل"),
    "ASUS": ("asus", "rog strix", "tuf gaming", "vivobook", "zenbook", "اسوس", "أسوس"),
    "Acer": ("acer", "predator", "nitro 5", "ايسر", "أيسر"),
    "MSI": ("msi", "ام اس اي"),
    "Gigabyte": ("gigabyte", "aorus", "جيجابايت"),
    "ASRock": ("asrock",),
    "Intel": ("intel", "انتل", "إنتل"),
    "AMD": ("amd", "ryzen", "رايزن"),
    "NVIDIA": ("nvidia", "geforce", "انفيديا"),
    "Corsair": ("corsair", "كورسير"),
    "Kingston": ("kingston", "كينجستون"),
    "Crucial": ("crucial", "كروشيال"),
    "Western Digital": ("western digital", "wd blue", "wd black", "wd green", "wd red", "ويسترن ديجيتال"),
    "Seagate": ("seagate", "سيجيت"),
    "SanDisk": ("sandisk", "سانديسك"),
    "Lexar": ("lexar", "ليكسار"),
    "Kioxia": ("kioxia", "كيوكسيا"),
    "KingSpec": ("kingspec", "كينج سبيك"),
    "Transcend": ("transcend", "ترانسيند"),
    "TeamGroup": ("teamgroup", "team group"),
    "XPG": ("xpg",),
    "ADATA": ("adata", "اداتا"),
    "PNY": ("pny",),
    "G.Skill": ("g.skill", "gskill"),
    "Hikvision": ("hikvision", "هيك فيجن"),
    "Dahua": ("dahua", "داهوا"),
    "TP-Link": ("tp-link", "tplink", "tp link", "تي بي لينك"),
    "D-Link": ("d-link", "dlink", "دي لينك"),
    "Mercusys": ("mercusys", "ميركوسيس"),
    "Ubiquiti": ("ubiquiti", "unifi"),
    "MikroTik": ("mikrotik", "مايكروتيك"),
    "Logitech": ("logitech", "لوجيتك", "لوجيتيك"),
    "Razer": ("razer", "ريزر"),
    "HyperX": ("hyperx", "هايبر اكس"),
    "SteelSeries": ("steelseries", "ستيل سيريز"),
    "Redragon": ("redragon", "ريدراجون", "ريد دراجون"),
    "Bloody": ("bloody", "بلادي"),
    "Meetion": ("meetion", "ميتيون"),
    "Cougar": ("cougar", "cougaregy", "كوجار"),
    "Cooler Master": ("cooler master", "كولر ماستر"),
    "NZXT": ("nzxt",),
    "DeepCool": ("deepcool", "deep cool"),
    "Thermaltake": ("thermaltake",),
    "Lian Li": ("lian li",),
    "ID-COOLING": ("id-cooling", "id cooling"),
    "T-Dagger": ("t-dagger", "tdagger"),
    "AOC": ("aoc",),
    "BenQ": ("benq", "بينكيو"),
    "ViewSonic": ("viewsonic", "فيوسونيك"),
    "Canon": ("canon", "كانون"),
    "Nikon": ("nikon", "نيكون"),
    "Fujifilm": ("fujifilm", "فوجي فيلم"),
    "GoPro": ("gopro", "جو برو"),
    "DJI": ("dji",),
    "Insta360": ("insta360",),
    "Godox": ("godox", "جودوكس"),
    "Boya": ("boya", "بويا"),
    "Saramonic": ("saramonic",),
    "Anker": ("anker", "soundcore", "eufy", "انكر", "أنكر", "ساوند كور", "ساوندكور"),
    "JBL": ("jbl", "جي بي ال", "جي بي إل"),
    "Bose": ("bose", "بوز"),
    "Marshall": ("marshall", "مارشال"),
    "Harman Kardon": ("harman kardon", "هارمان كاردون"),
    "Sennheiser": ("sennheiser", "سنهايزر"),
    "Skullcandy": ("skullcandy",),
    "Edifier": ("edifier", "اديفاير"),
    "Oraimo": ("oraimo", "اورايمو", "أورايمو"),
    "UGREEN": ("ugreen", "u-green", "يوجرين", "يو جرين"),
    "Baseus": ("baseus", "بيسوس", "باسوس"),
    "Joyroom": ("joyroom", "جوي روم", "جويروم"),
    "RAVPower": ("ravpower", "rav power", "راف باور"),
    "CardoO": ("cardoo", "كاردو"),
    "Remax": ("remax", "ريماكس"),
    "Hoco": ("hoco", "هوكو"),
    "Promate": ("promate", "بروميت"),
    "Porodo": ("porodo", "بورودو"),
    "Green Lion": ("green lion", "جرين لايون"),
    "WiWU": ("wiwu", "ويوو"),
    "Belkin": ("belkin", "بيلكن"),
    "Spigen": ("spigen", "سبيجن"),
    "Kieslect": ("kieslect", "كيسليكت"),
    "Amazfit": ("amazfit", "امازفيت", "أمازفيت"),
    "Garmin": ("garmin", "جارمين"),
    "Fitbit": ("fitbit", "فيت بيت"),
    "ZeroTech": ("zerotech", "زيروتك"),
    "Epson": ("epson", "ابسون", "إبسون"),
    "Brother": ("brother", "براذر"),
    "Pantum": ("pantum", "بانتم"),
    "Xerox": ("xerox", "زيروكس"),
    "Nintendo": ("nintendo", "نينتندو"),
    "Microsoft": ("microsoft", "xbox", "مايكروسوفت"),
    "TCL": ("tcl", "تي سي ال", "تي سي إل"),
    "Hisense": ("hisense", "هايسنس"),
    "Skyworth": ("skyworth", "سكاي وورث"),
    "Syinix": ("syinix", "سينكس"),
    "Contex": ("contex", "كونتكس"),
    "JAC": ("jac", "جاك"),
    # --- Home Appliances ---
    "Toshiba": ("toshiba", "توشيبا"),
    "Sharp": ("sharp", "شارب"),
    "Tornado": ("tornado", "تورنيدو"),
    "Fresh": ("fresh", "فريش"),
    "Zanussi": ("zanussi", "زانوسي"),
    "Beko": ("beko", "بيكو"),
    "Bosch": ("bosch", "بوش"),
    "Siemens": ("siemens", "سيمنز"),
    "Electrolux": ("electrolux", "الكترولوكس"),
    "Indesit": ("indesit", "اندست", "إندست"),
    "Ariston": ("ariston", "اريستون", "أريستون"),
    "Hoover": ("hoover", "هوفير"),
    "Candy": ("candy", "كاندي"),
    "Haier": ("haier", "هاير"),
    "Midea": ("midea", "ميديا"),
    "Carrier": ("carrier", "كاريير"),
    "Gree": ("gree", "جري"),
    "York": ("york", "يورك"),
    "Unionaire": ("unionaire", "union air", "يونيون اير"),
    "Kiriazi": ("kiriazi", "كريازي"),
    "White Point": ("white point", "whitepoint", "وايت بوينت"),
    "White Whale": ("white whale", "whitewhale", "وايت ويل"),
    "Universal": ("universal", "يونيفرسال"),
    "La Germania": ("la germania", "lagermania", "لا جيرمانيا"),
    "Olympic Electric": ("olympic electric", "اوليمبيك اليكتريك", "اوليمبيك"),
    "Tank": ("tank water", "تانك"),
    "Passap": ("passap", "باساب"),
    "Electrostar": ("electrostar", "الكتروستار"),
    "Kenwood": ("kenwood", "كينوود"),
    "Braun": ("braun", "براون"),
    "Philips": ("philips", "فيليبس"),
    "Tefal": ("tefal", "تيفال"),
    "Moulinex": ("moulinex", "مولينكس"),
    "Black & Decker": ("black & decker", "black+decker", "black and decker", "blackdecker", "بلاك اند ديكر"),
    "DeLonghi": ("delonghi", "de'longhi", "ديلونجي"),
    "Nespresso": ("nespresso", "نسبريسو"),
    "Krups": ("krups", "كروبس"),
    "Ninja": ("ninja", "نينجا"),
    "Nutribullet": ("nutribullet", "نيوتري بوليت"),
    "KitchenAid": ("kitchenaid", "كيتشن ايد"),
    "Russell Hobbs": ("russell hobbs", "راسل هوبز"),
    "Sokany": ("sokany", "سوكاني"),
    "Sonai": ("sonai", "سوناي"),
    "Mienta": ("mienta", "مينتا"),
    "Black & White": ("black & white", "بلاك اند وايت"),
    "Karcher": ("karcher", "kärcher", "كارشر"),
    "Dyson": ("dyson", "دايسون"),
    "Rowenta": ("rowenta", "روينتا"),
    "BaByliss": ("babyliss", "بيبي ليس"),
    "Remington": ("remington", "ريمنجتون"),
    "Wahl": ("wahl", "وال"),
    "Moser": ("moser", "موزر"),
    "Panasonic": ("panasonic", "باناسونيك"),
    "Hitachi": ("hitachi", "هيتاشي"),
    "Daikin": ("daikin", "دايكن"),
    "CASO": ("caso",),
    "ProfiCook": ("proficook", "profi cook"),
    "Bomann": ("bomann",),
    "Clatronic": ("clatronic",),
    "Heinrich's": ("heinrich's", "heinrichs", "heinrich’s"),
    "GastroBack": ("gastroback",),
    "GGM Gastro": ("ggm gastro",),
    "Cilio": ("cilio",),
    "Purity": ("purity",),
    "Teka": ("teka", "تيكا"),
    "Elba": ("elba", "البا"),
    "Franke": ("franke", "فرانكي"),
    "Faber": ("faber",),
    "Silverline": ("silverline",),
    "Hansa": ("hansa",),
    "Severin": ("severin",),
    "Beurer": ("beurer", "بيورير"),
    "AEG": ("aeg",),
    "Miele": ("miele", "ميلي"),
    # --- Fashion, Footwear, Sports, Luggage ---
    "Nike": ("nike", "نايك", "نايكي"),
    "Adidas": ("adidas", "adidas eg", "اديداس", "أديداس"),
    "Puma": ("puma", "puma eg", "بوما"),
    "Reebok": ("reebok", "ريبوك"),
    "New Balance": ("new balance", "نيو بالانس"),
    "Skechers": ("skechers", "سكيتشرز"),
    "Under Armour": ("under armour", "under armor", "اندر ارمر"),
    "ASICS": ("asics", "اسيكس"),
    "Converse": ("converse", "كونفرس"),
    "Vans": ("vans", "فانز"),
    "Timberland": ("timberland", "timberland eg", "تمبيرلاند", "تيمبرلاند"),
    "Crocs": ("crocs", "كروكس"),
    "Clarks": ("clarks", "كلاركس"),
    "Caterpillar": ("caterpillar", "cat footwear", "كاتربيلر"),
    "Hush Puppies": ("hush puppies", "هاش بابيز"),
    "Merrell": ("merrell", "ميريل"),
    "Salomon": ("salomon", "سالومون"),
    "Columbia": ("columbia", "كولومبيا"),
    "The North Face": ("the north face",),
    "Fila": ("fila", "فيلا"),
    "Kappa": ("kappa", "كابا"),
    "Hummel": ("hummel", "هامل"),
    "Diadora": ("diadora", "ديادورا"),
    "Lotto": ("lotto", "لوتو"),
    "Umbro": ("umbro", "امبرو"),
    "XTEP": ("xtep",),
    "Anta": ("anta", "انتا"),
    "Li-Ning": ("li-ning", "lining"),
    "Decathlon": ("decathlon", "quechua", "kalenji", "domyos", "kipsta", "kiprun", "artengo", "nabaiji", "ديكاتلون"),
    "Aldo": ("aldo", "aldo eg", "الدو", "ألدو"),
    "Steve Madden": ("steve madden", "ستيف مادن"),
    "Nine West": ("nine west", "ناين ويست"),
    "Zara": ("zara", "زارا"),
    "H&M": ("h&m",),
    "Mango": ("mango", "مانجو"),
    "LC Waikiki": ("lc waikiki", "lcw", "ال سي وايكيكي"),
    "DeFacto": ("defacto", "ديفاكتو"),
    "Levi's": ("levi's", "levis", "ليفايز"),
    "Lacoste": ("lacoste", "لاكوست"),
    "Tommy Hilfiger": ("tommy hilfiger", "تومي هيلفيجر"),
    "Calvin Klein": ("calvin klein", "كالفن كلاين"),
    "Ralph Lauren": ("ralph lauren", "رالف لورين"),
    "U.S. Polo Assn.": ("u.s. polo", "us polo", "uspa"),
    "Guess": ("guess", "جيس"),
    "Michael Kors": ("michael kors", "مايكل كورس"),
    "Hugo Boss": ("hugo boss", "هوجو بوس"),
    "Samsonite": ("samsonite", "سامسونايت"),
    "American Tourister": ("american tourister",),
    "Casio": ("casio", "g-shock", "كاسيو"),
    "Seiko": ("seiko", "سيكو"),
    "Citizen": ("citizen", "سيتيزن"),
    "Tissot": ("tissot", "تيسو"),
    "Fossil": ("fossil", "فوسيل"),
    "Swatch": ("swatch", "سواتش"),
    "Ray-Ban": ("ray-ban", "rayban", "راي بان"),
    "Town Team": ("town team", "تاون تيم"),
    "Concrete": ("concrete", "كونكريت"),
    "Mobaco": ("mobaco", "موباكو"),
    "Activ": ("activ", "activ abou alaa", "اكتيف"),
    "Carina": ("carina", "كارينا"),
    "Dalydress": ("dalydress", "daly dress", "دالي دريس"),
    "Dejavu": ("dejavu", "ديجافو"),
    "Khotwh": ("khotwh", "خطوة"),
    "Cottonil": ("cottonil", "قطونيل"),
    "Dice": ("dice", "دايس"),
    "Ravin": ("ravin", "رافين"),
    "Andora": ("andora", "اندورا"),
    "Tie House": ("tie house", "تاي هاوس"),
    "Tie Shop": ("tie shop",),
    "Dott Jeans": ("dott jeans",),
    "Mintra": ("mintra", "مينترا"),
    # --- Beauty, Skincare, Perfumes & Health ---
    "L'Oreal": ("l'oreal", "loreal", "l'oréal", "لوريال"),
    "Maybelline": ("maybelline", "ميبلين"),
    "Garnier": ("garnier", "غارنييه", "جارنييه"),
    "Nivea": ("nivea", "نيفيا"),
    "Dove": ("dove", "دوف"),
    "Vaseline": ("vaseline", "فازلين"),
    "CeraVe": ("cerave", "سيرافي"),
    "La Roche-Posay": ("la roche-posay", "la roche posay", "laroche", "لاروش بوزيه", "لا روش بوزيه"),
    "Vichy": ("vichy", "فيشي"),
    "Bioderma": ("bioderma", "بيوديرما"),
    "Eucerin": ("eucerin", "يوسيرين"),
    "Avene": ("avene", "avène", "افين", "أفين"),
    "Uriage": ("uriage", "يورياج"),
    "SVR": ("svr",),
    "Cetaphil": ("cetaphil", "سيتافيل"),
    "Neutrogena": ("neutrogena", "نيوتروجينا"),
    "The Ordinary": ("the ordinary", "ذا اورديناري"),
    "COSRX": ("cosrx",),
    "Beauty of Joseon": ("beauty of joseon",),
    "Anua": ("anua",),
    "Paula's Choice": ("paula's choice", "paulas choice"),
    "PanOxyl": ("panoxyl",),
    "Kiko Milano": ("kiko milano", "كيكو ميلانو"),
    "Flormar": ("flormar", "فلورمار"),
    "Bourjois": ("bourjois", "بورجوا"),
    "NYX": ("nyx",),
    "MAC": ("mac cosmetics",),
    "Essence": ("essence", "ايسنس"),
    "Catrice": ("catrice", "كاتريس"),
    "Rimmel": ("rimmel", "ريميل"),
    "Max Factor": ("max factor", "ماكس فاكتور"),
    "Cybele": ("cybele", "سيبيل"),
    "Amanda Milano": ("amanda milano", "اماندا ميلانو"),
    "Eva": ("eva cosmetics", "eva skin", "aloe eva", "ايفا"),
    "Luna": ("luna", "لونا"),
    "Bobana": ("bobana", "بوبانا"),
    "Bless": ("bless", "بليس"),
    "Starville": ("starville", "ستارفيل"),
    "Shaan": ("shaan", "شان"),
    "Kolagra": ("kolagra", "كولاجرا"),
    "Infinity": ("infinity", "انفينيتي"),
    "Melano": ("melano", "ميلانو"),
    "Hayah": ("hayah", "حياة"),
    "Cleo": ("cleo", "كليو"),
    "Dermaelle": ("dermaelle",),
    "Neuth": ("neuth",),
    "Telofill": ("telofill",),
    "Dermatique": ("dermatique", "ديرماتيك"),
    "Raw African": ("raw african",),
    "The Hair Addict": ("the hair addict",),
    "Nefertari": ("nefertari", "نفرتاري"),
    "The Body Shop": ("the body shop", "ذا بودي شوب"),
    "Bath & Body Works": ("bath & body works", "bath and body works"),
    "Victoria's Secret": ("victoria's secret", "victorias secret"),
    "Dior": ("dior", "christian dior", "ديور"),
    "Chanel": ("chanel", "شانيل"),
    "Yves Saint Laurent": ("yves saint laurent", "ysl", "ايف سان لوران"),
    "Giorgio Armani": ("giorgio armani", "armani", "ارماني"),
    "Gucci": ("gucci", "جوتشي"),
    "Versace": ("versace", "فرزاتشي"),
    "Carolina Herrera": ("carolina herrera",),
    "Jean Paul Gaultier": ("jean paul gaultier",),
    "Paco Rabanne": ("paco rabanne", "rabanne"),
    "Burberry": ("burberry", "بربري"),
    "Lancôme": ("lancome", "lancôme", "لانكوم"),
    "Lattafa": ("lattafa", "لطافة"),
    "Armaf": ("armaf", "ارماف"),
    "Afnan": ("afnan", "افنان"),
    "Rasasi": ("rasasi", "رصاصي"),
    "Pantene": ("pantene", "بانتين"),
    "Head & Shoulders": ("head & shoulders", "head and shoulders", "هيد اند شولدرز"),
    "Sunsilk": ("sunsilk", "صانسيلك"),
    "TRESemme": ("tresemme", "tresemmé", "تريسيمي"),
    "Herbal Essences": ("herbal essences",),
    "Clear": ("clear shampoo",),
    "Olaplex": ("olaplex", "اولابلكس"),
    "Kerastase": ("kerastase", "kérastase", "كيراستاس"),
    "Oral-B": ("oral-b", "oral b", "اورال بي"),
    "Sensodyne": ("sensodyne", "سنسوداين"),
    "Signal": ("signal", "سيجنال"),
    "Colgate": ("colgate", "كولجيت"),
    "Gillette": ("gillette", "جيليت"),
    "Rexona": ("rexona", "ريكسونا"),
    "Old Spice": ("old spice",),
    "Optimum Nutrition": ("optimum nutrition", "اوبتيمم نيوترشن"),
    "Dymatize": ("dymatize", "دايماتايز"),
    "MuscleTech": ("muscletech", "ماسل تك"),
    "BSN": ("bsn",),
    "MyProtein": ("myprotein", "my protein"),
    "Rule 1": ("rule 1", "rule one"),
    "Kevin Levrone": ("kevin levrone",),
    "Applied Nutrition": ("applied nutrition",),
    "NOW Foods": ("now foods", "ناو فودز"),
    "Solgar": ("solgar", "سولجار"),
    "Centrum": ("centrum", "سنتروم"),
    "Limitless": ("limitless", "ليمتلس"),
    "Organic Nation": ("organic nation",),
    "Max Muscle": ("max muscle", "ماكس ماسل"),
    # --- Groceries, Coffee, Baby, Pet, Home ---
    "Juhayna": ("juhayna", "جهينة", "جهينه"),
    "Beyti": ("beyti", "بيتي"),
    "Lamar": ("lamar", "لمار"),
    "Almarai": ("almarai", "المراعي"),
    "Domty": ("domty", "دومتي"),
    "Obour Land": ("obour land", "obourland", "عبور لاند"),
    "President": ("president", "président", "بريزيدون"),
    "Kiri": ("kiri", "كيري"),
    "La Vache Qui Rit": ("la vache qui rit", "لافاش كيري"),
    "Crystal": ("crystal", "كريستال"),
    "Afia": ("afia", "عافية"),
    "Slite": ("slite", "سلايت"),
    "Rawabi": ("rawabi", "روابي"),
    "Ganna": ("ganna", "جنة"),
    "Fern": ("fern", "فيرن"),
    "Lurpak": ("lurpak", "لورباك"),
    "El Doha": ("el doha", "eldoha", "الضحى", "الضحي"),
    "El Maleka": ("el maleka", "elmaleka", "الملكة", "الملكه"),
    "Italiano": ("italiano", "ايطاليانو"),
    "Regina": ("regina", "ريجينا"),
    "Barilla": ("barilla", "باريلا"),
    "Indomie": ("indomie", "اندومي", "إندومي"),
    "Nescafe": ("nescafe", "nescafé", "نسكافيه"),
    "Lipton": ("lipton", "ليبتون"),
    "El Arosa": ("el arosa", "elarosa", "العروسة", "العروسه"),
    "Ahmad Tea": ("ahmad tea", "احمد تي"),
    "Dilmah": ("dilmah", "ديلما"),
    "Twinings": ("twinings", "تويننجز"),
    "Lavazza": ("lavazza", "لافازا"),
    "Illy": ("illy", "ايلي"),
    "Starbucks": ("starbucks", "ستاربكس"),
    "Davidoff": ("davidoff", "دافيدوف"),
    "Jacobs": ("jacobs", "جاكوبس"),
    "Abu Auf": ("abu auf", "abuauf", "ابو عوف", "أبو عوف"),
    "Heinz": ("heinz", "هاينز"),
    "Harvest": ("harvest", "هارفست"),
    "Vitrac": ("vitrac", "فيتراك"),
    "Hero": ("hero baby", "hero jam", "هيرو"),
    "Isis": ("isis", "ايزيس"),
    "Imtenan": ("imtenan", "امتنان"),
    "Sunshine": ("sunshine", "صن شاين"),
    "Dolphin": ("dolphin", "دولفين"),
    "Americana": ("americana", "امريكانا"),
    "Halwani": ("halwani", "حلواني"),
    "Atyab": ("atyab", "اطياب"),
    "Koki": ("koki", "كوكي"),
    "Pepsi": ("pepsi", "بيبسي"),
    "Coca-Cola": ("coca-cola", "coca cola", "كوكاكولا"),
    "Schweppes": ("schweppes", "شويبس"),
    "Baraka": ("baraka", "بركة"),
    "Nestle": ("nestle", "nestlé", "نستله"),
    "Red Bull": ("red bull", "ريد بول"),
    "Cadbury": ("cadbury", "كادبوري"),
    "KitKat": ("kitkat", "kit kat", "كيت كات"),
    "Kinder": ("kinder", "كيندر"),
    "Nutella": ("nutella", "نوتيلا"),
    "Oreo": ("oreo", "اوريو"),
    "Ariel": ("ariel", "اريال", "أريال"),
    "Persil": ("persil", "برسيل"),
    "Tide": ("tide", "تايد"),
    "Oxi": ("oxi", "اوكسي"),
    "Downy": ("downy", "داوني"),
    "Comfort": ("comfort", "كومفورت"),
    "Fairy": ("fairy", "فيري"),
    "Pril": ("pril", "بريل"),
    "Clorox": ("clorox", "كلوركس"),
    "Dettol": ("dettol", "ديتول"),
    "Harpic": ("harpic", "هاربيك"),
    "Finish": ("finish", "فينيش"),
    "Fine": ("fine", "فاين"),
    "Zeina": ("zeina", "زينة"),
    "Pampers": ("pampers", "بامبرز"),
    "Molfix": ("molfix", "مولفيكس"),
    "BabyJoy": ("babyjoy", "baby joy", "بيبي جوي"),
    "Chicco": ("chicco", "شيكو"),
    "Philips Avent": ("philips avent", "avent", "افينت"),
    "LEGO": ("lego", "ليجو"),
    "Hot Wheels": ("hot wheels",),
    "Barbie": ("barbie", "باربي"),
    "Fisher-Price": ("fisher-price", "fisher price"),
    "Intex": ("intex", "انتكس"),
    "Bestway": ("bestway", "بيست واي"),
    "Royal Canin": ("royal canin", "رويال كانين"),
    "Whiskas": ("whiskas", "ويسكاس"),
    "Friskies": ("friskies", "فريسكيز"),
    "Purina": ("purina", "pro plan", "proplan", "بورينا"),
    "Pedigree": ("pedigree", "بيديجري"),
    "Josera": ("josera", "جوسيرا"),
    "Leonardo": ("leonardo", "ليوناردو"),
    "Reflex": ("reflex", "ريفلكس"),
    "Belcando": ("belcando",),
    "Bewi": ("bewi",),
    "Wanpy": ("wanpy",),
    "Imac": ("imac",),
    "Miglior": ("miglior", "migliorgatto", "migliorcane"),
    "Monge": ("monge",),
    "Happy Cat": ("happy cat",),
    "Happy Dog": ("happy dog",),
    "Carnilove": ("carnilove",),
    "Farmina": ("farmina",),
    "GimCat": ("gimcat",),
    "Trixie": ("trixie",),
    "Catit": ("catit",),
    "Beaphar": ("beaphar",),
    "Sanicat": ("sanicat",),
    "Inaba": ("inaba", "churu"),
    "Sheba": ("sheba",),
    "Felix": ("felix",),
    "Tupperware": ("tupperware", "تابروير"),
    "Neoflam": ("neoflam", "نيوفلام"),
    "Nouval": ("nouval", "نوفال"),
    "El Zenouki": ("el zenouki", "elzenouki", "الزنوكي"),
    "Zahran": ("zahran", "زهران"),
    "Pyrex": ("pyrex", "بايركس"),
    "Luminarc": ("luminarc", "لومينارك"),
    "IKEA": ("ikea", "ايكيا", "إيكيا"),
    "Oriental Weavers": ("oriental weavers", "النساجون الشرقيون"),
    "Kabbani": ("kabbani", "قباني"),
    "Ariika": ("ariika", "اريكة"),
    "Janssen": ("janssen", "يانسن"),
    "Habitat": ("habitat", "هابيتات"),
}

# Short/ambiguous English words that must only match as standalone tokens (never inside titles loosely)
_AMBIGUOUS_TITLE_ALIASES: frozenset[str] = frozenset(
    {
        "fine", "hero", "fresh", "clear", "guess", "mango", "crystal", "anchor",
        "universal", "candy", "apple", "galaxy", "corona", "dolphin", "sunshine",
        "harvest", "comfort", "finish", "signal", "bloody", "dice", "bless", "luna",
        "cat", "mac", "nothing", "brother", "boss", "polo",
    }
)


def _norm_key(text: str) -> str:
    s = _AR_DIACRITICS_RE.sub("", (text or "").strip().lower()).translate(_AR_NORM_TRANS)
    return re.sub(r"\s+", " ", s).strip()


# Build fast O(1) exact alias map + O(tokens) n-gram lookup (trigrams -> bigrams -> unigrams)
_EXACT_ALIAS_MAP: dict[str, str] = {}
_NGRAM_ALIAS_MAP: dict[str, str] = {}

for _canonical, _aliases in CANONICAL_BRAND_ALIASES.items():
    _EXACT_ALIAS_MAP[_norm_key(_canonical)] = _canonical
    for _alias in _aliases:
        _nk = _norm_key(_alias)
        if not _nk:
            continue
        _EXACT_ALIAS_MAP[_nk] = _canonical
        if _nk not in _AMBIGUOUS_TITLE_ALIASES and len(_nk) >= 2:
            _NGRAM_ALIAS_MAP[_nk] = _canonical

_TOKEN_RE = re.compile(r"[a-z0-9\u0600-\u06FF]+(?:['&+.\-][a-z0-9\u0600-\u06FF]+)*", re.I)

# Leading-token ambiguous aliases that ARE safe when appearing as the very first word of a title
_LEADING_SAFE_ALIASES: dict[str, str] = {
    "fresh": "Fresh",
    "apple": "Apple",
    "mango": "Mango",
    "guess": "Guess",
    "crystal": "Crystal",
    "universal": "Universal",
    "candy": "Candy",
    "hero": "Hero",
    "fine": "Fine",
    "brother": "Brother",
    "luna": "Luna",
    "bless": "Bless",
    "dice": "Dice",
    "signal": "Signal",
    "comfort": "Comfort",
    "finish": "Finish",
    "harvest": "Harvest",
    "sunshine": "Sunshine",
    "dolphin": "Dolphin",
    "bloody": "Bloody",
}


def is_placeholder_brand(raw_brand: Optional[str], store_name: str = "") -> bool:
    """Return True if `raw_brand` is missing, generic, or a multi-brand retailer name."""
    store_key = (store_name or "").strip().lower()
    nk = _norm_key(raw_brand or "")
    if not nk:
        return True
    # Single-brand / private-label stores own their store brand name (unless literal My Store/Unknown/Generic)
    if store_key in SINGLE_BRAND_STORES:
        return nk in {"unknown", "generic", "other", "none", "null", "n/a", "na", "n_a", "brand", "unbranded", "default", "various", "no brand", "no_brand", "my store", "my_store", "store", "vendor"}
    if nk in PLACEHOLDER_BRANDS:
        return True
    if store_key in MULTI_BRAND_RETAILERS:
        s_norm = _norm_key(store_key).replace("_", " ")
        if nk.replace("_", " ").replace("-", " ") == s_norm:
            return True
    return False


def extract_brand_from_text(text: str, *, strip_compat: bool = True) -> Optional[str]:
    """Extract canonical brand from a bilingual Arabic/English product title or URL slug (O(tokens))."""
    if not text:
        return None
    cleaned = _COMPAT_TAIL_RE.sub("", text) if strip_compat else text
    norm = _norm_key(cleaned)
    if not norm:
        return None

    tokens = _TOKEN_RE.findall(norm)
    if not tokens:
        return None

    # Check leading-token safe brands first (e.g. "Fresh 1.5HP AC", "Apple iPhone 16")
    if tokens[0] in _LEADING_SAFE_ALIASES:
        return _LEADING_SAFE_ALIASES[tokens[0]]

    # Check longest n-grams first (4 -> 3 -> 2 -> 1) in O(len(tokens))
    n = len(tokens)
    for size in (4, 3, 2, 1):
        if n < size:
            continue
        for i in range(n - size + 1):
            phrase = tokens[i] if size == 1 else " ".join(tokens[i : i + size])
            hit = _NGRAM_ALIAS_MAP.get(phrase)
            if hit:
                return hit
            # Handle Arabic definite prefix "ال" (e.g. "السامسونج" / "الباناسونيك")
            if size == 1 and len(phrase) > 4 and phrase.startswith("ال"):
                hit2 = _NGRAM_ALIAS_MAP.get(phrase[2:])
                if hit2:
                    return hit2
    return None


def _extract_brand_from_url(product_url: str) -> Optional[str]:
    if not product_url:
        return None
    try:
        path = urlparse(product_url).path
    except Exception:
        return None
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        return None
    slug_text = re.sub(r"[-_]+", " ", slug)
    return extract_brand_from_text(slug_text, strip_compat=True)


def normalize_product_brand(
    raw_brand: Optional[str],
    *,
    product_title: str = "",
    store_name: str = "",
    product_url: str = "",
    attributes_json: Optional[Mapping[str, Any]] = None,
) -> str:
    """Resolve and normalize a product's canonical display brand in pure Python.

    Priority order:
      1. If `raw_brand` is valid (not placeholder/retailer-as-brand):
         canonicalize via exact AR/EN alias map or preserve clean display casing.
      2. Official single-brand store mapping (`SINGLE_BRAND_STORES`).
      3. Structured attribute hint (`attributes_json['brand'|'manufacturer'|'vendor']`).
      4. Bilingual Arabic + English title extraction (excluding `for <Brand>` clauses).
      5. URL slug extraction.
      6. Fallback `"Generic"` (when title explicitly starts with `"Generic "`) or `"Unknown"`.
    """
    store_key = (store_name or "").strip().lower()
    raw_clean = re.sub(r"\s+", " ", (raw_brand or "").strip())
    raw_norm = _norm_key(raw_clean)

    # 1. Valid non-placeholder brand -> canonicalize via alias dictionary
    if raw_clean and not is_placeholder_brand(raw_clean, store_key):
        if raw_norm in _EXACT_ALIAS_MAP:
            return _EXACT_ALIAS_MAP[raw_norm]
        # Strip trailing country/store noise like "PUMA EG" / "ALDO Egypt"
        stripped_eg = re.sub(r"\s+(?:eg|egypt|official|store)$", "", raw_norm).strip()
        if stripped_eg and stripped_eg in _EXACT_ALIAS_MAP:
            return _EXACT_ALIAS_MAP[stripped_eg]
        # Clean ALL-CAPS multi-char brands (keep short acronyms like LG, HP, MSI, JBL)
        if raw_clean.isupper() and len(raw_clean) > 4 and " " not in raw_clean:
            return raw_clean.title()[:100]
        return raw_clean[:100]

    # 2. Official single-brand store
    if store_key in SINGLE_BRAND_STORES:
        return SINGLE_BRAND_STORES[store_key]

    # 3. Attributes hint
    if isinstance(attributes_json, Mapping):
        for attr_key in ("brand", "manufacturer", "vendor"):
            val = attributes_json.get(attr_key)
            if isinstance(val, str) and val.strip() and not is_placeholder_brand(val, store_key):
                nk = _norm_key(val)
                return _EXACT_ALIAS_MAP.get(nk, val.strip()[:100])

    # 4. Bilingual title extraction (respecting compatibility clauses)
    # If a title literally begins with "Generic ", only extract a real brand if NOT followed by "for ..."
    title_clean = (product_title or "").strip()
    starts_generic = title_clean.lower().startswith("generic ")
    extracted = extract_brand_from_text(
        title_clean[8:] if starts_generic else title_clean,
        strip_compat=True,
    )
    if extracted and not (starts_generic and any(w in title_clean.lower() for w in ("case", "cover", "cap", "hood", "protector", "bag", "strap"))):
        return extracted

    # 5. URL slug extraction (skip when explicitly marked "Generic ..." accessory)
    if not starts_generic:
        url_brand = _extract_brand_from_url(product_url)
        if url_brand:
            return url_brand

    return "Generic" if starts_generic else "Unknown"
