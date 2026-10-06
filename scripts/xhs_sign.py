#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs_sign.py —— 小红书 x-s/x-t API 签名封装（第 13 轮迭代）
==========================================================
签名算法来源：Cloxl/xhshow（1081 stars, MIT, pip install xhshow）
https://github.com/Cloxl/xhshow —— 纯 Python 逆向实现，生成
x-s / x-s-common / x-t / x-b3-traceid / x-rap-param 等请求头。

本模块只做薄封装：
  - Cookie 仍只从 ~/.config/ppt-studio/xiaohongshu.json 读取（600 权限校验）
  - 不在任何地方硬编码 Cookie 或输出 Cookie 值

用法：
    from xhs_sign import signed_get_headers, api_search_notes
    headers = signed_get_headers(uri, params, cookies)
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

# 复用 xhs_search 的 Cookie 读取（含 600 权限校验）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from xhs_search import load_cookies  # noqa: E402

try:
    from xhshow import Xhshow
except ImportError:
    # 尝试从本地 .venv site-packages 加载
    _repo_root = Path(__file__).resolve().parent.parent
    _venv_site = list((_repo_root / ".venv" / "lib").glob("python*/site-packages"))
    if _venv_site and str(_venv_site[0]) not in sys.path:
        sys.path.insert(0, str(_venv_site[0]))
    try:
        from xhshow import Xhshow
    except ImportError:
        sys.exit("[error] 缺少 xhshow 库：/home/tom/Work/ppt-studio/.venv/bin/pip install xhshow")

# 搜索 API endpoint（2026-09-30 实测确认）
# edith.xiaohongshu.com/api/sns/web/v1/search/notes 仅支持 POST；
# GET 返回 404 纯文本无法区分路径是否存在，POST + xys 签名返回 HTTP 200。
# so/v2 曾被误认为迁移目标，实测同样 404，已废弃。
SEARCH_API = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def ensure_device_cookies(cookies: dict) -> dict:
    """补齐签名所需的设备标识 cookie（a1/webId，非登录凭证，可本地生成）。"""
    client = Xhshow()
    cookies = dict(cookies)
    if not cookies.get("a1"):
        cookies["a1"] = client.generate_a1()
    if not cookies.get("webId"):
        cookies["webId"] = Xhshow.generate_web_id(cookies["a1"])
    return cookies


def signed_get_headers(uri: str, params: dict, cookies: dict,
                       x_rap: bool = True) -> dict:
    """生成带 x-s/x-t/x-rap-param 的 GET 请求头。

    x_rap=True：搜索/feed/笔记接口必需的风控头（xhshow 文档明确要求）。
    """
    client = Xhshow()
    cookies = ensure_device_cookies(cookies)
    headers = client.sign_headers_get(uri=uri, cookies=cookies,
                                      params=params, x_rap=x_rap)
    headers["User-Agent"] = UA
    headers["Referer"] = "https://www.xiaohongshu.com/"
    headers["Origin"] = "https://www.xiaohongshu.com"
    return headers


def signed_post_headers(uri, payload, cookies, x_rap=True):
    """生成带 x-s/x-t/x-rap-param 的 POST 请求头。

    2026-09-30 实测：搜索接口必须用 POST + 默认 xys 签名格式；
    xyw 格式会被风控以 HTTP 461 拒绝（xhshow 文档称 xyw 用于 user_posted
    类数据接口，但搜索接口实测要求 xys）。
    """
    client = Xhshow()
    cookies = ensure_device_cookies(cookies)
    headers = client.sign_headers_post(uri=uri, cookies=cookies,
                                       payload=payload, x_rap=x_rap)
    headers["User-Agent"] = UA
    headers["Referer"] = "https://www.xiaohongshu.com/"
    headers["Origin"] = "https://www.xiaohongshu.com"
    headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


def build_search_params(keyword: str, page: int = 1, page_size: int = 20) -> dict:
    """构造搜索 API 参数（含 search_id / request_id）。"""
    client = Xhshow()
    return {
        "keyword": keyword,
        "page": page,
        "page_size": page_size,
        "search_id": client.get_search_id(),
        "sort": "general",
        "note_type": 0,
    }


def api_search_notes(keyword: str, max_n: int = 10,
                     cookies: dict | None = None,
                     key_file: Path | str | None = None) -> list:
    """调真实搜索 API（带签名），返回笔记列表。只发 1 个请求。"""
    cookies = cookies or load_cookies(key_file=key_file)
    payload = build_search_params(keyword, page_size=min(max_n, 20))
    headers = signed_post_headers(SEARCH_API, payload, cookies, x_rap=True)

    cookie_str = "; ".join("%s=%s" % (k, v) for k, v in cookies.items() if v)
    headers["Cookie"] = cookie_str
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(SEARCH_API, data=body_bytes,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "ignore")
    data = json.loads(body)
    if not data.get("success", False):
        raise RuntimeError("搜索 API 返回失败: %s" % data.get("msg", body[:200]))

    items = ((data.get("data") or {}).get("items") or [])
    out = []
    for it in items[:max_n]:
        card = (it.get("note_card") or {})
        user = (card.get("user") or {})
        interact = (card.get("interact_info") or {})
        note_id = it.get("id") or card.get("note_id") or ""
        out.append({
            "title": card.get("display_title") or card.get("title") or "",
            "author": user.get("nickname") or user.get("nick_name") or "",
            "liked": interact.get("liked_count", ""),
            "url": ("https://www.xiaohongshu.com/explore/%s" % note_id
                    if note_id else ""),
        })
    return out


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="小红书 API 签名搜索")
    ap.add_argument("keyword", nargs="?", default="", help="搜索关键词")
    ap.add_argument("--max", type=int, default=10, help="最大返回条数")
    ap.add_argument("-o", "--output", help="输出 JSON 文件")
    ap.add_argument("--key-file", help="指定 Cookie 文件路径（默认 ~/.config/ppt-studio/xiaohongshu.json）")
    ap.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    a = ap.parse_args(argv)
    if not a.keyword:
        ap.print_help()
        return 0
    effective_base = (
        Path(a.base_dir).resolve()
        if a.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )
    key_file = None
    if a.key_file:
        kf_p = Path(a.key_file)
        key_file = (effective_base / kf_p).resolve() if not kf_p.is_absolute() else kf_p.resolve()
    try:
        results = api_search_notes(a.keyword, a.max, key_file=key_file)
    except Exception as e:
        sys.exit("[error] %s" % e)
    if a.output:
        out_p = Path(a.output)
        out_file = (effective_base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[ok] %d 条结果 -> %s" % (len(results), out_file))
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
