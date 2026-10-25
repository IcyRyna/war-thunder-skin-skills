"""Windows Photoshop COM/ExtendScript UV review adapter.

--probe attaches only to an already active Photoshop. Normal use also attaches
by default; --launch explicitly permits starting an installed Photoshop.
Composa is a different editor and is never reported as native Photoshop.
"""
from pathlib import Path
import argparse
import json
import sys
import hashlib

JS = r'''
(function(cfg) {
    function quote(s) { return '"' + String(s).replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n') + '"'; }
    var initial = {}, activeId = null, owned = null, sourceCount = app.documents.length;
    var i;
    for (i=0; i<app.documents.length; i++) initial[String(app.documents[i].id)] = true;
    if (app.documents.length) activeId = app.activeDocument.id;
    function restoreActive() {
        if (activeId === null) return;
        for (var j=0; j<app.documents.length; j++) if (app.documents[j].id === activeId) { app.activeDocument=app.documents[j]; return; }
    }
    function addLayer(path, name) {
        var src = app.open(new File(path)), imported = null;
        try {
            var old = src.activeLayer.bounds;
            var x = old[0].as('px'), y = old[1].as('px');
            imported = src.activeLayer.duplicate(owned, ElementPlacement.PLACEATBEGINNING);
            app.activeDocument = owned;
            var current = imported.bounds;
            imported.translate(UnitValue(x-current[0].as('px'),'px'), UnitValue(y-current[1].as('px'),'px'));
            imported.name = name;
        } finally {
            if (!initial[String(src.id)] && src.id !== owned.id) src.close(SaveOptions.DONOTSAVECHANGES);
            app.activeDocument = owned;
        }
        return imported;
    }
    try {
        owned = app.documents.add(UnitValue(cfg.width,'px'), UnitValue(cfg.height,'px'), 72,
            'Native UV review', NewDocumentMode.RGB, DocumentFill.TRANSPARENT, 1, BitsPerChannelType.EIGHT);
        var base = addLayer(cfg.base, 'SOURCE_COLOUR');
        var guide = addLayer(cfg.wire, 'UV_GUIDE_HIDE_FOR_EXPORT'); guide.opacity = 70;
        var psd = new PhotoshopSaveOptions(); psd.layers = true;
        owned.saveAs(new File(cfg.psd), psd, false, Extension.LOWERCASE);
        var png = new PNGSaveOptions(); png.interlaced = false;
        owned.saveAs(new File(cfg.guide_preview), png, true, Extension.LOWERCASE);
        guide.visible = false;
        owned.saveAs(new File(cfg.clean_export), png, true, Extension.LOWERCASE);
        guide.visible = true; owned.save();
        var ownedId = owned.id;
        owned.close(SaveOptions.DONOTSAVECHANGES); owned = null;
        restoreActive();
        return '{"ok":true,"document_id":'+ownedId+',"initial_document_count":'+sourceCount+',"final_document_count":'+app.documents.length+'}';
    } catch (error) {
        var recovered = false;
        if (owned !== null) {
            try { var opt = new PhotoshopSaveOptions(); opt.layers = true; owned.saveAs(new File(cfg.recovery), opt, false, Extension.LOWERCASE); recovered = true; } catch (ignored) {}
        }
        // Leave the owned document open on failure, never discard it or close others.
        restoreActive();
        return '{"ok":false,"error":'+quote(error)+',"recovery_saved":'+recovered+',"owned_document_left_open":'+(owned!==null)+'}';
    }
})(__WT_UV_CONFIG__);
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--launch', action='store_true')
    p.add_argument('--base', type=Path)
    p.add_argument('--wire', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.probe and a.launch:
        p.error('--probe cannot launch Photoshop')
    if a.out.exists() and any(a.out.iterdir()):
        p.error('--out must be new/empty')
    a.out.mkdir(parents=True, exist_ok=True)
    record = {'backend': 'native Adobe Photoshop COM/ExtendScript', 'launched': False, 'mode': 'probe' if a.probe else 'UV review'}
    try:
        import win32com.client
        try:
            app = win32com.client.GetActiveObject('Photoshop.Application')
        except Exception:
            if not a.launch:
                raise RuntimeError('No active native Photoshop COM session; no application was launched. Composa does not satisfy this native-Photoshop probe.')
            app = win32com.client.Dispatch('Photoshop.Application'); record['launched'] = True
        info = str(app.DoJavaScript("app.version + '|' + app.documents.length;"))
        record.update(status='available', version_and_document_count=info)
    except Exception as error:
        record.update(status='unavailable', reason=str(error))
        (a.out / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=True)); return 2
    if not a.probe:
        if a.base is None or a.wire is None:
            p.error('--base and --wire are required for review')
        from PIL import Image
        files = [a.base.resolve(strict=True), a.wire.resolve(strict=True)]
        if any(x.suffix.lower() != '.png' for x in files):
            p.error('Use lossless colour PNG and transparent UV PNG; preserve original DDS separately')
        if any(a.out.resolve() in x.parents for x in files):
            p.error('Output must not contain its inputs')
        sizes = []
        for path in files:
            with Image.open(path) as image:
                sizes.append(image.size)
        if sizes[0] != sizes[1]:
            p.error('Base and UV guide must have identical original atlas dimensions')
        cfg = {'base': str(files[0]), 'wire': str(files[1]), 'width': sizes[0][0], 'height': sizes[0][1],
               'psd': str((a.out / 'native-uv-review.psd').resolve()),
               'guide_preview': str((a.out / 'uv-guide-preview.png').resolve()),
               'clean_export': str((a.out / 'colour-without-guide.png').resolve()),
               'recovery': str((a.out / 'failed-owned-document-recovery.psd').resolve())}
        fingerprints = {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in files}
        code = 'var __WT_UV_CONFIG__ = ' + json.dumps(cfg, ensure_ascii=True) + ';\n' + JS
        (a.out / 'executed.jsx').write_text(code, encoding='utf-8')
        try:
            result = json.loads(str(app.DoJavaScript(code)))
        except Exception as error:
            record.update(status='unknown_after_call', reason=str(error), automatic_retry_allowed=False,
                          recovery='Inspect native Photoshop documents and executed.jsx before any retry; do not discard or close unknown work')
            (a.out / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(record, ensure_ascii=True)); return 1
        record.update(status='success' if result.get('ok') else 'failed', result=result, inputs=fingerprints)
        if result.get('ok'):
            for key in ['psd', 'guide_preview', 'clean_export']:
                path = Path(cfg[key])
                if not path.is_file() or not path.stat().st_size:
                    record.update(status='failed_missing_output', missing_output=key)
            if record['status'] == 'success':
                import numpy as np
                with Image.open(files[0]) as original, Image.open(cfg['clean_export']) as clean:
                    record['clean_export_rgba_exact'] = bool(np.array_equal(np.asarray(original.convert('RGBA')), np.asarray(clean.convert('RGBA'))))
                if not record['clean_export_rgba_exact']:
                    record['status'] = 'failed_colour_roundtrip'
        record['source_files_unchanged'] = all(hashlib.sha256(Path(x).read_bytes()).hexdigest() == h for x, h in fingerprints.items())
        if not record['source_files_unchanged']:
            record['status'] = 'failed_input_changed'
    (a.out / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=True))
    return 0 if record['status'] in ['available', 'success'] else 1


if __name__ == '__main__':
    sys.exit(main())
