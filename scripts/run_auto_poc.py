#!/usr/bin/env python3
import os
import re

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

base_path = "/Users/tom/Desktop/workspace/ppt-studio/projects/auto_poc"
tpl_169_path = "/Users/tom/Desktop/workspace/ppt/tools/ppt-master/skills/ppt-master/templates/layouts/editorial_bleed/templates"
tpl_43_path = "/Users/tom/Desktop/workspace/ppt/tools/ppt-master/skills/ppt-master/templates/layouts/presentation_core_43/templates"

def inject_svg(tpl_file, data_dict):
    if not os.path.exists(tpl_file):
        return f"<svg viewBox='0 0 1000 500'><text y='200'>{os.path.basename(tpl_file)} not found</text></svg>"
    with open(tpl_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
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

print("🛠️ [Step 2] 并行进行 SVG 模板注入 (双画幅自适应映射)")
for idx, page in enumerate(manifest):
    # 处理 16:9
    svg_169 = inject_svg(f"{tpl_169_path}/{page['role']['169']}", page['data'])
    with open(f"{base_path}/svg_16x9/page_{idx:02d}.svg", "w", encoding='utf-8') as f:
        f.write(svg_169)
        
    # 处理 4:3
    svg_43 = inject_svg(f"{tpl_43_path}/{page['role']['43']}", page['data'])
    with open(f"{base_path}/svg_4x3/page_{idx:02d}.svg", "w", encoding='utf-8') as f:
        f.write(svg_43)

print("✅ 双画幅 (16:9 & 4:3) SVG 生成完毕。")
