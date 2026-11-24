"""Unit tests for Shopify brand-new out-of-stock skipping & pagination guards."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from data_platform.ingestion.scrapers.adapters.shopify_base import ShopifyBaseScraper
from data_platform.ingestion.scrapers.base import PoliteHttpClient
from data_platform.ingestion.scrapers.shopify import TownTeamScraper


class _DummyShopifyBase(ShopifyBaseScraper):
    store_name = "dummy_shopify"
    base_url = "https://dummy-shopify.example.com"
    category = "electronics"
    supported_verticals = ("core",)
    default_brand = "DummyBrand"
    per_page = 2
    use_impersonation = False


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeFetcher:
    def __init__(self, pages: dict[int, list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.requested_pages: list[int] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        page = int((kwargs.get("params") or {}).get("page", 1))
        self.requested_pages.append(page)
        return _FakeResponse({"products": self.pages.get(page, [])})


def _shopify_product(
    pid: int,
    title: str,
    variants: list[dict[str, Any]],
    *,
    handle: str | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "handle": handle or f"item-{pid}",
        "title": title,
        "vendor": "TestBrand",
        "product_type": "Accessories",
        "variants": variants,
        "images": [{"src": f"https://cdn.example.com/{pid}.jpg"}],
    }


class TestShopifyBaseOosSkip(unittest.TestCase):
    def setUp(self) -> None:
        self.http = PoliteHttpClient(min_delay_seconds=0.0)
        self.snap_date = date(2026, 11, 24)
        self.scraped_at = datetime(2026, 11, 24, 10, 0, 0)

    def tearDown(self) -> None:
        self.http.close()

    def test_skips_brand_new_oos_single_variant(self) -> None:
        scraper = _DummyShopifyBase(self.http, tracked_external_ids=set())
        raw = _shopify_product(
            1001,
            "Archived USB-C Cable",
            [{"id": 11, "price": "250.00", "available": False, "title": "Default Title"}],
        )
        recs = scraper._parse_product_variants(raw, "electronics", None, self.snap_date, self.scraped_at)
        self.assertEqual(recs, [])
        self.assertEqual(scraper.skipped_oos_count, 1)

    def test_preserves_already_tracked_oos_single_variant(self) -> None:
        scraper = _DummyShopifyBase(self.http, tracked_external_ids={"1001"})
        raw = _shopify_product(
            1001,
            "Tracked USB-C Cable Now Sold Out",
            [{"id": 11, "price": "250.00", "available": False, "title": "Default Title"}],
        )
        recs = scraper._parse_product_variants(raw, "electronics", None, self.snap_date, self.scraped_at)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].external_id, "1001")
        self.assertFalse(recs[0].in_stock)
        self.assertEqual(scraper.skipped_oos_count, 0)

    def test_multi_variant_skips_new_oos_keeps_in_stock_and_tracked_oos(self) -> None:
        scraper = _DummyShopifyBase(self.http, tracked_external_ids={"2001__v23"})
        raw = _shopify_product(
            2001,
            "Rug Classic Pattern",
            [
                {"id": 21, "price": "1200.00", "available": False, "title": "120x180 cm"},  # brand-new OOS -> skip
                {"id": 22, "price": "2200.00", "available": True, "title": "160x230 cm"},   # in-stock -> keep
                {"id": 23, "price": "3200.00", "available": False, "title": "200x300 cm"},  # tracked OOS -> keep
            ],
        )
        recs = scraper._parse_product_variants(raw, "home_furniture", None, self.snap_date, self.scraped_at)
        ext_ids = {r.external_id: r for r in recs}
        self.assertEqual(set(ext_ids.keys()), {"2001__v22", "2001__v23"})
        self.assertTrue(ext_ids["2001__v22"].in_stock)
        self.assertFalse(ext_ids["2001__v23"].in_stock)
        self.assertEqual(scraper.skipped_oos_count, 1)
        for rec in recs:
            self.assertEqual(rec.attributes_json["variant_count"], 2)
            self.assertEqual(rec.attributes_json["variant_min_price"], 2200.0)
            self.assertEqual(rec.attributes_json["variant_max_price"], 3200.0)
            self.assertGreaterEqual(rec.current_price, Decimal(str(rec.attributes_json["variant_min_price"])))
            self.assertLessEqual(rec.current_price, Decimal(str(rec.attributes_json["variant_max_price"])))

    def test_multi_variant_dedup_prefers_in_stock_over_oos_same_tier(self) -> None:
        scraper = _DummyShopifyBase(self.http, tracked_external_ids=set())
        raw = _shopify_product(
            3001,
            "Perfume Eau de Parfum",
            [
                {"id": 31, "price": "950.00", "available": False, "title": "50ml"},  # OOS comes first
                {"id": 32, "price": "950.00", "available": True, "title": "50ml"},   # in-stock same (price, label)
                {"id": 33, "price": "1600.00", "available": False, "title": "100ml"},
            ],
        )
        recs = scraper._parse_product_variants(raw, "beauty", None, self.snap_date, self.scraped_at)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].external_id, "3001__v32")
        self.assertTrue(recs[0].in_stock)
        # Single surviving variant triggers compact_attributes_json default-stripping
        self.assertNotIn("variant_count", recs[0].attributes_json)
        self.assertNotIn("variant_min_price", recs[0].attributes_json)
        self.assertNotIn("variant_max_price", recs[0].attributes_json)
        self.assertEqual(recs[0].attributes_json.get("variant_label"), "50ml")

    def test_pagination_continues_past_all_oos_page_and_stops_on_duplicate_loop(self) -> None:
        class _TwoPerPageShopify(_DummyShopifyBase):
            per_page = 2

        scraper = _TwoPerPageShopify(self.http, mode="daily", tracked_external_ids=set())
        fetcher = _FakeFetcher(
            {
                1: [
                    _shopify_product(4001, "Old Item 1", [{"id": 1, "price": "100", "available": False}]),
                    _shopify_product(4002, "Old Item 2", [{"id": 2, "price": "100", "available": False}]),
                ],
                2: [
                    _shopify_product(4003, "Live Item 3", [{"id": 3, "price": "500", "available": True}]),
                    _shopify_product(4004, "Live Item 4", [{"id": 4, "price": "600", "available": True}]),
                ],
                3: [],
            }
        )
        recs = scraper._scrape_with_fetcher(fetcher, target_limit=10)
        self.assertEqual([r.external_id for r in recs], ["4003", "4004"])
        self.assertEqual(fetcher.requested_pages, [1, 2, 3])
        self.assertEqual(scraper.skipped_oos_count, 2)


class TestShopifyScraperOosSkip(unittest.TestCase):
    def setUp(self) -> None:
        self.http = PoliteHttpClient(min_delay_seconds=0.0)
        self.snap_date = date(2026, 11, 24)
        self.scraped_at = datetime(2026, 11, 24, 10, 0, 0)

    def tearDown(self) -> None:
        self.http.close()

    def test_skips_brand_new_oos_and_keeps_tracked_oos(self) -> None:
        scraper = TownTeamScraper(self.http, tracked_external_ids={"9002"})
        oos_new = _shopify_product(
            9001,
            "Archived Jacket 2022",
            [{"id": 91, "price": "899.00", "available": False, "option1": "L"}],
        )
        oos_tracked = _shopify_product(
            9002,
            "Tracked Polo Shirt",
            [{"id": 92, "price": "599.00", "available": False, "option1": "M"}],
        )
        self.assertIsNone(scraper._parse_product(oos_new, self.snap_date, self.scraped_at))
        self.assertEqual(scraper.skipped_oos_count, 1)

        rec_tracked = scraper._parse_product(oos_tracked, self.snap_date, self.scraped_at)
        self.assertIsNotNone(rec_tracked)
        assert rec_tracked is not None
        self.assertEqual(rec_tracked.external_id, "9002")
        self.assertFalse(rec_tracked.in_stock)

    def test_pagination_continues_past_all_oos_page(self) -> None:
        class _SmallPageTownTeam(TownTeamScraper):
            per_page = 2
            use_impersonation = False

        scraper = _SmallPageTownTeam(self.http, mode="daily", tracked_external_ids=set())
        fetcher = _FakeFetcher(
            {
                1: [
                    _shopify_product(9101, "Archived Tee 1", [{"id": 1, "price": "300", "available": False}]),
                    _shopify_product(9102, "Archived Tee 2", [{"id": 2, "price": "300", "available": False}]),
                ],
                2: [
                    _shopify_product(9103, "Active Hoodie", [{"id": 3, "price": "950", "available": True}]),
                ],
            }
        )
        recs = scraper._scrape_with_fetcher(fetcher, target_limit=10, is_impersonated=False)
        self.assertEqual([r.external_id for r in recs], ["9103"])
        self.assertEqual(fetcher.requested_pages, [1, 2])
        self.assertEqual(scraper.skipped_oos_count, 2)


if __name__ == "__main__":
    unittest.main()
