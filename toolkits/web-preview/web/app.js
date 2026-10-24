import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { TGALoader } from 'three/addons/loaders/TGALoader.js';
import { createEditor } from './editor.js';
import {CATEGORIES,partRecord,materialLabel,validatePartOverrides} from './parts.js';
import {setupSkinImport} from './skin-open.js';
import {makeDemo} from './demo.js';

const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['viewport','empty','loading','modelName','parts','partCount','search','quality','wire','isolate','showAll','materials','replace','uv','picked','materialInfo','record','capture','status','metrics'].map(id => [id, $(id)]));
const state = { model:null, meshes:[], materials:[], selected:null, material:null, marker:null, originals:new Map(), records:[], source:null, serial:0, frames:0, triangles:0, textures:new Set(),parts:[],annotations:{},clipCache:new Map(),uvWireCache:new Map() };
let renderer, scene, camera, controls, radius = 6, center = new THREE.Vector3(), bounds = null, renderPending = false;
const raycaster = new THREE.Raycaster();
const context = ui.uv.getContext('2d');
let selectionBox=null;
const editor=createEditor({ensureNative,identity:materialIdentity,modelIdentity:()=>state.source?.manifest?.source_obj_sha256 || state.source?.model_signature || state.source?.sha256 || null,
  findMaterial:name=>state.materials.find(m=>m.name===name),
  setImage:(m,image)=>{const old=state.originals.get(m);old?.source?.dispose();old?.source?.image?.close?.();state.originals.set(m,image);applyQuality(m);},redrawUV:drawUV,error:fail,message:status,
  materialLabel:m=>materialLabel(m.name,state.materials.indexOf(m)),annotations:()=>structuredClone(state.annotations),validateAnnotations:rows=>{validatePartOverrides(rows);for(const id of Object.keys(rows))if(!state.parts.some(p=>p.id===id))throw new Error('工程里的部件编号与当前模型不同');return rows;},
  restoreAnnotations:rows=>{for(const id of Object.keys(rows))if(!state.parts.some(p=>p.id===id))throw new Error('工程里的部件编号与当前模型不同');state.annotations=rows;state.parts=state.meshes.map((mesh,i)=>partRecord(mesh,i,rows));showParts();},
  selectedParts:()=>state.selected?[state.selected.userData.workbenchPartId]:[],partLabel:id=>state.parts.find(p=>p.id===id)?.label||'部件未找到',
  hasPart:id=>state.parts.some(p=>p.id===id),resolveClip,
  focusParts:ids=>{const part=state.parts.find(p=>ids.includes(p.id));if(part){selectMesh(part.mesh);fit('front',new THREE.Box3().setFromObject(part.mesh));}}
});

function materialIdentity(m) {
  const info=m.userData?.source;
  return {name:m.name,source_sha256:info?.source_sha256 || state.source?.sha256 || null,source_size:info?.source_size || [state.originals.get(m)?.width,state.originals.get(m)?.height],view_mode:info?.view_mode || 'fixed-color-rgb',camo_sha256:info?.camo_sha256 || null};
}
async function ensureNative(m,refresh=true) {
  const original=state.originals.get(m), info=m.userData?.source;
  if(info?.source_quality==='thumbnail-only'&&!original?.userNative)throw new Error('游戏资源目前只有此材质的缩略级纹理；请先替换原尺寸颜色图，创作器不会把缩略图当生产基底');
  if(original?.userNative&&!original.editorCanvas)return original;
  const expected=info?.source_size;
  if (original && (!expected || original.width===expected[0] && original.height===expected[1])) return original;
  const filename=info?.native_file;
  if (!state.source?.manifestURL || !/^native-color-[0-9]+\.png$/.test(filename || '')) throw new Error('当前只有预览图；请先替换为此材质原尺寸 RGB 图，或使用本地 prepare 场景再创作');
  const url=new URL(filename,state.source.manifestURL);
  status('正在按需读取原尺寸颜色图…');
  const serial=state.serial;const response=await fetch(url);if(!response.ok)throw new Error('原尺寸颜色图读取失败: '+response.status);
  const blob=await response.blob();
  if (info.native_sha256) { const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join(''); if(hash!==info.native_sha256)throw new Error('原尺寸颜色图哈希变化，拒绝编辑'); }
  const bitmap=await createImageBitmap(blob);
  if(!expected || bitmap.width!==expected[0] || bitmap.height!==expected[1]){bitmap.close();throw new Error('原尺寸颜色图尺寸不匹配');}
  const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;canvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();
  if(serial!==state.serial)throw new Error('读取底图时模型已经切换');
  const value={image:canvas,width:canvas.width,height:canvas.height};original?.source?.dispose();original?.source?.image?.close?.();state.originals.set(m,value);if(refresh)applyQuality(m);status('已读取原尺寸底图；模型显示档位不改变导出画布');return value;
}

function status(text, error = false) { ui.status.textContent = text; ui.status.classList.toggle('error', error); }
function fail(error) { console.error(error); status(error.message || String(error), true); ui.loading.hidden = true; }
function download(blob, name) { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function render() { renderPending = false; if (!renderer || document.hidden) return; renderer.render(scene, camera); state.frames++; ui.metrics.dataset.frames=String(state.frames); }
function invalidate() { if (!renderPending && renderer) { renderPending = true; requestAnimationFrame(render); } }
function resize() { if (!renderer) return; const box = ui.viewport.getBoundingClientRect(),limit=Math.min(Number(ui.quality.value),renderer.capabilities.maxTextureSize,renderer.getContext().getParameter(renderer.getContext().MAX_RENDERBUFFER_SIZE));const scale=limit/Math.max(box.width,box.height);renderer.setSize(Math.max(1,Math.round(box.width*scale)),Math.max(1,Math.round(box.height*scale)),false);camera.aspect=box.width/box.height;camera.updateProjectionMatrix();$('renderInfo').textContent=`模型画面 ${renderer.domElement.width} × ${renderer.domElement.height} · 不改变模型面数`;invalidate(); }

function startRenderer() {
  if (renderer) return;
  try { renderer = new THREE.WebGLRenderer({antialias:false, alpha:false, powerPreference:'low-power'}); }
  catch { throw new Error('无法启动 WebGL2。请启用浏览器硬件加速，或换用支持 WebGL2 的浏览器。'); }
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  ui.viewport.append(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color('#94979c');
  camera = new THREE.PerspectiveCamera(36, 1, .01, 10000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x737a83, 1.5));
  const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(4, 7, 4); scene.add(key);
  const fill = new THREE.DirectionalLight(0xe9f0ff, 1); fill.position.set(-5, 3, -3); scene.add(fill);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false; controls.screenSpacePanning = true;
  controls.addEventListener('change', () => { document.querySelectorAll('[data-view]').forEach(b => b.classList.remove('active')); invalidate(); });
  new ResizeObserver(resize).observe(ui.viewport);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) invalidate(); });
  renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); status('图形上下文已丢失，请重新打开模型或刷新页面。', true); });
  renderer.domElement.addEventListener('webglcontextrestored', () => { status('图形上下文已恢复'); invalidate(); });
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => { if (down && Math.hypot(down[0]-e.clientX, down[1]-e.clientY)<5) pick(e); down = null; });
  resize();
}

function releaseModel(model) {
  if (!model) return;
  const materials = new Set(), textures = new Set();
  model.traverse(obj => { if (obj.geometry) obj.geometry.dispose(); for (const m of Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []) { materials.add(m); for (const val of Object.values(m)) if (val?.isTexture) textures.add(val); } });
  for (const texture of textures) { texture.dispose(); if (texture.image?.close) texture.image.close(); }
  for (const m of materials) m.dispose();
  scene?.remove(model);
}

function materialList(mesh) { return Array.isArray(mesh.material) ? mesh.material : [mesh.material]; }
function resetModel() {
  editor.reset();
  releaseModel(state.model);
  const originals=new Set([...state.originals.values()].map(value => value.source).filter(Boolean));
  for (const texture of originals) { texture.dispose(); texture.image?.close?.(); }
  for (const texture of state.textures) texture.dispose();
  state.textures.clear(); state.originals.clear(); state.meshes=[]; state.materials=[];
  state.model=null; state.selected=null; state.material=null; state.marker=null; state.triangles=0;
  state.parts=[];state.annotations={};state.clipCache.clear();state.uvWireCache.clear();clearSelection();$('partEditor').hidden=true;
  ui.empty.hidden=false;
  for (const id of ['materials','replace','record','capture','showAll']) ui[id].disabled=true;
}

function showParts() {
  const query = ui.search.value.toLowerCase(); ui.parts.replaceChildren();
  for(const category of CATEGORIES){
    const rows=state.parts.filter(p=>p.category===category&&`${p.label} ${p.original} ${p.category}`.toLowerCase().includes(query));if(!rows.length)continue;
    const group=document.createElement('details'),summary=document.createElement('summary');summary.textContent=`${category}（${rows.length}）`;group.open=!!query||rows.some(p=>p.mesh===state.selected)||category==='车身';group.append(summary);
    for(const part of rows){const b=document.createElement('button');b.className='part';b.textContent=part.label+(part.confirmed?' · 已确认':'');b.title=part.original+'\n'+(part.confirmed?'人工确认':'按名称推测，可在下方修正');b.dataset.partId=part.id;b.classList.toggle('active',part.mesh===state.selected);b.addEventListener('click',()=>selectMesh(part.mesh));group.append(b);}ui.parts.append(group);
  }
  ui.partCount.textContent = String(state.meshes.length);
}

function clearSelection(){if(selectionBox){scene?.remove(selectionBox);selectionBox.geometry.dispose();selectionBox.material.dispose();selectionBox=null;}}
function resolveClip(ids,materialName){
  const key=JSON.stringify([ids,materialName]);if(state.clipCache.has(key))return state.clipCache.get(key);
  const result=[];
  for(const part of state.parts.filter(p=>ids.includes(p.id))){const geometry=part.mesh.geometry,uv=geometry.attributes.uv,index=geometry.index;if(!uv)continue;const mats=materialList(part.mesh),groups=geometry.groups.length?geometry.groups:[{start:0,count:index?.count??geometry.attributes.position.count,materialIndex:0}];
    for(const group of groups){if(mats[group.materialIndex]?.name!==materialName)continue;for(let i=group.start;i<group.start+group.count;i+=3){const triangle=[];for(let j=0;j<3;j++){const n=index?index.getX(i+j):i+j;triangle.push([uv.getX(n),state.source?.format==='obj'?1-uv.getY(n):uv.getY(n)]);}const xs=triangle.map(p=>p[0]),ys=triangle.map(p=>p[1]),x0=Math.floor(Math.min(...xs)),x1=Math.floor(Math.max(...xs)),y0=Math.floor(Math.min(...ys)),y1=Math.floor(Math.max(...ys));if(x1-x0>16||y1-y0>16)continue;for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++)result.push(triangle.map(p=>[p[0]-x,p[1]-y]));}}
  }state.clipCache.set(key,result);return result;
}

function applyVisibility() { for (const mesh of state.meshes) mesh.visible = !ui.isolate.checked || mesh === state.selected; invalidate(); }
function selectMesh(mesh, hit = null) {
  state.selected = mesh; showParts(); applyVisibility();
  clearSelection();selectionBox=new THREE.BoxHelper(mesh,0x4185e8);selectionBox.material.depthTest=false;scene.add(selectionBox);
  const part=state.parts.find(p=>p.mesh===mesh);$('partAlias').value=part?.label||'';$('partCategory').value=part?.category||'待分类';$('partOriginal').textContent=mesh.name;$('partBasis').textContent=part?.confirmed?'人工已确认':'按名称推测，请看模型核对';$('partEditor').hidden=false;editor.refresh();
  const mats=materialList(mesh); const m=mats[hit?.face?.materialIndex ?? 0];
  if (m) selectMaterial(m);
  if (hit?.uv) {
    const sourceUV = {u:hit.uv.x, v:state.source?.format === 'obj' ? hit.uv.y : 1-hit.uv.y};
    const record = {node:mesh.name, material:m.name, uv_obj:sourceUV, face_index:hit.faceIndex, point:hit.point.toArray(), time:new Date().toISOString()};
    state.marker=sourceUV; state.records.push(record);
    ui.picked.textContent=`选中：${part?.label||'部件'} · 平面位置 ${(sourceUV.u*100).toFixed(1)}%，${((1-sourceUV.v)*100).toFixed(1)}%`;
    drawUV();
    editor.picked(sourceUV,mesh.userData.workbenchPartId);
  }
}

function selectMaterial(material) {
  state.material = material; state.marker = null;
  ui.materials.value=String(state.materials.indexOf(material));
  const info=material.userData?.source || material.userData?.gltfExtensions?.source;
  const original=state.originals.get(material);
  ui.materialInfo.textContent = `${material.name || '未命名材质'}${original ? ` · 当前图 ${original.width}×${original.height}` : ' · 未绑定颜色图'}${info?.source_size ? ` · 源图 ${info.source_size.join('×')}` : ''}${info?.view_mode==='stock-camo-approx'?' · 原车涂层近似':''}${info?.source_quality==='thumbnail-only'?' · 仅缩略级，编辑需补原图':''}${info?.shader ? '\n源 shader: '+info.shader : ''}`;
  editor.select(material);
  ui.picked.textContent='点击模型选部件或图案，也可在平面贴图上精调'; drawUV();
}

function drawUV() {
  const size=ui.uv.width; context.clearRect(0,0,size,size);
  const material=state.material;
  if (!material) return;
  const image=state.originals.get(material)?.image;
  if (image) {ui.uv.style.aspectRatio=`${image.width} / ${image.height}`;context.drawImage(image,0,0,size,size);}
  if($('uvLines').checked){
  let wire=state.uvWireCache.get(material);
  if(!wire){wire=document.createElement('canvas');wire.width=wire.height=size;const wireContext=wire.getContext('2d');
  wireContext.strokeStyle='rgba(203,222,245,.65)';wireContext.lineWidth=.8;wireContext.beginPath();
  for (const mesh of state.meshes) {
    const geometry=mesh.geometry, uv=geometry.attributes.uv; if (!uv) continue;
    const materials=materialList(mesh); const index=geometry.index;
    const groups=geometry.groups.length ? geometry.groups : [{start:0,count:index?.count ?? geometry.attributes.position.count,materialIndex:0}];
    for (const group of groups) {
      if (materials[group.materialIndex] !== material) continue;
      for (let i=group.start; i<group.start+group.count; i+=3) {
        const points=[];
        for (let j=0;j<3;j++) { const n=index ? index.getX(i+j) : i+j; const u=uv.getX(n), v=uv.getY(n); points.push([u*size,(state.source?.format==='obj' ? 1-v : v)*size]); }
        wireContext.moveTo(...points[0]); wireContext.lineTo(...points[1]); wireContext.lineTo(...points[2]); wireContext.lineTo(...points[0]);
      }
    }
  }
  wireContext.stroke();state.uvWireCache.set(material,wire);}
  context.drawImage(wire,0,0);}
  if (state.marker) {
    const x=((state.marker.u%1)+1)%1*size, y=(1-((state.marker.v%1)+1)%1)*size;
    context.strokeStyle='#ff3d55'; context.lineWidth=4; context.beginPath(); context.arc(x,y,13,0,Math.PI*2); context.moveTo(x-22,y); context.lineTo(x+22,y); context.moveTo(x,y-22); context.lineTo(x,y+22); context.stroke();
  }
  editor.overlay();
}

function fit(view='front',selectedBounds=null) {
  const frameBounds=selectedBounds||bounds;if(!frameBounds)return;const frameCenter=frameBounds.getCenter(new THREE.Vector3()),frameRadius=Math.max(.01,frameBounds.getBoundingSphere(new THREE.Sphere()).radius);
  const vectors={front:[1,.45,-1],left:[1,.12,0],right:[-1,.12,0],top:[0,1,.0001],reset:[1,.45,-1]};
  const direction=new THREE.Vector3(...vectors[view]).normalize();
  const vertical=camera.fov*Math.PI/180; const horizontal=2*Math.atan(Math.tan(vertical/2)*camera.aspect);
  const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),direction).normalize();
  const up=new THREE.Vector3().crossVectors(direction,right).normalize();
  let distance=0;
  for (const x of [frameBounds.min.x,frameBounds.max.x]) for (const y of [frameBounds.min.y,frameBounds.max.y]) for (const z of [frameBounds.min.z,frameBounds.max.z]) {
    const corner=new THREE.Vector3(x,y,z).sub(frameCenter);
    distance=Math.max(distance,corner.dot(direction)+Math.max(Math.abs(corner.dot(right))/Math.tan(horizontal/2),Math.abs(corner.dot(up))/Math.tan(vertical/2)));
  }
  distance*=1.08;
  camera.position.copy(frameCenter).add(direction.normalize().multiplyScalar(distance)); camera.up.set(0,1,0);
  camera.near=Math.max(frameRadius/1000,.001); camera.far=Math.max(radius,frameRadius)*100; camera.updateProjectionMatrix();
  controls.target.copy(frameCenter); controls.minDistance=frameRadius*.1; controls.maxDistance=radius*30; controls.update();
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active',b.dataset.view===view)); invalidate();
}

async function bitmapFromTexture(texture) {
  const img=texture?.image;
  if (!img) return null;
  if (texture.isCompressedTexture || img.data) {
    // Compressed DDS pixels require GPU decompression; do not fake a readable UV image.
    return null;
  }
  const canvas=document.createElement('canvas'); canvas.width=img.width; canvas.height=img.height;
  const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0); return canvas;
}

function applyQuality(targetMaterial=null) {
  const limit=Number(ui.quality.value);
  renderer?.setPixelRatio(1);
  for (const material of targetMaterial ? [targetMaterial] : state.materials) {
    const original=state.originals.get(material); if (!original) continue;
    const scale=Math.min(1,limit/original.width,limit/original.height);
    const canvas=document.createElement('canvas'); canvas.width=Math.max(1,Math.round(original.width*scale)); canvas.height=Math.max(1,Math.round(original.height*scale));
    canvas.getContext('2d').drawImage(original.image,0,0,canvas.width,canvas.height);
    const previous=material.map; const map=new THREE.CanvasTexture(canvas); map.colorSpace=THREE.SRGBColorSpace;
    map.flipY=state.source?.format==='obj'; map.wrapS=map.wrapT=THREE.RepeatWrapping;
    map.anisotropy=1; material.map=map; material.color.set(0xffffff); material.needsUpdate=true;
    if (previous && previous!==original.source) { previous.dispose(); state.textures.delete(previous); }
    state.textures.add(map);
  }
  resize(); drawUV(); invalidate();
}

async function acceptModel(object, label, source, serial) {
  if (serial!==state.serial) { releaseModel(object); return; }
  startRenderer(); resetModel(); state.model=object; state.source=source; state.records=[];
  object.traverse(obj => {
    if (!obj.isMesh) return;
    if (!obj.geometry.attributes.normal) obj.geometry.computeVertexNormals();
    state.meshes.push(obj); state.triangles+=(obj.geometry.index?.count ?? obj.geometry.attributes.position.count)/3;
    for (const m of materialList(obj)) { m.wireframe=ui.wire.checked; m.side=THREE.DoubleSide; if (!state.materials.includes(m)) state.materials.push(m); }
  });
  if (!state.meshes.length) { resetModel(); throw new Error('模型没有可显示的三角面'); }
  for (const material of state.materials) {
    const image=await bitmapFromTexture(material.map);
    if (serial!==state.serial) return;
    if (image) state.originals.set(material,{image,width:image.width,height:image.height,source:material.map});
  }
  scene.add(object);
  state.parts=state.meshes.map((mesh,index)=>{const record=partRecord(mesh,index);mesh.userData.workbenchPartId=record.id;return record;});
  const box=new THREE.Box3().setFromObject(object); bounds=box.clone(); const sphere=box.getBoundingSphere(new THREE.Sphere());
  if (!Number.isFinite(sphere.radius) || sphere.radius===0) throw new Error('模型边界无效');
  center.copy(sphere.center); radius=sphere.radius;
  ui.modelName.textContent=label==='ztz_99a'?'99A 主战坦克':label; ui.modelName.title=label; ui.materials.replaceChildren();
  state.materials.forEach((m,i) => { const option=document.createElement('option'); option.value=String(i); const label=materialLabel(m.name,i),siblings=state.materials.filter(n=>materialLabel(n.name,state.materials.indexOf(n))===label);option.textContent=label+(siblings.length>1?' '+(siblings.indexOf(m)+1):'');option.title=m.name;ui.materials.append(option); });
  for (const id of ['materials','replace','record','capture','showAll']) ui[id].disabled=false;
  ui.empty.hidden=true; ui.loading.hidden=true; showParts(); applyVisibility(); selectMaterial(state.materials[0]); applyQuality(); fit();
  ui.metrics.textContent=`${state.meshes.length} 个可选部件 · ${Math.round(state.triangles).toLocaleString()} 三角面`;
  const imported=source.manifest?.imported_skin;if(imported&&$('importStatus'))$('importStatus').textContent=`已识别 ${label==='ztz_99a'?'99A 主战坦克':label} · 模型来源：${imported.model_origin==='package'?'包内配套模型':'战雷安装文件夹'}${imported.warnings?.length?' · '+imported.warnings.join('；'):''}`;
  const unbound=state.materials.filter(m => !m.map).length, thumbnails=state.materials.filter(m=>m.userData?.source?.source_quality==='thumbnail-only').length;
  status(`按需渲染 · 本地文件仅在浏览器处理${unbound ? ` · ${unbound} 个材质未绑定颜色图` : ''}${thumbnails?` · ${thumbnails} 个材质只有缩略级纹理`:''}`);
}

async function loadTexture(file) {
  if (file.size>128*1024*1024) throw new Error('颜色图文件超过 128 MiB，请先生成预览副本');
  const extension=file.name.split('.').pop().toLowerCase();
  if (extension==='dds') throw new Error('DDS 请先由 prepare 转成 RGB 预览，避免把压缩格式或数据 Alpha 当颜色透明度');
  if (extension==='tga') {
    const data=new TGALoader().parse(await file.arrayBuffer());
    const canvas=document.createElement('canvas'); canvas.width=data.width; canvas.height=data.height;
    const pixels=new Uint8ClampedArray(data.data);
    for (let i=3;i<pixels.length;i+=4) pixels[i]=255;
    canvas.getContext('2d').putImageData(new ImageData(pixels,data.width,data.height),0,0);
    return {image:canvas,width:canvas.width,height:canvas.height};
  }
  const bitmap=await createImageBitmap(file);
  if (bitmap.width>16384 || bitmap.height>16384) { bitmap.close(); throw new Error('颜色图尺寸超过 16384，请用本地工具准备预览'); }
  const canvas=document.createElement('canvas'); canvas.width=bitmap.width; canvas.height=bitmap.height;
  const ctx=canvas.getContext('2d'); ctx.drawImage(bitmap,0,0); bitmap.close();
  const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
  for (let i=3;i<pixels.length;i+=4) if (pixels[i]!==255) throw new Error('此颜色图含透明 Alpha；请通过 prepare 转成 RGB 预览，保留隐藏颜色数据');
  return {image:canvas,width:canvas.width,height:canvas.height};
}

async function loadFiles(files) {
  if(!editor.confirmDiscard())return;
  const serial=++state.serial;
  const models=files.filter(f => /\.(glb|obj)$/i.test(f.name));
  if (models.length!==1) throw new Error('一次请选择一个 GLB 或 OBJ 模型，可同时选配套 MTL 和颜色图');
  const file=models[0]; if (file.size>100*1024*1024) throw new Error('模型超过 100 MiB，请先用 prepare 生成紧凑 GLB');
  ui.loading.hidden=false;
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('');
  let object, source={name:file.name,bytes:file.size,sha256:hash,format:file.name.toLowerCase().endsWith('.obj') ? 'obj' : 'glb'};
  if (source.format==='obj') {
    object=new OBJLoader().parse(await file.text());
    const mtl=files.find(f => /\.mtl$/i.test(f.name)); const maps=new Map();
    if (mtl) {
      let name=''; for (const line of (await mtl.text()).split(/\r?\n/)) { const match=/^\s*(newmtl|map_Kd)\s+(.+?)\s*$/.exec(line); if (!match) continue; if (match[1]==='newmtl') name=match[2]; else maps.set(name,match[2].replaceAll('\\','/').split('/').pop()); }
    }
    const loaded=new Map();
    for (const [name,filename] of maps) {
      const textureFile=files.find(f => f.name===filename); if (!textureFile) continue;
      loaded.set(name,await loadTexture(textureFile));
    }
    object.traverse(mesh => { if (!mesh.isMesh) return; for (const material of materialList(mesh)) { const data=loaded.get(material.name); if (data) { material.map=new THREE.CanvasTexture(data.image); material.map.colorSpace=THREE.SRGBColorSpace; material.map.flipY=true; material.color.set(0xffffff); } } });
  } else {
    // Only embedded resources: opening a local GLB must never follow an embedded remote URL.
    const manager=new THREE.LoadingManager(); manager.setURLModifier(url => { if (!url.startsWith('blob:') && !url.startsWith('data:')) throw new Error('GLB 引用了外部资源，请打包成自包含 GLB'); return url; });
    const gltf=await new GLTFLoader(manager).parseAsync(await file.arrayBuffer(),''); object=gltf.scene;source.model_signature=object.userData?.source_obj_sha256;
  }
  await acceptModel(object,file.name,source,serial);
}

async function loadScene(url,localScene=null) {
  const serial=++state.serial; ui.loading.hidden=false;
  const base=new URL(url,location.href); if (base.origin!==location.origin) throw new Error('仅加载同源准备场景');
  const response=await fetch(base); if (!response.ok) throw new Error(`场景读取失败 ${response.status}`);
  const manifest=await response.json();
  if (manifest.schema_version!==1 || typeof manifest.model!=='string') throw new Error('未知场景清单格式');
  const modelURL=new URL(manifest.model,base); if (modelURL.origin!==base.origin) throw new Error('模型必须与场景同源');
  const modelResponse=await fetch(modelURL); if (!modelResponse.ok) throw new Error(`模型读取失败 ${modelResponse.status}`);
  const buffer=await modelResponse.arrayBuffer();
  const manager=new THREE.LoadingManager(); manager.setURLModifier(url => { if (!url.startsWith('blob:') && !url.startsWith('data:')) throw new Error('准备场景需要自包含 GLB'); return url; });
  const gltf=await new GLTFLoader(manager).parseAsync(buffer,'');
  await acceptModel(gltf.scene,manifest.label || manifest.model,{format:'glb',manifest,manifestURL:base.href,localScene},serial);
}

function pick(event) {
  if (!state.model) return;
  const rect=renderer.domElement.getBoundingClientRect(); const point=new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
  raycaster.setFromCamera(point,camera);
  const hit=raycaster.intersectObjects(state.meshes.filter(m => m.visible),false)[0]; if (hit) selectMesh(hit.object,hit);
}

$('open').addEventListener('click',() => $('files').click()); $('openEmpty').addEventListener('click',() => $('files').click());
$('files').addEventListener('change',async e => { try { await loadFiles([...e.target.files]); } catch(error) { fail(error); } finally { e.target.value=''; } });
ui.viewport.addEventListener('dragover',e => e.preventDefault()); ui.viewport.addEventListener('drop',async e => { e.preventDefault(); try { await loadFiles([...e.dataTransfer.files]); } catch(error) { fail(error); } });
ui.search.addEventListener('input',showParts);
ui.showAll.addEventListener('click',() => { ui.isolate.checked=false; ui.search.value=''; showParts(); applyVisibility(); });
ui.isolate.addEventListener('change',applyVisibility);
ui.quality.addEventListener('change',async()=>{const limit=Number(ui.quality.value),serial=state.serial;ui.quality.disabled=true;try{if(limit>1024&&state.source?.manifestURL)for(const m of state.materials){const info=m.userData?.source,original=state.originals.get(m);if(info?.native_file&&info.source_quality!=='thumbnail-only'&&!editor.hasDocument(m)&&info.source_size&&Math.max(...info.source_size)>Math.max(original?.width||0,original?.height||0))await ensureNative(m,false);}if(serial!==state.serial)return;applyQuality();editor.quality(limit);status(`模型显示上限 ${limit===512?'512':limit/1024+'K'}；导出仍按各贴图画布设置`);}catch(error){fail(error);}finally{ui.quality.disabled=false;}});
ui.wire.addEventListener('change',() => { for (const m of state.materials) m.wireframe=ui.wire.checked; invalidate(); });
ui.materials.addEventListener('change',() => selectMaterial(state.materials[Number(ui.materials.value)]));
ui.replace.addEventListener('click',() => $('textureFile').click());
$('textureFile').addEventListener('change',async e => {
  const file=e.target.files[0], material=state.material, serial=state.serial; if (!file || !material) return;
  try { const texture=await loadTexture(file); if (serial!==state.serial) return; const info=material.userData?.source,expected=info?.source_size;const aspectChanged=expected&&Math.abs(texture.width/texture.height-expected[0]/expected[1])>.01;if(Math.max(texture.width,texture.height)>8192)throw new Error('编辑底图最大支持 8192');texture.userNative=true;const old=state.originals.get(material); old?.source?.dispose(); old?.source?.image?.close?.(); editor.replaceBase(material);state.originals.set(material,texture); applyQuality(); selectMaterial(material); status(`已换成 ${texture.width}×${texture.height} 的颜色底图；原文件保留${aspectChanged?'；宽高比例已变化，请核对模型上的图案':''}`); }
  catch(error) { fail(error); } finally { e.target.value=''; }
});
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click',() => { if (state.model) fit(b.dataset.view); }));
ui.capture.addEventListener('click',() => { if(selectionBox)selectionBox.visible=false;renderer.render(scene,camera); renderer.domElement.toBlob(blob => { if (blob) download(blob,'模型预览.png'); else status('截图失败',true); });if(selectionBox)selectionBox.visible=true;invalidate(); });
ui.record.addEventListener('click',() => download(new Blob([JSON.stringify({schema_version:1,source:state.source,camera:{position:camera.position.toArray(),target:controls.target.toArray()},quality:Number(ui.quality.value),observations:state.records,game:'not_run',visual:'requires-review'},null,2)],{type:'application/json'}),'模型UV检查.json'));
window.addEventListener('pagehide',() => { resetModel(); controls?.dispose(); renderer?.dispose(); });
const sceneURL=new URLSearchParams(location.search).get('scene');
async function loadDemo(){if(!editor.confirmDiscard())return;await acceptModel(makeDemo(),'交互演示车 · 非游戏模型',{format:'glb',sha256:'procedural-demo-v1'},++state.serial);status('这是可旋转、可选部件、可编辑贴图的三维演示；打开模型可查看你自己的载具');}
if (sceneURL) loadScene(sceneURL).catch(fail);else loadDemo().catch(fail);
$('demo').addEventListener('click',()=>loadDemo().catch(fail));
setupSkinImport({confirmDiscard:editor.confirmDiscard,hasEdits:editor.hasEdits,loadScene,serial:()=>state.serial,message:status,error:fail});
$('partCategory').replaceChildren(...CATEGORIES.map(value=>{const option=document.createElement('option');option.value=option.textContent=value;return option;}));
$('savePart').addEventListener('click',()=>{if(!state.selected)return;const label=$('partAlias').value.trim();if(!label){status('给这个部件起一个中文名称',true);return;}const id=state.selected.userData.workbenchPartId;state.annotations[id]={label,category:$('partCategory').value,confirmed:true};state.parts=state.meshes.map((m,i)=>partRecord(m,i,state.annotations));showParts();$('partBasis').textContent='人工已确认';editor.annotationsChanged();status('部件分类已更新，保存工程后可保留');});
$('focusPart').addEventListener('click',()=>{if(state.selected)fit('front',new THREE.Box3().setFromObject(state.selected));else status('先选一个部件，再看近一点');});
$('exportContract').addEventListener('click',()=>{if(!state.model){status('先打开模型',true);return;}download(new Blob([JSON.stringify({schema_version:1,kind:'wt-paint-contract',local_scene:state.source?.localScene||null,model:state.source?.manifest?.source_obj_sha256||state.source?.model_signature||state.source?.sha256,parts:state.parts.map(({mesh,...record})=>record),materials:state.materials.map((m,i)=>({name:m.name,label:materialLabel(m.name,i),identity:materialIdentity(m)}))},null,2)],{type:'application/json'}),'给AI的部件与贴图清单.json');});
$('uvLines').addEventListener('change',drawUV);
// Small read-only diagnostics for functional verification and AI inspection.
window.previewDiagnostics=() => ({meshes:state.meshes.length,materials:state.materials.length,triangles:state.triangles,frames:state.frames,selected:state.selected?.name,observations:state.records.length,textureSizes:state.materials.map(m => ({name:m.name,width:m.map?.image?.width,height:m.map?.image?.height})),renderer:renderer?.info.render,source:state.source});
