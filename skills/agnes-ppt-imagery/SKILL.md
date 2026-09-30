---
name: agnes-ppt-imagery
description: 用 Agnes Studio（本机 New API 出图）给 PPT Master 生成并落地配图。当用户要给 PPT 配图、生成封面底图、插图、背景图，或提到 Agnes / agnesstudio / 生图接入 PPT / PPT 缺图 时使用。内含生图红线（只走 Agnes，禁用 gemini）、PPT Master 的 Path B 契约、以及三个已踩过的真坑（虚化提示词、竖向接缝检测器自指 bug、乘法补偿越修越糟）。
agent_created: true
---

# Agnes → PPT Master 配图管线

把 Agnes Studio 的出图能力接成 PPT Master 的 **Path B（host-native image tool）**。

> 前置：`ppt-master`（`hugohe3/ppt-master`）需单独安装，转换脚本不在本仓库内。

## 🔴 第一条：生图红线

**只能用 Agnes，禁止用 gemini。**

- 本机 gemini 是**反代（中转文本通道）**，没有可靠图像生成能力。
- 模型黑名单：`gemini*`、`dall-e*`、`gpt-image*`、`flux*`、`seedream*`。
- 唯一通道：New API `http://127.0.0.1:13000/v1`，凭据 `~/.new-api/local_key.json`。
- 可用模型仅 2 个：`agnes-image-2.5-flash`（主用）、`agnes-image-2.1-flash`。

**别搞混两类模型**：
| 用途 | 谁在干 | 能不能用 gemini |
|---|---|---|
| 语言模型（驱动 Agent 流程、写文案） | 宿主 Agent 自带 | ✅ 可以（反代没问题） |
| 图像模型（出图） | 独立后端 | ❌ 禁止 |

> PPT Master 的 README 推荐 `gemini-3.1-flash-image`，那是假设直连 Google 官方，本机环境一律按红线覆盖。

## 工具（均在仓库 `scripts/` 下）

```bash
# 1) 出图（只用标准库，任意 python3 可跑）
python3 scripts/agnes_ppt_bridge.py --prompt "..." --filename cover_bg.png \
     --project <project> --aspect-ratio 16:9
python3 scripts/agnes_ppt_bridge.py --manifest <project>/images/image_prompts.json   # 批量
python3 scripts/agnes_ppt_bridge.py --render-md <project>/images/image_prompts.json  # 只出 sidecar

# 2) 后处理 —— 裁精确 16:9 + 去接缝 + 压暗
#    源图 1312x736，显示按 1280x720，裁到 1308x736 即可，别放大
python3 scripts/prepare_agnes_image.py <raw.png> <out.png> --size 1308x736 --brightness 0.95 --seam auto

# 2.5) 客观验收（看图被拦截时用数据代替眼睛）
python3 scripts/analyze_image.py <project>/images/*.png

# 2.6) 主体裁切 —— 让主体填满面板（见坑 9）
python3 scripts/crop_panel.py heal_bg.png --aspect 580:385 --pad 1.15 --apply

# 2.7) 版面总检 —— 溢出 + 面板墨量 + 全页 WCAG，一次跑完
python3 scripts/qa_layout.py <project>/svg_output <render_dir>

# 3) 渲染 —— macOS 需系统 python3（playwright 装在那里）
/opt/homebrew/bin/python3 scripts/render_svg.py <project>/svg_output <out_dir> --scale 1
```

## 标准流程

1. **出图** → `agnes_ppt_bridge.py`，产出 `_raw_*.png`（Agnes 默认 1312x736，非精确 16:9）
2. **后处理** → `prepare_agnes_image.py` 裁到 2560x1440，顺手检/修接缝
3. **看** → 用 Read 工具直接看 `_raw_*.png` 和成品，**不要只看命令返回码就往下走**
4. **嵌 SVG** → `<image href="../images/xxx.png" x="0" y="0" width="1280" height="720" preserveAspectRatio="xMidYMid slice"/>`，放在 `<rect fill="#08090C"/>` 之后、文字之前；**再叠渐变遮罩**保护文字对比度
5. **门禁** → `svg_quality_checker.py <project> --canonical-authoring --stage final --json`，要求 blocking=0
6. **导出** → `svg_to_pptx.py <project> -f ppt169 -t morph -o out.pptx`
7. **验证** → `unzip -q out.pptx && ls ppt/media/`，并 grep 每页 `<p:pic>` 数量 + `morph` 计数

## 三个真坑（踩过，别再犯）

### 坑 1：提示词里的氛围词会毁掉整张图
写 `volumetric fog` / `cinematic depth of field` / `atmospheric haze` → 模型输出**全屏焦外虚化**，糊成一团。

必带三连：
```
all lines razor sharp, perfectly in focus, crisp hard edges.
No blur, no fog, no bokeh, no depth of field, no motion blur.
```

### 坑 2：说"右半/左半"会让模型真的切一刀
提示词里写 `RIGHT HALF ... LEFT HALF`，模型会留一条**竖向亮度接缝**。

补救提示词：`The background must be one single uniform flat dark tone across the whole frame, no panels, no split, no visible vertical seam, no hard division.`

已写自动检测+修复（`detect_seam` / `fix_seam`），但有两个反直觉的数学结论：

- **检测器**：判定"近邻是否还有同级台阶"时，**必须排除 `diff[i]` 自己**，否则永远自判失败（真阳性 0/8）。排除后 8/8。
- **修复器**：必须「**加偏移 + 与台阶对齐的硬阶跃**」。
  - 乘增益 → 台阶同比例放大（跳变 14→18.6，越修越糟）❌
  - 加偏移 + 平滑过渡带 → 补偿在台阶处变化量≈0，等于没补（残差 13.05）❌
  - 左侧整体 +Δ、不做斜坡 → 跳变 8~30 降到 0.44~1.14（噪声底）✅

回归测试：8/8 真阳性 + 3/3 真阴性（无接缝 / 仅边缘台阶 / 平滑渐变都不误报）。改这两个函数后**务必重跑测试**。

### 坑 3：Agnes 优先调用的速度差 15 倍
把 `gemini-*-image` 排在候选模型最前面时，每次都要等它们超时重试：**3 分 7 秒/张**。
Agnes 排最前后：**12~13 秒/张**。

### 坑 4：🔴 绝不能禁掉 glow —— 禁了模型就吐空图
为了"清晰"写上 `no glow, no bloom, pen plotter, flat vector line-art` →
模型直接输出**几乎全空的图**（P99 从 103 掉到 24，墨迹均匀分布 = 没画东西）。

**Agnes 靠发光来形成可见图形。** 正确做法：保留 `bold glowing` / `strong luminous strokes`，
同时用 `razor sharp / crisp hard edges / no blur` 保证锐度。两者不冲突。

### 坑 5：别盲目放大分辨率
源图 1312×736，最终只按 1280×720 显示 → **不需要放大到 2560×1440**。
放大 1.95× 后主体锐度从 411 塌到 148（插值假象），体积还翻倍。
直接精确裁到 **1308×736**（原生分辨率，比例已精确 16:9）锐度最高、体积最小。

### 坑 6：接缝检测器会把「内容边缘」当接缝（已修，别改回去）
发光图形自身的硬边缘在「列均值曲线」上和接缝长得一模一样。
实测 heal_bg 被误报 x=330，强行抹平反而把跳变从 7.4 **放大**到 8.4。

正解判据：**接缝贯穿全高，内容边缘只占部分行** → 只统计「暗行一致率」：
- 真接缝 **0.93~1.00**
- 误报最高 **0.49**（bus_bg），其余 0.00~0.40

（只用「全行一致率」时真接缝 0.93 vs 误报 0.71，间隔太窄不稳；改用暗行后拉开到 0.49 vs 0.93。）

搜索流程也不能反：
- ❌ 逐行 argmax 找列 → 被噪点主导（千列噪声极值可达 15，盖过 Δ=8 的接缝）
- ✅ **列均值（720 行平均掉噪声）找候选 + 暗行一致率验证**

当前回归：真阳性 **30/30**、真阴性 **12/12**、修复后跳变全部 <1.2。
改 `detect_seam` / `fix_seam` 后必须重跑这套测试。

### 坑 7：验收指标会把「文字本身」算进去 → 误判背景过亮
量"文字区亮度"用均值时，72px 白色粗体字（#F7F7F9=247）被算进区域，
导致明明对比度 18.5:1 却报"背景过亮"。

正解：**背景取区域 20 分位数**（≈背景），字色取 99.5 分位数，算 WCAG 对比度。
判据：背景 ≤45 且对比度 ≥4.5:1。实测七页背景 9~19、对比度 17.3~18.6:1。

### 无法肉眼看图时的客观验收（重要）
图片查看可能被模型能力拦截（`does not support images`）。此时**不要用返回码蒙混过关**，改用：

```bash
python3 analyze_image.py a.png b.png ...    # 清晰度/墨迹分布/亮度/接缝
```

四个判据：
| 指标 | 含义 | 及格线 |
|---|---|---|
| 主体锐 | 只框最亮 1% 像素算拉普拉斯方差 | ≥80（发光软边可放宽到 ~45） |
| P99 | 亮部强度 | ≥40，<40 说明没高光 |
| 主体分布最高格 | 每格 11% 为均匀基线 | ≥25% 才有明确主体，<15% 视为没画出图形 |
| 接缝 | detect_seam | None |

版面落地后再量一次：文字区 20 分位（背景）+ 99.5 分位（字色）→ WCAG 对比度 ≥4.5:1。

## 版式：想让图"站前台"必须改信息架构

缩卡片（580→420、留 140px 竖条）只是**折中**，图还是配角。
真正有效的是**把内容从右半搬走，整个右半留给图**：

| 页面 | 怎么搬 | 图位 |
|---|---|---|
| 05 总线页 | 六个接入项从卡片搬出 → 左侧 chip 网格（x=80/330 × y=424/476/528，230×42） | 620–1200 × 150–535（580×385） |
| 04 自愈页 | 终端卡缩到左侧 80–560、只留 3 行关键证据 | 620–1200 × 150–535 |
| 06 对比页 | 图表压到右下半（y=372–562，190 高） | 620–1200 × 150–336（580×186 横幅） |

面板写法：
```xml
<clipPath id="xx-panel-clip"><rect x="620" y="150" width="580" height="385" rx="8"/></clipPath>
<image href="../images/xx_bg_panel.png" x="620" y="150" width="580" height="385"
       preserveAspectRatio="xMidYMid slice" clip-path="url(#xx-panel-clip)"/>
<rect x="620" y="150" width="580" height="385" rx="8" fill="none" stroke="#23242E"/>
```

⚠️ **`clip-path` 必须挂在 `<image>` 上，不能挂包裹的 `<g>`**，
否则质量门禁 blocking：
`clip-path is allowed only on <image> or an imported data-pptx-crop="1" wrapper`

改完务必：
1. 重排剩余内容（双列网格放不下就改单列；图表收窄柱宽与间距）
2. 跑 `qa_layout.py`：溢出（已正确 handling `text-anchor`）+ 面板墨量 + 全页 WCAG
   - 溢出宽度估算：CJK=1.0em、比例字体其他=0.52em、等宽=0.60em
   - 锚点边界：`start=[x, x+w] / middle=[x-w/2, x+w/2] / **end=[x-w, x]**`
     （end 最容易算错——它向左延伸，右端就是 x）

### 坑 8：🔴 别用「亮度」衡量彩色笔画 —— 会得出完全错误的结论

靛蓝 `#6E7BFF` 的蓝通道是 255，但**相对亮度权重只有 0.0722** → 折算灰度仅 **~136**。
用「L 通道的 std / p99 / max」去判图够不够亮，会把**满饱和的靛蓝笔画误判成"太暗"**
（实测七张图 max 亮度只有 129~218，`>150` 占比 0.00%，看着像全废）。

✅ 正确指标：**max(R,G,B) 通道值**
- 墨量 = `mean(max通道 > 80)`
- 笔画色 = 亮像素均值；背景 = 第 10 百分位；两者算 WCAG 对比
- 判据：墨量 ≥6%（<3% 说明主体太小），笔画/背景对比 ≥3:1

### 坑 9：图看着空，原因通常是「主体太小」而不是「太暗」

16:9 整幅图直接塞进右半面板（1.51:1），主体往往只剩 **3% 墨量** —— 面板大半是空的。

两步，先裁后重生成：

1. **`crop_panel.py` 按主体包围盒裁切**（不动原图，另存 `*_panel.png`）
   ```bash
   python3 crop_panel.py diverge_bg.png --aspect 580:385 --pad 1.15 --apply
   ```
   实测：diverge 3.83%→**16.5%**、bus 11.8%→**25.3%**。
   ⚠️ 两个前提：
   - 主体若是**贯穿全宽的细线**（bbox 宽高比 >3），裁切无效（heal v2 只有 1.1×）→ 重生成
   - 裁完宽度必须 **≥580**，否则显示时要放大、会糊（见坑 10）

2. **重生成时补两条硬约束**（光说 "BOLD, BRIGHT" 没用，模型不知道要多大）：
   ```
   CRITICAL: strokes must be THICK and DENSE, at least 6-8 pixels wide at 1280px frame width.
   COMPOSITION IS CRITICAL: the emblem sits in the CENTRE of the frame and occupies
   about 45% of the frame WIDTH and 55% of the frame HEIGHT.
   ```
   实测：heal 2.4%→**18.4%**、bus 2.3%→**11.8%**。

（附 `boost_ink.py`：黑点保持增益 `out = black + (in-black)*gain`。
纯属备用——普通乘法会把 #08090C 黑底一起提亮成灰底，图会发雾。）

### 坑 10：🔴 亮度和尺寸是两条独立的 prompt 约束，必须同时写

只写 "BOLD, BRIGHT, HIGH CONTRAST" 或只写 "occupies 45%×55%" 都不够。
实测同一张「修复徽记」连试 5 版：

| 版 | prompt 侧重 | 墨量 | 对比 | 主体 bbox | 问题 |
|---|---|---|---|---|---|
| v2 | 粗笔画 + 45%×55% | 18.4% | 4.3:1 | 1047×295 | 宽高比 3.55，是根横条不紧凑 |
| v3 | 紧凑方形 + 40%×60% | 3.0% | 2.3:1 | 260×256 | **又暗又小** |
| v4 | NEON TUBES + MAXIMUM BRIGHTNESS | 1.3% | **5.3:1** | 164×165 | 亮了，但主体只有 164px |
| v5 | 上面两条 + SIZE IS CRITICAL 70%H/50%W | **25.2%** | 3.9:1 | **782×729** | ✅ |

必写两组关键词：
```
# 管亮度（缺了就出暗线）
BOLD NEON TUBES: very thick, fully saturated, at MAXIMUM BRIGHTNESS ...
Absolutely NO thin hairlines, NO faint dim outlines.
# 管尺寸（缺了就出小图标）
SIZE IS CRITICAL: height ~70% of frame HEIGHT, width ~50% of frame WIDTH.
DO NOT draw a tiny icon floating in a big empty frame.
```

⚠️ **主体太小还有个隐藏代价：放大插值会把锐度毁掉。**
面板 580×385，若源图主体只有 164px，裁出来约 285×190 → 要**放大 2×**，糊。
判据：裁切后的 `*_panel.png` 宽度必须 **≥580**（越小越好）。
Agnes 固定出 1312×736，要不到 2K，所以只能靠 prompt 把主体画大。

### 坑 11：🔴 "让图更抢眼"不等于"做成角落面板"——底图要铺满

我为了让图抢眼，把整幅底图换成了右半一块面板，结果三页跟其余四页的底图语言断裂。
用户一句「图没有做到底图效果」点破。

**底图的硬指标：最大 `<image>` 面积 / 画布 ≥ 90%。**（`qa_layout.py` 的 `[底图]` 检查）
实测事故：01/02/03/07 = 100%，04/05 = **24.2%**，06 = **11.7%**。

正确做法（一页一张图 + 整幅铺满 + 内容浮在上面）：
```xml
<g id="background">
  <rect width="1280" height="720" fill="#08090C"/>
  <image href="../images/xx_bg.png" x="0" y="0" width="1280" height="720"
         preserveAspectRatio="xMidYMid slice"/>
  <rect width="1280" height="720" fill="url(#xx-scrim-x)"/>  <!-- 护文字 -->
  <rect width="1280" height="720" fill="url(#xx-scrim-y)"/>  <!-- 护页脚 -->
</g>
```
- **scrim 用方向性渐变，别整幅糊**：`0→0.92 / 0.45→0.80 / 0.62→0.30 / 1→0.04`
  文字侧压住、空侧几乎不遮，图才有存在感
- **卡片改半透明** `fill-opacity="0.66"`（转换器支持），底图从卡片后面透出来
- 徽章/数字可以浮在底图上，比塞进卡片里更有力

**排版前先量主体的左右分布**（三列墨量），再决定文字放哪边：
heal 左18/中43/右14、bus 左1.8/中33/右0.4 都能配"文字在左"；
diverge 曾经左11.5/中0/右0 —— 主体和文字撞在同一边，必须让它靠右
（用 `RIGHT QUARTER 72–98%` prompt 重生成，或直接水平翻转 `Image.FLIP_LEFT_RIGHT`）。

### 坑 11b：🔴 一页里同一张图不要用两次（会看成重影）

为了"让图更抢眼"，很容易走成：全幅铺底用 `xxx_bg.png` + 右半面板又用 `xxx_bg_panel.png`。
**同一个徽记在一页里出现两遍**，用户一眼就看出来是重影。

正解：**一页只保留一个图位**。铺底和面板二选一。
内容页（有文字/卡片/图表的）→ 去掉铺底图，只留面板；背景改成极淡渐变
（`#0C0D13 → #08090C → #0A0B11` 对角），别用纯平色显得死。
只有封面 / 纯主张页才用整幅铺底。

`qa_layout.py` 已内置 `[重影]` 检查（按文件名去 `_panel` 后缀比对），
每页应输出 `OK（每张源图仅一次）`，PPTX 里每页 `<p:pic>` 应为 1。

### 坑 12：语义色也要过 WCAG，别只看"好看"

`tertiary_text: #5A5B66` 在 `#12131A` 卡片上只有 **2.9:1**，低于 AA 4.5:1
（页码、BEFORE 标签、图表标题、数据口径脚注都中招）。
→ 上调到 **`#7F8090`（4.75:1）**，spec_lock + 全部页面同步替换。

算 WCAG 时记住：`#6E7BFF` 这类高饱和色的**视觉冲击 ≠ 亮度对比**，
靛蓝对黑底只有 ~5.6:1，别想当然。

### 坑 13：🔴 验证器自己撒谎——读 font-size 必须解析继承

`text.get('font-size')` 只能拿到**写在自己身上**的字号。
字号经常写在父 `<g>` 上由子 `<text>` 继承：
```xml
<g id="tension-statement" font-size="56">   <!-- 只改这里 -->
  <text x="80" y="280">流程跑通了 97%</text>  <!-- 这里没有 font-size -->
</g>
```
只遍历 `<text>` 会把它当成默认 16px → **审计表完全失真，56px 的主句被记成 16px**。
我据此得出"字号都在阶梯上"的结论，用户一眼看出"一时大一时小"。

修法：`_iter_with_parents()` 带祖先链遍历 + `inherited_font_size()` 向上回溯。
溢出 / 压行 / 对比度三处**全部**要改继承感知，只改一处等于没改。

### 坑 14：锁「角色 → 字号档位」，别只锁字号集合

spec_lock 里写 `body: 16 / caption: 13` 不够，必须写死哪个角色用哪档，
否则同一角色在不同页会落到不同档。实测事故：

| 页 | 页面主句 |
|---|---|
| 02 / 07 | 56 |
| 03 | **72** |
| 04 / 05 | **44** |

四个尺寸干同一件事。统一成 `statement: 56` 后全篇才稳。

本项目现用阶梯（写进 `spec_lock.md`，`qa_layout.py` 从那里读，单一事实源）：
```
11 kicker   页眉小标
13 caption  页脚 / 页号 / 微标签（BEFORE·AFTER、图表轴、徽章副标）
16 body     正文 / 卡片内文 / chip / 终端行 / 图表数值
20 lead     强调层 / 徽章数字
24 subtitle 卡片标题 / 封面主张
32 title    封面英文副标
44 headline 大数字度量
56 statement 页面主句 ← 02/03/04/05/07 必须用同一档
96 cover    封面主标题
```
⚠️ **`- role: N` 后面不能跟行内注释**，ppt-master 解析器会报
`typography title must be a numeric px value: '32    # 注释'`。注释单独占一行。

## 🔁 交付前必跑的验收流程（用户明确要求"做好的工作要验证"）

改完 SVG **不许只看导出命令的返回码**，按顺序走完：

```bash
# 1) 渲染
/opt/homebrew/bin/python3 render_svg.py <proj>/svg_output qa_render

# 2) 版面总检：字号 / 溢出 / 压行 / 底图 / 重影 / 面板墨量 / WCAG
/opt/homebrew/bin/python3 qa_layout.py <proj>/svg_output qa_render
#    七项必须全部 OK，输出 ALL CLEAR 才算过

# 3) 门禁
python3 <ppt-master>/scripts/svg_quality_checker.py <proj> \
        --canonical-authoring --stage final --json      # blocking 必须为 0

# 4) 导出
python3 <ppt-master>/scripts/svg_to_pptx.py <proj> -o out.pptx

# 5) 回读导出物 —— 关键，别只信源文件
unzip -q out.pptx -d /tmp/chk
#    图片：每页 <p:pic> 数量、ppt/media/ 文件数
#    字号：grep sz= 换算（PPT 1pt = SVG 0.75px @1280×720，如 56px→42pt）
#          确认同一角色在各页落到同一 pt
```

**第 5 步不能省。** 源文件对了不代表导出对了；这次就是从 PPTX 反查 `sz=` 才确认
slide 2/3/4/5/7 的主句都是 42pt（=56px）。

改了以下任一处，**上面 1–5 全部重跑**：
字号 / 元素 y 坐标 / 图片引用 / 画布结构 / spec_lock。

## 语义化选图（比"好看"更重要）

配图要**承载这一页的论点**，不是装饰：

| 页面类型 | 该配什么 |
|---|---|
| 封面 | 结构性图形（晶格/网格/点阵），左侧或中央留大片空白给标题 |
| 张力/问题页 | 崩坏隐喻（断裂、乱结、分叉） |
| 能力页 | 通常**不需要**配图，图标 + 终端片段更有说服力 |
| 数据页 | 矢量图表，**不要**用 AI 图 |
| 收尾页 | 闭合/前向隐喻（圆环、光弧、地平线） |

**构图铁律**：先看那页文字在哪，再定图片内容落哪侧。文字在左 → 提示词写"内容落右半、左半留空"，再叠横向渐变遮罩。

## 产物位置

- 配图：`<project>/images/*.png` + `_raw_*.png`（原图保留）+ `*_panel.png`（主体裁切版，供面板引用）
- manifest（PPT Master 契约）：`<project>/images/image_prompts.json`，`acquisition_path` 填 `host-native`
- 导出：`output/*.pptx` + `build_preview.py` 生成的自包含预览 HTML
