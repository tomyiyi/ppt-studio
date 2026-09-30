"""PPT 项目级验收编排：只串联已有 QA gate，不复制检查算法。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.qa_image_pipeline import run_image_qa
from scripts.qa_layout import run_qa_layout
from scripts.qa_cards import run_qa_cards
from scripts.qa_long_card import run_qa_long_card


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测待验收的项目根目录。

    1. 若显式指定非 '.' 的 project_arg：
       - 转换为绝对路径（若为相对路径则基于 base_dir 或当前工作目录解析）；
       - 若存在且为子目录（如 images、svg_output、cards、notes），自动回退到其父目录；
       - 返回绝对路径。
    2. 若未显式指定 project_arg 或为 '.'：
       - 探测 base_dir（默认当前工作目录）：
         * 若当前目录直接包含有效项目特征（images/、svg_output/、cards/ 或 spec_lock.md），返回该目录；
         * 若当前位于子目录（如 images/、svg_output/、cards/），返回其父目录；
       - 从 base/projects 或仓库根目录 projects/ 探测：
         * 收集所有包含有效项目特征的子项目；
         * 若唯一匹配，返回该项目；
         * 若存在多个匹配项目，抛出 ValueError（避免歧义导致错误验收）；
         * 若未发现匹配项目，安全保留 base 路径。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    is_default = (project_arg is None or str(project_arg).strip() in ("", "."))

    if not is_default:
        p = Path(project_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
        if p.is_dir() and p.name in ("images", "svg_output", "cards", "notes"):
            return p.parent.resolve()
        return p

    def is_valid_project(p: Path) -> bool:
        if not p.is_dir():
            return False
        return (
            (p / "images").is_dir()
            or (p / "svg_output").is_dir()
            or (p / "cards").is_dir()
            or (p / "spec_lock.md").is_file()
        )

    if is_valid_project(base):
        return base

    if base.name in ("images", "svg_output", "cards", "notes") and is_valid_project(base.parent):
        return base.parent.resolve()

    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        repo_root = Path(__file__).resolve().parent.parent
        p_cand = repo_root / "projects"
        if p_cand.is_dir():
            candidate_projects_dirs.append(p_cand)

    found: list[Path] = []
    seen: set[Path] = set()
    for p_dir in candidate_projects_dirs:
        if not p_dir.is_dir():
            continue
        for sub in sorted(p_dir.iterdir()):
            if is_valid_project(sub):
                r = sub.resolve()
                if r not in seen:
                    seen.add(r)
                    found.append(r)

    if len(found) == 1:
        return found[0]
    elif len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise ValueError(f"发现多个项目 ({names})，无法安全确定，请显式指定 project 参数")

    return base


def run_project_qa(
    project: str | Path = ".",
    *,
    image_targets: str | Path | list[str | Path] | None = None,
    layout_target: str | Path | None = None,
    cards_target: str | Path | None = None,
    long_card_target: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """按 image -> layout -> cards -> long_card 顺序执行项目验收。"""
    root = resolve_project_dir(project)
    image_input = image_targets if image_targets is not None else root / "images"
    stages: dict[str, Any] = {}
    image_result = run_image_qa(image_input, verbose=False)
    stages["image"] = image_result
    if not image_result["ok"]:
        return {"ok": False, "failed_stage": "image", "stages": stages}

    for name, runner, target in (
        ("layout", run_qa_layout, layout_target if layout_target is not None else root),
        ("cards", run_qa_cards, cards_target if cards_target is not None else root),
        ("long_card", run_qa_long_card, long_card_target if long_card_target is not None else root),
    ):
        ok = bool(runner(target, verbose=verbose))
        stages[name] = {"ok": ok}
        if not ok:
            return {"ok": False, "failed_stage": name, "stages": stages}

    return {"ok": True, "failed_stage": None, "stages": stages}


qa_project = run_project_qa


def build_qa_attestation(result: dict[str, Any]) -> dict[str, Any]:
    """把已有项目 QA 结果转换成稳定、可消费的最小验收凭据。"""
    stages = result.get("stages", {})
    attestation: dict[str, Any] = {
        "schema_version": 1,
        "overall": bool(result.get("ok")) and all(
            bool(stages.get(name, {}).get("ok"))
            for name in ("image", "layout", "cards", "long_card")
        ),
        "stages": {
            name: {"ok": bool(stages.get(name, {}).get("ok"))}
            for name in ("image", "layout", "cards", "long_card")
        },
    }
    if result.get("failed_stage") is not None:
        attestation["failed_stage"] = result["failed_stage"]
    for name, stage in stages.items():
        if isinstance(stage, dict):
            for key in ("code", "reason"):
                if key in stage:
                    attestation["stages"].setdefault(name, {})[key] = stage[key]
    return attestation


def write_qa_attestation(result: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    """原子写入项目 QA 凭据，并返回实际写入的标准 JSON 对象。"""
    attestation = build_qa_attestation(result)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(attestation, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return attestation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio 项目级全链路客观质量验收门禁")
    parser.add_argument("project", nargs="?", default=".", help="项目根目录（默认当前目录）")
    parser.add_argument("--attestation", help="可选输出验收凭据 JSON 路径")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 格式输出验收结果")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
    args = parser.parse_args(argv)

    try:
        result = run_project_qa(args.project, verbose=args.verbose)
        if args.attestation:
            write_qa_attestation(result, args.attestation)
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as err:
        if args.as_json:
            print(json.dumps({"ok": False, "error": str(err)}, ensure_ascii=False))
        else:
            print(f"[err] {err}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        status = "✓ 项目客观质量门禁全量通过" if result["ok"] else f"✗ 项目客观质量门禁失败 (阶段: {result.get('failed_stage')})"
        print(f"[门禁] {status}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

