"""Offline corpus, route, HTML and importer regression checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build import Builder, OUT, is_dynamic, load, path_of, text
from import_wordpress import inventory, media_url


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = Builder()
        if not (OUT / "build-report.json").exists():
            raise RuntimeError("Build first: python scripts/build.py")
        cls.report = json.loads((OUT / "build-report.json").read_text(encoding="utf-8"))

    def generated(self, item):
        return BeautifulSoup((OUT / unquote(path_of(item["link"])).lstrip("/") / "index.html").read_text(encoding="utf-8"), "html.parser")

    def test_full_api_and_sitemap_inventory(self):
        report = load("migration-report")
        self.assertEqual(len(self.builder.posts), report["totals"]["posts"])
        self.assertEqual(len(self.builder.pages), report["totals"]["pages"])
        for kind, records in (("post", self.builder.posts), ("page", self.builder.pages)):
            paths = set()
            for file in (ROOT / "content").glob(f"wp-sitemap-posts-{kind}-*.xml"):
                paths.update(node.text for node in ET.parse(file).iter() if node.tag.endswith("}loc"))
            expected = {item["link"] for item in records}
            if kind == "page":
                expected.add("https://powertips.es/")
            self.assertEqual(paths, expected)
        self.assertEqual(report["media_inventory"]["returned"], len(load("media")))
        self.assertEqual(report["media_inventory"]["unavailable"], report["totals"]["media"] - len(load("media")))

    def test_every_original_permalink_and_full_article_text(self):
        for item in self.builder.posts + self.builder.pages:
            with self.subTest(url=item["link"]):
                soup = self.generated(item)
                self.assertEqual(soup.html["lang"], "es")
                self.assertEqual(soup.select_one("link[rel=canonical]")["href"], item["link"])
                self.assertEqual(soup.h1.get_text(), text(item["title"]["rendered"]))
                self.assertTrue(soup.select_one("meta[name=description]")["content"])
                body = soup.select_one(".article-body")
                if item in self.builder.posts and not item["content"]["protected"]:
                    self.assertEqual(text(str(body)), text(item["content"]["rendered"]), "Article body was truncated/changed")
                    self.assertEqual(soup.select_one(".article-heading time")["datetime"], item["date"][:10])
                    source = BeautifulSoup(item["content"]["rendered"], "html.parser")
                    self.assertEqual(len(body.find_all("iframe")), len(source.find_all("iframe")))
                    self.assertEqual(len(body.find_all("img")), len(source.find_all("img")))
                self.assertFalse(body.find_all(["form", "input", "script", "textarea", "button"]))
                self.assertNotIn("[anspress]", body.get_text())
                if is_dynamic(path_of(item["link"])):
                    self.assertIsNotNone(body.select_one(".notice"))
                    self.assertEqual(soup.select_one('meta[name="robots"]')["content"], "noindex,follow")

    def test_all_internal_links_and_media_resolve(self):
        self.assertEqual(self.report["missing_assets"], [])
        self.assertEqual(self.report["unmapped_internal_links"], [])
        self.assertEqual(self.report["unsupported_embeds"], [])
        self.assertEqual(self.report["unresolved_shortcodes"], [])
        for file in OUT.rglob("*.html"):
            soup = BeautifulSoup(file.read_text(encoding="utf-8"), "html.parser")
            self.assertIsNotNone(soup.select_one('a[href="#contenido"]'))
            for tag in soup.find_all(["a", "img", "script", "link"]):
                url = tag.get("href") or tag.get("src")
                if not url or not url.startswith("/") or url.startswith("//"):
                    continue
                path = unquote(urlsplit(url).path)
                target = OUT / path.lstrip("/")
                if path.endswith("/"):
                    target /= "index.html"
                self.assertTrue(target.is_file(), f"{file}: missing {url}")
            for iframe in soup.find_all("iframe"):
                self.assertTrue(iframe.get("title"))
                self.assertEqual(iframe.get("loading"), "lazy")

    def test_media_assets_complete_and_identical(self):
        report = load("migration-report")
        mapping = load("media-map")
        self.assertEqual(report["media_failures"], [])
        self.assertEqual(len(mapping), report["assets"]["referenced"])
        for url, path in mapping.items():
            with self.subTest(url=url):
                self.assertTrue(path.startswith("/assets/media/"))
                source = ROOT / path.lstrip("/")
                output = OUT / path.lstrip("/")
                self.assertGreater(source.stat().st_size, 0)
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(output.read_bytes()).digest())

    def test_search_index_complete_and_untruncated(self):
        index = json.loads((OUT / "search-index.json").read_text(encoding="utf-8"))
        expected = {path_of(item["link"]): item for item in self.builder.posts if not item["content"]["protected"]}
        self.assertEqual({item["url"] for item in index}, set(expected))
        for item in index:
            self.assertEqual(item["text"], text(expected[item["url"]]["content"]["rendered"]))
            self.assertEqual(item["title"], text(expected[item["url"]]["title"]["rendered"]))

    def test_sitemap_cname_and_legacy_id_mapping(self):
        self.assertEqual((OUT / "CNAME").read_text().strip(), "powertips.es")
        urls = {node.text for node in ET.parse(OUT / "sitemap.xml").iter() if node.tag.endswith("}loc")}
        self.assertTrue({item["link"] for item in self.builder.posts}.issubset(urls))
        self.assertTrue(all(url.startswith("https://powertips.es/") and url.endswith("/") for url in urls))
        self.assertFalse(any("/questions/" in url for url in urls))
        compatibility = json.loads((OUT / "compatibility.json").read_text(encoding="utf-8"))
        for item in self.builder.posts + self.builder.pages:
            self.assertEqual(compatibility["ids"][str(item["id"])], path_of(item["link"]))
        ET.parse(OUT / "feed" / "index.xml")

    def test_sanitizer_drops_active_wordpress_features(self):
        item = deepcopy(self.builder.posts[0])
        item["content"]["rendered"] = '<p onclick="alert(1)">Texto <strong>útil</strong></p><script>danger()</script><form><input><button>Enviar</button></form><a href="javascript:alert(1)">Enlace</a><img src="https://example.com/a.jpg" onerror="danger()"><iframe src="https://www.youtube.com/embed/demo"></iframe>'
        soup = BeautifulSoup(self.builder.body(item), "html.parser")
        self.assertFalse(soup.find_all(["script", "form", "input", "button"]))
        self.assertFalse(soup.find(attrs={"onclick": True}))
        self.assertFalse(soup.find(attrs={"onerror": True}))
        self.assertIsNone(soup.find("a", string="Enlace").get("href"))
        self.assertEqual(soup.strong.get_text(), "útil")
        self.assertEqual(soup.iframe["title"], "Vídeo de YouTube")
        self.assertIsNotNone(soup.select_one(".notice"))

    def test_unknown_shortcode_fails_instead_of_silent_omission(self):
        item = deepcopy(self.builder.posts[0])
        item["content"]["rendered"] = "<p>[unknown_form]</p>"
        with self.assertRaisesRegex(ValueError, "Unresolved WordPress shortcodes"):
            self.builder.body(item)

    def test_asset_normalization(self):
        self.assertEqual(media_url("https://i0.wp.com/powertips.es/wp-content/uploads/image.png?w=800"), "https://powertips.es/wp-content/uploads/image.png")
        self.assertIsNone(media_url("https://external.example/image.png"))


class ImporterTests(unittest.TestCase):
    def test_pagination_and_headers(self):
        responses = [(json.dumps([{"id": 1}, {"id": 2}]).encode(), {"X-WP-Total": "3", "X-WP-TotalPages": "2"}),
                     (json.dumps([{"id": 3}]).encode(), {"x-wp-total": "3", "x-wp-totalpages": "2"})]
        with patch("import_wordpress.fetch", side_effect=responses) as fetch:
            items, total = inventory("posts")
        self.assertEqual(len(items), total)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("page=2", fetch.call_args.args[0])

    def test_incomplete_articles_fail_loudly(self):
        with patch("import_wordpress.fetch", return_value=(b'[{"id": 1}]', {"X-WP-Total": "2", "X-WP-TotalPages": "1"})):
            with self.assertRaisesRegex(RuntimeError, "incomplete/duplicate pagination"):
                inventory("posts")

    def test_duplicate_records_fail_even_for_media(self):
        with patch("import_wordpress.fetch", return_value=(b'[{"id": 1},{"id": 1}]', {"X-WP-Total": "2", "X-WP-TotalPages": "1"})):
            with self.assertRaisesRegex(RuntimeError, "incomplete/duplicate pagination"):
                inventory("media")

    def test_changing_api_inventory_fails(self):
        responses = [(b'[{"id": 1}]', {"X-WP-Total": "2", "X-WP-TotalPages": "2"}),
                     (b'[{"id": 2}]', {"X-WP-Total": "3", "X-WP-TotalPages": "2"})]
        with patch("import_wordpress.fetch", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "API changed"):
                inventory("pages")


if __name__ == "__main__":
    unittest.main()
