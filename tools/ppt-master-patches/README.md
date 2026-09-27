# ppt-master 外部兼容补丁

## 用途

`ppt-master` 导出的短小、带正字距的全大写拉丁微标签，在 LibreOffice 中可能发生末字折行。该补丁只作用于 DrawingML 单行文本框的宽度估算；PPT Studio 的 SVG、主题、HTML 和布局流水线不改。

目标上游文件：`scripts/svg_to_pptx/drawingml/elements.py`

补丁条件：非 CJK、全大写、`letter_spacing_px > 0`。

经验值：`_TRACKED_CAPS_HEADROOM = 1.14`。DSH 上已对 1.13/1.14/1.15/1.16 做 LibreOffice PDF 实测；1.13 仍折行，1.14 起通过。本值是当前 deck 的最低已验证值，不宣称对所有字体和 Office 版本普适。

## 应用和验收

```bash
cd <ppt-master>
git apply <ppt-studio>/tools/ppt-master-patches/libreoffice-tracked-caps.patch
```

然后用干净的 Light/Dark themed project 导出 PPTX，必须运行项目 `qa_pptx.py`，并用 LibreOffice 转 PDF 后确认第 06 页 `BEFORE`、`AFTER` 均为单行；不得出现 `BEFOR`/`E` 或 `AFTE`/`R`。

该补丁不应改动 PPT Studio 的 SVG、theme、HTML 文件。
