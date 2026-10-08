#!/usr/bin/env python3
"""spec_lock.md 的唯一解析器。qa_layout / plan_contract / 所有 recipe 都从这里取版式常量。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

class TokensError(Exception):
    """spec_lock 缺节、缺键、栅格不闭合、色板缺键 —— 一律硬失败，不静默兜底。"""

KEY_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][\w-]*)\s*[:=]\s*(.*)$")
SEC_RE = re.compile(r"^\s*##\s+(.+?)\s*$")

def _blocks(text: str) -> dict[str, list[str]]:
    """按 `## 节名` 切块，返回 {节名: [原始行, ...]}（跳过代码块围栏内的假节名）。"""
    out: dict[str, list[str]] = {}
    cur: list[str] | None = None
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = SEC_RE.match(line)
        if m and not in_fence:
            cur = out.setdefault(m.group(1).strip(), [])
            continue
        if cur is not None and not in_fence:
            cur.append(line)
    return out

def _fields(lines: list[str]) -> dict[str, str]:
    """解析 `- key: value`。标量取 value 的第一个空白前 token，容忍历史行内注释。"""
    out: dict[str, str] = {}
    for line in lines:
        m = KEY_RE.match(line)
        if not m:
            continue
        k, raw = m.group(1), m.group(2).strip()
        if not raw:
            continue
        out[k] = raw.split()[0]
    return out

def _fields_raw(lines: list[str]) -> dict[str, str]:
    """解析 `- key: value`，保留完整 value（用于 bands 等多值字段）。"""
    out: dict[str, str] = {}
    for line in lines:
        m = KEY_RE.match(line)
        if not m:
            continue
        k, raw = m.group(1), m.group(2).strip()
        if not raw:
            continue
        # 去掉行内注释
        if "#" in raw:
            raw = raw[:raw.index("#")].strip()
        out[k] = raw
    return out

def section_names(text: str) -> set[str]:
    return {s for s in _blocks(text)}

@dataclass(frozen=True)
class Tokens:
    canvas_w: int
    canvas_h: int
    margin: int
    cols: int
    col: int
    gut: int
    bands: tuple[int, ...]
    baseline_step: int
    ramp: frozenset[int]
    poster: int
    colors: dict[str, str] = field(default_factory=dict)
    fonts: dict[str, str] = field(default_factory=dict)

    @property
    def content_w(self) -> int:
        return self.canvas_w - 2 * self.margin

    def colx(self, i: int) -> int:
        """第 i 列（0-based）左边界的 x。"""
        return self.margin + i * (self.col + self.gut)

    def colw(self, n: int) -> int:
        """跨 n 列的宽度。"""
        return n * self.col + (n - 1) * self.gut

    @property
    def closure_ok(self) -> bool:
        return self.margin + self.cols * self.col + (self.cols - 1) * self.gut + self.margin == self.canvas_w

    def palette(self, *names: str) -> dict[str, str]:
        return {n: self.colors[n] for n in names}

    def has_size(self, pt: int) -> bool:
        return pt in self.ramp

PALETTE_KEYS = {
    "background": "FIELD",
    "surface": "SURF",
    "divider": "STRUCT",
    "primary_text": "INK",
    "secondary_text": "SUB",
    "tertiary_text": "SUB2",
    "accent": "FOCUS",
    "improvement": "CAUTION",
}

def _ints(raw: str) -> tuple[int, ...]:
    return tuple(int(v) for v in re.findall(r"-?\d+", raw))

def parse(text: str) -> Tokens:
    b = _blocks(text)
    for need in ("canvas", "grid", "typography", "colors"):
        if need not in b:
            raise TokensError(f"spec_lock 缺 ## {need} 节")
    canv = _fields(b["canvas"]); grid = _fields_raw(b["grid"])
    typo = _fields(b["typography"]); cols_ = _fields(b["colors"])
    for k in ("width", "height"):
        if k not in canv:
            raise TokensError(f"## canvas 缺 {k}")
    for k in ("margin", "cols", "col", "gut", "bands", "baseline_step"):
        if k not in grid:
            raise TokensError(f"## grid 缺 {k}")
    if "poster" not in typo:
        raise TokensError("## typography 缺 poster —— 封面 P1 无法定字号")
    w = _ints(canv["width"])[0]
    h = _ints(canv["height"])[0]
    t = Tokens(
        canvas_w=w, canvas_h=h,
        margin=_ints(grid["margin"])[0], cols=_ints(grid["cols"])[0],
        col=_ints(grid["col"])[0], gut=_ints(grid["gut"])[0],
        bands=_ints(grid["bands"]), baseline_step=_ints(grid["baseline_step"])[0],
        ramp=frozenset(_ints(" ".join(v for k, v in typo.items() if k != "poster"))) | {_ints(typo["poster"])[0]},
        poster=_ints(typo["poster"])[0],
        colors={PALETTE_KEYS[k]: v for k, v in cols_.items() if k in PALETTE_KEYS},
        fonts=_fields(b.get("fonts", [])),
    )
    missing = sorted(set(PALETTE_KEYS.values()) - set(t.colors))
    if missing:
        raise TokensError(f"色板缺键: {missing}")
    if not t.closure_ok:
        raise TokensError(
            f"栅格不闭合: {t.margin}+{t.cols}×{t.col}+{t.cols-1}×{t.gut}+{t.margin}"
            f"={t.margin*2 + t.cols*t.col + (t.cols-1)*t.gut} != {t.canvas_w}")
    return t

def load(path: str | Path) -> Tokens:
    p = Path(path)
    if not p.exists():
        raise TokensError(f"spec_lock 不存在: {p}")
    return parse(p.read_text(encoding="utf-8"))

def load_project(project_dir: str | Path) -> Tokens:
    return load(Path(project_dir) / "spec_lock.md")
