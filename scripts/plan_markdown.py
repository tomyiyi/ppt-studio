#!/usr/bin/env python3
"""Parse the deliberately small Markdown contract used by ppt-studio slide plans."""

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


_HEADING = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*$")
_BULLET = re.compile(r"^[ \t]*([-*])[ \t]+(.+?)[ \t]*$")
_ORDERED = re.compile(r"^[ \t]*(\d+)[.]\s+(.+?)[ \t]*$")
_QUOTE = re.compile(r"^>[ \t]+(.+?)[ \t]*$")
_TABLE = re.compile(r"^\|(.+)\|[ \t]*$")
_METRIC = re.compile(r"^([^:：\-][^:：]*?)[ \t]*:[ \t]*(.+)$")
_IMAGE = re.compile(r"^!\[([^\]]+)\]\(([^)]+)\)[ \t]*$")
_CODE_OPEN = re.compile(r"^```([A-Za-z0-9_+\-]{0,16})[ \t]*$")
_CODE_LANGUAGES = {"python", "bash", "json", "typescript", "sql"}


def _parse_image(line: str) -> dict | None:
    match = _IMAGE.match(line)
    if not match:
        return None
    alt, path = match.group(1).strip(), match.group(2).strip()
    if not alt or not path:
        raise ValueError("image alt and path must be non-empty")
    if path.startswith(("http://", "https://", "data:")):
        raise ValueError("image path must be a local relative path")
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("image path must be a local relative path")
    if posix.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("image path extension must be .png, .jpg, or .jpeg")
    return {"type": "image", "alt": alt, "path": path}


def _normalise_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def parse_markdown(text: str) -> list[dict]:
    lines = _normalise_lines(text)
    slides: list[dict] = []
    current: dict | None = None
    i = 0
    h1_count = 0
    while i < len(lines):
        line = lines[i]
        code_open = _CODE_OPEN.match(line)
        if code_open:
            language = code_open.group(1).lower()
            if language and language not in _CODE_LANGUAGES:
                raise ValueError(f"unsupported code language: {language}")
            i += 1
            code_lines = []
            while i < len(lines) and not re.fullmatch(r"```[ \t]*", lines[i]):
                if lines[i].startswith("```"):
                    raise ValueError("nested fenced code block is not supported")
                if lines[i].strip():
                    code_lines.append(lines[i])
                i += 1
            if i >= len(lines):
                raise ValueError("unclosed fenced code block")
            if not 2 <= len(code_lines) <= 8:
                raise ValueError("code block requires 2-8 non-empty code lines")
            current["blocks"].append({"type": "code", "language": language, "lines": code_lines})
            i += 1
            continue
        if line.strip().startswith("```"):
            raise ValueError("unsupported markdown structure: fenced code block")
        if not line.strip():
            i += 1
            continue
        match = _HEADING.match(line)
        if match:
            level, title = len(match.group(1)), match.group(2).strip()
            if level == 1:
                h1_count += 1
                if h1_count > 1:
                    raise ValueError("expected exactly one H1")
                if slides:
                    raise ValueError("H1 must be the first heading")
                current = {"kind": "cover", "title": title, "blocks": []}
                slides.append(current)
            elif level == 2:
                if h1_count != 1:
                    raise ValueError("H2 appeared before H1")
                current = {"kind": "content", "title": title, "blocks": []}
                slides.append(current)
            else:
                raise ValueError("unsupported markdown structure: ### heading")
            i += 1
            continue
        if current is None:
            raise ValueError("content appeared before H1")
        image = _parse_image(line)
        if image:
            current["blocks"].append(image)
            i += 1
            continue
        table = _TABLE.match(line)
        if table:
            rows=[]
            while i < len(lines) and _TABLE.match(lines[i]):
                cells=[x.strip() for x in _TABLE.match(lines[i]).group(1).split("|")]
                if any(not x for x in cells): raise ValueError("comparison table cells must be non-empty")
                rows.append(cells); i += 1
            if len(rows)==1: raise ValueError("unsupported markdown structure: table")
            if len(rows)<3: raise ValueError("comparison table requires header and 2-4 data rows")
            if len(rows[0])!=2: raise ValueError("comparison table requires exactly 2 columns")
            if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("comparison table alignment syntax is not supported")
            data=rows[2:]
            if not 2<=len(data)<=4 or any(len(x)!=2 for x in data): raise ValueError("comparison table requires 2-4 data rows")
            current["blocks"].append({"type":"comparison-table","headers":rows[0],"rows":data})
            continue
        bullet = _BULLET.match(line)
        if bullet:
            items = []
            while i < len(lines):
                item = _BULLET.match(lines[i])
                if not item:
                    break
                items.append(item.group(2).strip())
                i += 1
            metric_items = []
            for item in items:
                metric = _METRIC.match(item)
                if not metric:
                    metric_items = []
                    break
                label, value = metric.group(1).strip(), metric.group(2).strip()
                if not label or not value:
                    raise ValueError("metric label and value must be non-empty")
                metric_items.append({"label": label, "value": value})
            if metric_items:
                if not 2 <= len(metric_items) <= 4:
                    raise ValueError("metric list requires 2-4 items in v1")
                current["blocks"].append({"type": "metric-list", "items": metric_items})
            else:
                current["blocks"].append({"type": "bullets", "items": items})
            continue
        ordered = _ORDERED.match(line)
        if ordered:
            items = []
            expected = 1
            while i < len(lines):
                item = _ORDERED.match(lines[i])
                if not item:
                    break
                if int(item.group(1)) != expected:
                    raise ValueError("ordered steps must start at 1 and be strictly consecutive")
                items.append(item.group(2).strip())
                expected += 1
                i += 1
            current["blocks"].append({"type": "steps", "items": items})
            continue
        quote = _QUOTE.match(line)
        if quote:
            raw=[]
            while i < len(lines):
                item=_QUOTE.match(lines[i])
                if not item: break
                raw.append(item.group(1).strip()); i += 1
            if not raw or any(not x for x in raw): raise ValueError("empty quote content is not supported")
            attribution=None
            if raw[-1].startswith("—"):
                attribution=raw.pop()[1:].strip()
                if not attribution: raise ValueError("empty quote attribution is not supported")
            if any(x.startswith("—") for x in raw): raise ValueError("quote attribution must be the final blockquote line")
            if not 1 <= len(raw) <= 2: raise ValueError("quote block supports 1-2 quote lines in v1")
            block={"type":"quote","lines":raw}
            if attribution: block["attribution"]=attribution
            current["blocks"].append(block)
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not _HEADING.match(lines[i]) and not _BULLET.match(lines[i]) and not _ORDERED.match(lines[i]) and not _QUOTE.match(lines[i]) and not _IMAGE.match(lines[i]) and not _CODE_OPEN.match(lines[i]):
            if lines[i].lstrip().startswith("|"):
                raise ValueError("unsupported markdown structure: table")
            paragraph.append(lines[i].strip())
            i += 1
        current["blocks"].append({"type": "paragraph", "text": " ".join(paragraph)})
    if h1_count != 1:
        raise ValueError("expected exactly one H1")
    return slides


def build_plan(source_name: str, source_bytes: bytes) -> dict:
    text = source_bytes.decode("utf-8")
    raw_slides = parse_markdown(text)
    slides = []
    for index, slide in enumerate(raw_slides, 1):
        slides.append({"index": index, "id": f"{index:02d}", **slide})
    return {
        "schema": "ppt-studio-slide-plan/v1",
        "source_name": source_name,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "slides": slides,
    }


def write_plan(plan: dict, output: Path) -> None:
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert V1 Markdown into a deterministic PPT slide plan")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source_bytes = args.source.read_bytes()
        write_plan(build_plan(args.source.name, source_bytes), args.output)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
