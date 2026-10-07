#!/usr/bin/env python3
"""auto_poc 双画幅 SVG 生成管线（POC 验证用）。

输出目录默认走仓库内 ``projects/auto_poc``（由本脚本位置向上推导 repo root），
可用 ``--base-dir`` 覆盖。

SVG 模板已 vendor 进本仓库（``vendor/ppt-master/templates/layouts``，
来源 hugohe3/ppt-master，MIT），开箱即用；
也可用 ``--tpl-169-dir`` / ``--tpl-43-dir`` 或 ``PPT_MASTER_ROOT`` 环境变量覆盖。
"""
import argparse
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = REPO_ROOT / "projects" / "auto_poc"
PPT_MASTER_ROOT = Path(os.environ.get(
    "PPT_MASTER_ROOT",
    str(REPO_ROOT / "vendor" / "ppt-master"),
))
DEFAULT_TPL_169_DIR = PPT_MASTER_ROOT / "templates" / "layouts" / "editorial_bleed" / "templates"
DEFAULT_TPL_43_DIR = PPT_MASTER_ROOT / "templates" / "layouts" / "presentation_core_43" / "templates"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="auto_poc 双画幅 SVG 生成管线（POC 验证用）")
    p.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR,
                   help=f"输出根目录（默认 {DEFAULT_BASE_DIR}）")
    p.add_argument("--tpl-169-dir", type=Path, default=DEFAULT_TPL_169_DIR,
                   help="16:9 模板目录（默认 vendor/ppt-master）")
    p.add_argument("--tpl-43-dir", type=Path, default=DEFAULT_TPL_43_DIR,
                   help="4:3 模板目录（默认 vendor/ppt-master）")
    return p.parse_args(argv)


def inject_svg(tpl_file, data_dict):
    tpl_file = Path(tpl_file)
    if not tpl_file.exists():
        return f"<svg viewBox='0 0 1000 500'><text y='200'>{tpl_file.name} not found</text></svg>"
    content = tpl_file.read_text(encoding='utf-8')

    # 强制将底图改为黑色调，注入 Agnes 的科技深邃风格背景代替白底
    # 找 <svg> 后插入背景
    bg_rect = '<rect width="100%" height="100%" fill="#08090C" />'
    content = content.replace('.svg">', f'.svg">{bg_rect}', 1)

    # 增强文本填充颜色，确保在深色模式下可见
    # 针对 16:9 editorial 和 4:3 常见白底文字，将文字填成浅色
    content = content.replace('fill="#000000"', 'fill="#FFFFFF"')
    content = content.replace('fill="#2D3748"', 'fill="#E2E8F0"')

    for k, v in data_dict.items():
        # 如果占位符有大括号 ({{TITLE}})
        content = content.replace(f'{{{{{k}}}}}', v)
        # 有些是单括号或者直接是大写 (TITLE)
        # 用正则保守点
        content = re.sub(r'\{\{?\s*' + k + r'\s*\}?\}', v, content)

    # 对于没填充满的 {{XXX}} 清空
    content = re.sub(r'\{\{[A-Z_0-9]+\}\}', '', content)
    return content


def main(argv=None):
    args = parse_args(argv)

    for name, d in (("16:9 模板", args.tpl_169_dir), ("4:3 模板", args.tpl_43_dir)):
        if not d.is_dir():
            raise SystemExit(
                f"错误：{name}目录不存在：{d}\n"
                "模板是外部依赖（兄弟仓库 ppt/tools/ppt-master），"
                "请用 --tpl-169-dir / --tpl-43-dir 或 PPT_MASTER_ROOT 环境变量指定正确位置。"
            )
    out_169 = args.base_dir / "svg_16x9"
    out_43 = args.base_dir / "svg_4x3"
    out_169.mkdir(parents=True, exist_ok=True)
    out_43.mkdir(parents=True, exist_ok=True)

    print("🚀 [Step 1] 启动工作流引擎... 加载强约束的极简内容契约及去AI味大纲")

    # 这里模拟了从大模型产出，并且经过字数过滤器拦截洗稿后的结果
    # 没有废话，只有干货
    manifest = [
        {
            "page": "01_cover",
            "role": {"169": "01_hero_full.svg", "43": "01_title_slide.svg"},
            "data": {
                "TITLE": "无人驾驶商业化临界点",
                "SUBTITLE": "特斯拉 FSD V14 架构深度剖析",
                "KEY_MESSAGE": "无人驾驶商业化临界点"
            }
        },
        {
            "page": "02_kpi",
            "role": {"169": "09_full_statement.svg", "43": "12_kpi_grid.svg"},
            "data": {
                "PAGE_TITLE": "核心突破",
                "TITLE": "端到端网络打通",
                "KEY_MESSAGE": "接管率环比下降 97%",
                "SUBTITLE": "纯视觉路线首次在复杂市区路段实现零干预通行。",
                "KPI_1": "99.8%",
                "KPI_2": "-97%",
                "KPI_3": "0.1s",
                "KPI_4": "L4级",
                "CONTENT_AREA": "纯视觉路线在复杂交通流中实现泛化，重定义算力算法闭环。"
            }
        }
    ]

    print("🛠️ [Step 2] 并行进行 SVG 模板注入 (双画幅自适应映射)")
    for idx, page in enumerate(manifest):
        # 处理 16:9
        svg_169 = inject_svg(args.tpl_169_dir / page['role']['169'], page['data'])
        (out_169 / f"page_{idx:02d}.svg").write_text(svg_169, encoding='utf-8')

        # 处理 4:3
        svg_43 = inject_svg(args.tpl_43_dir / page['role']['43'], page['data'])
        (out_43 / f"page_{idx:02d}.svg").write_text(svg_43, encoding='utf-8')

    print("✅ 双画幅 (16:9 & 4:3) SVG 生成完毕。")


if __name__ == "__main__":
    main()
