#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topic_to_deck.py — 一个主题进，一套 deck 出（单入口编排）

串起既有六段，不新造判据、不改任何阈值：

    brief -> research -> article -> narrative -> gate -> deck

    brief      主题 -> topic_brief.json（T-01：core_questions ≥2 才放行）
    research   auto_research.py（TAVILY_API_KEY 或 --injected，缺任一拒绝并说明）
    article    write_article.py（可选 --hook，无人值守期禁止自动生成）
    narrative  plan_narrative.py --md article.md [--role-plan] [--intent-plan]
    gate       check_narrative.py（blocking > 0 即停，**不跳过、不放宽**）
    deck       md_to_pptx.py（--no-images 出纯文字版）

设计约束：
- 只用标准库；每段是一次 subprocess 调用，可用 --dry-run 先看计划。
- 每段完成写 state.json，配合 --resume 断电可续（panic / 会话中断后不重跑已完成段）。
- 绝不打印任何密钥值，只打印环境变量**名字**与是否缺失。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import console_utf8  # noqa: F401  中文 Windows 控制台 GBK 兜底

SCRIPTS = Path(__file__).resolve().parent

STAGES = ["brief", "research", "article", "narrative", "gate", "deck"]

BLOCK_RE = re.compile(r"blocking\s+(\d+)\s+条")


class ConfigError(Exception):
    """入口配置问题：缺主题、问题数不足、来源不明。不动判据，直接拒。"""


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def make_brief(topic: str, audience: str, purpose: str,
               core_questions: Sequence[str]) -> dict:
    return {"topic": topic, "audience": audience, "purpose": purpose,
            "core_questions": list(core_questions)}


def validate_brief(brief: dict) -> None:
    """T-01 门禁：主题不裸写。core_questions < 2 说明还没想清楚，拒了再说。"""
    topic = (brief.get("topic") or "").strip()
    qs = [q for q in brief.get("core_questions", []) if str(q).strip()]
    if not topic:
        raise ConfigError("缺 topic：主题不能为空")
    if len(qs) < 2:
        raise ConfigError(
            f"T-01 未过：core_questions 只有 {len(qs)} 条，需 ≥2 条才允许开写（"
            "见 skills/article-writing-from-topic/SKILL.md）")


def stage_argv(cfg: argparse.Namespace) -> dict[str, list[str]]:
    """每段的 argv。纯函数：--dry-run 与测试都靠它，不碰文件系统。"""
    d = Path(cfg.workdir)
    py = sys.executable
    research = d / "research.json"
    article = d / "article" / "article.md"
    narrative = d / "narrative.json"
    argv: dict[str, list[str]] = {}

    if cfg.injected and Path(cfg.injected).exists():
        argv["research"] = [py, str(SCRIPTS / "auto_research.py"),
                            "--brief", str(d / "topic_brief.json"),
                            "--injected", str(cfg.injected),
                            "--out", str(research)]
    else:
        argv["research"] = [py, str(SCRIPTS / "auto_research.py"),
                            "--brief", str(d / "topic_brief.json"),
                            "--out", str(research)]

    argv["article"] = [py, str(SCRIPTS / "write_article.py"),
                       "--research", str(research),
                       "--out", str(d / "article"), "--name", "article"]
    if cfg.hook:
        argv["article"] += ["--hook", str(cfg.hook)]

    argv["narrative"] = [py, str(SCRIPTS / "plan_narrative.py"),
                         "--md", str(article), "--out", str(narrative)]
    if cfg.role_plan:
        argv["narrative"] += ["--role-plan", str(cfg.role_plan)]
    # 配图意图只能由人/LLM 显式给出文件，编排器绝不自动生成（未声明的页默认 none，
    # 由 check_narrative W-30 登记为需人读，不静默当成"决定不配图"）。
    if getattr(cfg, "intent_plan", None):
        argv["narrative"] += ["--intent-plan", str(cfg.intent_plan)]
    if cfg.governing:
        argv["narrative"] += ["--governing", cfg.governing]
    if cfg.audience:
        argv["narrative"] += ["--audience", cfg.audience]

    # check_narrative 的第二个参数是"素材根目录"，evidence 回指按 <根>/<文件名>#L 解析；
    # article.md 落在 workdir/article/ 下，所以根必须是该目录，否则 W-19 回指全部解析失败。
    argv["gate"] = [py, str(SCRIPTS / "check_narrative.py"),
                    str(narrative), str(article.parent)]

    argv["deck"] = [py, str(SCRIPTS / "md_to_pptx.py"),
                    "--md", str(article), "--out", str(d / "deck"),
                    "--name", "deck", "--narrative", str(narrative)]
    if cfg.no_images:
        argv["deck"] += ["--no-images"]
    return argv


def outputs_for(stage: str, cfg: argparse.Namespace) -> list[Path]:
    d = Path(cfg.workdir)
    return {
        "brief": [d / "topic_brief.json"],
        "research": [d / "research.json"],
        "article": [d / "article" / "article.md", d / "article" / "article_outline.json"],
        "narrative": [d / "narrative.json"],
        "gate": [d / "gate_report.json"],
        "deck": [d / "deck"],
    }[stage]


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"stages": {}}
    return {"stages": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_blocking(text: str) -> int | None:
    m = BLOCK_RE.search(text or "")
    return int(m.group(1)) if m else None


def run(cfg: argparse.Namespace,
        execute: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        log: Callable[[str], str] = print) -> dict:
    """按序执行所选阶段。返回 summary（各段状态 + blocking 数 + 停在哪）。"""
    workdir = Path(cfg.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    state_path = workdir / "state.json"
    state = load_state(state_path)
    state.setdefault("topic", cfg.topic)
    state.setdefault("stages", {})

    # --- brief 段（本进程内完成，不起子进程）---
    want = select_stages(cfg)
    if "brief" in want:
        brief = (json.loads(Path(cfg.brief).read_text(encoding="utf-8"))
                 if cfg.brief else
                 make_brief(cfg.topic, cfg.audience, cfg.purpose,
                            split_questions(cfg.core_questions)))
        validate_brief(brief)
        if cfg.dry_run:
            log("[dry-run] brief 校验通过：" + str(len(brief["core_questions"])) + " 条核心问题")
        else:
            (workdir / "topic_brief.json").write_text(
                json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
            mark(state, "brief", "done", cfg.dry_run)
            save_state(state_path, state)

    argv = stage_argv(cfg)
    summary = {"topic": cfg.topic, "stages": {}, "stopped_at": None, "blocking": None}

    for stage in STAGES:
        if stage == "brief" or stage not in want:
            continue
        if cfg.resume and state["stages"].get(stage, {}).get("status") == "done" \
                and all(p.exists() for p in outputs_for(stage, cfg)):
            log(f"[skip] {stage} 已完成且产物在盘（--resume）")
            summary["stages"][stage] = "skipped"
            continue
        cmd = argv[stage]
        if cfg.dry_run:
            log("[dry-run] " + " ".join(str(c) for c in cmd))
            summary["stages"][stage] = "planned"
            continue

        log(f"[{stage}] " + " ".join(str(c) for c in cmd))
        proc = (execute or default_execute)(cmd)
        stdout = getattr(proc, "stdout", "") or ""
        mark(state, stage, "done" if proc.returncode == 0 else "failed",
             cfg.dry_run, rc=proc.returncode)
        save_state(state_path, state)
        summary["stages"][stage] = "done" if proc.returncode == 0 else "failed"
        log(stdout.rstrip("\n"))

        if stage == "gate":
            blocking = parse_blocking(stdout)
            summary["blocking"] = blocking
            if not cfg.dry_run:
                (workdir / "gate_report.json").write_text(json.dumps({
                    "at": now_iso(), "blocking": blocking,
                    "note": "blocking>0 即停；判据与阈值一律未修改",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            if proc.returncode != 0 or (blocking or 0) > 0:
                summary["stopped_at"] = "gate"
                log(f"[停] 叙事门禁 blocking {blocking} 条——按纪律不跳过、不放宽，"
                    "已写 gate_report.json")
                return summary

        if proc.returncode != 0:
            summary["stopped_at"] = stage
            log(f"[停] {stage} 退出码 {proc.returncode}")
            return summary

    return summary


def default_execute(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          env=console_utf8.child_env(), **console_utf8.TEXT_KW)


def split_questions(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [q.strip() for q in re.split(r"[;；\n]", raw) if q.strip()]


def select_stages(cfg: argparse.Namespace) -> list[str]:
    """--stage a,b 选段；--from 起点；默认全跑。"""
    if cfg.stage:
        picked = [s.strip() for s in cfg.stage.split(",") if s.strip()]
        bad = [s for s in picked if s not in STAGES]
        if bad:
            raise ConfigError(f"未知阶段 {bad}，可选：{STAGES}")
        return [s for s in STAGES if s in picked]
    if cfg.from_stage:
        if cfg.from_stage not in STAGES:
            raise ConfigError(f"未知起点 {cfg.from_stage}")
        return STAGES[STAGES.index(cfg.from_stage):]
    return list(STAGES)


def mark(state: dict, stage: str, status: str, dry_run: bool, rc: int | None = None) -> None:
    entry = {"status": status, "at": now_iso()}
    if rc is not None:
        entry["rc"] = rc
    if dry_run:
        entry["dry_run"] = True
    state["stages"][stage] = entry


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="主题 -> deck 单入口编排")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--workdir", required=True, help="本套产物的工作目录")
    ap.add_argument("--brief", default=None, help="现成 topic_brief.json（给了就跳过生成）")
    ap.add_argument("--core-questions", default=None, help="用 ; 分隔，需 ≥2 条（T-01）")
    ap.add_argument("--audience", default="")
    ap.add_argument("--purpose", default="")
    ap.add_argument("--injected", default=None, help="无检索 key 时的预注入结果 JSON")
    ap.add_argument("--hook", default=None, help="extract_hook 产出 JSON；无人值守期禁止自动生成")
    ap.add_argument("--role-plan", default=None)
    ap.add_argument("--intent-plan", default=None,
                    help='JSON: {"节标题": "none|background|panel|hero"}；无人值守期禁止自动生成')
    ap.add_argument("--governing", default="")
    ap.add_argument("--stage", default=None, help="只跑这些阶段：a,b")
    ap.add_argument("--from", dest="from_stage", default=None, help="从某阶段起跑")
    ap.add_argument("--resume", action="store_true", help="跳过 state.json 里已完成且产物在盘的阶段")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不起子进程、不写产物")
    ap.add_argument("--no-images", action="store_true", help="deck 段跳过生图（纯文字版）")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    cfg = ap.parse_args(argv)
    if cfg.injected and not Path(cfg.injected).exists():
        print(f"--injected 指向的文件不存在：{cfg.injected}", file=sys.stderr)
        return 2
    if not cfg.brief and not cfg.injected:
        import os
        if not os.environ.get("TAVILY_API_KEY"):
            print("无检索来源：既没有 --injected，也没有设置环境变量 TAVILY_API_KEY。"
                  "拒绝伪造检索结果。", file=sys.stderr)
            return 2
    try:
        summary = run(cfg)
    except ConfigError as e:
        print(f"入口配置错误：{e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    if summary.get("stopped_at") == "gate":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
