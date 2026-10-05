import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "scraper", Path(__file__).resolve().parents[1] / "scripts/scrape_pepperhead.py"
)
scraper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scraper)


def page(data):
    return '<html><script id="data" type="application/json">' + json.dumps(data) + '</script></html>'


class ScraperTests(unittest.TestCase):
    def test_extract_keeps_all_fields(self):
        data = {"games": [{"key": "demo", "commentary": [{"summary": "original"}]}], "meta": {}}
        self.assertEqual(scraper.extract(page(data)), data)

    def test_missing_or_duplicate_block_rejected(self):
        with self.assertRaises(ValueError):
            scraper.extract("<html>No data</html>")
        with self.assertRaises(ValueError):
            scraper.extract(page({"games": [{"key": "x"}]}) * 2)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            scraper.extract(page({"games": [{"key": "x"}, {"key": "x"}]}))

    def test_invalid_games_rejected(self):
        for data in ({"games": []}, {"games": [None]}, {"games": [{"key": 1}]}, []):
            with self.subTest(data=data), self.assertRaises(ValueError):
                scraper.extract(page(data))

    def test_slugs_are_safe_and_distinct(self):
        keys = ["../unsafe", "a/b", "a b", "a-b", "é", "漢字"]
        slugs = [scraper.game_slug(k) for k in keys]
        self.assertEqual(len(set(slugs)), len(keys))
        for slug in slugs:
            self.assertRegex(slug, r"^[a-z0-9-]+$")

    def test_unicode_and_entities_preserved(self):
        data = {"games": [{"key": "é", "name": "R&D <demo>", "description": "Fish &amp; chips"}]}
        self.assertEqual(scraper.extract(page(data)), data)

    def test_archive_round_trip_and_attribution(self):
        data = {"meta": {"data_date": "source date"}, "games": [
            {"key": "demo", "name": "Demo", "img": "img/a.jpg", "commentary": [{"summary": "Unverified"}]}
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(scraper.archive(data, root, scraper.SOURCE, "test-time", {}, "hash"), 1)
            index = json.loads((root / "index.json").read_text())
            record = json.loads((root / index[0]["json"]).read_text())
            self.assertEqual(record["game"], data["games"][0])
            self.assertEqual(record["provenance"]["notice"], scraper.NOTICE)
            self.assertEqual(index[0]["image_url"], scraper.SOURCE + "img/a.jpg")
            self.assertIn("Unverified", (root / index[0]["markdown"]).read_text())
            self.assertEqual(json.loads((root / "source-data.json").read_text()), data)
            llm_index = (root / "llms.txt").read_text()
            self.assertIn("https://raw.githubusercontent.com/", llm_index)
            self.assertIn(index[0]["markdown"], llm_index)
            self.assertIn("[Demo]", llm_index)

    def test_scalar_fields_precede_nested_sections(self):
        rendered = "\n".join(scraper.render_fields({"tags": ["tag"], "price": "$1"}))
        self.assertLess(rendered.index("**Price:**"), rendered.index("### Tags"))

    def test_refresh_removes_only_stale_generated_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scraper.archive({"games": [{"key": "old"}]}, root, scraper.SOURCE, "time", {}, "hash")
            extra = root / "games/notes.md"
            extra.write_text("manual notes")
            scraper.archive({"games": [{"key": "new"}]}, root, scraper.SOURCE, "time", {}, "hash")
            self.assertTrue(extra.exists())
            self.assertFalse((root / "games" / (scraper.game_slug("old") + ".json")).exists())
            self.assertTrue((root / "games" / (scraper.game_slug("new") + ".json")).exists())


if __name__ == "__main__":
    unittest.main()
