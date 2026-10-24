import {ORIGINS,TYPES,FONTS,canvasSize,cloneLayers,serializeLayers,renderDocument,validateLayer,hitLayer,layerGeometry,wrapUV,pointInPolygon} from './editor-core.js';
import {downloadZip} from './zip.js';

export function createEditor(bridge){
  const panel=document.getElementById('creative');
  panel.innerHTML=`<h2>动手改涂装</h2>
  <div class="tool-grid"><button data-tool="select">选图案</button><button id="addDecal">加装饰图</button><button id="addText">加文字</button><button id="addShape">加色块</button><button data-tool="rect">框选改色</button><button data-tool="polygon">圈选改色</button><button data-tool="brush">画笔修补</button><button data-tool="erase">擦图层</button></div>
  <input id="decalFile" type="file" accept="image/png" hidden>
  <p id="toolHint" class="hint">新增图案可单独选中；已经合进底图的图案无法自动拆成图层。</p>
  <div class="canvas-choice"><label for="canvasResolution">这张贴图的画布</label><select id="canvasResolution" disabled><option value="0">跟随原图</option><option value="512">512 长边</option><option value="1024">1K 长边</option><option value="2048">2K 长边</option><option value="4096">4K 长边</option></select></div>
  <p id="editResolution" class="hint">预览清晰度与导出画布分开设置。</p>
  <div class="base-row">底图（已经合并）<small>不能当作独立装饰选中</small></div>
  <div id="layers" aria-label="装饰与改色图层"></div>
  <div id="layerSettings" hidden>
    <label class="field-wide">图层名称<input id="layerName" maxlength="120"></label>
    <label class="field-wide">这层从哪来<select id="layerOrigin"><option value="manual">手动添加</option><option value="ai">AI 添加</option><option value="imported">来源未注明</option></select></label>
    <div id="placementFields" class="edit-fields"><label>左右位置 %<input id="decalX" type="number" min="-100" max="200" step="0.1"></label><label>上下位置 %<input id="decalY" type="number" min="-100" max="200" step="0.1"></label><label id="widthField">宽度 %<input id="decalWidth" type="number" min="0.1" max="200" step="0.1"></label><label>旋转 °<input id="decalRotation" type="number" min="-360" max="360" step="1"></label><label id="heightField">高度 %<input id="shapeHeight" type="number" min="0.1" max="200" step="0.1"></label></div>
    <div id="textFields" hidden><label class="field-wide">文字内容<textarea id="textValue" rows="2" maxlength="500"></textarea></label><div class="edit-fields"><label>字号 px<input id="textSize" type="number" min="1" max="4096" step="1"></label><label>字体<select id="textFont"><option value="Microsoft YaHei">微软雅黑</option><option value="Arial">英文无衬线</option><option value="sans-serif">系统无衬线</option><option value="serif">衬线字体</option><option value="monospace">等宽字体</option></select></label></div><label class="check"><input id="textBold" type="checkbox">加粗文字</label></div>
    <div id="colorFields" class="edit-fields"><label>颜色<input id="tintColor" type="color" value="#d6ad41"></label><label id="blendField">怎么混色<select id="tintBlend"><option value="color">保留明暗</option><option value="source-over">直接盖色</option><option value="multiply">加深底色</option></select></label></div>
    <label class="opacity-label">不透明度<input id="layerOpacity" type="range" min="0" max="1" step="0.01"><output id="opacityValue">100%</output></label>
    <div class="button-row"><button id="positionOnModel">到模型上点位置</button><button id="flipX">左右翻转</button><button id="flipY">上下翻转</button></div>
    <p id="layerPart" class="hint"></p><div class="button-row"><button id="linkPart">关联选中部件</button><button id="locatePart">看关联部件</button></div><label class="check"><input id="clipToPart" type="checkbox">只画在关联部件的贴图区</label>
    <div class="button-row"><button id="duplicateLayer">复制一层</button><button id="layerUp">往上移</button><button id="layerDown">往下移</button><button id="removeLayer">删除这层</button></div>
  </div>
  <div id="brushSettings" hidden><label class="field-wide">笔刷粗细 px<input id="brushSize" type="number" min="1" max="1024" value="24"></label><p class="hint">在平面贴图上画；橡皮只擦当前图层，不破坏底图。</p></div>
  <button id="finishPolygon" class="full" hidden>完成这个选区</button><button id="tintPart" class="full">给选中部件改色</button>
  <div class="button-row"><button id="undo" disabled>撤销</button><button id="redo" disabled>重做</button><button id="cancelTool">退出绘制</button></div>
  <div class="edit-exports"><button id="exportColor" disabled>导出这张贴图</button><button id="exportAll" disabled>导出改过的贴图 ZIP</button></div>
  <div class="edit-exports"><button id="saveProject" class="primary" disabled>保存可编辑工程</button><button id="openProject">打开 AI／人工工程</button></div>
  <input id="projectFile" type="file" accept=".json" hidden><p class="hint">只编辑颜色；反射、法线和 AO 暂未接入。</p>`;
  const $=id=>document.getElementById(id),uv=$('uv'),overlayContext=uv.getContext('2d'),documents=new Map(),queued=new Set();
  let material=null,mode='select',polygon=[],draft=null,drag=null,dirty=false,pending=false,quality=1024,loadGeneration=0,revision=0;
  const limits={layers:64,history:32,maxDimension:8192,maxProjectBytes:128*1024*1024};
  const doc=()=>documents.get(material),selected=()=>doc()?.layers.find(row=>row.id===doc().selected);
  const safeName=name=>name.replace(/[^\p{L}\p{N}_.-]+/gu,'_');
  function save(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function hint(text){$('toolHint').textContent=text;}
  function report(error){bridge.error(error);}
  function baseLayer(type,name){return{id:crypto.randomUUID(),type,name,origin:'manual',opacity:1,visible:true,locked:false,part_refs:bridge.selectedParts?.()||[]};}
  async function imageFromData(src){
    if(typeof src!=='string'||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(src))throw new Error('工程中的图片必须是内嵌 PNG');
    const image=new Image();image.src=src;await image.decode();
    if(!image.width||image.width>limits.maxDimension||image.height>limits.maxDimension)throw new Error('图案或底图最大边长为 8192');
    return image;
  }
  function attachAlpha(row){if(row.type!=='decal')return;const c=document.createElement('canvas'),s=Math.min(1,512/Math.max(row.image.width,row.image.height));c.width=Math.max(1,Math.round(row.image.width*s));c.height=Math.max(1,Math.round(row.image.height*s));const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(row.image,0,0,c.width,c.height);row.alphaImage={data:ctx.getImageData(0,0,c.width,c.height).data,width:c.width,height:c.height};}
  function sampleAlpha(row,x,y){const a=row.alphaImage;if(!a)return 255;return a.data[(Math.max(0,Math.min(a.height-1,Math.floor(y*a.height)))*a.width+Math.max(0,Math.min(a.width-1,Math.floor(x*a.width))))*4+3];}
  function makeDocument(base,m,longEdge=0){
    const sourceBase=document.createElement('canvas');sourceBase.width=base.width;sourceBase.height=base.height;sourceBase.getContext('2d').drawImage(base.image,0,0);
    return{sourceBase,materialName:m.name,longEdge,...canvasSize(base.width,base.height,longEdge),layers:[],selected:null,history:[{layers:[],longEdge}],cursor:0,identity:bridge.identity(m),preview:document.createElement('canvas'),scratch:document.createElement('canvas')};
  }
  async function ensure(){
    if(!material)throw new Error('先打开模型，再选一张要修改的贴图');
    if(!documents.has(material)){const current=material,generation=loadGeneration;const base=await bridge.ensureNative(current);if(material!==current||generation!==loadGeneration)throw new Error('模型或贴图已经切换，请重试');if(base.width>8192||base.height>8192)throw new Error('底图超过 8192，不能偷偷降清晰度');documents.set(current,makeDocument(base,current));}
    return doc();
  }
  function clipPolygons(row,m=material?.name){return row.clipParts?.length?bridge.resolveClip(row.clipParts,m):[];}
  function containsClip(row,point){return !row.clipParts?.length||clipPolygons(row).some(p=>pointInPolygon(point,p));}
  function compose(m=material){if(!m||!documents.has(m))return;queued.add(m);if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;for(const target of queued){const d=documents.get(target);if(!d)continue;const size=canvasSize(d.width,d.height,Math.min(quality,Math.max(d.width,d.height)));if(d.preview.width!==size.width)d.preview.width=size.width;if(d.preview.height!==size.height)d.preview.height=size.height;renderDocument(d,d.preview,d.scratch,bridge.resolveClip);bridge.setImage(target,{image:d.preview,width:size.width,height:size.height,userNative:true,editorCanvas:[d.width,d.height]});}queued.clear();updateControls();});}
  function snapshot(d){return{layers:cloneLayers(d.layers),longEdge:d.longEdge};}
  function commit(row=selected()){const d=doc();if(!d)return;revision++;if(row)row.manually_adjusted=true;d.history=d.history.slice(0,d.cursor+1);d.history.push(snapshot(d));if(d.history.length>limits.history)d.history.shift();d.cursor=d.history.length-1;dirty=true;renderLayers();compose();}
  function append(row){const d=doc();if(d.layers.length>=limits.layers)throw new Error('这张贴图最多放 64 个图层');validateLayer(row);d.layers.push(row);d.selected=row.id;commit();}
  function setInput(id,value){if(document.activeElement!==$(id))$(id).value=value;}
  function updateControls(){
    const d=doc(),row=selected(),editable=!!row&&!row.locked;
    for(const button of panel.querySelectorAll('[data-tool]')){button.disabled=!material;button.classList.toggle('active',button.dataset.tool===mode);button.setAttribute('aria-pressed',String(button.dataset.tool===mode));}
    for(const id of ['addDecal','addText','addShape','tintPart'])$(id).disabled=!material;
    $('layerSettings').hidden=!row;$('canvasResolution').disabled=!material;
    if(d){setInput('canvasResolution',d.longEdge);$('editResolution').textContent=`原图 ${d.sourceBase.width}×${d.sourceBase.height} → 画布 ${d.width}×${d.height} · ${d.layers.length} 层${Math.max(d.sourceBase.width,d.sourceBase.height)<Math.max(d.width,d.height)?'；放大底图不增加原始细节':''}`;}
    else $('editResolution').textContent='先选画布分辨率；只在编辑时读取原尺寸底图。';
    const positioned=row&&['decal','text','shape'].includes(row.type);
    $('placementFields').hidden=!positioned;$('widthField').hidden=row?.type==='text';$('heightField').hidden=row?.type!=='shape';$('textFields').hidden=row?.type!=='text';
    $('colorFields').hidden=!row||row.type==='decal';$('blendField').hidden=row?.type!=='tint';$('brushSettings').hidden=!['brush','erase'].includes(mode);$('finishPolygon').hidden=mode!=='polygon';
    for(const id of ['positionOnModel','flipX','flipY'])$(id).disabled=!editable||!positioned;
    $('removeLayer').disabled=!editable;$('duplicateLayer').disabled=!row;$('layerUp').disabled=!editable||d.layers.at(-1)===row;$('layerDown').disabled=!editable||d.layers[0]===row;
    $('linkPart').disabled=!editable||!bridge.selectedParts?.().length;$('locatePart').disabled=!row?.part_refs?.length;$('clipToPart').disabled=!editable||!row?.part_refs?.length;
    if(row){setInput('layerName',row.name);setInput('layerOrigin',row.origin||'imported');$('layerName').disabled=!editable;$('layerOrigin').disabled=!editable;
      setInput('decalX',(row.x*100).toFixed(2));setInput('decalY',(row.y*100).toFixed(2));setInput('decalWidth',(row.width*100).toFixed(2));setInput('shapeHeight',(row.height*100).toFixed(2));setInput('decalRotation',row.rotation);
      setInput('textValue',row.text||'');setInput('textSize',Math.round((row.fontSize||.04)*d.width));setInput('textFont',row.font||'Microsoft YaHei');$('textBold').checked=!!row.bold;
      setInput('tintColor',row.color||'#d6ad41');setInput('tintBlend',row.blend||'color');setInput('layerOpacity',row.opacity);$('opacityValue').textContent=Math.round(row.opacity*100)+'%';$('layerOpacity').disabled=!editable;
      $('clipToPart').checked=!!row.clipParts?.length;$('layerPart').textContent=row.part_refs?.length?'关联部件：'+row.part_refs.map(id=>bridge.partLabel(id)).join('、'):'尚未关联具体部件；可先在左侧选一个。';
      for(const input of $('placementFields').querySelectorAll('input'))input.disabled=!editable;for(const input of $('textFields').querySelectorAll('input,textarea,select'))input.disabled=!editable;for(const input of $('colorFields').querySelectorAll('input,select'))input.disabled=!editable;
    }
    $('undo').disabled=!d||d.cursor===0;$('redo').disabled=!d||d.cursor===d.history.length-1;$('exportColor').disabled=!d;$('exportAll').disabled=!documents.size;$('saveProject').disabled=!material;
    uv.classList.toggle('editing',mode!=='view');
    const count=[...documents.values()].reduce((n,item)=>n+item.layers.filter(l=>l.type==='decal'||l.type==='text'||l.type==='shape').length,0);panel.dataset.decorations=String(count);
  }
  function renderLayers(){
    const container=$('layers');container.replaceChildren();const d=doc();
    if(!d?.layers.length){const p=document.createElement('p');p.className='hint';p.textContent='还没有独立图层。加装饰图，或打开 AI 保留了图层的工程。';container.append(p);}
    for(const row of [...(d?.layers||[])].reverse()){
      const wrapper=document.createElement('div');wrapper.className='layer-row'+(row.id===d.selected?' active':'');wrapper.dataset.layerId=row.id;
      const eye=document.createElement('input');eye.type='checkbox';eye.checked=row.visible!==false;eye.setAttribute('aria-label','显示 '+row.name);eye.addEventListener('change',()=>{row.visible=eye.checked;commit(row);});
      const button=document.createElement('button');button.className='layer-main';button.title=row.name;button.setAttribute('aria-label',row.name);
      if(row.type==='decal'){const image=document.createElement('img');image.src=row.src;image.alt='';button.append(image);}else{const swatch=document.createElement('span');swatch.className='layer-swatch';swatch.style.backgroundColor=row.color||'#ccc';swatch.textContent=row.type==='text'?'字':row.type==='brush'?'笔':'';button.append(swatch);}
      const label=document.createElement('span'),name=document.createElement('strong'),meta=document.createElement('small');name.textContent=row.name;meta.textContent=`${ORIGINS[row.origin||'imported']} · ${TYPES[row.type]}${row.origin==='ai'&&row.manually_adjusted?' · 手动改过':''}`;label.append(name,meta);button.append(label);button.addEventListener('click',()=>{d.selected=row.id;mode='select';renderLayers();bridge.redrawUV();});
      const lock=document.createElement('button');lock.className='lock';lock.textContent=row.locked?'解锁':'锁定';lock.setAttribute('aria-label',(row.locked?'解锁 ':'锁定 ')+row.name);lock.addEventListener('click',()=>{row.locked=!row.locked;commit(row);});wrapper.append(eye,button,lock);container.append(wrapper);
    }updateControls();
  }
  function normalPoint(event){const b=uv.getBoundingClientRect();return[Math.max(0,Math.min(1,(event.clientX-b.left)/b.width)),Math.max(0,Math.min(1,(event.clientY-b.top)/b.height))];}
  function findAt(point){const d=doc();if(!d)return null;return [...d.layers].reverse().find(row=>hitLayer(row,point,d.width,d.height,sampleAlpha,containsClip));}
  function selectAt(point){const row=findAt(point);if(row){doc().selected=row.id;renderLayers();bridge.redrawUV();}else bridge.message('这里没有可单选的独立图层；底图里的图案可能已经合并。');return row;}
  async function setTool(next){try{await ensure();mode=next;polygon=[];draft=null;drag=null;
      if(next==='brush'&&selected()?.type!=='brush')append({...baseLayer('brush','手绘修补'),color:$('tintColor').value,strokes:[]});
      if(next==='erase'&&!selected())throw new Error('先选一个要擦的图层');
      hint(next==='rect'?'在平面贴图上拖一个框，松开后生成改色图层。':next==='polygon'?'在平面贴图上逐点点击，再按“完成这个选区”。':next==='brush'?'在平面贴图上涂画，松开鼠标算一步，支持撤销。':next==='erase'?'只擦选中图层，底图不受影响。':'点击模型或平面贴图选图案；拖动平面贴图可移动它。');updateControls();bridge.redrawUV();
    }catch(error){report(error);}}
  for(const button of panel.querySelectorAll('[data-tool]'))button.addEventListener('click',()=>setTool(button.dataset.tool));
  $('addDecal').addEventListener('click',async()=>{try{await ensure();$('decalFile').click();}catch(error){report(error);}});
  $('decalFile').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;const current=material,generation=loadGeneration;try{if(file.type!=='image/png'||file.size>16*1024*1024)throw new Error('装饰图需要 16 MiB 以内的透明 PNG');const src=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(new Error('无法读取装饰图，请确认文件仍然存在'));r.readAsDataURL(file);});const image=await imageFromData(src);if(current!==material||generation!==loadGeneration)throw new Error('模型或贴图已切换，请重试');const row={...baseLayer('decal',file.name),src,image,x:.5,y:.5,width:.15,rotation:0,flipX:false,flipY:false};attachAlpha(row);append(row);mode='position';hint('在模型上点一下放置，也可以在平面贴图上拖动，或输入百分比精调。');updateControls();}catch(error){report(error);}finally{event.target.value='';}});
  $('addText').addEventListener('click',async()=>{try{await ensure();append({...baseLayer('text','文字标识'),text:'涂装标识',font:'Microsoft YaHei',fontSize:.04,bold:true,color:'#ffffff',x:.5,y:.5,rotation:0});mode='position';updateControls();}catch(error){report(error);}});
  $('addShape').addEventListener('click',async()=>{try{await ensure();append({...baseLayer('shape','颜色条带'),color:'#d6ad41',x:.5,y:.5,width:.25,height:.04,rotation:0});mode='position';updateControls();}catch(error){report(error);}});
  function addTint(points=null,clipParts=[]){append({...baseLayer('tint','区域改色 '+(doc().layers.length+1)),points,color:$('tintColor').value,blend:$('tintBlend').value,clipParts});}
  $('tintPart').addEventListener('click',async()=>{try{await ensure();const ids=bridge.selectedParts?.()||[];if(!ids.length)throw new Error('先在模型或左侧点选一个部件');if(!bridge.resolveClip(ids,material.name).length)throw new Error('选中部件不使用当前贴图，先切换到它对应的贴图');addTint(null,ids);mode='select';}catch(error){report(error);}});
  uv.addEventListener('pointerdown',event=>{if(!doc()||mode==='view')return;const p=normalPoint(event);uv.setPointerCapture(event.pointerId);
    if(mode==='polygon'){polygon.push(p);bridge.redrawUV();return;}
    if(mode==='rect'){drag={start:p};draft=[p,p,p,p];return;}
    if(mode==='select'&&!selectAt(p))return;
    const row=selected();if(!row||row.locked)return;
    if(mode==='brush'&&row.type==='brush'){const stroke={points:[p],width:Number($('brushSize').value)/doc().width,color:$('tintColor').value};row.strokes.push(stroke);drag={stroke};compose();}
    else if(mode==='erase'){const stroke={points:[p],width:Number($('brushSize').value)/doc().width};(row.erasures??=[]).push(stroke);drag={stroke};compose();}
    else if(['decal','text','shape'].includes(row.type))drag={start:p,x:row.x,y:row.y,changed:false};
  });
  uv.addEventListener('pointermove',event=>{if(!drag)return;const p=normalPoint(event);if(drag.stroke){const last=drag.stroke.points.at(-1);if(Math.hypot(p[0]-last[0],p[1]-last[1])>.001&&drag.stroke.points.length<20000){drag.stroke.points.push(p);compose();}}
    else if(mode==='rect'){const [x,y]=drag.start;draft=[[x,y],[p[0],y],p,[x,p[1]]];bridge.redrawUV();}else{const row=selected();row.x=Math.max(-1,Math.min(2,drag.x+p[0]-drag.start[0]));row.y=Math.max(-1,Math.min(2,drag.y+p[1]-drag.start[1]));drag.changed ||= Math.hypot(p[0]-drag.start[0],p[1]-drag.start[1])>1e-5;compose();}});
  uv.addEventListener('pointerup',()=>{if(!drag)return;try{if(mode==='rect'&&Math.abs(draft[2][0]-draft[0][0])*Math.abs(draft[2][1]-draft[0][1])>1e-6)addTint(draft.map(p=>[...p]));else if(mode!=='rect'&&(drag.stroke||drag.changed))commit();}catch(error){report(error);}drag=null;draft=null;bridge.redrawUV();});
  uv.addEventListener('pointercancel',()=>{if(drag){const d=doc();d.layers=cloneLayers(d.history[d.cursor].layers);compose();}drag=null;draft=null;bridge.redrawUV();});
  $('finishPolygon').addEventListener('click',()=>{if(polygon.length<3){bridge.message('至少点三个位置，才能围出选区');return;}try{addTint(polygon.map(p=>[...p]));polygon=[];bridge.redrawUV();}catch(error){report(error);}});
  $('cancelTool').addEventListener('click',()=>{mode='view';polygon=[];draft=null;drag=null;hint('现在可以安心旋转查看；要继续编辑，点选图层或绘制工具。');updateControls();bridge.redrawUV();});
  const numeric=[['decalX','x',.01],['decalY','y',.01],['decalWidth','width',.01],['decalRotation','rotation',1],['shapeHeight','height',.01],['textSize','fontSize',()=>1/doc().width]];
  for(const [id,key,factor] of numeric){$(id).addEventListener('input',()=>{const row=selected();const value=Number($(id).value);if(row&&!row.locked&&Number.isFinite(value)&&$(id).validity.valid){row[key]=value*(typeof factor==='function'?factor():factor);compose();}});$(id).addEventListener('change',()=>{if($(id).validity.valid)commit();else{bridge.message('这个数值超出范围，已恢复之前的设置');document.activeElement?.blur();updateControls();}});}
  for(const [id,key] of [['layerName','name'],['layerOrigin','origin'],['textValue','text'],['textFont','font'],['tintColor','color'],['tintBlend','blend']])$(id).addEventListener('change',()=>{const row=selected();if(row&&!row.locked){const old=row[key];row[key]=$(id).value;try{validateLayer(row);commit();}catch(error){row[key]=old;report(error);updateControls();}}});
  $('textBold').addEventListener('change',()=>{if(selected()&&!selected().locked){selected().bold=$('textBold').checked;commit();}});
  $('layerOpacity').addEventListener('input',()=>{if(selected()&&!selected().locked){selected().opacity=Number($('layerOpacity').value);compose();}});$('layerOpacity').addEventListener('change',()=>commit());
  $('canvasResolution').addEventListener('change',async()=>{try{const d=await ensure();d.longEdge=Number($('canvasResolution').value);Object.assign(d,canvasSize(d.sourceBase.width,d.sourceBase.height,d.longEdge));commit(null);}catch(error){report(error);updateControls();}});
  $('positionOnModel').addEventListener('click',()=>{mode='position';hint('在模型的同一张贴图表面点一下，移动当前图案；拖动模型仍然旋转视角。');updateControls();});
  for(const id of ['flipX','flipY'])$(id).addEventListener('click',()=>{if(selected()&&!selected().locked){selected()[id]=!selected()[id];commit();}});
  $('duplicateLayer').addEventListener('click',()=>{if(!selected())return;try{const row=cloneLayers([selected()])[0];row.id=crypto.randomUUID();row.name+=' 副本';row.locked=false;if(Number.isFinite(row.x))row.x+=.02;append(row);}catch(error){report(error);}});
  $('removeLayer').addEventListener('click',()=>{const d=doc();d.layers=d.layers.filter(row=>row.id!==d.selected);d.selected=d.layers.at(-1)?.id??null;commit(null);});
  for(const [id,delta] of [['layerUp',1],['layerDown',-1]])$(id).addEventListener('click',()=>{const d=doc(),i=d.layers.findIndex(r=>r.id===d.selected),j=i+delta;if(i<0||j<0||j>=d.layers.length)return;[d.layers[i],d.layers[j]]=[d.layers[j],d.layers[i]];commit();});
  $('linkPart').addEventListener('click',()=>{const row=selected();if(!row||row.locked)return;row.part_refs=bridge.selectedParts();if(row.clipParts?.length)row.clipParts=[...row.part_refs];commit();});
  $('locatePart').addEventListener('click',()=>bridge.focusParts(selected()?.part_refs||[]));
  $('clipToPart').addEventListener('change',()=>{const row=selected();if(!row||row.locked)return;row.clipParts=$('clipToPart').checked?[...(row.part_refs||[])]:[];commit();});
  for(const [id,delta] of [['undo',-1],['redo',1]])$(id).addEventListener('click',()=>{const d=doc(),i=d.cursor+delta;if(i<0||i>=d.history.length)return;revision++;d.cursor=i;d.layers=cloneLayers(d.history[i].layers);d.longEdge=d.history[i].longEdge;Object.assign(d,canvasSize(d.sourceBase.width,d.sourceBase.height,d.longEdge));d.selected=d.layers.at(-1)?.id??null;dirty=true;renderLayers();compose();});
  async function exportPNG(d){const canvas=document.createElement('canvas'),scratch=document.createElement('canvas');canvas.width=d.width;canvas.height=d.height;renderDocument(d,canvas,scratch,bridge.resolveClip);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));canvas.width=scratch.width=1;canvas.height=scratch.height=1;if(!blob)throw new Error('PNG 导出失败，请先保存工程');return blob;}
  $('exportColor').addEventListener('click',async()=>{try{bridge.message('正在按画布分辨率导出…');const m=material,d=doc();const blob=await exportPNG(d);save(blob,safeName(bridge.materialLabel(m))+'_颜色图.png');bridge.message(`已导出 ${d.width}×${d.height}；模型预览清晰度不会降低导出尺寸`);}catch(error){report(error);}});
  $('exportAll').addEventListener('click',async()=>{try{const files=[];let index=0;for(const [m,d] of documents)files.push({name:`${String(++index).padStart(2,'0')}_${safeName(bridge.materialLabel(m))}.png`,blob:await exportPNG(d)});await downloadZip(files,'改过的颜色贴图.zip');bridge.message('已导出修改过的颜色贴图；这不是完整游戏安装包');}catch(error){report(error);}});
  function projectData(){return{schema_version:2,kind:'wt-web-creative',model:bridge.modelIdentity(),parts:bridge.annotations(),materials:[...documents].map(([m,d])=>({name:m.name,identity:d.identity,native_width:d.sourceBase.width,native_height:d.sourceBase.height,width:d.width,height:d.height,long_edge:d.longEdge,base:d.sourceBase.toDataURL('image/png'),layers:serializeLayers(d.layers)})),output:'RGB color PNG; original C alpha/N/AO are not rewritten',game:'not_run'};}
  $('saveProject').addEventListener('click',()=>{try{const blob=new Blob([JSON.stringify(projectData())],{type:'application/json'});if(blob.size>limits.maxProjectBytes)throw new Error('工程超过 128 MiB，请减少内嵌素材后保存；当前修改仍保留');save(blob,'可编辑涂装工程.json');dirty=false;bridge.message('工程已保存，包含图层来源、中文部件分类和画布分辨率');}catch(error){report(error);}});
  $('openProject').addEventListener('click',()=>{if(!confirmDiscard())return;$('projectFile').click();});
  async function importProject(project){
    const generation=loadGeneration,startingRevision=revision;
    if(![1,2].includes(project.schema_version)||project.kind!=='wt-web-creative'||!Array.isArray(project.materials)||project.materials.length>64)throw new Error('这不是受支持的涂装工程');
    if(project.model!==bridge.modelIdentity())throw new Error('工程和当前模型不匹配，请打开保存工程时的同一模型');
    const pending=[],names=new Set();
    for(const record of project.materials){
      if(names.has(record.name))throw new Error('工程里重复保存了同一张贴图');names.add(record.name);const m=bridge.findMaterial(record.name);if(!m)throw new Error('当前模型没有这张贴图：'+record.name);
    if(!['name','source_sha256','source_size','view_mode','camo_sha256'].every(key=>JSON.stringify(record.identity?.[key])===JSON.stringify(bridge.identity(m)[key])))throw new Error('工程底图身份不匹配：'+bridge.materialLabel(m));
      if(!Array.isArray(record.layers)||record.layers.length>limits.layers)throw new Error('工程图层数量无效');
      const image=await imageFromData(record.base),nw=record.native_width||record.width,nh=record.native_height||record.height;if(image.width!==nw||image.height!==nh)throw new Error('工程原图尺寸不匹配');
      const longEdge=project.schema_version===1?0:record.long_edge??0;const d=makeDocument({image,width:nw,height:nh},m,longEdge);if(d.width!==record.width||d.height!==record.height)throw new Error('工程画布尺寸不匹配');
      const ids=new Set();for(const raw of record.layers){const row={...raw,origin:raw.origin||'imported'};validateLayer(row);if(ids.has(row.id))throw new Error('图层编号重复');ids.add(row.id);if(row.type==='decal'){row.image=await imageFromData(row.src);attachAlpha(row);}if([...(row.clipParts||[]),...(row.part_refs||[])].some(id=>!bridge.hasPart(id)))throw new Error('图层关联部件缺失，请核对模型');d.layers.push(row);}
      d.selected=d.layers.at(-1)?.id??null;d.history=[snapshot(d)];pending.push([m,d]);
    }
    const parts=bridge.validateAnnotations(project.parts||{});if(project.producer==='ai')for(const row of Object.values(parts))row.confirmed=false;if(generation!==loadGeneration)throw new Error('读取工程时模型发生了切换');if(revision!==startingRevision)throw new Error('读取期间出现了新修改，已保留当前工作，请重新打开工程');
    for(const [m,d] of documents)if(!names.has(m.name))bridge.setImage(m,{image:d.sourceBase,width:d.sourceBase.width,height:d.sourceBase.height,userNative:true});
    documents.clear();for(const [m,d] of pending){documents.set(m,d);compose(m);}bridge.restoreAnnotations(parts);dirty=false;mode='select';polygon=[];draft=null;renderLayers();bridge.redrawUV();bridge.message('工程已恢复：独立图案、改色和部件分类都可继续修改');
  }
  $('projectFile').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>limits.maxProjectBytes)throw new Error('工程超过 128 MiB，请拆分素材或减少底图数量');await importProject(JSON.parse(await file.text()));}catch(error){report(error);}finally{event.target.value='';}});
  function overlay(){const row=selected(),d=doc(),ctx=overlayContext,size=uv.width;if(!d)return;ctx.save();ctx.strokeStyle='#2865df';ctx.fillStyle='#2865df';ctx.lineWidth=3;
    if(row&&['decal','text','shape'].includes(row.type)){const g=layerGeometry(row,d.width,d.height);ctx.scale(size/d.width,size/d.height);ctx.translate(g.x,g.y);ctx.rotate(g.rotation);ctx.lineWidth=3*d.width/size;ctx.strokeRect(-g.width/2,-g.height/2,g.width,g.height);for(const x of [-g.width/2,g.width/2])for(const y of [-g.height/2,g.height/2])ctx.fillRect(x-4*d.width/size,y-4*d.height/size,8*d.width/size,8*d.height/size);}
    else{const points=draft||(polygon.length?polygon:row?.points);if(points?.length){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p[0]*size,p[1]*size):ctx.moveTo(p[0]*size,p[1]*size));if(!polygon.length)ctx.closePath();ctx.stroke();}}ctx.restore();}
  function confirmDiscard(){return !dirty||confirm('还有修改没保存。打开其它模型或工程会替换它们，继续吗？');}
  renderLayers();
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  return {
    select(m){if(material===m){updateControls();return;}material=m;mode='select';polygon=[];draft=null;drag=null;renderLayers();},
    reset(){loadGeneration++;documents.clear();queued.clear();material=null;mode='select';dirty=false;polygon=[];draft=null;drag=null;renderLayers();},overlay,
    picked(point,partId){const p=wrapUV(point),row=selected();if(mode==='position'&&row&&!row.locked&&['decal','text','shape'].includes(row.type)){row.x=p[0];row.y=p[1];if(partId)row.part_refs=[partId];commit();}else if(mode==='select')selectAt(p);},
    quality(value){quality=value;for(const m of documents.keys())compose(m);},
    annotationsChanged(){revision++;dirty=true;updateControls();},
    replaceBase(m){documents.delete(m);if(material===m)renderLayers();},
    confirmDiscard,hasEdits:()=>dirty,hasDocument:m=>documents.has(m),refresh:updateControls
  };
}
