# rewrite_slide_copy

把提取的主张改写成演示型文案（适合放在 PPT 页面上）。

## 输入
- `claim`: 核心主张
- `evidence`: 论据列表
- `layout`: 目标版式（bullets/statement/compare/steps）

## 输出（JSON）
```json
{
  "slide_title": "页面标题（观点句，12字以内）",
  "bullets": ["短句1（20字以内）", "短句2", "短句3"],
  "takeaway": "本页记忆点（一句话，15字以内）"
}
```

## 规则
1. slide_title 是观点，不是章节名。坏："准则一"，好："AI 的自信是必然"
2. bullets 每条是一句完整的话，去掉修饰，保留动词和数字
3. 数字、对比、反差优先保留（"73% vs 46%" 比 "效果更好" 好）
4. takeaway 是观众合上电脑后还能记住的那句
5. 绝对不要超过 4 条 bullets
