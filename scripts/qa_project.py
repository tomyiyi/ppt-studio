"""PPT 项目级验收编排：只串联已有 QA gate，不复制检查算法。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.qa_image_pipeline import run_image_qa
from scripts.qa_layout import run_qa_layout
from scripts.qa_cards import run_qa_cards
from scripts.qa_long_card import run_qa_long_card


def run_project_qa(
    project: str | Path = ".",
    *,
    image_targets: str | Path | list[str | Path] | None = None,
    layout_target: str | Path | None = None,
    cards_target: str | Path | None = None,
    long_card_target: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """按 image -> layout -> cards -> long_card 顺序执行项目验收。"""
    root = Path(project).resolve()
    image_input = image_targets if image_targets is not None else root / "images"
    stages: dict[str, Any] = {}
    image_result = run_image_qa(image_input, verbose=False)
    stages["image"] = image_result
    if not image_result["ok"]:
        return {"ok": False, "failed_stage": "image", "stages": stages}

    for name, runner, target in (
        ("layout", run_qa_layout, layout_target if layout_target is not None else root),
        ("cards", run_qa_cards, cards_target if cards_target is not None else root),
        ("long_card", run_qa_long_card, long_card_target if long_card_target is not None else root),
    ):
        ok = bool(runner(target, verbose=verbose))
        stages[name] = {"ok": ok}
        if not ok:
            return {"ok": False, "failed_stage": name, "stages": stages}

    return {"ok": True, "failed_stage": None, "stages": stages}
