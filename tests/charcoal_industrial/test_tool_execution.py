"""Synthetic evidence-consistency tests, separate from live tool smoke tests."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from PIL import Image

ROOT=(Path(__file__).resolve().parents[2]/'src/styles/ground/wt-style-charcoal-industrial')
sys.path.insert(0,str(ROOT/'scripts'))
from production_tools import audit_tools,collect_session,spec
from editor_batch import build_command
from tank_preview import preview_views
from tank_core import load_obj


class ToolEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='charcoal-tool-contract-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.write('native.cmps',b'synthetic project; not a real editor production claim')
        self.write('copy.cmps',(self.root/'native.cmps').read_bytes())
        for name in ('saved.png','reopened.png','canonical.png'):
            Image.new('RGBA',(8,8),(34,34,34,255)).save(self.root/name)
        self.write('model.obj',b'synthetic model');self.write('body.dds',b'synthetic DDS identity')
        self.write('model-check.py',b'print("synthetic test")');self.write('model.log',b'synthetic success log')
        (self.root/'responses').mkdir()
        pairs=[('new_document',{}),('place_image',{'path':str(self.root/'saved.png')}),
               ('save_document',{'path':str(self.root/'native.cmps')}),('export_image',{'path':str(self.root/'saved.png')}),
               ('open_document',{'path':str(self.root/'copy.cmps')}),('export_image',{'path':str(self.root/'reopened.png')})]
        self.calls=[]
        for i,(name,args) in enumerate(pairs):
            path=f'responses/{i}.json';self.json(path,{'content':[{'type':'text','text':'synthetic success'}],'isError':False})
            self.calls.append({'name':name,'arguments':args,'state':'completed','server_is_error':False,'response_path':path})
        self.json('session.json',{'state':'completed','calls':self.calls})
        self.json('tools.json',{'tools':[{'name':name} for name,_ in pairs]})
        self.json('lifecycle.json',{'baseline':['user-doc'],'owned':['own-doc'],'events':[{'state':'completed'}]})
        receipt={'executable':'synthetic-blender','version':'synthetic','argv':['--background','--python-exit-code','1','--python',str(self.root/'model-check.py')],
                 'script':self.s('model-check.py'),'run_log':self.s('model.log'),'exit_code':0,
                 'model_sha256':self.s('model.obj')['sha256'],'bound_runtime_dds':{'c':self.s('body.dds')['sha256']},
                 'geometry_uv_before_sha256':'a'*64,'geometry_uv_after_sha256':'a'*64}
        self.json('blender.json',receipt)
        self.data={'model':self.s('model.obj'),'runtime_textures':[{'id':'c','role':'color','state':'modified','dds':self.s('body.dds'),'canonical':self.s('canonical.png')}],
            'production_tools':{'schema_version':1,'editor':{'sessions':[collect_session(self.root)],'projects':[{
                'project':self.s('native.cmps'),'reopened_copy':self.s('copy.cmps'),'saved_export':self.s('saved.png'),'reopened_export':self.s('reopened.png'),
                'outputs':[{'runtime_texture_id':'c','canonical':self.s('canonical.png')}]}]},
                'blender':{'status':'checked','receipt':self.s('blender.json')}}}
    def write(self,name,value):
        (self.root/name).write_bytes(value)
    def json(self,name,data):
        (self.root/name).write_text(json.dumps(data),encoding='utf-8')
    def s(self,name):return spec(self.root/name)
    def refresh(self):self.data['production_tools']['editor']['sessions']=[collect_session(self.root)]
    def audit(self):return audit_tools(self.root,self.data)
    def test_complete_evidence_graph(self):
        self.assertEqual(self.audit()['blender']['bound_runtime_count'],1)
    def test_missing_tools_not_production_complete(self):
        del self.data['production_tools']
        with self.assertRaisesRegex(ValueError,'production_tools'):self.audit()
    def test_uncertain_editor_session_rejected(self):
        self.json('session.json',{'state':'uncertain','calls':self.calls});self.refresh()
        with self.assertRaisesRegex(ValueError,'complete cleanly'):self.audit()
    def test_actual_tool_error_rejected(self):
        self.json('responses/1.json',{'isError':True,'content':[]});self.refresh()
        with self.assertRaisesRegex(ValueError,'Original editor response'):self.audit()
    def test_missing_raw_response_rejected(self):
        self.data['production_tools']['editor']['sessions'][0]['responses'].pop()
        with self.assertRaisesRegex(ValueError,'frozen original'):self.audit()
    def test_schema_only_not_editing(self):
        self.calls[1]['name']='new_document';self.json('session.json',{'state':'completed','calls':self.calls});self.refresh()
        with self.assertRaisesRegex(ValueError,'not real layer work'):self.audit()
    def test_cannot_own_user_document(self):
        self.json('lifecycle.json',{'baseline':['user'],'owned':['user'],'events':[{'state':'completed'}]});self.refresh()
        with self.assertRaisesRegex(ValueError,'Baseline'):self.audit()
    def test_cleanup_uncertainty_rejected(self):
        self.json('lifecycle.json',{'owned':['own'],'events':[{'state':'retained','reason':'uncertain_call'}]});self.refresh()
        with self.assertRaisesRegex(ValueError,'unresolved failure'):self.audit()
    def test_same_file_is_not_reopen_export(self):
        self.data['production_tools']['editor']['projects'][0]['reopened_export']=self.s('saved.png')
        with self.assertRaisesRegex(ValueError,'distinct'):self.audit()
    def test_reopen_pixel_change_rejected(self):
        Image.new('RGBA',(8,8),(35,34,34,255)).save(self.root/'reopened.png')
        self.data['production_tools']['editor']['projects'][0]['reopened_export']=self.s('reopened.png')
        with self.assertRaisesRegex(ValueError,'pixels differ'):self.audit()
    def test_export_cannot_precede_copy_reopen(self):
        self.calls[4],self.calls[5]=self.calls[5],self.calls[4]
        self.json('session.json',{'state':'completed','calls':self.calls});self.refresh()
        with self.assertRaisesRegex(ValueError,'order is inconsistent'):self.audit()
    def test_stale_final_color_rejected(self):
        self.write('stale.png',(self.root/'canonical.png').read_bytes())
        Image.new('RGBA',(8,8),(36,34,34,255)).save(self.root/'canonical.png')
        self.data['runtime_textures'][0]['canonical']=self.s('canonical.png')
        self.data['production_tools']['editor']['projects'][0]['outputs'][0]['canonical']=self.s('stale.png')
        with self.assertRaisesRegex(ValueError,'stale runtime'):self.audit()
    def test_successful_postprocess_bound_to_input_output(self):
        Image.new('RGBA',(4,8),(34,34,34,255)).save(self.root/'canonical.png')
        self.data['runtime_textures'][0]['canonical']=self.s('canonical.png')
        output=self.data['production_tools']['editor']['projects'][0]['outputs'][0]
        output.update(canonical=self.s('canonical.png'),postprocess={'script':self.s('model-check.py'),'run_log':self.s('model.log'),
            'exit_code':0,'input_sha256':self.s('saved.png')['sha256'],'output_sha256':self.s('canonical.png')['sha256'],'operation':'synthetic grid transform'})
        self.audit()
        output['postprocess']['input_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'actual input/output'):self.audit()
    def test_wrong_blender_model_rejected(self):
        p=json.loads((self.root/'blender.json').read_text());p['model_sha256']='0'*64;self.json('blender.json',p)
        self.data['production_tools']['blender']['receipt']=self.s('blender.json')
        with self.assertRaisesRegex(ValueError,'different model'):self.audit()
    def test_missing_final_binding_rejected(self):
        p=json.loads((self.root/'blender.json').read_text());p['bound_runtime_dds']={};self.json('blender.json',p)
        self.data['production_tools']['blender']['receipt']=self.s('blender.json')
        with self.assertRaisesRegex(ValueError,'every current final DDS'):self.audit()
    def test_real_unavailability_is_reported_not_checked(self):
        self.json('missing.json',{'usable':False,'attempts':[{'entry':'configured binary','outcome':'not_found'}]})
        self.data['production_tools']['blender']={'status':'unavailable','reason':'synthetic missing binary','diagnostic':self.s('missing.json')}
        self.assertEqual(self.audit()['blender']['model_tool_validation'],'not_run')


class ToolInvocationTests(unittest.TestCase):
    def test_delivery_cli_requires_tools_after_technical_checks(self):
        from test_candidate import Fixture
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'fixture';fixture=Fixture(root);fixture.final()
            result=subprocess.run([sys.executable,'-B','-X','utf8',str(ROOT/'scripts/delivery_validate.py'),
                '--manifest',str(root/'vehicle.json'),'--zip',str(root/'absent.zip')],capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Production delivery requires production_tools',result.stderr)

    def args(self,**overrides):
        value=argparse.Namespace(calls=Path('calls.json'),out=Path('out'),timeout=15.,lock_timeout=5.,exe=None,keep_open=False)
        for k,v in overrides.items():setattr(value,k,v)
        return value
    def test_child_has_explicit_utf8(self):
        command=build_command(self.args());self.assertEqual(command[1:4],['-B','-X','utf8'])
    def test_nonfinite_timeout_rejected(self):
        for field in ('timeout','lock_timeout'):
            with self.assertRaises(ValueError):build_command(self.args(**{field:float('nan')}))
    def test_schema_listing_and_explicit_executable(self):
        command=build_command(self.args(calls=None,exe=Path('actual.exe')))
        self.assertNotIn('--calls',command);self.assertIn('actual.exe',command)
    def test_preview_default_is_one_view(self):self.assertEqual(preview_views(),['iso'])
    def test_seven_views_need_current_authorization(self):
        with self.assertRaisesRegex(ValueError,'authorization'):preview_views(['iso','opposite','top','left','right','rear','front'])
    def test_seven_view_authorization_must_match(self):
        views=['iso','opposite','top','left','right','rear','front']
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'authorization.json'
            path.write_text(json.dumps({'user_request':'synthetic explicit request','request_reference':'synthetic test','authorized_views':views}))
            self.assertEqual(preview_views(views,path),views)
            with self.assertRaisesRegex(ValueError,'view list'):preview_views(views[::-1],path)

    def test_render_parser_preserves_source_face_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'model.obj'
            path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 1 1\nf 1 2 3\n')
            model=load_obj(path)
            self.assertEqual(model['source_face_ids'].tolist(),[1])
            self.assertEqual(model['skipped_source_face_ids'].tolist(),[0])
            self.assertEqual(int(model['source_triangle_count']),2)

    def test_obj_cache_uses_bytes_not_just_mtime(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'model.obj';cache=Path(temp)/'cache.npz'
            source='v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
            path.write_text(source);before=path.stat();first=load_obj(path,cache)
            path.write_text(source.replace('v 1 0 0','v 2 0 0'));os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
            second=load_obj(path,cache)
            self.assertNotEqual(str(first['source_sha256']),str(second['source_sha256']))
            self.assertEqual(float(second['positions'][0,1,0]),2.)

    def test_nonfinite_obj_fails_instead_of_silent_omission(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'model.obj';path.write_text('v 0 0 0\nv 1 0 0\nv 0 nan 0\nf 1 2 3\n')
            with self.assertRaisesRegex(ValueError,'non-finite'):load_obj(path)


if __name__=='__main__':unittest.main()
