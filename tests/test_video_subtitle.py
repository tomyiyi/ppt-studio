import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.video_subtitle import (
    format_srt_cues,
    main,
    parse_vtt_cues,
    seconds_to_srt_time,
    vtt_time_to_seconds,
    write_srt,
)
import scripts.make_video as make_video


class TestVideoSubtitle(unittest.TestCase):
    def test_vtt_time_to_seconds_three_parts(self):
        self.assertAlmostEqual(vtt_time_to_seconds("01:02:03.500"), 3723.5)
        self.assertAlmostEqual(vtt_time_to_seconds("00:00:01,250"), 1.25)

    def test_vtt_time_to_seconds_two_parts(self):
        self.assertAlmostEqual(vtt_time_to_seconds("02:30.200"), 150.2)
        self.assertAlmostEqual(vtt_time_to_seconds("00:05"), 5.0)

    def test_vtt_time_to_seconds_one_part(self):
        self.assertAlmostEqual(vtt_time_to_seconds("42.5"), 42.5)

    def test_seconds_to_srt_time(self):
        self.assertEqual(seconds_to_srt_time(0.0), "00:00:00,000")
        self.assertEqual(seconds_to_srt_time(65.123), "00:01:05,123")
        self.assertEqual(seconds_to_srt_time(3661.004), "01:01:01,004")
        # 边界与溢出保护测试
        self.assertEqual(seconds_to_srt_time(0.9999), "00:00:00,999")

    def test_parse_vtt_cues_nonexistent(self):
        self.assertEqual(parse_vtt_cues(Path("/non_existent_sub_file.vtt")), [])
        self.assertEqual(parse_vtt_cues("/non_existent_sub_file.vtt"), [])

    def test_parse_vtt_cues_content_and_offset(self):
        sample_vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
第一行字幕
多行内容

00:00:04.000 --> 00:00:06.000
第二行字幕
"""
        with tempfile.TemporaryDirectory() as td:
            vtt_p = Path(td) / "test.vtt"
            vtt_p.write_text(sample_vtt, encoding="utf-8")

            # 测试 Path 输入
            cues = parse_vtt_cues(vtt_p, offset_sec=0.0)
            self.assertEqual(len(cues), 2)
            self.assertAlmostEqual(cues[0]["start"], 1.0)
            self.assertAlmostEqual(cues[0]["end"], 3.5)
            self.assertEqual(cues[0]["text"], "第一行字幕 多行内容")

            # 测试 str 输入与 offset_sec 偏移
            cues_offset = parse_vtt_cues(str(vtt_p), offset_sec=10.0)
            self.assertEqual(len(cues_offset), 2)
            self.assertAlmostEqual(cues_offset[0]["start"], 11.0)
            self.assertAlmostEqual(cues_offset[0]["end"], 13.5)
            self.assertAlmostEqual(cues_offset[1]["start"], 14.0)
            self.assertAlmostEqual(cues_offset[1]["end"], 16.0)

    def test_parse_vtt_cues_with_base_dir(self):
        sample_vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n"
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            rel_dir = base / "subs"
            rel_dir.mkdir()
            vtt = rel_dir / "intro.vtt"
            vtt.write_text(sample_vtt, encoding="utf-8")

            cues = parse_vtt_cues("subs/intro.vtt", base_dir=base)
            self.assertEqual(len(cues), 1)
            self.assertEqual(cues[0]["text"], "Hello")

    def test_format_srt_cues_and_write_srt(self):
        cues = [
            {"start": 1.0, "end": 2.5, "text": "Hello world"},
            {"start": 3.0, "end": 5.0, "text": "PPT Studio"},
        ]
        formatted = format_srt_cues(cues)
        self.assertIn("1\n00:00:01,000 --> 00:00:02,500\nHello world", formatted)
        self.assertIn("2\n00:00:03,000 --> 00:00:05,000\nPPT Studio", formatted)

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_file = write_srt(cues, "out/sub.srt", base_dir=base)
            self.assertTrue(out_file.is_file())
            content = out_file.read_text(encoding="utf-8")
            self.assertEqual(content, formatted)

    def test_make_video_exports_video_subtitle_symbols(self):
        self.assertTrue(hasattr(make_video, "format_srt_cues"))
        self.assertTrue(hasattr(make_video, "write_srt"))
        self.assertTrue(hasattr(make_video, "parse_vtt_cues"))
        self.assertTrue(hasattr(make_video, "seconds_to_srt_time"))
        self.assertTrue(hasattr(make_video, "vtt_time_to_seconds"))


class TestVideoSubtitleMain(unittest.TestCase):
    SAMPLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:03.500
第一行字幕
多行内容

00:00:04.000 --> 00:00:06.000
第二行字幕
"""

    def test_main_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            vtt_p = Path(td) / "test.vtt"
            vtt_p.write_text(self.SAMPLE_VTT, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(vtt_p)])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("00:00:01,000 --> 00:00:03,500", out)
            self.assertIn("第一行字幕 多行内容", out)

    def test_main_output_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            vtt_p = base / "test.vtt"
            vtt_p.write_text(self.SAMPLE_VTT, encoding="utf-8")
            out_p = base / "out" / "sub.srt"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(vtt_p), "-o", str(out_p)], base_dir=base)
            self.assertEqual(rc, 0)
            self.assertTrue(out_p.is_file())
            content = out_p.read_text(encoding="utf-8")
            self.assertIn("00:00:04,000 --> 00:00:06,000", content)
            self.assertIn("第二行字幕", content)

    def test_main_with_offset(self):
        with tempfile.TemporaryDirectory() as td:
            vtt_p = Path(td) / "test.vtt"
            vtt_p.write_text(self.SAMPLE_VTT, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(vtt_p), "--offset", "2.5"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("00:00:03,500 --> 00:00:06,000", out)

    def test_main_json_output(self):
        with tempfile.TemporaryDirectory() as td:
            vtt_p = Path(td) / "test.vtt"
            vtt_p.write_text(self.SAMPLE_VTT, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(vtt_p), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["text"], "第一行字幕 多行内容")

    def test_main_with_base_dir_relative(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            vtt_dir = base / "subs"
            vtt_dir.mkdir()
            vtt_p = vtt_dir / "sample.vtt"
            vtt_p.write_text(self.SAMPLE_VTT, encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["subs/sample.vtt", "-o", "out/sample.srt", "--base-dir", str(base)])
            self.assertEqual(rc, 0)
            self.assertTrue((base / "out" / "sample.srt").is_file())

    def test_main_file_not_found(self):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = main(["/non_existent_path.vtt"])
        self.assertEqual(rc, 1)
        self.assertIn("找不到 VTT 字幕文件", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
