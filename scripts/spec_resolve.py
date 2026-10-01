"""spec_resolve.py -- spec_lock 多版本治理：单点解析 spec 文件版本选择。

背景（第 20 轮）：一个项目目录下可能并存多个 spec 锁文件
（spec_lock.md、spec_lock_v4.md 等），而各脚本此前硬编码只认
"spec_lock.md"，导致 v4 交付物被拿 v3 锁校验、误报"字号阶梯漂移"。

选择规则（显式 > 版本 > 基线）：
  1. 调用方 --spec 显式传入：永远优先（本模块不管，只约定俗成）。
  2. 同一目录下：spec_lock_v<N>.md 中 N 最大的胜出；
  3. 无版本化文件时回退 spec_lock.md；
  4. 备份/草稿变体（spec_lock.md.bak-*、spec_lock.md.v2bak、spec_lock.md.v3new
     等）永远不被选中——它们不是锁，只是历史残留。

用法：
  from scripts.spec_resolve import resolve_spec, find_spec
  spec = resolve_spec(project_dir)          # Path | None
  spec = find_spec(svg_or_pptx_target_path) # 周边目录逐层向上 + 仓库扫描
"""
from __future__ import annotations

import re
from pathlib import Path

# 只认严格的版本化命名：spec_lock_v<纯数字>.md
_VERSION_RE = re.compile(r"^spec_lock_v(\d+)\.md$", re.IGNORECASE)
_BASE_NAME = "spec_lock.md"


def resolve_spec(project_dir: str | Path) -> Path | None:
    """在单个项目目录内按 版本 > 基线 规则选择 spec 文件。

    返回绝对路径；目录不存在或无任何 spec 文件时返回 None。
    """
    d = Path(project_dir)
    if not d.is_dir():
        return None
    versioned: list[tuple[int, Path]] = []
    for p in d.glob("spec_lock_v*.md"):
        m = _VERSION_RE.match(p.name)
        if m and p.is_file():
            versioned.append((int(m.group(1)), p))
    if versioned:
        versioned.sort(key=lambda t: t[0])
        return versioned[-1][1].resolve()
    base = d / _BASE_NAME
    return base.resolve() if base.is_file() else None


def candidate_dirs(target_path: str | Path | None = None) -> list[Path]:
    """按优先级列出可能包含 spec 的目录（不做文件存在性判断）。"""
    dirs: list[Path] = []
    if target_path:
        tp = Path(target_path).resolve()
        if tp.is_file():
            dirs.extend([tp.parent, tp.parent.parent])
        else:
            dirs.extend([tp, tp.parent, tp.parent.parent])
    repo_root = Path(__file__).resolve().parent.parent
    dirs.extend([Path.cwd(), repo_root])
    # 去重保序
    seen: set[str] = set()
    uniq: list[Path] = []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def find_spec(target_path: str | Path | None = None) -> Path | None:
    """在目标路径周边目录逐层向上查找 spec，找不到时扫描仓库 projects/*。

    多项目各有 spec 时（>1 个项目目录能解析出 spec）返回 None，
    避免静默选错——调用方应要求用户用 --spec 显式指定。
    """
    for d in candidate_dirs(target_path):
        spec = resolve_spec(d)
        if spec:
            return spec
    # 兜底：动态扫描 projects/*/<spec>，避免硬编码项目名
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[Path] = []
    for cwd in (Path.cwd(), repo_root):
        proj_root = cwd / "projects"
        if not proj_root.is_dir():
            continue
        for proj_dir in sorted(proj_root.iterdir()):
            if not proj_dir.is_dir():
                continue
            spec = resolve_spec(proj_dir)
            if spec:
                hits.append(spec)
        if hits:
            break
    if len(hits) == 1:
        return hits[0]
    return None
