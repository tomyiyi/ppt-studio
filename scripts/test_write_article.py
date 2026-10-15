#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_write_article.py — 成文层（T-01…T-12）自检

26 项：分流与双源门禁 5、从缺 2、大纲结构 4、成文细则 6、导语取料 7、hook 与附录措辞 2。
判据一律来自 skills/article-writing-from-topic/SKILL.md 与 write_article.py 的实现口径，
**禁止为通过而放宽**；红了就判"半截实现"还是"真缺陷"，如实记录。
"""
import sys, os, json, re, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from pathlib import Path

import write_article as WA

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}   {detail}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "spikes/RUN-20261015/fixtures/research_fixture.json"

print("[A] 分流与双源门禁（T-02/T-03）")

if not FIXTURE.exists():
    print(f"  缺夹具：{FIXTURE}")
    sys.exit(1)

research = WA.load_research(FIXTURE)
verified, unverified = WA.split_claims(research["claims"])
ok("A1 split_claims 全量分流", len(verified) + len(unverified) == len(research["claims"]),
   f"verified={len(verified)} unverified={len(unverified)} total={len(research['claims'])}")
ok("A2 verified 均为双源以上", all(WA._domain_count(c) >= 2 for c in verified),
   f"最低域名数={min((WA._domain_count(c) for c in verified), default=None)}")
ok("A3 unverified 均未达双源", all(WA._domain_count(c) < 2 for c in unverified),
   f"最高域名数={max((WA._domain_count(c) for c in unverified), default=None)}")

outline = WA.build_outline(research, verified)
article = WA.write_article(research, outline, verified, unverified)
body = article.split("---")[0] if "---" in article else article

# 正文禁止出现任何 unverified 的句子（逐条取前 12 字做子串判定，避免标点差异）
leaked = [c["claim"][:12] for c in unverified if c["claim"][:12] in body]
ok("A4 正文零泄漏 unverified", not leaked, f"泄漏={leaked}")
ok("A5 附录收全 unverified", all(c["claim"] in article for c in unverified),
   f"附录应含 {len(unverified)} 条")

print("\n[B] verified 为空时必须从缺（T-03，禁止硬写）")
empty_research = {"topic": "空验证主题", "perspectives": [{"name": "现状"}], "claims": []}
v0, u0 = WA.split_claims([])
o0 = WA.build_outline(empty_research, v0)
a0 = WA.write_article(empty_research, o0, v0, u0)
ok("B1 导语声明从缺", "暂无通过双源验证的结论" in a0, "")
ok("B2 有研究说明节、无结论节", "## 研究说明" in a0 and "## 是什么" not in a0, "")

print("\n[C] 大纲结构与节序（T-06）")
order = {n: i for i, (n, _) in enumerate(WA.PERSPECTIVE_FLOW)}
pidx = [order.get(s["perspective"], 99) for s in outline["sections"]]
ok("C1 节序按 PERSPECTIVE_FLOW 单调不减", pidx == sorted(pidx), f"perspectives={[s['perspective'] for s in outline['sections']]}")
ok("C2 每节 claim ≤3", all(len(s["claim_ids"]) <= 3 for s in outline["sections"]),
   f"最多={max((len(s['claim_ids']) for s in outline['sections']), default=0)}")
many = [{"id": f"x{i}", "claim": f"结论{i}", "evidence": "", "sources": [], "perspectives": ["现状"]} for i in range(7)]
o_many = WA.build_outline({"perspectives": [{"name": "现状"}]}, many)
titles = [s["title"] for s in o_many["sections"]]
ok("C3 超 3 条拆节并标（续）", len(o_many["sections"]) == 3 and titles[1].endswith("（续）"),
   f"sections={len(o_many['sections'])} titles={titles}")
ok("C4 无 verified 的视角不建节",
   all(any(c["id"] in s["claim_ids"] for s in o_many["sections"]) for c in many),
   f"claims=7 sections={len(o_many['sections'])}")

print("\n[D] 成文细则（T-04/T-07/T-08/T-09）")
# 只看 claim 展开出来的正文段（导语与"写在最后"不是 claim 段，另行判定）
claim_paras = [WA.expand_claim(c) for c in verified]
body_paras = [p for p in article.split("\n\n")
              if p and not p.startswith(("#", ">", "---", "- "))
              and not p.startswith("以下 ") and "（待验证）" not in p
              and not p.startswith("本篇基于") and not p.startswith("一句话总结")
              and not p.startswith("本次研究") and not p.startswith("本次检索")]
ok("D1 每个 claim 段以句末标点+来源收尾",
   all(re.search(r"[。！？]（[^）]+）$", p) for p in claim_paras),
   f"claim 段数={len(claim_paras)} 未命中={[p[-24:] for p in claim_paras if not re.search('[。！？]（', p)][:2]}")
ok("D2 claim 段以全角括号域名列表收尾",
   all(re.search(r"（[a-z0-9.\-]+(?:、[a-z0-9.\-]+)*）$", p) for p in claim_paras),
   f"未命中={[p[-20:] for p in claim_paras if not re.search('）$', p)][:2]}")
ok("D3 来源域名已剥 www", not any("www." in p for p in claim_paras), "")
ok("D4 正文段数与 verified 一致（一节一段，不合并吞段）",
   len(body_paras) == len(verified), f"body={len(body_paras)} verified={len(verified)}")
ok("D5「覆盖 N 个」保留空格（10-10 修复回归锁）",
   re.search(r"覆盖 \d+ 个方面", article) is not None, "")
# 转述去重：evidence 与 claim 同句时不得重复陈述
dup_claim = {"claim": "会议压缩后连续编码时长从 1.8 小时升到 2.6 小时",
             "evidence": "会议压缩后连续编码时长从 1.8 小时升到 2.6 小时",
             "sources": [{"url": "https://example.com/a"}]}
p_dup = WA.expand_claim(dup_claim)
ok("D6 evidence 与 claim 重复时不重复陈述",
   p_dup.count("连续编码时长") == 1, p_dup)

print("\n[E] 导语取料（宁缺不切：绝不裁出半截数字或半截话）")
long_claim = [{"claim": "会议时长压缩之后，一线工程师单次不被打断的连续编码时长中位数出现了明显变化并且这个变化在不同团队之间差异很大",
               "evidence": "", "sources": [{"url": "https://a.com"}, {"url": "https://b.com"}]}] * 4
lede_long = WA.distill_lede({"topic": "T"}, long_claim)
ok("E1 超长首句整条不取，只报条数", "具体判断见正文各节" in lede_long, lede_long[:48])
short = [{"claim": "周会砍半之后事故翻倍。随后两家团队恢复了每周一次同步。",
          "evidence": "", "sources": [{"url": "https://a.com"}, {"url": "https://b.com"}]}]
lede_short = WA.distill_lede({"topic": "T"}, short)
ok("E2 能装下的首句原样进导语（未裁剪）", "周会砍半之后事故翻倍" in lede_short, lede_short)
ok("E3 单条 verified 走专属句式", "唯一通过双源验证的结论" in lede_short, lede_short)
lede = WA.distill_lede(research, verified)
ok("E4 实际导语不含悬挂数字（旧缺陷回归锁）",
   not re.search(r"从 \d+(?:\.\d+)?\s*。", lede) and not re.search(r"\d(?:\.\d?)?\s+。", lede)
   and not re.search(r"[\d.]\s*$", lede.replace("。", "")), lede[:70])
# 夹具里的 claim 首句普遍超 36 字 => 规则版宁缺不切，导语退化为"只报条数"（已知限制，见 SKILL §7）
ok("E5 规则版对长句夹具如实退化，不硬凑片段",
   "具体判断见正文各节" in lede, lede[:56])
multi = [{"claim": "周会砍半之后事故翻倍。两家团队随即恢复了每周同步。",
          "evidence": "", "sources": [{"url": "https://a.com"}, {"url": "https://b.com"}]},
         {"claim": "纪要字数反而增加四成。书面化并没有省下沟通成本。",
          "evidence": "", "sources": [{"url": "https://c.com"}, {"url": "https://d.com"}]}]
lede_m = WA.distill_lede({"topic": "T"}, multi)
frags = lede_m.split("：", 1)[1].rstrip("。").split("；")
all_claims = " ".join(c["claim"] for c in multi)
ok("E6 能装下的多条主张并列进导语且逐字回指（W-27）",
   len(frags) == 2 and all(f.strip() in all_claims for f in frags), lede_m)
ok("E7 导语取料总长受控", len("；".join(frags)) <= WA.LEDE_TOTAL_MAX,
   f"取料长度={len('；'.join(frags))} 上限={WA.LEDE_TOTAL_MAX}")

print("\n[F] hook 入口与附录措辞（T-11/T-12）")
hooked = dict(research)
hooked["hook"] = {"title": "周会砍掉一半，事故反增", "lede": "5 条双源结论里，最大分歧是取消周会之后交付事故翻倍。"}
a_h = WA.write_article(hooked, outline, verified, unverified)
ok("F1 hook 标题与导语生效", a_h.startswith("# 周会砍掉一半，事故反增")
   and "最大分歧是取消周会之后交付事故翻倍" in a_h, "")
single_only = [{"claim": "甲", "evidence": "", "sources": [{"url": "https://example.com/a"}]}]
lead1 = WA._appendix_lead(single_only)
ok("F2 附录措辞按实际来源数说话", "1 条仅单源" in lead1 and "无可标注来源" not in lead1, lead1)

print("\n" + "=" * 56)
print(f"通过 {PASS} / 失败 {FAIL}")
sys.exit(0 if FAIL == 0 else 1)
