import {zipBlob} from './zip.js';

export function setupSkinImport({confirmDiscard,hasEdits,loadScene,serial,message,error}){
  const panel=document.getElementById('skinImport');
  panel.innerHTML=`<h2>打开现成涂装</h2><div class="button-row"><button id="openSkinZip" disabled>打开涂装 ZIP</button><button id="openSkinFolder" disabled>打开涂装文件夹</button></div><input id="skinZipFile" type="file" accept=".zip" hidden><input id="skinFolderFiles" type="file" webkitdirectory multiple hidden><p id="importHelp" class="hint">正在检查本地导入工具…</p><p id="importStatus" class="hint" role="status"></p><div id="importChoices" hidden><label class="field-wide">包里的哪套涂装<select id="importConfig"></select></label><label class="field-wide">确认车型<select id="importVehicle"></select></label><button id="continueImport" class="full">按这套车型继续</button></div><button id="loadImported" class="full" hidden>打开准备好的涂装</button>`;
  const $=id=>document.getElementById(id);let capabilities=null,jobId=null,startingSerial=0,readyURL=null,readyScene=null,configs=[],pollTimer=null;
  const showError=err=>{error(err);$('importStatus').textContent=err.message||String(err);};
  function choices(job){configs=job.configs;$('importChoices').hidden=false;$('importConfig').replaceChildren(...configs.map(row=>{const o=document.createElement('option');o.value=row.blk;o.textContent=row.blk;return o;}));updateVehicles();}
  function updateVehicles(){const config=configs.find(row=>row.blk===$('importConfig').value);$('importVehicle').replaceChildren(...(config?.candidates||[]).map(row=>{const o=document.createElement('option');o.value=row.name;o.textContent=row.name==='ztz_99a'?'99A 主战坦克':row.name;o.title=row.reason.join('；');return o;}));$('continueImport').disabled=!config?.candidates?.length;}
  async function loadReady(){if(!readyURL)return;if(!confirmDiscard())return;await loadScene(readyURL,readyScene);$('loadImported').hidden=true;message('已打开导入涂装；旧贴图中的装饰是合并底图，新增装饰可独立编辑');}
  async function poll(){
    if(!jobId)return;
    try{const response=await fetch('/api/imports/'+jobId);const job=await response.json();if(!response.ok)throw new Error(job.error||'无法读取导入进度');$('importStatus').textContent=job.message;
      if(job.state==='working'){pollTimer=setTimeout(poll,1000);return;}
      $('openSkinZip').disabled=$('openSkinFolder').disabled=false;
      if(job.state==='needs_selection'){choices(job);return;}
      if(job.state==='error')throw new Error(job.message);
      if(job.state==='ready'){readyURL=job.scene_url;readyScene=job.scene;const warnings=job.warnings?.length?' · '+job.warnings.join('；'):'';$('importStatus').textContent=`已识别 ${job.vehicle==='ztz_99a'?'99A 主战坦克':job.vehicle}，模型与涂装已准备好${warnings}`;if(serial()===startingSerial&&!hasEdits())await loadReady();else{$('loadImported').hidden=false;message('导入完成；你现在的编辑已保留，可先保存再打开新涂装');}}
    }catch(err){$('openSkinZip').disabled=$('openSkinFolder').disabled=false;showError(err);}
  }
  async function upload(blob){if(!capabilities?.skin_import)throw new Error('本地提取工具尚未就绪，请查看导入说明');if(blob.size>capabilities.max_upload_bytes)throw new Error('压缩包超过 512 MiB，请只导入一套游戏用涂装');startingSerial=serial();$('openSkinZip').disabled=$('openSkinFolder').disabled=true;$('importChoices').hidden=true;$('loadImported').hidden=true;$('importStatus').textContent='正在把文件交给本机工具，不会上传到外网…';const response=await fetch('/api/import-skin',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Workbench-Token':capabilities.token},body:blob});const data=await response.json();if(!response.ok)throw new Error(data.error||'导入请求失败');jobId=data.id;poll();}
  $('openSkinZip').addEventListener('click',()=>$('skinZipFile').click());
  $('openSkinFolder').addEventListener('click',()=>$('skinFolderFiles').click());
  $('skinZipFile').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{await upload(file);}catch(err){showError(err);$('openSkinZip').disabled=$('openSkinFolder').disabled=false;}finally{event.target.value='';}});
  $('skinFolderFiles').addEventListener('change',async event=>{try{const files=[...event.target.files].filter(file=>/\.(blk|dds|tga|png|grp)$/i.test(file.name));if(!files.length)throw new Error('这个文件夹里没有 .blk 和颜色贴图');if(files.length>64||files.reduce((sum,f)=>sum+f.size,0)>256*1024*1024)throw new Error('文件夹较大，请压成 ZIP 后导入，或只选其中一套涂装');$('importStatus').textContent='正在整理选中文件夹…';const blob=await zipBlob(files.map(file=>({name:file.webkitRelativePath||file.name,blob:file})));await upload(blob);}catch(err){showError(err);}finally{event.target.value='';}});
  $('importConfig').addEventListener('change',updateVehicles);
  $('continueImport').addEventListener('click',async()=>{try{$('importChoices').hidden=true;const response=await fetch('/api/imports/'+jobId+'/choose',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':capabilities.token},body:JSON.stringify({blk:$('importConfig').value,vehicle:$('importVehicle').value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'车型选择失败');poll();}catch(err){showError(err);$('importChoices').hidden=false;}});
  $('loadImported').addEventListener('click',()=>loadReady().catch(showError));
  const availability=location.hostname.endsWith('.github.io')?Promise.reject(new Error('在线 3D 预览已可用。自动读取战雷目录与涂装 ZIP，请启动本地提取工具；也可直接打开已准备的 GLB 模型')):fetch('/api/capabilities');
  availability.then(async response=>{if(!response.ok)throw new Error('在线 3D 预览已可用。自动读取战雷目录与涂装 ZIP，请启动本地提取工具；也可直接打开已准备的 GLB 模型');capabilities=await response.json();if(!capabilities.skin_import)throw new Error('本地提取工具或战雷目录尚未就绪；请按使用说明运行 setup，并检查 --game-dir');$('openSkinZip').disabled=$('openSkinFolder').disabled=false;$('importHelp').textContent='读取配置 → 自动识别车型 → 从战雷文件夹提取模型。原压缩包与原文件夹保留。';}).catch(err=>{$('importHelp').textContent=err.message;const a=document.createElement('a');a.href='https://github.com/IcyRyna/war-thunder-skin-skills/blob/main/docs/web-preview.md';a.textContent='如何打开自己的涂装与模型';a.className='hint';panel.append(a);});
  window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
}
