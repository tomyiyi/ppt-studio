#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prepare_agnes_image.py
=================================
测试 prepare_agnes_image.py 的接缝检测、平滑对齐、尺寸裁切、亮度调整与 CLI 异常处理。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

# 将项目根目录加入 sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 确保能加载项目内 .venv site-packages 中的 numpy 与 PIL
for site_pkg in REPO_ROOT.glob(".venv/lib/python*/site-packages"):
    if site_pkg.is_dir() and str(site_pkg) not in sys.path:
        sys.path.insert(0, str(site_pkg))

PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
if not PYTHON_BIN.exists():
    PYTHON_BIN = Path(sys.executable)
SCRIPT_PATH = REPO_ROOT / "scripts" / "prepare_agnes_image.py"

import numpy as np
from PIL import Image

from scripts.prepare_agnes_image import (
    parse_size,
    detect_seam,
    fix_seam,
    remove_seam,
    prepare,
    resolve_image_targets,
    resolve_manifest_target,
    parse_postprocess_cmd,
    check_images,
    run_qa_prepared_images,
    qa_prepared_images,
    qa_single_prepared_image,
    run_qa_single_prepared_image,
    prepare_agnes_images,
    prepare_images,
    BatchResult,
    SCHEMA_VERSION,
    COMMON_SCHEMA_KEYS,
    PREPARE_SCHEMA_KEYS,
    CHECK_SCHEMA_KEYS,
    FAILURE_ITEM_KEYS,
    main,
)
from scripts.boost_ink import boost_image


def create_test_image(
    path: Path,
    width: int = 100,
    height: int = 80,
    mode: str = "RGB",
    left_val: int = 20,
    right_val: int = 60,
    seam_x: int | None = None,
) -> None:
    """创建合成图像，可指定竖向接缝位置及两侧亮度。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "RGB":
        arr = np.full((height, width, 3), left_val, dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:] = right_val
        im = Image.fromarray(arr, "RGB")
    elif mode == "RGBA":
        arr = np.full((height, width, 4), [left_val, left_val, left_val, 255], dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:, :3] = right_val
        im = Image.fromarray(arr, "RGBA")
    elif mode == "L":
        arr = np.full((height, width), left_val, dtype=np.uint8)
        if seam_x is not None and 0 < seam_x < width:
            arr[:, seam_x:] = right_val
        im = Image.fromarray(arr, "L")
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    im.save(path, "PNG")


# ==============================================================================
# 极小独立 JSON v1 Consumer / Parser
# 与 BatchResult、SCHEMA_VERSION、脚本内部 Schema 常量完全解耦，
# 仅依据公开 JSON v1 契约进行反序列化、格式验证与字段读取。
# ==============================================================================


class V1ConsumerError(ValueError):
    """JSON v1 独立消费者契约违规异常。"""

    pass


@dataclass
class V1ConsumerFailure:
    """JSON v1 失败明细项独立消费模型。"""

    file: str
    name: str
    code: str
    reason: str
    extra: dict = field(default_factory=dict)

    def __getitem__(self, key: str):
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra[key]

    def get(self, key: str, default=None):
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra.get(key, default)


@dataclass
class V1ConsumerResult:
    """JSON v1 独立消费根结果模型。"""

    schema_version: int
    ok: bool
    total: int
    success_count: int
    failure_count: int
    failures: list[V1ConsumerFailure]
    items: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def __getitem__(self, key: str):
        if hasattr(self, key):
            return getattr(self, key)
        return self.raw[key]

    def get(self, key: str, default=None):
        if hasattr(self, key):
            return getattr(self, key)
        return self.raw.get(key, default)


def parse_v1_json(raw: str | bytes | dict) -> V1ConsumerResult:
    """解析并校验 JSON v1 输出。

    独立消费者规则：
    1. 根对象必须为合法 JSON 字典；
    2. schema_version 必须严格为整型 1 (非 1、字符串或 bool 均明确拒绝)；
    3. 必需基础字段包含 ok(bool), total(int>=0), success_count(int>=0), failure_count(int>=0), failures(list)；
    4. failures[] 列表项中每个元素必须包含 file(str), name(str), code(str), reason(str)；
    5. 未知额外字段（例如 reports, unreadable, partial_success, 自定义扩展字段）完全容忍并保留；
    6. 缺失必需字段或基础类型错误均明确拒绝 (抛出 V1ConsumerError)。
    """
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except Exception as e:
            raise V1ConsumerError(f"无效的 JSON 数据: {e}") from e
    elif isinstance(raw, dict):
        data = raw
    else:
        raise V1ConsumerError(f"预期输入 str, bytes 或 dict，实际收到 {type(raw).__name__}")

    if not isinstance(data, dict):
        raise V1ConsumerError(f"根节点必须为 JSON 对象 (dict)，实际为 {type(data).__name__}")

    # 1. 严格检查 schema_version == 1
    if "schema_version" not in data:
        raise V1ConsumerError("缺少必需字段: 'schema_version'")
    sv = data["schema_version"]
    if type(sv) is not int or isinstance(sv, bool):
        raise V1ConsumerError(f"schema_version 必须为严格整型，实际为 {type(sv).__name__}")
    if sv != 1:
        raise V1ConsumerError(f"不支持的 schema_version: {sv} (当前独立消费者仅支持 v1)")

    # 2. 检查根节点必需字段存在性
    required_root = ("ok", "total", "success_count", "failure_count", "failures")
    for req in required_root:
        if req not in data:
            raise V1ConsumerError(f"缺少必需字段: '{req}'")

    # 3. 基础类型与计数严格校验
    if type(data["ok"]) is not bool:
        raise V1ConsumerError(f"'ok' 必须为 bool 类型，实际为 {type(data['ok']).__name__}")

    for count_key in ("total", "success_count", "failure_count"):
        val = data[count_key]
        if type(val) is not int or isinstance(val, bool):
            raise V1ConsumerError(f"'{count_key}' 必须为严格整型，实际为 {type(val).__name__}")
        if val < 0:
            raise V1ConsumerError(f"'{count_key}' 不能为负数，实际为 {val}")

    if not isinstance(data["failures"], list):
        raise V1ConsumerError(f"'failures' 必须为列表，实际为 {type(data['failures']).__name__}")

    # 4. 解析与校验 failures[] 项
    parsed_failures: list[V1ConsumerFailure] = []
    failure_req_fields = ("file", "name", "code", "reason")
    for i, item in enumerate(data["failures"]):
        if not isinstance(item, dict):
            raise V1ConsumerError(f"failures[{i}] 必须为字典对象，实际为 {type(item).__name__}")
        for fkey in failure_req_fields:
            if fkey not in item:
                raise V1ConsumerError(f"failures[{i}] 缺失必需字段: '{fkey}'")
            if type(item[fkey]) is not str:
                raise V1ConsumerError(f"failures[{i}].{fkey} 必须为 str，实际为 {type(item[fkey]).__name__}")
        extra_fields = {k: v for k, v in item.items() if k not in failure_req_fields}
        parsed_failures.append(
            V1ConsumerFailure(
                file=item["file"],
                name=item["name"],
                code=item["code"],
                reason=item["reason"],
                extra=extra_fields,
            )
        )

    # 5. 可选 items 字段处理（若存在需为 list）
    items_list = data.get("items", [])
    if items_list is not None and not isinstance(items_list, list):
        raise V1ConsumerError(f"'items' 若存在必须为列表，实际为 {type(items_list).__name__}")

    return V1ConsumerResult(
        schema_version=sv,
        ok=data["ok"],
        total=data["total"],
        success_count=data["success_count"],
        failure_count=data["failure_count"],
        failures=parsed_failures,
        items=items_list if isinstance(items_list, list) else [],
        raw=dict(data),
    )


class TestParseSize(unittest.TestCase):
    def test_valid_sizes(self):
        self.assertEqual(parse_size("2560x1440"), (2560, 1440))
        self.assertEqual(parse_size("1920X1080"), (1920, 1080))
        self.assertEqual(parse_size(" 1280 x 720 "), (1280, 720))

    def test_invalid_formats(self):
        invalid_inputs = [
            "2560",
            "2560_1440",
            "100x200x300",
            "axb",
            "100x",
            "x100",
            "-10x100",
            "100x-50",
            "0x100",
            "100x0",
        ]
        for val in invalid_inputs:
            with self.subTest(val=val):
                with self.assertRaises(ValueError):
                    parse_size(val)


class TestDetectSeam(unittest.TestCase):
    def test_uniform_image_has_no_seam(self):
        arr = np.full((80, 100, 3), 30, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))

    def test_narrow_image_returns_none(self):
        arr = np.full((50, 30, 3), 30, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))

    def test_detect_significant_vertical_seam(self):
        # 宽 100 高 80，在 x=50 处存在由 20 到 60 的竖向突变台阶
        arr = np.full((80, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "RGB")
        col = detect_seam(im)
        self.assertIsNotNone(col)
        self.assertIn(col, (49, 50, 51))

    def test_weak_step_ignored(self):
        # 突变幅度 2.0 < min_step(6.0)
        arr = np.full((80, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 22
        im = Image.fromarray(arr, "RGB")
        self.assertIsNone(detect_seam(im))


class TestFixSeam(unittest.TestCase):
    def test_fix_seam_rgb(self):
        arr = np.full((50, 100, 3), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "RGB")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        # 修复后，左侧与右侧均值应基本对齐
        left_m = fixed_arr[:, :50].mean()
        right_m = fixed_arr[:, 50:].mean()
        self.assertAlmostEqual(left_m, right_m, delta=1.0)

    def test_fix_seam_grayscale(self):
        arr = np.full((50, 100), 20, dtype=np.uint8)
        arr[:, 50:] = 60
        im = Image.fromarray(arr, "L")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        left_m = fixed_arr[:, :50].mean()
        right_m = fixed_arr[:, 50:].mean()
        self.assertAlmostEqual(left_m, right_m, delta=1.0)

    def test_fix_seam_rgba_preserves_alpha(self):
        arr = np.full((50, 100, 4), [20, 20, 20, 200], dtype=np.uint8)
        arr[:, 50:, :3] = 60
        im = Image.fromarray(arr, "RGBA")
        fixed = fix_seam(im, 50)
        fixed_arr = np.asarray(fixed)
        self.assertEqual(fixed_arr.shape[2], 4)
        # alpha 通道应保持 200 不变
        self.assertEqual(fixed_arr[:, :, 3].min(), 200)
        self.assertEqual(fixed_arr[:, :, 3].max(), 200)

    def test_fix_seam_out_of_bounds_clip(self):
        arr = np.full((50, 100, 3), 20, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        # 不会因超界报错，会被 clip
        fixed = fix_seam(im, -10)
        self.assertEqual(fixed.size, (100, 50))
        fixed2 = fix_seam(im, 200)
        self.assertEqual(fixed2.size, (100, 50))

    @staticmethod
    def _seam_step(im: Image.Image, x: int) -> float:
        """x 处接缝残差：逐行取左右 5 列均值差的中位数（左窗钳制在边界内）。"""
        g = np.asarray(im.convert("L"), dtype=np.float32)
        lo = max(0, x - 5)
        per_row = g[:, x:x + 5].mean(axis=1) - g[:, lo:x].mean(axis=1)
        return float(np.median(np.abs(per_row)))

    def test_fix_seam_asymmetric_content(self):
        """第 32 轮回归：内容左右不对称时，补偿量不能被内容带偏。

        旧实现取整图左右半区均值差——右侧亮色块会把 delta 带偏，
        修复后跳变反而放大（实测 8.4 → 62.1）。正确估计量是
        detect_seam 的检测口径本身：全行列均值曲线在 x 处的跳变，
        内容噪声被 H 行平均掉，只剩系统性台阶。
        """
        arr = np.full((60, 100, 3), 100, dtype=np.uint8)
        arr[:, 50:] += 30  # 接缝：x=50 处 +30 台阶（贯穿全高）
        arr[10:40, 70:90] = 200  # 非对称内容：只在右侧的亮色块
        im = Image.fromarray(arr, "RGB")
        before = self._seam_step(im, 50)
        self.assertGreater(before, 20)  # 确认合成图确有接缝
        fixed = fix_seam(im, 50)
        after = self._seam_step(fixed, 50)
        self.assertLess(after, 3.0, f"接缝未抹平，残差={after}")
        # 亮色块内容不受影响（仍在原位、仍亮）
        farr = np.asarray(fixed.convert("L"))
        self.assertGreater(farr[10:40, 70:90].mean(), 180)

    def test_fix_seam_band_clamped_near_edge(self):
        """x 贴边时采样带宽钳制在边界内，不报错。"""
        arr = np.full((40, 100, 3), 50, dtype=np.uint8)
        arr[:, 3:] = 80
        im = Image.fromarray(arr, "RGB")
        fixed = fix_seam(im, 3, band=24)  # 左侧只有 3 列可用
        self.assertEqual(fixed.size, (100, 40))
        self.assertLess(self._seam_step(fixed, 3), 3.0)


class TestRemoveSeam(unittest.TestCase):
    """第 32 轮：缓坡型接缝必须迭代 nibble，不能单次硬阶跃了事。"""

    @staticmethod
    def _boosted_detect(im: Image.Image):
        boosted, *_ = boost_image(im)
        return detect_seam(boosted)

    def test_remove_seam_hard_step_single_iter(self):
        """硬台阶：一次迭代精确清零。"""
        arr = np.full((60, 100, 3), 100, dtype=np.uint8)
        arr[:, 50:] = 140
        im = Image.fromarray(arr, "RGB")
        self.assertIsNotNone(self._boosted_detect(im))
        fixed, cols, converged = remove_seam(im)
        self.assertTrue(converged)
        self.assertEqual(cols, [50])
        self.assertIsNone(self._boosted_detect(fixed))

    def test_remove_seam_ramp(self):
        """缓坡（4 列宽、每列 +10）：迭代 nibble 直到无检出。

        这是 05_essentials_bg 的合成复刻——单次 fix_seam(band=1) 只能
        清掉峰值列，修完一处又冒出一处。
        """
        arr = np.full((60, 100, 3), 100, dtype=np.uint8)
        for i, add in enumerate((10, 20, 30, 40)):
            arr[:, 48 + i] = np.clip(
                arr[:, 48 + i].astype(np.int16) + add, 0, 255)
        im = Image.fromarray(arr, "RGB")
        self.assertIsNotNone(self._boosted_detect(im))
        fixed, cols, converged = remove_seam(im)
        self.assertTrue(converged, f"未收敛，已修列={cols}")
        self.assertGreater(len(cols), 1, "缓坡应触发多次迭代")
        self.assertTrue(all(abs(c - 50) <= 4 for c in cols))
        self.assertIsNone(self._boosted_detect(fixed))

    def test_remove_seam_no_seam(self):
        """无接缝：原样返回，不碰图像。"""
        arr = np.full((60, 100, 3), 100, dtype=np.uint8)
        im = Image.fromarray(arr, "RGB")
        fixed, cols, converged = remove_seam(im)
        self.assertTrue(converged)
        self.assertEqual(cols, [])
        self.assertTrue(np.array_equal(np.asarray(fixed), arr))

    def test_remove_seam_explicit_x(self):
        """显式给 x：只修该条接缝附近。"""
        arr = np.full((60, 100, 3), 100, dtype=np.uint8)
        arr[:, 50:] = 140
        im = Image.fromarray(arr, "RGB")
        fixed, cols, converged = remove_seam(im, x=50)
        self.assertTrue(converged)
        self.assertEqual(cols, [50])
        self.assertIsNone(self._boosted_detect(fixed))

    def test_no_circular_import_degradation(self):
        """第 32 轮回归：top-level 导入 prepare_agnes_image 再导入 boost_ink，
        不能因循环导入把 boost_ink.detect_seam 静默置为 None
        （否则 QA 门禁的接缝检查被静默跳过——此前 /tmp 实验脚本
        正是因此漏检了 777 接缝）。子进程隔离，复刻当时的导入顺序。"""
        scripts_dir = str(REPO_ROOT / "scripts")
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from prepare_agnes_image import remove_seam;"
            "import boost_ink;"
            "assert boost_ink.detect_seam is not None,"
            " 'detect_seam 被循环导入静默置为 None';"
            "print('CIRCULAR_IMPORT_OK')"
        ) % scripts_dir
        r = subprocess.run(
            [str(PYTHON_BIN), "-c", code],
            capture_output=True, text=True, timeout=180,
        )
        self.assertIn(
            "CIRCULAR_IMPORT_OK", r.stdout,
            f"循环导入导致静默降级，stderr={r.stderr[-800:]}",
        )


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.raw_path = self.dir_path / "raw.png"
        self.out_path = self.dir_path / "out.png"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_missing_raw_file_raises_not_found(self):
        with self.assertRaises(FileNotFoundError):
            prepare(self.dir_path / "not_found.png", self.out_path)

    def test_invalid_size_raises_value_error(self):
        create_test_image(self.raw_path)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, size=(0, 100))
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, size=(-10, 100))

    def test_invalid_brightness_raises_value_error(self):
        create_test_image(self.raw_path)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, brightness=-0.5)

    def test_normal_resize_and_crop(self):
        # 尺寸 200x120 -> 目标 160x90
        create_test_image(self.raw_path, width=200, height=120)
        rep = prepare(self.raw_path, self.out_path, size=(160, 90), brightness=1.0, seam="off")
        self.assertTrue(self.out_path.exists())
        self.assertEqual(rep["src"], "200x120")
        self.assertEqual(rep["out"], "160x90")
        self.assertFalse(rep["fixed"])
        with Image.open(self.out_path) as out_im:
            self.assertEqual(out_im.size, (160, 90))

    def test_auto_seam_detection_and_fix(self):
        # 制作含接缝的图片 (x=60)
        create_test_image(self.raw_path, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        rep = prepare(self.raw_path, self.out_path, size=(120, 80), seam="auto")
        self.assertTrue(rep["fixed"])
        self.assertIsNotNone(rep["seam"])

    def test_manual_seam_columns(self):
        create_test_image(self.raw_path, width=120, height=80, left_val=20, right_val=60)
        # 单列
        rep1 = prepare(self.raw_path, self.out_path, size=(120, 80), seam="50")
        self.assertTrue(rep1["fixed"])
        self.assertEqual(rep1["seam"], 50)

        # 多列
        rep2 = prepare(self.raw_path, self.out_path, size=(120, 80), seam="40, 70")
        self.assertTrue(rep2["fixed"])
        self.assertEqual(rep2["seam"], [40, 70])

    def test_invalid_seam_specification(self):
        create_test_image(self.raw_path, width=100, height=60)
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, seam="invalid_col")
        with self.assertRaises(ValueError):
            prepare(self.raw_path, self.out_path, seam="999")  # 999 >= width=100

    def test_brightness_adjustment(self):
        create_test_image(self.raw_path, width=100, height=60, left_val=50, right_val=50)
        prepare(self.raw_path, self.out_path, size=(100, 60), brightness=1.5, seam="off")
        with Image.open(self.out_path) as im_bright:
            mean_bright = np.asarray(im_bright).mean()

        out_dark = self.dir_path / "dark.png"
        prepare(self.raw_path, out_dark, size=(100, 60), brightness=0.5, seam="off")
        with Image.open(out_dark) as im_dark:
            mean_dark = np.asarray(im_dark).mean()

        self.assertGreater(mean_bright, mean_dark)


class TestMainCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.raw_path = self.dir_path / "raw.png"
        self.out_path = self.dir_path / "out.png"
        create_test_image(self.raw_path, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_success(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertTrue(self.out_path.exists())
        self.assertIn("120x80 → 100x60", buf.getvalue())

    def test_cli_missing_raw_file(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.dir_path / "no_such.png"), str(self.out_path)])
        self.assertEqual(ret, 1)
        self.assertIn("源图片文件不存在", buf.getvalue())

    def test_cli_invalid_size(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--size", "invalid_size"])
        self.assertEqual(ret, 1)
        self.assertIn("尺寸格式无效", buf.getvalue())

    def test_cli_invalid_brightness(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--brightness", "-1"])
        self.assertEqual(ret, 1)
        self.assertIn("亮度系数必须 >= 0", buf.getvalue())

    def test_cli_invalid_seam(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            ret = main([str(self.raw_path), str(self.out_path), "--seam", "bad_col"])
        self.assertEqual(ret, 1)
        self.assertIn("无效的接缝列号", buf.getvalue())

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(io.StringIO()):
                main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_single_raw_dry_run(self):
        buf = io.StringIO()
        orig_mtime = self.raw_path.stat().st_mtime
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertIn("[预演]", buf.getvalue())
        self.assertIn("加 --apply 执行写盘", buf.getvalue())
        # 文件未被修改
        self.assertEqual(self.raw_path.stat().st_mtime, orig_mtime)

    def test_cli_single_raw_apply_with_backup(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--apply", "--size", "100x60"])
        self.assertEqual(ret, 0)
        self.assertIn("(已写盘)", buf.getvalue())
        # 验证备份存在
        bak = self.raw_path.parent / f"_pre_{self.raw_path.name}"
        self.assertTrue(bak.exists())
        with Image.open(self.raw_path) as im:
            self.assertEqual(im.size, (100, 60))

    def test_cli_single_raw_apply_no_backup(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--apply", "--no-backup", "--size", "90x50"])
        self.assertEqual(ret, 0)
        with Image.open(self.raw_path) as im:
            self.assertEqual(im.size, (90, 50))

    def test_cli_check_success(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--check"])
        self.assertEqual(ret, 0)
        self.assertIn("ALL CLEAR ✅", buf.getvalue())

    def test_cli_check_failure_on_seam(self):
        seam_img = self.dir_path / "seam_img.png"
        create_test_image(seam_img, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(seam_img), "--check"])
        self.assertEqual(ret, 1)
        self.assertIn("门禁未通过", buf.getvalue())
        self.assertIn("seam_img.png", buf.getvalue())

    def test_cli_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main([str(self.raw_path), "--json"])
        self.assertEqual(ret, 0)
        import json
        out_data = json.loads(buf.getvalue().strip())
        self.assertIsInstance(out_data, dict)
        self.assertEqual(out_data["total"], 1)
        self.assertEqual(out_data["success_count"], 1)
        self.assertEqual(out_data["failure_count"], 0)
        self.assertFalse(out_data["partial_success"])
        self.assertEqual(out_data["failures"], [])
        self.assertEqual(out_data["items"][0]["name"], self.raw_path.name)


class TestTargetResolutionAndManifest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img_dir = self.dir_path / "images"
        self.img_dir.mkdir(parents=True)
        self.p1 = self.img_dir / "p1.png"
        self.p2 = self.img_dir / "p2.png"
        create_test_image(self.p1, width=120, height=80)
        create_test_image(self.p2, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_image_targets_directory(self):
        targets = resolve_image_targets(self.dir_path)
        self.assertEqual(len(targets), 2)
        self.assertEqual([t.name for t in targets], ["p1.png", "p2.png"])

    def test_resolve_image_targets_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            resolve_image_targets(self.dir_path / "not_exist")

    def test_parse_postprocess_cmd(self):
        cmd = "prepare_agnes_image.py --size 1308x736 --brightness 0.88 --seam auto"
        cfg = parse_postprocess_cmd(cmd)
        self.assertEqual(cfg["size"], (1308, 736))
        self.assertEqual(cfg["brightness"], 0.88)
        self.assertEqual(cfg["seam"], "auto")

    def test_resolve_manifest_target_and_execution(self):
        manifest_path = self.img_dir / "image_prompts.json"
        import json
        manifest_data = {
            "project": "test-proj",
            "items": [
                {
                    "filename": "p1.png",
                    "postprocess": "prepare_agnes_image.py --size 100x50 --brightness 0.9 --seam auto",
                },
                {
                    "filename": "p2.png",
                    "postprocess": "prepare_agnes_image.py --size 120x60 --brightness 1.1 --seam auto",
                },
            ],
        }
        manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False), encoding="utf-8")

        resolved_mf = resolve_manifest_target(self.dir_path)
        self.assertEqual(resolved_mf.resolve(), manifest_path.resolve())

        # 运行 CLI manifest 预演
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(["--manifest", str(manifest_path)])
        self.assertEqual(ret, 0)
        self.assertIn("100x50", buf.getvalue())
        self.assertIn("120x60", buf.getvalue())

        # 运行 CLI manifest --apply
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            ret2 = main(["--manifest", str(manifest_path), "--apply"])
        self.assertEqual(ret2, 0)
        with Image.open(self.p1) as im1:
            self.assertEqual(im1.size, (100, 50))
        with Image.open(self.p2) as im2:
            self.assertEqual(im2.size, (120, 60))


class TestCheckImagesGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.clean_img = self.dir_path / "clean.png"
        create_test_image(self.clean_img, width=120, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_images_clean(self):
        res = check_images([self.clean_img], size=(120, 80), verbose=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["failed_seams"]), 0)

    def test_check_images_detects_seam(self):
        seam_img = self.dir_path / "seam.png"
        create_test_image(seam_img, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        res = check_images([seam_img], verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["failed_seams"]), 1)

    def test_check_images_detects_dimension_mismatch(self):
        res = check_images([self.clean_img], size=(200, 100), verbose=False)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["dimension_mismatches"]), 1)

    def test_check_images_flexible_inputs(self):
        # 单个 Path
        res_path = check_images(self.clean_img, size=(120, 80), verbose=False)
        self.assertTrue(res_path["ok"])

        # 字符串形式路径
        res_str = check_images(str(self.clean_img), size=(120, 80), verbose=False)
        self.assertTrue(res_str["ok"])

        # 目录路径
        res_dir = check_images(self.dir_path, size=(120, 80), verbose=False)
        self.assertTrue(res_dir["ok"])

        # 缺失或非法目标（优雅失败）
        res_missing = check_images(self.dir_path / "not_existing.png", verbose=False)
        self.assertFalse(res_missing["ok"])
        self.assertTrue(len(res_missing["unreadable"]) > 0)

    def test_run_qa_prepared_images_and_aliases(self):
        self.assertTrue(run_qa_prepared_images(self.clean_img, size=(120, 80), verbose=False))
        self.assertFalse(run_qa_prepared_images(self.clean_img, size=(999, 999), verbose=False))

        # 别名验证
        self.assertIs(qa_prepared_images, run_qa_prepared_images)
        self.assertIs(qa_single_prepared_image, check_images)
        self.assertIs(run_qa_single_prepared_image, check_images)

    def test_cli_quiet_and_verbose_flags(self):
        # --quiet
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code_q = main([str(self.clean_img), "--check", "--quiet"])
        self.assertEqual(code_q, 0)
        self.assertEqual(buf_out.getvalue(), "")
        self.assertEqual(buf_err.getvalue(), "")

        # --verbose
        buf_v = io.StringIO()
        with redirect_stdout(buf_v):
            code_v = main([str(self.clean_img), "--check", "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertIn("[门禁] ✓ 配图客观后处理门禁通过", buf_v.getvalue())


class TestPrepareAgnesImagesAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, width=100, height=80)
        create_test_image(self.img2, width=100, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_agnes_images_dry_run(self):
        reports = prepare_agnes_images(self.dir_path, size=(60, 40), apply=False)
        self.assertTrue(reports["ok"])
        self.assertEqual(reports["total"], 2)
        self.assertEqual(reports["success_count"], 2)
        self.assertEqual(reports["failure_count"], 0)
        self.assertFalse(reports["partial_success"])
        self.assertEqual(len(reports["items"]), 2)
        self.assertFalse(reports["items"][0]["applied"])
        self.assertFalse(reports[0]["applied"])
        # 原图尺寸不变
        with Image.open(self.img1) as im:
            self.assertEqual(im.size, (100, 80))

    def test_prepare_agnes_images_apply_mode(self):
        reports = prepare_agnes_images(
            self.dir_path,
            size="60x40",
            apply=True,
            no_backup=False,
            check=True,
        )
        self.assertTrue(reports["ok"])
        self.assertEqual(reports["total"], 2)
        self.assertEqual(reports["success_count"], 2)
        self.assertEqual(reports["failure_count"], 0)
        self.assertFalse(reports["partial_success"])
        self.assertEqual(len(reports["items"]), 2)
        self.assertTrue(reports["items"][0]["applied"])
        self.assertTrue(reports[0]["applied"])
        # 验证已裁切
        with Image.open(self.img1) as im:
            self.assertEqual(im.size, (60, 40))
        # 验证备份存在
        bak = self.dir_path / f"_pre_{self.img1.name}"
        self.assertTrue(bak.exists())

    def test_prepare_agnes_images_check_failure(self):
        seam_img = self.dir_path / "seam_bad.png"
        create_test_image(seam_img, width=120, height=80, left_val=10, right_val=80, seam_x=60)
        with self.assertRaises(RuntimeError):
            prepare_agnes_images(seam_img, seam="off", check=True)

    def test_prepare_images_alias(self):
        self.assertIs(prepare_images, prepare_agnes_images)


class TestBatchStructuredResultAndFailures(unittest.TestCase):
    """验证批量结果结构化契约、部分失败可定位性、重复目标去重与计数一致性。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.img1 = self.dir_path / "img1.png"
        self.img2 = self.dir_path / "img2.png"
        create_test_image(self.img1, width=100, height=80)
        create_test_image(self.img2, width=100, height=80)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_batch_all_success(self):
        targets = [self.img1, self.img2]
        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # check_images 契约
        self.assertTrue(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 2)
        self.assertEqual(res_chk["failure_count"], 0)
        self.assertFalse(res_chk["partial_success"])
        self.assertFalse(res_chk["is_partial_success"])
        self.assertEqual(res_chk["failures"], [])
        self.assertEqual(len(res_chk["items"]), 2)

        # prepare_images 契约
        self.assertTrue(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 2)
        self.assertEqual(res_prep["failure_count"], 0)
        self.assertFalse(res_prep["partial_success"])
        self.assertFalse(res_prep["is_partial_success"])
        self.assertEqual(res_prep["failures"], [])
        self.assertEqual(len(res_prep["items"]), 2)

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_single_failure(self):
        missing = self.dir_path / "non_existing.png"
        res_chk = check_images([missing], verbose=False)
        res_prep = prepare_images([missing], verbose=False)

        # check_images 契约
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 1)
        self.assertEqual(res_chk["success_count"], 0)
        self.assertEqual(res_chk["failure_count"], 1)
        self.assertFalse(res_chk["partial_success"])
        self.assertEqual(len(res_chk["failures"]), 1)
        self.assertEqual(res_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(res_chk["failures"][0]["name"], "non_existing.png")
        self.assertIn("non_existing.png", res_chk["failures"][0]["reason"])

        # prepare_images 契约
        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 1)
        self.assertEqual(res_prep["success_count"], 0)
        self.assertEqual(res_prep["failure_count"], 1)
        self.assertFalse(res_prep["partial_success"])
        self.assertEqual(len(res_prep["failures"]), 1)
        self.assertEqual(res_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(res_prep["failures"][0]["name"], "non_existing.png")
        self.assertIn("non_existing.png", res_prep["failures"][0]["reason"])

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_partial_failure(self):
        missing = self.dir_path / "not_found.png"
        targets = [self.img1, missing]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # 验证部分成功标记与可定位性
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 1)
        self.assertEqual(res_chk["failure_count"], 1)
        self.assertTrue(res_chk["partial_success"])
        self.assertTrue(res_chk["is_partial_success"])
        self.assertEqual(len(res_chk["failures"]), 1)
        self.assertEqual(res_chk["failures"][0]["name"], "not_found.png")
        self.assertEqual(res_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(len(res_chk["items"]), 1)

        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 1)
        self.assertEqual(res_prep["failure_count"], 1)
        self.assertTrue(res_prep["partial_success"])
        self.assertTrue(res_prep["is_partial_success"])
        self.assertEqual(len(res_prep["failures"]), 1)
        self.assertEqual(res_prep["failures"][0]["name"], "not_found.png")
        self.assertEqual(res_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(len(res_prep["items"]), 1)

        # 计数严格一致
        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_all_failure(self):
        m1 = self.dir_path / "m1.png"
        m2 = self.dir_path / "m2.png"
        targets = [m1, m2]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, verbose=False)

        # 全失败断言
        self.assertFalse(res_chk["ok"])
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 0)
        self.assertEqual(res_chk["failure_count"], 2)
        self.assertFalse(res_chk["partial_success"])
        self.assertEqual(len(res_chk["failures"]), 2)

        self.assertFalse(res_prep["ok"])
        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 0)
        self.assertEqual(res_prep["failure_count"], 2)
        self.assertFalse(res_prep["partial_success"])
        self.assertEqual(len(res_prep["failures"]), 2)

        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])
        self.assertEqual(res_chk["partial_success"], res_prep["partial_success"])

    def test_batch_deduplication(self):
        # 传递带有重复 Path 及等价字符串的目标列表
        targets = [self.img1, str(self.img1), self.img2, self.img1]

        res_chk = check_images(targets, verbose=False)
        res_prep = prepare_images(targets, size=(50, 40), apply=False, verbose=False)

        # 重复项被去重，有效总数应为 2
        self.assertEqual(res_chk["total"], 2)
        self.assertEqual(res_chk["success_count"], 2)
        self.assertEqual(res_chk["failure_count"], 0)
        self.assertFalse(res_chk["partial_success"])

        self.assertEqual(res_prep["total"], 2)
        self.assertEqual(res_prep["success_count"], 2)
        self.assertEqual(res_prep["failure_count"], 0)
        self.assertFalse(res_prep["partial_success"])

        self.assertEqual(res_chk["total"], res_prep["total"])
        self.assertEqual(res_chk["success_count"], res_prep["success_count"])
        self.assertEqual(res_chk["failure_count"], res_prep["failure_count"])

    def test_quiet_verbose_do_not_alter_structured_result(self):
        targets = [self.img1, self.dir_path / "missing.png"]

        # check_images quiet vs verbose
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            res_chk_v = check_images(targets, verbose=True)
        res_chk_q = check_images(targets, verbose=False)
        self.assertEqual(res_chk_v, res_chk_q)

        # prepare_images quiet vs verbose
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            res_prep_v = prepare_images(targets, size=(50, 40), apply=False, verbose=True)
        res_prep_q = prepare_images(targets, size=(50, 40), apply=False, verbose=False)
        self.assertEqual(res_prep_v, res_prep_q)

    def test_counts_consistency_across_scenarios(self):
        test_cases = [
            # 全成功
            [self.img1, self.img2],
            # 单失败
            [self.dir_path / "bad1.png"],
            # 部分失败
            [self.img1, self.dir_path / "bad2.png"],
            # 全失败
            [self.dir_path / "bad1.png", self.dir_path / "bad2.png"],
            # 重复目标去重
            [self.img1, self.img1, self.img2],
            # 空目标
            [],
        ]
        for idx, tc in enumerate(test_cases):
            with self.subTest(case_idx=idx):
                chk = check_images(tc, verbose=False)
                prep = prepare_images(tc, size=(50, 40), apply=False, verbose=False)
                self.assertEqual(chk["total"], prep["total"])
                self.assertEqual(chk["success_count"], prep["success_count"])
                self.assertEqual(chk["failure_count"], prep["failure_count"])
                self.assertEqual(chk["partial_success"], prep["partial_success"])
                self.assertEqual(chk["ok"], prep["ok"])


class TestCLIJsonAndExitCodes(unittest.TestCase):
    """测试配图处理与客观门禁 CLI 的 --json 机器可读模式与退出码语义。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 全成功目录
        self.clean_dir = self.dir_path / "clean_dir"
        self.clean_dir.mkdir(parents=True)
        self.clean1 = self.clean_dir / "clean1.png"
        self.clean2 = self.clean_dir / "clean2.png"
        create_test_image(self.clean1, width=120, height=80)
        create_test_image(self.clean2, width=120, height=80)

        # 2. 部分失败目录 (1 正常 + 1 坏图: 空文件)
        self.partial_dir = self.dir_path / "partial_dir"
        self.partial_dir.mkdir(parents=True)
        self.p_good = self.partial_dir / "p_good.png"
        self.p_bad = self.partial_dir / "p_bad.png"
        create_test_image(self.p_good, width=120, height=80)
        self.p_bad.write_bytes(b"")

        # 3. 全失败目录 (2 坏图: 0 字节文件与非图片文本文件)
        self.fail_dir = self.dir_path / "fail_dir"
        self.fail_dir.mkdir(parents=True)
        self.f_bad1 = self.fail_dir / "f_bad1.png"
        self.f_bad2 = self.fail_dir / "f_bad2.png"
        self.f_bad1.write_bytes(b"")
        self.f_bad2.write_bytes(b"NOT_A_PNG_FILE_CONTENT")

        # 4. 门禁部分失败与全失败目录 (含接缝)
        self.seam_partial_dir = self.dir_path / "seam_partial_dir"
        self.seam_partial_dir.mkdir(parents=True)
        self.sp_clean = self.seam_partial_dir / "sp_clean.png"
        self.sp_seam = self.seam_partial_dir / "sp_seam.png"
        create_test_image(self.sp_clean, width=120, height=80)
        create_test_image(self.sp_seam, width=120, height=80, left_val=20, right_val=60, seam_x=60)

        self.seam_all_fail_dir = self.dir_path / "seam_all_fail_dir"
        self.seam_all_fail_dir.mkdir(parents=True)
        self.sa_seam1 = self.seam_all_fail_dir / "sa_seam1.png"
        self.sa_seam2 = self.seam_all_fail_dir / "sa_seam2.png"
        create_test_image(self.sa_seam1, width=120, height=80, left_val=20, right_val=60, seam_x=60)
        create_test_image(self.sa_seam2, width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_cli_json_all_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")

        # 标准 JSON 解析与字段契约
        data = json.loads(buf_out.getvalue())
        self.assertIsInstance(data, dict)
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self.assertEqual(len(data["items"]), 2)

        # stdout 纯净无人类日志混入
        self.assertTrue(buf_out.getvalue().strip().startswith("{"))
        self.assertTrue(buf_out.getvalue().strip().endswith("}"))
        self.assertNotIn("✓", buf_out.getvalue())
        self.assertNotIn("[预演]", buf_out.getvalue())

    def test_prepare_cli_json_partial_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.partial_dir), "--json", "--size", "100x60"])
        # 存在失败时必须返回非零退出码
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])
        self.assertEqual(len(data["failures"]), 1)

        fail = data["failures"][0]
        self.assertEqual(fail["name"], "p_bad.png")
        self.assertEqual(fail["code"], "EMPTY_FILE")
        self.assertIn("空图片文件", fail["reason"])

    def test_prepare_cli_json_all_failure(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.fail_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(len(data["failures"]), 2)
        for fail in data["failures"]:
            self.assertIn("file", fail)
            self.assertIn("code", fail)
            self.assertIn("reason", fail)

    def test_prepare_cli_json_matches_python_api(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = main([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 0)
        cli_data = json.loads(buf_out.getvalue())

        api_res = prepare_images(self.clean_dir, size=(100, 60), apply=False, verbose=False)
        api_data = json.loads(json.dumps(api_res))
        self.assertEqual(cli_data, api_data)

    def test_check_cli_json_all_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")

        data = json.loads(buf_out.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self.assertNotIn("ALL CLEAR", buf_out.getvalue())
        self.assertNotIn("🔍", buf_out.getvalue())

    def test_check_cli_json_partial_success(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.seam_partial_dir), "--check", "--json"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])
        self.assertEqual(len(data["failures"]), 1)
        self.assertEqual(data["failures"][0]["code"], "SEAM_DETECTED")
        self.assertIn("残留接缝", data["failures"][0]["reason"])

    def test_check_cli_json_all_failure(self):
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.seam_all_fail_dir), "--check", "--json"])
        self.assertEqual(code, 1)

        data = json.loads(buf_out.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(len(data["failures"]), 2)
        for fail in data["failures"]:
            self.assertEqual(fail["code"], "SEAM_DETECTED")

    def test_check_cli_json_matches_python_api(self):
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            code = main([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(code, 0)
        cli_data = json.loads(buf_out.getvalue())

        api_res = check_images(self.clean_dir, size=(120, 80), verbose=False)
        api_data = json.loads(json.dumps(api_res))
        self.assertEqual(cli_data, api_data)

    def test_cli_json_deterministic_structure_and_ordering(self):
        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            code1 = main([str(self.clean_dir), "--json", "--size", "100x60"])
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = main([str(self.clean_dir), "--json", "--size", "100x60"])

        self.assertEqual(code1, code2)
        self.assertEqual(buf1.getvalue(), buf2.getvalue())

        data1 = json.loads(buf1.getvalue())
        data2 = json.loads(buf2.getvalue())
        self.assertEqual(
            [item["file"] for item in data1["items"]],
            [item["file"] for item in data2["items"]],
        )

    def test_cli_quiet_and_verbose_combinations_with_json(self):
        # 1. prepare --json + --quiet
        buf_out_q = io.StringIO()
        buf_err_q = io.StringIO()
        with redirect_stdout(buf_out_q), redirect_stderr(buf_err_q):
            code_q = main([str(self.clean_dir), "--json", "--quiet"])
        self.assertEqual(code_q, 0)
        self.assertEqual(buf_err_q.getvalue(), "")
        json.loads(buf_out_q.getvalue())

        # 2. prepare --json + --verbose
        buf_out_v = io.StringIO()
        buf_err_v = io.StringIO()
        with redirect_stdout(buf_out_v), redirect_stderr(buf_err_v):
            code_v = main([str(self.clean_dir), "--json", "--verbose"])
        self.assertEqual(code_v, 0)
        self.assertEqual(buf_err_v.getvalue(), "")
        json.loads(buf_out_v.getvalue())

        # 3. check --json + --quiet
        buf_out_cq = io.StringIO()
        buf_err_cq = io.StringIO()
        with redirect_stdout(buf_out_cq), redirect_stderr(buf_err_cq):
            code_cq = main([str(self.clean_dir), "--check", "--json", "--quiet"])
        self.assertEqual(code_cq, 0)
        self.assertEqual(buf_err_cq.getvalue(), "")
        json.loads(buf_out_cq.getvalue())

        # 4. check --json + --verbose
        buf_out_cv = io.StringIO()
        buf_err_cv = io.StringIO()
        with redirect_stdout(buf_out_cv), redirect_stderr(buf_err_cv):
            code_cv = main([str(self.clean_dir), "--check", "--json", "--verbose"])
        self.assertEqual(code_cv, 0)
        self.assertEqual(buf_err_cv.getvalue(), "")
        json.loads(buf_out_cv.getvalue())

    def test_default_cli_output_and_batch_exit_codes_without_json(self):
        # 全成功: 退出码 0，保持人类可读输出与提示
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main([str(self.clean_dir), "--size", "100x60"])
        self.assertEqual(code, 0)
        self.assertEqual(buf_err.getvalue(), "")
        self.assertIn("[预演]", buf_out.getvalue())
        self.assertIn("clean1.png", buf_out.getvalue())
        self.assertIn("clean2.png", buf_out.getvalue())
        self.assertIn("加 --apply 执行写盘", buf_out.getvalue())

        # 包含失败项: 退出码为 1，诊断信息走 stderr，stdout 仍正常输出成功项预演
        buf_out_p = io.StringIO()
        buf_err_p = io.StringIO()
        with redirect_stdout(buf_out_p), redirect_stderr(buf_err_p):
            code_p = main([str(self.partial_dir), "--size", "100x60"])
        self.assertEqual(code_p, 1)
        self.assertIn("[预演] p_good.png", buf_out_p.getvalue())
        self.assertIn("[!] 处理图片 p_bad.png 失败", buf_err_p.getvalue())

    def test_invalid_cli_arguments_keep_contract(self):
        # 非法 size
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            ret = main([str(self.clean_dir), "--size", "invalid_size"])
        self.assertEqual(ret, 1)
        self.assertIn("尺寸格式无效", buf_err.getvalue())

        # 非法 brightness
        buf_err2 = io.StringIO()
        with redirect_stderr(buf_err2):
            ret2 = main([str(self.clean_dir), "--brightness", "-1"])
        self.assertEqual(ret2, 1)
        self.assertIn("亮度系数必须 >= 0", buf_err2.getvalue())

        # 非法 seam
        buf_err3 = io.StringIO()
        with redirect_stderr(buf_err3):
            ret3 = main([str(self.clean_dir), "--seam", "bad_col"])
        self.assertEqual(ret3, 1)
        self.assertIn("无效的接缝列号", buf_err3.getvalue())

        # 非法 argparse 参数抛出 SystemExit 且退出码为 2
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()):
                main([str(self.clean_dir), "--non-existent-option"])
        self.assertEqual(cm.exception.code, 2)


class TestRealCLIFailureContract(unittest.TestCase):
    """真实独立子进程 CLI 针对 --json 模式失败路径与契约一致性的定向测试。
    验证 stdout 纯 JSON、failure_count/partial_success、failures 明细与 Python API 完全一致、
    有失败时退出码非零、成功项不会因部分失败消失、stderr 诊断不污染 stdout、
    quiet/verbose 不改变 JSON 语义，且不泄漏任何敏感值。
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 正常有效测试图
        self.clean1 = self.dir_path / "clean1.png"
        self.clean2 = self.dir_path / "clean2.png"
        create_test_image(self.clean1, width=120, height=80)
        create_test_image(self.clean2, width=120, height=80)

        # 2. 0 字节空文件 (无法读取/损坏图片)
        self.bad_empty = self.dir_path / "bad_empty.png"
        self.bad_empty.write_bytes(b"")

        # 3. 损坏的图片文件 (非图像二进制文本)
        self.bad_corrupt = self.dir_path / "bad_corrupt.png"
        self.bad_corrupt.write_bytes(b"CORRUPTED_NOT_AN_IMAGE_PAYLOAD\x00\xff\xfe")

        # 4. 截断的伪 PNG 文件
        self.bad_truncated = self.dir_path / "bad_truncated.png"
        self.bad_truncated.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR_TRUNCATED")

        # 5. 接缝质检失败图 (用于图片质量门禁失败)
        self.bad_seam = self.dir_path / "bad_seam.png"
        create_test_image(self.bad_seam, width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 6. 不存在的文件路径
        self.missing_file = self.dir_path / "non_existing_file_98765.png"

        # 7. 批量目录构建 (包含成功项与多种失败项)
        self.batch_dir = self.dir_path / "batch_mixed"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.clean1, self.batch_dir / "clean1.png")
        shutil.copy2(self.clean2, self.batch_dir / "clean2.png")
        (self.batch_dir / "bad_empty.png").write_bytes(b"")
        (self.batch_dir / "bad_corrupt.png").write_bytes(b"CORRUPTED_NOT_AN_IMAGE_PAYLOAD\x00\xff\xfe")
        create_test_image(self.batch_dir / "bad_seam.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_cli(self, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        if env:
            full_env.update(env)
        return subprocess.run(
            [str(PYTHON_BIN), str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=full_env,
        )

    def _assert_pure_json(self, stdout: str) -> dict:
        stripped = stdout.strip()
        self.assertTrue(stripped.startswith("{"), f"stdout 未以 '{{' 开头: {stripped[:80]}")
        self.assertTrue(stripped.endswith("}"), f"stdout 未以 '}}' 结尾: {stripped[-80:]}")
        # 人类日志标记不得混入机器可读 stdout
        for marker in ["[预演]", "✓", "ALL CLEAR", "❌", "🔍", "[!]", "[提示]"]:
            self.assertNotIn(marker, stdout)
        try:
            return json.loads(stdout)
        except Exception as e:
            self.fail(f"stdout 不是合规的 JSON: {e}\n完整 stdout:\n{stdout}")

    def _assert_no_sensitive_values(self, stdout: str, stderr: str, tokens: list[str]):
        combined = f"{stdout}\n{stderr}"
        for token in tokens:
            self.assertNotIn(token, combined)

    def test_real_cli_file_not_found(self):
        """覆盖 FILE_NOT_FOUND 失败路径：单文件、不存在目录与空目录。"""
        # 1. 单个不存在的文件 --check --json
        p_chk = self._run_cli([str(self.missing_file), "--check", "--json"])
        self.assertEqual(p_chk.returncode, 1)
        self.assertEqual(p_chk.stderr, "")
        cli_chk = self._assert_pure_json(p_chk.stdout)
        api_chk = json.loads(json.dumps(check_images(self.missing_file, verbose=False)))

        self.assertFalse(cli_chk["ok"])
        self.assertEqual(cli_chk["total"], 1)
        self.assertEqual(cli_chk["success_count"], 0)
        self.assertEqual(cli_chk["failure_count"], 1)
        self.assertFalse(cli_chk["partial_success"])
        self.assertEqual(len(cli_chk["failures"]), 1)
        self.assertEqual(cli_chk["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(cli_chk["failures"][0]["name"], self.missing_file.name)
        self.assertIn("源图片文件不存在", cli_chk["failures"][0]["reason"])
        self.assertEqual(cli_chk["failures"], api_chk["failures"])
        self.assertEqual(cli_chk, api_chk)

        # 2. 单个不存在的文件 prepare --json
        p_prep = self._run_cli([str(self.missing_file), "--json"])
        self.assertEqual(p_prep.returncode, 1)
        self.assertEqual(p_prep.stderr, "")
        cli_prep = self._assert_pure_json(p_prep.stdout)
        api_prep = json.loads(json.dumps(prepare_images(self.missing_file, verbose=False)))

        self.assertFalse(cli_prep["ok"])
        self.assertEqual(cli_prep["total"], 1)
        self.assertEqual(cli_prep["success_count"], 0)
        self.assertEqual(cli_prep["failure_count"], 1)
        self.assertFalse(cli_prep["partial_success"])
        self.assertEqual(len(cli_prep["failures"]), 1)
        self.assertEqual(cli_prep["failures"][0]["code"], "FILE_NOT_FOUND")
        self.assertEqual(cli_prep["failures"][0]["name"], self.missing_file.name)
        self.assertIn("源图片文件不存在", cli_prep["failures"][0]["reason"])
        self.assertEqual(cli_prep["failures"], api_prep["failures"])
        self.assertEqual(cli_prep, api_prep)

        # 3. 不存在的目录路径
        non_dir = self.dir_path / "non_existing_dir_404"
        p_dir_chk = self._run_cli([str(non_dir), "--check", "--json"])
        self.assertEqual(p_dir_chk.returncode, 1)
        cli_dir_chk = self._assert_pure_json(p_dir_chk.stdout)
        api_dir_chk = json.loads(json.dumps(check_images(non_dir, verbose=False)))
        self.assertEqual(cli_dir_chk["failures"], api_dir_chk["failures"])
        self.assertEqual(cli_dir_chk["failures"][0]["code"], "FILE_NOT_FOUND")

        # 4. 存在但为空的目录 (无 PNG 图片)
        empty_dir = self.dir_path / "empty_dir_no_images"
        empty_dir.mkdir(parents=True, exist_ok=True)
        p_empty_dir = self._run_cli([str(empty_dir), "--json"])
        self.assertEqual(p_empty_dir.returncode, 1)
        cli_empty_dir = self._assert_pure_json(p_empty_dir.stdout)
        api_empty_dir = json.loads(json.dumps(prepare_images(empty_dir, verbose=False)))
        self.assertEqual(cli_empty_dir["failures"][0]["code"], "TARGET_RESOLUTION_ERROR")
        self.assertEqual(cli_empty_dir["failures"], api_empty_dir["failures"])

    def test_real_cli_unreadable_and_corrupt_images(self):
        """覆盖无法读取/损坏图片失败路径：0 字节空文件与文件内容损坏。"""
        # 1. 0 字节文件
        # check --json -> EMPTY_FILE
        p_c_empty = self._run_cli([str(self.bad_empty), "--check", "--json"])
        self.assertEqual(p_c_empty.returncode, 1)
        self.assertEqual(p_c_empty.stderr, "")
        cli_c_empty = self._assert_pure_json(p_c_empty.stdout)
        api_c_empty = json.loads(json.dumps(check_images(self.bad_empty, verbose=False)))
        self.assertEqual(cli_c_empty["failures"][0]["code"], "EMPTY_FILE")
        self.assertEqual(cli_c_empty["failures"], api_c_empty["failures"])
        self.assertEqual(cli_c_empty, api_c_empty)

        # prepare --json -> EMPTY_FILE
        p_p_empty = self._run_cli([str(self.bad_empty), "--json"])
        self.assertEqual(p_p_empty.returncode, 1)
        self.assertEqual(p_p_empty.stderr, "")
        cli_p_empty = self._assert_pure_json(p_p_empty.stdout)
        api_p_empty = json.loads(json.dumps(prepare_images(self.bad_empty, verbose=False)))
        self.assertEqual(cli_p_empty["failures"][0]["code"], "EMPTY_FILE")
        self.assertEqual(cli_p_empty["failures"], api_p_empty["failures"])
        self.assertEqual(cli_p_empty, api_p_empty)

        # 2. 损坏文件 (bad_corrupt)
        # check --json -> UNREADABLE_IMAGE
        p_c_corrupt = self._run_cli([str(self.bad_corrupt), "--check", "--json"])
        self.assertEqual(p_c_corrupt.returncode, 1)
        self.assertEqual(p_c_corrupt.stderr, "")
        cli_c_corrupt = self._assert_pure_json(p_c_corrupt.stdout)
        api_c_corrupt = json.loads(json.dumps(check_images(self.bad_corrupt, verbose=False)))
        self.assertEqual(cli_c_corrupt["failures"][0]["code"], "UNREADABLE_IMAGE")
        self.assertEqual(cli_c_corrupt["failures"], api_c_corrupt["failures"])
        self.assertEqual(cli_c_corrupt, api_c_corrupt)

        # prepare --json -> PREPARE_ERROR
        p_p_corrupt = self._run_cli([str(self.bad_corrupt), "--json"])
        self.assertEqual(p_p_corrupt.returncode, 1)
        self.assertEqual(p_p_corrupt.stderr, "")
        cli_p_corrupt = self._assert_pure_json(p_p_corrupt.stdout)
        api_p_corrupt = json.loads(json.dumps(prepare_images(self.bad_corrupt, verbose=False)))
        self.assertEqual(cli_p_corrupt["failures"][0]["code"], "PREPARE_ERROR")
        self.assertEqual(cli_p_corrupt["failures"], api_p_corrupt["failures"])
        self.assertEqual(cli_p_corrupt, api_p_corrupt)

        # 3. 截断文件 (bad_truncated)
        p_c_trunc = self._run_cli([str(self.bad_truncated), "--check", "--json"])
        self.assertEqual(p_c_trunc.returncode, 1)
        cli_c_trunc = self._assert_pure_json(p_c_trunc.stdout)
        api_c_trunc = json.loads(json.dumps(check_images(self.bad_truncated, verbose=False)))
        self.assertEqual(cli_c_trunc["failures"][0]["code"], "UNREADABLE_IMAGE")
        self.assertEqual(cli_c_trunc["failures"], api_c_trunc["failures"])

        p_p_trunc = self._run_cli([str(self.bad_truncated), "--json"])
        self.assertEqual(p_p_trunc.returncode, 1)
        cli_p_trunc = self._assert_pure_json(p_p_trunc.stdout)
        api_p_trunc = json.loads(json.dumps(prepare_images(self.bad_truncated, verbose=False)))
        self.assertEqual(cli_p_trunc["failures"][0]["code"], "PREPARE_ERROR")
        self.assertEqual(cli_p_trunc["failures"], api_p_trunc["failures"])

    def test_real_cli_quality_gate_failures(self):
        """覆盖图片质量门禁失败路径：残留接缝、尺寸偏差及二者复合。"""
        # 1. 残留接缝 (SEAM_DETECTED)
        p_seam = self._run_cli([str(self.bad_seam), "--check", "--json"])
        self.assertEqual(p_seam.returncode, 1)
        self.assertEqual(p_seam.stderr, "")
        cli_seam = self._assert_pure_json(p_seam.stdout)
        api_seam = json.loads(json.dumps(check_images(self.bad_seam, verbose=False)))

        self.assertFalse(cli_seam["ok"])
        self.assertEqual(cli_seam["failure_count"], 1)
        self.assertEqual(cli_seam["failures"][0]["code"], "SEAM_DETECTED")
        self.assertIn("残留接缝", cli_seam["failures"][0]["reason"])
        self.assertEqual(cli_seam["failures"], api_seam["failures"])
        self.assertEqual(cli_seam, api_seam)

        # 2. 尺寸偏差 (DIMENSION_MISMATCH)
        p_dim = self._run_cli([str(self.clean1), "--check", "--json", "--size", "300x200"])
        self.assertEqual(p_dim.returncode, 1)
        self.assertEqual(p_dim.stderr, "")
        cli_dim = self._assert_pure_json(p_dim.stdout)
        api_dim = json.loads(json.dumps(check_images(self.clean1, size=(300, 200), verbose=False)))

        self.assertFalse(cli_dim["ok"])
        self.assertEqual(cli_dim["failure_count"], 1)
        self.assertEqual(cli_dim["failures"][0]["code"], "DIMENSION_MISMATCH")
        self.assertIn("尺寸不匹配", cli_dim["failures"][0]["reason"])
        self.assertEqual(cli_dim["failures"], api_dim["failures"])
        self.assertEqual(cli_dim, api_dim)

        # 3. 复合门禁失败 (SEAM_AND_DIMENSION_MISMATCH)
        p_both = self._run_cli([str(self.bad_seam), "--check", "--json", "--size", "300x200"])
        self.assertEqual(p_both.returncode, 1)
        self.assertEqual(p_both.stderr, "")
        cli_both = self._assert_pure_json(p_both.stdout)
        api_both = json.loads(json.dumps(check_images(self.bad_seam, size=(300, 200), verbose=False)))

        self.assertFalse(cli_both["ok"])
        self.assertEqual(cli_both["failure_count"], 1)
        self.assertEqual(cli_both["failures"][0]["code"], "SEAM_AND_DIMENSION_MISMATCH")
        self.assertIn("残留接缝", cli_both["failures"][0]["reason"])
        self.assertIn("尺寸不符合预期", cli_both["failures"][0]["reason"])
        self.assertEqual(cli_both["failures"], api_both["failures"])
        self.assertEqual(cli_both, api_both)

    def test_real_cli_batch_partial_failures_and_retention(self):
        """覆盖批量输入中的部分失败：确认 partial_success、成功项完整保留、明细与 API 严格一致。"""
        # 批量目录包含: clean1, clean2, bad_empty, bad_corrupt, bad_seam (共 5 项)

        # 1. prepare --json 预演模式
        p_prep = self._run_cli([str(self.batch_dir), "--json", "--size", "100x60"])
        self.assertEqual(p_prep.returncode, 1)  # 包含失败项，退出码非零
        self.assertEqual(p_prep.stderr, "")    # --json 纯净无 stderr 杂音
        cli_prep = self._assert_pure_json(p_prep.stdout)
        api_prep = json.loads(json.dumps(prepare_images(self.batch_dir, size=(100, 60), apply=False, verbose=False)))

        self.assertFalse(cli_prep["ok"])
        self.assertEqual(cli_prep["total"], 5)
        # clean1, clean2, bad_seam（seam 在 prepare 中成功抹平）为 3 成功；bad_empty, bad_corrupt 为 2 失败
        self.assertEqual(cli_prep["success_count"], 3)
        self.assertEqual(cli_prep["failure_count"], 2)
        self.assertTrue(cli_prep["partial_success"])
        self.assertTrue(cli_prep["is_partial_success"])

        # 成功项不会因部分失败消失
        self.assertEqual(len(cli_prep["items"]), 3)
        success_names = {item["name"] for item in cli_prep["items"]}
        self.assertEqual(success_names, {"clean1.png", "clean2.png", "bad_seam.png"})

        # 失败项定位与契约一致性
        self.assertEqual(len(cli_prep["failures"]), 2)
        fail_codes = {f["name"]: f["code"] for f in cli_prep["failures"]}
        self.assertEqual(fail_codes["bad_empty.png"], "EMPTY_FILE")
        self.assertEqual(fail_codes["bad_corrupt.png"], "PREPARE_ERROR")
        self.assertEqual(cli_prep["failures"], api_prep["failures"])
        self.assertEqual(cli_prep, api_prep)

        # 2. prepare --json --out <dir> 实际写盘模式：成功项正常落地，失败项记录
        out_batch_dir = self.dir_path / "out_batch_written"
        p_prep_out = self._run_cli([str(self.batch_dir), "--out", str(out_batch_dir), "--json", "--size", "100x60"])
        self.assertEqual(p_prep_out.returncode, 1)
        cli_prep_out = self._assert_pure_json(p_prep_out.stdout)
        self.assertTrue(cli_prep_out["partial_success"])
        # 成功项物理落地存在
        self.assertTrue((out_batch_dir / "clean1.png").is_file())
        self.assertTrue((out_batch_dir / "clean2.png").is_file())
        self.assertTrue((out_batch_dir / "bad_seam.png").is_file())
        # 失败项未落地
        self.assertFalse((out_batch_dir / "bad_empty.png").exists())
        self.assertFalse((out_batch_dir / "bad_corrupt.png").exists())

        # 3. check --check --json 门禁模式
        p_chk = self._run_cli([str(self.batch_dir), "--check", "--json"])
        self.assertEqual(p_chk.returncode, 1)
        self.assertEqual(p_chk.stderr, "")
        cli_chk = self._assert_pure_json(p_chk.stdout)
        api_chk = json.loads(json.dumps(check_images(self.batch_dir, verbose=False)))

        self.assertFalse(cli_chk["ok"])
        self.assertEqual(cli_chk["total"], 5)
        # clean1, clean2 为 2 成功；bad_empty, bad_corrupt, bad_seam 为 3 失败
        self.assertEqual(cli_chk["success_count"], 2)
        self.assertEqual(cli_chk["failure_count"], 3)
        self.assertTrue(cli_chk["partial_success"])
        self.assertTrue(cli_chk["is_partial_success"])

        # 成功项未丢失
        self.assertEqual(len(cli_chk["items"]), 2)
        chk_success_names = {item["name"] for item in cli_chk["items"]}
        self.assertEqual(chk_success_names, {"clean1.png", "clean2.png"})

        # 失败项定位与契约一致性
        self.assertEqual(len(cli_chk["failures"]), 3)
        chk_fail_codes = {f["name"]: f["code"] for f in cli_chk["failures"]}
        self.assertEqual(chk_fail_codes["bad_empty.png"], "EMPTY_FILE")
        self.assertEqual(chk_fail_codes["bad_corrupt.png"], "UNREADABLE_IMAGE")
        self.assertEqual(chk_fail_codes["bad_seam.png"], "SEAM_DETECTED")
        self.assertEqual(cli_chk["failures"], api_chk["failures"])
        self.assertEqual(cli_chk, api_chk)

    def test_real_cli_quiet_and_verbose_consistency(self):
        """确认 quiet 与 verbose 组合在 --json 模式下不改变 JSON 语义，且 stderr 不污染 stdout。"""
        # 1. prepare --json: 默认 vs --quiet vs -q vs --verbose vs -v
        p_def = self._run_cli([str(self.batch_dir), "--json", "--size", "100x60"])
        p_quiet = self._run_cli([str(self.batch_dir), "--json", "--quiet", "--size", "100x60"])
        p_q = self._run_cli([str(self.batch_dir), "--json", "-q", "--size", "100x60"])
        p_verb = self._run_cli([str(self.batch_dir), "--json", "--verbose", "--size", "100x60"])
        p_v = self._run_cli([str(self.batch_dir), "--json", "-v", "--size", "100x60"])

        data_def = self._assert_pure_json(p_def.stdout)
        for label, proc in [("quiet", p_quiet), ("-q", p_q), ("verbose", p_verb), ("-v", p_v)]:
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stderr, "", f"{label} 产生了非预期的 stderr 输出")
            data = self._assert_pure_json(proc.stdout)
            self.assertEqual(data, data_def, f"{label} 改变了 JSON 语义")

        # 2. check --check --json: 默认 vs --quiet vs -q vs --verbose vs -v
        p_c_def = self._run_cli([str(self.batch_dir), "--check", "--json"])
        p_c_quiet = self._run_cli([str(self.batch_dir), "--check", "--json", "--quiet"])
        p_c_q = self._run_cli([str(self.batch_dir), "--check", "--json", "-q"])
        p_c_verb = self._run_cli([str(self.batch_dir), "--check", "--json", "--verbose"])
        p_c_v = self._run_cli([str(self.batch_dir), "--check", "--json", "-v"])

        data_c_def = self._assert_pure_json(p_c_def.stdout)
        for label, proc in [("quiet", p_c_quiet), ("-q", p_c_q), ("verbose", p_c_verb), ("-v", p_c_v)]:
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stderr, "", f"{label} 产生了非预期的 stderr 输出")
            data = self._assert_pure_json(proc.stdout)
            self.assertEqual(data, data_c_def, f"{label} 改变了 JSON 语义")

    def test_real_cli_no_sensitive_values_leaked(self):
        """确认各种失败路径与异常状态下，不会向 stdout 或 stderr 泄漏敏感值。"""
        fake_secrets = [
            "SECRET_TOKEN_XYZ_1234567890",
            "PASSWORD_MY_SUPER_SECRET_KEY",
            "API_KEY_AI_AGENT_PLATFORM_ABC",
        ]
        secret_env = {
            "SECRET_TOKEN": fake_secrets[0],
            "API_PASSWORD": fake_secrets[1],
            "OPENAI_API_KEY": fake_secrets[2],
        }

        # 针对各类失败模式运行并验证无敏感值输出
        cases = [
            # FILE_NOT_FOUND
            [str(self.missing_file), "--json"],
            [str(self.missing_file), "--check", "--json"],
            # 坏图与空图
            [str(self.bad_empty), "--json"],
            [str(self.bad_corrupt), "--check", "--json"],
            # 接缝门禁失败
            [str(self.bad_seam), "--check", "--json"],
            # 批量部分失败
            [str(self.batch_dir), "--json", "--size", "100x60"],
            [str(self.batch_dir), "--check", "--json"],
            # 参数错误失败
            [str(self.clean1), "--json", "--size", "invalid_size"],
            [str(self.clean1), "--json", "--brightness", "-1"],
        ]

        for argv in cases:
            proc = self._run_cli(argv, env=secret_env)
            self._assert_no_sensitive_values(proc.stdout, proc.stderr, fake_secrets)

    def test_real_cli_invalid_arguments_keep_clean_output(self):
        """确认非法参数在 --json 下保持非零退出码，stdout 不被污染，stderr 包含合规诊断。"""
        # 1. 非法尺寸 --size
        p_size = self._run_cli([str(self.clean1), "--json", "--size", "invalid"])
        self.assertEqual(p_size.returncode, 1)
        self.assertEqual(p_size.stdout, "")
        self.assertIn("尺寸格式无效", p_size.stderr)

        # 2. 非法亮度 --brightness
        p_b = self._run_cli([str(self.clean1), "--json", "--brightness", "-0.5"])
        self.assertEqual(p_b.returncode, 1)
        self.assertEqual(p_b.stdout, "")
        self.assertIn("亮度系数必须 >= 0", p_b.stderr)

        # 3. 非法接缝 --seam
        p_seam = self._run_cli([str(self.clean1), "--json", "--seam", "bad_col"])
        self.assertEqual(p_seam.returncode, 1)
        self.assertEqual(p_seam.stdout, "")
        self.assertIn("无效的接缝列号", p_seam.stderr)

        # 4. quiet 模式下非法参数抑制 stderr
        p_size_q = self._run_cli([str(self.clean1), "--json", "--size", "invalid", "--quiet"])
        self.assertEqual(p_size_q.returncode, 1)
        self.assertEqual(p_size_q.stdout, "")
        self.assertEqual(p_size_q.stderr, "")


class TestCLIJSONSchemaCompatibilityContract(unittest.TestCase):
    """测试 --json CLI 输出的 schema/version 兼容性保护。
    固定当前 JSON 结果的字段集合、基本类型和 failure item 结构，
    增加回归测试防止字段删除、重命名、类型漂移、success/failure/partial/quiet/verbose 路径不一致。
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 干净有效图片
        self.clean_dir = self.dir_path / "clean_dir"
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        self.clean1 = self.clean_dir / "c1.png"
        self.clean2 = self.clean_dir / "c2.png"
        create_test_image(self.clean1, width=120, height=80)
        create_test_image(self.clean2, width=120, height=80)

        # 2. 纯失败图片目录（0 字节空文件与非图像损坏文件）
        self.fail_dir = self.dir_path / "fail_dir"
        self.fail_dir.mkdir(parents=True, exist_ok=True)
        (self.fail_dir / "bad_empty.png").write_bytes(b"")
        (self.fail_dir / "bad_corrupt.png").write_bytes(b"NOT_A_VALID_IMAGE_DATA\x00\x01\x02")

        # 3. 混合目录（用于 partial_success 测试）
        self.partial_dir = self.dir_path / "partial_dir"
        self.partial_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.partial_dir / "p_good.png", width=120, height=80)
        (self.partial_dir / "p_empty.png").write_bytes(b"")

        # 4. 接缝门禁失败目录
        self.seam_dir = self.dir_path / "seam_dir"
        self.seam_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.seam_dir / "seam1.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)
        create_test_image(self.seam_dir / "seam2.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 5. 接缝混合目录（1 干净，1 带接缝）
        self.seam_partial_dir = self.dir_path / "seam_partial_dir"
        self.seam_partial_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.seam_partial_dir / "sp_clean.png", width=120, height=80)
        create_test_image(self.seam_partial_dir / "sp_seam.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _assert_root_schema(self, data: dict, mode: str = "prepare"):
        """严格校验根字典的字段集合与基本数据类型，杜绝字段漂移。"""
        self.assertIsInstance(data, dict, "根节点必须为 JSON 对象字典")

        expected_keys = PREPARE_SCHEMA_KEYS if mode == "prepare" else CHECK_SCHEMA_KEYS
        self.assertEqual(
            set(data.keys()),
            set(expected_keys),
            f"根字典字段集合与固定契约不符！缺失: {set(expected_keys) - set(data.keys())}, 多余: {set(data.keys()) - set(expected_keys)}"
        )

        # 1. 显式 schema_version 校验
        self.assertIs(type(data["schema_version"]), int, "schema_version 必须为 int 类型，不可为 bool 或 string")
        self.assertEqual(data["schema_version"], SCHEMA_VERSION, f"schema_version 必须等于当前系统版本 {SCHEMA_VERSION}")
        self.assertEqual(data["schema_version"], 1, "当前设计目标固定 schema_version 为 1")

        # 2. 基础标量类型严格校验（注意：bool 在 Python 中继承自 int，故必须用 type() is ... 进行强类型判别）
        self.assertIs(type(data["ok"]), bool, "ok 字段必须为严格 bool 类型")
        self.assertIs(type(data["total"]), int, "total 字段必须为严格 int 类型")
        self.assertGreaterEqual(data["total"], 0, "total 计数不可为负数")
        self.assertIs(type(data["success_count"]), int, "success_count 必须为严格 int 类型")
        self.assertGreaterEqual(data["success_count"], 0, "success_count 计数不可为负数")
        self.assertIs(type(data["failure_count"]), int, "failure_count 必须为严格 int 类型")
        self.assertGreaterEqual(data["failure_count"], 0, "failure_count 计数不可为负数")
        self.assertIs(type(data["partial_success"]), bool, "partial_success 必须为严格 bool 类型")
        self.assertIs(type(data["is_partial_success"]), bool, "is_partial_success 必须为严格 bool 类型")

        # 3. 列表容器类型严格校验
        self.assertIs(type(data["failures"]), list, "failures 必须为 list 类型")
        self.assertIs(type(data["failed_items"]), list, "failed_items 必须为 list 类型")
        self.assertIs(type(data["items"]), list, "items 必须为 list 类型")

        # 4. 衍生一致性与别名一致性
        self.assertEqual(data["failures"], data["failed_items"], "failures 与 failed_items 必须内容完全一致")
        self.assertEqual(data["total"], data["success_count"] + data["failure_count"], "total 必须严格等于成功数加失败数")
        self.assertEqual(len(data["failures"]), data["failure_count"], "failures 列表长度必须与 failure_count 严格对齐")
        self.assertEqual(len(data["items"]), data["success_count"], "items 列表长度必须与 success_count 严格对齐")
        self.assertEqual(data["ok"], data["total"] > 0 and data["failure_count"] == 0, "ok 布尔值判定逻辑必须自洽")
        self.assertEqual(
            data["partial_success"],
            data["success_count"] > 0 and data["failure_count"] > 0,
            "partial_success 布尔值必须与 (success>0 and failure>0) 严格一致"
        )
        self.assertEqual(data["is_partial_success"], data["partial_success"], "is_partial_success 必须与 partial_success 一致")

        # 5. 特定模式字段类型
        if mode == "prepare":
            self.assertIs(type(data["reports"]), list, "prepare 模式的 reports 必须为 list 类型")
            self.assertEqual(data["reports"], data["items"], "reports 必须与 items 完全一致")
        elif mode == "check":
            self.assertIs(type(data["unreadable"]), list, "check 模式的 unreadable 必须为 list 类型")
            self.assertIs(type(data["failed_seams"]), list, "check 模式的 failed_seams 必须为 list 类型")
            self.assertIs(type(data["dimension_mismatches"]), list, "check 模式的 dimension_mismatches 必须为 list 类型")

    def _assert_failure_items_schema(self, failures: list[dict]):
        """严格校验 failure item 的结构、字段集合和基本类型。"""
        for item in failures:
            self.assertIsInstance(item, dict, "failure item 必须为字典对象")
            self.assertEqual(
                set(item.keys()),
                set(FAILURE_ITEM_KEYS),
                f"failure item 结构字段漂移！期望 {FAILURE_ITEM_KEYS}, 实际 {set(item.keys())}"
            )
            self.assertIs(type(item["file"]), str, "failure item.file 必须为 str")
            self.assertIs(type(item["name"]), str, "failure item.name 必须为 str")
            self.assertIs(type(item["code"]), str, "failure item.code 必须为 str")
            self.assertIs(type(item["reason"]), str, "failure item.reason 必须为 str")
            self.assertGreater(len(item["code"]), 0, "failure item.code 不可为空字符串")
            self.assertGreater(len(item["reason"]), 0, "failure item.reason 不可为空字符串")

    def _assert_prepare_success_items_schema(self, items: list[dict]):
        """严格校验 prepare 成功项的结构与基本类型。"""
        required_keys = {"file", "name", "src", "out", "seam", "fixed", "kb", "applied"}
        for item in items:
            self.assertIsInstance(item, dict, "success item 必须为字典对象")
            self.assertTrue(
                required_keys.issubset(set(item.keys())),
                f"prepare success item 缺失核心字段！实际字段: {set(item.keys())}"
            )
            self.assertIs(type(item["file"]), str)
            self.assertIs(type(item["name"]), str)
            self.assertIs(type(item["src"]), str)
            self.assertIs(type(item["out"]), str)
            self.assertIs(type(item["fixed"]), bool)
            self.assertIs(type(item["kb"]), int)
            self.assertIs(type(item["applied"]), bool)
            self.assertTrue(item["seam"] is None or isinstance(item["seam"], (int, list)))

    def _assert_check_success_items_schema(self, items: list[dict]):
        """严格校验 check 成功项的结构与基本类型。"""
        expected_keys = {"file", "name", "size", "seam"}
        for item in items:
            self.assertIsInstance(item, dict, "check success item 必须为字典对象")
            self.assertEqual(set(item.keys()), expected_keys, f"check success item 字段集合不符合固定规范: {set(item.keys())}")
            self.assertIs(type(item["file"]), str)
            self.assertIs(type(item["name"]), str)
            self.assertIs(type(item["size"]), str)
            self.assertTrue(item["seam"] is None or isinstance(item["seam"], int))

    def _run_cli_in_process(self, argv: list[str]) -> tuple[int, dict, str]:
        """内存中运行 main(argv) 并捕获 stdout/stderr。"""
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = main(argv)
        out_str = buf_out.getvalue()
        err_str = buf_err.getvalue()
        self.assertTrue(out_str.strip().startswith("{"), f"CLI --json stdout 必须以 '{{' 开头: {out_str[:60]}")
        self.assertTrue(out_str.strip().endswith("}"), f"CLI --json stdout 必须以 '}}' 结尾: {out_str[-60:]}")
        try:
            data = json.loads(out_str)
        except Exception as e:
            self.fail(f"stdout 无法解析为 JSON: {e}\nstdout:\n{out_str}")
        return code, data, err_str

    def _run_cli_subprocess(self, argv: list[str]) -> tuple[int, dict, str]:
        """独立子进程运行 CLI 并捕获 stdout/stderr。"""
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [str(PYTHON_BIN), str(SCRIPT_PATH), *argv],
            capture_output=True,
            text=True,
            env=full_env,
        )
        self.assertTrue(proc.stdout.strip().startswith("{"), f"独立子进程 stdout 未以 '{{' 开头: {proc.stdout[:60]}")
        self.assertTrue(proc.stdout.strip().endswith("}"), f"独立子进程 stdout 未以 '}}' 结尾: {proc.stdout[-60:]}")
        try:
            data = json.loads(proc.stdout)
        except Exception as e:
            self.fail(f"独立子进程 stdout 无法解析为 JSON: {e}\nstdout:\n{proc.stdout}")
        return proc.returncode, data, proc.stderr

    def test_schema_version_single_source_and_batch_result_contract(self):
        """确认 schema_version=1 在模块常量、BatchResult 与 API 单一来源生成。"""
        self.assertEqual(SCHEMA_VERSION, 1)

        # 默认无参数创建 BatchResult
        br_empty = BatchResult()
        self.assertEqual(br_empty.get("schema_version"), 1)
        self.assertIs(type(br_empty["schema_version"]), int)

        # 传入非空字典未指定 schema_version
        br_data = BatchResult({"total": 3, "ok": True})
        self.assertEqual(br_data["schema_version"], 1)
        self.assertEqual(br_data["total"], 3)

        # Python API 产生的结果自动包含 schema_version=1
        res_prep = prepare_images(self.clean_dir, size=(100, 60), apply=False, verbose=False)
        self.assertIsInstance(res_prep, BatchResult)
        self.assertEqual(res_prep.get("schema_version"), 1)

        res_chk = check_images(self.clean_dir, size=(120, 80), verbose=False)
        self.assertIsInstance(res_chk, BatchResult)
        self.assertEqual(res_chk.get("schema_version"), 1)

    def test_schema_contract_prepare_success(self):
        """测试 prepare --json 成功路径：schema_version=1、字段完备且类型一致。"""
        code, data, err = self._run_cli_in_process([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="prepare")
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self._assert_prepare_success_items_schema(data["items"])

    def test_schema_contract_check_success(self):
        """测试 check --check --json 成功路径：schema_version=1、字段完备且类型一致。"""
        code, data, err = self._run_cli_in_process([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="check")
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 2)
        self.assertEqual(data["failure_count"], 0)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["failures"], [])
        self._assert_check_success_items_schema(data["items"])

    def test_schema_contract_prepare_partial(self):
        """测试 prepare --json 部分成功路径：失败项与成功项结构均受 schema 保护。"""
        code, data, err = self._run_cli_in_process([str(self.partial_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="prepare")
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])
        self.assertTrue(data["is_partial_success"])

        self._assert_failure_items_schema(data["failures"])
        self._assert_prepare_success_items_schema(data["items"])

    def test_schema_contract_check_partial(self):
        """测试 check --check --json 部分成功路径：接缝失败项受 schema 保护。"""
        code, data, err = self._run_cli_in_process([str(self.seam_partial_dir), "--check", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="check")
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)
        self.assertTrue(data["partial_success"])

        self._assert_failure_items_schema(data["failures"])
        self._assert_check_success_items_schema(data["items"])

    def test_schema_contract_prepare_all_failure(self):
        """测试 prepare --json 全量失败路径：items 为空列表，failures 包含全量明细。"""
        code, data, err = self._run_cli_in_process([str(self.fail_dir), "--json", "--size", "100x60"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="prepare")
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["items"], [])
        self._assert_failure_items_schema(data["failures"])

    def test_schema_contract_check_all_failure(self):
        """测试 check --check --json 全量失败路径：items 为空列表，failures 包含全量明细。"""
        code, data, err = self._run_cli_in_process([str(self.seam_dir), "--check", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "")

        self._assert_root_schema(data, mode="check")
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 2)
        self.assertFalse(data["partial_success"])
        self.assertEqual(data["items"], [])
        self._assert_failure_items_schema(data["failures"])

    def test_schema_contract_quiet_and_verbose_combinations(self):
        """测试 quiet/verbose 组合在 prepare 与 check 模式下，schema 与数据 100% 保持一致。"""
        flag_sets = [
            [],
            ["--quiet"],
            ["-q"],
            ["--verbose"],
            ["-v"],
        ]

        # 1. prepare 模式在 5 种参数组合下的 schema 一致性
        base_prep_data = None
        for flags in flag_sets:
            code, data, err = self._run_cli_in_process([str(self.clean_dir), "--json", "--size", "100x60", *flags])
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self._assert_root_schema(data, mode="prepare")
            if base_prep_data is None:
                base_prep_data = data
            else:
                self.assertEqual(data, base_prep_data, f"prepare 模式下参数 {flags} 改变了 JSON 输出语义")

        # 2. check 模式在 5 种参数组合下的 schema 一致性
        base_chk_data = None
        for flags in flag_sets:
            code, data, err = self._run_cli_in_process([str(self.clean_dir), "--check", "--json", "--size", "120x80", *flags])
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self._assert_root_schema(data, mode="check")
            if base_chk_data is None:
                base_chk_data = data
            else:
                self.assertEqual(data, base_chk_data, f"check 模式下参数 {flags} 改变了 JSON 输出语义")

        # 3. 失败场景下 quiet 与 verbose 的 schema 一致性
        base_fail_data = None
        for flags in flag_sets:
            code, data, err = self._run_cli_in_process([str(self.partial_dir), "--json", "--size", "100x60", *flags])
            self.assertEqual(code, 1)
            self.assertEqual(err, "")
            self._assert_root_schema(data, mode="prepare")
            if base_fail_data is None:
                base_fail_data = data
            else:
                self.assertEqual(data, base_fail_data, f"失败场景下参数 {flags} 改变了 JSON 输出语义")

    def test_schema_contract_success_and_failure_paths_consistency(self):
        """确认 success 与 failure 路径的顶层字段集合完全一致，类型完全一致，防止条件分支造成字段缺失。"""
        # Prepare 模式成功 vs 失败
        code_s, data_s, _ = self._run_cli_in_process([str(self.clean_dir), "--json", "--size", "100x60"])
        code_f, data_f, _ = self._run_cli_in_process([str(self.fail_dir), "--json", "--size", "100x60"])
        self.assertEqual(set(data_s.keys()), set(data_f.keys()))
        for key in data_s:
            self.assertIs(type(data_s[key]), type(data_f[key]), f"字段 {key} 在成功与失败路径之间发生了类型漂移！")

        # Check 模式成功 vs 失败
        code_cs, data_cs, _ = self._run_cli_in_process([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        code_cf, data_cf, _ = self._run_cli_in_process([str(self.seam_dir), "--check", "--json"])
        self.assertEqual(set(data_cs.keys()), set(data_cf.keys()))
        for key in data_cs:
            self.assertIs(type(data_cs[key]), type(data_cf[key]), f"check 模式字段 {key} 在成功与失败路径间发生了类型漂移！")

    def test_failure_item_structure_comprehensive_error_codes(self):
        """针对多类错误码（不存在、空文件、损坏、接缝残留、尺寸不符、参数异常），
        检验每个 failure item 的结构均严格固定为 (file, name, code, reason)。
        """
        all_collected_failures = []

        # 1. 不存在文件与目录错误 (FILE_NOT_FOUND, TARGET_RESOLUTION_ERROR)
        res_fnf = check_images(self.dir_path / "non_existing_9999.png", verbose=False)
        all_collected_failures.extend(res_fnf["failures"])

        # 2. 空文件 (EMPTY_FILE) 与损坏文件 (UNREADABLE_IMAGE)
        res_corrupt = check_images(self.fail_dir, verbose=False)
        all_collected_failures.extend(res_corrupt["failures"])

        # 3. 接缝残留 (SEAM_DETECTED)
        res_seam = check_images(self.seam_dir, verbose=False)
        all_collected_failures.extend(res_seam["failures"])

        # 4. 尺寸不匹配 (DIMENSION_MISMATCH)
        res_dim = check_images(self.clean1, size=(500, 300), verbose=False)
        all_collected_failures.extend(res_dim["failures"])

        # 5. 接缝且尺寸不匹配 (SEAM_AND_DIMENSION_MISMATCH)
        res_both = check_images(self.seam_dir / "seam1.png", size=(500, 300), verbose=False)
        all_collected_failures.extend(res_both["failures"])

        # 6. prepare 失败 (PREPARE_ERROR)
        res_prep_err = prepare_images(self.fail_dir, size=(100, 60), apply=False, verbose=False)
        all_collected_failures.extend(res_prep_err["failures"])

        self.assertGreaterEqual(len(all_collected_failures), 6)
        self._assert_failure_items_schema(all_collected_failures)

        # 验证涵盖的核心错误码均已真实触发
        codes = {f["code"] for f in all_collected_failures}
        expected_sample_codes = {
            "FILE_NOT_FOUND",
            "EMPTY_FILE",
            "UNREADABLE_IMAGE",
            "SEAM_DETECTED",
            "DIMENSION_MISMATCH",
            "SEAM_AND_DIMENSION_MISMATCH",
        }
        self.assertTrue(expected_sample_codes.issubset(codes), f"错误码覆盖不足: {codes}")

    def test_real_cli_subprocess_schema_contract(self):
        """通过独立系统子进程执行 CLI，全量验证真实环境下的 schema/version 契约。"""
        # 1. prepare 成功
        c1, d1, e1 = self._run_cli_subprocess([str(self.clean_dir), "--json", "--size", "100x60"])
        self.assertEqual(c1, 0)
        self.assertEqual(e1, "")
        self._assert_root_schema(d1, mode="prepare")
        self._assert_prepare_success_items_schema(d1["items"])

        # 2. prepare 部分失败
        c2, d2, e2 = self._run_cli_subprocess([str(self.partial_dir), "--json", "--size", "100x60"])
        self.assertEqual(c2, 1)
        self.assertEqual(e2, "")
        self._assert_root_schema(d2, mode="prepare")
        self._assert_failure_items_schema(d2["failures"])
        self._assert_prepare_success_items_schema(d2["items"])

        # 3. check 成功
        c3, d3, e3 = self._run_cli_subprocess([str(self.clean_dir), "--check", "--json", "--size", "120x80"])
        self.assertEqual(c3, 0)
        self.assertEqual(e3, "")
        self._assert_root_schema(d3, mode="check")
        self._assert_check_success_items_schema(d3["items"])

        # 4. check 部分失败
        c4, d4, e4 = self._run_cli_subprocess([str(self.seam_partial_dir), "--check", "--json"])
        self.assertEqual(c4, 1)
        self.assertEqual(e4, "")
        self._assert_root_schema(d4, mode="check")
        self._assert_failure_items_schema(d4["failures"])

        # 5. quiet 与 verbose 组合子进程
        c_q, d_q, e_q = self._run_cli_subprocess([str(self.clean_dir), "--json", "--size", "100x60", "--quiet"])
        c_v, d_v, e_v = self._run_cli_subprocess([str(self.clean_dir), "--json", "--size", "100x60", "--verbose"])
        self.assertEqual(c_q, 0)
        self.assertEqual(c_v, 0)
        self.assertEqual(e_q, "")
        self.assertEqual(e_v, "")
        self.assertEqual(d_q, d_v)
        self._assert_root_schema(d_q, mode="prepare")


class TestJSONV1IndependentConsumerContract(unittest.TestCase):
    """验证网页 ChatGPT 指定的 JSON v1 独立消费者兼容性门禁。

    设计规范：
    1. 与 BatchResult、SCHEMA_VERSION 及内部契约常量完全解耦；
    2. 喂入真实 CLI 子进程 stdout，覆盖 success、failure、partial-success；
    3. 检验消费者对 schema_version、计数、failures[].(file, name, code, reason) 的读取能力；
    4. 检验对未知额外字段的完全容忍；
    5. 检验对缺失必需字段、基础类型错误及 schema_version != 1 的明确拒绝。
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 干净有效图片目录 (success)
        self.clean_dir = self.dir_path / "clean_dir"
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.clean_dir / "c1.png", width=120, height=80)
        create_test_image(self.clean_dir / "c2.png", width=120, height=80)

        # 2. 失败图片目录 (failure)
        self.fail_dir = self.dir_path / "fail_dir"
        self.fail_dir.mkdir(parents=True, exist_ok=True)
        (self.fail_dir / "bad_empty.png").write_bytes(b"")
        (self.fail_dir / "bad_corrupt.png").write_bytes(b"BAD_IMAGE_DATA\x00\x01\x02")

        # 3. 混合图片目录 (partial-success)
        self.partial_dir = self.dir_path / "partial_dir"
        self.partial_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.partial_dir / "good.png", width=120, height=80)
        (self.partial_dir / "empty.png").write_bytes(b"")

        # 4. 接缝失败目录 (check failure)
        self.seam_dir = self.dir_path / "seam_dir"
        self.seam_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.seam_dir / "s1.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)
        create_test_image(self.seam_dir / "s2.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 5. 接缝混合目录 (check partial-success)
        self.seam_partial_dir = self.dir_path / "seam_partial_dir"
        self.seam_partial_dir.mkdir(parents=True, exist_ok=True)
        create_test_image(self.seam_partial_dir / "sp_clean.png", width=120, height=80)
        create_test_image(self.seam_partial_dir / "sp_seam.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_cli_subprocess_raw(self, argv: list[str]) -> tuple[int, str, str]:
        """执行真实系统 CLI 子进程，原样返回退出码与原始标准输出/标准错误。"""
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [str(PYTHON_BIN), str(SCRIPT_PATH), *argv],
            capture_output=True,
            text=True,
            env=full_env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_real_cli_subprocess_success_parsed_by_independent_consumer(self):
        """真实 CLI 子进程 success 场景喂给独立 consumer：
        验证 consumer 正确解析 schema_version=1、ok=True、计数，且无 failure。
        """
        # prepare 模式成功
        code, stdout, stderr = self._run_cli_subprocess_raw(
            [str(self.clean_dir), "--json", "--size", "100x60"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        consumer_res = parse_v1_json(stdout)
        self.assertEqual(consumer_res.schema_version, 1)
        self.assertIs(consumer_res.ok, True)
        self.assertEqual(consumer_res.total, 2)
        self.assertEqual(consumer_res.success_count, 2)
        self.assertEqual(consumer_res.failure_count, 0)
        self.assertEqual(len(consumer_res.failures), 0)
        self.assertEqual(len(consumer_res.items), 2)
        # 兼容字典访问语法
        self.assertEqual(consumer_res["schema_version"], 1)
        self.assertIs(consumer_res["ok"], True)
        self.assertEqual(consumer_res["total"], 2)

        # check 模式成功
        code_c, stdout_c, stderr_c = self._run_cli_subprocess_raw(
            [str(self.clean_dir), "--check", "--json", "--size", "120x80"]
        )
        self.assertEqual(code_c, 0)
        self.assertEqual(stderr_c, "")
        consumer_chk = parse_v1_json(stdout_c)
        self.assertEqual(consumer_chk.schema_version, 1)
        self.assertIs(consumer_chk.ok, True)
        self.assertEqual(consumer_chk.total, 2)
        self.assertEqual(consumer_chk.success_count, 2)
        self.assertEqual(consumer_chk.failure_count, 0)
        self.assertEqual(len(consumer_chk.failures), 0)

    def test_real_cli_subprocess_failure_parsed_by_independent_consumer(self):
        """真实 CLI 子进程 failure 场景喂给独立 consumer：
        验证 consumer 正确解析 schema_version=1、ok=False、计数，
        并能逐一读取 failures[].file/name/code/reason。
        """
        # prepare 模式全失败
        code, stdout, stderr = self._run_cli_subprocess_raw(
            [str(self.fail_dir), "--json", "--size", "100x60"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        res = parse_v1_json(stdout)
        self.assertEqual(res.schema_version, 1)
        self.assertIs(res.ok, False)
        self.assertEqual(res.total, 2)
        self.assertEqual(res.success_count, 0)
        self.assertEqual(res.failure_count, 2)
        self.assertEqual(len(res.failures), 2)

        # 逐项验证 consumer 读取 failures 结构的能力（属性访问与字典下标均支持）
        for f in res.failures:
            self.assertIsInstance(f, V1ConsumerFailure)
            self.assertIsInstance(f.file, str)
            self.assertGreater(len(f.file), 0)
            self.assertIsInstance(f.name, str)
            self.assertGreater(len(f.name), 0)
            self.assertIsInstance(f.code, str)
            self.assertGreater(len(f.code), 0)
            self.assertIsInstance(f.reason, str)
            self.assertGreater(len(f.reason), 0)
            # 字典语法对齐
            self.assertEqual(f["file"], f.file)
            self.assertEqual(f["name"], f.name)
            self.assertEqual(f["code"], f.code)
            self.assertEqual(f["reason"], f.reason)

        fail_names = {f.name for f in res.failures}
        self.assertEqual(fail_names, {"bad_empty.png", "bad_corrupt.png"})

        # check 模式接缝门禁全失败
        code_s, stdout_s, _ = self._run_cli_subprocess_raw(
            [str(self.seam_dir), "--check", "--json"]
        )
        self.assertEqual(code_s, 1)
        res_s = parse_v1_json(stdout_s)
        self.assertEqual(res_s.schema_version, 1)
        self.assertIs(res_s.ok, False)
        self.assertEqual(res_s.failure_count, 2)
        for f in res_s.failures:
            self.assertEqual(f.code, "SEAM_DETECTED")
            self.assertIn("接缝", f.reason)

        # 单文件不存在失败
        code_nf, stdout_nf, _ = self._run_cli_subprocess_raw(
            ["non_existing_9999.png", "--json"]
        )
        self.assertEqual(code_nf, 1)
        res_nf = parse_v1_json(stdout_nf)
        self.assertEqual(res_nf.schema_version, 1)
        self.assertIs(res_nf.ok, False)
        self.assertEqual(res_nf.failure_count, 1)
        self.assertEqual(res_nf.failures[0].code, "FILE_NOT_FOUND")

    def test_real_cli_subprocess_partial_success_parsed_by_independent_consumer(self):
        """真实 CLI 子进程 partial-success 场景喂给独立 consumer：
        验证 consumer 能准确读取混合状态下的 success/failure 计数与局部失败详情。
        """
        # prepare 混合模式 (1 成功 1 失败)
        code, stdout, stderr = self._run_cli_subprocess_raw(
            [str(self.partial_dir), "--json", "--size", "100x60"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(stderr, "")
        res = parse_v1_json(stdout)
        self.assertEqual(res.schema_version, 1)
        self.assertIs(res.ok, False)
        self.assertEqual(res.total, 2)
        self.assertEqual(res.success_count, 1)
        self.assertEqual(res.failure_count, 1)
        self.assertEqual(len(res.failures), 1)

        f0 = res.failures[0]
        self.assertEqual(f0.name, "empty.png")
        self.assertEqual(f0.code, "EMPTY_FILE")
        self.assertIn("0 字节", f0.reason)
        self.assertGreater(len(f0.reason), 0)

        # check 混合模式 (1 干净 1 接缝)
        code_cp, stdout_cp, _ = self._run_cli_subprocess_raw(
            [str(self.seam_partial_dir), "--check", "--json"]
        )
        self.assertEqual(code_cp, 1)
        res_cp = parse_v1_json(stdout_cp)
        self.assertEqual(res_cp.schema_version, 1)
        self.assertIs(res_cp.ok, False)
        self.assertEqual(res_cp.total, 2)
        self.assertEqual(res_cp.success_count, 1)
        self.assertEqual(res_cp.failure_count, 1)
        self.assertEqual(len(res_cp.failures), 1)
        self.assertEqual(res_cp.failures[0].name, "sp_seam.png")
        self.assertEqual(res_cp.failures[0].code, "SEAM_DETECTED")

    def test_consumer_tolerates_unknown_extra_fields(self):
        """验证独立 consumer 对未知额外字段的前向兼容与完全容忍（顶层与 failures 内均不应报错）。"""
        payload = {
            "schema_version": 1,
            "ok": False,
            "total": 5,
            "success_count": 4,
            "failure_count": 1,
            "failures": [
                {
                    "file": "/path/to/img.png",
                    "name": "img.png",
                    "code": "CUSTOM_GATE_FAIL",
                    "reason": "gate triggered",
                    "unexpected_failure_meta": {"timestamp": 12345678, "level": "WARN"},
                    "retry_count": 3,
                }
            ],
            # 未知扩展字段
            "future_spec_v1_patch": True,
            "orchestrator_node_id": "worker-09",
            "extended_metrics": {"avg_time_ms": 42.1},
        }

        # 字符串形式与字典形式均能安全解析，不抛出任何异常
        res = parse_v1_json(json.dumps(payload))
        self.assertEqual(res.schema_version, 1)
        self.assertIs(res.ok, False)
        self.assertEqual(res.total, 5)
        self.assertEqual(res.success_count, 4)
        self.assertEqual(res.failure_count, 1)
        self.assertEqual(len(res.failures), 1)

        f = res.failures[0]
        self.assertEqual(f.file, "/path/to/img.png")
        self.assertEqual(f.name, "img.png")
        self.assertEqual(f.code, "CUSTOM_GATE_FAIL")
        self.assertEqual(f.reason, "gate triggered")
        self.assertEqual(f["retry_count"], 3)
        self.assertEqual(f.extra["unexpected_failure_meta"]["level"], "WARN")

        # 根字典扩展字段能够透过 raw 或下标安全读取
        self.assertEqual(res["future_spec_v1_patch"], True)
        self.assertEqual(res.raw["orchestrator_node_id"], "worker-09")
        self.assertEqual(res.get("extended_metrics"), {"avg_time_ms": 42.1})

    def test_consumer_rejects_missing_required_fields(self):
        """验证缺少必需字段时 consumer 明确抛出 V1ConsumerError 异常拒绝。"""
        valid_base = {
            "schema_version": 1,
            "ok": True,
            "total": 0,
            "success_count": 0,
            "failure_count": 0,
            "failures": [],
        }

        # 顶层缺少必需字段
        for missing_key in ("schema_version", "ok", "total", "success_count", "failure_count", "failures"):
            mutated = dict(valid_base)
            del mutated[missing_key]
            with self.assertRaises(V1ConsumerError, msg=f"缺少顶层字段 {missing_key} 应拒绝") as ctx:
                parse_v1_json(json.dumps(mutated))
            self.assertIn("缺少必需字段", str(ctx.exception))

        # failures 内部缺少必需字段
        for missing_fkey in ("file", "name", "code", "reason"):
            bad_item = {
                "file": "/a/b.png",
                "name": "b.png",
                "code": "ERR",
                "reason": "bad image",
            }
            del bad_item[missing_fkey]
            mutated = dict(valid_base)
            mutated["failures"] = [bad_item]
            with self.assertRaises(V1ConsumerError, msg=f"failures 缺少项字段 {missing_fkey} 应拒绝") as ctx:
                parse_v1_json(mutated)
            self.assertIn(f"缺失必需字段: '{missing_fkey}'", str(ctx.exception))

    def test_consumer_rejects_basic_type_errors(self):
        """验证基础类型不匹配时 consumer 明确抛出 V1ConsumerError 异常拒绝。"""
        base = {
            "schema_version": 1,
            "ok": True,
            "total": 1,
            "success_count": 1,
            "failure_count": 0,
            "failures": [],
        }

        # ok 不是 bool (如整型 1、0 或字符串 "true")
        for bad_ok in (1, 0, "true", "False", None, []):
            d = dict(base, ok=bad_ok)
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(d)

        # 计数不是严格整型或为负数
        for bad_count in ("1", 1.5, True, False, None, -1):
            d1 = dict(base, total=bad_count)
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(d1)
            d2 = dict(base, success_count=bad_count)
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(d2)
            d3 = dict(base, failure_count=bad_count)
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(d3)

        # failures 不是 list
        for bad_failures in ("not_a_list", 123, None, {}):
            d = dict(base, failures=bad_failures)
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(d)

        # failures 中的项不是 dict
        d = dict(base, failures=["string_item"])
        with self.assertRaises(V1ConsumerError):
            parse_v1_json(d)

        # failures 中的项字段类型不为 str
        for bad_str in (123, True, None, [], {}):
            item_bad_file = {"file": bad_str, "name": "n", "code": "C", "reason": "R"}
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(dict(base, failures=[item_bad_file]))

            item_bad_code = {"file": "f", "name": "n", "code": bad_str, "reason": "R"}
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(dict(base, failures=[item_bad_code]))

    def test_consumer_rejects_schema_version_mismatch(self):
        """验证 schema_version != 1 或类型非严格整型时明确拒绝。"""
        base = {
            "schema_version": 1,
            "ok": True,
            "total": 0,
            "success_count": 0,
            "failure_count": 0,
            "failures": [],
        }

        # 版本非 1
        for bad_ver in (0, 2, -1, 99):
            d = dict(base, schema_version=bad_ver)
            with self.assertRaises(V1ConsumerError) as ctx:
                parse_v1_json(d)
            self.assertIn("不支持的 schema_version", str(ctx.exception))

        # 版本类型非严格 int
        for bad_ver_type in ("1", 1.0, True, False, None, [1]):
            d = dict(base, schema_version=bad_ver_type)
            with self.assertRaises(V1ConsumerError) as ctx:
                parse_v1_json(d)
            self.assertIn("schema_version", str(ctx.exception))

    def test_consumer_rejects_malformed_json_and_non_dict_root(self):
        """验证非合法 JSON 或根节点不是字典时明确拒绝。"""
        for malformed in ("{bad json", "[1, 2, 3]", "42", "true", "null", ""):
            with self.assertRaises(V1ConsumerError):
                parse_v1_json(malformed)

        with self.assertRaises(V1ConsumerError):
            parse_v1_json([{"schema_version": 1}])
        with self.assertRaises(V1ConsumerError):
            parse_v1_json(12345)




class TestCLIProcessExitContract(unittest.TestCase):
    """测试并锁定 CLI 进程级退出契约与真实 subprocess 行为。

    严格遵循当前系统稳定语义，禁止凭空设计新退出码：
    - 进程退出码 0：所有指定目标均处理/检验成功 (ok=True)
    - 进程退出码 1：合法调用但发生业务/图片失败、门禁不通过或参数值校验失败 (ok=False)
    - 进程退出码 2：未知命令行参数或 argparse 语法错误 (保持标准语义，不强行 JSON)
    - 绝不凭空发明冲突参数组合；非法参数配合 --apply 稳定失败且无半执行
    - quiet/verbose 组合不改变进程退出码分类和 stdout JSON 契约
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

        # 1. 正常有效单图与全成功目录
        self.clean_single = self.dir_path / "clean_single.png"
        create_test_image(self.clean_single, width=120, height=80)

        self.clean_dir = self.dir_path / "clean_dir"
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        self.clean_img1 = self.clean_dir / "clean_1.png"
        self.clean_img2 = self.clean_dir / "clean_2.png"
        create_test_image(self.clean_img1, width=120, height=80)
        create_test_image(self.clean_img2, width=120, height=80)

        # 2. 缺失文件
        self.missing_file = self.dir_path / "non_existent_image_12345.png"

        # 3. 0 字节空文件与非图片损坏文件
        self.empty_file = self.dir_path / "empty_0byte.png"
        self.empty_file.write_bytes(b"")

        self.corrupt_file = self.dir_path / "corrupt_data.png"
        self.corrupt_file.write_bytes(b"NOT_A_PNG_IMAGE_DATA\x00\x01\x02")

        # 4. 接缝门禁失败图
        self.seam_file = self.dir_path / "seam_bad.png"
        create_test_image(self.seam_file, width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 5. 混合批量目录 (部分失败: 2 成功 + 3 失败)
        self.mixed_dir = self.dir_path / "mixed_batch"
        self.mixed_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.clean_single, self.mixed_dir / "m_clean1.png")
        shutil.copy2(self.clean_single, self.mixed_dir / "m_clean2.png")
        (self.mixed_dir / "m_empty.png").write_bytes(b"")
        (self.mixed_dir / "m_corrupt.png").write_bytes(b"CORRUPT")
        create_test_image(self.mixed_dir / "m_seam.png", width=120, height=80, left_val=20, right_val=60, seam_x=60)

        # 6. 全失败批量目录 (2 坏图)
        self.all_fail_dir = self.dir_path / "all_fail_batch"
        self.all_fail_dir.mkdir(parents=True, exist_ok=True)
        (self.all_fail_dir / "f_empty.png").write_bytes(b"")
        (self.all_fail_dir / "f_corrupt.png").write_bytes(b"CORRUPT")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_cli(self, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        if env:
            full_env.update(env)
        return subprocess.run(
            [str(PYTHON_BIN), str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=full_env,
        )

    def test_normal_check_json_success_exit_code_zero_and_clean_stdout_stderr(self):
        """1) 覆盖正常 --check --json 成功时：rc=0、stdout 可解析为合法 JSON v1、stderr 严格不污染。"""
        # A. 单张正常有效图片 --check --json
        p_single = self._run_cli([str(self.clean_single), "--check", "--json"])
        self.assertEqual(p_single.returncode, 0, f"单图成功门禁返回码应为 0，实际为 {p_single.returncode}")
        self.assertEqual(p_single.stderr, "", f"成功退出时 stderr 必须严格为空，实际有输出: {p_single.stderr}")
        res_single = parse_v1_json(p_single.stdout)
        self.assertEqual(res_single.schema_version, 1)
        self.assertTrue(res_single.ok)
        self.assertEqual(res_single.total, 1)
        self.assertEqual(res_single.success_count, 1)
        self.assertEqual(res_single.failure_count, 0)
        self.assertEqual(res_single.failures, [])
        self.assertEqual(len(res_single.items), 1)

        # stdout 纯净无人类日志杂质
        for marker in ["[预演]", "✓", "ALL CLEAR", "❌", "🔍", "[!]", "[提示]"]:
            self.assertNotIn(marker, p_single.stdout)

        # B. 目录批量有效图片 --check --json
        p_dir = self._run_cli([str(self.clean_dir), "--check", "--json"])
        self.assertEqual(p_dir.returncode, 0, f"目录成功门禁返回码应为 0，实际为 {p_dir.returncode}")
        self.assertEqual(p_dir.stderr, "", f"成功退出时 stderr 必须严格为空，实际有输出: {p_dir.stderr}")
        res_dir = parse_v1_json(p_dir.stdout)
        self.assertEqual(res_dir.schema_version, 1)
        self.assertTrue(res_dir.ok)
        self.assertEqual(res_dir.total, 2)
        self.assertEqual(res_dir.success_count, 2)
        self.assertEqual(res_dir.failure_count, 0)
        self.assertEqual(res_dir.failures, [])

        # C. 常规 prepare --json 成功路径作为对照
        p_prep = self._run_cli([str(self.clean_single), "--json"])
        self.assertEqual(p_prep.returncode, 0)
        self.assertEqual(p_prep.stderr, "")
        res_prep = parse_v1_json(p_prep.stdout)
        self.assertTrue(res_prep.ok)

    def test_real_10_images_check_json_success_contract(self):
        """1) 覆盖项目中真实 10 图资产运行 --check --json 的进程级退出码与 stdout/stderr 契约。"""
        real_img_dir = REPO_ROOT / "projects" / "agentflow-os-launch" / "images"
        if not real_img_dir.is_dir():
            self.skipTest(f"真实图片目录不存在: {real_img_dir}")

        p = self._run_cli([str(real_img_dir), "--check", "--json"])
        self.assertEqual(p.returncode, 0, f"10 图门禁返回码必须为 0，实际为 {p.returncode}")
        self.assertEqual(p.stderr, "", f"10 图门禁 stderr 不得有污染输出，实际为: {p.stderr}")
        res = parse_v1_json(p.stdout)
        self.assertEqual(res.schema_version, 1)
        self.assertTrue(res.ok)
        self.assertEqual(res.total, 10)
        self.assertEqual(res.success_count, 10)
        self.assertEqual(res.failure_count, 0)
        self.assertEqual(len(res.failures), 0)
        self.assertEqual(len(res.items), 10)

    def test_legal_invocation_business_failure_exit_code_one_and_json_v1(self):
        """2) 覆盖合法调用但业务/图片失败时：rc=1、stdout 可解析为合规 JSON v1、stderr 不污染。"""
        # A. 缺失文件 --check --json
        p_c_missing = self._run_cli([str(self.missing_file), "--check", "--json"])
        self.assertEqual(p_c_missing.returncode, 1, "缺失文件时 rc 必须稳定为 1 (禁止凭空发明退出码)")
        self.assertEqual(p_c_missing.stderr, "", "--json 模式下 stderr 不受人类日志污染")
        res_c_missing = parse_v1_json(p_c_missing.stdout)
        self.assertFalse(res_c_missing.ok)
        self.assertEqual(res_c_missing.failure_count, 1)
        self.assertEqual(res_c_missing.failures[0].code, "FILE_NOT_FOUND")

        # B. 缺失文件 prepare --json
        p_p_missing = self._run_cli([str(self.missing_file), "--json"])
        self.assertEqual(p_p_missing.returncode, 1)
        self.assertEqual(p_p_missing.stderr, "")
        res_p_missing = parse_v1_json(p_p_missing.stdout)
        self.assertFalse(res_p_missing.ok)
        self.assertEqual(res_p_missing.failure_count, 1)
        self.assertEqual(res_p_missing.failures[0].code, "FILE_NOT_FOUND")

        # C. 0 字节空文件 --check --json
        p_c_empty = self._run_cli([str(self.empty_file), "--check", "--json"])
        self.assertEqual(p_c_empty.returncode, 1)
        self.assertEqual(p_c_empty.stderr, "")
        res_c_empty = parse_v1_json(p_c_empty.stdout)
        self.assertFalse(res_c_empty.ok)
        self.assertEqual(res_c_empty.failures[0].code, "EMPTY_FILE")

        # D. 损坏非图片文件 --check --json
        p_c_corrupt = self._run_cli([str(self.corrupt_file), "--check", "--json"])
        self.assertEqual(p_c_corrupt.returncode, 1)
        self.assertEqual(p_c_corrupt.stderr, "")
        res_c_corrupt = parse_v1_json(p_c_corrupt.stdout)
        self.assertFalse(res_c_corrupt.ok)
        self.assertEqual(res_c_corrupt.failures[0].code, "UNREADABLE_IMAGE")

        # E. 存在残留接缝 --check --json
        p_c_seam = self._run_cli([str(self.seam_file), "--check", "--json"])
        self.assertEqual(p_c_seam.returncode, 1)
        self.assertEqual(p_c_seam.stderr, "")
        res_c_seam = parse_v1_json(p_c_seam.stdout)
        self.assertFalse(res_c_seam.ok)
        self.assertEqual(res_c_seam.failures[0].code, "SEAM_DETECTED")

        # F. 尺寸不符合门禁要求 --check --json --size 999x999
        p_c_size = self._run_cli([str(self.clean_single), "--check", "--json", "--size", "999x999"])
        self.assertEqual(p_c_size.returncode, 1)
        self.assertEqual(p_c_size.stderr, "")
        res_c_size = parse_v1_json(p_c_size.stdout)
        self.assertFalse(res_c_size.ok)
        self.assertEqual(res_c_size.failures[0].code, "DIMENSION_MISMATCH")

        # G. 批量部分失败目录 --check --json
        p_c_mixed = self._run_cli([str(self.mixed_dir), "--check", "--json"])
        self.assertEqual(p_c_mixed.returncode, 1)
        self.assertEqual(p_c_mixed.stderr, "")
        res_c_mixed = parse_v1_json(p_c_mixed.stdout)
        self.assertFalse(res_c_mixed.ok)
        self.assertEqual(res_c_mixed.total, 5)
        self.assertEqual(res_c_mixed.success_count, 2)
        self.assertEqual(res_c_mixed.failure_count, 3)
        self.assertTrue(res_c_mixed["partial_success"])

        # H. 批量全失败目录 --check --json
        p_c_all_fail = self._run_cli([str(self.all_fail_dir), "--check", "--json"])
        self.assertEqual(p_c_all_fail.returncode, 1)
        self.assertEqual(p_c_all_fail.stderr, "")
        res_c_all_fail = parse_v1_json(p_c_all_fail.stdout)
        self.assertFalse(res_c_all_fail.ok)
        self.assertEqual(res_c_all_fail.total, 2)
        self.assertEqual(res_c_all_fail.success_count, 0)
        self.assertEqual(res_c_all_fail.failure_count, 2)

    def test_unknown_arguments_argparse_usage_error_semantics(self):
        """3) 覆盖未知参数/argparse usage-error：保持当前稳定语义 (rc=2)，stderr 输出用法，绝不强行 JSON。"""
        # A. 独立未知参数
        p_unknown = self._run_cli(["--unknown-parameter-flag-98765"])
        self.assertEqual(p_unknown.returncode, 2, "argparse 未知参数错误返回码必须稳定为 2")
        self.assertEqual(p_unknown.stdout, "", "未知参数下 stdout 必须为空，严禁强行输出 JSON")
        self.assertIn("usage: prepare_agnes_image.py", p_unknown.stderr)
        self.assertIn("unrecognized arguments", p_unknown.stderr)

        # B. 未知参数配合 --json 选项：仍应保持 argparse 错误契约，不得强行输出 JSON
        p_unknown_json = self._run_cli(["--unknown-parameter-flag-98765", "--json"])
        self.assertEqual(p_unknown_json.returncode, 2)
        self.assertEqual(p_unknown_json.stdout, "", "即使指定了 --json，未知参数仍必须保持 stdout 为空")
        self.assertIn("usage: prepare_agnes_image.py", p_unknown_json.stderr)

        # C. 未知短参数
        p_unknown_short = self._run_cli(["-z"])
        self.assertEqual(p_unknown_short.returncode, 2)
        self.assertEqual(p_unknown_short.stdout, "")
        self.assertIn("usage: prepare_agnes_image.py", p_unknown_short.stderr)

        # D. --check --json 配合未知参数
        p_check_unknown = self._run_cli(["--check", "--json", "--bad-flag-xyz"])
        self.assertEqual(p_check_unknown.returncode, 2)
        self.assertEqual(p_check_unknown.stdout, "")
        self.assertIn("usage: prepare_agnes_image.py", p_check_unknown.stderr)

        # E. 未知参数配合 --quiet 与 -q：argparse 在参数解析阶段退出，usage 诊断正常输出至 stderr
        p_unknown_quiet = self._run_cli(["--unknown-flag-quiet", "--quiet"])
        self.assertEqual(p_unknown_quiet.returncode, 2)
        self.assertEqual(p_unknown_quiet.stdout, "")
        self.assertIn("usage: prepare_agnes_image.py", p_unknown_quiet.stderr)

        p_unknown_q = self._run_cli(["--unknown-flag-q", "-q"])
        self.assertEqual(p_unknown_q.returncode, 2)
        self.assertEqual(p_unknown_q.stdout, "")
        self.assertIn("usage: prepare_agnes_image.py", p_unknown_q.stderr)

    def test_no_invented_conflicts_and_validation_error_prevents_partial_execution(self):
        """4) 覆盖 CLI 参数冲突契约：不凭空发明冲突组合；非法参数配合 --apply 稳定失败且零半执行。"""
        # A. 确认当前 CLI 不存在凭空编造的互斥组合：正交合法参数可和谐共存
        # 例如 --check 与合法 --size、合法 raw 路径、--verbose/--quiet 正常共存
        p_valid_coexist = self._run_cli([str(self.clean_single), "--check", "--size", "120x80", "--verbose"])
        self.assertEqual(p_valid_coexist.returncode, 0)

        # B. 验证非法参数组合/校验失败时：稳定失败 (rc=1 或 rc=2) 且绝不发生半执行 (无文件篡改、无备份生成)
        original_bytes = b"ORIGINAL_ATOMIC_PROTECTED_DATA"
        atomic_file = self.dir_path / "atomic_target.png"
        atomic_file.write_bytes(original_bytes)

        # Case 1: 非法 --size 配合 --apply 写盘模式
        p_bad_size = self._run_cli([str(atomic_file), "--apply", "--size", "invalid_size_format"])
        self.assertEqual(p_bad_size.returncode, 1)
        self.assertEqual(p_bad_size.stdout, "")
        self.assertIn("尺寸格式无效", p_bad_size.stderr)
        # 目标文件字节严格未动
        self.assertEqual(atomic_file.read_bytes(), original_bytes)
        # 绝不产生 _pre_* 备份半执行产物
        pre_backups = list(self.dir_path.glob("_pre_*"))
        self.assertEqual(pre_backups, [], f"非法参数时不得创建任何 _pre_* 备份: {pre_backups}")

        # Case 2: 非法 --brightness 配合 --apply 写盘模式
        p_bad_bright = self._run_cli([str(atomic_file), "--apply", "--brightness", "-2.0"])
        self.assertEqual(p_bad_bright.returncode, 1)
        self.assertEqual(p_bad_bright.stdout, "")
        self.assertIn("亮度系数必须 >= 0", p_bad_bright.stderr)
        self.assertEqual(atomic_file.read_bytes(), original_bytes)
        self.assertEqual(list(self.dir_path.glob("_pre_*")), [])

        # Case 3: 非法 --seam 配合 --apply 写盘模式
        p_bad_seam = self._run_cli([str(atomic_file), "--apply", "--seam", "bad_col_token"])
        self.assertEqual(p_bad_seam.returncode, 1)
        self.assertEqual(p_bad_seam.stdout, "")
        self.assertIn("无效的接缝列号", p_bad_seam.stderr)
        self.assertEqual(atomic_file.read_bytes(), original_bytes)
        self.assertEqual(list(self.dir_path.glob("_pre_*")), [])

        # Case 4: 不存在的 --manifest 配合 --apply 写盘模式
        p_bad_mf = self._run_cli([str(atomic_file), "--apply", "--manifest", "non_existing_manifest_file.json"])
        self.assertEqual(p_bad_mf.returncode, 1)
        self.assertEqual(p_bad_mf.stdout, "")
        self.assertIn("指定的清单路径不存在", p_bad_mf.stderr)
        self.assertEqual(atomic_file.read_bytes(), original_bytes)
        self.assertEqual(list(self.dir_path.glob("_pre_*")), [])

        # Case 5: 未知参数配合 --apply
        p_bad_arg_apply = self._run_cli([str(atomic_file), "--apply", "--unknown-flag-no-exec"])
        self.assertEqual(p_bad_arg_apply.returncode, 2)
        self.assertEqual(p_bad_arg_apply.stdout, "")
        self.assertEqual(atomic_file.read_bytes(), original_bytes)
        self.assertEqual(list(self.dir_path.glob("_pre_*")), [])

    def test_quiet_and_verbose_preserve_exit_classification_and_json_contract(self):
        """5) 覆盖 quiet/verbose 组合不改变退出分类和 stdout JSON 契约。"""
        flag_combinations = [
            [],
            ["--verbose"],
            ["-v"],
            ["--quiet"],
            ["-q"],
            ["--verbose", "--quiet"],
            ["-v", "-q"],
        ]

        # A. 正常成功场景：所有 quiet/verbose 组合退出码均为 0，stdout 解析出的 JSON v1 语义一致，stderr 为空
        p_success_base = self._run_cli([str(self.clean_single), "--check", "--json"])
        self.assertEqual(p_success_base.returncode, 0)
        res_success_base = parse_v1_json(p_success_base.stdout)

        for flags in flag_combinations:
            p = self._run_cli([str(self.clean_single), "--check", "--json", *flags])
            self.assertEqual(p.returncode, 0, f"flags={flags} 时退出码必须为 0")
            self.assertEqual(p.stderr, "", f"flags={flags} 时 stderr 必须为空")
            res = parse_v1_json(p.stdout)
            self.assertEqual(res.ok, res_success_base.ok)
            self.assertEqual(res.total, res_success_base.total)
            self.assertEqual(res.success_count, res_success_base.success_count)
            self.assertEqual(res.failure_count, res_success_base.failure_count)
            self.assertEqual(len(res.failures), len(res_success_base.failures))

        # B. 业务失败场景 (缺失文件)：所有 quiet/verbose 组合退出码均为 1，stdout 解析出的 JSON v1 语义一致，stderr 为空
        p_fail_base = self._run_cli([str(self.missing_file), "--check", "--json"])
        self.assertEqual(p_fail_base.returncode, 1)
        res_fail_base = parse_v1_json(p_fail_base.stdout)

        for flags in flag_combinations:
            p = self._run_cli([str(self.missing_file), "--check", "--json", *flags])
            self.assertEqual(p.returncode, 1, f"flags={flags} 时失败退出码必须为 1")
            self.assertEqual(p.stderr, "", f"flags={flags} 时 --json 失败 stderr 必须为空")
            res = parse_v1_json(p.stdout)
            self.assertEqual(res.ok, res_fail_base.ok)
            self.assertEqual(res.total, res_fail_base.total)
            self.assertEqual(res.failure_count, res_fail_base.failure_count)
            self.assertEqual(res.failures[0].code, res_fail_base.failures[0].code)

        # C. 批量部分失败场景：所有 quiet/verbose 组合退出码均为 1，stdout 解析出的 JSON v1 语义一致，stderr 为空
        p_mixed_base = self._run_cli([str(self.mixed_dir), "--check", "--json"])
        self.assertEqual(p_mixed_base.returncode, 1)
        res_mixed_base = parse_v1_json(p_mixed_base.stdout)

        for flags in flag_combinations:
            p = self._run_cli([str(self.mixed_dir), "--check", "--json", *flags])
            self.assertEqual(p.returncode, 1)
            self.assertEqual(p.stderr, "")
            res = parse_v1_json(p.stdout)
            self.assertEqual(res.total, res_mixed_base.total)
            self.assertEqual(res.success_count, res_mixed_base.success_count)
            self.assertEqual(res.failure_count, res_mixed_base.failure_count)
            self.assertEqual(res.raw["partial_success"], res_mixed_base.raw["partial_success"])

        # D. 常规 prepare --json 业务失败场景
        p_prep_fail_base = self._run_cli([str(self.missing_file), "--json"])
        self.assertEqual(p_prep_fail_base.returncode, 1)
        res_prep_fail_base = parse_v1_json(p_prep_fail_base.stdout)

        for flags in flag_combinations:
            p = self._run_cli([str(self.missing_file), "--json", *flags])
            self.assertEqual(p.returncode, 1)
            self.assertEqual(p.stderr, "")
            res = parse_v1_json(p.stdout)
            self.assertEqual(res.failure_count, res_prep_fail_base.failure_count)

    def test_quiet_suppresses_stderr_on_validation_failure_without_changing_exit_code(self):
        """5b) 验证非法参数在无 --json 时：quiet 模式抑制 stderr，但不改变 rc=1 退出码分类。"""
        # 默认模式：rc=1，stderr 有报错
        p_def = self._run_cli([str(self.clean_single), "--size", "invalid_size"])
        self.assertEqual(p_def.returncode, 1)
        self.assertEqual(p_def.stdout, "")
        self.assertIn("尺寸格式无效", p_def.stderr)

        # verbose 模式：rc=1，stderr 有报错
        p_verb = self._run_cli([str(self.clean_single), "--size", "invalid_size", "--verbose"])
        self.assertEqual(p_verb.returncode, 1)
        self.assertEqual(p_verb.stdout, "")
        self.assertIn("尺寸格式无效", p_verb.stderr)

        # quiet 模式：rc=1 保持不变，stderr 被抑制
        p_quiet = self._run_cli([str(self.clean_single), "--size", "invalid_size", "--quiet"])
        self.assertEqual(p_quiet.returncode, 1, "quiet 模式下退出码必须保持为 1")
        self.assertEqual(p_quiet.stdout, "")
        self.assertEqual(p_quiet.stderr, "", "quiet 模式下 stderr 必须被抑制")

        p_q = self._run_cli([str(self.clean_single), "--size", "invalid_size", "-q"])
        self.assertEqual(p_q.returncode, 1)
        self.assertEqual(p_q.stdout, "")
        self.assertEqual(p_q.stderr, "")


class TestPrepareAgnesImageBaseDir(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.img_dir = self.base / "images"
        self.img_dir.mkdir(parents=True)
        self.img1 = self.img_dir / "slide1.png"
        self.img2 = self.img_dir / "slide2.png"
        create_test_image(self.img1, width=160, height=90)
        create_test_image(self.img2, width=160, height=90)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_image_targets_with_base_dir(self):
        # 1. 相对目录
        res = resolve_image_targets("images", base_dir=self.base)
        self.assertEqual(len(res), 2)
        self.assertEqual({p.name for p in res}, {"slide1.png", "slide2.png"})
        self.assertTrue(all(p.is_absolute() for p in res))

        # 2. 相对单文件
        res_single = resolve_image_targets("images/slide1.png", base_dir=self.base)
        self.assertEqual(len(res_single), 1)
        self.assertEqual(res_single[0].resolve(), self.img1.resolve())

        # 3. None 自发现 base_dir 下的 images
        res_none = resolve_image_targets(None, base_dir=self.base)
        self.assertEqual(len(res_none), 2)

    def test_resolve_manifest_target_with_base_dir(self):
        mf_path = self.img_dir / "image_prompts.json"
        mf_path.write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")

        # 相对路径解析
        resolved = resolve_manifest_target("images/image_prompts.json", base_dir=self.base)
        self.assertEqual(resolved.resolve(), mf_path.resolve())

        # 相对目录解析
        resolved_dir = resolve_manifest_target("images", base_dir=self.base)
        self.assertEqual(resolved_dir.resolve(), mf_path.resolve())

        # None 自发现
        resolved_none = resolve_manifest_target(None, base_dir=self.base)
        self.assertEqual(resolved_none.resolve(), mf_path.resolve())

    def test_check_images_and_run_qa_with_base_dir(self):
        res = check_images("images", size=(160, 90), verbose=False, base_dir=self.base)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 2)

        ok = run_qa_prepared_images("images", size=(160, 90), verbose=False, base_dir=self.base)
        self.assertTrue(ok)

    def test_prepare_agnes_images_with_base_dir(self):
        out_dir = self.base / "out"
        res = prepare_agnes_images(
            targets="images",
            out="out",
            size=(100, 50),
            apply=True,
            base_dir=self.base,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["success_count"], 2)
        self.assertTrue((out_dir / "slide1.png").is_file())
        self.assertTrue((out_dir / "slide2.png").is_file())

    def test_main_cli_with_base_dir_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["images", "--check", "--json", "--base-dir", str(self.base)])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)

    def test_main_function_with_base_dir_kwarg(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["images", "--check", "--json"], base_dir=self.base)
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 2)


if __name__ == "__main__":
    unittest.main()

