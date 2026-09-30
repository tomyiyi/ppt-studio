# ppt-studio 工作流（v3.0 · FW2026 沉淀版）

从内容到交付物，共 9 个阶段。阶段 1、7、8 不是可选项。

> 本流程由 FW2026 秋冬趋势 PPT 项目（v1→v4 四轮迭代）实战沉淀。
> 三条核心教训：
> 1. 技术 QA 通过 ≠ 审美验收通过；
> 2. 断言必须溯源，D 级内容宁可删；
> 3. 图片策略（实拍/AI/混合）决定成品上限，动手前先定。

---

## 阶段 0：内容研究

**目标**：先有扎实的内容底座，再谈版式。

1. **多源搜集**：同一主题至少 3 个独立来源交叉验证。权威来源（官方报告、专业媒体）优先；二手转述只能做线索，不能做结论。
2. **数据不能只有唯一来源**：关键数字（增长率、排名、规模）必须找到原始出处，找不到的不写进 PPT。
3. **研究报告落盘**：`projects/xxx/notes/research.md`
   - 每条关键断言后面必须跟来源（链接或出处名）。
   - 明确标注"待核实"项 —— 搜不到来源的先记下来，不直接当事实用。

---

## 阶段 1：来源审计（强制，不可跳过）

**目标**：PPT 里不允许出现无法溯源的断言。

### 断言分级

| 级别 | 定义 | 示例 |
|---|---|---|
| A | 一手来源：官方报告、品牌官方、数据平台官方 | Pantone 官方色板、Trendalytics 官方博客 |
| B | 专业媒体：有编辑流程的时尚/行业媒体 | Vogue、WWD、BoF、Harper's Bazaar、Coveteur |
| C | 二手转述：聚合站、自媒体转述 | 中文时尚号、小众趋势站 |
| D | 弱来源/无来源：个人小站、无出处、"据传" | 搜不到出处的数字、匿名说法 |

### 铁律

1. **D 级断言必须找到 B 级以上佐证，否则从内容中删除。** 宁可删掉一条存疑内容，也不让 PPT 出现无法溯源的断言。
2. **不允许误导性归因**：通用 stock 图不得标注为某品牌秀场实拍；AI 生成图必须如实标注"AI 生成"；实拍图必须标注真实来源。
3. **来源列表只写实际引用的**：PPT 结尾页的"资料来源"必须与研究报告中的引用一一对应，不许为了撑门面列没引过的媒体。

### 输出

《来源审计报告》`projects/xxx/notes/source_audit.md`：每条断言 → 来源 → 分级 → 处理（保留 / 升级 / 删除）。

---

## 阶段 2：图片策略（前置决策）

**目标**：动手生图/找图之前，先决定图片从哪来。图片策略决定成品上限。

### 三选一

| 策略 | 适用场景 |
|---|---|
| 纯 AI | 抽象概念、信息图、静物、面料特写为主；无真人需求 |
| 纯实拍 | 纪实、案例、人物为主；有可靠图库 |
| 混合制（推荐） | 真人/秀场/氛围用实拍，单品/面料/细节用 AI |

### 分工原则（FW2026 实测结论）

- **AI 画不好真人质感**：皮肤蜡感、uniform 高光、完美眼神反射是模型固有缺陷，prompt 只能缓解不能根治。模特、秀场、人物氛围图优先用真实摄影。
- **AI 画静物是强项**：单品、面料特写、配饰静物可以精确到配色和构图，且无版权风险。

### 实拍图规范

1. 来源：Unsplash / Pexels 等明确免费商用的图库。
2. **每张图记录**：来源链接、摄影师、许可证、下载时间。落盘 `projects/xxx/images/image_sources.md`。
3. **下载原图 full-res**，不用压缩预览版。压缩版放大后锐度塌陷。
4. 摄影师署名必须二次验证（不许从 CDN 文件名 slug 脑补）；验证不了的写"来源/真实摄影"，不编造人名。
5. 可识别人脸的大特写慎用（model release 风险）；优先选半身/全身/侧脸/背影。

### AI 生图规范

1. **生图只走 Agnes**（`agnes-image-2.5-flash`）。`agnes_ppt_bridge.py` 内置黑名单会拦掉 gemini / gpt-image / flux 等模型名 —— 这是硬约束，不是默认偏好。
2. prompt 三组关键词必须同时写，缺一组就翻车：

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

3. **人物 prompt 必须加缺陷描写**（反直觉但有效）：`visible skin pores, natural asymmetric skin tone variation, one or two stray hairs, no wax skin, no porcelain retouching` —— 不写缺陷，模型就输出磨皮蜡脸。
4. **用相机语言不用画质语言**：写 `shot on 35mm film, f/2.8`，不写 `8K hyperrealistic`（后者触发过度磨皮）。
5. ⚠️ **不要写 `no glow` / `no bloom` / `pen plotter`** —— Agnes 靠发光形成可见图形，禁掉后吐出几乎全空的图。
6. 9 张图共用全局 `style_suffix`（统一光影/色调描述），保证"同一本杂志"的一致性；后处理可批量加轻微去饱和 + 胶片颗粒。

---

## 阶段 3：设计系统（前置决策）

**目标**：动手画 SVG 之前，先把设计语言定死。不要 9 页套同一个模板。

### Page Role

每页定一个角色，9 页至少 4–6 种版式轮换，**不允许连续两页同构图**：

| Role | 用法示例 |
|---|---|
| Cover | 全出血 hero 图，标题压图 |
| Swatch Essay | 色块/数据纵向陈列 + 配图 |
| Detail Macro | 特写拼贴 |
| Typographic Hero | 纯文字页，字形本身做视觉 |
| Product Grid | 多件单品网格 |
| Pull Quote | 中央引言 + 两侧窄图 |
| Hero Number | 超大数字 + 支撑小图 |
| Runway Strip | 横向多图 film strip |
| Closing | 居中短句收束 |

### 网格与字阶

- 12 栏网格，页边距 ≈ 画布宽度 7.5%。
- **字阶锁死 5 级**（角色→字号一一对应，写进 spec_lock.md）：

| 角色 | 字号 | 说明 |
|---|---|---|
| kicker/页眉 | 11–13px | 全大写 + 0.16–0.22em 字距 |
| caption/图注 | 13px | 全大写，**每张内容图强制配图注**（来源/品牌/季） |
| body | 17–18px | 正文 |
| deck/导语 | 24–28px | 标题下的导语段 |
| headline/标题 | 96–150px | 高对比衬线，细→中字重 |

- **层级靠字号对比（150px vs 17px ≈ 9:1），不靠字重。** 时尚标题几乎不用粗黑体。

### 色彩

- 60-30-10：主色 60 / 辅助 30 / **强调色只定一个**（10%）。
- 强调色选项目主题色（如 FW26 用酒红 `#7A1F2B`），全项目只出现在同一类位置（页码/关键词/分割线），不许滥用。

### 信息层级

Vogue 三级：**标题（大字）/ 导语 deck（衬线细体）/ 正文**，另加**图注（全大写小字）**。图注是编辑的签名动作，每张内容图都必须有。

---

## 阶段 4：写内容笔记

一页一个 `notes/NN_xxx.md`。只写内容，不写版式：

```markdown
# 04 能力：自愈
- 主句：失败不用等人来
- 三个证据：自动重试 / 断点续跑 / 异常分诊
- 数字：0 人工介入次数
- [来源：xxx 报告 p12]
```

- 每条断言后标注来源（阶段 1 审计结论的直接引用）。
- D 级已删除的断言不得出现在这里。
- 版式交给 spec，别在这一步纠结字号。

---

## 阶段 5：定 `spec_lock.md`（版式契约）

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

- 把阶段 3 的设计系统决策（page role 清单、网格、强调色、字阶表）写进 spec_lock.md 顶部，做到"设计决策可追溯"。
- ⚠️ `- role: N` 后面**不能跟行内注释**，ppt-master 解析器会报错。注释单独占一行。

---

## 阶段 6：备图 → 客观验收 → 画 SVG

```bash
python3 scripts/agnes_ppt_bridge.py --manifest projects/xxx/images/image_prompts.json
python3 scripts/prepare_agnes_image.py raw.png out.png --size 1308x736 --seam auto
```

- **画布默认 1920×1080 起，不再用 1280×720。**（FW2026 教训：720p 画布 + 压缩原图 = 成品高清度先天不足。）
- 实拍图下载后先验证文件头完好再用：
  ```bash
  file img.jpg && magick identify img.jpg   # 无 JPEG SOI 头 = 传输损坏，重下
  ```
- 客观验收（看图被拦截时靠这个）：
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

画 SVG 画布要点：

- **底图要铺满**，覆盖率 ≥ 90%，内容浮在上面；一页只用一个图位（铺底 + 面板同图 = 重影）。
- **scrim 用方向性渐变**，别整幅糊。文字侧压住，空侧几乎不遮。
- `clip-path` **必须挂在 `<image>` 上**，不能挂外层 `<g>`，否则门禁报 blocking。
- 排版前先量主体的左右分布（三列墨量），文字放墨量少的一侧。

---

## 阶段 7：质检（必跑）

```bash
python3 scripts/render_svg.py projects/xxx/svg_output qa_render
python3 scripts/qa_layout.py projects/xxx/svg_output qa_render
```

七项检查，全部 OK 才是 `ALL CLEAR`（字号 / 底图 / 重影 / 溢出 / 压行 / 面板 / 对比；另有 `[主句]` 跨页一致性检查）。三个反直觉点保留：字号要解析继承、`text-anchor="end"` 边界是 `[x-w, x]`、背景取分位数不取均值。

### 新增铁律（FW2026 沉淀）

1. **QA 通过 ≠ 审美验收通过。** `ALL CLEAR` 只覆盖版式门禁，不覆盖事实正确性和"好不好看"。交付前必须有**用户目检**（或指定审美验收人）逐页看渲染图。
2. **QA 不覆盖事实**：色号、品牌名、数据、人名归属这类事实错误，脚本抓不到。事实正确性由阶段 1 的来源审计负责，QA 只管版式。
3. **每次改动后 QA 全量重跑**：改了字号 / 元素 y 坐标 / 图片引用 / 画布结构 / spec_lock 中的任一处，质检与导出全部重跑，不许"只改了一处就跳过"。

多出口（卡片 / 长图 / 视频 / HTML 预览）沿用 `make_cards.py` / `make_long_card.py` / `make_video.py` / `build_preview.py`，各自的 QA（`qa_cards` / `qa_long_card` / `qa_video` / `qa_preview`）同样必跑，改动后同样全量重跑。

---

## 阶段 8：导出并回读

```bash
python3 scripts/svg_to_pptx.py projects/xxx -f ppt169 -o output/xxx.pptx
python3 scripts/qa_pptx.py output/xxx.pptx
python3 scripts/build_preview.py projects/xxx/svg_output output/预览.html "标题"

# 回读 —— 关键，别只信源文件
unzip -q output/xxx.pptx -d /tmp/chk
# 图片：每页 <p:pic> 数量、ppt/media/ 文件数
# 字号：grep sz= 换算（1pt = 0.75px @1920×1080，84px → 63pt）
#       确认同一角色在各页落到同一 pt
```

**回读不能省。** 源文件对了不代表导出对了。字号一致性最终是从 PPTX 里反查 `sz=` 才确认的。

交付归档清单（随 PPTX 一并保留）：
- `notes/research.md`（研究报告）
- `notes/source_audit.md`（来源审计报告）
- `images/image_sources.md`（实拍图来源/摄影师/许可证清单）
- `images/image_prompts.json`（Agnes 生图 manifest：prompt / 模型 / 生成状态）

---

## 附：FW2026 翻车档案

| # | 现象 | 真因 | 修法 | 沉淀为流程 |
|---|---|---|---|---|
| 1 | Pantone 色号标错（Red Mahogany 写成 19-1524，官方 19-1521） | 转述二手小站，未核对官方色板 | 用官方色板逐字核对 | 阶段 1：编号类断言必须对一手来源 |
| 2 | 两个色号无依据（Mulberry 19-2430、Citrus Orange 16-1257 不在官方色板） | 个人小站说法被当成事实 | 删除编号或替换为官方色 | 阶段 1：D 级无佐证即删除 |
| 3 | 通用 Pexels 走秀图被标注为 SAINT LAURENT / DIOR / HERMÈS 2026 FW 秀场 | 图注为了"高级感"编造归属 | 去品牌化，改为"RUNWAY · PEXELS 真实摄影" | 阶段 1 铁律：不允许误导性归因 |
| 4 | 封面摄影师名取自 CDN 文件名 slug，未验证 | 图方便 | 删除具体人名或注"待核实" | 阶段 2：摄影师署名必须二次验证 |
| 5 | Pexels 下载的是压缩版（200–384KB），放大后糊 | 没注意图库有多档分辨率 | 重新下载 full-res 原图 | 阶段 2：必须下载原图 full-res |
| 6 | 画布 1280×720，照片被二次压缩 | 沿用旧默认 | 画布默认 1920×1080 起 | 阶段 6：分辨率下限写入流程 |
| 7 | QA 四轮 ALL CLEAR，但色号错误、品牌误标一张没抓到 | QA 只覆盖版式门禁 | 来源审计独立成阶段 | 阶段 7 铁律：QA 通过 ≠ 事实/审美验收通过 |
| 8 | v1/v2 九页同一模板（左文右图出血），用户"不够高级" | Keynote 模板思维 | page role 轮换、6 种版式 | 阶段 3：设计系统前置 |
| 9 | AI 模特蜡皮脸，用户两次不满意 | prompt 只写"保留质感"，没写缺陷描写 | 缺陷描写 + 相机语言；真人改用实拍 | 阶段 2：人物 prompt 模板 + 混合制分工 |
| 10 | 3 张预置图传输损坏（无 JPEG SOI 头），QA 没发现 | QA 不校验图片文件头 | `file` + `magick identify` 验证 | 阶段 6：备图后验证文件头 |
| 11 | 来源列表写了 VOGUE，但全文无一篇具体 Vogue 引用 | 撑门面 | 按实际引用列来源 | 阶段 1 铁律：来源列表只写实际引用的 |

---

## 旧版翻车档案（v3.0 前沉淀，保留）

| 现象 | 真因 | 修法 |
|---|---|---|
| 图糊成一团 | 提示词写了 `volumetric fog` / `cinematic DoF` | 加 razor sharp 三连 |
| 图几乎全空 | 提示词写了 `no glow` / `pen plotter` | 保留 `bold glowing`，另加 razor sharp |
| 图上有竖线 | 提示词说了 "左半 / 右半" | 改成 "uniform flat tone, no split" |
| 主体太小 | 只写了亮度约束没写尺寸约束 | 补 `SIZE IS CRITICAL` 组 |
| 放大后锐度塌陷 | 源图 1312×736 放到 2560×1440 | 精确裁到目标尺寸，别放大 |
| 一页看到两个相同图形 | 铺底 + 面板用了同一张图 | 二选一 |
| 底部文字读不清 | 整幅糊遮罩 | 改方向性渐变 scrim |
| 小字对比度不足 | `tertiary_text` 用了 `#5A5B66`（2.9:1） | 改 `#7F8090`（4.75:1） |
| 字忽大忽小 | 同一角色在不同页落了不同档 | spec_lock 里锁死角色→档位 |
| 审计表字号全是 16 | 验证器没解析继承 | `_iter_with_parents` + 向上回溯 |
| 卡片下半屏空着 | 图片带高度写死 | 按内容量自适应 40%–62% |
| 卡片上的图看不见 | scrim 压太狠 | 降到 0.78/0.28/0.05/0.16 |
| 卡片圆牌里塞了中文短语 | 徽章抽取取到了标签 | 取徽章组里 y 最小的那段（数字） |
| 质检阈值和生成器打架 | 两边各写各的常量 | 阈值对齐生成器下限并注明理由 |
