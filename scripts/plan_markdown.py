#!/usr/bin/env python3
"""Parse the deliberately small Markdown contract used by ppt-studio slide plans."""

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


_HEADING = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*$")
_BULLET = re.compile(r"^[ \t]*([-*])[ \t]+(.+?)[ \t]*$")
_BULLET_ROOT = re.compile(r"^([-*])[ \t]+(.+?)[ \t]*$")
_BULLET_CHILD = re.compile(r"^  ([-*])[ \t]+(.+?)[ \t]*$")
_FAQ_Q = re.compile(r"^[ \t]*Q:[ \t]*(.+?)[ \t]*$")
_FAQ_A = re.compile(r"^[ \t]*A:[ \t]*(.+?)[ \t]*$")
_FAQ_Q_MARKER = re.compile(r"^[ \t]*Q:[ \t]*$")
_FAQ_A_MARKER = re.compile(r"^[ \t]*A:[ \t]*$")
_ORDERED = re.compile(r"^[ \t]*(\d+)[.]\s+(.+?)[ \t]*$")
_QUOTE = re.compile(r"^>[ \t]+(.+?)[ \t]*$")
_TABLE = re.compile(r"^\|(.+)\|[ \t]*$")
_METRIC = re.compile(r"^([^:：\-][^:：]*?)[ \t]*:[ \t]*(.+)$")
_MILESTONE = re.compile(r"^(\d{4}(?:-\d{2})?(?:-\d{2})?)[ \t]*:[ \t]*(.+)$")
_FUNNEL = re.compile(r"^([^=:\-][^=:\-]*?)[ \t]*=>[ \t]*(.+)$")
_LAYER = re.compile(r"^([^=:\-][^=:\-]*?)[ \t]*=>[ \t]*(.+)$")
_BAR = re.compile(r"^([^=:\-][^=:\-]*?)[ \t]*=[ \t]*(\d+(?:\.\d{1,2})?)$")
_TASK = re.compile(r"^\[([ xX])\][ \t]+(.+)$")
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
                if rows[0] == ["Item", "W1", "W2", "W3", "W4"]:
                    if len(rows[1])!=5 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("status heatmap alignment syntax is not supported")
                    data=rows[2:]
                    if not 3<=len(data)<=5 or any(len(x)!=5 or any(not cell for cell in x) for x in data): raise ValueError("status heatmap requires 3-5 non-empty data rows")
                    items=[row[0] for row in data]
                    if len(set(items)) != len(items): raise ValueError("status heatmap items must be unique in v1")
                    if any(len(row[0])>18 for row in data): raise ValueError("status heatmap item exceeds budget")
                    allowed={"Low","Medium","High"}
                    if any(value not in allowed for row in data for value in row[1:]): raise ValueError("status heatmap values must be Low, Medium, or High in v1")
                    current["blocks"].append({"type":"status-heatmap","headers":rows[0],"periods":["W1","W2","W3","W4"],"items":[{"item":row[0],"statuses":row[1:]} for row in data]})
                    continue
            if len(rows[0])==3:
                if rows[0] == ["Option", "Impact", "Effort"]:
                    if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("decision matrix alignment syntax is not supported")
                    data=rows[2:]
                    if not 2<=len(data)<=4 or any(len(x)!=3 for x in data): raise ValueError("decision matrix requires 2-4 data rows")
                    if any(not r[0] or r[1] not in {"Low","Medium","High"} or r[2] not in {"Low","Medium","High"} for r in data): raise ValueError("decision matrix impact and effort must be Low, Medium, or High")
                    current["blocks"].append({"type":"decision-matrix","headers":rows[0],"rows":data})
                    continue
                if rows[0] == ["Category", "Before", "After"]:
                    if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("grouped bar alignment syntax is not supported")
                    data=rows[2:]
                    if not 3<=len(data)<=5 or any(len(x)!=3 or any(not cell for cell in x) for x in data): raise ValueError("grouped bar data requires 3-5 non-empty data rows")
                    categories=[x[0] for x in data]
                    if len(set(categories)) != len(categories): raise ValueError("grouped bar categories must be unique in v1")
                    items=[]
                    for row in data:
                        values=[]
                        for raw in row[1:]:
                            if not re.fullmatch(r"(?:0|[1-9]\d{0,3})(?:\.\d{1,2})?", raw): raise ValueError("grouped bar values must be non-negative decimals up to 9999")
                            values.append(float(raw))
                        items.append({"category":row[0],"values":values})
                    current["blocks"].append({"type":"grouped-bar-data","headers":rows[0],"series":["Before","After"],"items":items})
                    continue
                if rows[0] == ["Label", "X", "Y"]:
                    if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("scatter plot alignment syntax is not supported")
                    data=rows[2:]
                    if not 3<=len(data)<=6 or any(len(x)!=3 or any(not cell for cell in x) for x in data): raise ValueError("scatter plot data requires 3-6 non-empty data rows")
                    labels=[x[0] for x in data]
                    if len(set(labels)) != len(labels): raise ValueError("scatter plot labels must be unique in v1")
                    items=[]
                    for row in data:
                        values=[]
                        for raw in row[1:]:
                            if not re.fullmatch(r"(?:0|[1-9]\d{0,3})(?:\.\d{1,2})?", raw): raise ValueError("scatter plot values must be non-negative decimals up to 9999")
                            values.append(float(raw))
                        items.append({"label":row[0],"x":values[0],"y":values[1]})
                    current["blocks"].append({"type":"scatter-data","headers":rows[0],"items":items})
                    continue
                if rows[0] == ["Task", "Start", "End"]:
                    if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("gantt schedule alignment syntax is not supported")
                    data=rows[2:]
                    if not 3<=len(data)<=5 or any(len(x)!=3 or any(not cell for cell in x) for x in data): raise ValueError("gantt schedule requires 3-5 non-empty data rows")
                    tasks=[x[0] for x in data]
                    if len(set(tasks)) != len(tasks): raise ValueError("gantt tasks must be unique in v1")
                    items=[]
                    for row in data:
                        if len(row[0])>20: raise ValueError("gantt task exceeds budget")
                        if not re.fullmatch(r"W(?:[1-9]|1[0-2])", row[1]) or not re.fullmatch(r"W(?:[1-9]|1[0-2])", row[2]): raise ValueError("gantt weeks must be W1 through W12")
                        start,end=int(row[1][1:]),int(row[2][1:])
                        if start>end: raise ValueError("gantt task start must be <= end")
                        items.append({"task":row[0],"start":start,"end":end})
                    current["blocks"].append({"type":"gantt-schedule","headers":rows[0],"items":items})
                    continue
                if rows[0] == ["Stage", "Owner", "Output"]:
                    if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("swimlane handoff alignment syntax is not supported")
                    data=rows[2:]
                    if not 3<=len(data)<=5 or any(len(x)!=3 or any(not cell for cell in x) for x in data): raise ValueError("swimlane handoff requires 3-5 non-empty data rows")
                    owners=[]
                    for row in data:
                        if row[1] not in owners: owners.append(row[1])
                    if not 2<=len(owners)<=3: raise ValueError("swimlane handoff supports 2-3 distinct owners in v1")
                    current["blocks"].append({"type":"swimlane-handoff","headers":rows[0],"rows":data,"owners":owners})
                    continue
                if rows[0] != ["Risk", "Severity", "Mitigation"]:
                    raise ValueError("risk-register header mismatch")
                if len(rows[1])!=3 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("risk-register alignment syntax is not supported")
                data=rows[2:]
                if not 2<=len(data)<=4 or any(len(x)!=3 for x in data): raise ValueError("risk-register requires 2-4 data rows")
                if any(x not in {"Low","Medium","High"} for x in [r[1] for r in data]): raise ValueError("risk-register severity must be Low, Medium, or High")
                current["blocks"].append({"type":"risk-register","headers":rows[0],"rows":data})
                continue
            if rows[0] == ["Segment", "Share"]:
                if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("composition bar alignment syntax is not supported")
                data=rows[2:]
                if not 3<=len(data)<=5 or any(len(x)!=2 or not x[0] for x in data): raise ValueError("composition data requires 3-5 data rows")
                segments=[x[0] for x in data]
                if len(set(segments)) != len(segments): raise ValueError("composition data segments must be unique in v1")
                items=[]
                for row in data:
                    if not re.fullmatch(r"(?:[1-9]|[1-7]\d|8[0-4])%", row[1]): raise ValueError("composition shares must be integer percentages from 8% to 84%")
                    items.append({"segment":row[0],"share":int(row[1][:-1])})
                if sum(x["share"] for x in items) != 100: raise ValueError("composition shares must sum to 100 in v1")
                current["blocks"].append({"type":"composition-data","headers":rows[0],"items":items})
                continue
            if rows[0] == ["Driver", "Delta"]:
                if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("waterfall change alignment syntax is not supported")
                data=rows[2:]
                if not 3<=len(data)<=5 or any(len(x)!=2 or not x[0] or not x[1] for x in data): raise ValueError("waterfall data requires 3-5 non-empty data rows")
                drivers=[x[0] for x in data]
                if len(set(drivers)) != len(drivers): raise ValueError("waterfall drivers must be unique in v1")
                items=[]
                for row in data:
                    raw=row[1]
                    if not raw.startswith(("+", "-")): raise ValueError("waterfall delta must use an explicit + or - sign in v1")
                    if not re.fullmatch(r"[+-](?:0|[1-9]\d{0,3})(?:\.\d{1,2})?", raw): raise ValueError("waterfall deltas must be signed decimals up to 9999")
                    value=float(raw)
                    if value == 0 or abs(value)>9999: raise ValueError("waterfall delta must be non-zero and within 9999")
                    items.append({"driver":row[0],"delta":value})
                current["blocks"].append({"type":"waterfall-data","headers":rows[0],"items":items})
                continue
            if rows[0] == ["Stage", "Detail"]:
                if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("cycle stage alignment syntax is not supported")
                data=rows[2:]
                if not 3<=len(data)<=5 or any(len(x)!=2 or not x[0] or not x[1] for x in data): raise ValueError("cycle stages require 3-5 non-empty data rows")
                stages=[x[0] for x in data]
                if len(set(stages)) != len(stages): raise ValueError("cycle stages must be unique in v1")
                if any(len(x[0])>16 or len(x[1])>24 for x in data): raise ValueError("cycle stage exceeds budget")
                current["blocks"].append({"type":"cycle-stages","headers":rows[0],"items":[{"stage":x[0],"detail":x[1]} for x in data]})
                continue
            if rows[0] == ["Period", "Value"]:
                if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("trend series alignment syntax is not supported")
                data=rows[2:]
                if not 3<=len(data)<=6 or any(len(x)!=2 or not x[0] for x in data): raise ValueError("trend series requires 3-6 data rows")
                periods=[x[0] for x in data]
                if len(set(periods)) != len(periods): raise ValueError("trend series periods must be unique in v1")
                values=[]
                for row in data:
                    if not re.fullmatch(r"(?:0|[1-9]\d{0,3})(?:\.\d{1,2})?", row[1]): raise ValueError("trend series values must be non-negative decimals up to 9999")
                    values.append({"period":row[0],"value":float(row[1])})
                current["blocks"].append({"type":"trend-series","headers":rows[0],"items":values})
                continue
            if len(rows[0])!=2: raise ValueError("comparison table requires exactly 2 columns")
            if len(rows[1])!=2 or any(not re.fullmatch(r":?-{3,}:?", x) for x in rows[1]): raise ValueError("comparison table alignment syntax is not supported")
            data=rows[2:]
            if not 2<=len(data)<=4 or any(len(x)!=2 for x in data): raise ValueError("comparison table requires 2-4 data rows")
            current["blocks"].append({"type":"comparison-table","headers":rows[0],"rows":data})
            continue
        bullet = _BULLET.match(line)
        if bullet:
            if _BULLET_ROOT.match(line) and i + 1 < len(lines) and lines[i + 1].startswith(" "):
                root = _BULLET_ROOT.match(line).group(2).strip(); i += 1; children = []
                while i < len(lines) and lines[i].strip():
                    if _BULLET_ROOT.match(lines[i]): raise ValueError("hierarchy tree requires exactly one root in v1")
                    child = _BULLET_CHILD.match(lines[i])
                    if not child:
                        if lines[i].startswith((" ", "\t")): raise ValueError("hierarchy tree supports exactly one nesting level in v1")
                        break
                    children.append(child.group(2).strip()); i += 1
                if not root or any(not child for child in children): raise ValueError("hierarchy tree labels must be non-empty")
                if not 2 <= len(children) <= 4: raise ValueError("hierarchy tree requires 2-4 children in v1")
                current["blocks"].append({"type":"hierarchy-tree","root":root,"children":children}); continue
            items = []
            while i < len(lines):
                item = _BULLET.match(lines[i])
                if not item:
                    break
                items.append(item.group(2).strip())
                i += 1
            task_items=[]; task_matches=0
            for item in items:
                tm=_TASK.match(item)
                if item.startswith("[") and not tm:
                    raise ValueError("invalid task checkbox marker")
                if tm:
                    task_items.append({"text":tm.group(2).strip(),"checked":tm.group(1).lower()=="x"}); task_matches+=1
            if task_matches:
                if task_matches != len(items): raise ValueError("mixed task and non-task bullet items are not supported in v1")
                if not 3 <= len(task_items) <= 6: raise ValueError("task list requires 3-6 items in v1")
                if any(not x["text"] for x in task_items): raise ValueError("task text must be non-empty")
                current["blocks"].append({"type":"task-list","items":task_items})
                continue
            metric_items = []
            metric_matches = 0
            for item in items:
                metric = _METRIC.match(item)
                if not metric:
                    if ":" in item or "：" in item:
                        raise ValueError("mixed metric and plain bullet items are not supported in v1")
                    metric_items = []
                    continue
                label, value = metric.group(1).strip(), metric.group(2).strip()
                if not label or not value:
                    raise ValueError("metric label and value must be non-empty")
                metric_items.append({"label": label, "value": value})
                metric_matches += 1
            if metric_matches and metric_matches != len(items):
                raise ValueError("mixed metric and plain bullet items are not supported in v1")
            if metric_items:
                if not 2 <= len(metric_items) <= 4:
                    raise ValueError("metric list requires 2-4 items in v1")
                current["blocks"].append({"type": "metric-list", "items": metric_items})
            else:
                layer_items=[]; matches=0
                for item in items:
                    m=_LAYER.match(item)
                    if not m:
                        bar=_BAR.match(item)
                        if bar:
                            bar_items=[]
                            for candidate in items:
                                bm=_BAR.match(candidate)
                                if not bm: raise ValueError("mixed structured and plain bullet items are not supported in v1")
                                value=float(bm.group(2))
                                if value>9999: raise ValueError("bar value must be between 0 and 9999")
                                bar_items.append({"label":bm.group(1).strip(),"value":value})
                            if not 3 <= len(bar_items) <= 5: raise ValueError("bar data requires 3-5 items in v1")
                            current["blocks"].append({"type":"bar-data","items":bar_items}); layer_items=[]; matches=len(items); break
                        if "=>" in item: raise ValueError("mixed structured and plain bullet items are not supported in v1")
                        layer_items=[]; continue
                    label,description=m.group(1).strip(),m.group(2).strip()
                    if not label or not description: raise ValueError("layer label and description must be non-empty")
                    layer_items.append({"label":label,"description":description}); matches+=1
                if matches and matches != len(items): raise ValueError("mixed structured and plain bullet items are not supported in v1")
                if layer_items:
                    if not 3 <= len(layer_items) <= 5: raise ValueError("layer list requires 3-5 items in v1")
                    current["blocks"].append({"type":"layer-list","items":layer_items})
                elif not any(b.get("type")=="bar-data" for b in current["blocks"]): current["blocks"].append({"type":"bullets","items":items})
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
            milestones = []
            funnel_items = []
            funnel_matches = 0
            for item in items:
                fm = _FUNNEL.match(item)
                if fm:
                    label, description = fm.group(1).strip(), fm.group(2).strip()
                    if not label or not description: raise ValueError("funnel label and description must be non-empty")
                    funnel_items.append({"label": label, "description": description}); funnel_matches += 1; continue
                match_m = _MILESTONE.match(item)
                if not match_m:
                    if ":" in item:
                        raise ValueError("mixed milestone and plain ordered items are not supported in v1")
                    milestones = []
                    continue
                milestones.append({"date": match_m.group(1), "text": match_m.group(2).strip()})
            if funnel_matches and funnel_matches != len(items):
                raise ValueError("mixed structured ordered item types are not supported in v1")
            if funnel_items:
                if not 3 <= len(funnel_items) <= 5: raise ValueError("funnel stages require 3-5 items in v1")
                current["blocks"].append({"type":"funnel-stages","items":funnel_items}); continue
            if milestones and len(milestones) != len(items):
                raise ValueError("mixed milestone and plain ordered items are not supported in v1")
            if milestones:
                if not 3 <= len(milestones) <= 5:
                    raise ValueError("milestone list requires 3-5 items in v1")
                current["blocks"].append({"type": "milestone-list", "items": milestones})
            else:
                current["blocks"].append({"type":"steps","items":items})
            continue
        if _FAQ_A.match(line) or _FAQ_A_MARKER.match(line):
            raise ValueError("faq block requires each Q line to be followed by one A line")
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
        qmatch = _FAQ_Q.match(line)
        if _FAQ_Q_MARKER.match(line):
            raise ValueError("faq question and answer must be non-empty")
        if qmatch:
            items=[]
            while i < len(lines):
                while i < len(lines) and not lines[i].strip(): i += 1
                if i >= len(lines) or _HEADING.match(lines[i]): break
                q=_FAQ_Q.match(lines[i])
                if not q: raise ValueError("faq block requires each Q line to be followed by one A line")
                i += 1
                if i >= len(lines) or not _FAQ_A.match(lines[i]): raise ValueError("faq block requires each Q line to be followed by one A line")
                a=_FAQ_A.match(lines[i]); i += 1
                if not q.group(1).strip() or not a.group(1).strip(): raise ValueError("faq question and answer must be non-empty")
                items.append({"question":q.group(1).strip(),"answer":a.group(1).strip()})
            if not 2 <= len(items) <= 4: raise ValueError("faq block requires 2-4 Q/A pairs in v1")
            current["blocks"].append({"type":"faq","items":items}); continue
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
