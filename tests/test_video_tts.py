import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.video_tts import (
    VOICE_MAP,
    generate_tts,
    load_voiceover,
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


if __name__ == "__main__":
    unittest.main()
