# RUN-20261015 收口报告（2026-10-16）

> 执行：Qoder CLI 前台 + 兜底续跑会话（双轨台账）
> 真相源：`/Volumes/3TB_DATA/05-开发项目/ppt-studio`（main `1dcd971`→`275f517`+）、`/Volumes/3TB_DATA/05-开发项目/agnes-studio-work`（main `746a720`→`cb8d4e6`）
> 台账：`spikes/RUN-20261015/LEDGER.md`（每阶段两写）；阶段报告 13 份见 `spikes/RUN-20261015/reports/INDEX.html`

## 1. 交付总览

| 阶段 | 内容 | commit |
|---|---|---|
| S1–S4 | 台账基线、写作链（主题→文章→叙事）、编排 | ppt `9519bc1` `bf6fea4` `f0b008f`；AGNES `2f17afc` |
| S5 | 纯文字全链 E2E 出 deck + 看成品 | ppt `53968c5` |
| S6 | 三级配图路由 agnes/asset/vector（判据只加不松） | ppt `b0e75bf` |
| S7 | cairosvg 无浏览器栅格化旁路 | ppt `964908b` |
| S8 | Agnes 实采 12 张五指标验收 | ppt `5dc9a1c` |
| S9 | 海报三重门禁 + sach_01 + F1/F2 修复 | AGNES `ecae4d4`；ppt `ad85132` `c7a2a83` |
| S10 | 8089 平行实例 + /api/write-copy（8088 未动） | AGNES `cb8d4e6`；ppt `bc15709` |
| S11 | deck→海报双向出口桥接 | ppt `2992e10` |
| S12 | 知识回写 3T（3 卡 + 快照 + 进度行） | 3T 文件（非 git）；ppt `275f517` |
| S13 | 本报告 + 9 风险实测 | 本笔 |

## 2. 回归（S13 重跑，输出原样）

```
spec_tokens exit=0 通过 17 / 失败 0
plan_narrative exit=0 通过 34 / 失败 0
check_narrative exit=0 通过 26 / 失败 0
qa_layout_fixes exit=0 自检全部通过 ✅
qa_scale_and_contrast exit=0 通过 17 / 失败 0
plan_contract_sections exit=0 通过 9 / 失败 0
layout_recipes exit=0 通过 24 / 失败 0 / xfail 0
image_route exit=0 通过 19 / 失败 0
write_article exit=0 通过 26 / 失败 0
topic_to_deck exit=0 通过 29 / 失败 0
```

AGNES 侧：`test_poster_gate.py` 通过 12/失败 0（S9 实测；存量 `test_gemini_integration.py` 因硬禁 gemini 未运行，如实声明）。

## 3. 原计划末尾 9 条未闭环风险 · 逐条实测

1. **版心 60→76 会让页数增加**：run5 全链实测产出 **4 页**（00_cover + 3×bullets），`needs_split(max_bullets=4)` 触发 **0 次**（pipeline 控制台无拆页行）；「页数增加」在本主题短稿上未显现，长稿仍需人确认拆页粒度。
2. **`[尺度]/[网格]` 历史页大量命中是预期**：对 `projects/agentflow-os-launch` 7 页实跑 `qa_layout` → **待修 2 项**：«06» 一级标题同屏 5 次、«07» 同屏 2 次；对比度 7 页全部达标（最低 4.8:1，不达标 0/63）。"大量"实测为 2/7 页，仍只记录不回填。
3. **W-01/W-06 中文判定启发式、「、」误伤**：run5 四页标题含「、」计数 = **0**，本轮无实伤样本；误伤场景仍靠人读兜底（PASS 行只代表部分合格的声明保留）。
4. **照抄率 ≤40% 是本仓自定（D 级）**：复核确认 `check_narrative.py:13` `COPY_MAX = 0.40  # 本仓自定（D 级），非外部标准` —— 定性不变，无外部文献支持，本轮未调线。
5. **宋体标题投影糊笔画未实测**：本轮补测——`Songti.ttc` 56px + 4 向偏移深色投影渲染探针（`/tmp/songti_shadow_probe.png`），**目检笔画锐利无糊**；≥44px 档投影可用，推断转实测。
6. **封面 P1 亮/暗调色版需肉眼再确认**：run5 `00_cover.png` 已内嵌 S13 报告，**审美判定归用户，本轮不自我批准**。
7. **macOS 截图不代表 Windows 放映**：`FONT_FALLBACK_WIN` 复核在位（`vendor/ppt-master/scripts/svg_to_pptx/drawingml/utils.py:97`），导出仍走字体改写、无真嵌入；Windows 实机放映本轮未验证，遗留。
8. **vendor 严格 schema 与 `## grid` 冲突**：实测该命令**当前不可达**——vendored 副本里 `*.schema.json` 检索为 0 个文件，`validate_markdown_text` 先撞 `FileNotFoundError`（且该命令不在管线内）；冲突从「待处理」改判为「随 vendor 副本缺 schema 而搁置，接回前先补 schema」。
9. **`section_anchor` 新造几何无 spike**：本轮无独立 spike，但已进常驻门禁：`layout_recipes` 24/0 + run5 qa_layout ALL CLEAR（最低对比 11.4:1）为其现有全部证据，性质仍是「门禁+人读」，不虚报为已验证。

## 4. 合规扫描（收口实测）

- **密钥**：本轮新增 198 个文件逐一 `sk-` 扫描，3 处命中全部为测试令牌清单/扫描命令说明/打码占位（`sk-***`），**真实密钥明文 0 处**；3T 五份新产物扫描 5/5 归 0；两份 20261006 历史快照正文全程未复制。
- **垃圾文件**：全部本轮 commit 中 `cards/02_tension.svg`、`03_position.svg`、`._*` 命中 **0**（逐 commit `git show --stat` 扫描）；工作树除 S13 在途文件外干净。
- **判据**：`THRESHOLD_DEFAULT=80`、`WCAG_MIN=4.5`、`COPY_MAX=0.40`、needs_split max_bullets=4 等常量在 `git diff 1dcd971..HEAD` 中**零改动行**；本轮全部改动为收紧（F1 接入空转门禁、F2 颜色策略、五指标、三重门禁）。
- **红线**：8088 PID 2252 全程未动（lsof 前后留证）；未 push、未 stash、未 reset、未建 .env、未跑 pytest、未新增第三方依赖；生图调用 12/12 封顶内。
- **git log 对齐台账**：ppt 13 笔、AGNES 4 笔与台账逐行一致（§1 表），无未提交残留（S13 本笔除外）。

## 5. 遗留与下一批（同步进 ROADMAP.md）

见 `ROADMAP.md`「RUN-20261015 收口后 backlog」。8088→8089 切换、照片色相豁免口径、A/B/D 三项待决均归主控/用户，本任务 S13 后停止，不再自我排期。
