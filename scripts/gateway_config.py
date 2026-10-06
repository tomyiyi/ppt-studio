#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gateway_config.py —— 网关配置统一解析
======================================

把「环境变量 → 配置文件 → 内置默认值」的配置层级抽成一个可复用函数，
消除各脚本手写 load_gateway / load_credentials 的重复逻辑。

层级（优先级从高到低）：
  显式 config_path（若给出）：
      配置文件值 > 环境变量 > 内置默认值
  默认配置文件（~/.new-api/local_key.json）：
      环境变量 > 配置文件值 > 内置默认值

注意两个分支的文件/环境优先级有意不同：显式传入的配置文件被视为
「用户本次明确指定」，其文件值优先；而默认配置文件只是兜底，
环境变量优先。保持与历史行为一致，不要「顺手统一」。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:13000/v1"
DEFAULT_KEY_PATH = Path.home() / ".new-api" / "local_key.json"


def _read_json_file(p: Path) -> dict:
    """读 JSON 配置文件；失败返回空 dict 并打印告警（保持历史行为）。"""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] 读取网关配置失败: {e}")
        return {}


def _first_present(d: dict, keys: tuple[str, ...]) -> str:
    """按顺序取第一个非空的文件键值。"""
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return ""


def resolve_gateway(
    *,
    env_base_var: str,
    env_key_var: str,
    file_base_keys: tuple[str, ...] = ("image_base_url", "base_url"),
    file_key_key: str = "api_key",
    default_base: str = DEFAULT_BASE,
    default_key: str = "",
    config_path: Path | str | None = None,
    default_path: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> tuple[str, str]:
    """统一解析网关配置，返回 (base_url, api_key)。

    参数：
      env_base_var / env_key_var: 环境变量名（如 AGNES_IMAGE_BASE_URL）
      file_base_keys: 配置文件里按优先级尝试的 base 键名
      file_key_key: 配置文件里的 api key 键名
      default_base / default_key: 内置默认值
      config_path: 显式指定的配置文件（可选）
      default_path: 默认配置文件路径（默认 ~/.new-api/local_key.json）
      base_dir: 基础工作目录（可选，用于解析相对路径的 config_path）
    """
    env_base = os.environ.get(env_base_var, "").strip()
    env_key = os.environ.get(env_key_var, "")

    if config_path:
        p = Path(config_path)
        if base_dir and not p.is_absolute():
            p = (Path(base_dir) / p).resolve()
        base = env_base or default_base
        key = env_key
        if p.exists():
            d = _read_json_file(p)
            if d:
                base = _first_present(d, file_base_keys) or base
                key = d.get(file_key_key) or key
        return base.rstrip("/"), key

    dp = Path(default_path) if default_path else DEFAULT_KEY_PATH
    file_base, file_key = "", ""
    if dp.exists():
        d = _read_json_file(dp)
        if d:
            file_base = _first_present(d, file_base_keys)
            file_key = d.get(file_key_key) or ""

    base = env_base or file_base or default_base
    key = env_key or file_key or default_key
    return base.rstrip("/"), key


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="gateway_config.py —— 网关配置统一解析工具",
    )
    parser.add_argument(
        "--env-base-var",
        default="AGNES_IMAGE_BASE_URL",
        help="网关 Base URL 环境变量名 (默认: AGNES_IMAGE_BASE_URL)",
    )
    parser.add_argument(
        "--env-key-var",
        default="AGNES_IMAGE_API_KEY",
        help="网关 API Key 环境变量名 (默认: AGNES_IMAGE_API_KEY)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="显式指定的配置文件路径",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出解析结果",
    )
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    base, key = resolve_gateway(
        env_base_var=args.env_base_var,
        env_key_var=args.env_key_var,
        config_path=args.config,
        base_dir=effective_base,
    )

    if args.json:
        masked_key = (key[:3] + "..." + key[-4:]) if len(key) >= 8 else ("***" if key else "")
        print(json.dumps({
            "base_url": base,
            "has_key": bool(key),
            "masked_key": masked_key,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"base_url={base} has_key={bool(key)}")
    return 0


__all__ = [
    "DEFAULT_BASE",
    "DEFAULT_KEY_PATH",
    "resolve_gateway",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
