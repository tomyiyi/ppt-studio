<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- width: 1280
- height: 720
- viewBox: 0 0 1280 720
- format: PPT 16:9

## communication
- primary_language: zh-Hans
- audience: 技术决策者、平台工程负责人、早期采用者
- objective: 发布智流 OS，让受众看见能力本身并知道下一步怎么开始
- core_message: 不是更大的模型，是能真正动手的运行时
- consumption_mode: presented

## mode
- mode: showcase

## visual_style
- visual_style: product-launch

## colors
- background: #08090C
- surface: #12131A
- divider: #23242E
- primary_text: #F7F7F9
- secondary_text: #8E8F9A
- tertiary_text: #7F8090   # 2026-09-23 由 #5A5B66 上调：原值在 #12131A 上仅 2.9:1，低于 WCAG AA 4.5:1；现值 4.75:1
- accent: #6E7BFF
- improvement: #4ADE80
- neutral_bar: #3A3B45
- terminal_bg: #0E0F14

## typography
- font_family: Microsoft YaHei, Arial
- title_family: Microsoft YaHei, sans-serif
- body_family: Microsoft YaHei, Arial, sans-serif
- mono_family: Consolas, monospace
# 2026-09-23 收紧。原来 11~96 共 12 档，用下来同一角色在不同页落到不同档：
# 正文有的 16 有的 14、微标签有的 13 有的 12，全篇翻着就是"一时大一时小"。
# 现压到 8 档并写死「角色 → 档位」；12 / 14 / 56 / 72 四档停用。
#   kicker    页眉小标（letter-spacing 4）
#   caption   页脚 / 页号 / 微标签（BEFORE·AFTER、图表轴、徽章副标）
#   body      正文 / 卡片内文 / chip / 终端行 / 图表数值
#   lead      强调层（与正文区分的那一级）/ 徽章数字
#   subtitle  卡片标题 / 封面主张
#   title     封面英文副标
#   headline  大数字度量（41% / 6.2h / 3.4x）
#   statement 页面主句——02/03/04/05/07 必须统一用这一档
#   cover     封面主标题
# 2026-09-23 再修：主句这一档此前四页用了四个尺寸（03=72、02/07=56、04/05=44），
# 翻页就是"一时大一时小"。现全部归到 56；72 停用。
- kicker: 11
- caption: 13
- body: 16
- lead: 20
- subtitle: 24
- title: 32
- headline: 44
- statement: 56
- cover: 96
# 封面 P1 纯排版标题档位，不参与正文阶梯
- poster: 160

## grid
# 版心/栅格真相源。margin 取 L-01（画布宽 6%）；自检 76+12×72+11×24+76==1280
- margin: 76
- cols: 12
- col: 72
- gut: 24
- bands: 4 8 12 16 24 32 48 64
- baseline_step: 8

## icons
- library: tabler-outline
- stroke_width: 2
- inventory: bolt, refresh, plug-connected, shield-check, brain

## page_rhythm
- P01: anchor cover, breathing generous
- P02: anchor tension-statement, breathing generous
- P03: anchor position-claim, breathing generous
- P04: anchor capability-reveal, dense left-light right-artifact
- P05: anchor capability-reveal, dense left-light right-artifact
- P06: anchor before-after, dense moderate
- P07: anchor next-step, breathing generous

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
- 不要使用任何阴影、发光和渐变 (user)
- 一页只讲一个能力，不要在一页放两个 reveal (user)
- 标题写受众能得到什么，不要写功能名 (user)
