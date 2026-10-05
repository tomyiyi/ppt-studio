#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_preview.py
========================
测试 qa_preview.py 的客观门禁判定规则、文件发现机制及 CLI 行为。
使用标准库 unittest 与 tempfile，不修改或覆盖现有 output/ 生成物。
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.qa_preview import (
    check_html_standards,
    find_preview_files,
    resolve_project_dir,
    run_qa_slide_preview,
    run_qa_showroom_portal,
    run_qa_html_file,
    run_qa_preview,
    qa_preview,
    qa_single_preview,
    run_qa_single_preview,
    main,
)


def make_valid_slide_preview_html(
    slides_count: int = 2,
    aspect_w: int = 1280,
    aspect_h: int = 720,
    active_idx: int = 0,
    include_img: bool = False,
    img_src: str = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    include_nav: bool = True,
    ind_text: str | None = None,
    include_keys: bool = True,
    include_fullscreen: bool = True,
    extra_external: str = "",
) -> str:
    """构造符合规范或用于故障测试的幻灯片预览 HTML 字符串。"""
    slides_html = []
    for i in range(slides_count):
        is_active = (i == active_idx)
        active_cls = " active" if is_active else ""
        img_tag = f'<image href="{img_src}" width="100" height="100" />' if include_img else ""
        svg = (
            f'<svg viewBox="0 0 {aspect_w} {aspect_h}">'
            f'<text x="50" y="50">Slide {i+1}</text>'
            f'{img_tag}'
            f'</svg>'
        )
        slides_html.append(f'<div class="slide{active_cls}"><div class="canvas">{svg}</div></div>')

    slides_body = "\n".join(slides_html)
    actual_ind = ind_text if ind_text is not None else f"01 / {slides_count:02d}"

    nav_html = ""
    if include_nav:
        nav_html = (
            '<div class="nav-bar">'
            '<button onclick="go(-1)">‹</button>'
            f'<div id="ind">{actual_ind}</div>'
            '<button onclick="go(1)">›</button>'
            '</div>'
        )

    key_script = ""
    if include_keys or include_fullscreen:
        key_body = []
        if include_keys:
            key_body.append('if (e.key === "ArrowRight" || e.key === "ArrowLeft" || e.key === " ") { /*翻页*/ }')
        if include_fullscreen:
            key_body.append('if (e.key === "f" || e.key === "F") { document.documentElement.requestFullscreen(); }')
        key_script = f"""
<script>
function go(n) {{}}
document.addEventListener("keydown", function(e) {{
    {" ".join(key_body)}
}});
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>测试幻灯片预览</title>
  {extra_external}
  <style>
    body {{ background: #0b0c12; margin: 0; }}
    .stage {{ width: 100vw; height: 100vh; position: relative; }}
    .slide {{ display: none; }}
    .slide.active {{ display: block; }}
  </style>
</head>
<body>
  <div class="stage">
    {slides_body}
    {nav_html}
  </div>
  {key_script}
</body>
</html>
"""


def make_valid_showroom_html(
    base_dir: Path,
    include_all_forms: bool = True,
    broken_link: bool = False,
    empty_file: bool = False,
    broken_media: bool = False,
    external_script: bool = False,
    external_style: bool = False,
    external_import: bool = False,
    custom_accent: str = "#6E7BFF",
    custom_bg: str = "#090a10",
) -> Path:
    """构造符合规范或用于故障测试的多形态展厅 index.html 及关联文件。"""
    # 创建被引用的本地物料文件
    pptx_file = base_dir / "deck.pptx"
    pptx_file.write_bytes(b"dummy pptx content" if not empty_file else b"")

    card_file = base_dir / "cards.html"
    card_file.write_text("dummy card content", encoding="utf-8")

    long_file = base_dir / "long.png"
    long_file.write_bytes(b"dummy png content")

    video_file = base_dir / "video.mp4"
    if not broken_media:
        video_file.write_bytes(b"dummy mp4 video bytes")

    short_file = base_dir / "short.mp4"
    if not broken_media:
        short_file.write_bytes(b"dummy mp4 short video bytes")

    poster_file = base_dir / "poster.png"
    if not broken_media:
        poster_file.write_bytes(b"dummy poster bytes")

    pptx_link = "deck.pptx" if not broken_link else "non_existent.pptx"

    forms_cards = []
    if include_all_forms:
        forms_cards = [
            f'<div class="card"><h3>发布会 PPT (Office 原生)</h3><a href="{pptx_link}">下载 PPTX</a></div>',
            f'<div class="card"><h3>小红书 卡片集</h3><a href="cards.html">浏览卡片</a></div>',
            f'<div class="card"><h3>纵向通读 长图</h3><a href="long.png">查看长图</a></div>',
            f'<div class="card"><h3>1080p 解说视频</h3><video poster="poster.png"><source src="video.mp4"></video></div>',
            f'<div class="card"><h3>9:16 竖版 短视频</h3><video><source src="short.mp4"></video></div>',
        ]
    else:
        forms_cards = [
            '<div class="card"><h3>未知物料</h3><p>内容不足</p></div>',
            '<div class="card"><h3>物料二</h3><p>缺少核心</p></div>',
            '<div class="card"><h3>物料三</h3><p>缺少核心</p></div>',
        ]

    ext_tags = []
    if external_script:
        ext_tags.append('<script src="http://cdn.example.com/lib.js"></script>')
    if external_style:
        ext_tags.append('<link rel="stylesheet" href="http://cdn.example.com/style.css">')
    if external_import:
        ext_tags.append('<style>@import url("http://fonts.googleapis.com/css?family=Roboto");</style>')
    ext_tag = "\n  ".join(ext_tags)

    content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ppt-studio · 全形态物料在线展厅</title>
  {ext_tag}
  <style>
    :root {{
      --bg: {custom_bg};
      --accent: {custom_accent};
    }}
    body {{
      background: radial-gradient(circle at 50% 0%, #151828 0%, var(--bg) 60%);
      color: #F7F7F9;
    }}
    .badge {{
      border: 1px solid var(--accent);
      color: var(--accent);
    }}
    .grid {{
      display: grid;
    }}
    @media (max-width: 768px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="badge">MULTI-OUTPUT PIPELINE</div>
    <h1>多形态展厅</h1>
    <p class="lead">统一生成</p>
  </header>
  <div class="grid">
    {"".join(forms_cards)}
  </div>
</body>
</html>
"""
    index_file = base_dir / "index.html"
    index_file.write_text(content, encoding="utf-8")
    return index_file


class TestCheckHtmlStandards(unittest.TestCase):
    """测试 HTML5 基础规范检查。"""

    def test_valid_html(self):
        html = '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>测试</title></head><body></body></html>'
        ok, msg = check_html_standards(html)
        self.assertTrue(ok)
        self.assertIn("HTML5 标准骨架", msg)

    def test_missing_doctype(self):
        html = '<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>测试</title></head><body></body></html>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("DOCTYPE", msg)

    def test_missing_html_tag(self):
        html = '<!DOCTYPE html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>测试</title></head>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("<html>", msg)

    def test_missing_charset(self):
        html = '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width"><title>测试</title></head></html>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("charset", msg)

    def test_missing_viewport(self):
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>测试</title></head></html>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("viewport", msg)

    def test_missing_title(self):
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"></head></html>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("title", msg)

    def test_empty_title(self):
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>   </title></head></html>'
        ok, msg = check_html_standards(html)
        self.assertFalse(ok)
        self.assertIn("title", msg)


class TestFindPreviewFiles(unittest.TestCase):
    """测试 HTML 待检文件查找与自动发现机制。"""

    def test_explicit_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "test.html"
            f.write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
            found = find_preview_files(f)
            self.assertEqual(found, [f.resolve()])

    def test_explicit_non_html_raises(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "test.txt"
            f.touch()
            with self.assertRaises(ValueError):
                find_preview_files(f)

    def test_nonexistent_target_raises(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "not_found.html"
            with self.assertRaises(FileNotFoundError):
                find_preview_files(f)

    def test_find_in_target_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            h1 = base / "a.html"
            h1.touch()
            h2 = base / "b.html"
            h2.touch()
            found = find_preview_files(base)
            self.assertEqual(found, [h1.resolve(), h2.resolve()])

    def test_find_in_output_subfolder(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_dir = base / "output"
            out_dir.mkdir()
            h = out_dir / "preview.html"
            h.touch()
            found = find_preview_files(base)
            self.assertEqual(found, [h.resolve()])

    def test_find_in_projects_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            p_out = base / "projects" / "p1" / "output"
            p_out.mkdir(parents=True)
            h = p_out / "portal.html"
            h.touch()
            found = find_preview_files(base)
            self.assertEqual(found, [h.resolve()])

    def test_relative_path_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            sub = base / "subdir"
            sub.mkdir()
            h = sub / "view.html"
            h.touch()
            found = find_preview_files("subdir", base_dir=base)
            self.assertEqual(found, [h.resolve()])

    def test_find_in_parent_output_when_called_from_subdir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_dir = base / "output"
            out_dir.mkdir()
            h = out_dir / "preview.html"
            h.touch()
            sub = base / "projects" / "my_project"
            sub.mkdir(parents=True)
            found = find_preview_files(sub)
            self.assertEqual(found, [h.resolve()])


class TestRunQaSlidePreview(unittest.TestCase):
    """测试幻灯片交互式预览质检门禁。"""

    def test_valid_pure_vector_slide_preview(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_img=False)
            p.write_text(html, encoding="utf-8")
            self.assertTrue(run_qa_slide_preview(p))

    def test_comma_separated_viewbox_slide_preview(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_img=False)
            html = html.replace('viewBox="0 0 1280 720"', 'viewBox="0, 0, 1280, 720"')
            p.write_text(html, encoding="utf-8")
            self.assertTrue(run_qa_slide_preview(p))

    def test_valid_slide_preview_with_embedded_image(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            # 填充足够长度保证通过大于 10KB 要求
            big_b64 = "data:image/png;base64," + ("A" * 16000)
            html = make_valid_slide_preview_html(slides_count=2, include_img=True, img_src=big_b64)
            p.write_text(html, encoding="utf-8")
            self.assertTrue(run_qa_slide_preview(p))

    def test_external_image_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_img=True, img_src="../images/pic.png")
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_corrupt_data_uri_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_img=True, img_src="data:image/png;base64,")
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_missing_slides_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>测试</title></head><body><div class="stage"></div></body></html>'
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_multiple_active_slides_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2)
            # 将第二页也设为 active
            html = html.replace('class="slide"', 'class="slide active"', 1)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_non_first_active_slide_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, active_idx=1)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_aspect_ratio_drift_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2)
            # 修改第二页的 viewBox 为 1080 1350
            html = html.replace('viewBox="0 0 1280 720"', 'viewBox="0 0 1080 1350"', 1)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_missing_nav_buttons_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_nav=False)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_mismatched_indicator_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=3, ind_text="01 / 02")
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_missing_keyboard_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            html = make_valid_slide_preview_html(slides_count=2, include_keys=False)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_external_cdn_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            ext = '<script src="https://cdn.jsdelivr.net/npm/vue@3"></script>'
            html = make_valid_slide_preview_html(slides_count=2, extra_external=ext)
            p.write_text(html, encoding="utf-8")
            self.assertFalse(run_qa_slide_preview(p))

    def test_severely_truncated_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            p.write_text("<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='w'><title>T</title></head><body><div class='slide active'><svg viewBox='0 0 1280 720'></svg></div><button onclick='go(-1)'></button><button onclick='go(1)'></button><div id='ind'>01 / 01</div><script>function go(){};document.addEventListener('keydown',function(e){if(e.key==='ArrowRight'||e.key==='ArrowLeft'||e.key===' '){}if(e.key==='f'||e.key==='F'){document.documentElement.requestFullscreen();}});</script></body></html>", encoding="utf-8")
            # 截断到极小字节
            p.write_bytes(p.read_bytes()[:200])
            self.assertFalse(run_qa_slide_preview(p))

    def test_nav_buttons_with_spaces_and_span_indicator(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "custom_tags.html"
            html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>自定义指示器测试</title>
  <style>
    body { background: #0b0c12; margin: 0; }
    .stage { width: 100vw; height: 100vh; position: relative; }
    .slide { display: none; }
    .slide.active { display: block; }
    .canvas { width: 100%; height: 100%; }
    .nav-bar { position: absolute; }
  </style>
</head>
<body>
  <div class="stage">
    <div class="slide active"><div class="canvas"><svg viewBox="0 0 1280 720"><text>S1</text></svg></div></div>
    <div class="slide"><div class="canvas"><svg viewBox="0 0 1280 720"><text>S2</text></svg></div></div>
  </div>
  <div class="nav-bar">
    <button onclick="go( -1 )">‹</button>
    <span id="ind">01 / 02</span>
    <button onclick="go( 1 )">›</button>
  </div>
<script>
function go(n) {}
document.addEventListener("keydown", function(e) {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {}
    if (e.key === "f" || e.key === "F") { document.documentElement.requestFullscreen(); }
});
</script>
</body>
</html>"""
            p.write_text(html, encoding="utf-8")
            self.assertTrue(run_qa_slide_preview(p, verbose=False))


class TestRunQaShowroomPortal(unittest.TestCase):
    """测试多形态物料展厅客观门禁。"""

    def test_valid_showroom_portal(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base)
            self.assertTrue(run_qa_showroom_portal(index_path))

    def test_missing_material_forms_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, include_all_forms=False)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_broken_link_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, broken_link=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_empty_linked_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, empty_file=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_broken_media_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, broken_media=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_external_script_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, external_script=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_external_style_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, external_style=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_external_import_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, external_import=True)
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_truncated_showroom_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base)
            index_path.write_bytes(index_path.read_bytes()[:200])
            self.assertFalse(run_qa_showroom_portal(index_path))

    def test_non_standard_colors_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base, custom_accent="#FF0000", custom_bg="#FFFFFF")
            self.assertFalse(run_qa_showroom_portal(index_path))


class TestRunQaHtmlFileRouting(unittest.TestCase):
    """测试 run_qa_html_file 根据页面类型自动路由。"""

    def test_routes_to_showroom(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            index_path = make_valid_showroom_html(base)
            self.assertTrue(run_qa_html_file(index_path))

    def test_routes_to_slide_preview(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "deck_preview.html"
            html = make_valid_slide_preview_html(slides_count=2)
            p.write_text(html, encoding="utf-8")
            self.assertTrue(run_qa_html_file(p))

    def test_run_qa_single_preview_alias(self):
        self.assertIs(run_qa_single_preview, run_qa_html_file)
        self.assertIs(qa_single_preview, run_qa_html_file)
        self.assertIs(qa_preview, run_qa_preview)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "preview.html"
            p.write_text(make_valid_slide_preview_html(slides_count=1), encoding="utf-8")
            self.assertTrue(run_qa_single_preview(p, verbose=False))

    def test_unreadable_file_fails(self):
        p = Path("/non_existent_dir_12345/non_existent_file.html")
        self.assertFalse(run_qa_html_file(p))


class TestMainCli(unittest.TestCase):
    """测试命令行入口 CLI。"""

    def test_cli_success_on_valid_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "slide.html"
            html = make_valid_slide_preview_html(slides_count=1)
            p.write_text(html, encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main([str(p)])
            self.assertEqual(code, 0)

    def test_cli_quiet_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "slide.html"
            html = make_valid_slide_preview_html(slides_count=1)
            p.write_text(html, encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as out_q:
                code_q = main([str(p), "-q"])
            self.assertEqual(code_q, 0)
            self.assertEqual(out_q.getvalue(), "")

            with patch("sys.stdout", new_callable=io.StringIO) as out_quiet:
                code_quiet = main([str(p), "--quiet"])
            self.assertEqual(code_quiet, 0)
            self.assertEqual(out_quiet.getvalue(), "")

    def test_cli_verbose_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "slide.html"
            html = make_valid_slide_preview_html(slides_count=1)
            p.write_text(html, encoding="utf-8")
            with patch("sys.stdout", new_callable=io.StringIO) as out_v:
                code_v = main([str(p), "-v"])
            self.assertEqual(code_v, 0)
            self.assertIn("ALL CLEAR", out_v.getvalue())

            with patch("sys.stdout", new_callable=io.StringIO) as out_verbose:
                code_verbose = main([str(p), "--verbose"])
            self.assertEqual(code_verbose, 0)
            self.assertIn("ALL CLEAR", out_verbose.getvalue())

    def test_cli_fails_on_nonexistent_target(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            code = main(["/path/does_not_exist_xyz.html"])
        self.assertEqual(code, 1)

    def test_cli_fails_when_no_html_found_in_dir(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main([td])
            self.assertEqual(code, 1)


class TestQAPreviewSubdirAndSpecResolution(unittest.TestCase):
    """测试 qa_preview 对子目录、规范文件及单文件自适应项目解析。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.proj = Path(self.td.name) / "test_proj"
        self.svg_dir = self.proj / "svg_output"
        self.render_dir = self.proj / "render"
        self.images_dir = self.proj / "images"
        self.notes_dir = self.proj / "notes"
        self.output_dir = self.proj / "output"
        self.svg_dir.mkdir(parents=True)
        self.render_dir.mkdir(parents=True)
        self.images_dir.mkdir(parents=True)
        self.notes_dir.mkdir(parents=True)
        self.output_dir.mkdir(parents=True)

        self.spec_file = self.proj / "spec_lock.md"
        self.spec_file.write_text("# spec\n", encoding="utf-8")

        self.preview_html = self.output_dir / "preview.html"
        self.preview_html.write_text(
            make_valid_slide_preview_html(slides_count=2),
            encoding="utf-8",
        )

    def tearDown(self):
        self.td.cleanup()

    def test_resolve_project_dir_subfolders_and_file(self):
        self.assertEqual(resolve_project_dir(self.svg_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.render_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.images_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.notes_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(self.spec_file), self.proj.resolve())

    def test_resolve_project_dir_render_cards_and_output(self):
        render_cards = self.proj / "render_cards"
        render_cards.mkdir(parents=True, exist_ok=True)
        output_dir = self.proj / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.assertEqual(resolve_project_dir(render_cards), self.proj.resolve())
        self.assertEqual(resolve_project_dir(output_dir), self.proj.resolve())

    def test_resolve_project_dir_fallback_without_cpm(self):
        from unittest.mock import patch
        with patch("scripts.qa_preview._cpm_resolve_project_dir", None):
            self.assertEqual(resolve_project_dir(self.svg_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(self.render_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(self.images_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(self.notes_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(self.spec_file), self.proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=self.svg_dir), self.proj.resolve())
            self.assertEqual(resolve_project_dir(base_dir=self.spec_file), self.proj.resolve())
            self.assertEqual(resolve_project_dir(""), Path.cwd().resolve())
            self.assertEqual(resolve_project_dir("."), Path.cwd().resolve())

    def test_resolve_project_dir_base_dir(self):
        self.assertEqual(resolve_project_dir(base_dir=self.svg_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.render_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.images_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.notes_dir), self.proj.resolve())
        self.assertEqual(resolve_project_dir(base_dir=self.spec_file), self.proj.resolve())

    def test_find_preview_files_from_subfolder(self):
        found_render = find_preview_files(self.render_dir)
        self.assertEqual(found_render, [self.preview_html.resolve()])

        found_images = find_preview_files(self.images_dir)
        self.assertEqual(found_images, [self.preview_html.resolve()])

    def test_find_preview_files_from_spec_file(self):
        found_spec = find_preview_files(self.spec_file)
        self.assertEqual(found_spec, [self.preview_html.resolve()])

    def test_find_preview_files_from_spec_file_without_html_raises(self):
        empty_proj = Path(self.td.name) / "empty_proj"
        empty_proj.mkdir(parents=True)
        empty_spec = empty_proj / "spec_lock.md"
        empty_spec.write_text("# spec\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            find_preview_files(empty_spec)
        self.assertIn("未发现 HTML 文件", str(ctx.exception))

    def test_run_qa_preview_from_subfolder_and_spec_file(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(run_qa_preview(self.render_dir))
            self.assertTrue(run_qa_preview(self.spec_file))

    def test_cli_from_subfolder_and_spec_file(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            code1 = main([str(self.render_dir)])
            self.assertEqual(code1, 0)
            code2 = main([str(self.spec_file)])
            self.assertEqual(code2, 0)

    def test_run_qa_preview_and_main_with_base_dir(self):
        base = Path(self.td.name)
        rel_proj = self.proj.relative_to(base)
        rel_html = self.preview_html.relative_to(base)

        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertTrue(run_qa_slide_preview(rel_html, base_dir=base))
            self.assertTrue(run_qa_html_file(rel_html, base_dir=base))
            self.assertTrue(run_qa_preview(rel_proj, base_dir=base))
            self.assertEqual(main([str(rel_proj)], base_dir=base), 0)
            self.assertEqual(main([str(rel_html)], base_dir=base), 0)

    def test_cli_with_base_dir_flag(self):
        base = Path(self.td.name)
        rel_proj = self.proj.relative_to(base)
        rel_html = self.preview_html.relative_to(base)

        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main([str(rel_proj), "--base-dir", str(base)]), 0)
            self.assertEqual(main([str(rel_html), "--base-dir", str(base)]), 0)


if __name__ == "__main__":
    unittest.main()
