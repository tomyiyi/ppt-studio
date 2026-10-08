#!/bin/bash
# 内容页 v2 spike 驱动：生成 → 三道门禁 → 导出 → 截图
set -u
S="/Volumes/3TB_DATA/05-开发项目/ppt/tools/ppt-master/skills/ppt-master"
PS="/Volumes/3TB_DATA/05-开发项目/ppt-studio"
PY="$PS/.venv/bin/python"; [ -x "$PY" ] || PY=/usr/local/bin/python3.11
D=/tmp/bkspike
P="$D/projD"
SRC="$PS/projects/workflow_full"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$P/svg_output" "$P/images" "$D/shotsD" "$D/shotsD1280"
cp /tmp/bkspike/coverproj/images/hero_blueprint.png "$P/images/" 2>/dev/null
"$PY" "$D/gen_pages_v2.py" "$P/svg_output" || { echo "生成失败"; exit 1; }

cp "$SRC/spec_lock.md" "$P/spec_lock.md"
python3 - "$P/spec_lock.md" <<'PY'
import sys
p = sys.argv[1]; s = open(p, encoding="utf-8").read()
if "- poster: 160" not in s:
    s = s.replace("- cover: 96", "- cover: 96\n- poster: 160")
open(p, "w", encoding="utf-8").write(s)
PY

cat > "$P/pages.json" <<'JSON'
{"pages": [
 {"index": 10, "layout": "table_v2", "title": "九档字号收紧后，同一角色不再忽大忽小",
  "bullets": ["所有文本字号落在锁定档位内", "同一源图不在一页出现两次", "文本不越出画布安全区",
              "相邻文本行盒不相交", "WCAG 文本对比度", "每页根节点带 <title>",
              "八项判据全部脚本化，交付前不再靠肉眼判断"]},
 {"index": 8, "layout": "flow_v2", "title": "三道门禁串行拦截，肉眼判断不参与交付",
  "bullets": ["md_to_pages", "agnes_bridge", "template_renderer", "plan_contract",
              "qa_score", "quality_checker", "svg_to_pptx",
              "门禁把「看起来对不对」换成「脚本判没判过」",
              "不通过 → 退回上一环节重跑（不进人工兜底）"]}
]}
JSON

echo "===== 门禁 1  svg_quality_checker"
"$PY" "$S/scripts/svg_quality_checker.py" "$P" --canonical-authoring --stage final --json > "$D/D_gate.txt" 2>&1
echo "exit=$?  ERROR行=$(grep -c 'ERROR' "$D/D_gate.txt")  WARN行=$(grep -c 'WARN' "$D/D_gate.txt")"
grep -m6 "ERROR" "$D/D_gate.txt"

echo "===== 门禁 2  plan_contract"
(cd "$PS" && "$PY" scripts/plan_contract.py --project "$P" 2>&1 | tail -10)

echo "===== 截图"
for f in "$P/svg_output"/*.svg; do
  b=$(basename "$f" .svg)
  "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox --window-size=1920,1080 \
    --force-device-scale-factor=1 --screenshot="$D/shotsD/$b.png" "file://$f" >/dev/null 2>&1
  sips -Z 1280 -s format png "$D/shotsD/$b.png" --out "$D/shotsD1280/$b.png" >/dev/null 2>&1
  echo "  $b.png $(stat -f%z "$D/shotsD/$b.png") bytes"
done

echo "===== 门禁 3  qa_layout"
(cd "$PS" && "$PY" scripts/qa_layout.py "$P/svg_output" "$D/shotsD1280" 2>&1 | tail -40)

echo "===== 导出"
(cd "$D" && "$PY" "$S/scripts/svg_to_pptx.py" projD -f ppt169 -o "$D/D.pptx" > "$D/D_export.log" 2>&1; echo "exit=$?")
tail -3 "$D/D_export.log"
echo "----- 字体面内嵌检查"
echo "  unsafe_exported_font_faces 命中=$(grep -c 'unsafe_exported_font_faces' "$D/D_export.log")"
grep -i "POSTFLIGHT\|unsafe_exported\|font" "$D/D_export.log" | head -6
[ -f "$D/D.pptx" ] && echo "  D.pptx $(stat -f%z "$D/D.pptx") bytes / slides=$(unzip -l "$D/D.pptx" | grep -c 'ppt/slides/slide[0-9]*\.xml')"
