#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_router.py -- 统一搜索路由：多后端 fallback + doctor 自检
================================================================
吸收自 Panniantong/Agent-Reach（~66K stars）的两个核心机制：

1. multi-backend fallback（对标 Agent-Reach transcribe._transcribe_with_fallback）：
   后端按优先级逐个尝试，首个"成功且有产出"即返回；某后端抛异常或
   返回空结果时静默顺延到下一个；全部后端都失败才抛错。调用方只需
   调一个 search()，不用关心 Tavily key 耗尽 / 小红书 cookie 过期 /
   B站风控等单点故障。

2. doctor（对标 Agent-Reach doctor.check_all）：
   每个后端实现自检 check()，doctor() 聚合所有后端状态；单个后端
   自检抛异常时降级为 status="error"，绝不拖垮整份报告。

后端注册表（默认优先级 tavily -> xhs -> bili -> wiki -> commons -> openverse）：
  - tavily：Tavily 全网搜索（load_keys 做 key 轮换，需 TAVILY_API_KEY 或
    ~/.config/ppt-studio/tavily.json）
  - xhs：小红书搜索（需 ~/.config/ppt-studio/xiaohongshu.json cookie）
  - bili：B站视频搜索（免凭证）
  - wiki：Wikipedia 搜索（免凭证，zh 无结果时回退 en）
  - commons：Wikimedia Commons 图片搜索（免凭证，只取位图，附授权/作者/缩略图）
  - openverse：Openverse CC 图片搜索（免凭证匿名：20/min · 200/day，附授权/作者/直链）

归一化结果字段：title / url / snippet / source / backend / extra。

用法：
    python3 scripts/search_router.py "Pantone FW2026" --max 10
    python3 scripts/search_router.py "查询词" --backends xhs,bili --no-fallback
    python3 scripts/search_router.py --doctor
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bili_search  # noqa: E402
import tavily_search  # noqa: E402
import xhs_search  # noqa: E402

# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------


def normalize_tavily(raw: dict) -> list[dict]:
    """Tavily search() 返回的 dict -> 统一结果列表。"""
    out = []
    for r in raw.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        out.append({
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "snippet": (r.get("content") or "")[:500],
            "source": "tavily",
            "backend": "tavily",
            "extra": {"score": r.get("score"), "published": r.get("published_date")},
        })
    return out


def normalize_xhs(raw: list) -> list[dict]:
    """xhs_search.search() 返回的 note 列表 -> 统一结果列表。"""
    out = []
    for n in raw or []:
        if not isinstance(n, dict):
            continue
        snippet = "作者: %s" % n.get("author", "")
        if n.get("liked"):
            snippet += " · 点赞 %s" % n.get("liked")
        out.append({
            "title": n.get("title") or "",
            "url": n.get("url") or "",
            "snippet": snippet,
            "source": "xiaohongshu",
            "backend": "xhs",
            "extra": {"author": n.get("author"), "liked": n.get("liked")},
        })
    return out


def normalize_bili(raw: list) -> list[dict]:
    """bili_search.search() 返回的视频列表 -> 统一结果列表。"""
    out = []
    for v in raw or []:
        if not isinstance(v, dict):
            continue
        snippet = (v.get("description") or "")[:500]
        if v.get("play"):
            snippet = "播放 %s · %s" % (v.get("play"), snippet)
        out.append({
            "title": v.get("title") or "",
            "url": v.get("url") or "",
            "snippet": snippet,
            "source": "bilibili",
            "backend": "bili",
            "extra": {"author": v.get("author"), "play": v.get("play"),
                      "published_at": v.get("published_at")},
        })
    return out


def normalize_wiki(raw: dict, lang: str = "zh") -> list[dict]:
    """Wikipedia API list=search 响应 -> 统一结果列表。"""
    out = []
    q = raw.get("query") or {}
    for item in q.get("search", []) or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        url = ("https://%s.wikipedia.org/wiki/%s"
               % (lang, urllib.parse.quote(title.replace(" ", "_"))))
        snippet = re.sub(r"<[^>]+>", "", item.get("snippet") or "")[:500]
        out.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": "wikipedia(%s)" % lang,
            "backend": "wiki",
            "extra": {"pageid": item.get("pageid"), "lang": lang},
        })
    return out


# ---------------------------------------------------------------------------
# MediaWiki 通用 GET（含瞬时故障重试）+ Commons 后端
# ---------------------------------------------------------------------------


def _wikimedia_get_json(url: str, label: str) -> dict:
    """MediaWiki 系 API 通用 GET（免凭证）。

    偶发 SSL EOF 属已知瞬时故障（第 23 轮实跑复现），URLError/SSLError/
    TimeoutError/ConnectionError 最多重试 1 次（sleep 1s）；HTTPError
    （4xx/5xx）直接抛，不重试。
    """
    import ssl  # noqa: E402 -- 延迟导入，保持模块顶层轻量
    import time  # noqa: E402
    import urllib.error  # noqa: E402
    req = urllib.request.Request(
        url, headers={"User-Agent": "ppt-studio/search_router (research use)"})
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ssl.SSLError, TimeoutError,
                ConnectionError) as e:  # noqa: BLE001 -- 瞬时故障才重试
            last = e
            if attempt == 1:
                time.sleep(1)
    raise RuntimeError("%s 2 次尝试均失败: %s" % (label, last))


def _strip_utm(url: str) -> str:
    """Commons imageinfo 返回的直链自带 ?utm_source=… 跟踪参数，剥离得干净直链。"""
    return url.split("?", 1)[0] if url else ""


def normalize_commons(raw: dict) -> list[dict]:
    """Commons API generator=search（文件命名空间）响应 -> 统一结果列表。"""
    out = []
    q = raw.get("query") or {}
    for page in q.get("pages", []) or []:
        if not isinstance(page, dict):
            continue
        title = page.get("title") or ""
        infos = page.get("imageinfo") or []
        ii = infos[0] if infos and isinstance(infos[0], dict) else {}
        em = ii.get("extmetadata") or {}
        lic = (em.get("LicenseShortName") or {}).get("value", "") or "未知授权"
        artist = html.unescape(re.sub(
            r"<[^>]+>", "", (em.get("Artist") or {}).get("value", "") or ""))[:80]
        desc = html.unescape(re.sub(
            r"<[^>]+>", "", (em.get("ImageDescription") or {}).get("value", "")
            or ""))[:120]
        w, h = ii.get("width"), ii.get("height")
        snippet = "%s · %s · %sx%s" % (lic, artist or "作者未知",
                                      w or "?", h or "?")
        if desc:
            snippet = "%s | %s" % (desc, snippet)
        url = ("https://commons.wikimedia.org/wiki/%s"
               % urllib.parse.quote(title.replace(" ", "_")))
        out.append({
            "title": title.replace("File:", "", 1),
            "url": url,
            "snippet": snippet,
            "source": "wikimedia-commons",
            "backend": "commons",
            "extra": {
                "thumburl": _strip_utm(ii.get("thumburl") or ""),
                "imageurl": _strip_utm(ii.get("url") or ""),
                "license": lic,
                "artist": artist,
                "width": w, "height": h, "mime": ii.get("mime"),
                "filetitle": title,
            },
        })
    return out


def _commons_api_search(query: str, limit: int) -> dict:
    """调 Wikimedia Commons API（免凭证）：只取位图，附 800px 缩略图与授权信息。"""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "search", "gsrsearch": "filetype:bitmap %s" % query,
        "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
        "iiurlwidth": 800, "utf8": 1,
    })
    url = "https://commons.wikimedia.org/w/api.php?%s" % params
    return _wikimedia_get_json(url, "commons api")


def _commons_run(query: str, max_results: int) -> list[dict]:
    """Wikimedia Commons 图片搜索：免凭证；只取位图，附 800px 缩略图与授权信息。"""
    return normalize_commons(_commons_api_search(query, max_results))


def _commons_check() -> tuple[str, str]:
    # 免凭证公开 API：模块可导入即视为可用（不做真实网络探活，保持 doctor 轻量）
    return "ok", "免凭证（Wikimedia Commons API，只取位图）"


# ---------------------------------------------------------------------------
# openverse 后端（第 30 轮）
# ---------------------------------------------------------------------------

_OPENVERSE_LICENSE_NAMES = {
    "by": "CC BY", "by-sa": "CC BY-SA", "by-nd": "CC BY-ND",
    "by-nc": "CC BY-NC", "by-nc-sa": "CC BY-NC-SA", "by-nc-nd": "CC BY-NC-ND",
    "pdm": "Public Domain Mark", "cc0": "CC0",
}


def normalize_openverse(raw: dict) -> list[dict]:
    """Openverse /v1/images/ 响应 -> 统一结果列表。

    过滤 mature 内容（PPT 素材安全）；url 指向来源落地页，
    extra.imageurl 为可直接下载的原图直链。
    """
    out = []
    for r in raw.get("results", []) or []:
        if not isinstance(r, dict) or r.get("mature"):
            continue
        img_url = r.get("url") or ""
        if not img_url:
            continue
        lic = r.get("license") or ""
        lic_name = _OPENVERSE_LICENSE_NAMES.get(lic, lic.upper() or "未知授权")
        if r.get("license_version"):
            lic_name = "%s %s" % (lic_name, r["license_version"])
        creator = (r.get("creator") or "作者未知")[:80]
        title = r.get("title") or "(无标题)"
        w, h = r.get("width"), r.get("height")
        snippet = "%s · %s · %sx%s" % (lic_name, creator, w or "?", h or "?")
        out.append({
            "title": title,
            "url": r.get("foreign_landing_url") or img_url,
            "snippet": snippet,
            "source": "openverse",
            "backend": "openverse",
            "extra": {
                "imageurl": img_url,
                "thumburl": r.get("thumbnail") or "",
                "license": lic_name,
                "license_url": r.get("license_url") or "",
                "attribution": r.get("attribution") or "",
                "artist": creator,
                "width": w, "height": h,
                "provider": r.get("provider") or "",
            },
        })
    return out


def _openverse_api_search(query: str, limit: int) -> dict:
    """调 Openverse 图片搜索（免凭证匿名；匿名端每页最多 20 条）。"""
    params = urllib.parse.urlencode({
        "q": query, "page_size": max(1, min(limit, 20)),
    })
    url = "https://api.openverse.org/v1/images/?%s" % params
    # 复用通用免凭证 GET：瞬时故障重试 1 次；HTTPError（含 429 限流）直接抛，不重试
    return _wikimedia_get_json(url, "openverse api")


def _openverse_run(query: str, max_results: int) -> list[dict]:
    """Openverse CC 图片搜索：免凭证匿名（20/min · 200/day），过滤 mature 内容。"""
    return normalize_openverse(_openverse_api_search(query, max_results))


def _openverse_check() -> tuple[str, str]:
    # 免凭证公开 API：模块可导入即视为可用（不做真实网络探活，保持 doctor 轻量）
    return "ok", "免凭证匿名（Openverse API，20/min · 200/day）"


# ---------------------------------------------------------------------------
# 后端适配器
# ---------------------------------------------------------------------------


def _tavily_run(query: str, max_results: int) -> list[dict]:
    """Tavily：内部 key 轮换（复用 tavily_search.load_keys）。"""
    try:
        keys = tavily_search.load_keys()
    except SystemExit as e:
        # load_keys 无 key 时直接 sys.exit，转为普通异常以便 fallback
        raise RuntimeError("tavily 无可用 key: %s" % e)
    last_err: Exception | None = None
    for key in keys:
        try:
            raw = tavily_search.search(query, key, "advanced", max_results)
            return normalize_tavily(raw)
        except Exception as e:  # noqa: BLE001 -- 单 key 失败就换下一个
            last_err = e
    raise RuntimeError("tavily 所有 key 均失败: %s" % last_err)


def _xhs_run(query: str, max_results: int) -> list[dict]:
    return normalize_xhs(xhs_search.search(query, max_n=max_results, use_api=True))


def _bili_run(query: str, max_results: int) -> list[dict]:
    return normalize_bili(bili_search.search(query, max_results=max_results))


def _tavily_check() -> tuple[str, str]:
    try:
        keys = tavily_search.load_keys()
    except SystemExit:
        return "missing", "无可用 Tavily key（TAVILY_API_KEY 或 ~/.config/ppt-studio/tavily.json）"
    except Exception as e:  # noqa: BLE001
        return "error", "key 检查异常: %s" % e
    return "ok", "%d 个 key 已配置" % len(keys)


def _xhs_check() -> tuple[str, str]:
    try:
        cookies = xhs_search.load_cookies()
    except Exception as e:  # noqa: BLE001
        return "missing", "cookie 加载失败: %s" % e
    if not cookies:
        return "missing", "cookie 为空（~/.config/ppt-studio/xiaohongshu.json）"
    return "ok", "cookie 已配置"


def _bili_check() -> tuple[str, str]:
    # B站搜索免凭证：模块可导入即视为可用（不做真实网络探活，保持 doctor 轻量）
    return "ok", "免凭证（模块可用）"


def _wiki_api_search(query: str, lang: str, limit: int) -> dict:
    """调 Wikipedia API list=search（免凭证）。瞬时故障重试逻辑见
    _wikimedia_get_json（第 26 轮抽取的共享实现，原 _wiki_api_search 内联逻辑）。"""
    params = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": limit, "format": "json", "utf8": 1,
    })
    url = "https://%s.wikipedia.org/w/api.php?%s" % (lang, params)
    return _wikimedia_get_json(url, "wikipedia api")


def _wiki_run(query: str, max_results: int) -> list[dict]:
    """Wikipedia：免凭证；zh 无结果时回退 en。"""
    items = normalize_wiki(_wiki_api_search(query, "zh", max_results), "zh")
    if not items:
        items = normalize_wiki(_wiki_api_search(query, "en", max_results), "en")
    return items


def _wiki_check() -> tuple[str, str]:
    # 免凭证公开 API：模块可导入即视为可用（不做真实网络探活，保持 doctor 轻量）
    return "ok", "免凭证（Wikipedia API，zh→en 回退）"


@dataclass
class Backend:
    name: str
    run: Callable[[str, int], list[dict]]
    check: Callable[[], tuple[str, str]]
    description: str = ""


BACKENDS: list[Backend] = [
    Backend("tavily", _tavily_run, _tavily_check, "Tavily 全网搜索（key 轮换）"),
    Backend("xhs", _xhs_run, _xhs_check, "小红书笔记搜索（cookie）"),
    Backend("bili", _bili_run, _bili_check, "B站视频搜索（免凭证）"),
    Backend("wiki", _wiki_run, _wiki_check, "Wikipedia 搜索（免凭证，zh→en 回退）"),
    Backend("commons", _commons_run, _commons_check,
            "Wikimedia Commons 图片搜索（免凭证，只取位图，附授权/作者/缩略图）"),
    Backend("openverse", _openverse_run, _openverse_check,
            "Openverse CC 图片搜索（免凭证匿名，附授权/作者/直链）"),
]

_BACKEND_MAP = {b.name: b for b in BACKENDS}


class SearchAllBackendsFailed(RuntimeError):
    """所有后端都失败（抛异常）。空结果不算失败，见 search()。"""


def resolve_backends(spec: str | list[str] | None) -> list[Backend]:
    """解析 backends 参数：None/"auto" -> 全部按优先级；否则按指定顺序。"""
    if spec is None or (isinstance(spec, str) and spec.strip().lower() == "auto"):
        return list(BACKENDS)
    names = spec if isinstance(spec, list) else [s.strip() for s in spec.split(",")]
    out = []
    for n in names:
        if n not in _BACKEND_MAP:
            raise ValueError("未知搜索后端: %s（可选: %s）"
                             % (n, ", ".join(_BACKEND_MAP)))
        out.append(_BACKEND_MAP[n])
    return out


def search(query: str, *,
           backends: str | list[str] | None = "auto",
           max_results: int = 10,
           allow_fallback: bool = True) -> dict:
    """统一搜索入口。

    返回 {"query", "backend_used", "results", "attempts"}：
      - backend_used: 实际产出结果的后端名（都空时为 None）
      - attempts: 每个尝试过的后端 {"backend", "ok", "n", "error"}
    语义（Agent-Reach fallback 同构）：
      - 某后端抛异常 -> 记录后顺延下一个；
      - 某后端返回空列表 -> 视为无产出，顺延下一个；
      - 全部后端都抛异常 -> 抛 SearchAllBackendsFailed；
      - 全部后端都返回空 -> 正常返回空 results（ok=True）。
    allow_fallback=False 时只用第一个指定的后端，失败直接抛错。
    """
    chain = resolve_backends(backends)
    attempts: list[dict] = []
    for b in chain:
        try:
            results = b.run(query, max_results)
        except Exception as e:  # noqa: BLE001 -- 单后端失败不中断链
            attempts.append({"backend": b.name, "ok": False, "n": 0,
                             "error": str(e)[:200]})
            if not allow_fallback:
                raise
            continue
        n = len(results)
        attempts.append({"backend": b.name, "ok": True, "n": n, "error": ""})
        if n > 0:
            return {"query": query, "backend_used": b.name,
                    "results": results[:max_results], "attempts": attempts}
        if not allow_fallback:
            return {"query": query, "backend_used": None,
                    "results": [], "attempts": attempts}
        # 空结果：继续试下一个后端
    if attempts and all(not a["ok"] for a in attempts):
        raise SearchAllBackendsFailed(
            "所有搜索后端均失败: %s"
            % "; ".join("%s(%s)" % (a["backend"], a["error"]) for a in attempts))
    return {"query": query, "backend_used": None, "results": [],
            "attempts": attempts}


def doctor() -> dict[str, dict]:
    """聚合所有后端自检；单个后端异常降级为 error，不拖垮整体。"""
    results: dict[str, dict] = {}
    for b in BACKENDS:
        try:
            status, message = b.check()
        except Exception as e:  # noqa: BLE001 -- doctor 必须扛住任何后端
            status, message = "error", "自检异常: %s" % e
        results[b.name] = {"status": status, "description": b.description,
                           "message": message}
    return results


def main(argv: list[str] | None = None, base_dir: str | Path | None = None) -> int:
    ap = argparse.ArgumentParser(description="统一搜索路由（多后端 fallback）")
    ap.add_argument("query", nargs="?", help="搜索关键词")
    ap.add_argument("--backends", default="auto",
                    help="后端选择：auto 或逗号分隔如 xhs,bili")
    ap.add_argument("--max", type=int, default=10, help="最大结果数")
    ap.add_argument("--no-fallback", action="store_true",
                    help="禁用 fallback，只用第一个后端")
    ap.add_argument("--doctor", action="store_true", help="只做后端自检")
    ap.add_argument("-o", "--output", help="结果写 JSON 文件")
    ap.add_argument(
        "--base-dir",
        default=None,
        help="指定基础工作目录 (默认: 当前工作目录)",
    )
    a = ap.parse_args(argv)
    effective_base = (
        Path(a.base_dir).resolve()
        if a.base_dir
        else (Path(base_dir).resolve() if base_dir else Path.cwd().resolve())
    )

    if a.doctor:
        rep = doctor()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    if not a.query:
        ap.error("需要 query，或用 --doctor 自检")

    try:
        res = search(a.query, backends=a.backends, max_results=a.max,
                     allow_fallback=not a.no_fallback)
    except (SearchAllBackendsFailed, ValueError, RuntimeError) as e:
        raise SystemExit("[error] %s" % e)

    out = json.dumps(res, ensure_ascii=False, indent=2)
    if a.output:
        out_p = Path(a.output)
        out_file = (effective_base / out_p).resolve() if not out_p.is_absolute() else out_p.resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(out, encoding="utf-8")
    else:
        print(out)
    print("[ok] 后端=%s 结果=%d 条" % (res["backend_used"], len(res["results"])),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
