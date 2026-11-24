"""
Config-driven Magento 2 GraphQL adapter (`MagentoGraphQLBaseScraper`).

Supports both plain HTTP (`PoliteHttpClient`) and optional TLS impersonation
(`ImpersonatedHttpClient` via `curl_cffi`, `impersonate="chrome"`) with graceful
403/WAF handling. Parses `sku`/EAN, `final_price`, `regular_price`, `stock_status`,
`small_image`/`image`, `categories`, and pagination across search queries.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import math
import re
from typing import Any, Optional

from ..base import (
    BaseScraper,
    Category,
    ImpersonatedHttpClient,
    RawProductSnapshot,
    ScrapeVertical,
    ThrottledResponseError,
    parse_egp_price,
    utc_now_naive,
)
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)
from ..two_b import _normalize_brand

logger = logging.getLogger(__name__)

_DEFAULT_GQL_QUERY = """
query SearchProducts($search: String!, $pageSize: Int!, $currentPage: Int!) {
  products(search: $search, pageSize: $pageSize, currentPage: $currentPage) {
    total_count
    page_info {
      current_page
      total_pages
    }
    items {
      name
      sku
      url_key
      stock_status
      small_image { url }
      thumbnail { url }
      categories { name }
      price_range {
        minimum_price {
          final_price { value currency }
          regular_price { value }
        }
      }
    }
  }
}
""".strip()

_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")
_WEIGHT_OPTION_TITLE_RE = re.compile(r"(?:\bweight\b|\bportion\b|\bpack\s*weight\b|وزن|الوزن)", re.I)
_WEIGHT_VALUE_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(g|gm|gr|gram|grams|kg|kgs|kilo|kilos|ml|l|liter|litre|جم|جرام|كجم|كيلو)\b",
    re.I,
)
_TITLE_HAS_WEIGHT_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:g|gm|gr|gram|grams|kg|kgs|kilo|ml|l|liter|litre)\b|\d+(?:\.\d+)?\s*(?:جم|جرام|كجم|كيلو))",
    re.I,
)


def _normalize_weight_option_label(raw_label: str) -> Optional[str]:
    """Normalize a Magento customizable weight option label like '125 gm' -> '125g', '0.5 kg' -> '500g'."""
    text = re.sub(r"\s+", " ", (raw_label or "").strip())
    if not text:
        return None
    m = _WEIGHT_VALUE_RE.search(text)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ("kg", "kgs", "kilo", "kilos", "كجم", "كيلو"):
        if val < 1.0:
            grams = int(round(val * 1000))
            return f"{grams}g" if grams > 0 else None
        s = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{s}kg"
    if unit in ("g", "gm", "gr", "gram", "grams", "جم", "جرام"):
        grams = int(round(val))
        return f"{grams}g" if grams > 0 else None
    if unit in ("l", "liter", "litre"):
        s = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{s}L"
    if unit == "ml":
        ml = int(round(val))
        return f"{ml}ml" if ml > 0 else None
    return None


def _apply_option_modifier(
    base_price: Decimal, mod_price: Decimal, price_type: str
) -> Optional[Decimal]:
    """Compute effective option price given a Magento base price and option modifier."""
    ptype = (price_type or "FIXED").upper()
    if ptype == "PERCENT":
        eff = base_price * (Decimal("1") + (mod_price / Decimal("100")))
    else:
        eff = base_price + mod_price
    if eff <= Decimal("0"):
        return None
    return eff.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _extract_custom_weight_pricing(
    item: dict[str, Any],
    current_price: Decimal,
    regular_price: Optional[Decimal],
    max_final_price: Optional[Decimal],
) -> tuple[Optional[Decimal], Optional[str], dict[str, Any]]:
    """
    Resolve true same-unit `claimed_original_price` and selected weight label for
    Magento 2 weighted/customizable products (e.g. Gourmet Egypt deli/produce items).

    Magento stores like Gourmet model weighted items with base `regular_price` = 1kg
    and a required negative-PERCENT `Weight` option (e.g. `125g` = `-87.5%`).
    Without inspecting `options` / `special_price` / `maximum_price`, the 1kg base
    price leaks as a bogus 50%–87.5% `claimed_original_price`.
    """
    has_special_key = "special_price" in item
    special_price = parse_egp_price(item.get("special_price")) if item.get("special_price") is not None else None
    has_real_special = (
        special_price is not None
        and regular_price is not None
        and special_price < regular_price
    )

    options = item.get("options") if isinstance(item.get("options"), list) else []
    weight_entries: list[dict[str, Any]] = []
    any_negative_option = False

    for opt in options:
        if not isinstance(opt, dict):
            continue
        opt_title = str(opt.get("title") or "").strip()
        raw_values = opt.get("value")
        values = raw_values if isinstance(raw_values, list) else ([raw_values] if isinstance(raw_values, dict) else [])
        is_weight_opt = bool(_WEIGHT_OPTION_TITLE_RE.search(opt_title))

        parsed_entries: list[dict[str, Any]] = []
        for val in values:
            if not isinstance(val, dict):
                continue
            v_title = str(val.get("title") or "").strip()
            raw_mod = val.get("price")
            try:
                mod_dec = Decimal(str(raw_mod)) if raw_mod is not None else Decimal("0")
            except Exception:
                mod_dec = Decimal("0")
            if mod_dec < Decimal("0"):
                any_negative_option = True
            ptype = str(val.get("price_type") or "FIXED").upper()
            norm_label = _normalize_weight_option_label(v_title)
            if is_weight_opt or norm_label is not None:
                parsed_entries.append(
                    {
                        "label": norm_label or v_title,
                        "mod": mod_dec,
                        "price_type": ptype,
                    }
                )
        if parsed_entries and (is_weight_opt or any(e["mod"] < Decimal("0") for e in parsed_entries)):
            weight_entries.extend(parsed_entries)

    selected_label: Optional[str] = None
    selected_entry: Optional[dict[str, Any]] = None
    extra_attrs: dict[str, Any] = {}

    effective_base = special_price if has_real_special else regular_price
    if weight_entries and effective_base is not None:
        option_prices: list[Decimal] = []
        best_diff: Optional[Decimal] = None
        for entry in weight_entries:
            eff = _apply_option_modifier(effective_base, entry["mod"], entry["price_type"])
            if eff is None:
                continue
            option_prices.append(eff)
            diff = abs(eff - current_price)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                selected_entry = entry

        # Accept the matched option when within 2% (or 1 EGP) of current_price
        if selected_entry is not None and best_diff is not None:
            tol = max(Decimal("1.00"), current_price * Decimal("0.02"))
            if best_diff <= tol and selected_entry.get("label"):
                selected_label = str(selected_entry["label"])

        if len(option_prices) > 1:
            min_opt = min(current_price, *option_prices)
            max_opt = max(current_price, *option_prices)
            extra_attrs["variant_count"] = len(option_prices)
            extra_attrs["variant_min_price"] = float(min_opt)
            extra_attrs["variant_max_price"] = float(max_opt)

    # Determine claimed_original_price safely
    has_negative_weight = any(e["mod"] < Decimal("0") for e in weight_entries)
    option_driven_gap = (
        has_negative_weight
        or any_negative_option
        or (
            has_special_key
            and not has_real_special
            and max_final_price is not None
            and max_final_price > current_price
        )
    )

    if option_driven_gap:
        if has_real_special and regular_price is not None and selected_entry is not None:
            # Compute same-weight original price so a true promo on a weighted item is preserved
            same_weight_orig = _apply_option_modifier(
                regular_price, selected_entry["mod"], selected_entry["price_type"]
            )
            claimed_original = (
                same_weight_orig
                if (same_weight_orig is not None and same_weight_orig > current_price)
                else None
            )
        else:
            claimed_original = None
    else:
        claimed_original = (
            regular_price if (regular_price is not None and regular_price > current_price) else None
        )

    return claimed_original, selected_label, extra_attrs


class MagentoGraphQLBaseScraper(BaseScraper):
    """Config-driven Magento 2 `/graphql` scraper (plain HTTP or `curl_cffi`)."""

    store_name: str = ""
    category: Category = "groceries"
    base_url: str = ""
    graphql_url: str = ""
    product_url_prefix: str = "/en/"  # joined with url_key
    product_url_suffix: str = ""  # e.g. ".html"
    use_impersonation: bool = False
    use_post: bool = False
    store_header: Optional[str] = None
    default_brand: str = ""
    override_brand: bool = False
    gql_query: str = _DEFAULT_GQL_QUERY
    search_queries: tuple[tuple[str, Category, str], ...] = ()  # (sub_category, category, query)
    exclude_category_terms: tuple[str, ...] = ()
    default_limit: int = 200
    discover_limit: int = 900
    groceries_limit: int = 250
    discover_groceries_limit: int = 900
    supported_verticals: tuple[ScrapeVertical, ...] = ("groceries",)
    min_delay_seconds: float = 1.5
    request_timeout: float = 25.0
    page_size: int = 24

    def _clean_title(self, raw_title: str) -> str:
        cleaned = re.sub(r"^\s*[-–—]+\s*", "", raw_title or "")
        return re.sub(r"\s+", " ", cleaned).strip()

    def _build_product_url(self, url_key: str) -> str:
        clean_key = url_key.strip().lstrip("/")
        prefix = self.product_url_prefix
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        if not prefix.endswith("/"):
            prefix += "/"
        return f"{self.base_url.rstrip('/')}{prefix}{clean_key}{self.product_url_suffix}"

    def _extract_ean(self, sku: str, url_key: str) -> Optional[str]:
        digits = re.sub(r"\D", "", sku or "")
        if _EAN_RE.match(digits):
            return digits
        if m := re.search(r"-(\d{8}(?:\d{4,6})?)$", url_key or ""):
            return m.group(1)
        return None

    def _parse_item(
        self,
        item: dict[str, Any],
        default_sub: str,
        cat: Category,
        snapshot_date: Any,
        scraped_at: Any,
    ) -> Optional[RawProductSnapshot]:
        sku = str(item.get("sku") or "").strip()
        url_key = str(item.get("url_key") or "").strip()
        title = self._clean_title(str(item.get("name") or ""))
        if not sku or not url_key or len(title) < 3:
            return None

        price_range = item.get("price_range") if isinstance(item.get("price_range"), dict) else {}
        min_price = price_range.get("minimum_price") if isinstance(price_range.get("minimum_price"), dict) else {}
        max_price = price_range.get("maximum_price") if isinstance(price_range.get("maximum_price"), dict) else {}
        final_obj = min_price.get("final_price") if isinstance(min_price.get("final_price"), dict) else {}
        regular_obj = min_price.get("regular_price") if isinstance(min_price.get("regular_price"), dict) else {}
        max_final_obj = max_price.get("final_price") if isinstance(max_price.get("final_price"), dict) else {}

        current_price = parse_egp_price(final_obj.get("value"))
        if current_price is None:
            return None
        regular_price = parse_egp_price(regular_obj.get("value"))
        max_final_price = parse_egp_price(max_final_obj.get("value"))
        claimed_original, selected_weight_label, weight_extra_attrs = _extract_custom_weight_pricing(
            item, current_price, regular_price, max_final_price
        )
        if selected_weight_label:
            compact_title = re.sub(r"\s+", "", title).lower()
            if selected_weight_label.lower() not in compact_title and not _TITLE_HAS_WEIGHT_RE.search(title):
                title = f"{title} - {selected_weight_label}"
            elif selected_weight_label.lower() not in compact_title:
                title = f"{title} ({selected_weight_label})"

        image_url: Optional[str] = None
        for img_key in ("small_image", "image", "thumbnail"):
            img_obj = item.get(img_key)
            if isinstance(img_obj, dict) and img_obj.get("url"):
                cand = str(img_obj["url"]).strip()
                if cand.startswith("http") and "placeholder" not in cand.lower():
                    image_url = cand
                    break

        cat_names = [
            str(c.get("name")).strip()
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        cat_low = " ".join(cat_names).lower()
        if self.exclude_category_terms and any(term in cat_low for term in self.exclude_category_terms):
            return None

        ean = self._extract_ean(sku, url_key)
        external_id = (ean or sku)[:120]

        # Guard against variable-weight GS1 PLU (`20%`) deli/produce items leaking a 1 kg base
        # regular_price as a bogus >= 50% strikethrough discount on a fractional weight step.
        if (
            cat == "groceries"
            and claimed_original is not None
            and ean
            and ean.startswith("20")
            and claimed_original >= (current_price * Decimal("2.0"))
        ):
            claimed_original = None

        raw_brand: Optional[str] = None
        brand_field = item.get("brand")
        if isinstance(brand_field, dict) and brand_field.get("name"):
            raw_brand = str(brand_field["name"]).strip()
        elif isinstance(brand_field, str) and brand_field.strip():
            raw_brand = brand_field.strip()

        if cat == "groceries":
            brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, raw_brand or self.default_brand)
            sub_category = refine_grocery_sub_category(f"{title} {' '.join(cat_names)}", default_sub)
        elif self.override_brand and self.default_brand:
            brand = self.default_brand
            sub_category = default_sub
        else:
            brand = _normalize_brand(raw_brand or self.default_brand or None, title)
            sub_category = default_sub

        attrs: dict[str, Any] = {f"{self.store_name}_category": cat_names[0] if cat_names else sub_category}
        if ean:
            attrs["ean"] = ean
        if selected_weight_label:
            attrs["variant_label"] = selected_weight_label
        if weight_extra_attrs:
            attrs.update(weight_extra_attrs)
        if cat == "groceries":
            pkg = parse_grocery_packaging(
                title,
                extra_text=selected_weight_label or "",
                raw_payload={"ean": ean} if ean else None,
            )
            if selected_weight_label:
                # Ensure the authoritative Weight option wins over any base unit token in title
                opt_pkg = parse_grocery_packaging(selected_weight_label)
                for k in ("net_weight_g", "net_volume_ml", "pack_size"):
                    if k in opt_pkg:
                        pkg[k] = opt_pkg[k]
            attrs.update(pkg)

        stock_status = str(item.get("stock_status") or "IN_STOCK").upper()
        in_stock = stock_status == "IN_STOCK"

        return self.validate_record(
            {
                "store_name": self.store_name,
                "external_id": external_id,
                "canonical_product_key": None,
                "category": cat,
                "sub_category": sub_category,
                "brand": brand[:100],
                "product_title": title,
                "product_url": self._build_product_url(url_key),
                "image_url": image_url,
                "attributes_json": attrs,
                "current_price": current_price,
                "claimed_original_price": claimed_original,
                "in_stock": in_stock,
                "snapshot_date": snapshot_date,
                "scraped_at": scraped_at,
            }
        )

    def _run_queries(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        queries = self.search_queries or ((self.category, self.category, "a"),)
        per_query_cap = max(2, math.ceil(target_limit / len(queries)))
        max_pages = 8 if self.mode == "discover" else (2 if target_limit <= 100 else 3)
        blocked = False

        extra_headers = {"Accept": "application/json, text/plain, */*"}
        if self.store_header:
            extra_headers["Store"] = self.store_header

        for default_sub, cat, query in queries:
            if len(snapshots) >= target_limit or blocked:
                break
            query_collected = 0

            for page in range(1, max_pages + 1):
                if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                    break

                logger.info("[%s] Fetching GraphQL query=%r (%s) page %d", self.store_name, query, default_sub, page)
                variables_dict = {"search": query, "pageSize": self.page_size, "currentPage": page}
                variables_json = (
                    f'{{"search": "{query}", "pageSize": {self.page_size}, "currentPage": {page}}}'
                )
                try:
                    if self.use_post:
                        post_headers = {"Content-Type": "application/json", **extra_headers}
                        post_body = {"query": self.gql_query, "variables": variables_dict}
                        if self.use_impersonation:
                            resp = fetcher.post(
                                self.graphql_url,
                                json=post_body,
                                headers=post_headers,
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                                check_throttle=False,
                            )
                        else:
                            resp = fetcher.post(
                                self.graphql_url,
                                json=post_body,
                                headers=post_headers,
                                min_delay_seconds=effective_delay,
                                timeout=self.request_timeout,
                            )
                    elif self.use_impersonation:
                        resp = fetcher.get(
                            self.graphql_url,
                            params={"query": self.gql_query, "variables": variables_json},
                            headers=extra_headers,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                            check_throttle=False,
                        )
                    else:
                        resp = fetcher.get(
                            self.graphql_url,
                            params={"query": self.gql_query, "variables": variables_json},
                            headers=extra_headers,
                            min_delay_seconds=effective_delay,
                            timeout=self.request_timeout,
                        )
                except ThrottledResponseError as exc:
                    logger.warning("[%s] WAF/403 block on query=%r (%s); exiting gracefully.", self.store_name, query, exc)
                    blocked = True
                    break
                except Exception as exc:
                    logger.warning("[%s] GraphQL error on query=%r page %d: %s", self.store_name, query, page, exc)
                    break

                self.pages_fetched += 1
                try:
                    payload = resp.json()
                except Exception:
                    logger.warning("[%s] Non-JSON GraphQL response (HTTP %s); exiting gracefully.", self.store_name, resp.status_code)
                    blocked = True
                    break

                if payload.get("errors"):
                    logger.warning("[%s] GraphQL errors for query=%r: %s", self.store_name, query, payload["errors"])
                    break

                products_block = (payload.get("data") or {}).get("products") or {}
                raw_items = products_block.get("items") or []
                if not raw_items:
                    break

                page_records: list[RawProductSnapshot] = []
                new_raw_skus = 0
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    sku_val = str(raw.get("sku") or "").strip()
                    if not sku_val or sku_val not in seen_ids:
                        new_raw_skus += 1
                    rec = self._parse_item(raw, default_sub, cat, today, now)
                    if rec is not None and rec.external_id not in seen_ids:
                        page_records.append(rec)

                page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                for rec in page_records:
                    if rec.external_id in seen_ids:
                        continue
                    seen_ids.add(rec.external_id)
                    snapshots.append(rec)
                    query_collected += 1
                    if len(snapshots) >= target_limit or query_collected >= per_query_cap:
                        break

                page_info = products_block.get("page_info") or {}
                total_pages = int(page_info.get("total_pages") or 1)
                if page >= total_pages or new_raw_skus == 0:
                    break

            self.category_counts[default_sub] = self.category_counts.get(default_sub, 0) + query_collected

        logger.info("[%s] Per-subcategory counts: %s", self.store_name, self.category_counts)
        return snapshots

    def _run_expand_queries(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        """Checkpointed incremental catalog expansion resuming from `(start_cursor, start_page)`."""
        now = utc_now_naive()
        today = now.date()
        snapshots: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)
        queries = self.search_queries or ((self.category, self.category, "a"),)

        start_q = 0
        start_p = self.start_page
        if self.start_cursor:
            try:
                cur_data = json.loads(self.start_cursor)
                if isinstance(cur_data, dict):
                    start_q = max(0, int(cur_data.get("q", 0)))
                    start_p = max(0, int(cur_data.get("page", self.start_page)))
            except Exception:
                start_q = 0
                start_p = self.start_page

        if start_q >= len(queries):
            start_q = 0
            start_p = 0

        extra_headers = {"Accept": "application/json, text/plain, */*"}
        if self.store_header:
            extra_headers["Store"] = self.store_header

        max_pages_budget = max(1, self.expand_max_pages)
        pages_used = 0
        cur_q = start_q
        page = start_p + 1
        last_good_q = start_q
        last_good_page = start_p
        had_error = False

        while cur_q < len(queries) and len(snapshots) < target_limit and pages_used < max_pages_budget:
            default_sub, cat, query = queries[cur_q]
            logger.info(
                "[%s] Expand GraphQL q=%d/%d (%r) page=%d",
                self.store_name,
                cur_q + 1,
                len(queries),
                query,
                page,
            )
            variables_dict = {"search": query, "pageSize": self.page_size, "currentPage": page}
            variables_json = json.dumps(variables_dict)
            try:
                if self.use_post:
                    post_headers = {"Content-Type": "application/json", **extra_headers}
                    post_body = {"query": self.gql_query, "variables": variables_dict}
                    post_kwargs: dict[str, Any] = {
                        "json": post_body,
                        "headers": post_headers,
                        "min_delay_seconds": effective_delay,
                        "timeout": self.request_timeout,
                    }
                    if self.use_impersonation:
                        post_kwargs["check_throttle"] = False
                    resp = fetcher.post(self.graphql_url, **post_kwargs)
                else:
                    get_kwargs: dict[str, Any] = {
                        "params": {"query": self.gql_query, "variables": variables_json},
                        "headers": extra_headers,
                        "min_delay_seconds": effective_delay,
                        "timeout": self.request_timeout,
                    }
                    if self.use_impersonation:
                        get_kwargs["check_throttle"] = False
                    resp = fetcher.get(self.graphql_url, **get_kwargs)
                payload = resp.json()
            except ThrottledResponseError as exc:
                logger.warning("[%s] Expand GraphQL WAF/403 on q=%r page=%d (%s).", self.store_name, query, page, exc)
                had_error = True
                break
            except Exception as exc:
                logger.warning("[%s] Expand GraphQL error on q=%r page=%d: %s", self.store_name, query, page, exc)
                had_error = True
                break

            self.pages_fetched += 1
            pages_used += 1
            if not isinstance(payload, dict) or payload.get("errors"):
                cur_q += 1
                page = 1
                last_good_q = cur_q
                last_good_page = 0
                continue

            products_block = (payload.get("data") or {}).get("products") or {}
            raw_items = products_block.get("items") or []
            if not raw_items:
                cur_q += 1
                page = 1
                last_good_q = cur_q
                last_good_page = 0
                continue

            q_added = 0
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                rec = self._parse_item(raw, default_sub, cat, today, now)
                if rec is not None and rec.external_id not in seen_ids:
                    seen_ids.add(rec.external_id)
                    snapshots.append(rec)
                    q_added += 1
                    if len(snapshots) >= target_limit:
                        break

            self.category_counts[default_sub] = self.category_counts.get(default_sub, 0) + q_added
            last_good_q = cur_q
            last_good_page = page

            page_info = products_block.get("page_info") or {}
            total_pages = int(page_info.get("total_pages") or 1)
            if page >= total_pages:
                cur_q += 1
                page = 1
                last_good_q = cur_q
                last_good_page = 0
            else:
                page += 1

        if not had_error or pages_used > 0:
            self._checkpoint_updated = True
            if cur_q >= len(queries):
                self.exhausted_catalog = True
                self.next_page = 0
                self.next_cursor = None
            else:
                self.exhausted_catalog = False
                self.next_page = last_good_page
                self.next_cursor = json.dumps({"q": last_good_q, "page": last_good_page})

        return snapshots

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        runner = self._run_expand_queries if self.mode == "expand" else self._run_queries
        if self.use_impersonation:
            with ImpersonatedHttpClient(
                impersonate="chrome",
                timeout=self.request_timeout or 30.0,
                max_retries=3,
                backoff_base=2.0,
                min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
                jitter_range=(0.3, 1.0),
            ) as client:
                return runner(client, target_limit)

        return runner(self.http, target_limit)
