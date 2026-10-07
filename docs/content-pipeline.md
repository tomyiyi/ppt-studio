# 内容驱动管线：Markdown 文章 -> PPTX

源自 ContentForge 知识库的内容生产管线思想（想法→主题→写文→配图→排版→推送），
在 ppt-studio 落地为"文章进、PPTX 出"的最小可用闭环。

## 一键用法

```bash
python3 scripts/md_to_pptx.py --md <文章.md> --out <输出目录> [--name deck]
```

## 六阶段

1. **切页**（`md_to_pages.py`）：`##` 节 -> 页；列表 -> 要点；`>` -> 封面副标题；
   layout 自动推导（compare/steps/bullets）
2. **渲染**（`pages_to_svg.py`）：cover/bullets/compare/steps 四版式，
   1280x720，60px 边距，字号吸附阶梯档
3. **合同校验**（`plan_contract.py`）：images 引用 + spec_lock 完整性
4. **打分质检**（`qa_score.py`）：6 项 0-100 打分，阈值 80
5. **vendor 门禁**（`svg_quality_checker.py`）：blocking 必须为 0
6. **转 PPTX**（`svg_to_pptx.py`）：原生 DrawingML，可编辑

## 相关模块

- `scripts/prompt_safety.py`：生图 prompt 安全拦截（配图阶段用）
- `scripts/cover_archetypes.py`：封面原型推导（`agnes_design_cover.py --platform/--tone`）

## 环境要求

- vendor 转换链需 Python 3.10+（黑苹果：`/usr/local/bin/python3.11`，脚本自动选用）
- `python-pptx`、`pillow`（3.11 下需另装）

## 已验证

- "AI Agent开发的5条硬核准则" -> 9 页 SVG -> 9 页 PPTX（plan PASS，qa 9/9 满分）
- "Transformer 类比" -> 5 页 PPTX，一键通过
