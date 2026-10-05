#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_pptx.py
=====================
测试 qa_pptx.py 的客观门禁判定规则、文件发现机制及 CLI 行为。
使用标准库 unittest、zipfile 与 tempfile，不修改或覆盖现有 output/ 生成物。
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.qa_pptx import (
    load_spec_typography,
    load_spec_ramp,
    check_zip_and_structure,
    check_geometry,
    check_media,
    check_slide_layers,
    check_font_ramp,
    check_role_consistency,
    check_relationships,
    find_spec_lock,
    find_pptx_files,
    resolve_project_dir,
    qa_single_pptx,
    run_qa_single_pptx,
    run_qa_pptx,
    qa_pptx,
    main,
)

# 1x1 红色有效 PNG 字节
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def create_mock_pptx(
    target_path: Path,
    cx: int = 12192000,
    cy: int = 6858000,
    slides_count: int = 3,
    has_media: bool = False,
    corrupt_media: bool = False,
    include_pic: bool = True,
    include_sp: bool = True,
    statement_sz: int = 2800,  # 28pt = 56px @1920px->13.333in (2800/100/0.5)
    second_stmt_sz: int | None = None,
    off_ramp_sz: int | None = None,
    missing_required_entry: str | None = None,
    broken_rel: bool = False,
    include_external_rel: bool = False,
) -> Path:
    """在指定路径生成结构合规或包含注入异常的合成 PPTX 文件。"""
    with zipfile.ZipFile(target_path, "w") as z:
        if missing_required_entry != "[Content_Types].xml":
            z.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '</Types>',
            )

        if missing_required_entry != "ppt/presentation.xml":
            z.writestr(
                "ppt/presentation.xml",
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f'<p:sldSz cx="{cx}" cy="{cy}"/>'
                f'</p:presentation>',
            )

        if missing_required_entry != "ppt/_rels/presentation.xml.rels":
            z.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
            )

        if has_media:
            media_bytes = b"" if corrupt_media else TINY_PNG
            z.writestr("ppt/media/image1.png", media_bytes)

        for i in range(1, slides_count + 1):
            slide_name = f"ppt/slides/slide{i}.xml"
            curr_stmt = statement_sz
            if i == 2 and second_stmt_sz is not None:
                curr_stmt = second_stmt_sz

            sp_elements = []
            if include_sp:
                rpr_sz_attr = f' sz="{curr_stmt}"'
                if off_ramp_sz is not None and i == 1:
                    rpr_sz_attr = f' sz="{off_ramp_sz}"'
                sp_elements.append(
                    f'<p:sp>'
                    f'<p:txBody>'
                    f'<a:p><a:r><a:rPr{rpr_sz_attr}/><a:t>幻灯片第 {i} 页主句</a:t></a:r></a:p>'
                    f'</p:txBody>'
                    f'</p:sp>'
                )

            pic_elements = []
            if include_pic and has_media:
                pic_elements.append(
                    '<p:pic><p:blipFill><a:blip r:embed="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></p:blipFill></p:pic>'
                )

            slide_xml = (
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f'<p:cSld><p:spTree>'
                f'{"".join(pic_elements)}'
                f'{"".join(sp_elements)}'
                f'</p:spTree></p:cSld>'
                f'</p:sld>'
            )
            z.writestr(slide_name, slide_xml)

            # Slide relationships
            rel_path = f"ppt/slides/_rels/slide{i}.xml.rels"
            rels = []
            if has_media:
                target_rel = "../media/image1.png" if not broken_rel else "../media/non_existent.png"
                rels.append(
                    f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target_rel}"/>'
                )
            if include_external_rel:
                rels.append(
                    '<Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>'
                )

            rels_xml = (
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'{"".join(rels)}'
                f'</Relationships>'
            )
            z.writestr(rel_path, rels_xml)

    return target_path


class TestLoadSpecTypography(unittest.TestCase):
    """测试 spec_lock.md 字号阶梯解析。"""

    def test_default_when_no_spec(self):
        ramp, stmt_sz = load_spec_typography(None)
        self.assertEqual(ramp, [11, 13, 16, 20, 24, 32, 44, 56, 96])
        self.assertEqual(stmt_sz, 56)

    def test_custom_spec_typography(self):
        content = """# spec
## typography
- headline: 96
- statement: 44
- body: 20
- footnote: 13
"""
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec_lock.md"
            spec.write_text(content, encoding="utf-8")
            ramp, stmt_sz = load_spec_typography(spec)
            self.assertEqual(stmt_sz, 44)
            self.assertIn(44, ramp)
            self.assertIn(96, ramp)
            self.assertEqual(load_spec_ramp(spec), ramp)

    def test_sizes_directive_and_inline_comments(self):
        content = """# spec
- sizes: [11, 13, 16, 20, 24, 32, 44, 56, 96] # 阶梯

## typography
- statement: 44 # 统摄主句
- 96 headline # 封面主标
- body: 16 # 正文
"""
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec_lock.md"
            spec.write_text(content, encoding="utf-8")
            ramp, stmt_sz = load_spec_typography(spec)
            self.assertEqual(stmt_sz, 44)
            self.assertIn(16, ramp)
            self.assertIn(44, ramp)
            self.assertIn(96, ramp)

    def test_nonexistent_spec_path_fallback(self):
        ramp, stmt_sz = load_spec_typography(Path("/path/to/nonexistent/spec_lock.md"))
        self.assertEqual(ramp, [11, 13, 16, 20, 24, 32, 44, 56, 96])
        self.assertEqual(stmt_sz, 56)


class TestCheckZipAndStructure(unittest.TestCase):
    """测试 PPTX Zip 基础结构与 presentation.xml 检验。"""

    def test_valid_structure(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx")
            with zipfile.ZipFile(p, "r") as z:
                ok, msg, pres_xml = check_zip_and_structure(z)
                self.assertTrue(ok)
                self.assertIsNotNone(pres_xml)
                self.assertIn("基础骨架完整", msg)

    def test_missing_content_types(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", missing_required_entry="[Content_Types].xml")
            with zipfile.ZipFile(p, "r") as z:
                ok, msg, pres_xml = check_zip_and_structure(z)
                self.assertFalse(ok)
                self.assertIsNone(pres_xml)
                self.assertIn("缺少关键 OpenXML 结构文件", msg)

    def test_corrupt_presentation_xml(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "bad.pptx"
            with zipfile.ZipFile(target, "w") as z:
                z.writestr("[Content_Types].xml", "<types/>")
                z.writestr("ppt/_rels/presentation.xml.rels", "<rels/>")
                z.writestr("ppt/presentation.xml", "<unclosed_xml")
            with zipfile.ZipFile(target, "r") as z:
                ok, msg, pres_xml = check_zip_and_structure(z)
                self.assertFalse(ok)
                self.assertIn("解析异常", msg)


class TestCheckGeometry(unittest.TestCase):
    """测试画幅比例客观门禁。"""

    def test_valid_16_9(self):
        xml_str = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="12192000" cy="6858000"/></p:presentation>'
        root = ET.fromstring(xml_str)
        ok, msg = check_geometry(root)
        self.assertTrue(ok)
        self.assertIn("16:9 比例标准", msg)

    def test_invalid_aspect_ratio_4_3(self):
        xml_str = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="9144000" cy="6858000"/></p:presentation>'
        root = ET.fromstring(xml_str)
        ok, msg = check_geometry(root)
        self.assertFalse(ok)
        self.assertIn("非 16:9 比例", msg)

    def test_missing_sldSz(self):
        xml_str = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
        root = ET.fromstring(xml_str)
        ok, msg = check_geometry(root)
        self.assertFalse(ok)
        self.assertIn("未找到 <p:sldSz>", msg)

    def test_zero_dimensions(self):
        xml_str = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="0" cy="6858000"/></p:presentation>'
        root = ET.fromstring(xml_str)
        ok, msg = check_geometry(root)
        self.assertFalse(ok)
        self.assertIn("非法画幅尺寸", msg)


class TestCheckMedia(unittest.TestCase):
    """测试媒体资源检验。"""

    def test_pure_vector_no_media(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "vector.pptx", has_media=False)
            with zipfile.ZipFile(p, "r") as z:
                ok, msg = check_media(z)
                self.assertTrue(ok)
                self.assertIn("无内嵌媒体文件", msg)

    def test_valid_embedded_png(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "media.pptx", has_media=True)
            with zipfile.ZipFile(p, "r") as z:
                ok, msg = check_media(z)
                self.assertTrue(ok)
                self.assertIn("全部有效", msg)

    def test_corrupt_empty_media(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "corrupt.pptx", has_media=True, corrupt_media=True)
            with zipfile.ZipFile(p, "r") as z:
                ok, msg = check_media(z)
                self.assertFalse(ok)
                self.assertIn("存在损坏或无效媒体", msg)

    def test_expected_media_count_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "media.pptx", has_media=True)
            with zipfile.ZipFile(p, "r") as z:
                ok, msg = check_media(z, expected_media=5)
                self.assertFalse(ok)
                self.assertIn("媒体文件数", msg)


class TestCheckSlideLayers(unittest.TestCase):
    """测试幻灯片图层结构。"""

    def test_valid_layers(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", has_media=True, include_pic=True, include_sp=True)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg = check_slide_layers(z, slides, has_media=True)
                self.assertTrue(ok)
                self.assertIn("结构完整", msg)

    def test_missing_pic_when_media_expected(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", has_media=True, include_pic=False, include_sp=True)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg = check_slide_layers(z, slides, has_media=True)
                self.assertFalse(ok)
                self.assertIn("缺失配图层", msg)

    def test_missing_text_sp(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", has_media=False, include_pic=False, include_sp=False)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg = check_slide_layers(z, slides, has_media=False)
                self.assertFalse(ok)
                self.assertIn("缺失文本图元", msg)

    def test_no_slides_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx")
            with zipfile.ZipFile(p, "r") as z:
                ok, msg = check_slide_layers(z, [], has_media=False)
                self.assertFalse(ok)
                self.assertIn("无幻灯片", msg)


class TestCheckFontRamp(unittest.TestCase):
    """测试字号阶梯符合度。"""

    def test_compliant_ramp(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", statement_sz=2800)  # 56px
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg, text_map = check_font_ramp(z, slides, [11, 13, 16, 20, 24, 32, 44, 56, 96])
                self.assertTrue(ok)
                self.assertIn("全部合规", msg)

    def test_off_ramp_size_detected(self):
        with tempfile.TemporaryDirectory() as td:
            # 2500/100/0.5 = 50px (不在阶梯内)
            p = create_mock_pptx(Path(td) / "test.pptx", off_ramp_sz=2500)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg, _ = check_font_ramp(z, slides, [11, 13, 16, 20, 24, 32, 44, 56, 96])
                self.assertFalse(ok)
                self.assertIn("发现非规范字号", msg)


class TestCheckRoleConsistency(unittest.TestCase):
    """测试跨页主句字号一致性。"""

    def test_fewer_than_3_slides_skipped(self):
        mapping = {"ppt/slides/slide1.xml": [(56, "封面")], "ppt/slides/slide2.xml": [(56, "正文")]}
        ok, msg = check_role_consistency(mapping, 56)
        self.assertTrue(ok)
        self.assertIn("跳过", msg)

    def test_consistent_statement(self):
        mapping = {
            "ppt/slides/slide1.xml": [(96, "封面大标题")],
            "ppt/slides/slide2.xml": [(56, "正文一主句")],
            "ppt/slides/slide3.xml": [(56, "正文二主句")],
            "ppt/slides/slide4.xml": [(56, "正文三主句")],
        }
        ok, msg = check_role_consistency(mapping, 56)
        self.assertTrue(ok)
        self.assertIn("与 spec 对齐", msg)

    def test_drifting_statement_detected(self):
        mapping = {
            "ppt/slides/slide1.xml": [(96, "封面大标题")],
            "ppt/slides/slide2.xml": [(56, "正文一主句")],
            "ppt/slides/slide3.xml": [(72, "正文二变大主句")],  # 72px
            "ppt/slides/slide4.xml": [(56, "正文三主句")],
        }
        ok, msg = check_role_consistency(mapping, 56)
        self.assertFalse(ok)
        self.assertIn("不符", msg)

    def test_slide_with_only_small_elements_not_treated_as_statement(self):
        # 模拟如 06_before_after 仅有正文或指标标注（最大 24px），不误判为主句漂移
        mapping = {
            "ppt/slides/slide1.xml": [(96, "封面大标题")],
            "ppt/slides/slide2.xml": [(56, "正文一主句")],
            "ppt/slides/slide3.xml": [(56, "正文二主句")],
            "ppt/slides/slide4.xml": [(24, "对比图表标注")],
            "ppt/slides/slide5.xml": [(56, "正文四主句")],
        }
        ok, msg = check_role_consistency(mapping, 56)
        self.assertTrue(ok)
        self.assertIn("与 spec 对齐", msg)

    def test_mismatch_with_expected_statement_size(self):
        mapping = {
            "ppt/slides/slide1.xml": [(96, "封面大标题")],
            "ppt/slides/slide2.xml": [(72, "正文一主句")],  # 72px
            "ppt/slides/slide3.xml": [(72, "正文二主句")],  # 72px
            "ppt/slides/slide4.xml": [(72, "正文三主句")],  # 72px
        }
        ok, msg = check_role_consistency(mapping, 56)
        self.assertFalse(ok)
        self.assertIn("spec 期望", msg)


class TestFindSpecLock(unittest.TestCase):
    """测试 spec_lock.md 动态发现。"""

    def test_find_spec_lock_from_output_file(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            proj.mkdir()
            (proj / "spec_lock.md").touch()
            out_pptx = proj / "output" / "deck.pptx"
            out_pptx.parent.mkdir()
            out_pptx.touch()

            found = find_spec_lock(out_pptx)
            self.assertEqual(found, (proj / "spec_lock.md").resolve())

    def test_find_spec_lock_from_project_dir(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_project"
            proj.mkdir()
            (proj / "spec_lock.md").touch()

            found = find_spec_lock(proj)
            self.assertEqual(found, (proj / "spec_lock.md").resolve())

    def test_find_spec_lock_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "my_project"
            proj.mkdir()
            (proj / "spec_lock.md").touch()

            found = find_spec_lock("my_project", base_dir=base)
            self.assertEqual(found, (proj / "spec_lock.md").resolve())


class TestCheckRelationships(unittest.TestCase):
    """测试 OpenXML .rels 引用闭环。"""

    def test_closed_relationships(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", has_media=True, broken_rel=False, include_external_rel=True)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg = check_relationships(z, slides)
                self.assertTrue(ok)
                self.assertIn("无断链", msg)

    def test_broken_relationship_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "test.pptx", has_media=True, broken_rel=True)
            with zipfile.ZipFile(p, "r") as z:
                slides = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
                ok, msg = check_relationships(z, slides)
                self.assertFalse(ok)
                self.assertIn("断链关系引用", msg)


class TestFindPptxFiles(unittest.TestCase):
    """测试 PPTX 待质检文件发现逻辑。"""

    def test_explicit_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "file.pptx")
            found = find_pptx_files(p)
            self.assertEqual(found, [p.resolve()])

    def test_explicit_non_pptx_raises(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "file.txt"
            f.touch()
            with self.assertRaises(ValueError):
                find_pptx_files(f)

    def test_nonexistent_target_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                find_pptx_files(Path(td) / "not_found.pptx")

    def test_find_in_target_dir_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            p1 = create_mock_pptx(base / "a.pptx")
            out_dir = base / "output"
            out_dir.mkdir()
            p2 = create_mock_pptx(out_dir / "b.pptx")
            found = find_pptx_files(base)
            self.assertEqual(found, [p1.resolve(), p2.resolve()])

    def test_find_in_projects_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            p_out = base / "projects" / "proj_alpha" / "output"
            p_out.mkdir(parents=True)
            p = create_mock_pptx(p_out / "deck.pptx")
            found = find_pptx_files(base)
            self.assertEqual(found, [p.resolve()])

    def test_find_pptx_files_none_default(self):
        # find_pptx_files(None) 不应触发 TypeError 且安全回退到当前目录
        res = find_pptx_files(None)
        self.assertIsInstance(res, list)


class TestRunQaPptxAPI(unittest.TestCase):
    """测试 qa_pptx 编程接口及单测场景覆盖。"""

    def test_qa_single_pptx_with_path_and_str(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "deck.pptx")
            self.assertTrue(qa_single_pptx(p, verbose=False))
            self.assertTrue(qa_single_pptx(str(p), verbose=False))

    def test_qa_single_pptx_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            create_mock_pptx(base / "deck.pptx")
            self.assertTrue(qa_single_pptx("deck.pptx", verbose=False, base_dir=base))

    def test_qa_single_pptx_verbose_false(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "deck.pptx")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                res = qa_single_pptx(p, verbose=False)
            self.assertTrue(res)
            self.assertEqual(buf.getvalue(), "")

    def test_qa_single_pptx_nonexistent_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            non_exist = Path(td) / "missing.pptx"
            self.assertFalse(qa_single_pptx(non_exist, verbose=False))

    def test_qa_single_pptx_non_zip_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            bad_file = Path(td) / "corrupt.pptx"
            bad_file.write_text("not a valid zip", encoding="utf-8")
            self.assertFalse(qa_single_pptx(bad_file, verbose=False))

    def test_qa_single_pptx_expected_slides_check(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "deck.pptx", slides_count=3)
            self.assertTrue(qa_single_pptx(p, expected_slides=3, verbose=False))
            self.assertFalse(qa_single_pptx(p, expected_slides=5, verbose=False))

    def test_qa_single_pptx_expected_media_check(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "deck.pptx", has_media=True)
            self.assertTrue(qa_single_pptx(p, expected_media=1, verbose=False))
            self.assertFalse(qa_single_pptx(p, expected_media=0, verbose=False))

    def test_run_qa_pptx_file_target(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "deck.pptx")
            self.assertTrue(run_qa_pptx(p, verbose=False))
            self.assertTrue(run_qa_pptx(str(p), verbose=False))

    def test_run_qa_pptx_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            create_mock_pptx(base / "deck.pptx")
            self.assertTrue(run_qa_pptx("deck.pptx", verbose=False, base_dir=base))
            self.assertTrue(qa_pptx("deck.pptx", verbose=False, base_dir=base))

    def test_run_qa_pptx_non_pptx_file_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            txt_file = Path(td) / "note.txt"
            txt_file.touch()
            self.assertFalse(run_qa_pptx(txt_file, verbose=False))

    def test_run_qa_pptx_directory_target(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            create_mock_pptx(base / "a.pptx")
            create_mock_pptx(base / "b.pptx")
            self.assertTrue(run_qa_pptx(base, verbose=False))
            self.assertTrue(run_qa_pptx(str(base), verbose=False))

    def test_run_qa_pptx_empty_directory_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(run_qa_pptx(Path(td), verbose=False))

    def test_run_qa_pptx_nonexistent_returns_false(self):
        self.assertFalse(run_qa_pptx("/non_existent_pptx_dir_9999", verbose=False))

    def test_run_qa_pptx_spec_auto_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_file = base / "spec_lock.md"
            spec_file.write_text("- sizes: [11, 13, 16, 20, 24, 32, 44, 56, 96]\n", encoding="utf-8")
            p = create_mock_pptx(base / "deck.pptx")
            self.assertTrue(run_qa_pptx(p, verbose=False))

    def test_qa_pptx_alias(self):
        self.assertIs(qa_pptx, run_qa_pptx)

    def test_alias_run_qa_single_pptx(self):
        self.assertIs(run_qa_single_pptx, qa_single_pptx)


class TestMainCli(unittest.TestCase):
    """测试 qa_pptx CLI 命令入口。"""

    def test_cli_success_on_valid_pptx(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "valid.pptx")
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main([str(p)])
            self.assertEqual(code, 0)

    def test_cli_nonexistent_returns_1(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            code = main(["/path/not_exist_xyz.pptx"])
        self.assertEqual(code, 1)

    def test_cli_dir_without_pptx_returns_1(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("sys.stderr", new_callable=io.StringIO):
                code = main([td])
            self.assertEqual(code, 1)

    def test_cli_quiet_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "valid.pptx")
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                code = main([str(p), "--quiet"])
            self.assertEqual(code, 0)
            self.assertEqual(buf_out.getvalue(), "")
            self.assertEqual(buf_err.getvalue(), "")

            # -q 短参数测试
            buf_out2 = io.StringIO()
            with patch("sys.stdout", buf_out2), patch("sys.stderr", buf_err):
                code2 = main([str(p), "-q"])
            self.assertEqual(code2, 0)
            self.assertEqual(buf_out2.getvalue(), "")

    def test_cli_verbose_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = create_mock_pptx(Path(td) / "valid.pptx")
            buf_out = io.StringIO()
            with patch("sys.stdout", buf_out):
                code = main([str(p), "--verbose"])
            self.assertEqual(code, 0)
            self.assertIn("ALL CLEAR", buf_out.getvalue())

    def test_cli_quiet_error_silenced(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
            code = main(["/path/not_exist_xyz.pptx", "--quiet"])
        self.assertEqual(code, 1)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")


"""第 24 轮测试：check_role_consistency spec 优先硬对齐。"""


def _smap(sizes):
    """构造 slide_text_map：slide1..N，每页一个主句文本框。

    sizes: [(页名, 字号px, 文本)]；map 直接存 px（与 check_font_ramp 输出一致）。
    """
    m = {}
    for name, px, txt in sizes:
        m[name] = [(float(px), txt)]
    return m


class CheckRoleConsistencyTest(unittest.TestCase):
    PAGES = ["slide1", "slide2", "slide3", "slide4"]

    def test_spec_aligned_passes(self):
        m = _smap([(p, 84, "主句") for p in self.PAGES])
        ok, msg = check_role_consistency(m, 84)
        self.assertTrue(ok, msg)

    def test_spec_mismatch_flagged(self):
        # 第 21 轮真实漂移：P04=225, P06=72 vs spec 84
        m = _smap([("slide1", 84, "封面"), ("slide2", 84, "主句"),
                   ("slide3", 225, "廓形"), ("slide4", 72, "让人记住")])
        ok, msg = check_role_consistency(m, 84)
        self.assertFalse(ok)
        self.assertIn("slide3(225px", msg)
        self.assertIn("slide4(72px", msg)

    def test_spec_mismatch_when_dominant_is_off_spec(self):
        # 旧逻辑静默放过的 case：全页 225 vs spec 84
        m = _smap([(p, 225, "主句") for p in self.PAGES])
        ok, msg = check_role_consistency(m, 84)
        self.assertFalse(ok, msg)
        self.assertIn("84px", msg)

    def test_no_spec_internal_consistency(self):
        m = _smap([("slide1", 84, "a"), ("slide2", 84, "b"),
                   ("slide3", 84, "c"), ("slide4", 225, "d")])
        ok, msg = check_role_consistency(m, None)
        self.assertFalse(ok)
        self.assertIn("主流为 84px", msg)

    def test_no_spec_uniform_passes(self):
        m = _smap([(p, 225, "主句") for p in self.PAGES])
        ok, msg = check_role_consistency(m, None)
        self.assertTrue(ok, msg)

    def test_too_few_slides_skipped(self):
        m = _smap([("slide1", 84, "a"), ("slide2", 84, "b")])
        ok, _ = check_role_consistency(m, 84)
        self.assertTrue(ok)


class TestQAPptxSubdirAndSpecResolution(unittest.TestCase):
    """测试 qa_pptx 对子目录、规范文件及单文件自适应项目解析。"""

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

        self.pptx_file = self.output_dir / "deck.pptx"
        create_mock_pptx(self.pptx_file)

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
        with patch("scripts.qa_pptx._cpm_resolve_project_dir", None):
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

    def test_find_pptx_files_from_subfolder(self):
        found_render = find_pptx_files(self.render_dir)
        self.assertEqual(found_render, [self.pptx_file.resolve()])

        found_images = find_pptx_files(self.images_dir)
        self.assertEqual(found_images, [self.pptx_file.resolve()])

        found_notes = find_pptx_files(self.notes_dir)
        self.assertEqual(found_notes, [self.pptx_file.resolve()])

    def test_find_pptx_files_with_base_dir(self):
        # 相对路径 + base_dir
        found = find_pptx_files("output", base_dir=self.proj)
        self.assertEqual(found, [self.pptx_file.resolve()])
        found_dot = find_pptx_files(".", base_dir=self.render_dir)
        self.assertEqual(found_dot, [self.pptx_file.resolve()])

    def test_find_pptx_files_from_spec_file(self):
        found_spec = find_pptx_files(self.spec_file)
        self.assertEqual(found_spec, [self.pptx_file.resolve()])

    def test_find_pptx_files_from_spec_file_empty_proj(self):
        empty_proj = Path(self.td.name) / "empty_proj"
        empty_proj.mkdir(parents=True)
        empty_spec = empty_proj / "spec_lock.md"
        empty_spec.write_text("# spec\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            find_pptx_files(empty_spec)

    @patch("scripts.qa_pptx.qa_single_pptx", return_value=True)
    def test_run_qa_pptx_from_subfolder_and_spec_file(self, mock_single):
        self.assertTrue(run_qa_pptx(self.render_dir, verbose=False))
        self.assertTrue(run_qa_pptx(self.spec_file, verbose=False))
        self.assertEqual(mock_single.call_count, 2)

    @patch("scripts.qa_pptx.qa_single_pptx", return_value=True)
    def test_run_qa_pptx_with_base_dir(self, mock_single):
        self.assertTrue(run_qa_pptx(".", base_dir=self.render_dir, verbose=False))
        self.assertTrue(run_qa_pptx("spec_lock.md", base_dir=self.proj, verbose=False))
        self.assertEqual(mock_single.call_count, 2)

    @patch("scripts.qa_pptx.qa_single_pptx", return_value=True)
    def test_cli_from_subfolder_and_spec_file(self, mock_single):
        with patch("sys.stdout", new_callable=io.StringIO):
            code1 = main([str(self.render_dir)])
            self.assertEqual(code1, 0)
            code2 = main([str(self.spec_file)])
            self.assertEqual(code2, 0)
        self.assertEqual(mock_single.call_count, 2)

    @patch("scripts.qa_pptx.qa_single_pptx", return_value=True)
    def test_cli_with_base_dir(self, mock_single):
        with patch("sys.stdout", new_callable=io.StringIO):
            code1 = main(["."], base_dir=self.render_dir)
            self.assertEqual(code1, 0)
            code2 = main(["spec_lock.md"], base_dir=self.proj)
            self.assertEqual(code2, 0)
            code3 = main([".", "--spec", "spec_lock.md"], base_dir=self.proj)
            self.assertEqual(code3, 0)
        self.assertEqual(mock_single.call_count, 3)


if __name__ == "__main__":
    unittest.main()
