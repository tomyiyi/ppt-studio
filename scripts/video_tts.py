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

def load_voiceover(project_dir: Path) -> list[dict]:
    vo_path = project_dir / "voiceover.json"
    if vo_path.exists():
        with open(vo_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data:
                raise ValueError(f"voiceover.json 内容为空: {vo_path}")
            return data

    # 回退：从 notes/*.md 提取
    print("[*] 未找到 voiceover.json，尝试从 notes/*.md 解析...")
    notes_dir = project_dir / "notes"
    if not notes_dir.exists():
        raise FileNotFoundError(f"项目未找到 voiceover.json 或 notes 目录: {project_dir}")

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
            "motion": "ken_burns_zoom_in"
        })
    return vo_list

def generate_tts(text: str, voice: str, out_audio: Path, out_vtt: Path) -> None:
    """调用 edge-tts 生成音频与原始 VTT 字母。"""
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
        "--write-media", str(out_audio),
        "--write-subtitles", str(out_vtt),
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
            "--write-media", str(out_audio),
            "--write-subtitles", str(out_vtt),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"TTS 生成失败: {res.stderr}")

