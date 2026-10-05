#!/usr/bin/env python3
# -*- coding: utf-8
"""
video_tts.py -- 视频管线的语音合成与解说稿加载

从 make_video.py 拆出: VOICE_MAP / load_voiceover / generate_tts。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

VOICE_MAP = {
    "zh-female": "zh-CN-XiaoxiaoNeural",
    "zh-female-calm": "zh-CN-XiaoyiNeural",
    "zh-male": "zh-CN-YunxiNeural",
    "zh-male-deep": "zh-CN-YunjianNeural",
    "zh-male-doc": "zh-CN-YunyangNeural",
}


def load_voiceover(
    project_dir: Path | str,
    base_dir: str | Path | None = None,
) -> list[dict]:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    raw_p = Path(project_dir)
    p = (base / raw_p).resolve() if not raw_p.is_absolute() else raw_p.resolve()

    if not p.is_dir():
        raise FileNotFoundError(f"项目目录不存在: {p}")

    vo_path = p / "voiceover.json"
    if vo_path.exists():
        with open(vo_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data:
                raise ValueError(f"voiceover.json 内容为空: {vo_path}")
            return data

    # 回退：从 notes/*.md 提取
    print("[*] 未找到 voiceover.json，尝试从 notes/*.md 解析...")
    notes_dir = p / "notes"
    if not notes_dir.exists():
        raise FileNotFoundError(f"项目未找到 voiceover.json 或 notes 目录: {p}")

    note_files = sorted(notes_dir.glob("*.md"))
    if not note_files:
        raise ValueError(f"notes/ 目录下未找到任何 .md 文件: {notes_dir}")

    vo_list = []
    for nf in note_files:
        stem = nf.stem
        lines = [line.strip() for line in nf.read_text(encoding="utf-8").splitlines() if line.strip()]
        title = lines[0] if lines else stem
        # 寻找重点推荐句子
        body_lines = [l.lstrip("-* ").strip() for l in lines[1:] if not l.startswith("#")]
        narration = " ".join(body_lines[:2]) if body_lines else f"{title}展示"
        vo_list.append({
            "page": stem,
            "title": title,
            "narration": narration,
            "pause_after": 1.0,
            "motion": "ken_burns_zoom_in",
        })
    return vo_list


def generate_tts(
    text: str,
    voice: str,
    out_audio: Path | str,
    out_vtt: Path | str,
    base_dir: str | Path | None = None,
) -> None:
    """调用 edge-tts 生成音频与原始 VTT 字幕。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    audio_raw = Path(out_audio)
    vtt_raw = Path(out_vtt)
    audio_path = (base / audio_raw).resolve() if not audio_raw.is_absolute() else audio_raw.resolve()
    vtt_path = (base / vtt_raw).resolve() if not vtt_raw.is_absolute() else vtt_raw.resolve()

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    vtt_path.parent.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parent.parent
    python_bin = sys.executable
    for venv_py in [repo_root / ".venv/bin/python3", repo_root / ".venv/bin/python"]:
        if venv_py.is_file() and os.access(venv_py, os.X_OK):
            python_bin = str(venv_py)
            break

    cmd = [
        python_bin, "-m", "edge_tts",
        "--voice", voice,
        "--text", text,
        "--write-media", str(audio_path),
        "--write-subtitles", str(vtt_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # 降级尝试虚拟环境或全局 edge-tts
        tts_bin = "edge-tts"
        venv_tts = repo_root / ".venv/bin/edge-tts"
        if venv_tts.is_file() and os.access(venv_tts, os.X_OK):
            tts_bin = str(venv_tts)
        cmd = [
            tts_bin,
            "--voice", voice,
            "--text", text,
            "--write-media", str(audio_path),
            "--write-subtitles", str(vtt_path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"TTS 生成失败: {res.stderr}")


__all__ = [
    "VOICE_MAP",
    "load_voiceover",
    "generate_tts",
]
