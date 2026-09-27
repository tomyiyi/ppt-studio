import tempfile
import unittest
from pathlib import Path

from PIL import Image

import compare_versions


class CompareVersionsTest(unittest.TestCase):
    def _dirs(self):
        root = Path(tempfile.mkdtemp())
        left, right = root / "a", root / "b"
        left.mkdir(); right.mkdir()
        return root, left, right

    def test_identical_images_have_zero_diff(self):
        _, left, right = self._dirs()
        image = Image.new("RGB", (128, 72), "black")
        image.save(left / "01_slide.png"); image.save(right / "01_slide.png")
        item = compare_versions.compare(left, right)[0]
        self.assertEqual(item.changed_pixels, 0)
        self.assertEqual(item.changed_ratio, 0)
        self.assertIsNone(item.bbox)

    def test_changed_rectangle_returns_exact_bbox(self):
        _, left, right = self._dirs()
        Image.new("RGB", (128, 72), "black").save(left / "01_slide.png")
        image = Image.new("RGB", (128, 72), "black")
        for x in range(20, 40):
            for y in range(10, 30):
                image.putpixel((x, y), (255, 255, 255))
        image.save(right / "01_slide.png")
        item = compare_versions.compare(left, right)[0]
        self.assertEqual(item.bbox, (20, 10, 40, 30))
        self.assertEqual(item.changed_pixels, 400)

    def test_threshold_ignores_eight_but_detects_thirteen(self):
        _, left, right = self._dirs()
        Image.new("RGB", (2, 1), (100, 100, 100)).save(left / "01_slide.png")
        image = Image.new("RGB", (2, 1), (100, 100, 100))
        image.putpixel((0, 0), (108, 100, 100)); image.putpixel((1, 0), (113, 100, 100))
        image.save(right / "01_slide.png")
        self.assertEqual(compare_versions.compare(left, right)[0].changed_pixels, 1)

    def test_mismatched_dimensions_fail(self):
        _, left, right = self._dirs()
        Image.new("RGB", (1280, 720), "black").save(left / "01_slide.png")
        Image.new("RGB", (1080, 1350), "black").save(right / "01_slide.png")
        with self.assertRaisesRegex(ValueError, "dimensions differ"):
            compare_versions.compare(left, right)

    def test_mismatched_slide_sets_fail(self):
        _, left, right = self._dirs()
        Image.new("RGB", (10, 10), "black").save(left / "01_slide.png")
        Image.new("RGB", (10, 10), "black").save(right / "02_slide.png")
        with self.assertRaisesRegex(ValueError, "slide sets do not match"):
            compare_versions.compare(left, right)

    def test_report_is_self_contained(self):
        _, left, right = self._dirs()
        Image.new("RGB", (10, 10), "black").save(left / "01_slide.png")
        Image.new("RGB", (10, 10), "white").save(right / "01_slide.png")
        html = compare_versions.render_report(compare_versions.compare(left, right))
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("changed: 100.00%", html)


if __name__ == "__main__":
    unittest.main()
