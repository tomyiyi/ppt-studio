#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_index.py — 扫描本阶段报告目录，生成 INDEX.html（手机入口）。

用法：python3 spikes/RUN-20261015/make_index.py [额外镜像目录]
写两处：仓库 spikes/RUN-20261015/reports/INDEX.html 与（若给出）镜像目录/INDEX.html。
镜像目录建议给 iCloud 上的 ~/Desktop/00-接力报告/RUN-20261015，手机上"文件"App 直接能看。
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"

STAGE_GOAL = {
    "S1": "现场自证 + 断点台账 + 基线绿灯",
    "S2": "写作 skill：主题→成文法规与自检",
    "S3": "单入口编排 topic_to_deck.py",
    "S4": "文章入叙事时 image_intent 对账",
    "S5": "纯文字全链 E2E 留档",
    "S6": "三级配图路由 agnes / asset / vector",
    "S7": "cairosvg 无浏览器栅格化旁路",
    "S8": "真实 Agnes 出图（封顶 12 张）并客观验收",
    "S9": "海报提质：新增版式 key + poster_gate 自检",
    "S10": "8089 平行实例自证 + 文案端点",
    "S11": "deck 页 ↔ 海报 双向出口",
    "S12": "知识回写 3T 知识库",
    "S13": "收口报告 + 9 条未闭环风险实测",
    "S14": "海报文字可读性：墨色随底图明度自适应",
}

CSS = """
:root{--bg:#0f1115;--card:#171b22;--ink:#e8ebf0;--dim:#9aa4b2;--line:#282f3a;--ok:#3ddc84;--warn:#ffb454}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 -apple-system,"PingFang SC",sans-serif}
main{max-width:760px;margin:0 auto;padding:22px 16px 70px}h1{font-size:23px;margin:6px 0 2px}
.meta{color:var(--dim);font-size:15px}a{color:#7cc4ff;text-decoration:none}a:active{opacity:.7}
.row{display:flex;gap:12px;align-items:flex-start;background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:13px 15px;margin:10px 0}
.s{font:600 13px/1 ui-monospace,Menlo,monospace;color:var(--dim);padding-top:4px;min-width:34px}
.done .s{color:var(--ok)}.todo .s{color:var(--warn)}
.t{font-weight:600}.d{color:var(--dim);font-size:15px;margin-top:3px}
"""


def title_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else path.stem


def stage_key(name: str) -> str | None:
    m = re.match(r"S0*(\d+)\b", name)
    return f"S{m.group(1)}" if m else None


def main() -> None:
    extra = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    files = {}
    for p in sorted(REPORTS.glob("S*.html")):
        key = stage_key(p.name)
        if key:
            files.setdefault(key, p)

    rows = []
    for stage in [f"S{i}" for i in range(1, 15)]:
        goal = STAGE_GOAL.get(stage, "")
        if stage in files:
            f = files[stage]
            rows.append(
                f'<div class="row done"><div class="s">{stage}</div><div>'
                f'<a class="t" href="{html.escape(f.name)}">{html.escape(goal)}</a>'
                f'<div class="d">{html.escape(title_of(f))}</div></div></div>'
            )
        else:
            rows.append(
                f'<div class="row todo"><div class="s">{stage}</div><div>'
                f'<span class="t">{html.escape(goal)}</span>'
                f'<div class="d">未开始</div></div></div>'
            )

    done = sum(1 for s in [f"S{i}" for i in range(1, 15)] if s in files)
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RUN-20261015 接力报告</title><style>{CSS}</style></head>
<body><main>
<h1>RUN-20261015 · PPT Studio × AGNES Studio</h1>
<p class="meta">阶段 {done} / 14 已完成 ｜ 更新于 {datetime.now().strftime("%Y-%m-%d %H:%M")} (+0800)<br>
写作（主题→成文→deck）与设计与生图（配图三级路由 + 海报提质）。每阶段一份报告，含实际命令与实际输出。</p>
{chr(10).join(rows)}
<p class="meta">绿=已有报告，黄=未开始。计划文件：<code>~/.qoder-cn/plans/wise-oasis-wolf.md</code>；
台账：<code>ppt-studio/spikes/RUN-20261015/LEDGER.md</code></p>
</main></body></html>
"""
    (REPORTS / "INDEX.html").write_text(doc, encoding="utf-8")
    print(f"-> {REPORTS / 'INDEX.html'}  (阶段 {done}/14)")
    if extra:
        extra.mkdir(parents=True, exist_ok=True)
        (extra / "INDEX.html").write_text(doc, encoding="utf-8")
        print(f"-> {extra / 'INDEX.html'}")


if __name__ == "__main__":
    main()
