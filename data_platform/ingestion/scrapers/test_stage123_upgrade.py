"""Unit tests for the 3-Stage Upgrade: Bilingual Search, 3-Tier Hybrid Matcher,
Config-Driven Multi-Store Registry, Delta Snapshots, and Cloud Batch Matrix."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from data_platform.ingestion.scrapers.adapters import ShopifyBaseScraper, WooCommerceBaseScraper
from data_platform.ingestion.scrapers.base import RawProductSnapshot, compute_delta_snapshots
from data_platform.ingestion.scrapers.bilingual import (
    build_search_document,
    expand_search_query,
    normalize_arabic,
    translate_arabic_retail_terms,
)
from data_platform.ingestion.scrapers.matcher import assign_canonical_keys
from data_platform.ingestion.scrapers.registry_loader import (
    StoreRegistryEntry,
    build_platform_scraper_class,
    get_batch_targets,
    list_active_batches,
    load_stores_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_rec(
    store: str,
    ext_id: str,
    title: str,
    price: float,
    *,
    category: str = "home_appliances",
    sub_category: str = "tvs",
    brand: str = "Samsung",
    claimed: float | None = None,
    in_stock: bool = True,
    snap_date: date = date(2026, 11, 22),
) -> RawProductSnapshot:
    return RawProductSnapshot(
        store_name=store,
        external_id=ext_id,
        category=category,  # type: ignore[arg-type]
        sub_category=sub_category,
        brand=brand,
        product_title=title,
        product_url=f"https://example.com/{store}/{ext_id}",
        image_url=f"https://example.com/{store}/{ext_id}.jpg",
        attributes_json={},
        current_price=Decimal(f"{price:.2f}"),
        claimed_original_price=Decimal(f"{claimed:.2f}") if claimed else None,
        in_stock=in_stock,
        snapshot_date=snap_date,
        scraped_at=datetime(2026, 11, 22, 4, 0, 0),
    )


class TestStage1BilingualAndHybridMatcher(unittest.TestCase):
    def test_arabic_normalization_and_bilingual_synonym_expansion(self) -> None:
        self.assertEqual(normalize_arabic("ثَلاَّجَة أَصْلِيَّة ٦٥"), "ثلاجه اصليه 65")
        self.assertIn("refrigerator", translate_arabic_retail_terms("تلاجة سامسونج 450 لتر"))
        self.assertIn("samsung", translate_arabic_retail_terms("تلاجة سامسونج 450 لتر"))
        self.assertIn("65 inch", translate_arabic_retail_terms("شاشة 65 بوصة"))
        self.assertIn("1.5 hp", translate_arabic_retail_terms("تكييف 1.5 حصان"))
        self.assertIn("256 gb", translate_arabic_retail_terms("ايفون 16 256 جيجا"))

        ex = expand_search_query("تلاجة سامسونج")
        self.assertTrue(any("refrigerator" in v and "samsung" in v for v in ex))
        self.assertTrue(any("fridge" in v and "samsung" in v for v in ex))

        doc = build_search_document(
            product_title="Samsung 55 Inch Smart TV",
            brand="Samsung",
            category="home_appliances",
            sub_category="tvs",
            store_name="btech",
        )
        self.assertIn("samsung", doc)
        self.assertIn("سامسونج", doc)
        self.assertIn("بوصه", doc)

    def test_tier1_bilingual_ar_en_exact_model_match(self) -> None:
        ar_tv = _make_rec(
            "dubaiphone",
            "dp-s85h",
            "تلفزيون سامسونج S85H الذكي OLED مقاس 65 بوصة بدقة 4K",
            69999.0,
            category="home_appliances",
            sub_category="tvs",
            brand="Unknown",
        )
        en_tv = _make_rec(
            "btech",
            "bt-s85h",
            "Samsung 65 Inch 4K OLED Smart TV S85H",
            72500.0,
            category="home_appliances",
            sub_category="tvs",
            brand="Samsung",
        )
        summary = assign_canonical_keys([ar_tv, en_tv])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(summary.tier1_groups, 1)
        self.assertIsNotNone(ar_tv.canonical_product_key)
        self.assertEqual(ar_tv.canonical_product_key, en_tv.canonical_product_key)

    def test_tier2_spec_blocked_match_and_size_isolation(self) -> None:
        # Same 90cm 5-burner Fresh Professional cooker in EN and AR (no MPN code) -> Tier 2 match
        c1 = _make_rec(
            "raneen",
            "rn-cook1",
            "Fresh Professional Cooker 90 cm 5 Gas Burners Stainless Steel",
            21500.0,
            sub_category="cookers",
            brand="Fresh",
        )
        c2 = _make_rec(
            "elaraby",
            "ea-cook1",
            "فريش بوتاجاز بروفيشنال 90 سم 5 شعلة استانلس ستيل",
            22100.0,
            sub_category="cookers",
            brand="Fresh",
        )
        # Different size (60cm 4-burner) -> MUST NOT merge!
        c_small = _make_rec(
            "btech",
            "bt-cook-60",
            "Fresh Professional Cooker 60 cm 4 Gas Burners Stainless Steel",
            14500.0,
            sub_category="cookers",
            brand="Fresh",
        )
        summary = assign_canonical_keys([c1, c2, c_small])
        self.assertIsNotNone(c1.canonical_product_key)
        self.assertNotEqual(c1.canonical_product_key, c_small.canonical_product_key)
        self.assertIsNone(c_small.canonical_product_key)
        # Even without identical wording, c1 & c2 share the 90cm_5b spec block; verify same-spec match
        c2_en = _make_rec(
            "cairosales",
            "cs-cook1",
            "Fresh Professional Gas Cooker 90 cm 5 Burners Stainless",
            21900.0,
            sub_category="cookers",
            brand="Fresh",
        )
        summary2 = assign_canonical_keys([c1, c2_en, c_small])
        self.assertEqual(summary2.matched_groups, 1)
        self.assertEqual(c1.canonical_product_key, c2_en.canonical_product_key)
        self.assertIsNone(c_small.canonical_product_key)

    def test_tier3_semantic_similarity_respects_spec_block_and_price_ratio(self) -> None:
        # Same spec block (1.5hp_inv_hc) + high token/ngram overlap, slight wording difference -> Tier 3 match
        ac1 = _make_rec(
            "btech",
            "bt-ac1",
            "Carrier Optimax Inverter Split Air Conditioner 1.5 HP Cooling Heating White",
            27500.0,
            sub_category="air_conditioners",
            brand="Carrier",
        )
        ac2 = _make_rec(
            "raneen",
            "rn-ac1",
            "Carrier Optimax Pro Inverter Air Conditioner 1.5 HP Cool Heat",
            28900.0,
            sub_category="air_conditioners",
            brand="Carrier",
        )
        # Wildly different price (3x outlier) -> MUST NOT merge in Tier 3
        ac_outlier = _make_rec(
            "rayashop",
            "ry-ac-out",
            "Carrier Optimax Inverter Split Air Conditioner 1.5 HP Cooling Heating",
            65000.0,
            sub_category="air_conditioners",
            brand="Carrier",
        )
        # Different tonnage (2.25 HP) -> MUST NOT merge!
        ac_bigger = _make_rec(
            "cairosales",
            "cs-ac225",
            "Carrier Optimax Inverter Split Air Conditioner 2.25 HP Cooling Heating",
            39500.0,
            sub_category="air_conditioners",
            brand="Carrier",
        )
        summary = assign_canonical_keys([ac1, ac2, ac_outlier, ac_bigger])
        self.assertEqual(summary.matched_groups, 1)
        self.assertEqual(summary.tier3_groups, 1)
        self.assertEqual(ac1.canonical_product_key, ac2.canonical_product_key)
        self.assertIsNone(ac_outlier.canonical_product_key)
        self.assertIsNone(ac_bigger.canonical_product_key)


class TestStage2And3RegistryDeltaAndMatrix(unittest.TestCase):
    def test_delta_snapshots_skips_unchanged_and_tracks_savings(self) -> None:
        existing = {
            ("sigma", "SKU-1"): (Decimal("15000.00"), None, True, "ASUS Monitor 24 Inch", date(2026, 11, 20)),
            ("sigma", "SKU-2"): (Decimal("20000.00"), Decimal("22000.00"), True, "Lenovo Laptop", date(2026, 11, 20)),
            ("sigma", "SKU-3"): (Decimal("8500.00"), None, True, "LG Monitor", date(2026, 11, 20)),
        }
        incoming = [
            # Unchanged -> skipped (only touch last_seen_at)
            _make_rec("sigma", "SKU-1", "ASUS Monitor 24 Inch", 15000.0, category="electronics", sub_category="monitors"),
            # Price dropped -> inserted!
            _make_rec("sigma", "SKU-2", "Lenovo Laptop", 18999.0, category="electronics", sub_category="laptops", claimed=22000.0),
            # Stock changed -> inserted!
            _make_rec("sigma", "SKU-3", "LG Monitor", 8500.0, category="electronics", sub_category="monitors", in_stock=False),
            # Brand new SKU -> inserted!
            _make_rec("sigma", "SKU-4", "HP Monitor 27 Inch", 11000.0, category="electronics", sub_category="monitors"),
        ]
        changed, touch_rows, stats = compute_delta_snapshots(incoming, existing)
        self.assertEqual([r.external_id for r in changed], ["SKU-2", "SKU-3", "SKU-4"])
        self.assertEqual(len(touch_rows), 1)
        self.assertEqual(touch_rows[0][:3], ("sigma", "SKU-1", date(2026, 11, 20)))
        self.assertEqual(stats.total_scraped, 4)
        self.assertEqual(stats.inserted_or_changed, 3)
        self.assertEqual(stats.skipped_unchanged, 1)
        self.assertEqual(stats.savings_pct, 25.0)

    def test_stores_registry_yaml_structure_and_dynamic_adapter_synthesis(self) -> None:
        all_stores = load_stores_registry()
        self.assertGreaterEqual(len(all_stores), 100)
        enabled_stores = load_stores_registry(enabled_only=True)
        self.assertEqual(len(enabled_stores), 30)

        local_only = {s.store_key for s in load_stores_registry(enabled_only=True, region_mode="local_only")}
        self.assertEqual(local_only, {"2b", "sigma"})

        cloud_batches = list_active_batches(region_mode="cloud")
        self.assertNotIn("local_core", cloud_batches)
        self.assertGreaterEqual(len(cloud_batches), 5)
        self.assertIn("core_1", cloud_batches)
        self.assertIn("groceries_1", cloud_batches)
        self.assertIn("fashion_1", cloud_batches)

        g1 = get_batch_targets("groceries_1", region_mode="cloud")
        g1_keys = {k for k, _ in g1}
        self.assertTrue({"spinneys", "hyperone", "seoudi", "amazon_eg", "noon"}.issubset(g1_keys))

        # Dynamic synthesis for generic Shopify & WooCommerce registry entries
        sh_cls = build_platform_scraper_class(
            StoreRegistryEntry(
                store_key="demo_shopify",
                display_name="Demo Shopify",
                platform="shopify",
                base_url="https://demo.myshopify.com",
                category="home_furniture",
                vertical="core",
                enabled=True,
            )
        )
        self.assertIsNotNone(sh_cls)
        assert sh_cls is not None
        self.assertTrue(issubclass(sh_cls, ShopifyBaseScraper))
        self.assertEqual(sh_cls.category, "home_appliances")

        wc_cls = build_platform_scraper_class(
            StoreRegistryEntry(
                store_key="demo_woo",
                display_name="Demo Woo",
                platform="woocommerce",
                base_url="https://demo.eg",
                category="pharmacy",
                vertical="groceries",
                enabled=True,
            )
        )
        self.assertIsNotNone(wc_cls)
        assert wc_cls is not None
        self.assertTrue(issubclass(wc_cls, WooCommerceBaseScraper))
        self.assertEqual(wc_cls.category, "groceries")

    def test_daily_stores_matrix_workflow_yaml_valid(self) -> None:
        wf_path = REPO_ROOT / ".github" / "workflows" / "daily-stores-matrix.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        self.assertIn("plan-batches", wf["jobs"])
        self.assertIn("scrape-batch", wf["jobs"])
        self.assertIn("match-and-dbt", wf["jobs"])
        self.assertEqual(wf["jobs"]["scrape-batch"]["timeout-minutes"], 25)


if __name__ == "__main__":
    unittest.main()
