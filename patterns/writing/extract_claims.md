# extract_claims

从文章的一个章节中提取核心主张。

## 输入
- `section_title`: 章节标题
- `section_body`: 章节正文（Markdown）

## 输出（JSON）
```json
{
  "claim": "一句话核心主张（观点句，不超过20字）",
  "evidence": ["论据1（不超过30字）", "论据2", "论据3"],
  "hook_candidate": "金句候选（原文中最有力的一句，不超过30字）"
}
```

## 规则
1. claim 必须是观点断言，不是描述。坏："介绍了第一性原理"，好："AI 的自信是机制必然，不是 bug"
2. evidence 每条独立成句，去掉"首先/其次/另外"等连接词
3. hook_candidate 从原文找，不要自己编
4. 如果章节是表格/对照，claim 提炼表格的核心结论
