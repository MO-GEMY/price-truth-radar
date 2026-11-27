"""Unit tests for strict EGP currency guards, Shopify Egypt localization, and ingestion flip circuit breaker."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from data_platform.ingestion.scrapers.adapters.magento_graphql_base import MagentoGraphQLBaseScraper
from data_platform.ingestion.scrapers.adapters.shopify_base import ShopifyBaseScraper
from data_platform.ingestion.scrapers.adapters.woocommerce_base import WooCommerceBaseScraper
from data_platform.ingestion.scrapers.base import (
    PoliteHttpClient,
    RawProductSnapshot,
    compute_product_sk,
)
from data_platform.ingestion.scrapers.currency_guard import (
    detect_store_currency_flips,
    enforce_shopify_egypt_context,
    is_same_store_host,
    is_valid_egp_currency,
    normalize_currency_code,
)
from data_platform.ingestion.scrapers.shopify import TownTeamScraper


class _FakeResp:
    def __init__(self, payload: Any, *, url: str = "") -> None:
        self._payload = payload
        self.url = url
        self.status_code = 200

    def json(self) -> Any:
        return self._payload


class _FakeShopifyMarketsFetcher:
    """Simulates a Shopify Markets storefront reacting to POST /localization + cookies."""

    def __init__(
        self,
        *,
        initial_currency: str = "USD",
        supports_eg_switch: bool = True,
        redirect_url: str | None = None,
        products_egp: list[dict[str, Any]] | None = None,
    ) -> None:
        self.currency = initial_currency
        self.supports_eg_switch = supports_eg_switch
        self.redirect_url = redirect_url
        self.products_egp = products_egp or []
        self.cookies: dict[str, str] = {}
        self.post_calls: list[tuple[str, Any]] = []
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def set_cookies(self, cookies: dict[str, str], *, domain: str | None = None) -> None:
        self.cookies.update(cookies)

    def post(self, url: str, **kwargs: Any) -> _FakeResp:
        self.post_calls.append((url, kwargs.get("data")))
        if self.redirect_url:
            return _FakeResp({}, url=self.redirect_url)
        data = kwargs.get("data") or {}
        if self.supports_eg_switch and data.get("country_code") == "EG":
            self.currency = "EGP"
        return _FakeResp({}, url=url)

    def get(self, url: str, **kwargs: Any) -> _FakeResp:
        params = dict(kwargs.get("params") or {})
        self.get_calls.append((url, params))
        if self.redirect_url:
            return _FakeResp({"currency": self.currency, "products": self.products_egp}, url=self.redirect_url)
        if url.endswith("/cart.js"):
            return _FakeResp({"currency": self.currency}, url=url)
        if params.get("page", 1) == 1:
            return _FakeResp({"products": self.products_egp}, url=url)
        return _FakeResp({"products": []}, url=url)


class _DummyShopify(ShopifyBaseScraper):
    store_name = "shopzhivago"
    base_url = "https://shopzhivago.com"
    category = "fashion"
    supported_verticals = ("fashion",)
    use_impersonation = False


class _DummyWoo(WooCommerceBaseScraper):
    store_name = "dummy_woo"
    base_url = "https://dummy-woo.example.com"
    category = "electronics"
    supported_verticals = ("core",)
    use_impersonation = False


class _DummyMagento(MagentoGraphQLBaseScraper):
    store_name = "dummy_magento"
    base_url = "https://dummy-magento.example.com"
    graphql_url = "https://dummy-magento.example.com/graphql"
    category = "groceries"
    supported_verticals = ("groceries",)
    use_impersonation = False
    search_queries = (("oils", "groceries", "oil"),)


def _make_snap(store: str, ext_id: str, price: str) -> RawProductSnapshot:
    return RawProductSnapshot.model_validate(
        {
            "store_name": store,
            "external_id": ext_id,
            "canonical_product_key": None,
            "category": "fashion",
            "sub_category": "knitwear",
            "brand": "Zhivago",
            "product_title": f"Full-Zip Knit Sweater {ext_id}",
            "product_url": f"https://shopzhivago.com/products/{ext_id}",
            "image_url": None,
            "attributes_json": {},
            "current_price": Decimal(price),
            "claimed_original_price": None,
            "in_stock": True,
            "snapshot_date": date(2026, 11, 24),
            "scraped_at": datetime(2026, 11, 24, 12, 0, 0),
        }
    )


class TestCurrencyHelpersAndShopifyLocalization(unittest.TestCase):
    def setUp(self) -> None:
        self.http = PoliteHttpClient(min_delay_seconds=0.0)

    def tearDown(self) -> None:
        self.http.close()

    def test_currency_normalization_and_host_matching(self) -> None:
        self.assertEqual(normalize_currency_code("egp"), "EGP")
        self.assertEqual(normalize_currency_code("L.E."), "EGP")
        self.assertEqual(normalize_currency_code("ج.م"), "EGP")
        self.assertEqual(normalize_currency_code("$"), "USD")
        self.assertTrue(is_valid_egp_currency("EGP"))
        self.assertFalse(is_valid_egp_currency("USD"))
        self.assertFalse(is_valid_egp_currency("AED"))
        self.assertFalse(is_valid_egp_currency("EUR"))
        self.assertFalse(is_valid_egp_currency(None, allow_missing=False))
        self.assertTrue(is_valid_egp_currency(None, allow_missing=True))

        # www. is ignored, but regional subdomains (eg.okhtein.com vs okhtein.com) MUST mismatch!
        self.assertTrue(is_same_store_host("https://www.shopzhivago.com/products.json", "https://shopzhivago.com"))
        self.assertFalse(is_same_store_host("https://okhtein.com/products.json", "https://eg.okhtein.com"))
        self.assertFalse(is_same_store_host("https://azzafahmy.com/cart.js", "https://eg.azzafahmy.com"))

    def test_shopify_forces_egypt_localization_and_succeeds_when_egp(self) -> None:
        sample_products = [
            {
                "id": 1001,
                "handle": "full-zip-knit-sweater",
                "title": "Full-Zip Knit Sweater",
                "vendor": "Zhivago",
                "product_type": "Sweater",
                "variants": [{"id": 11, "price": "1750.00", "compare_at_price": "2500.00", "available": True}],
                "images": [{"src": "https://cdn.shopify.com/1001.jpg"}],
            }
        ]
        fetcher = _FakeShopifyMarketsFetcher(
            initial_currency="USD",
            supports_eg_switch=True,
            products_egp=sample_products,
        )
        scraper = _DummyShopify(self.http, mode="daily")
        recs = scraper._scrape_with_fetcher(fetcher, target_limit=10)

        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].current_price, Decimal("1750.00"))
        self.assertEqual(fetcher.cookies.get("localization"), "EG")
        self.assertEqual(fetcher.cookies.get("cart_currency"), "EGP")
        self.assertTrue(any(url.endswith("/localization") and data.get("country_code") == "EG" for url, data in fetcher.post_calls))
        prod_calls = [params for url, params in fetcher.get_calls if url.endswith("/products.json")]
        self.assertEqual(len(prod_calls), 1)
        self.assertEqual(prod_calls[0].get("currency"), "EGP")
        self.assertEqual(prod_calls[0].get("country"), "EG")

    def test_shopify_aborts_when_store_refuses_egp_and_returns_usd(self) -> None:
        sample_products = [
            {
                "id": 1001,
                "handle": "full-zip-knit-sweater",
                "title": "Full-Zip Knit Sweater",
                "vendor": "Zhivago",
                "variants": [{"id": 11, "price": "83.00", "available": True}],
            }
        ]
        fetcher = _FakeShopifyMarketsFetcher(
            initial_currency="USD",
            supports_eg_switch=False,
            products_egp=sample_products,
        )
        scraper = _DummyShopify(self.http, mode="daily")
        recs = scraper._scrape_with_fetcher(fetcher, target_limit=10)
        self.assertEqual(recs, [])
        # Must abort BEFORE fetching /products.json
        self.assertFalse(any(url.endswith("/products.json") for url, _ in fetcher.get_calls))

        # Legacy ShopifyScraper (TownTeam/Dejavu/Dalydress) also aborts cleanly on USD
        legacy_scraper = TownTeamScraper(self.http, mode="daily")
        legacy_recs = legacy_scraper._scrape_with_fetcher(fetcher, target_limit=10, is_impersonated=False)
        self.assertEqual(legacy_recs, [])

    def test_shopify_aborts_on_geo_redirect_host_mismatch(self) -> None:
        fetcher = _FakeShopifyMarketsFetcher(
            initial_currency="EGP",
            redirect_url="https://okhtein.com/cart.js",
        )
        res = enforce_shopify_egypt_context(fetcher, "https://eg.okhtein.com", "okhtein")
        self.assertFalse(res.ok)
        self.assertEqual(res.redirected_host, "okhtein.com")
        self.assertIn("GEO_REDIRECT_HOST_MISMATCH", res.reason)


class TestWooCommerceAndMagentoCurrencyGuards(unittest.TestCase):
    def setUp(self) -> None:
        self.http = PoliteHttpClient(min_delay_seconds=0.0)
        self.snap_date = date(2026, 11, 24)
        self.scraped_at = datetime(2026, 11, 24, 12, 0, 0)

    def tearDown(self) -> None:
        self.http.close()

    def test_woocommerce_rejects_non_egp_and_accepts_egp(self) -> None:
        scraper = _DummyWoo(self.http)
        usd_item = {
            "id": 501,
            "name": "Wireless Mouse Pro",
            "permalink": "https://dummy-woo.example.com/product/mouse",
            "prices": {"price": "2500", "regular_price": "3000", "currency_code": "USD", "currency_minor_unit": 2},
            "is_in_stock": True,
        }
        egp_item = {
            **usd_item,
            "prices": {"price": "125000", "regular_price": "150000", "currency_code": "EGP", "currency_minor_unit": 2},
        }
        self.assertEqual(scraper._parse_item_variants(usd_item, self.snap_date, self.scraped_at), [])
        recs = scraper._parse_item_variants(egp_item, self.snap_date, self.scraped_at)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].current_price, Decimal("1250.00"))

        # Full fetch loop aborts entire store if API returns AED
        class _WooUsdFetcher:
            def get(self, url: str, **kwargs: Any) -> _FakeResp:
                return _FakeResp([usd_item], url=url)

        self.assertEqual(scraper._run_fetch(_WooUsdFetcher(), target_limit=10), [])

    def test_magento_graphql_rejects_non_egp_and_accepts_egp(self) -> None:
        scraper = _DummyMagento(self.http)
        usd_item = {
            "name": "Extra Virgin Olive Oil 1L",
            "sku": "OIL-001",
            "url_key": "olive-oil-1l",
            "stock_status": "IN_STOCK",
            "price_range": {
                "minimum_price": {
                    "final_price": {"value": 12.0, "currency": "USD"},
                    "regular_price": {"value": 15.0, "currency": "USD"},
                }
            },
        }
        egp_item = {
            **usd_item,
            "price_range": {
                "minimum_price": {
                    "final_price": {"value": 450.0, "currency": "EGP"},
                    "regular_price": {"value": 520.0, "currency": "EGP"},
                }
            },
        }
        self.assertIsNone(scraper._parse_item(usd_item, "oils", "groceries", self.snap_date, self.scraped_at))
        rec = scraper._parse_item(egp_item, "oils", "groceries", self.snap_date, self.scraped_at)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.current_price, Decimal("450.00"))

        class _MagUsdFetcher:
            def get(self, url: str, **kwargs: Any) -> _FakeResp:
                return _FakeResp({"data": {"products": {"items": [usd_item], "page_info": {"total_pages": 1}}}}, url=url)

        self.assertEqual(scraper._run_queries(_MagUsdFetcher(), target_limit=10), [])


class TestIngestionCurrencyFlipCircuitBreaker(unittest.TestCase):
    def test_quarantines_usd_drop_flip_and_preserves_healthy_store(self) -> None:
        # Reference EGP prices in Neon for shopzhivago (10 SKUs) & healthy_store (10 SKUs)
        refs = {
            "shopzhivago": {compute_product_sk("shopzhivago", f"sku-{i}"): 1750.0 for i in range(10)},
            "healthy_store": {compute_product_sk("healthy_store", f"h-{i}"): 1000.0 for i in range(10)},
        }
        # Incoming batch: shopzhivago flipped to USD (~83 EGP = 0.047x), healthy_store has normal 25% White Friday sale (750 EGP = 0.75x)
        incoming = (
            [_make_snap("shopzhivago", f"sku-{i}", "83.00") for i in range(10)]
            + [_make_snap("healthy_store", f"h-{i}", "750.00") for i in range(10)]
        )

        kept, alerts = detect_store_currency_flips(incoming, refs)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].store_name, "shopzhivago")
        self.assertEqual(alerts[0].reason, "overlap_price_shift")
        self.assertLessEqual(alerts[0].median_ratio, 0.30)
        self.assertEqual({s.store_name for s in kept}, {"healthy_store"})
        self.assertEqual(len(kept), 10)

    def test_quarantines_upward_21x_currency_flip(self) -> None:
        refs = {
            "shopzhivago": {compute_product_sk("shopzhivago", f"sku-{i}"): 83.0 for i in range(8)},
        }
        incoming = [_make_snap("shopzhivago", f"sku-{i}", "1750.00") for i in range(8)]
        kept, alerts = detect_store_currency_flips(incoming, refs)
        self.assertEqual(kept, [])
        self.assertEqual(len(alerts), 1)
        self.assertGreaterEqual(alerts[0].median_ratio, 20.0)

    def test_quarantines_zero_overlap_split_storefront_geo_redirect(self) -> None:
        # Simulates okhtein / azza_fahmy redirecting to global USD storefront with completely different product IDs
        refs = {
            "okhtein": {compute_product_sk("okhtein", f"eg-{i}"): 65000.0 for i in range(25)},
        }
        incoming = [_make_snap("okhtein", f"global-usd-{i}", "400.00") for i in range(25)]
        kept, alerts = detect_store_currency_flips(incoming, refs)
        self.assertEqual(kept, [])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].store_name, "okhtein")
        self.assertEqual(alerts[0].reason, "catalog_median_shift_zero_overlap")

    def test_allows_normal_white_friday_discounts_and_rebounds(self) -> None:
        refs = {
            "hayah_labs": {compute_product_sk("hayah_labs", f"p-{i}"): 200.0 for i in range(10)},
        }
        # 40% sale ending (+66.7% rebound = 1.67x) must NOT trigger currency flip alarm
        incoming = [_make_snap("hayah_labs", f"p-{i}", "333.00") for i in range(10)]
        kept, alerts = detect_store_currency_flips(incoming, refs)
        self.assertEqual(alerts, [])
        self.assertEqual(len(kept), 10)

    def test_geo_redirected_and_cloud_blocked_stores_are_pinned_to_local_only(self) -> None:
        from pathlib import Path
        import yaml
        from data_platform.ingestion.scrapers.registry_loader import load_stores_registry

        entries = {e.store_key: e for e in load_stores_registry(enabled_only=True)}
        for key in ("okhtein", "azza_fahmy", "egyptlaptop", "dubaiphone", "spinneys", "elaraby"):
            self.assertIn(key, entries)
            self.assertEqual(
                entries[key].region_mode,
                "local_only",
                f"{key} blocks or geo-redirects US cloud IPs and must remain local_only",
            )
        # Amazon Egypt is promoted to Priority #1 cloud with 5 parallel department shards
        self.assertEqual(entries["amazon_eg"].region_mode, "cloud")
        self.assertEqual(entries["amazon_eg"].tier, 1)
        self.assertEqual(entries["amazon_eg"].priority_group, "major_brands")

        wf_dir = Path(__file__).resolve().parents[3] / ".github" / "workflows"
        wf_names = sorted(p.name for p in wf_dir.glob("*.yml"))
        self.assertEqual(wf_names, ["check-price-alerts.yml", "daily-stores-matrix.yml"])

        matrix_wf = yaml.safe_load((wf_dir / "daily-stores-matrix.yml").read_text(encoding="utf-8"))
        matrix_on = matrix_wf.get("on") or matrix_wf.get(True)
        matrix_crons = [c["cron"] for c in matrix_on["schedule"]]
        self.assertEqual(matrix_crons, ["37 0 * * 0-5", "37 0 * * 6"])
        load_cmd = " ".join(str(s.get("run", "")) for s in matrix_wf["jobs"]["load-match-dbt"]["steps"])
        self.assertIn("--run-alerts", load_cmd)

        # Price Drop Alert Checker MUST have zero separate schedule (runs inside daily-stores-matrix warm window)
        alerts_wf = yaml.safe_load((wf_dir / "check-price-alerts.yml").read_text(encoding="utf-8"))
        alerts_on = alerts_wf.get("on") or alerts_wf.get(True)
        self.assertNotIn("schedule", alerts_on)


if __name__ == "__main__":
    unittest.main()
