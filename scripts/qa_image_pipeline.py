"""组合 PPT 图片的现有质量门禁，不复制底层算法。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

try:
    from scripts.prepare_agnes_image import _resolve_and_dedup_targets, check_images
    from scripts.crop_panel import check_crop_panel
    from scripts.boost_ink import check_boost_ink
except ImportError:
    try:
        from prepare_agnes_image import _resolve_and_dedup_targets, check_images
        from crop_panel import check_crop_panel
        from boost_ink import check_boost_ink
    except ImportError:
        _resolve_and_dedup_targets = None  # type: ignore
        check_images = None  # type: ignore
        check_crop_panel = None  # type: ignore
        check_boost_ink = None  # type: ignore


def run_image_qa(
    targets: list[str | Path] | str | Path | None = None,
    *,
    size: tuple[int, int] | None = None,
    aspect: str | float = "580:385",
    pad: float = 1.12,
    crop_min_ink: float = 3.0,
    boost_min_ink: float = 2.0,
    verbose: bool = False,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """按 prepare -> crop -> boost 顺序检查每个图片并汇总结果。"""
    if _resolve_and_dedup_targets is None or check_images is None:
        raise RuntimeError("无法加载 prepare_agnes_image 模块")
    if check_crop_panel is None:
        raise RuntimeError("无法加载 crop_panel 模块")
    if check_boost_ink is None:
        raise RuntimeError("无法加载 boost_ink 模块")
    resolved, resolution_failures = _resolve_and_dedup_targets(targets, base_dir=base_dir)
    items: list[dict[str, Any]] = [{"file": f.get("file", ""), "name": f.get("name", ""), "ok": False, "stage": "prepare", "code": f.get("code", "TARGET_ERROR"), "reason": f.get("reason", "目标解析失败")} for f in resolution_failures]
    for path in resolved:
        record: dict[str, Any] = {"file": str(path), "name": path.name, "ok": False}
        prepared = check_images(path, size=size, verbose=False)
        if not prepared.get("ok"):
            failure = (prepared.get("failures") or [{}])[0]
            record.update({"stage": "prepare", "code": failure.get("code", "PREPARE_FAILED"), "reason": failure.get("reason", "prepare QA 未通过")})
            items.append(record)
            continue
        record["prepare"] = {"ok": True}
        crop_ok, crop_result, crop_issues = check_crop_panel(path, aspect=aspect, pad=pad, min_ink=crop_min_ink)
        if not crop_ok:
            record.update({"stage": "crop", "code": "CROP_QA_FAILED", "reason": "; ".join(crop_issues) or "crop QA 未通过", "crop": crop_result})
            items.append(record)
            continue
        record["crop"] = {"ok": True, "result": crop_result}
        boost_ok, boost_result, boost_issues = check_boost_ink(path, min_ink=boost_min_ink)
        if not boost_ok:
            record.update({"stage": "boost", "code": "BOOST_QA_FAILED", "reason": "; ".join(boost_issues) or "boost QA 未通过", "boost": boost_result})
            items.append(record)
            continue
        record.update({"ok": True, "stage": "complete", "code": "OK", "reason": "", "boost": {"ok": True, "result": boost_result}})
        items.append(record)
    passed = sum(1 for item in items if item["ok"])
    result = {"ok": bool(items) and passed == len(items), "total": len(items), "passed": passed, "failed": len(items) - passed, "items": items}
    if verbose:
        print(f"image QA: {passed}/{len(items)} passed")
    return result


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 PPT 图片统一质量门禁")
    parser.add_argument("targets", nargs="+", help="一个或多个图片、目录或项目路径")
    parser.add_argument("--json", action="store_true", dest="as_json", help="仅输出 JSON 结果")
    parser.add_argument("--base-dir", default=None, help="指定基础工作目录 (默认: 当前工作目录)")
    args = parser.parse_args(argv)
    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    try:
        result = run_image_qa(args.targets, verbose=not args.as_json, base_dir=effective_base)
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as err:
        if args.as_json:
            print(json.dumps({"ok": False, "error": str(err)}, ensure_ascii=False))
        else:
            print(f"[err] {err}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        print(json.dumps({k: result[k] for k in ("ok", "total", "passed", "failed")}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
