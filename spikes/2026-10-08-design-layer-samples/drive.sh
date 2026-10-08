#!/bin/bash
# spike 驱动 v2：修 sed 误伤（pptx_structure.mode 必须留 flat），门禁按计数复核
set -u
S=/Volumes/3TB_DATA/05-开发项目/ppt/tools/ppt-master/skills/ppt-master
PY=/Volumes/3TB_DATA/05-开发项目/ppt-studio/.venv/bin/python
[ -x "$PY" ] || PY=/usr/local/bin/python3.11
SRC=/Volumes/3TB_DATA/05-开发项目/ppt-studio/projects/workflow_full
D=/tmp/bkspike
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

for k in A B; do
  cp "$SRC/spec_lock.md" "$D/$k/spec_lock.md"
  # 只改「## mode」小节下的那一条 - mode:，以及 visual_style 行
  python3 - "$D/$k/spec_lock.md" "$k" <<'PY'
import sys
p, k = sys.argv[1], sys.argv[2]
mode = "instructional"
style = {"A": "blueprint", "B": "sketch-notes"}[k]
out, inmode = [], False
for ln in open(p):
    s = ln.rstrip("\n")
    if s.strip() == "## mode": inmode = True; out.append(s); continue
    if s.startswith("## "): inmode = False
    if inmode and s.startswith("- mode:"): s = "- mode: " + mode
    if s.startswith("- visual_style:"): s = "- visual_style: " + style
    out.append(s)
open(p, "w").write("\n".join(out) + "\n")
PY
  echo "[$k] $(grep -E '^- (mode|visual_style)' "$D/$k/spec_lock.md" | tr '\n' ' ') | $(grep -A1 '^## pptx_structure' "$D/$k/spec_lock.md" | tail -1)"
done

for k in A B; do
  echo "===== 门禁 $k ====="
  "$PY" "$S/scripts/svg_quality_checker.py" "$D/$k" --canonical-authoring --stage final --json \
    > "$D/${k}_gate.txt" 2>&1
  echo "exit=$?  ERROR=$(grep -c '\[ERROR\]' "$D/${k}_gate.txt")  WARN=$(grep -c '\[WARN\]' "$D/${k}_gate.txt")"
  grep '\[ERROR\]' "$D/${k}_gate.txt" | sed -n '2,7p'
done

for k in A B; do
  echo "===== 导出 $k ====="
  (cd "$D" && "$PY" "$S/scripts/svg_to_pptx.py" "$k" -f ppt169 -o "$D/${k}.pptx" 2>&1 | tail -3)
  [ -f "$D/${k}.pptx" ] && echo "  ${k}.pptx $(stat -f%z "$D/${k}.pptx") bytes / slides=$(unzip -l "$D/${k}.pptx" | grep -c 'ppt/slides/slide[0-9]*\.xml')"
done

echo "===== 截图 ====="
mkdir -p "$D/shots"
for k in A B; do
  for f in 00_cover 10_table 08_bullets; do
    "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
      --window-size=1920,1080 --force-device-scale-factor=1 \
      --screenshot="$D/shots/${k}_${f}.png" "file://$D/$k/$f.svg" >/dev/null 2>&1
  done
done
for f in 00_cover 10_table 08_bullets; do
  "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
    --window-size=1920,1080 --force-device-scale-factor=1 \
    --screenshot="$D/shots/C_${f}.png" "file://$SRC/svg_output/$f.svg" >/dev/null 2>&1
done
ls -l "$D/shots" | awk '{print $5, $9}'
