"""Static checks for the documented energy dashboard and market landscape.

These tests validate the catalogue and UI wiring, not claims or live vendor links.
"""
from __future__ import annotations

import csv
import pathlib
import unittest
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "research" / "EXISTING_PRODUCTS_CATALOG.csv"
LANDSCAPE = ROOT / "landscape.html"
REVIEW = ROOT / "research" / "DASHBOARDS_AND_COMPETITORS.md"

ALLOWED_SEGMENTS = {
    "public_dashboard", "monitoring_app", "tariff_comparison",
    "heating_control", "storage_ev_control", "retrofit_assessment",
    "open_source", "data_access",
}
REQUIRED = {
    "id", "name", "segment", "provider_type", "access", "data_signals",
    "stated_capabilities", "api_or_open_data", "research_value",
    "limitations", "public_url", "source_url", "reviewed_utc",
}


class LandscapeCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            cls.headers = set(reader.fieldnames or ())
            cls.rows = list(reader)

    def test_catalog_has_required_columns(self):
        self.assertTrue(REQUIRED <= self.headers)

    def test_catalog_has_broad_coverage(self):
        self.assertGreaterEqual(len(self.rows), 45)
        self.assertEqual({r["segment"] for r in self.rows}, ALLOWED_SEGMENTS)

    def test_ids_unique_and_content_present(self):
        ids = [row["id"] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in self.rows:
            with self.subTest(id=row["id"]):
                self.assertTrue(all((row.get(field) or "").strip() for field in REQUIRED))
                self.assertEqual(row["reviewed_utc"], "2026-11-22")

    def test_source_links_are_http_urls_not_placeholders(self):
        for row in self.rows:
            with self.subTest(id=row["id"]):
                for field in ("public_url", "source_url"):
                    url = urlparse(row[field])
                    self.assertIn(url.scheme, ("http", "https"))
                    self.assertTrue(url.netloc and "." in url.netloc)
                    self.assertNotIn("example.com", url.netloc)

    def test_html_has_accessible_live_catalogue(self):
        page = LANDSCAPE.read_text(encoding="utf-8")
        for fragment in (
            'id="search"', 'id="segment"', 'id="access"',
            'id="list"', 'id="count"', 'aria-live="polite"',
            "research/EXISTING_PRODUCTS_CATALOG.csv",
            "research/DASHBOARDS_AND_COMPETITORS.md",
            "replaceChildren()", "textContent",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, page)
        self.assertIn("EXISTING_PRODUCTS_CATALOG.csv", REVIEW.read_text(encoding="utf-8"))
        self.assertIn('href="landscape.html"', (ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertIn("landscape.html", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
