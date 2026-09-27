import tempfile
import unittest
from pathlib import Path

from scripts.build_preview import build_preview
from scripts.qa_preview import run_qa_slide_preview


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><text>{}</text></svg>'


class ContentHtmlPreviewTests(unittest.TestCase):
    def test_content_deck_enters_existing_html_outlet(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "svg_output"
            source.mkdir()
            for index, filename in enumerate(("01_cover.svg", "02_statement_list.svg", "03_statement.svg", "04_statement.svg"), 1):
                (source / filename).write_text(SVG.format(f"MARKER-{index}"), encoding="utf-8")
            output = root / "content-preview.html"
            result = build_preview(source, output, title="Content deck", check=True)
            html = result.read_text(encoding="utf-8")
            self.assertEqual(html.count('class="slide'), 4)
            self.assertEqual(html.count("<svg"), 4)
            self.assertEqual(html.index("MARKER-1") < html.index("MARKER-2") < html.index("MARKER-3") < html.index("MARKER-4"), True)
            self.assertIn("01 / 04", html)
            self.assertTrue(run_qa_slide_preview(result, verbose=False))


if __name__ == "__main__":
    unittest.main()
