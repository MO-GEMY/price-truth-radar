"""
Live scraper for Raya Shop Egypt (`https://www.rayashop.com`).

Uses `curl_cffi` TLS impersonation (`ImpersonatedHttpClient`, `impersonate="chrome"`)
across Raya Shop's SSR category pages (`/en/mobiles-and-tablets`,
`/en/televisions-and-receivers`, `/en/large-appliances`, `/en/laptops-pcs`,
`/en/small-appliances`). Parses embedded `JSON-LD Product` blocks when present
and targets `article.ProductCardPlpGrid` cash-price elements strictly while
excluding monthly installment widgets (`Takseety`, `valU`, `Aman`, `Souhoola`,
`/mo`, `قسط`, `شهري`) and `- N EGP` savings badges.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    is_installment_text,
    parse_egp_price,
    strip_installment_segments,
    utc_now_naive,
)
from .two_b import _extract_specs, _normalize_brand, _refine_sub_category

logger = logging.getLogger(__name__)

RAYASHOP_CATEGORIES: tuple[tuple[str, Category, str], ...] = (
    ("smartphones", "electronics", "https://www.rayashop.com/en/mobiles-and-tablets"),
    ("tvs", "home_appliances", "https://www.rayashop.com/en/televisions-and-receivers"),
    ("laptops", "electronics", "https://www.rayashop.com/en/laptops-pcs"),
    ("large_appliances", "home_appliances", "https://www.rayashop.com/en/large-appliances"),
    ("small_appliances", "home_appliances", "https://www.rayashop.com/en/small-appliances"),
)

_PRICE_NUM_RE = re.compile(
    r"(?<!-\s)(?<!-)(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{2,7}(?:\.\d{1,2})?)\s*EGP\b",
    re.I,
)

_EXCLUDED_PRICE_CLASS_TOKENS: tuple[str, ...] = (
    "productcardcustomlabels",
    "installment",
    "takseety",
    "valu",
    "aman",
    "suhoula",
    "souhoola",
    "bg-red-50",
    "text-red-700",
)


def _has_excluded_price_ancestor(el: Tag, stop_at: Tag) -> bool:
    """Return True if `el` or any ancestor up to `stop_at` is an installment or savings badge."""
    cur: Optional[Tag] = el
    while cur is not None and cur is not stop_at:
        classes = " ".join(cur.get("class") or []).lower()
        if any(tok in classes for tok in _EXCLUDED_PRICE_CLASS_TOKENS):
            return True
        own_txt = re.sub(r"\s+", " ", cur.get_text(" ", strip=True))
        if own_txt.startswith("-") or is_installment_text(own_txt):
            return True
        cur = cur.parent if isinstance(cur.parent, Tag) else None
    return False


def _extract_rayashop_card_prices(card: Tag) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract (cash_price, claimed_original_price) from a Raya Shop product card.

    Strictly targets `.ProductCardPlpGrid__Price` cash & strikethrough spans and
    excludes monthly installment banners (`Takseety ... EGP/ 36 mo`, `valU`,
    `Aman`, `Souhoola`, `قسط`, `شهري`) and `- N EGP` savings badges.
    """
    price_container = card.select_one(".ProductCardPlpGrid__Price")
    if price_container is not None:
        cash_price: Optional[Decimal] = None
        old_price: Optional[Decimal] = None

        for span in price_container.select("span.currency"):
            if _has_excluded_price_ancestor(span, price_container):
                continue
            raw_txt = re.sub(r"\s+", " ", span.get_text(" ", strip=True))
            if raw_txt.startswith("-") or is_installment_text(raw_txt):
                continue
            parsed = parse_egp_price(raw_txt)
            if parsed is None:
                continue
            classes = {c.lower() for c in (span.get("class") or [])}
            if "line-through" in classes:
                if old_price is None or parsed > old_price:
                    old_price = parsed
            elif cash_price is None:
                cash_price = parsed

        if cash_price is not None:
            claimed = old_price if (old_price is not None and old_price > cash_price) else None
            return cash_price, claimed

    # Safe fallback if Raya Shop updates DOM class names: scrub installment & savings elements first
    parts: list[str] = []
    for node in card.descendants:
        if isinstance(node, Tag) and node.name in ("span", "div", "p"):
            classes = " ".join(node.get("class") or []).lower()
            if any(tok in classes for tok in _EXCLUDED_PRICE_CLASS_TOKENS):
                continue
    # Remove installment/savings nodes from a lightweight text view
    safe_chunks: list[str] = []
    for text_node in card.find_all(string=True):
        parent = text_node.parent if isinstance(text_node.parent, Tag) else None
        if parent is not None and _has_excluded_price_ancestor(parent, card):
            continue
        chunk = str(text_node).strip()
        if chunk:
            safe_chunks.append(chunk)
    cleaned_txt = strip_installment_segments(" ".join(safe_chunks))
    matches = [parse_egp_price(m) for m in _PRICE_NUM_RE.findall(cleaned_txt)]
    valid = [p for p in matches if p is not None and p >= Decimal("10")]
    if not valid or len(valid) > 3:
        return None, None
    cash_price = valid[0]
    claimed = max(valid) if max(valid) > cash_price else None
    return cash_price, claimed


def _extract_jsonld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = parsed if isinstance(parsed, list) else [parsed]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if node.get("@type") == "Product" and node.get("name"):
                    found.append(node)
                for key in ("@graph", "itemListElement", "mainEntity", "hasPart"):
                    child = node.get(key)
                    if isinstance(child, (list, dict)):
                        stack.append(child)
                if isinstance(node.get("item"), dict):
                    stack.append(node["item"])
    return found


class RayaShopScraper(BaseScraper):
    """Live scraper for Raya Shop Egypt (`curl_cffi` chrome + JSON-LD / SSR DOM)."""

    store_name = "rayashop"
    category: Category = "electronics"
    base_url = "https://www.rayashop.com"
    default_limit = 200
    discover_limit = 800
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 2.0
    request_timeout = 30.0

    def _parse_single_card(
        self,
        card: Tag,
        cat_name: Category,
        default_sub: str,
        snapshot_date: Any,
        scraped_at: datetime,
        seen_urls: set[str],
    ) -> Optional[RawProductSnapshot]:
        anchor = (
            card.select_one('a.ProductCardPlpGrid__ImageLink[href]')
            or card.select_one('.ProductCardPlpGrid__Footer a[href]')
            or card.select_one('a[href^="/en/"], a[href^="https://www.rayashop.com/en/"]')
        )
        if anchor is None:
            return None
        href = str(anchor.get("href") or "").strip()
        path = urlparse(urljoin(self.base_url, href)).path.rstrip("/")
        if not path or path.count("/") < 2:
            return None
        if any(
            skip in path.lower()
            for skip in ("/login", "/cart", "/account", "/checkout", "/black-friday", "/brands", "/stores", "/category")
        ):
            return None
        full_url = urljoin(self.base_url, path)
        if full_url in seen_urls:
            return None

        current_price, claimed_price = _extract_rayashop_card_prices(card)
        if current_price is None:
            return None

        title = ""
        for sel in (".ProductCardPlpGrid__Name", "h2", "h3", "h4", "[class*='title']", "[class*='name']"):
            el = card.select_one(sel)
            if el:
                cand = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
                if len(cand) >= 6 and "EGP" not in cand:
                    title = cand
                    break
        if not title:
            img = card.select_one("img[alt]")
            if img:
                title = re.sub(r"\s+", " ", str(img.get("alt") or "")).strip()
        if len(title) < 6:
            return None

        img_url: Optional[str] = None
        for img in card.select("img.ProductCardPlpGrid__Thumb, img"):
            for attr in ("data-src", "src"):
                val = str(img.get(attr) or "").strip()
                if val.startswith("http") and not val.endswith(".svg") and "logo" not in val.lower():
                    img_url = val
                    break
            if img_url:
                break

        slug = path.rsplit("/", 1)[-1]
        seen_urls.add(full_url)
        brand = _normalize_brand(None, title)
        sub_cat = _refine_sub_category(default_sub, cat_name, title)
        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
        attrs.pop("two_b_category", None)
        attrs["rayashop_category"] = sub_cat
        card_txt = card.get_text(" ", strip=True)

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": slug[:120],
                "canonical_product_key": None,
                "category": cat_name,
                "sub_category": sub_cat,
                "brand": brand,
                "product_title": title,
                "product_url": full_url,
                "image_url": img_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_price,
                "in_stock": "out of stock" not in card_txt.lower(),
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _parse_dom_cards(
        self,
        soup: BeautifulSoup,
        cat_name: Category,
        default_sub: str,
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> list[RawProductSnapshot]:
        results: list[RawProductSnapshot] = []
        seen_urls: set[str] = set()

        # Primary: Raya Shop Nuxt PLP product cards (`article.ProductCardPlpGrid`)
        plp_cards = soup.select("article.ProductCardPlpGrid")
        if plp_cards:
            for card in plp_cards:
                rec = self._parse_single_card(card, cat_name, default_sub, snapshot_date, scraped_at, seen_urls)
                if rec is not None:
                    results.append(rec)
            return results

        # Fallback: walk from product anchors to card container (still guarded against installments)
        for anchor in soup.select('a[href^="/en/"], a[href^="https://www.rayashop.com/en/"]'):
            card = anchor
            for _ in range(3):
                txt = card.get_text(" ", strip=True)
                if _PRICE_NUM_RE.search(txt) and card.select_one("img"):
                    break
                if isinstance(card.parent, Tag):
                    card = card.parent
            rec = self._parse_single_card(card, cat_name, default_sub, snapshot_date, scraped_at, seen_urls)
            if rec is not None:
                results.append(rec)

        return results

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}

        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        per_cat_cap = max(2, math.ceil(target_limit / len(RAYASHOP_CATEGORIES)))
        max_pages = 6 if self.mode == "discover" else (2 if target_limit > 40 else 1)
        blocked = False

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 30.0,
            max_retries=3,
            backoff_base=2.0,
            min_delay_seconds=effective_delay,
            jitter_range=(0.3, 1.0),
        ) as client:
            for default_sub, cat_name, cat_url in RAYASHOP_CATEGORIES:
                if len(collected) >= target_limit or blocked:
                    break
                cat_collected = 0

                for page in range(1, max_pages + 1):
                    if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    logger.info("[rayashop] Fetching %s/%s page %d (%s)", cat_name, default_sub, page, cat_url)
                    try:
                        resp = client.get(
                            cat_url,
                            params={"page": page} if page > 1 else None,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=True,
                            min_html_bytes=5120,
                        )
                    except ThrottledResponseError as exc:
                        logger.warning("[rayashop] WAF/403 block on %s (%s); exiting gracefully with %d snapshots.", cat_url, exc, len(collected))
                        blocked = True
                        break
                    except Exception as exc:
                        logger.warning("[rayashop] Fetch error on %s page %d: %s", cat_url, page, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_records: list[RawProductSnapshot] = []

                    # Primary: JSON-LD Product items when present
                    for ld in _extract_jsonld_items(soup):
                        title = re.sub(r"\s+", " ", str(ld.get("name") or "")).strip()
                        raw_url = str(ld.get("url") or "").strip()
                        offers = ld.get("offers")
                        offer = offers[0] if isinstance(offers, list) and offers else (offers if isinstance(offers, dict) else {})
                        price = parse_egp_price(offer.get("price"))
                        if not title or not raw_url or price is None:
                            continue
                        full_url = urljoin(self.base_url, raw_url)
                        slug = urlparse(full_url).path.rstrip("/").rsplit("/", 1)[-1]
                        img_raw = ld.get("image")
                        img_url = img_raw[0] if isinstance(img_raw, list) and img_raw else (img_raw if isinstance(img_raw, str) else None)
                        brand_obj = ld.get("brand")
                        raw_brand = brand_obj.get("name") if isinstance(brand_obj, dict) else (brand_obj if isinstance(brand_obj, str) else None)
                        sub_cat = _refine_sub_category(default_sub, cat_name, title)
                        attrs: dict[str, Any] = _extract_specs(title, sub_cat)
                        attrs.pop("two_b_category", None)
                        attrs["rayashop_category"] = sub_cat
                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": str(ld.get("sku") or slug)[:120],
                                "canonical_product_key": None,
                                "category": cat_name,
                                "sub_category": sub_cat,
                                "brand": _normalize_brand(raw_brand, title),
                                "product_title": title,
                                "product_url": full_url,
                                "image_url": img_url,
                                "attributes_json": attrs,
                                "current_price": price,
                                "claimed_original_price": None,
                                "in_stock": "outofstock" not in str(offer.get("availability") or "").lower(),
                                "snapshot_date": snapshot_date,
                                "scraped_at": scraped_at,
                            }
                        )
                        if rec is not None:
                            page_records.append(rec)

                    if not page_records:
                        page_records = self._parse_dom_cards(soup, cat_name, default_sub, snapshot_date, scraped_at)

                    page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                    added = 0
                    for rec in page_records:
                        if rec.external_id in seen_ids:
                            continue
                        seen_ids.add(rec.external_id)
                        collected.append(rec)
                        cat_collected += 1
                        added += 1
                        if len(collected) >= target_limit or cat_collected >= per_cat_cap:
                            break

                    if added == 0:
                        break

                self.category_counts[f"{cat_name}/{default_sub}"] = cat_collected

        logger.info("[rayashop] Per-category counts: %s", self.category_counts)
        return collected
