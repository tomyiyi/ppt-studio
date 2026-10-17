#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台资产根定位（黑苹果 macOS / Windows / Linux 共用一份代码）。

为什么需要它：仓库里原先写死了 `/Volumes/3TB_DATA/05-开发项目/...`，
迁到 Windows 主力开发后这些路径全部失效，但 3TB 素材盘的**盘符会变**，
所以按目录特征（存在 `05-开发项目` 这一层）扫描卷，而不是写死 E: 还是 F:。

对外三个函数，全部遵守同一优先级：
    环境变量  >  NTFS 开发区(F:\\Work)  >  3TB 素材盘  >  仓库 vendor
拿不到时返回第一个候选，由调用方按 exists() 如实报错，绝不静默兜底造假。

用法：
    from agnes_paths import agnes_root, agnes_data_dir, assets_root, template_root
"""
from __future__ import annotations

import os
import string
from pathlib import Path

THIS_SCRIPTS = Path(__file__).resolve().parent
PPT_STUDIO_ROOT = THIS_SCRIPTS.parent

_DATA_DIR_NAME = "05-开发项目"

# 3TB 素材卷上「开发项目」根的已知位置
_MAC_3TB = Path("/Volumes/3TB_DATA") / _DATA_DIR_NAME
_WIN_WORK = Path(r"F:\Work")


def data_root() -> Path:
    """3TB 素材盘上的 05-开发项目 根；找不到返回 macOS 老路径（调用方自行判存在）。"""
    env = os.environ.get("PPT_DATA_ROOT")
    if env:
        return Path(env)
    if _MAC_3TB.is_dir():
        return _MAC_3TB
    for letter in string.ascii_uppercase:
        cand = Path(letter + ":\\") / _DATA_DIR_NAME
        if cand.is_dir():
            return cand
    return _MAC_3TB


def _first_dir(cands):
    for c in cands:
        if c and Path(c).is_dir():
            return Path(c)
    return None


def agnes_root() -> Path:
    """agnes-studio 代码仓根目录。"""
    env = os.environ.get("AGNES_STUDIO_ROOT")
    if env:
        return Path(env)
    hit = _first_dir([
        _WIN_WORK / "agnes-studio",
        PPT_STUDIO_ROOT.parent / "agnes-studio",
        Path.home() / "Work" / "agnes-studio",
        _MAC_3TB / "agnes-studio-work",
        data_root() / "agnes-studio-work",
    ])
    return hit or (_MAC_3TB / "agnes-studio-work")


def agnes_data_dir() -> Path:
    return agnes_root() / "data"


def agnes_scripts_dir() -> Path:
    return agnes_root() / "scripts"


def assets_root() -> Path:
    """开源海报素材库（347MB 体量，留在 3TB 素材盘，不进 NTFS 开发区）。"""
    env = os.environ.get("AGNES_ASSETS_ROOT")
    if env:
        return Path(env)
    hit = _first_dir([
        data_root() / "agnes-studio-assets" / "open_source_posters",
        _MAC_3TB / "agnes-studio-assets" / "open_source_posters",
    ])
    return hit or (_MAC_3TB / "agnes-studio-assets" / "open_source_posters")


def template_root() -> Path:
    """ppt-master 版式模板根。3TB 上是 9 套完整版式，仓库 vendor 只有 2 套 ——
    优先 3TB，与黑苹果产出保持一致；3TB 不在线时才退回 vendor。"""
    env = os.environ.get("PPT_TEMPLATE_ROOT")
    if env:
        return Path(env)
    rel = Path("ppt") / "tools" / "ppt-master" / "skills" / "ppt-master" / "templates" / "layouts"
    hit = _first_dir([
        data_root() / rel,
        _MAC_3TB / rel,
        PPT_STUDIO_ROOT / "vendor" / "ppt-master" / "templates" / "layouts",
    ])
    return hit or (PPT_STUDIO_ROOT / "vendor" / "ppt-master" / "templates" / "layouts")


if __name__ == "__main__":
    print("data_root      =", data_root(), data_root().is_dir())
    print("agnes_root     =", agnes_root(), agnes_root().is_dir())
    print("assets_root    =", assets_root(), assets_root().is_dir())
    print("template_root  =", template_root(), template_root().is_dir())
