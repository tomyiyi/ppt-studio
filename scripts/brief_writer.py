#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brief_writer.py -- 三段式研究第 3 段：Agnes 撰写带 citation 的简报
==================================================================
输入：research_to_spec.py 第 1+2 段产出的 JSON（含 sources，每条有 url/title/snippet/trust/grade）
输出：markdown 简报，每条断言后跟 [n] 引用，文末附编号来源清单。

铁律（prompt + 后验双保险）：
  1. 只写有来源支撑的内容，无来源支撑的不写；
  2. 引用格式统一为 [n]，n 对应文末来源清单编号；
  3. A/B 级来源优先引用，D 级来源不引用。

用法：
    python3 scripts/brief_writer.py brief.json -o report.md
    python3 scripts/brief_writer.py brief.json --dry-run   # 只打印 prompt，不调 API

Agnes 走 New API /v1/chat/completions：
  环境变量 AGNES_CHAT_BASE_URL / AGNES_CHAT_API_KEY 优先，
  兜底 ~/.new-api/local_key.json，默认 http://127.0.0.1:13000/v1。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from gateway_config import resolve_gateway
except ImportError:
    resolve_gateway = None  # type: ignore

DEFAULT_TEXT_MODEL = "agnes-3.0-flash"
CITABLE_GRADES = ("A", "B", "C")  # D 级不引用


def load_chat_gateway():
    """解析 Agnes 文本网关 (base, key)。"""
    if resolve_gateway is None:
        raise RuntimeError("无法加载 gateway_config 模块")
    return resolve_gateway(
        env_base_var="AGNES_CHAT_BASE_URL",
        env_key_var="AGNES_CHAT_API_KEY",
    )


def citable_sources(brief: dict) -> list[dict]:
    """过滤出可引用的来源（A/B/C 级），保持原 trust 排序。"""
    return [s for s in brief.get("sources", [])
            if s.get("grade") in CITABLE_GRADES and s.get("url")]


def build_brief_prompt(topic: str, sources: list[dict]) -> str:
    """构造第 3 段 prompt：只写有来源支撑的内容，统一 [n] 引用。"""
    numbered = []
    for i, s in enumerate(sources, 1):
        numbered.append(
            "[%d] %s\n    URL: %s\n    等级: %s (trust %.2f)\n    摘要: %s"
            % (i, s.get("title", ""), s.get("url", ""),
               s.get("grade", "?"), float(s.get("trust", 0)),
               (s.get("snippet") or "")[:400])
        )
    src_block = "\n".join(numbered)
    return (
        "你是时尚产业研究助理。根据以下已策展、可信度打分的来源，"
        "撰写一份关于「%s」的中文研究报告简报。\n\n"
        "【铁律】\n"
        "1. 只写有来源支撑的内容：每条事实性断言（数据、品牌动作、趋势判断）\n"
        "   后面必须紧跟 [n] 引用，n 为下方来源编号；\n"
        "2. 没有来源支撑的内容，一律不写，不要推测、不要脑补；\n"
        "3. 优先引用 A/B 级来源；同一断言有多个来源时引用等级最高的；\n"
        "4. 引用格式统一为 [n]，不要用脚注、不要用超链接 inline；\n"
        "5. 简报结构：## 核心结论（3-5 条） / ## 分项趋势 / ## 数据一览表；\n"
        "6. 文末附「## 来源清单」，按编号列出标题 + URL；\n"
        "7. 若某子主题无可用来源，写「暂无可靠来源支撑，略去」而不是编造。\n\n"
        "【来源】（共 %d 条，已按可信度排序）\n%s\n"
        % (topic, len(sources), src_block)
    )


def call_agnes(prompt: str, model: str = DEFAULT_TEXT_MODEL,
               timeout: int = 180) -> str:
    """调 New API /v1/chat/completions，返回 markdown 文本。"""
    base, key = load_chat_gateway()
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "ppt-studio-brief-writer/1.0",
                 **({"Authorization": f"Bearer {key}"} if key else {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Agnes 返回空 choices")
    return (choices[0].get("message") or {}).get("content", "")


def validate_citations(md: str, n_sources: int) -> dict:
    """后验：检查 [n] 引用合法性。

    返回 {"ok": bool, "problems": [...]}：
      - 引用编号超出 [1..n_sources] 范围；
      - 含数字的事实行没有任何引用（启发式）。
    """
    problems: list[str] = []
    cited = set()
    for m in re.finditer(r"\[(\d+)\]", md):
        n = int(m.group(1))
        cited.add(n)
        if not (1 <= n <= n_sources):
            problems.append("引用 [%d] 超出来源范围 [1..%d]" % (n, n_sources))
    # 启发式：含百分号/数字+单位的事实行应有引用
    for line in md.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("["):
            continue
        if re.search(r"\d+\s*[%％]|\+?\d+%", s) and not re.search(r"\[\d+\]", s):
            problems.append("疑似无引用断言: %s" % s[:60])
    return {"ok": not problems, "problems": problems,
            "cited_count": len(cited), "source_count": n_sources}


def write_brief(brief_path: str, output: str | None = None,
                model: str = DEFAULT_TEXT_MODEL,
                dry_run: bool = False) -> dict:
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    sources = citable_sources(brief)
    if not sources:
        raise RuntimeError("无可引用来源（A/B/C 级为空），拒绝生成")
    prompt = build_brief_prompt(brief.get("topic", ""), sources)
    if dry_run:
        print(prompt)
        return {"dry_run": True, "prompt_chars": len(prompt)}
    md = call_agnes(prompt, model=model)
    check = validate_citations(md, len(sources))
    # 文末自动补来源清单（防 Agnes 漏写）
    if "## 来源清单" not in md:
        lines = ["", "## 来源清单", ""]
        for i, s in enumerate(sources, 1):
            lines.append("[%d] %s  \n    %s" % (i, s.get("title", ""), s.get("url", "")))
        md = md.rstrip() + "\n" + "\n".join(lines) + "\n"
    result = {"topic": brief.get("topic", ""), "model": model,
              "sources_used": len(sources),
              "citation_check": check, "markdown": md}
    if output:
        Path(output).write_text(md, encoding="utf-8")
        print("[ok] 简报 → %s（引用 %d/%d 来源）"
              % (output, check["cited_count"], len(sources)))
    if not check["ok"]:
        print("[warn] 引用校验发现 %d 个问题：" % len(check["problems"]),
              file=sys.stderr)
        for p in check["problems"][:10]:
            print("  - %s" % p, file=sys.stderr)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="三段式研究第 3 段：Agnes 写带 citation 简报")
    ap.add_argument("brief_json", help="research_to_spec.py 输出的 JSON")
    ap.add_argument("-o", "--output", help="输出 markdown 路径")
    ap.add_argument("--model", default=DEFAULT_TEXT_MODEL)
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印 prompt，不调 API")
    a = ap.parse_args()
    write_brief(a.brief_json, a.output, model=a.model, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
