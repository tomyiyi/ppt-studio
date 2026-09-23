# ppt-studio

把一份「会说话的内容」变成**一套可传播的多形态物料**：先美化成有设计感的 PPT，再导出 HTML / PPTX / 卡片图，未来接上视频与配音。

不是模板库，也不是又一个 PPT 生成器。它是一条**可验证的流水线**：内容 → 版式规格 → 配图 → SVG 画布 → PPTX / HTML → 质检。每一步都有脚本、有指标、有闸门，而不是「生成完就交」。

---

## 目标（这条线要走到哪）

> 我想 PPT 可以美化好，可以 HTML、PPT、精美的、视觉的，之后又可以变成卡片式方便传播，计划未来可以转换成视频 + 有配音的内容。

拆成四个形态，一条链路喂全部：

| 形态 | 用途 | 状态 |
|---|---|---|
| **PPTX** | 线下汇报 / 发布会大屏 / 交付存档 | ✅ 已通 |
| **HTML** | 网页翻页、嵌进文章、分享链接 | ✅ 已通 |
| **卡片图** | 微信 / 小红书 / 社群传播，1080×1350 竖版 | ✅ 已通 |
| **视频 + 配音** | 抖音 / B 站 / 视频号 | 🔜 规划中 |

四个形态共用同一份 **SVG 画布**作为唯一真源 —— 画布是 1280×720 的矢量底稿，往后切卡片、切视频分镜都是同一份源的不同裁切，不需要重做设计。

---

## 现在能跑通什么

以 `projects/agentflow-os-launch`（智流 OS 发布会，7 页）为完整样例：

```
内容笔记 (notes/*.md)
    ↓
spec_lock.md        ← 横版版式契约：字号阶梯 / 色板，全项目唯一真源
    ↓
SVG 画布 (svg_output/*.svg)   ← 1280×720，图做满幅底图，文字压在暗面上
    ↓
Agnes 配图 (images/*.png)     ← 生图只走 Agnes，gemini 不参与生图
    ↓
├→ PPTX    原生 DrawingML（不是贴图，文字可编辑、图形可改）
├→ HTML    单文件预览，含全部内嵌资源
└→ 卡片    1080×1350 竖版重排（不是拉伸裁切，见下）
    ↓
qa_layout.py   ← 横版 7 项质检
qa_cards.py    ← 卡片 7 项质检
```

### 卡片不是「把横版裁一裁」

16:9 直接 slice 成 3:4 会横向砍掉 55% 的画面，横版的字号在手机上也会小到读不清。
所以 `make_cards.py` 做的是**重排**：从 SVG 抽取内容要素（主句 / 副句 / 指标 / 徽章），
换一套竖版字号阶梯（28→132，比横版大得多），重新排版。

三个关键设计：

- **自适应图片带**（40%–62%）。内容少 → 图涨到 62%，不留下半屏空白；内容多 → 图让位到 40%。固定比例会让「只有一句主句」的卡片空一半（实测面板墨量 2.96%）。
- **装不下就按优先级砍**。卡片只装得下一个主张：先砍副句，再减指标。02 页因此保留了三个数字、丢了场景描写——数字比正文更适合卡片。
- **主句左侧 6px 强调竖线**是所有卡片统一的签名元素。

最后一步不是可选项。交付前必须跑质检 —— 这条是本项目的工作纪律，不是建议。

---

## 目录

```
ppt-studio/
├── scripts/                      8 个流水线脚本（见下表）
├── skills/agnes-ppt-imagery/     配图 Skill：提示词写法 + 14 条避坑 + 验收流程
├── projects/
│   └── agentflow-os-launch/      完整样例项目
│       ├── spec_lock.md          版式契约（字号阶梯 / 色彩 / 栅格）
│       ├── notes/                7 页内容笔记
│       ├── images/               10 张成品图 + image_prompts.json
│       └── svg_output/           7 页 SVG 画布
├── docs/
│   ├── workflow.md               完整工作流与踩坑记录
│   └── qa-checklist.md           交付前质检清单
├── output/                       已产出的 PPTX / HTML
└── ROADMAP.md                    四形态演进计划
```

---

## 脚本

| 脚本 | 干什么 |
|---|---|
| `agnes_ppt_bridge.py` | 读 `image_prompts.json` 批量调 Agnes 生图；内置模型黑名单，**拦截 gemini / gpt-image / flux 等** |
| `prepare_agnes_image.py` | 生图后处理：裁到 16:9、自动检测并消除拼缝、亮度归一 |
| `analyze_image.py` | 客观量化一张图：锐度、主体位置 3×3 分布、墨量、接缝检测 |
| `crop_panel.py` | 按主体包围盒裁切，让主体撑满面板而不是缩在中间 |
| `boost_ink.py` | 保黑点的增益（背景不被抬灰），救偏暗的图 |
| `render_svg.py` | SVG → PNG 渲染，供质检和预览用 |
| `build_preview.py` | 把若干 SVG 打包成单文件 HTML 翻页预览 |
| `make_cards.py` | 横版画布 → 1080×1350 竖版卡片（重排，非裁切） |
| `qa_layout.py` | **横版质检闸门**：7 项检查，字号阶梯直接从 `spec_lock.md` 读 |
| `qa_cards.py` | **卡片质检闸门**：7 项检查，阶梯从 `card_spec.md` 读 |

### 跑一遍样例

```bash
cd projects/agentflow-os-launch

# 1. 配图（只在缺图时跑，已有图会跳过）
python3 ../../scripts/agnes_ppt_bridge.py --manifest images/image_prompts.json

# 2. 渲染成 PNG，供质检读取像素
python3 ../../scripts/render_svg.py svg_output/ render/

# 3. 质检（必跑）
python3 ../../scripts/qa_layout.py svg_output/ render/

# 3b. 出卡片（可选，同一份 SVG 的第三个出口）
python3 ../../scripts/make_cards.py .            # → cards/
/opt/homebrew/bin/python3 ../../scripts/render_svg.py cards/ render_cards/
python3 ../../scripts/qa_cards.py cards/ render_cards/
```

质检全绿会打印 `ALL CLEAR`。任何一项有告警，先改 SVG 再交付。

---

## 两条铁律

**1. 生图模型只用 Agnes。** 语言模型（gemini 反代）负责文案与规划，生图一律走 Agnes Studio / New API（`http://127.0.0.1:3000/v1`）。`agnes_ppt_bridge.py` 内置黑名单会硬性拦截 `gemini-*-image` 之类的模型名 —— 不是性能问题，是明确的约束。可用模型：`agnes-image-2.5-flash`（主）、`agnes-image-2.1-flash`。

**2. 做完要验证，不能凭 "跑通了" 就交付。** 返回码成功 ≠ 结果正确。本项目踩过的坑里，有一半是脚本本身在骗人（比如质检脚本没解析父节点继承的 `font-size`，把 56px 大标题读成 16px，整张审计表都是错的）。所以：写完改完，跑 `qa_layout.py`，读它的输出，再说"好了"。

---

## 环境

- Python 3.13 + `Pillow` / `numpy`（图像分析）
- `cairosvg` 或 Playwright/Chrome（SVG 渲染）
- ppt-master 的 SVG→PPTX 转换器（SVG 画布 `viewBox="0 0 1280 720"`，边距 60px）
- Agnes Studio / New API 本地端点（生图）

---

## License

MIT
