#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_video.py -- SVG 画布 + 解说稿 → 自动配音短视频
===================================================

同一份内容的第四出口：
将 spec_lock / SVG 画布 / notes 串联，结合 Edge-TTS 中文语音合成与 FFmpeg，
自动生成带旁白解说、转场动效与字幕轨的短视频（1080p 横版或 9:16 竖版）。

特性：
  - 音频驱动时序：每页视频时长由 TTS 解说时长自适应决定，去机械卡顿感
  - 自然口语化解说稿（voiceover.json 或 notes/*.md 智能提取）
  - 动态效果：微 Ken Burns 运镜（缓慢推近），赋予静态幻灯片生动质感
  - 自动对齐多段字幕，生成工程级统一 SRT 字幕轨并支持硬字幕烧录
  - 极速合成与规范化导出（H.264 + AAC，跨端兼容性最佳）

用法：
  python3 scripts/make_video.py [project_dir] [--voice zh-female] [--subtitles burned] [--out video.mp4] [--check]
  （未传 project 时自动从当前目录或 projects/ 下发现唯一有效项目）

模块拆分（对外接口不变）：
  scripts/video_tts.py      -- VOICE_MAP / load_voiceover / generate_tts
  scripts/video_subtitle.py -- VTT/SRT 解析与时间转换
  scripts/video_assemble.py -- run_cmd / commit_video_pair / probe_duration /
                               ensure_page_images / resolve_project_dir
  本文件保留编排入口 make_video() 与 CLI main()，并 re-export 全部名称以兼容旧引用。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.qa_video import run_qa_video
except ImportError:
    try:
        from qa_video import run_qa_video
    except ImportError:
        run_qa_video = None

try:
    from scripts.video_tts import VOICE_MAP, generate_tts, load_voiceover
    from scripts.video_subtitle import (
        format_srt_cues,
        parse_vtt_cues,
        seconds_to_srt_time,
        vtt_time_to_seconds,
        write_srt,
    )
    from scripts.video_assemble import (
        commit_video_pair,
        ensure_page_images,
        probe_duration,
        resolve_project_dir,
        run_cmd,
    )
except ImportError:
    from video_tts import VOICE_MAP, generate_tts, load_voiceover
    from video_subtitle import (
        format_srt_cues,
        parse_vtt_cues,
        seconds_to_srt_time,
        vtt_time_to_seconds,
        write_srt,
    )
    from video_assemble import (
        commit_video_pair,
        ensure_page_images,
        probe_duration,
        resolve_project_dir,
        run_cmd,
    )

__all__ = [
    "VOICE_MAP",
    "commit_video_pair",
    "ensure_page_images",
    "format_srt_cues",
    "generate_tts",
    "load_voiceover",
    "make_video",
    "main",
    "parse_vtt_cues",
    "probe_duration",
    "resolve_project_dir",
    "run_cmd",
    "run_qa_video",
    "seconds_to_srt_time",
    "vtt_time_to_seconds",
    "write_srt",
]


def make_video(
    project_dir: Path | str | None = None,
    voice_key: str = "zh-female",
    format_ratio: str = "16:9",
    subtitles_mode: str = "burned",
    motion: str = "subtle",
    out_video_path: Path | str | None = None,
    check: bool = False,
    base_dir: str | Path | None = None,
) -> Path:
    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    if project_dir is not None:
        p_in = Path(project_dir)
        p_resolved = (base / p_in).resolve() if not p_in.is_absolute() else p_in.resolve()
        project_dir = resolve_project_dir(p_resolved, base_dir=base)
    else:
        project_dir = resolve_project_dir(base_dir=base)

    project_dir = project_dir.resolve()
    vo_items = load_voiceover(project_dir, base_dir=base)
    if not vo_items:
        raise ValueError("未找到任何有效解说分镜 (voiceover 为空)")
    voice_name = VOICE_MAP.get(voice_key, voice_key)

    if out_video_path is None:
        repo_root = Path(__file__).resolve().parent.parent
        suffix = "_1080p.mp4" if format_ratio == "16:9" else "_竖版.mp4"
        if (project_dir / "output").is_dir():
            out_dir = project_dir / "output"
        elif (repo_root / "output").is_dir():
            out_dir = repo_root / "output"
        else:
            out_dir = project_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_video_path = out_dir / f"{project_dir.name}{suffix}"
    else:
        out_p = Path(out_video_path)
        out_video_path = (base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
        out_video_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"==================================================")
    print(f"🎬 启动 PPT-Studio 视频合成管线")
    print(f"   项目: {project_dir.name}")
    print(f"   画幅: {format_ratio}")
    print(f"   音色: {voice_name} ({voice_key})")
    print(f"   字幕: {subtitles_mode}")
    print(f"   运镜: {motion}")
    print(f"   目标: {out_video_path}")
    print(f"==================================================")

    tmp_dir = Path(tempfile.mkdtemp(prefix="ppt_studio_video_"))
    try:
        pages = [item["page"] for item in vo_items]
        print(f"[*] 第 1 步：渲染高精底图（{len(pages)} 页）...")
        try:
            img_map = ensure_page_images(project_dir, pages, format_ratio, tmp_dir, base_dir=base)
        except TypeError:
            img_map = ensure_page_images(project_dir, pages, format_ratio, tmp_dir)

        print(f"[*] 第 2 步：语音合成 (TTS) 与分镜时长计算...")
        all_cues = []
        timeline = []
        accumulated_time = 0.0

        for idx, item in enumerate(vo_items, 1):
            p = item["page"]
            text = item.get("narration", "").strip()
            pause = float(item.get("pause_after", 1.0))
            raw_audio = tmp_dir / f"{p}_raw.mp3"
            raw_vtt = tmp_dir / f"{p}.vtt"

            print(f"    [{idx}/{len(vo_items)}] 生成配音: {p}（{len(text)} 字）...")
            try:
                generate_tts(text, voice_name, raw_audio, raw_vtt, base_dir=base)
            except TypeError:
                generate_tts(text, voice_name, raw_audio, raw_vtt)
            try:
                audio_dur = probe_duration(raw_audio, base_dir=base)
            except TypeError:
                audio_dur = probe_duration(raw_audio)

            # 在音频末尾添加静音垫片
            final_audio = tmp_dir / f"{p}_audio.wav"
            pad_cmd = [
                "ffmpeg", "-y", "-i", str(raw_audio),
                "-af", f"apad=pad_dur={pause}",
                str(final_audio),
            ]
            run_cmd(pad_cmd)
            try:
                slide_dur = probe_duration(final_audio, base_dir=base)
            except TypeError:
                slide_dur = probe_duration(final_audio)

            # 解析字幕时间戳
            try:
                page_cues = parse_vtt_cues(raw_vtt, offset_sec=accumulated_time, base_dir=base)
            except TypeError:
                page_cues = parse_vtt_cues(raw_vtt, offset_sec=accumulated_time)
            all_cues.extend(page_cues)

            timeline.append({
                "page": p,
                "audio": final_audio,
                "image": img_map[p],
                "duration": slide_dur,
                "start": accumulated_time,
                "end": accumulated_time + slide_dur,
                "motion": item.get("motion", "ken_burns_zoom_in"),
            })
            accumulated_time += slide_dur

        print(f"[*] 全片总时长估算: {accumulated_time:.1f} 秒 ({accumulated_time/60:.2f} 分钟)")

        # 生成工程统一 SRT
        srt_file = tmp_dir / "timeline.srt"
        try:
            write_srt(all_cues, srt_file, base_dir=base)
        except TypeError:
            write_srt(all_cues, srt_file)

        # 先在事务临时目录中准备字幕；正式目录只在 MP4 和 SRT 都成功后更新。
        out_srt = out_video_path.with_suffix(".srt")
        staged_srt = tmp_dir / out_srt.name
        shutil.copyfile(srt_file, staged_srt)
        print(f"✓ 统一字幕轨已准备: {out_srt}")
        staged_video = tmp_dir / out_video_path.name

        print(f"[*] 第 3 步：分镜视频片段渲染与动效合成...")
        segment_files = []
        for idx, slide in enumerate(timeline, 1):
            p = slide["page"]
            dur = slide["duration"]
            img_p = slide["image"]
            aud_p = slide["audio"]
            seg_mp4 = tmp_dir / f"seg_{idx:02d}_{p}.mp4"

            # 帧率与像素规格
            fps = 30
            total_frames = int(round(dur * fps))

            if format_ratio == "16:9":
                res_w, res_h = 1920, 1080
            else:
                res_w, res_h = 1080, 1920

            if motion == "subtle":
                # 微 Ken Burns: 从 1.0 缓慢缩放到 1.035
                vf = (
                    f"zoompan=z='min(zoom+0.0004,1.035)':d={total_frames}:"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={res_w}x{res_h}:fps={fps},"
                    f"format=yuv420p"
                )
            else:
                vf = f"scale={res_w}:{res_h},format=yuv420p"

            seg_cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fps), "-i", str(img_p),
                "-i", str(aud_p),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                "-t", f"{dur:.3f}",
                str(seg_mp4),
            ]
            run_cmd(seg_cmd)
            segment_files.append(seg_mp4)
            print(f"    ✓ 分镜 {idx}/{len(timeline)} 完成: {seg_mp4.name} ({dur:.1f}s)")

        print(f"[*] 第 4 步：拼接所有分镜片段...")
        concat_list = tmp_dir / "concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for s in segment_files:
                f.write(f"file '{s.resolve()}'\n")

        merged_raw_mp4 = tmp_dir / "merged_raw.mp4"
        concat_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(merged_raw_mp4),
        ]
        run_cmd(concat_cmd)

        if subtitles_mode == "burned":
            print(f"[*] 第 5 步：烧录精装硬字幕...")
            # 优雅字幕样式：居中微底边、大字、阴影描边
            font_size = 22 if format_ratio == "16:9" else 26
            margin_v = 45 if format_ratio == "16:9" else 120
            style = (
                f"FontSize={font_size},"
                f"PrimaryColour=&H00F9F7F7,"    # 白偏米色
                f"OutlineColour=&H000C0908,"    # 暗黑边
                f"BackColour=&H60000000,"       # 半透灰黑底衬
                f"BorderStyle=3,"
                f"Outline=1.5,"
                f"Shadow=0,"
                f"MarginV={margin_v},"
                f"Alignment=2"
            )
            # 转义路径中可能的冒号等字符
            escaped_srt = str(srt_file).replace(":", r"\:").replace("\\", "/")
            burn_cmd = [
                "ffmpeg", "-y", "-i", str(merged_raw_mp4),
                "-vf", f"subtitles='{escaped_srt}':force_style='{style}'",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "copy",
                str(staged_video),
            ]
            run_cmd(burn_cmd)
        else:
            # 直接拷贝
            shutil.copyfile(merged_raw_mp4, staged_video)

        try:
            final_dur = probe_duration(staged_video, base_dir=base)
        except TypeError:
            final_dur = probe_duration(staged_video)
        file_size_mb = staged_video.stat().st_size / (1024 * 1024)
        print(f"==================================================")
        print(f"🎉 视频合成圆满完成！")
        print(f"   产物: {out_video_path}")
        print(f"   时长: {final_dur:.1f} 秒 ({final_dur/60:.2f} 分钟)")
        print(f"   大小: {file_size_mb:.2f} MB")
        print(f"   分镜: 共 {len(timeline)} 页")
        print(f"==================================================")

        if check:
            if run_qa_video is not None:
                srt_arg = staged_srt if subtitles_mode != "none" else None
                try:
                    ok = run_qa_video(staged_video, srt_path=srt_arg, base_dir=base)
                except TypeError:
                    ok = run_qa_video(staged_video, srt_path=srt_arg)
                if not ok:
                    raise RuntimeError(f"视频客观质量门禁未通过: {out_video_path}")
                print("  [门禁] ✓ 视频客观质量门禁通过")
            else:
                print("  [warn] 未导入 run_qa_video，跳过视频门禁检查")

        try:
            commit_video_pair(staged_video, staged_srt, out_video_path, out_srt, base_dir=base)
        except TypeError:
            commit_video_pair(staged_video, staged_srt, out_video_path, out_srt)
        print(f"✓ MP4/SRT 成对提交完成: {out_video_path} + {out_srt}")
        return out_video_path

    finally:
        # 清理临时文件
        shutil.rmtree(tmp_dir, ignore_errors=True)

def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="SVG 画布 + 解说稿 → 自动配音短视频")
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="项目根目录，例如 projects/agentflow-os-launch（默认自动发现）",
    )
    parser.add_argument("--base-dir", default=None, help="指定基础工作目录 (默认: 当前工作目录)")
    parser.add_argument("--voice", default="zh-female", choices=list(VOICE_MAP.keys()), help="中文 TTS 发音人")
    parser.add_argument("--format", default="16:9", choices=["16:9", "9:16"], help="视频比例")
    parser.add_argument("--subtitles", default="burned", choices=["burned", "soft", "none"], help="字幕模式")
    parser.add_argument("--motion", default="subtle", choices=["subtle", "none"], help="动效模式")
    parser.add_argument("--out", help="自定义输出 MP4 路径")
    parser.add_argument("--check", action="store_true", help="合成完成后执行视频质量客观门禁校验 (qa_video.py)")
    args = parser.parse_args(argv)

    effective_base = (
        Path(args.base_dir).resolve()
        if args.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    try:
        proj_dir = resolve_project_dir(args.project, base_dir=effective_base)
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1

    out_p = Path(args.out) if args.out else None
    if out_p is not None and not out_p.is_absolute():
        out_p = (effective_base / out_p).resolve()

    try:
        make_video(
            project_dir=proj_dir,
            voice_key=args.voice,
            format_ratio=args.format,
            subtitles_mode=args.subtitles,
            motion=args.motion,
            out_video_path=out_p,
            check=args.check,
            base_dir=effective_base,
        )
    except Exception as err:
        print(f"[err] 视频合成失败: {err}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
