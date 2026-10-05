#!/usr/bin/env python3
# -*- coding: utf-8
"""
video_subtitle.py -- VTT/SRT 字幕解析与转换

从 make_video.py 拆出: vtt_time_to_seconds / seconds_to_srt_time / parse_vtt_cues / format_srt_cues / write_srt。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def vtt_time_to_seconds(t_str: str) -> float:
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    return float(parts[0])


def seconds_to_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_vtt_cues(
    vtt_path: Path | str,
    offset_sec: float = 0.0,
    base_dir: str | Path | None = None,
) -> list[dict]:
    """解析 WebVTT 格式字幕切片，返回包含 start/end/text 的 cue 列表。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    raw_p = Path(vtt_path)
    p = (base / raw_p).resolve() if not raw_p.is_absolute() else raw_p.resolve()

    if not p.is_file():
        return []

    content = p.read_text(encoding="utf-8")
    lines = content.splitlines()
    cues: list[dict] = []
    i = 0
    time_pat = re.compile(r"(\d+[:\d.,]+)\s*-->\s*(\d+[:\d.,]+)")
    while i < len(lines):
        line = lines[i].strip()
        m = time_pat.search(line)
        if m:
            start_s = vtt_time_to_seconds(m.group(1)) + offset_sec
            end_s = vtt_time_to_seconds(m.group(2)) + offset_sec
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not time_pat.search(lines[i]):
                text_lines.append(lines[i].strip())
                i += 1
            cue_text = " ".join(text_lines)
            if cue_text:
                cues.append({"start": start_s, "end": end_s, "text": cue_text})
        else:
            i += 1
    return cues


def format_srt_cues(cues: list[dict]) -> str:
    """将 cue 列表格式化为标准 SRT 字幕字符串。"""
    chunks: list[str] = []
    for c_idx, cue in enumerate(cues, 1):
        start_str = seconds_to_srt_time(cue["start"])
        end_str = seconds_to_srt_time(cue["end"])
        text_str = str(cue.get("text", "")).strip()
        chunks.append(f"{c_idx}\n{start_str} --> {end_str}\n{text_str}\n")
    return "\n".join(chunks)


def write_srt(
    cues: list[dict],
    out_path: str | Path,
    base_dir: str | Path | None = None,
) -> Path:
    """将 cue 列表写入指定的 SRT 文件路径，返回绝对路径。"""
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    raw_out = Path(out_path)
    dest = (base / raw_out).resolve() if not raw_out.is_absolute() else raw_out.resolve()

    dest.parent.mkdir(parents=True, exist_ok=True)
    srt_content = format_srt_cues(cues)
    dest.write_text(srt_content, encoding="utf-8")
    return dest


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="video_subtitle -- WebVTT 字幕解析与转换工具",
    )
    parser.add_argument(
        "vtt_file",
        help="WebVTT 字幕文件路径",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出 SRT 文件路径 (可选；未指定且未指定 --json 则输出至标准输出)",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=0.0,
        help="字幕时间偏移秒数 (默认: 0.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出解析后的 cue 列表",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    raw_vtt = Path(args.vtt_file)
    vtt_path = (effective_base / raw_vtt).resolve() if not raw_vtt.is_absolute() else raw_vtt.resolve()

    if not vtt_path.is_file():
        print(f"[!] 找不到 VTT 字幕文件: {vtt_path}", file=sys.stderr)
        return 1

    cues = parse_vtt_cues(vtt_path, offset_sec=args.offset, base_dir=effective_base)

    if args.json:
        print(json.dumps(cues, ensure_ascii=False, indent=2))
        return 0

    if args.output:
        raw_out = Path(args.output)
        out_path = (effective_base / raw_out).resolve() if not raw_out.is_absolute() else raw_out.resolve()
        write_srt(cues, out_path, base_dir=effective_base)
        print(f"[+] SRT 文件已写入: {out_path}")
        return 0

    print(format_srt_cues(cues), end="")
    return 0


__all__ = [
    "vtt_time_to_seconds",
    "seconds_to_srt_time",
    "parse_vtt_cues",
    "format_srt_cues",
    "write_srt",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
