#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_agnes_ppt_bridge.py
==============================
测试 agnes_ppt_bridge.py 的配置加载、模型过滤红线、图片尺寸探测、
清单解析自发现、Markdown 伴生渲染、交付门禁检查、批量生图状态回写与 CLI 异常处理。
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agnes_ppt_bridge import (
    BLOCKED_IMAGE_MODELS,
    candidate_models,
    check_manifest,
    load_gateway,
    main,
    probe_dimensions,
    render_md,
    resolve_manifest_path,
    run_manifest,
    save_image,
)


def make_png_bytes(width: int, height: int) -> bytes:
    """构造合法的 PNG 文件头字节。"""
    header = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 4 bytes length (13), 4 bytes "IHDR", 4 bytes width, 4 bytes height,
    # 5 bytes (bit depth, color type, compression, filter, interlace), 4 bytes CRC
    ihdr_data = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 2, 0, 0, 0])
    )
    ihdr_chunk = len(ihdr_data).to_bytes(4, "big") + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return header + ihdr_chunk


class TestGatewayConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_gateway_default_fallback(self):
        non_exist = self.tmp_dir / "no_key.json"
        base, key = load_gateway(non_exist)
        self.assertEqual(base, "http://127.0.0.1:3000/v1")
        self.assertEqual(key, "")

    def test_load_gateway_valid_config(self):
        cfg = self.tmp_dir / "key.json"
        cfg.write_text(
            json.dumps({"base_url": "http://api.local:8000/v1/", "api_key": "sk-123456"}),
            encoding="utf-8",
        )
        base, key = load_gateway(cfg)
        self.assertEqual(base, "http://api.local:8000/v1")
        self.assertEqual(key, "sk-123456")

    def test_load_gateway_corrupted_json(self):
        cfg = self.tmp_dir / "bad.json"
        cfg.write_text("not a json", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            base, key = load_gateway(cfg)
        self.assertEqual(base, "http://127.0.0.1:3000/v1")
        self.assertEqual(key, "")
        self.assertIn("[warn] 读取网关配置失败", buf.getvalue())


class TestModelResolution(unittest.TestCase):
    def test_candidate_models_default(self):
        models = candidate_models("16:9")
        self.assertIn("agnes-image-2.5-flash", models)
        self.assertIn("agnes-image-2.1-flash", models)
        self.assertEqual(models[0], "agnes-image-2.5-flash")

    def test_candidate_models_with_preferred(self):
        models = candidate_models("16:9", preferred="agnes-image-special")
        self.assertEqual(models[0], "agnes-image-special")
        self.assertIn("agnes-image-2.5-flash", models)

    def test_candidate_models_blocked_models(self):
        for blocked in BLOCKED_IMAGE_MODELS:
            buf = io.StringIO()
            with redirect_stdout(buf):
                models = candidate_models("16:9", preferred=f"my-{blocked}-v1")
            self.assertNotIn(f"my-{blocked}-v1", models)
            self.assertIn("[红线] 忽略被禁模型", buf.getvalue())


class TestProbeDimensionsAndSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_probe_dimensions_valid_png(self):
        png_path = self.tmp_dir / "test.png"
        png_path.write_bytes(make_png_bytes(1920, 1080))
        w, h = probe_dimensions(png_path)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    def test_probe_dimensions_str_path(self):
        png_path = self.tmp_dir / "test_str.png"
        png_path.write_bytes(make_png_bytes(1080, 1350))
        w, h = probe_dimensions(str(png_path))
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1350)

    def test_probe_dimensions_invalid_file(self):
        bad_path = self.tmp_dir / "bad.png"
        bad_path.write_bytes(b"not a png image header")
        w, h = probe_dimensions(bad_path)
        self.assertIsNone(w)
        self.assertIsNone(h)

    def test_probe_dimensions_non_existent(self):
        w, h = probe_dimensions(self.tmp_dir / "missing.png")
        self.assertIsNone(w)
        self.assertIsNone(h)

    def test_save_image(self):
        out_path = self.tmp_dir / "nested" / "dir" / "out.png"
        raw = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        saved = save_image({"bytes": raw}, out_path)
        self.assertEqual(saved, out_path)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.read_bytes(), raw)


class TestResolveManifestPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolve_direct_file(self):
        mf = self.tmp_dir / "image_prompts.json"
        mf.write_text("{}", encoding="utf-8")
        resolved = resolve_manifest_path(str(mf))
        self.assertEqual(resolved, mf.resolve())

    def test_resolve_project_dir_with_images_subdir(self):
        proj = self.tmp_dir / "proj1"
        img_dir = proj / "images"
        img_dir.mkdir(parents=True)
        mf = img_dir / "image_prompts.json"
        mf.write_text("{}", encoding="utf-8")
        resolved = resolve_manifest_path(str(proj))
        self.assertEqual(resolved, mf.resolve())

    def test_resolve_project_dir_with_root_manifest(self):
        proj = self.tmp_dir / "proj2"
        proj.mkdir(parents=True)
        mf = proj / "image_prompts.json"
        mf.write_text("{}", encoding="utf-8")
        resolved = resolve_manifest_path(str(proj))
        self.assertEqual(resolved, mf.resolve())

    def test_resolve_non_existent_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_manifest_path(str(self.tmp_dir / "non_existent"))

    def test_resolve_non_json_raises(self):
        txt = self.tmp_dir / "test.txt"
        txt.write_text("hello", encoding="utf-8")
        with self.assertRaises(ValueError):
            resolve_manifest_path(str(txt))

    def test_auto_discovery_from_base_dir(self):
        img_dir = self.tmp_dir / "images"
        img_dir.mkdir(parents=True)
        mf = img_dir / "image_prompts.json"
        mf.write_text("{}", encoding="utf-8")
        resolved = resolve_manifest_path(None, base_dir=self.tmp_dir)
        self.assertEqual(resolved, mf.resolve())

    def test_auto_discovery_from_projects_dir(self):
        base = self.tmp_dir / "repo"
        proj = base / "projects" / "my_project" / "images"
        proj.mkdir(parents=True)
        mf = proj / "image_prompts.json"
        mf.write_text("{}", encoding="utf-8")
        resolved = resolve_manifest_path(None, base_dir=base)
        self.assertEqual(resolved, mf.resolve())

    def test_auto_discovery_multiple_projects_raises_value_error(self):
        base = self.tmp_dir / "repo"
        for name in ("p1", "p2"):
            p = base / "projects" / name / "images"
            p.mkdir(parents=True)
            (p / "image_prompts.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            resolve_manifest_path(None, base_dir=base)
        self.assertIn("发现多个有效配图清单", str(ctx.exception))

    def test_auto_discovery_none_found_raises(self):
        base = self.tmp_dir / "empty_repo"
        base.mkdir()
        with self.assertRaises(FileNotFoundError):
            resolve_manifest_path(None, base_dir=base)


class TestRenderMarkdown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_md_success(self):
        mf_path = self.tmp_dir / "images" / "image_prompts.json"
        mf_path.parent.mkdir(parents=True)
        data = {
            "project": "test-project",
            "deck_rendering": "dark-minimal",
            "color_scheme": {"background": "#000", "accent": "#6E7BFF"},
            "items": [
                {
                    "filename": "cover.png",
                    "purpose": "封面底图",
                    "aspect_ratio": "16:9",
                    "status": "Generated",
                    "model": "agnes-image-2.5-flash",
                    "dimensions": "1920x1080",
                    "prompt": "Test prompt text",
                }
            ],
        }
        mf_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            out_md = render_md(mf_path)

        self.assertTrue(out_md.is_file())
        content = out_md.read_text(encoding="utf-8")
        self.assertIn("# test-project — 图片清单", content)
        self.assertIn("dark-minimal", content)
        self.assertIn("#6E7BFF", content)
        self.assertIn("cover.png", content)
        self.assertIn("1920x1080", content)
        self.assertIn("Test prompt text", content)

    def test_render_md_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            render_md(self.tmp_dir / "missing.json")

    def test_render_md_invalid_json_raises(self):
        bad_json = self.tmp_dir / "bad.json"
        bad_json.write_text("invalid json content", encoding="utf-8")
        with self.assertRaises(ValueError):
            render_md(bad_json)


class TestCheckManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.images_dir = self.tmp_dir / "images"
        self.images_dir.mkdir(parents=True)
        self.mf_path = self.images_dir / "image_prompts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_manifest_all_clear(self):
        img_file = self.images_dir / "cover.png"
        img_file.write_bytes(make_png_bytes(1920, 1080))
        data = {
            "project": "sample",
            "items": [
                {
                    "filename": "cover.png",
                    "status": "Generated",
                    "model": "agnes-image-2.5-flash",
                    "dimensions": "1920x1080",
                }
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            res = check_manifest(self.mf_path, verbose=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["generated"], 1)
        self.assertEqual(res["pending"], 0)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(len(res["missing_files"]), 0)
        self.assertIn("ALL CLEAR ✅", buf.getvalue())

    def test_check_manifest_pending_items(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "cover.png", "status": "Pending", "model": "agnes-image-2.5-flash"}
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            res = check_manifest(self.mf_path, verbose=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["pending"], 1)
        self.assertIn("门禁未通过", buf.getvalue())

    def test_check_manifest_failed_items(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "cover.png", "status": "Failed", "model": "agnes-image-2.5-flash"}
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        res = check_manifest(self.mf_path, verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed"], 1)

    def test_check_manifest_missing_disk_file(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "cover.png", "status": "Generated", "model": "agnes-image-2.5-flash"}
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        res = check_manifest(self.mf_path, verbose=False)
        self.assertFalse(res["ok"])
        self.assertIn("cover.png", res["missing_files"])

    def test_check_manifest_forbidden_model(self):
        img_file = self.images_dir / "cover.png"
        img_file.write_bytes(make_png_bytes(1920, 1080))
        data = {
            "project": "sample",
            "items": [
                {
                    "filename": "cover.png",
                    "status": "Generated",
                    "model": "gemini-3.1-flash-image",
                }
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        res = check_manifest(self.mf_path, verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["forbidden_models"]), 1)
        self.assertEqual(res["forbidden_models"][0][0], "cover.png")


class TestRunManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.images_dir = self.tmp_dir / "images"
        self.images_dir.mkdir(parents=True)
        self.mf_path = self.images_dir / "image_prompts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_manifest_success(self):
        data = {
            "project": "sample",
            "items": [
                {
                    "filename": "img1.png",
                    "status": "Pending",
                    "aspect_ratio": "16:9",
                    "prompt": "a glowing blue sphere",
                },
                {
                    "filename": "img2.png",
                    "status": "Generated",
                    "aspect_ratio": "16:9",
                    "prompt": "already generated",
                },
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        def fake_generate(prompt, ratio="16:9", model=None):
            return {
                "ok": True,
                "bytes": make_png_bytes(1920, 1080),
                "via": "agnes-image-2.5-flash",
                "cost_s": 1.2,
            }

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, generate_fn=fake_generate)

        self.assertEqual(ret, 0)
        self.assertTrue((self.images_dir / "img1.png").is_file())

        updated = json.loads(self.mf_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["items"][0]["status"], "Generated")
        self.assertEqual(updated["items"][0]["dimensions"], "1920x1080")
        self.assertEqual(updated["items"][0]["model"], "agnes-image-2.5-flash")

    def test_run_manifest_with_only_filter(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "img1.png", "status": "Pending", "prompt": "p1"},
                {"filename": "img2.png", "status": "Pending", "prompt": "p2"},
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        called_filenames = []

        def fake_generate(prompt, ratio="16:9", model=None):
            called_filenames.append(prompt)
            return {"ok": True, "bytes": make_png_bytes(100, 100), "via": "agnes", "cost_s": 0.1}

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, only=["img1.png"], generate_fn=fake_generate)

        self.assertEqual(ret, 0)
        self.assertEqual(called_filenames, ["p1"])
        updated = json.loads(self.mf_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["items"][0]["status"], "Generated")
        self.assertEqual(updated["items"][1]["status"], "Pending")

    def test_run_manifest_failure_recording(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "fail.png", "status": "Pending", "prompt": "error test"}
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        def fake_generate(prompt, ratio="16:9", model=None):
            return {"ok": False, "error": "upstream timeout"}

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, generate_fn=fake_generate)

        self.assertEqual(ret, 1)
        updated = json.loads(self.mf_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["items"][0]["status"], "Failed")
        self.assertEqual(updated["items"][0]["error"], "upstream timeout")

    def test_run_manifest_retry_failed_includes_pending_and_failed(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "pending.png", "status": "Pending", "prompt": "p"},
                {"filename": "failed.png", "status": "Failed", "prompt": "f", "error": "old"},
                {"filename": "done.png", "status": "Generated", "prompt": "d"},
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        called = []

        def fake_generate(prompt, ratio="16:9", model=None):
            called.append(prompt)
            return {"ok": True, "bytes": make_png_bytes(100, 100), "via": "agnes", "cost_s": 0.1}

        with redirect_stdout(io.StringIO()):
            ret = run_manifest(self.mf_path, retry_failed=True, generate_fn=fake_generate)

        self.assertEqual(ret, 0)
        self.assertEqual(called, ["p", "f"])
        updated = json.loads(self.mf_path.read_text(encoding="utf-8"))
        self.assertEqual([it["status"] for it in updated["items"]], ["Generated", "Generated", "Generated"])
        self.assertNotIn("error", updated["items"][1])

    def test_run_manifest_retry_failed_does_not_process_generated(self):
        data = {
            "project": "sample",
            "items": [{"filename": "done.png", "status": "Generated", "prompt": "done"}],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        called = []

        def fake_generate(prompt, ratio="16:9", model=None):
            called.append(prompt)
            return {"ok": True, "bytes": make_png_bytes(100, 100), "via": "agnes", "cost_s": 0.1}

        with redirect_stdout(io.StringIO()):
            ret = run_manifest(self.mf_path, retry_failed=True, generate_fn=fake_generate)

        self.assertEqual(ret, 0)
        self.assertEqual(called, [])

    def test_run_manifest_retry_failed_failure_updates_error(self):
        data = {
            "project": "sample",
            "items": [{"filename": "failed.png", "status": "Failed", "prompt": "retry", "error": "old"}],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")

        def fake_generate(prompt, ratio="16:9", model=None):
            return {"ok": False, "error": "new timeout"}

        with redirect_stdout(io.StringIO()):
            ret = run_manifest(self.mf_path, retry_failed=True, generate_fn=fake_generate)

        self.assertEqual(ret, 1)
        updated = json.loads(self.mf_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["items"][0]["status"], "Failed")
        self.assertEqual(updated["items"][0]["error"], "new timeout")

    def test_run_manifest_dry_run_selects_pending_only_without_side_effects(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "pending.png", "status": "Pending", "prompt": "p"},
                {"filename": "failed.png", "status": "Failed", "prompt": "f"},
                {"filename": "done.png", "status": "Generated", "prompt": "d"},
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        before = self.mf_path.stat().st_mtime_ns
        called = []

        def fake_generate(prompt, ratio="16:9", model=None):
            called.append(prompt)
            return {"ok": True, "bytes": make_png_bytes(100, 100), "via": "agnes", "cost_s": 0.1}

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, dry_run=True, generate_fn=fake_generate)

        self.assertEqual(ret, 0)
        self.assertEqual(called, [])
        self.assertEqual(self.mf_path.read_text(encoding="utf-8"), json.dumps(data))
        self.assertEqual(self.mf_path.stat().st_mtime_ns, before)
        self.assertIn("pending.png", buf.getvalue())
        self.assertNotIn("failed.png", buf.getvalue())
        self.assertNotIn("done.png", buf.getvalue())

    def test_run_manifest_dry_run_retry_failed_and_only_intersection(self):
        data = {
            "project": "sample",
            "items": [
                {"filename": "pending.png", "status": "Pending"},
                {"filename": "failed.png", "status": "Failed"},
                {"filename": "done.png", "status": "Generated"},
            ],
        }
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, only=["failed.png"], retry_failed=True, dry_run=True)
        self.assertEqual(ret, 0)
        self.assertIn("failed.png", buf.getvalue())
        self.assertNotIn("pending.png", buf.getvalue())
        self.assertNotIn("done.png", buf.getvalue())

    def test_run_manifest_dry_run_force_selects_generated(self):
        data = {"project": "sample", "items": [{"filename": "done.png", "status": "Generated"}]}
        self.mf_path.write_text(json.dumps(data), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = run_manifest(self.mf_path, force=True, dry_run=True)
        self.assertEqual(ret, 0)
        self.assertIn("done.png", buf.getvalue())


class TestCLI(unittest.TestCase):
    def test_cli_help(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", buf.getvalue())

    def test_cli_check_repo_manifest(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--check"])
        self.assertEqual(code, 0)
        self.assertIn("ALL CLEAR ✅", buf.getvalue())

    def test_cli_status_repo_manifest(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--status"])
        self.assertEqual(code, 0)
        self.assertIn("ALL CLEAR ✅", buf.getvalue())

    def test_cli_prompt_missing_args(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--prompt", "test prompt without filename"])
        self.assertEqual(code, 2)
        self.assertIn("单张模式需同时给", buf.getvalue())

    def test_cli_invalid_path(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["/non_existent_12345/image_prompts.json", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("[err]", buf.getvalue())

    def test_cli_retry_failed_passes_through(self):
        with mock.patch("scripts.agnes_ppt_bridge.resolve_manifest_path") as resolve, \
                mock.patch("scripts.agnes_ppt_bridge.run_manifest", return_value=0) as run:
            resolve.return_value = Path("/tmp/manifest.json")
            code = main(["/tmp/manifest.json", "--retry-failed", "--only", "failed.png"])
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            Path("/tmp/manifest.json"),
            only=["failed.png"],
            force=False,
            retry_failed=True,
            dry_run=False,
        )

    def test_cli_dry_run_rejects_check_conflict(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--dry-run", "--check"])
        self.assertEqual(code, 2)
        self.assertIn("--dry-run 只能与", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
