"""Regression unit tests for installment-price exclusion and price-floor sanity guards."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from bs4 import BeautifulSoup
from pydantic import ValidationError

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


if __name__ == "__main__":
    unittest.main()
