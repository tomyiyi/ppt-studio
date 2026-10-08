---
title: ppt-studio 设计层重写 spec
type: spec
status: draft-for-review
created: 2026-10-08
area: 项目
tags: [ppt-studio, 设计层, spec]
---

# ppt-studio 设计层重写 spec（v1 草案，待复核）

真相源：`blackapple:/Volumes/3TB_DATA/05-开发项目/ppt-studio/docs/superpowers/specs/2026-10-08-ppt-design-layer-design.md`
状态：**待用户复核。批准前不改任何管线代码。**

---

## 0. 一句话与不变量

**要解决的问题**：现在的管线把文字灌进模板槽位，产出的页面没有「页面角色 + 断言式标题 + 证据 + 视觉主角」这一层，所以门禁全绿仍然被判定"不是设计"。

本轮实测已证实（可当事实用）：

| 事实 | 证据 |
|---|---|
| 门禁 PASS 不是质量标准 | 三套封面样张 vendor `errors 0` 完全相同，用户判定仍是"封面没有视觉主角" |
| 差距在版式层不在校验层 | 旧渲染器 `template_renderer.py`（746 行）只做「槽位定位 + 字号降档塞入」（`_slot_bounds` / `_fit_plan` / `FIT_SIZES=(22,20,16)`），没有任何"这页承担什么叙事任务"的输入 |
| 规则已被证明能落地 | spike 的 `gen_covers.py` / `gen_pages_v2.py` 用 12 栏栅格 + 尺度跨档 + 三线表，两道内容页 `qa_layout ALL CLEAR`、对比最低 8.3:1，并已导出可编辑 pptx |
| 字体可移植性已收口 | 换 OFL 栈后 `unsafe_exported_font_faces 命中=0`（封面与内容页各验一次） |
| qa_layout 三处误判已修 | 23 页回归：压行误报 25→0、面板识别 0→1、待修项 59→30，且**无任何一页变差** |
| 真相源"唯一"是假的 | `md_to_pptx.py:108-111` 缺 spec_lock 时**硬编码复制 `projects/agentflow-os-launch/spec_lock.md`**——模板由工程实例兼任，改一处即污染所有新工程 |
| 新增 `## grid` 节不影响导出 | 四变体对照实测：交付门禁 `svg_quality_checker` 对 spec_lock 内容**不做 schema 校验**（原样 / `poster` 键 / 未知节 / `canvas` 未知键，四组门禁输出一字不差，blocking 均 0）；vendor 严格 schema 会拒未知节，但该命令不在管线内，且存量已有 22 条同类报错 |

**四条红线（本 spec 不得越界）**

1. 不替换 ppt-master 底座，只替换 ppt-studio 自己的设计层。
2. `spec_lock.md` 是全项目唯一真相源；任何常量新增必须先进这里，再进代码。
3. 门禁是必要条件不是质量标准：每段验收必须同时给「机器判据」和「人读判据」。
4. 破坏性操作（删除旧渲染路径、改写既有 18 页工程）不在本期，本期只做加法与可回滚替换。

**本轮已被用户裁决、直接作为输入的三件事**：封面基准 = **P1 纯排版（poster 160 两行 + 唯一强调色块，无图）**；字体 = **OFL 可内嵌栈**（已实测完成）；qa_layout = **三处都修带回归**（已完成）。

---

## 1. 页面角色系统（新增管线阶段 `narrative_plan`）

### 1.1 现状与缺口

现有链路（`md_to_pptx.py` 实测编排）：

```
md → md_to_pages.py → pages.json → template_renderer.py → svg_output
     → plan_contract.py → qa_score.py → vendor svg_quality_checker → svg_to_pptx
```

`pages.json` 每页只有 `{index, title, layout, bullets, needs_review, image_prompt}`。`layout` 的取值是**版式名**（cover/bullets/compare/steps/table），不是**叙事角色**——渲染器因此无从知道"这页要干什么"，只能选个模板灌字。

### 1.2 裁决：引入两层——角色（role）决定版式，版式决定坐标

新增阶段 **N1 `plan_narrative.py`**（位置：`md_to_pages.py` 之前），输入源 md + 受众 + 时长，输出 `narrative.json`：

```json
{
  "governing_thought": "全场唯一的一句话论点（可被反驳）",
  "audience": "技术决策者 / 平台负责人",
  "pages": [
    {
      "index": 3,
      "role": "data",                       // 7 选 1，见 1.3
      "assertion": "自愈把人工介入压到 0 次",   // 含动词的判断句，≤24 字
      "evidence": [
        {"kind": "number", "text": "0 人工介入", "baseline": "改造前 12 次/周", "source": "notes/04.md#L3"}
      ],
      "so_what": "值班可以从 7×24 降级到日报",  // 页尾落地句
      "visual_protagonist": "44px 大数字 0 + 对比基准行",
      "image_intent": "none",                // none | hero | panel | background
      "scope_note": "统计口径：近 8 周"        // 可选
    }
  ]
}
```

`narrative.json` 是新的**上游真相源**；`pages.json` 保留并降级为它的投影（新增 `role` / `assertion` / `so_what` / `evidence` 字段，旧字段不动，保证 18 页既有工程不破）。

### 1.3 七种角色与对应版式配方（recipes）

| role | 叙事任务 | 版式配方 | 必填字段 | 视觉主角（默认） |
|---|---|---|---|---|
| `cover` | 立主张 | `cover_p1` | title_claim(≤12) / subtitle_takeaway(≤24) / audience_question / presenter+date | poster 160 两行标题 |
| `section` | 换章节 | `section_anchor` | eyebrow / assertion | 章节编号 96 |
| `claim` | 给结论 | `assertion_evidence` | assertion / evidence(≤3) / so_what | 56px 断言句 |
| `data` | 摆证据 | `three_line_table` | action_title / chart_intent / baseline / highlight_series / so_what | 44–56px 大数字或三线表 |
| `mechanism` | 讲原理 | `mechanism_flow` | assertion / diagram_nodes(≥3+因果标签) / counter_case / implication | 3px 主链流程图 |
| `teaching` | 教会用 | `teaching_pair` | concept_def(≤30) / good_bad_pair / check_question | 对错并排双栏 |
| `closing` | 要行动 | `action_list` | actions(≤3，动词+对象+时限/责任人) | 编号列表 |

**裁决**：`role → recipe` 一对一，不做"自动挑模板"。挑模板是把设计责任推给猜测器，正是当前问题的来源。

### 1.4 N2：写作契约门禁 `check_narrative.py`（blocking）

把 `ppt-narrative-writing` 的 W-xx 里**可机械判定**的部分转成断言，跑在渲染之前（渲染后判已经太晚）。规则编号直接进报告行，实现见 §7 第 7 项。

| 判据 | 实现口径 | 级 |
|---|---|---|
| W-01 断言句 | 标题命中 `(背景\|概况\|分析\|介绍\|说明\|总结\|举措)$` → blocking | 可脚本 |
| W-02 长度 | `len(assertion) ≤ 24`；`split` 后每行 ≤16 且 ≤2 行 | 可脚本 |
| W-06 一页一论点 | 标题含 `和/及/以及/、` 连接两个结论 → blocking 提示拆页 | 可脚本 |
| W-07 证据对象 | 每页 `len(evidence) ≥ 1` 且 `≤ 3`，注释合计 ≤60 字 | 可脚本 |
| W-12 数字带基准 | 页内每个数字必须能在同一页文本里找到基准词（同比/环比/相比/目标/去年/对标/×倍） | 可脚本 |
| W-24 禁空词 | 词表 grep，命中 >1 次/页 → blocking | 可脚本 |
| W-27 回指素材 | `evidence.source` 指向的原文行必须存在且含该数字，否则 blocking | 可脚本 |
| W-29 照抄率 | 与源 md 做 5-gram 重合，>40% → blocking | 可脚本 |
| W-03 可反驳 | **机器判不了**，打印"待人工确认"清单 | 人读 |
| W-04 标题链 | 机器只检查"标题连读不含断裂词"，链条成立与否人读 | 人读 |

**诚实边界**：W-03/W-04/so-what 质量这三条只能人读。spec 不假装脚本能替代它们，交付报告必须写"机器判 X 条通过，人读 Y 条待确认"。

### 1.5 验收

- 机器：`check_narrative.py` 0 blocking；每页 `role` 合法且**该 role 在 §1.3 表里的必填字段齐全**（不是所有页同一套字段——`cover` 不该有 `evidence`，`data` 不该只有 bullet）。
- 人读：只读全部 `assertion` 一遍，能复述完整论证链（W-04）；任何一条像"××概况"就退回。
- 回归：既有 18 页工程缺 `role` 时走兼容分支（不新增 blocking），保证不破坏历史交付。

---

## 2. 写作契约（内容层如何进代码）

### 2.1 数据流

```
源 md ──N1 plan_narrative.py──> narrative.json ──N2 check_narrative.py──> 通过
                                     │
                                     ├─> md_to_pages.py（改：读 narrative，不再自拟标题）
                                     └─> images/image_prompts.json（生图改由 image_intent 驱动，见 §5）
```

`plan_narrative.py` 不写文案，它做的是**把文案要求变成结构**：切节、识别每节数字与来源行、按 `role` 建必填字段骨架、缺项报错。文案由 agent 按 `ppt-narrative-writing` 填进骨架，填不满就过不了 N2。这样规则和代码之间没有"自由发挥"的空隙。

### 2.2 契约扩展：`plan_contract.py` 加内容完整性以外的字段校验

现状：`check_content_loss()` 已能抓"pages.json 里的 bullet 没画进 SVG"（渲染器"放不下就不画"会被抓成 blocking）。
本期新增：

- 每页必须有 `assertion` + `so_what`，且两者都真实出现在 SVG（复用 `_flat` 前缀判定）。
- `evidence[].source` 的原文行号必须在源 md 里可解析。
- `role` 必须 ∈ 7 种，未注册 role = blocking。

**理由**：写手层最容易偷的懒是"标题写了但页面上没有"，现有门禁只看 bullets，看不到断言。

---

## 3. 封面：P1 纯排版为基准

### 3.1 已裁决

**默认基准 = P1 纯排版**（无图、poster 160 两行、唯一强调色块）。P2 hero 单边出血 / P3 全幅 duotone 降为**按需备选**，仅在"确有强主体图"时启用，不再是候选基准。

### 3.2 P1 参数化配方（把 spike 里被认可的几何钉成代码）

`recipe_cover_p1(page, tokens)` —— 全部坐标取自本轮实测样张 `00_v1_type_only.svg`，不自创新数值：

| 元素 | 参数 | 来源 |
|---|---|---|
| 版心 | `M=76`（画布宽 6%） | L-01 |
| kicker | `y=102`，13px，等宽 `letter-spacing 3` | gen_covers v1 |
| 顶 hairline | `y=128`，1px，`RULE` | gen_covers v1 |
| 主标题 | **poster 160** 两行，`y=330` / `y=330+176`（行高 1.10），weight 300，**中文零字距** | gen_covers v1 |
| 强调色块 | `rect(M, 556, 64, 4)`，面积 0.03%（≤5% 红线） | C-09 |
| takeaway | `y=610`，32px | gen_covers v1 |
| 说明 | `y=648`，16px `MUTED` | gen_covers v1 |
| 右栏目录锚 | 3 行 13px `anchor=end`，`y=306+i×34`，配 2 条 hairline（`W-380→W-M`，`y=274/414`） | gen_covers v1 |
| 页脚 | `y=702`，13px + 页码等宽 | gen_covers v1 |

生成时自检（写死在配方里，不靠事后 QA）：

- `cjk(每行标题) × 160 ≤ 1280 × 0.66`（主角占宽 55–65%）；不满足 → **拆行，不许缩字号**（"放不下就不画"是这个项目被否掉的老毛病）。
- 尺度差：`poster / subtitle_takeaway ≥ 160/32 = 5×`，满足 C-03「3–4 倍」下限。
- 同屏相邻层级跨 ≥2 档（L-08b）。
- 最坏情况对比自检（底图保守取纯白，逐层合成压平/遮罩色，取文字块右端）——本轮靠它抓出 4 处真实不达标，保留。

### 3.3 明确不做

- 封面**不接生图**（P1 无图）。`image_intent: none` 是封面的合法默认值，不再为封面自动出 hero。
- 不写新的封面引擎。`split_cover_title` 从 `cover_v2.py` 复用（本轮 spike 绕开它是已知偏差，本期纠正）；**但 P1 不用 `fit_font_size`**——它按可用宽度反解字号，与 P1"字号钉死在 poster 160、放不下只拆行"的规则直接冲突。`fit_font_size` 只留给 P2/P3 的图配字场景。

---

## 4. 版式系统（用参数化配方替换填槽）

### 4.1 单一真相源先补齐

**本轮核查发现的真相源缺口（M，已实测）**：`md_to_pptx.py:108-111` 的逻辑是——工程缺 `spec_lock.md` 时，**直接从 `projects/agentflow-os-launch/spec_lock.md` 复制一份**。也就是说"唯一真相源"实际由**某个工程实例**兼任，而不是 `patterns/` 下的模板件；vendor 侧虽有 `templates/scaffolds/spec_lock.md` + `cli.py scaffold-lock`，本管线没有用它。风险很具体：任何人顺手改了那个工程实例，之后新建的每个工程都静默继承改动，且没有 diff 面可审。

本期第一件事是把它变成实物：

1. **新增 `patterns/spec_lock.template.md`**（模板真相源）；`md_to_pptx.py` 的取样路径从工程实例改为该模板；`plan_contract.py` 校验工程内 spec_lock 与模板的**节名集合一致**（缺节 = blocking）。既有 2 份工程副本同步补齐新节。
2. 模板与副本同时补：

```markdown
## grid
- margin: 76          # 取 L-01（画布宽 6%），qa_layout 的 MARGIN=60 同步改读此值
- cols: 12
- col: 72
- gut: 24             # 自检 76 + 12×72 + 11×24 + 76 == 1280
- bands: 4 8 12 16 24 32 48 64
- baseline_step: 8

## typography
… 现有九档 …
- poster: 160         # ← 本轮裁决写入真相源（当前只活在 /tmp/bkspike 的一次性副本里）
```

**schema 兼容性已实测（M，2026-10-08 四变体对照）**——这条决定上面两节能不能这么写，不能靠猜：

| spec_lock 变体 | 交付门禁 `svg_quality_checker --stage final` | vendor 严格 schema `validate_markdown_text` |
|---|---|---|
| 原样（基线） | blocking **0**，3/3 页 Passed（with warnings） | 22 条报错（**全是存量**：`consumption_mode` 值非法、`page_rhythm` 写法） |
| `typography` 加 `- poster: 160` | **与基线一字不差** | **22 条，零新增**（typography 允许自定义 role 键） |
| 新增未知节 `## grid` | **与基线一字不差** | 23 条，新增 `unknown section 'grid'` |
| `## canvas` 塞 `- margin/- cols` | **与基线一字不差** | 27 条，每个键一条 `unknown field`（canvas 是封闭白名单） |

> 计数口径备注：第一版探针用 `grep -c '[ERROR]'` 得出"ERROR 1"，实际命中的是汇总行 `[ERROR] With errors: 0`，**不是真错误**。上表已改用逐页 `Passed/Failed` 判定复核。

三条结论直接进设计：

- **交付门禁不校验 spec_lock schema**（四变体输出一字不差），所以新增 `## grid` 节**不会拦导出**，方案成立。
- vendor 的严格校验器 `project_management/cli.py validate` 会拒绝未知节，但**该命令不在本管线内**，且现状存量已有 22 条同类报错——本期不去"顺手严格化"它（属另一条战线，见 §9 不做）。若将来要接，唯一出路是把 `## grid` 写进 vendor schema，而不是把常量塞进 `canvas`（实测塞不进去）。
- `poster` 落 `typography` 是**双把尺子都干净**的写法，可以放心作为档位真相源。

**写法红线**：上面代码块里的行内注释是**示意说明，不写进实际文件**。`## typography` 的 `- 角色: 档位` 行由 `qa_layout.load_ramp()` 自己解析，`ppt-master` 侧也有"行内注释会报错"的已记档坑（workflow.md），所以新增行的注释一律单独占行。`workflow_full` 里 `tertiary_text` 那行带行内注释属历史例外，本期不动。

新增 `scripts/spec_tokens.py`：唯一读取 `spec_lock.md` 的解析器，`qa_layout.py`、`plan_contract.py`、所有 recipe 全部从这里取常量。

**根因修复而非表面补丁**：现在 `pages_to_svg.py` 写死 `MARGIN=60 / RAMP={11,13,16,20,24,32,44,96}`（连 56 都没有），`qa_layout.py` 也写死 60，而 `L-01` 说 76 —— 三处各写各的正是 workflow.md「常见翻车档案」里那条"质检阈值和生成器打架"。收敛到一个解析器，不各处补调。

### 4.2 配方与渲染器分工

- **新增** `scripts/layout_recipes.py`：**7 个配方，与 §1.3 的 7 种 role 一一对应**（`cover_p1` / `section_anchor` / `assertion_evidence` / `three_line_table` / `mechanism_flow` / `teaching_pair` / `action_list`）。每个签名 `def recipe(page: dict, tok: Tokens) -> str`，返回一段完整 SVG。其中后两个（`section_anchor` / `action_list`）是简单排布，各 ≤30 行，不单独占实施批次。
- **保留** `scripts/template_renderer.py` 不动，只作为 `role` 未覆盖时的兜底与回归基线。
- `md_to_pptx.py` 的路由：`role ∈ RECIPES` → 走配方；否则走 template_renderer 并在报告里打印 `fallback=true`。**本期不做删除**（避免破坏 18 页历史工程）。

### 4.3 内容页几何（沿用已过全部门禁的实测值）

页头页脚（`10_table_v2` / `09_flow_v2`，`qa_layout ALL CLEAR`）：

```
kicker   y=96  13px MONO ls3      页标(右上) y=96 13px FOCUS anchor=end
hairline y=116 STRUCT op0.5
断言标题 y=168 44px weight600       so-what 行 y=204 20px SUB
来源行   y=H-46 13px SUB            hairline y=H-76
```

三线表：`ty=252 / hh=32 / rh=40`；0 竖线 0 外框 0 斑马纹；顶底线 2px、栏目线 1px；数字右对齐走 Menlo；单位下沉表头；高亮 ≤2 格且只用 `CAUTION fill-opacity 0.10`；强调行顶栏 2px 色条。

机制流：主链 3px / 普通 1.5px / 辅助 1px 虚线 `4 3`；节点 ≤6、等宽、单节点宽 ≤320、高 ≥88；卡片高**随节点数收缩** `nh = 34 + n×32 + 12`；主链走第一行 `cy = ny+56`，回流线走最高组底边下 40px 且必须虚线；圆徽 24px 圆 + 13px 数字。

**一条钉死的工程护栏**（已写进 `gen_covers.py` 的 assert）：24px 圆徽中心与相邻文本的 x 距离必须 >24，否则 vendor 门禁的压行判据会误报。

### 4.4 尺度门禁化

把"高级感"翻译成可测代理，全部进 `qa_layout`（新增两项检查，不新建脚本）：

| 新检查 | 判据 | 违规动作 |
|---|---|---|
| `[尺度]` | 同屏相邻层级必须跨 ≥2 档（44→20→16 合规；44→32→24 违规） | blocking（这是"填字感"的根因） |
| `[网格]` | 元素 y 坐标落 8px 步进（容差 ±1px） | warn（历史 18 页会大量命中，先不 blocking） |

留白率**不进门禁**：实测包围盒估法系统性低估（数据表页 14.8%、机制页 24.3%，肉眼并不挤），只作趋势打印。这条是本轮的诚实结论，不要为了凑数字把它写成硬判据。

---

## 5. 生图接入（由证据计划驱动，不再"每页自动配氛围图"）

### 5.1 现状问题

`pages_to_svg.py` / `md_to_pages.py` 对每页无条件生成 `image_prompt`（实测 `workflow_full/pages.json` 18 页每页都挂着一长串 "deep graphite gradient backdrop, rim lighting…"）。结果是"一张氛围糊图压一行小字"——与"图承担信息"无关。

### 5.2 裁决：`image_intent` 是开关，`narrative.json` 是来源

| image_intent | 何时用 | 生图要求 |
|---|---|---|
| `none` | 默认。封面 P1、数据表页、文字机制页 | 不调 agnes |
| `background` | 需要氛围托底且有文字净空区 | 全幅 + 方向性 scrim；`check_backdrop ≥90%` |
| `panel` | 局部证据图（截图/实物/示意） | `<image>` 整幅声明 + `clipPath` 只露面板（B-3 合规写法） |
| `hero` | 确有强主体（P2/P3 备选） | 单边局部出血 |

`recipe` 拿到 `background/panel/hero` 才向 `agnes_ppt_bridge.py` 要图；`image_intent` 的**内容依据来自 `visual_protagonist`**（例："0 人工介入次数的对比柱"），不是来自 `narrative_rewrite.py` 那张关键词→隐喻映射表。映射表降为兜底。

### 5.3 保留的红线（不重写）

- 生图只走 Agnes（`agnes-image-2.5-flash`），黑名单硬拦 gemini/gpt-image/flux。
- 提示词两组关键词必须同时写（亮度组 + 尺寸组），禁 `no glow` / `pen plotter` / "左半右半"。
- 出图后必跑 `analyze_image.py` 客观验收（锐度 ≥80、P99 ≥40、主体分布 ≥25%、墨量 ≥6%、接缝 None）；墨量用 max(R,G,B) 通道不用亮度。
- 一页只用一个图位，铺底与面板不得同图（重影）。

---

## 6. QA 门禁与导出

### 6.1 门禁链（顺序固定，缺一不可）

```
N2 check_narrative（新增，写作契约）
 → plan_contract（内容完整性 + 断言/so-what 落地 + role 合法）
 → qa_layout（8 项：字号/底图/重影/溢出/压行/面板/对比 + 新增尺度、网格）
 → qa_score（阈值 80，权重表按 §6.2 调）
 → vendor svg_quality_checker --stage final   ← 必须在项目目录内先跑，否则 svg_to_pptx 拒绝导出（B-4）
 → svg_to_pptx → 回读 pptx（sz= / <p:sp> / <a:t> / <p:pic>）
```

### 6.2 权重表调整（`qa_score.WEIGHTS`）

现有 6 项加起来 100，新增两项必须重新配平：

| 项 | 现权重 | 新权重 | 理由 |
|---|---|---|---|
| typescale | 20 | 14 | 字号档已由 `[尺度]` 抓更本质的问题 |
| hierarchy（新） | — | 12 | 跨档与唯一 L1 是"高级感"主代理 |
| backdrop | 15 | 12 | `image_intent=none` 的页 N/A，权重下调 |
| dup_images | 15 | 12 | 同上 |
| overflow | 20 | 18 | 保持 |
| collisions | 10 | 8 | 判据已修（B-1），误报清零后不必给高权 |
| contrast | 20 | 24 | 可读性是底线，唯一上调项 |

阈值 80 不变。**注意**：权重变了，历史 18 页的分数会整体位移，回归对账看的是**逐页通过/不通过是否劣化**，不是总分可比。

### 6.3 对比度口径（把 §7 裁决写进代码）

- 正文（<24px）：WCAG **4.5:1**。
- 大字：`size ≥ 32` 或 `size ≥ 24 且 weight ≥ 700` → **3:1**（这是 WCAG large-text 分档的本仓落点，此前"大字不可判定"已由 B-5 Otsu 修复）。
- 装饰符号（`•` `—` 等单字符标记）：按**非文本图形 3:1** 判，不按正文 4.5 判，也不豁免。
- 报告必须打印每项用了哪档阈值，否则无法复核。

### 6.4 作者契约补齐（消除每次交付都带的 warning）

本轮实测：spike 交付带 `quality_introduced_warnings`（封面 6 / 内容页 4），两条成因已定位——逻辑单元未包进顶层 `<g id="…">`、页根缺 `data-pptx-page-role`。

裁决：`layout_recipes.py` 统一在 `page()` 包装函数里补齐这两个属性，目标 **`quality_introduced_warnings = 0`**，并把 "=0" 加进 `qa-checklist.md` 的交付硬条件。recipe 之外的模板路径（`template_renderer`）不动，历史工程维持现状。

### 6.5 字体（本轮已实测完，spec 只钉结论）

- 作者栈：`Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif`（首站 SIL OFL 1.1，黑苹果已装 Real）。
- 导出契约不变：`spec_lock.md` 的 `font_family: Microsoft YaHei, Arial` 是真相源；vendor `FONT_FALLBACK_WIN` 会把 Noto/PingFang/Hiragino/Source Han 全部改写成 `Microsoft YaHei`。
- **含义必须写进交付说明**：macOS 截图的字形不代表 Windows 放映效果，任何字形好不好看的判断按"最终落到雅黑/宋体"评估。
- `unsafe_exported_font_faces` 现为 0；回归时若再次出现，先查是否有人又把 face 名写回 `STHeiti Light` 一类白名单外值。

### 6.6 卡片（第三出口）

本期**不改** `make_cards.py` / `qa_cards.py`。`spec_tokens.py` 落地后卡片自动继承版心常量，但重排逻辑不在本 spec 范围内，避免一次改动三个出口。

---

## 7. 七个开口项的逐条裁决（请重点复核这一节）

| # | 开口项 | 裁决建议 | 依据 |
|---|---|---|---|
| 1 | `poster: 160` 进不进 `spec_lock.md` | **进**，与 `## grid` 节同批落 | 不进就违反自家档位门禁（X-06），封面 P1 无法过 `[字号]` |
| 2 | 版心 76 vs `qa_layout.MARGIN=60` | **取 76**，常量从 `spec_lock ## grid` 读；两处脚本硬编码（`qa_layout` / `pages_to_svg`）改成读 tok，skill 里的 L-01 保留作规则说明 | L-01 更严；60 是"生成器与质检打架"的根源 |
| 3 | WCAG 大字分档阈值 | **≥32px 或 ≥24px bold 用 3:1，其余 4.5:1** | WCAG large-text 原口径；本仓正文最小 16、卡片标题常落 24，若 24 就放宽会放行一批真不合格 |
| 4 | 装饰符号 `•` 怎么判 | **按非文本图形 3:1**，不豁免 | 现值 3.20:1 → 判过；若按 4.5 判则是假阳性，按豁免则漏真问题 |
| 5 | 字体嵌入走哪条路 | **本期不做真嵌入**，只在交付说明里给"交稿前 PowerPoint 勾嵌入字体"的人工步骤 | vendor 无 `--embed`，`pptx_embedded_fonts.py` 只是往返 sidecar；自写包级后处理（embeddedFontLst + font parts + content-types + rels）风险高、收益只有跨机放映，而 face 反正被改写成雅黑 |
| 6 | 作者契约 `quality_introduced_warnings` | **补齐到 0** 并进交付硬条件（`<g id>` + `data-pptx-page-role` 在 recipe 的 `page()` 里统一生成） | 本轮实测 6/4 条全部来自这两处缺失 |
| 7 | 三个 skill 怎么接进管线 | **skill 当规则源，不当文案源**：`check_narrative.py` 逐条实现 W-xx，`layout_recipes.py` 头部注释引用 L-xx 编号，封面配方引用 C-xx；报告行打印规则编号 | 把 SKILL.md 塞进 prompt 会让"合规"变成模型心情；编号化后才能定位是哪条规则没过 |

**另加一条本期明确推迟**：`[网格]`（坐标落 8px）先 warn 不 blocking——历史 18 页大面积不合规，一旦 blocking 会把本期变成无法收口的清理工程。

---

## 8. 实施顺序、回归口径与回滚

**改动面（新增 4 个脚本 + 1 份真相源模板；改动 4 个脚本 + 2 份既有 `spec_lock.md` 副本 + 2 份文档；`template_renderer.py` 与卡片链路不动）**

```
新增  patterns/spec_lock.template.md 真相源模板（当前缺实物，见 §4.1）
新增  scripts/plan_narrative.py      N1 结构器（不写文案）
新增  scripts/check_narrative.py     N2 写作契约门禁
新增  scripts/spec_tokens.py         spec_lock 唯一解析器
新增  scripts/layout_recipes.py      7 个参数化配方（与 §1.3 的 7 种 role 一一对应）
改动  projects/*/spec_lock.md（2 份） + ## grid / + poster: 160
改动  scripts/qa_layout.py           MARGIN/字号读 tok；+ [尺度] [网格]；阈值分档
改动  scripts/pages_to_svg.py        只把写死的 MARGIN=60 / RAMP 换成读 tok（它缺 56 档是实测 bug），渲染逻辑不动
改动  scripts/plan_contract.py       断言/so-what 落地 + role 校验
改动  scripts/md_to_pptx.py          插 N1/N2；recipe 路由；analyze_image 前置
改动  docs/workflow.md + qa-checklist.md
```

**分批与回归闸门（每批都要过才进下一批）**

1. **真相源**：落 `patterns/spec_lock.template.md`（补 `## grid` + `poster: 160`，注释单独占行）→ 同步 2 份既有副本 → `md_to_pptx.py` 取样路径从工程实例改指模板 → `plan_contract.REQUIRED_SPEC_SECTIONS` 加 `## grid` → `spec_tokens.py` 落地。**这一步的 schema 风险已实测消除**（§4.1 对照表：未知节与 `poster` 键都不影响交付门禁），不需再试探 vendor。随后 `qa_layout` 对 `workflow_full` 跑改前/改后对账，要求逐页不劣化（脚本现成 `spikes/2026-10-08-design-layer-v2/qa-regression/regression_qa.sh`）。
2. N1/N2：对 `workflow_full` 的 18 页反向生成 `narrative.json`，看有多少页真能被契约接住；接不住的是设计层缺口，记录但不放宽门禁。
3. 配方 7 个里的前两个：`three_line_table` + `mechanism_flow`（已有实测几何），与 spike 样张逐像素比对（差值报告，不靠眼睛）。
4. 封面 `cover_p1`：与 `00_v1_type_only.svg` 逐元素 diff。
5. `teaching_pair` / `section_anchor` + 生图路由 + 文档收口 + 三道门禁全链重跑 + 导出回读。

**回滚**：每批一个 commit；`git diff --stat` 保持可读；`template_renderer` 未删，任何一步失败都能退回原管线出完整交付。

**不做**：不重写 vendor、不改 `svg_to_pptx`、不动卡片重排、不批量回填历史 18 页（除非单独授权）；**不启用 vendor 的严格校验命令 `project_management/cli.py validate`**——它对现状 spec_lock 就报 22 条存量错误（`consumption_mode` 值域、`page_rhythm` 写法），接进来等于把本期变成 vendor schema 合规大扫除，与本 spec 目标无关。要接的话另立一项，并需先决定是改我们的写法还是改 vendor schema。

---

## 9. 验收标准（三层，缺一不可）

1. **机器层**：`check_narrative` blocking 0；`plan_contract` PASS；`qa_layout` 内容页 ALL CLEAR；`qa_score ≥ 80`；vendor `errors 0`；`quality_introduced_warnings 0`；`unsafe_exported_font_faces 0`；pptx 回读 shapes/runs/pics 与 SVG 逻辑单元对应。
2. **人读层**：只读全部 `assertion` 能复述论证链；封面一眼看到唯一主角；内容页一眼看到"断言在哪、证据在哪、so-what 在哪"。
3. **回归层**：既有 18 页工程在新门禁下**无任何一页变差**；`workflow_full` 剩余 30 项待修（本轮已证实是真问题）在 spec 落地后给出逐条处置。

三层里第 2 层不可被第 1 层替代——这正是本轮用三套样张证伪过的结论。
