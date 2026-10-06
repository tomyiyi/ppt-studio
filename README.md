# ppt-studio

**内容 → 多形态物料的可验证流水线。** 一份内容笔记，先变成 1280×720 的 SVG 画布（唯一真源），再经质检闸门分出三条出口：原生 PPTX、单文件 HTML、1080×1350 传播卡片。每一步都有脚本、有指标、有闸门——不凭"跑通了"交付。

[![CI](https://github.com/tomyiyi/ppt-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/tomyiyi/ppt-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-3776AB?logo=python&logoColor=white)](scripts/)

---

## 架构

```
内容笔记 (notes/*.md)
        │
        ▼
版式契约 spec_lock.md ── 字号阶梯 / 色板 / 栅格，全项目唯一真源
        │
        ▼
SVG 画布 (svg_output/*.svg)   ◄── 1280×720，唯一真源
        │                        配图只走 Agnes（见"配图铁律"）
        ├─► render_svg.py ──► PNG 预览
        │         │
        │         ▼
        │   qa_layout.py ── 7 项质检闸门 ──► ALL CLEAR ✅
        │
        ├─► make_cards.py ──► cards/*.svg（1080×1350 重排，非裁切）
        │         │
        │         ▼
        │   qa_cards.py ── 7 项卡片质检 ──► ALL CLEAR ✅
        │
        ├─► build_preview.py ──► 单文件 HTML 翻页预览
        │
        └─► PPTX 出口（外部依赖，见下）
              ① svg_quality_checker.py（外部）门禁 blocking=0
              ② svg_to_pptx.py（外部）──► 原生 DrawingML，可编辑
```

## 样例项目

`projects/agentflow-os-launch/`（产品发布会物料）是完整可跑的样例：7 页内容笔记、7 张 SVG 画布、11 张配图。

## QuickStart（已在干净 venv 实测）

```bash
git clone https://github.com/tomyiyi/ppt-studio.git
cd ppt-studio

python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -r requirements.txt
# SVG 渲染用 Playwright 驱动系统 Chrome；若本机装了 Google Chrome，
# render_svg.py 会直接用它，无需 python -m playwright install chromium

cd projects/agentflow-os-launch

# 1. 渲染 SVG → PNG（供质检读像素）
python3 ../../scripts/render_svg.py svg_output/ qa_render/
# 2. 横版质检闸门（必跑）
python3 ../../scripts/qa_layout.py svg_output/ qa_render/
# 3. 竖版卡片（同一份 SVG 的第二个出口）
python3 ../../scripts/make_cards.py .
python3 ../../scripts/render_svg.py cards/ qa_cards_render/
python3 ../../scripts/qa_cards.py cards/ qa_cards_render/
# 4. 单文件 HTML 预览（可选）
python3 ../../scripts/build_preview.py svg_output/ preview.html "发布会预览"
```

两道闸门都输出 `ALL CLEAR ✅` 才能往下走；任一告警先改 SVG 再交付。
（实测：Python 3.14.6，macOS，干净 venv 按上装依赖；render_svg 渲染 7 页约 13 秒，make_cards 生成 7 张 1080×1350 卡片，qa_layout 与 qa_cards 均为 `ALL CLEAR ✅`。注：qa_layout 含像素级对比分析，7 页约 2–3 分钟，属正常。）

> 配图生成（`agnes_ppt_bridge.py`）只在缺图时跑：读 `images/image_prompts.json` 批量调 Agnes 生图，已有图自动跳过。需要本机 New API（`http://127.0.0.1:3000/v1`）。

## PPTX 出口（诚实说明）

PPTX 转换**不在本仓库**：`svg_to_pptx.py` 是兄弟目录 `ppt/tools/ppt-master` 的外部依赖（vendoring / submodule 待定，本仓库不复制）。导出是两步，不是"一键直达"：

```bash
PPT_MASTER=/Volumes/3TB_DATA/05-开发项目/ppt/tools/ppt-master   # 按你的实际路径改
# 1. 质量门禁：blocking 必须为 0，否则不许转
python3 $PPT_MASTER/skills/ppt-master/scripts/svg_quality_checker.py \
    projects/agentflow-os-launch --canonical-authoring --stage final --json
# 2. 转换（原生 DrawingML：文字可编辑、图形可改，不是贴图）
python3 $PPT_MASTER/skills/ppt-master/scripts/svg_to_pptx.py \
    projects/agentflow-os-launch -o output/deck.pptx
# 3. 回读验证：unzip -q output/deck.pptx -d /tmp/chk，核对 ppt/media/ 文件数与每页 <p:pic> 数量
```

SVG 画布约定：`viewBox="0 0 1280 720"`，边距 60px。

## 脚本（11 个，全部在本仓库）

| 脚本 | 干什么 |
|---|---|
| `agnes_ppt_bridge.py` | 读 `image_prompts.json` 批量调 Agnes 生图；内置模型黑名单，硬性拦截 gemini / dall-e / gpt-image / flux / seedream |
| `prepare_agnes_image.py` | 生图后处理：等比放大居中裁到精确 16:9、消除拼缝、压暗归一 |
| `analyze_image.py` | 配图客观验收：锐度（拉普拉斯方差）、主体 3×3 位置分布、墨量、接缝检测 |
| `crop_panel.py` | 按主体包围盒裁切，让主体撑满面板而非缩在中间 |
| `boost_ink.py` | 暗底线性图提亮：黑点保持 + 高光增益，背景不被抬灰 |
| `render_svg.py` | SVG → PNG（Playwright 驱动系统 Chrome；`<image href>` 自动内联 base64） |
| `build_preview.py` | 若干 SVG → 单文件 HTML 翻页预览（图片内联 data URI） |
| `make_cards.py` | 横版画布 → 1080×1350 竖版卡片：内容要素重排（自适应图片带 40%–62%，装不下按优先级砍） |
| `qa_layout.py` | 横版质检闸门：溢出 / 字号阶梯 / 底图 / 重复图片 / 面板墨量 / 压行 / 对比度，7 项 |
| `qa_cards.py` | 卡片质检闸门：字号 / 安全区 / 溢出 / 压行 / 对比度 / 底图 / 留白，7 项 |
| `run_auto_poc.py` | auto_poc 双画幅（16:9 + 4:3）SVG 生成管线，POC 验证用；模板目录从外部 ppt-master 推导（`--tpl-169-dir` / `--tpl-43-dir` 可覆盖） |

## 配图铁律

**生图只走 Agnes。** 本机 `gemini-*` 是反代文本通道，没有可靠的图像生成能力；`agnes_ppt_bridge.py` 的 `BLOCKED_IMAGE_MODELS` 会硬性拦截 `gemini / dall-e / gpt-image / flux / seedream`，命中即跳过并告警。可用模型：`agnes-image-2.5-flash`（优先）、`agnes-image-2.1-flash`，经本机 New API（`http://127.0.0.1:3000/v1`）。

## Troubleshooting

| 现象 | 真因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: PIL / playwright` | 用的解释器和装依赖的不是同一个 | 全程用同一个：`.venv/bin/python`，或 `python3 -m pip install -r requirements.txt` 装到当前 `python3` |
| `render_svg.py` 打印 `[warn] 缺图 ../images/x.png` | SVG 引了不存在的图片 | 补图或先跑 `agnes_ppt_bridge.py`；注意路径是相对 SVG 文件的 |
| `qa_cards.py` 打印 `[warn] 缺 numpy/Pillow，跳过像素级检查` | 像素级检查被静默跳过，闸门变弱 | `python3 -m pip install -r requirements.txt` 装齐再跑 |
| `make_cards.py` 打印 `[skip] xx.svg 无可提取内容` | 该页抽不到主句/指标 | 检查 SVG 文本层；纯装饰页可接受 skip |
| 质检报 `[溢出]` / `[压行]` | 文本超出安全区或行框重叠 | 改 SVG（缩字号/删副句），不要调质检阈值 |
| 卡片下半屏空白 | 图片带高度写死 | `make_cards.py` 已按内容量自适应 40%–62%；若还空，说明该页内容要素太少，补指标或副句 |
| 小字对比度不足 | `tertiary_text` 颜色太浅 | 改 `#7F8090`（4.75:1）起步，WCAG ≥ 4.5:1 |

## 目录

```
ppt-studio/
├── scripts/                  11 个流水线脚本（见上表）
├── skills/agnes-ppt-imagery/ 配图 Skill：提示词写法、避坑、验收流程
├── projects/
│   ├── agentflow-os-launch/  完整样例（7 页）
│   ├── auto_poc/             双画幅 POC 产物
│   └── workflow_poc/
├── docs/
│   ├── workflow.md           完整工作流与踩坑记录
│   └── qa-checklist.md       交付前质检清单（含 PPTX 回读步骤）
├── output/                   已产出的 PPTX / HTML
├── requirements.txt          pillow / numpy / playwright
├── ROADMAP.md                四形态演进计划（视频 + 配音在路上）
└── LICENSE                   MIT
```

## 延伸阅读

- `docs/workflow.md` —— 从内容笔记到交付的完整工作流，含"常见翻车档案"
- `docs/qa-checklist.md` —— 交付前逐项核对清单
- `skills/agnes-ppt-imagery/SKILL.md` —— 配图提示词写法与 14 条避坑

---

## 🌐 English Summary

**ppt-studio** is a verifiable content → multi-format publishing pipeline. A content brief becomes a 1280×720 SVG canvas (single source of truth), then passes QA gates (`qa_layout.py` / `qa_cards.py`, 7 checks each, both must print `ALL CLEAR`) into three outputs: native editable PPTX, single-file HTML slide preview, and 1080×1350 social cards (reflowed for vertical, not cropped). Image generation goes exclusively through Agnes (other model families are hard-blocked). The PPTX converter (`svg_to_pptx.py`) lives in the sibling `ppt/tools/ppt-master` repo and is an explicit external dependency with a quality gate (`svg_quality_checker.py`, blocking=0) before conversion. Video + narration is on the roadmap.

## License

MIT · 欢迎提 Issue 和 PR。
