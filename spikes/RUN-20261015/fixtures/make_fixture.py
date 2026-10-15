import json, sys
from pathlib import Path
sys.path.insert(0, "/Volumes/3TB_DATA/05-开发项目/ppt-studio/scripts")
import auto_research as AR

FIXDIR = Path("/Volumes/3TB_DATA/05-开发项目/ppt-studio/spikes/RUN-20261015/fixtures")
FIXDIR.mkdir(parents=True, exist_ok=True)

TOPIC = "远程交付团队的周会节奏（测试夹具）"
NOTE = ("本文件是测试夹具（fixture）：域名为 example-* 占位假数据，句子为编造示例文本，"
        "仅用于验证 检索→双源门禁→大纲→成文 链路的分流与结构，不得作为任何事实来源引用。")

brief = {
    "topic": TOPIC,
    "audience": "带 6-15 人交付团队的项目负责人",
    "purpose": "判断周会该开多长、多久一次、哪些环节可以用异步文档替代",
    "core_questions": [
        "远程团队的周会时长与交付缺陷率之间有没有可量化的关系？",
        "哪些会议内容已经被异步文档替代，替代之后出了什么问题？",
    ],
    "_note": NOTE,
}
persps = AR.generate_perspectives(brief)

CONTENT = {
    "现状": [
        ("受访的 42 个远程交付团队平均每周召开 4.5 小时同步会议，其中约三分之一没有形成任何可执行的决议。", "example.com", "example.org"),
        ("七成受访团队保留了每日站会这一形式，但把单次日站时长从 25 分钟压缩到了 10 分钟以内。", "example.net", None),
    ],
    "变化": [
        ("把每周例会从 60 分钟改成 25 分钟之后，会后书面纪要的平均字数不降反升，增加了约四成。", "example.com", "example.org"),
        ("书面状态更新工具普及以来，大约两成低价值同步会被异步文档取代，替代过程集中在近两年完成。", "example.net", None),
    ],
    "动因": [
        ("跨时区协作使固定时间的同步会议成本显著上升，参与方不得不在会议之外补齐上下文，异步文档因此成为默认选择。", "example.org", "example.net"),
    ],
    "影响": [
        ("会议时长压缩之后，一线工程师单次不被打断的连续编码时长中位数从 1.8 小时提高到 2.6 小时。", "example.com", "example.net"),
        ("纯异步流程下的新入职成员，首次提问到获得有效回复的等待时间中位数增加了 6 个小时。", "example.org", None),
    ],
    "反例": [
        ("有两家团队在完全取消周会之后的两个月内交付事故数量翻倍，随后恢复了每周一次的同步会议并保留书面纪要。", "example.net", "example.com"),
    ],
}

queries = {}
for p in persps:
    name = p["name"]
    items = CONTENT.get(name, [])
    results = []
    for j, (sent, d1, d2) in enumerate(items):
        results.append({"url": f"https://{d1}/report/{name}-{j}", "title": f"{name}样本 A{j}", "snippet": sent})
        if d2:
            results.append({"url": f"https://{d2}/mirror/{name}-{j}", "title": f"{name}样本 B{j}", "snippet": sent})
    for idx, q in enumerate(p["questions"]):
        queries[q] = results if idx == 0 else []

injected = {"_note": NOTE, "queries": queries}
(FIXDIR / "topic_brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
(FIXDIR / "injected.json").write_text(json.dumps(injected, ensure_ascii=False, indent=2), encoding="utf-8")
print("perspectives:", [p["name"] for p in persps], "queries:", len(queries))
