#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_video.py —— SVG 画布 + 解说稿 → 自动配音短视频
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
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

VOICE_MAP = {
    "zh-female": "zh-CN-XiaoxiaoNeural",
    "zh-female-calm": "zh-CN-XiaoyiNeural",
    "zh-male": "zh-CN-YunxiNeural",
    "zh-male-deep": "zh-CN-YunjianNeural",
    "zh-male-doc": "zh-CN-YunyangNeural",
}


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)


def probe_duration(media_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    res = run_cmd(cmd)
    return float(res.stdout.strip())


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


def ensure_page_images(project_dir: Path, pages: list[str], format_ratio: str, work_dir: Path) -> dict[str, Path]:
    """根据画面比例渲染或准备高分辨率静态底图。"""
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    from render_svg import render_one

    out_images = {}
    if format_ratio == "16:9":
        # 横版：基于 svg_output/*.svg 渲染 1920×1080 (scale 1.5)
        src_dir = project_dir / "svg_output"
        scale = 1.5
    else:
        # 竖版：基于 cards/*.svg 渲染 1080×1350 或 1080×1920
        src_dir = project_dir / "cards"
        scale = 1.0

    if not src_dir.exists():
        raise FileNotFoundError(f"源画面目录不存在: {src_dir}")

    for p in pages:
        svg_file = src_dir / f"{p}.svg"
        if not svg_file.exists():
            # 尝试模糊匹配 (比如前缀 01_ 等)
            matches = list(src_dir.glob(f"{p}*.svg"))
            if matches:
                svg_file = matches[0]
            else:
                raise FileNotFoundError(f"未找到对应页面 SVG: {p} in {src_dir}")

        dest_png = work_dir / f"{p}.png"
        render_one(svg_file, dest_png, scale=scale)
        out_images[p] = dest_png
    return out_images


def make_video(
    project_dir: Path,
    voice_key: str = "zh-female",
    format_ratio: str = "16:9",
    subtitles_mode: str = "burned",
    motion: str = "subtle",
    out_video_path: Path | None = None,
    check: bool = False,
) -> Path:
    project_dir = project_dir.resolve()
    vo_items = load_voiceover(project_dir)
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
            generate_tts(text, voice_name, raw_audio, raw_vtt)
            audio_dur = probe_duration(raw_audio)

            # 在音频末尾添加静音垫片
            final_audio = tmp_dir / f"{p}_audio.wav"
            pad_cmd = [
                "ffmpeg", "-y", "-i", str(raw_audio),
                "-af", f"apad=pad_dur={pause}",
                str(final_audio),
            ]
            run_cmd(pad_cmd)
            slide_dur = probe_duration(final_audio)

            # 解析字幕时间戳
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
        with open(srt_file, "w", encoding="utf-8") as f:
            for c_idx, cue in enumerate(all_cues, 1):
                f.write(f"{c_idx}\n")
                f.write(f"{seconds_to_srt_time(cue['start'])} --> {seconds_to_srt_time(cue['end'])}\n")
                f.write(f"{cue['text']}\n\n")

        # 复制一份到输出目录备用
        out_srt = out_video_path.with_suffix(".srt")
        shutil.copyfile(srt_file, out_srt)
        print(f"✓ 统一字幕轨生成: {out_srt}")

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
                str(out_video_path),
            ]
            run_cmd(burn_cmd)
        else:
            # 直接拷贝
            shutil.copyfile(merged_raw_mp4, out_video_path)

        final_dur = probe_duration(out_video_path)
        file_size_mb = out_video_path.stat().st_size / (1024 * 1024)
        print(f"==================================================")
        print(f"🎉 视频合成圆满完成！")
        print(f"   产物: {out_video_path}")
        print(f"   时长: {final_dur:.1f} 秒 ({final_dur/60:.2f} 分钟)")
        print(f"   大小: {file_size_mb:.2f} MB")
        print(f"   分镜: 共 {len(timeline)} 页")
        print(f"==================================================")

        if check:
            if run_qa_video is not None:
                srt_arg = out_srt if subtitles_mode != "none" else None
                ok = run_qa_video(out_video_path, srt_path=srt_arg)
                if not ok:
                    raise RuntimeError(f"视频客观质量门禁未通过: {out_video_path}")
                print("  [门禁] ✓ 视频客观质量门禁通过")
            else:
                print("  [warn] 未导入 run_qa_video，跳过视频门禁检查")

        return out_video_path

    finally:
        # 清理临时文件
        shutil.rmtree(tmp_dir, ignore_errors=True)


def resolve_project_dir(
    project_arg: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """自适应探测包含视频合成资源的项目目录。

    保留显式 project 参数行为；
    未传时从当前目录或 projects/ 下安全发现唯一包含 voiceover/notes 及 SVG 画布的项目。
    """
    if project_arg is not None and str(project_arg).strip() != "":
        proj = Path(project_arg)
        if not proj.is_absolute() and base_dir is not None:
            proj = (Path(base_dir) / proj).resolve()
        else:
            proj = proj.resolve()
        if not proj.exists():
            raise FileNotFoundError(f"指定的项目目录不存在: {project_arg}")
        if proj.name in ("svg_output", "cards", "notes") and proj.is_dir():
            proj = proj.parent
        return proj

    base = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()

    def is_valid_project(p: Path) -> bool:
        if not p.is_dir():
            return False
        has_vo = (p / "voiceover.json").is_file() or (
            (p / "notes").is_dir() and any((p / "notes").glob("*.md"))
        )
        has_svg = (
            ((p / "svg_output").is_dir() and any((p / "svg_output").glob("*.svg")))
            or ((p / "cards").is_dir() and any((p / "cards").glob("*.svg")))
        )
        return has_vo and has_svg

    # 1. 当前目录本身就是有效项目目录
    if is_valid_project(base):
        return base

    # 若当前位于子目录 (如 svg_output/、cards/、notes/)
    if base.name in ("svg_output", "cards", "notes") and is_valid_project(base.parent):
        return base.parent

    # 2. 从 projects/ 目录下安全发现
    candidate_projects_dirs: list[Path] = []
    if base.is_dir() and base.name == "projects":
        candidate_projects_dirs.append(base)
    elif (base / "projects").is_dir():
        candidate_projects_dirs.append(base / "projects")
    elif base_dir is None:
        for cand in [base.parent, base.parent.parent, Path(__file__).resolve().parent.parent]:
            try:
                p_cand = cand / "projects"
                if p_cand.is_dir() and p_cand.resolve() not in [d.resolve() for d in candidate_projects_dirs]:
                    candidate_projects_dirs.append(p_cand)
                    break
            except Exception:
                pass

    found: list[Path] = []
    seen: set[Path] = set()

    for p_dir in candidate_projects_dirs:
        for sub in sorted(p_dir.iterdir()):
            if sub.is_dir() and is_valid_project(sub):
                r_sub = sub.resolve()
                if r_sub not in seen:
                    seen.add(r_sub)
                    found.append(r_sub)
        if found:
            break

    if len(found) == 1:
        return found[0]
    elif len(found) == 0:
        raise FileNotFoundError(
            "未在当前目录或 projects/ 下发现包含解说稿及 SVG 画布的有效项目，请显式指定 project 参数"
        )
    else:
        names = ", ".join(p.name for p in found)
        raise ValueError(
            f"发现多个有效项目 ({names})，无法安全确定，请显式指定 project 参数"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SVG 画布 + 解说稿 → 自动配音短视频")
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="项目根目录，例如 projects/agentflow-os-launch（默认自动发现）",
    )
    parser.add_argument("--voice", default="zh-female", choices=list(VOICE_MAP.keys()), help="中文 TTS 发音人")
    parser.add_argument("--format", default="16:9", choices=["16:9", "9:16"], help="视频比例")
    parser.add_argument("--subtitles", default="burned", choices=["burned", "soft", "none"], help="字幕模式")
    parser.add_argument("--motion", default="subtle", choices=["subtle", "none"], help="动效模式")
    parser.add_argument("--out", help="自定义输出 MP4 路径")
    parser.add_argument("--check", action="store_true", help="合成完成后执行视频质量客观门禁校验 (qa_video.py)")
    args = parser.parse_args(argv)

    try:
        proj_dir = resolve_project_dir(args.project)
    except (FileNotFoundError, ValueError) as err:
        print(f"[err] {err}", file=sys.stderr)
        return 1

    out_p = Path(args.out).resolve() if args.out else None

    try:
        make_video(
            project_dir=proj_dir,
            voice_key=args.voice,
            format_ratio=args.format,
            subtitles_mode=args.subtitles,
            motion=args.motion,
            out_video_path=out_p,
            check=args.check,
        )
    except Exception as err:
        print(f"[err] 视频合成失败: {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
