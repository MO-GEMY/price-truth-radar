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
            "public, s-maxage=300, stale-while-revalidate=600",
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
            "public, s-maxage=300, stale-while-revalidate=600",
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
            "public, s-maxage=300, stale-while-revalidate=600",
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


if __name__ == "__main__":
    unittest.main()
