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
) -> Path:
    """凭据通过后调用现有 preview builder；失败时不触碰输出文件。"""
    validate_attestation_for_preview(attestation_path)
    return build_preview(src=src, out=output_path, title=title, cards=cards, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="带 QA attestation 门禁的 HTML preview 交付")
    parser.add_argument("src", nargs="?", default=None, help="build_preview 原有源目录参数")
    parser.add_argument("--attestation", required=True, help="已生成的 QA attestation JSON")
    parser.add_argument("--output", required=True, help="最终 HTML 输出路径")
    parser.add_argument("--title", default=None, help="HTML 标题")
    parser.add_argument("--cards", action="store_true", help="沿用 build_preview 的 cards 模式")
    args = parser.parse_args(argv)
    try:
        deliver_preview(
            attestation_path=args.attestation,
            src=args.src,
            output_path=args.output,
            title=args.title,
            cards=args.cards,
        )
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
