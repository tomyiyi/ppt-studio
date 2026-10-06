"""在 QA attestation 通过后生成单一 HTML preview 交付物。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

try:
    from scripts.build_preview import build_preview
except ImportError:
    try:
        from build_preview import build_preview
    except ImportError:
        build_preview = None  # type: ignore


_STAGES = ("image", "layout", "cards", "long_card")


def validate_attestation_for_preview(
    path: str | Path,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p = Path(path)
    if not p.is_absolute() and base_dir is not None:
        p = (base / p).resolve()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ATTESTATION_INVALID") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("ATTESTATION_SCHEMA_UNSUPPORTED")
    stages = data.get("stages")
    if data.get("overall") is not True or not isinstance(stages, dict):
        raise ValueError("QA_NOT_PASSED")
    if any(
        name not in stages
        or not isinstance(stages.get(name), dict)
        or stages[name].get("ok") is not True
        for name in _STAGES
    ):
        raise ValueError("QA_NOT_PASSED")
    if any(not isinstance(v, dict) or v.get("ok") is not True for v in stages.values()):
        raise ValueError("QA_NOT_PASSED")
    return data


def deliver_preview(
    attestation_path: str | Path,
    src: str | Path | None,
    output_path: str | Path,
    *,
    title: str | None = None,
    cards: bool = False,
    check: bool = False,
    base_dir: str | Path | None = None,
) -> Path:
    """凭据通过后调用现有 preview builder；失败时不触碰输出文件。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    validate_attestation_for_preview(attestation_path, base_dir=base_dir)
    if not output_path or not str(output_path).strip():
        raise ValueError("交付目标路径不能为空")
    out = Path(output_path)
    if not out.is_absolute() and base_dir is not None:
        out = (base / out).resolve()
    if out.is_dir():
        raise IsADirectoryError(f"交付目标不能是已存在目录: {out}")
    if build_preview is None:
        raise RuntimeError("无法加载 build_preview 模块")

    resolved_src = src
    if base_dir is not None:
        if resolved_src is not None:
            src_p = Path(resolved_src)
            if not src_p.is_absolute():
                resolved_src = (base / src_p).resolve()
        else:
            resolved_src = base

    target_out = out if (base_dir is not None and not Path(output_path).is_absolute()) else output_path
    return build_preview(src=resolved_src, out=target_out, title=title, cards=cards, check=check)


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="带 QA attestation 门禁的 HTML preview 交付")
    parser.add_argument("src", nargs="?", default=None, help="包含 SVG 文件的目录或项目根目录（默认自发现）")
    parser.add_argument("output", nargs="?", default=None, help="最终 HTML 输出路径")
    parser.add_argument("--attestation", required=True, help="已生成的 QA attestation JSON")
    parser.add_argument("--base-dir", default=None, help="指定基础工作目录 (默认: 当前工作目录)")
    parser.add_argument("--src", dest="src_opt", help="包含 SVG 文件的目录或项目根目录（覆盖位置参数）")
    parser.add_argument("--output", dest="output_opt", help="最终 HTML 输出路径（覆盖位置参数）")
    parser.add_argument("--title", default=None, help="HTML 标题")
    parser.add_argument("--cards", action="store_true", help="沿用 build_preview 的 cards 模式")
    parser.add_argument("--check", action="store_true", help="交付前执行翻页预览客观质量门禁校验")
    args = parser.parse_args(argv)

    explicit_base = args.base_dir is not None or base_dir is not None
    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    src = args.src_opt or args.src
    out = args.output_opt or args.output

    if args.output_opt is None and args.output is None and args.src is not None:
        if args.src_opt is not None:
            out = args.src
            src = args.src_opt
        elif args.src.lower().endswith((".html", ".htm")):
            out = args.src
            src = None

    try:
        if not out:
            raise ValueError("交付翻页预览时必须指定输出路径")
        delivered = deliver_preview(
            attestation_path=args.attestation,
            src=src,
            output_path=out,
            title=args.title,
            cards=args.cards,
            check=args.check,
            base_dir=effective_base if explicit_base else None,
        )
        print(f"[✓] 已交付翻页预览: {delivered}")
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
