"""对已生成产物执行最薄的 QA 凭据交付门禁。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


_STAGES = ("image", "layout", "cards", "long_card")


def load_valid_attestation(path: str | Path) -> dict[str, Any]:
    """读取并严格校验 schema v1 的通过凭据；异常统一 fail-closed。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
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


def deliver_project(
    attestation_path: str | Path,
    source_path: str | Path,
    destination_path: str | Path,
) -> Path:
    """凭据通过后原子复制一个已生成产物；失败时不产生交付副作用。"""
    load_valid_attestation(attestation_path)
    source = Path(source_path)
    destination = Path(destination_path)
    if not source.is_file():
        raise FileNotFoundError(f"交付源产物不存在: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        os.close(fd)
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


def deliver_artifact_set(
    attestation_path: str | Path,
    sources: list[str | Path],
    destination_dir: str | Path,
) -> list[Path]:
    """在 cards QA 通过后事务性交付一组 SVG；失败时保留旧目录。"""
    attestation = load_valid_attestation(attestation_path)
    if attestation["stages"]["cards"]["ok"] is not True:
        raise ValueError("cards QA 未通过，禁止交付卡片集")

    resolved_sources: list[Path] = []
    seen: set[Path] = set()
    for raw_source in sources:
        source = Path(raw_source)
        resolved = source.resolve()
        if resolved in seen:
            raise ValueError(f"卡片源重复: {source}")
        seen.add(resolved)
        if source.suffix.lower() != ".svg":
            raise ValueError(f"卡片集包含非 SVG 文件: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"卡片源产物不存在: {source}")
        resolved_sources.append(source)
    if not resolved_sources:
        raise ValueError("卡片集不能为空")

    destination = Path(destination_dir)
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
