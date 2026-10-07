#!/usr/bin/env python3
"""Agnes 海报设计 -> PPT 封面素材桥接。

用 agnes-studio 的海报排版引擎设计一张 1200x1200 海报，
裁成 16:9 后放入 <project>/images/cover_agnes.png，
供 SVG 排版引用（href="../images/cover_agnes.png"）。

Agnes 位置：AGNES_STUDIO_ROOT 环境变量，默认黑苹果上的 agnes-studio-work。
依赖：Pillow、playwright（见 requirements.txt）。

示例：
    python3 scripts/agnes_design_cover.py --title "智能生产力" \\
        --subtitle "AI WORKFLOW" --style swiss_01 \\
        --project projects/agentflow-os-launch
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AGNES_ROOT = Path(os.environ.get(
    "AGNES_STUDIO_ROOT",
    "/Volumes/3TB_DATA/05-开发项目/agnes-studio-work",
))
AGNES_SCRIPTS = AGNES_ROOT / "scripts"

STYLES = [
    "swiss_01", "swiss_02",
    "article_01", "article_02",
    "cyber_01", "cyber_02",
    "chinese_01", "chinese_02",
    "cinema_01", "cinema_02",
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Agnes 海报设计 -> PPT 封面素材")
    p.add_argument("--title", required=True, help="海报主标题")
    p.add_argument("--subtitle", default="", help="英文副标题")
    p.add_argument("--body", default="", help="正文/标语")
    p.add_argument("--author", default="TOM // AGNES STUDIO", help="署名")
    p.add_argument("--style", default="swiss_01", choices=STYLES, help="海报风格")
    p.add_argument("--project", type=Path, required=True, help="ppt 项目目录")
    p.add_argument("--filename", default="cover_agnes.png", help="输出文件名")
    p.add_argument("--crop", default="top", choices=("top", "center", "bottom"),
                   help="1200x1200 裁 16:9 的锚点（海报标题多在上方，默认 top）")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not (AGNES_SCRIPTS / "pro_poster_renderer.py").exists():
        print(f"找不到 agnes-studio：{AGNES_ROOT}", file=sys.stderr)
        print("请设置 AGNES_STUDIO_ROOT 环境变量。", file=sys.stderr)
        return 1

    os.environ["AGNES_VENV_SWITCHED"] = "1"
    sys.path.insert(0, str(AGNES_SCRIPTS))
    from pro_poster_renderer import render_html_to_poster
    import studio_server as agnes_srv
    from PIL import Image

    project = args.project
    images_dir = project / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎨 Agnes 设计海报：style={args.style} title={args.title}")
    html = agnes_srv.generate_custom_poster_html(
        style=args.style,
        title=args.title,
        subtitle=args.subtitle,
        body=args.body,
        author=args.author,
        bg_uri="",
    )
    square_path = images_dir / "cover_agnes_square.png"
    render_html_to_poster(html, str(square_path))

    # 1200x1200 -> 1200x675（16:9）
    im = Image.open(square_path)
    assert im.size == (1200, 1200), im.size
    target_h = 675
    if args.crop == "top":
        top = 0
    elif args.crop == "bottom":
        top = 1200 - target_h
    else:
        top = (1200 - target_h) // 2
    im.crop((0, top, 1200, top + target_h)).save(images_dir / args.filename)
    print(f"✅ 封面素材：{images_dir / args.filename} (1200x675)")
    print(f"   方版原图：{square_path} (1200x1200)")
    print("下一步：在 SVG 里引用 href=\"../images/%s\"，然后跑质检与 PPTX 导出。" % args.filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
