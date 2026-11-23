"""Regression unit tests for installment-price exclusion and price-floor sanity guards."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from bs4 import BeautifulSoup
from pydantic import ValidationError

from data_platform.ingestion.scrapers.adapters import (
    ShopifyBaseScraper,
    WooCommerceBaseScraper,
)
from data_platform.ingestion.scrapers.base import (
    RawProductSnapshot,
    is_installment_text,
    strip_installment_segments,
)
from data_platform.ingestion.scrapers.rayashop import (
    RayaShopScraper,
    _extract_rayashop_card_prices,
)


def _snapshot_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "store_name": "rayashop",
        "external_id": "bosch-cooker-90cm",
        "canonical_product_key": None,
        "category": "home_appliances",
        "sub_category": "cookers",
        "brand": "Bosch",
        "product_title": "BOSCH 90cm 5-Burner Gas Cooker Stainless Steel",
        "product_url": "https://www.rayashop.com/en/bosch-90cm-5-burner-gas-cooker",
        "image_url": "https://prod-fastly.rayashop.com/bosch.jpg",
        "attributes_json": {},
        "current_price": Decimal("28900.00"),
        "claimed_original_price": Decimal("32000.00"),
        "in_stock": True,
        "snapshot_date": date(2026, 11, 22),
        "scraped_at": datetime(2026, 11, 22, 12, 0, 0),
    }
    base.update(overrides)
    return base


class TestInstallmentAndPriceFloorGuards(unittest.TestCase):
    def test_rayashop_plp_card_extracts_cash_price_not_takseety_or_savings(self) -> None:
        html = """
        <article class="ProductCardPlpGrid bg-white">
          <div class="ProductCardPlpGrid__Image">
            <a class="ProductCardPlpGrid__ImageLink" href="/en/bosch-90cm-5-burner-gas-cooker-ss">
              <img class="ProductCardPlpGrid__Thumb" alt="BOSCH 90cm 5-Burner Gas Cooker" src="https://prod-fastly.rayashop.com/bosch.jpg" />
            </a>
          </div>
          <div class="ProductCardPlpGrid__Footer">
            <a href="/en/bosch-90cm-5-burner-gas-cooker-ss">
              <p class="ProductCardPlpGrid__Name">BOSCH 90cm 5-Burner Gas Cooker Stainless Steel</p>
            </a>
            <div class="ProductCardPlpGrid__Price">
              <div>
                <span class="inline-flex currency font-bold">28,900 <span>EGP</span></span>
                <span class="inline-flex currency line-through">33,500 <span>EGP</span></span>
              </div>
              <span class="bg-red-50 text-red-700">- <span class="currency">4,600 <span>EGP</span></span></span>
            </div>
            <div class="ProductCardCustomLabels">
              <span class="ProductCardCustomLabels__text">Takseety 1445 EGP/ 36 mo</span>
              <span class="ProductCardCustomLabels__text">0% Interest 0% DP</span>
            </div>
          </div>
        </article>
        """
        soup = BeautifulSoup(html, "html.parser")
        card = soup.select_one("article.ProductCardPlpGrid")
        assert card is not None

        cash, old = _extract_rayashop_card_prices(card)
        self.assertEqual(cash, Decimal("28900.00"))
        self.assertEqual(old, Decimal("33500.00"))

        scraper = RayaShopScraper(http_client=None)  # type: ignore[arg-type]
        recs = scraper._parse_dom_cards(
            soup,
            "home_appliances",
            "large_appliances",
            date(2026, 11, 22),
            datetime(2026, 11, 22, 12, 0, 0),
        )
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].current_price, Decimal("28900.00"))
        self.assertEqual(recs[0].claimed_original_price, Decimal("33500.00"))
        self.assertEqual(recs[0].sub_category, "cookers")

    def test_installment_text_patterns_excluded_in_fallback(self) -> None:
        for sample in (
            "Takseety 1109 EGP/ 36 mo",
            "1,445 EGP / month with valU",
            "قسط شهرياً 1,445 ج.م",
            "1,445 ج.م في الشهر عبر Aman",
            "Installment via Suhoula 900 EGP/mo",
        ):
            self.assertTrue(is_installment_text(sample), f"Should detect installment: {sample}")

        scrubbed = strip_installment_segments(
            "BOSCH Gas Cooker | 28,900 EGP | - 3,000 EGP | قسط شهري 1,445 EGP مع valU"
        )
        self.assertIn("28,900 EGP", scrubbed)
        self.assertNotIn("1,445", scrubbed)
        self.assertNotIn("3,000", scrubbed)

    def test_rejects_sub_10_egp_non_grocery_but_allows_groceries(self) -> None:
        for cat, price in (
            ("electronics", Decimal("1.00")),
            ("home_appliances", Decimal("5.00")),
            ("fashion", Decimal("9.00")),
        ):
            with self.assertRaises(ValidationError):
                RawProductSnapshot.model_validate(
                    _snapshot_payload(category=cat, sub_category="accessories", current_price=price, claimed_original_price=None)
                )

        # Groceries under 10 EGP remain valid
        groc = RawProductSnapshot.model_validate(
            _snapshot_payload(
                category="groceries",
                sub_category="canned_sauces",
                product_title="Fine Salt Sachet 250g",
                current_price=Decimal("7.50"),
                claimed_original_price=None,
            )
        )
        self.assertEqual(groc.current_price, Decimal("7.50"))

    def test_rejects_low_price_major_appliance_unless_accessory(self) -> None:
        # 1,445 EGP Bosch gas cooker (installment leak) MUST be rejected
        with self.assertRaises(ValidationError):
            RawProductSnapshot.model_validate(
                _snapshot_payload(
                    sub_category="cookers",
                    product_title="BOSCH 90cm 5-Burner Gas Cooker",
                    current_price=Decimal("1445.00"),
                )
            )

        # 1,200 EGP 55-inch Smart TV MUST be rejected
        with self.assertRaises(ValidationError):
            RawProductSnapshot.model_validate(
                _snapshot_payload(
                    sub_category="tvs",
                    product_title="Samsung 55 Inch 4K Smart TV",
                    current_price=Decimal("1200.00"),
                )
            )

        # Legitimate accessories/spare parts under 2,500 EGP MUST pass
        for sub, title, price in (
            ("tvs", "LG Magic Remote Control - Black", Decimal("139.00")),
            ("tvs", "FOX TV Wall Mount 40-80 Inch", Decimal("116.00")),
            ("cookers", "Waterproof Gas Cooker Cover 90cm", Decimal("240.00")),
            ("washing_machines", "Inlet Hose for Automatic Washing Machine", Decimal("185.00")),
            ("air_conditioners", "غطاء تكييف خارجي مقاوم للمياه", Decimal("290.00")),
        ):
            rec = RawProductSnapshot.model_validate(
                _snapshot_payload(
                    sub_category=sub,
                    product_title=title,
                    current_price=price,
                    claimed_original_price=None,
                )
            )
            self.assertEqual(rec.current_price, price)

    def test_shopify_multi_variant_strict_single_variant_pairing(self) -> None:
        scraper = ShopifyBaseScraper(http_client=None)  # type: ignore[arg-type]
        scraper.store_name = "happet"
        scraper.category = "pet_care"
        scraper.base_url = "https://happet.net"

        # 300gm at 130 EGP (compare_at_price: null) + 15kg at 4000 EGP (compare_at_price: 4450)
        # MUST NOT mix 130 EGP with 4450 EGP!
        rec = scraper._parse_product(
            {
                "id": 99001,
                "handle": "leonardo-fish-cat-dry-food",
                "title": "Leonardo Fish Cat Dry Food",
                "vendor": "Leonardo",
                "product_type": "Dry Cat Food",
                "images": [{"src": "https://happet.net/leonardo.jpg"}],
                "variants": [
                    {"id": 1, "title": "300gm", "price": "130.00", "compare_at_price": None, "available": True, "sku": "LEO-300"},
                    {"id": 2, "title": "2kg", "price": "780.00", "compare_at_price": "850.00", "available": True, "sku": "LEO-2K"},
                    {"id": 3, "title": "15kg", "price": "4000.00", "compare_at_price": "4450.00", "available": True, "sku": "LEO-15K"},
                ],
            },
            "pet_care",
            None,
            date(2026, 11, 23),
            datetime(2026, 11, 23, 1, 0, 0),
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.category, "pet_care")
        self.assertEqual(rec.sub_category, "cat_food")
        self.assertEqual(rec.current_price, Decimal("130.00"))
        self.assertIsNone(rec.claimed_original_price)
        self.assertTrue(rec.in_stock)

        # First variant OOS -> picks FIRST IN-STOCK variant (2kg: 780 / 850), NOT 15kg (4450)
        rec_oos_first = scraper._parse_product(
            {
                "id": 99002,
                "handle": "leonardo-fish-cat-dry-food-2",
                "title": "Leonardo Fish Cat Dry Food",
                "vendor": "Leonardo",
                "product_type": "Dry Cat Food",
                "images": [{"src": "https://happet.net/leonardo.jpg"}],
                "variants": [
                    {"id": 1, "title": "300gm", "price": "130.00", "compare_at_price": None, "available": False},
                    {"id": 2, "title": "2kg", "price": "780.00", "compare_at_price": "850.00", "available": True},
                    {"id": 3, "title": "15kg", "price": "4000.00", "compare_at_price": "4450.00", "available": True},
                ],
            },
            "pet_care",
            None,
            date(2026, 11, 23),
            datetime(2026, 11, 23, 1, 0, 0),
        )
        self.assertIsNotNone(rec_oos_first)
        assert rec_oos_first is not None
        self.assertEqual(rec_oos_first.current_price, Decimal("780.00"))
        self.assertEqual(rec_oos_first.claimed_original_price, Decimal("850.00"))
        self.assertTrue(rec_oos_first.in_stock)

        # All variants OOS -> falls back to first valid variant, paired strictly with its own compare_at_price
        rec_all_oos = scraper._parse_product(
            {
                "id": 99003,
                "handle": "leonardo-all-oos",
                "title": "Leonardo Cat Food",
                "vendor": "Leonardo",
                "product_type": "Cat Food",
                "images": [{"src": "https://happet.net/leonardo.jpg"}],
                "variants": [
                    {"id": 1, "title": "300gm", "price": "130.00", "compare_at_price": "120.00", "available": False},
                    {"id": 2, "title": "15kg", "price": "4000.00", "compare_at_price": "4450.00", "available": False},
                ],
            },
            "pet_care",
            None,
            date(2026, 11, 23),
            datetime(2026, 11, 23, 1, 0, 0),
        )
        self.assertIsNotNone(rec_all_oos)
        assert rec_all_oos is not None
        self.assertEqual(rec_all_oos.current_price, Decimal("130.00"))
        self.assertIsNone(rec_all_oos.claimed_original_price)
        self.assertFalse(rec_all_oos.in_stock)

    def test_woocommerce_variable_price_range_does_not_mix_variants(self) -> None:
        wc = WooCommerceBaseScraper(http_client=None)  # type: ignore[arg-type]
        wc.store_name = "egysupps"
        wc.category = "health"
        wc.base_url = "https://egysupps.com"

        # Variable product spanning 130 EGP .. 4450 EGP MUST NOT emit claimed_original_price=4450
        rec_spread = wc._parse_item(
            {
                "id": 5001,
                "type": "variable",
                "name": "Whey Protein Gold Standard",
                "permalink": "https://egysupps.com/product/whey-gold",
                "on_sale": True,
                "prices": {
                    "price": "13000",
                    "regular_price": "445000",
                    "sale_price": "13000",
                    "currency_minor_unit": 2,
                    "price_range": {"min_amount": "13000", "max_amount": "445000"},
                },
                "images": [{"src": "https://egysupps.com/whey.jpg"}],
                "categories": [{"name": "Protein"}],
                "is_in_stock": True,
            },
            date(2026, 11, 23),
            datetime(2026, 11, 23, 1, 0, 0),
        )
        self.assertIsNotNone(rec_spread)
        assert rec_spread is not None
        self.assertEqual(rec_spread.category, "health")
        self.assertEqual(rec_spread.current_price, Decimal("130.00"))
        self.assertIsNone(rec_spread.claimed_original_price)

        # Uniform-price variable product (e.g. sizes S/M/L all on sale 500 -> 650) keeps valid discount
        rec_uniform = wc._parse_item(
            {
                "id": 5002,
                "type": "variable",
                "name": "Multivitamin Pack",
                "permalink": "https://egysupps.com/product/multi",
                "on_sale": True,
                "prices": {
                    "price": "50000",
                    "regular_price": "65000",
                    "sale_price": "50000",
                    "currency_minor_unit": 2,
                    "price_range": {"min_amount": "50000", "max_amount": "50000"},
                },
                "images": [{"src": "https://egysupps.com/multi.jpg"}],
                "categories": [{"name": "Vitamins"}],
                "is_in_stock": True,
            },
            date(2026, 11, 23),
            datetime(2026, 11, 23, 1, 0, 0),
        )
        self.assertIsNotNone(rec_uniform)
        assert rec_uniform is not None
        self.assertEqual(rec_uniform.current_price, Decimal("500.00"))
        self.assertEqual(rec_uniform.claimed_original_price, Decimal("650.00"))

    def test_shopify_multi_size_rug_emits_distinct_variant_snapshots_with_metadata(self) -> None:
        scraper = ShopifyBaseScraper(http_client=None)  # type: ignore[arg-type]
        scraper.store_name = "kabbani"
        scraper.category = "home_furniture"
        scraper.base_url = "https://www.kabbanifurniture.com"

        recs = scraper._parse_product_variants(
            {
                "id": 10887656898854,
                "handle": "boho-rug",
                "title": "سجادة بوهو",
                "vendor": "Kabbani Furniture",
                "product_type": "Rugs",
                "images": [{"src": "https://www.kabbanifurniture.com/boho.jpg"}],
                "variants": [
                    {"id": 101, "title": "120x180 cm", "price": "1380.00", "compare_at_price": "1980.00", "available": True, "sku": "RUG-120"},
                    {"id": 102, "title": "160x230 cm", "price": "2300.00", "compare_at_price": "3300.00", "available": True, "sku": "RUG-160"},
                    {"id": 103, "title": "200x300 cm", "price": "3450.00", "compare_at_price": "4950.00", "available": False, "sku": "RUG-200"},
                ],
            },
            "home_furniture",
            None,
            date(2026, 11, 23),
            datetime(2026, 11, 23, 3, 0, 0),
        )
        self.assertEqual(len(recs), 3)
        self.assertEqual(
            [r.external_id for r in recs],
            ["10887656898854__v101", "10887656898854__v102", "10887656898854__v103"],
        )
        self.assertEqual([r.current_price for r in recs], [Decimal("1380.00"), Decimal("2300.00"), Decimal("3450.00")])
        self.assertEqual([r.claimed_original_price for r in recs], [Decimal("1980.00"), Decimal("3300.00"), Decimal("4950.00")])
        self.assertEqual([r.in_stock for r in recs], [True, True, False])
        self.assertIn("?variant=102", recs[1].product_url)
        self.assertIn("160x230 cm", recs[1].product_title)

        for r, vid, lbl in zip(recs, ("101", "102", "103"), ("120x180 cm", "160x230 cm", "200x300 cm")):
            attrs = r.attributes_json
            self.assertEqual(attrs["parent_product_key"], "kabbani::10887656898854")
            self.assertEqual(attrs["variant_id"], vid)
            self.assertEqual(attrs["variant_label"], lbl)
            self.assertEqual(attrs["variant_count"], 3)
            self.assertEqual(attrs["variant_min_price"], 1380.0)
            self.assertEqual(attrs["variant_max_price"], 3450.0)

    def test_shopify_uniform_price_apparel_preserves_single_record_with_variant_rollup(self) -> None:
        scraper = ShopifyBaseScraper(http_client=None)  # type: ignore[arg-type]
        scraper.store_name = "town_team"
        scraper.category = "fashion"
        scraper.base_url = "https://townteam.com"

        recs = scraper._parse_product_variants(
            {
                "id": 777001,
                "handle": "basic-hoodie",
                "title": "Basic Cotton Hoodie",
                "vendor": "Town Team",
                "product_type": "Hoodies",
                "options": [{"name": "Size"}],
                "images": [{"src": "https://townteam.com/hoodie.jpg"}],
                "variants": [
                    {"id": 1, "title": "M", "option1": "M", "price": "999.00", "compare_at_price": "1299.00", "available": True},
                    {"id": 2, "title": "L", "option1": "L", "price": "999.00", "compare_at_price": "1299.00", "available": True},
                    {"id": 3, "title": "XL", "option1": "XL", "price": "999.00", "compare_at_price": "1299.00", "available": False},
                ],
            },
            "fashion",
            None,
            date(2026, 11, 23),
            datetime(2026, 11, 23, 3, 0, 0),
        )
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r.external_id, "777001")
        self.assertEqual(r.attributes_json["parent_product_key"], "town_team::777001")
        self.assertEqual(r.attributes_json["variant_count"], 3)
        self.assertEqual(r.attributes_json["variant_min_price"], 999.0)
        self.assertEqual(r.attributes_json["variant_max_price"], 999.0)
        self.assertEqual(r.attributes_json["available_sizes"], ["M", "L"])
        self.assertEqual(r.attributes_json["total_sizes"], 3)

    def test_woocommerce_variable_mattress_emits_variant_metadata_and_external_id(self) -> None:
        wc = WooCommerceBaseScraper(http_client=None)  # type: ignore[arg-type]
        wc.store_name = "habitat_eg"
        wc.category = "home_furniture"
        wc.base_url = "https://habitategy.com"

        recs = wc._parse_item_variants(
            {
                "id": 32439,
                "type": "variable",
                "name": "مرتبة قطن بلس أرتفاع 25 سم",
                "permalink": "https://habitategy.com/product/cotton-plus",
                "on_sale": False,
                "prices": {
                    "price": "584300",
                    "regular_price": "584300",
                    "sale_price": "584300",
                    "currency_minor_unit": 2,
                    "price_range": {"min_amount": "584300", "max_amount": "1193200"},
                },
                "variations": [
                    {"id": 32440, "attributes": [{"name": "Length", "value": "190"}, {"name": "Width", "value": "90"}]},
                    {"id": 32441, "attributes": [{"name": "Length", "value": "200"}, {"name": "Width", "value": "180"}]},
                ],
                "images": [{"src": "https://habitategy.com/mattress.jpg"}],
                "categories": [{"name": "Mattresses"}],
                "is_in_stock": True,
            },
            date(2026, 11, 23),
            datetime(2026, 11, 23, 3, 0, 0),
        )
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r.external_id, "32439__v32440")
        self.assertEqual(r.current_price, Decimal("5843.00"))
        self.assertIsNone(r.claimed_original_price)
        self.assertEqual(r.attributes_json["parent_product_key"], "habitat_eg::32439")
        self.assertEqual(r.attributes_json["variant_id"], "32440")
        self.assertEqual(r.attributes_json["variant_label"], "190x90")
        self.assertEqual(r.attributes_json["variant_count"], 2)
        self.assertEqual(r.attributes_json["variant_min_price"], 5843.0)
        self.assertEqual(r.attributes_json["variant_max_price"], 11932.0)


if __name__ == "__main__":
    unittest.main()
