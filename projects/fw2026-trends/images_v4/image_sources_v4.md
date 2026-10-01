# fw2026-trends v4 · 图片来源清单

> 建档日期 2026-09-30。v3 未落盘记录 Pexels 源 URL，本次补记并固化映射关系。

## 实拍（Pexels，免费商用许可）

| v4 文件 | 内容对应 v3 | 尺寸 | 摄影师 | 备注 |
|---|---|---|---|---|
| real_cover.jpg | real_cover.jpg（1281×1920 压缩版） | 4015×6016 | 待核实 | 原图 = images_v3/new_cover_src.jpg，经 RMSE 内容校验一致；v3 图注已删具体人名 |
| real_colour.jpg | real_colour.jpg（960×1440 压缩版） | 1920×2880 | 待核实 | 原图 = images_v3/real_colour.orig.jpg，经 RMSE 内容校验一致 |
| real_style.jpg | real_style.jpg（1081×1920 压缩版） | 3512×6240 | EYÜPCAN TIMUR（v3 已验证，B 级） | 原图 = images_v3/new_style_src.jpg，经 RMSE 内容校验一致 |
| real_runway1.jpg | 同名 | 1920×2880 | 待核实 | v3 即为 1920 宽版本，沿用；P08 图注已去品牌化 |
| real_runway2.jpg | 同名 | 1920×1372 | 待核实 | 同上 |
| real_runway3.jpg | 同名 | 1920×1280 | 待核实 | 同上 |
| real_street.jpg | 新拍（Pexels photo 19329361） | 3441×5161（工作副本 2667×4000） | Samed S. | 2026-10-01 替换旧 500×750 版本。内容：金发女子穿优雅大衣走过秋日历史街区 （街拍主题，P06 右图 315×720 / P02 0.1 透明底纹）；真原图归档 real_street.fullres.jpg；Pexels 免费许可 https://www.pexels.com/license/ |

## AI 生成（Agnes agnes-image-2.5-flash）

13 张 ai_*.jpg 自 images_v3 原样复用（1024×1024 / 1248×832 / 1312×736），v4 展示尺寸均小于源图，无需重生成。
图注如实标注"AGNES 生成"。

## 验证

全部 20 个文件经 `file`（JPEG SOI 头）+ `magick identify` 验证文件头完好，无传输损坏。

## 渲染上限说明（2026-09-30 实测）

- real_cover.jpg（4015×6016）/ real_style.jpg（3512×6240）的真原图已归档为
  real_cover.fullres.jpg / real_style.fullres.jpg（字节级保留，file + identify 已验）。
- 工作副本按长边 4000px 等比降采样（2670×4000 / 2251×4000）：实测 24MP 原图
  + SVG 去饱和滤镜会导致本机 headless Chrome 截图时 target crashed（内存压力）；
  1920×1080 输出下 4000px（约 2x 过采样）无可见损失。
- SVG 引用的均为工作副本；真原图留档备查。
