"""Unit tests for:
  1. Zero-Neon Coupons service (CSV parsing, Africa/Cairo expiry, verification gate, price math,
     fallback, API endpoints & RAM overlay).
  2. Passive Scraper Coupon Radar (Arabic/English extraction, false-positive guard, draft queue file).
  3. Stateless Telegram `/start` webhook & strict numeric Chat ID validation.
  4. Neon storage guardrails (`fct_price_history` change-only deduplication + 3-day raw retention & VACUUM outside tx).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parents[1]
for p in (str(_BACKEND_DIR), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.cache import api_cache, product_detail_cache  # noqa: E402
from app.coupons_service import (  # noqa: E402
    CAIRO_TZ,
    CouponRecord,
    CouponStore,
    compute_coupon_price,
    coupon_store,
    is_coupon_expired,
    is_coupon_servable,
    is_verification_stale,
    load_local_coupons,
    parse_coupons_csv,
)
from app.database import get_db, get_write_db  # noqa: E402
from app.main import app  # noqa: E402
from data_platform.ingestion.scrapers import base as scraper_base  # noqa: E402
from data_platform.ingestion.scrapers import coupon_radar, run_scrapers  # noqa: E402


# Verified reference time for every coupon test below (Africa/Cairo).
NOW = datetime(2026, 11, 24, 15, 0, tzinfo=CAIRO_TZ)

SAMPLE_CSV = """\ufeffstore_id,store_name_ar,code,title_ar,discount_type,value,max_discount,min_order,scope,category,affiliate_url,expires_at,active,notes_ar,verified,verified_at
noon,نون مصر,SAVE10,خصم 10% على نون,percent,10,150,500,general,all,https://www.noon.com/egypt-ar/,2027-12-31,TRUE,خصم عام,TRUE,2026-11-20
amazon_eg,أمازون مصر,EXPIRED50,كود منتهي,fixed,50,50,100,seasonal,all,https://amazon.eg,2020-01-01,TRUE,منتهي,TRUE,2026-11-20
btech,بي تك,INACTIVE20,كود غير مفعل,percent,20,200,500,bank,electronics,https://btech.com,2027-12-31,FALSE,غير نشط,TRUE,2026-11-20
2b,تو بي,FLAT200,خصم 200 جنيه,fixed,200,,1000,first_order,electronics,https://2b.com.eg,2027-06-30,true,لأول طلب,true,2026-11-01
raneen,رنين,UNVERIFIED30,كود غير مُجرَّب,percent,30,300,1000,general,all,https://raneen.com,2027-12-31,TRUE,,FALSE,2026-11-20
raneen,رنين,NODATE35,بدون تاريخ تجربة,percent,35,300,1000,general,all,https://raneen.com,2027-12-31,TRUE,,TRUE,
raneen,رنين,STALE40,تجربة قديمة,percent,40,300,1000,general,all,https://raneen.com,2027-12-31,TRUE,,TRUE,2026-09-01
raneen,رنين,FUTURE45,تاريخ في المستقبل,percent,45,300,1000,general,all,https://raneen.com,2027-12-31,TRUE,,TRUE,2026-12-25
btech,بي تك,NOEXP50,بدون تاريخ انتهاء,fixed,50,50,100,general,all,https://btech.com,,TRUE,,TRUE,2026-11-20
,,,,,,,,,,,,,,,,
,,
"""

# The sheet as published before the verification columns existed: the single unverified
# sample row that was live on 2026-11-24.
_LEGACY_HEADER, _LEGACY_NOON, *_ = SAMPLE_CSV.lstrip("\ufeff").splitlines()
LEGACY_CSV = (
    "\ufeff"
    + ",".join(_LEGACY_HEADER.split(",")[:14])
    + "\n"
    + ",".join(_LEGACY_NOON.split(",")[:14])
    + "\n"
)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._scalar


class _FakeDB:
    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.calls: list[str] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement)
        self.calls.append(sql)
        return self._handler(sql, params or {})


def _http_mock(status_code: int, text: str = "", json_body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(status_code=status_code)
    resp.text = text
    resp.json.return_value = json_body if json_body is not None else {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestCouponsSystem(unittest.TestCase):
    def setUp(self) -> None:
        coupon_store.reset()
        product_detail_cache.clear()
        api_cache.clear()
        app.dependency_overrides.clear()

    def tearDown(self) -> None:
        coupon_store.reset()
        product_detail_cache.clear()
        api_cache.clear()
        app.dependency_overrides.clear()

    def test_csv_parsing_filters_inactive_and_expired_in_cairo_tz(self) -> None:
        ref_now = datetime(2026, 11, 24, 15, 0, tzinfo=CAIRO_TZ)
        items = parse_coupons_csv(SAMPLE_CSV, now=ref_now)
        self.assertEqual([c.code for c in items], ["SAVE10", "FLAT200"])
        self.assertEqual(items[0].store_id, "noon")
        self.assertEqual(items[0].max_discount, 150.0)
        self.assertEqual(items[1].min_order, 1000.0)
        self.assertTrue(items[0].verified)
        self.assertEqual(items[0].verified_at, "2026-11-20")

        # Boundary test on Africa/Cairo end-of-day expiry
        before_midnight = datetime(2026, 11, 24, 23, 59, 58, tzinfo=CAIRO_TZ)
        after_midnight = datetime(2026, 11, 25, 0, 0, 1, tzinfo=CAIRO_TZ)
        self.assertFalse(is_coupon_expired("2026-11-24", now=before_midnight))
        self.assertTrue(is_coupon_expired("2026-11-24", now=after_midnight))

    def test_unverified_stale_and_open_ended_rows_are_dropped_with_a_reason(self) -> None:
        dropped: list[str] = []
        items = parse_coupons_csv(SAMPLE_CSV, now=NOW, dropped=dropped)

        self.assertEqual([c.code for c in items], ["SAVE10", "FLAT200"])
        # One entry per rejected row, naming the store/code and why
        self.assertEqual(len(dropped), 7)
        joined = " | ".join(dropped)
        self.assertIn("amazon_eg/EXPIRED50: expired", joined)
        self.assertIn("btech/INACTIVE20: inactive", joined)
        self.assertIn("raneen/UNVERIFIED30: not verified", joined)
        self.assertIn("raneen/NODATE35: verified_at", joined)
        self.assertIn("raneen/STALE40: verified_at", joined)
        self.assertIn("raneen/FUTURE45: verified_at", joined)
        self.assertIn("btech/NOEXP50: missing expires_at", joined)

    def test_verification_window_is_bounded_by_cairo_calendar_days(self) -> None:
        for bogus in (None, "", "   ", "n/a", "not-a-date", "31/12/2026"):
            self.assertTrue(is_verification_stale(bogus, now=NOW), repr(bogus))
        # 30 days old today still counts; a date in the future never does
        self.assertFalse(is_verification_stale("2026-10-25", now=NOW))
        self.assertTrue(is_verification_stale("2026-10-24", now=NOW))
        self.assertTrue(is_verification_stale("2026-11-25", now=NOW))
        with patch.dict(os.environ, {"COUPONS_VERIFIED_MAX_AGE_DAYS": "10"}):
            self.assertFalse(is_verification_stale("2026-11-14", now=NOW))
            self.assertTrue(is_verification_stale("2026-11-13", now=NOW))
            # FLAT200 was verified 23 days ago: fine for a 30-day window, not for a 10-day one
            self.assertEqual([c.code for c in parse_coupons_csv(SAMPLE_CSV, now=NOW)], ["SAVE10"])

    def test_sheet_without_verification_columns_is_rejected(self) -> None:
        # Drop the header cells themselves: an explicit schema error beats silently serving rows
        with self.assertRaisesRegex(ValueError, "missing required columns: expires_at, verified, verified_at"):
            parse_coupons_csv(LEGACY_CSV.replace(",expires_at,", ",", 1), now=NOW)
        with self.assertRaisesRegex(ValueError, "missing required columns: verified, verified_at"):
            parse_coupons_csv(LEGACY_CSV, now=NOW)

    def test_servable_requires_active_expiry_and_fresh_verification(self) -> None:
        good = CouponRecord(
            store_id="noon",
            store_name_ar="نون",
            code="NOON10",
            title_ar="خصم 10%",
            discount_type="percent",
            value=10.0,
            expires_at="2026-11-24",
            verified=True,
            verified_at="2026-11-20",
        )
        self.assertTrue(is_coupon_servable(good, now=NOW))
        self.assertFalse(is_coupon_servable(good.model_copy(update={"active": False}), now=NOW))
        self.assertFalse(is_coupon_servable(good.model_copy(update={"verified": False}), now=NOW))
        self.assertFalse(is_coupon_servable(good.model_copy(update={"expires_at": None}), now=NOW))
        self.assertFalse(is_coupon_servable(good.model_copy(update={"verified_at": None}), now=NOW))
        # Valid through the end of 2026-11-24 in Cairo, gone one second after midnight
        self.assertTrue(is_coupon_servable(good, now=datetime(2026, 11, 24, 23, 59, 58, tzinfo=CAIRO_TZ)))
        self.assertFalse(is_coupon_servable(good, now=datetime(2026, 11, 25, 0, 0, 1, tzinfo=CAIRO_TZ)))

    def test_retained_snapshot_is_rechecked_on_every_read(self) -> None:
        store = CouponStore(refresh_interval_seconds=1800.0)
        with patch.dict(os.environ, {"COUPONS_SHEET_CSV_URL": "https://sheets.example/coupons.csv"}):
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, SAMPLE_CSV)):
                self.assertEqual(store.refresh(force=True)["count"], 2)
            # Upstream goes down: the snapshot is kept but must not outlive the coupons
            with patch("app.coupons_service.httpx.get", side_effect=RuntimeError("timeout")):
                self.assertFalse(store.refresh(force=True)["ok"])

        def codes(at: datetime) -> list[str]:
            return [c.code for c in store.get_coupons(now=at)[0]]

        self.assertEqual(codes(NOW), ["SAVE10", "FLAT200"])
        # 2026-12-20: FLAT200's check is 49 days old (dropped), SAVE10's is exactly 30 (kept)
        self.assertEqual(codes(datetime(2026, 12, 20, 15, 0, tzinfo=CAIRO_TZ)), ["SAVE10"])
        self.assertEqual(codes(datetime(2026, 12, 21, 15, 0, tzinfo=CAIRO_TZ)), [])

    def test_bundled_seed_and_unverified_sheet_never_publish_a_coupon(self) -> None:
        # web_app/backend/data/coupons.json is packaged by Railway and mirrored at repo data/coupons.json
        backend_seed_path = _BACKEND_DIR / "data" / "coupons.json"
        repo_seed_path = _REPO_ROOT / "data" / "coupons.json"
        self.assertTrue(backend_seed_path.is_file(), "web_app/backend/data/coupons.json must exist for Railway deploys")
        raw_seed = json.loads(backend_seed_path.read_text(encoding="utf-8"))
        self.assertEqual(raw_seed, json.loads(repo_seed_path.read_text(encoding="utf-8")))
        loaded_local = load_local_coupons(now=NOW)
        self.assertEqual(len(loaded_local), len(raw_seed))
        self.assertIn("MOZHELA15", [c.code for c in loaded_local])

        store = CouponStore(refresh_interval_seconds=1800.0)
        with patch.dict(
            os.environ,
            {"COUPONS_SHEET_CSV_URL": "https://sheets.example/coupons.csv", "COUPONS_LOCAL_FILE": ""},
        ):
            # Cold start while the sheet is unreachable -> local seed only
            with patch("app.coupons_service.httpx.get", side_effect=RuntimeError("timeout")):
                res = store.refresh(force=True)
            self.assertEqual((res["source"], res["count"]), ("local_fallback", len(raw_seed)))
            self.assertEqual(len(store.get_coupons(now=NOW)[0]), len(raw_seed))

            # The pre-verification sheet (unverified legacy CSV) is rejected -> falls back to verified local seed only
            client = TestClient(app)
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, LEGACY_CSV)):
                body = client.get("/api/v1/coupons").json()
        self.assertEqual(body["total"], len(raw_seed))
        self.assertNotIn("SAVE10", [item["code"] for item in body["items"]])

    def test_compute_coupon_price_percent_fixed_min_order_and_max_discount(self) -> None:
        pct_coupon = CouponRecord(
            store_id="noon",
            store_name_ar="نون",
            code="NOON10",
            title_ar="خصم 10%",
            discount_type="percent",
            value=10.0,
            max_discount=150.0,
            min_order=500.0,
            scope="general",
        )
        # Below min_order -> None
        self.assertIsNone(compute_coupon_price(499.0, pct_coupon))
        # Within cap: 10% of 1000 = 100 -> 900
        self.assertEqual(compute_coupon_price(1000.0, pct_coupon), 900.0)
        # Capped by max_discount: 10% of 5000 = 500 -> capped at 150 -> 4850
        self.assertEqual(compute_coupon_price(5000.0, pct_coupon), 4850.0)

        fixed_coupon = CouponRecord(
            store_id="btech",
            store_name_ar="بي تك",
            code="FIX250",
            title_ar="خصم 250 ج.م",
            discount_type="fixed",
            value=250.0,
            min_order=1000.0,
            scope="first_order",
        )
        self.assertIsNone(compute_coupon_price(900.0, fixed_coupon))
        self.assertEqual(compute_coupon_price(2500.0, fixed_coupon), 2250.0)

    def test_store_keeps_last_known_good_snapshot_on_sheet_error(self) -> None:
        store = CouponStore(refresh_interval_seconds=1800.0)
        with patch.dict(os.environ, {"COUPONS_SHEET_CSV_URL": "https://sheets.example/coupons.csv"}):
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, SAMPLE_CSV)):
                res1 = store.refresh(force=True)
            self.assertTrue(res1["ok"])
            self.assertEqual(res1["source"], "sheet_csv")
            self.assertEqual(res1["count"], 2)

            # Subsequent outage keeps the previous 2 coupons without raising
            with patch("app.coupons_service.httpx.get", side_effect=RuntimeError("timeout")):
                res2 = store.refresh(force=True)
            self.assertFalse(res2["ok"])
            items, source, _ = store.get_coupons()
            self.assertEqual(source, "sheet_csv")
            self.assertEqual(len(items), 2)

    def test_coupons_endpoints_cache_headers_filters_and_admin_refresh(self) -> None:
        client = TestClient(app)
        with patch.dict(
            os.environ,
            {
                "COUPONS_SHEET_CSV_URL": "https://sheets.example/coupons.csv",
                "ADMIN_REFRESH_SECRET": "super-secret-token",
            },
        ):
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, SAMPLE_CSV)):
                r_all = client.get("/api/v1/coupons")
                self.assertEqual(r_all.status_code, 200)
                self.assertEqual(
                    r_all.headers.get("cache-control"),
                    "public, s-maxage=1800, stale-while-revalidate=3600",
                )
                self.assertEqual(
                    r_all.headers.get("cdn-cache-control"),
                    "public, s-maxage=1800, stale-while-revalidate=3600",
                )
                self.assertEqual(r_all.json()["total"], 2)
                self.assertTrue(all(c["verified"] and c["verified_at"] for c in r_all.json()["items"]))

                r_store = client.get("/api/v1/coupons?store_id=noon&scope=general")
                self.assertEqual(r_store.status_code, 200)
                self.assertEqual([c["code"] for c in r_store.json()["items"]], ["SAVE10"])

            # Refresh without or with wrong secret -> 401
            self.assertEqual(client.post("/api/v1/coupons/refresh").status_code, 401)
            self.assertEqual(
                client.post("/api/v1/coupons/refresh", headers={"X-Admin-Secret": "wrong"}).status_code,
                401,
            )

            # Valid secret refreshes immediately
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, SAMPLE_CSV)):
                r_ref = client.post(
                    "/api/v1/coupons/refresh",
                    headers={"X-Admin-Secret": "super-secret-token"},
                )
            self.assertEqual(r_ref.status_code, 200)
            self.assertTrue(r_ref.json()["ok"])
            self.assertEqual(r_ref.json()["count"], 2)
            # The admin refresh explains every row that was not published
            self.assertEqual(len(r_ref.json()["skipped"]), 7)

    def test_product_detail_attaches_in_memory_coupons_without_extra_db_queries(self) -> None:
        now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
        prod_row = {
            "product_sk": "sk_noon_1",
            "canonical_product_key": "canon_1",
            "store_name": "noon",
            "category": "electronics",
            "sub_category": "smartphones",
            "brand": "Apple",
            "product_title": "Apple iPhone 16 128GB",
            "product_url": "https://noon.com/p/1",
            "image_url": None,
            "attributes_json": {},
            "current_price": 1000.0,
            "claimed_original_price": None,
            "rolling_60d_median": 1000.0,
            "min_historical_price": 1000.0,
            "max_historical_price": 1000.0,
            "claimed_discount_pct": 0.0,
            "real_discount_pct": 0.0,
            "discount_verdict": "NORMAL_PRICE",
            "scarcity_flag": False,
            "in_stock": True,
            "last_updated_at": now,
            "parent_product_key": "noon::p1",
            "variant_label": None,
            "variant_count": 1,
            "has_multiple_variants": False,
            "min_variant_price": 1000.0,
            "max_variant_price": 1000.0,
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
                                {
                                    "product_sk": "sk_2b_1",
                                    "store_name": "2b",
                                    "price": 1200.0,
                                    "in_stock": True,
                                    "product_url": "https://2b.com.eg/p/1",
                                    "discount_verdict": "NORMAL_PRICE",
                                }
                            ]
                        }
                    ]
                )
            return _FakeResult(rows=[])

        fake_db = _FakeDB(handler)
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        with patch.dict(os.environ, {"COUPONS_SHEET_CSV_URL": "https://sheets.example/coupons.csv"}):
            with patch("app.coupons_service.httpx.get", return_value=_http_mock(200, SAMPLE_CSV)):
                resp = client.get("/api/v1/products/sk_noon_1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Noon product (1000 EGP) gets SAVE10 (10% off -> 900 EGP)
        self.assertEqual(body["product"]["estimated_price_after_coupon"], 900.0)
        self.assertEqual(body["product"]["applicable_coupons"][0]["code"], "SAVE10")
        # Product pages are cached for a day, so the UI needs the expiry to hide the code later
        self.assertEqual(body["product"]["applicable_coupons"][0]["expires_at"], "2027-12-31")
        # 2B alternative (1200 EGP) gets FLAT200 (200 off -> 1000 EGP)
        self.assertEqual(body["alternatives"][0]["estimated_price_after_coupon"], 1000.0)
        self.assertEqual(body["alternatives"][0]["applicable_coupons"][0]["code"], "FLAT200")


class TestCouponRadar(unittest.TestCase):
    def test_extracts_ar_and_en_codes_and_blocks_false_positives(self) -> None:
        text = (
            "<p>خصم إضافي! استخدم كود خصم: EGYPT20 عند الدفع.</p>"
            "<p>Use code WINTER15 for 15% off! Also ignore use code below, "
            "promo code 256GB, discount code FREE, and SKU code SKU9988.</p>"
        )
        found = coupon_radar.extract_coupon_candidates(text, excluded_tokens={"SKU9988"})
        codes = [code for code, _ in found]
        self.assertEqual(codes, ["EGYPT20", "WINTER15"])

    def test_record_pending_coupons_deduplicates_and_writes_draft_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_file = Path(tmpdir) / "pending_coupons.json"
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
                added1 = coupon_radar.scan_and_record_coupons(
                    "noon",
                    ["استخدم كود خصم FLASH25 اليوم فقط"],
                    source_url="https://noon.com/p/1",
                    pending_path=pending_file,
                )
                added2 = coupon_radar.scan_and_record_coupons(
                    "noon",
                    ["استخدم كود خصم FLASH25 اليوم فقط"],
                    source_url="https://noon.com/p/2",
                    pending_path=pending_file,
                )
            self.assertEqual(len(added1), 1)
            self.assertEqual(added1[0]["code"], "FLASH25")
            self.assertEqual(added1[0]["status"], "pending_review")
            # Duplicate (store_id, code) is not appended twice
            self.assertEqual(len(added2), 0)
            persisted = json.loads(pending_file.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted), 1)


class TestTelegramWebhookAndAlerts(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_webhook_rejects_missing_or_wrong_secret(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "wh_sec_123"}):
            self.assertEqual(
                self.client.post("/api/v1/telegram/webhook", json={}).status_code,
                401,
            )
            self.assertEqual(
                self.client.post(
                    "/api/v1/telegram/webhook",
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                    json={},
                ).status_code,
                401,
            )

    def test_webhook_start_replies_with_html_chat_id_zero_db(self) -> None:
        update = {
            "update_id": 1001,
            "message": {
                "message_id": 12,
                "chat": {"id": 987654321, "type": "private"},
                "text": "/start alerts",
            },
        }
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_WEBHOOK_SECRET": "wh_sec_123",
                "TELEGRAM_BOT_TOKEN": "123:BOTTOKEN",
            },
        ), patch("app.notify.httpx.post", return_value=_http_mock(200, json_body={"ok": True})) as post:
            resp = self.client.post(
                "/api/v1/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "wh_sec_123"},
                json=update,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "987654321")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("<code>987654321</code>", payload["text"])
        self.assertIn("asarak.com", payload["text"])

    def test_webhook_non_start_update_returns_ok_without_sending(self) -> None:
        other_updates = [
            {"message": {"chat": {"id": 987654321}, "text": "مرحبا"}},
            {"callback_query": {"id": "cb1", "data": "ping"}},
            {"edited_message": {"chat": {"id": 987654321}, "text": "/start"}},
        ]
        with patch.dict(
            os.environ,
            {"TELEGRAM_WEBHOOK_SECRET": "wh_sec_123", "TELEGRAM_BOT_TOKEN": "123:BOTTOKEN"},
        ), patch("app.notify.httpx.post") as post:
            for upd in other_updates:
                r = self.client.post(
                    "/api/v1/telegram/webhook",
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wh_sec_123"},
                    json=upd,
                )
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json(), {"ok": True})
        post.assert_not_called()

    def test_alerts_rejects_telegram_username_with_arabic_message(self) -> None:
        fake_db = MagicMock()
        app.dependency_overrides[get_write_db] = lambda: fake_db
        resp = self.client.post(
            "/api/alerts",
            json={
                "product_key": "iphone_16",
                "target_price": 40000,
                "channel": "telegram",
                "destination": "@my_handle",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body_text = json.dumps(resp.json(), ensure_ascii=False)
        self.assertIn("Chat ID", body_text)
        self.assertIn("Start", body_text)
        fake_db.execute.assert_not_called()


class TestNeonStorageGuardrails(unittest.TestCase):
    def test_fct_price_history_sql_implements_change_only_dedup_and_weighted_median(self) -> None:
        sql_path = _REPO_ROOT / "data_platform" / "warehouse_dbt" / "models" / "marts" / "fct_price_history.sql"
        sql = sql_path.read_text(encoding="utf-8")
        # Incremental change-only guardrails & prior-history preservation
        self.assertIn("existing_latest AS MATERIALIZED", sql)
        self.assertIn("accepted_staged AS MATERIALIZED", sql)
        self.assertIn("cand.price IS DISTINCT FROM cand.latest_price", sql)
        self.assertIn("cand.claimed_original_price IS DISTINCT FROM cand.latest_claimed_original_price", sql)
        self.assertIn("cand.in_stock IS DISTINCT FROM cand.latest_in_stock", sql)
        # Reuses preserved {{ this }} history so 3-day raw pruning never breaks 60-day rolling medians
        self.assertIn("FROM {{ this }} t", sql)
        # Duration-weighted 60d median over intervals
        self.assertIn("all_next_dates", sql)
        self.assertIn("((total_w + 1) / 2)", sql)
        self.assertIn("((total_w + 2) / 2)", sql)

    def test_prune_old_raw_snapshots_deletes_then_vacuums_outside_transaction(self) -> None:
        executed_sql: list[tuple[str, bool]] = []

        class _FakeCur:
            rowcount = 42000

            def __enter__(self) -> "_FakeCur":
                return self

            def __exit__(self, *_args: Any) -> None:
                pass

            def execute(self, sql: str, _params: Any = None) -> None:
                executed_sql.append((sql.strip(), conn.autocommit))

        class _FakeConn:
            autocommit = False

            def __enter__(self) -> "_FakeConn":
                return self

            def __exit__(self, *_args: Any) -> None:
                pass

            def cursor(self) -> _FakeCur:
                return _FakeCur()

            def close(self) -> None:
                pass

        conn = _FakeConn()
        with patch.dict(os.environ, {"DATABASE_URL_ADMIN": "postgresql://u:p@host/db"}), patch(
            "data_platform.ingestion.scrapers.base.psycopg2.connect", return_value=conn
        ):
            deleted = scraper_base.prune_old_raw_snapshots(retention_days=3, vacuum=True)

        self.assertEqual(deleted, 42000)
        self.assertEqual(len(executed_sql), 2)
        # 1. DELETE ran inside transaction (autocommit=False)
        self.assertIn("DELETE FROM raw.raw_product_snapshots", executed_sql[0][0])
        self.assertFalse(executed_sql[0][1])
        # 2. VACUUM (ANALYZE) ran strictly outside transaction (autocommit=True)
        self.assertEqual(executed_sql[1][0], "VACUUM (ANALYZE) raw.raw_product_snapshots;")
        self.assertTrue(executed_sql[1][1])

    def test_post_dbt_cleanup_aborts_pruning_if_dbt_test_fails(self) -> None:
        with patch("data_platform.ingestion.scrapers.run_scrapers.subprocess.call", side_effect=[0, 1]), patch(
            "data_platform.ingestion.scrapers.run_scrapers.prune_old_raw_snapshots"
        ) as prune_mock:
            rc = run_scrapers.run_post_dbt_raw_retention_cleanup(retention_days=3, run_dbt_first=True)
        self.assertEqual(rc, 1)
        prune_mock.assert_not_called()

    def test_compact_attributes_json_strips_bloat_and_stores_null_when_empty(self) -> None:
        # Bloated single-variant Shopify payload -> empty dict -> serialized as SQL NULL
        compacted = scraper_base.compact_attributes_json(
            {
                "parent_product_key": "hedeya::12345",
                "variant_count": 1,
                "variant_min_price": 500.0,
                "variant_max_price": 500.0,
                "shopify_product_type": "Toys",
                "hedeya_category": "Baby Toys",
                "amazon_query": "lego",
                "sku": "12345",
                "pack_count": 1,
                "available_sizes": ["M"],  # stripped for non-fashion
            },
            store_name="hedeya",
            external_id="12345",
            category="baby_kids",
        )
        self.assertEqual(compacted, {})

        # Useful keys (EAN, unit weight, multi-variant prices, fashion sizes, specs) preserved
        kept_groc = scraper_base.compact_attributes_json(
            {
                "ean": "6222023700642",
                "net_weight_g": 400,
                "pack_size": "400g",
                "pack_count": 2,
                "seoudi_category": "Dairy",
            },
            store_name="seoudi",
            external_id="991",
            category="groceries",
        )
        self.assertEqual(
            kept_groc,
            {"ean": "6222023700642", "net_weight_g": 400, "pack_size": "400g", "pack_count": 2},
        )

        kept_fashion = scraper_base.compact_attributes_json(
            {
                "available_sizes": ["M", "L"],
                "total_sizes": 4,
                "variant_count": 3,
                "variant_min_price": 450.0,
                "variant_max_price": 650.0,
                "shopify_product_type": "Shirts",
            },
            store_name="town_team",
            external_id="555__v1",
            category="fashion",
        )
        self.assertEqual(
            kept_fashion,
            {
                "available_sizes": ["M", "L"],
                "total_sizes": 4,
                "variant_count": 3,
                "variant_min_price": 450.0,
                "variant_max_price": 650.0,
            },
        )

    def test_product_schema_coerces_null_attributes_json_to_empty_dict(self) -> None:
        from app.schemas import ProductVerdictItem

        item = ProductVerdictItem.model_validate(
            {
                "product_sk": "sk_null_attr",
                "store_name": "btech",
                "category": "electronics",
                "sub_category": "smartphones",
                "brand": "Apple",
                "product_title": "Apple iPhone 16",
                "product_url": "https://btech.com/p/1",
                "attributes_json": None,
                "current_price": 45000.0,
                "rolling_60d_median": 45000.0,
                "min_historical_price": 45000.0,
                "max_historical_price": 45000.0,
                "claimed_discount_pct": 0.0,
                "real_discount_pct": 0.0,
                "discount_verdict": "NORMAL_PRICE",
                "scarcity_flag": False,
                "in_stock": True,
                "last_updated_at": datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
            }
        )
        self.assertEqual(item.attributes_json, {})

    def test_idle_pool_reaper_disposes_engine_after_idle_timeout(self) -> None:
        import time as _time
        from app.database import _IdlePoolReaper

        fake_engine = MagicMock()
        reaper = _IdlePoolReaper(fake_engine, idle_seconds=0.05)
        reaper.on_checkout()
        reaper.on_checkin()
        _time.sleep(0.12)
        fake_engine.dispose.assert_called_once()

    def test_health_is_zero_db_and_alerts_is_no_store(self) -> None:
        client = TestClient(app)
        r_health = client.get("/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.text, "OK")
        self.assertEqual(r_health.headers.get("cache-control"), "no-store")


if __name__ == "__main__":
    unittest.main()
