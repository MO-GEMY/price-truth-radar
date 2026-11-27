"""
Config-driven Sllr (`https://sllr.co`) storefront adapter (`SllrBaseScraper`).

Uses plain HTTP (`PoliteHttpClient` / `httpx`) against Sllr's public JSON API:
  1. `GET https://api.sllr.co/business/{slug}` -> resolves `businessId`, verifies
     Egypt country guard (`country.code == "EG"`), and reads store metadata.
  2. `GET https://api.sllr.co/products/v2/popularProducts/{businessId}?page={P}&limit={N}`
     -> paginates through the full catalog, extracting EGP selling price,
     strikethrough original price (`variantOriginalPrice` / `originalPrice`),
     in-stock status, available sizes, images, and canonical `https://sllr.co/{slug}/product/{id}` URLs.
"""

from __future__ import annotations

import logging
import math
import re
from decimal import Decimal
from typing import Any, Optional

from ..base import (
    BaseScraper,
    Category,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

SLLR_API_BASE = "https://api.sllr.co"

_FASHION_SUBCAT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("jerseys", ("jersey", "kit", "تيشيرت نادي", "تيشرت", "طقم")),
    ("knitwear", ("hoodie", "sweatshirt", "pullover", "cardigan", "sweater", "crewneck", "هودي", "سويت")),
    ("jackets", ("jacket", "coat", "tracksuit", "windbreaker", "bomber", "vest", "جاكيت", "ترنج")),
    ("pants", ("pant", "short", "jogger", "trouser", "jean", "denim", "sweatpant", "شورت", "بنطلون")),
    ("polos", ("polo", "بولو")),
    ("tees", ("t-shirt", "tshirt", "tee", "تيشيرت")),
    ("shirts", ("shirt", "قميص")),
    ("footwear", ("shoe", "sneaker", "boot", "sandal", "slipper", "كوتشي", "حذاء")),
    ("accessories", ("cap", "hat", "scarf", "bag", "sock", "keychain", "mug", "poster", "كاب", "شنطة")),
)


def _infer_sllr_sub_category(title: str, cat_name: str, top_category: Category) -> str:
    combined = f"{title} {cat_name}".lower()
    if top_category == "groceries":
        return refine_grocery_sub_category(combined, "pantry")
    if top_category in ("fashion", "sports"):
        for sub, keywords in _FASHION_SUBCAT_RULES:
            if any(kw in combined for kw in keywords):
                return sub
        return "apparel"
    slug = normalize_snake_slug(cat_name, fallback="", max_len=60)
    return slug or top_category


class SllrBaseScraper(BaseScraper):
    """Reusable config-driven scraper for Egyptian Sllr (`sllr.co`) storefronts."""

    store_name: str = ""
    category: Category = "fashion"
    base_url: str = ""
    store_slug: str = ""
    default_brand: str = ""
    override_brand: bool = False
    default_limit: int = 2500
    discover_limit: int = 8000
    groceries_limit: int = 2500
    discover_groceries_limit: int = 8000
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)
    min_delay_seconds: float = 1.0
    request_timeout: float = 20.0
    per_page: int = 50

    def _resolve_slug(self) -> str:
        if self.store_slug:
            return self.store_slug.strip().strip("/")
        cleaned = self.base_url.strip().rstrip("/")
        if "sllr.co/" in cleaned:
            tail = cleaned.split("sllr.co/", 1)[1].split("/", 1)[0]
            if tail:
                return tail.strip()
        return self.store_name

    def _fetch_business_meta(self, slug: str) -> Optional[dict[str, Any]]:
        url = f"{SLLR_API_BASE}/business/{slug}"
        headers = {
            "Accept": "application/json",
            "Origin": "https://sllr.co",
            "Referer": f"https://sllr.co/{slug}/home",
        }
        try:
            resp = self.http.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("[%s] Sllr business API returned HTTP %d", self.store_name, resp.status_code)
                return None
            payload = resp.json()
        except Exception as exc:
            logger.warning("[%s] Failed fetching Sllr business metadata: %s", self.store_name, exc)
            return None

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("_id"):
            logger.warning("[%s] Missing businessId in Sllr business payload", self.store_name)
            return None

        country = data.get("country") if isinstance(data.get("country"), dict) else {}
        country_code = str(country.get("code") or "").strip().upper()
        if country_code and country_code != "EG":
            logger.error(
                "CURRENCY_MISMATCH_ABORT | store=%s | Sllr country.code=%r (expected 'EG')",
                self.store_name,
                country_code,
            )
            return None

        return data

    def _parse_product(
        self,
        item: dict[str, Any],
        slug: str,
        store_display_name: str,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        raw_id = item.get("id")
        if raw_id is None:
            return None
        external_id = str(raw_id).strip()[:120]
        if not external_id:
            return None

        raw_title = str(item.get("name") or item.get("nameAr") or "").strip()
        title = re.sub(r"\s+", " ", raw_title).strip()
        if len(title) < 2:
            return None

        variances = item.get("productsVariances") if isinstance(item.get("productsVariances"), list) else []
        active_variances = [v for v in variances if isinstance(v, dict) and v.get("isActive", True)]

        # Extract selling price & strikethrough original price from active variants or product fields
        price_candidates: list[Decimal] = []
        orig_candidates: list[Decimal] = []
        available_sizes: list[str] = []
        total_sizes: list[str] = []
        any_var_qty_positive = False

        for v in active_variances:
            vp = parse_egp_price(v.get("variantPrice"))
            if vp is not None:
                price_candidates.append(vp)
            vo = parse_egp_price(v.get("variantOriginalPrice"))
            if vo is not None:
                orig_candidates.append(vo)
            vqty = v.get("variantQuantity")
            qty_ok = isinstance(vqty, (int, float)) and vqty > 0
            if qty_ok:
                any_var_qty_positive = True
            opt = str(v.get("optionsString") or "").strip()
            if opt:
                total_sizes.append(opt)
                if qty_ok:
                    available_sizes.append(opt)

        # Also check optionsOrder for total size count when API only returns a subset of variants
        opts_order = item.get("optionsOrder")
        if isinstance(opts_order, dict):
            size_obj = opts_order.get("Size") or opts_order.get("size") or opts_order.get("المقاس")
            if isinstance(size_obj, dict) and isinstance(size_obj.get("values"), list):
                ordered_vals = [str(x).strip() for x in size_obj["values"] if str(x).strip()]
                if len(ordered_vals) > len(total_sizes):
                    total_sizes = ordered_vals

        current_price: Optional[Decimal] = None
        if price_candidates:
            current_price = min(price_candidates)
        else:
            for k in ("minPrice", "defaultPrice", "maxPrice"):
                p = parse_egp_price(item.get(k))
                if p is not None:
                    current_price = p
                    break
        if current_price is None:
            return None

        claimed_original: Optional[Decimal] = None
        if orig_candidates:
            cand = max(orig_candidates)
            if cand > current_price:
                claimed_original = cand
        if claimed_original is None:
            cand = parse_egp_price(item.get("originalPrice"))
            if cand is not None and cand > current_price:
                claimed_original = cand

        is_active = bool(item.get("isActive", True))
        prod_qty = item.get("quantity")
        no_active_var = item.get("noOfActiveVariance")
        in_stock = is_active and (
            any_var_qty_positive
            or (isinstance(prod_qty, (int, float)) and prod_qty > 0)
            or (not active_variances and isinstance(no_active_var, (int, float)) and no_active_var > 0)
        )

        # Image URL
        image_url: Optional[str] = None
        for cand_img in [item.get("defaultImage")] + [v.get("variantDefaultImage") for v in active_variances]:
            if isinstance(cand_img, str) and cand_img.strip().startswith("http"):
                image_url = cand_img.strip()
                break

        cat_obj = item.get("category") if isinstance(item.get("category"), dict) else {}
        cat_name = str(cat_obj.get("categoryName") or cat_obj.get("categoryNameAr") or "").strip()
        sub_category = _infer_sllr_sub_category(title, cat_name, self.category)

        if self.override_brand and self.default_brand:
            brand = self.default_brand
        elif self.category == "groceries":
            brand = extract_grocery_brand(title, self.default_brand or store_display_name)
        else:
            brand = self.default_brand or store_display_name or "Unknown"

        attrs: dict[str, Any] = {}
        if cat_name:
            attrs["sllr_category"] = cat_name[:80]
        if total_sizes:
            attrs["total_sizes"] = len(total_sizes)
            if available_sizes:
                attrs["available_sizes"] = available_sizes
        if self.category == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload=item))

        product_url = f"https://sllr.co/{slug}/product/{external_id}"
        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": self.category,
                "sub_category": sub_category,
                "brand": brand,
                "product_title": title,
                "product_url": product_url,
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        slug = self._resolve_slug()
        biz = self._fetch_business_meta(slug)
        if not biz:
            return []

        business_id = str(biz["_id"]).strip()
        store_display_name = str(biz.get("name") or self.default_brand or self.store_name).strip()
        now = utc_now_naive()
        today = now.date()

        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        headers = {
            "Accept": "application/json",
            "Origin": "https://sllr.co",
            "Referer": f"https://sllr.co/{slug}/home",
        }

        max_pages = max(4, math.ceil(target_limit / max(1, self.per_page)) + 2)
        for page in range(1, max_pages + 1):
            if len(snapshots) >= target_limit:
                break
            url = f"{SLLR_API_BASE}/products/v2/popularProducts/{business_id}"
            try:
                resp = self.http.get(
                    url,
                    params={"page": page, "limit": self.per_page},
                    headers=headers,
                )
                if resp.status_code in (403, 404, 429):
                    logger.warning("[%s] Sllr products API HTTP %d on page %d", self.store_name, resp.status_code, page)
                    break
                payload = resp.json()
            except Exception as exc:
                logger.warning("[%s] Sllr products API failed on page %d: %s", self.store_name, page, exc)
                break

            self.pages_fetched += 1
            data = payload.get("data") if isinstance(payload, dict) else None
            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list) or not products:
                break

            page_new_ids = 0
            for item in products:
                if not isinstance(item, dict):
                    continue
                raw_id = str(item.get("id") or "").strip()
                if not raw_id or raw_id in seen_ids:
                    continue
                seen_ids.add(raw_id)
                page_new_ids += 1
                rec = self._parse_product(item, slug, store_display_name, today, now)
                if rec is not None:
                    snapshots.append(rec)
                    if len(snapshots) >= target_limit:
                        break

            total_count = data.get("productCount") if isinstance(data, dict) else None
            if page_new_ids == 0 or (isinstance(total_count, int) and len(seen_ids) >= total_count):
                break
            if len(products) < self.per_page:
                break

        return snapshots
