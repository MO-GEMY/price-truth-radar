"""Unit tests for the cross-store canonical matcher (`scrapers.matcher`).

Covers:
- POSITIVE matches: same model across stores with divergent taxonomies,
  formats, and languages (Arabic vs English groceries).
- NEGATIVE guards: different storage / RAM / screen size / HP / weight /
  pack size / scent / flavor, and accessory-vs-device, must NEVER merge.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from data_platform.ingestion.scrapers.base import RawProductSnapshot
from data_platform.ingestion.scrapers.groceries import (
    compute_grocery_type_key,
    parse_grocery_packaging,
)
from data_platform.ingestion.scrapers.matcher import (
    assign_canonical_keys,
    compute_candidate_key,
)

_SNAP_DATE = date(2026, 11, 22)


def snap(
    store: str,
    title: str,
    *,
    category: str = "electronics",
    sub_category: str = "electronics",
    brand: str | None = None,
    price: float = 1000.0,
    attrs: dict | None = None,
    ext_id: str = "x1",
) -> RawProductSnapshot:
    return RawProductSnapshot(
        store_name=store,
        external_id=ext_id,
        category=category,
        sub_category=sub_category,
        brand=brand or title.split()[0],
        product_title=title,
        product_url=f"https://example.com/{store}/{ext_id}",
        image_url=None,
        attributes_json=attrs or {},
        current_price=Decimal(str(price)),
        claimed_original_price=None,
        in_stock=True,
        snapshot_date=_SNAP_DATE,
        scraped_at=datetime(2026, 11, 22, 2, 30),
    )


def make_group(*records: RawProductSnapshot) -> bool:
    """Run the matcher and report whether ALL records share one canonical key."""
    assign_canonical_keys(list(records), max_price_ratio=100.0)
    keys = {r.canonical_product_key for r in records}
    return None not in keys and len(keys) == 1


class TestElectronicsMatches(unittest.TestCase):
    """Positive matches across divergent store taxonomies & title formats."""

    def test_gaming_vs_peripherals_taxonomy_collapse(self):
        """Logitech G502 HERO: `gaming` at 2B, `peripherals` at Sigma."""
        r1 = snap("2b", "Logitech G502 HERO High Performance Gaming Mouse-USB-EWR2 - 910-005471",
                  sub_category="gaming", brand="Logitech", price=1999)
        r2 = snap("sigma", "Logitech G502 HERO High Performance Wired Gaming Mouse",
                  sub_category="peripherals", brand="Logitech", price=2050)
        self.assertTrue(make_group(r1, r2))

    def test_printer_code_match_across_stores(self):
        """HP LaserJet M111W: different title word order + sub_category slugs."""
        r1 = snap("raneen", "HP LaserJet M111W Black White Laser Printer, Wireless Connectivity, 7Md68A - White",
                  sub_category="printers", brand="HP", price=4200)
        r2 = snap("rayashop", "HP M111W LaserJet Printer, White - 7MD68A",
                  sub_category="printer", brand="HP", price=4350)
        self.assertTrue(make_group(r1, r2))

    def test_smartphone_storage_ram_formats(self):
        """Samsung Galaxy A17: Amazon prose vs B.Tech comma format."""
        r1 = snap("amazon_eg", "Samsung Galaxy A17 LTE, Android Smartphone, 256GB Storage, 8GB RAM, Gray, 6x OS Upgrades, Large Display, 50MP",
                  sub_category="smartphones", brand="Samsung", price=9500)
        r2 = snap("btech", "Samsung Galaxy A17 , 256 GB , 8 GB , 4G , Dual-SIM - Gray",
                  sub_category="smartphones", brand="Samsung", price=9800)
        self.assertTrue(make_group(r1, r2))

    def test_laptop_cpu_gpu_variant_match(self):
        """Lenovo Legion 5 15IRX10 i7-13650HX: same chassis + CPU + GPU."""
        r1 = snap("compumarts", "Lenovo Legion 5 15IRX10 Gaming Laptop – Intel Core i7-13650HX, RTX 5050, 16GB, 1TB",
                  sub_category="laptops", brand="Lenovo", price=48000)
        r2 = snap("egyptlaptop", "Lenovo Legion 5 15IRX10 Intel Core i7-13650HX 1TB SSD 16GB Ram RTX 5050",
                  sub_category="laptops", brand="Lenovo", price=49000)
        self.assertTrue(make_group(r1, r2))

    def test_tv_same_model_same_size_match(self):
        """Toshiba 50C350RP: same size, same code, different stores."""
        r1 = snap("2b", "Toshiba TV 50 Inch Smart - 4K UHD LED With Built-In Receiver - 50C350RP",
                  category="home_appliances", sub_category="tvs", brand="Toshiba", price=15000)
        r2 = snap("cairosales", "Toshiba 50C350RP Smart TV 50 inch 4K UHD",
                  category="home_appliances", sub_category="tvs", brand="Toshiba", price=15400)
        self.assertTrue(make_group(r1, r2))

    def test_midea_ac_code_normalization(self):
        """Midea AC: dash/space formats + M0/MO letter-zero + HP guard align."""
        r1 = snap("noon", "Midea XTreme Pro 1.5HP, Cool Only M1SEFT-12CRN8F-Q8/M0SEFT-12CN8-X2Q8",
                  category="home_appliances", sub_category="air_conditioners", brand="Midea", price=19000)
        r2 = snap("raneen", "Midea M1SEFT-12CRN8F-Q8 R32 (MOSEFT-12CN8-X2Q8) Extreme Pro Split Air Conditioner 1.5 HP",
                  category="home_appliances", sub_category="air_conditioners", brand="Midea", price=19500)
        self.assertTrue(make_group(r1, r2))

    def test_aio_cooler_miscategorized_sub_category(self):
        """ID-COOLING AIO cooler: one store files it under `monitors`.

        Same variant (LCD) across divergent sub_categories must match; the
        sibling TD variant (digital-screen SKU) must stay separate.
        """
        r1 = snap("sigma", "ID-COOLING FX360 LCD Gen 7 Pro Pump ARGB Liquid CPU Cooler (AIO)",
                  sub_category="cooling", brand="ID-COOLING", price=5200)
        r2 = snap("compumarts", "ID-COOLING FX360 LCD White AIO Liquid CPU Cooler with Digital Screen",
                  sub_category="monitors", brand="ID-COOLING", price=5300)
        self.assertTrue(make_group(r1, r2))

    def test_aio_cooler_lcd_vs_td_variant_no_match(self):
        r1 = snap("sigma", "ID-COOLING FX360 LCD Gen 7 Pro Pump ARGB Liquid CPU Cooler (AIO)",
                  sub_category="cooling", brand="ID-COOLING", price=5200)
        r2 = snap("compumarts", "ID-COOLING FX360 TD Digital Screen Gen 7 Pro Pump ARGB AIO Liquid CPU Cooler",
                  sub_category="monitors", brand="ID-COOLING", price=5300)
        self.assertFalse(make_group(r1, r2))


class TestElectronicsNegativeGuards(unittest.TestCase):
    """Strict variant guards — different specs must NEVER share a key."""

    def test_tv_different_screen_size_no_match(self):
        r1 = snap("2b", "Toshiba TV 50 Inch Smart - 4K UHD LED With Built-In Receiver - 50C350RP",
                  category="home_appliances", sub_category="tvs", brand="Toshiba", price=15000)
        r2 = snap("2b", "Toshiba TV 55 Inch Smart - 4K UHD LED With Built-In Receiver - 55C350RP",
                  category="home_appliances", sub_category="tvs", brand="Toshiba", price=17000)
        self.assertFalse(make_group(r1, r2))

    def test_tv_embedded_size_digits_no_match(self):
        """LG NU830 family: 65 vs 75 inch — size embedded in the model code."""
        r1 = snap("cairosales", "LG 65 Inch Nano AI NU83 4K Smart TV Magic remote 65NU830B6LA",
                  category="home_appliances", sub_category="tvs", brand="LG", price=30000)
        r2 = snap("cairosales", "LG 75 Inch Nano AI NU83 4K Smart TV Magic remote 75NU830B6LA",
                  category="home_appliances", sub_category="tvs", brand="LG", price=40000)
        self.assertFalse(make_group(r1, r2))

    def test_laptop_different_cpu_no_match(self):
        r1 = snap("compumarts", "Lenovo Legion 5 15IRX10 Gaming Laptop – Intel Core i7-13650HX, RTX 5050, 16GB, 1TB",
                  sub_category="laptops", brand="Lenovo", price=48000)
        r2 = snap("egyptlaptop", "Lenovo Legion 5 15IRX10 Intel Core i9-14900HX 1TB SSD 32GB Ram RTX 5070",
                  sub_category="laptops", brand="Lenovo", price=62000)
        self.assertFalse(make_group(r1, r2))

    def test_phone_different_ram_no_match(self):
        """Vivo Y11D 6GB (2B) vs 4GB (Noon) — different variants stay apart."""
        r1 = snap("2b", "Vivo Y11D - 6GB RAM - 128GB - Gold",
                  sub_category="smartphones", brand="Vivo", price=7000)
        r2 = snap("noon", "vivo Y11d Dual SIM Sunrise Gold 4GB RAM 128GB 4G - Middle East Version",
                  sub_category="smartphones", brand="Vivo", price=6800)
        self.assertFalse(make_group(r1, r2))

    def test_phone_different_storage_no_match(self):
        r1 = snap("btech", "Samsung Galaxy S26 FE , 512 GB , 8 GB , 5G , Dual-SIM - Graphite",
                  sub_category="smartphones", brand="Samsung", price=30000)
        r2 = snap("btech", "Samsung Galaxy S26 FE , 256 GB , 8 GB , 5G , Dual-SIM - Graphite",
                  sub_category="smartphones", brand="Samsung", price=27000)
        self.assertFalse(make_group(r1, r2))

    def test_g502_hero_vs_x_plus_no_match(self):
        r1 = snap("sigma", "Logitech G502 HERO High Performance Wired Gaming Mouse",
                  sub_category="peripherals", brand="Logitech", price=1999)
        r2 = snap("sigma", "LOGITECH G502 X Plus Wireless RGB Gaming Mouse White",
                  sub_category="peripherals", brand="Logitech", price=2600)
        self.assertFalse(make_group(r1, r2))

    def test_ac_different_hp_no_match(self):
        r1 = snap("2b", "Carrier XCool Air Conditioner 1.5 HP - Split Cooling & Heating - KHEFT12N",
                  category="home_appliances", sub_category="air_conditioners", brand="Carrier", price=18000)
        r2 = snap("raneen", "Carrier XCool Air Conditioner 2.25 HP Split - KHEFT24N",
                  category="home_appliances", sub_category="air_conditioners", brand="Carrier", price=26000)
        self.assertFalse(make_group(r1, r2))

    def test_washer_different_kg_no_match(self):
        r1 = snap("2b", "Zanussi PerlaMax Inverter Front Load Washing Machine , 8 kg , Dark Grey - ZWF8240DS5",
                  category="home_appliances", sub_category="washing_machines", brand="Zanussi", price=22000)
        r2 = snap("2b", "Zanussi PerlaMax Inverter Front Load Washing Machine , 6 kg , White - ZWF6240DS5",
                  category="home_appliances", sub_category="washing_machines", brand="Zanussi", price=19000)
        self.assertFalse(make_group(r1, r2))

    def test_accessory_vs_device_no_match(self):
        """An iPhone case must never merge with the iPhone itself."""
        r1 = snap("tradeline", "Laut FLEXI PROTECT case for iPhone 18 Pro - Black",
                  sub_category="accessories", brand="Laut", price=700)
        r2 = snap("noon", "Apple iPhone 18 Pro 256GB Natural Titanium",
                  sub_category="smartphones", brand="Apple", price=65000)
        self.assertFalse(make_group(r1, r2))


class TestGroceriesMatches(unittest.TestCase):
    """Bilingual AR <-> EN matches and strict size/flavor guards."""

    def test_arabic_english_ghee_type_pass(self):
        """Fern ghee: Arabic title (noon/amazon) vs English (Spinneys-style)."""
        r1 = snap("amazon_eg", "سمن بقرى طبيعى نقى 1400 جرام فرن",
                  category="groceries", sub_category="oils_ghee", brand="Fern", price=180)
        r2 = snap("spinneys", "Fern Pure Ghee - 1400g",
                  category="groceries", sub_category="oils_ghee", brand="Fern", price=185)
        self.assertTrue(make_group(r1, r2))

    def test_detergent_gel_size_match(self):
        r1 = snap("spinneys", "Persil Gel Detergent - 2.65L",
                  category="groceries", sub_category="detergents", brand="Persil", price=410)
        r2 = snap("noon", "Persil Washing Gel Liquid Detergent 2.65 L",
                  category="groceries", sub_category="detergents", brand="Persil", price=425)
        self.assertTrue(make_group(r1, r2))

    def test_juhayna_juice_arabic_english(self):
        r1 = snap("hyperone", "جهينة عصير مانجو - 1 لتر",
                  category="groceries", sub_category="beverages", brand="Juhayna", price=95)
        r2 = snap("noon", "Juhayna Mango Juice - 1L",
                  category="groceries", sub_category="beverages", brand="Juhayna", price=96)
        self.assertTrue(make_group(r1, r2))

    def test_baraka_water_size_match(self):
        r1 = snap("spinneys", "Baraka - Mineral Water - 1.5l",
                  category="groceries", sub_category="beverages", brand="Baraka", price=15)
        r2 = snap("metro_market", "Baraka Mineral Water 1.5 L",
                  category="groceries", sub_category="beverages", brand="Baraka", price=16)
        self.assertTrue(make_group(r1, r2))

    def test_pack_size_match(self):
        r1 = snap("noon", "Lametna Penne Rigate Pasta 400grams",
                  category="groceries", sub_category="rice_pasta", brand="Lametna", price=32)
        r2 = snap("amazon_eg", "Lametna Penne Rigate 400 g",
                  category="groceries", sub_category="rice_pasta", brand="Lametna", price=33)
        self.assertTrue(make_group(r1, r2))


class TestGroceriesNegativeGuards(unittest.TestCase):
    """Different sizes / flavors / scents must NEVER merge."""

    def test_pepsi_different_sizes_no_match(self):
        r1 = snap("hyperone", "Pepsi Soda Drink - 1.47L",
                  category="groceries", sub_category="beverages", brand="Pepsi", price=25)
        r2 = snap("hyperone", "Pepsi Soda Drink - 390ml",
                  category="groceries", sub_category="beverages", brand="Pepsi", price=12)
        self.assertFalse(make_group(r1, r2))

    def test_juice_different_flavor_same_size_no_match(self):
        r1 = snap("seoudi", "Almarai Guava Juice - 235 ml",
                  category="groceries", sub_category="beverages", brand="Almarai", price=28)
        r2 = snap("seoudi", "Almarai Mango Juice - 235 ml",
                  category="groceries", sub_category="beverages", brand="Almarai", price=28)
        self.assertFalse(make_group(r1, r2))

    def test_detergent_different_scent_no_match(self):
        r1 = snap("spinneys", "Persil Gel Detergent Lavender - 2.65L",
                  category="groceries", sub_category="detergents", brand="Persil", price=410)
        r2 = snap("spinneys", "Persil Gel Detergent Regular - 2.65L",
                  category="groceries", sub_category="detergents", brand="Persil", price=400)
        self.assertFalse(make_group(r1, r2))

    def test_ghee_vs_oil_same_brand_size_no_match(self):
        """Same brand, same size, different product type (ghee vs corn oil)."""
        r1 = snap("noon", "Fern Corn Oil 800ml",
                  category="groceries", sub_category="oils_ghee", brand="Fern", price=90)
        r2 = snap("spinneys", "Fern Pure Ghee - 800g",
                  category="groceries", sub_category="oils_ghee", brand="Fern", price=95)
        self.assertFalse(make_group(r1, r2))

    def test_rice_different_weight_no_match(self):
        r1 = snap("spinneys", "Tilda Basmati Rice- 1 Kg",
                  category="groceries", sub_category="rice_pasta", brand="Tilda", price=280)
        r2 = snap("noon", "Tilda Basmati Rice 5 Kg",
                  category="groceries", sub_category="rice_pasta", brand="Tilda", price=1200)
        self.assertFalse(make_group(r1, r2))

    def test_weight_vs_volume_never_cross_match(self):
        """500g of powder and 500ml of liquid are different products."""
        r1 = snap("spinneys", "Persil Washing Powder Low Suds Lavender - 500 g",
                  category="groceries", sub_category="detergents", brand="Persil", price=120)
        r2 = snap("hyperone", "Persil Gel Detergent - 500 ml",
                  category="groceries", sub_category="detergents", brand="Persil", price=120)
        self.assertFalse(make_group(r1, r2))

    def test_pasta_shape_variants_no_match(self):
        """El Maleka 400g: Small Rings vs Penne are different SKUs."""
        r1 = snap("noon", "El Maleka Pasta Small Rings 400grams",
                  category="groceries", sub_category="rice_pasta", brand="El Maleka", price=17)
        r2 = snap("amazon_eg", "El Maleka Pasta Penne 400G",
                  category="groceries", sub_category="rice_pasta", brand="El Maleka", price=18)
        self.assertFalse(make_group(r1, r2))

    def test_rice_variant_beyti_vs_vermicelli_no_match(self):
        """Al Doha 320g: Beyti edition vs Vermicelli edition are different SKUs."""
        r1 = snap("amazon_eg", "Al Doha Easy Rice Beyti - 320 g",
                  category="groceries", sub_category="rice_pasta", brand="Al Doha", price=22)
        r2 = snap("seoudi", "Al Doha Rice with Vermicelli, Easy Rice Edition - 320 g",
                  category="groceries", sub_category="rice_pasta", brand="Al Doha", price=29)
        self.assertFalse(make_group(r1, r2))

    def test_tuna_cuts_shredded_vs_chunks_no_match(self):
        r1 = snap("noon", "Sunshine Tuna shredded Xpress Easy Open 150grams",
                  category="groceries", sub_category="canned_sauces", brand="Sunshine", price=39)
        r2 = snap("hyperone", "Sunshine Tuna Chunk Xpress Easy Open 150grams",
                  category="groceries", sub_category="canned_sauces", brand="Sunshine", price=40)
        self.assertFalse(make_group(r1, r2))

    def test_xpress_spelling_variant_matches(self):
        """'Xpress' and 'Express' are the same product line."""
        r1 = snap("noon", "Sunshine Tuna shredded Xpress Easy Open 150grams",
                  category="groceries", sub_category="canned_sauces", brand="Sunshine", price=39)
        r2 = snap("hyperone", "Sunshine Express Shredded Tuna - 150g",
                  category="groceries", sub_category="canned_sauces", brand="Sunshine", price=40)
        self.assertTrue(make_group(r1, r2))

    def test_el_article_brands_stay_separate(self):
        """'El Masa' vs 'El Matbakh Elmasry' — the Arabic article must not
        collapse distinct brands into one."""
        r1 = snap("hyperone", "El Masa Big Rings Pasta - 400g",
                  category="groceries", sub_category="rice_pasta", brand="El Masa", price=14)
        r2 = snap("amazon_eg", "El Matbakh Elmasry Vermicelli Pasta, 400 gm",
                  category="groceries", sub_category="rice_pasta", brand="El Matbakh Elmasry", price=15)
        self.assertFalse(make_group(r1, r2))

    def test_samsung_different_tv_models_same_size_no_match(self):
        """Samsung 55-inch Mini LED M70H vs The Frame LS03F — same size,
        different TVs (regression for the `samsung_tv_inch_55in` FP)."""
        r1 = snap("cairosales", "SAMSUNG 55-inch Class Mini LED UHD 4K Smart TV 55M70H",
                  category="home_appliances", sub_category="tvs", brand="Samsung", price=22999)
        r2 = snap("amazon_eg", "Samsung 55-inch Mini LED 4K Smart TV, Advanced AI Picture Engine, HDR10+",
                  category="home_appliances", sub_category="tvs", brand="Samsung", price=23199)
        self.assertFalse(make_group(r1, r2))

    def test_dolphin_chili_vs_plain_tuna_no_match(self):
        r1 = snap("hyperone", "Dolphin Shredded Tuna - 200g",
                  category="groceries", sub_category="canned_sauces", brand="Dolphin", price=46)
        r2 = snap("hyperone", "Dolphin Chili Shredded Tuna - 200g",
                  category="groceries", sub_category="canned_sauces", brand="Dolphin", price=47)
        self.assertFalse(make_group(r1, r2))


class TestUnitPriceFallbackData(unittest.TestCase):
    """Packaging parser feeds `net_weight_g` / `net_volume_ml` used by matching."""

    def test_arabic_multipack_parse(self):
        parsed = parse_grocery_packaging("6 × 1 لتر مياه")
        self.assertEqual(parsed.get("pack_count"), 6)
        self.assertEqual(parsed.get("net_volume_ml"), 6000)
        self.assertEqual(parsed.get("pack_size"), "6x1L")

    def test_arabic_weight_parse(self):
        parsed = parse_grocery_packaging("سمن بقرى طبيعى نقى 1400 جرام فرن")
        self.assertEqual(parsed.get("net_weight_g"), 1400)

    def test_type_key_requires_brand_and_size(self):
        r1 = snap("hyperone", "Red Cheddar Cheese", category="groceries",
                  sub_category="dairy_cheese", brand="Unknown", price=100)
        self.assertIsNone(compute_grocery_type_key(r1))


if __name__ == "__main__":
    unittest.main()
