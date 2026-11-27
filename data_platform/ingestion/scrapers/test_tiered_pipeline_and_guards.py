"""Unit tests for Priority 1-3 tiered orchestration, brand normalization, cross-adapter OOS skip,
900/950 MB storage circuit-breaker, and offline GitHub Actions workflow validation."""

from __future__ import annotations

import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import yaml

from data_platform.ingestion.scrapers import (
    BaseScraper,
    PoliteHttpClient,
    RawProductSnapshot,
    SCRAPER_REGISTRY,
    compute_product_sk,
    load_stores_registry,
    normalize_product_brand,
    plan_tiered_waves_for_day,
)
from data_platform.ingestion.scrapers.storage_circuit_breaker import (
    StorageSnapshot,
    TableSizeStat,
    can_run_vacuum_full,
    evaluate_storage_mode,
    filter_for_price_update_only,
    format_telegram_storage_alert,
    send_storage_telegram_alert,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_snap(store: str, ext_id: str, *, brand: str = "Unknown", title: str = "Test Product", in_stock: bool = True, price: str = "999.00", url: str = "https://example.com/p/1") -> RawProductSnapshot:
    return RawProductSnapshot.model_validate(
        {
            "store_name": store,
            "external_id": ext_id,
            "canonical_product_key": None,
            "category": "electronics",
            "sub_category": "accessories",
            "brand": brand,
            "product_title": title,
            "product_url": url,
            "image_url": None,
            "attributes_json": {},
            "current_price": Decimal(price),
            "claimed_original_price": None,
            "in_stock": in_stock,
            "snapshot_date": date(2026, 11, 24),
            "scraped_at": datetime(2026, 11, 24, 12, 0, 0),
        }
    )


class TestBrandNormalizer(unittest.TestCase):
    def test_single_brand_stores_and_suffix_stripping(self) -> None:
        self.assertEqual(normalize_product_brand("My Store", store_name="eva_cosmetics", product_title="Eva Lotion"), "Eva")
        self.assertEqual(normalize_product_brand("Unknown", store_name="zanussi_eg", product_title="غسالة اتوماتيك زانوسي 8 كيلو"), "Zanussi")
        self.assertEqual(normalize_product_brand("My Store", store_name="espresso_egypt", product_title="Brazil Specialty Coffee"), "Espresso Egypt")
        self.assertEqual(normalize_product_brand("PUMA EG", store_name="puma_eg", product_title="Running Shoes"), "Puma")
        self.assertEqual(normalize_product_brand("ALDO EG", store_name="aldo_eg", product_title="Leather Loafer"), "Aldo")
        self.assertEqual(normalize_product_brand("", store_name="timberland_eg", product_title="Euro Hiker Boot"), "Timberland")

    def test_bilingual_arabic_and_english_title_extraction(self) -> None:
        self.assertEqual(normalize_product_brand("Unknown", store_name="dubaiphone", product_title="سماعة أنكر ساوند كور Q20i"), "Anker")
        self.assertEqual(normalize_product_brand("Unknown", store_name="dubaiphone", product_title="حامل هاتف للسيارة يوجرين LP200"), "UGREEN")
        self.assertEqual(normalize_product_brand("Unknown", store_name="dubaiphone", product_title="سماعة جي بي إل بارتي بوكس كلوب 120"), "JBL")
        self.assertEqual(normalize_product_brand("Kaufen Egypt Online Store", store_name="kaufen_eg", product_title="CASO Microwave MCG 30 Ceramic Chef"), "CASO")
        self.assertEqual(normalize_product_brand("Happet", store_name="happet", product_title="Pro Plan Dog Dry Food Adult 3 kg"), "Purina")
        self.assertEqual(normalize_product_brand("Unknown", store_name="sigma", product_title="KIOXIA EXCERIA PLUS G3 2TB NVMe SSD"), "Kioxia")

    def test_compatibility_clause_does_not_mislabel_generic_accessory(self) -> None:
        brand = normalize_product_brand(
            "Generic",
            store_name="icamstore",
            product_title="Generic Silicone Protection Case for Canon PowerShot G7 X Mark III",
        )
        self.assertEqual(brand, "Generic")

    def test_raw_product_snapshot_normalizes_brand_automatically(self) -> None:
        snap = _make_snap("dubaiphone", "sku-1", brand="Unknown", title="سماعة أنكر ساوند كور Q20i")
        self.assertEqual(snap.brand, "Anker")


class TestCrossAdapterOosSkip(unittest.TestCase):
    def test_base_scraper_skips_brand_new_oos_and_keeps_tracked_oos(self) -> None:
        class _DummyCustomScraper(BaseScraper):
            store_name = "dummy_custom"
            base_url = "https://dummy.example.com"

            def scrape(self, limit: int = 30) -> list[RawProductSnapshot]:
                return []

        http = PoliteHttpClient(min_delay_seconds=0.0)
        try:
            scraper = _DummyCustomScraper(http, tracked_external_ids={"tracked-oos"})
            base_payload = {
                "store_name": "dummy_custom",
                "canonical_product_key": None,
                "category": "electronics",
                "sub_category": "accessories",
                "brand": "Anker",
                "product_title": "Anker USB-C Hub",
                "product_url": "https://dummy.example.com/p/1",
                "image_url": None,
                "attributes_json": {},
                "current_price": Decimal("650.00"),
                "claimed_original_price": None,
                "snapshot_date": date(2026, 11, 24),
                "scraped_at": datetime(2026, 11, 24, 12, 0, 0),
            }
            # Brand-new OOS -> skipped
            self.assertIsNone(scraper.validate_record({**base_payload, "external_id": "new-oos", "in_stock": False}))
            self.assertEqual(scraper.skipped_oos_count, 1)

            # Tracked OOS -> preserved
            rec_tracked = scraper.validate_record({**base_payload, "external_id": "tracked-oos", "in_stock": False})
            self.assertIsNotNone(rec_tracked)
            assert rec_tracked is not None
            self.assertFalse(rec_tracked.in_stock)

            # Brand-new in-stock -> preserved
            rec_live = scraper.validate_record({**base_payload, "external_id": "new-live", "in_stock": True})
            self.assertIsNotNone(rec_live)
            assert rec_live is not None
            self.assertTrue(rec_live.in_stock)
        finally:
            http.close()


class TestTieredRegistryAndWavePlanning(unittest.TestCase):
    def test_new_priority1_major_brand_stores_registered_and_tier1(self) -> None:
        expected_new = {
            "timberland_eg", "samsonite_eg", "tupperware_eg", "tank_eg", "luna_eg",
            "mintra_eg", "ravin", "andora_eg", "tie_house_eg", "tie_shop_eg",
            "dott_jeans_eg", "runner_eg", "dstore_eg", "kayanek_eg", "el_sallab_eg",
            "cherry_and_berry",
        }
        entries = {e.store_key: e for e in load_stores_registry(enabled_only=True)}
        for key in expected_new:
            self.assertIn(key, entries, f"Missing enabled Priority 1 store: {key}")
            self.assertEqual(entries[key].tier, 1)
            self.assertEqual(entries[key].priority_group, "major_brands")
            self.assertIn(key, SCRAPER_REGISTRY, f"Store {key} not synthesized in SCRAPER_REGISTRY")

    def test_amazon_eg_is_p1_top_priority_with_all_10_category_shards(self) -> None:
        from data_platform.ingestion.scrapers.amazon_eg import (
            AMAZON_EG_DEPARTMENT_QUERIES,
            AMAZON_EG_DEPARTMENT_SHARD_ORDER,
            AmazonEgScraper,
        )
        from data_platform.ingestion.scrapers.base import CANONICAL_CATEGORIES, ThrottledResponseError

        # Cloud plan MUST exclude amazon_eg (local_only residential execution avoids Azure 503s)
        cloud_plan = plan_tiered_waves_for_day(1, region_mode="cloud", tier2_cadence_days=3, tier3_cadence_days=5)
        self.assertNotIn("amazon_eg", cloud_plan["priority_1_stores"])

        # Local-included plan MUST put amazon_eg #1 in Priority 1 with all 5 department shards
        plan = plan_tiered_waves_for_day(1, region_mode=None, tier2_cadence_days=3, tier3_cadence_days=5)
        self.assertEqual(plan["priority_1_stores"][0], "amazon_eg")
        first_five = [s["shard"] for s in plan["shards"][:5]]
        self.assertEqual(
            first_five,
            [
                "p1_amazon_eg_electronics",
                "p1_amazon_eg_home_appliances",
                "p1_amazon_eg_fashion_beauty",
                "p1_amazon_eg_groceries_health",
                "p1_amazon_eg_home_sports_baby_pet",
            ],
        )
        covered_cats = {
            cat
            for grp in AMAZON_EG_DEPARTMENT_SHARD_ORDER
            for _, cat, _ in AMAZON_EG_DEPARTMENT_QUERIES[grp]
        }
        self.assertEqual(covered_cats, set(CANONICAL_CATEGORIES))
        self.assertIn("super_supplements", SCRAPER_REGISTRY)

        # Verify AmazonEgScraper recovers from transient 503s (does NOT abort on strike=1)
        class _FakeResp:
            def __init__(self, text: str) -> None:
                self.text = text

        sample_html = (
            '<div data-component-type="s-search-result" data-asin="B0TEST1234">'
            '<h2>Samsung</h2><h2>Galaxy A55 5G Smartphone</h2>'
            '<span class="a-price"><span class="a-offscreen">EGP 18,999.00</span></span>'
            '</div>'
        )
        calls = {"search": 0, "opened": 0}

        class _FakeClient:
            def get(self, url: str, **kwargs):
                if "/-/en/s?" in url:
                    calls["search"] += 1
                    if calls["search"] == 1:
                        raise ThrottledResponseError("HTTP 503 transient")
                    return _FakeResp(sample_html)
                return _FakeResp("<html><title>Amazon.eg</title>" + ("x" * 6000) + "</html>")

            def close(self) -> None:
                pass

        with PoliteHttpClient(min_delay_seconds=0.0) as http:
            scraper = AmazonEgScraper(http, department_group="electronics")
            scraper.throttle_cooldown_range = (0.0, 0.0)
            scraper.page_delay_range = (0.0, 0.0)
            with patch.object(scraper, "_open_client", side_effect=lambda *a, **k: (calls.__setitem__("opened", calls["opened"] + 1) or _FakeClient())):
                recs = scraper.scrape(limit=1)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].external_id, "B0TEST1234")
        self.assertGreaterEqual(calls["opened"], 2, "Expected session rotation after transient 503")

    def test_strict_priority_order_and_tier2_tier3_rotation(self) -> None:
        plan_d1 = plan_tiered_waves_for_day(1, region_mode="cloud", tier2_cadence_days=3, tier3_cadence_days=5)
        priorities = [s["priority"] for s in plan_d1["shards"]]
        rank_map = {"p1_major_brands": 0, "p2_major_stores": 1, "p3_tier2": 2, "p3_tier3": 3}
        ranks = [rank_map[p] for p in priorities]
        self.assertEqual(ranks, sorted(ranks), "Shards must stay in strict P1 -> P2 -> P3A -> P3B order")

        # Tier-1 stores run daily (identical across consecutive days)
        plan_d2 = plan_tiered_waves_for_day(2, region_mode="cloud", tier2_cadence_days=3, tier3_cadence_days=5)
        self.assertEqual(plan_d1["priority_1_stores"], plan_d2["priority_1_stores"])
        self.assertEqual(plan_d1["priority_2_stores"], plan_d2["priority_2_stores"])

        # Over a 3-day window, 100% of Tier-2 stores are covered; over 5 days, 100% of Tier-3
        t2_union: set[str] = set()
        for d in range(1, 4):
            t2_union.update(plan_tiered_waves_for_day(d, region_mode="cloud", tier2_cadence_days=3)["tier2_today_stores"])
        self.assertEqual(len(t2_union), plan_d1["counts"]["tier2_total"])

        t3_union: set[str] = set()
        for d in range(1, 6):
            t3_union.update(plan_tiered_waves_for_day(d, region_mode="cloud", tier3_cadence_days=5)["tier3_today_stores"])
        self.assertEqual(len(t3_union), plan_d1["counts"]["tier3_total"])


class TestStorageCircuitBreaker(unittest.TestCase):
    def test_thresholds_900mb_950mb_and_vacuum_full_700mb_guard(self) -> None:
        d_ok = evaluate_storage_mode(534.97)
        self.assertEqual(d_ok.mode, "FULL_EXPANSION")
        self.assertTrue(d_ok.allow_new_inserts)
        self.assertTrue(d_ok.allow_writes)
        self.assertFalse(d_ok.should_notify)

        d_warn = evaluate_storage_mode(951.20)
        self.assertEqual(d_warn.mode, "PRICE_UPDATE_ONLY")
        self.assertFalse(d_warn.allow_new_inserts)
        self.assertTrue(d_warn.allow_writes)
        self.assertTrue(d_warn.should_notify)

        d_stop = evaluate_storage_mode(971.20)
        self.assertEqual(d_stop.mode, "HARD_STOP")
        self.assertFalse(d_stop.allow_new_inserts)
        self.assertFalse(d_stop.allow_writes)
        self.assertTrue(d_stop.should_notify)

        self.assertTrue(can_run_vacuum_full(699.9))
        self.assertFalse(can_run_vacuum_full(700.1))

    def test_price_update_only_filter_keeps_tracked_and_drops_new(self) -> None:
        s_tracked = _make_snap("amazon_eg", "B0TRACKED1", brand="Samsung", title="Samsung TV")
        s_new = _make_snap("amazon_eg", "B0BRANDNEW", brand="Samsung", title="Samsung Phone")
        tracked_sks = {compute_product_sk("amazon_eg", "B0TRACKED1")}
        kept, dropped = filter_for_price_update_only([s_tracked, s_new], tracked_sks)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].external_id, "B0TRACKED1")
        self.assertEqual(dropped, 1)

    def test_telegram_alert_format_and_dispatch(self) -> None:
        snap = StorageSnapshot(
            db_size_mb=918.5,
            db_size_bytes=int(918.5 * 1024 * 1024),
            tables=(TableSizeStat("gold.mart_product_verdicts", 620.0, 480.0, 140.0, 350000),),
        )
        dec = evaluate_storage_mode(snap.db_size_mb)
        msg = format_telegram_storage_alert(dec, snap, context="P3_TIER2_MID")
        self.assertIn("PRICE_UPDATE_ONLY", msg)
        self.assertIn("918.50 MB", msg)
        self.assertIn("gold.mart_product_verdicts", msg)

        posted: list[dict] = []

        class _Resp:
            status_code = 200

        def _fake_post(url: str, json: dict, timeout: float):
            posted.append({"url": url, "json": json})
            return _Resp()

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:test-token", "TELEGRAM_NOTIFY_CHAT_ID": "99999"}):
            ok = send_storage_telegram_alert(dec, snap, context="P3_TIER2_MID", http_post=_fake_post)
        self.assertTrue(ok)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["json"]["chat_id"], "99999")
        self.assertIn("PRICE_UPDATE_ONLY", posted[0]["json"]["text"])


class TestWorkflowAndDbtHygieneGuards(unittest.TestCase):
    def test_daily_workflow_yaml_offline_zero_neon_contract(self) -> None:
        wf_path = REPO_ROOT / ".github" / "workflows" / "daily-stores-matrix.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        self.assertIn("plan-waves", wf["jobs"])
        self.assertIn("scrape-offline", wf["jobs"])
        self.assertIn("load-match-dbt", wf["jobs"])

        # Verify scrape-offline NEVER receives Neon secrets (explicitly blanked)
        scrape_steps = wf["jobs"]["scrape-offline"]["steps"]
        run_step = next(s for s in scrape_steps if "scrape-shard" in str(s.get("run", "")))
        env = run_step.get("env") or {}
        self.assertEqual(env.get("DATABASE_URL_ADMIN"), "")
        self.assertEqual(env.get("DATABASE_URL_READONLY"), "")

        # Verify load-match-dbt runs strictly after scrape-offline with upgraded circuit breaker
        load_job = wf["jobs"]["load-match-dbt"]
        self.assertIn("scrape-offline", load_job["needs"])
        load_cmd = " ".join(str(s.get("run", "")) for s in load_job["steps"])
        self.assertIn("--warn-mb 4500", load_cmd)
        self.assertIn("--stop-mb 4900", load_cmd)

    def test_dbt_mart_verdicts_has_45d_oos_hygiene_and_preserves_history(self) -> None:
        sql = (REPO_ROOT / "data_platform" / "warehouse_dbt" / "models" / "marts" / "mart_product_verdicts.sql").read_text(encoding="utf-8")
        self.assertIn("INTERVAL '45 days'", sql)
        self.assertIn("DELETE FROM {{ this }}", sql)
        self.assertNotIn("DELETE FROM gold.fct_price_history", sql)


if __name__ == "__main__":
    unittest.main()
