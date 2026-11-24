"""Unit tests for bilingual subcategory taxonomy, cached facets endpoint, and scoped search/feed."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.cache import api_cache, search_cache  # noqa: E402
from app.catalog_search import (  # noqa: E402
    build_catalog_query,
    coverage_catalog_sql,
    exact_catalog_sql,
    fuzzy_catalog_sql,
)
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import CANONICAL_CATEGORIES  # noqa: E402
from app.subcategories import (  # noqa: E402
    SUBCATEGORY_TAXONOMY,
    build_subcategory_sql_filter,
    classify_product_subcategory,
    get_category_subcategories,
)


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def one(self) -> dict[str, Any]:
        return self._rows[0]

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)

    def scalar_one(self) -> int:
        return len(self._rows)


class _FakeConn:
    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql_text = str(statement)
        self.calls.append((sql_text, dict(params or {})))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeResult(rows)

    def rollback(self) -> None:
        pass


class TestSubcategoryTaxonomy(unittest.TestCase):
    def test_all_canonical_categories_covered_bilingually(self) -> None:
        for cat in CANONICAL_CATEGORIES:
            specs = get_category_subcategories(cat)
            self.assertGreaterEqual(len(specs), 4, f"{cat} should have at least 4 subcategories")
            slugs = [s.slug for s in specs]
            self.assertEqual(len(slugs), len(set(slugs)), f"Duplicate slugs in {cat}")
            for spec in specs:
                self.assertTrue(spec.label_en.strip())
                self.assertTrue(spec.label_ar.strip())
                self.assertTrue(any("\u0600" <= ch <= "\u06ff" for ch in spec.label_ar))

    def test_bilingual_classification_and_exclusion_guards(self) -> None:
        self.assertEqual(
            classify_product_subcategory("groceries", "oils_ghee", "زيت ذرة كريستال 2.2 لتر"),
            "oils_ghee",
        )
        self.assertEqual(
            classify_product_subcategory("groceries", "canned_sauces", "Galaxy Smooth Milk Chocolate 90g"),
            "snacks_chocolate",
        )
        self.assertEqual(
            classify_product_subcategory("groceries", "canned_sauces", "تونة مفتتة صن شاين 140 جم"),
            "meat_poultry",
        )
        self.assertEqual(
            classify_product_subcategory("electronics", "smartphones", "Apple iPhone 16 Pro 256GB"),
            "smartphones",
        )
        # iPhone case must NOT be classified as smartphones
        self.assertNotEqual(
            classify_product_subcategory("electronics", "smartphones", "Silicone Case Cover for iPhone 16 Pro"),
            "smartphones",
        )
        self.assertEqual(
            classify_product_subcategory("home_appliances", "air_conditioners", "تكييف كاريير اوبتيماكس 1.5 حصان"),
            "air_conditioners",
        )
        self.assertEqual(
            classify_product_subcategory("beauty", "perfumes", "Dior Sauvage Eau de Parfum 100ml"),
            "fragrances",
        )
        self.assertEqual(
            classify_product_subcategory("home_furniture", "beds", "Cotton Bedsheet Set 4 Pieces"),
            "bedding_rugs",
        )

    def test_sql_filter_uses_pg_word_boundaries_and_alias(self) -> None:
        pred, params = build_subcategory_sql_filter("groceries", "oils_ghee", alias="p", param_prefix="t")
        self.assertIsNotNone(pred)
        assert pred is not None
        self.assertIn("p.sub_category", pred)
        self.assertIn("p.product_title", pred)
        for val in params.values():
            if isinstance(val, str):
                self.assertNotIn(r"\b", val, "PostgreSQL POSIX regex must use \\y instead of \\b")

        # Raw fallback slug
        raw_pred, raw_params = build_subcategory_sql_filter("groceries", "custom_raw_slug", alias="p")
        self.assertEqual(raw_pred, "LOWER(COALESCE(p.sub_category, '')) = :sub_exact")
        self.assertEqual(raw_params, {"sub_exact": "custom_raw_slug"})

    def test_catalog_search_sql_scopes_both_direct_and_deduped(self) -> None:
        q = build_catalog_query("crystal sunflower oil")
        filters_sql = "p.category = :search_cat AND p.store_name = :search_store"
        filters_params = {"search_cat": "groceries", "search_store": "carrefour_eg"}

        exact_sql, exact_params = exact_catalog_sql(q, 20, filters_sql=filters_sql, filters_params=filters_params)
        self.assertEqual(exact_sql.count(filters_sql), 2)
        self.assertEqual(exact_params["search_cat"], "groceries")
        self.assertEqual(exact_params["search_store"], "carrefour_eg")

        cov = coverage_catalog_sql(q, 20, filters_sql=filters_sql, filters_params=filters_params)
        self.assertIsNotNone(cov)
        assert cov is not None
        self.assertIn(filters_sql, cov[0])
        self.assertEqual(cov[1]["search_cat"], "groceries")

        fuz = fuzzy_catalog_sql(q, 20, filters_sql=filters_sql, filters_params=filters_params)
        self.assertIsNotNone(fuz)
        assert fuz is not None
        self.assertIn(filters_sql, fuz[0])
        self.assertEqual(fuz[1]["search_store"], "carrefour_eg")


class TestFacetsAndScopedEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        api_cache.clear()
        search_cache.clear()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        api_cache.clear()
        search_cache.clear()

    def test_category_facets_hides_empty_and_caches(self) -> None:
        specs = SUBCATEGORY_TAXONOMY["groceries"]
        sub_row: dict[str, Any] = {"total_in_stock": 1500}
        for idx, spec in enumerate(specs):
            sub_row[f"cnt_{idx}"] = 420 if spec.slug == "oils_ghee" else (310 if spec.slug == "dairy_cheese" else 0)
        facets_row = {
            "scoped_total": 1500,
            "stores": [{"slug": "carrefour_eg", "count": 900}, {"slug": "hyperone", "count": 600}],
            "brands": [{"name": "Crystal", "count": 120}, {"name": "Juhayna", "count": 95}],
        }
        fake_db = _FakeConn([[sub_row], [facets_row]])
        app.dependency_overrides[get_db] = lambda: fake_db

        client = TestClient(app)
        resp1 = client.get("/api/v1/categories/groceries/facets")
        self.assertEqual(resp1.status_code, 200)
        self.assertIn("s-maxage=21600", resp1.headers.get("cache-control", ""))
        data = resp1.json()
        self.assertEqual(data["category"], "groceries")
        self.assertEqual(data["total_in_stock"], 1500)
        self.assertEqual([s["slug"] for s in data["subcategories"]], ["oils_ghee", "dairy_cheese"])
        self.assertEqual([s["slug"] for s in data["stores"]], ["carrefour_eg", "hyperone"])
        self.assertEqual([b["name"] for b in data["brands"]], ["Crystal", "Juhayna"])
        self.assertEqual(len(fake_db.calls), 2)

        # Second call must hit in-memory api_cache with ZERO DB queries
        resp2 = client.get("/api/v1/categories/facets?category=groceries")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json(), data)
        self.assertEqual(len(fake_db.calls), 2)

        # Subcategory-scoped call reuses cached subcategory counts (only 1 DB query for scoped stores/brands!)
        fake_db._responses.append(
            [
                {
                    "scoped_total": 420,
                    "stores": [{"slug": "carrefour_eg", "count": 420}],
                    "brands": [{"name": "Crystal", "count": 120}],
                }
            ]
        )
        resp3 = client.get("/api/v1/categories/groceries/facets?subcategory=oils_ghee")
        self.assertEqual(resp3.status_code, 200)
        d3 = resp3.json()
        self.assertEqual(d3["subcategory"], "oils_ghee")
        self.assertEqual(d3["total_in_stock"], 420)
        self.assertEqual([s["slug"] for s in d3["subcategories"]], ["oils_ghee", "dairy_cheese"])
        self.assertEqual([s["slug"] for s in d3["stores"]], ["carrefour_eg"])
        self.assertEqual(len(fake_db.calls), 3)

    def test_radar_feed_and_search_accept_subcategory_and_brand(self) -> None:
        fake_db = _FakeConn([[], []])
        app.dependency_overrides[get_db] = lambda: fake_db
        client = TestClient(app)

        feed_resp = client.get(
            "/api/v1/radar/feed?category=groceries&subcategory=oils_ghee&brand=Crystal&store=carrefour_eg"
        )
        self.assertEqual(feed_resp.status_code, 200)
        self.assertGreaterEqual(len(fake_db.calls), 1)
        feed_sql, feed_params = fake_db.calls[0]
        self.assertIn("category = :category", feed_sql)
        self.assertIn("LOWER(TRIM(COALESCE(brand, ''))) = :brand", feed_sql)
        self.assertEqual(feed_params["category"], "groceries")
        self.assertEqual(feed_params["brand"], "crystal")
        self.assertEqual(feed_params["store"], "carrefour_eg")
        self.assertIn("rsub_raw_list", feed_params)

        fake_db2 = _FakeConn([[], []])
        app.dependency_overrides[get_db] = lambda: fake_db2
        search_resp = client.get(
            "/api/v1/products/search?q=crystal&category=groceries&subcategory=oils_ghee&store=carrefour_eg&brand=Crystal"
        )
        self.assertEqual(search_resp.status_code, 200)
        self.assertGreaterEqual(len(fake_db2.calls), 1)
        s_sql, s_params = fake_db2.calls[0]
        self.assertIn("p.category = :search_cat", s_sql)
        self.assertIn("p.store_name = :search_store", s_sql)
        self.assertIn("LOWER(TRIM(COALESCE(p.brand, ''))) = :search_brand", s_sql)
        self.assertEqual(s_params["search_cat"], "groceries")
        self.assertEqual(s_params["search_store"], "carrefour_eg")
        self.assertEqual(s_params["search_brand"], "crystal")
        self.assertIn("ssub_raw_list", s_params)


if __name__ == "__main__":
    unittest.main()
