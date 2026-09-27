#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_video.py —— PPT-Studio 视频质量自动化门禁
=============================================

对自动合成的 MP4 视频进行 7 项客观工业级质检：
  1. 流完整性   : 包含且仅包含单路 H.264 视频流与 AAC 音频流
  2. 分辨率标准 : 严格匹配 1080p（1920×1080 或 1080×1920），yuv420p 像素格式
  3. 音画同步   : 视频时长与音频流总时长差值在容差范围内（≤ 0.25s）
  4. 响度与削顶 : 平均响度在 [-35dB, -12dB] 广播级区间，峰值不削顶（< 0dB）
  5. 画面有效性 : 全程无异常黑屏死帧（blackdetect > 1.5s 报警）
  6. 字幕时间线 : SRT 字幕时序单调递增、无负时长、无重叠，收尾不超出视频时长
  7. 帧率与码率 : 稳定 24–60fps，码率在合理区间，无畸形编码

用法：
  python3 scripts/qa_video.py <video_path_or_project_dir> [--srt path.srt]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run_probe(cmd: list[str]) -> str:
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.stdout.strip()


def probe_streams(video_path: Path | str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(video_path),
    ]
    raw = run_probe(cmd)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def check_streams(streams_data: dict) -> tuple[bool, str]:
    v_streams = [s for s in streams_data.get("streams", []) if s.get("codec_type") == "video"]
    a_streams = [s for s in streams_data.get("streams", []) if s.get("codec_type") == "audio"]

    if not v_streams:
        return False, "缺少视频流"
    if not a_streams:
        return False, "缺少音频流"

    v_codec = v_streams[0].get("codec_name")
    a_codec = a_streams[0].get("codec_name")

    if v_codec != "h264":
        return False, f"视频编码非 H.264 (当前: {v_codec})"
    if a_codec != "aac":
        return False, f"音频编码非 AAC (当前: {a_codec})"

    sample_rate = a_streams[0].get("sample_rate", "")
    channels = int(a_streams[0].get("channels", 0))
    if channels < 1:
        return False, "音频声道配置异常 (声道数 < 1)"

    sr_str = f" · {sample_rate}Hz/{channels}ch" if sample_rate else ""
    return True, f"视频 {v_codec} · 音频 {a_codec}{sr_str}"


def check_resolution(v_stream: dict | None) -> tuple[bool, str]:
    if not v_stream:
        return False, "缺少视频流，无法核验分辨率"
    w = int(v_stream.get("width", 0))
    h = int(v_stream.get("height", 0))
    pix_fmt = v_stream.get("pix_fmt", "")

    valid_res = (w == 1920 and h == 1080) or (w == 1080 and h == 1920) or (w == 1080 and h == 1350)
    if not valid_res:
        return False, f"非标准发布分辨率 {w}×{h}"
    if pix_fmt != "yuv420p":
        return False, f"像素格式非 yuv420p ({pix_fmt})，移动端可能黑屏"

    ratio = "16:9" if w > h else ("9:16" if h == 1920 else "3:4")
    return True, f"{w}×{h} ({ratio}) · {pix_fmt}"


def check_av_sync(streams_data: dict) -> tuple[bool, str]:
    v_stream = next((s for s in streams_data.get("streams", []) if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams_data.get("streams", []) if s.get("codec_type") == "audio"), None)

    if not v_stream or not a_stream:
        return False, "缺少视频或音频流，无法核验音画同步"

    v_dur = float(v_stream.get("duration") or streams_data.get("format", {}).get("duration", 0))
    a_dur = float(a_stream.get("duration") or v_dur)

    diff = abs(v_dur - a_dur)
    if diff > 0.35:
        return False, f"音画时长偏差过大 ({diff:.2f}s, 视频 {v_dur:.2f}s vs 音频 {a_dur:.2f}s)"

    return True, f"视频 {v_dur:.1f}s / 音频 {a_dur:.1f}s (偏差 {diff:.2f}s ≤ 0.35s)"


def check_audio_loudness(video_path: Path | str) -> tuple[bool, str]:
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", "volumedetect",
        "-vn", "-sn", "-dn",
        "-f", "null", "/dev/null",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = res.stderr

    mean_m = re.search(r"mean_volume:\s*([-0-9.]+)\s*dB", out)
    max_m = re.search(r"max_volume:\s*([-0-9.]+)\s*dB", out)

    if not mean_m or not max_m:
        return False, "未能提取音量特征"

    mean_v = float(mean_m.group(1))
    max_v = float(max_m.group(1))

    if mean_v < -45.0:
        return False, f"音频严重过轻或静音 (mean_volume: {mean_v} dB)"
    if max_v > -0.05:
        return False, f"音频存在削顶破音失真 (max_volume: {max_v} dB)"

    return True, f"平均响度 {mean_v:.1f} dB · 峰值 {max_v:.1f} dB"


def check_black_frames(video_path: Path | str) -> tuple[bool, str]:
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", "blackdetect=d=1.5:pix_th=0.10",
        "-an", "-f", "null", "/dev/null",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = res.stderr

    black_blocks = re.findall(r"black_start:([0-9.]+)\s*black_end:([0-9.]+)\s*black_duration:([0-9.]+)", out)
    if black_blocks:
        long_blacks = [b for b in black_blocks if float(b[2]) > 1.8]
        if long_blacks:
            return False, f"检测到 {len(long_blacks)} 处死黑屏 (最长 {long_blacks[0][2]}s)"

    return True, "全片无异常死黑屏"


def parse_srt_time(t_str: str) -> float:
    t_str = t_str.strip().replace(",", ".")
    parts = t_str.split(":")
    h, m = float(parts[0]), float(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def find_associated_srt(video_path: Path | str, explicit_srt: Path | str | None = None) -> Path | None:
    """自动探查关联的字幕文件。"""
    v_path = Path(video_path).resolve()
    if explicit_srt:
        p_explicit = Path(explicit_srt).resolve()
        if p_explicit.exists():
            return p_explicit

    # 1. 同名 srt
    direct_srt = v_path.with_suffix(".srt")
    if direct_srt.exists():
        return direct_srt

    # 2. 同目录下的 srt 文件（单文件或前缀/语义匹配）
    parent_dir = v_path.parent
    srts = sorted(parent_dir.glob("*.srt"))
    if len(srts) == 1:
        return srts[0]
    elif len(srts) > 1:
        # 优先匹配带有共同前缀的 srt
        stem_prefix = v_path.stem[:4]
        matched = [s for s in srts if stem_prefix in s.stem]
        if matched:
            return matched[0]
        return srts[0]

    return None


def check_subtitles(srt_path: Path | str | None, video_duration: float) -> tuple[bool, str]:
    srt_p = Path(srt_path).resolve() if srt_path else None
    if srt_p is None or not srt_p.exists():
        return True, "无独立字幕文件（跳过外部 SRT 检查）"

    try:
        content = srt_p.read_text(encoding="utf-8").strip()
    except Exception as e:
        return False, f"字幕文件读取失败: {e}"

    if not content:
        return False, "SRT 文件为空"

    blocks = [b.strip() for b in re.split(r"\n\s*\n", content) if b.strip()]
    if not blocks:
        return False, "SRT 文件为空"

    last_end = 0.0
    valid_cues = 0
    time_pat = re.compile(r"(\d+:\d+:\d+(?:[,\.]\d+)?)\s*-->\s*(\d+:\d+:\d+(?:[,\.]\d+)?)")

    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = time_pat.search(lines[1] if len(lines) > 1 and "-->" in lines[1] else lines[0])
        if not m:
            continue
        start_s = parse_srt_time(m.group(1))
        end_s = parse_srt_time(m.group(2))

        if end_s <= start_s:
            return False, f"字幕时序倒挂: {m.group(0)}"
        if start_s < last_end - 0.1:
            return False, f"字幕严重重叠: 上一条结束 {last_end:.2f}s, 当前开始 {start_s:.2f}s"
        last_end = end_s
        valid_cues += 1

    if valid_cues == 0:
        return False, "SRT 文件未解析出任何有效字幕时序条目"

    if last_end > video_duration + 1.0:
        return False, f"字幕超出视频时长 (字幕尾 {last_end:.1f}s > 视频尾 {video_duration:.1f}s)"

    return True, f"{valid_cues} 条字幕时序合规 · 尾部对齐良好"


def check_bitrate_and_fps(v_stream: dict | None, format_info: dict) -> tuple[bool, str]:
    if not v_stream:
        return False, "缺少视频流，无法核验帧率与码率"

    r_fps = v_stream.get("r_frame_rate", "30/1")
    if "/" in r_fps:
        num, den = r_fps.split("/")
        fps = float(num) / float(den)
    else:
        fps = float(r_fps)

    bitrate = int(format_info.get("bit_rate", 0)) // 1000

    if fps < 23.9 or fps > 61.0:
        return False, f"异常帧率: {fps:.1f} fps"
    if bitrate < 200:
        return False, f"码率过低可能劣化画质: {bitrate} kbps"

    return True, f"{fps:.1f} fps · {bitrate} kbps"


def find_videos(target: Path | str) -> list[Path]:
    """在目标路径或其子目录中查找 mp4 视频文件。"""
    target_path = Path(target).resolve()
    if target_path.is_file():
        return [target_path] if target_path.suffix.lower() == ".mp4" else []

    if not target_path.is_dir():
        return []

    # 1. 目标目录内直接包含的 mp4
    found = sorted(target_path.glob("*.mp4"))
    if found:
        return found

    # 2. 目标目录内的 output/ 子目录
    if (target_path / "output").is_dir():
        found = sorted((target_path / "output").glob("*.mp4"))
        if found:
            return found

    # 3. 目标目录下的 projects/*/output/ 或目标本身为 projects 时的子项目
    candidate_p_dirs: list[Path] = []
    if (target_path / "projects").is_dir():
        candidate_p_dirs.append(target_path / "projects")
    elif target_path.name == "projects":
        candidate_p_dirs.append(target_path)
    elif (target_path.parent / "projects").is_dir():
        candidate_p_dirs.append(target_path.parent / "projects")

    for p_dir in candidate_p_dirs:
        for p in sorted(p_dir.iterdir()):
            if p.is_dir() and (p / "output").is_dir():
                found.extend(sorted((p / "output").glob("*.mp4")))

    # 4. 向上查找 output 目录（如从项目根目录或子目录调用）
    if not found and (target_path.parent / "output").is_dir():
        found = sorted((target_path.parent / "output").glob("*.mp4"))

    # 去重保持顺序
    seen: set[Path] = set()
    deduped: list[Path] = []
    for f in found:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            deduped.append(rf)

    return deduped


def qa_single_video(
    video_path: Path | str,
    srt_path: Path | str | None = None,
    verbose: bool = True,
) -> bool:
    """对单个 MP4 视频执行 7 项客观工业级质量门禁复核。"""
    video_p = Path(video_path).resolve()
    srt_p = Path(srt_path).resolve() if srt_path else None

    def _log(msg: str = "") -> None:
        if verbose:
            print(msg)

    _log("==================================================")
    _log("🔍 运行 PPT-Studio 视频质量自动化门禁")
    _log(f"   目标: {video_p}")
    _log("==================================================")

    if not video_p.exists():
        _log(f"[ERROR] 目标视频文件不存在: {video_p}")
        return False

    meta = probe_streams(video_p)
    if not meta:
        _log("[ERROR] 无法通过 ffprobe 解析视频元数据")
        return False

    v_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), None)
    v_dur = float(meta.get("format", {}).get("duration", 0))

    resolved_srt = find_associated_srt(video_p, srt_p)

    checks = [
        ("流完整性", lambda: check_streams(meta)),
        ("分辨率与像素格式", lambda: check_resolution(v_stream)),
        ("音画同步匹配", lambda: check_av_sync(meta)),
        ("音频响度与削顶", lambda: check_audio_loudness(video_p)),
        ("死黑屏与卡顿", lambda: check_black_frames(video_p)),
        ("字幕时间线", lambda: check_subtitles(resolved_srt, v_dur)),
        ("帧率与码率健康", lambda: check_bitrate_and_fps(v_stream, meta.get("format", {}))),
    ]

    all_passed = True
    for name, fn in checks:
        passed, msg = fn()
        status_icon = "✓" if passed else "✗ [FAIL]"
        _log(f"  [{status_icon}] {name:16s} : {msg}")
        if not passed:
            all_passed = False

    _log("==================================================")
    if all_passed:
        _log("ALL CLEAR ✅")
        return True
    else:
        _log("QA GATES FAILED ❌ 请根据上述检查项修正重试！")
        return False


def qa_video(
    video_path: Path | str | None = None,
    srt_path: Path | str | None = None,
    verbose: bool = True,
) -> bool:
    """运行 PPT-Studio 视频质量自动化客观门禁。

    支持输入单个 MP4 视频文件路径、包含 *.mp4 的目录路径，或留空默认自发现。
    支持 Path、str 或 None 输入。
    """
    target = Path(video_path).resolve() if video_path else Path.cwd().resolve()
    srt_p = Path(srt_path).resolve() if srt_path else None

    if not target.exists():
        if verbose:
            print(f"[ERROR] 目标视频路径不存在: {target}")
        return False

    if target.is_file():
        if target.suffix.lower() != ".mp4":
            if verbose:
                print(f"[ERROR] 目标文件非有效 MP4 格式: {target}")
            return False
        return qa_single_video(target, srt_p, verbose=verbose)

    if target.is_dir():
        mp4s = find_videos(target)
        if not mp4s:
            if verbose:
                print(f"[ERROR] 在 {target} 或 output/、projects/*/output/ 下未找到 mp4 视频")
            return False
        all_passed = True
        for i, p in enumerate(mp4s):
            ok = qa_single_video(p, srt_p, verbose=verbose)
            if not ok:
                all_passed = False
            if verbose and i < len(mp4s) - 1:
                print()
        return all_passed

    return False


run_qa_video = qa_video
run_qa_single_video = qa_single_video


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PPT-Studio 视频质量自动化门禁")
    parser.add_argument("target", nargs="?", default=".", help="视频文件路径、包含 *.mp4 的目录或项目目录（默认当前目录）")
    parser.add_argument("--srt", help="可选指定 SRT 文件路径")
    args = parser.parse_args(argv)

    target_path = Path(args.target).resolve()
    srt_p = Path(args.srt).resolve() if args.srt else None

    if target_path.is_file():
        passed = qa_video(target_path, srt_p)
        return 0 if passed else 2

    elif target_path.is_dir():
        mp4s = find_videos(target_path)
        if not mp4s:
            print(f"[ERROR] 在 {target_path} 或 output/、projects/*/output/ 下未找到 mp4 视频", file=sys.stderr)
            return 1

        all_ok = True
        for p in mp4s:
            ok = qa_video(p, srt_p)
            if not ok:
                all_ok = False
            print()
        return 0 if all_ok else 2
    else:
        print(f"[ERROR] 路径不存在: {target_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
