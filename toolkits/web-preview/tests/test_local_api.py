import io
import json
from pathlib import Path
import tempfile
import unittest

from local_api import LocalAPI


class Handler:
    def __init__(self,headers=None):
        self.headers=headers or {};self.wfile=io.BytesIO();self.rfile=io.BytesIO();self.status=None
    def send_response(self,status):self.status=status
    def send_header(self,*args):pass
    def end_headers(self):pass
    def send_error(self,status):self.status=status


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.api=LocalAPI(self.root,self.root/'imports','game','extractor','python')
    def tearDown(self):self.temp.cleanup()
    def test_other_origins_hosts_and_missing_tokens_cannot_submit(self):
        for headers in ({},{'Host':'evil.example','X-Workbench-Token':self.api.token},
                        {'Host':'127.0.0.1:8000','Origin':'http://evil.example','X-Workbench-Token':self.api.token},
                        {'Host':'127.0.0.1:8000','Origin':'http://127.0.0.1:9000','X-Workbench-Token':self.api.token}):
            h=Handler(headers);self.api.post(h,'/api/import-skin');self.assertEqual(h.status,403)
        self.assertFalse((self.root/'imports').exists())
        self.assertTrue(self.api.authorized(Handler({'Host':'localhost:8000','Origin':'http://localhost:8000','X-Workbench-Token':self.api.token})))
    def test_only_allowlisted_ready_scene_files_are_served(self):
        scene=self.root/'scene';scene.mkdir();(scene/'scene.json').write_text(json.dumps({'materials':[]}));(scene/'raw.grp').write_bytes(b'private')
        identifier='a'*32;self.api.jobs[identifier]={'state':'ready','scene':str(scene)}
        h=Handler();self.assertTrue(self.api.get(h,f'/imports/{identifier}/raw.grp'));self.assertEqual(h.status,404)
        h=Handler();self.api.get(h,f'/imports/{identifier}/scene.json');self.assertEqual(h.status,200)
        self.api.jobs[identifier]['state']='working';h=Handler();self.api.get(h,f'/imports/{identifier}/scene.json');self.assertEqual(h.status,404)
    def test_ready_reflection_files_are_allowlisted_but_raw_inputs_are_not(self):
        scene=self.root/'scene';scene.mkdir();native=scene/'native-orm-000.png';native.write_bytes(b'png')
        (scene/'scene.json').write_text(json.dumps({'materials':[{'reflection':{'orm':{'file':native.name},'normal':{'file':'../private.png'}}}]}))
        identifier='c'*32;self.api.jobs[identifier]={'state':'ready','scene':str(scene)}
        h=Handler();self.api.get(h,f'/imports/{identifier}/{native.name}');self.assertEqual(h.status,200);self.assertEqual(h.wfile.getvalue(),b'png')
        h=Handler();self.api.get(h,f'/imports/{identifier}/private.png');self.assertEqual(h.status,404)

    def test_upload_size_validation_does_not_create_job_or_directory(self):
        h=Handler({'Host':'127.0.0.1:8000','X-Workbench-Token':self.api.token,'Content-Length':str(513*1024*1024)})
        self.api.post(h,'/api/import-skin');self.assertEqual(h.status,400);self.assertFalse(self.api.jobs);self.assertFalse((self.root/'imports').exists())
    def test_status_does_not_expose_raw_working_folder(self):
        identifier='b'*32;self.api.jobs[identifier]={'state':'error','folder':str(self.root),'discovery':'private.json','message':'bad input'}
        h=Handler();self.api.get(h,f'/api/imports/{identifier}');data=json.loads(h.wfile.getvalue())
        self.assertNotIn('folder',data);self.assertNotIn('discovery',data);self.assertEqual(data['message'],'bad input')


if __name__=='__main__':unittest.main()
