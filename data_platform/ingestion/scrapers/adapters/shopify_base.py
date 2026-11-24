"""
Config-driven Shopify storefront adapter (`ShopifyBaseScraper`).

Uses plain HTTP (`PoliteHttpClient` / `httpx`) against public Shopify JSON endpoints:
  - `/collections/{handle}/products.json?limit=250&page={N}` (when `collection_handles` is set)
  - `/products.json?limit=250&page={N}` (default full catalog)

Supports all 4 verticals (`fashion`, `groceries`, `electronics`, `home_appliances`):
  - Parses EGP `price`, `compare_at_price` (kept only when strictly `> price`),
    `in_stock` (True if any variant is available), `image_url`, canonical `product_url`,
    `brand`/`vendor`, `sku` & `barcode` (EAN/GTIN when valid 8–14 digits).
  - For `category == "fashion"`: extracts `available_sizes` & `total_sizes` for scarcity tracking.
  - For `category == "groceries"`: runs `groceries.py` packaging, brand, and 7-subcategory normalization.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from ..base import (
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
from ..coupon_radar import scan_and_record_coupons
from ..groceries import (
    extract_grocery_brand,
    parse_grocery_packaging,
    refine_grocery_sub_category,
)

logger = logging.getLogger(__name__)

_SIZE_OPTION_NAMES = {"size", "sizes", "shoe size", "uk", "eu", "us", "المقاس", "مقاس"}
_EAN_RE = re.compile(r"^\d{8}(?:\d{4,6})?$")

_FASHION_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sunglass", "eyewear", "glasses", "optical", "نظارة", "نظاره", "عدس"), "eyewear"),
    (("watch", "ring", "bracelet", "necklace", "earring", "pendant", "jewelry", "jewellery", "ساعة", "خاتم"), "watches_jewelry"),
    (("sneaker", "trainer", "running", "loafers", "loafer", "boot", "sandal", "slipper", "mule", "heel", "flat", "clog", "shoe", "footwear"), "footwear"),
    (("bag", "handbag", "backpack", "tote", "crossbody", "clutch", "wallet", "duffle", "luggage", "belt", "cap", "hat", "scarf", "sock", "tie", "cravat", "accessory", "accessories"), "accessories"),
    (("dress", "abaya", "kaftan", "jumpsuit", "skirt", "gown"), "dresses"),
    (("jacket", "coat", "blazer", "vest", "gilet", "trench", "puffer", "bomber", "suit", "overcoat"), "jackets"),
    (("hoodie", "sweatshirt", "pullover", "cardigan", "sweater", "knit", "turtleneck", "crewneck"), "knitwear"),
    (("jean", "denim", "trouser", "pant", "chino", "jogger", "short", "legging", "cargo", "sweatpant"), "pants"),
    (("polo",), "polos"),
    (("t-shirt", "tshirt", "tee"), "tees"),
    (("shirt", "blouse", "top", "tunic", "chemise"), "shirts"),
)

_BEAUTY_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("perfume", "parfum", "eau de", "cologne", "fragrance", "body mist", "body splash", "oud", "musk", "عطر", "برفيوم"), "perfumes"),
    (("shampoo", "conditioner", "hair", "scalp", "henna", "keratin", "curl", "شعر", "شامبو"), "haircare"),
    (("lipstick", "lip glaze", "lip gloss", "mascara", "blush", "foundation", "concealer", "eyeliner", "powder", "makeup", "palette", "مكياج"), "makeup"),
    (("sunscreen", "sunblock", "spf", "sun shield", "واقي شمس"), "sunscreen"),
    (("cleanser", "face wash", "serum", "moisturizer", "toner", "retinol", "acne", "cream", "gel", "mask", "scrub", "skin", "غسول", "بشرة", "بشره"), "skincare"),
    (("body wash", "body butter", "lotion", "deodorant", "soap", "shower", "body care", "جسم"), "body_care"),
)

_HOME_FURNITURE_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mattress", "مرتبة", "مرتبه", "سوست"), "mattresses"),
    (("sheet", "pillow", "duvet", "bedspread", "comforter", "towel", "linen", "bedding", "ملاية", "ملايه", "مخدة", "لحاف", "فوط"), "bedding_linens"),
    (("cookware", "pot", "pan", "frying", "granite", "stainless", "kitchen", "kettle", "حلة", "طقم حلل", "مقلاة", "طاسة"), "cookware"),
    (("sofa", "couch", "sectional", "l-shape", "كنبة", "انتريه", "ركنة"), "sofas"),
    (("bed", "bedroom", "wardrobe", "سرير", "غرفة نوم", "نوم", "دولاب"), "beds"),
    (("table", "desk", "dining", "coffee table", "ترابيزة", "مكتب", "سفرة"), "tables"),
    (("chair", "stool", "bean bag", "pouf", "كرسي", "بين باج"), "chairs"),
    (("lamp", "light", "chandelier", "اضاءة", "إضاءة", "نجفة"), "lighting"),
    (("rug", "carpet", "curtain", "cushion", "mirror", "vase", "decor", "سجادة", "ستارة"), "home_decor"),
)

_HEALTH_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("protein", "whey", "creatine", "bcaa", "pre-workout", "preworkout", "mass gainer", "amino", "بروتين", "كرياتين"), "sports_nutrition"),
    (("vitamin", "magnesium", "zinc", "omega", "ashwagandha", "collagen", "probiotic", "multivitamin", "iron", "calcium", "فيتامين"), "vitamins"),
    (("supplement", "capsule", "tablet", "bundle", "fat burner", "مكمل"), "supplements"),
    (("pharmacy", "medical", "cream", "gel", "wash", "drop", "spray", "صيدلية"), "pharmacy"),
)

_SPORTS_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("treadmill", "bike", "elliptical", "dumbbell", "barbell", "weight", "bench", "pull up", "kettlebell", "gym", "مشاية", "عجلة", "دامبل"), "fitness_equipment"),
    (("boxing", "punching", "mma", "gloves", "ملاكمة"), "combat_sports"),
    (("shoe", "sneaker", "running", "cleat", "boot", "حذاء"), "sports_shoes"),
    (("short", "shirt", "jersey", "legging", "hoodie", "sock", "tracksuit", "top", "tight", "jacket"), "sportswear"),
)

_PET_CARE_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("litter", "رمل"), "cat_litter"),
    (("cat", "kitten", "feline", "قطط", "قط"), "cat_food"),
    (("dog", "puppy", "canine", "كلاب", "كلب"), "dog_food"),
    (("treat", "snack", "biscuit", "مكافآت"), "pet_treats"),
    (("shampoo", "brush", "groom", "collar", "leash", "bowl", "bed", "toy", "carrier"), "pet_accessories"),
)

_BABY_KIDS_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("puzzle", "toy", "lego", "doll", "game", "plush", "rc", "car", "لعبة", "العاب", "ألعاب"), "toys"),
    (("stroller", "car seat", "crib", "cot", "high chair", "walker", "swaddle", "blanket", "عربية اطفال"), "baby_gear"),
    (("desk", "bed", "bunk", "room", "furniture", "kids bundle"), "kids_furniture"),
    (("romper", "onesie", "dress", "shirt", "pants", "jacket", "shoe", "outfit", "cotton"), "kids_clothing"),
)

_ELECTRONICS_SUBCAT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    # Check phone/camera accessories FIRST so cases, lens protectors, and cages for iPhone/Galaxy
    # are never misclassified as smartphones.
    (
        (
            "magclick", "magsafe", "coehl", "nillkin", "frosted shield", "video cage", "smallrig",
            "lens protector", "screen protector", "tempered glass", "phone case", "back cover",
            "case ", " cover", "charger", "cable", "adapter", "power bank", "mount", "holder",
            "tripod", "حماية عدسات", "جراب", "كفر", "اسكرين", "شاحن", "كابل",
        ),
        "accessories",
    ),
    (("iphone", "galaxy", "smartphone", "mobile", "redmi", "xiaomi", "oppo", "realme"), "smartphones"),
    (("laptop", "macbook", "notebook", "thinkpad", "ideapad", "vivobook", "zenbook"), "laptops"),
    (("ipad", "tablet", "tab"), "tablets"),
    (("monitor", "screen"), "monitors"),
    (("headphone", "earbud", "airpods", "headset", "speaker", "audio"), "headphones"),
    (("watch", "band", "wearable"), "wearables"),
    (("rtx", "gtx", "gpu", "vga", "graphics"), "gpus"),
    (("cpu", "processor", "ryzen", "core i"), "cpus"),
    (("motherboard", "mainboard"), "motherboards"),
    (("ssd", "hdd", "nvme", "hard drive", "flash"), "storage"),
    (("ram", "ddr4", "ddr5", "memory"), "memory"),
    (("mouse", "keyboard", "gaming", "controller", "chair", "pad"), "peripherals"),
    (("tv", "television", "qled", "oled", "smart tv"), "tvs"),
    (("air conditioner", "split ac", "inverter ac"), "air_conditioners"),
    (("refrigerator", "fridge", "freezer"), "refrigerators"),
    (("washing machine", "washer", "dryer", "dishwasher"), "washing_machines"),
    (("microwave", "oven", "cooker", "air fryer", "blender", "kettle", "coffee", "vacuum", "heater", "fan"), "kitchen_appliances"),
)


def _normalize_size(raw: str) -> str:
    val = re.sub(r"\s+", " ", raw.strip())
    if not val:
        return ""
    low = val.lower()
    if low in {"default title", "default", "one size", "os", "free size", "free"}:
        return "One Size"
    if len(val) <= 5 and re.fullmatch(r"[0-9a-zA-Z./+-]+", val):
        return val.upper()
    return val[:20]


def _extract_fashion_sizes(raw_product: dict[str, Any]) -> tuple[list[str], int]:
    variants = raw_product.get("variants") or []
    options = raw_product.get("options") or []
    size_pos: Optional[int] = None
    for idx, opt in enumerate(options, start=1):
        if isinstance(opt, dict) and str(opt.get("name") or "").strip().lower() in _SIZE_OPTION_NAMES:
            size_pos = idx
            break

    all_sizes: list[str] = []
    avail_sizes: list[str] = []
    seen_all: set[str] = set()
    seen_avail: set[str] = set()

    for v in variants:
        if not isinstance(v, dict):
            continue
        raw_size = ""
        if size_pos is not None:
            raw_size = str(v.get(f"option{size_pos}") or "")
        else:
            for pos in (1, 2, 3):
                cand = str(v.get(f"option{pos}") or "").strip()
                if cand and re.fullmatch(r"(?:[2-5]?\d(?:\.5)?|XXS|XS|S|M|L|XL|2XL|3XL|4XL|5XL|XXL|XXXL)", cand, re.I):
                    raw_size = cand
                    break
            if not raw_size:
                raw_size = str(v.get("option1") or v.get("title") or "")

        norm = _normalize_size(raw_size)
        if not norm:
            continue
        if norm not in seen_all:
            seen_all.add(norm)
            all_sizes.append(norm)
        if bool(v.get("available")) and norm not in seen_avail:
            seen_avail.add(norm)
            avail_sizes.append(norm)

    if not all_sizes:
        any_avail = any(isinstance(v, dict) and bool(v.get("available")) for v in variants)
        return (["One Size"] if any_avail else []), 1
    return avail_sizes, len(all_sizes)


_DEFAULT_VARIANT_TITLES = frozenset({"default title", "default", "title", ""})


def _clean_variant_label(raw_variant: dict[str, Any]) -> Optional[str]:
    """Build a concise human-readable variant label (e.g. '160x230 cm' or 'Beige / 150*80 سم')."""
    raw_title = re.sub(r"\s+", " ", str(raw_variant.get("title") or "")).strip()
    if raw_title and raw_title.lower() not in _DEFAULT_VARIANT_TITLES:
        return raw_title[:80]
    parts: list[str] = []
    for pos in (1, 2, 3):
        val = re.sub(r"\s+", " ", str(raw_variant.get(f"option{pos}") or "")).strip()
        if val and val.lower() not in _DEFAULT_VARIANT_TITLES and val not in parts:
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


def _sample_price_variants(
    candidates: list[tuple[dict[str, Any], Decimal, Optional[str]]],
    max_variants: int,
) -> list[tuple[dict[str, Any], Decimal, Optional[str]]]:
    """Keep all distinct price-bearing variants up to `max_variants`, preserving min & max tiers."""
    if len(candidates) <= max_variants:
        return candidates
    # Sort deterministically by (price, variant_id) and sample evenly including min and max
    ordered = sorted(candidates, key=lambda item: (item[1], str(item[0].get("id") or "")))
    if max_variants <= 1:
        return [ordered[0]]
    step = (len(ordered) - 1) / (max_variants - 1)
    picked_indices = sorted({round(i * step) for i in range(max_variants)})
    return [ordered[idx] for idx in picked_indices]


class ShopifyBaseScraper(BaseScraper):
    """Config-driven Shopify `/products.json` & `/collections/{handle}/products.json` scraper."""

    store_name: str = ""
    category: Category = "fashion"
    base_url: str = ""
    default_brand: str = ""
    override_brand: bool = False
    default_limit: int = 180
    discover_limit: int = 950
    expand_max_pages: int = 6
    groceries_limit: int = 180
    discover_groceries_limit: int = 750
    max_variants_per_product: int = 12
    supported_verticals: tuple[ScrapeVertical, ...] = ("fashion",)
    collection_handles: tuple[tuple[str, Category, str], ...] = ()  # (sub_category, category, handle)
    min_delay_seconds: float = 1.2
    request_timeout: float = 25.0
    use_impersonation: bool = True
    per_page: int = 250
    skip_new_out_of_stock: bool = True

    def _resolve_sub_category(self, title: str, product_type: str, default_sub: Optional[str], cat: Category) -> str:
        if cat == "groceries":
            return refine_grocery_sub_category(f"{title} {product_type}", default_sub or "canned_sauces")
        hay = f"{product_type} {title}".lower()
        table_map: dict[str, tuple[tuple[tuple[tuple[str, ...], str], ...], str]] = {
            "fashion": (_FASHION_SUBCAT_KEYWORDS, "apparel"),
            "beauty": (_BEAUTY_SUBCAT_KEYWORDS, "beauty"),
            "home_furniture": (_HOME_FURNITURE_SUBCAT_KEYWORDS, "furniture"),
            "health": (_HEALTH_SUBCAT_KEYWORDS, "wellness"),
            "sports": (_SPORTS_SUBCAT_KEYWORDS, "sports_gear"),
            "pet_care": (_PET_CARE_SUBCAT_KEYWORDS, "pet_supplies"),
            "baby_kids": (_BABY_KIDS_SUBCAT_KEYWORDS, "kids"),
        }
        if cat in table_map:
            rules, fallback = table_map[cat]
            for kws, mapped in rules:
                if any(k in hay for k in kws):
                    return mapped
            return default_sub or (normalize_snake_slug(product_type, fallback=fallback, max_len=60) if product_type else fallback)
        for kws, mapped in _ELECTRONICS_SUBCAT_KEYWORDS:
            if any(k in hay for k in kws):
                return mapped
        return default_sub or (normalize_snake_slug(product_type, fallback="accessories", max_len=60) if product_type else "accessories")

    def _parse_product_variants(
        self,
        raw: dict[str, Any],
        cat: Category,
        default_sub: Optional[str],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> list[RawProductSnapshot]:
        """Parse a Shopify product JSON object into one or more variant-safe snapshots.

        - Price-differentiated multi-variant products (e.g. rugs 120x180 vs 200x300,
          mattresses, perfumes 50ml vs 100ml, pet food 300g vs 15kg) emit one
          deterministic `RawProductSnapshot` per distinct variant (`{pid}__v{vid}`),
          pairing `current_price` and `compare_at_price` strictly from that same variant.
        - Single-variant and uniform-price multi-variant products (e.g. apparel S/M/L
          at the exact same EGP price) emit one consolidated snapshot preserving
          `available_sizes` / `total_sizes` and full variant rollup metadata.
        """
        pid = raw.get("id")
        handle = str(raw.get("handle") or "").strip()
        title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
        if not pid or not handle or len(title) < 3:
            return []

        variants = raw.get("variants") if isinstance(raw.get("variants"), list) else []
        if not variants:
            return []

        valid_variants: list[tuple[dict[str, Any], Decimal, Optional[str]]] = []
        any_available = False
        for v in variants:
            if not isinstance(v, dict):
                continue
            p = parse_egp_price(v.get("price"))
            if p is None:
                continue
            if bool(v.get("available")):
                any_available = True
            valid_variants.append((v, p, _clean_variant_label(v)))

        if not valid_variants:
            return []

        all_prices = [p for _, p, _ in valid_variants]
        min_variant_price = min(all_prices)
        max_variant_price = max(all_prices)
        variant_count = len(valid_variants)
        parent_product_key = f"{self.store_name}::{pid}"
        split_by_variant = variant_count > 1 and max_variant_price > min_variant_price

        def _variant_ext_id(v_dict: dict[str, Any], p_val: Decimal, v_lbl: Optional[str]) -> str:
            raw_vid = v_dict.get("id")
            vid_str = str(raw_vid).strip() if raw_vid is not None else ""
            if vid_str:
                return f"{pid}__v{vid_str}"[:120]
            slug_lbl = normalize_snake_slug(v_lbl or str(p_val), fallback="var", max_len=40)
            return f"{pid}__v_{slug_lbl}"[:120]

        if split_by_variant:
            # Deduplicate variants that share identical (price, normalized_label) so
            # e.g. 5 colors of the same rug size at the same price don't bloat snapshots,
            # preferring in-stock (and tracked) representatives first.
            ordered_variants = sorted(
                valid_variants,
                key=lambda item: (
                    0 if bool(item[0].get("available")) else (1 if _variant_ext_id(item[0], item[1], item[2]) in self.tracked_external_ids else 2)
                ),
            )
            deduped: list[tuple[dict[str, Any], Decimal, Optional[str]]] = []
            seen_tier: set[tuple[Decimal, str]] = set()
            for v, p, lbl in ordered_variants:
                tier_key = (p, (lbl or "").lower())
                if tier_key in seen_tier:
                    continue
                seen_tier.add(tier_key)
                deduped.append((v, p, lbl))

            if self.skip_new_out_of_stock:
                eligible_deduped: list[tuple[dict[str, Any], Decimal, Optional[str]]] = []
                for v, p, lbl in deduped:
                    v_ext_id = _variant_ext_id(v, p, lbl)
                    if bool(v.get("available")) or v_ext_id in self.tracked_external_ids:
                        eligible_deduped.append((v, p, lbl))
                    else:
                        self.skipped_oos_count += 1
                if not eligible_deduped:
                    return []
                deduped = eligible_deduped

            # If multiple distinct variants exist with distinct labels/prices, emit up to cap
            emitted_variants = _sample_price_variants(deduped, self.max_variants_per_product)
            kept_prices = [p for _, p, _ in emitted_variants]
            min_variant_price = min(kept_prices)
            max_variant_price = max(kept_prices)
            variant_count = len(emitted_variants)
        else:
            single_ext_id = str(pid)[:120]
            if self.skip_new_out_of_stock and not any_available and single_ext_id not in self.tracked_external_ids:
                self.skipped_oos_count += 1
                return []
            # Single-variant or uniform-price multi-variant: prefer first in-stock variant
            chosen = next(
                (item for item in valid_variants if bool(item[0].get("available"))),
                valid_variants[0],
            )
            emitted_variants = [chosen]

        base_image_url: Optional[str] = None
        images = raw.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict) and images[0].get("src"):
            base_image_url = str(images[0]["src"]).strip()

        vendor = str(raw.get("vendor") or "").strip()
        product_type = str(raw.get("product_type") or "").strip()

        if cat == "groceries":
            brand = self.default_brand if self.override_brand and self.default_brand else extract_grocery_brand(title, vendor or self.default_brand)
        elif self.override_brand and self.default_brand:
            brand = self.default_brand
        else:
            brand = vendor or self.default_brand or "Unknown"

        sub_category = self._resolve_sub_category(title, product_type, default_sub, cat)
        base_product_url = f"{self.base_url.rstrip('/')}/products/{handle}"

        # Passive non-blocking promo-code radar (draft queue only — never auto-publishes)
        try:
            radar_texts: list[str] = [title]
            body_html = raw.get("body_html")
            if isinstance(body_html, str) and body_html:
                radar_texts.append(body_html)
            raw_tags = raw.get("tags")
            if isinstance(raw_tags, list) and raw_tags:
                radar_texts.append(" ".join(str(t) for t in raw_tags if t))
            elif isinstance(raw_tags, str) and raw_tags:
                radar_texts.append(raw_tags)
            excluded = {str(pid).strip().upper(), handle.upper()}
            for v, _, _ in valid_variants:
                v_sku = str(v.get("sku") or "").strip().upper()
                if v_sku:
                    excluded.add(v_sku)
            scan_and_record_coupons(
                self.store_name,
                radar_texts,
                source_url=base_product_url,
                excluded_tokens=excluded,
            )
        except Exception:
            pass

        records: list[RawProductSnapshot] = []
        for v, current_price, variant_label in emitted_variants:
            raw_vid = v.get("id")
            vid_str = str(raw_vid).strip() if raw_vid is not None else ""
            raw_compare = parse_egp_price(v.get("compare_at_price"))
            claimed_original = (
                raw_compare
                if (raw_compare is not None and raw_compare > current_price)
                else None
            )

            sku = str(v.get("sku") or "").strip()
            barcode = ""
            raw_bc = str(v.get("barcode") or "").strip()
            if raw_bc:
                cand_bc = re.sub(r"\D", "", raw_bc)
                if _EAN_RE.match(cand_bc):
                    barcode = cand_bc
            if not split_by_variant and (not sku or not barcode):
                for other_v, _, _ in valid_variants:
                    if not sku and other_v.get("sku"):
                        sku = str(other_v["sku"]).strip()
                    if not barcode and other_v.get("barcode"):
                        cand_bc = re.sub(r"\D", "", str(other_v["barcode"]).strip())
                        if _EAN_RE.match(cand_bc):
                            barcode = cand_bc

            variant_img = base_image_url
            feat_img = v.get("featured_image")
            if isinstance(feat_img, dict) and feat_img.get("src"):
                cand_img = str(feat_img["src"]).strip()
                if cand_img.startswith("http"):
                    variant_img = cand_img

            if split_by_variant:
                if vid_str:
                    ext_id = f"{pid}__v{vid_str}"[:120]
                    product_url = f"{base_product_url}?variant={vid_str}"
                else:
                    slug_lbl = normalize_snake_slug(variant_label or str(current_price), fallback="var", max_len=40)
                    ext_id = f"{pid}__v_{slug_lbl}"[:120]
                    product_url = base_product_url
                rec_title = _append_variant_to_title(title, variant_label)
                rec_in_stock = bool(v.get("available"))
            else:
                ext_id = str(pid)[:120]
                product_url = base_product_url
                rec_title = title
                rec_in_stock = any_available

            attrs: dict[str, Any] = {
                "parent_product_key": parent_product_key,
                "variant_count": variant_count,
                "variant_min_price": float(min_variant_price),
                "variant_max_price": float(max_variant_price),
            }
            if vid_str:
                attrs["variant_id"] = vid_str
            if variant_label:
                attrs["variant_label"] = variant_label
            if product_type:
                attrs["shopify_product_type"] = product_type
            if sku:
                attrs["sku"] = sku
            if barcode:
                attrs["ean"] = barcode

            if cat == "fashion":
                avail_sizes, total_sizes = _extract_fashion_sizes(raw)
                attrs["available_sizes"] = avail_sizes
                attrs["total_sizes"] = total_sizes
            elif cat == "groceries":
                attrs.update(parse_grocery_packaging(rec_title, raw_payload={"ean": barcode} if barcode else None))

            rec = self.validate_record(
                {
                    "store_name": self.store_name,
                    "external_id": ext_id,
                    "canonical_product_key": None,
                    "category": cat,
                    "sub_category": sub_category,
                    "brand": brand[:100],
                    "product_title": rec_title,
                    "product_url": product_url,
                    "image_url": variant_img,
                    "attributes_json": attrs,
                    "current_price": current_price,
                    "claimed_original_price": claimed_original,
                    "in_stock": rec_in_stock,
                    "snapshot_date": snapshot_date,
                    "scraped_at": scraped_at,
                }
            )
            if rec is not None:
                records.append(rec)

        return records

    def _parse_product(
        self,
        raw: dict[str, Any],
        cat: Category,
        default_sub: Optional[str],
        snapshot_date: Any,
        scraped_at: datetime,
    ) -> Optional[RawProductSnapshot]:
        """Single-record helper returning the first in-stock (or first) parsed variant."""
        recs = self._parse_product_variants(raw, cat, default_sub, snapshot_date, scraped_at)
        if not recs:
            return None
        return next((r for r in recs if r.in_stock), recs[0])

    def _scrape_with_fetcher(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)

        if self.collection_handles:
            endpoints: list[tuple[Optional[str], Category, str]] = [
                (sub, cat, f"{self.base_url.rstrip('/')}/collections/{handle}/products.json")
                for sub, cat, handle in self.collection_handles
            ]
            per_ep_cap = max(3, math.ceil(target_limit / len(endpoints)))
        else:
            endpoints = [(None, self.category, f"{self.base_url.rstrip('/')}/products.json")]
            per_ep_cap = target_limit

        for default_sub, cat, endpoint in endpoints:
            if len(collected) >= target_limit:
                break
            ep_collected = 0
            page = 1
            req_limit = min(self.per_page, max(20, per_ep_cap))
            max_pages = max(4, math.ceil(per_ep_cap / self.per_page) + 4)
            seen_raw_pids: set[str] = set()

            while len(collected) < target_limit and ep_collected < per_ep_cap and page <= max_pages:
                logger.info("[%s] Fetching Shopify JSON page %d (%s)", self.store_name, page, endpoint)
                try:
                    get_kwargs: dict[str, Any] = {
                        "params": {"limit": req_limit, "page": page},
                        "min_delay_seconds": effective_delay,
                        "timeout": self.request_timeout,
                    }
                    if self.use_impersonation:
                        get_kwargs["check_throttle"] = False
                    resp = fetcher.get(endpoint, **get_kwargs)
                    payload = resp.json()
                except Exception as exc:
                    logger.warning("[%s] Error fetching %s page %d: %s", self.store_name, endpoint, page, exc)
                    break

                self.pages_fetched += 1
                products = payload.get("products") if isinstance(payload, dict) else None
                if not isinstance(products, list) or not products:
                    break

                new_raw_products = 0
                page_records: list[RawProductSnapshot] = []
                for raw in products:
                    if not isinstance(raw, dict):
                        continue
                    raw_pid = str(raw.get("id") or "").strip()
                    if raw_pid:
                        if raw_pid not in seen_raw_pids:
                            seen_raw_pids.add(raw_pid)
                            new_raw_products += 1
                    else:
                        new_raw_products += 1
                    for rec in self._parse_product_variants(raw, cat, default_sub, snapshot_date, scraped_at):
                        if rec.external_id not in seen_ids:
                            page_records.append(rec)

                page_records = self.prioritize_tracked(page_records, lambda r: r.external_id)
                for rec in page_records:
                    if rec.external_id in seen_ids:
                        continue
                    seen_ids.add(rec.external_id)
                    collected.append(rec)
                    ep_collected += 1
                    if len(collected) >= target_limit or ep_collected >= per_ep_cap:
                        break

                if len(products) < req_limit or new_raw_products == 0:
                    break
                page += 1

            self.category_counts[default_sub or cat] = self.category_counts.get(default_sub or cat, 0) + ep_collected

        if self.skipped_oos_count > 0:
            logger.info(
                "[%s] Skipped %d brand-new out-of-stock Shopify items.",
                self.store_name,
                self.skipped_oos_count,
            )

        return collected

    def _scrape_expand_with_fetcher(self, fetcher: Any, target_limit: int) -> list[RawProductSnapshot]:
        """Checkpointed incremental catalog expansion resuming from `(start_cursor, start_page)`."""
        snapshot_date = datetime.now(timezone.utc).date()
        scraped_at = utc_now_naive()
        collected: list[RawProductSnapshot] = []
        seen_ids: set[str] = set()
        self.category_counts = {}
        effective_delay = max(self.min_delay_seconds, self.http.min_delay_seconds)

        if self.collection_handles:
            endpoints: list[tuple[Optional[str], Category, str]] = [
                (sub, cat, f"{self.base_url.rstrip('/')}/collections/{handle}/products.json")
                for sub, cat, handle in self.collection_handles
            ]
        else:
            endpoints = [(None, self.category, f"{self.base_url.rstrip('/')}/products.json")]

        start_ep = 0
        start_p = self.start_page
        if self.start_cursor:
            try:
                cur_data = json.loads(self.start_cursor)
                if isinstance(cur_data, dict):
                    start_ep = max(0, int(cur_data.get("ep", 0)))
                    start_p = max(0, int(cur_data.get("page", self.start_page)))
            except Exception:
                start_ep = 0
                start_p = self.start_page

        if start_ep >= len(endpoints):
            start_ep = 0
            start_p = 0

        max_pages_budget = max(1, self.expand_max_pages)
        req_limit = min(self.per_page, max(50, target_limit))
        pages_used = 0
        cur_ep = start_ep
        page = start_p + 1
        last_good_ep = start_ep
        last_good_page = start_p
        had_error = False
        seen_raw_pids_ep: set[str] = set()

        while cur_ep < len(endpoints) and len(collected) < target_limit and pages_used < max_pages_budget:
            default_sub, cat, endpoint = endpoints[cur_ep]
            logger.info(
                "[%s] Expand Shopify JSON ep=%d/%d page=%d (%s)",
                self.store_name,
                cur_ep + 1,
                len(endpoints),
                page,
                endpoint,
            )
            try:
                get_kwargs: dict[str, Any] = {
                    "params": {"limit": req_limit, "page": page},
                    "min_delay_seconds": effective_delay,
                    "timeout": self.request_timeout,
                }
                if self.use_impersonation:
                    get_kwargs["check_throttle"] = False
                resp = fetcher.get(endpoint, **get_kwargs)
                payload = resp.json()
            except ThrottledResponseError as exc:
                # Some Shopify themes restrict /products.json while allowing /collections/all/products.json
                if page == 1 and endpoint.endswith("/products.json") and "/collections/" not in endpoint:
                    alt_endpoint = f"{self.base_url.rstrip('/')}/collections/all/products.json"
                    logger.info("[%s] Retrying restricted /products.json via %s", self.store_name, alt_endpoint)
                    try:
                        resp = fetcher.get(alt_endpoint, **get_kwargs)
                        payload = resp.json()
                        endpoints[cur_ep] = (default_sub, cat, alt_endpoint)
                        endpoint = alt_endpoint
                    except Exception as alt_exc:
                        logger.warning("[%s] Expand WAF/throttle on %s (%s); failing fast.", self.store_name, alt_endpoint, alt_exc)
                        had_error = True
                        break
                else:
                    logger.warning("[%s] Expand WAF/throttle on %s page %d (%s); failing fast.", self.store_name, endpoint, page, exc)
                    had_error = True
                    break
            except Exception as exc:
                logger.warning("[%s] Expand error fetching %s page %d: %s", self.store_name, endpoint, page, exc)
                had_error = True
                break

            self.pages_fetched += 1
            pages_used += 1
            products = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(products, list) or not products:
                cur_ep += 1
                page = 1
                seen_raw_pids_ep.clear()
                last_good_ep = cur_ep
                last_good_page = 0
                continue

            new_raw_products = 0
            ep_added = 0
            for raw in products:
                if not isinstance(raw, dict):
                    continue
                raw_pid = str(raw.get("id") or "").strip()
                if raw_pid:
                    if raw_pid not in seen_raw_pids_ep:
                        seen_raw_pids_ep.add(raw_pid)
                        new_raw_products += 1
                else:
                    new_raw_products += 1
                for rec in self._parse_product_variants(raw, cat, default_sub, snapshot_date, scraped_at):
                    if rec.external_id in seen_ids:
                        continue
                    seen_ids.add(rec.external_id)
                    collected.append(rec)
                    ep_added += 1
                    if len(collected) >= target_limit:
                        break
                if len(collected) >= target_limit:
                    break

            self.category_counts[default_sub or cat] = self.category_counts.get(default_sub or cat, 0) + ep_added
            last_good_ep = cur_ep
            last_good_page = page

            if len(products) < req_limit or new_raw_products == 0:
                cur_ep += 1
                page = 1
                seen_raw_pids_ep.clear()
                last_good_ep = cur_ep
                last_good_page = 0
            else:
                page += 1

        if self.skipped_oos_count > 0:
            logger.info(
                "[%s] Expand skipped %d brand-new out-of-stock Shopify items.",
                self.store_name,
                self.skipped_oos_count,
            )

        if not had_error or pages_used > 0:
            self._checkpoint_updated = True
            if cur_ep >= len(endpoints):
                self.exhausted_catalog = True
                self.next_page = 0
                self.next_cursor = None
            else:
                self.exhausted_catalog = False
                self.next_page = last_good_page
                self.next_cursor = json.dumps({"ep": last_good_ep, "page": last_good_page})

        return collected

    def scrape(self, limit: Optional[int] = None) -> list[RawProductSnapshot]:
        target_limit = self.get_target_limit() if limit is None else limit
        if target_limit <= 0:
            return []

        runner = self._scrape_expand_with_fetcher if self.mode == "expand" else self._scrape_with_fetcher
        if self.use_impersonation:
            try:
                with ImpersonatedHttpClient(
                    impersonate="chrome",
                    timeout=self.request_timeout or 25.0,
                    max_retries=2,
                    backoff_base=2.0,
                    min_delay_seconds=max(self.min_delay_seconds, self.http.min_delay_seconds),
                    jitter_range=(0.2, 0.6),
                    headers={"Accept": "application/json, text/plain, */*"},
                ) as client:
                    return runner(client, target_limit)
            except ImportError:
                logger.warning("[%s] curl_cffi unavailable; falling back to PoliteHttpClient.", self.store_name)

        return runner(self.http, target_limit)
