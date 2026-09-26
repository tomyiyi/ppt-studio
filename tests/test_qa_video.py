#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_qa_video.py
======================
测试 qa_video.py 的客观门禁判定规则、字幕解析、视频发现机制及 CLI 行为。
使用标准库 unittest 与 tempfile，不依赖真实编解码器执行，不生成或覆盖任何输出。
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.qa_video import (
    parse_srt_time,
    find_associated_srt,
    check_subtitles,
    check_streams,
    check_resolution,
    check_av_sync,
    check_bitrate_and_fps,
    find_videos,
    main,
)


class TestParseSrtTime(unittest.TestCase):
    """测试 SRT 时间戳解析。"""

    def test_standard_format(self):
        self.assertAlmostEqual(parse_srt_time("00:01:23,456"), 83.456)
        self.assertAlmostEqual(parse_srt_time("01:00:00,000"), 3600.0)

    def test_dot_separator(self):
        self.assertAlmostEqual(parse_srt_time("00:00:05.500"), 5.5)

    def test_no_milliseconds(self):
        self.assertAlmostEqual(parse_srt_time("00:02:10"), 130.0)


class TestFindAssociatedSrt(unittest.TestCase):
    """测试关联字幕文件的安全探查机制。"""

    def test_explicit_existing_srt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            video = tmp / "video.mp4"
            video.touch()
            explicit = tmp / "custom.srt"
            explicit.touch()
            self.assertEqual(find_associated_srt(video, explicit), explicit)

    def test_same_stem_srt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            video = tmp / "sample.mp4"
            video.touch()
            srt = tmp / "sample.srt"
            srt.touch()
            self.assertEqual(find_associated_srt(video), srt)

    def test_single_srt_in_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            video = tmp / "movie_1080p.mp4"
            video.touch()
            srt = tmp / "other_name.srt"
            srt.touch()
            self.assertEqual(find_associated_srt(video), srt)

    def test_prefix_match_srt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            video = tmp / "proj_card_1080p.mp4"
            video.touch()
            srt1 = tmp / "proj_card_subtitles.srt"
            srt1.touch()
            srt2 = tmp / "unrelated.srt"
            srt2.touch()
            self.assertEqual(find_associated_srt(video), srt1)

    def test_no_srt_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            video = tmp / "video.mp4"
            video.touch()
            self.assertIsNone(find_associated_srt(video))


class TestCheckSubtitles(unittest.TestCase):
    """测试字幕时序客观质检规则。"""

    def test_none_or_missing_srt_passes_gracefully(self):
        ok, msg = check_subtitles(None, 60.0)
        self.assertTrue(ok)
        self.assertIn("跳过", msg)

        with tempfile.TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "missing.srt"
            ok, msg = check_subtitles(missing, 60.0)
            self.assertTrue(ok)

    def test_empty_srt_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt = Path(tmp_dir) / "empty.srt"
            srt.write_text("   \n\n", encoding="utf-8")
            ok, msg = check_subtitles(srt, 60.0)
            self.assertFalse(ok)
            self.assertIn("为空", msg)

    def test_valid_srt(self):
        valid_srt_content = (
            "1\n00:00:01,000 --> 00:00:04,000\n第一句解说文本\n\n"
            "2\n00:00:04,500 --> 00:00:08,000\n第二句解说文本\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt = Path(tmp_dir) / "valid.srt"
            srt.write_text(valid_srt_content, encoding="utf-8")
            ok, msg = check_subtitles(srt, 10.0)
            self.assertTrue(ok)
            self.assertIn("2 条字幕", msg)

    def test_inverted_timing_fails(self):
        bad_srt_content = "1\n00:00:05,000 --> 00:00:03,000\n倒挂文本\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt = Path(tmp_dir) / "inverted.srt"
            srt.write_text(bad_srt_content, encoding="utf-8")
            ok, msg = check_subtitles(srt, 10.0)
            self.assertFalse(ok)
            self.assertIn("时序倒挂", msg)

    def test_overlapping_cues_fails(self):
        overlap_srt = (
            "1\n00:00:01,000 --> 00:00:05,000\n上一句\n\n"
            "2\n00:00:03,000 --> 00:00:08,000\n严重重叠的一句\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt = Path(tmp_dir) / "overlap.srt"
            srt.write_text(overlap_srt, encoding="utf-8")
            ok, msg = check_subtitles(srt, 10.0)
            self.assertFalse(ok)
            self.assertIn("严重重叠", msg)

    def test_cue_exceeding_video_duration_fails(self):
        exceed_srt = "1\n00:00:01,000 --> 00:00:15,000\n超出结尾\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt = Path(tmp_dir) / "exceed.srt"
            srt.write_text(exceed_srt, encoding="utf-8")
            ok, msg = check_subtitles(srt, 10.0)  # 视频仅 10s，字幕到达 15s
            self.assertFalse(ok)
            self.assertIn("超出视频时长", msg)


class TestCheckStreams(unittest.TestCase):
    """测试音视频流配置及编码规范校验。"""

    def test_valid_streams(self):
        meta = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "24000", "channels": 1},
            ]
        }
        ok, msg = check_streams(meta)
        self.assertTrue(ok)
        self.assertIn("h264", msg)
        self.assertIn("aac", msg)

    def test_missing_video_stream(self):
        meta = {"streams": [{"codec_type": "audio", "codec_name": "aac", "channels": 1}]}
        ok, msg = check_streams(meta)
        self.assertFalse(ok)
        self.assertIn("缺少视频流", msg)

    def test_missing_audio_stream(self):
        meta = {"streams": [{"codec_type": "video", "codec_name": "h264"}]}
        ok, msg = check_streams(meta)
        self.assertFalse(ok)
        self.assertIn("缺少音频流", msg)

    def test_invalid_video_codec(self):
        meta = {
            "streams": [
                {"codec_type": "video", "codec_name": "hevc"},
                {"codec_type": "audio", "codec_name": "aac", "channels": 1},
            ]
        }
        ok, msg = check_streams(meta)
        self.assertFalse(ok)
        self.assertIn("非 H.264", msg)

    def test_invalid_audio_codec(self):
        meta = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "mp3", "channels": 1},
            ]
        }
        ok, msg = check_streams(meta)
        self.assertFalse(ok)
        self.assertIn("非 AAC", msg)

    def test_zero_channels(self):
        meta = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac", "channels": 0},
            ]
        }
        ok, msg = check_streams(meta)
        self.assertFalse(ok)
        self.assertIn("声道数 < 1", msg)


class TestCheckResolution(unittest.TestCase):
    """测试画幅分辨率与色彩空间校验。"""

    def test_none_stream(self):
        ok, msg = check_resolution(None)
        self.assertFalse(ok)

    def test_valid_resolutions(self):
        for w, h, expected_ratio in [(1920, 1080, "16:9"), (1080, 1920, "9:16"), (1080, 1350, "3:4")]:
            v_stream = {"width": w, "height": h, "pix_fmt": "yuv420p"}
            ok, msg = check_resolution(v_stream)
            self.assertTrue(ok)
            self.assertIn(expected_ratio, msg)
            self.assertIn("yuv420p", msg)

    def test_invalid_resolution(self):
        v_stream = {"width": 1280, "height": 720, "pix_fmt": "yuv420p"}
        ok, msg = check_resolution(v_stream)
        self.assertFalse(ok)
        self.assertIn("非标准发布分辨率", msg)

    def test_invalid_pix_fmt(self):
        v_stream = {"width": 1920, "height": 1080, "pix_fmt": "yuv444p"}
        ok, msg = check_resolution(v_stream)
        self.assertFalse(ok)
        self.assertIn("像素格式非 yuv420p", msg)


class TestCheckAvSync(unittest.TestCase):
    """测试音画同步容差判定。"""

    def test_missing_stream(self):
        ok, _ = check_av_sync({})
        self.assertFalse(ok)

    def test_in_sync(self):
        meta = {
            "streams": [
                {"codec_type": "video", "duration": "10.05"},
                {"codec_type": "audio", "duration": "10.10"},
            ]
        }
        ok, msg = check_av_sync(meta)
        self.assertTrue(ok)
        self.assertIn("≤ 0.35s", msg)

    def test_out_of_sync(self):
        meta = {
            "streams": [
                {"codec_type": "video", "duration": "10.00"},
                {"codec_type": "audio", "duration": "10.50"},
            ]
        }
        ok, msg = check_av_sync(meta)
        self.assertFalse(ok)
        self.assertIn("音画时长偏差过大", msg)


class TestCheckBitrateAndFps(unittest.TestCase):
    """测试帧率与码率安全范围。"""

    def test_none_stream(self):
        ok, _ = check_bitrate_and_fps(None, {})
        self.assertFalse(ok)

    def test_normal_fps_and_bitrate(self):
        v_stream = {"r_frame_rate": "30/1"}
        fmt = {"bit_rate": "1200000"}
        ok, msg = check_bitrate_and_fps(v_stream, fmt)
        self.assertTrue(ok)
        self.assertIn("30.0 fps", msg)
        self.assertIn("1200 kbps", msg)

    def test_fractional_fps(self):
        v_stream = {"r_frame_rate": "60000/1001"}
        fmt = {"bit_rate": "2500000"}
        ok, msg = check_bitrate_and_fps(v_stream, fmt)
        self.assertTrue(ok)
        self.assertIn("59.9 fps", msg)

    def test_low_bitrate(self):
        v_stream = {"r_frame_rate": "30/1"}
        fmt = {"bit_rate": "150000"}
        ok, msg = check_bitrate_and_fps(v_stream, fmt)
        self.assertFalse(ok)
        self.assertIn("码率过低", msg)

    def test_abnormal_fps(self):
        v_stream = {"r_frame_rate": "15/1"}
        fmt = {"bit_rate": "1000000"}
        ok, msg = check_bitrate_and_fps(v_stream, fmt)
        self.assertFalse(ok)
        self.assertIn("异常帧率", msg)


class TestFindVideos(unittest.TestCase):
    """测试视频发现逻辑在各种文件树结构下的稳健性。"""

    def test_explicit_file_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "test.mp4"
            f.touch()
            self.assertEqual(find_videos(f), [f])

    def test_explicit_non_mp4_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "test.txt"
            f.touch()
            self.assertEqual(find_videos(f), [])

    def test_direct_mp4_in_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            f = d / "clip.mp4"
            f.touch()
            self.assertEqual(find_videos(d), [f])

    def test_output_subdir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            out = d / "output"
            out.mkdir()
            v = out / "clip.mp4"
            v.touch()
            self.assertEqual(find_videos(d), [v])

    def test_projects_target_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            proj_root = Path(tmp_dir) / "projects"
            p1_out = proj_root / "proj_alpha" / "output"
            p1_out.mkdir(parents=True)
            v1 = p1_out / "alpha.mp4"
            v1.touch()

            found = find_videos(proj_root)
            self.assertEqual(found, [v1])

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual(find_videos(Path(tmp_dir)), [])


class TestQAVideoCLI(unittest.TestCase):
    """测试 qa_video CLI 返回码与调度。"""

    def test_nonexistent_path_returns_1(self):
        exit_code = main(["/non_existent_path_12345"])
        self.assertEqual(exit_code, 1)

    def test_dir_without_videos_returns_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main([tmp_dir])
            self.assertEqual(exit_code, 1)

    @patch("scripts.qa_video.qa_video", return_value=True)
    def test_cli_success_returns_0(self, mock_qa):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "sample.mp4"
            f.touch()
            exit_code = main([str(f)])
            self.assertEqual(exit_code, 0)
            mock_qa.assert_called_once()

    @patch("scripts.qa_video.qa_video", return_value=False)
    def test_cli_failure_returns_2(self, mock_qa):
        with tempfile.TemporaryDirectory() as tmp_dir:
            f = Path(tmp_dir) / "sample.mp4"
            f.touch()
            exit_code = main([str(f)])
            self.assertEqual(exit_code, 2)
            mock_qa.assert_called_once()


if __name__ == "__main__":
    unittest.main()
