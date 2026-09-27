import hashlib, json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.apply_theme import main

class ThemeTest(unittest.TestCase):
    def test_only_declared_colors_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            (src/'01.svg').write_text('<svg viewBox="0 0 1 1"><rect fill="#08090C"/><path stroke="#ABCDEF"/><text x="1">文案</text></svg>')
            theme=root/'theme.json'; theme.write_text(json.dumps({'name':'x','colors':{'#08090C':'#111827'}}))
            main([str(src),str(out),'--theme',str(theme)])
            got=(out/'01.svg').read_text()
            self.assertIn('#111827',got); self.assertIn('#ABCDEF',got); self.assertIn('文案',got)
            self.assertIn('viewBox="0 0 1 1"',got)
    def test_output_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=root/'src'; out=root/'out'; src.mkdir()
            p=src/'01.svg'; p.write_text('<svg fill="#08090C"/>'); before=hashlib.sha256(p.read_bytes()).hexdigest()
            theme=root/'theme.json'; theme.write_text('{"name":"x","colors":{"#08090C":"#111827"}}')
            main([str(src),str(out),'--theme',str(theme)])
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())

if __name__=='__main__': unittest.main()
