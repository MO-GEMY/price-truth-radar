"""Unit & offline dry-run tests for Breadfast (`breadfast`) and Talabat Egypt (`talabat_eg`) adapters."""

from __future__ import annotations

import base64
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from data_platform.ingestion.scrapers import (
    BreadfastScraper,
    PoliteHttpClient,
    SCRAPER_REGISTRY,
    TalabatEgScraper,
    compute_product_sk,
    load_stores_registry,
    plan_tiered_waves_for_day,
)
from data_platform.ingestion.scrapers.base import CANONICAL_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestBreadfastAndTalabatAdapters(unittest.TestCase):
    def test_both_registered_strictly_under_local_only(self) -> None:
        self.assertIn("breadfast", SCRAPER_REGISTRY)
        self.assertIn("talabat_eg", SCRAPER_REGISTRY)

        enabled_all = {e.store_key: e for e in load_stores_registry(enabled_only=True)}
        for key in ("breadfast", "talabat_eg"):
            self.assertIn(key, enabled_all)
            self.assertEqual(enabled_all[key].region_mode, "local_only")
            self.assertTrue(enabled_all[key].enabled)

        # Must NEVER appear in GitHub Actions cloud-only shard plan
        cloud_plan = plan_tiered_waves_for_day(1, region_mode="cloud", include_all_tiers=True)
        cloud_stores = {st.split(":", 1)[0] for sh in cloud_plan["shards"] for st in sh["stores"]}
        self.assertNotIn("breadfast", cloud_stores)
        self.assertNotIn("talabat_eg", cloud_stores)

        # MUST appear when local_only stores are included
        full_plan = plan_tiered_waves_for_day(1, region_mode=None, include_all_tiers=True)
        full_stores = {st.split(":", 1)[0] for sh in full_plan["shards"] for st in sh["stores"]}
        self.assertIn("breadfast", full_stores)
        self.assertIn("talabat_eg", full_stores)

    def test_breadfast_har_and_json_feed_ingestion_and_non_404_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feed_dir = Path(tmp)
            # 1) Plain JSON product dump
            (feed_dir / "catalog.json").write_text(
                json.dumps(
                    {
                        "products": [
                            {
                                "sku": "BF-6221007001",
                                "name": "Juhayna Full Cream Milk 1L",
                                "brand": "Juhayna",
                                "department": "Dairy & Eggs",
                                "price": 46.50,
                                "original_price": 52.00,
                                "currency": "EGP",
                                "in_stock": True,
                                "barcode": "6221007001234",
                                "image_url": "https://cdn.breadfast.com/milk.jpg",
                            },
                            {
                                "sku": "BF-PET-99",
                                "name": "Whiskas Adult Cat Food Chicken 1.2kg",
                                "department": "Pet Supplies",
                                "price": 295.00,
                                "in_stock": True,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            # 2) Base64-encoded HAR 1.2 capture
            har_inner = json.dumps(
                {
                    "data": {
                        "items": [
                            {
                                "id": "BF-VIT-77",
                                "name_en": "Centrum Adult Multivitamin 30 Tablets",
                                "category": "Pharmacy & Health",
                                "sale_price": 410.00,
                                "regular_price": 450.00,
                                "is_available": True,
                            }
                        ]
                    }
                }
            )
            har_doc = {
                "log": {
                    "entries": [
                        {
                            "response": {
                                "content": {
                                    "encoding": "base64",
                                    "text": base64.b64encode(har_inner.encode("utf-8")).decode("ascii"),
                                }
                            }
                        }
                    ]
                }
            }
            (feed_dir / "session.har").write_text(json.dumps(har_doc), encoding="utf-8")

            with PoliteHttpClient(min_delay_seconds=0.0) as http:
                scraper = BreadfastScraper(http, feed_dir=feed_dir)
                recs = scraper.scrape(limit=20)

            self.assertEqual(len(recs), 3)
            by_id = {r.external_id: r for r in recs}

            milk = by_id["BF-6221007001"]
            self.assertEqual(milk.store_name, "breadfast")
            self.assertEqual(milk.category, "groceries")
            self.assertEqual(milk.sub_category, "dairy_cheese")
            self.assertEqual(float(milk.current_price), 46.50)
            self.assertEqual(float(milk.claimed_original_price), 52.00)
            self.assertTrue(milk.in_stock)
            self.assertEqual(milk.product_url, "https://www.breadfast.com/?asarak_item=BF-6221007001")
            self.assertTrue(compute_product_sk("breadfast", milk.external_id))

            self.assertEqual(by_id["BF-PET-99"].category, "pet_care")
            self.assertEqual(by_id["BF-VIT-77"].category, "health")
            for r in recs:
                self.assertIn(r.category, CANONICAL_CATEGORIES)

    def test_talabat_eg_feed_ingestion_and_offline_scrape_shard_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bf_dir = tmp_path / "bf_feed"
            tb_dir = tmp_path / "tb_feed"
            bf_dir.mkdir()
            tb_dir.mkdir()

            (bf_dir / "sample.json").write_text(
                json.dumps(
                    [
                        {
                            "sku": "BF-1001",
                            "name": "Crystal Sunflower Oil 1.6L",
                            "department": "Cooking Oils",
                            "price": 179.0,
                            "original_price": 195.0,
                            "in_stock": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (tb_dir / "talabat_mart.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "TM-8821",
                                "name": "Pampers Premium Care Diapers Size 4 64 Count",
                                "categoryName": "Baby Care",
                                "price": 549.0,
                                "oldPrice": 620.0,
                                "isAvailable": True,
                                "slug": "pampers-premium-care-size-4",
                                "imageUrl": "https://images.deliveryhero.io/image/talabat/pampers.jpg",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            out_gz = tmp_path / "local_dryrun.jsonl.gz"
            env = dict(os.environ)
            for k in ("DATABASE_URL", "DATABASE_URL_ADMIN", "DATABASE_URL_READONLY"):
                env[k] = ""
            env["BREADFAST_FEED_DIR"] = str(bf_dir)
            env["TALABAT_FEED_DIR"] = str(tb_dir)

            res = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "offline_tiered_pipeline.py"),
                    "scrape-shard",
                    "--shard",
                    "local_groceries_test",
                    "--priority",
                    "p3_tier2",
                    "--stores",
                    "breadfast,talabat_eg",
                    "--mode",
                    "daily",
                    "--workers",
                    "2",
                    "--out",
                    str(out_gz),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            rows = []
            with gzip.open(out_gz, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
            self.assertEqual(len(rows), 2)
            by_store = {r["store_name"]: r for r in rows}

            self.assertEqual(by_store["breadfast"]["category"], "groceries")
            self.assertEqual(by_store["breadfast"]["current_price"], 179.0)
            self.assertEqual(
                by_store["breadfast"]["product_url"],
                "https://www.breadfast.com/?asarak_item=BF-1001",
            )

            self.assertEqual(by_store["talabat_eg"]["category"], "baby_kids")
            self.assertEqual(by_store["talabat_eg"]["current_price"], 549.0)
            self.assertTrue(
                by_store["talabat_eg"]["product_url"].startswith("https://www.talabat.com/egypt/")
            )


if __name__ == "__main__":
    unittest.main()
