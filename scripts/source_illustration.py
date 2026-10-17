#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_illustration.py — 三级配图路由的 asset 档：本地开源图库索引 + 授权核对 + 查询选图。

图库根：/Volumes/3TB_DATA/05-开发项目/agnes-studio-assets/open_source_posters
（4 个 GitHub 开源仓库的本地克隆，387M。本脚本不复制整库入库，只登记素材清单与出处。）

授权门禁（硬）：
1. 仓库根必须有 LICENSE 且为 MIT/BSD/Apache/ISC/CC0/zlib 系；无 LICENSE 仓库整体排除。
2. 仓库 LICENSE 只覆盖代码、不覆盖其中复刻的历史名家海报原作——这类文件标记
   artwork_rights="third-party-artwork"，默认排除，不做"代码许可=素材可用"的偷换。

用法：
  python3 scripts/source_illustration.py --build-index
  python3 scripts/source_illustration.py --query "架构 留白" --out /tmp/pick.png
  python3 scripts/source_illustration.py --report          # 授权审计口径，原样打印
退出码：0 选中；2 无匹配（候选原样打印，不硬塞）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from agnes_paths import assets_root

ASSET_ROOT = assets_root()
REPO_INDEX = Path(__file__).resolve().parent.parent / "data" / "asset_index.json"

LICENSE_RE = re.compile(r"MIT License|BSD|Apache|ISC|zlib|CC0|Creative Commons Zero", re.I)
IMG_PATTERNS = ("*.png", "*.jpg", "*.jpeg")
# 应用截图/录屏归档不是插画素材；原作复刻目录见 ARTWORK_EXCLUDE
DIR_EXCLUDE = {"node_modules", "screencasts", "archive", ".git", "screenshots"}
# 仓库 LICENSE 覆盖不了的历史/第三方作品目录（授权核对结论，2026-10-16 逐仓 README/LICENSE 检查）
ARTWORK_EXCLUDE = {"ResponsiveMullerBrockmann"}

# 中文查询 → 英文素材名/风格词的可核对映射（只做检索展开，不做语义伪装）
ALIAS = {
    "留白": ["minimal", "grid", "summary", "white"],
    "架构": ["grid", "steps", "content", "summary"],
    "结构": ["grid", "steps", "content"],
    "封面": ["cover", "poster"],
    "海报": ["cover", "poster"],
    "金句": ["quote"],
    "引用": ["quote"],
    "数据": ["content", "grid"],
    "科技": ["dark-tech", "cyberpunk"],
    "极简": ["minimal"],
    "国潮": ["guochao"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def check_repo(root: Path) -> dict:
    """返回仓库级授权结论。"""
    lic = None
    for name in ("LICENSE", "LICENSE.md", "COPYING"):
        p = root / name
        if p.exists():
            lic = p
            break
    if lic is None:
        return {"license": None, "accepted": False,
                "reason": "仓库无 LICENSE，整体排除（默认保留所有权利）"}
    head = lic.read_text(encoding="utf-8", errors="replace")[:400]
    m = LICENSE_RE.search(head)
    if not m:
        return {"license": "unknown", "accepted": False,
                "reason": "LICENSE 非宽松系或未识别，排除"}
    third_party = root.name in ARTWORK_EXCLUDE
    if third_party:
        return {"license": m.group(0), "accepted": False,
                "reason": "LICENSE 只覆盖代码；库内为历史名家海报复刻，画作权利不在授予范围，"
                          "默认排除（如需使用须单独核对原作版权状态）"}
    return {"license": m.group(0), "accepted": True, "reason": "ok"}


def tags_for(rel: str) -> list[str]:
    stem = re.sub(r"\.[a-z]+$", "", rel.split("/")[-1]).lower()
    parts = [p.lower() for p in re.split(r"[-_/]", stem) if p]
    dirs = [d.lower() for d in rel.split("/")[:-1] if d not in ("examples",)]
    return sorted(set(parts + dirs))


def build_index(root: Path = ASSET_ROOT) -> dict:
    entries, repo_notes = [], []
    for repo in sorted(p for p in root.iterdir() if p.is_dir()):
        verdict = check_repo(repo)
        repo_notes.append({"repo": repo.name, **verdict})
        if not verdict["accepted"]:
            continue
        for pat in IMG_PATTERNS:
            for p in sorted(repo.rglob(pat)):
                if any(part in DIR_EXCLUDE for part in p.parts):
                    continue
                rel = str(p.relative_to(repo))
                entries.append({
                    "path": str(p), "repo": repo.name, "rel": rel,
                    "tags": tags_for(rel), "license": verdict["license"],
                    "artwork_rights": "author-demo", "sha256_16": sha256(p),
                })
    return {"generated_from": str(root), "repos": repo_notes,
            "excluded_repos": [r["repo"] for r in repo_notes if not r["accepted"]],
            "entries": entries}


def load_index(path: Path = REPO_INDEX) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expand_query(q: str) -> list[str]:
    toks = []
    for raw in re.split(r"[\s,，、/]+", q):
        if not raw:
            continue
        toks.append(raw.lower())
        toks.extend(ALIAS.get(raw, []))
    return toks


def pick(index: dict, query: str):
    toks = expand_query(query)
    scored = []
    for e in index["entries"]:
        hay = ("/".join([e["repo"], e["rel"]]) + " " + " ".join(e["tags"])).lower()
        s = sum(2 for t in toks if t in e["tags"]) + sum(1 for t in toks if t in hay and t not in e["tags"])
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], x[1]["rel"]))
    return scored


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-index", action="store_true")
    ap.add_argument("--report", action="store_true", help="打印逐仓授权结论")
    ap.add_argument("--root", default=str(ASSET_ROOT))
    ap.add_argument("--index", default=str(REPO_INDEX))
    ap.add_argument("--query")
    ap.add_argument("--out")
    ap.add_argument("--emit-json", help="选图出处写入该 json 路径")
    a = ap.parse_args(argv)

    idx_path = Path(a.index)
    if a.build_index or not idx_path.exists():
        index = build_index(Path(a.root))
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        print("索引 %d 条素材 / 排除仓库 %s -> %s"
              % (len(index["entries"]), index["excluded_repos"], idx_path))
    else:
        index = load_index(idx_path)

    if a.report:
        for r in index["repos"]:
            print("%-28s license=%-10s accepted=%s  %s"
                  % (r["repo"], r["license"], r["accepted"], r["reason"]))
        print("素材条目 %d" % len(index["entries"]))
        return 0

    if a.query:
        scored = pick(index, a.query)
        if not scored:
            print("无匹配（查询词=%r 展开=%s；库内 tags=%s）"
                  % (a.query, expand_query(a.query),
                     sorted({t for e in index["entries"] for t in e["tags"]})))
            return 2
        if not a.out:
            for s, e in scored[:8]:
                print("  %-3d %s" % (s, e["rel"]))
            return 0
        score, e = scored[0]
        if Path(a.out).suffix.lower() in (".png", ".jpg", ".jpeg"):
            shutil.copyfile(e["path"], a.out)
        else:
            Path(a.out).with_suffix(".png").write_bytes(Path(e["path"]).read_bytes())
            a.out = str(Path(a.out).with_suffix(".png"))
        prov = {"picked": e["rel"], "source": e["path"], "repo": e["repo"],
                "license": e["license"], "artwork_rights": e["artwork_rights"],
                "sha256_16": e["sha256_16"], "score": score,
                "candidates": [x["rel"] for _, x in scored[:8]]}
        if a.emit_json:
            Path(a.emit_json).write_text(json.dumps(prov, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
        print(json.dumps(prov, ensure_ascii=False))
        return 0
    if not (a.build_index or a.report):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
