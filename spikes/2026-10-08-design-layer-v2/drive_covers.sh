#!/bin/bash
# 封面 v2 spike 驱动：生成 → 门禁 → 契约 → 导出 → 截图 → 版面复核（全在黑苹果上跑）
set -u
S="/Volumes/3TB_DATA/05-开发项目/ppt/tools/ppt-master/skills/ppt-master"
PS="/Volumes/3TB_DATA/05-开发项目/ppt-studio"
PY="$PS/.venv/bin/python"; [ -x "$PY" ] || PY=/usr/local/bin/python3.11
D=/tmp/bkspike
P="$D/projC"
SRC="$PS/projects/workflow_full"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$P/svg_output" "$P/images" "$D/shotsC"
cp /tmp/bkspike/coverproj/images/hero_blueprint.png /tmp/bkspike/coverproj/images/hero_duotone2.png "$P/images/"
"$PY" "$D/gen_covers.py" "$P/svg_output" || { echo "生成失败"; exit 1; }

# spec_lock：沿用真实项目的锁定档，只加一条提案档位 poster: 160
cp "$SRC/spec_lock.md" "$P/spec_lock.md"
python3 - "$P/spec_lock.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "- poster: 160" not in s:
    s = s.replace("- cover: 96", "- cover: 96\n# 2026-10-08 封面 v2 提案：poster 档（160），\n"
                "# 相邻 1.25 倍档差导致「填字感」，封面需要 2.5~5 倍尺度跳跃\n- poster: 160")
    open(p, "w", encoding="utf-8").write(s)
print([l for l in s.splitlines() if l.startswith("- poster") or l.startswith("- cover")])
PY

echo "===== 门禁 1  svg_quality_checker"
"$PY" "$S/scripts/svg_quality_checker.py" "$P" --canonical-authoring --stage final --json \
  > "$D/C_gate.txt" 2>&1
echo "exit=$?  ERROR=$(grep -c '\[ERROR\]' "$D/C_gate.txt")  WARN=$(grep -c '\[WARN\]' "$D/C_gate.txt")"
grep '\[ERROR\]' "$D/C_gate.txt" | head -6

echo "===== 门禁 2  plan_contract"
# pages.json：把每页要落地的文字登记进契约，逼渲染器不许「放不下就不画」
cat > "$P/pages.json" <<'JSON'
{"pages": [
 {"index": 0, "layout": "v1_type_only", "title": "文字进槽 不等于设计",
  "bullets": ["每页要有主张、有证据、有视觉主角", "封面不是一张氛围图压一行小字",
              "01  现状 · 三个硬伤", "02  方法 · 契约 + 尺度 + 证据", "03  结果 · 可编辑 pptx"]},
 {"index": 1, "layout": "v2_split_bleed", "title": "文字进槽 不等于设计",
  "bullets": ["每页要有主张、有证据、", "有视觉主角；底图只承担信息，", "不做氛围糊图",
              "汇报  PPT STUDIO 设计层", "2026-10-08 · spike v2"]},
 {"index": 2, "layout": "v3_duotone", "title": "文字进槽 不等于设计",
  "bullets": ["每页要有主张、有证据、有视觉主角", "全幅底图 · 单色压平 · 文字走图内左净空区"]}
]}
JSON
(cd "$PS" && "$PY" scripts/plan_contract.py --project "$P" 2>&1 | tail -12)

echo "===== 截图（qa_layout 与人工复核都要用）"
for f in "$P/svg_output"/*.svg; do
  b=$(basename "$f" .svg)
  "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
    --window-size=1920,1080 --force-device-scale-factor=1 \
    --screenshot="$D/shotsC/$b.png" "file://$f" >/dev/null 2>&1
  echo "  $b.png $(stat -f%z "$D/shotsC/$b.png") bytes"
done

echo "===== 门禁 3  qa_layout（字号/底图/重影/溢出/压行/面板/对比）"
# qa_layout 按 SVG 坐标 1:1 取样，必须给它 1280x720 的渲染图
mkdir -p "$D/shotsC1280"
for f in "$D/shotsC"/*.png; do
  sips -Z 1280 -s format png "$f" --out "$D/shotsC1280/$(basename "$f")" >/dev/null 2>&1
done
(cd "$PS" && "$PY" scripts/qa_layout.py "$P/svg_output" "$D/shotsC1280" 2>&1 | tail -70)

echo "===== 导出 svg_to_pptx"
(cd "$D" && "$PY" "$S/scripts/svg_to_pptx.py" projC -f ppt169 -o "$D/C.pptx" > "$D/C_export.log" 2>&1; echo "exit=$?")
tail -4 "$D/C_export.log"
echo "----- 字体面内嵌检查"
echo "  unsafe_exported_font_faces 命中=$(grep -c 'unsafe_exported_font_faces' "$D/C_export.log")"
grep -i "POSTFLIGHT\|unsafe_exported\|font" "$D/C_export.log" | head -6
[ -f "$D/C.pptx" ] && echo "  C.pptx $(stat -f%z "$D/C.pptx") bytes / slides=$(unzip -l "$D/C.pptx" | grep -c 'ppt/slides/slide[0-9]*\.xml')"

echo "===== 可编辑性复核（形状数 / 文本 run 数 / 图片数）"
"$PY" - "$D/C.pptx" <<'PY'
import sys, zipfile, re
z = zipfile.ZipFile(sys.argv[1])
for n in sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)):
    x = z.read(n).decode("utf-8")
    print("  ", n, "shapes=", x.count("<p:sp>"), "runs=", x.count("<a:t>"),
          "pics=", x.count("<p:pic>"))
PY
