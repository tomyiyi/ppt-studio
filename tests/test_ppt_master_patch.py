#!/usr/bin/env python3
"""验证外部 ppt-master 兼容补丁的边界，不 vendor 转换器源码。"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "tools/ppt-master-patches/libreoffice-tracked-caps.patch"


class TestPptMasterPatch(unittest.TestCase):
    def test_patch_is_scoped_to_tracked_caps_headroom(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("_TRACKED_CAPS_HEADROOM = 1.14", text)
        self.assertIn("caps == 1.0", text)
        self.assertIn("letter_spacing_px > 0", text)
        self.assertEqual(text.count("elements.py"), 4)
        self.assertNotIn("06_before_after.svg", text)
        self.assertNotIn("light-business.json", text)


if __name__ == "__main__":
    unittest.main()
