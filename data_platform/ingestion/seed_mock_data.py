"""
60-Day Realistic Mock History Generator for Price Truth Radar.

Generates 60 days of daily price snapshots for 100 realistic Egyptian e-commerce
products (50 electronics + 50 fashion), deliberately engineering all 5 discount
verdicts from CONTRACTS.md and scarcity flags for fashion items, then loads them
idempotently into `raw.raw_product_snapshots` on Neon PostgreSQL.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

RNG_SEED = 20261121
HISTORY_DAYS = 60


class RawProductSnapshot(BaseModel):
    store_name: str = Field(..., min_length=1, max_length=100)
    external_id: str = Field(..., min_length=1, max_length=120)
    canonical_product_key: Optional[str] = Field(default=None, max_length=160)
    category: str = Field(..., pattern="^(electronics|fashion)$")
    sub_category: str = Field(..., min_length=1, max_length=80)
    brand: str = Field(..., min_length=1, max_length=100)
    product_title: str = Field(..., min_length=1)
    product_url: str = Field(..., min_length=1)
    image_url: Optional[str] = None
    attributes_json: dict[str, Any]
    current_price: Decimal = Field(..., gt=0)
    claimed_original_price: Optional[Decimal] = Field(default=None, gt=0)
    in_stock: bool
    snapshot_date: date
    scraped_at: datetime


@dataclass(frozen=True)
class ProductSpec:
    store_name: str
    external_id: str
    canonical_product_key: Optional[str]
    category: str
    sub_category: str
    brand: str
    product_title: str
    base_price: float
    attributes_base: dict[str, Any]
    verdict_profile: str  # FAKE_DISCOUNT | ALL_TIME_LOW | GENUINE_DEAL | PRESALE_HIKE | NORMAL_PRICE
    scarce: bool = False
    out_of_stock_end: bool = False


STORE_DOMAINS: dict[str, str] = {
    "btech": "https://btech.com/en/p",
    "sigma": "https://www.sigma-computer.com/item",
    "2b": "https://2b.com.eg/en/product",
    "dubai_phone": "https://dubaiphone.net/products",
    "cairo_street": "https://cairostreet.eg/products",
    "nile_threads": "https://nilethreads.com/products",
    "urban_eg": "https://urbaneg.store/products",
}

STORE_PRICE_FACTOR: dict[str, float] = {
    "sigma": 0.96,
    "dubai_phone": 0.99,
    "2b": 1.03,
    "btech": 1.06,
    "cairo_street": 1.00,
    "nile_threads": 1.00,
    "urban_eg": 1.00,
}

# Realistic verdict profiles cycled carefully so every category and store
# displays all 5 verdict archetypes with strong representation.
ELECTRONICS_CANONICAL_CATALOG: list[dict[str, Any]] = [
    # Smartphones (6 canonical products -> 17 listings)
    {
        "key": "samsung_s24_ultra_256gb_12gb",
        "sub_category": "smartphones",
        "brand": "Samsung",
        "title": "Samsung Galaxy S24 Ultra 256GB 12GB RAM",
        "base_price": 53500,
        "attrs": {"ram_gb": 12, "storage_gb": 256, "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("sigma", "GENUINE_DEAL"),
            ("2b", "PRESALE_HIKE"),
            ("dubai_phone", "ALL_TIME_LOW"),
        ],
    },
    {
        "key": "apple_iphone_15_pro_max_256gb",
        "sub_category": "smartphones",
        "brand": "Apple",
        "title": "Apple iPhone 15 Pro Max 256GB Natural Titanium",
        "base_price": 64000,
        "attrs": {"ram_gb": 8, "storage_gb": 256, "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("2b", "NORMAL_PRICE"),
            ("dubai_phone", "GENUINE_DEAL"),
        ],
    },
    {
        "key": "xiaomi_redmi_note_13_pro_256gb_8gb",
        "sub_category": "smartphones",
        "brand": "Xiaomi",
        "title": "Xiaomi Redmi Note 13 Pro 256GB 8GB RAM",
        "base_price": 14500,
        "attrs": {"ram_gb": 8, "storage_gb": 256, "warranty": "local"},
        "stores": [
            ("btech", "PRESALE_HIKE"),
            ("sigma", "ALL_TIME_LOW"),
            ("dubai_phone", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "samsung_a55_5g_256gb_8gb",
        "sub_category": "smartphones",
        "brand": "Samsung",
        "title": "Samsung Galaxy A55 5G 256GB 8GB RAM",
        "base_price": 21500,
        "attrs": {"ram_gb": 8, "storage_gb": 256, "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("2b", "GENUINE_DEAL"),
            ("dubai_phone", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "oppo_reno_11_5g_256gb_12gb",
        "sub_category": "smartphones",
        "brand": "OPPO",
        "title": "OPPO Reno 11 5G 256GB 12GB RAM",
        "base_price": 18900,
        "attrs": {"ram_gb": 12, "storage_gb": 256, "warranty": "local"},
        "stores": [
            ("btech", "NORMAL_PRICE"),
            ("dubai_phone", "ALL_TIME_LOW"),
        ],
    },
    {
        "key": "apple_iphone_15_128gb",
        "sub_category": "smartphones",
        "brand": "Apple",
        "title": "Apple iPhone 15 128GB Black",
        "base_price": 42500,
        "attrs": {"ram_gb": 6, "storage_gb": 128, "warranty": "international"},
        "stores": [
            ("2b", "FAKE_DISCOUNT"),
            ("dubai_phone", "GENUINE_DEAL"),
        ],
    },
    # Laptops (5 canonical products -> 14 listings)
    {
        "key": "lenovo_loq_15_i5_rtx4050_16gb_512gb",
        "sub_category": "laptops",
        "brand": "Lenovo",
        "title": "Lenovo LOQ 15IRH8 Core i5-12450H RTX 4050 16GB 512GB",
        "base_price": 41000,
        "attrs": {"ram_gb": 16, "storage_gb": 512, "gpu": "RTX 4050", "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("sigma", "ALL_TIME_LOW"),
            ("2b", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "hp_victus_15_r5_rtx2050_16gb_512gb",
        "sub_category": "laptops",
        "brand": "HP",
        "title": "HP Victus 15 Ryzen 5 7535HS RTX 2050 16GB 512GB",
        "base_price": 33500,
        "attrs": {"ram_gb": 16, "storage_gb": 512, "gpu": "RTX 2050", "warranty": "local"},
        "stores": [
            ("sigma", "GENUINE_DEAL"),
            ("2b", "PRESALE_HIKE"),
            ("btech", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "apple_macbook_air_m2_13_8gb_256gb",
        "sub_category": "laptops",
        "brand": "Apple",
        "title": "Apple MacBook Air 13 M2 8GB 256GB Midnight",
        "base_price": 52000,
        "attrs": {"ram_gb": 8, "storage_gb": 256, "chip": "Apple M2", "warranty": "international"},
        "stores": [
            ("btech", "PRESALE_HIKE"),
            ("sigma", "GENUINE_DEAL"),
            ("2b", "FAKE_DISCOUNT"),
            ("dubai_phone", "ALL_TIME_LOW"),
        ],
    },
    {
        "key": "asus_tuf_f15_i7_rtx4060_16gb_1tb",
        "sub_category": "laptops",
        "brand": "ASUS",
        "title": "ASUS TUF Gaming F15 Core i7-13700H RTX 4060 16GB 1TB",
        "base_price": 58000,
        "attrs": {"ram_gb": 16, "storage_gb": 1024, "gpu": "RTX 4060", "warranty": "local"},
        "stores": [
            ("sigma", "ALL_TIME_LOW"),
            ("2b", "FAKE_DISCOUNT"),
        ],
    },
    {
        "key": "dell_inspiron_15_3520_i5_8gb_512gb",
        "sub_category": "laptops",
        "brand": "Dell",
        "title": "Dell Inspiron 15 3520 Core i5-1235U 8GB 512GB",
        "base_price": 23500,
        "attrs": {"ram_gb": 8, "storage_gb": 512, "warranty": "local"},
        "stores": [
            ("btech", "NORMAL_PRICE"),
            ("2b", "GENUINE_DEAL"),
        ],
    },
    # Monitors (4 canonical products -> 9 listings)
    {
        "key": "lg_ultragear_27gp850_27_qhd_165hz",
        "sub_category": "monitors",
        "brand": "LG",
        "title": "LG UltraGear 27GP850-B 27-Inch QHD Nano IPS 165Hz",
        "base_price": 16500,
        "attrs": {"screen_inch": 27, "refresh_hz": 165, "panel": "IPS", "warranty": "local"},
        "stores": [
            ("sigma", "ALL_TIME_LOW"),
            ("2b", "FAKE_DISCOUNT"),
        ],
    },
    {
        "key": "samsung_odyssey_g5_27_qhd_144hz",
        "sub_category": "monitors",
        "brand": "Samsung",
        "title": "Samsung Odyssey G5 27-Inch Curved QHD 144Hz",
        "base_price": 12800,
        "attrs": {"screen_inch": 27, "refresh_hz": 144, "panel": "VA", "warranty": "local"},
        "stores": [
            ("btech", "PRESALE_HIKE"),
            ("sigma", "GENUINE_DEAL"),
            ("2b", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "aoc_24g2sp_24_fhd_165hz",
        "sub_category": "monitors",
        "brand": "AOC",
        "title": "AOC 24G2SP 24-Inch FHD IPS 165Hz Gaming Monitor",
        "base_price": 8200,
        "attrs": {"screen_inch": 24, "refresh_hz": 165, "panel": "IPS", "warranty": "local"},
        "stores": [
            ("sigma", "NORMAL_PRICE"),
            ("2b", "FAKE_DISCOUNT"),
        ],
    },
    {
        "key": "msi_g274qpf_27_qhd_170hz",
        "sub_category": "monitors",
        "brand": "MSI",
        "title": "MSI G274QPF 27-Inch Rapid IPS QHD 170Hz",
        "base_price": 14200,
        "attrs": {"screen_inch": 27, "refresh_hz": 170, "panel": "IPS", "warranty": "local"},
        "stores": [
            ("sigma", "GENUINE_DEAL"),
            ("btech", "PRESALE_HIKE"),
        ],
    },
    # Headphones (3 canonical products -> 8 listings)
    {
        "key": "sony_wh1000xm5_anc_black",
        "sub_category": "headphones",
        "brand": "Sony",
        "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
        "base_price": 17500,
        "attrs": {"anc": True, "battery_hours": 30, "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("2b", "NORMAL_PRICE"),
            ("dubai_phone", "ALL_TIME_LOW"),
        ],
    },
    {
        "key": "apple_airpods_pro_2_usbc",
        "sub_category": "headphones",
        "brand": "Apple",
        "title": "Apple AirPods Pro 2nd Gen USB-C MagSafe",
        "base_price": 13200,
        "attrs": {"anc": True, "battery_hours": 30, "warranty": "international"},
        "stores": [
            ("btech", "PRESALE_HIKE"),
            ("2b", "GENUINE_DEAL"),
            ("dubai_phone", "NORMAL_PRICE"),
        ],
    },
    {
        "key": "anker_soundcore_q45_anc",
        "sub_category": "headphones",
        "brand": "Anker",
        "title": "Anker Soundcore Space Q45 Adaptive ANC Headphones",
        "base_price": 6400,
        "attrs": {"anc": True, "battery_hours": 50, "warranty": "local"},
        "stores": [
            ("btech", "FAKE_DISCOUNT"),
            ("dubai_phone", "NORMAL_PRICE"),
        ],
    },
]

# 2 single-store electronics items -> total 50 electronics listings
ELECTRONICS_EXCLUSIVES: list[dict[str, Any]] = [
    {
        "key": None,
        "store": "sigma",
        "sub_category": "headphones",
        "brand": "HyperX",
        "title": "HyperX Cloud III Wired Gaming Headset Black/Red",
        "base_price": 4650,
        "attrs": {"anc": False, "connectivity": "USB-C / 3.5mm", "warranty": "local"},
        "verdict": "ALL_TIME_LOW",
    },
    {
        "key": None,
        "store": "dubai_phone",
        "sub_category": "smartphones",
        "brand": "Realme",
        "title": "Realme 12 Pro+ 5G 256GB 12GB RAM Submarine Blue",
        "base_price": 19800,
        "attrs": {"ram_gb": 12, "storage_gb": 256, "warranty": "local"},
        "verdict": "GENUINE_DEAL",
    },
]

FASHION_CATALOG: list[tuple[str, str, str, str, float, str, bool]] = [
    # (store, sub_category, brand, title, base_price, verdict, scarce)
    # Hoodies (14)
    ("cairo_street", "hoodies", "Cairo Street", "Cairo Street Heavyweight Oversized Hoodie Charcoal", 1450, "FAKE_DISCOUNT", True),
    ("cairo_street", "hoodies", "Cairo Street", "Cairo Street Downtown Boxy Zip Hoodie Jet Black", 1650, "ALL_TIME_LOW", False),
    ("cairo_street", "hoodies", "Cairo Street", "Cairo Street Nile Graphic Fleece Hoodie Cream", 1550, "GENUINE_DEAL", True),
    ("cairo_street", "hoodies", "Cairo Street", "Cairo Street Acid Wash Pullover Hoodie Slate", 1700, "PRESALE_HIKE", False),
    ("cairo_street", "hoodies", "Cairo Street", "Cairo Street Essential Terry Hoodie Olive", 1350, "NORMAL_PRICE", False),
    ("nile_threads", "hoodies", "Nile Threads", "Nile Threads Egyptian Cotton Drop-Shoulder Hoodie Sand", 1600, "FAKE_DISCOUNT", True),
    ("nile_threads", "hoodies", "Nile Threads", "Nile Threads Heritage Embroidered Hoodie Forest", 1850, "GENUINE_DEAL", False),
    ("nile_threads", "hoodies", "Nile Threads", "Nile Threads Zamalek Studio Half-Zip Hoodie Ecru", 1900, "PRESALE_HIKE", True),
    ("nile_threads", "hoodies", "Nile Threads", "Nile Threads Minimalist Crest Hoodie Navy", 1500, "NORMAL_PRICE", False),
    ("nile_threads", "hoodies", "Nile Threads", "Nile Threads Brushed Fleece Hoodie Burgundy", 1400, "ALL_TIME_LOW", False),
    ("urban_eg", "hoodies", "Urban EG", "Urban EG Street Code Heavy Hoodie Ash Grey", 1550, "FAKE_DISCOUNT", False),
    ("urban_eg", "hoodies", "Urban EG", "Urban EG Nocturne Oversized Hoodie Washed Black", 1750, "GENUINE_DEAL", True),
    ("urban_eg", "hoodies", "Urban EG", "Urban EG Concrete Capsule Zip Hoodie Stone", 1800, "NORMAL_PRICE", False),
    ("urban_eg", "hoodies", "Urban EG", "Urban EG Maadi Club Archival Hoodie Mocha", 1650, "ALL_TIME_LOW", True),
    # Sneakers (12)
    ("cairo_street", "sneakers", "Cairo Street", "Cairo Street Retro Court Leather Sneakers White/Green", 3200, "FAKE_DISCOUNT", True),
    ("cairo_street", "sneakers", "Cairo Street", "Cairo Street Chunky Runner Sneakers Triple Black", 3600, "ALL_TIME_LOW", False),
    ("cairo_street", "sneakers", "Cairo Street", "Cairo Street Suede Low-Top Sneakers Sand/Gum", 2950, "GENUINE_DEAL", False),
    ("cairo_street", "sneakers", "Cairo Street", "Cairo Street Metro Canvas High-Top Sneakers Ecru", 2400, "NORMAL_PRICE", False),
    ("nile_threads", "sneakers", "Nile Threads", "Nile Threads Alexandria Leather Trainer Off-White", 3450, "PRESALE_HIKE", True),
    ("nile_threads", "sneakers", "Nile Threads", "Nile Threads Oasis Mesh Trail Sneakers Olive/Bone", 3850, "FAKE_DISCOUNT", False),
    ("nile_threads", "sneakers", "Nile Threads", "Nile Threads Court Classic 88 Sneakers Chalk/Navy", 3100, "GENUINE_DEAL", True),
    ("nile_threads", "sneakers", "Nile Threads", "Nile Threads Minimal Cup-Sole Sneakers Slate", 2800, "NORMAL_PRICE", False),
    ("urban_eg", "sneakers", "Urban EG", "Urban EG Velocity Knit Runners Charcoal/Volt", 3500, "ALL_TIME_LOW", True),
    ("urban_eg", "sneakers", "Urban EG", "Urban EG Distressed Skate Sneakers Bone/Grey", 2900, "FAKE_DISCOUNT", False),
    ("urban_eg", "sneakers", "Urban EG", "Urban EG Horizon Nubuck Sneakers Taupe", 3700, "PRESALE_HIKE", False),
    ("urban_eg", "sneakers", "Urban EG", "Urban EG Street Low 01 Sneakers Black/White", 2650, "NORMAL_PRICE", False),
    # Tees (12)
    ("cairo_street", "tees", "Cairo Street", "Cairo Street 280GSM Boxy Tee Washed Black", 680, "FAKE_DISCOUNT", False),
    ("cairo_street", "tees", "Cairo Street", "Cairo Street Vintage Cairo Typography Tee Off-White", 720, "GENUINE_DEAL", True),
    ("cairo_street", "tees", "Cairo Street", "Cairo Street Garment-Dyed Pocket Tee Sage", 620, "NORMAL_PRICE", False),
    ("cairo_street", "tees", "Cairo Street", "Cairo Street Heavy Jersey Oversized Tee Espresso", 690, "PRESALE_HIKE", False),
    ("nile_threads", "tees", "Nile Threads", "Nile Threads Giza Supima Crew Tee Pure White", 750, "ALL_TIME_LOW", False),
    ("nile_threads", "tees", "Nile Threads", "Nile Threads Delta Embroidered Logo Tee Navy", 700, "FAKE_DISCOUNT", True),
    ("nile_threads", "tees", "Nile Threads", "Nile Threads Relaxed Pique Polo Tee Sand", 890, "GENUINE_DEAL", False),
    ("nile_threads", "tees", "Nile Threads", "Nile Threads Everyday Combed Cotton Tee Heather Grey", 580, "NORMAL_PRICE", False),
    ("urban_eg", "tees", "Urban EG", "Urban EG Backprint Graphic Tee Charcoal", 740, "FAKE_DISCOUNT", True),
    ("urban_eg", "tees", "Urban EG", "Urban EG Waffle Knit Longline Tee Bone", 820, "ALL_TIME_LOW", False),
    ("urban_eg", "tees", "Urban EG", "Urban EG Drop-Shoulder Essential Tee Forest", 650, "NORMAL_PRICE", False),
    ("urban_eg", "tees", "Urban EG", "Urban EG Studio Capsule Heavy Tee Terracotta", 760, "PRESALE_HIKE", False),
    # Jeans (12)
    ("cairo_street", "jeans", "Cairo Street", "Cairo Street Baggy Carpenter Denim Jeans Vintage Blue", 1850, "FAKE_DISCOUNT", True),
    ("cairo_street", "jeans", "Cairo Street", "Cairo Street Wide-Leg Raw Selvedge Jeans Indigo", 2100, "ALL_TIME_LOW", False),
    ("cairo_street", "jeans", "Cairo Street", "Cairo Street Relaxed Straight Jeans Washed Black", 1650, "GENUINE_DEAL", False),
    ("cairo_street", "jeans", "Cairo Street", "Cairo Street Cargo Utility Denim Jeans Charcoal", 1950, "NORMAL_PRICE", False),
    ("nile_threads", "jeans", "Nile Threads", "Nile Threads Tapered Comfort Stretch Jeans Mid Blue", 1550, "PRESALE_HIKE", False),
    ("nile_threads", "jeans", "Nile Threads", "Nile Threads Loose Fit 90s Denim Jeans Light Wash", 1750, "FAKE_DISCOUNT", True),
    ("nile_threads", "jeans", "Nile Threads", "Nile Threads Heritage Straight Jeans Deep Indigo", 1800, "GENUINE_DEAL", False),
    ("nile_threads", "jeans", "Nile Threads", "Nile Threads Everyday Slim-Straight Jeans Onyx", 1600, "NORMAL_PRICE", False),
    ("urban_eg", "jeans", "Urban EG", "Urban EG Skater Baggy Denim Jeans Acid Grey", 1900, "ALL_TIME_LOW", True),
    ("urban_eg", "jeans", "Urban EG", "Urban EG Distressed Knee Straight Jeans Blue", 1700, "FAKE_DISCOUNT", False),
    ("urban_eg", "jeans", "Urban EG", "Urban EG Pleated Wide Denim Trousers Ecru", 2050, "PRESALE_HIKE", False),
    ("urban_eg", "jeans", "Urban EG", "Urban EG Classic Regular Fit Jeans Dark Wash", 1500, "NORMAL_PRICE", False),
]


def build_product_specs() -> list[ProductSpec]:
    specs: list[ProductSpec] = []
    idx = 1

    # 48 matched electronics listings (18 canonical keys)
    for item in ELECTRONICS_CANONICAL_CATALOG:
        for store_slug, verdict in item["stores"]:
            factor = STORE_PRICE_FACTOR[store_slug]
            store_base = round(item["base_price"] * factor / 10.0) * 10.0
            # Introduce subtle store title variation to test clean title normalization
            title_suffix = ""
            if store_slug == "btech":
                title_suffix = " - Official Warranty"
            elif store_slug == "sigma":
                title_suffix = " (Egypt)"
            specs.append(
                ProductSpec(
                    store_name=store_slug,
                    external_id=f"EL-{idx:04d}",
                    canonical_product_key=item["key"],
                    category="electronics",
                    sub_category=item["sub_category"],
                    brand=item["brand"],
                    product_title=f"{item['title']}{title_suffix}",
                    base_price=store_base,
                    attributes_base=dict(item["attrs"]),
                    verdict_profile=verdict,
                )
            )
            idx += 1

    # 2 exclusive electronics listings -> 50 total electronics
    for exc in ELECTRONICS_EXCLUSIVES:
        specs.append(
            ProductSpec(
                store_name=exc["store"],
                external_id=f"EL-{idx:04d}",
                canonical_product_key=exc["key"],
                category="electronics",
                sub_category=exc["sub_category"],
                brand=exc["brand"],
                product_title=exc["title"],
                base_price=float(exc["base_price"]),
                attributes_base=dict(exc["attrs"]),
                verdict_profile=exc["verdict"],
            )
        )
        idx += 1

    # 50 fashion listings
    f_idx = 1
    for store_slug, sub_cat, brand, title, base_price, verdict, scarce in FASHION_CATALOG:
        all_sizes = (
            ["40", "41", "42", "43", "44", "45"]
            if sub_cat == "sneakers"
            else ["S", "M", "L", "XL", "XXL"]
        )
        specs.append(
            ProductSpec(
                store_name=store_slug,
                external_id=f"FA-{f_idx:04d}",
                canonical_product_key=None,
                category="fashion",
                sub_category=sub_cat,
                brand=brand,
                product_title=title,
                base_price=float(base_price),
                attributes_base={
                    "all_sizes": all_sizes,
                    "total_sizes": len(all_sizes),
                },
                verdict_profile=verdict,
                scarce=scarce,
                out_of_stock_end=(f_idx in (19, 44)),
            )
        )
        f_idx += 1

    assert len(specs) == 100, f"Expected 100 products, got {len(specs)}"
    return specs


def round_egp(price: float, category: str) -> Decimal:
    step = 50.0 if (category == "electronics" and price >= 5000) else 10.0
    rounded = max(step, round(price / step) * step)
    return Decimal(f"{rounded:.2f}")


def generate_snapshots(specs: list[ProductSpec], end_date: date) -> list[RawProductSnapshot]:
    rng = random.Random(RNG_SEED)
    start_date = end_date - timedelta(days=HISTORY_DAYS - 1)
    snapshots: list[RawProductSnapshot] = []

    for prod_idx, spec in enumerate(specs):
        base = spec.base_price
        verdict = spec.verdict_profile

        # Subtle raw casing/whitespace messiness on a few rows so silver staging cleans them
        raw_brand = f"  {spec.brand}  " if prod_idx % 7 == 0 else spec.brand
        raw_title = f"  {spec.product_title}  " if prod_idx % 9 == 0 else spec.product_title

        domain = STORE_DOMAINS[spec.store_name]
        slug = spec.external_id.lower()
        product_url = f"{domain}/{slug}"
        image_url = f"https://cdn.pricetruthradar.eg/images/{spec.category}/{slug}.jpg"

        # Pre-generate deterministic parameters per product
        fake_bump = rng.uniform(0.00, 0.04)
        fake_claimed_markup = rng.uniform(0.18, 0.34)
        atl_drop = rng.uniform(0.12, 0.22)
        genuine_past_dip = rng.uniform(0.22, 0.28)
        genuine_now_drop = rng.uniform(0.12, 0.17)
        hike_pct = rng.uniform(0.15, 0.24)
        past_dip_start = rng.randint(15, 25)
        recent_change_days = rng.randint(3, 6)

        for day_offset in range(HISTORY_DAYS):
            snap_date = start_date + timedelta(days=day_offset)
            days_from_end = (HISTORY_DAYS - 1) - day_offset

            # Gentle baseline drift (+/- 2% piecewise weekly)
            week_bucket = day_offset // 7
            weekly_noise = ((hash((spec.external_id, week_bucket)) % 5) - 2) * 0.006
            price_val = base * (1.0 + weekly_noise)
            claimed_orig: Optional[Decimal] = None

            if verdict == "FAKE_DISCOUNT":
                if days_from_end < recent_change_days:
                    price_val = base * (1.0 + fake_bump)
                    claimed_orig = round_egp(price_val * (1.0 + fake_claimed_markup), spec.category)
                elif 20 <= day_offset <= 24:
                    # Brief small promo earlier
                    price_val = base * 0.97
                    claimed_orig = round_egp(base * 1.12, spec.category)

            elif verdict == "ALL_TIME_LOW":
                if days_from_end < recent_change_days:
                    # Strict new 60-day minimum, >= 12% below 60d median
                    price_val = base * (1.0 - atl_drop)
                    claimed_orig = round_egp(base, spec.category)
                else:
                    # Keep historical prices clearly above the final drop
                    price_val = base * (1.0 + abs(weekly_noise))

            elif verdict == "GENUINE_DEAL":
                if past_dip_start <= day_offset <= past_dip_start + 3:
                    # Deeper flash-sale dip earlier so min_historical_price < current_price
                    price_val = base * (1.0 - genuine_past_dip)
                    claimed_orig = round_egp(base, spec.category)
                elif days_from_end < recent_change_days:
                    price_val = base * (1.0 - genuine_now_drop)
                    claimed_orig = round_egp(base, spec.category)

            elif verdict == "PRESALE_HIKE":
                if days_from_end < 8:
                    # Price quietly hiked >= 15% with no claimed strikethrough discount
                    price_val = base * (1.0 + hike_pct)
                    claimed_orig = None
                else:
                    price_val = base * (1.0 + weekly_noise * 0.5)

            else:  # NORMAL_PRICE
                price_val = base * (1.0 + weekly_noise)
                # Occasional minor honest 4% strikethrough well below 10%
                if days_from_end == 0 and prod_idx % 5 == 0:
                    claimed_orig = round_egp(price_val * 1.04, spec.category)

            current_price_dec = round_egp(price_val, spec.category)
            if claimed_orig is not None and claimed_orig <= current_price_dec:
                claimed_orig = None

            # Stock & fashion size availability evolution
            in_stock = True
            attrs = dict(spec.attributes_base)
            if spec.category == "fashion":
                all_sizes: list[str] = list(attrs.pop("all_sizes"))
                total_sizes = len(all_sizes)
                if spec.out_of_stock_end and days_from_end < 2:
                    avail_sizes: list[str] = []
                    in_stock = False
                elif spec.scarce:
                    # Gradually sell down over 60 days to 1 remaining size (< 25%)
                    if day_offset < 20:
                        avail_sizes = all_sizes[:]
                    elif day_offset < 40:
                        avail_sizes = all_sizes[:3]
                    elif day_offset < 52:
                        avail_sizes = all_sizes[:2]
                    else:
                        avail_sizes = all_sizes[:1]
                else:
                    # Healthy size availability (3 to all sizes)
                    if day_offset < 30:
                        avail_sizes = all_sizes[:]
                    else:
                        keep = max(3, total_sizes - (prod_idx % 2))
                        avail_sizes = all_sizes[:keep]

                attrs = {
                    "available_sizes": avail_sizes,
                    "total_sizes": total_sizes,
                }
            else:
                # One electronics item briefly out of stock mid-month
                if prod_idx in (7, 29) and 35 <= day_offset <= 37:
                    in_stock = False

            scraped_at = datetime.combine(snap_date, time(3, 0, 0), tzinfo=timezone.utc).replace(tzinfo=None)

            snapshots.append(
                RawProductSnapshot(
                    store_name=spec.store_name,
                    external_id=spec.external_id,
                    canonical_product_key=spec.canonical_product_key,
                    category=spec.category,
                    sub_category=spec.sub_category,
                    brand=raw_brand,
                    product_title=raw_title,
                    product_url=product_url,
                    image_url=image_url,
                    attributes_json=attrs,
                    current_price=current_price_dec,
                    claimed_original_price=claimed_orig,
                    in_stock=in_stock,
                    snapshot_date=snap_date,
                    scraped_at=scraped_at,
                )
            )

    return snapshots


DDL_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS raw.raw_product_snapshots (
    store_name              VARCHAR(100) NOT NULL,
    external_id             VARCHAR(120) NOT NULL,
    canonical_product_key   VARCHAR(160),
    category                VARCHAR(50)  NOT NULL,
    sub_category            VARCHAR(80)  NOT NULL,
    brand                   VARCHAR(100) NOT NULL,
    product_title           TEXT         NOT NULL,
    product_url             TEXT         NOT NULL,
    image_url               TEXT,
    attributes_json         JSONB        NOT NULL,
    current_price           NUMERIC(12,2) NOT NULL,
    claimed_original_price  NUMERIC(12,2),
    in_stock                BOOLEAN      NOT NULL,
    snapshot_date           DATE         NOT NULL,
    scraped_at              TIMESTAMP    NOT NULL,
    PRIMARY KEY (store_name, external_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_raw_snapshots_date
    ON raw.raw_product_snapshots (snapshot_date);
"""

INSERT_SQL = """
INSERT INTO raw.raw_product_snapshots (
    store_name,
    external_id,
    canonical_product_key,
    category,
    sub_category,
    brand,
    product_title,
    product_url,
    image_url,
    attributes_json,
    current_price,
    claimed_original_price,
    in_stock,
    snapshot_date,
    scraped_at
) VALUES %s
ON CONFLICT (store_name, external_id, snapshot_date) DO UPDATE SET
    canonical_product_key  = EXCLUDED.canonical_product_key,
    category               = EXCLUDED.category,
    sub_category           = EXCLUDED.sub_category,
    brand                  = EXCLUDED.brand,
    product_title          = EXCLUDED.product_title,
    product_url            = EXCLUDED.product_url,
    image_url              = EXCLUDED.image_url,
    attributes_json        = EXCLUDED.attributes_json,
    current_price          = EXCLUDED.current_price,
    claimed_original_price = EXCLUDED.claimed_original_price,
    in_stock               = EXCLUDED.in_stock,
    scraped_at             = EXCLUDED.scraped_at;
"""


def load_to_neon(snapshots: list[RawProductSnapshot]) -> int:
    db_url = os.getenv("DATABASE_URL_ADMIN")
    if not db_url:
        raise RuntimeError("DATABASE_URL_ADMIN is not set in environment / .env")

    rows = [
        (
            s.store_name,
            s.external_id,
            s.canonical_product_key,
            s.category,
            s.sub_category,
            s.brand,
            s.product_title,
            s.product_url,
            s.image_url,
            json.dumps(s.attributes_json),
            s.current_price,
            s.claimed_original_price,
            s.in_stock,
            s.snapshot_date,
            s.scraped_at,
        )
        for s in snapshots
    ]

    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(DDL_SQL)
                cur.execute("TRUNCATE TABLE raw.raw_product_snapshots;")
                execute_values(cur, INSERT_SQL, rows, page_size=1000)
                cur.execute("SELECT COUNT(*) FROM raw.raw_product_snapshots;")
                total_rows = int(cur.fetchone()[0])
    finally:
        conn.close()

    return total_rows


def main() -> None:
    end_date = date.today()
    specs = build_product_specs()
    snapshots = generate_snapshots(specs, end_date=end_date)
    total_loaded = load_to_neon(snapshots)
    electronics_count = sum(1 for s in specs if s.category == "electronics")
    fashion_count = sum(1 for s in specs if s.category == "fashion")
    canonical_keys = {s.canonical_product_key for s in specs if s.canonical_product_key}
    print(
        f"Seeded {total_loaded} rows into raw.raw_product_snapshots "
        f"({electronics_count} electronics + {fashion_count} fashion across {HISTORY_DAYS} days; "
        f"{len(canonical_keys)} cross-store canonical keys; end_date={end_date.isoformat()})."
    )


if __name__ == "__main__":
    main()
