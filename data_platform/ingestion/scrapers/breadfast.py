"""
Hybrid offline ingestion adapter for Breadfast Egypt (`breadfast`, `region_mode: local_only`).

Breadfast operates as an app-only quick-commerce platform with no public web storefront.
This adapter supports two sanctioned ingestion modes (0 CU during scraping):

1. Direct Mobile/Partner API Mode (optional `.env` config):
   - `BREADFAST_API_BASE`           : Authorized JSON API base URL (e.g. `https://...`)
   - `BREADFAST_AUTH_TOKEN`         : Optional Bearer token
   - `BREADFAST_ZONE_ID`            : Optional Cairo zone/branch ID
   - `BREADFAST_LAT` / `BREADFAST_LNG`: Deterministic Cairo coordinates (default `30.0561`, `31.3301` — Nasr City)
   - `BREADFAST_PRODUCT_URL_TEMPLATE`: Non-404 landing/app URL template (default `https://www.breadfast.com/?asarak_item={sku}`)

2. Captured Mobile Dump / HAR Ingestion Mode (automatic):
   - Scans `data/manual_feeds/breadfast/` (or `BREADFAST_FEED_DIR`) for `.har`, `.json`, and `.jsonl` files
     exported from an authorized device/emulator session (e.g. HTTP Toolkit / mitmproxy).
   - Normalizes every product into `RawProductSnapshot` records compatible with
     `silver.stg_products`, `gold.fct_price_history`, and `gold.mart_product_verdicts`.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import quote

from .base import (
    BaseScraper,
    Category,
    REPO_ROOT,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from .currency_guard import is_valid_egp_currency
from .groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

DEFAULT_CAIRO_LAT = 30.0561
DEFAULT_CAIRO_LNG = 31.3301
DEFAULT_BREADFAST_FEED_DIR = REPO_ROOT / "data" / "manual_feeds" / "breadfast"
DEFAULT_BREADFAST_URL_TEMPLATE = "https://www.breadfast.com/?asarak_item={sku}"

_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")

_DEPT_TO_CATEGORY: tuple[tuple[tuple[str, ...], Category, str], ...] = (
    (("pet", "cat ", "dog ", "litter", "whiskas", "royal canin", "purina", "حيوان", "قطط", "كلاب"), "pet_care", "pet_food"),
    (("baby", "diaper", "pampers", "molfix", "infant", "formula", "kids", "toy", "أطفال", "حفاض", "رضع"), "baby_kids", "baby_care"),
    (("pharmacy", "medicine", "vitamin", "supplement", "protein", "health", "medical", "thermometer", "صيدل", "فيتامين", "دواء"), "health", "vitamins"),
    (("skincare", "makeup", "perfume", "fragrance", "cosmetic", "beauty", "serum", "sunscreen", "عطور", "مكياج", "بشرة"), "beauty", "skincare"),
    (("appliance", "kettle", "blender", "toaster", "coffee maker", "espresso machine", "microwave", "vacuum", "أجهزة"), "home_appliances", "kitchen_appliances"),
    (("cookware", "kitchenware", "home decor", "bedding", "pillow", "towel", "storage", "أدوات منزلية"), "home_furniture", "cookware"),
)


def map_retail_department_to_category(
    title: str,
    department_text: str = "",
) -> tuple[Category, str]:
    """Map Breadfast / quick-commerce department & title onto canonical Asarak category & sub_category."""
    combined = f" {department_text} {title} ".lower()
    for keywords, cat, default_sub in _DEPT_TO_CATEGORY:
        if any(kw in combined for kw in keywords):
            return cat, default_sub
    sub = refine_grocery_sub_category(combined, "pantry")
    return "groceries", sub


def iter_json_payloads_from_feed_dir(feed_dir: Path) -> Iterator[tuple[str, Any]]:
    """Yield `(source_name, parsed_json)` from all `.json`, `.jsonl`, and `.har` files in `feed_dir`."""
    if not feed_dir.exists() or not feed_dir.is_dir():
        return

    for fp in sorted(feed_dir.iterdir()):
        if not fp.is_file():
            continue
        suffix = fp.suffix.lower()
        if suffix not in (".json", ".jsonl", ".har"):
            continue

        try:
            raw_text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Failed reading feed file %s: %s", fp, exc)
            continue

        if suffix == ".jsonl":
            for line_no, line in enumerate(raw_text.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield f"{fp.name}:{line_no}", json.loads(line)
                except json.JSONDecodeError:
                    continue
            continue

        try:
            doc = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in %s: %s", fp, exc)
            continue

        if suffix == ".har" and isinstance(doc, dict) and isinstance(doc.get("log"), dict):
            entries = doc["log"].get("entries") or []
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                resp = entry.get("response")
                if not isinstance(resp, dict):
                    continue
                content = resp.get("content")
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if not text or not isinstance(text, str):
                    continue
                if content.get("encoding") == "base64":
                    try:
                        text = base64.b64decode(text).decode("utf-8", errors="replace")
                    except Exception:
                        continue
                stripped = text.lstrip()
                if not stripped.startswith(("{", "[")):
                    continue
                try:
                    yield f"{fp.name}#entry{idx}", json.loads(stripped)
                except json.JSONDecodeError:
                    continue
        else:
            yield fp.name, doc


def extract_product_dicts(payload: Any, *, _depth: int = 0) -> list[dict[str, Any]]:
    """Recursively locate product-like dicts inside arbitrary mobile API / HAR JSON payloads."""
    if _depth > 8 or payload is None:
        return []

    found: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            found.extend(extract_product_dicts(item, _depth=_depth + 1))
        return found

    if not isinstance(payload, dict):
        return []

    # Heuristic: a product dict has a title/name AND a price field AND an id/sku/code
    has_title = any(
        isinstance(payload.get(k), str) and len(str(payload.get(k)).strip()) >= 2
        for k in ("name", "title", "product_name", "productName", "name_en", "en_name")
    )
    has_price = any(
        payload.get(k) is not None
        for k in ("price", "sale_price", "salePrice", "current_price", "final_price", "selling_price", "regular_price", "prices")
    )
    has_id = any(
        payload.get(k) is not None
        for k in ("id", "sku", "product_id", "productId", "external_id", "code", "barcode", "item_id", "itemId")
    )
    if has_title and has_price and has_id:
        found.append(payload)
        return found

    # Recurse into likely container keys
    for key in (
        "products",
        "items",
        "results",
        "data",
        "catalog",
        "categories",
        "sections",
        "subcategories",
        "departments",
        "menu",
        "hits",
        "records",
        "list",
        "edges",
        "node",
        "payload",
        "response",
    ):
        val = payload.get(key)
        if isinstance(val, (dict, list)):
            found.extend(extract_product_dicts(val, _depth=_depth + 1))
    return found


def _first_non_empty(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        val = item.get(k)
        if val is not None and str(val).strip() != "":
            return val
    return None


def _extract_image_url(item: dict[str, Any]) -> Optional[str]:
    for key in ("image_url", "imageUrl", "image", "thumbnail", "photo", "main_image", "img"):
        val = item.get(key)
        if isinstance(val, str) and val.strip().startswith("http"):
            return val.strip()
        if isinstance(val, dict):
            for sub in ("url", "src", "large", "medium", "original"):
                sv = val.get(sub)
                if isinstance(sv, str) and sv.strip().startswith("http"):
                    return sv.strip()
    imgs = item.get("images")
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, str) and first.strip().startswith("http"):
            return first.strip()
        if isinstance(first, dict):
            for sub in ("url", "src", "large", "original"):
                sv = first.get(sub)
                if isinstance(sv, str) and sv.strip().startswith("http"):
                    return sv.strip()
    return None


def _extract_in_stock(item: dict[str, Any]) -> bool:
    for key in ("in_stock", "inStock", "is_available", "isAvailable", "available", "is_in_stock"):
        val = item.get(key)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val > 0
        if isinstance(val, str):
            low = val.strip().lower()
            if low in ("true", "1", "yes", "in_stock", "available"):
                return True
            if low in ("false", "0", "no", "out_of_stock", "unavailable", "sold_out"):
                return False
    qty = _first_non_empty(item, ("stock_quantity", "stockQuantity", "quantity", "stock", "inventory"))
    if isinstance(qty, (int, float)):
        return qty > 0
    status = str(item.get("stock_status") or item.get("status") or "").strip().upper()
    if status in ("OUT_OF_STOCK", "UNAVAILABLE", "SOLD_OUT"):
        return False
    return True


def _extract_prices(item: dict[str, Any]) -> tuple[Any, Any, Optional[str]]:
    """Return `(current_raw, original_raw, currency_code)` from common mobile/e-commerce JSON shapes."""
    currency = _first_non_empty(item, ("currency", "currency_code", "currencyCode"))
    prices_obj = item.get("prices")
    if isinstance(prices_obj, dict):
        currency = currency or _first_non_empty(prices_obj, ("currency", "currency_code", "currencyCode"))
        cur = _first_non_empty(prices_obj, ("sale_price", "salePrice", "final_price", "price", "current"))
        orig = _first_non_empty(prices_obj, ("regular_price", "regularPrice", "original_price", "old_price", "compare_at_price"))
        return cur, orig, str(currency) if currency else None

    cur = _first_non_empty(
        item,
        ("sale_price", "salePrice", "final_price", "finalPrice", "current_price", "currentPrice", "selling_price", "price"),
    )
    orig = _first_non_empty(
        item,
        ("original_price", "originalPrice", "regular_price", "regularPrice", "old_price", "oldPrice", "compare_at_price", "list_price", "price"),
    )
    if orig == cur:
        orig = None
    return cur, orig, str(currency) if currency else None


class BreadfastScraper(BaseScraper):
    """Hybrid Mobile-API & HAR/JSON Feed adapter for Breadfast Egypt (`local_only`)."""

    store_name = "breadfast"
    category: Category = "groceries"
    base_url = "https://www.breadfast.com"
    default_limit = 5000
    discover_limit = 15000
    groceries_limit = 5000
    discover_groceries_limit = 15000
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries", "core")
    min_delay_seconds = 1.0
    request_timeout = 20.0

    def __init__(
        self,
        *args: Any,
        feed_dir: Optional[Path] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        env_dir = (os.getenv("BREADFAST_FEED_DIR") or "").strip()
        self.feed_dir = feed_dir or (Path(env_dir) if env_dir else DEFAULT_BREADFAST_FEED_DIR)
        self.api_base = (os.getenv("BREADFAST_API_BASE") or "").strip().rstrip("/")
        self.auth_token = (os.getenv("BREADFAST_AUTH_TOKEN") or "").strip()
        self.zone_id = (os.getenv("BREADFAST_ZONE_ID") or "").strip()
        self.cairo_lat = float(os.getenv("BREADFAST_LAT") or DEFAULT_CAIRO_LAT)
        self.cairo_lng = float(os.getenv("BREADFAST_LNG") or DEFAULT_CAIRO_LNG)
        self.product_url_template = (
            os.getenv("BREADFAST_PRODUCT_URL_TEMPLATE") or DEFAULT_BREADFAST_URL_TEMPLATE
        ).strip()

    def _build_product_url(self, sku: str, item: dict[str, Any]) -> str:
        raw_url = str(item.get("product_url") or item.get("url") or "").strip()
        if raw_url.startswith("https://www.breadfast.com/"):
            return raw_url
        safe_sku = quote(sku, safe="-_.")
        return self.product_url_template.replace("{sku}", safe_sku)

    def _parse_product_dict(
        self,
        item: dict[str, Any],
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        raw_id = _first_non_empty(item, ("sku", "id", "product_id", "productId", "external_id", "barcode", "code"))
        raw_title = _first_non_empty(item, ("name_en", "en_name", "name", "title", "product_name", "productName"))
        if raw_id is None or raw_title is None:
            return None

        sku = str(raw_id).strip()[:120]
        title = re.sub(r"\s+", " ", str(raw_title)).strip()
        if not sku or len(title) < 3:
            return None

        cur_raw, orig_raw, currency = _extract_prices(item)
        if not is_valid_egp_currency(currency, allow_missing=True):
            logger.error("CURRENCY_MISMATCH_ABORT | store=breadfast | sku=%s currency=%r", sku, currency)
            return None

        current_price = parse_egp_price(cur_raw)
        if current_price is None:
            return None

        orig_price = parse_egp_price(orig_raw) if orig_raw is not None else None
        claimed_original = orig_price if (orig_price is not None and orig_price > current_price) else None

        dept_parts: list[str] = []
        for k in ("department", "category", "category_name", "categoryName", "sub_category", "subcategory"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                dept_parts.append(v.strip())
            elif isinstance(v, dict) and v.get("name"):
                dept_parts.append(str(v["name"]).strip())
        cats_arr = item.get("categories")
        if isinstance(cats_arr, list):
            for c in cats_arr:
                if isinstance(c, str) and c.strip():
                    dept_parts.append(c.strip())
                elif isinstance(c, dict) and c.get("name"):
                    dept_parts.append(str(c["name"]).strip())
        dept_text = " ".join(dept_parts)

        category, sub_category = map_retail_department_to_category(title, dept_text)
        raw_brand_val = _first_non_empty(item, ("brand", "brand_name", "brandName", "vendor", "manufacturer"))
        if isinstance(raw_brand_val, dict):
            raw_brand_val = raw_brand_val.get("name")
        raw_brand = str(raw_brand_val).strip() if raw_brand_val else None
        brand = extract_grocery_brand(title, raw_brand) if category == "groceries" else (raw_brand or "Unknown")

        attrs: dict[str, Any] = {
            "cairo_zone": self.zone_id or f"{self.cairo_lat:.4f},{self.cairo_lng:.4f}",
        }
        if dept_parts:
            attrs["breadfast_department"] = dept_parts[0][:80]
        if category == "groceries":
            attrs.update(parse_grocery_packaging(title, raw_payload=item))
        barcode = _first_non_empty(item, ("barcode", "ean", "gtin"))
        if barcode and _EAN_RE.match(str(barcode).strip()):
            attrs["ean"] = str(barcode).strip()

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": sku,
                "canonical_product_key": None,
                "category": category,
                "sub_category": normalize_snake_slug(sub_category, fallback="other"),
                "brand": brand,
                "product_title": title,
                "product_url": self._build_product_url(sku, item),
                "image_url": _extract_image_url(item),
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": _extract_in_stock(item),
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _fetch_from_mobile_api(self, limit: int) -> list[dict[str, Any]]:
        """Mode A: Fetch catalog items from configured `BREADFAST_API_BASE` using lightweight httpx."""
        if not self.api_base:
            return []

        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = (
                self.auth_token if self.auth_token.lower().startswith("bearer ") else f"Bearer {self.auth_token}"
            )

        collected_raw: list[dict[str, Any]] = []
        base_params: dict[str, Any] = {
            "lat": self.cairo_lat,
            "lng": self.cairo_lng,
        }
        if self.zone_id:
            base_params["zone_id"] = self.zone_id

        page = 1
        max_pages = max(1, min(100, (limit // 50) + 2))
        while len(collected_raw) < limit and page <= max_pages:
            params = {**base_params, "page": page, "per_page": 50}
            url = f"{self.api_base}/products" if not self.api_base.endswith("/products") else self.api_base
            try:
                resp = self.http.get(url, params=params, headers=headers)
                if resp.status_code in (401, 403, 404, 429):
                    logger.warning("[breadfast] API returned HTTP %d on page %d; stopping API mode.", resp.status_code, page)
                    break
                payload = resp.json()
            except Exception as exc:
                logger.warning("[breadfast] API request failed on page %d: %s", page, exc)
                break

            self.pages_fetched += 1
            batch = extract_product_dicts(payload)
            if not batch:
                break
            collected_raw.extend(batch)
            if len(batch) < 20:
                break
            page += 1

        return collected_raw

    def _load_from_manual_feeds(self) -> list[dict[str, Any]]:
        """Mode B: Parse all `.har`, `.json`, and `.jsonl` files placed in `data/manual_feeds/breadfast/`."""
        items: list[dict[str, Any]] = []
        for source_name, payload in iter_json_payloads_from_feed_dir(self.feed_dir):
            batch = extract_product_dicts(payload)
            if batch:
                logger.info("[breadfast] Parsed %d candidate items from %s", len(batch), source_name)
                items.extend(batch)
        return items

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()

        raw_items: list[dict[str, Any]] = []
        raw_items.extend(self._fetch_from_mobile_api(target_limit))
        raw_items.extend(self._load_from_manual_feeds())

        if not raw_items:
            logger.info(
                "[breadfast] No API credentials (BREADFAST_API_BASE) or feed files found in %s; returning 0 records.",
                self.feed_dir,
            )
            return []

        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        for item in raw_items:
            if len(snapshots) >= target_limit:
                break
            rec = self._parse_product_dict(item, today, now)
            if rec is None or rec.external_id in seen_ids:
                continue
            seen_ids.add(rec.external_id)
            snapshots.append(rec)

        return snapshots
