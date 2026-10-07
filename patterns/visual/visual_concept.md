# visual_concept

从页面内容提炼视觉概念（Midjourney 6 段式的前三段）。

## 输入
- `slide_title`: 页面标题
- `bullets`: 页面要点
- `layout`: 版式

## 输出（JSON）
```json
{
  "subject": "画面主体（具体名词，英文，3-5词）",
  "action": "主体动作/状态（英文，2-4词）",
  "environment": "环境氛围（英文，3-5词）"
}
```

## 规则
1. 写具体名词，不写抽象主题。坏："concept of trust"，好："fortress gate with multiple checkpoints"
2. Subject 是画面中心唯一的视觉焦点
3. 隐喻映射表（关键词→视觉）：
   - 第一性原理/本质/核心 → "peeling layers revealing core"
   - 对抗/审查/测试 → "stress test chamber, red team"
   - 校验/确定性 → "precision caliper measuring"
   - 零信任/安全 → "fortress with layered checkpoints"
   - 记忆/沉淀 → "library archive, glowing threads"
   - 对比/对照 → "split diptych, two sides"
   - 流程/步骤 → "flowing timeline path"
4. 避免人物面部（AI 画中文场景的人脸容易崩）
