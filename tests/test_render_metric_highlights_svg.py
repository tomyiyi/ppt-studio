import sys, unittest, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import render_metric_highlights_svg as renderer

class MetricRendererTests(unittest.TestCase):
    def test_deterministic_render(self):
        plan={'schema':'ppt-studio-slide-plan/v1','slides':[{'id':'02','kind':'content','title':'K','blocks':[{'type':'metric-list','items':[{'label':'A','value':'1'},{'label':'B','value':'2'}]}]}]}
        raw=b'plan'; intent={'schema':'ppt-studio-layout-intent/v1','source_plan_sha256':__import__('hashlib').sha256(raw).hexdigest(),'slides':[{'id':'02','layout':'metric-highlights'}]}
        c={'background':'#000000','surface':'#111111','primary_text':'#ffffff','secondary_text':'#888888','accent':'#4444ff','divider':'#222222'}; s={'kicker':11,'body':24,'caption':13}
        a=renderer.render(renderer.validate(plan,raw,intent)[0],1,c,s,'Arial'); b=renderer.render(renderer.validate(plan,raw,intent)[0],1,c,s,'Arial')
        self.assertEqual(a,b); self.assertIn('metric highlights', a.lower())

if __name__ == '__main__': unittest.main()
