#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_check_page_map.py"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_page_map import parse_page_map, check


class TestParsePageMap(unittest.TestCase):
    def _write(self, tmp, content):
        p = Path(tmp) / "spec_lock.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_basic(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "## page_map\n- P01: role=Cover, rhythm=anchor\n- P02: role=Grid, rhythm=dense\n")
            m = parse_page_map(p)
            self.assertEqual(m["P01"], {"role": "Cover", "rhythm": "anchor"})
            self.assertEqual(m["P02"]["rhythm"], "dense")

    def test_missing_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "## canvas\n- viewBox: 0 0 1280 720\n")
            self.assertEqual(parse_page_map(p), {})

    def test_nonexistent(self):
        self.assertEqual(parse_page_map(Path("/no/such/file.md")), {})


class TestCheck(unittest.TestCase):
    def _proj(self, tmp, spec_content, svg_names):
        import tempfile
        proj = Path(tmp) / "proj"
        (proj / "svg_output").mkdir(parents=True)
        (proj / "spec_lock.md").write_text(spec_content, encoding="utf-8")
        for n in svg_names:
            (proj / "svg_output" / n).touch()
        return proj

    def test_complete(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = self._proj(d, "## page_map\n- P01: role=Cover, rhythm=anchor\n",
                              ["P01_cover.svg"])
            ok, issues = check(proj)
            self.assertTrue(ok)
            self.assertEqual(issues, [])

    def test_missing_svg(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = self._proj(d, "## page_map\n- P01: role=Cover\n- P02: role=Grid\n",
                              ["P01_cover.svg"])
            ok, issues = check(proj)
            self.assertFalse(ok)
            self.assertTrue(any("P02" in i for i in issues))

    def test_missing_map_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = self._proj(d, "## page_map\n- P01: role=Cover\n",
                              ["P01_cover.svg", "P02_extra.svg"])
            ok, issues = check(proj)
            self.assertFalse(ok)
            self.assertTrue(any("P02" in i for i in issues))

    def test_no_page_map_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = self._proj(d, "## canvas\n- viewBox: 0 0 1280 720\n",
                              ["P01_cover.svg"])
            ok, issues = check(proj)
            self.assertFalse(ok)
            self.assertTrue(any("page_map" in i for i in issues))

    def test_numeric_filename(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = self._proj(d, "## page_map\n- P01: role=Cover\n",
                              ["01_cover.svg"])
            ok, _ = check(proj)
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
