<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock — fw2026-trends (v4 来源加固 + 高清升级版)

## v4 变更纪要（2026-09-30）
- 画布 1280×720 → **1920×1080**（坐标 ×1.5；字号取整：13→20 / 17→26 / 24→36 / 28→42 / 48→72 / 56→84 / 120→180 / 150→225）
  取整原因：qa_layout.py 字号阶梯解析只认整数（isdigit），小数会回退默认阶梯导致误报。
- 来源加固 7 处：P02 删 RED MAHOGANY 编号、删 MULBERRY/CITRUS ORANGE 色块（5→3 色块）；
  P08 走秀图去品牌化 + 标题"秀场瞬间"；P01 副标题/封面图注；P09 来源列表删 VOGUE；
  P06 引言署名 formosalive（转述）；P07 爵士鞋注 Celine Hiver 2026 秀场首推；P03 BioFluff 注 NYT/CFDA 报道。
- 图片：Pexels 全部换 full-res 原图（images_v4/，file + magick identify 已验）；
  Agnes 13 张复用（源图 ≥1024px，v4 展示尺寸内无需重生成）。
- 图注铁律 v4：不再标注品牌秀场归属；格式 = 主题 · 来源（PEXELS 真实摄影 / AGNES 生成）。

## canvas
- viewBox: 0 0 1920 1080
- format: PPT 16:9
- margin: 144px（≈ 画布宽度 7.5%，四边统一）
- grid: 12 栏 / 槽宽 36px（文字区 1–5 栏，图片 6–12 栏或全出血变体）

## communication
- primary_language: zh-Hans
- audience: 关注时尚趋势的消费者、买手、内容创作者
- objective: 呈现 2026 秋冬时尚趋势，给出可执行的购买与搭配建议
- core_message: 少买，但买得有特色
- consumption_mode: presented

## mode
- mode: showcase

## visual_style
- visual_style: luxury-editorial-v3（杂志思维：page role 轮换，9 页 6 种版式）
- layout_principle: 每页一种 role，每页只讲一件事；节奏 图→文→图→纯文字→图→引言→数字→图→收束
- page_roles: 01 Cover 全出血 / 02 Swatch Essay / 03 Detail Macro / 04 Typographic Hero / 05 Product Grid / 06 Pull Quote / 07 Hero Number / 08 Runway Strip / 09 Closing

## colors（60-30-10 秩序）
- background: #F5EFE6（骨色 60，纸面）
- primary_text: #1A1A1A（墨黑 30，非纯黑）
- accent: #7A1F2B（酒红 Red Mahogany 10，唯一强调色：kicker 线、页码、关键词）
- secondary_text: #575046（暖灰正文辅助，对比度 6.95:1 ≥ 4.5）
- gold: 已删除（v3 拿掉香槟金）
- scrim: linear-gradient 方向性渐隐（文字侧 85% → 0%）
- rule: NO frames（去框化，禁止双框线、圆角、投影）

## typography
- sizes: [20, 26, 36, 42, 72, 84, 180, 225]
- statement: 84
（5 级字阶，锁死）
- font_head_zh: Noto Serif CJK SC, weight 900 (Heavy，高对比宋体替代；中文标题字距 0.01em)
- font_didone: Bodoni Moda（英文/数字 Didone 系；英文 kicker 全大写 + 0.16em）
- font_body: Noto Sans CJK SC, sans-serif
- masthead: 20px / 500 / 0.22em 全大写 / 无衬线
- headline: 144–225px / 700–900 / 中文 0.01em / 行高 1.05
- deck: 36–42px / 400 / 衬线细体 / 0.015em / 行高 1.4
- body: 26–27px / 400 / 无衬线 / 行高 1.7
- caption: 20px / 500 / 0.18em 全大写 / 无衬线 / 行高 1.5（每张图强制图注，格式：主题 · 来源）
- pullquote: 60–84px / 400 italic / 衬线斜体 / 0.01em / 行高 1.25
- folio: 225px / Bodoni Moda 数字 / 8% 透明度墨黑 / 右下角
- 铁律：中文标题用 Heavy（900）高对比宋体；英文/数字标题用细→中字重（300–600）；层级靠字号对比（≈9:1）+ 字重分工，不靠单一字重

## details
- footer: FW26 TREND REPORT · PARIS — MILAN — NEW YORK（全大写，0.16em 字距）
- wine_line: 60px 长 1.5px 酒红线（章节分隔用，全页唯一强调色点）
- no_frames: 禁止任何框线分区
- image_post: 去饱和 12% + 胶片颗粒 + 微对比度（9 页统一杂志感；SVG 层用滤镜近似，渲染后以 qa panel 门禁复核）
- hero_bleed: hero 图必须出血至少一边
- caption_rule: 每张配图配 20px 全大写图注（含来源：PEXELS 真实摄影 或 AGNES 生成；不标注品牌秀场）
## page_map
- P01: role=Cover, rhythm=anchor
- P02: role=Swatch Essay, rhythm=dense
- P03: role=Detail Macro, rhythm=dense
- P04: role=Typographic Hero, rhythm=breathing
- P05: role=Product Grid, rhythm=dense
- P06: role=Pull Quote, rhythm=breathing
- P07: role=Hero Number, rhythm=dense
- P08: role=Runway Strip, rhythm=dense
- P09: role=Closing, rhythm=anchor
