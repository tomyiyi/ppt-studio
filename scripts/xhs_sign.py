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
                     cookies: dict | None = None) -> list:
    """调真实搜索 API（带签名），返回笔记列表。只发 1 个请求。"""
    cookies = cookies or load_cookies()
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
