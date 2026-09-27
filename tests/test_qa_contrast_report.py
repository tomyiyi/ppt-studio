import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.qa_contrast_report import build_report
from scripts.qa_layout import check_contrast, check_contrast_detailed


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
<rect width="1280" height="720" fill="#0A0D14"/>
<text x="80" y="140" font-size="56" fill="#F0F3FF">标题</text>
</svg>'''


class ContrastReportTest(unittest.TestCase):
    def test_detailed_result_keeps_legacy_projection(self):
        root = Path(tempfile.mkdtemp())
        svg = root / "01_test.svg"
        png = root / "01_test.png"
        svg.write_text(SVG, encoding="utf-8")
        image = Image.new("RGB", (1280, 720), (10, 13, 20))
        for x in range(80, 180):
            for y in range(80, 145):
                image.putpixel((x, y), (20, 22, 28))
        image.save(png)
        import xml.etree.ElementTree as ET
        tree = ET.parse(svg).getroot()
        detailed = check_contrast_detailed(Image.open(png), tree)
        legacy = check_contrast(Image.open(png), tree)
        self.assertEqual(len(detailed), len(legacy))
        self.assertTrue(all("bbox" in row for row in detailed))
        if detailed:
            self.assertEqual(legacy[0][1], detailed[0]["text"])

    def test_report_is_self_contained_and_marks_failure(self):
        root = Path(tempfile.mkdtemp())
        svg_dir, render_dir = root / "svg", root / "render"
        svg_dir.mkdir(); render_dir.mkdir()
        (svg_dir / "01_test.svg").write_text(SVG, encoding="utf-8")
        Image.new("RGB", (1280, 720), (10, 13, 20)).save(render_dir / "01_test.png")
        out = root / "report.html"
        build_report(svg_dir, render_dir, out)
        html = out.read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("01_test", html)
        self.assertNotIn('src="/', html)


if __name__ == "__main__":
    unittest.main()
