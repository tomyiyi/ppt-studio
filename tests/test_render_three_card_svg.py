import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SPEC=importlib.util.spec_from_file_location("render_three_card_svg",ROOT/"scripts"/"render_three_card_svg.py")
MODULE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)
class ThreeCardTests(unittest.TestCase):
    def test_valid_deterministic(self):
        plan={"schema":"ppt-studio-slide-plan/v1","slides":[{"id":"01","kind":"cover","title":"AgentFlow","blocks":[]},{"id":"02","kind":"content","title":"三个核心能力","blocks":[{"type":"paragraph","text":"上下文理解决定现在发生了什么。"},{"type":"paragraph","text":"工具执行让计划真正作用于外部世界。"},{"type":"paragraph","text":"状态恢复保证失败之后可以继续运行。"}]}]}
        raw=json.dumps(plan,ensure_ascii=False).encode(); intent={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(raw).hexdigest(),"slides":[{"id":"01","layout":"cover"},{"id":"02","layout":"three-card"}]}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); pp=p/"p.json"; ii=p/"i.json"; pp.write_bytes(raw); ii.write_text(json.dumps(intent),encoding="utf-8")
            out1=MODULE.validate(plan,raw,intent); out2=MODULE.validate(plan,raw,intent); self.assertEqual(out1,out2); self.assertEqual(len(out1[0]["texts"]),3)
    def test_invalid_shapes(self):
        base={"id":"01","kind":"content","title":"T","blocks":[{"type":"paragraph","text":"a"},{"type":"paragraph","text":"b"},{"type":"paragraph","text":"c"},{"type":"paragraph","text":"d"}]}
        raw=b"{}"; it={"schema":"ppt-studio-layout-intent/v1","source_plan_sha256":hashlib.sha256(raw).hexdigest(),"slides":[{"id":"01","layout":"three-card"}]}
        with self.assertRaises(ValueError): MODULE.validate({"schema":"ppt-studio-slide-plan/v1","slides":[base]},raw,it)
if __name__=="__main__": unittest.main()
