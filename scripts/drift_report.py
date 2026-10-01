"""drift_report.py -- spec 漂移可视化对比报告（供用户做设计决策）。

背景（第 21 轮）：第 20 轮证伪了"字号阶梯漂移"（人工制品），
唯一真实漂移是主句一致性（P04/P06/P07）。本脚本把"实际 vs spec 期望"
做成自包含 HTML 报告，逐页可视化字号对比，作为用户决策材料
（回齐 spec / 更新 spec / 保持现状三选一）。

数据口径与 qa_layout.check_statement_consistency 完全一致：
- 排除封面（01* / *cover*）；
- 跳过 data-decorative="true" 装饰文字；
- 正文页主句 = 该页 ≥40px 非装饰文本中的最大字号；
- 预期字号 = spec_lock 的 statement 值。

用法：
  python3 scripts/drift_report.py projects/fw2026-trends
  python3 scripts/drift_report.py projects/fw2026-trends -o /tmp/drift.html --spec path/to/spec_lock.md
  python3 scripts/drift_report.py projects/fw2026-trends --format md   # 决策简报 Markdown（粘贴给用户做决策）
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.spec_resolve import find_spec, resolve_spec  # noqa: E402
from scripts.check_page_map import find_svg_dir  # noqa: E402
from scripts import qa_layout as _ql  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"
MIN_STATEMENT_PX = 40


def _is_cover(stem: str) -> bool:
    return stem.startswith("01") or "cover" in stem.lower()


def page_statement(root: ET.Element) -> tuple[int, str] | None:
    """返回 (字号px, 文本)，无主句页返回 None。口径同 qa_layout。"""
    sizes: list[tuple[int, str]] = []
    for t, anc in _ql._iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        if t.get("data-decorative") == "true":
            continue
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        s = int(round(_ql.inherited_font_size(t, anc)))
        sizes.append((s, txt))
    large = [(s, txt) for s, txt in sizes if s >= MIN_STATEMENT_PX]
    if not large:
        return None
    top_sz = max(s for s, _ in large)
    top_txt = next(txt for s, txt in large if s == top_sz)
    return top_sz, top_txt


def page_sizes(root: ET.Element) -> set[int]:
    """该页所有非装饰文本字号集合（用于字阶覆盖面展示）。"""
    out: set[int] = set()
    for t, anc in _ql._iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        if t.get("data-decorative") == "true":
            continue
        txt = "".join(t.itertext()).strip()
        if not txt:
            continue
        out.add(int(round(_ql.inherited_font_size(t, anc))))
    return out


def load_statement_size(spec_path: Path) -> int | None:
    """从 spec_lock 读 statement: Npx。"""
    m = re.search(r"^-\s*statement:\s*(\d+)", spec_path.read_text(encoding="utf-8"),
                  re.MULTILINE)
    return int(m.group(1)) if m else None


def build_report(project_dir: Path, spec_path: Path | None = None) -> dict:
    """返回报告数据结构（JSON 可序列化）。"""
    spec = Path(spec_path).resolve() if spec_path else (
        resolve_spec(project_dir) or find_spec(project_dir)
    )
    if spec is None:
        raise FileNotFoundError(f"找不到 spec_lock: {project_dir}")
    expected = load_statement_size(spec)
    if expected is None:
        raise ValueError(f"spec 缺少 statement 字段: {spec}")
    try:
        ramp = _ql.load_ramp(str(spec))
    except Exception:
        ramp = []

    svg_dir = find_svg_dir(project_dir)
    if svg_dir is None:
        raise FileNotFoundError(f"找不到 SVG 目录: {project_dir}")

    pages: list[dict] = []
    all_sizes: set[int] = set()
    for svg in sorted(svg_dir.glob("*.svg")):
        stem = svg.stem
        root = ET.parse(svg).getroot()
        sizes = page_sizes(root)
        all_sizes |= sizes
        entry: dict = {
            "page": stem,
            "cover": _is_cover(stem),
            "statement_text": None,
            "statement_size": None,
            "sizes": sorted(sizes),
        }
        if not _is_cover(stem):
            st = page_statement(root)
            if st:
                sz, txt = st
                entry["statement_text"] = txt
                entry["statement_size"] = sz
                entry["drift"] = (sz != expected)
                entry["delta"] = sz - expected
        pages.append(entry)

    ramp_set = set(ramp)
    off_ramp = sorted(s for s in all_sizes if s not in ramp_set)
    drift_pages = [p for p in pages if p.get("drift")]
    return {
        "project": project_dir.name,
        "spec_file": spec.name,
        "spec_path": str(spec),
        "expected_statement": expected,
        "ramp": sorted(ramp_set),
        "off_ramp_sizes": off_ramp,
        "pages": pages,
        "drift_pages": [p["page"] for p in drift_pages],
        "n_drift": len(drift_pages),
    }


def render_html(rep: dict) -> str:
    """自包含 HTML：逐页字号条形对比。"""
    exp = rep["expected_statement"]
    max_px = max([exp] + [p["statement_size"] or 0 for p in rep["pages"] if not p["cover"]] + [1])

    def bar(px: int | None, cls: str) -> str:
        if px is None:
            return '<span class="na">—</span>'
        w = max(2, int(px / max_px * 220))
        return f'<span class="bar {cls}" style="width:{w}px"></span><b>{px}px</b>'

    cards = []
    for p in rep["pages"]:
        if p["cover"]:
            cards.append(
                f'<div class="card"><h3>{html.escape(p["page"])} <span class="tag">封面（不参与主句比对）</span></h3>'
                f'<div class="sizes">本页字号：{", ".join(map(str, p["sizes"])) or "—"}</div></div>'
            )
            continue
        st = p["statement_text"]
        if st is None:
            cards.append(
                f'<div class="card"><h3>{html.escape(p["page"])}</h3>'
                f'<div class="warn">未检测到 ≥40px 主句</div></div>'
            )
            continue
        badge = '<span class="badge drift">DRIFT</span>' if p["drift"] else '<span class="badge ok">OK</span>'
        delta = f'（{p["delta"]:+d}px）' if p["drift"] else ""
        cards.append(
            f'<div class="card"><h3>{html.escape(p["page"])} {badge}</h3>'
            f'<div class="stmt">「{html.escape(st[:60])}」</div>'
            f'<div class="row"><span class="lbl">实际</span>{bar(p["statement_size"], "actual" + (" d" if p["drift"] else ""))}</div>'
            f'<div class="row"><span class="lbl">spec 期望</span>{bar(exp, "expected")}</div>'
            f'<div class="delta">{delta}</div>'
            f'<div class="sizes">本页字号：{", ".join(map(str, p["sizes"]))}</div></div>'
        )

    ramp_html = ", ".join(map(str, rep["ramp"])) or "—"
    off = ", ".join(map(str, rep["off_ramp_sizes"]))
    off_html = f'<div class="warn">⚠️ 脱离字阶的字号：{html.escape(off)}</div>' if off else \
        '<div class="okline">✓ 全 deck 字号均合规于字阶</div>'
    verdict = (f'<div class="verdict bad">发现 {rep["n_drift"]} 页主句漂移：{", ".join(rep["drift_pages"])}——待设计决策</div>'
               if rep["n_drift"] else '<div class="verdict good">主句字号全页对齐，无漂移</div>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Spec 漂移对比报告 — {html.escape(rep["project"])}</title>
<style>
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#222;background:#fafafa}}
h1{{font-size:22px}} .meta{{color:#666;font-size:13px;margin-bottom:16px}}
.verdict{{padding:12px 16px;border-radius:8px;font-weight:700;margin:16px 0}}
.verdict.bad{{background:#fdecea;color:#a33}} .verdict.good{{background:#e6f4ea;color:#1a7f37}}
.card{{background:#fff;border:1px solid #e5e5e5;border-radius:10px;padding:14px 18px;margin:12px 0}}
.card h3{{margin:0 0 8px;font-size:16px}} .stmt{{font-size:15px;margin:6px 0;color:#111}}
.row{{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:13px}}
.lbl{{width:70px;color:#666}} .bar{{display:inline-block;height:14px;border-radius:4px;background:#9ec1ff}}
.bar.expected{{background:#c8c8c8}} .bar.d{{background:#ff8a8a}} .na{{color:#999}}
.badge{{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff}}
.badge.ok{{background:#1a7f37}} .badge.drift{{background:#cf222e}}
.tag{{font-size:11px;color:#666;font-weight:400}} .sizes{{font-size:12px;color:#888;margin-top:6px}}
.delta{{font-size:13px;color:#cf222e;font-weight:700}} .warn{{color:#a33;font-size:13px}} .okline{{color:#1a7f37;font-size:13px}}
.ramp{{font-size:13px;color:#444;margin:8px 0}}
</style></head><body>
<h1>Spec 漂移对比报告 — {html.escape(rep["project"])}</h1>
<div class="meta">spec 文件：{html.escape(rep["spec_file"])}（{html.escape(rep["spec_path"])}）<br>
口径：正文页主句 = 该页 ≥40px 非装饰文本最大字号；封面不参与；装饰水印（data-decorative）排除</div>
{verdict}
<div class="ramp">spec 字阶：[{ramp_html}]</div>
{off_html}
{"".join(cards)}
</body></html>"""


def render_markdown(rep: dict) -> str:
    """决策简报 Markdown（第 28 轮）：可直接粘贴给用户做决策的文本版报告。

    与 render_html 同源（build_report），但面向"决策"而非"浏览"：
    每页漂移给出 A（回齐 spec）/B（更新 spec）两个显式选项，并标注
    实际字号是否在 spec 字阶内——在阶内 = 纯 statement 档位选择问题，
    不在阶内 = 字号本身失控，建议先查来源再决策。
    """
    ramp_set = set(rep["ramp"])
    out = [f"# Spec 漂移决策简报 — {rep['project']}", "",
           f"- spec 文件：{rep['spec_file']}",
           f"- spec statement 字号：{rep['expected_statement']}px",
           f"- spec 字阶：[{', '.join(map(str, rep['ramp']))}]"]
    drifts = [p for p in rep["pages"] if p.get("drift")]
    oks = [p for p in rep["pages"]
           if not p.get("cover") and not p.get("drift") and p.get("statement_size")]
    if drifts:
        out.append(f"- 结论：{rep['n_drift']} 页主句漂移"
                   f"（{', '.join(rep['drift_pages'])}），需逐页决策。")
    else:
        out.append("- 结论：无主句漂移，无需决策。")
    out.append("")

    if drifts:
        out.append("## 需决策")
        out.append("")
        for p in drifts:
            sz, exp, delta = p["statement_size"], rep["expected_statement"], p["delta"]
            ramp_note = ("在 spec 字阶内（纯 statement 档位选择问题）"
                         if sz in ramp_set else
                         "⚠️ 不在 spec 字阶内（字号本身失控，建议先查来源再决策）")
            out.append(f"### {p['page']} —— 「{p['statement_text']}」")
            out.append(f"- 实际 {sz}px vs 期望 {exp}px（{delta:+d}px）；{ramp_note}。")
            out.append(f"- 选项 A（回齐 spec）：把本页主句字号改回 {exp}px"
                       "（改 SVG → 重新导出 pptx → 回读验证）。")
            out.append(f"- 选项 B（更新 spec）：接受 {sz}px 为本页设计，"
                       f"在 {rep['spec_file']} 中为本页备注例外，或调整 statement 定义。")
            out.append("")

    if oks:
        out.append("## 无需决策（主句合规）")
        out.append("")
        out.append("、".join(f"{p['page']}（{p['statement_size']}px）" for p in oks) + "。")
        out.append("")

    if rep["off_ramp_sizes"]:
        out.append("## ⚠️ 脱离字阶的字号")
        out.append("")
        out.append("、".join(map(str, rep["off_ramp_sizes"]))
                   + "px 未在 spec 字阶中，建议先查来源再决策。")
        out.append("")
    else:
        out.append("脱离字阶的字号：无。")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 spec 漂移对比报告（HTML 可视化 / Markdown 决策简报）")
    ap.add_argument("project_dir", nargs="?", default=".",
                    help="项目目录（缺省当前目录）")
    ap.add_argument("--spec", help="显式指定 spec_lock 文件")
    ap.add_argument("-o", "--output", help="输出路径（缺省 <项目>/output/drift-report.<html|md>，随 --format）")
    ap.add_argument("--format", choices=["html", "md"], default="html",
                    help="html=可视化对比报告（默认），md=决策简报 Markdown（可直接粘贴给用户做决策）")
    a = ap.parse_args(argv)

    proj = Path(a.project_dir).resolve()
    try:
        rep = build_report(proj, Path(a.spec) if a.spec else None)
    except (FileNotFoundError, ValueError) as e:
        print(f"[fail] {e}", file=sys.stderr)
        return 1
    default_name = "drift-report.html" if a.format == "html" else "drift-report.md"
    out = Path(a.output).resolve() if a.output else proj / "output" / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    body = render_html(rep) if a.format == "html" else render_markdown(rep)
    out.write_text(body, encoding="utf-8")
    print(f"[ok] 漂移报告已生成: {out}")
    print(f"     主句漂移 {rep['n_drift']} 页: {', '.join(rep['drift_pages']) or '无'}；"
          f"脱离字阶字号: {', '.join(map(str, rep['off_ramp_sizes'])) or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
