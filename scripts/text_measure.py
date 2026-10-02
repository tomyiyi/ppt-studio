#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
text_measure.py -- PIL 实测字体宽度（带缓存）
=============================================
借鉴 ppt-master 差距5：用 PIL ImageFont 实测文本像素宽度，
替代字符数启发式（CJK=1.0em / 拉丁=0.52em），让 overflow 检查更准。

设计：
  - FontCache：按 (family_key, size) 缓存 ImageFont，避免重复加载
  - measure(text, size_px, family=None) -> float | None
    成功返回像素宽度；PIL 缺失/字体找不到时返回 None（调用方回退启发式）
  - 零依赖退化：无 PIL 也能 import，本模块 import 失败不影响主流程

字体查找顺序：family 指定 → Noto Sans CJK → Noto Sans → PIL 默认位图字体。
"""
from __future__ import annotations
import re
from pathlib import Path

try:
    from PIL import ImageFont
    _PIL_OK = True
except ImportError:
    ImageFont = None
    _PIL_OK = False

# 系统常见字体路径（Linux / macOS 兜底）
_FONT_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

_family_cache: dict[str, str | None] = {}


def _resolve_font(family: str | None) -> str | None:
    """family 名称 → 字体文件路径；找不到返回 None。"""
    key = (family or "").strip().lower()
    if key in _family_cache:
        return _family_cache[key]
    found = None
    # 1. family 直接是路径
    if family and Path(family).is_file():
        found = family
    else:
        # 2. fontconfig 精确解析（Linux 通用；硬编码路径在目标机不存在时兜底）
        if family:
            try:
                import subprocess
                r = subprocess.run(
                    ["fc-match", family, "--format=%{file}"],
                    capture_output=True, text=True, timeout=5)
                cand = r.stdout.strip().split("\n")[0]
                if cand and Path(cand).is_file():
                    found = cand
            except Exception:
                pass
    if not found:
        # 3. 按名称模糊匹配系统字体
        for cand in _FONT_CANDIDATES:
            if not Path(cand).is_file():
                continue
            stem = Path(cand).stem.lower()
            if not key or key.replace(" ", "") in stem.replace(" ", "") \
                    or "notosanscjk" in stem or "pingfang" in stem:
                found = cand
                break
        # 4. 兜底：第一个存在的候选
        if not found:
            for cand in _FONT_CANDIDATES:
                if Path(cand).is_file():
                    found = cand
                    break
    _family_cache[key] = found
    return found


class FontCache:
    """按 (font_path, size) 缓存 ImageFont。"""

    def __init__(self):
        self._fonts: dict[tuple[str, int], object] = {}

    def get(self, size: int, family: str | None = None):
        if not _PIL_OK:
            return None
        path = _resolve_font(family)
        key = (path or "default", size)
        if key not in self._fonts:
            try:
                if path:
                    self._fonts[key] = ImageFont.truetype(path, size)
                else:
                    self._fonts[key] = ImageFont.load_default()
            except Exception:
                return None
        return self._fonts[key]

    def measure(self, text: str, size: int, family: str | None = None) -> float | None:
        """返回文本像素宽度；失败返回 None。"""
        font = self.get(size, family)
        if font is None:
            return None
        try:
            # getbbox 比 getlength 更准（含字形边距）
            bbox = font.getbbox(text)
            if bbox:
                return float(bbox[2] - bbox[0])
            return float(font.getlength(text))
        except Exception:
            return None


_default_cache = FontCache()


def measure(text: str, size: int, family: str | None = None) -> float | None:
    """模块级快捷调用（共享默认缓存）。"""
    return _default_cache.measure(text, size, family)


def pil_available() -> bool:
    return _PIL_OK
