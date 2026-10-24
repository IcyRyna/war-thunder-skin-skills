import * as THREE from 'three';

// A small generated studio environment: no HDR download, renderer stays on demand.
export function studioEnvironment(renderer){
  const room=new THREE.Scene();room.background=new THREE.Color(.35,.37,.4);
  const geometry=new THREE.BoxGeometry(1,1,1);
  const wall=new THREE.MeshBasicMaterial({color:0x6d7480,side:THREE.BackSide});
  const box=new THREE.Mesh(geometry,wall);box.scale.set(20,14,20);room.add(box);
  const materials=[wall];
  for(const [position,scale,intensity] of [[[0,6,0],[8,.1,6],4],[[7,2,1],[.1,6,4],2.5],[[-7,1,-2],[.1,5,7],1.8]]){
    const material=new THREE.MeshBasicMaterial({color:new THREE.Color(intensity,intensity,intensity)});materials.push(material);
    const panel=new THREE.Mesh(geometry,material);panel.position.set(...position);panel.scale.set(...scale);room.add(panel);
  }
  const generator=new THREE.PMREMGenerator(renderer);const target=generator.fromScene(room,.04);generator.dispose();geometry.dispose();materials.forEach(m=>m.dispose());return target;
}

export function createReflection({enabled,amount,detail,summary,invalidate,source}){
  let rows=[],serial=0;
  function draw(limit){
    for(const row of rows){
      const active=enabled.checked;
      for(const key of ['roughnessMap','metalnessMap','normalMap']){
        const original=row.maps[key];const image=original?.image;
        if(!original||!image){row.material[key]=null;continue;}
        let map=row.display.get(original);
        if(!map||map.userData.limit!==limit){
          map?.dispose();const scale=Math.min(1,limit/Math.max(image.width,image.height));
          const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
          map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.NoColorSpace;map.flipY=original.flipY;map.wrapS=original.wrapS;map.wrapT=original.wrapT;map.userData.limit=limit;row.display.set(original,map);
        }
        row.material[key]=active&&(key!=='normalMap'||detail.checked)?map:null;
      }
      row.material.roughness=active?row.roughness:.85;row.material.metalness=active?row.metalness:0;
      row.material.envMapIntensity=active?Number(amount.value):0;row.material.needsUpdate=true;
    }
    summary.textContent=rows.length?`已读取 ${rows.filter(r=>r.info?.reflection).length} 个材质的反射贴图 · ${enabled.checked?'反射已开启':'反射已关闭'}`:'打开模型后读取反射贴图';
    summary.dataset.bound=String(rows.filter(r=>r.info?.reflection).length);summary.dataset.enabled=String(enabled.checked);summary.dataset.textureEdge=String(Math.max(0,...rows.map(r=>Math.max(r.material.roughnessMap?.image?.width||0,r.material.roughnessMap?.image?.height||0))));invalidate();
  }
  let quality=1024;
  for(const control of [enabled,amount,detail])control.addEventListener('input',()=>draw(quality));
  return {
    accept(materials){serial++;rows=materials.filter(m=>m.isMeshStandardMaterial).map(material=>{const maps={roughnessMap:material.roughnessMap,metalnessMap:material.metalnessMap,normalMap:material.normalMap};return {material,info:material.userData?.source,roughness:material.roughness,metalness:material.metalness,maps:{...maps},originalMaps:maps,display:new Map()};});draw(quality);},
    async quality(limit){
      quality=limit;const current=serial;
      if(limit>1024&&source()?.manifestURL)for(const row of rows){
        for(const [channel,keys] of [['orm',['roughnessMap','metalnessMap']],['normal',['normalMap']]]){
          const record=row.info?.reflection?.[channel];const previous=row.maps[keys[0]];
          if(!record||!previous||Math.max(previous.image.width,previous.image.height)>=Math.min(limit,Math.max(...record.size)))continue;
          if(!/^(?:native-(?:orm|normal)-[0-9]+\.png|\.\.\/\.\.\/shared\/[0-9a-f]{64}\.png)$/.test(record.file))throw new Error('反射贴图路径无效');
          const url=new URL(record.file,source().manifestURL);if(url.origin!==location.origin)throw new Error('反射贴图必须同源');
          const response=await fetch(url);if(!response.ok)throw new Error('反射贴图读取失败：'+response.status);
          const data=await response.arrayBuffer();const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(n=>n.toString(16).padStart(2,'0')).join('');if(hash!==record.sha256)throw new Error('反射贴图校验失败');
          const bitmap=await createImageBitmap(new Blob([data],{type:'image/png'}),{colorSpaceConversion:'none',premultiplyAlpha:'none'});
          if(current!==serial){bitmap.close();return;}
          if(bitmap.width!==record.size[0]||bitmap.height!==record.size[1]){bitmap.close();throw new Error('反射贴图尺寸不匹配');}
          const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;canvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();
          const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.NoColorSpace;texture.flipY=previous.flipY;texture.wrapS=previous.wrapS;texture.wrapT=previous.wrapT;
          row.display.get(previous)?.dispose();row.display.delete(previous);
          for(const key of keys)row.maps[key]=texture;
          // Original embedded maps remain owned by model disposal; new maps are freed in clear().
          row.native??=new Set();row.native.add(texture);
        }
      }
      if(current===serial)draw(limit);
    },
    clear(){serial++;for(const row of rows){for(const map of row.display.values())map.dispose();for(const map of row.native||[])map.dispose();for(const [key,map] of Object.entries(row.originalMaps))row.material[key]=map;}rows=[];}
  };
}
