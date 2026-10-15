# RUN-20261015 断点台账 — PPT Studio

**这是唯一续跑依据。** 新会话/中断后接手，必须先做三件事再动代码：
1. 读本表**最后一行**的 `下一步` 与 `未决`。
2. 原样贴出 `git -C /Volumes/3TB_DATA/05-开发项目/ppt-studio log --oneline -1` 与 `git status --porcelain` 的结果，证明接的是真实现场而不是猜测的现场。
3. 跑基线自检 `for t in spec_tokens plan_narrative check_narrative qa_layout_fixes qa_scale_and_contrast plan_contract_sections layout_recipes image_route; do python3 scripts/test_$t.py; done`，**红了先判"半截实现"还是"真缺陷"，不得改判据凑绿**。

计划全文：`/Users/tom/.qoder-cn/plans/wise-oasis-wolf.md`（RUN-20261015）。

## 硬约束（沿用 `spikes/CONTINUE-2026-10-09.md`，违反即停）

- `git add` 只按文件名精确添加；**禁止** `git add -A` / `git add .` / `git stash` / `git reset --hard` / **push**。
- 每次提交后 `git show --stat HEAD | grep -c 'cards/'` 必须 0，`grep -c '\._'` 必须 0。
- 禁止修改任何阈值/判据/上限让检查通过（qa_score 80、WCAG_MIN、照抄率 40%、列数 ≤5、节点数 ≤6、`[尺度]` 判据）。放宽是决策，归主控。
- 禁止 pytest、禁止新增第三方依赖（标准库 + 已有 numpy/Pillow/playwright/python-pptx）。测试一律 `scripts/test_*.py` + `ok(name, cond)` + 退出码。
- 报告/日志/commit 里严禁出现任何 api key 明文；禁止创建或修改 `.env`。
- 闸门不过就停下写 `spikes/RUN-20261015/FAILURE.md`（实际命令+实际输出+根因+需要主控决定什么），不得跳批。
- 无人值守期不自动写叙事 `_todo` 文案；需要成文走 S2/S3 的显式主题入口。
- Chrome 纪律：单次 Playwright 批 ≤6 页、批间退出进程；验证循环优先 cairosvg 旁路（本机 10-02/10-13 两次 WindowServer 看门狗 panic，长跑少开浏览器）。

## 现场基线（2026-10-15 23:0x 实测）

| 项 | 实测值 |
|---|---|
| HEAD | `6ffe46a fix(write_article): 来源标注改全角括号，"覆盖 N 个"补空格` |
| 工作树 | 仅 2 个未跟踪笔记：`spikes/CONTINUE-2026-10-09.md`、`spikes/PROGRESS.md`；无已跟踪文件改动 |
| 基线自检 | 8 个套件全 exit=0：spec_tokens 17/17、plan_narrative 17/17、check_narrative 22/22、qa_layout_fixes 全绿、qa_scale_and_contrast 17/17、plan_contract_sections 9/9、layout_recipes 24/24/0xfail、image_route 9/9 |
| 10-06 未合并分支 | `06-agent资源/repos/ppt-studio.git` 的 `fix/blackapple-review-20261006` @ `0f96603`，相对其 main **246 files / +38773 / -2072**，含整套 `tests/` 与 `themes/dark-editorial.json`。**只读存档，本轮不合并、不推送** |
| 配图现状 | `check_narrative.py:25` `VALID_IMAGE_INTENTS = {"none","background","panel","hero"}`；`test_image_route.py` 9/9 绿但**实际路由为 none**，即配图链路未通 |

## 阶段台账

| 开工 | 收工 | 阶段 | commit | Verify 摘要 | 产物 | 下一步 | 未决 |
|---|---|---|---|---|---|---|---|
| 2026-10-15 23:05 | — | S1 现场自证+台账 | 进行中 | 8 套件基线全绿（见上表）；现场自证已贴 | `LEDGER.md` + `S01-baseline.html` | 提交 S1，测 qoder_cron 兜底能力，转 S2 | 无 |
