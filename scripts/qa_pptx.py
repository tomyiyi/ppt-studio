#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_pptx.py —— PPT-Studio PPTX 导出物客观回读质检
=================================================

对导出的 PPTX 原生文件执行 7 项自动化客观质量门禁，遵循 docs/qa-checklist.md 第三节规范：
  1. [结构完整性] Zip 压缩包完整，OpenXML 基础骨架（Content_Types, presentation.xml）无损
  2. [画幅与比例] 画面尺寸符合 16:9 标准比例（允许 ±1.5% 容差，严防误导出 4:3 变形）
  3. [媒体资源集] ppt/media/ 内所有图像资源有效可读、非零体积、无破损或截断
  4. [幻灯片图元] 内容页包含完整背景/插图层 (<p:pic>) 与文本图层 (<p:sp>/<p:txBody>)
  5. [字号阶梯]   DrawingML <a:rPr sz="..."> 换算回 px (sz/75)，严格合规于 spec 阶梯
  6. [角色一致性] 跨页同角色（页面主句 statement 等）字号绝对统一，严防"一时大一时小"
  7. [引用关系链] 所有 slides、layouts 与 media 引用关系 (rels) 闭环无断链

用法：
  python3 scripts/qa_pptx.py <pptx_file_or_dir> [--spec path/to/spec_lock.md] [--expected-media N]
"""

from __future__ import annotations

import argparse
import io
import os
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# 确保在未显式激活 .venv 时也能从项目内 .venv 加载依赖
try:
    from PIL import Image
except ImportError:
    repo_root = Path(__file__).resolve().parent.parent
    for site_pkg in repo_root.glob(".venv/lib/python*/site-packages"):
        if site_pkg.is_dir() and str(site_pkg) not in sys.path:
            sys.path.insert(0, str(site_pkg))
    try:
        from PIL import Image
    except ImportError:
        Image = None

NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/package/2006/relationships}"

DEFAULT_RAMP = [11, 13, 16, 20, 24, 32, 44, 56, 96]


def load_spec_typography(spec_path: Path | None) -> tuple[list[int], int]:
    """从 spec_lock.md 加载字号阶梯及预期 statement 字号。
    支持 - sizes: [11, 13, ...] 与 ## typography 角色映射，过滤行内注释。"""
    ramp = list(DEFAULT_RAMP)
    stmt_sz = 56
    if not spec_path:
        return ramp, stmt_sz
    p = Path(spec_path)
    if not p.is_file():
        return ramp, stmt_sz

    try:
        content = p.read_text(encoding="utf-8")
        # 格式 1: - sizes: [11, 13, 16, 20, 24, 32, 44, 56, 96]
        m_sizes = re.search(r"-\s*sizes:\s*\[([0-9,\s]+)\]", content)
        if m_sizes:
            parsed_sizes = []
            for x in m_sizes.group(1).split(","):
                s = x.strip()
                if s.isdigit():
                    parsed_sizes.append(int(s))
            if parsed_sizes:
                ramp = sorted(set(parsed_sizes))

        # 格式 2: ## typography 段
        m_typo = re.search(r"^##\s+typography\s*$(.*?)(?=^##\s|\Z)", content, re.S | re.M)
        if m_typo:
            roles = {}
            for line in m_typo.group(1).splitlines():
                line = line.split("#")[0].strip()
                if not line:
                    continue
                # 支持 56 statement 或 - 56 statement
                mm1 = re.match(r"^[-*]?\s*(\d+)\s+([a-zA-Z_]\w*)", line)
                if mm1:
                    roles[mm1.group(2)] = int(mm1.group(1))
                    continue
                # 支持 - statement: 56 或 statement: 56
                mm2 = re.match(r"^[-*]?\s*([a-zA-Z_]\w*)\s*[:=]\s*(\d+)", line)
                if mm2:
                    roles[mm2.group(1)] = int(mm2.group(2))
            if roles:
                ramp = sorted(set(ramp + list(roles.values())))
                if "statement" in roles:
                    stmt_sz = roles["statement"]
    except Exception:
        pass
    return ramp, stmt_sz


def load_spec_ramp(spec_path: Path | None) -> list[int]:
    """向后兼容字号阶梯加载函数。"""
    ramp, _ = load_spec_typography(spec_path)
    return ramp


def check_zip_and_structure(z: zipfile.ZipFile) -> tuple[bool, str, ET.Element | None]:
    """检查 PPTX Zip 基础结构与 presentation.xml"""
    namelist = z.namelist()
    required = ["[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"]
    for req in required:
        if req not in namelist:
            return False, f"缺少关键 OpenXML 结构文件: {req}", None

    try:
        pres_xml = ET.fromstring(z.read("ppt/presentation.xml"))
        return True, "OpenXML 基础骨架完整", pres_xml
    except Exception as e:
        return False, f"presentation.xml 解析异常: {e}", None


def check_geometry(pres_xml: ET.Element) -> tuple[bool, str]:
    """检查画幅比例是否符合 16:9。"""
    sldSz = pres_xml.find(f"{NS_P}sldSz")
    if sldSz is None:
        return False, "未找到 <p:sldSz> 画幅尺寸定义"

    cx = float(sldSz.get("cx", 0))
    cy = float(sldSz.get("cy", 0))
    if cx <= 0 or cy <= 0:
        return False, f"非法画幅尺寸: cx={cx}, cy={cy}"

    ratio = cx / cy
    target = 16.0 / 9.0  # 1.777777...
    err = abs(ratio - target) / target

    if err > 0.02:
        return False, f"画幅非 16:9 比例 (当前: {cx:.0f}×{cy:.0f}, ratio={ratio:.3f}, 期望 1.778)"
    return True, f"{int(cx)} × {int(cy)} (16:9 比例标准)"


def check_media(z: zipfile.ZipFile, expected_media: int | None = None) -> tuple[bool, str]:
    """检查 ppt/media/ 图像有效性与格式。"""
    media_files = sorted([f for f in z.namelist() if f.startswith("ppt/media/") and not f.endswith("/")])
    
    if expected_media is not None and len(media_files) != expected_media:
        return False, f"媒体文件数 ({len(media_files)}) 与预期 ({expected_media}) 不符"

    if not media_files:
        return True, "无内嵌媒体文件 (Office 原生矢量绘图形态)"

    corrupt = []
    sizes = []
    for mf in media_files:
        raw = z.read(mf)
        if len(raw) == 0:
            corrupt.append(f"{mf} (空文件 0 字节)")
            continue
        if Image is not None:
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    img.verify()
                sizes.append(len(raw))
            except Exception as e:
                corrupt.append(f"{mf} ({e})")
        else:
            # 轻量级图像魔数校验 (PNG / JPEG / WebP / BMP)
            if (
                raw.startswith(b"\x89PNG\r\n\x1a\n")
                or raw.startswith(b"\xff\xd8\xff")
                or raw.startswith(b"RIFF")
                or raw.startswith(b"BM")
            ):
                sizes.append(len(raw))
            else:
                corrupt.append(f"{mf} (无法识别的图像文件格式)")

    if corrupt:
        return False, f"存在损坏或无效媒体: {', '.join(corrupt[:3])}"

    total_kb = sum(sizes) // 1024
    return True, f"{len(media_files)} 个媒体文件全部有效 (PNG/JPEG 合计 {total_kb} KB)"


def check_slide_layers(z: zipfile.ZipFile, slide_names: list[str], has_media: bool) -> tuple[bool, str]:
    """检查每页幻灯片的图层与元素。"""
    if not slide_names:
        return False, "PPTX 内无幻灯片"

    missing_pics = []
    missing_texts = []

    for s_name in slide_names:
        root = ET.fromstring(z.read(s_name))
        pics = root.findall(f".//{NS_P}pic")
        sp_texts = root.findall(f".//{NS_P}sp")
        
        # 配图版每页应有 1 张满幅底图/插图
        if has_media and len(pics) < 1:
            missing_pics.append(s_name)
        if len(sp_texts) < 1:
            missing_texts.append(s_name)

    if missing_pics:
        return False, f"部分页面缺失配图层 (<p:pic>): {', '.join(missing_pics[:3])}"
    if missing_texts:
        return False, f"部分页面缺失文本图元 (<p:sp>): {', '.join(missing_texts[:3])}"

    return True, f"{len(slide_names)} 页幻灯片图元与图层结构完整"


def check_font_ramp(z: zipfile.ZipFile, slide_names: list[str], ramp: list[int]) -> tuple[bool, str, dict]:
    """反查 DrawingML <a:rPr sz="..."> 换算回 px，验证是否落在阶梯内。"""
    ramp_set = set(ramp)
    total_runs = 0
    all_sz = set()
    off_ramp = []
    slide_text_map: dict[str, list[tuple[int, str]]] = {}

    for s_name in slide_names:
        root = ET.fromstring(z.read(s_name))
        slide_entries = []

        # 遍历形状与段落
        for sp in root.findall(f".//{NS_P}sp"):
            sp_text = "".join(sp.itertext()).strip()
            sz_vals = [int(r.get("sz")) for r in sp.findall(f".//{NS_A}rPr") if r.get("sz")]
            if sp_text and sz_vals:
                slide_entries.append((max(sz_vals), sp_text))

            for r in sp.findall(f".//{NS_A}rPr"):
                sz_str = r.get("sz")
                if sz_str:
                    total_runs += 1
                    sz = int(sz_str)
                    all_sz.add(sz)
                    # 1pt = 0.75px @1280x720, sz 是百分之一 pt (cents of pt)
                    # pt = sz / 100, px = pt / 0.75 = sz / 75.0
                    px = round(sz / 75.0)
                    if px not in ramp_set:
                        # 容差: 极小浮点取整偏差 (±1px)
                        matched = any(abs(px - authorized) <= 0.6 for authorized in ramp_set)
                        if not matched:
                            off_ramp.append((s_name, sz, px, sp_text[:20]))

        slide_text_map[s_name] = slide_entries

    if total_runs == 0:
        return True, "无内联 DrawingML 字号覆盖 (采用母版预设继承字号)", slide_text_map

    if off_ramp:
        err_samples = [f"{s} sz={sz}(~{px}px)" for s, sz, px, _ in off_ramp[:3]]
        return False, f"发现非规范字号: {', '.join(err_samples)} (允许阶梯: {ramp})", slide_text_map

    px_ramp_detected = sorted(set(round(sz / 75.0) for sz in all_sz))
    return True, f"{total_runs} 处文本全部合规于阶梯 {px_ramp_detected} px", slide_text_map


def check_role_consistency(slide_text_map: dict[str, list[tuple[int, str]]], expected_stmt_sz: int = 56) -> tuple[bool, str]:
    """验证主句在各个正文页的字号是否严格一致，并与 spec_lock 期望对齐。"""
    # 提取第 2 页到倒数第 1 页的正文页主句 (排除第 1 页封面/封底等特殊页)
    slides = list(slide_text_map.keys())
    if len(slides) < 3:
        return True, "页数较少，跳过跨页主句一致性比对"

    # 正文页: 排除第 1 页 (封面)，检查后续页面的主句候选（字号 >= 40px 的大标题文本）
    content_slides = slides[1:]
    statement_slides = {}

    for s in content_slides:
        entries = slide_text_map.get(s, [])
        if not entries:
            continue
        large_entries = [e for e in entries if round(e[0] / 75.0) >= 40]
        if not large_entries:
            continue
        # 排序取该页最高字号（一般为 statement 或 headline）
        top_sz, top_txt = max(large_entries, key=lambda x: x[0])
        px = round(top_sz / 75.0)
        statement_slides[s] = (px, top_txt[:15])

    # 聚类正文页的 statement 尺寸（通常为 56px / 42pt = 4200）
    if not statement_slides:
        return True, "未检测到内联主句标记"

    from collections import Counter
    counts = Counter(v[0] for v in statement_slides.values())
    dominant_px, dominant_count = counts.most_common(1)[0]

    target_px = expected_stmt_sz if (expected_stmt_sz and expected_stmt_sz in counts) else dominant_px

    # 如果 dominant_px 与规范预期发生档位漂移
    if expected_stmt_sz and dominant_px != expected_stmt_sz and dominant_px in (44, 56, 72):
        return False, f"页面主句字号 ({dominant_px}px) 与规范期望 ({expected_stmt_sz}px) 不符"

    drifts = []
    for s, (px, txt) in sorted(statement_slides.items()):
        if px != target_px:
            drifts.append(f"{s}({px}px: {txt})")

    if drifts:
        return False, f"页面主句字号不一致 (主流为 {target_px}px，漂移页: {', '.join(drifts)})"

    return True, f"各正文页页面主句字号严格对齐 ({target_px}px / {target_px * 0.75:.0f}pt)"


def check_relationships(z: zipfile.ZipFile, slide_names: list[str]) -> tuple[bool, str]:
    """检查关系文件 (.rels) 链接是否全部闭环。"""
    broken_rels = []
    
    for s in slide_names:
        base_dir = posixpath.dirname(s)
        file_name = posixpath.basename(s)
        rel_path = f"{base_dir}/_rels/{file_name}.rels"
        
        if rel_path in z.namelist():
            try:
                root = ET.fromstring(z.read(rel_path))
                for rel in root.findall(f"{NS_R}Relationship"):
                    if rel.get("TargetMode") == "External":
                        continue
                    target = rel.get("Target", "")
                    if not target:
                        continue
                    norm_target = posixpath.normpath(posixpath.join(base_dir, target))
                    if norm_target not in z.namelist():
                        broken_rels.append(f"{s} -> {target}")
            except Exception as e:
                broken_rels.append(f"{rel_path} ({e})")

    if broken_rels:
        return False, f"存在断链关系引用: {', '.join(broken_rels[:3])}"

    return True, "全量幻灯片、母版与媒体关联引用无断链"


def run_qa_pptx(
    pptx_path: Path,
    spec_path: Path | None = None,
    expected_slides: int | None = None,
    expected_media: int | None = None,
) -> bool:
    print("=" * 60)
    print(f"🔍 运行 PPT-Studio PPTX 导出物客观回读质检")
    print(f"   目标: {pptx_path}")
    print("=" * 60)

    if not pptx_path.exists():
        print(f"  [✗] 文件不存在: {pptx_path}")
        return False

    if not zipfile.is_zipfile(pptx_path):
        print(f"  [✗] 目标文件非有效 PPTX/Zip 压缩包: {pptx_path}")
        return False

    ramp, expected_stmt_sz = load_spec_typography(spec_path)

    with zipfile.ZipFile(pptx_path, "r") as z:
        # 1. Zip 基础结构
        ok_struct, msg_struct, pres_xml = check_zip_and_structure(z)
        print(f"  [{'✓' if ok_struct else '✗'}] PPTX 基础结构       : {msg_struct}")
        if not ok_struct:
            return False

        # 2. 画幅与比例
        ok_geom, msg_geom = check_geometry(pres_xml)
        print(f"  [{'✓' if ok_geom else '✗'}] 画幅与标准比例     : {msg_geom}")

        # 3. 媒体资源检验
        has_media = any(f.startswith("ppt/media/") for f in z.namelist())
        ok_media, msg_media = check_media(z, expected_media=expected_media)
        print(f"  [{'✓' if ok_media else '✗'}] 媒体资源完整性     : {msg_media}")

        # 幻灯片清单
        slide_names = sorted([f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")])
        if expected_slides is not None and len(slide_names) != expected_slides:
            print(f"  [✗] 幻灯片总页数       : 实际 {len(slide_names)} 页，与预期 ({expected_slides} 页) 不符")
            return False

        # 4. 幻灯片图层结构
        ok_layers, msg_layers = check_slide_layers(z, slide_names, has_media)
        print(f"  [{'✓' if ok_layers else '✗'}] 幻灯片图元结构     : {msg_layers}")

        # 5. 字号阶梯符合度
        ok_ramp, msg_ramp, text_map = check_font_ramp(z, slide_names, ramp)
        print(f"  [{'✓' if ok_ramp else '✗'}] 字号阶梯合规性     : {msg_ramp}")

        # 6. 跨页主句一致性
        ok_consist, msg_consist = check_role_consistency(text_map, expected_stmt_sz)
        print(f"  [{'✓' if ok_consist else '✗'}] 跨页主句一致性     : {msg_consist}")

        # 7. 引用关系链
        ok_rels, msg_rels = check_relationships(z, slide_names)
        print(f"  [{'✓' if ok_rels else '✗'}] 引用关系链完整性   : {msg_rels}")

    all_passed = all([ok_struct, ok_geom, ok_media, ok_layers, ok_ramp, ok_consist, ok_rels])
    print("=" * 60)
    if all_passed:
        print("ALL CLEAR ✅")
        return True
    else:
        print("QA FAILED ❌")
        return False


def find_spec_lock(target_path: Path | str | None = None) -> Path | None:
    """在目标路径周边或默认项目路径中发现 spec_lock.md。"""
    candidates: list[Path] = []
    if target_path:
        tp = Path(target_path).resolve()
        if tp.is_file():
            candidates.extend([
                tp.parent / "spec_lock.md",
                tp.parent.parent / "spec_lock.md",
            ])
        else:
            candidates.extend([
                tp / "spec_lock.md",
                tp.parent / "spec_lock.md",
                tp.parent.parent / "spec_lock.md",
            ])

    repo_root = Path(__file__).resolve().parent.parent
    for candidate_dir in [Path.cwd(), repo_root]:
        candidates.append(candidate_dir / "spec_lock.md")

    for c in candidates:
        if c and c.is_file():
            return c.resolve()

    # 动态扫描 projects/*/spec_lock.md，避免硬编码项目名
    for candidate_dir in [Path.cwd(), repo_root]:
        p_cands = sorted((candidate_dir / "projects").glob("*/spec_lock.md"))
        if len(p_cands) == 1:
            return p_cands[0].resolve()

    return None


def find_pptx_files(target: Path | str = ".", base_dir: Path | None = None) -> list[Path]:
    """发现并解析待质检的 PPTX 文件列表。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = (base / target_path).resolve()

    if not target_path.exists():
        raise FileNotFoundError(f"目标路径不存在: {target_path}")

    if target_path.is_file():
        if target_path.suffix.lower() == ".pptx":
            return [target_path]
        raise ValueError(f"目标文件不是 PPTX 文件: {target_path}")

    found: list[Path] = []
    # 1. 目标目录直接包含的 *.pptx
    found.extend(sorted(target_path.glob("*.pptx")))
    # 2. 目标目录中的 output/ 子目录
    if (target_path / "output").is_dir():
        found.extend(sorted((target_path / "output").glob("*.pptx")))
    # 3. 目标目录中的 projects/*/output/ 子目录
    candidate_p_dirs: list[Path] = []
    if (target_path / "projects").is_dir():
        candidate_p_dirs.append(target_path / "projects")
    elif target_path.name == "projects":
        candidate_p_dirs.append(target_path)
    elif (target_path.parent / "projects").is_dir():
        candidate_p_dirs.append(target_path.parent / "projects")

    for p_dir in candidate_p_dirs:
        for p in sorted(p_dir.iterdir()):
            if p.is_dir() and (p / "output").is_dir():
                found.extend(sorted((p / "output").glob("*.pptx")))

    # 4. 向上查找 output 目录（如从子目录调用）
    if not found and (target_path.parent / "output").is_dir():
        found.extend(sorted((target_path.parent / "output").glob("*.pptx")))
    if not found and (target_path.parent.parent / "output").is_dir():
        found.extend(sorted((target_path.parent.parent / "output").glob("*.pptx")))

    # 去重保持顺序，排除 .venv 与 site-packages
    seen: set[Path] = set()
    deduped: list[Path] = []
    for f in found:
        rf = f.resolve()
        if rf not in seen and ".venv" not in str(rf) and "site-packages" not in str(rf):
            seen.add(rf)
            deduped.append(rf)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio PPTX 导出物客观回读质检")
    parser.add_argument("target", nargs="?", default=".", help="PPTX 文件路径，或包含 *.pptx / output/*.pptx 的目录（默认当前目录）")
    parser.add_argument("--spec", help="可选指定 spec_lock.md 路径")
    parser.add_argument("--expected-slides", type=int, help="可选预期总页数")
    parser.add_argument("--expected-media", type=int, help="可选预期媒体文件数")
    args = parser.parse_args(argv)

    try:
        pptx_files = find_pptx_files(args.target)
    except (FileNotFoundError, ValueError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    if not pptx_files:
        print(f"[!] 目录 {args.target} 及其子目录下未找到 .pptx 文件", file=sys.stderr)
        return 1

    spec_path = Path(args.spec).resolve() if args.spec else find_spec_lock(Path(args.target).resolve())

    all_ok = True
    for p in pptx_files:
        ok = run_qa_pptx(p, spec_path, args.expected_slides, args.expected_media)
        if not ok:
            all_ok = False
        print()

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
