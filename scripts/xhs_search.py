#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs_search.py —— 小红书搜索（ppt-studio 中文社媒层）
====================================================
Cookie 只从 ~/.config/ppt-studio/xiaohongshu.json 读取（600 权限），
格式：{"cookies": {"web_session": "...", "id_token": "...", ...}}。

原理：请求小红书 web 搜索页 HTML，解析内嵌的 window.__INITIAL_STATE__
（服务端渲染，无需 x-s/x-t API 签名）。

用法：
    python3 scripts/xhs_search.py "2026秋冬穿搭" --max 10
    python3 scripts/xhs_search.py "关键词" --max 10 -o out.json

注意：控制请求频率，勿高频调用触发风控。
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KEY_FILE = Path.home() / ".config" / "ppt-studio" / "xiaohongshu.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

REQUIRED_COOKIES = ("web_session",)


class CookieExpiredError(RuntimeError):
    pass


def load_cookies() -> dict:
    """读 Cookie 文件；权限非 600 直接拒绝。"""
    if not KEY_FILE.exists():
        sys.exit("[error] Cookie 文件不存在: %s" % KEY_FILE)
    mode = stat.S_IMODE(os.stat(KEY_FILE).st_mode)
    if mode != 0o600:
        sys.exit("[error] Cookie 文件权限必须为 600，当前 %s，拒绝读取" % oct(mode))
    try:
        data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit("[error] Cookie 文件解析失败: %s" % e)
    cookies = data.get("cookies", {})
    missing = [k for k in REQUIRED_COOKIES if not cookies.get(k)]
    if missing:
        sys.exit("[error] Cookie 缺失关键字段: %s" % missing)
    return cookies


def fetch_search_html(keyword: str, cookies: dict) -> str:
    cookie_str = "; ".join("%s=%s" % (k, v) for k, v in cookies.items() if v)
    url = "http://www.xiaohongshu.com/search_result/?keyword=" + urllib.parse.quote(keyword)
    req = urllib.request.Request(url, headers={
        "Cookie": cookie_str,
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
            if "login" in final:
                raise CookieExpiredError("Cookie 失效，请更新（被跳转到登录页）")
            return r.read().decode("utf-8", "ignore")
    except CookieExpiredError:
        raise
    except Exception as e:
        if "401" in str(e) or "403" in str(e):
            raise CookieExpiredError("Cookie 失效，请更新")
        raise


def extract_state(html: str) -> dict:
    """括号计数提取 __INITIAL_STATE__，JS undefined -> null。"""
    start = html.find("window.__INITIAL_STATE__")
    if start < 0:
        raise CookieExpiredError("Cookie 失效，请更新（页面无登录态数据）")
    start = html.find("{", start)
    dq = chr(34)  # 双引号，避开 heredoc 引号问题
    bs = chr(92)  # 反斜杠
    depth, instr, esc, i = 0, False, False, start
    while i < len(html):
        c = html[i]
        if instr:
            if esc:
                esc = False
            elif c == bs:
                esc = True
            elif c == dq:
                instr = False
        else:
            if c == dq:
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    raw = html[start:i + 1].replace(":undefined", ":null").replace(",undefined", ",null")
    return json.loads(raw)


def _find_notes(obj, depth=0):
    """多路径兼容：找搜索结果 notes 列表。"""
    if depth > 10:
        return []
    if isinstance(obj, dict):
        notes = obj.get("notes")
        if isinstance(notes, list) and notes and isinstance(notes[0], dict):
            return notes
        for v in obj.values():
            r = _find_notes(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj[:3]:
            r = _find_notes(v, depth + 1)
            if r:
                return r
    return []


def parse_notes(state: dict, max_n: int) -> list:
    # 优先 search 分支，避免命中 user/notes（用户自己的笔记）
    search_branch = state.get("search", {})
    notes = _find_notes(search_branch) or _find_notes(state)
    out = []
    for n in notes[:max_n]:
        if not isinstance(n, dict):
            continue
        card = n.get("note_card") if isinstance(n.get("note_card"), dict) else {}
        src = card or n
        user = src.get("user") if isinstance(src.get("user"), dict) else {}
        interact = src.get("interact_info") if isinstance(src.get("interact_info"), dict) else {}
        note_id = n.get("id") or src.get("note_id") or ""
        out.append({
            "title": src.get("display_title") or src.get("title") or "",
            "author": user.get("nickname") or user.get("nick_name") or "",
            "liked": interact.get("liked_count", ""),
            "url": "https://www.xiaohongshu.com/explore/%s" % note_id if note_id else "",
        })
    return out


def search(keyword: str, max_n: int = 10) -> list:
    cookies = load_cookies()
    html = fetch_search_html(keyword, cookies)
    state = extract_state(html)
    return parse_notes(state, max_n)


def main() -> None:
    ap = argparse.ArgumentParser(description="小红书关键词搜索")
    ap.add_argument("keyword", help="搜索关键词")
    ap.add_argument("--max", type=int, default=10, help="最大返回条数")
    ap.add_argument("-o", "--output", help="输出 JSON 文件")
    a = ap.parse_args()
    try:
        results = search(a.keyword, a.max)
    except CookieExpiredError as e:
        sys.exit("[error] %s" % e)
    if a.output:
        Path(a.output).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("[ok] %d 条结果 -> %s" % (len(results), a.output))
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
