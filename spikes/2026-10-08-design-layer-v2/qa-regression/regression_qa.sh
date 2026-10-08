#!/bin/bash
# qa_layout.py 三处修正的回归对账：同一批渲染图，跑「改前」与「改后」两版，逐页比输出。
# 样本 = 现有 18 页 workflow_full + 本轮 spike 的 3 封面 / 2 内容页（含三条已知误判用例）
set -u
PS="/Volumes/3TB_DATA/05-开发项目/ppt-studio"
PY="$PS/.venv/bin/python"; [ -x "$PY" ] || PY=/usr/local/bin/python3.11
D=/tmp/bkspike
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
R=/tmp/bkreg
mkdir -p "$R/old" "$R/new"

# 改前版本从 git 取，保证不是我手写的近似版
(cd "$PS" && git show HEAD:scripts/qa_layout.py) > "$R/old/qa_layout.py"
cp "$D/qa_layout.py" "$R/new/qa_layout.py"
echo "改前 $(wc -l < "$R/old/qa_layout.py") 行 / 改后 $(wc -l < "$R/new/qa_layout.py") 行"
grep -q "Otsu" "$R/new/qa_layout.py" || { echo "新版未含 Otsu 修正 → 同步失败"; exit 1; }
grep -q "Otsu" "$R/old/qa_layout.py" && { echo "git 取到的版本已含修正 → 对账无效"; exit 1; }

SETS="wf:$PS/projects/workflow_full/svg_output
C:/tmp/bkspike/projC/svg_output
D:/tmp/bkspike/projD/svg_output"

# 渲染一次，两版共用（qa_layout 按 SVG 坐标 1:1 取样，必须 1280x720）
echo "$SETS" | while IFS=':' read -r tag dir; do
  mkdir -p "$R/shots1280/$tag"
  for f in "$dir"/*.svg; do
    b=$(basename "$f" .svg)
    [ -f "$R/shots1280/$tag/$b.png" ] && continue
    "$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
      --window-size=1920,1080 --force-device-scale-factor=1 \
      --screenshot="$R/tmp_$b.png" "file://$f" >/dev/null 2>&1
    sips -Z 1280 -s format png "$R/tmp_$b.png" --out "$R/shots1280/$tag/$b.png" >/dev/null 2>&1
    rm -f "$R/tmp_$b.png"
  done
  echo "  渲染 $tag: $(ls "$R/shots1280/$tag" | wc -l) 张"
done

for ver in old new; do
  : > "$R/$ver.txt"
  echo "$SETS" | while IFS=':' read -r tag dir; do
    echo "##### $tag" >> "$R/$ver.txt"
    (cd "$R/$ver" && "$PY" qa_layout.py "$dir" "$R/shots1280/$tag" 2>&1) >> "$R/$ver.txt"
  done
done

echo
echo "===== 总判定"
for ver in old new; do
  printf "  %-4s → %s   （压行 %s 条 / 面板行 %s / 不达标行 %s）\n" "$ver" \
    "$(grep -E 'ALL CLEAR|待修' "$R/$ver.txt" | tr '\n' ' ')" \
    "$(grep -c '\[压行\]' "$R/$ver.txt")" \
    "$(grep -c '\[面板\]' "$R/$ver.txt")" \
    "$(grep -c ':1  «' "$R/$ver.txt")"
done

echo
echo "===== 逐页差异（改前 → 改后）"
diff "$R/old.txt" "$R/new.txt" | sed -n '1,160p'
