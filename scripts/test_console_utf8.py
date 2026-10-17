#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_console_utf8.py — Windows GBK 控制台兜底的常驻门禁（S17，ppt-studio 侧）。

为什么要有这条门禁：这台机器的代码页是 936（GBK）。脚本只要往 stdout 打一个
✓ / ✗ / →，就会在**那一行**抛 UnicodeEncodeError 并让整个进程退出——最坏的是
真正的错误信息根本没打出来，人只看到一段 traceback。console_utf8.py 在导入时把
stdout/stderr reconfigure 成 UTF-8 + errors=replace，是全仓库统一的兜底；
但它是"隐式依赖"：新脚本忘了 import 就没人知道，直到某次在真终端里跑炸。

本门禁只做两件事，都不碰判据、不联网、不开浏览器：
  1) 静态：凡是要打印 cp936 编不出来的字符的脚本，其 import 闭包必须够得到
     console_utf8（或自身就是兜底模块）。
  2) 动态：import console_utf8 之后，stdout 必须真能吐出 ✓。

跑法： python scripts/test_console_utf8.py     （退出码 0 = 全过）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

GUARD_MODULE = "console_utf8"
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    RESULTS.append((ok, msg))


def risky_chars(text: str) -> set[str]:
    """返回该文件里 cp936 编码不了的字符（即"打了就炸"的字符）。"""
    out = set()
    for ch in text:
        if ord(ch) < 128:
            continue
        try:
            ch.encode("cp936")
        except UnicodeEncodeError:
            out.add(ch)
    return out


def top_level_imports(path: Path) -> set[str]:
    """只看模块级 import（函数内的不算——兜底必须在脚本一开始就生效）。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    mods: set[str] = set()
    for node in tree.body:                      # 只遍历模块顶层语句
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Try):         # try: import x 也算
            for sub in node.body:
                if isinstance(sub, ast.Import):
                    mods |= {a.name.split(".")[0] for a in sub.names}
                elif isinstance(sub, ast.ImportFrom) and sub.module:
                    mods.add(sub.module.split(".")[0])
    return mods


def reaches_guard(name: str) -> bool:
    """从该脚本出发做 import 闭包 BFS，够得到 console_utf8 即为有兜底。"""
    seen: set[str] = set()
    stack = [name]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        p = SCRIPTS / f"{cur}.py"
        if not p.exists():
            continue
        mods = top_level_imports(p)
        if GUARD_MODULE in mods:
            return True
        stack += sorted(m for m in mods if (SCRIPTS / f"{m}.py").exists())
    return False


def main() -> int:
    # ---- 1. 静态：谁在打 cp936 打不出的字，谁就必须够得到兜底 ----
    offenders = []
    scanned = 0
    for p in sorted(SCRIPTS.glob("*.py")):
        if p.name == Path(__file__).name:
            continue
        chars = risky_chars(p.read_text(encoding="utf-8", errors="replace"))
        scanned += 1
        if not chars:
            continue
        if p.stem == GUARD_MODULE:
            continue
        if not reaches_guard(p.stem):
            offenders.append((p.name, "".join(sorted(chars))[:12]))
    check(not offenders,
          f"静态：扫了 {scanned} 个脚本，缺 UTF-8 兜底的 {len(offenders)} 个"
          + ("" if not offenders else " -> " + "; ".join(f"{n}({c})" for n, c in offenders[:6])))

    # ---- 2. 动态：兜底确实生效（能吐出 ✓）----
    import console_utf8  # noqa: F401  导入即 reconfigure
    enc = (sys.stdout.encoding or "").lower()
    check("utf" in enc, f"动态：import console_utf8 后 stdout.encoding = {sys.stdout.encoding}")
    try:
        sys.stdout.write("\n  ✓ 兜底可打印\n")
        sys.stdout.flush()
        printed = True
    except UnicodeEncodeError as e:
        printed = False
        check(False, f"动态：打印 ✓ 仍抛 UnicodeEncodeError：{e}")
    if printed:
        check(True, "动态：✓ 顺利写出（GBK 终端下这一步原先会直接让进程炸掉）")

    bad = [m for ok, m in RESULTS if not ok]
    for ok, m in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {m}")
    print(f"通过 {len(RESULTS) - len(bad)} / 失败 {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
