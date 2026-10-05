#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_sync_spec.py"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sync_spec import (
    svg_viewboxes, spec_viewbox, find_svg_dir, check, fix_canvas, resolve_project_dir, main,
)


def _make_proj(tmp, viewboxes, spec_vb):
    proj = Path(tmp) / "proj"
    svg_dir = proj / "svg_output_v4"
    svg_dir.mkdir(parents=True)
    for name, vb in viewboxes.items():
        (svg_dir / name).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s"/>' % vb,
            encoding="utf-8")
    (proj / "spec_lock.md").write_text(
        "## canvas\n- viewBox: %s\n- format: PPT 16:9\n" % spec_vb,
        encoding="utf-8")
    return proj


class TestSyncSpec(unittest.TestCase):
    def test_no_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1920 1080")
            ok, issues, ctx = check(proj)
            self.assertTrue(ok)
            self.assertEqual(issues, [])

    def test_drift_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            ok, issues, ctx = check(proj)
            self.assertFalse(ok)
            self.assertTrue(any("漂移" in i for i in issues))
            self.assertEqual(ctx["svg_vb"], "0 0 1920 1080")
            self.assertEqual(ctx["spec_vb"], "0 0 1280 720")

    def test_inconsistent_svg(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080",
                                  "02_b.svg": "0 0 1280 720"}, "0 0 1920 1080")
            ok, issues, _ = check(proj)
            self.assertFalse(ok)
            self.assertTrue(any("不一致" in i for i in issues))

    def test_fix_canvas(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            spec = proj / "spec_lock.md"
            self.assertTrue(fix_canvas(spec, "0 0 1920 1080"))
            # 换行保留
            txt = spec.read_text(encoding="utf-8")
            self.assertIn("- viewBox: 0 0 1920 1080\n- format:", txt)
            # 修复后无漂移
            ok, _, _ = check(proj)
            self.assertTrue(ok)

    def test_fix_canvas_with_str_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            spec_str = str(proj / "spec_lock.md")
            self.assertTrue(fix_canvas(spec_str, "0 0 1920 1080"))
            txt = Path(spec_str).read_text(encoding="utf-8")
            self.assertIn("- viewBox: 0 0 1920 1080\n", txt)

    def test_find_svg_dir_prefers_latest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            for v in ["svg_output", "svg_output_v3", "svg_output_v4"]:
                dd = proj / v
                dd.mkdir(parents=True)
                (dd / "01_a.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            self.assertEqual(find_svg_dir(proj).name, "svg_output_v4")

    def test_find_svg_dir_numeric_version_priority(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            for v in ["svg_output", "svg_output_v2", "svg_output_v10"]:
                dd = proj / v
                dd.mkdir(parents=True)
                (dd / "01_a.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            self.assertEqual(find_svg_dir(proj).name, "svg_output_v10")

    def test_spec_viewbox(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "spec.md"
            p.write_text("## canvas\n- viewBox: 0 0 1920 1080\n", encoding="utf-8")
            self.assertEqual(spec_viewbox(p), "0 0 1920 1080")


class TestMultiVersionAndSubdir(unittest.TestCase):
    def test_check_with_explicit_spec(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            alt_spec = proj / "spec_custom.md"
            alt_spec.write_text("## canvas\n- viewBox: 0 0 1920 1080\n", encoding="utf-8")
            ok, issues, ctx = check(proj, spec_path=alt_spec)
            self.assertTrue(ok)
            self.assertEqual(ctx["spec"], str(alt_spec.resolve()))
            self.assertEqual(ctx["spec_vb"], "0 0 1920 1080")

    def test_check_from_subfolder(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1920 1080")
            sub = proj / "svg_output_v4"
            ok, issues, ctx = check(sub)
            self.assertTrue(ok)
            self.assertEqual(ctx["svg_vb"], "0 0 1920 1080")

    def test_check_versioned_spec_lock_priority(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            # 增加 spec_lock_v5.md，与 svg 一致
            v5_spec = proj / "spec_lock_v5.md"
            v5_spec.write_text("## canvas\n- viewBox: 0 0 1920 1080\n", encoding="utf-8")
            ok, issues, ctx = check(proj)
            self.assertTrue(ok)
            self.assertEqual(ctx["spec"], str(v5_spec.resolve()))
            self.assertEqual(ctx["spec_vb"], "0 0 1920 1080")

    def test_resolve_project_dir_normalization(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1920 1080")
            sub = proj / "svg_output_v4"
            self.assertEqual(resolve_project_dir(sub), proj.resolve())
            spec_file = proj / "spec_lock.md"
            self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=sub), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
            self.assertEqual(resolve_project_dir("svg_output_v4", base_dir=proj), proj.resolve())

            render_cards = proj / "render_cards"
            render_cards.mkdir(parents=True, exist_ok=True)
            output_dir = proj / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            self.assertEqual(resolve_project_dir(render_cards), proj.resolve())
            self.assertEqual(resolve_project_dir(output_dir), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=render_cards), proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=output_dir), proj.resolve())

            with patch("scripts.sync_spec._cpm_resolve_project_dir", None):
                self.assertEqual(resolve_project_dir(sub), proj.resolve())
                self.assertEqual(resolve_project_dir(render_cards), proj.resolve())
                self.assertEqual(resolve_project_dir(output_dir), proj.resolve())
                self.assertEqual(resolve_project_dir(spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=sub), proj.resolve())
                self.assertEqual(resolve_project_dir(base_dir=spec_file), proj.resolve())
                self.assertEqual(resolve_project_dir("svg_output_v4", base_dir=proj), proj.resolve())
                self.assertEqual(resolve_project_dir(""), Path.cwd().resolve())
                self.assertEqual(resolve_project_dir("."), Path.cwd().resolve())

    def test_check_with_base_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1920 1080")
            ok, issues, ctx = check(".", base_dir=proj)
            self.assertTrue(ok)
            self.assertEqual(ctx["svg_vb"], "0 0 1920 1080")

            ok_sub, issues_sub, ctx_sub = check("svg_output_v4", base_dir=proj)
            self.assertTrue(ok_sub)
            self.assertEqual(ctx_sub["svg_vb"], "0 0 1920 1080")

            ok_spec, _, ctx_spec = check(".", spec_path="spec_lock.md", base_dir=proj)
            self.assertTrue(ok_spec)
            self.assertEqual(ctx_spec["svg_vb"], "0 0 1920 1080")

    def test_main_cli_with_base_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            alt_spec = proj / "spec_alt.md"
            alt_spec.write_text("## canvas\n- viewBox: 0 0 1280 720\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                main([".", "--spec", "spec_alt.md", "--fix"], base_dir=proj)
            self.assertEqual(cm.exception.code, 0)
            txt = alt_spec.read_text(encoding="utf-8")
            self.assertIn("- viewBox: 0 0 1920 1080\n", txt)

    def test_main_cli_spec_and_fix(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"01_a.svg": "0 0 1920 1080"}, "0 0 1280 720")
            alt_spec = proj / "spec_alt.md"
            alt_spec.write_text("## canvas\n- viewBox: 0 0 1280 720\n", encoding="utf-8")
            # 运行 main 并带 --spec 和 --fix
            with patch("sys.argv", ["sync_spec.py", str(proj), "--spec", str(alt_spec), "--fix"]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
            txt = alt_spec.read_text(encoding="utf-8")
            self.assertIn("- viewBox: 0 0 1920 1080\n", txt)


"""第 25 轮测试 B：sync_spec.check() 的 ctx 携带所用 spec 路径。"""


class CtxSpecTest(unittest.TestCase):
    def test_ctx_carries_spec_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = _make_proj(d, {"P01.svg": "0 0 1920 1080"}, "0 0 1920 1080")
            ok, issues, ctx = check(proj)
            self.assertIn("spec", ctx)
            self.assertTrue(ctx["spec"].endswith("spec_lock.md"), ctx["spec"])


if __name__ == "__main__":
    unittest.main()
