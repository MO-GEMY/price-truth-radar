"""Unit tests for Phase A (`units.py`) and Phase B (`matcher_verticals.py` & upgraded `matcher.py`)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from data_platform.ingestion.scrapers.base import RawProductSnapshot
from data_platform.ingestion.scrapers.groceries import parse_grocery_packaging
from data_platform.ingestion.scrapers.matcher import assign_canonical_keys
from data_platform.ingestion.scrapers.units import parse_unit_spec, units_conflict

_SNAP_DATE = date(2026, 11, 23)


def _snap(
    store: str,
    title: str,
    *,
    category: str = "health",
    sub_category: str = "supplements",
    brand: str = "Unknown",
    price: float = 500.0,
    attrs: dict | None = None,
    ext_id: str = "1",
) -> RawProductSnapshot:
    return RawProductSnapshot(
        store_name=store,
        external_id=ext_id,
        category=category,  # type: ignore[arg-type]
        sub_category=sub_category,
        brand=brand,
        product_title=title,
        product_url=f"https://example.com/{store}/{ext_id}",
        image_url=None,
        attributes_json=attrs or {},
        current_price=Decimal(f"{price:.2f}"),
        claimed_original_price=None,
        in_stock=True,
        snapshot_date=_SNAP_DATE,
        scraped_at=datetime(2026, 11, 23, 12, 0),
    )


class TestBilingualUnitsParser(unittest.TestCase):
    def test_arabic_fractional_weights_and_volumes(self):
        self.assertEqual(parse_unit_spec("بن أبو عوف ربع كيلو سادة").weight_g, 250)
        self.assertEqual(parse_unit_spec("بن شاهين نص كيلو محوج").weight_g, 500)
        self.assertEqual(parse_unit_spec("شاي العروسة ثمن كيلو").weight_g, 125)
        self.assertEqual(parse_unit_spec("سكر الضحى كيلو ونص").weight_g, 1500)
        self.assertEqual(parse_unit_spec("لبن جهينة نص لتر").volume_ml, 500)
        self.assertEqual(parse_unit_spec("عصير ربع لتر").volume_ml, 250)
        self.assertEqual(parse_unit_spec("كرتونة عصير دستة 200 مل").pack_count, 12)
        # Groceries packaging integration
        pkg = parse_grocery_packaging("بن أبو عوف ربع كيلو سادة")
        self.assertEqual(pkg.get("net_weight_g"), 250)

    def test_url_encoded_arabic_variant_label_wins_over_multi_size_title(self):
        spec = parse_unit_spec(
            "هيبتا بانثينول ريتش لوشن للجسم 100 مل / 250 مل",
            variant_label="100%d9%85%d9%84",
        )
        self.assertFalse(spec.has_ambiguous_multi_size)
        self.assertEqual(spec.volume_ml, 100)

    def test_mg_dosage_not_confused_with_grams(self):
        spec = parse_unit_spec("NOW Foods Magnesium Citrate 400mg 120 VegCaps")
        self.assertIsNone(spec.weight_g)
        self.assertEqual(spec.unit_count, 120)
        self.assertEqual(spec.unit_kind, "caps")
        self.assertEqual(spec.dosage_tag, "400mg")

    def test_units_conflict_guard(self):
        a = parse_unit_spec("Abu Auf Coffee 250g")
        b = parse_unit_spec("Abu Auf Coffee 1kg")
        self.assertTrue(units_conflict(a, b))

        c = parse_unit_spec("NOW Vitamin D3 1000IU 60 Softgels")
        d = parse_unit_spec("NOW Vitamin D3 5000IU 60 Softgels")
        self.assertTrue(units_conflict(c, d))

        e = parse_unit_spec("Abu Auf Coffee ربع كيلو")
        self.assertFalse(units_conflict(a, e))


class TestHealthBeautyAndFootwearMatchers(unittest.TestCase):
    def test_health_bilingual_match_and_size_isolation(self):
        r1 = _snap("beseha", "سيروم الريتينول 30 مل – سيرافي", category="health", brand="سيرافي", price=826)
        r2 = _snap("source_beauty", "CeraVe Retinol Serum 30ml", category="beauty", brand="CeraVe", price=890)
        r_big = _snap("bloom_pharmacy", "CeraVe Retinol Serum 50ml", category="health", brand="CeraVe", price=1250)
        summary = assign_canonical_keys([r1, r2, r_big])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(r1.canonical_product_key, r2.canonical_product_key)
        self.assertIsNone(r_big.canonical_product_key)

    def test_health_supplement_lb_vs_g_match_and_collapsed_variant_block(self):
        r1 = _snap("mfsupps_eg", "Optimum Nutrition Gold Standard 100% Whey Protein 2 lbs", category="health", brand="Optimum Nutrition", price=2500)
        r2 = _snap("max_muscle_eg", "Optimum Nutrition 100% Whey Gold Standard 907g", category="health", brand="Optimum Nutrition", price=2650)
        # Collapsed multi-price WooCommerce parent (1lb..5lb) without variant_label -> MUST NOT match
        r_collapsed = _snap(
            "ifit_eg",
            "Optimum Nutrition Gold Standard 100% Whey Protein 2 lbs",
            category="health",
            brand="Optimum Nutrition",
            price=2450,
            attrs={"variant_count": 4, "variant_min_price": 1200, "variant_max_price": 6500},
        )
        summary = assign_canonical_keys([r1, r2, r_collapsed])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(r1.canonical_product_key, r2.canonical_product_key)
        self.assertIsNone(r_collapsed.canonical_product_key)

    def test_perfume_edp_vs_edt_and_volume_strict_isolation(self):
        p1 = _snap("source_beauty", "Giorgio Armani Acqua Di Gio Pour Homme EDP 100ml", category="beauty", brand="Giorgio Armani", price=6200)
        p2 = _snap("bashrety", "Giorgio Armani Acqua Di Gio Men Eau De Parfum 100 ml", category="beauty", brand="Giorgio Armani", price=6500)
        p_edt = _snap("mood_fragrances", "Giorgio Armani Acqua Di Gio Pour Homme EDT 100ml", category="beauty", brand="Giorgio Armani", price=5400)
        p_50 = _snap("diwan_fragrances", "Giorgio Armani Acqua Di Gio Pour Homme EDP 50ml", category="beauty", brand="Giorgio Armani", price=4200)
        summary = assign_canonical_keys([p1, p2, p_edt, p_50])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(p1.canonical_product_key, p2.canonical_product_key)
        self.assertIsNone(p_edt.canonical_product_key)
        self.assertIsNone(p_50.canonical_product_key)

    def test_footwear_parent_model_match_and_kids_or_version_isolation(self):
        s1 = _snap("wayup_sports", "Nike Downshifter 14 Road Running Shoes Men - Black — 42", category="sports", sub_category="sports_shoes", brand="Nike", price=4724)
        s2 = _snap("intersport_eg", "Nike Downshifter 14 Running Shoes For Men, White EU 44", category="sports", sub_category="sports_shoes", brand="Nike", price=4899)
        s_v13 = _snap("gosport_eg", "Nike Downshifter 13 Running Shoes For Men Black 42", category="sports", sub_category="sports_shoes", brand="Nike", price=4200)
        s_kids = _snap("puma_eg", "Nike Downshifter 14 Running Shoes Kids Boys 36", category="sports", sub_category="sports_shoes", brand="Nike", price=2900)
        s_tee = _snap("activ", "Nike Downshifter 14 Running T-Shirt Men", category="fashion", sub_category="apparel", brand="Nike", price=1200)
        summary = assign_canonical_keys([s1, s2, s_v13, s_kids, s_tee])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(s1.canonical_product_key, s2.canonical_product_key)
        self.assertIsNone(s_v13.canonical_product_key)
        self.assertIsNone(s_kids.canonical_product_key)
        self.assertIsNone(s_tee.canonical_product_key)

    def test_sokany_glued_arabic_model_code_match(self):
        a1 = _snap("sokany_eg", "غلايه سوكاني 2200وات 1.7لتر موديلSK-09006", category="home_appliances", sub_category="kitchen_appliances", brand="غلايه", price=750)
        a2 = _snap("raneen", "Sokany Electric Kettle 1.7L 2200W SK-09006", category="home_appliances", sub_category="kitchen_appliances", brand="Sokany", price=820)
        summary = assign_canonical_keys([a1, a2])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(a1.canonical_product_key, a2.canonical_product_key)

    def test_grocery_arabic_quarter_kilo_matches_250g(self):
        g1 = _snap("seoudi", "بن أبو عوف سادة وسط ربع كيلو", category="groceries", sub_category="tea_coffee", brand="Abu Auf", price=145)
        g2 = _snap("spinneys", "Abu Auf Plain Medium Turkish Coffee 250g", category="groceries", sub_category="tea_coffee", brand="Abu Auf", price=155)
        g_kg = _snap("hyperone", "Abu Auf Plain Medium Turkish Coffee 1kg", category="groceries", sub_category="tea_coffee", brand="Abu Auf", price=580)
        summary = assign_canonical_keys([g1, g2, g_kg])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(g1.canonical_product_key, g2.canonical_product_key)
        self.assertIsNone(g_kg.canonical_product_key)


    def test_motherboard_chipset_submodel_isolation(self):
        m1 = _snap("sigma", "GIGABYTE A520M K V2 Socket AM4 Motherboard", category="electronics", sub_category="motherboards", brand="Gigabyte", price=3300)
        m2 = _snap("alfrensia", "Gigabyte A520M K V2 Motherboard", category="electronics", sub_category="motherboards", brand="Gigabyte", price=3299)
        m_other = _snap("compumarts", "GIGABYTE A520M S2H (Rev. 1.x) Motherboard AMD Socket AM4", category="electronics", sub_category="motherboards", brand="Gigabyte", price=3250)
        summary = assign_canonical_keys([m1, m2, m_other])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(m1.canonical_product_key, m2.canonical_product_key)
        self.assertIsNone(m_other.canonical_product_key)

    def test_hdr10_spec_not_treated_as_model_code(self):
        mon = _snap("sigma", 'SAMSUNG Odyssey G4 LS27BG402EMXUE 27" FHD IPS Monitor - 240Hz, 1ms, HDR10', category="electronics", sub_category="monitors", brand="Samsung", price=9999)
        tv = _snap("noon", "Samsung 50-inch Crystal UHD 4K Smart TV, Vision AI, HDR10+, Crystal Processor 4K", category="electronics", sub_category="tvs", brand="Samsung", price=18199)
        summary = assign_canonical_keys([mon, tv])
        self.assertEqual(summary.matched_groups, 0)

    def test_beauty_scents_stay_separate(self):
        b1 = _snap("bloom_pharmacy", "Bubblzz Coconut Shower Gel - 250ml", category="beauty", sub_category="body_care", brand="Bubblzz", price=102)
        b2 = _snap("source_beauty", "Vanilla Shower Gel - 250ml", category="beauty", sub_category="body_care", brand="Bubblzz", price=102)
        summary = assign_canonical_keys([b1, b2])
        self.assertEqual(summary.matched_groups, 0)

    def test_footwear_gender_from_variant_label_blocks_men_vs_women(self):
        f1 = _snap("gosport_eg", "NIKE COURT VISION LO BE", category="sports", sub_category="sports_shoes", brand="Nike", price=4249, attrs={"variant_label": "42.5 / Black / Men"})
        f2 = _snap("intersport_eg", "Nike Court Vision Lo Be Lifestyle Shoes For Women, White", category="sports", sub_category="sports_shoes", brand="Nike", price=8099)
        summary = assign_canonical_keys([f1, f2])
        self.assertEqual(summary.matched_groups, 0)


if __name__ == "__main__":
    unittest.main()
