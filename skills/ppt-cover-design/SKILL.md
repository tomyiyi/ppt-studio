---
name: ppt-cover-design
description: PPT 封面与视觉主角规则（ppt-studio 设计层三 skill 之一）。当要做封面、章节隔页、需要"有视觉主角而不是氛围图压一行小字"时使用。含三种构图范式（纯排版尺度锚 / hero 图单边出血 / 全幅 duotone 压平）、clipPath 合规写法、agnes 生图红线、中文字体与许可表。含本轮实测证据：门禁 PASS 不等于有视觉主角。
agent_created: true
---

# 封面设计规则（视觉主角）

> 起因（用户原话）：**"封面没有"**、"不是现在只是放文字进去"。
> 本轮实测事实：三套封面样张 vendor 门禁同为 `errors 0`，仍被判"没有视觉主角"。
> **门禁 PASS 是必要条件，不是封面合格的判据。** 合格的判据是 §1 的单一主角测试。
> 证据级：**A**=一手原文 / **B**=页面要点或二手全文 / **C**=摘要或推断 / **M**=本轮实测第一方。

## 1. 单一视觉主角（封面第一原则）

| 编号 | 规则 | 判定 | 级 |
|---|---|---|---|
| C-01 | 整版**只允许 1 个 dominant 元素**，其余降为 secondary/tertiary；尺度差 **≥2.5 倍**；主角占画布 **60-65%** | 眯眼看：能否只看到一个东西 | B |
| C-02 | 可用超大数字/字母做尺度锚，高度占画布 **45-55%** | 量算 | B |
| C-03 | 尺度跳跃：封面标题 ≈ 副标的 **3-4 倍**、≈ 正文的 **5-6 倍** | 除法 | B |
| C-04 | 大标题行高 **1.08-1.12**（越紧越显专业）；标题占宽 **55-65%** | 量算 | B |
| C-09 | **1 个强调色，面积 ≤5%**；大字（≥18pt 或 14pt bold）对比 ≥3:1、小字 ≥4.5:1；只用 1 条 hairline 做骨架 | 面积算 + 对比度自检 | A |
| C-10 | **非对称网格优先，拒绝居中堆装饰**。高级感来自「对比度 + 留白 + 尺度跳跃 + 色板限制」，不是装饰 | 数装饰元素：>0 即疑 | B |

**实测参考（M）**：`poster 160px` 两行标题、行高 1.10（`y=330 / 330+176`）、中文**零字距**、唯一强调色块 `64×4`（面积 0.03%）、右栏 3 行 13px 目录锚压住右半空场。自检 `cjk(标题) × 字号 ≤ 画布宽 × 0.66`。

## 2. 三种构图范式（都已跑通门禁；**2026-10-08 用户裁决：默认基准 = P1 纯排版**）

| 范式 | 做法 | 实测样张 | 适用 |
|---|---|---|---|
| **P1 纯排版 + 尺度锚** ✅ **基准** | 无图。超大标题即主角，靠字号跨档 + 一条 hairline + 一个色块 | `00_v1_type_only.svg`（对比自检 0/11 不达标，最低 5.0:1） | **默认封面**；内部汇报、数据向、无合适配图时 |
| **P2 hero 图单边局部出血** | 图按整幅声明，`clipPath` 只露一侧；另一侧不透明纸面板放文字 | `01_v2_split_bleed.svg`（文字区 690/1280=54%，可见图区 46%） | 有强主体图、教学/品牌页 |
| **P3 全幅 duotone 压平** | 整幅图 + 单色压平 + **方向性**渐隐遮罩，文字落在图内净空区 | `02_v3_duotone.svg`（自检 0/7，最低 9.3:1） | 需要氛围但不能牺牲可读性 |

**关键工程解法（M，解决 X-02 冲突）**：既有门禁 `check_backdrop` 要求"最大 image 面积/画布 ≥90%"，而封面规范要求"局部出血 ≤40% 画布"。
→ **两者不矛盾**：`<image>` 仍按 1280×720 **整幅声明**（面积 100%，过门禁），用 `clipPath` 只**露出**局部。
反例：把 image 尺寸直接写成局部大小 → 触发 backdrop 与 clip 双重 blocking。

## 3. 遮罩与底图（含冲突裁决）

| 编号 | 规则 | 级 |
|---|---|---|
| C-14 | 遮罩**默认不加**。先过"图内有安静区 ≥30% + 柔光"的选图测试；失配才用**局部**、取图内暗调的 tint；遮罩只在图字交界一条渐隐 | B（guizang `image-overlay.md`，AGPL 只借规则） |
| C-16 | 渐隐必须**方向性**，禁整幅糊。实测可用台阶：`0→0.92 / 0.45→0.80 / 0.62→0.30 / 1→0.04` | M |
| C-15 | **最坏情况自检法**：底图保守取纯白，逐层合成压平色与遮罩色，取文字块**右端（遮罩最薄处）**校验对比。实现见 `gen_covers.py` 的 `v3_bg()/comp()/ramp()/check()` | M |
| C-17 | 卡片面板要让底图透出：`fill-opacity ≈ 0.66` | M |
| C-18 | 局部裁切合规写法：`<clipPath><path d="M690 0 H1280 V720 H690 Z"/></clipPath>`，`clip-path` 挂在 `<image>` 上。用 `<rect>` 局部裁切 = blocking；挂外层 `<g>` = blocking | M |

**裁决 X-01**：外部规范写"禁全幅底图压字、alpha ≤0.30"，实测 P3 用 `FLAT_A=0.34` 全幅压平 + 方向性遮罩**通过全部三道门禁且对比最低 9.3:1**。
→ 本仓不采"禁止"表述，改为**可判定条件**：全幅压平允许，但必须过 C-15 最坏情况自检（小字 ≥4.5:1）。压平系数不设死上限，由自检结果决定。

**亮底陷阱（M，X-21）**：底图 prompt 写亮/氛围 → band 亮度 0.48~0.76，白字压不住，只能靠加深遮罩硬救（WARN 18 条）。
→ **根因修法**：prompt 改暗调锚，band 亮度降到 0.001~0.005，遮罩系数从 ×1.04~1.23 收回 ×0.16~0.17，WARN 18→0。**先修图，别先修遮罩。**

## 4. 生图（agnes）红线

| 编号 | 规则 | 级 |
|---|---|---|
| C-19 | prompt 必须显式排除文字：`absolutely no text no letters no numbers no typography`。否则模型会画巨型字母，与标题打架（实测首张 `hero_duotone.png` 就是这样废掉的） | M |
| C-23 | 出图只走 `scripts/agnes_ppt_bridge.py --prompt … --filename … --project … --aspect-ratio 16:9`（模型 `agnes-image-2.5-flash`，输出 1312×736）。生图红线详见 `agnes-ppt-imagery` skill：**禁 gemini/dall-e/gpt-image/flux/seedream** | M |
| C-24 | 与论断无关的装饰性配图应删（实测 n=1941，装饰图对成绩无显著差异，p>0.35）；图要被注视足够久才起作用 | A/B |
| C-13 | 配图手法：主体高识别度、单边局部出血、降饱和或单色化；**文字不压图**，标题错开到图内净空区 | B |

## 5. 中文封面字体

| 编号 | 规则 | 级 |
|---|---|---|
| C-05 | 中文标题**不加字距**（汉字方格等分）；仅小字号英/数标签加约 `+0.05em`。（外部"大字号英文负字距 -0.003em@48px"来自 Apple HIG 页面的 noscript 回退 CSS，**不是 HIG 条款**，禁止当规范引用） | C |
| C-06 | 单字重标题体（得意黑等）层级只能靠**字号 + 颜色 + 位置**，不能假造 bold 轴 | B |
| C-07 | 标题用黑体族与正文区分（屏显规范）；汉字与拉丁/数字间隙 ≤1/4 汉字宽 | B |
| C-08 | 封面大数字用等宽数字（Menlo）；clreq 认比例数字适合 2-3 位场景 | B |
| C-11 | 文案：主标题 **≤12 字** + 副标题一句总结论 **≤24 字**，禁空洞口号；字段 `title_claim / subtitle_takeaway / audience_question / presenter+date` | C |

**投幕红线（M + L-36）**：屏显一律黑体。P2/P3 用了 96px **Songti** 做标题 —— 可读性风险仍在（细笔画投影会糊，真机未测），但**它不是导出告警的来源**：vendor 把 `Songti SC` 映射成 `SimSun`，属安全表内 face。

**字体告警归因更正（M，2026-10-08 实测）**：`POSTFLIGHT WARNING unsafe_exported_font_faces=1` 的**唯一**来源是黑体栈首站的 `STHeiti Light` —— 它既不在 `PPT_SAFE_FONTS`，也不在 `FONT_FALLBACK_WIN`（表里只有 `STHeiti`，不带 ` Light` 后缀），导出后是一个要求收件机自行安装的 face。
把栈首换成 **`Noto Sans SC`**（SIL OFL 1.1，黑苹果已装）后：`/checks/font_portability = passed`、`unsafe_exported_faces len=0`，三套封面 + 两页内容页 **warning 全部归零**；代价是 160px 标题字形变化（旧 STHeiti vs 新 Noto，标题区像素差 2.98%），见 `v1_font_ab.png`。

### 字体许可（决定能不能嵌进 pptx）

| 字体 | 许可 | 用途 | 级 |
|---|---|---|---|
| 思源黑体 `adobe-fonts/source-han-sans` | 文档标 **SIL OFL 1.1**（GitHub API 显示 NOASSERTION，以仓库文档为准） | 正文/黑体栈，7 字重 + 可变 | B |
| 霞鹜文楷 `lxgw/LxgwWenKai` | **OFL-1.1**（已读 README） | 正文替代 | A |
| 得意黑 `atelier-anchor/smiley-sans` | **OFL-1.1**（已读 README） | 标题体；**仅 1 字重 + Oblique，无 Bold/Black** → 见 C-06 | A |
| ZCOOL 快乐体 / 小薇 / 庆科黄油体 | **OFL**，各单字重 | 标题/装饰 | A |
| 阿里普惠体 2.0 / MiSans / HarmonyOS Sans | 免费商用但**自定义 EULA，非 OFL，原文未读** → 人工确认前不可嵌入 | — | C |
| pptx 嵌入限制 | MS 官方页（已读）：两点拦路——字体类型不受支持，或授权未授予嵌入权限。OFL 允许嵌入；`tnum` 支持需实测 | — | A |
| 本机黑苹果可用中文字体 | NotoSansSC(R/B/Black)、STHeiti Light/Medium、Hiragino Sans GB、Songti.ttc、ZCOOL KuaiLe/QingKeHuangYou、MaShanZheng、ZhiMangXing、SmileySans-Oblique；**无 PingFang SC** | — | M |

## 6. 复用仓库既有零件（不要重写）

| 零件 | 位置 | 用途 |
|---|---|---|
| 封面引擎 | `cover_v2.py`：`fit_font_size`（"the title is the design"）、`split_cover_title`、`generate_cover_copy`、`detect_mood`、`get_cover_font_family`、`COVER_VARIANTS{hero_full, split, minimal}` | **P1/P2/P3 应先复用它**，本轮 spike 未复用是已知偏差 |
| 封面辅助 | `cover_picker.py`、`cover_archetypes.py`、`agnes_design_cover.py`（agnes 海报引擎→封面素材）、`crop_panel.py`（按主体包围盒裁面板比例） | 主角选取与出血裁切 |
| 场景规格包 | ppt-master `templates/styles/*/templates/design_spec.md`（15 个） | 每场景版式默认值，可当 skill 的规格输入 |

## 7. 已裁决 / 未闭环

**已裁决（2026-10-08 用户）**：封面基准 = **P1 纯排版**（poster 160 两行 + 唯一强调色块，无图）。P2/P3 保留为"有强主体图 / 需要氛围"时的备选，不再是候选基准。

**未闭环（不得称已验收）**：

1. `poster: 160` 目前只在 spike 的 `spec_lock.md` 副本里，**未进契约真相源**。
2. **真·字体嵌入做不到（M 实测）**：vendor 的 `pptx_embedded_fonts.py` 只是"从**源 pptx** 捕获 `embeddedFontLst` 再随往返带出去"的 sidecar，`svg_to_pptx.py` **没有 `--embed` 参数**，无法从零把 OFL 字体打进新 deck。可达路径只有两条：① 交稿前在 PowerPoint 里勾"将字体嵌入文件"；② 自己写包级后处理（`embeddedFontLst` + font parts + content-types + rels）。→ 需在 spec 里裁决走哪条。
3. **导出 face 会被统一改写（M 实测）**：`FONT_FALLBACK_WIN` 把 `Noto Sans SC` / `PingFang SC` / `Hiragino Sans GB` / `Source Han Sans SC` 全部映射成 `Microsoft YaHei`，`Songti SC` → `SimSun`。含义：**macOS 截图看到的字形从来不代表 Windows 放映效果**，任何"字体好不好看"的判断都要按"最终落到雅黑/宋体"来评估。
4. 宋体标题（P2/P3）在投影仪上的糊笔画**未实测** —— 与告警无关，是独立的可读性风险。
5. C-24 的 n=1941 结论来自 CRL 同行评审正文，但**效应量口径未逐字复核**，引用时保留"无显著差异"的定性表述。
