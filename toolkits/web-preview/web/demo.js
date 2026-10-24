import * as THREE from 'three';

// Original procedural demo, deliberately separate from War Thunder resources.
export function makeDemo(){
  const model=new THREE.Group();
  function paint(name,color,stripe=false){
    const canvas=document.createElement('canvas');canvas.width=canvas.height=512;
    const c=canvas.getContext('2d');c.fillStyle=color;c.fillRect(0,0,512,512);
    c.strokeStyle='rgba(255,255,255,.1)';c.lineWidth=2;
    for(let p=0;p<=512;p+=64){c.beginPath();c.moveTo(p,0);c.lineTo(p,512);c.moveTo(0,p);c.lineTo(512,p);c.stroke();}
    if(stripe){c.fillStyle='#dfb842';c.fillRect(0,180,512,48);c.fillStyle='#f3f1e7';c.font='bold 60px sans-serif';c.fillText('DEMO',150,345);}
    const map=new THREE.CanvasTexture(canvas);map.flipY=false;map.colorSpace=THREE.SRGBColorSpace;
    const material=new THREE.MeshStandardMaterial({name,map,roughness:.8,metalness:.1});
    return material;
  }
  const body=paint('demo_body','#53604f',true),turret=paint('demo_turret','#bcc0b4',true),gun=paint('demo_gun','#4c5850'),rubber=paint('demo_track','#303632');
  function mesh(name,geometry,material,position,rotation=null){const m=new THREE.Mesh(geometry,material);m.name=name;m.position.set(...position);if(rotation)m.rotation.set(...rotation);model.add(m);return m;}
  const box=(name,size,mat,pos)=>mesh(name,new THREE.BoxGeometry(...size),mat,pos);
  box('root',[3,1.1,6.2],body,[0,1.15,0]);
  box('turret',[2.25,.8,2.5],turret,[0,2.1,-.25]);
  box('turret_hatch',[.75,.15,.8],gun,[.4,2.57,-.2]);
  mesh('gun_barrel',new THREE.CylinderGeometry(.13,.18,3.8,16),gun,[0,2.15,-3.15],[Math.PI/2,0,0]);
  for(const side of [-1,1]){
    const suffix=side<0?'l':'r';
    box('track_'+suffix,[.5,.28,5.7],rubber,[side*1.55,.25,0]);
    box('ex_armor_'+suffix,[.16,.65,5.4],body,[side*1.77,1.3,0]);
    for(let i=0;i<6;i++)mesh(`wheel_${suffix}_${i+1}`,new THREE.CylinderGeometry(.48,.48,.38,20),rubber,[side*1.55,.68,-2.3+i*.92],[0,0,Math.PI/2]);
  }
  return model;
}
