#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文 Windows 控制台的编码兜底（S17）
===================================

中文 Windows 的控制台/管道默认编码是 GBK，脚本里一个 `✓`(U+2713) 或 `✗`(U+2717)
就够触发 `UnicodeEncodeError` 把整个进程崩掉 —— 崩的位置还偏偏在"打印失败原因"
那一行，于是真错误永远看不到（ppt-studio 的 render_svg.py 实测踩过）。

两种用法：
1. 入口脚本 import 段加一行 `import console_utf8  # noqa: F401  GBK 控制台兜底`，
   导入即把 stdout/stderr 改成 UTF-8。
2. 起子进程时用 `child_env()`（给子进程塞 PYTHONUTF8=1）并配
   `encoding="utf-8", errors="replace"` 解码，避免父 GBK / 子 UTF-8 的错位。

不覆盖 stdin：交互输入沿用系统编码，避免影响 `input()` 的既有行为。
"""
from __future__ import annotations

import os
import sys


def reconfigure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # 已被重定向/关闭等异常状态，不因此崩
                pass


def child_env(extra: dict | None = None) -> dict:
    """子进程环境：强制 UTF-8 mode，让被 spawn 的脚本不再被 GBK 崩掉。"""
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8:replace")
    if extra:
        env.update(extra)
    return env


TEXT_KW = {"encoding": "utf-8", "errors": "replace"}


reconfigure_streams()
