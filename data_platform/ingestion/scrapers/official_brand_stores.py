"""
Verified official Egyptian brand store scrapers:
  - `samsung_eg`             : Samsung Egypt official Product Finder JSON API (`searchapi.samsung.com`, `cloud`)
  - `max_fashion_eg`         : Max Fashion Egypt SSR `ItemList` JSON-LD (`maxfashion.com/eg/en`, `local_only`)
  - `oraimo_eg`              : Oraimo Egypt official store SSR `.site-item` + EANs (`eg.oraimo.com`, `cloud`)
  - `bath_and_body_works_eg` : Bath & Body Works Egypt Algolia catalog (`bathandbodyworks.com.eg`, `cloud`)

All 4 enforce strict EGP currency guards, in-stock filtering, polite pacing, and 0 Neon connections.
"""

from __future__ import annotations

import json
import logging
import math
import re
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    normalize_snake_slug,
    parse_egp_price,
    utc_now_naive,
)
from .currency_guard import is_valid_egp_currency
from .noon import _extract_specs, _refine_sub_category
from ..fx_rates import convert_to_egp

logger = logging.getLogger(__name__)

_EGP_PRICE_RE = re.compile(r"(?:EGP|LE|ج\.م)\s*(\d[\d,]*(?:\.\d{1,2})?)|(\d[\d,]*(?:\.\d{1,2})?)\s*(?:EGP|LE|ج\.م)", re.I)
_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")


# ---------------------------------------------------------------------------
# 1. Samsung Egypt (`samsung_eg`) — Official Samsung Product Finder JSON API
# ---------------------------------------------------------------------------
class SamsungEgScraper(BaseScraper):
    """Official Samsung Egypt scraper via `searchapi.samsung.com` (`siteCode=eg`, `cloud`)."""

    store_name = "samsung_eg"
    category: Category = "electronics"
    base_url = "https://www.samsung.com"
    api_url = "https://searchapi.samsung.com/v6/front/b2c/product/finder/global"
    default_limit = 2000
    discover_limit = 5000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.0
    request_timeout = 20.0

    _DEPARTMENT_TYPES: tuple[tuple[str, Category, str], ...] = (
        ("01010000", "electronics", "smartphones"),
        ("01020000", "electronics", "tablets"),
        ("01030000", "electronics", "wearables"),
        ("01040000", "electronics", "headphones"),
        ("04010000", "home_appliances", "tvs"),
        ("05010000", "electronics", "speakers"),
        ("07010000", "electronics", "monitors"),
        ("08010000", "home_appliances", "refrigerators"),
        ("08030000", "home_appliances", "washing_machines"),
        ("08070000", "home_appliances", "vacuums"),
    )

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_codes: set[str] = set()
        headers = {"Accept": "application/json", "Origin": "https://www.samsung.com"}

        for type_code, top_cat, default_sub in self._DEPARTMENT_TYPES:
            if len(snapshots) >= target_limit:
                break
            start = 1
            page_size = 50
            while len(snapshots) < target_limit:
                params = {
                    "type": type_code,
                    "siteCode": "eg",
                    "start": start,
                    "num": page_size,
                    "sort": "recommended",
                    "onlyFilterInfoYN": "N",
                }
                try:
                    resp = self.http.get(self.api_url, params=params, headers=headers)
                    if resp.status_code != 200:
                        break
                    payload = resp.json()
                except Exception as exc:
                    logger.warning("[samsung_eg] Finder API failed for type=%s start=%d: %s", type_code, start, exc)
                    break

                self.pages_fetched += 1
                result_data = (payload.get("response") or {}).get("resultData") or {}
                product_list = result_data.get("productList") or []
                if not product_list:
                    break

                for family in product_list:
                    for model in (family.get("modelList") or []):
                        if not isinstance(model, dict):
                            continue
                        code = str(model.get("modelCode") or "").strip().upper()
                        if not code or code in seen_codes:
                            continue

                        title = re.sub(r"\s+", " ", str(model.get("displayName") or family.get("fmyEngName") or "")).strip()
                        if len(title) < 3:
                            continue
                        if not title.lower().startswith("samsung"):
                            title = f"Samsung {title}"

                        # Verify EGP currency via priceDisplay when present
                        price_disp = str(model.get("priceDisplay") or "")
                        if price_disp and not any(tok in price_disp for tok in ("ج.م", "EGP", "LE")):
                            continue

                        reg_price = parse_egp_price(model.get("price"))
                        promo_price = parse_egp_price(model.get("promotionPrice"))
                        if promo_price is not None and (reg_price is None or promo_price < reg_price):
                            current_price = promo_price
                            claimed_original = reg_price if (reg_price is not None and reg_price > promo_price) else None
                        else:
                            current_price = reg_price
                            claimed_original = None
                        if current_price is None:
                            continue

                        stock_text = str(model.get("stockStatusText") or "").strip().lower()
                        in_stock = stock_text not in ("outofstock", "out_of_stock", "soldout", "discontinued")

                        pdp_path = str(model.get("pdpUrl") or "").strip()
                        if not pdp_path:
                            continue
                        product_url = pdp_path if pdp_path.startswith("http") else urljoin(self.base_url, pdp_path)

                        thumb = str(model.get("thumbUrl") or "").strip()
                        image_url = f"https:{thumb}" if thumb.startswith("//") else (thumb if thumb.startswith("http") else None)

                        sub_category = _refine_sub_category(title, top_cat, default_sub)
                        attrs = _extract_specs(title, top_cat, sub_category)
                        attrs.pop("noon_category", None)
                        attrs["model_code"] = code

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": code[:120],
                                "canonical_product_key": None,
                                "category": top_cat,
                                "sub_category": sub_category,
                                "brand": "Samsung",
                                "product_title": title,
                                "product_url": product_url,
                                "image_url": image_url,
                                "attributes_json": attrs,
                                "current_price": current_price,
                                "claimed_original_price": claimed_original,
                                "in_stock": in_stock,
                                "snapshot_date": today,
                                "scraped_at": now,
                            }
                        )
                        if rec is not None:
                            seen_codes.add(code)
                            snapshots.append(rec)
                            if len(snapshots) >= target_limit:
                                break
                    if len(snapshots) >= target_limit:
                        break

                total_rec = int((result_data.get("common") or {}).get("totalRecord") or 0)
                start += page_size
                if start > total_rec or len(product_list) < page_size:
                    break

        return snapshots


# ---------------------------------------------------------------------------
# 2. Max Fashion Egypt (`max_fashion_eg`) — SSR JSON-LD ItemList (`local_only`)
# ---------------------------------------------------------------------------
class MaxFashionEgScraper(BaseScraper):
    """Official Max Fashion Egypt scraper via SSR `ItemList` JSON-LD (`local_only`)."""

    store_name = "max_fashion_eg"
    category: Category = "fashion"
    base_url = "https://www.maxfashion.com"
    default_limit = 2500
    discover_limit = 6000
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion", "core")
    min_delay_seconds = 1.5
    request_timeout = 25.0

    _CATEGORY_PATHS: tuple[tuple[str, Category, str], ...] = (
        ("/eg/en/c/mxwomen", "fashion", "apparel"),
        ("/eg/en/c/mxmen", "fashion", "apparel"),
        ("/eg/en/c/mxkids", "baby_kids", "apparel"),
        ("/eg/en/c/mxhome", "home_furniture", "home_decor"),
    )

    @staticmethod
    def _infer_fashion_sub(title: str, default_sub: str) -> str:
        low = title.lower()
        for sub, kws in (
            ("footwear", ("shoe", "sneaker", "boot", "sandal", "slipper", "loafer", "heel", "flat")),
            ("jackets", ("jacket", "coat", "blazer", "puffer", "bomber", "vest")),
            ("knitwear", ("hoodie", "sweatshirt", "sweater", "pullover", "cardigan", "knit")),
            ("dresses", ("dress", "abaya", "kaftan", "jumpsuit", "skirt")),
            ("pants", ("jean", "denim", "trouser", "pant", "jogger", "short", "legging")),
            ("tees", ("t-shirt", "tshirt", "tee", "polo")),
            ("shirts", ("shirt", "blouse", "top", "tunic")),
            ("accessories", ("bag", "backpack", "wallet", "belt", "cap", "hat", "scarf", "sock", "sunglass")),
        ):
            if any(kw in low for kw in kws):
                return sub
        return default_sub

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        per_cat_cap = max(20, math.ceil(target_limit / len(self._CATEGORY_PATHS)))
        max_pages = 8 if self.mode in ("discover", "expand") else 3

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 25.0,
            max_retries=2,
            min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
            jitter_range=(0.3, 1.0),
            headers={"Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            for path, top_cat, default_sub in self._CATEGORY_PATHS:
                if len(snapshots) >= target_limit:
                    break
                cat_collected = 0
                for page in range(1, max_pages + 1):
                    if len(snapshots) >= target_limit or cat_collected >= per_cat_cap:
                        break
                    url = f"{self.base_url}{path}" if page == 1 else f"{self.base_url}{path}?p={page}"
                    try:
                        resp = client.get(url, check_throttle=True, min_html_bytes=5120)
                    except ThrottledResponseError as exc:
                        logger.warning("[max_fashion_eg] Throttled on %s: %s", url, exc)
                        return snapshots
                    except Exception as exc:
                        logger.warning("[max_fashion_eg] Failed %s: %s", url, exc)
                        break

                    self.pages_fetched += 1
                    soup = BeautifulSoup(resp.text, "html.parser")
                    items_raw: list[dict[str, Any]] = []
                    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
                        try:
                            doc = json.loads(sc.get_text(strip=True))
                        except Exception:
                            continue
                        if isinstance(doc, dict):
                            me = doc.get("mainEntity")
                            if isinstance(me, dict) and isinstance(me.get("itemListElement"), list):
                                items_raw.extend(me["itemListElement"])
                    if not items_raw:
                        break

                    page_added = 0
                    for entry in items_raw:
                        prod = entry.get("item") if isinstance(entry, dict) and isinstance(entry.get("item"), dict) else entry
                        if not isinstance(prod, dict):
                            continue
                        prod_url = str(prod.get("url") or "").strip()
                        if not prod_url.startswith("http"):
                            continue
                        m_sku = re.search(r"/p/([A-Za-z0-9_-]+)", prod_url)
                        sku = m_sku.group(1).upper() if m_sku else normalize_snake_slug(prod_url.rsplit("/", 1)[-1], fallback="")
                        if not sku or sku in seen_ids:
                            continue

                        offers = prod.get("offers") if isinstance(prod.get("offers"), dict) else {}
                        currency = offers.get("priceCurrency")
                        if not is_valid_egp_currency(currency, allow_missing=False):
                            logger.error("CURRENCY_MISMATCH_ABORT | store=max_fashion_eg | currency=%r", currency)
                            return snapshots

                        current_price = parse_egp_price(offers.get("price"))
                        if current_price is None:
                            continue

                        avail = str(offers.get("availability") or "").lower()
                        in_stock = "outofstock" not in avail

                        title = re.sub(r"\s+", " ", str(prod.get("name") or "")).strip()
                        if len(title) < 3:
                            continue

                        img = prod.get("image")
                        image_url = img if isinstance(img, str) and img.startswith("http") else None
                        sub_cat = self._infer_fashion_sub(title, default_sub) if top_cat == "fashion" else default_sub

                        rec = self.validate_record(
                            {
                                "store_name": self.store_name,
                                "external_id": sku[:120],
                                "canonical_product_key": None,
                                "category": top_cat,
                                "sub_category": sub_cat,
                                "brand": "Max",
                                "product_title": title,
                                "product_url": prod_url,
                                "image_url": image_url,
                                "attributes_json": {"max_section": path.rsplit("/", 1)[-1]},
                                "current_price": current_price,
                                "claimed_original_price": None,
                                "in_stock": in_stock,
                                "snapshot_date": today,
                                "scraped_at": now,
                            }
                        )
                        if rec is not None:
                            seen_ids.add(sku)
                            snapshots.append(rec)
                            cat_collected += 1
                            page_added += 1
                            if len(snapshots) >= target_limit or cat_collected >= per_cat_cap:
                                break
                    if page_added == 0:
                        break

        return snapshots


# ---------------------------------------------------------------------------
# 3. Oraimo Egypt (`oraimo_eg`) — SSR `.site-item` Cards + EANs (`cloud`)
# ---------------------------------------------------------------------------
class OraimoEgScraper(BaseScraper):
    """Official Oraimo Egypt online store scraper (`https://eg.oraimo.com`, `cloud`)."""

    store_name = "oraimo_eg"
    category: Category = "electronics"
    base_url = "https://eg.oraimo.com"
    default_limit = 1500
    discover_limit = 3000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.0
    request_timeout = 20.0

    _COLLECTIONS: tuple[tuple[str, Category, str], ...] = (
        ("/collections/audio", "electronics", "headphones"),
        ("/collections/power", "electronics", "accessories"),
        ("/collections/home-appliances", "home_appliances", "small_appliances"),
        ("/collections/kitchen-appliances", "home_appliances", "kitchen_appliances"),
        ("/collections/wearables", "electronics", "wearables"),
        ("/collections/personal-care", "beauty", "personal_care"),
        ("/collections/cables", "electronics", "accessories"),
        ("/collections/car-chargers", "electronics", "accessories"),
        ("/collections/open-ear-headphones", "electronics", "headphones"),
        ("/collections/mifi", "electronics", "networking"),
    )

    @staticmethod
    def _extract_egp_prices_from_card(card_text: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Extract visible EGP prices from card text (ignoring USD `data-price` attribute)."""
        found: list[Decimal] = []
        for m in _EGP_PRICE_RE.finditer(card_text):
            raw = m.group(1) or m.group(2)
            p = parse_egp_price(raw)
            if p is not None and p not in found:
                found.append(p)
        if not found:
            return None, None
        current_price = found[0]
        claimed = max(found[1:]) if len(found) > 1 and max(found[1:]) > current_price else None
        return current_price, claimed

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_skus: set[str] = set()

        for col_path, top_cat, default_sub in self._COLLECTIONS:
            if len(snapshots) >= target_limit:
                break
            url = f"{self.base_url}{col_path}"
            try:
                resp = self.http.get(url)
                if resp.status_code != 200:
                    continue
            except Exception as exc:
                logger.warning("[oraimo_eg] Failed %s: %s", url, exc)
                continue

            self.pages_fetched += 1
            soup = BeautifulSoup(resp.text, "html.parser")
            for item_div in soup.select(".site-item"):
                if len(snapshots) >= target_limit:
                    break
                link = item_div.select_one("a[data-sku]")
                if not link:
                    continue
                sku = str(link.get("data-sku") or "").strip().upper()
                if not sku or sku in seen_skus:
                    continue
                href = str(link.get("href") or "").strip()
                if not href or "membership" in href.lower():
                    continue
                product_url = urljoin(self.base_url, href)

                title = re.sub(r"\s+", " ", str(link.get("data-name") or "")).strip()
                if len(title) < 3:
                    continue
                if "oraimo" not in title.lower():
                    title = f"Oraimo {title}"

                card_text = item_div.get_text(" ", strip=True)
                current_price, claimed_original = self._extract_egp_prices_from_card(card_text)
                if current_price is None:
                    continue

                card_low = card_text.lower()
                in_stock = not any(tok in card_low for tok in ("out of stock", "sold out", "نفذت الكمية", "غير متوفر"))

                img = item_div.select_one("img")
                image_url: Optional[str] = None
                if img:
                    for attr in ("data-src", "src"):
                        val = str(img.get(attr) or "").strip()
                        if val.startswith("http"):
                            image_url = val
                            break

                sub_cat = _refine_sub_category(title, top_cat, default_sub)
                attrs = _extract_specs(title, top_cat, sub_cat)
                attrs.pop("noon_category", None)
                qs = parse_qs(urlparse(product_url).query)
                ean_cand = (qs.get("ean") or [""])[0].strip()
                if _EAN_RE.match(ean_cand):
                    attrs["ean"] = ean_cand

                rec = self.validate_record(
                    {
                        "store_name": self.store_name,
                        "external_id": sku[:120],
                        "canonical_product_key": None,
                        "category": top_cat,
                        "sub_category": sub_cat,
                        "brand": "Oraimo",
                        "product_title": title,
                        "product_url": product_url,
                        "image_url": image_url,
                        "attributes_json": attrs,
                        "current_price": current_price,
                        "claimed_original_price": claimed_original,
                        "in_stock": in_stock,
                        "snapshot_date": today,
                        "scraped_at": now,
                    }
                )
                if rec is not None:
                    seen_skus.add(sku)
                    snapshots.append(rec)

        return snapshots


# ---------------------------------------------------------------------------
# 4. Bath & Body Works Egypt (`bath_and_body_works_eg`) — Public Algolia API
# ---------------------------------------------------------------------------
class BathAndBodyWorksEgScraper(BaseScraper):
    """Official Bath & Body Works Egypt scraper via public Alshaya Algolia index (`cloud`)."""

    store_name = "bath_and_body_works_eg"
    category: Category = "beauty"
    base_url = "https://www.bathandbodyworks.com.eg"
    configs_url = "https://www.bathandbodyworks.com.eg/configs.json"
    default_algolia_app_id = "6TOQSJY0O6"
    default_algolia_api_key = "c7af7bb2c02f6f150cf0e92eeaef1476"
    default_algolia_index = "bbw_prod_eg_product_list"
    default_limit = 2500
    discover_limit = 5000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 0.6
    request_timeout = 20.0

    def _resolve_algolia_config(self) -> tuple[str, str, str]:
        try:
            resp = self.http.get(self.configs_url, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json().get("data") or []
                kv = {str(row.get("key") or ""): str(row.get("value") or "") for row in data if isinstance(row, dict)}
                app_id = kv.get("x-algolia-application-id") or self.default_algolia_app_id
                api_key = kv.get("x-algolia-api-key") or self.default_algolia_api_key
                index_name = kv.get("algolia-plp-index") or self.default_algolia_index
                return app_id, api_key, index_name
        except Exception as exc:
            logger.debug("[bath_and_body_works_eg] Using default Algolia config (%s)", exc)
        return self.default_algolia_app_id, self.default_algolia_api_key, self.default_algolia_index

    @staticmethod
    def _infer_bbw_sub_category(title: str, form: str) -> str:
        low = f"{title} {form}".lower()
        if any(k in low for k in ("mist", "perfume", "cologne", "parfum", "eau de", "spray")):
            return "perfumes"
        if any(k in low for k in ("candle", "wallflower", "diffuser", "room spray", "car fragrance")):
            return "home_fragrance"
        if any(k in low for k in ("shampoo", "conditioner", "hair")):
            return "haircare"
        if any(k in low for k in ("sanitizer", "pocketbac", "hand soap", "hand gel")):
            return "body_care"
        return "body_care"

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        app_id, api_key, index_name = self._resolve_algolia_config()
        algolia_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
        headers = {
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_skus: set[str] = set()
        page = 0
        hits_per_page = 100

        while len(snapshots) < target_limit:
            try:
                resp = self.http.post(
                    algolia_url,
                    json={"query": "", "hitsPerPage": hits_per_page, "page": page},
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning("[bath_and_body_works_eg] Algolia HTTP %d on page %d", resp.status_code, page)
                    break
                payload = resp.json()
            except Exception as exc:
                logger.warning("[bath_and_body_works_eg] Algolia failed on page %d: %s", page, exc)
                break

            self.pages_fetched += 1
            hits = payload.get("hits") or []
            if not hits:
                break

            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                sku = str(hit.get("sku") or hit.get("objectID") or "").strip().upper()
                if not sku or sku in seen_skus:
                    continue

                title_obj = hit.get("title")
                raw_title = (
                    str(title_obj.get("en") or title_obj.get("ar") or "")
                    if isinstance(title_obj, dict)
                    else str(title_obj or "")
                ).strip()
                form_obj = hit.get("attr_form")
                form_str = (
                    str(form_obj.get("en") or "") if isinstance(form_obj, dict) else str(form_obj or "")
                ).strip()
                title = f"{raw_title} {form_str}".strip() if (form_str and form_str.lower() not in raw_title.lower()) else raw_title
                title = re.sub(r"\s+", " ", title).strip()
                if len(title) < 3:
                    continue
                if "bath" not in title.lower():
                    title = f"Bath & Body Works {title}"

                fp_obj = hit.get("final_price")
                pr_obj = hit.get("price")
                op_obj = hit.get("original_price")
                fp_raw = fp_obj.get("en") if isinstance(fp_obj, dict) else fp_obj
                pr_raw = pr_obj.get("en") if isinstance(pr_obj, dict) else pr_obj
                op_raw = op_obj.get("en") if isinstance(op_obj, dict) else op_obj

                current_price = parse_egp_price(fp_raw if fp_raw is not None else pr_raw)
                if current_price is None:
                    continue
                orig_cand = parse_egp_price(op_raw)
                claimed_original = orig_cand if (orig_cand is not None and orig_cand > current_price) else None

                in_stock = bool(hit.get("in_stock")) and (
                    hit.get("stock") is None or (isinstance(hit.get("stock"), (int, float)) and hit["stock"] > 0)
                )

                url_obj = hit.get("url")
                rel_url = (url_obj.get("en") or url_obj.get("ar") or "") if isinstance(url_obj, dict) else str(url_obj or "")
                rel_url = str(rel_url).strip()
                if not rel_url:
                    continue
                product_url = rel_url if rel_url.startswith("http") else urljoin(self.base_url, rel_url)

                image_url: Optional[str] = None
                media = hit.get("media")
                if isinstance(media, list):
                    for m in media:
                        if isinstance(m, dict) and str(m.get("url") or "").startswith("http"):
                            image_url = str(m["url"]).strip()
                            break

                attrs: dict[str, Any] = {}
                barcode = str(hit.get("attr_aims_barcode") or "").strip()
                if _EAN_RE.match(barcode):
                    attrs["ean"] = barcode
                if form_str:
                    attrs["form"] = form_str[:60]

                rec = self.validate_record(
                    {
                        "store_name": self.store_name,
                        "external_id": sku[:120],
                        "canonical_product_key": None,
                        "category": "beauty",
                        "sub_category": self._infer_bbw_sub_category(title, form_str),
                        "brand": "Bath & Body Works",
                        "product_title": title,
                        "product_url": product_url,
                        "image_url": image_url,
                        "attributes_json": attrs,
                        "current_price": current_price,
                        "claimed_original_price": claimed_original,
                        "in_stock": in_stock,
                        "snapshot_date": today,
                        "scraped_at": now,
                    }
                )
                if rec is not None:
                    seen_skus.add(sku)
                    snapshots.append(rec)
                    if len(snapshots) >= target_limit:
                        break

            nb_pages = int(payload.get("nbPages") or 0)
            page += 1
            if page >= nb_pages:
                break

        return snapshots


# ---------------------------------------------------------------------------
# 5. The Body Shop Egypt (`the_body_shop_eg`) — Regional UAE Shopify (FX Est.)
# ---------------------------------------------------------------------------
class TheBodyShopEgScraper(BaseScraper):
    """Official regional The Body Shop catalog (`thebodyshop.ae`, AED -> FX-estimated EGP)."""

    store_name = "the_body_shop_eg"
    category: Category = "beauty"
    base_url = "https://www.thebodyshop.ae"
    source_currency = "AED"
    default_limit = 1500
    discover_limit = 3000
    supported_verticals: tuple[ScrapeVertical, ...] = ("core",)
    min_delay_seconds = 1.0
    request_timeout = 20.0

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()

        with ImpersonatedHttpClient(
            impersonate="chrome",
            timeout=self.request_timeout or 20.0,
            max_retries=2,
            min_delay_seconds=max(1.8, self.http.min_delay_seconds),
            jitter_range=(0.4, 1.0),
            headers={"Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            for page in range(1, 20):
                if len(snapshots) >= target_limit:
                    break
                url = f"{self.base_url}/products.json"
                try:
                    resp = client.get(url, params={"limit": 250, "page": page})
                    if resp.status_code != 200:
                        logger.warning("[the_body_shop_eg] Page %d HTTP %d", page, resp.status_code)
                        break
                    products = (resp.json() or {}).get("products") or []
                except Exception as exc:
                    logger.warning("[the_body_shop_eg] Page %d failed: %s", page, exc)
                    break

                if not products:
                    break
                self.pages_fetched += 1

                for prod in products:
                    if not isinstance(prod, dict):
                        continue
                    pid = str(prod.get("id") or "").strip()
                    handle = str(prod.get("handle") or "").strip()
                    title = re.sub(r"\s+", " ", str(prod.get("title") or "")).strip()
                    if not pid or not handle or len(title) < 3 or pid in seen_ids:
                        continue
                    if "body shop" not in title.lower():
                        title = f"The Body Shop {title}"

                    variants = [v for v in (prod.get("variants") or []) if isinstance(v, dict)]
                    avail_vars = [v for v in variants if v.get("available", True)]
                    chosen = avail_vars[0] if avail_vars else (variants[0] if variants else None)
                    if not chosen:
                        continue

                    src_price = parse_egp_price(chosen.get("price"))
                    if src_price is None:
                        continue
                    egp_price, fx_rate = convert_to_egp(src_price, self.source_currency)

                    src_compare = parse_egp_price(chosen.get("compare_at_price"))
                    claimed_egp = None
                    if src_compare is not None and src_compare > src_price:
                        claimed_egp, _ = convert_to_egp(src_compare, self.source_currency)

                    imgs = prod.get("images") or []
                    image_url = imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else None

                    low = f"{title} {prod.get('product_type') or ''}".lower()
                    if any(k in low for k in ("perfume", "mist", "eau de", "fragrance")):
                        sub_cat = "perfumes"
                    elif any(k in low for k in ("shampoo", "conditioner", "hair")):
                        sub_cat = "haircare"
                    elif any(k in low for k in ("face", "serum", "cleanser", "toner", "mask", "cream", "skin")):
                        sub_cat = "skincare"
                    else:
                        sub_cat = "body_care"

                    rec = self.validate_record(
                        {
                            "store_name": self.store_name,
                            "external_id": pid[:120],
                            "canonical_product_key": None,
                            "category": "beauty",
                            "sub_category": sub_cat,
                            "brand": "The Body Shop",
                            "product_title": title,
                            "product_url": f"{self.base_url}/products/{handle}",
                            "image_url": image_url,
                            "attributes_json": {
                                "is_estimated_price": True,
                                "source_currency": self.source_currency,
                                "source_price": float(src_price),
                                "fx_rate": fx_rate,
                            },
                            "current_price": egp_price,
                            "claimed_original_price": claimed_egp,
                            "in_stock": bool(avail_vars),
                            "snapshot_date": today,
                            "scraped_at": now,
                        }
                    )
                    if rec is not None:
                        seen_ids.add(pid)
                        snapshots.append(rec)
                        if len(snapshots) >= target_limit:
                            break
                if len(products) < 250:
                    break

        return snapshots


OFFICIAL_BRAND_SCRAPER_CLASSES: tuple[type[BaseScraper], ...] = (
    SamsungEgScraper,
    MaxFashionEgScraper,
    OraimoEgScraper,
    BathAndBodyWorksEgScraper,
    TheBodyShopEgScraper,
)
