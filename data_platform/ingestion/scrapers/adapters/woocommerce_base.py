"""
Config-driven WooCommerce Store API adapter (`WooCommerceBaseScraper`).

Queries public `/wp-json/wc/store/v1/products?per_page={N}&page={P}` endpoints
(plain HTTP or optional `curl_cffi`). Parses EGP minor-unit prices (`currency_minor_unit`),
regular vs sale prices, stock status, images, brand/categories, and routes groceries
through `groceries.py` packaging/EAN normalization.
"""

from __future__ import annotations

import html as html_lib
import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from ..base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    normalize_snake_slug,
    utc_now_naive,
)
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")

_FASHION_SUBCAT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blazers", ("blazer", "suit", "tuxedo")),
    ("jackets", ("jacket", "coat", "parka", "bomber", "vest", "gilet")),
    ("polos", ("polo",)),
    ("shirts", ("shirt", "overshirt")),
    ("t_shirts", ("t-shirt", "tshirt", "tee")),
    ("sweaters", ("sweater", "pullover", "cardigan", "hoodie", "sweatshirt", "knit")),
    ("jeans", ("jeans", "denim")),
    ("pants", ("pant", "trouser", "chino", "jogger", "short", "cargo")),
    ("shoes", ("shoe", "sneaker", "loafer", "boot", "sandal", "moccasin")),
    ("accessories", ("belt", "tie", "scarf", "bag", "wallet", "cap", "hat", "sock", "perfume")),
)

_IGNORED_WC_CATS = frozenset({
    "uncategorized", "all", "new", "new_arrivals", "sale", "en_without_ar", "ar_without_en",
    "featured", "shop", "products", "home", "default", "men", "women", "kids",
})


def _infer_fashion_sub_category(title: str, cat_names: list[str]) -> str:
    low = f"{title} {' '.join(cat_names)}".lower()
    for sub, keywords in _FASHION_SUBCAT_RULES:
        if any(kw in low for kw in keywords):
            return sub
    for cname in cat_names:
        slug = normalize_snake_slug(cname, fallback="", max_len=60)
        if slug and slug not in _IGNORED_WC_CATS and not slug.startswith("en_") and not slug.startswith("ar_"):
            return slug
    return "apparel"


def _parse_wc_minor_price(raw_val: Any, minor_unit: int) -> Optional[Decimal]:
    if raw_val is None:
        return None
    s = str(raw_val).strip()
    if not s or not re.fullmatch(r"\d+", s):
        return None
    val = Decimal(s) / (Decimal(10) ** minor_unit)
    val = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if val <= Decimal("0") or val > Decimal("50000000"):
        return None
    return val


def _extract_wc_paired_prices(item: dict[str, Any]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract (current_price, claimed_original_price) without cross-variant mixing.

    For WooCommerce variable products whose `price_range` spans multiple price tiers
    (`max_amount > min_amount`), WooCommerce's top-level `prices.price` and
    `prices.regular_price` can come from different variations (e.g. smallest pack vs.
    largest pack). In that case, prefer an embedded single-variation price object if
    present; otherwise set `claimed_original_price = None`.
    """
    prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}
    raw_minor = prices.get("currency_minor_unit")
    minor_unit = int(raw_minor) if raw_minor is not None else 2

    # If a Store API response embeds per-variation price dicts, pair strictly from ONE variation
    variations = item.get("variations")
    if isinstance(variations, list):
        priced_vars = [
            v for v in variations
            if isinstance(v, dict) and isinstance(v.get("prices"), dict) and v["prices"].get("price") is not None
        ]
        if priced_vars:
            chosen = next(
                (v for v in priced_vars if v.get("is_in_stock", True) is not False),
                priced_vars[0],
            )
            vp = chosen["prices"]
            v_minor = int(vp["currency_minor_unit"]) if vp.get("currency_minor_unit") is not None else minor_unit
            cur = _parse_wc_minor_price(vp.get("price"), v_minor)
            if cur is None:
                return None, None
            reg = _parse_wc_minor_price(vp.get("regular_price"), v_minor)
            on_sale = chosen.get("on_sale")
            claimed = reg if (reg is not None and reg > cur and on_sale is not False) else None
            return cur, claimed

    current_price = _parse_wc_minor_price(prices.get("price"), minor_unit)
    if current_price is None:
        return None, None

    regular_price = _parse_wc_minor_price(prices.get("regular_price"), minor_unit)
    sale_price = _parse_wc_minor_price(prices.get("sale_price"), minor_unit)

    price_range = prices.get("price_range")
    has_price_range_spread = False
    if isinstance(price_range, dict):
        min_amt = _parse_wc_minor_price(price_range.get("min_amount"), minor_unit)
        max_amt = _parse_wc_minor_price(price_range.get("max_amount"), minor_unit)
        if min_amt is not None and max_amt is not None and max_amt > min_amt:
            has_price_range_spread = True

    item_type = str(item.get("type") or "").strip().lower()
    on_sale = item.get("on_sale")

    # Never mix cross-variant price ranges into a strikethrough discount
    if has_price_range_spread:
        return current_price, None

    if on_sale is False:
        return current_price, None

    if item_type == "variable" and sale_price is not None and sale_price != current_price:
        return current_price, None

    claimed_original = (
        regular_price
        if (regular_price is not None and regular_price > current_price)
        else None
    )
    return current_price, claimed_original


def _infer_wc_sub_category(cat: Category, title: str, cat_names: list[str]) -> str:
    if cat == "groceries":
        return refine_grocery_sub_category(f"{title} {' '.join(cat_names)}", "canned_sauces")
    if cat == "fashion":
        return _infer_fashion_sub_category(title, cat_names)
    low = f"{title} {' '.join(cat_names)}".lower()
    if cat == "pet_care":
        if any(k in low for k in ("litter", "رمل")):
            return "cat_litter"
        if any(k in low for k in ("cat", "kitten", "قطط", "قط")):
            return "cat_food"
        if any(k in low for k in ("dog", "puppy", "كلاب", "كلب")):
            return "dog_food"
        return "pet_supplies"
    if cat == "beauty":
        if any(k in low for k in ("perfume", "parfum", "fragrance", "oud", "عطر")):
            return "perfumes"
        if any(k in low for k in ("hair", "shampoo", "conditioner", "شعر")):
            return "haircare"
        if any(k in low for k in ("makeup", "lipstick", "blush", "mascara")):
            return "makeup"
        return "skincare"
    if cat == "home_furniture":
        if any(k in low for k in ("mattress", "مرتبة", "مرتبه", "سوست")):
            return "mattresses"
        if any(k in low for k in ("pot", "pan", "cookware", "granite", "stainless", "حلة")):
            return "cookware"
        if any(k in low for k in ("sheet", "pillow", "duvet", "linen", "bedding")):
            return "bedding_linens"
        return normalize_snake_slug(cat_names[0], fallback="furniture", max_len=60) if cat_names else "furniture"
    if cat == "health":
        if any(k in low for k in ("protein", "whey", "creatine", "bcaa", "pre-workout")):
            return "sports_nutrition"
        if any(k in low for k in ("vitamin", "omega", "magnesium", "probiotic", "zinc")):
            return "vitamins"
        return "supplements"
    if cat == "baby_kids":
        if any(k in low for k in ("puzzle", "toy", "game", "lego", "doll", "لعبة")):
            return "toys"
        return "kids"
    if cat == "sports":
        return "sports_gear"
    return normalize_snake_slug(cat_names[0], fallback="other", max_len=60) if cat_names else "other"


class WooCommerceBaseScraper(BaseScraper):
    """Config-driven WooCommerce Store API (`/wp-json/wc/store/v1/products`) scraper."""

    store_name: str = ""
    category: Category = "electronics"
    base_url: str = ""
    api_path: str = "/wp-json/wc/store/v1/products"
    default_brand: str = ""
    override_brand: bool = False
    use_impersonation: bool = False
    default_limit: int = 180
    discover_limit: int = 800
    groceries_limit: int = 180
    discover_groceries_limit: int = 750
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds: float = 1.5
    request_timeout: float = 25.0
    per_page: int = 40

    def _parse_item(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        pid = item.get("id")
        permalink = str(item.get("permalink") or "").strip()
        raw_name = html_lib.unescape(str(item.get("name") or ""))
        title = re.sub(r"\s+", " ", raw_name).strip()
        if not pid or not permalink.startswith("http") or len(title) < 3:
            return None

        current_price, claimed_original = _extract_wc_paired_prices(item)
        if current_price is None:
            return None

        image_url: Optional[str] = None
        images = item.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict):
            cand = str(images[0].get("src") or images[0].get("thumbnail") or "").strip()
            if cand.startswith("http"):
                image_url = cand

        cat_names = [
            html_lib.unescape(str(c.get("name") or "")).strip()
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        sku = str(item.get("sku") or "").strip()
        ean: Optional[str] = None
        digits = re.sub(r"\D", "", sku)
        if _EAN_RE.match(digits):
            ean = digits

        raw_brand: Optional[str] = None
        brands_list = item.get("brands")
        if isinstance(brands_list, list) and brands_list and isinstance(brands_list[0], dict):
            raw_brand = html_lib.unescape(str(brands_list[0].get("name") or "")).strip() or None

        cat = self.category
        if cat == "groceries":
            brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, raw_brand or self.default_brand)
        else:
            brand = (self.default_brand if self.override_brand else None) or raw_brand or self.default_brand or (title.split(" ", 1)[0][:100] if title else "Unknown")
        sub_category = _infer_wc_sub_category(cat, title, cat_names)

        attrs: dict[str, Any] = {}
        if cat_names:
            attrs[f"{self.store_name}_category"] = cat_names[0]
        if sku:
            attrs["sku"] = sku
        if ean:
            attrs["ean"] = ean
        if cat == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload={"ean": ean} if ean else None))

        in_stock = bool(item.get("is_in_stock", True))

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": (ean or str(pid))[:120],
                "canonical_product_key": None,
                "category": cat,
                "sub_category": sub_category,
                "brand": brand[:100],
                "product_title": title,
                "product_url": permalink,
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _parse_wp_rest_item(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        """Fallback parser for `/wp-json/wp/v2/product` when Store API is disabled."""
        pid = item.get("id")
        permalink = str(item.get("link") or "").strip()
        title_obj = item.get("title")
        raw_title = title_obj.get("rendered") if isinstance(title_obj, dict) else str(title_obj or "")
        title = re.sub(r"\s+", " ", html_lib.unescape(str(raw_title or ""))).strip()
        if not pid or not permalink.startswith("http") or len(title) < 3:
            return None

        content_obj = item.get("content")
        excerpt_obj = item.get("excerpt")
        text_blob = " ".join(
            [
                str(content_obj.get("rendered") or "") if isinstance(content_obj, dict) else "",
                str(excerpt_obj.get("rendered") or "") if isinstance(excerpt_obj, dict) else "",
            ]
        )
        m = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:EGP|LE|ج\.م)", text_blob, re.I)
        if not m:
            return None
        from ..base import parse_egp_price

        current_price = parse_egp_price(m.group(1))
        if current_price is None:
            return None

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": str(pid)[:120],
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": "apparel" if self.category == "fashion" else "other",
                "brand": self.default_brand or (title.split(" ", 1)[0][:100] if title else "Unknown"),
                "product_title": title,
                "product_url": permalink,
                "image_url": None,
                "attributes_json": {f"{self.store_name}_source": "wp_v2_fallback"},
                "current_price": current_price,
                "claimed_original_price": None,
                "in_stock": True,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _run_fetch(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        endpoint = f"{self.base_url.rstrip('/')}{self.api_path}"
        req_per_page = min(self.per_page, max(10, target_limit))
        max_pages = max(1, math.ceil(target_limit / req_per_page) + 2)
        use_wp_fallback = False

        for page in range(1, max_pages + 1):
            if len(collected) >= target_limit:
                break
            active_endpoint = (
                f"{self.base_url.rstrip('/')}/wp-json/wp/v2/product"
                if use_wp_fallback
                else endpoint
            )
            logger.info("[%s] Fetching WooCommerce API page %d (%s)", self.store_name, page, active_endpoint)
            try:
                if self.use_impersonation:
                    resp = fetcher.get(
                        active_endpoint,
                        params={"per_page": req_per_page, "page": page},
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                        check_throttle=False,
                    )
                else:
                    resp = fetcher.get(
                        active_endpoint,
                        params={"per_page": req_per_page, "page": page},
                        min_delay_seconds=effective_delay,
                        timeout=self.request_timeout,
                    )
                payload = resp.json()
            except ThrottledResponseError as exc:
                logger.warning("[%s] WAF/throttle block on page %d (%s); exiting gracefully.", self.store_name, page, exc)
                break
            except Exception as exc:
                if page == 1 and not use_wp_fallback:
                    logger.info("[%s] Store API unavailable (%s); trying /wp-json/wp/v2/product fallback.", self.store_name, exc)
                    use_wp_fallback = True
                    try:
                        resp = fetcher.get(
                            f"{self.base_url.rstrip('/')}/wp-json/wp/v2/product",
                            params={"per_page": req_per_page, "page": 1},
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                        )
                        payload = resp.json()
                    except Exception as fb_exc:
                        logger.warning("[%s] WooCommerce fallback also failed: %s", self.store_name, fb_exc)
                        break
                else:
                    logger.warning("[%s] WooCommerce error on page %d: %s", self.store_name, page, exc)
                    break

            self.pages_fetched += 1
            if not isinstance(payload, list) or not payload:
                break

            page_records: list[RawProductSnapshot] = []
            for raw in payload:
                if not isinstance(raw, dict):
                    continue
                rec = (
                    self._parse_wp_rest_item(raw, snapshot_date, scraped_at)
                    if use_wp_fallback
                    else self._parse_item(raw, snapshot_date, scraped_at)
                )
                if rec is not None and rec.external_id not in seen_ids:
                    page_records.append(rec)

            page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
            added = 0
            for rec in page_records:
                if rec.external_id in seen_ids:
                    continue
                seen_ids.add(rec.external_id)
                collected.append(rec)
                added += 1
                if len(collected) >= target_limit:
                    break

            if len(payload) < req_per_page or added == 0:
                break

        return collected

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        if self.use_impersonation:
            with ImpersonatedHttpClient(
                impersonate="chrome",
                timeout=self.request_timeout or 25.0,
                max_retries=3,
                backoff_base=2.0,
                min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
                jitter_range=(0.25, 0.8),
            ) as client:
                return self._run_fetch(client, target_limit)

        return self._run_fetch(self.http, target_limit)
