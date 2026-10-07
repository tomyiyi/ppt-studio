#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes Studio -> PPT Master 配图桥接器
=====================================

把 Agnes Studio 的生图能力接成 PPT Master 的 **Path B（host-native image tool）**。

契约来源（ppt-master/skills/ppt-master/references/）：
  - image-generator.md §6  manifest schema   -> project/images/image_prompts.json
  - image-generator.md §7  Path B            -> 输出落到 project/images/<filename>，回写 Generated
  - svg-image-embedding.md                   -> SVG 里用 <image href="../images/xxx.png" .../>

用法：
  # 1) 跑 manifest（只处理 Pending）
  python3 agnes_ppt_bridge.py --manifest <project>/images/image_prompts.json

  # 2) 单张即席出图（re-roll）
  python3 agnes_ppt_bridge.py --prompt "..." --filename cover_bg.png \
          --project <project> --aspect_ratio 16:9

  # 3) 只把 manifest 渲染成 Markdown 伴生（不生图）
  python3 agnes_ppt_bridge.py --render-md <project>/images/image_prompts.json

依赖：只用标准库（urllib/json/pathlib）。生图走本机 New API（127.0.0.1:3000）。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from prompt_safety import assert_prompt_safe  # ContentForge 白瓷肌安全拦截

# ---------------------------------------------------------------- 配置解析

def load_gateway() -> tuple[str, str]:
    """复用 Agnes Studio 的 ~/.new-api/local_key.json，不另存密钥。"""
    p = Path.home() / ".new-api" / "local_key.json"
    base, key = "http://127.0.0.1:3000/v1", ""
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            base = d.get("base_url") or base
            key = d.get("api_key") or key
        except Exception as e:
            print(f"[warn] 读取网关配置失败: {e}")
    return base.rstrip("/"), key


# ------------------------------------------------- 宽高比 -> 尺寸 / 模型

# 优先选「原生带比例后缀」的模型，避免后端拉伸或留白边。
# 顺序即优先级：先试原生比例模型，再退回通用模型 + size 参数。
RATIO_SIZE = {
    "16:9": "1920x1080",
    "21:9": "2560x1080",
    "4:3":  "1600x1200",
    "3:4":  "1200x1600",
    "1:1":  "1440x1440",
    "3:2":  "1800x1200",
    "2:3":  "1200x1800",
}

RATIO_SUFFIX = {"16:9": "16x9", "21:9": "21x9", "4:3": "4x3", "3:4": "3x4", "1:1": "1x1"}


# ============================================================================
# 红线：生图只走 Agnes，绝不用 gemini
# ----------------------------------------------------------------------------
# 原因：本机 gemini 是反代（中转文本通道 /v1/chat/completions），没有可靠的
# 图像生成能力。PPT Master 的 README 虽然推荐 gemini-3.1-flash-image，但那是
# 直连 Google 官方的假设；本机的 gemini-* 模型一律排除。
# 语言模型（驱动流程）用 gemini 反代没问题 —— 那是宿主 Agent 自己的事，
# 与生图后端无关。两者不要混。
# ============================================================================
BLOCKED_IMAGE_MODELS = ("gemini", "dall-e", "gpt-image", "flux", "seedream")


def candidate_models(ratio: str, preferred: str | None = None) -> list[str]:
    """按优先级给出候选模型 —— 只有 Agnes 系列。

    preferred 来自 manifest 的 items[].model；若它命中黑名单则直接忽略并告警。
    """
    out: list[str] = []
    if preferred:
        low = preferred.lower()
        if any(b in low for b in BLOCKED_IMAGE_MODELS):
            print(f"    [红线] 忽略被禁模型 {preferred}（生图只走 Agnes）")
        else:
            out.append(preferred)
    out += ["agnes-image-2.5-flash", "agnes-image-2.1-flash"]
    # 去重保序
    seen, res = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            res.append(m)
    return res


# ---------------------------------------------------------------- 生成

def generate(prompt: str, ratio: str = "16:9", model: str | None = None,
             retries: int = 2, timeout: int = 180) -> dict:
    """调 New API /v1/images/generations，返回 {ok, bytes, via, cost_s, error}。"""
    try:
        assert_prompt_safe(prompt)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    base, key = load_gateway()
    size = RATIO_SIZE.get(ratio, "1920x1080")
    payload_base = {"prompt": prompt, "n": 1, "size": size,
                    "response_format": "b64_json"}  # 直接拿 base64，绕开 CDN

    last_err = None
    for m in candidate_models(ratio, model):
        for attempt in range(retries + 1):
            t0 = time.time()
            body = json.dumps({**payload_base, "model": m}).encode("utf-8")
            req = urllib.request.Request(
                f"{base}/images/generations", data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "User-Agent": "AgnesStudio-PPTBridge/1.0",
                         **({"Authorization": f"Bearer {key}"} if key else {})},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                items = data.get("data") or []
                if not items:
                    last_err = f"{m}: 返回空 data"
                    break
                it = items[0]
                raw = None
                if it.get("b64_json"):
                    raw = base64.b64decode(it["b64_json"])
                elif it.get("url"):
                    # CDN 下载间歇性挂起：短超时 + 3 次重试，仍失败则抛给外层重试换模型
                    raw = None
                    dl_err = None
                    for _ in range(2):
                        try:
                            with urllib.request.urlopen(it["url"], timeout=15) as r2:
                                raw = r2.read()
                            break
                        except Exception as e:
                            dl_err = e
                            time.sleep(3)
                    if raw is None:
                        raise RuntimeError(f"图片 URL 下载失败(2次): {dl_err}")
                if not raw:
                    last_err = f"{m}: 无 b64_json 也无 url"
                    break
                return {"ok": True, "bytes": raw, "via": m,
                        "cost_s": round(time.time() - t0, 1), "size": size}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:200]
                last_err = f"{m}: HTTP {e.code} {detail}"
                if e.code in (400, 401, 404, 422):   # 模型级问题，换下一个
                    break
            except Exception as e:
                last_err = f"{m}: {type(e).__name__} {e}"
            time.sleep(2)
    return {"ok": False, "error": last_err or "无可用模型"}


def save_image(res: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(res["bytes"])
    return out_path


def probe_dimensions(png: Path):
    """不依赖 PIL，直接从 PNG 头读宽高。"""
    try:
        with png.open("rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(head[16:20], "big")
            h = int.from_bytes(head[20:24], "big")
            return w, h
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------- manifest

def run_manifest(manifest_path: Path, only: list[str] | None = None, force: bool = False) -> int:
    mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_dir = manifest_path.parent.parent          # <project>/images/xxx.json -> <project>
    images_dir = manifest_path.parent

    items = mf.get("items") or []
    todo = [it for it in items
            if (force or str(it.get("status", "Pending")).lower() == "pending")
            and (not only or it.get("filename") in only)]

    print(f"· manifest {manifest_path.name}: 共 {len(items)} 项，待生 {len(todo)} 项")
    ok = fail = 0

    for it in todo:
        fn = it.get("filename")
        if not fn:
            print("  [skip] 缺 filename")
            continue
        ratio = it.get("aspect_ratio", "16:9")
        print(f"  → {fn}  ({ratio}, {it.get('purpose','')[:40]})")
        res = generate(it.get("prompt", ""), ratio=ratio, model=it.get("model"))
        if not res.get("ok"):
            it["status"] = "Failed"
            it["error"] = res.get("error")
            fail += 1
            print(f"    ✗ {res.get('error')}")
            continue
        out = save_image(res, images_dir / fn)
        w, h = probe_dimensions(out)
        it["status"] = "Generated"
        it["model"] = res["via"]
        it["dimensions"] = f"{w}x{h}" if w else None
        it.pop("error", None)
        ok += 1
        kb = out.stat().st_size // 1024
        print(f"    ✓ {w}x{h} {kb}KB  via {res['via']}  ({res['cost_s']}s)")

    manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
    render_md(manifest_path)
    print(f"✓ 完成 {ok} 项，失败 {fail} 项 → {manifest_path}")
    return 1 if fail else 0


def render_md(manifest_path: Path) -> Path:
    """生成 image_prompts.md 伴生（PPT Master 要求的 sidecar）。"""
    mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    out = manifest_path.with_suffix(".md")
    lines = [f"# {mf.get('project', manifest_path.parent.parent.name)} — 图片清单", ""]
    if mf.get("deck_rendering"):
        lines += [f"- 渲染风格：`{mf['deck_rendering']}`", ""]
    cs = mf.get("color_scheme") or {}
    if cs:
        lines += ["| 角色 | 色值 |", "|---|---|"]
        lines += [f"| {k} | `{v}` |" for k, v in cs.items()]
        lines.append("")
    lines += ["| Filename | 用途 | 比例 | 状态 | 模型 | 尺寸 |", "|---|---|---|---|---|---|"]
    for it in mf.get("items") or []:
        lines.append("| {fn} | {p} | {ar} | {st} | {mo} | {dm} |".format(
            fn=it.get("filename", ""),
            p=(it.get("purpose") or "").replace("|", "/"),
            ar=it.get("aspect_ratio", ""),
            st=it.get("status", ""),
            mo=it.get("model", "-"),
            dm=it.get("dimensions") or "-",
        ))
    lines += ["", "## Prompts", ""]
    for it in mf.get("items") or []:
        lines += [f"### {it.get('filename','')}", "",
                  "```", (it.get("prompt") or "").strip(), "```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"· sidecar → {out}")
    return out


# ---------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="Agnes Studio → PPT Master 配图桥接器")
    ap.add_argument("--manifest", help="PPT Master 的 images/image_prompts.json")
    ap.add_argument("--render-md", metavar="MANIFEST", help="只渲染 Markdown 伴生")
    ap.add_argument("--prompt", help="即席生图（配合 --filename/--project）")
    ap.add_argument("--filename", help="输出文件名，如 cover_bg.png")
    ap.add_argument("--project", help="项目目录（单张模式）")
    ap.add_argument("--aspect-ratio", dest="aspect_ratio", default="16:9")
    ap.add_argument("--model", help="指定后端模型")
    ap.add_argument("--only", nargs="*", help="只处理这些 filename")
    ap.add_argument("--force", action="store_true", help="连 Generated 的也重跑")
    args = ap.parse_args()

    if args.render_md:
        render_md(Path(args.render_md))
        return 0

    if args.manifest:
        return run_manifest(Path(args.manifest), only=args.only, force=args.force)

    if args.prompt:
        if not (args.filename and args.project):
            print("[err] 单张模式需同时给 --filename 和 --project")
            return 2
        out = Path(args.project) / "images" / args.filename
        print(f"· 即席生图 {args.filename} ({args.aspect_ratio})")
        res = generate(args.prompt, ratio=args.aspect_ratio, model=args.model)
        if not res.get("ok"):
            print(f"✗ {res.get('error')}")
            return 1
        save_image(res, out)
        w, h = probe_dimensions(out)
        print(f"✓ {out}  {w}x{h}  {out.stat().st_size//1024}KB  via {res['via']}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
