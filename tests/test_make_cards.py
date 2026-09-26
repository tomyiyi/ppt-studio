#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_make_cards.py
========================
测试 make_cards.py 的显式项目参数与安全自动发现机制。
使用临时目录与标准库 unittest，不引入第三方依赖。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.make_cards import (
    resolve_project_dir,
    main,
    parse_colors_from_spec_text,
    load_spec_colors,
    load_spec_roles,
    load_deck_title,
    card_svg,
)


def create_minimal_svg(svg_path: Path) -> None:
    """创建包含最简有效 text 的 SVG 文件。"""
    svg_content = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<text x="100" y="200" font-size="72" fill="#F7F7F9">智流 OS 核心架构</text>'
        '</svg>'
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg_content, encoding="utf-8")


class TestResolveProjectDir(unittest.TestCase):
    def test_explicit_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_proj"
            proj.mkdir()
            resolved = resolve_project_dir(str(proj))
            self.assertEqual(resolved, proj.resolve())

    def test_explicit_nonexistent_project_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_exist = Path(tmp_dir) / "does_not_exist"
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(str(non_exist))

    def test_auto_discovery_from_current_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            create_minimal_svg(base / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, base.resolve())

    def test_auto_discovery_from_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "alpha"
            create_minimal_svg(proj / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_when_base_is_projects_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "projects"
            proj = base / "beta"
            create_minimal_svg(proj / "svg_output" / "01_test.svg")
            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, proj.resolve())

    def test_auto_discovery_none_found_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                resolve_project_dir(None, base_dir=base)

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "proj_1"
            p2 = base / "projects" / "proj_2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")
            with self.assertRaises(ValueError) as ctx:
                resolve_project_dir(None, base_dir=base)
            self.assertIn("proj_1", str(ctx.exception))
            self.assertIn("proj_2", str(ctx.exception))

    def test_auto_discovery_ignores_dirs_without_svgs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p_empty = base / "projects" / "empty_dir"
            p_empty.mkdir(parents=True)
            p_no_svgs = base / "projects" / "no_svgs" / "svg_output"
            p_no_svgs.mkdir(parents=True)
            (p_no_svgs / "readme.txt").write_text("not svg", encoding="utf-8")
            p_real = base / "projects" / "real_proj"
            create_minimal_svg(p_real / "svg_output" / "01.svg")

            resolved = resolve_project_dir(None, base_dir=base)
            self.assertEqual(resolved, p_real.resolve())


class TestSpecLoading(unittest.TestCase):
    """测试规范文本解析与色彩、字号与项目标题加载。"""

    def test_parse_colors_from_spec_text_basic(self):
        text = """## colors
bg #0B0C12
accent #6E7BFF
"""
        colors = parse_colors_from_spec_text(text)
        self.assertEqual(colors.get("bg"), "#0B0C12")
        self.assertEqual(colors.get("accent"), "#6E7BFF")

    def test_parse_colors_from_spec_text_yaml_and_comments(self):
        text = """## colors
- background: "#08090C" # 背景底色
- accent: #FF6600       # 品牌强调色
- rule: #334455
"""
        colors = parse_colors_from_spec_text(text)
        self.assertEqual(colors.get("background"), "#08090C")
        self.assertEqual(colors.get("accent"), "#FF6600")
        self.assertEqual(colors.get("rule"), "#334455")

    def test_parse_colors_gradient_arrow(self):
        text = """## colors
bg #0B0C12 → #08090C（面板竖向渐变）
accent #6E7BFF
"""
        colors = parse_colors_from_spec_text(text)
        self.assertEqual(colors.get("bg"), "#0B0C12")
        self.assertEqual(colors.get("bg_bottom"), "#08090C")

    def test_load_spec_colors_from_card_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "card_spec.md").write_text(
                "## colors\naccent #FF5500\nbg #010203\n",
                encoding="utf-8",
            )
            colors = load_spec_colors(proj)
            self.assertEqual(colors.get("accent"), "#FF5500")
            self.assertEqual(colors.get("bg"), "#010203")

    def test_load_spec_colors_fallback_to_spec_lock(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "spec_lock.md").write_text(
                "## colors\n- background: #020304\n- accent: #112233\n",
                encoding="utf-8",
            )
            colors = load_spec_colors(proj)
            self.assertEqual(colors.get("accent"), "#112233")
            self.assertEqual(colors.get("bg"), "#020304")

    def test_load_spec_roles_from_card_spec(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            (proj / "card_spec.md").write_text(
                """## typography
- statement: 64 # 自定义主句
- hero: 120 # 封面
- metric: 88
""",
                encoding="utf-8",
            )
            roles = load_spec_roles(proj)
            self.assertEqual(roles.get("statement"), 64)
            self.assertEqual(roles.get("hero"), 120)
            self.assertEqual(roles.get("metric"), 88)

    def test_load_deck_title_from_cover_svg(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            cover_svg = proj / "01_cover.svg"
            cover_svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
                '<text x="80" y="300" font-size="96" fill="#FFF">超流引擎</text>'
                '</svg>',
                encoding="utf-8",
            )
            title = load_deck_title(proj, [cover_svg])
            self.assertEqual(title, "超流引擎")

    def test_load_deck_title_from_notes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "proj"
            proj.mkdir()
            notes_dir = proj / "notes"
            notes_dir.mkdir()
            (notes_dir / "01_cover.md").write_text("# 极速发布会\n\n- 开场\n", encoding="utf-8")
            title = load_deck_title(proj)
            self.assertEqual(title, "极速发布会")

    def test_load_deck_title_from_project_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "super-system-demo"
            proj.mkdir()
            title = load_deck_title(proj)
            self.assertEqual(title, "Super System Demo")


class TestCardSvgCustomization(unittest.TestCase):
    """测试 card_svg 接收自定义颜色、字号与页脚标题的渲染表现。"""

    def test_card_svg_applies_custom_accent_color(self):
        c = {
            "primary": {"text": "系统主句测试", "runs": [("系统主句测试", None)]},
            "kind": "statement",
            "support": [],
            "metrics": [({"text": "99.9%", "runs": []}, None)],
            "kicker": "KICKER",
            "badge": None,
            "title": None,
            "hero": None,
        }
        svg = card_svg(
            "02_test",
            "演示标题",
            c,
            None,
            1,
            5,
            1080,
            1350,
            colors={"accent": "#FF5500", "bg": "#101010"},
        )
        # 验证 6px 签名竖线应用了自定义强调色
        self.assertIn('fill="#FF5500"', svg)
        # 验证指标文本使用了强调色
        self.assertIn('fill="#FF5500">99.9%</text>', svg)
        # 验证页脚包含传入的演示标题
        self.assertIn('>演示标题</text>', svg)

    def test_card_svg_applies_custom_statement_size(self):
        c = {
            "primary": {"text": "主句字号测试", "runs": [("主句字号测试", None)]},
            "kind": "statement",
            "support": [],
            "metrics": [],
            "kicker": None,
            "badge": None,
            "title": None,
            "hero": None,
        }
        svg = card_svg(
            "02_test",
            "标题",
            c,
            None,
            1,
            5,
            1080,
            1350,
            sizes={"statement": 64},
        )
        self.assertIn('font-size="64"', svg)


class TestMakeCardsCLI(unittest.TestCase):
    def test_cli_explicit_argument(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            res = subprocess.run(
                [sys.executable, str(script), str(proj)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_auto_discovery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "test_proj"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            # 以项目目录作为工作目录运行，不带 project 参数
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(proj),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_auto_discovery_from_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            proj = base / "projects" / "p1"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            # 以模拟仓库根目录作为工作目录运行，不带 project 参数
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, msg=f"CLI failed: {res.stderr}")
            self.assertTrue((proj / "cards" / "01_cover.svg").exists())

    def test_cli_ambiguous_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            p1 = base / "projects" / "p1"
            p2 = base / "projects" / "p2"
            create_minimal_svg(p1 / "svg_output" / "01.svg")
            create_minimal_svg(p2 / "svg_output" / "02.svg")

            script = REPO_ROOT / "scripts" / "make_cards.py"
            res = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(base),
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("无法安全确定", res.stderr)

    def test_cli_custom_spec_integration_passes_qa(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj = Path(tmp_dir) / "custom_brand_proj"
            create_minimal_svg(proj / "svg_output" / "01_cover.svg")
            (proj / "card_spec.md").write_text(
                """## typography
- sizes: [28, 36, 44, 56, 72, 96, 132]
- statement: 72
- hero: 132

## colors
- accent: #FF6600 # 品牌橙
- bg: #0A0D14
""",
                encoding="utf-8",
            )
            script_make = REPO_ROOT / "scripts" / "make_cards.py"
            res_make = subprocess.run(
                [sys.executable, str(script_make), str(proj)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_make.returncode, 0, msg=f"make_cards failed: {res_make.stderr}")

            out_card = proj / "cards" / "01_cover.svg"
            self.assertTrue(out_card.exists())
            card_content = out_card.read_text(encoding="utf-8")
            self.assertIn('fill="#FF6600"', card_content)

            script_qa = REPO_ROOT / "scripts" / "qa_cards.py"
            res_qa = subprocess.run(
                [sys.executable, str(script_qa), str(proj)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_qa.returncode, 0, msg=f"qa_cards failed: {res_qa.stdout}\n{res_qa.stderr}")
            self.assertIn("ALL CLEAR", res_qa.stdout)


if __name__ == "__main__":
    unittest.main()
