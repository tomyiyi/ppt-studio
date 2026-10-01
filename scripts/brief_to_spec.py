"""brief_to_spec.py -- research/brief -> spec_lock.md 初稿（管线第 3.5 段）。

背景（第 22 轮）：research_to_spec（1+2 段：子查询→搜索→打分）与
brief_writer（第 3 段：Agnes 撰写简报）之间已打通，但"简报 → spec_lock.md
执行锁"仍是人工环节。本脚本补上这段：Agnes 按铁律把简报转成 spec 初稿，
程序做结构硬校验（绝不只看 Agnes 说写好了）。

注意：输出是**初稿**，必须经人工审定才能成为真正的执行锁；
本脚本只保证结构合法，不保证设计决策正确。

用法：
python3 scripts/brief_to_spec.py brief.md -o spec_draft.md [--dry-run]
python3 scripts/brief_to_spec.py brief.md --dry-run # 只看 prompt，不调 Agnes
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.brief_writer import call_agnes, DEFAULT_TEXT_MODEL # noqa: E402
from scripts.check_page_map import parse_page_map # noqa: E402

# 字阶锁死：初稿不许 Agnes 自创字号（与 fw2026 v4 锁一致）
CANON_RAMP = [20, 26, 36, 42, 72, 84, 180, 225]
CANON_STATEMENT = 84
RHYTHMS = {"anchor", "dense", "breathing"}


def build_spec_prompt(topic: str, brief_md: str) -> str:
    """铁律 prompt：只输出 spec_lock.md 初稿，无解释无前后缀。"""
    lines_out = [
        "你是 PPT 执行锁（spec_lock.md）起草员。根据以下简报，为主题「%s」起草一份" % topic,
        "spec_lock.md **初稿**。只输出 markdown 本身，不要任何解释、前言、后记或代码围栏。",
        "",
        "【铁律】",
        "1. 骨架必须包含 ## canvas / ## typography / ## page_map / ## details 四节，顺序固定；",
        "2. `## canvas`：`- viewBox: 0 0 1920 1080` 与 `- margin: 144px` 逐字保留；",
        "3. `## typography`：`- sizes: [20, 26, 36, 42, 72, 84, 180, 225]` 与",
        "   `- statement: 84` 逐字保留，不许增删改任何数字；字体族可按主题微调；",
        "4. `## page_map`：从 P01 开始连续编号（P01, P02, …），每行格式严格为",
        "   `- P01: role=Cover, rhythm=anchor`；P01 必须是 role=Cover, rhythm=anchor；",
        "   最后一页 role=Closing, rhythm=anchor；rhythm 只能是 anchor/dense/breathing；",
        "   页数 = 简报章节数 + 2（封面+结尾），控制在 6–12 页；",
        "   每页 role 必须贴合该页实际内容（从简报章节提炼），不许写\"待定/略\"；",
        "5. `## details`：列出本主题必需的排版铁律（图注格式、禁用项等），从简报来源要求提炼；",
        "6. 简报中无来源支撑的内容不许写进 spec；",
        "7. 全文不许出现\"TODO/待定/xxx\"占位符。",
        "",
        "【简报】",
        brief_md,
    ]
    return "\n".join(lines_out).strip() + "\n"


def _strip_fences(md: str) -> str:
    """剥离 Agnes 常加的整体代码围栏（```markdown ... ```）。

    实跑发现：prompt 明令禁止围栏，模型仍可能整体包裹输出。
    纵深防御：程序侧自动剥离后再校验，并打印提示（第 22 轮）。
    """
    s = md.strip()
    if not s.startswith("```"):
        return md
    lines = s.splitlines()
    lines = lines[1:]  # 去掉首行 ```xxx
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def validate_spec_draft(md: str) -> dict:
    """结构硬校验。返回 {ok, problems[]}。"""
    problems: list[str] = []
    # 1. 四节齐全
    sections = re.findall(r"^##\s+(\S+)", md, re.M)
    for need in ("canvas", "typography", "page_map", "details"):
        if need not in sections:
            problems.append("缺少 ## %s 节" % need)
    # 2. canvas 铁律行逐字保留
    if "- viewBox: 0 0 1920 1080" not in md:
        problems.append("canvas 缺少逐字行：- viewBox: 0 0 1920 1080")
    if "- margin: 144px" not in md:
        problems.append("canvas 缺少逐字行：- margin: 144px")
    # 3. 字阶/主句逐字保留
    if "- sizes: [%s]" % ", ".join(map(str, CANON_RAMP)) not in md:
        problems.append("typography 字阶被改动（必须逐字保留）")
    if "- statement: %d" % CANON_STATEMENT not in md:
        problems.append("typography statement 被改动（必须逐字保留）")
    # 4. page_map：复用 check_page_map.parse_page_map（写临时文件）
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(md)
        tmp = Path(f.name)
    try:
        pm = parse_page_map(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    if not pm:
        problems.append("page_map 解析为空（格式须为 `- P01: role=X, rhythm=Y`）")
    else:
        keys = sorted(pm)
        expect = ["P%02d" % i for i in range(1, len(keys) + 1)]
        if keys != expect:
            problems.append("page_map 页码不连续：%s（期望 %s）" % (keys, expect))
        if pm.get("P01", {}).get("role") != "Cover":
            problems.append("P01 role 必须为 Cover")
        last = keys[-1]
        if pm.get(last, {}).get("role") != "Closing":
            problems.append("%s role 必须为 Closing" % last)
        for k, v in pm.items():
            if not v.get("role"):
                problems.append("%s 缺少 role" % k)
            if v.get("rhythm") not in RHYTHMS:
                problems.append("%s rhythm 非法：%s" % (k, v.get("rhythm")))
        if not (6 <= len(keys) <= 12):
            problems.append("page_map 页数 %d 超出 6–12 范围" % len(keys))
    # 5. 占位符
    for bad in ("TODO", "待定", "xxx", "XXX", "TBD"):
        if bad in md:
            problems.append("含占位符：%s" % bad)
    # 6. 代码围栏（要求纯 markdown）
    if "```" in md:
        problems.append("含代码围栏（要求直接输出 markdown）")
    return {"ok": not problems, "problems": problems,
            "pages": len(pm) if pm else 0}


def draft_spec(brief_path: str, output: str | None = None,
               model: str = DEFAULT_TEXT_MODEL,
               dry_run: bool = False) -> dict:
    """brief.md → spec 初稿。返回 {markdown, validation, ...}。"""
    brief_md = Path(brief_path).read_text(encoding="utf-8")
    topic = "未命名主题"
    m = re.search(r"^#\s+(.+)$", brief_md, re.M)
    if m:
        topic = m.group(1).strip()
    prompt = build_spec_prompt(topic, brief_md)
    if dry_run:
        print(prompt)
        return {"dry_run": True, "prompt_chars": len(prompt)}
    md = call_agnes(prompt, model=model)
    stripped = _strip_fences(md)
    if stripped != md:
        print("[i] 已自动剥离模型输出的代码围栏", file=sys.stderr)
        md = stripped
    check = validate_spec_draft(md)
    if output:
        Path(output).write_text(md, encoding="utf-8")
        print("[ok] spec 初稿 → %s（%d 页，结构校验 %s）"
              % (output, check["pages"], "通过" if check["ok"] else "失败"))
    if not check["ok"]:
        print("[warn] 初稿结构校验发现 %d 个问题：" % len(check["problems"]),
              file=sys.stderr)
        for p in check["problems"]:
            print("  - %s" % p, file=sys.stderr)
    return {"topic": topic, "model": model, "markdown": md,
            "validation": check}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="简报 → spec_lock.md 初稿（Agnes 起草 + 结构硬校验）")
    ap.add_argument("brief_md", help="brief_writer 产出的简报 markdown")
    ap.add_argument("-o", "--output", help="输出 spec 初稿路径")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="只打印 prompt，不调 Agnes")
    a = ap.parse_args(argv)
    result = draft_spec(a.brief_md, output=a.output, model=a.model,
                        dry_run=a.dry_run)
    if not a.dry_run and not result["validation"]["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
