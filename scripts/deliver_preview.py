"""在 QA attestation 通过后生成单一 HTML preview 交付物。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.build_preview import build_preview
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.build_preview import build_preview


_STAGES = ("image", "layout", "cards", "long_card")


def validate_attestation_for_preview(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ATTESTATION_INVALID") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("ATTESTATION_SCHEMA_UNSUPPORTED")
    stages = data.get("stages")
    if data.get("overall") is not True or not isinstance(stages, dict):
        raise ValueError("QA_NOT_PASSED")
    if any(stages.get(name, {}).get("ok") is not True for name in _STAGES):
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
) -> Path:
    """凭据通过后调用现有 preview builder；失败时不触碰输出文件。"""
    validate_attestation_for_preview(attestation_path)
    if not output_path or not str(output_path).strip():
        raise ValueError("交付目标路径不能为空")
    out = Path(output_path)
    if out.is_dir():
        raise IsADirectoryError(f"交付目标不能是已存在目录: {out}")
    return build_preview(src=src, out=output_path, title=title, cards=cards, check=check)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="带 QA attestation 门禁的 HTML preview 交付")
    parser.add_argument("src", nargs="?", default=None, help="包含 SVG 文件的目录或项目根目录（默认自发现）")
    parser.add_argument("output", nargs="?", default=None, help="最终 HTML 输出路径")
    parser.add_argument("--attestation", required=True, help="已生成的 QA attestation JSON")
    parser.add_argument("--src", dest="src_opt", help="包含 SVG 文件的目录或项目根目录（覆盖位置参数）")
    parser.add_argument("--output", dest="output_opt", help="最终 HTML 输出路径（覆盖位置参数）")
    parser.add_argument("--title", default=None, help="HTML 标题")
    parser.add_argument("--cards", action="store_true", help="沿用 build_preview 的 cards 模式")
    parser.add_argument("--check", action="store_true", help="交付前执行翻页预览客观质量门禁校验")
    args = parser.parse_args(argv)

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
        )
        print(f"[✓] 已交付翻页预览: {delivered}")
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
