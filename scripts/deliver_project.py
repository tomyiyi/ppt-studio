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
