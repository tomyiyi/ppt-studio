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
| 2026-10-15 23:05 | 2026-10-15 23:46 | S1 现场自证+台账 | `1dcd971` | 8 套件 exit=0（17/17/22/自检通过/17/9/24/9），输出留档 `baseline-suites.txt`；卫生扫描 cards=0 junk=0；`qoder_cron` 兜底任务**实测可建**，id `9bd5eb3b-57a2-49d1-ad0d-1fc549f7d9eb`，每 2h、`expiresAt` 2026-10-16 20:00、含"判活"防踩踏逻辑 | `LEDGER.md` + `reports/S01-baseline.html` + `baseline-suites.txt` | **S2 写作 skill**：`skills/article-writing-from-topic/SKILL.md`(T-01…T-12) + `scripts/test_write_article.py` | 兜底任务以 `bypassPermissions` 落盘，若需收敛权限由主控裁决 |
| 2026-10-15 23:50 | 2026-10-16 00:05 | S2 写作 skill | `9519bc1` | 夹具链离线跑通（verified 5 / unverified 3 / sections 5）；`test_write_article.py` 26/0；原 8 套件回归全 exit=0 且未动任何判据 | `skills/article-writing-from-topic/SKILL.md`、`patterns/writing/extract_hook.md`（成文版）、`scripts/test_write_article.py`、`scripts/write_article.py`（4 处缺陷修正）、`spikes/RUN-20261015/fixtures/*`、`reports/S02-writing-skill.html` | S3 `topic_to_deck.py` | 导语规则版只能报条数（走 `--hook` 需显式产出，无人值守禁自动写）；同注册域算双源、服饰白名单失真——两项门禁口径变更交主控裁决 |
| 2026-10-16 00:00 | 2026-10-16 00:12 | S3 单入口编排 | `bf6fea4` | `test_topic_to_deck.py` 27/0（全桩、零子进程）；`--dry-run` 计划正确；真实跑到 gate **blocking 16 条、exit=3、deck 未调用**（修复素材根传错前为 19 条）；`--resume` 实测把调用从 5 降到 4 | `scripts/topic_to_deck.py`、`scripts/test_topic_to_deck.py`、`spikes/RUN-20261015/e2e/run1/*`（含 `FAILURE.md`、`state.json`）、`make_index.py`、`reports/S03-topic-to-deck.html` | S4：claim 段落→evidence 确定性抽取 + `image_intent` 对账（判据只加不松） | **三项待主控裁决**见 `e2e/run1/FAILURE.md`：A 是否做散文→evidence；B 8 条 so_what 走人工/`--hook`/留档；C S5 是否接受"旧路径出 deck + 门禁原样留档"形态 |
| 2026-10-16 00:20 | 2026-10-16 00:40 | S4 配图意图对账 | 本笔（`git log --oneline -1` 即 S4 提交） | `test_plan_narrative.py` 17→**34/0**、`test_check_narrative.py` 22→**26/0**、`test_topic_to_deck.py` 27→**29/0**（只加不删）；10 套全量回归 exit 全 0（`regression-s4.txt`）；真实链路重跑 `e2e/run2`：**blocking 16 持平 / 需人读 10→11**（新增 W-30 登记）；声明 2 页的演示 `e2e/intent-demo`：blocking **16→18**（2 条 W-27），被声明页 `image_prompt` 长度 378、未声明页 0 | `scripts/plan_narrative.py`（`--intent-plan`/`IntentPlanError`/`apply_intent`/`sync_todo`/`load_json_arg` + 行号·列表标记·表格分隔行三处修正）、`scripts/check_narrative.py`（W-30）、`scripts/md_to_pages.py`（意图与来源透传、旧路径显式 intent）、`scripts/topic_to_deck.py`（`--intent-plan` 透传，不自动生成）、3 个测试文件、`e2e/run2/*`、`e2e/intent-demo/*`、`regression-s4.txt`、`reports/S04-narrative-intent.html` | S5 纯文字全链 E2E 出 deck 并**看成品** | 判据一律未动（COPY_MAX 0.40 / W-01…W-29 / qa 80 / WCAG / ≤5 列 / ≤6 节点 / 合法意图集未增删）。**S3 计划里的"claim 段落→evidence 确定性抽取"这半件我没做**：塞散文进 evidence 会让 6 条 W-07 自动消解，等于喂内容给门禁，属放宽判据的另一种写法，交主控裁决（A）。另三项待裁决：B 8 条 so_what、C S5 形态、**D 新发现：W-18 照抄率在文章→deck 路径是哑的**（`check_narrative.main()` 的 `src_text` 只读 `base_dir/README.md`）——接上 `article.md` 只需几行，但会把"逐字挑选的证据"全判超限，这是规则误用还是应当启用，由主控定，我不擅自改判据适用范围 |
| 2026-10-16 01:43 | 2026-10-16 01:43 | 兜底心跳 | 无（HEAD 仍为 `f0b008f`，00:25:48 +0800） | 前台仍在跑，最近 commit=`f0b008f`，本次未动代码；判活依据：台账末行收工 00:40（距 1h03m）、commit 00:25（距 1h17m）均 <2h；`git status --porcelain` 为空；AGNES 侧 HEAD `746a720`、`docs/reports/RUN-20261015/LEDGER.md` 有未提交改动（前台正在写，未触碰） | 无 | 由前台会话继续 S5 | 无新增 |
| 2026-10-16 03:47 | 2026-10-16 04:05 | S5 纯文字 E2E（兜底接管） | 本笔（`git log --oneline -1` 即 S5 提交） | 接管判活（03:42 实测）：commit `f0b008f` 距 3h17m、真实收工 00:40 距 2h59m 均 >2h，01:43 末行为兜底心跳不计前台活性⇒前台中断，自 S5 接续；AGNES 侧遗留台账改动收编为 `2f17afc`。全链 `md_to_pptx.py --no-images` **exit=0、8 页 deck**（`e2e/run3/deck/远程交付团队的周会节奏.pptx` 25KB，`unzip -l` slide=8/共33文件）；qa_layout 独立重跑 **ALL CLEAR ✅ exit=0**（修复前待修 16 项）；qa_score **8 页全 100**（阈值 80）；回归 10 套件全 exit=0（`e2e/run3/regression-s5.txt`）；成品经 cairosvg 旁路栅格化**目检**（报告内嵌 8 图）：可用，遗留润色 2 项入 S13 backlog（封面导语硬换行/02 页偏空）。**形态如实声明**：deck 走旧路径（C 预演），run2 门禁 **blocking 16 条原样未动** | `scripts/template_renderer.py`（`_align_to_spec_lock` 阶梯/边距对齐 + 封面引文接通，**未动任何阈值/判据**）、`e2e/run3/*`（console/qa 输出、svg、png_preview、pptx）、`reports/S05-e2e.html`、`INDEX.html` | S6 三级配图路由 | A/B/D 三项仍待主控裁决 |
| 2026-10-16 04:10 | 2026-10-16 04:15 | S6 三级配图路由（兜底续跑·收工） | 本笔（`git log --oneline -1` 即 S6 提交 `feat(image): 三级配图路由（判据只加不松）`） | 判活复查（03:58 第二次引导消息后）：前台真实 commit `f0b008f` 距 >3.5h，台账近三条均为兜底自身写入不计活性⇒继续接管。`source_illustration.py --report` 实测 4 库仅 article-poster-generator(MIT,作者自产示例) 可用，其余 3 库按红线排除（无 LICENSE×2 / 代码授权≠画作权利×1），素材 11 条；`--query "架构 留白"` 选中 grid.png score=4 并落出处 prov.json；`test_image_route.py` **通过 14/失败 0**（原 9 + D1–D5 只加不减，含真实 Agnes 生图 1 次系存量用例、在授权额度内）；10 套件回归全 exit=0（`e2e/run3/regression-s6.txt`）；asset-demo `qa_layout` **ALL CLEAR ✅ exit=0**；`gen_images()` 三级路由 + 修 `zip(pages,items)` 回写错位真缺陷（manifest 带 page_index）；**判据/阈值零改动**；目检发现两个渲染环境真问题并给出根因：① cairosvg 2.9.1 默认 unsafe=False 把外链图替换为 32 字节占位符（图"消失"真因，非生图失败）② 字体族名 SmileySans（无空格）cairo 精确解析不命中→豆腐块（"Smiley Sans"/PingFang SC/Noto Sans SC 正常）；如实声明 03:53 同文件曾渲染正常、当前无法复现该状态（疑 fontconfig 缓存重建），S5 已提交预览不回改 | `scripts/source_illustration.py`（新）、`scripts/check_narrative.py`、`scripts/plan_narrative.py`、`scripts/md_to_pptx.py`、`scripts/test_image_route.py`、`data/asset_index.json`、`e2e/asset-demo/*`（pages/deck/preview/preview_fixed）、`e2e/run3/regression-s6.txt`、`reports/S06-image-route.html`、`INDEX.html` | S7 cairosvg 无浏览器栅格化旁路（必做：unsafe=True + 字体族名规范化 + SVG 与相对资源同目录渲染） | asset 叠字观感→S9；素材池仅 11 条→S13 backlog；A/B/D 三项仍待主控裁决 |
