import hashlib, json, re, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.apply_theme import main

class ThemeTest(unittest.TestCase):
    def test_image_scrim_role_maps_stop_color_without_touching_stop_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            source='<svg><rect fill="#08090C"/><linearGradient><stop data-theme-role="image-scrim" offset="0.45" stop-color="#08090C" stop-opacity="0.80"/></linearGradient></svg>'
            (src/'01.svg').write_text(source)
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#08090C':'#FFFFFF'},'role_colors':{'image-scrim':{'#08090C':'#0F172A'}}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('<rect fill="#FFFFFF"/>', got)
            self.assertIn('data-theme-role="image-scrim" offset="0.45" stop-color="#0F172A" stop-opacity="0.80"', got)

    def test_only_allowed_roles_are_used_in_core_slice(self):
        allowed={'on-image','on-dark-surface','on-accent','image-scrim'}
        text=(Path(__file__).resolve().parents[1]/'projects/agentflow-os-launch/svg_output/04_capability_selfheal.svg').read_text()
        roles=set(re.findall(r'data-theme-role="([^"]+)"', text))
        self.assertTrue(roles <= allowed)
        self.assertEqual(roles, {'on-image','on-dark-surface','on-accent','image-scrim'})

    def test_scrim_metadata_does_not_change_non_metadata_source(self):
        import subprocess
        import re
        baseline=subprocess.check_output(['git','show','7b50234:projects/agentflow-os-launch/svg_output/04_capability_selfheal.svg'], text=True)
        current=(Path(__file__).resolve().parents[1]/'projects/agentflow-os-launch/svg_output/04_capability_selfheal.svg').read_text()
        strip=lambda s: re.sub(r'\sdata-theme-role="[^"]+"','',s)
        self.assertEqual(strip(baseline), strip(current))
    def test_only_declared_colors_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            (src/'01.svg').write_text('<svg viewBox="0 0 1 1"><rect fill="#08090C"/><path stroke="#ABCDEF"/><text x="1">文案</text></svg>')
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#08090C':'#111827'}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('#111827',got); self.assertIn('#ABCDEF',got); self.assertIn('文案',got)
            self.assertIn('viewBox="0 0 1 1"',got)

    def test_role_override_beats_global_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            (src/'01.svg').write_text('<svg><text fill="#8E8F9A">plain</text><text data-theme-role="on-image" fill="#8E8F9A">image</text></svg>')
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#8E8F9A':'#374151'},'role_colors':{'on-image':{'#8E8F9A':'#F8FAFC'}}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertRegex(got, r'<text fill="#374151">plain')
            self.assertRegex(got, r'<text data-theme-role="on-image" fill="#F8FAFC">image')

    def test_role_falls_back_to_global_and_supports_color_attributes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            (src/'01.svg').write_text('<svg><g data-theme-role="on-dark-surface" stroke="#8E8F9A"><stop data-theme-role="on-dark-surface" stop-color="#6E7BFF"/><path fill="#4ADE80"/></g></svg>')
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#8E8F9A':'#374151','#6E7BFF':'#0000AA','#4ADE80':'#16A34A'},'role_colors':{'on-dark-surface':{'#8E8F9A':'#CBD5E1','#6E7BFF':'#93C5FD'}}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('stroke="#CBD5E1"', got)
            self.assertIn('stop-color="#93C5FD"', got)
            self.assertIn('fill="#16A34A"', got)

    def test_same_source_color_can_have_distinct_roles(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            (src/'01.svg').write_text('<svg><text data-theme-role="on-image" fill="#8E8F9A"/><text data-theme-role="on-dark-surface" fill="#8E8F9A"/><text fill="#8E8F9A"/></svg>')
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#8E8F9A':'#374151'},'role_colors':{'on-image':{'#8E8F9A':'#F8FAFC'},'on-dark-surface':{'#8E8F9A':'#CBD5E1'}}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('data-theme-role="on-image" fill="#F8FAFC"', got)
            self.assertIn('data-theme-role="on-dark-surface" fill="#CBD5E1"', got)
            self.assertIn('<text fill="#374151"', got)

    def test_non_color_attributes_and_metadata_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            original='<svg viewBox="0 0 10 10"><image href="../images/a.png" x="1" y="2" width="3" height="4"/><text data-theme-role="on-accent" x="5" y="6" font-size="12" transform="scale(1)" fill="#08090C">0</text></svg>'
            (src/'01.svg').write_text(original)
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#08090C':'#FFFFFF'},'role_colors':{'on-accent':{'#08090C':'#111827'}}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('data-theme-role="on-accent"', got)
            self.assertIn('href="../images/a.png" x="1" y="2" width="3" height="4"', got)
            self.assertIn('x="5" y="6" font-size="12" transform="scale(1)" fill="#111827"', got)
            self.assertEqual((src/'01.svg').read_text(), original)
    def test_output_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            p=src/'01.svg'; p.write_text('<svg fill="#08090C"/>'); before=hashlib.sha256(p.read_bytes()).hexdigest()
            theme=root/'theme.json'; theme.write_text('{"name":"x","colors":{"#08090C":"#111827"}}')
            main([str(src),str(out),'--theme',str(theme)])
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())

if __name__=='__main__': unittest.main()
