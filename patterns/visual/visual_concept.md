# visual_concept

从页面内容提炼视觉概念（Midjourney 6 段式的前三段）。

## 输入
- `slide_title`: 页面标题
- `bullets`: 页面要点
- `layout`: 版式

## 输出（JSON）
```json
{
  "subject": "画面主体（具体名词，英文，3-5词）| null",
  "action": "主体动作/状态（英文，2-4词）",
  "environment": "环境氛围（英文，3-5词）| null",
  "domain": "fashion|tech|finance|null",
  "matched": "命中的关键词|null"
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

## 实现约束（`narrative_rewrite.py` 的落地边界）

这套方法论有部分**无法用规则可靠实现**。实现时必须守住以下边界，
否则会产出"看起来对但其实错"的内容——比留空更糟。

### ✅ 规则可以做
- 多字关键词精确匹配（按key 长度降序，保证「第一性原理」先于「本质」命中）
- 领域门槛判定（页面出现领域词才启用该领域的映射表与风格）
- 版式 → action 映射
- 排版计算（字号、行宽、断行）

### ❌ 规则不能做
- **不能用单字关键词**。中文单字歧义极大：旧版用「红」做 key，
  导致「红色预警」这类技术页被判成时装摄影布景。单字必须受领域门槛约束。
- **不能在无匹配时编造 subject**。返回 `null`，让调用方走中性底图。
  硬塞一个"总归对得上"的抽象词，是这类系统最典型的退化来源。

### 匹配失败时的正确行为
```
match_visual_concept(...) -> None      # 领域门槛不通过或无关键词命中
visual_concept(...)        -> {"subject": None, ...}
build_image_prompt(...)    -> 用排版元素兜底（subtle abstract geometric depth）
                            + 中性环境，不猜领域
```

**宁可留白，不要硬凑。** 匹配不上时"诚实降级"是可接受的结果，
"总归对得上"的内容才是系统性失败的开始。

