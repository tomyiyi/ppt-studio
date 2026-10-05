"""对已生成产物执行最薄的 QA 凭据交付门禁。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.qa_cards import run_qa_cards
    from scripts.qa_layout import run_qa_layout
    from scripts.qa_long_card import run_qa_long_card
    from scripts.qa_pptx import run_qa_pptx
    from scripts.qa_preview import run_qa_preview
    from scripts.qa_video import run_qa_subtitles, run_qa_video
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.qa_cards import run_qa_cards
    from scripts.qa_layout import run_qa_layout
    from scripts.qa_long_card import run_qa_long_card
    from scripts.qa_pptx import run_qa_pptx
    from scripts.qa_preview import run_qa_preview
    from scripts.qa_video import run_qa_subtitles, run_qa_video


_STAGES = ("image", "layout", "cards", "long_card")


def load_valid_attestation(path: str | Path, base_dir: str | Path | None = None) -> dict[str, Any]:
    """读取并严格校验 schema v1 的通过凭据；异常统一 fail-closed。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    p = Path(path)
    if not p.is_absolute():
        p = (base / p).resolve()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"QA attestation 无法读取或解析: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("QA attestation schema_version 不是 1")
    stages = data.get("stages")
    if data.get("overall") is not True or not isinstance(stages, dict):
        raise ValueError("QA attestation overall 未通过")
    if any(stages.get(name, {}).get("ok") is not True for name in _STAGES):
        raise ValueError("QA attestation 存在未通过阶段")
    return data


def validate_delivered_artifact(
    artifact_path: str | Path,
    original_name: str | None = None,
    *,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> None:
    """根据产物类型自动调用对应客观质量门禁。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    path = Path(artifact_path)
    if not path.is_absolute():
        path = (base / path).resolve()
    display_name = original_name or path.name
    if not path.is_file():
        raise FileNotFoundError(f"交付源产物不存在: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"产物客观质量门禁未通过: {display_name} (文件大小为 0 字节)")
    suffix = path.suffix.lower()
    ok = True
    if suffix == ".mp4":
        ok = bool(run_qa_video(path, verbose=verbose))
    elif suffix == ".pptx":
        ok = bool(run_qa_pptx(path, verbose=verbose))
    elif suffix == ".png":
        ok = bool(run_qa_long_card(path, verbose=verbose))
    elif suffix in (".html", ".htm"):
        ok = bool(run_qa_preview(path, verbose=verbose))
    elif suffix == ".svg":
        ok = bool(run_qa_layout(path, verbose=verbose))
    elif suffix == ".srt":
        ok = bool(run_qa_subtitles(path, verbose=verbose))

    if not ok:
        raise RuntimeError(f"产物客观质量门禁未通过: {display_name}")


def deliver_project(
    attestation_path: str | Path,
    source_path: str | Path,
    destination_path: str | Path,
    *,
    check: bool = False,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> Path:
    """凭据通过后原子复制一个已生成产物；失败时不产生交付副作用。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    load_valid_attestation(attestation_path, base_dir=base)
    source = Path(source_path)
    if not source.is_absolute():
        source = (base / source).resolve()
    destination = Path(destination_path)
    if not destination.is_absolute():
        destination = (base / destination).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"交付源产物不存在: {source}")
    if source.stat().st_size == 0:
        raise ValueError(f"交付源产物为空文件 (0 字节): {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=source.suffix,
        dir=destination.parent,
    )
    temp_path = Path(temporary)
    try:
        os.close(fd)
        shutil.copy2(source, temp_path)
        if check:
            validate_delivered_artifact(temp_path, original_name=source.name, verbose=verbose, base_dir=base)
        os.replace(temp_path, destination)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return destination


def deliver_artifact_set(
    attestation_path: str | Path,
    sources: list[str | Path],
    destination_dir: str | Path,
    *,
    check: bool = False,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> list[Path]:
    """在 cards QA 通过后事务性交付一组 SVG；失败时保留旧目录。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    attestation = load_valid_attestation(attestation_path, base_dir=base)
    if attestation["stages"]["cards"]["ok"] is not True:
        raise ValueError("cards QA 未通过，禁止交付卡片集")

    resolved_sources: list[Path] = []
    seen: set[Path] = set()
    for raw_source in sources:
        source = Path(raw_source)
        if not source.is_absolute():
            source = (base / source).resolve()
        resolved = source.resolve()
        if resolved in seen:
            raise ValueError(f"卡片源重复: {raw_source}")
        seen.add(resolved)
        if source.suffix.lower() != ".svg":
            raise ValueError(f"卡片集包含非 SVG 文件: {raw_source}")
        if not source.is_file():
            raise FileNotFoundError(f"卡片源产物不存在: {source}")
        if source.stat().st_size == 0:
            raise ValueError(f"卡片源产物为空文件 (0 字节): {source}")
        resolved_sources.append(source)
    if not resolved_sources:
        raise ValueError("卡片集不能为空")

    destination = Path(destination_dir)
    if not destination.is_absolute():
        destination = (base / destination).resolve()
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(f"卡片交付目标不是目录: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    backup: Path | None = None
    try:
        names: set[str] = set()
        for source in resolved_sources:
            if source.name in names:
                raise ValueError(f"卡片文件名冲突: {source.name}")
            names.add(source.name)
            shutil.copy2(source, staging / source.name)

        if check:
            if not run_qa_cards(staging, verbose=verbose):
                raise RuntimeError("卡片集客观质量门禁未通过")

        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{destination.name}.old.", dir=destination.parent))
            backup.rmdir()
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except Exception:
            if backup is not None and not destination.exists():
                os.replace(backup, destination)
                backup = None
            raise
        staging = None  # type: ignore[assignment]
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return [destination / source.name for source in resolved_sources]
    except Exception:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="带 QA attestation 门禁的已生成产物交付")
    parser.add_argument("source", nargs="?", default=None, help="单一产物交付源路径")
    parser.add_argument("destination", nargs="?", default=None, help="单一产物交付目标路径")
    parser.add_argument("--attestation", required=True, help="已生成的 QA attestation JSON")
    parser.add_argument("--source", dest="source_opt", help="单一产物交付源路径（覆盖位置参数）")
    parser.add_argument("--destination", dest="dest_opt", help="单一产物交付目标路径（覆盖位置参数）")
    parser.add_argument("--sources", nargs="+", help="卡片集交付源 SVG 文件列表")
    parser.add_argument("--destination-dir", help="卡片集交付目标目录")
    parser.add_argument("--check", action="store_true", help="交付前执行目标产物客观质量门禁校验")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志输出")
    args = parser.parse_args(argv)

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    try:
        if args.sources:
            if args.source_opt or args.source:
                raise ValueError("不能同时指定单一产物与卡片集交付源")
            dest_dir = args.destination_dir or args.dest_opt or args.destination
            if not dest_dir:
                raise ValueError("交付卡片集时必须指定 --destination-dir")
            delivered = deliver_artifact_set(
                attestation_path=args.attestation,
                sources=args.sources,
                destination_dir=dest_dir,
                check=args.check,
                verbose=args.verbose,
                base_dir=base,
            )
            print(f"[✓] 已交付卡片集: {len(delivered)} 张至 {dest_dir}")
        else:
            src = args.source_opt or args.source
            dst = args.dest_opt or args.destination
            if not src or not dst:
                raise ValueError("单一产物交付需要同时指定源路径与目标路径")
            delivered_file = deliver_project(
                attestation_path=args.attestation,
                source_path=src,
                destination_path=dst,
                check=args.check,
                verbose=args.verbose,
                base_dir=base,
            )
            print(f"[✓] 已交付产物: {delivered_file}")
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError, RuntimeError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

