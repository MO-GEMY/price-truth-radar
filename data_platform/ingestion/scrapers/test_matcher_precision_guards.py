"""Catalog-wide cross-store matching precision regression tests.

Covers:
1. Both live user-reported false positives (Gigabyte B850M D3HP vs B850 A Stealth;
   Cooler Master GX II Gold 850W vs GX III Gold 1250W).
2. Systemic false-match patterns discovered in the Phase 1 full-catalog audit across
   all 10 categories (Electronics, Home Appliances, Groceries, Health, Beauty,
   Fashion, Sports, Baby/Kids, Pet Care, Home Furniture).
3. Positive tests confirming genuine identical SKUs across stores still match cleanly.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from data_platform.ingestion.scrapers.base import RawProductSnapshot
from data_platform.ingestion.scrapers.matcher import assign_canonical_keys

_SNAP_DATE = date(2026, 11, 25)


def _rec(
    store: str,
    title: str,
    *,
    category: str = "electronics",
    sub_category: str = "components",
    brand: str = "Unknown",
    price: float = 1000.0,
    attrs: dict | None = None,
    ext_id: str | None = None,
) -> RawProductSnapshot:
    return RawProductSnapshot(
        store_name=store,
        external_id=ext_id or f"{store}-{abs(hash(title)) % 100000}",
        category=category,  # type: ignore[arg-type]
        sub_category=sub_category,
        brand=brand,
        product_title=title,
        product_url=f"https://example.com/{store}/item",
        image_url=None,
        attributes_json=attrs or {},
        current_price=Decimal(f"{price:.2f}"),
        claimed_original_price=None,
        in_stock=True,
        snapshot_date=_SNAP_DATE,
        scraped_at=datetime(2026, 11, 25, 4, 0),
    )


def _matched(r1: RawProductSnapshot, r2: RawProductSnapshot) -> bool:
    assign_canonical_keys([r1, r2])
    return r1.canonical_product_key is not None and r1.canonical_product_key == r2.canonical_product_key


class TestReportedFalsePositives(unittest.TestCase):
    def test_gigabyte_b850m_d3hp_vs_b850_a_stealth_blocked(self):
        a = _rec(
            "sigma",
            "Gigabyte B850M D3HP",
            sub_category="motherboards",
            brand="Gigabyte",
            price=7600,
        )
        b = _rec(
            "alfrensia",
            "Gigabyte B850 A Stealth Socket AM5 DDR5 ATX",
            sub_category="motherboards",
            brand="Gigabyte",
            price=16899,
        )
        self.assertFalse(_matched(a, b))

    def test_cooler_master_gx_ii_850w_vs_gx_iii_1250w_blocked(self):
        a = _rec(
            "alfrensia",
            "Cooler Master GX II Gold 850 850W",
            sub_category="psus",
            brand="Cooler Master",
            price=4900,
        )
        b = _rec(
            "sigma",
            "Cooler Master GX III Gold 1250W",
            sub_category="psus",
            brand="Cooler Master",
            price=10999,
        )
        self.assertFalse(_matched(a, b))


class TestElectronicsAndAppliancesPrecisionGuards(unittest.TestCase):
    def test_motherboard_series_and_trim_vetoes(self):
        # MSI MPG X870E CARBON WIFI vs MSI MEG X870E GODLIKE WIFI
        c1 = _rec("up_to_date_eg", "MSI MPG X870E CARBON WIFI", sub_category="motherboards", brand="MSI", price=26000)
        c2 = _rec("ahw_store", "MSI MEG X870E GODLIKE WIFI DDR5 AM5 ATX Motherboard Black", sub_category="motherboards", brand="MSI", price=62999)
        self.assertFalse(_matched(c1, c2))

        # MSI Pro B650M P vs MSI PRO B650M A WIFI
        p1 = _rec("alfrensia", "Msi Pro B650M P Motherboard", sub_category="motherboards", brand="MSI", price=6090)
        p2 = _rec("compumarts", "MSI PRO B650M A WIFI DDR5 AM5 Motherboard", sub_category="motherboards", brand="MSI", price=14650)
        self.assertFalse(_matched(p1, p2))

    def test_pc_build_chipset_never_merges_different_builds(self):
        b1 = _rec("gc_hardware", "Intel Core i5-12400F 16GB RAM 256GB SSD B760 Desktop PC Build", brand="Intel", price=24999)
        b2 = _rec("baraka_computer", "5050/14400F/B760 RTX Gaming PC", brand="Intel", price=62000)
        self.assertFalse(_matched(b1, b2))

    def test_ram_capacity_and_mhz_cl_guards(self):
        # Single-capacity 32GB vs 8GB DDR4 RAM
        r1 = _rec("alfrensia", "Klevv 32Gb DDR4 3200Mhz Udimm Desktop Memory", sub_category="memory", brand="Klevv", price=2651)
        r2 = _rec("sigma", "KLEVV DDR4 8GB 3200MHz UDIMM Desktop Memory", sub_category="memory", brand="Klevv", price=3350)
        self.assertFalse(_matched(r1, r2))

        # DDR5 5600MHz CL30 vs DDR5 6000MHz CL30 (`cl30` must not act as model code!)
        g1 = _rec("alfrensia", "G Skill Trident Z5 Neo RGB 32Gb ( 2X16Gb ) DDR5 5600Mhz CL30 Desktop Memory", sub_category="memory", brand="G.Skill", price=6001)
        g2 = _rec("compumarts", "RAM G.SKILL/F5-6000J3036F16GX2-TZ5NRW/Trident Z5 Neo RGB-DDR5-6000 CL30-32GB (2x16GB)", sub_category="memory", brand="G.Skill", price=14545)
        self.assertFalse(_matched(g1, g2))

    def test_monitor_submodel_suffix_and_tv_size_guards(self):
        # MSI MAG 274QPF E20 vs X30MV
        m1 = _rec("alfrensia", "Msi Mag 274Qpf E20 27 Inch WQHD 200Hz Rapid Ips Gaming Monitor", sub_category="monitors", brand="MSI", price=9999)
        m2 = _rec("ahw_store", "MSI MAG 274QPF X30MV 27 WQHD Gaming Monitor", sub_category="monitors", brand="MSI", price=24360)
        self.assertFalse(_matched(m1, m2))

        # Samsung 65" S90F vs 77 Inch S90F (quote inch mark!)
        t1 = _rec("cairosales", 'SAMSUNG 65" Class OLED S90F 4K Vision AI Smart TV 65S90F', category="home_appliances", sub_category="tvs", brand="Samsung", price=78889)
        t2 = _rec("ehab_center", "Samsung Class OLED 4K Smart TV S90F 77 Inch 77S90F", category="home_appliances", sub_category="tvs", brand="Samsung", price=153357)
        self.assertFalse(_matched(t1, t2))

        # Samsung 85 Inch 85QN80H vs 100-Inch 100QN80H (3-digit screen size!)
        q1 = _rec("ehab_center", "Samsung Neo QLED QN80H 4K Vision AI Smart 85 Inch 85QN80H", category="home_appliances", sub_category="tvs", brand="Samsung", price=170999)
        q2 = _rec("cairosales", "Samsung 100-Inch Class Neo QLED QN80H 4K Vision AI Smart TV 100QN80H", category="home_appliances", sub_category="tvs", brand="Samsung", price=318249)
        self.assertFalse(_matched(q1, q2))

    def test_networking_speed_and_cross_device_type_isolation(self):
        # Extender vs Router sharing AC1200
        n1 = _rec("alfrensia", "Tplink Ac1200 Re315 Dual Band Mesh Wifi Extender", sub_category="networking", brand="TP-Link", price=750)
        n2 = _rec("rayashop", "TP-Link Wireless Dual Band Router Archer, White - AC1200", sub_category="networking", brand="TP-Link", price=1864)
        self.assertFalse(_matched(n1, n2))

        # Different modem routers sharing 300Mbps
        w1 = _rec("alfrensia", "Tplink Td W8961N 300Mbps Wireless N Adsl2 Modem Router", sub_category="networking", brand="TP-Link", price=390)
        w2 = _rec("kimostore", "TP-Link TD-W9950 VDSL/ADSL Modem Router 4 Ports 2 Antenna 300Mbps", sub_category="networking", brand="TP-Link", price=950)
        self.assertFalse(_matched(w1, w2))

        # Mouse vs Headset sharing 3-Mode
        d1 = _rec("hardware_market", "Redragon M815 STD 3-Mode Wireless Optical Sensor 12000 DPI Gaming Mouse", sub_category="peripherals", brand="Redragon", price=1099)
        d2 = _rec("alfrensia", "Redragon H878 3-Mode Wireless Lighting Black Grey Gaming Headset", sub_category="peripherals", brand="Redragon", price=2650)
        self.assertFalse(_matched(d1, d2))

        # HyperX QuadCast 2 vs QuadCast 2 S
        mic1 = _rec("up_to_date_eg", "HyperX QuadCast 2 – USB Microphone", sub_category="audio", brand="HyperX", price=6200)
        mic2 = _rec("alfrensia", "Hyperx QuadCast 2 S RGB USB Microphone", sub_category="audio", brand="HyperX", price=9358)
        self.assertFalse(_matched(mic1, mic2))

    def test_home_appliances_2door_liters_and_cooker_dimensions(self):
        # Kiriazi 330L Defrost K330 vs 480L No Frost E520NV-2 sharing 2-Door
        f1 = _rec("raneen", "Kiriazi Defrost Refrigerator, 330 Liters, 2-Door, K330 (20010012) - Black", category="home_appliances", sub_category="refrigerators", brand="Kiriazi", price=15699)
        f2 = _rec("elghazawy", "Kiriazi Refrigerator Fairouza Turbo 480 Liters No Frost 2-Door E520NV-2 - Black", category="home_appliances", sub_category="refrigerators", brand="Kiriazi", price=34500)
        self.assertFalse(_matched(f1, f2))

        # Fresh Forno 80x55 vs Fresh Hummer 7430 80x55 (`80x55` must not act as model code!)
        k1 = _rec("fresh_eg", "Fresh Gas Cooker Forno Stainless Fan 80x55", category="home_appliances", sub_category="cookers", brand="Fresh", price=12223)
        k2 = _rec("raneen", "Fresh Hummer 7430 Full Stainless Gas Cooker, 5 Gas Burners, 80x55 cm - Black", category="home_appliances", sub_category="cookers", brand="Fresh", price=20499)
        self.assertFalse(_matched(k1, k2))


class TestHealthBeautyGroceriesAndVerticalGuards(unittest.TestCase):
    def test_health_servings_and_caps_never_match_different_supplements(self):
        # 30serv: Glutamine vs Iso Whey
        s1 = _rec("beseha", "Glutamine Muscle Tech 30serv | Pure L-Glutamine", category="health", sub_category="supplements", brand="MuscleTech", price=1500)
        s2 = _rec("max_muscle_eg", "Iso Whey.-30Serv.-907G | MuscleTech", category="health", sub_category="supplements", brand="MuscleTech", price=3490)
        self.assertFalse(_matched(s1, s2))

        # 30serv: Multivitamin vs IsoFit Protein
        n1 = _rec("max_muscle_eg", "Vitadapt Complete Sports Multivitamin.-30Serv.-90Tabs | Nutrex Research", category="health", sub_category="supplements", brand="Nutrex", price=1590)
        n2 = _rec("mfsupps_eg", "Nutrex Research, IsoFit, 1kg, 30 Servings", category="health", sub_category="supplements", brand="Nutrex", price=3100)
        self.assertFalse(_matched(n1, n2))

        # 100Tablets: Chromium Picolinate vs Liposomal Zinc Gluconate
        o1 = _rec("gofit_eg", "Organic Nation Chromium Picolinate 200mcg | 100 Tablets", category="health", sub_category="supplements", brand="Organic Nation", price=251)
        o2 = _rec("organic_nation", "Liposomal Zinc Gluconate-100Serv.-100Tablets", category="health", sub_category="supplements", brand="Organic Nation", price=450)
        self.assertFalse(_matched(o1, o2))

    def test_beauty_form_and_day_vs_night_vetoes(self):
        # Ampoule vs Ampoule Foam
        a1 = _rec("faces_eg", "Skin1004 Madagascar Centella Ampoule", category="beauty", sub_category="skincare", brand="Skin1004", price=463)
        a2 = _rec("source_beauty", "Centella Ampoule Foam — 125ml", category="beauty", sub_category="skincare", brand="Skin1004", price=1130)
        self.assertFalse(_matched(a1, a2))

        # Sunscreen Cream vs Sunscreen Gel
        b1 = _rec("el_ezaby", "BOBAI SUNSCREEN CREAM SPF+50 TINTED 60 ML", category="beauty", sub_category="skincare", brand="Bobai", price=225)
        b2 = _rec("source_beauty", "Tinted Sunscreen Gel SPF 50+", category="beauty", sub_category="skincare", brand="Bobai", price=325)
        self.assertFalse(_matched(b1, b2))

        # Night Cream vs Day Cream
        d1 = _rec("bloom_pharmacy", "Clarins Extra Firming Night Cream Dry Skin - 50ml", category="beauty", sub_category="skincare", brand="Clarins", price=4406)
        d2 = _rec("malak_eg", "Extra Firming Day Cream for Dry Skin 50 ml", category="beauty", sub_category="skincare", brand="Clarins", price=5336)
        self.assertFalse(_matched(d1, d2))

    def test_groceries_varieties_bundles_lines_and_sugarfree_vetoes(self):
        # Gouda vs Parmesan cheese
        c1 = _rec("seoudi", "Saluti Gouda Cheese - 250 g", category="groceries", sub_category="dairy_cheese", brand="Saluti", price=199)
        c2 = _rec("spinneys", "Saluti - Parmesan Cheese - 250g", category="groceries", sub_category="dairy_cheese", brand="Saluti", price=435)
        self.assertFalse(_matched(c1, c2))

        # Single Oil vs Oil + Corn Oil bundle
        o1 = _rec("spinneys", "Katfa Sunflower Oil, 700 ml", category="groceries", sub_category="oils_ghee", brand="Katfa", price=69)
        o2 = _rec("seoudi", "Katfa Sunflower Oil - 700 ml + Corn Oil - 700 ml", category="groceries", sub_category="oils_ghee", brand="Katfa", price=150)
        self.assertFalse(_matched(o1, o2))

        # Juhayna Classic vs Pure Juice
        j1 = _rec("amazon_eg", "Juhayna classic guava juice, 1 liter", category="groceries", sub_category="beverages", brand="Juhayna", price=35)
        j2 = _rec("spinneys", "Juhayna - Pure Guava Juice - 1l", category="groceries", sub_category="beverages", brand="Juhayna", price=74)
        self.assertFalse(_matched(j1, j2))

        # Quinoa Flour vs Almond Flour
        f1 = _rec("imtenan", "Organic Quinoa Flour - rich protein 500 gm", category="groceries", sub_category="baking", brand="Imtenan", price=230)
        f2 = _rec("seoudi", "Imtenan Gluten Free Almond Flour - 500 g", category="groceries", sub_category="baking", brand="Imtenan", price=480)
        self.assertFalse(_matched(f1, f2))

        # Regular Ice Tea vs Sugar-Free Ice Tea
        t1 = _rec("seoudi", "Lipton Peach Ice Tea - 330 ml", category="groceries", sub_category="beverages", brand="Lipton", price=70)
        t2 = _rec("noon", "Lipton Peach Iced Tea (Sugar-Free) 330ml", category="groceries", sub_category="beverages", brand="Lipton", price=145)
        self.assertFalse(_matched(t1, t2))

        # Dairy Half Cream Milk vs Almond Milk
        m1 = _rec("spinneys", "Juhayna - Milk Half Cream Save 10LE - 6*1l", category="groceries", sub_category="dairy_cheese", brand="Juhayna", price=320)
        m2 = _rec("noon", "Juhayna Almond Milk 1Liters Pack of 6", category="groceries", sub_category="dairy_cheese", brand="Juhayna", price=636)
        self.assertFalse(_matched(m1, m2))

        # Brazilian Coffee vs Turkish Coffee with Cardamom
        cf1 = _rec("abu_auf", "Medium Roasted blended Brazilian Coffee – 100gm", category="groceries", sub_category="tea_coffee", brand="Abu Auf", price=104)
        cf2 = _rec("seoudi", "Abu Auf Medium Turkish Coffee with Cardamom - 100 g", category="groceries", sub_category="tea_coffee", brand="Abu Auf", price=158)
        self.assertFalse(_matched(cf1, cf2))

    def test_fashion_toys_pet_and_furniture_guards(self):
        # Skechers Glide-Step 2.0 Maria vs Belah
        fw1 = _rec("skechers_shop_eg", "Women's Skechers Slip-ins: GO WALK Glide-Step 2.0 – Maria Sneakers Black", category="fashion", sub_category="shoes", brand="Skechers", price=3256)
        fw2 = _rec("wayup_sports", "Go Walk Glide-Step 2.0 - Belah Shoes", category="fashion", sub_category="shoes", brand="Skechers", price=7049)
        self.assertFalse(_matched(fw1, fw2))

        # Generic "Cross Training Shoes" non-model title
        sp1 = _rec("wayup_sports", "Cross Training Shoes", category="sports", sub_category="sports_shoes", brand="Anta", price=2370)
        sp2 = _rec("intersport_eg", "Anta Cross Training Shoes For Women, Beige", category="sports", sub_category="sports_shoes", brand="Anta", price=4739)
        self.assertFalse(_matched(sp1, sp2))

        # Lego Medium vs Large Creative Brick Box
        ty1 = _rec("ourkids_eg", "Lego Classic Medium Creative Brick Box", category="baby_kids", sub_category="toys", brand="Lego", price=2699)
        ty2 = _rec("hedeya", "Large Creative Brick", category="baby_kids", sub_category="toys", brand="Lego", price=4700)
        self.assertFalse(_matched(ty1, ty2))

        # Spoon & Fork Set vs (Plate + Spoon + Fork) Set
        bk1 = _rec("hedeya", "Spoon & Fork Set", category="baby_kids", sub_category="feeding", brand="La Frutta", price=90)
        bk2 = _rec("ourkids_eg", "La Frutta (Plate + Spoon + Fork) Set For Kids – Purple", category="baby_kids", sub_category="feeding", brand="La Frutta", price=170)
        self.assertFalse(_matched(bk1, bk2))

        # Non-clumping vs Clumping cat litter
        pt1 = _rec("amin_pet_shop", "Sanicat Classic Marseille Soap Non-Clumping Cat Litter 10 L", category="pet_care", sub_category="cat_litter", brand="Sanicat", price=340)
        pt2 = _rec("pets_egypt", "Sanicat Clumping White Active Marseille Soap Scented Cat Litter 10 L", category="pet_care", sub_category="cat_litter", brand="Sanicat", price=475)
        self.assertFalse(_matched(pt1, pt2))

        # Pet litter sizeless (5L price) vs 10L
        pt3 = _rec("pets_egypt", "Promaster Clumping Cat Litter Baby Powder Scented", category="pet_care", sub_category="cat_litter", brand="Promaster", price=180)
        pt4 = _rec("amin_pet_shop", "Promaster - Baby Powder Scented Clumping Cat Litter 10L", category="pet_care", sub_category="cat_litter", brand="Promaster", price=306)
        self.assertFalse(_matched(pt3, pt4))

        # Mattress 100cm vs 140cm / 195cm AND rival mattress brands ("pocket" must NOT be inferred as brand!)
        mt1 = _rec("mffco", "مرتبة بوكيت 30-100سم", category="home_furniture", sub_category="mattresses", brand="Janssen", price=5600)
        mt2 = _rec("bed_janssen", "مرتبة بوكيت قطن30 — 140CM / 195CM", category="home_furniture", sub_category="mattresses", brand="Janssen", price=10755)
        self.assertFalse(_matched(mt1, mt2))

        mt3 = _rec("mffco", "مرتبة بوكيت 30-180سم", category="home_furniture", sub_category="mattresses", brand="Unknown", price=9310)
        mt4 = _rec("bed_janssen", "مرتبة بوكيت قطن30 — 180CM / 190CM", category="home_furniture", sub_category="mattresses", brand="Unknown", price=13828)
        self.assertFalse(_matched(mt3, mt4))

        # Adidas Supernova Ease Men vs Supernova Ease 2 W (version 2 + women `2 W` must not be stripped as 2 Watts!)
        se1 = _rec("intersport_eg", "Adidas Supernova Ease Running Shoes For Men, Dark Blue/Silver/Grey", category="sports", sub_category="sports_shoes", brand="Adidas", price=6999)
        se2 = _rec("gosport_eg", "SUPERNOVA EASE 2 W RUNNING SHOES", category="sports", sub_category="sports_shoes", brand="Adidas", price=7599)
        self.assertFalse(_matched(se1, se2))


class TestGenuineIdenticalSkusStillMatch(unittest.TestCase):
    def test_identical_motherboard_matches(self):
        a = _rec("sigma", "Gigabyte B850M D3HP AM5 DDR5 mATX Motherboard", sub_category="motherboards", brand="Gigabyte", price=7600)
        b = _rec("alfrensia", "GIGABYTE B850M D3HP Motherboard", sub_category="motherboards", brand="Gigabyte", price=7950)
        self.assertTrue(_matched(a, b))

    def test_identical_psu_matches(self):
        a = _rec("alfrensia", "Cooler Master GX II Gold 850W Full Modular Power Supply", sub_category="psus", brand="Cooler Master", price=4900)
        b = _rec("sigma", "Cooler Master GX II Gold 850 Watt ATX 3.0 Power Supply", sub_category="psus", brand="Cooler Master", price=5350)
        self.assertTrue(_matched(a, b))

    def test_identical_ram_matches(self):
        a = _rec("alfrensia", "Klevv 8Gb DDR4 3200Mhz Udimm Desktop Memory", sub_category="memory", brand="Klevv", price=1450)
        b = _rec("sigma", "KLEVV DDR4 8GB 3200MHz UDIMM Desktop Memory", sub_category="memory", brand="Klevv", price=1550)
        self.assertTrue(_matched(a, b))

    def test_identical_monitor_and_100in_tv_match(self):
        m1 = _rec("alfrensia", "MSI MAG 274QPF E20 27 Inch WQHD 200Hz Gaming Monitor", sub_category="monitors", brand="MSI", price=9999)
        m2 = _rec("sigma", 'MSI MAG 274QPF E20 27" IPS 200Hz Monitor', sub_category="monitors", brand="MSI", price=10499)
        self.assertTrue(_matched(m1, m2))

        t1 = _rec("cairosales", "Samsung 100-Inch Class Neo QLED QN80H 4K Smart TV 100QN80H", category="home_appliances", sub_category="tvs", brand="Samsung", price=318249)
        t2 = _rec("ehab_center", 'Samsung 100" Neo QLED 4K Smart TV 100QN80H', category="home_appliances", sub_category="tvs", brand="Samsung", price=325000)
        self.assertTrue(_matched(t1, t2))

    def test_identical_grocery_and_appliance_rounding_match(self):
        g1 = _rec("seoudi", "Saluti Mild White Cheddar Cheese - 200 g", category="groceries", sub_category="dairy_cheese", brand="Saluti", price=141)
        g2 = _rec("spinneys", "Saluti - Mild White Cheddar Cheese - 200g", category="groceries", sub_category="dairy_cheese", brand="Saluti", price=160)
        self.assertTrue(_matched(g1, g2))

        # Exact same MPN with minor 65L vs 67L rounding across stores
        o1 = _rec("2b", "Purity Built-In Gas Oven, 60 cm, 67 Liter - INOX - OPT601GG", category="home_appliances", sub_category="ovens", brand="Purity", price=16989)
        o2 = _rec("btech", "Purity Built-in Oven with Grill 65 Liter, Stainless Steel - OPT601GG", category="home_appliances", sub_category="ovens", brand="Purity", price=19089)
        self.assertTrue(_matched(o1, o2))


if __name__ == "__main__":
    unittest.main()
