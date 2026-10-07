# Vendored: ppt-master

来源：https://github.com/hugohe3/ppt-master（MIT License，Copyright (c) 2025-2026 Hugo He）
版本：176235a3d6fae8f37edfc898d2c7f5ef418cf65a（vendor 日期 2026-10-07）

内容：上游 `skills/ppt-master` 的子集——SVG 质检与 PPTX 转换所需的 `scripts/`，
以及完整性门禁要求的 `SKILL.md` / `LICENSE` / `SPONSORS.md` / `SPONSORS_CN.md`
（门禁做 SHA 校验，一字未改）。

未包含：`templates/`（3.1GB 模板库；`run_auto_poc.py` 的模板生成功能仍需外部提供，
用 `PPT_MASTER_ROOT` 环境变量指定）、`references/`、`workflows/`。

注意：`scripts/attribution_guard.py` 每次调用都会做完整性校验，
不要删减门禁文件，不要修改 LICENSE / SKILL.md 中的署名元数据。
