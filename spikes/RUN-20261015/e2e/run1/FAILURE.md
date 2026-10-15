# FAILURE：S3 真实跑到 gate 段被拦（deck 未产出）

**这不是编排层的失败，是"文章→叙事"这一段本来就缺东西。** 按纪律停在这里并如实记录，不跳过、不放宽。

## 实际命令

```
python3 scripts/topic_to_deck.py \
  --topic "远程交付团队的周会节奏（测试夹具）" \
  --workdir spikes/RUN-20261015/e2e/run1 \
  --brief spikes/RUN-20261015/fixtures/topic_brief.json \
  --injected spikes/RUN-20261015/fixtures/injected.json \
  --no-images
```

## 实际输出（尾部原样）

```
blocking 16 条 / 需人读 10 条
FAIL(部分)：可机械判定的 W-xx 有 blocking。
[停] 叙事门禁 blocking 16 条——按纪律不跳过、不放宽，已写 gate_report.json
{"stages": {"research": "done", "article": "done", "narrative": "done", "gate": "failed"},
 "stopped_at": "gate", "blocking": 16}
exit=3
```

逐条命中数（原样统计）：W-24 缺 so_what ×8、W-07 缺 evidence ×6、W-12 数字缺 baseline ×2；
需人读 ×10（W-29 scope_note ×7、W-03/W-04/W-09 各 1，另 1 条重复计数行）。

修复前是 19 条，其中 6 条 `W-19 evidence 回指解析失败` 是编排层把素材根传错造成的**假阳性**，已修（见自检 C6）。

## 根因

1. **W-07 缺 evidence（结构性）**：`plan_narrative.split_sections()` 只把 **bullet / 表格行**当证据候选
   （`scripts/plan_narrative.py:90-91`：`BULLET_RE.match(...) or TABLE_RE.match(...)`）。
   而 `write_article.py` 的成文规则是"一条 claim 一段散文"（T-08），**文章里根本没有 bullet**
   ⇒ 每个 claim 页证据恒为空。这不是内容没写好，是**两个模块对"证据长什么样"的假设不一致**。
2. **W-24 缺 so_what（文案）**：`plan_narrative` 的设计是"只筛不写"（文件 docstring 原文），
   so_what 属创作判断。按 10-09 起沿用的停等点纪律，**无人值守期禁止自动写文案**，所以这里必须由人/显式 `--hook` 补。
3. **W-12 数字缺 baseline（内容）**：文章段的数字没有比较基准字段可回填；补基准等于编内容，不做。

## 需要主控决定（我不擅自裁决）

- **A**：S4 是否把"claim 段落 → evidence（带 `article.md#L行` 回指）"做成确定性抽取？（我倾向做，判据只加不松；
  这会把 W-07 的 6 条变成可判定项，但 **不会**自动消掉 W-24/W-12）
- **B**：W-24 的 8 条 so_what 走哪条路：人工补写 / 显式 `--hook` 授权我起草后你审 / 本期就让它停在 16 条并只出"旧路径（不带 --narrative）"的纯文字 deck 证明接线没坏。
- **C**：S5 的 E2E 产物是否接受"deck 由旧路径产出、叙事门禁 blocking 原样留档"这一形态（这正是 10-09 Task 15 用过的处置）。
