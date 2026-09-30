#!/usr/bin/env python3
# -*- coding: utf-8
"""
video_subtitle.py -- VTT/SRT 字幕解析与转换

从 make_video.py 拆出: vtt_time_to_seconds / seconds_to_srt_time / parse_vtt_cues。
"""

from __future__ import annotations

import re
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

def parse_vtt_cues(vtt_path: Path, offset_sec: float) -> list[dict]:
    if not vtt_path.exists():
        return []
    content = vtt_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    cues = []
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

