# PPT 设计层重写 — 实施计划

> **本计划的执行者假设：零上下文、无人值守、24 小时长跑。**
> 所有几何值、行号、门禁命令都来自 2026-10-08 对 3TB 实物与 spike 实证的取证，不是推测。
> 遇到与本计划不一致的现场事实，**以现场为准并停下来写报告**，不要自行发明替代方案。

**Spec（权威源，必读全文后再动手）**：
`docs/superpowers/specs/2026-10-08-ppt-design-layer-design.md`（406 行 / 28865 B）

**Goal**：把 ppt-studio 从"把文字填进模板槽位"升级为"有设计判断的演示文稿"——叙事结构先于排版、7 种页面角色各配一个参数化配方、封面走纯排版 P1 基准、版式常量收敛到单一真相源、质检门禁能机械化度量尺度与对比度。

**Architecture**（新增两层，旧层保留为兜底）：

```
markdown ──N1 plan_narrative.py──> narrative.json      （结构器，不写文案）
                │
                N2 check_narrative.py（可机械判定的 W-xx → blocking）
                │
   md_to_pages.py --narrative（同时产出 role/assertion/evidence/image_intent）
                │
   layout_recipes.py  7 配方 ← role            （未覆盖 role → template_renderer + fallback=true）
                │
   pages/*.svg ──render_svg──> png ── qa_layout.py（含新 [尺度]/[网格]）
                │                       qa_score.py（权重配平 + hierarchy 项）
                │                       vendor svg_quality_checker --stage final
   plan_contract.py（+ check_spec_parity / check_narrative_landing）
                │
   svg_to_pptx.py ──> .pptx（回读校验）
                ↑
   patterns/spec_lock.template.md ── scripts/spec_tokens.py（唯一常量解析器）
```

**Tech Stack**：Python 3.11 标准库 + 仓库已有的 numpy / Pillow / lxml-free（ET 用 `xml.etree.ElementTree`）。**禁止 pytest，禁止新增任何第三方依赖**（本仓约定是纯 python 自检脚本 `scripts/test_*.py`，`ok(name, cond)` + 非零退出码）。SVG 直写，不引入前端框架。

---

## Global Constraints（逐条硬约束，违反即停）

1. **仓库根 / 执行环境**（黑苹果侧）：
   ```bash
   PS=/Volumes/3TB_DATA/05-开发项目/ppt-studio
   PY=$PS/.venv/bin/python
   [ -x "$PY" ] || PY=/usr/local/bin/python3.11
   cd "$PS"
   ```
   dev 代码只认 3TB 工程中心，不要在别的副本上改。

2. **沟通与文档语言**：全部中文（commit message、报告、代码注释、issue 描述）。

3. **破坏性操作保持克制**：不删除、不重置、不 `checkout --`、不 `stash drop`、不 force-push、不批量改动、不改 git 配置。
   - **特别禁止**：`git stash` 之后的 `git stash drop`；若必须用 stash 取"改前快照"，取完立刻 `git stash pop` 并用 `git status --porcelain` 自证工作区已恢复。

4. **commit 纪律**：每个 Task 一个 commit（spec §8 已定，用户已批准实施）。
   - **绝对不得混入**：`projects/agentflow-os-launch/cards/02_tension.svg`、`projects/agentflow-os-launch/cards/03_position.svg` —— 这两个是历史遗留未提交改动，与本期无关。`git add` 只按文件名精确添加，**禁止 `git add -A` / `git add .`**。
   - 不 push（用户没要求推送）。

5. **密钥安全**：任务单、日志、报告中**严禁出现任何 api key 明文**。生图（Task 14）需要的变量只报告"缺哪个变量名"（如 `MODELBEST_API_KEY`），严禁创建或修改真实凭据文件（`.env` / `.env.local`）。缺凭据时该步标记为"需人工"，不得伪造成功。

6. **证据分级 / 防伪校验**（这是本仓最严重的历史翻车点）：
   - 错误计数**必须**落在逐页 `Passed/Failed` 行或 `--json` 字段上。
     ```bash
     # ✅ 正确口径
     ... --stage final --json | grep -c '"passed": false'
     # ❌ 历史事故口径：把汇总行 [ERROR] With errors: 0 数成 1 条错误
     ... | grep -c '[ERROR]'
     ```
   - 不得把"命令启动了 / 页面打开了 / 部分测试通过"说成端到端成功。
   - 任何"已验证"必须附实际命令与实际输出。未通过的检查显式写进报告，禁止用"基本完成""应该可以"掩盖。

7. **函数签名硬约束**（回归不破）：
   - `qa_layout.check_contrast(img, root)` 的**两参签名不得改变**（`scripts/test_qa_layout_fixes.py` 以 `Q.check_contrast(img1, svg(s5))` 调用并取 `r[0][0]`）。返回元组可以从 3 元扩到 4 元，但第 0 项必须仍是 ratio、第 1 项仍是文本。
   - `qa_score.WEIGHTS` 各项之和**必须仍为 100**，因为 `qa_score.py:97` 是 `total = sum(c["score"]*c["weight"] for c in checks)/100.0`。加维度不减权重 = 总分虚高。
   - `layout_recipes` 的配方签名统一 `def recipe_xxx(pg: dict, tok) -> str`（spec §4.2 写作 `page: dict`，本计划把参数名统一为 `pg`，避免与文档函数同名造成遮蔽 —— 语义不变），返回**完整 SVG 文档字符串**（含 `<svg>` 根）。

8. **版式常量唯一来源**：`patterns/spec_lock.template.md` → `scripts/spec_tokens.py`。任何新代码里出现 `60`/`76`/`1280` 之类的裸版式常量都算违规（渲染兜底除外，兜底必须注释"仅供缺 spec_lock 时自检"）。

9. **写作红线（配方/文案生成不得越界）**：规则层只做"筛"，不做"写"。不合格标题不截断成半句，标记 `needs_review` 交人/LLM 复核（详见 Task 6/7）。

---

## 对 spec 的两处就地修正（执行时按修正后口径，不再回问）

**修正 1 — 回归判定口径**。spec §9.3 写"历史 18 页无任何一页变差"，但 §4.1 把版心从 60 收到 76（单侧多 16px，内容宽少 32px），**必然**新增 `[溢出]` 命中。两者直接冲突。
采用口径：**按维度对账** —— 原有的 typescale / backdrop / dup_images / collisions / contrast 五个维度不得劣化；`[溢出]` 允许新增，但每一处新增都必须逐条归因到 margin 变化（给出页号 + 元素 + 改前后 x1 值），并写进报告；`[尺度]` / `[网格]` 是本期**新增维度**，在历史页上的命中只记录、不计入"变差"、不回填修改历史页。

**修正 2 — 字段完整性口径**。spec §1.5 写"每页 7 字段齐全"，但 `section` / `cover` 角色天然没有 `evidence` 与 `baseline`。
采用口径：**逐 role 定义必填集**（见 Task 6 的 `REQUIRED` 字典），缺该 role 的必填项才 blocking。

---

## File Structure（本期新增 / 改动全表）

**新增**：
| 文件 | 职责 | Task |
|---|---|---|
| `scripts/spec_tokens.py` | 唯一 spec_lock 解析器，产出 frozen `Tokens` | 2 |
| `scripts/test_spec_tokens.py` | 14 项合成用例 | 2 |
| `patterns/spec_lock.template.md` | 模板真相源（替代"工程实例兼任"） | 3 |
| `scripts/test_plan_contract_sections.py` | 节集合对账 + 落点校验 | 3, 8 |
| `scripts/plan_narrative.py` | N1 结构器 → narrative.json | 6 |
| `scripts/test_plan_narrative.py` | 11 项 | 6 |
| `scripts/check_narrative.py` | N2 写作门禁（W-xx） | 7 |
| `scripts/test_check_narrative.py` | 17 项 | 7 |
| `scripts/layout_recipes.py` | 7 个参数化配方 | 10-13 |
| `scripts/test_layout_recipes.py` | 18 项 | 10 |
| `scripts/test_qa_scale_and_contrast.py` | 12 项 | 5 |
| `spikes/2026-10-10-margin-regression/` | 版心回归对账留档 | 4 |
| `spikes/2026-10-10-narrative-backfill/probe.py` | 批 2 闸门：18 页反向构造跑门禁 | 7 |

**改动**：`scripts/qa_layout.py`（MARGIN/DEFAULT_RAMP 读 tok + `check_scale` + `check_grid_step` + `wcag_need` + main 两行输出）、`scripts/pages_to_svg.py`（兜底常量 + main 覆盖）、`scripts/qa_score.py`（权重配平 + hierarchy 项 + 传 margin）、`scripts/plan_contract.py`（`REQUIRED_SPEC_SECTIONS` + 两个新函数）、`scripts/md_to_pages.py`（`--narrative` + `_project_from_narrative`）、`scripts/md_to_pptx.py`（真相源路径 + N1/N2/render+qa_layout 接线 + recipe 路由）、`projects/*/spec_lock.md`（补 `## grid` + `poster`）、`docs/workflow.md`、`docs/qa-checklist.md`。

**保留不动**：`scripts/template_renderer.py`（兜底 + 回归基线）、`scripts/svg_to_pptx.py`、vendor `svg_quality_checker.py`。

---

## 批次映射（spec §8 五批 ↔ 本计划 16 Task）

| 批 | spec 内容 | Task | 闸门 |
|---|---|---|---|
| 批 0 | 基线钉死 | 1 | 自检绿 + commit |
| 批 1 | 真相源 + 尺度门禁 | 2,3,4,5 | 版心回归按修正 1 口径对账通过 |
| 批 2 | 叙事两层 | 6,7,8,9 | `check_narrative` 单测 17 绿 + 18 页反向构造探针报告 |
| 批 3 | 7 配方 | 10,11,12,13 | `test_layout_recipes` 18 绿 + vendor 门禁 0 introduced warning |
| 批 4 | 生图 + 接线 | 14,15 | 端到端 1 个真实工程出 pptx + 回读校验 |
| 批 5 | 收口 | 16 | 三层验收 + 知识库 post-flight |

**批间闸门是硬的：任一批的闸门不过，停止后续批次，写失败报告。** 不许"先往下做再回来补"。

---

## Task 1 — 把未提交的 qa_layout 修正钉成基线

**背景**：`git status --porcelain` 现状（2026-10-08 实测）是 ` M scripts/qa_layout.py`、`?? scripts/test_qa_layout_fixes.py`、`?? skills/ppt-*/`、`?? spikes/`、`?? docs/superpowers/`，HEAD = `1f01919`。而 `regression_qa.sh` 的"改前"参照依赖 `git show HEAD:` —— 修正不提交，后续所有回归对账的参照系都是错的。

**Steps**：
1. `cd "$PS" && "$PY" scripts/test_qa_layout_fixes.py` → 必须输出全绿、退出码 0。红则停：说明工作区的 qa_layout 修正本身有问题，写报告，不进任何后续 Task。
2. 精确添加（不含两个 cards SVG）：
   ```bash
   git add scripts/qa_layout.py scripts/test_qa_layout_fixes.py
   [ -d skills ] && git add skills
   [ -d spikes ] && git add spikes
   git add docs/superpowers
   git status --porcelain   # 人读一遍：确认 cards/*.svg 仍在 ' M' 未暂存列
   ```
3. `git commit -m "chore(qa): 固定 qa_layout 三处误判修正与自检，作为设计层重写基线"`
4. 若第 3 步把 cards 带进去了（`git show --stat HEAD` 里出现 `02_tension.svg`）：**立即** `git reset --soft HEAD~1`、`git reset HEAD projects/`、重新按第 2 步添加、重 commit，并在报告里记录这次返工。

**Verify**：
```bash
git log --oneline -1
git show --stat HEAD | grep -c 'cards/' # 必须 0
git show HEAD:scripts/qa_layout.py | grep -c 'Otsu' # >=1，证明修正在 HEAD 里
git status --porcelain | grep 'cards/'  # 必须仍在（未被本期动过）
```
**此后所有回归对账的"改前"参照必须用显式快照**（`cp` 到 `/tmp/bkreg*`），**不再用 HEAD** —— 因为 HEAD 会随每个 Task 前移。

---

## Task 2 — `scripts/spec_tokens.py`：唯一常量解析器

**根因**：`pages_to_svg.py:26-27` 写死 `MARGIN=60` / `RAMP={11,13,16,20,24,32,44,96}`（连 56 都没有），`qa_layout.py:36 MARGIN = 60`、`:101 DEFAULT_RAMP` 同样写死，而 `L-01` 规格里说 margin=76 —— 三处各写各的，正是 workflow.md「常见翻车档案」里"质检阈值和生成器打架"那条。收敛到一个解析器。

**Files**: 新增 `scripts/spec_tokens.py`、`scripts/test_spec_tokens.py`。

**Steps** — `spec_tokens.py` 全量实现：

```python
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

    # ---- 派生量（配方只调这些，不自己算） ----
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

PALETTE_KEYS = {                       # spec_lock 键 → 配方内部 token 名
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
    canv = _fields(b["canvas"]); grid = _fields(b["grid"])
    typo = _fields(b["typography"]); cols_ = _fields(b["colors"])
    for k in ("width", "height"):
        if k not in canv:
            raise TokensError(f"## canvas 缺 {k}")
    for k in ("margin", "cols", "col", "gut", "bands", "baseline_step"):
        if k not in grid:
            raise TokensError(f"## grid 缺 {k}")
    if "poster" not in typo:
        raise TokensError("## typography 缺 poster —— 封面 P1 无法定字号")
    w, h = int(canv["width"]), int(canv["height"])
    t = Tokens(
        canvas_w=w, canvas_h=h,
        margin=int(grid["margin"]), cols=int(grid["cols"]),
        col=int(grid["col"]), gut=int(grid["gut"]),
        bands=_ints(grid["bands"]), baseline_step=int(grid["baseline_step"]),
        ramp=frozenset(_ints(" ".join(v for k, v in typo.items() if k != "poster"))) | {int(typo["poster"])},
        poster=int(typo["poster"]),
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
```

**注意 ramp 的解析**：`typo` 里除 `poster` 外的角色行值都是字号（`body: 16` 等），`_ints(" ".join(...))` 一次拿到全部档位；实测 workflow_full 的九档是 `{11,13,16,20,24,32,44,56,96}` —— 加 poster 得十档。**必须包含 56**，这是 `pages_to_svg.py:27` 当前缺的那一档。

**Steps** — `test_spec_tokens.py`（14 项，纯合成，不依赖工程）：
`ok()` 辅助函数照抄 `scripts/test_qa_layout_fixes.py` 里的写法。用例清单：
1. 最小合法 spec（含 canvas/grid/typography/colors 全键，栅格闭合）→ `parse` 不抛。
2. 缺 `## grid` → `TokensError`，消息含 "grid"。
3. `## grid` 缺 `gut` → `TokensError` 含 "gut"。
4. `## typography` 缺 `poster` → `TokensError` 含 "poster"。
5. 栅格故意不闭合（margin 改 60）→ `TokensError` 含 "栅格不闭合"。
6. 色板故意删 `accent` → `TokensError` 含 "色板缺键"。
7. `colx(0)==margin`、`colx(1)==margin+col+gut`。
8. `colw(12)==content_w`。
9. `content_w == 1280-2*76 == 1128`。
10. 行内注释容忍：`- margin: 76          # 取 L-01` → `margin==76`（**这是关键用例**，历史 spec 有行内注释）。
11. `## canvas` 值带 `px` 单位（`width: 1280px`）→ `_ints` 仍能取到 1280。
12. `bands` 解析成 tuple 且升序、含 8。
13. `has_size(56)` 为真、`has_size(17)` 为假。
14. 代码块围栏里的 `## 假节` 不被当节名（`_blocks` 跳过围栏）。

**Verify**：`"$PY" scripts/test_spec_tokens.py` 全绿；`"$PY" -c "import sys;sys.path.insert(0,'scripts');import spec_tokens as s;print(s.load('projects/agentflow-os-launch/spec_lock.md'))"` —— **这一步预期抛 TokensError（该工程还没有 `## grid`）**，这是 Task 3 要补的；把它当作"解析器确实在硬校验"的证据记录进报告，不要为了让它通过而放宽解析器。

**Commit**：`git add scripts/spec_tokens.py scripts/test_spec_tokens.py && git commit -m "feat(tokens): 新增 spec_lock 唯一解析器与栅格闭合自检"`

---

## Task 3 — 真相源模板落地，切断"工程实例兼任 SSOT"

**背景（spec §4.1 实测）**：`md_to_pptx.py:108-111` 的逻辑是工程缺 `spec_lock.md` 时**从 `projects/agentflow-os-launch/spec_lock.md` 复制一份**。真相源由某个工程实例兼任，任何人改那个实例，之后新建的每个工程都静默继承，且没有 diff 面可审。

schema 兼容性已实测（spec §4.1 表）：交付门禁 `svg_quality_checker --stage final` **不校验 spec_lock schema**（四变体输出一字不差），所以新增 `## grid` 节不会拦导出；`poster` 落 `typography` 双把尺子都干净。vendor 的严格 `validate_markdown_text` 会拒绝未知节，但**该命令不在本管线内，本期不去顺手严格化它**（spec §9 明确列为不做）。

**写法红线**：新增行的注释一律**单独占行**，不写行内注释（`qa_layout.load_ramp()` 自解析 `## typography`，且 workflow.md 已记档"行内注释会报错"的坑）。`workflow_full` 里 `tertiary_text` 那行的行内注释属历史例外，**本期不动它**。

**Files**: 新增 `patterns/spec_lock.template.md`；改 `projects/*/spec_lock.md`（2 份副本）、`scripts/md_to_pptx.py`、`scripts/plan_contract.py`、新增 `scripts/test_plan_contract_sections.py`。

**Steps**：
1. 找母本：`ls patterns/ 2>/dev/null; git ls-files | grep -i spec_lock`。以 `projects/*/spec_lock.md` 中最完整的一份（`workflow_full` 母本在取证副本 `/tmp/pptplan/spec_lock_workflow_full.md`；若 3TB 上有更完整的一份，以 3TB 上为准，并在报告写明你用了哪份）。
2. `mkdir -p patterns && cp <母本> patterns/spec_lock.template.md`，然后对**模板**做三处 Edit：
   - **Edit A**：模板里凡是工程专属值（工程名、受众、时长、场合一类 `## communication` 节下的值）改成占位口径 `<待填>`，并单独加一行注释 `# 模板：工程新建时由人工/LLM 填入，不参与栅格计算`。
   - **Edit B**：`## typography` 节末尾追加两行（注释独立占行）：
     ```
     # 封面 P1 纯排版标题档位，不参与正文阶梯
     - poster: 160
     ```
   - **Edit C**：在 `## icons` 节**之前**插入整节：
     ```
     ## grid
     # 版心/栅格真相源。margin 取 L-01（画布宽 6%）；自检 76+12×72+11×24+76==1280
     - margin: 76
     - cols: 12
     - col: 72
     - gut: 24
     - bands: 4 8 12 16 24 32 48 64
     - baseline_step: 8
     ```
3. 两份工程副本同步补齐 Edit B + Edit C（**不做 Edit A**，副本保留各自工程专属值）。
4. `spec_tokens.load('projects/agentflow-os-launch/spec_lock.md')` 现在必须**不抛**。这是 Task 2 那个"预期抛"用例的反证。
5. 改 `md_to_pptx.py:108-111`：取样路径从工程实例改为 `patterns/spec_lock.template.md`，且缺模板即硬失败：
   ```python
   tmpl = ROOT / "patterns" / "spec_lock.template.md"
   if not tmpl.exists():
       raise SystemExit(f"缺真相源模板 {tmpl} —— 拒绝静默回退到工程实例（真相源缺口，见 spec §4.1）")
   shutil.copy(tmpl, project_dir / "spec_lock.md")
   ```
   保留原有 `shutil` 导入（若原代码用的不是 shutil，按现场实际写法改，只换路径 + 加缺模板硬失败）。
6. `plan_contract.py:72`：`REQUIRED_SPEC_SECTIONS = ["## canvas", "## colors", "## typography", "## grid"]`。
7. 在 `plan_contract.py` 新增：
   ```python
   def check_spec_parity(project: Path, template: Path) -> list[str]:
       """工程 spec_lock 与模板的节名集合对账：缺节 = blocking，多节 = 只提示。"""
       try:
           import spec_tokens as ST
       except ImportError:
           sys.path.insert(0, str(Path(__file__).resolve().parent))
           import spec_tokens as ST
       want, got = ST.section_names(template.read_text(encoding="utf-8")), \
                   ST.section_names((project / "spec_lock.md").read_text(encoding="utf-8"))
       want, got = {w.lstrip("# ").strip() for w in want}, {g.strip() for g in got}
       missing = sorted(want - got)
       extra = sorted(got - want)
       out = [f"[blocking] 缺节 {m}（模板有、工程无）" for m in missing]
       out += [f"[提示] 工程多出节 {e}" for e in extra]
       return out
   ```
   并把它接进 `build_plan()` 的既有报错收集处（返回非空 blocking 行时按现有 blocking 处理方式上报）。
8. `scripts/test_plan_contract_sections.py`：5 项 —— (a) 模板与 2 份副本节集合对账缺节为 0；(b) 故意删一份副本的 `## grid` → 出 1 条 blocking；(c) 故意多 `## foo` → 只出提示不出 blocking；(d) `REQUIRED_SPEC_SECTIONS` 含 `## grid`；(e) `md_to_pptx.py` 源码里不再出现 `agentflow-os-launch/spec_lock.md` 的复制路径（用 `grep` 断言）。

**Verify**：
```bash
"$PY" scripts/test_plan_contract_sections.py            # 全绿
"$PY" -c "import sys;sys.path.insert(0,'scripts');import spec_tokens as s;s.load_project('projects/agentflow-os-launch')"   # 不抛
grep -n 'agentflow-os-launch/spec_lock' scripts/md_to_pptx.py   # 必须为空
```
**Commit**：`git add patterns/spec_lock.template.md projects/agentflow-os-launch/spec_lock.md scripts/md_to_pptx.py scripts/plan_contract.py scripts/test_plan_contract_sections.py <另一份工程副本> && git commit -m "feat(ssot): spec_lock 模板化，切断工程实例兼任真相源并加节集合对账"`
（注意：`git add projects/.../spec_lock.md` 只加 spec_lock，**不要 `git add projects/`**，那会带上两个 cards SVG。）

---

## Task 4 — 版心 60→76 全链统一 + 回归对账

**Files**: `scripts/qa_layout.py`、`scripts/pages_to_svg.py`、`scripts/qa_score.py`；留档目录 `spikes/2026-10-10-margin-regression/`。

**Steps**：
1. 先取"改前快照"（**不能用 HEAD**，见 Task 1）：
   ```bash
   REG=spikes/2026-10-10-margin-regression; mkdir -p "$REG/old"
   cp scripts/qa_layout.py scripts/pages_to_svg.py "$REG/old/"
   grep -q 'MARGIN = 60' "$REG/old/qa_layout.py" || { echo "快照无效：取到的已是改后版"; exit 1; }
   ```
2. 改 `qa_layout.py`：
   - `:36` → `DEFAULT_MARGIN = 76` 且 `MARGIN = DEFAULT_MARGIN`（保留模块级 `MARGIN` 名，历史调用方与 `regression_qa.sh` 会读它）。
   - `check_overflow(root)` → `check_overflow(root, margin=MARGIN)`，函数体内所有 `MARGIN` 引用改用参数。
   - `main()` 里在遍历 SVG 之前：
     ```python
     try:
         import spec_tokens as ST
         tok = ST.load(os.path.join(svg_project_dir, "spec_lock.md"))
         MARGIN = tok.margin
         DEFAULT_RAMP = set(tok.ramp)
         print(f"[tokens] margin={tok.margin} ramp={sorted(tok.ramp)}")
     except Exception as e:                       # 缺 spec_lock / 缺节：兜底并**显式警告**
         print(f"[tokens][警告] 未读到 spec_lock，用兜底 margin={MARGIN} ramp={sorted(DEFAULT_RAMP)}：{e}")
     ```
     `DEFAULT_RAMP` 兜底值必须含 56 与 160。
   - **不要改** `:37 WCAG_MIN = 4.5`（分档在 Task 5 通过 `wcag_need` 实现，不动全局下限）。
3. 改 `pages_to_svg.py:26-27`：`MARGIN = 76`；`RAMP = {11, 13, 16, 20, 24, 32, 44, 56, 96, 160}`（注释标注"兜底，正常从 spec_lock 读"）。`main()` 里从 `args.pages.parent / "spec_lock.md"` 读 `spec_tokens`，覆盖 `MARGIN/RAMP`，读不到打同样格式的警告行。
4. 改 `qa_score.py`：`check_overflow(root)` 调用处传入 margin（`qa_score` 现在已在 `load_ramp(spec_lock)`，同一处一并 `spec_tokens.load_project` 取 margin；解析失败时沿用 `qa_layout` 的兜底 76 并在 evidence 里打印兜底警告）。

**回归对账（本 Task 的交付核心，按"修正 1"口径）**：
```bash
PROJ=projects/<历史 18 页工程名>          # 用 git ls-files 自己确认，报告里写明是哪个
OLD=$REG/pre_change; NEW=$REG/post_change; mkdir -p "$OLD" "$NEW"
# 改后（现工作区）
"$PY" scripts/qa_layout.py "$PROJ/pages" "$PROJ/render" > "$NEW/qa_layout.txt" 2>&1 || true
# 改前（快照，注意快照目录要能 import spec_tokens：把 scripts 加入 PYTHONPATH）
PYTHONPATH=scripts "$PY" - "$REG/old/qa_layout.py" "$PROJ" <<'PY' > "$OLD/qa_layout.txt" 2>&1 || true
# 用 runpy 跑快照文件；若快照的 DEFAULT_RAMP 缺 56 导致命中更多，这正是"改前"的真实基线，保留
PY
diff -u "$OLD/qa_layout.txt" "$NEW/qa_layout.txt" > "$REG/qa_layout.diff" || true
```
**逐页必须都跑到**：`grep -c '^=== ' "$NEW/qa_layout.txt"` 应为 18（历史页数）。少于 18 说明有页崩，视为闸门不过。

**判据（写进 `$REG/REPORT.md`，逐条给数字）**：
1. typescale / backdrop / dup_images / collisions / contrast 五个维度：改后命中数 ≤ 改前，否则列出具体页与原因并**停下**。
2. `[溢出]`：允许新增。每一处新增逐条列 `页号 | 元素文本 | 改前 x1 | 改后 x1 | 是否仅因 margin`，非 margin 归因的新增 = 闸门不过。
3. 新增维度 `[尺度]/[网格]` 此 Task 尚未实现（Task 5），本步不涉及。
4. vendor 门禁复跑一次并按"证据分级"第 6 条的正确口径计数，输出存 `$REG/vendor_final.txt`。
5. 页数影响预告：版心收窄可能让 `needs_split` 拆出更多页 —— 记录改前后页数，写进报告（这是 spec §9 已预告的代价，不是缺陷）。

**Verify**：`spikes/2026-10-10-margin-regression/REPORT.md` 存在且五个维度对账表齐全；`"$PY" scripts/test_qa_layout_fixes.py` 仍全绿（签名未破）。

**Verify**：`spikes/2026-10-10-margin-regression/REPORT.md` 存在且五个维度对账表齐全；`"$PY" scripts/test_qa_layout_fixes.py` 仍全绿（签名未破）。

**Commit**：`git add scripts/qa_layout.py scripts/pages_to_svg.py scripts/qa_score.py spikes/2026-10-10-margin-regression && git commit -m "fix(layout): 版心常量收敛到 spec_tokens 并统一为 76，附回归对账"`

---

## Task 5 — 尺度门禁化 + WCAG 分档 + qa_score 权重配平
**目标（spec §4.4 / §6.2）**：把"高级感"翻译成可测代理。`[尺度]` blocking（这是"填字感"的根因），`[网格]` warn。**留白率不进门禁** —— 实测包围盒估法系统性低估（数据表页 14.8%、机制页 24.3%，肉眼并不挤），只作趋势打印。这是本轮的诚实结论，不要为了凑数字把它写成硬判据。

**Files**: `scripts/qa_layout.py`、`scripts/qa_score.py`、新增 `scripts/test_qa_scale_and_contrast.py`。

**Steps** — 在 `qa_layout.py` 新增（放在 `check_contrast` 之前）：

```python
DECOR = set("✓✗!+·—→·※◆■●○①②③④⑤⑥⑦⑧⑨⑩")   # 单字符装饰符号

def _weight_of(t) -> int:
    """取 <text> 的有效字重：属性优先，其次 style:font-weight，再继承父 g。默认 400。"""
    w = t.get("font-weight")
    if w is None:
        m = re.search(r"font-weight\s*:\s*(\d+)", t.get("style", "") or "")
        w = m.group(1) if m else None
    return int(w) if w and str(w).isdigit() else 400

def wcag_need(size: float, weight: int, text: str) -> float:
    """对比度门槛分档：正文 4.5；大字 3.0（size>=32，或 size>=24 且 weight>=700）；
    单字符装饰符号按非文本图形 3.0，不豁免。"""
    body = "".join(ch for ch in text if ch.strip())
    if len(body) == 1:
        return 3.0
    if size >= 32 or (size >= 24 and weight >= 700):
        return 3.0
    return WCAG_MIN                    # 4.5

def check_scale(root, ramp: set) -> list[str]:
    """同屏相邻层级必须跨 >=2 档且尺度差 >=2.5x；一级标题字号同屏只能出现一次。"""
    sizes: dict[int, int] = {}
    for t, anc in _iter_with_parents(root):
        if t.tag != NS + "text":
            continue
        sp = text_span(t, anc)
        if sp is None:
            continue
        sizes[int(round(sp[3]))] = sizes.get(int(round(sp[3])), 0) + 1
    used = {s: c for s, c in sizes.items() if c > 0}
    bad = []
    ordered = sorted(used)
    big = [s for s in ordered if s >= 44]
    for a, b in zip(ordered, ordered[1:]):
        if a in big or b in big:          # 只约束"相邻层级"，同属大字号之间不算
            idx_a = sorted(big).index(a); idx_b = sorted(big).index(b)
            if idx_b - idx_a < 2 and b / a < 2.5:
                bad.append(f"{a}px→{b}px 未跨 2 档且尺度差 {b/a:.2f}<2.5")
        else:
            if sorted(ramp).index(b) - sorted(ramp).index(a) < 2 and b / a < 2.5:
                bad.append(f"{a}px→{b}px 未跨 2 档且尺度差 {b/a:.2f}<2.5")
    n_l1 = sum(c for s, c in used.items() if s >= 44)
    if n_l1 > 1:
        bad.append(f"一级标题字号同屏出现 {n_l1} 次（应仅 1 处断言）")
    return bad

def check_grid_step(root, step: int = 8, tol: float = 1.0) -> list[str]:
    """元素 y 坐标应落 step 步进（warn 用，不 blocking）。"""
    off = []
    for t, anc in _iter_with_parents(root):
        if t.tag not in (NS + "text", NS + "rect", NS + "line"):
            continue
        raw = t.get("y") if t.tag == NS + "text" else t.get("y", t.get("y1"))
        if raw is None:
            continue
        try:
            y = float(re.match(r"[-\d.]+", str(raw)).group(0))
        except Exception:
            continue
        if abs(y / step - round(y / step)) * step > tol:
            off.append(f"{t.tag.split('}')[-1]} y={y:g}")
    return off
```
上面 `check_scale` 的档位比较要处理"字号不在 ramp 上"的情况：`sorted(ramp).index(x)` 会 `ValueError`。**必须**先过滤 `ordered = [s for s in ordered if s in ramp]`（越出阶梯已由 `check_typescale` 报，本项不重复报），并在函数开头注明这条口径。这段以"能跑、口径写在注释里"为准，实现时若与实际 `_iter_with_parents/text_span` 签名不符，按现场签名调整并在报告中写明调整点。

`check_contrast` 末行改为（**函数签名保持 `(img, root)` 两参不变**）：
```python
        rows.append((ratio, txt, size, wcag_need(size, _weight_of(t), txt)))
```
所有消费点改为向后兼容取门槛：
```python
need = r[3] if len(r) > 3 else WCAG_MIN
fails = [r for r in rows if r[0] < need]
```
`qa_layout.main()` 在既有输出行后加两行：
```python
sv = check_scale(root, DEFAULT_RAMP)
for s in sv: print(f"    [尺度] {s}")
bad += sv                                  # blocking：计入本页失败
gt = check_grid_step(root, step=tok_step)  # tok_step 来自 spec_tokens.baseline_step，兜底 8
if gt: print(f"    [网格][warn] {len(gt)} 处未落 {tok_step}px 步进：" + "; ".join(gt[:4]))
                                                       # 不计入 bad
```
留白率：只 `print` 趋势，不设阈值、不计入 bad。

**Steps** — `qa_score.py` 权重**单一配平**（和必须仍为 100）：
```python
WEIGHTS = {"typescale": 14, "hierarchy": 12, "backdrop": 12, "dup_images": 12,
           "overflow": 18, "collisions": 8, "contrast": 24}   # 14+12+12+12+18+8+24 = 98 → 校验
```
**上面这行是错的**（和为 98），正确配平取 spec §6.2 已定值：**typescale 20→14、hierarchy(新) 12、backdrop 15→12、dup_images 15→12、overflow 20→18、collisions 10→8、contrast 20→24 → 14+12+12+12+18+8+24 = 100**。执行时在 `test_qa_scale_and_contrast.py` 里加一条硬断言 `sum(WEIGHTS.values()) == 100`，防止后续再加维度时漏减。阈值 80 不变。
新增打分项：
```python
    sv = check_scale(root, ramp)
    checks.append({"name": "hierarchy", "weight": WEIGHTS["hierarchy"],
                   "score": clamp(100 - 34 * len(sv)),
                   "evidence": sv[:6] or ["层级跨档合规"]})
```

**Steps** — `scripts/test_qa_scale_and_contrast.py` 12 项（合成 SVG 字符串 + 内存 PIL 图，不依赖工程）：
1. `sum(qa_score.WEIGHTS.values()) == 100`。
2. `wcag_need(16, 400, "正文") == 4.5`。
3. `wcag_need(44, 600, "断言标题") == 3.0`。
4. `wcag_need(24, 700, "强调") == 3.0`；`wcag_need(24, 400, "强调") == 4.5`。
5. `wcag_need(13, 400, "✓") == 3.0`（单字符装饰，不豁免）。
6. 44→20→16 三档同屏 → `check_scale` 返回空。
7. 44→32→24 同屏 → `check_scale` 非空，消息含 "未跨 2 档"。
8. 两个 44px 文本块同屏 → 消息含 "一级标题"。
9. `check_scale` 对"字号越出 ramp"的文本不报（越档由 typescale 负责，不双报）。
10. `check_grid_step` 对 `y=168` 不报、对 `y=171` 报（step=8, tol=1）。
11. `check_contrast(img, root)` 返回元组长度 4，且 `r[0]` 仍是 ratio、`r[1]` 仍是文本（**签名/前两项兼容**）。
12. 暗底亮字大标题在 3:1~4.5:1 之间 → 旧口径 fail、新口径 pass（证明分档真的生效）。

**Steps** — 历史 18 页新维度命中面实测（**只记录，不放宽、不回填**）：
```bash
"$PY" scripts/qa_layout.py "$PROJ/pages" "$PROJ/render" | grep -E '\[尺度\]|\[网格\]' \
  > "$REG/new_dims_hits.txt" 2>&1
wc -l "$REG/new_dims_hits.txt"
```
把命中页数、每类命中数写进 `$REG/REPORT.md` 的新章节，并明确一句："历史页大量命中是预期（它们是在旧规则下做的），本期不改历史页。" 若 `[尺度]` 导致历史页在 `qa_score` 下大面积跌破阈值 80，**不要动阈值**，在报告里列出哪些页跌破、跌破多少，作为"需要重做设计"的证据 —— 这正是本期要解决的问题本身。

**Verify**：`"$PY" scripts/test_qa_scale_and_contrast.py` 12 绿；`"$PY" scripts/test_qa_layout_fixes.py` 仍全绿；`"$PY" scripts/qa_score.py "$PROJ/pages" "$PROJ/render" --threshold 80` 能跑完并打印逐页分数（退出码非 0 不算失败，只要报告写清哪些页需复核）。

**Commit**：`git add scripts/qa_layout.py scripts/qa_score.py scripts/test_qa_scale_and_contrast.py spikes/2026-10-10-margin-regression/new_dims_hits.txt && git commit -m "feat(qa): 尺度/网格新维度与 WCAG 分档，qa_score 权重单一配平"`

---

## 批 1 闸门 — 必须全部满足才进批 2

1. `test_spec_tokens.py` 14 绿、`test_plan_contract_sections.py` 5 绿、`test_qa_scale_and_contrast.py` 12 绿、`test_qa_layout_fixes.py` 仍绿。
2. `spikes/2026-10-10-margin-regression/REPORT.md` 里五维对账表齐全、`[溢出]` 新增逐条归因齐全、新维度命中面记录齐全。
3. vendor `svg_quality_checker --stage final` 对历史工程复跑，按正确计数口径 `introduced` 为 0（即本期改动没新引入 vendor 侧错误）。
不满足 → 停止，写失败报告到 `spikes/2026-10-10-margin-regression/FAILURE.md`，不进入 Task 6。

---

## Task 6 — `scripts/plan_narrative.py`（N1 结构器，不写文案）

**职责边界（spec 核心裁决）**：N1 只做**结构**——把 markdown 切成节、给每节一个候选 role、把已有句子归位成 assertion/evidence/so_what 的**骨架**，并给每个字段带上**原文行号回指**。文案本身由 N2 门禁 + 人/LLM 复核产出，N1 不得"创作"。

**Files**: 新增 `scripts/plan_narrative.py`、`scripts/test_plan_narrative.py`。

**Steps** — 关键实现（其余按此风格补全）：

```python
#!/usr/bin/env python3
"""N1 叙事结构器：markdown -> narrative.json 骨架。只筛不写。"""
ROLES = ("cover", "section", "claim", "data", "mechanism", "teaching", "closing")

REQUIRED = {                     # 修正 2：逐 role 必填集（不是"每页 7 字段齐全"）
    "cover":     ["assertion"],
    "section":   ["assertion"],
    "claim":     ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "data":      ["assertion", "evidence", "so_what", "image_intent"],
    "mechanism": ["assertion", "evidence", "so_what", "visual_protagonist", "image_intent"],
    "teaching":  ["assertion", "evidence", "so_what", "image_intent"],
    "closing":   ["assertion", "so_what"],
}

class RolePlanError(Exception):
    pass

H1_RE = re.compile(r"^#\s+(.+)$", re.M)
H2_RE = re.compile(r"^##\s+(.+)$", re.M)
QUOTE_RE = re.compile(r"^>\s*(.+)$", re.M)
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")

def split_sections(md_text: str) -> list[dict]:
    """按 ## 切节，每节带**原文起始行号**（回指用），不改写任何文字。"""
    lines = md_text.split("\n")
    hits = [(i, H2_RE.match(l)) for i, l in enumerate(lines) if H2_RE.match(l)]
    out = []
    for k, (ln, m) in enumerate(hits):
        end = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
        out.append({"heading": m.group(1).strip(), "start_line": ln + 1,
                    "lines": lines[ln + 1:end]})
    return out

def numbers_in(text: str, base_line: int) -> list[str]:
    """句子若含数字，返回带行号的引用串列表（evidence 的 baseline 候选来源）。"""
    return [f"a.md#L{base_line + i}" for i, l in enumerate(text.split("\n"))
            if re.search(r"\d", l)]

def blank_page(i: int, role: str) -> dict:
    p = {"index": i, "role": role, "assertion": "", "evidence": [], "so_what": "",
         "visual_protagonist": "", "image_intent": "none", "scope_note": ""}
    p["_todo"] = [k for k in REQUIRED[role]
                  if not p.get(k) and k != "evidence"]
    return p

def build(md_path: Path, role_plan: dict | None = None) -> dict:
    """role_plan: {section_heading: role} —— 由人/LLM 给的意图标注；缺省时按启发式给候选并标 _todo。"""
    raw = md_path.read_text(encoding="utf-8")
    m1 = H1_RE.search(raw); title = m1.group(1).strip() if m1 else md_path.stem
    mq = QUOTE_RE.search(raw); sub = mq.group(1).strip() if mq else ""
    pages = []
    cover = blank_page(0, "cover")
    cover["assertion"] = title
    cover["scope_note"] = sub
    pages.append(cover)
    for k, sec in enumerate(split_sections(raw), start=1):
        role = (role_plan or {}).get(sec["heading"]) or guess_role(sec)
        if role not in ROLES:
            raise RolePlanError(f"非法 role: {role}")
        pg = blank_page(k, role)
        pg["_src"] = f"{md_path.name}#L{sec['start_line']}"
        cands = [l.strip() for l in sec["lines"] if BULLET_RE.match(l.strip()) or l.strip().startswith("|")]
        for j, c in enumerate(cands):
            pg["evidence"].append({"kind": kind_of(c), "text": strip_md(c),
                                   "baseline": None,
                                   "source": f"{md_path.name}#L{sec['start_line'] + 1 + j}"})
        if role == "claim" and not pg["evidence"]:
            pg["_todo"].append("evidence")
        pages.append(pg)
    return {"source": md_path.name, "governing_thought": "", "audience": "",
            "duration_min": None, "pages": pages}
```
`guess_role` 的启发式（必须写死在代码里并在注释标注"仅候选，N2 会校验，人可读 `_todo` 覆盖"）：标题含"表/数据/对比" → `data`；含"流程/机制/链路/步骤" → `mechanism`；含"错/对/容易/注意/对照" → `teaching`；含"总结/下一步/行动/落地" → `closing`；否则 `claim`。`kind_of`：以 `|` 开头为 `row`，含数字为 `number`，含"截图/图/照片"为 `image`，否则 `text`。

CLI：`--md（必需） --out（必需） --role-plan（可选 json：{"节标题": "role"}） --governing --audience --duration-min`；写出 `json.dumps(..., ensure_ascii=False, indent=2)`；末尾打印逐页 `_todo` 汇总行（`页 03 [claim] 缺: so_what, visual_protagonist`）。

**Steps** — `test_plan_narrative.py` 11 项（用 `tempfile` 合成 md）：
1. 三节 md → 4 页（封面 + 3）。
2. 封面 assertion == H1 文本，`scope_note` == 首个 `>` 引用。
3. 每页 `role ∈ ROLES`。
4. `--role-plan` 覆盖生效（给了 `data` 就不再走启发式）。
5. 非法 role 名 → `RolePlanError`。
6. `evidence.source` 形如 `x.md#L<n>` 且 n 指向的原文行确实含该文本子串（**回指真实性用例，最关键**）。
7. `image_intent` 默认 `"none"`。
8. 表格行进 evidence 且 kind=="row"，**不被条数截断**。
9. 无 bullet 的节：claim role → `_todo` 含 "evidence"。
10. `_todo` 只列该 role 的必填缺项（closing 不要求 evidence）。
11. 输出 JSON 可被 `json.loads` 回读且页数一致。

**Verify**：`"$PY" scripts/test_plan_narrative.py` 全绿；再对一份真实历史 md 跑一次 `--out /tmp/nar_probe.json`，把逐页 `_todo` 汇总存进 `spikes/2026-10-10-narrative-backfill/todo_from_history.txt`（Task 7 的探针共用该目录）。

**Commit**：`git add scripts/plan_narrative.py scripts/test_plan_narrative.py && git commit -m "feat(narrative): N1 结构器产出带行号回指的叙事骨架"`

---

## Task 7 — `scripts/check_narrative.py`（N2 写作门禁，W-xx 机械化）

**规则来源**：`skills/ppt-narrative-writing/` 的 W-xx 编号（取证副本 `/tmp/pptplan/skill_ppt-narrative-writing.md`）。**只把可机械判定的升级为 blocking**，判不准的进"需人读"清单，绝不让脚本假装看懂中文。

**Files**: 新增 `scripts/check_narrative.py`、`scripts/test_check_narrative.py`、`spikes/2026-10-10-narrative-backfill/probe.py`。

**Steps** — 覆盖的 W-xx（逐条实现，每条一个纯函数 + 一条测试）：

| 编号 | 机械判据 | 级别 |
|---|---|---|
| W-01 | assertion 以 `NOUN_TAIL_RE` 结尾（名词短语当标题） | blocking（启发式，见下方警示） |
| W-02 | assertion 命中 `TWO_POINT_RE`（一页两个论点） | blocking |
| W-05 | assertion 含 `FLUFF` 十词之一 | blocking |
| W-06 | assertion 长度 > 40 汉字或 < 6 | blocking |
| W-07 | evidence 为空但 role 要求 evidence | blocking |
| W-12 | `kind=="number"` 的 evidence 缺 `baseline` | blocking |
| W-18 | evidence 文本与原文照抄率 > 阈值（`copy_ratio`） | blocking |
| W-19 | evidence 缺 `source` 或 `source` 回指解析失败 | blocking |
| W-24 | `so_what` 为空或含 `BASELINE_WORDS` 之一（把所以然写成陈述） | blocking |
| W-27 | `visual_protagonist` 为空但 `image_intent != "none"` | blocking |
| W-28 | `image_intent` 不在 `{none, background, panel, hero}` | blocking |
| W-29 | `scope_note` 缺失（封面/closing 外） | warn |

```python
NOUN_TAIL_RE = re.compile(r"(背景|概况|分析|介绍|说明|总结|举措|现状|概览)$")
TWO_POINT_RE = re.compile(r"(以及|，且|，并|、| 和 )")
FLUFF = ("赋能", "抓手", "闭环", "颗粒度", "底层逻辑", "心智", "打法", "势能", "对齐", "拉通")
BASELINE_WORDS = ("可能", "大概", "左右", "若干", "一定", "适当")

def resolve_source(source: str, base_dir: Path) -> tuple[Path, int] | None:
    """'a.md#L12' -> (路径, 行号)；解析不了返回 None。Task 8 复用同一出口。"""
    if "#" not in source:
        return None
    f, frag = source.split("#", 1)
    m = re.match(r"L(\d+)", frag)
    if not m:
        return None
    p = (base_dir / f) if f else None
    if p is None or not p.exists():
        return None
    return p, int(m.group(1))

def copy_ratio(text: str, src_text: str, n: int = 5) -> float:
    """按 n 元字符 shingle 估计与原文的照抄比例（中文按字符滑窗，不分词）。"""
    t = re.sub(r"\s", "", text); s = re.sub(r"\s", "", src_text)
    if len(t) < n or not s:
        return 1.0 if t and t in s else 0.0
    sh = [t[i:i + n] for i in range(len(t) - n + 1)]
    return sum(1 for g in sh if g in s) / len(sh)
```
`check(plan, src_text, base_dir) -> (blocking: list[str], human_read: list[str])`，每条消息带 `[W-xx]` 前缀与页号，便于按前缀统计。
**明确写进 `human_read`（脚本判不了，别假装能判）**：W-03（论点是否真的成立）、W-04（证据是否充分支持论点）、W-09（so_what 是否是"决策"而非"复述"）。
**W-01/W-06 的中文判定是启发式**（`TWO_POINT_RE` 里的 `、` 会误伤枚举式标题，`FLUFF` 词表按本仓约定），PASS 行必须打印：
```
PASS(部分)：只代表可机械判定的 W-01/02/05/06/07/12/18/19/24/27/28 全过，不代表写作合格。
```
照抄率阈值 40% 是**本仓自定（D 级）**，写死为常量 `COPY_MAX = 0.40` 并在旁边注释标明非外部标准。

**Steps** — `test_check_narrative.py` 17 项：上表 12 条各一条正/反用例（选 12 条最关键的：W-01/W-02/W-05/W-06/W-12/W-18/W-19/W-24/W-27/W-28 各 1 反例 + W-07/W-29 各 1 反例），外加 5 条：
13. 全合规 plan → blocking 为空。
14. `resolve_source` 对 `a.md#L3` 命中真实行、对 `a.md#X3` / `missing.md#L3` 返回 None。
15. `copy_ratio` 对完全照抄返回 1.0、对全改写返回 < 0.2。
16. `human_read` 恰含 W-03/W-04/W-09 三条（证明"已知盲区"被显式登记，不是漏实现）。
17. 输出消息全部带 `[W-` 前缀（统计口径依赖它）。

**Steps** — 批 2 闸门正式探针 `spikes/2026-10-10-narrative-backfill/probe.py`：
把历史 18 页工程的 `pages.json` 逐页**反向构造**成 claim 页 plan（assertion 取该页标题、evidence 取 bullets、source 指向原 md），跑 `check()`，按 `[W-xx]` 前缀统计每条命中数，输出到同目录 `probe_report.md`。
判据：探针必须**能接住**（即历史页大面积命中是预期的，说明门禁有效）；若 18 页几乎全 PASS，说明门禁形同虚设，**报告并停下**，不要为了让历史页通过而放宽规则。

**Verify**：`"$PY" scripts/test_check_narrative.py` 17 绿；`"$PY" spikes/2026-10-10-narrative-backfill/probe.py` 跑完且 `probe_report.md` 有逐条 W-xx 命中表。

**Commit**：`git add scripts/check_narrative.py scripts/test_check_narrative.py spikes/2026-10-10-narrative-backfill && git commit -m "feat(narrative): N2 写作门禁 W-xx 机械化并登记不可判盲区"`

---

## Task 8 — `plan_contract` 加叙事落点校验（向后兼容，不新增拦历史页）

**Files**: `scripts/plan_contract.py`、`scripts/test_plan_contract_sections.py`（沿用 Task 3 那个文件，追加 3 个用例）。

**Steps** — 新增：
```python
def check_narrative_landing(project: Path, svg_dir: Path) -> list[str]:
    """narrative.json 的每条断言必须真的落在对应 SVG 上。缺 narrative.json 只算旧工程，不 blocking。"""
    nar = project / "narrative.json"
    if not nar.exists():
        print("[兼容] 无 narrative.json，跳过落点校验（历史工程路径不变）")
        return []
    plan = json.loads(nar.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_narrative import resolve_source
    out = []
    base_dir = project
    for pg in plan.get("pages", []):
        idx, role = pg["index"], pg.get("role", "")
        if role not in ROLES:
            out.append(f"[blocking] 页 {idx:02d} role 非法: {role}"); continue
        hit = sorted(svg_dir.glob(f"{idx:02d}_{role}.svg")) or \
              sorted(svg_dir.glob(f"{idx:02d}_*.svg"))
        if not hit:
            out.append(f"[blocking] 页 {idx:02d} 无对应 SVG"); continue
        text = _flat(hit[0].read_text(encoding="utf-8"))
        for f in ("assertion", "so_what"):
            v = (pg.get(f) or "").strip()
            if v and _flat(v)[:8] not in text:
                out.append(f"[blocking] 页 {idx:02d} {f} 未落进 {hit[0].name}: {v[:20]}")
        for ev in pg.get("evidence", []):
            if not resolve_source(ev.get("source", ""), base_dir):
                out.append(f"[blocking] 页 {idx:02d} evidence 回指解析失败: {ev.get('source')}")
    return out
```
接进 `build_plan()` 的报错收集处。`_flat` 是 `plan_contract.py` 既有函数（现用于 `BULLET_PREFIX=8` 前缀比对），**复用它，不要新写一个归一化**；`_flat(v)[:8]` 的 8 与既有 `BULLET_PREFIX` 对齐 —— 若 `_flat` 实际签名不接受 SVG 全文，就改用既有等价路径并在报告写明调整。

**Steps** — 在 `test_plan_contract_sections.py` 追加 3 项（全部 `tempfile` 合成工程）：
1. 无 narrative.json → 返回 `[]` 且打印 `[兼容]`（旧工程不被新校验拦）。
2. narrative 有断言、SVG 里确实含该断言前 8 字 → `[]`。
3. 断言在 SVG 里不存在 → 出 1 条 blocking，消息含页号。

**Verify**：`"$PY" scripts/test_plan_contract_sections.py` 8 绿；对历史工程跑 `build_plan()` 结果与改动前**逐字一致**（因为无 narrative.json 走 `[兼容]` 分支）—— 存 `git stash` 前的输出做对比，用 `diff`，比对通过后 `git stash pop`。

**Commit**：`git add scripts/plan_contract.py scripts/test_plan_contract_sections.py && git commit -m "feat(contract): 叙事落点校验并入 plan_contract，缺 narrative 走兼容分支"`

---

## Task 9 — `md_to_pages.py` 接 `--narrative`（旧字段只增不减）

**Files**: `scripts/md_to_pages.py`。

**Steps**：
1. `md_to_pages()` 增加参数 `narrative: dict | None = None`，CLI 增加 `--narrative <path>`（json）。
2. 新增映射函数：
```python
def _project_from_narrative(plan: dict, nar: dict) -> dict:
    """把 narrative.json 的 role 页转成现行 pages 结构。旧字段值必须与不传 --narrative 时一致。"""
    try:
        from layout_recipes import ROLE_TO_RECIPE
    except Exception:                       # 批 3 之前 layout_recipes 还不存在
        ROLE_TO_RECIPE = {"cover": "cover_p1", "section": "section_anchor",
                          "claim": "assertion_evidence", "data": "three_line_table",
                          "mechanism": "mechanism_flow", "teaching": "teaching_pair",
                          "closing": "action_list"}
    pages = []
    for i, pg in enumerate(nar["pages"]):
        role = pg["role"]; lay = ROLE_TO_RECIPE.get(role, "assertion_evidence")
        bullets = [e["text"] for e in pg.get("evidence", [])]
        if pg.get("so_what"):
            bullets.append(pg["so_what"])
        page = {"index": i, "title": pg.get("assertion") or pg.get("scope_note") or "",
                "bullets": bullets, "layout": lay,
                "needs_review": pg.get("_todo", []),
                "role": role, "assertion": pg.get("assertion", ""),
                "so_what": pg.get("so_what", ""), "evidence": pg.get("evidence", []),
                "image_intent": pg.get("image_intent", "none")}
        # 关键：image_intent 为 none 时**清空** image_prompt，切断"每页自动配氛围图"
        page["image_prompt"] = "" if page["image_intent"] == "none" else page_image_prompt(
            page["title"], lay, bullets)
        pages.append(page)
    return {"source": plan["source"], "title": plan["title"],
            "narrative_style": nar.get("governing_thought") or plan.get("narrative_style", ""),
            "closing_hint": plan.get("closing_hint", "收束"), "pages": pages}
```
3. 现状问题（spec §5.1）：`pages_to_svg.py` / `md_to_pages.py` 对每页无条件生成 `image_prompt`（实测 `workflow_full/pages.json` 18 页每页都挂着 "deep graphite gradient backdrop, rim lighting…"）。**本 Task 先把 `image_intent=="none"` 的页的 prompt 清空**，生图路由本身在 Task 14。

**兼容性实测（硬判据，写进测试）**：对历史工程不带 `--narrative` 跑一次，输出 `pages.json` 存 `/tmp/p_nar_off.json`；带 `--narrative` 指向反向构造的 plan 再跑一次存 `/tmp/p_nar_on.json`。断言：
- 两版的每页 `index/title/bullets/layout` **逐字相同**（不带 narrative 时）；
- 带 narrative 时旧字段仍存在、只**新增** `role/assertion/so_what/evidence/image_intent`，无字段消失：
  ```python
  assert set(old.keys()) <= set(new.keys())
  ```
把这两条断言放进 `scripts/test_plan_narrative.py`（Task 6 那个文件）作为第 12、13 项（测试数从 11 增到 13，后续 Task 不再改这个文件）。

**Verify**：`"$PY" scripts/md_to_pages.py <历史md> --out /tmp/pages_check.json` 不带 narrative 时输出与改动前 `diff` 为空（先 `cp` 存旧输出做对比）。

**Commit**：`git add scripts/md_to_pages.py scripts/test_plan_narrative.py && git commit -m "feat(pages): 接 --narrative 并在 image_intent=none 时清空生图提示词"`

---

## 批 2 闸门

1. `test_plan_narrative.py` 13 绿、`test_check_narrative.py` 17 绿、`test_plan_contract_sections.py` 8 绿。
2. 不带 `--narrative` 时 `md_to_pages.py` 输出与改动前逐字一致（diff 空）。
3. `probe_report.md` 存在且显示门禁**接得住**历史页（每条 W-xx 有非零命中，或明确解释为何零命中）。
不过 → 停止并写 `spikes/2026-10-10-narrative-backfill/FAILURE.md`。

---

## Task 10 — `scripts/layout_recipes.py`：配方骨架 + 三线表

**分工（spec §4.2）**：7 个配方与 §1.3 的 7 种 role 一一对应；`template_renderer.py` 保留不动，只作 role 未覆盖时的兜底与回归基线；**本期不做删除**（避免破坏 18 页历史工程）。

**Files**: 新增 `scripts/layout_recipes.py`、`scripts/test_layout_recipes.py`。

**Steps** — 骨架（这部分是全部配方的公共底座，必须逐字实现）：

```python
#!/usr/bin/env python3
"""7 个参数化版式配方。每个 recipe(pg: dict, tok: Tokens) -> 完整 SVG 文档字符串。
SVG 约束（vendor 门禁 + 本项目实测）：只允许 <rect>/<line>/<path>/<text>/<image>/<g>/<clipPath>，
禁止 <style>、class、mask、textPath、@font-face、<animate>、filter。"""
from __future__ import annotations
import html
import xml.etree.ElementTree as ET
```
（不 import 任何新模块；`RECIPE_FUNCS` 由本文件自维护，见下。）

W, H = 1280, 720                                  # 仅兜底；正常从 tok 取
DEFAULT_SANS = "Noto Sans SC"                     # 作者栈首站（导出会被 FONT_FALLBACK_WIN 改写）
HEI, MONO = "Noto Sans SC", "Menlo"

def cjk(s: str) -> int:
    """显示宽度：CJK/全角计 1，其余计 0.55。"""
    return sum(1 if ord(c) > 0x2E7F else 0.55 for c in s)

def esc(s: str) -> str:
    return html.escape(str(s), quote=True)

def tx(x, y, s, size, fill, *, weight="400", family=DEFAULT_SANS, anchor="start",
       ls=None, opacity=None) -> str:
    a = f' x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}"' \
        f' font-family="{family}" text-anchor="{anchor}"'
    if ls is not None: a += f' letter-spacing="{ls}"'
    if opacity is not None: a += f' fill-opacity="{opacity}"'
    return f'<text{a}>{esc(s)}</text>'

def ln(x1, y1, x2, y2, stroke, wdt=1, dash=None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{wdt}"{d}/>'

def rect(x, y, w, h, *, fill="none", rx=0, stroke=None, sw=1, fill_op=None, dash=None) -> str:
    s = f' x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"'
    if fill_op is not None: s += f' fill-opacity="{fill_op}"'
    if rx: s += f' rx="{rx}"'
    if stroke: s += f' stroke="{stroke}" stroke-width="{sw}"'
    if dash: s += f' stroke-dasharray="{dash}"'
    return f'<rect{s}/>'

def svg_doc(title: str, body: str, role: str) -> str:
    """统一补顶层 <g id> 与根 data-pptx-page-role —— 作者契约归零的关键，
    使 vendor 的 introduced warnings 为 0。配方里一律经 page_doc() 调它，
    不要把本函数命名为 page() —— 那会被配方的 page 参数遮蔽。"""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="1280" height="720" viewBox="0 0 1280 720" data-pptx-page-role="{role}">'
            f'<g id="{role}">{body}</g></svg>')

def header(tok, kicker, sheet, assertion, so_what, c) -> str:
    """页头几何：已过全部门禁的实测值（10_table_v2 / 09_flow_v2）。"""
    assert cjk(assertion) * 44 <= tok.content_w, "断言标题超版心：拆行，不缩字号"
    return "".join([
        tx(tok.margin, 96, kicker, 13, c["MUTED"], family=MONO, ls=3),
        tx(tok.canvas_w - tok.margin, 96, sheet, 13, c["FOCUS"], anchor="end"),
        ln(tok.margin, 116, tok.canvas_w - tok.margin, 116, c["RULE"], 1),
        tx(tok.margin, 168, assertion, 44, c["INK"], weight="600"),
        tx(tok.margin, 204, so_what, 20, c["SUB"]),
    ])

def footer(tok, source, page_no, c) -> str:
    return "".join([
        ln(tok.margin, tok.canvas_h - 76, tok.canvas_w - tok.margin, tok.canvas_h - 76, c["RULE"], 1),
        tx(tok.margin, tok.canvas_h - 46, source, 13, c["SUB"]),
        tx(tok.canvas_w - tok.margin, tok.canvas_h - 46, f"{page_no:02d}", 13, c["MUTED"],
           family=MONO, anchor="end"),
    ])
```
`RECIPES` 映射与注册：本文件内自维护即可（不新增 `layout_registry.py`，Ponytail 阶梯第 2/3 条 —— 一个 7 键字典不值得一个模块）：
```python
RECIPE_FUNCS: dict[str, callable] = {}
def recipe(name):
    def deco(fn):
        RECIPE_FUNCS[name] = fn
        return fn
    return deco
RECIPES = {"cover": "cover_p1", "section": "section_anchor", "claim": "assertion_evidence",
           "data": "three_line_table", "mechanism": "mechanism_flow",
           "teaching": "teaching_pair", "closing": "action_list"}
ROLE_TO_RECIPE = dict(RECIPES)             # Task 9 从这里 import
def render(page_dict, tok):                 # 统一入口，md_to_pptx 调这个
    fn = RECIPE_FUNCS.get(ROLE_TO_RECIPE[page_dict["role"]])
    return fn(page_dict, tok) if fn else None      # None → 调用方走 template_renderer + fallback=true
```
颜色 token 一律从 `tok.colors` 取（`FIELD/SURF/STRUCT/INK/SUB/SUB2/FOCUS/CAUTION`），`MUTED` 用 `SUB2`、`RULE` 用 `STRUCT` —— 在文件头做一次别名映射，不要在配方里散落十六进制。

**Steps** — `recipe_three_line_table(page, tok)`（Task 10 只实现 data 这一个配方，其余在 Task 11-13）：
照抄已过门禁的 spike 实测几何（`10_table_v2`）：
```python
@recipe("three_line_table")
def recipe_three_line_table(pg, tok):
    c = _colors(tok); rows = pg["bullets"]
    tbl = [r.split("|") for r in rows if r.strip().startswith("|")]
    tbl = [[strip_cells(x) for x in row if x.strip() != ""] for row in tbl]
    tbl = [r for r in tbl if r]
    sep = [i for i, r in enumerate(tbl) if set("".join(r)) <= set("-: ")]
    if sep: tbl = tbl[:sep[0]] + tbl[sep[0] + 1:]
    head, body = tbl[0], tbl[1:]
    assert len(head) <= 5, f"三线表列数 {len(head)} > 5，配方不适用（交人重排）"
    ty, hh, rh = 252, 32, 40                    # 实测值，不要改
    assert ty + hh + len(body) * rh + 8 <= tok.canvas_h - 76, "表格压到页脚：拆页，不缩行高"
    x0, w = tok.margin, tok.content_w
    ncols = len(head); cw = w / ncols
    out = [_bg(tok, c)] + list(header(tok, "DATA · " + str(pg["index"]).zfill(2),
                                      sheet_title(pg), pg["assertion"], pg.get("so_what", ""), c))
    out.append(rect(x0, ty, w, 2, fill=c["INK"]))                          # 顶线 2px
    for j, h in enumerate(head):
        right = j > 0 and any(ch.isdigit() for ch in h)                     # 数字列右对齐
        out.append(tx(x0 + j*cw + (cw-12 if right else 12), ty + hh - 10, h, 13, c["SUB"],
                      family=MONO if right else DEFAULT_SANS,
                      anchor="end" if right else "start"))
    out.append(ln(x0, ty + hh + 2, x0 + w, ty + hh + 2, c["STRUCT"], 1))   # 栏目线 1px
    for i, row in enumerate(body):
        y = ty + hh + 2 + i * rh
        out.append(ln(x0, y + rh, x0 + w, y + rh, c["STRUCT"], 1, dash=None))  # 行间横线（0 竖线）
        for j, cell in enumerate(row):
            right = j > 0 and any(ch.isdigit() for ch in cell)
            out.append(tx(x0 + j*cw + (cw-12 if right else 12), y + rh - 12, cell, 16,
                          c["INK"], family=MONO if right else DEFAULT_SANS,
                          anchor="end" if right else "start"))
    out.append(rect(x0, ty + hh + 2 + len(body)*rh, w, 2, fill=c["INK"]))  # 底线 2px
    out += footer(tok, pg.get("scope_note", "") or source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "data")
```
**高亮规则（写进代码注释并在测试里断言）**：0 竖线、0 外框、0 斑马纹；高亮格 **≤2 个**且只用 `CAUTION` 的 `fill-opacity 0.10`；强调行用顶栏 2px 色条。单位下沉到表头，不在每个单元格重复单位。

`_bg / strip_cells / sheet_title / source_line / page_doc / _colors` 是这 4 个 Task 共享的小工具，全部放本文件顶部，各 ≤8 行；`page_doc(pg, body, role)` 直接调 `svg_doc()` 并把 `pg["title"]` 传作文档标题；配方参数一律叫 `pg`（不叫 `page`）。**不要为这些工具再拆文件。**

**Steps** — `scripts/test_layout_recipes.py` 18 项（Task 10 先建 10 项，Task 11-13 各加，最终 18）：
1. `RECIPES` 的 7 个 value 全部在 `RECIPE_FUNCS` 里（Task 13 完成后才转绿；此前允许标 xfail 并在报告里写明"待批 3 完成"）。
2. 输出以 `<svg ` 开头、`</svg>` 结尾、可被 `ET.fromstring` 解析。
3. 根元素含 `data-pptx-page-role`。
4. 存在顶层 `<g id=`。
5. 无 `<style` / `class=` / `<mask` / `textPath` / `@font-face` / `<animate` / `filter=`。
6. 所有 `<text>` 字号 ∈ `tok.ramp`（直接调 `qa_layout.check_typescale`，返回空）。
7. `qa_layout.check_overflow(root, tok.margin)` 返回空。
8. `qa_layout.check_line_collisions(root)` 返回空。
9. `qa_layout.check_dup_images(root)` 返回空。
10. 6 列三线表 → `AssertionError`（列数护栏生效）。
11. 12 行三线表压到页脚 → `AssertionError`。
12. `check_scale(root, tok.ramp)` 返回空（页头 44→20→16 层级合规）。
13. `header()` 里断言超版心时抛 `AssertionError`（构造 30 字 CJK 标题）。
14. 数字列 `text-anchor="end"`、文本列 `"start"`（正则数一下）。
15. 高亮格数 >2 时配方不加高亮（构造 3 个含数字的"高亮候选"，断言 `CAUTION` 填充矩形数 ≤2）。
16. 同一 `page` 二次 render 输出**逐字节一致**（配方必须纯函数，无随机/时间戳）。
17. `render()` 对未注册 role 返回 `None`（不抛）。
18. 与 `template_renderer` 同页对照：recipe 版与兜底版都能出合法 SVG，且 recipe 版的 vendor introduced warning ≤ 兜底版。

**Verify**：`"$PY" scripts/test_layout_recipes.py`（1-17 绿；第 1、18 项在 Task 13 前 xfail）；`"$PY" scripts/qa_layout.py <临时输出目录>` 对该页 ALL CLEAR。

**Commit**：`git add scripts/layout_recipes.py scripts/test_layout_recipes.py && git commit -m "feat(recipes): 配方底座与三线表版式"`

---

## Task 11 — `mechanism_flow`（机制流）

几何来自已过门禁的 `09_flow_v2`（`/tmp/pptplan/gen_pages_v2.py` 与 spec §4.3）：
```python
@recipe("mechanism_flow")
def recipe_mechanism_flow(pg, tok):
    c = _colors(tok); nodes = mechanism_nodes(pg)            # ≤6，从 evidence 抽
    assert len(nodes) <= 6, f"节点 {len(nodes)} > 6，交人拆图"
    n = len(nodes)
    ny = 268; cy = ny + 56
    nh = 34 + n * 32 + 12                                     # 卡片高随节点数收缩
    total_w = tok.content_w; nw = min(320, (total_w - (n - 1) * 24) // n)
    gap = (total_w - n * nw) // max(n - 1, 1)
    out = [_bg(tok, c)] + list(header(tok, "mechanism", sheet_title(pg),
                                      pg["assertion"], pg.get("so_what", ""), c))
    for i, nd in enumerate(nodes):
        x = tok.margin + i * (nw + gap)
        out.append(rect(x, ny, nw, nh, fill=c["SURF"], rx=6))
        out.append(tx(x + 44, cy + 5, nd["label"], 16, c["INK"], weight="600"))
        # 圆徽 24px 圆 + 13px 数字；与相邻文本 x 距离必须 >24（vendor 压行判据会误报）
        cx0 = x + 24
        assert cx0 + 24 < x + 44, "圆徽与文本 x 距离 <=24，vendor 门禁会误报压行"
        out.append(f'<circle cx="{cx0}" cy="{cy}" r="12" fill="{c["FOCUS"]}"/>')
        out.append(tx(cx0, cy + 5, str(i + 1), 13, c["FIELD"], anchor="middle", weight="700"))
        out.append(tx(x + 44, cy + 28, nd.get("note", ""), 13, c["SUB"]))
        if i:
            out.append(ln(x - gap + 4, cy, x - 6, cy, c["INK"], 3))   # 主链 3px
            out.append('<path d="M%d %d l-8 -4 v8 z" fill="%s"/>' % (x - 6, cy, c["INK"]))
    top_bottom = ny + nh
    out.append(ln(tok.margin, top_bottom + 40, tok.canvas_w - tok.margin, top_bottom + 40,
                  c["SUB2"], 1, dash="4 3"))                  # 回流线：虚线，走最高组底边下 40px
    out += footer(tok, source_line(pg), pg["index"], c)
    return page_doc(pg, "".join(out), "mechanism")
```
辅助 `mechanism_nodes(pg)`：把 evidence 文本按"→ / 然后 / 再"切分成节点；切不出 ≥2 个节点时返回空列表，配方**退化成 claim 页并打印 `[退化]`**（不要在机制页硬塞单节点）。
主链 3px / 普通 1.5px / 辅助 1px 虚线 `4 3`；单节点宽 ≤320、高 ≥88（`nh` 公式在 n=2 时 110，满足 ≥88，测试里断一次）。
`<circle>` 允许（vendor 未禁），若实测被 vendor 拒，改用 `rect rx="12"` 并把这条改动写进报告。

**新增测试（并入 18 项总数）**：节点数 7 → `AssertionError`；`nh >= 88`；回流线必须带 `stroke-dasharray`；圆徽与文本间距 assert 生效。

**Verify**：`qa_layout` 对该页 ALL CLEAR（含 `[尺度]` 无命中）；`test_layout_recipes.py` 绿。

**Commit**：`git add scripts/layout_recipes.py scripts/test_layout_recipes.py && git commit -m "feat(recipes): 机制流配方与圆徽间距护栏"`

---

## Task 12 — `cover_p1`（纯排版封面，审美基准）

**权威基准（用户裁决）**：封面 = **P1/V1 纯排版**，poster 160 两行 + 唯一强调色块，**无图**；`image_intent: none` 是封面合法默认值，**不再为封面自动出 hero**。

**复用与禁用（spec §3.3）**：`split_cover_title` 从 `cover_v2.py` 复用（本轮 spike 绕开它是已知偏差，本期纠正）；**但 P1 不用 `fit_font_size`** —— 它按可用宽度反解字号，与 P1"字号钉死在 poster 160、放不下只拆行"直接冲突。`fit_font_size` 只留给 P2/P3 的图配字场景。

```python
@recipe("cover_p1")
def recipe_cover_p1(pg, tok):
    c = _colors(tok)
    lines = split_cover_title(pg["assertion"])          # 从 cover_v2 复用，import 之
    for ln_ in lines:
        assert cjk(ln_) * tok.poster <= tok.canvas_w * 0.66, \
            f"封面行 {ln_!r} 超 0.66 画布宽：再拆行，禁止缩字号"
    out = [_bg(tok, c)]
    out.append(tx(tok.margin, 102, pg.get("scope_note", "")[:40], 13, c["MUTED"], family=MONO, ls=3))
    out.append(ln(tok.margin, 128, tok.canvas_w - tok.margin, 128, c["RULE"], 1))
    y = 330
    for l in lines[:2]:
        out.append(tx(tok.margin, y, l, tok.poster, c["INK"], weight="300", ls=0))  # 零字距
        y += 176
    out.append(rect(tok.margin, 556, 64, 4, fill=c["FOCUS"]))     # 全页唯一强调色块
    out.append(tx(tok.margin, 610, pg.get("so_what") or pg.get("subtitle", ""), 32, c["SUB"]))
    out.append(tx(tok.margin, 648, pg.get("subtitle", ""), 16, c["SUB2"]))
    for i in range(3):                                            # 右栏 3 行元信息
        out.append(tx(tok.canvas_w - tok.margin, 306 + i * 34, meta_line(pg, i), 13,
                      c["SUB"], family=MONO, anchor="end"))
    out.append(ln(tok.canvas_w - 300, 274, tok.canvas_w - tok.margin, 274, c["RULE"], 1))
    out.append(ln(tok.canvas_w - 300, 414, tok.canvas_w - tok.margin, 414, c["RULE"], 1))
    out.append(tx(tok.margin, 676, pg.get("audience", ""), 13, c["MUTED"]))
    out.append(tx(tok.margin, 702, pg.get("date", ""), 13, c["MUTED"], family=MONO))
    assert 556 + 4 <= tok.canvas_h - 46, "强调色块压到页脚"
    return page_doc(pg, "".join(out), "cover")
```
`lines[:2]` 之外还有第三行时 → **打印 `[警告] 封面三行以上，交人重断句`** 并保留（不静默丢弃，绝不缩字号）。

**Verify（本 Task 的核心是肉眼可核对的回归）**：
1. 与已过审的 spike 实物逐元素 diff：
   ```bash
   "$PY" - "$PS/spikes/<封面spike目录>/00_v1_type_only.svg" <<'PY' > /tmp/cover_elem_new.txt
   # 用 ET 列出 (tag, x, y, font-size, font-weight, fill) 六元组，逐行输出
   PY
   diff -u /tmp/cover_elem_old.txt /tmp/cover_elem_new.txt   # 必须为空或只含 margin 60→76 的 x 平移
   ```
   把 diff 存进 `spikes/2026-10-10-recipes/cover_diff.txt`。
2. **双调色版留档**：封面调色版随工程 `## colors` 走，而 workflow_full 是**暗底**，用户批准的样张是 **PAPER 亮底**。必须同时渲染亮/暗两版 PNG 到 `spikes/2026-10-10-recipes/cover_{light,dark}.png`，并在报告里明确写"**待用户肉眼再确认取哪一版**"。不要自行选定。
3. vendor `--stage final` 对该封面 introduced warning 为 0（正确计数口径）。
4. `qa_layout` ALL CLEAR，且 `check_contrast` 里 poster 160 走 3:1 档。

**Commit**：`git add scripts/layout_recipes.py scripts/test_layout_recipes.py spikes/2026-10-10-recipes && git commit -m "feat(recipes): P1 纯排版封面，复用 split_cover_title 并禁用 fit_font_size"`

---

## Task 13 — `assertion_evidence` / `teaching_pair` / `section_anchor` / `action_list`

- **`assertion_evidence`（claim 页，主力版式）**：页头同上；正文区 `y0=252`，每条 evidence 一行卡片：`rect(margin, y, content_w, 40, fill=SURF, rx=4)` + 左侧 3px `FOCUS`/`CAUTION` 色条按 `kind` 分色（number→FOCUS，image→SUB2，text→STRUCT）+ 文本 20px INK + 右侧 baseline 13px MONO。`so_what` 单独一行 24px weight 700 收尾（这是"所以然"的视觉落点，必须比正文跨 ≥2 档）。
- **`teaching_pair`**：几何取自 `/tmp/pptplan/gen_samples.py` 的 `b3()`（已过审的对照样张）—— 左右两栏各 `rect(_, 200, 340, 230, fill=SURF, rx=6, stroke=(色, 2))`，栏内 `! 错` / `✓ 对` 标签 20px weight 700、示意块 300×150 与 210×78、栏底结论 16px。**必须把 b3 里写死的左边距 120 归一到 `tok.margin`（76）**，并把整组 x 平移 `-44`；归一化后重跑 `qa_layout` 证明仍 ALL CLEAR，把归一化前后 x 值列进报告。
- **`section_anchor` / `action_list`**：简单排布，各 ≤30 行，不单独占批次。**注意**：`section_anchor` 没有已过门禁的实测几何 —— 这是**本期新造**，必须在代码注释里写明 `# 新几何：无 spike 实测依据，仅靠 qa 门禁 + 人读确认`，并渲染 PNG 存进 `spikes/2026-10-10-recipes/section_anchor.png` 供人读。不得谎称"沿用实测值"。
- `action_list`：≤5 条行动项，每条 `rect` + 序号圆徽（沿用 Task 11 的 >24px 间距护栏）+ 24px 文本 + 13px 负责人/时间；收口语由 `narrative.closing_hint` 给。

**Verify**：`test_layout_recipes.py` 18 项**全绿含第 1 项**（7 配方注册齐全）与第 18 项；对每类 role 各造 1 页跑 `qa_layout` + vendor 门禁，`introduced = 0`。
**Commit**：`git add scripts/layout_recipes.py scripts/test_layout_recipes.py spikes/2026-10-10-recipes && git commit -m "feat(recipes): 断言证据/对照/章节锚/行动清单四配方，7 role 全覆盖"`

---

## 批 3 闸门
1. `test_layout_recipes.py` 18 项全绿（xfail 必须已消除）。
2. 7 类 role 各一页：`qa_layout` ALL CLEAR + vendor introduced 0。
3. `cover_diff.txt` 显示与过审 spike 逐元素一致（或只含 margin 平移）。
4. 封面双调色版 PNG 已产出并在报告中标注"待用户肉眼确认"。

---

## Task 14 — 生图接入（由证据计划驱动，删除"每页自动配氛围图"）

**开关与来源（spec §5.2）**：`image_intent ∈ {none, background, panel, hero}`，内容依据来自 `visual_protagonist`（例："0 人工介入次数的对比柱"），**不是**来自 `narrative_rewrite.py` 的关键词→隐喻映射表（映射表降为兜底）。`none` 时**不调 agnes**。

**保留的红线（不重写，逐条不得放松）**：
- 生图只走 Agnes（`agnes-image-2.5-flash`），黑名单硬拦 `gemini` / `gpt-image` / `flux`。
- 提示词两组关键词必须同时写：**亮度组 + 尺寸组**；禁 `no glow` / `pen plotter` / "左半右半"。
- 出图后必跑 `scripts/analyze_image.py` 客观验收：**锐度 ≥80、P99 ≥40、主体分布 ≥25%、墨量 ≥6%、接缝 None**；墨量用 `max(R,G,B)` 通道不用亮度。
- **一页只用一个图位**，铺底与面板不得同图（重影）—— 这是 B-3。

**Steps**：
1. 在 `md_to_pptx.py` 的 `gen_images()` 前加路由：
   ```python
   intent = page.get("image_intent", "none")
   if intent == "none":
       log(f"p{idx:02d} image_intent=none，跳过生图")
       continue
   prompt = build_prompt(intent, page["visual_protagonist"], page)   # 亮度组+尺寸组同时写入
   png = agnes_generate(prompt, size=SIZE_BY_INTENT[intent])
   ok, why = analyze_accept(png)                                      # 五个阈值逐条
   if not ok:
       retry_once(png, prompt, why)                                   # 只重试一次；再失败 → 降级为 none
   ```
   `SIZE_BY_INTENT`：`background`=1792x1024、`panel`=1536x1024、`hero`=1024x1536（与现有 agnes 尺寸白名单取交集，现场不符则以现场为准并报告）。
2. `analyze_accept` 必须**复用** `scripts/analyze_image.py` 的既有函数，不新写一套指标（Ponytail 第 2 条）。
3. `background` 必带方向性 scrim：文字侧 `fill-opacity 0.92 → 空侧 0.04` 的台阶（0 / 0.45 / 0.62 / 1 四段，实测值见 `gen_samples.py b3()`），且 `check_backdrop ≥90%`。
4. `panel` 合规写法 = `<image>` 整幅声明 + `clipPath` 只露面板；**禁止**把同一张图既铺底又挂面板。
5. 缺凭据时：`agnes_*` 调用抛出的错误只记录**变量名**（如 `MODELBEST_API_KEY`），该页降级 `image_intent=none` 并在报告里列为"需人工：未验生图路径"。**不得**创建 `.env`、不得把 key 写进任何留档。

**Verify**：构造一个含 1 页 `background` + 1 页 `panel` + 16 页 `none` 的 plan，跑 `gen_images()` 断言只发起 2 次 agnes 调用（用桩函数计数，不真出图）；`analyze_accept` 用一张已知合格的旧 PNG 返回 ok、用一张纯色图返回不 ok。这两个断言写进 `scripts/test_layout_recipes.py` 之外的新文件 `scripts/test_image_route.py`（8 项：路由 3 项、scrim 台阶 2 项、panel clipPath 1 项、黑名单 1 项、缺凭据降级 1 项）。
若网络/凭据可用且用户已授权出图（本期默认**不**消耗额度），额外做一次真出图并在报告附 `analyze_image.py` 原始输出。

**Commit**：`git add scripts/md_to_pptx.py scripts/test_image_route.py && git commit -m "feat(images): 按 image_intent 路由生图并前置客观验收"`

---

## Task 15 — `md_to_pptx.py` 编排接线（不新增脚本）

**当前 11 步链（实测行号）**：114 `md_to_pages.py` → `gen_images()` → 143 `template_renderer.py` → 149 `plan_contract.py` → 151 `qa_score.py` → 153 vendor `svg_quality_checker.py --canonical-authoring --stage final --json` → 158 `svg_to_pptx.py`。

**改成**（顺序固定，缺一不可）：
```
1) plan_narrative.py --md ... --out narrative.json        （N1）
2) 人工/LLM 填 _todo（本步在无人值守期不自动做，见下方"停等点"）
3) check_narrative.py narrative.json                       （N2，blocking 非空则停）
4) md_to_pages.py --narrative ...                           → pages.json
5) 每页：role ∈ RECIPES → layout_recipes.render(page, tok)
           否则 → template_renderer，并在报告打印 fallback=true
6) render_svg（Chrome headless --window-size=1920,1080 --force-device-scale-factor=1 + sips -Z 1280）
7) qa_layout.py pages/ render/        ← 新增，此前不在链里
8) plan_contract.py（含 check_spec_parity + check_narrative_landing）
9) qa_score.py pages/ render/ --threshold 80 --emit qa.json
10) vendor svg_quality_checker --canonical-authoring --stage final --json
11) svg_to_pptx.py → .pptx
```
**停等点（无人值守关键）**：第 2 步需要人/LLM 补 `_todo`。黑苹果侧**没有授权自动写文案**。正确处置：若 `_todo` 非空且 N2 报 blocking，**停在第 3 步**，写 `spikes/2026-10-10-wiring/HOLD-narrative-todo.md` 列出缺项页号，然后用**该工程已有的旧路径**（不带 `--narrative`）跑一遍完整链出 pptx，作为"接线本身没坏"的证据。这不算完成本期，但必须在报告里交付。

**回读校验（pptx 必须被反向验证，不能只看导出成功）**：
```bash
unzip -p out.pptx ppt/slides/slide1.xml | grep -o '<p:sp>' | wc -l   # 形状数 > 0
"$PY" -c "print(open('out.pptx','rb').read(2))"                       # 必须是 b'PK'
```
页数、每页形状数、文件大小写进报告。**字体那条诚实写明**：作者栈首站 `Noto Sans SC`，导出被 `FONT_FALLBACK_WIN` 改写成 `Microsoft YaHei` / `SimSun` → **macOS 截图不代表 Windows 放映效果**；本期不做真嵌入（spec §9 列为不做）。

**Verify**：端到端跑 1 个真实历史工程出 pptx；`qa.json` 逐页分数齐全；vendor 正确口径 introduced 0；`git diff --stat` 只含预期文件。

**Commit**：`git add scripts/md_to_pptx.py && git commit -m "feat(pipeline): 接入 N1/N2、配方路由、qa_layout 前置与 pptx 回读校验"`

---

## Task 16 — 文档收口 + 三层验收 + 知识库 post-flight

**Files**: `docs/workflow.md`、`docs/qa-checklist.md`。

1. `docs/workflow.md`：新增"设计层"章节，写清 11 步链、7 role↔7 配方对照表、`image_intent` 四值语义、真相源模板路径与"禁止工程实例兼任 SSOT"、常见翻车档案追加两条本期新坑（`grep -c '[ERROR]'` 计数口径；圆徽与文本 x 距离 ≤24 触发 vendor 误报）。
2. `docs/qa-checklist.md`：把 `[尺度]`（blocking）/ `[网格]`（warn）/ WCAG 分档表 / qa_score 权重表（和=100）/ 阈值 80 写进去；明确"留白率只作趋势、不进门禁"及其实测理由。
3. **三层验收**（spec §9，逐层给证据）：
   - L1 机器：4 个 `test_*.py` + `test_image_route.py` 全绿；`qa_score` 阈值；vendor introduced 0。
   - L2 半机械：`qa_layout` 对新配方页 ALL CLEAR；回归对账表；探针 W-xx 命中表。
   - L3 人读：封面/每类 role 各 1 页 PNG 联系表（`spikes/2026-10-10-acceptance/contact_sheet.png`），**明确标注"审美需用户肉眼确认，本期未自我批准"**。
4. **知识库 post-flight（必做，母本落 3TB）**：把本期结论写成知识卡投
   `blackapple:/Volumes/3TB_DATA/02-知识库/tom-brain-2026/00-入口/inbox/agent-submissions/`，
   frontmatter 遵守 vault 根 `AGENTS.md` §6，内容类 Markdown 必须带 §6 frontmatter。
   卡片正文只写**可迁移的结论**（真相源模板化做法、尺度门禁判据、计数口径事故、版心收窄的代价），不写流水账。**投 inbox 即止 —— 独立复核后才发布，不得自行挪出 inbox。**

**Verify**：两份文档 diff 可读；`contact_sheet.png` 存在；知识卡文件存在且 `head -20` 能证明 frontmatter 齐全；最终报告 `spikes/2026-10-10-acceptance/REPORT.md` 含未闭环风险清单（见下一节，逐条照抄并补实际数字）。

**Commit**：`git add docs/workflow.md docs/qa-checklist.md spikes/2026-10-10-acceptance && git commit -m "docs: 设计层工作流与质检清单收口，附三层验收留档"`

---

## 24 小时无人值守交接协议（黑苹果侧执行者必读）

1. **顺序**：Task 1→16 严格串行，不跳、不并行改同一文件。每个 Task 的 `Verify` 全过才 commit 并进下一个。
2. **闸门**：批 1 / 批 2 / 批 3 闸门（以及 Task 15 端到端）任一不过 → **停止**，把已做的 commit 保留（不要 revert，已 commit 的都是干净增量），写 `spikes/<日期>/FAILURE.md`：哪一步、实际命令、实际输出、你判断的根因、需要主控决定什么。
3. **不得自行放宽**：阈值、`[尺度]` 判据、照抄率、列数/节点数上限、`copy_ratio` 的 40%。**放宽本身是决策，归主控。**
4. **不得做的事**：push；改 `.env`；打印 key；`git add -A`；动 `projects/agentflow-os-launch/cards/02_tension.svg`、`03_position.svg`；删历史工程页；给历史 18 页回填改设计；自动写叙事文案（Task 15 停等点）。
5. **进度留档**：每完成一个 Task 往 `spikes/PROGRESS.md` 追加一行（时间、Task 号、commit hash、Verify 摘要）。主控会读这份文件判断进展，**不靠你的一句话汇报**。
6. **诚实条款**：报告里禁止出现"基本完成 / 应该可以 / 大致通过"。每个"通过"必须附命令 + 输出片段。做不了的写明做不了。
7. **额度与时长**：生图默认不消耗（Task 14 用桩验证）；若某步必须联网而失败，记录并降级，不要反复重试超过 2 次。

## 未闭环风险（必须在最终报告里逐条列出，不得省略）

1. **版心 60→76 会让页数增加**：`needs_split` 拆出更多页，交付页数变化需人确认是否接受。
2. **`[尺度]/[网格]` 在历史 18 页大量命中是预期**：本期只记录、不回填；意味着历史项目按新标准需要重做设计。
3. **W-01 / W-06 的中文判定是启发式**：`、` 会误伤枚举式标题；需人读兜底，PASS 行已强制声明只代表部分合格。
4. **照抄率 ≤40% 是本仓自定（D 级）**，非外部标准，无文献支持。
5. **宋体标题投影糊笔画未实测**：`SimSun` 在 44px 以上的投影/描边表现没有取证，属推断。
6. **封面 P1 亮/暗调色版需肉眼再确认**：随工程 `## colors` 走，与用户批准的 PAPER 亮底样张不一致。
7. **macOS 截图不代表 Windows 放映**：导出被 `FONT_FALLBACK_WIN` 改写字体，本期不做真嵌入。
8. **vendor 严格 schema 与 `## grid` 冲突**：`validate_markdown_text` 会报 `unknown section 'grid'`，本期不去严格化它（该命令不在管线内）；若将来要接，唯一出路是把 `## grid` 写进 vendor schema。
9. **`section_anchor` 是本期新造几何**，无 spike 实测依据，仅靠门禁 + 人读。

---

**计划自检（写计划的人留下的三个抓手，执行者拿来复核）**
- spec 覆盖：§3 封面→Task 12；§4.1 真相源→Task 2/3；§4.2 配方分工→Task 10-13；§4.3 几何→Task 10-13；§4.4 尺度门禁→Task 5；§5 生图→Task 14；§6 门禁链/权重/契约/字体→Task 5/8/15；§7 卡片→沿用既有 skills 目录（Task 1 已 commit）；§8 实施顺序→批次映射；§9 三层验收→Task 16。
- 类型一致性：`Tokens` 字段名与配方里用到的 `tok.margin/content_w/canvas_h/baseline_step/poster/ramp/colors` 全部在 Task 2 的 dataclass 内定义，无未定义字段引用。
- 签名硬约束：`check_contrast(img, root)` 两参不变（Task 5 明文）、`WEIGHTS` 和=100（Task 5 有测试）、配方签名 `(page, tok) -> str`（Task 10 明文）。

