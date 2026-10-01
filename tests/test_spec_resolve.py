"""tests/test_spec_resolve.py -- spec_lock 多版本治理（第 20 轮）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.spec_resolve import candidate_dirs, find_spec, resolve_spec


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


if __name__ == "__main__":
    unittest.main()
