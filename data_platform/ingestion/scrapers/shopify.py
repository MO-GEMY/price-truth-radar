"""
Reusable Shopify `/products.json` scraper foundation + verified live Egyptian
fashion & footwear retailers (`town_team`, `dejavu`, `dalydress`).

Fetches public Shopify storefront `/products.json?limit=100&page={N}` with
polite rate limiting, extracts EGP `price` and `compare_at_price`
(`claimed_original_price` only when strictly `> price`), computes real size
availability (`available_sizes`, `total_sizes`) for fashion `scarcity_flag`,
and validates every record against `raw.raw_product_snapshots`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

_FASHION_SUBCATEGORY_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("sneaker", "trainer", "running shoe", "sport shoe"), "sneakers"),
    (("boot", "loafer", "heel", "sandal", "slipper", "mule", "flat", "shoe", "footwear", "clog", "espadrille", "oxford"), "shoes"),
    (("hoodie", "sweatshirt", "pullover", "fleece"), "hoodies"),
    (("t-shirt", "tshirt", "tee", "crew neck"), "tees"),
    (("polo",), "polos"),
    (("shirt", "blouse", "tunic", "top"), "shirts"),
    (("jean", "denim"), "jeans"),
    (("trouser", "pant", "chino", "jogger", "short", "legging", "sweatpant"), "trousers"),
    (("jacket", "coat", "blazer", "vest", "puffer", "bomber", "cardigan", "sweater", "knit"), "outerwear"),
    (("dress", "jumpsuit", "abaya", "skirt", "kaftan"), "dresses"),
    (("bag", "backpack", "tote", "crossbody", "clutch", "wallet", "handbag", "purse"), "bags"),
    (("scarf", "shawl", "belt", "cap", "hat", "sock", "sunglass", "perfume", "boxer", "underwear"), "accessories"),
]

_SKU_LIKE_VENDOR_RE = re.compile(r"^[A-Z0-9_-]{8,}$")


def _normalize_fashion_subcat(product_type: str, title: str, tags: list[str]) -> str:
    for source in (product_type, title, " ".join(tags)):
        low = source.strip().lower()
        if not low:
            continue
        for keywords, mapped in _FASHION_SUBCATEGORY_KEYWORDS:
            if any(re.search(rf"\b{re.escape(kw)}", low) for kw in keywords):
                return mapped
    if product_type.strip():
        return normalize_snake_slug(product_type, fallback="apparel", max_len=80)
    return "apparel"


def _detect_option_positions(options: list[dict[str, Any]]) -> tuple[Optional[int], Optional[int]]:
    """Return 1-based `(size_pos, color_pos)` from Shopify product `options`."""
    size_pos: Optional[int] = None
    color_pos: Optional[int] = None
    for idx, opt in enumerate(options, start=1):
        if not isinstance(opt, dict):
            continue
        name = str(opt.get("name") or "").strip().lower()
        pos = int(opt.get("position") or idx)
        if any(k in name for k in ("size", "مقاس")):
            size_pos = pos
        elif any(k in name for k in ("color", "colour", "لون")):
            color_pos = pos
    return size_pos, color_pos


class ShopifyScraper(BaseScraper):
    """Reusable scraper for public Shopify `/products.json` storefronts."""

    category: Category = "fashion"
    supported_verticals = ("fashion",)
    default_brand: str = "Unknown"
    override_brand: bool = False
    default_limit: int = 250
    discover_limit: int = 1000
    min_delay_seconds: float = 1.0
    per_page: int = 100

    def _resolve_brand(self, vendor_raw: Optional[str]) -> str:
        if self.override_brand:
            return self.default_brand
        vendor = (vendor_raw or "").strip()
        if not vendor or _SKU_LIKE_VENDOR_RE.match(vendor):
            return self.default_brand
        return vendor[:100]

    def _parse_product(
        self,
        raw: dict[str, Any],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        product_id = raw.get("id")
        handle = str(raw.get("handle") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not product_id or not handle or not title:
            return None

        variants = raw.get("variants")
        if not isinstance(variants, list) or not variants:
            return None

        # Choose representative pricing from available variants first, else all variants
        priced_available: list[tuple[Decimal, Optional[Decimal]]] = []
        priced_all: list[tuple[Decimal, Optional[Decimal]]] = []
        any_available = False

        for v in variants:
            if not isinstance(v, dict):
                continue
            price = parse_egp_price(v.get("price"))
            if price is None:
                continue
            comp = parse_egp_price(v.get("compare_at_price"))
            claimed = comp if (comp is not None and comp > price) else None
            avail = bool(v.get("available"))
            priced_all.append((price, claimed))
            if avail:
                any_available = True
                priced_available.append((price, claimed))

        if not priced_all:
            return None

        chosen_pool = priced_available if priced_available else priced_all
        chosen_pool.sort(key=lambda pair: pair[0])
        current_price, claimed_original_price = chosen_pool[0]

        # Extract real size & color inventory from Shopify options + variants
        options = raw.get("options") if isinstance(raw.get("options"), list) else []
        size_pos, color_pos = _detect_option_positions(options)

        all_sizes: list[str] = []
        avail_sizes: list[str] = []
        colors: list[str] = []
        seen_all_sizes: set[str] = set()
        seen_avail_sizes: set[str] = set()
        seen_colors: set[str] = set()

        for v in variants:
            if not isinstance(v, dict):
                continue
            avail = bool(v.get("available"))
            if size_pos in (1, 2, 3):
                sz = str(v.get(f"option{size_pos}") or "").strip()
                if sz and sz.lower() != "default title":
                    if sz not in seen_all_sizes:
                        seen_all_sizes.add(sz)
                        all_sizes.append(sz)
                    if avail and sz not in seen_avail_sizes:
                        seen_avail_sizes.add(sz)
                        avail_sizes.append(sz)
            if color_pos in (1, 2, 3):
                col = str(v.get(f"option{color_pos}") or "").strip()
                if col and col.lower() != "default title" and col not in seen_colors:
                    seen_colors.add(col)
                    colors.append(col)

        attrs: dict[str, Any] = {}
        if all_sizes:
            attrs["available_sizes"] = avail_sizes
            attrs["total_sizes"] = len(all_sizes)
        else:
            attrs["available_sizes"] = ["One Size"] if any_available else []
            attrs["total_sizes"] = 1

        if colors:
            attrs["colors"] = colors[:8]

        product_type = str(raw.get("product_type") or "").strip()
        if product_type:
            attrs["product_type"] = product_type

        images = raw.get("images")
        image_url: Optional[str] = None
        if isinstance(images, list):
            for img in images:
                if isinstance(img, dict) and img.get("src"):
                    image_url = str(img["src"]).strip()
                    break

        tags_raw = raw.get("tags")
        tags = [str(t).strip() for t in tags_raw] if isinstance(tags_raw, list) else []
        sub_category = _normalize_fashion_subcat(product_type, title, tags)
        brand = self._resolve_brand(str(raw.get("vendor") or ""))

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": str(product_id).strip()[:120],
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": f"{self.base_url.rstrip('/')}/products/{handle}",
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original_price,
                "in_stock": any_available,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()

        endpoint = f"{self.base_url.rstrip('/')}/products.json"
        page = 1
        max_pages = max(1, (target_limit // self.per_page) + 4)

        while len(collected) < target_limit and page <= max_pages:
            logger.info("[%s] Fetching Shopify catalog page %d (%s?limit=%d&page=%d)", self.store_name, page, endpoint, self.per_page, page)
            resp = self.http.get(
                endpoint,
                params={"limit": self.per_page, "page": page},
                min_delay_seconds=self.min_delay_seconds,
                timeout=self.request_timeout,
            )
            self.pages_fetched += 1

            payload = resp.json()
            products = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(products, list) or not products:
                break

            page_records: list[RawProductSnapshot] = []
            for raw in products:
                if not isinstance(raw, dict):
                    continue
                rec = self._parse_product(raw, snapshot_date, scraped_at)
                if rec is not None and rec.external_id not in seen_ids:
                    page_records.append(rec)

            page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)

            added_this_page = 0
            for rec in page_records:
                if rec.external_id in seen_ids:
                    continue
                seen_ids.add(rec.external_id)
                collected.append(rec)
                added_this_page += 1
                if len(collected) >= target_limit:
                    break

            if len(products) < self.per_page or added_this_page == 0:
                break
            page += 1

        return collected


class TownTeamScraper(ShopifyScraper):
    """Town Team Egypt — menswear & casual apparel."""

    store_name = "town_team"
    base_url = "https://townteam.com"
    default_brand = "Town Team"
    override_brand = True  # Shopify vendor field contains internal POS SKU codes
    default_limit = 250


class DejavuScraper(ShopifyScraper):
    """Dejavu Egypt — footwear, sneakers, and bags."""

    store_name = "dejavu"
    base_url = "https://dejavu.shoes"
    default_brand = "Dejavu"
    default_limit = 250


class DalydressScraper(ShopifyScraper):
    """Dalydress Egypt — womenswear, dresses, and accessories."""

    store_name = "dalydress"
    base_url = "https://dalydress.com"
    default_brand = "Dalydress"
    default_limit = 250
