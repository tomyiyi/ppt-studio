"""tests/test_spec_resolve.py -- spec_lock 多版本治理（第 20 轮）。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.spec_resolve import candidate_dirs, find_spec, resolve_spec, main


class TestResolveSpec(unittest.TestCase):
    def _proj(self, td: str, files: list[str]) -> Path:
        proj = Path(td) / "proj"
        proj.mkdir()
        for f in files:
            (proj / f).write_text("# dummy\n", encoding="utf-8")
        return proj

    def test_versioned_beats_base(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(td, ["spec_lock.md", "spec_lock_v4.md"])
            self.assertEqual(resolve_spec(proj), (proj / "spec_lock_v4.md").resolve())

    def test_highest_version_wins(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(td, ["spec_lock_v2.md", "spec_lock_v10.md", "spec_lock.md"])
            self.assertEqual(resolve_spec(proj), (proj / "spec_lock_v10.md").resolve())

    def test_falls_back_to_base(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(td, ["spec_lock.md"])
            self.assertEqual(resolve_spec(proj), (proj / "spec_lock.md").resolve())

    def test_backup_variants_never_selected(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(
                td,
                ["spec_lock.md.bak-20260930b", "spec_lock.md.v2bak", "spec_lock.md.v3new"],
            )
            self.assertIsNone(resolve_spec(proj))

    def test_backup_variants_ignored_when_base_exists(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(td, ["spec_lock.md", "spec_lock.md.bak-20260930b"])
            self.assertEqual(resolve_spec(proj), (proj / "spec_lock.md").resolve())

    def test_non_numeric_version_suffix_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            proj = self._proj(td, ["spec_lock.md", "spec_lock_vnext.md"])
            self.assertEqual(resolve_spec(proj), (proj / "spec_lock.md").resolve())

    def test_missing_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(resolve_spec(Path(td) / "nope"))

    def test_empty_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(resolve_spec(Path(td)))

    def test_resolve_spec_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# base\n", encoding="utf-8")
            self.assertEqual(resolve_spec("my_proj", base_dir=base), (proj / "spec_lock.md").resolve())


class TestFindSpec(unittest.TestCase):
    def test_finds_from_nested_file(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            (proj / "output").mkdir(parents=True)
            (proj / "spec_lock_v4.md").write_text("# v4\n", encoding="utf-8")
            (proj / "spec_lock.md").write_text("# v3\n", encoding="utf-8")
            target = proj / "output" / "deck.pptx"
            target.touch()
            self.assertEqual(find_spec(target), (proj / "spec_lock_v4.md").resolve())

    def test_finds_from_project_dir(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# v3\n", encoding="utf-8")
            self.assertEqual(find_spec(proj), (proj / "spec_lock.md").resolve())

    def test_none_when_nothing_found(self):
        with tempfile.TemporaryDirectory() as td:
            # 目标目录本身无 spec；兜底扫描限定在 cwd 与仓库，临时目录不在其中
            # 这里只断言空目录返回 None（不依赖仓库状态）
            empty = Path(td) / "empty"
            empty.mkdir()
            self.assertIsNone(resolve_spec(empty))

    def test_candidate_dirs_deduped_and_ordered(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            proj.mkdir()
            target = proj / "deck.pptx"
            target.touch()
            dirs = candidate_dirs(target)
            self.assertEqual(dirs[0], proj.resolve())
            self.assertEqual(len(dirs), len({str(d) for d in dirs}))

    def test_find_spec_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# v1\n", encoding="utf-8")
            target = proj / "output" / "deck.pptx"
            target.parent.mkdir()
            target.touch()
            self.assertEqual(find_spec("proj/output/deck.pptx", base_dir=base), (proj / "spec_lock.md").resolve())


class TestSvgToPptxSoftDep(unittest.TestCase):
    """第 20 轮：无 python-pptx 时 svg_to_pptx 仍可 import（--help/--check 可用）。"""

    def test_align_map_guard_without_pptx(self):
        import sys

        # 模拟无 pptx 环境：阻止 pptx 导入后重载模块
        saved = {k: v for k, v in sys.modules.items() if k == "pptx" or k.startswith("pptx.")}
        # 第 27 轮：记住原模块对象；finally 必须恢复，否则 sys.modules 里
        # scripts.svg_to_pptx 悬空，后续 patch("scripts.svg_to_pptx.…") 会打到
        # 新 import 出来的模块对象上，对已绑定的旧函数引用无效（测试间污染）。
        orig_svg2pptx = sys.modules.get("scripts.svg_to_pptx")
        for k in saved:
            del sys.modules[k]
        sys.modules["pptx"] = None  # type: ignore[assignment]

        for mod in [m for m in list(sys.modules) if m == "scripts.svg_to_pptx" or m.startswith("scripts.svg_to_pptx.")]:
            del sys.modules[mod]
        try:
            import scripts.svg_to_pptx as m

            self.assertFalse(m._PPTX_OK)
            self.assertEqual(m._ALIGN_MAP, {})
        finally:
            for mod in [m for m in list(sys.modules) if m == "scripts.svg_to_pptx" or m.startswith("scripts.svg_to_pptx.")]:
                del sys.modules[mod]
            del sys.modules["pptx"]
            sys.modules.update(saved)
            if orig_svg2pptx is not None:
                sys.modules["scripts.svg_to_pptx"] = orig_svg2pptx

    def test_build_raises_clear_error_without_pptx(self):
        import sys

        saved = {k: v for k, v in sys.modules.items() if k == "pptx" or k.startswith("pptx.")}
        # 第 27 轮：记住原模块对象；finally 必须恢复，否则 sys.modules 里
        # scripts.svg_to_pptx 悬空，后续 patch("scripts.svg_to_pptx.…") 会打到
        # 新 import 出来的模块对象上，对已绑定的旧函数引用无效（测试间污染）。
        orig_svg2pptx = sys.modules.get("scripts.svg_to_pptx")
        for k in saved:
            del sys.modules[k]
        sys.modules["pptx"] = None  # type: ignore[assignment]
        for mod in [m for m in list(sys.modules) if m == "scripts.svg_to_pptx" or m.startswith("scripts.svg_to_pptx.")]:
            del sys.modules[mod]
        try:
            import scripts.svg_to_pptx as m

            with self.assertRaises(RuntimeError) as ctx:
                m.build_pptx([], Path("/tmp/x.pptx"))
            self.assertIn("python-pptx", str(ctx.exception))
        finally:
            for mod in [m for m in list(sys.modules) if m == "scripts.svg_to_pptx" or m.startswith("scripts.svg_to_pptx.")]:
                del sys.modules[mod]
            del sys.modules["pptx"]
            sys.modules.update(saved)
            if orig_svg2pptx is not None:
                sys.modules["scripts.svg_to_pptx"] = orig_svg2pptx


class TestSpecResolveMain(unittest.TestCase):
    def test_main_resolve_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# spec\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(proj)], base_dir=base)
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), str((proj / "spec_lock.md").resolve()))

    def test_main_find_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# spec\n", encoding="utf-8")
            target = proj / "deck.pptx"
            target.touch()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(target)], base_dir=base)
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), str((proj / "spec_lock.md").resolve()))

    def test_main_with_base_dir_cli(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "spec_lock_v2.md").write_text("# v2\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["proj", "--base-dir", str(base)])
            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), str((proj / "spec_lock_v2.md").resolve()))

    def test_main_json_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text("# spec\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["proj", "--base-dir", str(base), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["found"])
            self.assertEqual(data["spec"], str((proj / "spec_lock.md").resolve()))

    def test_main_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            empty = base / "empty"
            empty.mkdir()
            err_buf = io.StringIO()
            with contextlib.redirect_stderr(err_buf):
                rc = main([str(empty)], base_dir=base)
            self.assertEqual(rc, 1)
            self.assertIn("未找到 spec", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
