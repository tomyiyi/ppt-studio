# 工作流

从内容到交付物，一共七步。第 6、7 步不是可选项。

---

## 0. 前置

```bash
# 图像分析依赖（任意 python3.11+ 均可）
python3 -m venv .venv && .venv/bin/pip install pillow numpy

# SVG 渲染需要 Playwright（macOS 上 brew python 才有）
/opt/homebrew/bin/python3 -m pip install playwright cairosvg
```

⚠️ **两个 python 不要混用**：渲染要 Playwright，图像分析要 Pillow/numpy，装在不同解释器里。用错解释器会 `ModuleNotFoundError`。

---

## 1. 写内容笔记

一页一个 `notes/NN_xxx.md`。只写内容，不写版式：

```markdown
# 04 能力：自愈
- 主句：失败不用等人来
- 三个证据：自动重试 / 断点续跑 / 异常分诊
- 数字：0 人工介入次数
```

版式交给下一步的 spec，别在这一步纠结字号。

---

## 2. 定 `spec_lock.md`（版式契约）

全项目**唯一真源**。改字号只改这里，`qa_layout.py` 直接从该文件解析阶梯。

```markdown
## typography
# 角色 → 档位必须锁死，否则同一角色在不同页会落到不同档
11 kicker
13 caption
16 body
20 lead
24 subtitle
32 title
44 headline
56 statement
96 cover

## colors
bg: #08090C
tertiary_text: #7F8090    # 不要低于这个，#5A5B66 只有 2.9:1
```

⚠️ `- role: N` 后面**不能跟行内注释**，ppt-master 解析器会报错。注释单独占一行。

---

## 3. 生成配图

```bash
python3 scripts/agnes_ppt_bridge.py --manifest projects/xxx/images/image_prompts.json
python3 scripts/prepare_agnes_image.py raw.png out.png --size 1308x736 --seam auto
```

**生图只走 Agnes**（`agnes-image-2.5-flash`）。`agnes_ppt_bridge.py` 内置黑名单会拦掉 gemini / gpt-image / flux 等模型名 —— 这是硬约束，不是默认偏好。

提示词两组关键词必须同时写，缺一组就翻车：

```
# 管亮度（缺了出暗线）
BOLD NEON TUBES: very thick, fully saturated, at MAXIMUM BRIGHTNESS ...
Absolutely NO thin hairlines, NO faint dim outlines.
# 管尺寸（缺了出小图标）
SIZE IS CRITICAL: height ~70% of frame HEIGHT, width ~50% of frame WIDTH.
DO NOT draw a tiny icon floating in a big empty frame.
# 管锐度（缺了全屏焦外虚化）
all lines razor sharp, perfectly in focus, crisp hard edges.
No blur, no fog, no bokeh, no depth of field.
```

⚠️ **不要写 `no glow` / `no bloom` / `pen plotter`** —— Agnes 靠发光形成可见图形，禁掉后会吐出几乎全空的图。

---

## 4. 客观验收（看图被拦截时靠这个）

```bash
python3 scripts/analyze_image.py projects/xxx/images/*.png
```

| 指标 | 及格线 |
|---|---|
| 主体锐 | ≥80（发光软边可放宽到 ~45） |
| P99 | ≥40 |
| 主体分布最高格 | ≥25%（每格 11% 为均匀基线） |
| 墨量（max(R,G,B) 通道） | ≥6% |
| 接缝 | None |

🔴 **用 max(R,G,B) 通道，不要用亮度。** 靛蓝 `#6E7BFF` 蓝通道 255，但相对亮度权重只有 0.0722，折算灰度约 136 —— 按亮度判会把满饱和的靛蓝误判成"太暗"。

---

## 5. 画 SVG 画布

画布 `viewBox="0 0 1280 720"`，边距 60px。

**底图要铺满**，覆盖率 ≥ 90%，内容浮在上面：

```xml
<g id="background">
  <rect width="1280" height="720" fill="#08090C"/>
  <image href="../images/xx_bg.png" x="0" y="0" width="1280" height="720"
         preserveAspectRatio="xMidYMid slice"/>
  <rect width="1280" height="720" fill="url(#xx-scrim-x)"/>  <!-- 护文字 -->
  <rect width="1280" height="720" fill="url(#xx-scrim-y)"/>  <!-- 护页脚 -->
</g>
```

要点：

- **一页只用一个图位**。铺底 + 面板同时用同一张图 = 重影。
- **scrim 用方向性渐变**，别整幅糊：`0→0.92 / 0.45→0.80 / 0.62→0.30 / 1→0.04`。文字侧压住，空侧几乎不遮。
- **卡片改半透明** `fill-opacity="0.66"`，让底图透出来。
- `clip-path` **必须挂在 `<image>` 上**，不能挂外层 `<g>`，否则门禁报 blocking。
- 排版前先量主体的左右分布（三列墨量），文字放墨量少的一侧。

---

## 6. 质检（必跑）

```bash
/opt/homebrew/bin/python3 scripts/render_svg.py projects/xxx/svg_output qa_render
/opt/homebrew/bin/python3 scripts/qa_layout.py projects/xxx/svg_output qa_render
```

七项检查，全部 OK 才是 `ALL CLEAR`：

| 检查 | 内容 |
|---|---|
| `[字号]` | 所有文本字号落在 spec_lock 的九档内 |
| `[底图]` | 最大 `<image>` 面积 / 画布 ≥ 90% |
| `[重影]` | 同一源图不在一页出现两次 |
| `[溢出]` | 文本不超出画布（按 `text-anchor` 算边界） |
| `[压行]` | 相邻文本行不碰撞 |
| `[面板]` | 面板区域墨量 ≥ 6% |
| `[对比]` | WCAG ≥ 4.5:1（背景取 20 分位，字色取 99.5 分位） |

七项里的三个反直觉点：

1. **字号要解析继承**。`font-size` 常写在父 `<g>` 上，只读 `text.get('font-size')` 会把 56px 主句读成默认 16px，整张审计表失真。
2. **`text-anchor="end"` 向左延伸**：边界是 `[x-w, x]`，不是 `[x, x+w]`。
3. **背景取分位数，不取均值**。用均值会把白色大字算进"背景亮度"，明明 18:1 却报"背景过亮"。

---

## 6.5 出卡片（第三个出口）

```bash
python3 scripts/make_cards.py projects/xxx            # → cards/
/opt/homebrew/bin/python3 scripts/render_svg.py projects/xxx/cards qa_cards_render
python3 scripts/qa_cards.py projects/xxx/cards qa_cards_render
```

同一份 SVG，第三条出口。卡片是**重排**不是裁切：16:9 → 3:4 直接 slice
会横向砍掉 55% 画面，横版字号在手机上也读不清。

内容源是 SVG 本身，不是 notes —— notes 是演讲提示，不是文案。
`card_spec.md` 的 `## focus` 段可以给「源页没有主句档」的页人工指定主句。

卡片专属的三个坑：

1. **图片带高度要自适应**。固定 47% 会让只有一句主句的卡片下半屏空着（面板墨量 2.96%）。改成按内容量反推，40%–62% 之间浮动。
2. **遮罩别压太狠**。`0.88/0.42/0.08/0.30` 把暗图压到整带墨量 0.7%，等于没图。
3. **徽章要取数字不是标签**。徽章组里通常有「数字（y 小）+ 标签（y 大）」两段文字，取 y 小的那个，否则会把中文短语塞进小圆牌。

## 7. 导出并回读

```bash
python3 scripts/svg_to_pptx.py projects/xxx -f ppt169 -o output/xxx.pptx
python3 scripts/build_preview.py projects/xxx/svg_output output/预览.html "标题"

# 回读 —— 关键，别只信源文件
unzip -q output/xxx.pptx -d /tmp/chk
# 图片：每页 <p:pic> 数量、ppt/media/ 文件数
# 字号：grep sz= 换算（1pt = 0.75px @1280×720，56px → 42pt）
#       确认同一角色在各页落到同一 pt
```

**第 7 步的回读不能省。** 源文件对了不代表导出对了。字号一致性最终是从 PPTX 里反查 `sz=` 才确认的。

改了以下任一处，**6、7 全部重跑**：字号 / 元素 y 坐标 / 图片引用 / 画布结构 / spec_lock。

---

## 常见翻车档案

| 现象 | 真因 | 修法 |
|---|---|---|
| 图糊成一团 | 提示词写了 `volumetric fog` / `cinematic DoF` | 加 razor sharp 三连 |
| 图几乎全空 | 提示词写了 `no glow` / `pen plotter` | 保留 `bold glowing`，另加 razor sharp |
| 图上有竖线 | 提示词说了 "左半 / 右半" | 改成 "uniform flat tone, no split" |
| 主体太小 | 只写了亮度约束没写尺寸约束 | 补 `SIZE IS CRITICAL` 组 |
| 放大后锐度塌陷 | 源图 1312×736 放到 2560×1440 | 精确裁到 1308×736，别放大 |
| 一页看到两个相同图形 | 铺底 + 面板用了同一张图 | 二选一 |
| 底部文字读不清 | 整幅糊遮罩 | 改方向性渐变 scrim |
| 小字对比度不足 | `tertiary_text` 用了 `#5A5B66`（2.9:1） | 改 `#7F8090`（4.75:1） |
| 字忽大忽小 | 同一角色在不同页落了不同档 | spec_lock 里锁死角色→档位 |
| 审计表字号全是 16 | 验证器没解析继承 | `_iter_with_parents` + 向上回溯 |
| 卡片下半屏空着 | 图片带高度写死 | 按内容量自适应 40%–62% |
| 卡片上的图看不见 | scrim 压太狠 | 降到 0.78/0.28/0.05/0.16 |
| 卡片圆牌里塞了中文短语 | 徽章抽取取到了标签 | 取徽章组里 y 最小的那段（数字） |
| 质检阈值和生成器打架 | 两边各写各的常量 | 阈值对齐生成器下限并注明理由 |
