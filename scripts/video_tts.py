#!/usr/bin/env python3
# -*- coding: utf-8
"""
video_tts.py -- 视频管线的语音合成与解说稿加载

从 make_video.py 拆出: VOICE_MAP / load_voiceover / generate_tts。
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="video_tts -- 视频管线的语音合成与解说稿加载工具",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="项目目录 (包含 voiceover.json 或 notes/*.md)",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="直接合成指定单句文本",
    )
    parser.add_argument(
        "--voice",
        default="zh-female",
        help=f"发音人代码或全名 (默认: zh-female，支持: {', '.join(VOICE_MAP.keys())})",
    )
    parser.add_argument(
        "--audio",
        default=None,
        help="输出音频文件路径 (搭配 --text)",
    )
    parser.add_argument(
        "--vtt",
        default=None,
        help="输出 VTT 字幕文件路径 (搭配 --text)",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="列出内置发音人别名映射",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出项目解说稿 (默认行为)",
    )
    args = parser.parse_args(argv)

    if args.list_voices:
        print(json.dumps(VOICE_MAP, ensure_ascii=False, indent=2))
        return 0

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    if args.text is not None:
        if not args.audio or not args.vtt:
            print("[!] 指定 --text 时必须同时提供 --audio 与 --vtt 输出路径", file=sys.stderr)
            return 2
        voice_target = VOICE_MAP.get(args.voice, args.voice)
        try:
            generate_tts(args.text, voice_target, args.audio, args.vtt, base_dir=effective_base)
            print(f"[+] TTS 生成成功: audio={args.audio}, vtt={args.vtt}")
            return 0
        except Exception as e:
            print(f"[!] TTS 生成异常: {e}", file=sys.stderr)
            return 1

    target_proj = args.project if args.project is not None else "."
    try:
        vo_list = load_voiceover(target_proj, base_dir=effective_base)
        print(json.dumps(vo_list, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"[!] 加载解说稿失败: {e}", file=sys.stderr)
        return 1


__all__ = [
    "VOICE_MAP",
    "load_voiceover",
    "generate_tts",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
