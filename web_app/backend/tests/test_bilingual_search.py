"""Comprehensive unit tests for bilingual semantic/phonetic search, accessory demotion,
similar-product constraints, and overview cross-store fallback count.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.bilingual_search import (  # noqa: E402
    CatalogPhoneticIndex,
    arabic_phonetic_skeletons,
    canonicalize_bilingual_text,
    latin_phonetic_skeleton,
    reset_catalog_phonetic_index,
    split_glued_units,
)
from app.cache import api_cache, product_detail_cache, search_cache  # noqa: E402
from app.catalog_search import build_catalog_query, exact_catalog_sql  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import ProductVerdictItem  # noqa: E402
from app.similar_alternatives import find_similar_alternatives  # noqa: E402


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, Any]:
        return self._rows[0]


class _FakeDB:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(stmt)
        p = params or {}
        self.calls.append((sql, p))
        return self.handler(sql, p)


class TestBilingualSearchAndPhoneticResolver(unittest.TestCase):
    def setUp(self) -> None:
        api_cache.clear()
        search_cache.clear()
        product_detail_cache.clear()
        reset_catalog_phonetic_index()
        app.dependency_overrides.clear()

        self.phonetic = CatalogPhoneticIndex()
        self.phonetic.build_from_vocab(
            [
                ("CeraVe", 450, True),
                ("Sokany", 600, True),
                ("Baseus", 380, True),
                ("La Roche-Posay", 520, True),
                ("Zanussi", 290, True),
                ("Redragon", 710, True),
                ("Tefal", 440, True),
                ("Skechers", 890, True),
                ("Bioderma", 310, True),
                ("Anker", 410, True),
                ("DeLonghi", 180, True),
                ("foaming", 220, False),
                ("cleanser", 900, False),
            ]
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_arabic_normalization_and_glued_unit_splitting(self) -> None:
        self.assertEqual(split_glued_units("آيفون ٢٥٦جيجا"), "ايفون 256 gb")
        self.assertEqual(split_glued_units("تكييف ١٫٥حصان"), "تكييف 1.5 hp")
        self.assertEqual(split_glued_units("شاشة 55بوصة"), "شاشه 55 inch")
        self.assertEqual(split_glued_units("غسول 200مل"), "غسول 200 ml")
        self.assertEqual(split_glued_units("غسالة 8كيلو"), "غساله 8 kg")

    def test_automatic_phonetic_skeleton_resolution_for_long_tail_brands(self) -> None:
        expected_pairs = [
            ("سيرافي", "cerave"),
            ("سوكاني", "sokany"),
            ("باسيوس", "baseus"),
            ("لاروش", "la roche"),
            ("زانوسي", "zanussi"),
            ("ريدراجون", "redragon"),
            ("تيفال", "tefal"),
            ("سكيتشرز", "skechers"),
            ("بيوديرما", "bioderma"),
            ("انكر", "anker"),
        ]
        for ar_word, expected_latin in expected_pairs:
            hits = self.phonetic.resolve_arabic_token(ar_word, max_results=3)
            self.assertIn(
                expected_latin,
                hits,
                f"Expected {ar_word!r} (skel={arabic_phonetic_skeletons(ar_word)}) -> {expected_latin!r} "
                f"(skel={latin_phonetic_skeleton(expected_latin)}), got {hits}",
            )

    def test_key_arabic_ecommerce_queries_expand_accurately(self) -> None:
        # 1. "ايفون 15 برو ماكس"
        q_iphone = build_catalog_query("ايفون 15 برو ماكس", phonetic_index=self.phonetic)
        patterns = " ".join(t.pattern for t in q_iphone.terms)
        self.assertIn("iphone", patterns)
        self.assertIn("pro", patterns)
        self.assertIn("max", patterns)
        self.assertTrue(any(t.is_anchor and "15" in t.pattern for t in q_iphone.terms))
        self.assertTrue(q_iphone.demote_accessories)

        # 2. "غسول سيرافي" (semantic cleanser + automatic phonetic cerave!)
        q_cerave = build_catalog_query("غسول سيرافي", phonetic_index=self.phonetic)
        p_cerave = " ".join(t.pattern for t in q_cerave.terms)
        self.assertIn("cleanser", p_cerave)
        self.assertIn("cerave", p_cerave)
        self.assertTrue(q_cerave.demote_accessories)

        # 3. "غسالة زانوسي"
        q_zanussi = build_catalog_query("غسالة زانوسي", phonetic_index=self.phonetic)
        p_zanussi = " ".join(t.pattern for t in q_zanussi.terms)
        self.assertIn("washing", p_zanussi)
        self.assertIn("zanussi", p_zanussi)
        self.assertTrue(q_zanussi.demote_accessories)

        # 4. "تلاجة شارب"
        q_sharp = build_catalog_query("تلاجة شارب", phonetic_index=self.phonetic)
        p_sharp = " ".join(t.pattern for t in q_sharp.terms)
        self.assertIn("refrigerator", p_sharp)
        self.assertIn("sharp", p_sharp)
        self.assertTrue(q_sharp.demote_accessories)

        # 5. "سماعة ابل"
        q_apple = build_catalog_query("سماعة ابل", phonetic_index=self.phonetic)
        p_apple = " ".join(t.pattern for t in q_apple.terms)
        self.assertIn("airpods", p_apple)
        self.assertIn("apple", p_apple)
        self.assertTrue(q_apple.demote_accessories)

    def test_accessory_demotion_enabled_for_devices_and_disabled_for_accessory_queries(self) -> None:
        dev_q = build_catalog_query("ايفون 15 برو ماكس", phonetic_index=self.phonetic)
        sql_dev, params_dev = exact_catalog_sql(dev_q, 20)
        self.assertTrue(dev_q.demote_accessories)
        self.assertTrue(params_dev["demote_parts"])
        self.assertIn("part_order", sql_dev)
        self.assertIn("anchor_order", sql_dev)

        for acc_query in ("جراب ايفون 15", "كفر ايفون", "اسكرينة ايفون 15", "شاحن ابل", "iphone 15 case", "watch strap"):
            acc_q = build_catalog_query(acc_query, phonetic_index=self.phonetic)
            _, params_acc = exact_catalog_sql(acc_q, 20)
            self.assertFalse(acc_q.demote_accessories, f"Accessory demotion must be OFF for {acc_query!r}")
            self.assertFalse(params_acc["demote_parts"])

    def test_canonicalize_bilingual_text_bridges_ar_and_en(self) -> None:
        canon = canonicalize_bilingual_text("غسول سيرافي 200مل للبشرة", phonetic_index=self.phonetic)
        self.assertIn("cleanser", canon)
        self.assertIn("cerave", canon)
        self.assertIn("200", canon)
        self.assertIn("ml", canon)

    def test_similar_products_strict_subcategory_accessory_price_and_distinct_stores(self) -> None:
        now = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
        target = ProductVerdictItem(
            product_sk="sk_target_phone",
            canonical_product_key="apple_iphone_15_pro_256gb",
            store_name="tradeline",
            category="electronics",
            sub_category="smartphones",
            brand="Apple",
            product_title="Apple iPhone 15 Pro 256GB Natural Titanium",
            product_url="https://tradelinestores.com/iphone-15-pro",
            image_url="https://cdn.example.com/15pro.jpg",
            attributes_json={},
            current_price=60000.0,
            claimed_original_price=65000.0,
            rolling_60d_median=61000.0,
            min_historical_price=59000.0,
            max_historical_price=65000.0,
            claimed_discount_pct=7.7,
            real_discount_pct=1.6,
            discount_verdict="NORMAL_PRICE",
            scarcity_flag=False,
            in_stock=True,
            last_updated_at=now,
        )

        candidate_rows = [
            # Valid alternative 1 (same sub_category, distinct store, within ±30%)
            {
                "product_sk": "sk_s24u",
                "product_title": "Samsung Galaxy S24 Ultra 256GB Smartphone",
                "store_name": "btech",
                "brand": "Samsung",
                "category": "electronics",
                "sub_category": "smartphones",
                "current_price": 56000.0,
                "discount_verdict": "GENUINE_DEAL",
                "in_stock": True,
                "image_url": "https://cdn.example.com/s24u.jpg",
                "product_url": "https://btech.com/s24u",
                "parent_product_key": "btech::s24u",
                "canonical_product_key": "samsung_s24_ultra_256gb",
            },
            # Valid alternative 2 (Arabic smartphone title, bilingual similarity!)
            {
                "product_sk": "sk_ip15_ar",
                "product_title": "ابل ايفون 15 بلس 256 جيجا موبايل",
                "store_name": "noon",
                "brand": "Apple",
                "category": "electronics",
                "sub_category": "smartphones",
                "current_price": 52000.0,
                "discount_verdict": "NORMAL_PRICE",
                "in_stock": True,
                "image_url": "https://cdn.example.com/15plus.jpg",
                "product_url": "https://noon.com/15plus",
                "parent_product_key": "noon::15plus",
                "canonical_product_key": "apple_iphone_15_plus_256gb",
            },
            # MUST BE EXCLUDED: accessory case (even if same category/sub_category)
            {
                "product_sk": "sk_case",
                "product_title": "Apple Silicone Case for iPhone 15 Pro",
                "store_name": "amazon_eg",
                "brand": "Apple",
                "category": "electronics",
                "sub_category": "smartphones",
                "current_price": 50000.0,
                "discount_verdict": "NORMAL_PRICE",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://amazon.eg/case",
                "parent_product_key": "amazon_eg::case",
                "canonical_product_key": None,
            },
            # MUST BE EXCLUDED: different sub_category (laptops instead of smartphones)
            {
                "product_sk": "sk_macbook",
                "product_title": "Apple MacBook Air M2 256GB",
                "store_name": "2b",
                "brand": "Apple",
                "category": "electronics",
                "sub_category": "laptops",
                "current_price": 58000.0,
                "discount_verdict": "NORMAL_PRICE",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://2b.com.eg/mba",
                "parent_product_key": "2b::mba",
                "canonical_product_key": None,
            },
            # MUST BE EXCLUDED: same canonical_product_key cluster (exact match, not similar!)
            {
                "product_sk": "sk_exact_cluster",
                "product_title": "Apple iPhone 15 Pro 256GB Titanium",
                "store_name": "dream2000",
                "brand": "Apple",
                "category": "electronics",
                "sub_category": "smartphones",
                "current_price": 59500.0,
                "discount_verdict": "NORMAL_PRICE",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://dream2000.com/15pro",
                "parent_product_key": "dream2000::15pro",
                "canonical_product_key": "apple_iphone_15_pro_256gb",
            },
            # MUST BE EXCLUDED: outside ±30% price range (> 78,000 EGP)
            {
                "product_sk": "sk_too_expensive",
                "product_title": "Apple iPhone 16 Pro Max 1TB Smartphone",
                "store_name": "rayashop",
                "brand": "Apple",
                "category": "electronics",
                "sub_category": "smartphones",
                "current_price": 95000.0,
                "discount_verdict": "NORMAL_PRICE",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://rayashop.com/16pm",
                "parent_product_key": "rayashop::16pm",
                "canonical_product_key": None,
            },
        ]

        fake_db = _FakeDB(lambda _sql, _params: _FakeResult(rows=candidate_rows))
        results = find_similar_alternatives(fake_db, target, max_results=6)
        sks = [r.product_sk for r in results]
        self.assertEqual(set(sks), {"sk_s24u", "sk_ip15_ar"})
        # SQL strictly filters by sub_category
        self.assertIn("LOWER(sub_category) = :sub_cat", fake_db.calls[0][0])

    def test_product_detail_separates_exact_alternatives_sorted_instock_first_and_similar_products(self) -> None:
        now = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
        prod_row = {
            "product_sk": "sk_main",
            "canonical_product_key": "canon_main",
            "store_name": "btech",
            "category": "electronics",
            "sub_category": "smartphones",
            "brand": "Apple",
            "product_title": "Apple iPhone 15 Pro 256GB",
            "product_url": "https://btech.com/15pro",
            "image_url": "https://cdn.example.com/15pro.jpg",
            "attributes_json": {},
            "current_price": 60000.0,
            "claimed_original_price": None,
            "rolling_60d_median": 60000.0,
            "min_historical_price": 60000.0,
            "max_historical_price": 60000.0,
            "claimed_discount_pct": 0.0,
            "real_discount_pct": 0.0,
            "discount_verdict": "NORMAL_PRICE",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
            "parent_product_key": "btech::15pro",
            "variant_label": None,
            "variant_count": 1,
            "has_multiple_variants": False,
            "min_variant_price": 60000.0,
            "max_variant_price": 60000.0,
        }

        def handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "FROM gold.fct_price_history" in sql:
                return _FakeResult(rows=[])
            if "FROM gold.mart_product_verdicts" in sql and "WHERE product_sk = :product_sk" in sql:
                return _FakeResult(rows=[prod_row])
            if "FROM gold.mart_cross_store_matches" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "listings_json": [
                                # Out of stock cheaper offer -> must sort AFTER in-stock offers
                                {
                                    "product_sk": "sk_oos",
                                    "store_name": "dream2000",
                                    "price": 55000.0,
                                    "in_stock": False,
                                    "product_url": "https://dream2000.com/15pro",
                                    "discount_verdict": "NORMAL_PRICE",
                                },
                                # In-stock higher
                                {
                                    "product_sk": "sk_noon",
                                    "store_name": "noon",
                                    "price": 59500.0,
                                    "in_stock": True,
                                    "product_url": "https://noon.com/15pro",
                                    "discount_verdict": "NORMAL_PRICE",
                                },
                                # In-stock cheapest
                                {
                                    "product_sk": "sk_amz",
                                    "store_name": "amazon_eg",
                                    "price": 58000.0,
                                    "in_stock": True,
                                    "product_url": "https://amazon.eg/15pro",
                                    "discount_verdict": "GENUINE_DEAL",
                                },
                            ]
                        }
                    ]
                )
            if "LOWER(sub_category) = :sub_cat" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "product_sk": "sk_sim_1",
                            "product_title": "Apple iPhone 15 Plus 256GB Smartphone",
                            "store_name": "tradeline",
                            "brand": "Apple",
                            "category": "electronics",
                            "sub_category": "smartphones",
                            "current_price": 54000.0,
                            "discount_verdict": "NORMAL_PRICE",
                            "in_stock": True,
                            "image_url": None,
                            "product_url": "https://tradeline.com/15plus",
                            "parent_product_key": "tradeline::15plus",
                            "canonical_product_key": "canon_other",
                        }
                    ]
                )
            return _FakeResult(rows=[])

        fake_db = _FakeDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        resp = client.get("/api/v1/products/sk_main")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 1. Exact alternatives sorted cheapest in-stock first, OOS last
        self.assertEqual([a["store_name"] for a in body["alternatives"]], ["amazon_eg", "noon", "dream2000"])
        # 2. Smart similar_products clearly populated even when exact alternatives exist!
        self.assertEqual(len(body["similar_products"]), 1)
        self.assertEqual(body["similar_products"][0]["product_sk"], "sk_sim_1")
        self.assertEqual(body["similar_alternatives"], body["similar_products"])

        # 3. Cached inside 12h product_detail_cache (0 extra DB queries on second request)
        calls_after_first = len(fake_db.calls)
        resp2 = client.get("/api/v1/products/sk_main")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(fake_db.calls), calls_after_first)

    def test_similar_alternatives_strict_subtype_gating_blocks_dishwasher_washer_and_appliance_leaks(self) -> None:
        from app.similar_alternatives import _detect_subtype

        now = datetime(2026, 11, 25, 4, 0, 0, tzinfo=timezone.utc)
        # Real production bug: LG Dishwasher (plural "Dishwashers") filed under `washing_machines`
        lg_dishwasher = ProductVerdictItem(
            product_sk="sk_lg_dw",
            canonical_product_key="lg_dfc513fve",
            store_name="2b",
            category="home_appliances",
            sub_category="washing_machines",
            brand="LG",
            product_title="LG Free Standing Dishwashers 14 Place - 8 Programs Inverter Motor - DFC513FVE",
            product_url="https://2b.com.eg/lg-dishwasher",
            image_url=None,
            attributes_json={},
            current_price=38989.0,
            claimed_original_price=None,
            rolling_60d_median=38989.0,
            min_historical_price=38989.0,
            max_historical_price=38989.0,
            claimed_discount_pct=0.0,
            real_discount_pct=0.0,
            discount_verdict="NEWLY_TRACKED",
            scarcity_flag=False,
            in_stock=True,
            last_updated_at=now,
            parent_product_key="2b::lg-dw",
            tracked_days_count=2,
            history_maturity="EARLY",
            verified_historical_median=None,
        )

        candidates = [
            # VALID: Bosch Dishwasher filed under `dishwashers`
            {
                "product_sk": "sk_bosch_dw",
                "product_title": "Bosch Free Standing Dishwasher 14 Place Settings Silver SMS4HVI33E",
                "store_name": "ehab_center",
                "brand": "Bosch",
                "category": "home_appliances",
                "sub_category": "dishwashers",
                "current_price": 37999.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://ehabcenter.com/bosch-dw",
                "parent_product_key": "ehab_center::bosch-dw",
                "canonical_product_key": "bosch_sms4hvi33e",
            },
            # VALID: Arabic Dishwasher filed under `washing_machines`
            {
                "product_sk": "sk_beko_dw_ar",
                "product_title": "بيكو غسالة أطباق 14 فرد 6 برامج انفرتر فضي",
                "store_name": "btech",
                "brand": "Beko",
                "category": "home_appliances",
                "sub_category": "washing_machines",
                "current_price": 35500.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://btech.com/beko-dw",
                "parent_product_key": "btech::beko-dw",
                "canonical_product_key": None,
            },
            # MUST BE BLOCKED: Toshiba Washing Machine
            {
                "product_sk": "sk_toshiba_wm",
                "product_title": "Toshiba Front Load Washing Machine 10kg Inverter Motor Silver",
                "store_name": "rayashop",
                "brand": "Toshiba",
                "category": "home_appliances",
                "sub_category": "washing_machines",
                "current_price": 36999.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://rayashop.com/toshiba-wm",
                "parent_product_key": "rayashop::toshiba-wm",
                "canonical_product_key": None,
            },
            # MUST BE BLOCKED: Hoover Washing Machine
            {
                "product_sk": "sk_hoover_wm",
                "product_title": "Hoover Automatic Washer 11kg Front Load Inverter Silver",
                "store_name": "raneen",
                "brand": "Hoover",
                "category": "home_appliances",
                "sub_category": "washing_machines",
                "current_price": 37499.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://raneen.com/hoover-wm",
                "parent_product_key": "raneen::hoover-wm",
                "canonical_product_key": None,
            },
            # MUST BE BLOCKED: Clothes Dryer
            {
                "product_sk": "sk_hoover_dryer",
                "product_title": "Hoover Condenser Clothes Dryer 9kg Inverter Silver",
                "store_name": "amazon_eg",
                "brand": "Hoover",
                "category": "home_appliances",
                "sub_category": "washing_machines",
                "current_price": 37900.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://amazon.eg/hoover-dryer",
                "parent_product_key": "amazon_eg::hoover-dryer",
                "canonical_product_key": None,
            },
            # MUST BE BLOCKED: Dishwasher Tablets consumable
            {
                "product_sk": "sk_finish_tabs",
                "product_title": "Finish Powerball Dishwasher Tablets Pack of 100",
                "store_name": "seoudi",
                "brand": "Finish",
                "category": "home_appliances",
                "sub_category": "dishwashers",
                "current_price": 35000.0,
                "discount_verdict": "NEWLY_TRACKED",
                "in_stock": True,
                "image_url": None,
                "product_url": "https://seoudi.com/tabs",
                "parent_product_key": "seoudi::tabs",
                "canonical_product_key": None,
            },
        ]

        fake_db = _FakeDB(lambda _sql, _params: _FakeResult(rows=candidates))
        results = find_similar_alternatives(fake_db, lg_dishwasher, max_results=6)
        self.assertEqual({r.product_sk for r in results}, {"sk_bosch_dw", "sk_beko_dw_ar"})
        self.assertTrue(all(r.is_exact_match is False for r in results))

        # Verify subtype isolation across all critical incompatible product pairs
        self.assertEqual(_detect_subtype("LG Free Standing Dishwashers 14 Place", "washing_machines").code, "dishwasher")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Hoover Condenser Clothes Dryer 9kg", "washing_machines").code, "clothes_dryer")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Toshiba Washing Machine 10kg", "washing_machines").code, "washing_machine")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("ثلاجة شارب 450 لتر نوفروست فريزر علوي", "refrigerators").code, "refrigerator")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Sharp Deep Freezer 6 Drawers No Frost", "refrigerators").code, "deep_freezer")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Philips Air Fryer 6.2L Digital", "cookers").code, "air_fryer")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Instant Pot Multi Cooker 6L", "cookers").code, "multi_cooker")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("De'Longhi Espresso Machine EC685", "kitchen_appliances").code, "espresso_coffee_maker")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Tornado Electric Kettle 1.7L", "kitchen_appliances").code, "kettle")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Redmi Watch 4 Smartwatch", "wearables").code, "smartwatch")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Redmi Buds 5 Pro Wireless Earbuds", "audio").code, "earbuds")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Oppo Reno 12 256GB Smartphone", "smartphones").code, "smartphone")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Xiaomi Android TV Box S 2nd Gen", "tvs").code, "tv_receiver_box")  # type: ignore[union-attr]
        self.assertEqual(_detect_subtype("Samsung 55 Inch 4K Smart TV", "tvs").code, "tv")  # type: ignore[union-attr]

    def test_stats_overview_exposes_cross_store_matches_count(self) -> None:
        now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)

        def handler(_sql: str, _params: dict[str, Any]) -> _FakeResult:
            return _FakeResult(
                rows=[
                    {
                        "total_tracked": 333702,
                        "fake_discounts_today": 1400,
                        "genuine_deals_today": 820,
                        "all_time_lows_today": 0,
                        "presale_hikes_today": 110,
                        "avg_fake_inflation_pct": 19.5,
                        "last_pipeline_run_at": now,
                        "available_stores": ["amazon_eg", "btech", "noon"],
                        "category_counts": {"electronics": 62000},
                        "cross_store_matches_count": 10149,
                    }
                ]
            )

        fake_db = _FakeDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        resp = client.get("/api/v1/stats/overview")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["all_time_lows_today"], 0)
        self.assertEqual(body["cross_store_matches_count"], 10149)


if __name__ == "__main__":
    unittest.main()
