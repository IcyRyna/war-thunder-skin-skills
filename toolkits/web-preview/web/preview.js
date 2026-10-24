import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {studioEnvironment,createReflection} from './reflection.js';

const $=id=>document.getElementById(id);
const ui=Object.fromEntries(['viewport','loading','empty','quality','modelName','capture','status','metrics'].map(id=>[id,$(id)]));
const query=new URLSearchParams(location.search),embedded=query.get('embed')==='1';
const state={model:null,meshes:[],materials:[],colors:new Map(),source:null,frames:0,serial:0};
let renderer,scene,camera,controls,environment,bounds,radius=1,pending=false;
const reflections=createReflection({enabled:$('reflectionEnabled'),amount:$('reflectionAmount'),detail:$('normalEnabled'),summary:$('reflectionSummary'),invalidate,source:()=>state.source});
ui.quality.disabled=true;
for(const id of ['reflectionEnabled','reflectionAmount','normalEnabled'])$(id).disabled=true;
document.querySelectorAll('[data-view]').forEach(button=>{button.disabled=true;});

if(embedded){const link=$('expand'),url=new URL(location.href);url.searchParams.delete('embed');link.href=url.href;link.hidden=false;}
function status(message,error=false){ui.status.textContent=message;ui.status.classList.toggle('error',error);}
function fail(error){console.error(error);ui.loading.hidden=false;ui.loading.textContent='无法加载三维预览：'+(error.message||String(error));status(error.message||String(error),true);}
function invalidate(){if(!renderer||pending)return;pending=true;requestAnimationFrame(()=>{pending=false;if(document.hidden)return;renderer.render(scene,camera);ui.metrics.dataset.frames=String(++state.frames);});}
function resize(){
  if(!renderer)return;
  const box=ui.viewport.getBoundingClientRect();if(!box.width||!box.height)return;
  const gl=renderer.getContext(),limit=Math.min(Number(ui.quality.value),renderer.capabilities.maxTextureSize,gl.getParameter(gl.MAX_RENDERBUFFER_SIZE)),scale=limit/Math.max(box.width,box.height);
  renderer.setSize(Math.max(1,Math.round(box.width*scale)),Math.max(1,Math.round(box.height*scale)),false);camera.aspect=box.width/box.height;camera.updateProjectionMatrix();invalidate();
}
function start(){
  if(renderer)return;
  try{renderer=new THREE.WebGLRenderer({antialias:false,alpha:false,powerPreference:'low-power'});}catch{throw new Error('需要支持 WebGL2 的浏览器，请开启硬件加速');}
  renderer.setPixelRatio(1);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.NoToneMapping;
  ui.viewport.append(renderer.domElement);scene=new THREE.Scene();scene.background=new THREE.Color('#94979c');environment=studioEnvironment(renderer);scene.environment=environment.texture;
  camera=new THREE.PerspectiveCamera(36,1,.01,10000);
  scene.add(new THREE.HemisphereLight(0xffffff,0x737a83,1.5));
  const key=new THREE.DirectionalLight(0xffffff,2);key.position.set(4,7,4);scene.add(key);
  const fill=new THREE.DirectionalLight(0xe9f0ff,1);fill.position.set(-5,3,-3);scene.add(fill);
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.screenSpacePanning=true;
  controls.addEventListener('change',()=>{document.querySelectorAll('[data-view]').forEach(b=>b.classList.remove('active'));invalidate();});
  new ResizeObserver(resize).observe(ui.viewport);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)invalidate();});
  renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();status('图形上下文已丢失，请刷新页面重新载入。',true);});
  renderer.domElement.addEventListener('webglcontextrestored',invalidate);resize();
}
function fit(view='front'){
  if(!bounds||!camera)return;
  const center=bounds.getCenter(new THREE.Vector3());
  const vectors={front:[1,.45,-1],left:[0,.12,-1],right:[0,.12,1],top:[0,1,.0001],reset:[1,.45,-1]};
  const direction=new THREE.Vector3(...vectors[view]).normalize(),right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),direction).normalize(),up=new THREE.Vector3().crossVectors(direction,right).normalize();
  const vertical=camera.fov*Math.PI/180,horizontal=2*Math.atan(Math.tan(vertical/2)*camera.aspect),corner=new THREE.Vector3();let distance=0;
  state.model.updateMatrixWorld(true);
  for(const mesh of state.meshes){const positions=mesh.geometry.attributes.position;for(let i=0;i<positions.count;i++){
    corner.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld).sub(center);
    distance=Math.max(distance,corner.dot(direction)+Math.max(Math.abs(corner.dot(right))/Math.tan(horizontal/2),Math.abs(corner.dot(up))/Math.tan(vertical/2)));
  }}
  camera.position.copy(center).add(direction.multiplyScalar(distance*1.08));camera.up.set(0,1,0);camera.near=Math.max(radius/1000,.001);camera.far=radius*100;camera.updateProjectionMatrix();
  controls.target.copy(center);controls.minDistance=radius*.1;controls.maxDistance=radius*30;controls.update();
  document.querySelectorAll('[data-view]').forEach(button=>button.classList.toggle('active',button.dataset.view===view));invalidate();
}
function cloneMap(source,image,limit){
  const scale=Math.min(1,limit/Math.max(image.width,image.height)),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;map.flipY=source.flipY;map.wrapS=source.wrapS;map.wrapT=source.wrapT;map.channel=source.channel;map.offset.copy(source.offset);map.repeat.copy(source.repeat);map.center.copy(source.center);map.rotation=source.rotation;return map;
}
async function checkedPNG(record,filename,hashKey,sizeKey){
  if(!/^(?:native-color-[0-9]+\.png|\.\.\/\.\.\/shared\/[0-9a-f]{64}\.png)$/.test(filename))throw new Error('展示贴图路径无效');
  const url=new URL(filename,state.source.manifestURL);if(url.origin!==location.origin)throw new Error('展示贴图必须同源');
  const response=await fetch(url);if(!response.ok)throw new Error('高清贴图读取失败：'+response.status);
  const data=await response.arrayBuffer(),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(n=>n.toString(16).padStart(2,'0')).join('');if(hash!==record[hashKey])throw new Error('高清贴图哈希校验失败');
  const bitmap=await createImageBitmap(new Blob([data],{type:'image/png'}),{premultiplyAlpha:'none',colorSpaceConversion:'none'}),size=record[sizeKey];
  if(!size||bitmap.width!==size[0]||bitmap.height!==size[1]){bitmap.close();throw new Error('高清贴图尺寸不匹配');}
  return bitmap;
}
async function quality(){
  if(!renderer||!state.model)return;
  const limit=Number(ui.quality.value),serial=state.serial;ui.quality.disabled=true;
  try{
    if(limit>1024)for(const [material,row] of state.colors){
      const info=material.userData.source;
      if(!info?.native_file||!info.source_size||Math.max(row.image.width,row.image.height)>=Math.min(limit,Math.max(...info.source_size)))continue;
      const image=await checkedPNG(info,info.native_file,'native_sha256','source_size');
      if(serial!==state.serial){image.close();return;}
      if(row.native)row.image.close();row.image=image;row.native=true;
    }
    if(serial!==state.serial)return;
    await reflections.quality(limit);
    for(const [material,row] of state.colors){const previous=material.map;material.map=cloneMap(row.source,row.image,limit);material.needsUpdate=true;if(previous!==row.source)previous.dispose();}
    resize();status(`仅预览 · ${limit===512?'512':limit/1024+'K'} 显示 · 拖动旋转，滚轮拉近`);
  }finally{ui.quality.disabled=false;}
}
async function loadScene(path){
  const serial=++state.serial;ui.loading.hidden=false;ui.empty.hidden=true;
  const base=new URL(path,location.href);if(base.origin!==location.origin)throw new Error('仅加载本站展示场景');
  const response=await fetch(base);if(!response.ok)throw new Error('场景读取失败：'+response.status);
  const manifest=await response.json();if(manifest.schema_version!==1||manifest.model!=='model.glb'||!Array.isArray(manifest.materials))throw new Error('场景清单格式无效');
  const modelURL=new URL(manifest.model,base),modelResponse=await fetch(modelURL);if(!modelResponse.ok)throw new Error('模型读取失败：'+modelResponse.status);
  const data=await modelResponse.arrayBuffer();if(data.byteLength>128*1024*1024)throw new Error('展示模型超过 128 MiB');
  if(manifest.glb_sha256){const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(n=>n.toString(16).padStart(2,'0')).join('');if(hash!==manifest.glb_sha256)throw new Error('展示模型哈希校验失败');}
  const manager=new THREE.LoadingManager();manager.setURLModifier(url=>{if(!url.startsWith('blob:')&&!url.startsWith('data:'))throw new Error('展示模型只能使用内嵌资源');return url;});
  const gltf=await new GLTFLoader(manager).parseAsync(data,'');if(serial!==state.serial)return;
  start();state.model=gltf.scene;state.source={manifestURL:base.href};let triangles=0;
  state.model.traverse(mesh=>{if(!mesh.isMesh)return;if(!mesh.geometry.attributes.normal)mesh.geometry.computeVertexNormals();state.meshes.push(mesh);triangles+=(mesh.geometry.index?.count??mesh.geometry.attributes.position.count)/3;
    for(const material of Array.isArray(mesh.material)?mesh.material:[mesh.material]){
      if(state.materials.includes(material))continue;state.materials.push(material);material.side=THREE.DoubleSide;
      const record=manifest.materials.find(row=>row.name===material.name);if(record)material.userData.source=record;
      if(material.map?.image&&!material.map.isCompressedTexture)state.colors.set(material,{source:material.map,image:material.map.image,native:false});
    }
  });
  if(!state.meshes.length)throw new Error('模型没有可显示的三角面');
  bounds=new THREE.Box3().setFromObject(state.model);radius=bounds.getBoundingSphere(new THREE.Sphere()).radius;if(!Number.isFinite(radius)||radius<=0)throw new Error('模型边界无效');
  scene.add(state.model);ui.modelName.textContent=manifest.label||'涂装模型';document.title=(manifest.label||'涂装')+' · 3D 预览';ui.metrics.textContent=`${state.meshes.length} 个部件 · ${Math.round(triangles).toLocaleString()} 三角面`;
  reflections.accept(state.materials);await quality();fit();ui.loading.hidden=true;ui.capture.disabled=false;
  for(const id of ['reflectionEnabled','reflectionAmount','normalEnabled'])$(id).disabled=false;
  document.querySelectorAll('[data-view]').forEach(button=>{button.disabled=false;});
}
ui.quality.addEventListener('change',()=>quality().catch(fail));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>fit(button.dataset.view)));
ui.capture.addEventListener('click',()=>{
  if(!renderer)return;renderer.render(scene,camera);renderer.domElement.toBlob(blob=>{if(!blob){status('截图失败，请重试',true);return;}const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='模型预览.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
});
window.addEventListener('pagehide',event=>{
  if(event.persisted)return;
  reflections.clear();const textures=new Set(),materials=new Set();
  for(const [material,row] of state.colors){textures.add(row.source);if(row.native)row.image.close();}
  for(const mesh of state.meshes){mesh.geometry.dispose();for(const material of Array.isArray(mesh.material)?mesh.material:[mesh.material]){materials.add(material);for(const value of Object.values(material))if(value?.isTexture)textures.add(value);}}
  textures.forEach(texture=>{texture.dispose();texture.image?.close?.();});materials.forEach(material=>material.dispose());environment?.dispose();controls?.dispose();renderer?.dispose();
});
if(query.has('scene'))loadScene(query.get('scene')).catch(fail);
