#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_topic_to_deck.py — 编排层自检（全部用桩函数，**不打任何 API、不起子进程**）

29 项：阶段选择 4、T-01 入口门禁 3、argv 组装 8、执行与停等 8、续跑与卫生 6。
判据来自 scripts/topic_to_deck.py 的实现契约与 RUN-20261015 计划的硬约束。
"""
import sys, os, json, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))

import topic_to_deck as TD

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


class Stub:
    """记录每次被调用的 argv；按 stage 返回预设 rc/stdout。"""

    def __init__(self, rc=0, stdout="", rc_by_keyword=None, stdout_by_keyword=None):
        self.calls = []
        self.rc = rc
        self.stdout = stdout
        self.rc_by_keyword = rc_by_keyword or {}
        self.stdout_by_keyword = stdout_by_keyword or {}

    def __call__(self, cmd):
        self.calls.append([str(c) for c in cmd])
        joined = " ".join(str(c) for c in cmd)
        rc = self.rc
        out = self.stdout
        for kw, v in self.rc_by_keyword.items():
            if kw in joined:
                rc = v
        for kw, v in self.stdout_by_keyword.items():
            if kw in joined:
                out = v
        return type("P", (), {"returncode": rc, "stdout": out, "stderr": ""})()


def cfg_of(extra, topic="测试主题", wd=None):
    wd = wd or tempfile.mkdtemp()
    argv = ["--topic", topic, "--workdir", wd,
            "--core-questions", "这条链的瓶颈在哪；纯文字版能不能一次跑通"] + extra
    return TD.build_parser().parse_args(argv), wd


print("[A] 阶段选择")
cfg, _ = cfg_of([])
ok("A1 默认全跑 6 段", TD.select_stages(cfg) == TD.STAGES, str(TD.select_stages(cfg)))
cfg, _ = cfg_of(["--stage", "deck,research"])
ok("A2 --stage 子集仍按固定顺序", TD.select_stages(cfg) == ["research", "deck"],
   str(TD.select_stages(cfg)))
cfg, _ = cfg_of(["--from", "gate"])
ok("A3 --from 起点切片", TD.select_stages(cfg) == ["gate", "deck"], str(TD.select_stages(cfg)))
cfg, _ = cfg_of(["--stage", "nope"])
try:
    TD.select_stages(cfg)
    ok("A4 未知阶段被拒", False, "没抛异常")
except TD.ConfigError as e:
    ok("A4 未知阶段被拒", True, str(e)[:40])

print("\n[B] T-01 入口门禁（core_questions ≥2）")
try:
    TD.validate_brief({"topic": "T", "core_questions": ["只有一条"]})
    ok("B1 单条问题被拒", False, "没抛异常")
except TD.ConfigError as e:
    ok("B1 单条问题被拒", "core_questions 只有 1 条" in str(e), str(e)[:48])
try:
    TD.validate_brief({"topic": "  ", "core_questions": ["一", "二"]})
    ok("B2 空主题被拒", False, "没抛异常")
except TD.ConfigError as e:
    ok("B2 空主题被拒", True, str(e)[:30])
ok("B3 两条以上放行", TD.validate_brief(
    {"topic": "T", "core_questions": ["一", "二", "三"]}) is None, "")

print("\n[C] argv 组装")
with tempfile.TemporaryDirectory() as td:
    inj = Path(td) / "injected.json"; inj.write_text("{}", encoding="utf-8")
    cfg, wd = cfg_of(["--injected", str(inj), "--no-images"], wd=td)
    argv = TD.stage_argv(cfg)
    ok("C1 有 --injected 时 research 段带注入源", "--injected" in argv["research"], "")
    ok("C2 无 key 也能纯离线组装（argv 不含 tavily 调用）",
       not any("tavily" in " ".join(v).lower() for v in argv.values()), "")
    ok("C3 deck 段透传 --no-images", "--no-images" in argv["deck"], "")
    cfg2, _ = cfg_of(["--injected", str(inj)], wd=td)
    ok("C4 未指定 --no-images 时 deck 不带该参数",
       "--no-images" not in TD.stage_argv(cfg2)["deck"], "")
    ok("C5 六段脚本名与顺序正确",
       [Path(argv[s][1]).name for s in ["research", "article", "narrative", "gate", "deck"]] ==
       ["auto_research.py", "write_article.py", "plan_narrative.py",
        "check_narrative.py", "md_to_pptx.py"], "")

    ok("C6 gate 段素材根 = article.md 所在目录（W-19 回指依赖）",
       Path(argv["gate"][-1]).name == "article" and
       Path(argv["narrative"][argv["narrative"].index("--md") + 1]).parts[-2:] == ("article", "article.md"),
       argv["gate"][-1])

    # C7/C8：配图意图只能显式传入，编排器不自动生成（S4 对账）
    ip = Path(td) / "intent_plan.json"
    ip.write_text('{"第一节": "panel"}', encoding="utf-8")
    cfg3, _ = cfg_of(["--injected", str(inj), "--intent-plan", str(ip)], wd=td)
    nv = TD.stage_argv(cfg3)["narrative"]
    ok("C7 --intent-plan 显式透传给 narrative 段",
       "--intent-plan" in nv and nv[nv.index("--intent-plan") + 1] == str(ip), "")
    ok("C8 未传 --intent-plan 时 narrative 段不带该参数"
       "（默认由 check_narrative W-30 登记未声明）",
       "--intent-plan" not in TD.stage_argv(cfg2)["narrative"], "")

print("\n[D] 执行、停等与 dry-run")
with tempfile.TemporaryDirectory() as td:
    inj = Path(td) / "injected.json"; inj.write_text("{}", encoding="utf-8")
    cfg, wd = cfg_of(["--injected", str(inj), "--dry-run", "--no-images"], wd=td)
    s = Stub()
    TD.run(cfg, execute=s, log=lambda *_: None)
    ok("D1 --dry-run 零子进程调用", len(s.calls) == 0, f"calls={len(s.calls)}")
    ok("D2 --dry-run 不写产物只给计划",
       not (Path(wd) / "research.json").exists(), "")

    cfg, wd = cfg_of(["--injected", str(inj), "--no-images"], wd=td)
    s = Stub(stdout="完成")
    summ = TD.run(cfg, execute=s, log=lambda *_: None)
    ok("D3 全链 5 次子进程（brief 在本进程内）", len(s.calls) == 5, f"calls={len(s.calls)}")
    ok("D4 deck 是最后一次调用", "md_to_pptx.py" in " ".join(s.calls[-1]), "")
    ok("D5 全绿时 stopped_at 为 None", summ["stopped_at"] is None, str(summ["stopped_at"]))

    cfg, wd = cfg_of(["--injected", str(inj)], wd=td)
    s = Stub(rc_by_keyword={"check_narrative.py": 1},
             stdout_by_keyword={"check_narrative.py":
                                 "  BLOCKING  x\n\nblocking 24 条 / 需人读 3 条"})
    summ = TD.run(cfg, execute=s, log=lambda *_: None)
    ok("D6 门禁 blocking>0 时立即停，deck 未被调用",
       summ["stopped_at"] == "gate" and not any("md_to_pptx" in " ".join(c) for c in s.calls),
       f"calls={len(s.calls)}")
    ok("D7 blocking 条数原样解析（未动判据）", summ["blocking"] == 24, str(summ["blocking"]))
    ok("D8 停等时写 gate_report.json",
       (Path(wd) / "gate_report.json").exists(), "")

print("\n[E] 续跑与卫生")
ok("E1 parse_blocking 解析口径", TD.parse_blocking("blocking 7 条 / 需人读 2 条") == 7, "")
ok("E2 parse_blocking 缺字段返回 None", TD.parse_blocking("没有这个数字") is None, "")
with tempfile.TemporaryDirectory() as td:
    inj = Path(td) / "injected.json"; inj.write_text("{}", encoding="utf-8")
    cfg, wd = cfg_of(["--injected", str(inj), "--resume"], wd=td)
    Path(wd, "research.json").write_text("{}", encoding="utf-8")
    TD.save_state(Path(wd) / "state.json",
                  {"stages": {"research": {"status": "done"}}})
    s = Stub()
    summ = TD.run(cfg, execute=s, log=lambda *_: None)
    ok("E3 --resume 跳过已完成且产物在盘的阶段",
       summ["stages"]["research"] == "skipped" and len(s.calls) == 4,
       f"calls={len(s.calls)}")
    state = json.loads((Path(wd) / "state.json").read_text(encoding="utf-8"))
    ok("E4 state.json 逐段留痕（断电可续）",
       all(k in state["stages"] for k in ["brief", "research", "article", "narrative", "gate", "deck"]),
       str(sorted(state["stages"].keys())))

allcmds = " ".join(" ".join(c) for c in s.calls)
ok("E5 组装出的命令行不含任何密钥字面量",
   not any(tok in allcmds for tok in ["sk-", "Bearer", "api_key="]), "")

_saved = os.environ.pop("TAVILY_API_KEY", None)
with tempfile.TemporaryDirectory() as td:
    rc = TD.main(["--topic", "T", "--workdir", str(Path(td) / "x"),
                  "--core-questions", "一；二"])
ok("E6 既无 --injected 又无检索 key 时拒绝执行（不伪造检索）", rc == 2, f"rc={rc}")
if _saved is not None:
    os.environ["TAVILY_API_KEY"] = _saved

print("\n" + "=" * 56)
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(0 if FAIL == 0 else 1)
