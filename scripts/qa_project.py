"""PPT 项目级验收编排：只串联已有 QA gate，不复制检查算法。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.qa_image_pipeline import run_image_qa
from scripts.qa_assets import run_qa_assets
from scripts.qa_layout import run_qa_layout
from scripts.qa_cards import run_qa_cards
from scripts.qa_long_card import run_qa_long_card

try:
    from scripts.check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
except ImportError:
    try:
        from check_page_map import find_svg_dir, resolve_project_dir as _cpm_resolve_project_dir
    except ImportError:
        find_svg_dir = None
        _cpm_resolve_project_dir = None

try:
    from scripts.spec_resolve import resolve_spec
except ImportError:
    try:
        from spec_resolve import resolve_spec
    except ImportError:
        resolve_spec = None


def _find_svg_dir(p: Path) -> Path | None:
    if find_svg_dir is not None:
        return find_svg_dir(p)
    # fallback: 优先按数字版本最高 (svg_output_v4 > svg_output_v3 > svg_output)
    cands = sorted(
        [d for d in p.glob("svg_output*") if d.is_dir() and any(d.glob("*.svg"))],
        key=lambda d: (
            int(m.group(1)) if (m := re.match(r"^svg_output_v(\d+)$", d.name, re.I)) else (0 if d.name == "svg_output" else -1)
        ),
        reverse=True,
    )
    if cands:
        return cands[0]
    if any(p.glob("*.svg")):
        return p
    return None


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测待验收的项目根目录。

    1. 若显式指定非 '.' 的 project_arg：
       - 优先复用统一解析逻辑（若可用）；
       - 转换为绝对路径（若为相对路径则基于 base_dir 或当前工作目录解析）；
       - 若传入 spec 文件或关联文件，自适应回退到其所属项目目录；
       - 若存在且为子目录（如 images、svg_output、cards、notes、render、render_cards、output 等），自动回退到其父目录；
       - 返回绝对路径。
    2. 若未显式指定 project_arg 或为 '.'：
       - 探测 base_dir（默认当前工作目录）：
         * 若当前位于子目录（如 images/、svg_output/、cards/、render/ 等）或文件，优先回退到其所属有效项目目录；
         * 若当前目录直接包含有效项目特征（images/、svg_output/、cards/、render_cards/ 或 spec_lock.md、card_spec.md），返回该目录；
       - 从 base/projects 或仓库根目录 projects/ 探测：
         * 收集所有包含有效项目特征的子项目；
         * 若唯一匹配，返回该项目；
         * 若存在多个匹配项目，抛出 ValueError（避免歧义导致错误验收）；
         * 若未发现匹配项目，安全保留 base 路径。
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    is_default = (project_arg is None or str(project_arg).strip() in ("", "."))

    def is_valid_project(p: Path) -> bool:
        if not p.is_dir():
            return False
        if (
            p.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
            or p.name.startswith("svg_output")
            or p.name.startswith("render")
        ):
            return False
        cand_svg = _find_svg_dir(p)
        cand_spec = resolve_spec(p) if resolve_spec is not None else None
        return (
            (p / "images").is_dir()
            or (cand_svg is not None and cand_svg.is_dir() and any(cand_svg.glob("*.svg")))
            or (p / "svg_output").is_dir()
            or (p / "cards").is_dir()
            or (p / "render_cards").is_dir()
            or (p / "spec_lock.md").is_file()
            or (cand_spec is not None and cand_spec.is_file())
            or any(p.glob("spec_lock*.md"))
            or any(p.glob("card_spec*.md"))
        )

    if _cpm_resolve_project_dir is not None:
        try:
            cand = _cpm_resolve_project_dir(project_arg, base_dir=base_dir)
        except TypeError:
            cand = _cpm_resolve_project_dir(project_arg)
        if (
            cand.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
            or cand.name.startswith("svg_output")
            or cand.name.startswith("render")
        ):
            cand = cand.parent
        if not is_default:
            return cand
        if cand != base:
            return cand
        if is_valid_project(cand):
            return cand

    if not is_default:
        p = Path(project_arg)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()
        if p.is_file():
            if (
                (p.parent / "images").is_dir()
                or (p.parent / "cards").is_dir()
                or (p.parent / "svg_output").is_dir()
                or (p.parent / "render_cards").is_dir()
                or (p.parent / "render").is_dir()
                or any(p.parent.glob("card_spec*.md"))
                or any(p.parent.glob("spec_lock*.md"))
            ):
                return p.parent.resolve()
            p = p.parent
        if (
            p.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
            or p.name.startswith("svg_output")
            or p.name.startswith("render")
        ):
            return p.parent.resolve()
        return p

    # 优先检测 base 是否位于子产物目录或关联文件中
    if base.is_file():
        base = base.parent
    if (
        base.name in ("images", "svg_output", "render_cards", "render", "notes", "output", "cards")
        or base.name.startswith("svg_output")
        or base.name.startswith("render")
    ):
        return base.parent.resolve()

    if is_valid_project(base):
        return base

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
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """按 image -> assets -> layout -> cards -> long_card 顺序执行项目验收。"""
    root = resolve_project_dir(project, base_dir=base_dir)
    image_input = image_targets if image_targets is not None else root / "images"
    stages: dict[str, Any] = {}
    try:
        image_result = (
            run_image_qa(image_input, verbose=False, base_dir=base_dir)
            if base_dir is not None
            else run_image_qa(image_input, verbose=False)
        )
    except TypeError:
        image_result = run_image_qa(image_input, verbose=False)
    stages["image"] = image_result
    if not image_result["ok"]:
        return {"ok": False, "failed_stage": "image", "stages": stages}

    try:
        assets_result = run_qa_assets(root, base_dir=base_dir) if base_dir is not None else run_qa_assets(root)
    except TypeError:
        assets_result = run_qa_assets(root)
    stages["assets"] = assets_result
    if not assets_result["ok"]:
        return {"ok": False, "failed_stage": "assets", "stages": stages}

    try:
        layout_ok = bool(
            run_qa_layout(
                layout_target if layout_target is not None else root,
                verbose=verbose,
                base_dir=base_dir,
            )
            if base_dir is not None
            else run_qa_layout(layout_target if layout_target is not None else root, verbose=verbose)
        )
    except TypeError:
        layout_ok = bool(run_qa_layout(layout_target if layout_target is not None else root, verbose=verbose))
    stages["layout"] = {"ok": layout_ok}
    if not layout_ok:
        return {"ok": False, "failed_stage": "layout", "stages": stages}

    try:
        cards_ok = bool(
            run_qa_cards(
                cards_target if cards_target is not None else root,
                verbose=verbose,
                base_dir=base_dir,
            )
            if base_dir is not None
            else run_qa_cards(cards_target if cards_target is not None else root, verbose=verbose)
        )
    except TypeError:
        cards_ok = bool(run_qa_cards(cards_target if cards_target is not None else root, verbose=verbose))
    stages["cards"] = {"ok": cards_ok}
    if not cards_ok:
        return {"ok": False, "failed_stage": "cards", "stages": stages}

    try:
        long_card_ok = bool(
            run_qa_long_card(
                long_card_target if long_card_target is not None else root,
                verbose=verbose,
                base_dir=base_dir,
            )
            if base_dir is not None
            else run_qa_long_card(long_card_target if long_card_target is not None else root, verbose=verbose)
        )
    except TypeError:
        long_card_ok = bool(run_qa_long_card(long_card_target if long_card_target is not None else root, verbose=verbose))
    stages["long_card"] = {"ok": long_card_ok}
    if not long_card_ok:
        return {"ok": False, "failed_stage": "long_card", "stages": stages}

    return {"ok": True, "failed_stage": None, "stages": stages}


qa_project = run_project_qa


def build_qa_attestation(result: dict[str, Any]) -> dict[str, Any]:
    """把已有项目 QA 结果转换成稳定、可消费的最小验收凭据。"""
    stages = result.get("stages", {})
    attestation: dict[str, Any] = {
        "schema_version": 1,
        "overall": bool(result.get("ok")) and all(
            bool(stages.get(name, {}).get("ok"))
            for name in ("image", "assets", "layout", "cards", "long_card")
        ),
        "stages": {
            name: {"ok": bool(stages.get(name, {}).get("ok"))}
            for name in ("image", "assets", "layout", "cards", "long_card")
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


def write_qa_attestation(
    result: dict[str, Any],
    output_path: str | Path,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """原子写入项目 QA 凭据，并返回实际写入的标准 JSON 对象。"""
    attestation = build_qa_attestation(result)
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p = Path(output_path)
    destination = (base / p).resolve() if not p.is_absolute() else p.resolve()
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


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio 项目级全链路客观质量验收门禁")
    parser.add_argument("project", nargs="?", default=".", help="项目根目录（默认当前目录）")
    parser.add_argument("--attestation", help="可选输出验收凭据 JSON 路径")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 格式输出验收结果")
    parser.add_argument("--base-dir", default=None, help="指定基础工作目录 (默认: 当前工作目录)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    try:
        result = run_project_qa(args.project, verbose=args.verbose, base_dir=effective_base)
        if args.attestation:
            write_qa_attestation(result, args.attestation, base_dir=effective_base)
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

