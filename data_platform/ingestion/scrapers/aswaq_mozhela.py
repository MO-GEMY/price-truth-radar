"""Public JSON API scraper for Aswaq Mozhela (Egypt).

Endpoint:
    http://54.237.36.97/api/allproducts/latest-products/?count=5000

Features:
- Strict category allowlist mapping `model_name` onto canonical site categories
  (`fashion`, `beauty`, `baby_kids`, plus future standard verticals) while
  skipping off-category items (`Library`, `Birthday`, `Gifts`, empty/unknown).
- Cross-model ID disambiguation (`{model_slug}_{product_id}`) because the Django
  API emits per-model integer PKs (e.g. `Toys id=74` vs `Accessories id=74`).
- Phase 1 variant splitting (`{model_slug}_{product_id}__v{variant_id}`) with
  shared `parent_product_key`, clean stripped `variant_label`, and HTTPS S3
  image preference (ignoring HTTP `/static/products/placeholder.jpg`).
- 30s timeout with up to 3 retries + backoff for intermittent AWS host timeouts.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx

from .base import (
    BaseScraper,
    Category,
    PoliteHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

_API_URL = "http://54.237.36.97/api/allproducts/latest-products/?count=5000"
_FALLBACK_STORE_URL = "https://play.google.com/store/apps/details?id=com.herokuapp.aswaqmozhela"

# Strict allowlist mapping lowercased `model_name` -> (canonical_category, default_sub_category)
_ALLOWED_MODEL_MAP: dict[str, tuple[Category, str]] = {
    # Current live categories
    "accessories": ("fashion", "accessories"),
    "socks": ("fashion", "socks"),
    "veils": ("fashion", "scarves"),
    "shein": ("fashion", "apparel"),
    "toys": ("baby_kids", "toys"),
    # Future standard categories if added by the store
    "fashion": ("fashion", "apparel"),
    "clothing": ("fashion", "apparel"),
    "shoes": ("fashion", "shoes"),
    "bags": ("fashion", "bags"),
    "watches": ("fashion", "watches"),
    "electronics": ("electronics", "accessories"),
    "mobiles": ("electronics", "smartphones"),
    "phones": ("electronics", "smartphones"),
    "beauty": ("beauty", "beauty"),
    "makeup": ("beauty", "makeup"),
    "skincare": ("beauty", "skincare"),
    "cosmetics": ("beauty", "makeup"),
    "perfumes": ("beauty", "perfumes"),
    "health": ("health", "wellness"),
    "pharmacy": ("health", "pharmacy"),
    "groceries": ("groceries", "canned_sauces"),
    "supermarket": ("groceries", "canned_sauces"),
    "appliances": ("home_appliances", "small_appliances"),
    "home appliances": ("home_appliances", "small_appliances"),
    "home": ("home_furniture", "furniture"),
    "furniture": ("home_furniture", "furniture"),
    "sports": ("sports", "sports_gear"),
    "pets": ("pet_care", "pet_supplies"),
    "pet care": ("pet_care", "pet_supplies"),
}

_JEWELRY_GUARD_RE = re.compile(
    r"\b(bracelet|ring|necklace|earring|anklet|pendant|bangle|chain|watch)\b|سوار|خاتم|سلسلة|حلق|ساعة",
    re.I,
)
_BEAUTY_NAIL_RE = re.compile(r"\b(nails?|nail\s+file|nail\s+set|gel\s+nails?|manicure|pedicure)\b|أظافر|مبرد", re.I)
_BEAUTY_HAIR_RE = re.compile(r"\b(detangling|styling\s+brush|smart\s+brush|hair\s+brush|makeup|lipstick|mascara|cosmetic|perfume|skincare)\b|فرشاة\s+شعر|مكياج|عطر", re.I)
_ELECTRONICS_ACC_RE = re.compile(
    r"\b(charger|usb\s*cable|charging\s*cable|power\s*bank|earphone|earbuds|airpods|headphone|bluetooth\s+speaker|phone\s+case)\b|شاحن|كابل|باور\s*بانك|سماعة",
    re.I,
)


def _clean_https_image(url: Any) -> Optional[str]:
    """Return clean HTTPS image URL, ignoring HTTP/placeholder fallbacks."""
    if not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned.lower().startswith("https://"):
        return None
    if "placeholder" in cleaned.lower():
        return None
    return cleaned


def _clean_variant_label(color_name: Any, size: Any) -> Optional[str]:
    parts: list[str] = []
    for raw in (color_name, size):
        if raw is None:
            continue
        val = re.sub(r"\s+", " ", str(raw)).strip()
        if val and val.lower() not in ("none", "null", "n/a", "default") and val not in parts:
            parts.append(val)
    if not parts:
        return None
    return " / ".join(parts)[:80]


def _append_variant_to_title(base_title: str, variant_label: Optional[str]) -> str:
    if not variant_label:
        return base_title
    if variant_label.lower() in base_title.lower():
        return base_title
    return f"{base_title} — {variant_label}"


def _route_category_and_sub(model_name_raw: str, title: str) -> Optional[tuple[Category, str]]:
    """Map `model_name` onto canonical `(category, sub_category)`, or `None` to skip."""
    key = re.sub(r"\s+", " ", model_name_raw).strip().lower()
    if not key or key not in _ALLOWED_MODEL_MAP:
        return None

    category, sub_category = _ALLOWED_MODEL_MAP[key]

    # Refine mixed `Accessories` items: route genuine nail/hairbrush beauty items to `beauty`
    # and phone/charging accessories to `electronics`; keep fashion accessories in `fashion`.
    if key == "accessories":
        if _ELECTRONICS_ACC_RE.search(title):
            return "electronics", "accessories"
        if not _JEWELRY_GUARD_RE.search(title):
            if _BEAUTY_NAIL_RE.search(title):
                return "beauty", "makeup"
            if _BEAUTY_HAIR_RE.search(title):
                return "beauty", "haircare"
        low = title.lower()
        if any(w in low for w in ("watch", "chronograph", "ساعة")):
            return "fashion", "watches"
        if any(w in low for w in ("belt", "حزام")):
            return "fashion", "accessories"
        if any(w in low for w in ("hair", "clip", "claw", "hairband", "scrunchie", "توكة", "شعر")):
            return "fashion", "accessories"
        if any(w in low for w in ("bracelet", "ring", "necklace", "earring", "سوار", "خاتم")):
            return "fashion", "jewelry"

    return category, sub_category


class AswaqMozhelaScraper(BaseScraper):
    """Public JSON API scraper for Aswaq Mozhela (EGP)."""

    store_name = "aswaq_mozhela"
    category: Category = "fashion"
    base_url = _FALLBACK_STORE_URL
    default_limit = 600
    discover_limit = 2000
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion", "core")
    min_delay_seconds = 1.0
    request_timeout = 30.0

    def _fetch_products_payload(self) -> list[dict[str, Any]]:
        """Fetch API JSON payload with 30s timeout, up to 3 retries, and short backoff.

        Sends `Accept: application/json` explicitly so Django REST Framework returns
        compact JSON (~1-2s) rather than rendering its slow HTML Browsable API, and
        uses a fresh client per attempt so intermittent `WinError 10060` socket drops
        never poison subsequent retries.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                with httpx.Client(
                    headers={"Accept": "application/json"},
                    timeout=self.request_timeout,
                    follow_redirects=True,
                ) as client:
                    resp = client.get(_API_URL)
                    resp.raise_for_status()
                self.pages_fetched += 1
                data = resp.json()
                products = data.get("products") if isinstance(data, dict) else None
                if isinstance(products, list):
                    return products
                raise ValueError("Unexpected API response: missing 'products' list")
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                last_exc = exc
                if attempt < 3:
                    backoff = 2.0 * attempt
                    logger.warning(
                        "[%s] API fetch attempt %d/3 failed (%s); retrying in %.1fs...",
                        self.store_name,
                        attempt,
                        exc,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def parse_products(
        self,
        raw_products: list[dict[str, Any]],
        *,
        limit: Optional[int] = None,
    ) -> list[RawProductSnapshot]:
        """Parse raw API product list into validated, allowlisted snapshots."""
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        skipped_by_model: Counter[str] = Counter()
        self.category_counts = {}

        for raw in raw_products:
            if not isinstance(raw, dict):
                continue

            model_raw = str(raw.get("model_name") or "").strip()
            title = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
            # Clean occasional literal "Title: " prefix emitted by store CMS
            title = re.sub(r"^Title:\s*", "", title, flags=re.I).strip()

            routed = _route_category_and_sub(model_raw, title)
            if routed is None:
                skipped_by_model[model_raw or "<empty>"] += 1
                continue

            if not raw.get("is_active"):
                skipped_by_model[f"{model_raw}:inactive"] += 1
                continue

            pid = raw.get("id")
            if pid is None or len(title) < 3:
                self.skipped_count += 1
                continue

            cat, sub_cat = routed
            model_slug = normalize_snake_slug(model_raw, fallback="item", max_len=24)
            parent_ext_id = f"{model_slug}_{pid}"
            parent_product_key = f"{self.store_name}_{parent_ext_id}"
            primary_img = _clean_https_image(raw.get("primary_image"))

            raw_variants = raw.get("variants") if isinstance(raw.get("variants"), list) else []
            active_variants: list[tuple[dict[str, Any], Decimal, Optional[str]]] = []
            for v in raw_variants:
                if not isinstance(v, dict):
                    continue
                if not v.get("is_active"):
                    continue
                v_price = parse_egp_price(v.get("price"))
                if v_price is None or v_price <= 0:
                    continue
                active_variants.append((v, v_price, _clean_variant_label(v.get("color_name"), v.get("size"))))

            if active_variants:
                v_prices = [p for _, p, _ in active_variants]
                min_v_price = float(min(v_prices))
                max_v_price = float(max(v_prices))
                v_count = len(active_variants)

                for v, v_price, v_label in active_variants:
                    vid = v.get("id")
                    if vid is None:
                        continue
                    ext_id = f"{parent_ext_id}__v{vid}"
                    if ext_id in seen_ids:
                        continue

                    v_orig = parse_egp_price(v.get("original_price"))
                    claimed_orig = v_orig if (v_orig is not None and v_orig > v_price) else None
                    v_stock = int(v.get("stock") or 0)
                    v_in_stock = v_stock > 0
                    v_img = _clean_https_image(v.get("variant_image1")) or primary_img

                    attrs: dict[str, Any] = {
                        "parent_product_key": parent_product_key,
                        "variant_id": str(vid),
                        "variant_count": v_count,
                        "variant_min_price": min_v_price,
                        "variant_max_price": max_v_price,
                        "model_name": model_raw,
                    }
                    if v_label:
                        attrs["variant_label"] = v_label
                    if v.get("color_code"):
                        attrs["color_code"] = str(v["color_code"]).strip()

                    rec = self.validate_record(
                        {
                            "store_name": self.store_name,
                            "external_id": ext_id,
                            "category": cat,
                            "sub_category": sub_cat,
                            "brand": "Aswaq Mozhela",
                            "product_title": _append_variant_to_title(title, v_label),
                            "product_url": _FALLBACK_STORE_URL,
                            "image_url": v_img,
                            "attributes_json": attrs,
                            "current_price": v_price,
                            "claimed_original_price": claimed_orig,
                            "in_stock": v_in_stock,
                            "snapshot_date": snapshot_date,
                            "scraped_at": scraped_at,
                        }
                    )
                    if rec is not None:
                        seen_ids.add(ext_id)
                        collected.append(rec)
                        self.category_counts[cat] = self.category_counts.get(cat, 0) + 1
            else:
                price = parse_egp_price(raw.get("price"))
                if price is None or price <= 0:
                    skipped_by_model[f"{model_raw}:zero_or_invalid_price"] += 1
                    continue

                if parent_ext_id in seen_ids:
                    continue

                orig = parse_egp_price(raw.get("original_price"))
                claimed_orig = orig if (orig is not None and orig > price) else None
                in_stock = bool(raw.get("is_available") and int(raw.get("stock") or 0) > 0)

                attrs = {
                    "parent_product_key": parent_product_key,
                    "variant_count": 1,
                    "variant_min_price": float(price),
                    "variant_max_price": float(price),
                    "model_name": model_raw,
                }

                rec = self.validate_record(
                    {
                        "store_name": self.store_name,
                        "external_id": parent_ext_id,
                        "category": cat,
                        "sub_category": sub_cat,
                        "brand": "Aswaq Mozhela",
                        "product_title": title,
                        "product_url": _FALLBACK_STORE_URL,
                        "image_url": primary_img,
                        "attributes_json": attrs,
                        "current_price": price,
                        "claimed_original_price": claimed_orig,
                        "in_stock": in_stock,
                        "snapshot_date": snapshot_date,
                        "scraped_at": scraped_at,
                    }
                )
                if rec is not None:
                    seen_ids.add(parent_ext_id)
                    collected.append(rec)
                    self.category_counts[cat] = self.category_counts.get(cat, 0) + 1

        if skipped_by_model:
            summary_str = ", ".join(f"{k}={v}" for k, v in skipped_by_model.most_common())
            logger.info(
                "[%s] Skipped %d off-category/inactive/invalid items by model_name: %s",
                self.store_name,
                sum(skipped_by_model.values()),
                summary_str,
            )

        collected = self.prioritize_tracked(collected, lambda r: r.external_id)
        if limit is not None and limit > 0:
            collected = collected[:limit]
        return collected

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []
        raw_products = self._fetch_products_payload()
        return self.parse_products(raw_products, limit=target_limit)
