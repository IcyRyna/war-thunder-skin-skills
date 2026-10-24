import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('online_build',ROOT/'tools/build_online.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class OnlineBuildTests(unittest.TestCase):
    def test_distribution_contains_preview_controls_and_no_editor_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            output=module.build(Path(folder)/'online');files={p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(files,{'index.html',*module.FILES})
            text=(output/'index.html').read_text(encoding='utf-8');code=(output/'preview.js').read_text(encoding='utf-8')
            for identifier in ['quality','reflectionEnabled','reflectionAmount','normalEnabled','capture']:
                self.assertIn('id="'+identifier+'"',text)
            for marker in ['type="file"','id="creative"','id="saveProject"','id="textureFile"','id="uv"','id="partEditor"','id="skinImport"']:
                self.assertNotIn(marker,text)
            for name in ['app.js','editor.js','editor-core.js','skin-open.js','project.py','local_api.py']:
                self.assertNotIn(name,files);self.assertNotIn(name,code)
            self.assertNotIn("method:'POST'",code);self.assertNotIn('createEditor',code)

    def test_local_editor_is_preserved_and_output_is_never_overwritten(self):
        before=(ROOT/'web/index.html').read_bytes();self.assertIn(b'id="creative"',before);self.assertIn(b'id="saveProject"',(ROOT/'web/editor.js').read_bytes())
        with tempfile.TemporaryDirectory() as folder:
            output=module.build(Path(folder)/'online')
            with self.assertRaises(FileExistsError):module.build(output)
        self.assertEqual(before,(ROOT/'web/index.html').read_bytes())


if __name__=='__main__':unittest.main()
