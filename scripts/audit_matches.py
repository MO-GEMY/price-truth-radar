"""Read-only Cross-Store Matching Quality Audit Script for Asarak (أسعارك).

Audits `gold.mart_cross_store_matches` joined with `gold.mart_product_verdicts`
in a single lightweight read-only query (minimal Neon compute) to surface:
  1. Per-category match distribution & high-ratio counts (>=1.6x, >=2.0x, >=2.5x).
  2. Top suspicious high-price-ratio pairs (`max_price / min_price >= 1.6`) per category.
  3. Stratified deterministic sample of normal-gap pairs (`1.1x .. 1.59x`) per category
     to expose false positives hiding at similar price points.

Usage:
  python scripts/audit_matches.py
  python scripts/audit_matches.py --category electronics --top-high 25 --sample-normal 20
  python scripts/audit_matches.py --summary-only
  python scripts/audit_matches.py --json-out audit_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")


AUDIT_SQL = """
WITH match_rows AS (
    SELECT
        m.canonical_product_key,
        m.category,
        m.brand,
        m.product_title_clean,
        m.stores_count,
        m.lowest_price,
        m.highest_price,
        CASE WHEN m.lowest_price > 0
             THEN ROUND((m.highest_price / m.lowest_price)::numeric, 3)::float
             ELSE 1.0 END AS price_ratio,
        m.price_spread_pct
    FROM gold.mart_cross_store_matches m
    WHERE (%s IS NULL OR m.category = %s)
),
offer_titles AS (
    SELECT
        v.canonical_product_key,
        JSONB_AGG(
            JSONB_BUILD_OBJECT(
                'store', v.store_name,
                'price', v.current_price,
                'title', v.product_title,
                'sub_category', v.sub_category,
                'brand', v.brand,
                'in_stock', v.in_stock
            )
            ORDER BY v.current_price ASC, v.store_name ASC
        ) AS offers
    FROM gold.mart_product_verdicts v
    WHERE v.canonical_product_key IS NOT NULL
      AND (%s IS NULL OR v.category = %s)
    GROUP BY v.canonical_product_key
)
SELECT
    m.canonical_product_key,
    m.category,
    m.brand,
    m.stores_count,
    m.lowest_price,
    m.highest_price,
    m.price_ratio,
    m.price_spread_pct,
    COALESCE(o.offers, '[]'::jsonb) AS offers
FROM match_rows m
LEFT JOIN offer_titles o USING (canonical_product_key)
ORDER BY m.category ASC, m.price_ratio DESC, m.canonical_product_key ASC
"""


def _connect() -> Any:
    dsn = (
        os.getenv("DATABASE_URL_READONLY")
        or os.getenv("DATABASE_URL_ADMIN")
        or os.getenv("DATABASE_URL")
    )
    if not dsn:
        raise RuntimeError("No DATABASE_URL_READONLY / DATABASE_URL_ADMIN found in environment or .env")
    return psycopg2.connect(dsn)


def _format_offer_pair(offers: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not offers:
        return None, None
    # Prefer distinct-store min & max offers for clarity
    lo = offers[0]
    hi = offers[-1]
    if lo.get("store") == hi.get("store") and len(offers) > 2:
        for cand in reversed(offers):
            if cand.get("store") != lo.get("store"):
                hi = cand
                break
    return lo, hi


def _key_prefix(key: str) -> str:
    if not key:
        return "other"
    if key.startswith("ean_"):
        return "ean"
    if key.startswith("mpn_"):
        return "mpn"
    if key.startswith("er_code_"):
        return "er_code"
    if key.startswith("er_sim_"):
        return "er_sim"
    if key.startswith("er_"):
        return "er_other"
    if key.startswith("groc_"):
        return "groc"
    if key.startswith("hb_"):
        return "hb"
    if key.startswith("shoe_"):
        return "shoe"
    return "legacy_fp"


def run_audit(
    category: str | None = None,
    high_ratio_min: float = 1.6,
    top_high: int = 15,
    sample_normal: int = 15,
    summary_only: bool = False,
    json_out: str | None = None,
) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(AUDIT_SQL, (category, category, category, category))
            rows = cur.fetchall()

    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    key_source_counts: dict[str, int] = defaultdict(int)
    high_by_source: dict[str, int] = defaultdict(int)

    for r in rows:
        item = {
            "key": r[0],
            "source": _key_prefix(r[0]),
            "category": r[1] or "unknown",
            "brand": r[2] or "",
            "stores_count": int(r[3] or 0),
            "lowest_price": float(r[4] or 0.0),
            "highest_price": float(r[5] or 0.0),
            "price_ratio": float(r[6] or 1.0),
            "price_spread_pct": float(r[7] or 0.0),
            "offers": r[8] if isinstance(r[8], list) else [],
        }
        by_cat[item["category"]].append(item)
        key_source_counts[item["source"]] += 1
        if item["price_ratio"] >= high_ratio_min:
            high_by_source[item["source"]] += 1

    total_matches = len(rows)
    total_ge_16 = sum(1 for cat_rows in by_cat.values() for x in cat_rows if x["price_ratio"] >= 1.6)
    total_ge_20 = sum(1 for cat_rows in by_cat.values() for x in cat_rows if x["price_ratio"] >= 2.0)
    total_ge_25 = sum(1 for cat_rows in by_cat.values() for x in cat_rows if x["price_ratio"] >= 2.5)

    print("=" * 96)
    print(f"ASARAK CROSS-STORE MATCH AUDIT | Total Matches: {total_matches:,}")
    print(
        f"Ratio >= 1.6x: {total_ge_16:,} ({(total_ge_16/max(1,total_matches))*100:.1f}%) | "
        f">= 2.0x: {total_ge_20:,} ({(total_ge_20/max(1,total_matches))*100:.1f}%) | "
        f">= 2.5x: {total_ge_25:,} ({(total_ge_25/max(1,total_matches))*100:.1f}%)"
    )
    print("Key Sources (total / >=1.6x):")
    for src, cnt in sorted(key_source_counts.items(), key=lambda kv: -kv[1]):
        hcnt = high_by_source.get(src, 0)
        print(f"  {src:12s}: {cnt:6,d} total | {hcnt:5,d} high-ratio ({hcnt/max(1,cnt)*100:5.1f}%)")
    print("=" * 96)
    print(f"{'Category':18s} {'Total':>7s} {'>=1.6x':>7s} {'>=2.0x':>7s} {'>=2.5x':>7s} {'MedRatio':>9s} {'MaxRatio':>9s}")
    print("-" * 96)

    report: dict[str, Any] = {
        "total_matches": total_matches,
        "total_ge_16": total_ge_16,
        "total_ge_20": total_ge_20,
        "total_ge_25": total_ge_25,
        "key_sources": dict(key_source_counts),
        "high_by_source": dict(high_by_source),
        "categories": {},
    }

    for cat in sorted(by_cat.keys()):
        cat_rows = by_cat[cat]
        ratios = sorted(x["price_ratio"] for x in cat_rows)
        med_r = ratios[len(ratios) // 2] if ratios else 1.0
        max_r = ratios[-1] if ratios else 1.0
        ge16 = [x for x in cat_rows if x["price_ratio"] >= high_ratio_min]
        ge20 = [x for x in cat_rows if x["price_ratio"] >= 2.0]
        ge25 = [x for x in cat_rows if x["price_ratio"] >= 2.5]
        print(
            f"{cat:18s} {len(cat_rows):7,d} {len(ge16):7,d} {len(ge20):7,d} "
            f"{len(ge25):7,d} {med_r:8.2f}x {max_r:8.2f}x"
        )

        # Deterministic stratified sample in normal band [1.10x, 1.59x]
        normal_band = [x for x in cat_rows if 1.10 <= x["price_ratio"] < high_ratio_min]
        normal_band.sort(key=lambda x: hash(x["key"]) & 0xFFFFFFFF if False else (x["key"][-8:], x["key"]))
        # Use evenly spaced stride across key-sorted normal band for deterministic spread
        if len(normal_band) > sample_normal > 0:
            step = len(normal_band) / sample_normal
            sampled_normal = [normal_band[int(i * step)] for i in range(sample_normal)]
        else:
            sampled_normal = normal_band[:sample_normal]

        report["categories"][cat] = {
            "total": len(cat_rows),
            "ge_16": len(ge16),
            "ge_20": len(ge20),
            "ge_25": len(ge25),
            "median_ratio": med_r,
            "max_ratio": max_r,
            "top_high": ge16[:top_high],
            "sample_normal": sampled_normal,
        }

    if not summary_only:
        for cat in sorted(by_cat.keys()):
            cdata = report["categories"][cat]
            print(f"\n{'#' * 96}")
            print(f"CATEGORY: {cat} (total={cdata['total']:,}, >=1.6x={cdata['ge_16']:,})")
            print(f"{'#' * 96}")

            print(f"\n--- Top High-Ratio Pairs (>= {high_ratio_min}x, showing up to {top_high}) ---")
            for idx, item in enumerate(cdata["top_high"], 1):
                lo, hi = _format_offer_pair(item["offers"])
                print(
                    f"[{idx:02d}] {item['price_ratio']:.2f}x | key={item['key']} ({item['source']}) | stores={item['stores_count']}"
                )
                if lo:
                    print(f"     MIN ({lo['store']:18s} {lo['price']:>10,.0f} EGP): {lo['title'][:95]}")
                if hi:
                    print(f"     MAX ({hi['store']:18s} {hi['price']:>10,.0f} EGP): {hi['title'][:95]}")

            print(f"\n--- Stratified Normal-Gap Sample (1.10x .. {high_ratio_min - 0.01:.2f}x, n={len(cdata['sample_normal'])}) ---")
            for idx, item in enumerate(cdata["sample_normal"], 1):
                lo, hi = _format_offer_pair(item["offers"])
                print(
                    f"[{idx:02d}] {item['price_ratio']:.2f}x | key={item['key']} ({item['source']})"
                )
                if lo:
                    print(f"     MIN ({lo['store']:18s} {lo['price']:>10,.0f} EGP): {lo['title'][:95]}")
                if hi:
                    print(f"     MAX ({hi['store']:18s} {hi['price']:>10,.0f} EGP): {hi['title'][:95]}")

    if json_out:
        Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved JSON audit report to {json_out}")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only audit of gold.mart_cross_store_matches.")
    parser.add_argument("--category", default=None, help="Filter to a single canonical category")
    parser.add_argument("--high-ratio", type=float, default=1.6, help="High price ratio threshold (default 1.6)")
    parser.add_argument("--top-high", type=int, default=15, help="Top high-ratio pairs per category (default 15)")
    parser.add_argument("--sample-normal", type=int, default=15, help="Normal-gap sample size per category (default 15)")
    parser.add_argument("--summary-only", action="store_true", help="Print summary tables only")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path")
    args = parser.parse_args()
    run_audit(
        category=args.category,
        high_ratio_min=args.high_ratio,
        top_high=args.top_high,
        sample_normal=args.sample_normal,
        summary_only=args.summary_only,
        json_out=args.json_out,
    )


if __name__ == "__main__":
    main()
