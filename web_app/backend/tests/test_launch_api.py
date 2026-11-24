"""FastAPI TestClient tests covering caching headers, launch endpoints, alerts, and alert job."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.cache import api_cache, sitemap_cache  # noqa: E402
from app.database import get_db, get_write_db  # noqa: E402
from app.main import app  # noqa: E402
from jobs import check_price_alerts  # noqa: E402


class _FakeResult:
    def __init__(self, *, rows: list[dict[str, Any]] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def one(self) -> dict[str, Any]:
        return self._rows[0]

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeReadDB:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[str] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(stmt)
        self.calls.append(sql)
        return self.handler(sql, params or {})


class _FakeAlertsDB:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.next_id = 1

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(stmt)
        p = params or {}
        if "CREATE TABLE IF NOT EXISTS" in sql:
            return _FakeResult()
        if "SELECT id" in sql and "FROM public.price_alerts" in sql:
            dest = str(p["destination"]).lower()
            pk = str(p["product_key"])
            for r in self.rows:
                if r["is_active"] and r["destination"].lower() == dest and r["product_key"] == pk:
                    return _FakeResult(scalar=r["id"])
            return _FakeResult(scalar=None)
        if "SELECT COUNT(*)" in sql and "FROM public.price_alerts" in sql:
            dest = str(p["destination"]).lower()
            cnt = sum(1 for r in self.rows if r["is_active"] and r["destination"].lower() == dest)
            return _FakeResult(scalar=cnt)
        if "INSERT INTO public.price_alerts" in sql:
            row = {
                "id": self.next_id,
                "product_key": p["product_key"],
                "product_title": p["product_title"],
                "store_name": p["store_name"],
                "target_price": p["target_price"],
                "channel": p["channel"],
                "destination": p["destination"],
                "is_active": True,
                "triggered_at": None,
            }
            self.rows.append(row)
            self.next_id += 1
            return _FakeResult(scalar=row["id"])
        raise AssertionError(f"Unexpected SQL in fake alerts DB: {sql}")


class TestLaunchBackendAPI(unittest.TestCase):
    def setUp(self) -> None:
        api_cache.clear()
        sitemap_cache.clear()
        app.dependency_overrides.clear()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_radar_highlights_contract_and_cache_headers(self) -> None:
        now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        scandal_row = {
            "product_sk": "sk_scandal_1",
            "canonical_product_key": "samsung_s24_256gb",
            "store_name": "noon",
            "category": "electronics",
            "product_title": "Samsung Galaxy S24 256GB",
            "product_url": "https://www.noon.com/egypt-en/s24/p",
            "image_url": "https://cdn.example.com/s24.jpg",
            "current_price": 42000.0,
            "claimed_original_price": 56000.0,
            "rolling_60d_median": 38000.0,
            "min_historical_price": 37000.0,
            "claimed_discount_pct": 25.0,
            "real_discount_pct": -10.5,
            "discount_verdict": "PRESALE_HIKE",
            "last_updated_at": now,
        }
        deal_row = {
            "product_sk": "sk_deal_1",
            "canonical_product_key": "lg_oled_55",
            "store_name": "btech",
            "category": "home_appliances",
            "product_title": "LG 55 Inch OLED Smart TV",
            "product_url": "https://btech.com/en/p/lg-oled-55",
            "image_url": "https://cdn.example.com/lg.jpg",
            "current_price": 45000.0,
            "claimed_original_price": 55000.0,
            "rolling_60d_median": 52000.0,
            "min_historical_price": 45000.0,
            "claimed_discount_pct": 18.2,
            "real_discount_pct": 13.5,
            "discount_verdict": "ALL_TIME_LOW",
            "last_updated_at": now,
        }

        def handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "PRESALE_HIKE" in sql and "NOT IN" not in sql:
                return _FakeResult(rows=[scandal_row])
            return _FakeResult(rows=[deal_row])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        resp1 = client.get("/api/radar/highlights?limit=12&category=all")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(
            resp1.headers.get("cache-control"),
            "public, s-maxage=600, stale-while-revalidate=300",
        )
        body = resp1.json()
        self.assertEqual(body["updated_at"], "2026-11-22T12:00:00Z")
        self.assertEqual(len(body["biggest_scandals"]), 1)
        self.assertEqual(len(body["best_real_deals"]), 1)

        s0 = body["biggest_scandals"][0]
        self.assertEqual(
            set(s0.keys()),
            {
                "id",
                "product_key",
                "title",
                "store_name",
                "category",
                "image_url",
                "product_url",
                "current_price",
                "claimed_old_price",
                "baseline_price",
                "inflation_pct",
                "real_drop_pct",
                "verdict",
                "parent_product_key",
                "variant_label",
                "variant_count",
                "has_multiple_variants",
                "min_variant_price",
                "max_variant_price",
            },
        )
        self.assertEqual(s0["verdict"], "inflated_before_sale")
        self.assertGreater(s0["inflation_pct"], 0)
        self.assertEqual(body["best_real_deals"][0]["verdict"], "real_deal")
        self.assertEqual(body["best_real_deals"][0]["real_drop_pct"], 13.5)

        # Second identical call hits in-memory TTL cache (DB call count stays at 2)
        calls_after_first = len(fake_db.calls)
        resp2 = client.get("/api/radar/highlights?limit=12&category=all")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(fake_db.calls), calls_after_first)

    def test_highlights_excludes_bait_and_low_price_major_appliances(self) -> None:
        now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            # 1 EGP bait listing -> MUST be excluded
            {
                "product_sk": "sk_bait_1",
                "canonical_product_key": None,
                "store_name": "compumarts",
                "category": "electronics",
                "sub_category": "accessories",
                "product_title": "1 EGP Placeholder Promo Mouse",
                "product_url": "https://compumarts.com/products/bait",
                "image_url": "https://cdn.example.com/bait.jpg",
                "current_price": 1.0,
                "claimed_original_price": 500.0,
                "rolling_60d_median": 500.0,
                "min_historical_price": 1.0,
                "claimed_discount_pct": 99.8,
                "real_discount_pct": 99.8,
                "discount_verdict": "ALL_TIME_LOW",
                "last_updated_at": now,
            },
            # 1,445 EGP Bosch gas cooker (installment leak) -> MUST be excluded
            {
                "product_sk": "sk_cooker_leak",
                "canonical_product_key": None,
                "store_name": "rayashop",
                "category": "home_appliances",
                "sub_category": "cookers",
                "product_title": "BOSCH 90cm 5-Burner Gas Cooker",
                "product_url": "https://www.rayashop.com/en/bosch-cooker",
                "image_url": "https://cdn.example.com/cooker.jpg",
                "current_price": 1445.0,
                "claimed_original_price": 28900.0,
                "rolling_60d_median": 28900.0,
                "min_historical_price": 1445.0,
                "claimed_discount_pct": 95.0,
                "real_discount_pct": 95.0,
                "discount_verdict": "FAKE_DISCOUNT",
                "last_updated_at": now,
            },
            # Legitimate cash-price appliance -> MUST be kept
            {
                "product_sk": "sk_cooker_real",
                "canonical_product_key": "bosch_cooker_90",
                "store_name": "rayashop",
                "category": "home_appliances",
                "sub_category": "cookers",
                "product_title": "BOSCH 90cm 5-Burner Gas Cooker",
                "product_url": "https://www.rayashop.com/en/bosch-cooker-real",
                "image_url": "https://cdn.example.com/cooker.jpg",
                "current_price": 28900.0,
                "claimed_original_price": 34000.0,
                "rolling_60d_median": 31000.0,
                "min_historical_price": 28900.0,
                "claimed_discount_pct": 15.0,
                "real_discount_pct": 6.8,
                "discount_verdict": "ALL_TIME_LOW",
                "last_updated_at": now,
            },
        ]

        fake_db = _FakeReadDB(lambda _sql, _params: _FakeResult(rows=rows))
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        resp = client.get("/api/radar/highlights?limit=10&category=all")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Both SQL queries must include the price-floor guards
        self.assertTrue(all("current_price >= 10" in sql for sql in fake_db.calls))
        self.assertTrue(all("current_price < 2500" in sql for sql in fake_db.calls))
        # Neither bucket may contain the 1 EGP bait or 1,445 EGP cooker leak
        scandal_ids = [item["id"] for item in body["biggest_scandals"]]
        deal_ids = [item["id"] for item in body["best_real_deals"]]
        self.assertEqual(scandal_ids, ["sk_cooker_real"])
        self.assertEqual(deal_ids, ["sk_cooker_real"])

    def test_stats_and_compare_cache_headers_and_ttl_hit(self) -> None:
        now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)

        def handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "FROM gold.mart_product_verdicts" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "total_tracked": 25400,
                            "fake_discounts_today": 3100,
                            "genuine_deals_today": 920,
                            "all_time_lows_today": 410,
                            "presale_hikes_today": 280,
                            "avg_fake_inflation_pct": 21.4,
                            "last_pipeline_run_at": now,
                            "available_stores": ["amazon_eg", "btech", "noon"],
                        }
                    ]
                )
            if "COUNT(*)" in sql:
                return _FakeResult(scalar=0)
            return _FakeResult(rows=[])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        r_stats = client.get("/api/stats")
        self.assertEqual(r_stats.status_code, 200)
        self.assertEqual(
            r_stats.headers.get("cache-control"),
            "public, s-maxage=600, stale-while-revalidate=300",
        )
        self.assertEqual(r_stats.json()["total_tracked"], 25400)

        # Cached hit on /api/v1/stats/overview too
        calls_before = len(fake_db.calls)
        r_stats_v1 = client.get("/api/v1/stats/overview")
        self.assertEqual(r_stats_v1.status_code, 200)
        self.assertEqual(len(fake_db.calls), calls_before)

        r_cmp = client.get("/api/compare?limit=10")
        self.assertEqual(r_cmp.status_code, 200)
        self.assertEqual(
            r_cmp.headers.get("cache-control"),
            "public, s-maxage=600, stale-while-revalidate=300",
        )

    def test_alerts_creation_validation_dedup_and_rate_limit(self) -> None:
        fake_db = _FakeAlertsDB()
        app.dependency_overrides[get_write_db] = lambda: fake_db
        client = TestClient(app)

        # 1. Valid email alert -> 201
        r1 = client.post(
            "/api/alerts",
            json={
                "product_key": "iphone_16_128gb",
                "product_title": "Apple iPhone 16 128GB",
                "store_name": "tradeline",
                "target_price": 45000,
                "channel": "email",
                "destination": "Shopper@Example.com",
            },
        )
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r1.json()["id"], 1)
        self.assertEqual(r1.json()["status"], "active")

        # 2. Duplicate active alert for same destination + product -> 409
        r_dup = client.post(
            "/api/alerts",
            json={
                "product_key": "iphone_16_128gb",
                "product_title": "Apple iPhone 16 128GB",
                "store_name": "tradeline",
                "target_price": 44000,
                "channel": "email",
                "destination": "shopper@example.com",
            },
        )
        self.assertEqual(r_dup.status_code, 409)

        # 3. Valid Telegram @username and numeric chat_id -> 201
        r_tg = client.post(
            "/api/alerts",
            json={
                "product_key": "ps5_slim",
                "product_title": "Sony PlayStation 5 Slim",
                "store_name": "noon",
                "target_price": 24000.5,
                "channel": "telegram",
                "destination": "@cairo_deals_bot",
            },
        )
        self.assertEqual(r_tg.status_code, 201)

        r_tg_id = client.post(
            "/api/alerts",
            json={
                "product_key": "ps5_slim",
                "product_title": "Sony PlayStation 5 Slim",
                "store_name": "noon",
                "target_price": 24000.5,
                "channel": "telegram",
                "destination": "123456789",
            },
        )
        self.assertEqual(r_tg_id.status_code, 201)

        # 4. Invalid payloads -> 422
        bad_payloads = [
            # Non-positive price
            {
                "product_key": "sku1",
                "target_price": -10,
                "channel": "email",
                "destination": "a@b.com",
            },
            # Bad email
            {
                "product_key": "sku1",
                "target_price": 100,
                "channel": "email",
                "destination": "not-an-email",
            },
            # Bad Telegram handle (missing @ and non-numeric)
            {
                "product_key": "sku1",
                "target_price": 100,
                "channel": "telegram",
                "destination": "invalid_user",
            },
            # Unsupported channel
            {
                "product_key": "sku1",
                "target_price": 100,
                "channel": "sms",
                "destination": "+201000000000",
            },
        ]
        for bad in bad_payloads:
            r_bad = client.post("/api/alerts", json=bad)
            self.assertEqual(r_bad.status_code, 422, f"Expected 422 for {bad}, got {r_bad.status_code}")

    def test_seo_sitemap_entries_contract_and_1h_cache(self) -> None:
        now = datetime(2026, 11, 22, 10, 30, 0, tzinfo=timezone.utc)

        def handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "FROM gold.mart_product_verdicts" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "product_sk": "sk_1",
                            "product_key": "canon_1",
                            "category": "electronics",
                            "store_name": "sigma",
                            "last_updated_at": now,
                        }
                    ]
                )
            return _FakeResult(
                rows=[
                    {
                        "canonical_product_key": "canon_1",
                        "category": "electronics",
                        "stores_count": 3,
                    }
                ]
            )

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        r1 = client.get("/api/seo/sitemap-entries?limit=500")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(
            r1.headers.get("cache-control"),
            "public, s-maxage=3600, stale-while-revalidate=7200",
        )
        body = r1.json()
        self.assertEqual(body["last_updated"], "2026-11-22T10:30:00Z")
        self.assertEqual(len(body["products"]), 1)
        self.assertEqual(len(body["comparisons"]), 1)

        # Second call served from 1-hour sitemap_cache
        calls_before = len(fake_db.calls)
        r2 = client.get("/api/seo/sitemap-entries?limit=500")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len(fake_db.calls), calls_before)

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=False)
    def test_alert_checker_job_dry_run_without_secrets(self) -> None:
        triggered_ids: list[int] = []

        def handler(sql: str, params: dict[str, Any]) -> _FakeResult:
            if "CREATE TABLE IF NOT EXISTS" in sql:
                return _FakeResult()
            if "FROM public.price_alerts" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "id": 42,
                            "product_key": "iphone_16",
                            "product_title": "iPhone 16",
                            "store_name": None,
                            "target_price": 46000.0,
                            "channel": "telegram",
                            "destination": "123456789",
                        }
                    ]
                )
            if "FROM gold.mart_product_verdicts" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "product_sk": "sk_ip16",
                            "canonical_product_key": "iphone_16",
                            "product_title": "iPhone 16 128GB",
                            "store_name": "tradeline",
                            "current_price": 44999.0,
                            "product_url": "https://tradelinestores.com/products/iphone-16",
                        }
                    ]
                )
            if "UPDATE public.price_alerts" in sql:
                triggered_ids.append(int(params["alert_id"]))
                return _FakeResult()
            raise AssertionError(f"Unexpected SQL: {sql}")

        conn = _FakeReadDB(handler)
        summary = check_price_alerts.check_alerts_with_conn(conn, dry_run=False)
        self.assertEqual(summary["checked"], 1)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["delivered"], 0)
        self.assertEqual(summary["dry_run_skipped"], 1)
        self.assertEqual(triggered_ids, [])

        # With TELEGRAM_BOT_TOKEN set & mocked HTTP 200 -> delivers & marks triggered_at
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-bot-token"}, clear=False):
            with patch.object(check_price_alerts.httpx, "post", return_value=mock_resp):
                summary_live = check_price_alerts.check_alerts_with_conn(conn, dry_run=False)
        self.assertEqual(summary_live["delivered"], 1)
        self.assertEqual(triggered_ids, [42])

    def test_bilingual_arabic_search_expands_to_english_and_fuzzy_fallback(self) -> None:
        now = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        fridge_row = {
            "product_sk": "sk_fridge_1",
            "canonical_product_key": "samsung_fridge_450l",
            "store_name": "btech",
            "category": "home_appliances",
            "sub_category": "refrigerators",
            "brand": "Samsung",
            "product_title": "Samsung 450L No Frost Refrigerator Silver",
            "product_url": "https://btech.com/en/p/samsung-fridge-450",
            "image_url": "https://cdn.example.com/fridge.jpg",
            "attributes_json": {},
            "current_price": 32500.0,
            "claimed_original_price": 36000.0,
            "rolling_60d_median": 34000.0,
            "min_historical_price": 32500.0,
            "max_historical_price": 36000.0,
            "claimed_discount_pct": 9.7,
            "real_discount_pct": 4.4,
            "discount_verdict": "NORMAL_PRICE",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
        }

        captured_params: list[dict[str, Any]] = []

        def handler(sql: str, params: dict[str, Any]) -> _FakeResult:
            captured_params.append(params)
            self.assertIn("p.search_document", sql)
            return _FakeResult(rows=[{**fridge_row, "search_total": 7}])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        resp = client.get("/api/v1/products/search?q=تلاجة سامسونج")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["match_type"], "text_search")
        self.assertEqual(body["total"], 7)
        self.assertEqual(body["items"][0]["product_sk"], "sk_fridge_1")
        all_param_vals = " ".join(str(v) for p in captured_params for v in p.values())
        self.assertIn("refrigerator", all_param_vals)
        self.assertIn("samsung", all_param_vals)

        # A typo in more than one term falls back to bounded word similarity.
        api_cache.clear()

        def fuzzy_handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "strict_word_similarity(" in sql:
                return _FakeResult(rows=[{**fridge_row, "search_total": 1}])
            return _FakeResult(rows=[])

        fake_db2 = _FakeReadDB(fuzzy_handler)
        app.dependency_overrides[get_db] = lambda: fake_db2
        resp_fuzzy = client.get("/api/v1/products/search?q=samsng refrigrator")
        self.assertEqual(resp_fuzzy.status_code, 200)
        self.assertEqual(resp_fuzzy.json()["match_type"], "fuzzy_trgm")
        self.assertEqual(len(resp_fuzzy.json()["items"]), 1)

    def test_expanded_categories_facets_and_filters(self) -> None:
        now = datetime(2026, 11, 23, 1, 0, 0, tzinfo=timezone.utc)
        pet_row = {
            "product_sk": "sk_pet_1",
            "canonical_product_key": None,
            "store_name": "happet",
            "category": "pet_care",
            "sub_category": "cat_food",
            "brand": "Leonardo",
            "product_title": "Leonardo Fish Cat Dry Food",
            "product_url": "https://happet.net/products/leonardo-fish-cat-dry-food",
            "image_url": "https://happet.net/img.jpg",
            "attributes_json": {},
            "current_price": 130.0,
            "claimed_original_price": None,
            "rolling_60d_median": 130.0,
            "min_historical_price": 130.0,
            "max_historical_price": 130.0,
            "claimed_discount_pct": 0.0,
            "real_discount_pct": 0.0,
            "discount_verdict": "NORMAL_PRICE",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
        }

        def handler(sql: str, params: dict[str, Any]) -> _FakeResult:
            if "FULL OUTER JOIN compare_counts" in sql:
                return _FakeResult(
                    rows=[
                        {"category": "electronics", "product_count": 5000, "compare_count": 320},
                        {"category": "beauty", "product_count": 6200, "compare_count": 0},
                        {"category": "pet_care", "product_count": 480, "compare_count": 12},
                    ]
                )
            if "COUNT(*)" in sql or "COUNT(DISTINCT" in sql:
                return _FakeResult(scalar=1)
            if "FROM gold.mart_cross_store_matches" in sql:
                return _FakeResult(rows=[])
            return _FakeResult(rows=[pet_row])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        # /api/v1/categories returns only >0 categories with AR+EN metadata
        r_cats = client.get("/api/v1/categories")
        self.assertEqual(r_cats.status_code, 200)
        cats_body = r_cats.json()
        self.assertEqual([c["slug"] for c in cats_body["items"]], ["electronics", "beauty", "pet_care"])
        self.assertEqual(cats_body["items"][2]["label_ar"], "مستلزمات الحيوانات")
        self.assertEqual(cats_body["total_products"], 11680)

        # All new canonical categories accepted cleanly across feed, highlights, and compare
        for cat in ("home_furniture", "beauty", "health", "sports", "pet_care", "baby_kids"):
            r_feed = client.get(f"/api/v1/radar/feed?category={cat}&limit=5")
            self.assertEqual(r_feed.status_code, 200, f"feed failed for {cat}")
            r_hi = client.get(f"/api/radar/highlights?category={cat}&limit=5")
            self.assertEqual(r_hi.status_code, 200, f"highlights failed for {cat}")
            r_cmp = client.get(f"/api/v1/compare?category={cat}&limit=5")
            self.assertEqual(r_cmp.status_code, 200, f"compare failed for {cat}")

    def test_multi_variant_feed_dedup_and_product_detail_siblings(self) -> None:
        now = datetime(2026, 11, 23, 2, 0, 0, tzinfo=timezone.utc)
        rug_small = {
            "product_sk": "sk_rug_small",
            "canonical_product_key": None,
            "store_name": "kabbani",
            "category": "home_furniture",
            "sub_category": "rugs",
            "brand": "Kabbani",
            "product_title": "سجادة بوهو — 120x180 سم",
            "product_url": "https://www.kabbanifurniture.com/products/boho-rug?variant=101",
            "image_url": "https://cdn.example.com/rug.jpg",
            "attributes_json": {"parent_product_key": "kabbani::999", "variant_label": "120x180 سم"},
            "current_price": 2400.0,
            "claimed_original_price": 3200.0,
            "rolling_60d_median": 2400.0,
            "min_historical_price": 2400.0,
            "max_historical_price": 2400.0,
            "claimed_discount_pct": 25.0,
            "real_discount_pct": 0.0,
            "discount_verdict": "FAKE_DISCOUNT",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
            "parent_product_key": "kabbani::999",
            "variant_label": "120x180 سم",
            "variant_count": 3,
            "has_multiple_variants": True,
            "min_variant_price": 2400.0,
            "max_variant_price": 7200.0,
        }
        sibling_rows = [
            {
                "product_sk": "sk_rug_small",
                "variant_label": "120x180 سم",
                "title": "سجادة بوهو — 120x180 سم",
                "current_price": 2400.0,
                "claimed_original_price": 3200.0,
                "verdict": "FAKE_DISCOUNT",
                "in_stock": True,
                "product_url": "https://www.kabbanifurniture.com/products/boho-rug?variant=101",
            },
            {
                "product_sk": "sk_rug_med",
                "variant_label": "160x230 سم",
                "title": "سجادة بوهو — 160x230 سم",
                "current_price": 4500.0,
                "claimed_original_price": 6000.0,
                "verdict": "FAKE_DISCOUNT",
                "in_stock": True,
                "product_url": "https://www.kabbanifurniture.com/products/boho-rug?variant=102",
            },
            {
                "product_sk": "sk_rug_lg",
                "variant_label": "200x300 سم",
                "title": "سجادة بوهو — 200x300 سم",
                "current_price": 7200.0,
                "claimed_original_price": 9600.0,
                "verdict": "NORMAL_PRICE",
                "in_stock": False,
                "product_url": "https://www.kabbanifurniture.com/products/boho-rug?variant=103",
            },
        ]

        def handler(sql: str, params: dict[str, Any]) -> _FakeResult:
            if "is_primary_variant = TRUE" in sql or "DISTINCT ON" in sql:
                return _FakeResult(rows=[{**rug_small, "total_count": 1}])
            if "WHERE parent_product_key = :parent_key" in sql:
                self.assertEqual(params["parent_key"], "kabbani::999")
                return _FakeResult(rows=sibling_rows)
            if "FROM gold.fct_price_history" in sql:
                return _FakeResult(rows=[])
            if "WHERE product_sk = :product_sk" in sql:
                return _FakeResult(rows=[rug_small])
            return _FakeResult(rows=[])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        # 1. Feed deduplicates via single-pass `is_primary_variant = TRUE` + COUNT(*) OVER()
        r_feed = client.get("/api/v1/radar/feed?category=home_furniture&limit=10")
        self.assertEqual(r_feed.status_code, 200)
        feed_body = r_feed.json()
        self.assertEqual(feed_body["total"], 1)
        self.assertEqual(len(feed_body["items"]), 1)
        item = feed_body["items"][0]
        self.assertEqual(item["parent_product_key"], "kabbani::999")
        self.assertEqual(item["variant_label"], "120x180 سم")
        self.assertEqual(item["variant_count"], 3)
        self.assertTrue(item["has_multiple_variants"])
        self.assertEqual(item["min_variant_price"], 2400.0)
        self.assertEqual(item["max_variant_price"], 7200.0)
        self.assertEqual(len(fake_db.calls), 1)
        self.assertIn("is_primary_variant = TRUE", fake_db.calls[0])
        self.assertIn("COUNT(*) OVER()", fake_db.calls[0])

        # 2. Detail endpoint returns ordered sibling variants + product rollup fields
        r_det = client.get("/api/v1/products/sk_rug_small")
        self.assertEqual(r_det.status_code, 200)
        det = r_det.json()
        self.assertEqual(det["product"]["variant_count"], 3)
        self.assertEqual(det["product"]["min_variant_price"], 2400.0)
        self.assertEqual(det["product"]["max_variant_price"], 7200.0)
        self.assertEqual(len(det["variants"]), 3)
        self.assertEqual([v["product_sk"] for v in det["variants"]], ["sk_rug_small", "sk_rug_med", "sk_rug_lg"])
        self.assertEqual([v["current_price"] for v in det["variants"]], [2400.0, 4500.0, 7200.0])
        self.assertEqual(det["variants"][1]["variant_label"], "160x230 سم")
        self.assertEqual(det["variants"][2]["in_stock"], False)

    def test_zero_db_health_endpoint_and_health_db(self) -> None:
        fake_db = _FakeReadDB(lambda _sql, _params: _FakeResult(scalar=1))
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        # GET /health must return HTTP 200 "OK" with ZERO SQL queries
        r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "OK")
        self.assertEqual(len(fake_db.calls), 0)

        # GET /health/db runs SELECT 1 and reports DB connectivity
        r_db = client.get("/health/db")
        self.assertEqual(r_db.status_code, 200)
        self.assertEqual(r_db.json(), {"status": "ok", "database": "connected"})
        self.assertEqual(len(fake_db.calls), 1)

    def test_single_variant_product_detail_skips_variants_db_query(self) -> None:
        now = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
        single_row = {
            "product_sk": "sk_single_1",
            "canonical_product_key": "canon_single_1",
            "store_name": "amazon_eg",
            "category": "electronics",
            "sub_category": "smartphones",
            "brand": "Apple",
            "product_title": "Apple iPhone 15 128GB",
            "product_url": "https://www.amazon.eg/-/en/dp/B0CHX1W1XY",
            "image_url": "https://m.media-amazon.com/images/I/test.jpg",
            "attributes_json": {},
            "current_price": 42000.0,
            "claimed_original_price": None,
            "rolling_60d_median": 42000.0,
            "min_historical_price": 42000.0,
            "max_historical_price": 42000.0,
            "claimed_discount_pct": 0.0,
            "real_discount_pct": 0.0,
            "discount_verdict": "NORMAL_PRICE",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
            "parent_product_key": "amazon_eg::B0CHX1W1XY",
            "variant_label": None,
            "variant_count": 1,
            "has_multiple_variants": False,
            "min_variant_price": 42000.0,
            "max_variant_price": 42000.0,
        }

        def handler(sql: str, _params: dict[str, Any]) -> _FakeResult:
            if "WHERE product_sk = :product_sk" in sql and "mart_product_verdicts" in sql:
                return _FakeResult(rows=[single_row])
            if "FROM gold.fct_price_history" in sql:
                return _FakeResult(rows=[])
            if "FROM gold.mart_cross_store_matches" in sql:
                return _FakeResult(
                    rows=[
                        {
                            "listings_json": [
                                {
                                    "product_sk": "sk_single_1",
                                    "store_name": "amazon_eg",
                                    "price": 42000.0,
                                    "in_stock": True,
                                    "product_url": "https://www.amazon.eg/-/en/dp/B0CHX1W1XY",
                                    "discount_verdict": "NORMAL_PRICE",
                                },
                                {
                                    "product_sk": "sk_single_2",
                                    "store_name": "noon",
                                    "price": 43500.0,
                                    "in_stock": True,
                                    "product_url": "https://www.noon.com/egypt-en/n123/p/",
                                    "discount_verdict": "NORMAL_PRICE",
                                },
                            ]
                        }
                    ]
                )
            if "WHERE parent_product_key = :parent_key" in sql:
                raise AssertionError("Should NOT run variants DB query for single-variant products!")
            return _FakeResult(rows=[])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        r = client.get("/api/v1/products/sk_single_1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["variants"]), 1)
        self.assertEqual(body["variants"][0]["product_sk"], "sk_single_1")
        self.assertFalse(any("parent_product_key = :parent_key" in sql for sql in fake_db.calls))

    def test_url_lookup_narrows_by_store_name_for_known_domains(self) -> None:
        captured: list[tuple[str, dict[str, Any]]] = []

        def handler(sql: str, params: dict[str, Any]) -> _FakeResult:
            captured.append((sql, params))
            return _FakeResult(rows=[])

        fake_db = _FakeReadDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        r = client.get("/api/v1/products/search?url=https://www.amazon.eg/-/en/dp/B0DHX98Q3Q?utm_source=fb")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["match_type"], "url_not_found")
        self.assertTrue(len(captured) >= 2)
        self.assertIn("store_name = :inferred_store", captured[0][0])
        self.assertEqual(captured[0][1]["inferred_store"], "amazon_eg")
        self.assertIn("store_name = 'amazon_eg'", captured[1][0])


if __name__ == "__main__":
    unittest.main()
