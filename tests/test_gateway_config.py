#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_gateway_config.py -- gateway_config.py 单元测试"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gateway_config import DEFAULT_BASE, DEFAULT_KEY_PATH, main, resolve_gateway


class TestGatewayConfig(unittest.TestCase):
    def test_default_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            base, key = resolve_gateway(
                env_base_var="TEST_BASE",
                env_key_var="TEST_KEY",
                default_path="/non_existent_path_12345/local_key.json",
            )
            self.assertEqual(base, DEFAULT_BASE)
            self.assertEqual(key, "")

    def test_env_var_takes_precedence_over_default_path(self):
        with tempfile.TemporaryDirectory() as td:
            default_file = Path(td) / "local_key.json"
            default_file.write_text(
                json.dumps({
                    "base_url": "http://from-file.local/v1",
                    "api_key": "file-secret-key",
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "TEST_BASE": "http://from-env.local/v1",
                "TEST_KEY": "env-secret-key",
            }, clear=True):
                base, key = resolve_gateway(
                    env_base_var="TEST_BASE",
                    env_key_var="TEST_KEY",
                    default_path=default_file,
                )
                self.assertEqual(base, "http://from-env.local/v1")
                self.assertEqual(key, "env-secret-key")

    def test_default_path_used_when_env_empty(self):
        with tempfile.TemporaryDirectory() as td:
            default_file = Path(td) / "local_key.json"
            default_file.write_text(
                json.dumps({
                    "image_base_url": "http://from-file-image.local/v1",
                    "api_key": "file-secret-key",
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                base, key = resolve_gateway(
                    env_base_var="TEST_BASE",
                    env_key_var="TEST_KEY",
                    default_path=default_file,
                )
                self.assertEqual(base, "http://from-file-image.local/v1")
                self.assertEqual(key, "file-secret-key")

    def test_explicit_config_path_takes_precedence_over_env(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "custom_key.json"
            cfg_file.write_text(
                json.dumps({
                    "base_url": "http://custom-file.local/v1",
                    "api_key": "custom-secret-key",
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "TEST_BASE": "http://from-env.local/v1",
                "TEST_KEY": "env-secret-key",
            }, clear=True):
                base, key = resolve_gateway(
                    env_base_var="TEST_BASE",
                    env_key_var="TEST_KEY",
                    config_path=cfg_file,
                )
                self.assertEqual(base, "http://custom-file.local/v1")
                self.assertEqual(key, "custom-secret-key")

    def test_relative_config_path_with_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            cfg_file = base_dir / "keys" / "custom.json"
            cfg_file.parent.mkdir(parents=True)
            cfg_file.write_text(
                json.dumps({
                    "base_url": "http://base-dir-file.local/v1",
                    "api_key": "base-dir-key",
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                base, key = resolve_gateway(
                    env_base_var="TEST_BASE",
                    env_key_var="TEST_KEY",
                    config_path="keys/custom.json",
                    base_dir=base_dir,
                )
                self.assertEqual(base, "http://base-dir-file.local/v1")
                self.assertEqual(key, "base-dir-key")

    def test_broken_json_handled_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            broken_file = Path(td) / "broken.json"
            broken_file.write_text("invalid json {", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    base, key = resolve_gateway(
                        env_base_var="TEST_BASE",
                        env_key_var="TEST_KEY",
                        config_path=broken_file,
                    )
                self.assertEqual(base, DEFAULT_BASE)
                self.assertEqual(key, "")


class TestGatewayConfigMain(unittest.TestCase):
    def test_main_default(self):
        with patch.dict(os.environ, {}, clear=True):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([])
            self.assertEqual(rc, 0)
            self.assertIn("base_url=", buf.getvalue())

    def test_main_json(self):
        with patch.dict(os.environ, {"AGNES_IMAGE_API_KEY": "sk-1234567890abcdef"}, clear=True):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["has_key"])
            self.assertTrue(data["masked_key"].startswith("sk-"))

    def test_main_with_config_and_base_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            cfg_file = base_dir / "my_cfg.json"
            cfg_file.write_text(
                json.dumps({
                    "image_base_url": "http://my-cli.local/v1",
                    "api_key": "my-secret-key-123",
                }),
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--config", "my_cfg.json", "--base-dir", str(base_dir), "--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["base_url"], "http://my-cli.local/v1")
            self.assertTrue(data["has_key"])


if __name__ == "__main__":
    unittest.main()
