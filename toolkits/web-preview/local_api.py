"""Loopback-only import jobs. Uploaded files are never treated as executable code."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import uuid
from urllib.parse import urlsplit


class LocalAPI:
    def __init__(self,root,work_dir=None,game_dir=None,extractor=None,runtime=None):
        self.root=Path(root);self.work_dir=Path(work_dir).resolve() if work_dir else None
        self.game_dir=str(game_dir) if game_dir else None;self.extractor=str(extractor) if extractor else None;self.runtime=runtime
        self.token=secrets.token_urlsafe(32);self.jobs={};self.lock=threading.Lock();self.processes={};self.closing=False

    def json(self,handler,data,status=200):
        payload=json.dumps(data,ensure_ascii=False).encode();handler.send_response(status);handler.send_header('Content-Type','application/json; charset=utf-8');handler.send_header('Content-Length',str(len(payload)));handler.send_header('Cache-Control','no-store');handler.send_header('X-Content-Type-Options','nosniff');handler.end_headers();handler.wfile.write(payload)

    def get(self,handler,route):
        if route=='/api/capabilities':
            self.json(handler,{'skin_import':bool(self.work_dir and self.game_dir and self.extractor and self.runtime),'token':self.token if self.work_dir else None,
                               'formats':['zip','folder'],'game_folder_found':bool(self.game_dir),'max_upload_bytes':512*1024*1024});return True
        match=re.fullmatch(r'/api/imports/([0-9a-f]{32})',route)
        if match:
            with self.lock:job=dict(self.jobs.get(match[1],{}))
            if not job:self.json(handler,{'error':'没有这个导入任务'},404);return True
            progress=Path(job['folder'])/'progress.json'
            if job['state']=='working' and progress.is_file():
                try:job.update(json.loads(progress.read_text(encoding='utf-8')))
                except (OSError,ValueError):pass
            job.pop('folder',None);job.pop('discovery',None);self.json(handler,job);return True
        match=re.fullmatch(r'/imports/([0-9a-f]{32})/([^/]+)',route)
        if match:
            with self.lock:job=self.jobs.get(match[1],{})
            scene=job.get('scene')
            if not scene or job.get('state')!='ready':handler.send_error(404);return True
            scene=Path(scene);allowed={'scene.json','model.glb'}
            try:
                materials=json.loads((scene/'scene.json').read_text(encoding='utf-8'))['materials']
                allowed.update(r['native_file'] for r in materials if re.fullmatch(r'native-color-\d+\.png',r.get('native_file','')))
                for row in materials:
                    for channel in ('orm','normal'):
                        filename=row.get('reflection',{}).get(channel,{}).get('file','')
                        if re.fullmatch(r'native-(?:orm|normal)-\d+\.png',filename):allowed.add(filename)
            except (OSError,ValueError):handler.send_error(404);return True
            leaf=match[2];path=scene/leaf
            if leaf not in allowed or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(scene):handler.send_error(404);return True
            handler.send_response(200);handler.send_header('Content-Type',{'model.glb':'model/gltf-binary','scene.json':'application/json'}.get(leaf,'image/png'));handler.send_header('Content-Length',str(path.stat().st_size));handler.send_header('Cache-Control','no-store');handler.end_headers()
            with path.open('rb') as stream:
                import shutil
                shutil.copyfileobj(stream,handler.wfile)
            return True
        return False

    def authorized(self,handler):
        host=handler.headers.get('Host','');origin=handler.headers.get('Origin')
        if host.split(':')[0] not in ('127.0.0.1','localhost'):return False
        if origin and (urlsplit(origin).scheme!='http' or urlsplit(origin).netloc!=host):return False
        return secrets.compare_digest(handler.headers.get('X-Workbench-Token',''),self.token)

    def post(self,handler,route):
        if not self.authorized(handler):self.json(handler,{'error':'本地请求验证失败'},403);return
        if not self.work_dir or not self.game_dir or not self.extractor or not self.runtime:self.json(handler,{'error':'自动导入需要配置本地工作目录、战雷目录和资源解码工具'},409);return
        if route=='/api/import-skin':
            try:
                length=int(handler.headers.get('Content-Length','0'))
                if not 0<length<=512*1024*1024:raise ValueError('压缩包大小需要在 1 字节至 512 MiB 之间')
                with self.lock:
                    if sum(j['state']=='working' for j in self.jobs.values())>=1:raise ValueError('请等当前涂装导入完成后再导入下一套')
                identifier=uuid.uuid4().hex;folder=self.work_dir/identifier;folder.mkdir(parents=True,exist_ok=False)
                target=folder/'input.zip';remaining=length;handler.connection.settimeout(60)
                with target.open('xb') as stream:
                    while remaining:
                        data=handler.rfile.read(min(1048576,remaining))
                        if not data:raise ValueError('上传未完成，原文件保留，请重试')
                        stream.write(data);remaining-=len(data)
                job={'id':identifier,'folder':str(folder),'state':'working','message':'已收到文件，开始自动识别车型'}
                with self.lock:self.jobs[identifier]=job
                threading.Thread(target=self.run,args=(identifier,None),daemon=True).start();self.json(handler,{'id':identifier},202)
            except (OSError,ValueError) as error:self.json(handler,{'error':str(error)},400)
            return
        match=re.fullmatch(r'/api/imports/([0-9a-f]{32})/choose',route)
        if match:
            try:
                length=int(handler.headers.get('Content-Length','0'))
                if not 0<length<16384:raise ValueError('选择内容无效')
                selection=json.loads(handler.rfile.read(length));identifier=match[1]
                with self.lock:
                    job=self.jobs.get(identifier)
                    if not job or job['state']!='needs_selection':raise ValueError('当前任务不需要选择车型')
                    if any(other['state']=='working' for key,other in self.jobs.items() if key!=identifier):raise ValueError('请等另一套涂装导入完成后再继续')
                    data=json.loads(Path(job['discovery']).read_text(encoding='utf-8'));config=next((r for r in data['configs'] if r['blk']==selection.get('blk')),None)
                    if not config or not any(r['name']==selection.get('vehicle') for r in config['candidates']):raise ValueError('请选择包内配置和实际游戏模型候选')
                    job.update(state='working',message='按所选车型继续提取')
                threading.Thread(target=self.run,args=(identifier,selection),daemon=True).start();self.json(handler,{'id':identifier},202)
            except (OSError,ValueError,TypeError) as error:self.json(handler,{'error':str(error)},400)
            return
        self.json(handler,{'error':'没有这个接口'},404)

    def run(self,identifier,selection):
        with self.lock:job=self.jobs[identifier];folder=Path(job['folder'])
        if selection:
            command=[self.runtime,'-B',str(self.root/'skin_import.py'),'build','--discovery',job['discovery'],'--out',str(folder/'selected-result'),
                     '--vehicle',selection['vehicle'],'--blk',selection['blk'],'--progress',str(folder/'progress.json')]
        else:
            command=[self.runtime,'-B',str(self.root/'skin_import.py'),'import','--input',str(folder/'input.zip'),'--out',str(folder/'work'),
                     '--game-dir',self.game_dir,'--extractor',self.extractor,'--progress',str(folder/'progress.json')]
        try:
            with self.lock:
                if self.closing:raise RuntimeError('本地服务正在关闭')
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                                         env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.processes[identifier]=process
            try:output,_=process.communicate(timeout=900)
            except subprocess.TimeoutExpired:process.kill();output,_=process.communicate();raise RuntimeError('导入超过 15 分钟，已停止本任务；文件与日志保留')
            (folder/'worker.log').write_text(output,encoding='utf-8')
            result=json.loads(output.strip().splitlines()[-1]) if output.strip() else {'ok':False,'error':'导入工具没有返回结果'}
            with self.lock:
                if result.get('needs_selection'):job.update(state='needs_selection',message='配置或子型号不唯一，请确认',configs=result['configs'],discovery=result['discovery'])
                elif result.get('ok'):
                    job.update(state='ready',message='模型和涂装已准备好',scene=result['scene'],vehicle=result['vehicle'],warnings=result.get('warnings',[]),scene_url=f'/imports/{identifier}/scene.json')
                else:job.update(state='error',message=result.get('error','导入失败；请查看本地日志'))
        except Exception as error:
            with self.lock:job.update(state='error',message=str(error))
        finally:
            with self.lock:self.processes.pop(identifier,None)
            (folder/'job-summary.json').write_text(json.dumps({k:v for k,v in job.items() if k not in ('folder',)},ensure_ascii=False,indent=2),encoding='utf-8')

    def close(self):
        with self.lock:self.closing=True;processes=list(self.processes.values())
        for process in processes:
            if process.poll() is None:process.terminate()
