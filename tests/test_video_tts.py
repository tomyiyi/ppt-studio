import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.video_tts import (
    VOICE_MAP,
    generate_tts,
    load_voiceover,
    main,
)


class TestVideoTts(unittest.TestCase):
    def test_voice_map_contains_standard_voices(self):
        self.assertIn("zh-female", VOICE_MAP)
        self.assertIn("zh-male", VOICE_MAP)
        self.assertEqual(VOICE_MAP["zh-female"], "zh-CN-XiaoxiaoNeural")

    def test_load_voiceover_json_path_and_str(self):
        sample = [
            {"page": "01", "title": "封面", "narration": "欢迎收看", "pause_after": 1.0}
        ]
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "my_proj"
            proj.mkdir()
            (proj / "voiceover.json").write_text(json.dumps(sample), encoding="utf-8")

            # 测试 Path 输入
            vo1 = load_voiceover(proj)
            self.assertEqual(len(vo1), 1)
            self.assertEqual(vo1[0]["title"], "封面")

            # 测试 str 输入
            vo2 = load_voiceover(str(proj))
            self.assertEqual(len(vo2), 1)
            self.assertEqual(vo2[0]["narration"], "欢迎收看")

    def test_load_voiceover_with_base_dir(self):
        sample = [{"page": "01", "narration": "测试"}]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "nested_proj"
            proj.mkdir()
            (proj / "voiceover.json").write_text(json.dumps(sample), encoding="utf-8")

            vo = load_voiceover("nested_proj", base_dir=base)
            self.assertEqual(len(vo), 1)
            self.assertEqual(vo[0]["narration"], "测试")

    def test_load_voiceover_empty_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "voiceover.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_voiceover(proj)

    def test_load_voiceover_fallback_notes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            notes_dir = proj / "notes"
            notes_dir.mkdir()

            (notes_dir / "01_cover.md").write_text("封面大标题\n- 核心要点一\n- 核心要点二", encoding="utf-8")
            (notes_dir / "02_detail.md").write_text("详情页标题", encoding="utf-8")

            vo = load_voiceover(proj)
            self.assertEqual(len(vo), 2)
            self.assertEqual(vo[0]["page"], "01_cover")
            self.assertEqual(vo[0]["title"], "封面大标题")
            self.assertEqual(vo[0]["narration"], "核心要点一 核心要点二")
            self.assertEqual(vo[1]["page"], "02_detail")
            self.assertEqual(vo[1]["title"], "详情页标题")
            self.assertEqual(vo[1]["narration"], "详情页标题展示")

    def test_load_voiceover_nonexistent_proj(self):
        with self.assertRaises(FileNotFoundError):
            load_voiceover(Path("/non_existent_path_xyz123"))

    def test_load_voiceover_missing_notes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            with self.assertRaises(FileNotFoundError):
                load_voiceover(proj)

    def test_load_voiceover_empty_notes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "notes").mkdir()
            with self.assertRaises(ValueError):
                load_voiceover(proj)

    @patch("subprocess.run")
    def test_generate_tts_mock_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_audio = base / "out" / "test.mp3"
            out_vtt = base / "out" / "test.vtt"

            generate_tts("测试文本", "zh-CN-XiaoxiaoNeural", str(out_audio), str(out_vtt))
            self.assertTrue(mock_run.called)
            self.assertTrue((base / "out").is_dir())


class TestVideoTtsMain(unittest.TestCase):
    def test_main_list_voices(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--list-voices"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("zh-female", data)
        self.assertEqual(data["zh-female"], "zh-CN-XiaoxiaoNeural")

    def test_main_project_load(self):
        sample = [{"page": "01", "title": "封面", "narration": "欢迎收看"}]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "proj"
            proj.mkdir()
            (proj / "voiceover.json").write_text(json.dumps(sample), encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([str(proj)])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["title"], "封面")

    def test_main_project_with_base_dir(self):
        sample = [{"page": "01", "narration": "相对路径测试"}]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proj = base / "nested"
            proj.mkdir()
            (proj / "voiceover.json").write_text(json.dumps(sample), encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["nested", "--base-dir", str(base)])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data[0]["narration"], "相对路径测试")

    @patch("scripts.video_tts.generate_tts")
    def test_main_text_tts_mock(self, mock_gen):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--text", "测试文本", "--audio", "out.mp3", "--vtt", "out.vtt"])
        self.assertEqual(rc, 0)
        self.assertTrue(mock_gen.called)
        args, kwargs = mock_gen.call_args
        self.assertEqual(args[0], "测试文本")
        self.assertEqual(args[1], "zh-CN-XiaoxiaoNeural")
        self.assertIn("audio=out.mp3", buf.getvalue())

    def test_main_text_missing_paths(self):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = main(["--text", "测试文本"])
        self.assertEqual(rc, 2)
        self.assertIn("必须同时提供 --audio 与 --vtt", err_buf.getvalue())

    def test_main_project_not_found(self):
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = main(["/non_existent_project_dir_abc"])
        self.assertEqual(rc, 1)
        self.assertIn("加载解说稿失败", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
