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
  python3 agnes_ppt_bridge.py --render-md [manifest/project]

  # 4) 客观门禁校验 / 交付验收
  python3 agnes_ppt_bridge.py --check [manifest/project]

依赖：生图走本机 New API（默认 127.0.0.1:13000/v1；也可由 ~/.new-api/local_key.json 的 base_url 覆盖）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from scripts.gateway_config import resolve_gateway
except ImportError:
    try:
        from gateway_config import resolve_gateway
    except ImportError:
        resolve_gateway = None

# ---------------------------------------------------------------- 配置解析

def load_gateway(config_path: Path | str | None = None) -> tuple[str, str]:
    """复用 Agnes Studio 的 ~/.new-api/local_key.json，不另存密钥。

    遵循标准配置层级：显式 config_path > 环境变量 (AGNES_IMAGE_BASE_URL / AGNES_IMAGE_API_KEY)
    > 默认 local_key.json > 内置默认值。实际解析委托给 scripts/gateway_config.resolve_gateway。
    """
    if resolve_gateway is None:
        raise RuntimeError("无法加载 gateway_config 模块")
    return resolve_gateway(
        env_base_var="AGNES_IMAGE_BASE_URL",
        env_key_var="AGNES_IMAGE_API_KEY",
        config_path=config_path,
    )


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

# 请求分辨率档位：官方 size 只认 1K/2K/3K/4K 档位（传像素值会被服务器归一化
# 到 1K，2026-10-02 实测 1920x1080 -> 1312x736；size=2K -> 2048x2048 方形）。
# RATIO_SIZE 的值不再作为请求尺寸，仅保留宽高比语义，供 _crop_to_ratio 裁剪用。
# 环境变量 AGNES_IMAGE_SIZE_TIER 可覆盖（1K/2K/3K/4K），默认 2K。
SIZE_TIER = os.environ.get("AGNES_IMAGE_SIZE_TIER", "2K")

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


# ---------------------------------------------------------------- 路径与自发现

def resolve_manifest_path(
    target: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> Path:
    """解析并定位 image_prompts.json 清单文件。

    支持：
      1. 显式指定 image_prompts.json 文件路径
      2. 显式指定项目目录（包含 images/image_prompts.json 或 image_prompts.json）
      3. 显式指定 images 目录（包含 image_prompts.json）
      4. 未传时从当前目录或 projects/*/images/ 下安全发现唯一清单
    """
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    if target is not None and str(target).strip() != "":
        p = Path(target)
        if not p.is_absolute():
            p = (base / p).resolve()
        else:
            p = p.resolve()

        if not p.exists():
            raise FileNotFoundError(f"指定的路径不存在: {target}")

        if p.is_file():
            if p.suffix.lower() == ".json":
                return p
            raise ValueError(f"指定的文件不是 JSON 清单文件: {target}")

        if p.is_dir():
            cand1 = p / "images" / "image_prompts.json"
            if cand1.is_file():
                return cand1
            cand2 = p / "image_prompts.json"
            if cand2.is_file():
                return cand2
            candidates = list(p.glob("*.json")) + list(
                (p / "images").glob("*.json") if (p / "images").is_dir() else []
            )
            for c in candidates:
                if c.is_file() and c.name.endswith(".json"):
                    try:
                        data = json.loads(c.read_text(encoding="utf-8"))
                        if isinstance(data, dict) and "items" in data:
                            return c
                    except Exception:
                        pass
            raise FileNotFoundError(f"在目录 {target} 下未找到 image_prompts.json 清单文件")

    # 未显式指定 target 时自发现
    cands = [
        base / "images" / "image_prompts.json",
        base / "image_prompts.json",
    ]
    for c in cands:
        if c.is_file():
            return c

    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        for cand in [base.parent, base.parent.parent, Path(__file__).resolve().parent.parent]:
            try:
                p_cand = cand / "projects"
                if p_cand.is_dir() and p_cand.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
                    candidate_projects_dirs.append(p_cand)
                    break
            except Exception:
                pass

    found: list[Path] = []
    for p_dir in candidate_projects_dirs:
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                mf1 = sub / "images" / "image_prompts.json"
                if mf1.is_file() and mf1 not in found:
                    found.append(mf1)
                else:
                    mf2 = sub / "image_prompts.json"
                    if mf2.is_file() and mf2 not in found:
                        found.append(mf2)

    if len(found) == 1:
        return found[0]
    elif len(found) > 1:
        names = ", ".join(
            f.parent.parent.name if f.parent.name == "images" else f.parent.name for f in found
        )
        raise ValueError(f"发现多个有效配图清单 ({names})，无法安全确定，请显式指定 manifest 或 target 参数")

    raise FileNotFoundError("未在当前目录或 projects/*/images/ 下发现有效的 image_prompts.json 清单文件")


def _png_dimensions(raw: bytes) -> tuple[int | None, int | None]:
    if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    return None, None


def _crop_to_ratio(raw: bytes, ratio: str) -> bytes:
    """把档位图（如 2K 方形 2048x2048）按 ratio center-crop 到目标宽高比。

    背景：官方 size 只认档位，档位图恒为方形（ratio/aspect_ratio 字段被中继
    忽略，2026-10-02 实测）；传像素值会被归一化到 1K。于是请求档位 + 本地裁剪。
    依赖 ImageMagick convert；不可用或失败时原样返回 raw（不阻断流程）。
    """
    spec = RATIO_SIZE.get(ratio, "1920x1080")
    try:
        tw, th = (int(x) for x in spec.lower().split("x"))
        sw, sh = _png_dimensions(raw)
        if not sw or not sh or tw <= 0 or th <= 0:
            return raw
        if sw * th > sh * tw:      # 源更宽 -> 裁宽
            cw, ch = sh * tw // th, sh
        else:                      # 源更高（或等比） -> 裁高
            cw, ch = sw, sw * th // tw
        if cw <= 0 or ch <= 0 or (cw, ch) == (sw, sh):
            return raw
        import shutil
        import subprocess
        if not shutil.which("convert"):
            return raw
        pr = subprocess.run(
            ["convert", "png:-", "-gravity", "center",
             "-crop", f"{cw}x{ch}+0+0", "+repage", "png:-"],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=60)
        if pr.returncode == 0 and _png_dimensions(pr.stdout) == (cw, ch):
            return pr.stdout
    except Exception:
        pass
    return raw


# ---------------------------------------------------------------- 生成

def generate(prompt: str, ratio: str = "16:9", model: str | None = None,
             retries: int = 2, timeout: int = 180) -> dict:
    """调 New API /v1/images/generations，返回 {ok, bytes, via, cost_s, error}。"""
    base, key = load_gateway()
    payload_base = {"prompt": prompt, "n": 1, "size": SIZE_TIER}

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
                    with urllib.request.urlopen(it["url"], timeout=timeout) as r2:
                        raw = r2.read()
                if not raw:
                    last_err = f"{m}: 无 b64_json 也无 url"
                    break
                raw = _crop_to_ratio(raw, ratio)
                return {"ok": True, "bytes": raw, "via": m,
                        "cost_s": round(time.time() - t0, 1), "size": SIZE_TIER}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:200]
                last_err = f"{m}: HTTP {e.code} {detail}"
                if e.code in (400, 401, 404, 422):   # 模型级问题，换下一个
                    break
            except Exception as e:
                last_err = f"{m}: {type(e).__name__} {e}"
            time.sleep(2)
    return {"ok": False, "error": last_err or "无可用模型"}


def save_image(res: dict, out_path: Path | str) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(res["bytes"])
    return p


def probe_dimensions(png: Path | str) -> tuple[int | None, int | None]:
    """读取图片宽高（优先读 PNG 头，失败时通过 PIL 备用回退）。"""
    p = Path(png)
    try:
        with p.open("rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(head[16:20], "big")
            h = int.from_bytes(head[20:24], "big")
            return w, h
    except Exception:
        pass
    try:
        from PIL import Image
        with Image.open(p) as img:
            return img.size
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------- 门禁与质检

def check_manifest(manifest_path: Path | str, verbose: bool = True) -> dict:
    """检查配图清单的状态、模型规范与文件交付完整性。"""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest 文件不存在: {manifest_path}")

    try:
        mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"读取或解析 manifest 失败: {e}")

    images_dir = manifest_path.parent
    if images_dir.name != "images" and (manifest_path.parent / "images").is_dir():
        images_dir = manifest_path.parent / "images"

    items = mf.get("items") or []
    total = len(items)
    generated = 0
    pending = 0
    failed = 0
    missing_files: list[str] = []
    forbidden_models: list[tuple[str, str]] = []

    for it in items:
        fn = it.get("filename") or ""
        st = str(it.get("status", "Pending")).capitalize()
        model = str(it.get("model") or "")

        if model:
            low = model.lower()
            if any(b in low for b in BLOCKED_IMAGE_MODELS):
                forbidden_models.append((fn, model))

        if st == "Generated":
            generated += 1
            if fn:
                target_file = images_dir / fn
                if not target_file.is_file() or target_file.stat().st_size == 0:
                    missing_files.append(fn)
            else:
                missing_files.append("[未命名的项目]")
        elif st == "Pending":
            pending += 1
        elif st == "Failed":
            failed += 1

    ok = (
        total > 0
        and pending == 0
        and failed == 0
        and len(missing_files) == 0
        and len(forbidden_models) == 0
    )

    result = {
        "ok": ok,
        "manifest": str(manifest_path),
        "total": total,
        "generated": generated,
        "pending": pending,
        "failed": failed,
        "missing_files": missing_files,
        "forbidden_models": forbidden_models,
    }

    if verbose:
        print("=" * 60)
        print("🔍 运行 PPT-Studio 配图清单客观质检与交付门禁")
        print(f"   清单目标: {manifest_path}")
        print("=" * 60)

        proj_name = mf.get("project") or (
            manifest_path.parent.parent.name
            if manifest_path.parent.name == "images"
            else manifest_path.parent.name
        )
        print(f"  [✓] 格式与元数据       : 项目《{proj_name}》· 共 {total} 项配图规划")

        if total > 0 and pending == 0 and failed == 0:
            print(f"  [✓] 生成状态闭环       : {generated}/{total} 全部已完成生成 (无 Pending/Failed)")
        elif total == 0:
            print(f"  [✗] 生成状态闭环       : 清单中没有任何配图项")
        else:
            print(f"  [✗] 生成状态闭环       : 仍有 {pending} 项待生(Pending)，{failed} 项失败(Failed)")

        if generated > 0 and not missing_files:
            print(f"  [✓] 实体文件完整性     : {generated} 张生成图片均已落地到 {images_dir.name}/ 且体积非空")
        elif total == 0:
            print(f"  [✗] 实体文件完整性     : 无配图文件")
        elif missing_files:
            print(f"  [✗] 实体文件完整性     : 发现 {len(missing_files)} 张图片未落地或为空: {', '.join(missing_files[:5])}")
        else:
            print(f"  [✗] 实体文件完整性     : 尚未生成任何图片实体")

        if not forbidden_models:
            print(f"  [✓] 模型规范合规性     : 严禁模型 (gemini/flux等) 0 处违规 · 生图只走 Agnes")
        else:
            bad_desc = ", ".join(f"{f}({m})" for f, m in forbidden_models[:3])
            print(f"  [✗] 模型规范合规性     : 发现 {len(forbidden_models)} 处使用了违禁模型: {bad_desc}")

        print("=" * 60)
        if ok:
            print("ALL CLEAR ✅")
        else:
            print("❌ 门禁未通过")
        print("=" * 60)

    return result


# ---------------------------------------------------------------- manifest

def run_manifest(
    manifest_path: Path | str,
    only: list[str] | None = None,
    force: bool = False,
    retry_failed: bool = False,
    dry_run: bool = False,
    generate_fn: callable = generate,
) -> int:
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        print(f"[err] manifest 文件不存在: {manifest_path}")
        return 1

    try:
        mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[err] 读取或解析 manifest 失败: {e}")
        return 1

    images_dir = manifest_path.parent
    if images_dir.name != "images" and (manifest_path.parent / "images").is_dir():
        images_dir = manifest_path.parent / "images"

    items = mf.get("items") or []
    todo = [
        it for it in items
        if (
            force
            or str(it.get("status", "Pending")).lower() == "pending"
            or (retry_failed and str(it.get("status", "Pending")).lower() == "failed")
        )
        and (not only or it.get("filename") in only)
    ]

    if dry_run:
        print(f"· dry-run: 将处理 {len(todo)} 项")
        for it in todo:
            print(
                f"  - {it.get('filename', '[未命名]')}"
                f"  status={it.get('status', 'Pending')}"
                f"  aspect_ratio={it.get('aspect_ratio', '16:9')}"
            )
        return 0

    print(f"· manifest {manifest_path.name}: 共 {len(items)} 项，待生 {len(todo)} 项")
    ok = fail = 0

    for it in todo:
        fn = it.get("filename")
        if not fn:
            print("  [skip] 缺 filename")
            continue
        ratio = it.get("aspect_ratio", "16:9")
        print(f"  → {fn}  ({ratio}, {it.get('purpose','')[:40]})")
        res = generate_fn(it.get("prompt", ""), ratio=ratio, model=it.get("model"))
        if not res.get("ok"):
            it["status"] = "Failed"
            it["error"] = res.get("error")
            fail += 1
            manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    ✗ {res.get('error')}")
            continue
        out = save_image(res, images_dir / fn)
        w, h = probe_dimensions(out)
        it["status"] = "Generated"
        it["model"] = res.get("via", it.get("model", "agnes-image-2.5-flash"))
        it["dimensions"] = f"{w}x{h}" if w else None
        it.pop("error", None)
        ok += 1
        manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
        kb = out.stat().st_size // 1024
        print(f"    ✓ {w}x{h} {kb}KB  via {it['model']}  ({res.get('cost_s', 0)}s)")

    manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2), encoding="utf-8")
    render_md(manifest_path)
    print(f"✓ 完成 {ok} 项，失败 {fail} 项 → {manifest_path}")
    return 1 if fail else 0


def render_md(manifest_path: Path | str) -> Path:
    """生成 image_prompts.md 伴生（PPT Master 要求的 sidecar）。"""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest 文件不存在: {manifest_path}")

    try:
        mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"读取或解析 manifest 失败: {e}")

    out = manifest_path.with_suffix(".md")
    proj_title = mf.get("project") or (
        manifest_path.parent.parent.name
        if manifest_path.parent.name == "images"
        else manifest_path.parent.name
    )
    lines = [f"# {proj_title} — 图片清单", ""]
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

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agnes Studio → PPT Master 配图桥接器")
    ap.add_argument("target", nargs="?", help="项目目录或 images/image_prompts.json（可选，默认自发现）")
    ap.add_argument("--manifest", help="PPT Master 的 images/image_prompts.json")
    ap.add_argument("--render-md", nargs="?", const="", metavar="MANIFEST", help="只渲染 Markdown 伴生")
    ap.add_argument("--status", action="store_true", help="查看 manifest 统计与交付状态")
    ap.add_argument("--check", action="store_true", help="门禁校验：验证所有配图已生成且落地到 images/")
    ap.add_argument("--prompt", help="即席生图（配合 --filename/--project）")
    ap.add_argument("--filename", help="输出文件名，如 cover_bg.png")
    ap.add_argument("--project", help="项目目录（单张模式）")
    ap.add_argument("--aspect-ratio", dest="aspect_ratio", default="16:9")
    ap.add_argument("--model", help="指定后端模型")
    ap.add_argument("--only", nargs="*", help="只处理这些 filename")
    ap.add_argument("--force", action="store_true", help="连 Generated 的也重跑")
    ap.add_argument("--retry-failed", action="store_true", help="重试 Pending 与 Failed，但不重跑 Generated")
    ap.add_argument("--dry-run", action="store_true", help="只显示本次将处理的任务，不调用生图或修改文件")
    args = ap.parse_args(argv)

    if args.dry_run and (args.prompt or args.render_md is not None or args.status or args.check):
        print("[err] --dry-run 只能与 manifest/target、--only、--force、--retry-failed 配合")
        return 2

    if args.prompt:
        if not (args.filename and args.project):
            print("[err] 单张模式需同时给 --filename 和 --project")
            return 2
        proj_dir = Path(args.project)
        out = proj_dir / "images" / args.filename if (proj_dir / "images").is_dir() else proj_dir / args.filename
        print(f"· 即席生图 {args.filename} ({args.aspect_ratio})")
        res = generate(args.prompt, ratio=args.aspect_ratio, model=args.model)
        if not res.get("ok"):
            print(f"✗ {res.get('error')}")
            return 1
        save_image(res, out)
        w, h = probe_dimensions(out)
        print(f"✓ {out}  {w}x{h}  {out.stat().st_size//1024}KB  via {res['via']}")
        return 0

    if args.render_md is not None:
        target_raw = args.render_md if args.render_md != "" else (args.manifest or args.target)
        try:
            mf_path = resolve_manifest_path(target_raw)
            render_md(mf_path)
            return 0
        except Exception as e:
            print(f"[err] {e}")
            return 1

    if args.status or args.check:
        try:
            mf_path = resolve_manifest_path(args.manifest or args.target)
            res = check_manifest(mf_path, verbose=True)
            if args.check and not res["ok"]:
                return 1
            return 0
        except Exception as e:
            print(f"[err] {e}")
            return 1

    if args.manifest or args.target:
        try:
            mf_path = resolve_manifest_path(args.manifest or args.target)
            return run_manifest(
                mf_path,
                only=args.only,
                force=args.force,
                retry_failed=args.retry_failed,
                dry_run=args.dry_run,
            )
        except Exception as e:
            print(f"[err] {e}")
            return 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
