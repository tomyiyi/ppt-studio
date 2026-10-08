---
title: workflow_full 全量带图 deck 归档说明
type: note
status: verified
created: 2026-10-08
tags: [ppt-studio, 交付物]
---

# workflow_full（18 页 · 带图 · 真实文章）

- 成品：`output/workflow_full.pptx`，18 页 / 4,815,824 字节（`unzip -l` 数得 18 张 slide）。
- 门禁：`plan_contract.py` → 页面 18，错误 0，警告 0，PASS；vendor `svg_quality_checker.py --canonical-authoring --stage final` → errors 0、blocking 0、warnings 18（全部为模板级 noncanonical-authoring 建议项，与本次内容无关）。
- 生图：18/18 成功（agnes-image-2.5-flash，1312x736），`images/image_prompts.json` 有完整 prompt 台账。
- 底板明度：首版 18 张全是亮底（文字带亮度 0.48~0.76），遮罩必须压到 0.62~0.76 才够 4.5:1，底图被压成黑块；改暗调 prompt 后重出，文字带亮度降到 0.001~0.005，遮罩系数 x0.16~0.17，亮底 WARN 从 18 条归零。
- 版式回退：第 8 页（"5. 画 SVG 画布"）在 hero-side 槽位放不下全部条目，按设计弃底图改纯文字版式；该页正文字色已由 `#94A3B8`（对白底 2.56:1）收口为 `#475569`（6.99:1）。
- 本机独立复核：Chrome headless（1920x1080）截图确认第 8 页 4 条、第 13 页 3 条内容完整上屏；`pages.json` 全量 54 条中最长 85 字，未触发 160 字裁剪上限（即无静默截断）。

## 未闭环

- 源 md 的确切路径未确认（构建时在 `/tmp` 下，已被后续同名文件覆盖风险）。本目录的 `pages.json` + `spec_lock.md` 可复现渲染阶段，但**不能**复现"文章 → 分页"这一步；如需完全可复现，请补回源 md 到本目录并命名为 `source.md`。
