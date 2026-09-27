"""组合 PPT 图片的现有质量门禁，不复制底层算法。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.prepare_agnes_image import _resolve_and_dedup_targets, check_images
from scripts.crop_panel import check_crop_panel
from scripts.boost_ink import check_boost_ink


def run_image_qa(targets: list[str | Path] | str | Path | None = None, *, size: tuple[int, int] | None = None, aspect: str | float = "580:385", pad: float = 1.12, crop_min_ink: float = 3.0, boost_min_ink: float = 2.0, verbose: bool = False) -> dict[str, Any]:
    """按 prepare -> crop -> boost 顺序检查每个图片并汇总结果。"""
    resolved, resolution_failures = _resolve_and_dedup_targets(targets)
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
