export const ORIGINS={ai:'AI 添加',manual:'手动添加',imported:'来源未注明'};
export const TYPES={decal:'贴上的图案',tint:'区域改色',text:'文字标识',shape:'色块与条带',brush:'手绘修补'};
export const FONTS=['Microsoft YaHei','Arial','sans-serif','serif','monospace'];
export const BLENDS=['source-over','color','multiply'];
const finite=n=>typeof n==='number'&&Number.isFinite(n);

export function canvasSize(width,height,longEdge=0) {
  if(![width,height].every(n=>Number.isInteger(n)&&n>0&&n<=8192)||![0,512,1024,2048,4096].includes(longEdge))throw new Error('画布分辨率无效');
  const scale=longEdge?longEdge/Math.max(width,height):1;
  return {width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))};
}
export function cloneLayers(layers) {return layers.map(row=>({...row,points:row.points?.map(p=>[...p]),clipParts:row.clipParts?[...row.clipParts]:undefined,
  strokes:row.strokes?.map(s=>({...s,points:s.points.map(p=>[...p])})),erasures:row.erasures?.map(s=>({...s,points:s.points.map(p=>[...p])}))}));}
export function serializeLayers(layers) {return layers.map(({image,alphaImage,...row})=>row);}
export function wrapUV({u,v}){return [((u%1)+1)%1,1-((v%1)+1)%1];}
export function pointInPolygon(point,polygon){let inside=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){const a=polygon[i],b=polygon[j];if((a[1]>point[1])!==(b[1]>point[1])&&point[0]<(b[0]-a[0])*(point[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside;}
function distanceToSegment(p,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);}
export function hitsStroke(stroke,point,w,h){const p=[point[0]*w,point[1]*h],r=stroke.width*w/2;const pts=stroke.points.map(v=>[v[0]*w,v[1]*h]);return pts.length===1?Math.hypot(p[0]-pts[0][0],p[1]-pts[0][1])<=r:pts.slice(1).some((b,i)=>distanceToSegment(p,pts[i],b)<=r);}

export function layerGeometry(row,width,height){
  let w=row.width*width,h;
  if(row.type==='decal')h=w*row.image.height/row.image.width;
  else if(row.type==='text'){w=Math.max(row.fontSize*width*.6,row.fontSize*width*Math.max(...row.text.split('\n').map(s=>[...s].length)));h=row.fontSize*width*row.text.split('\n').length*1.25;}
  else h=row.height*height;
  return {x:row.x*width,y:row.y*height,width:w,height:h,rotation:(row.rotation||0)*Math.PI/180};
}
export function hitLayer(row,point,width,height,alphaSample=()=>255,clipContains=()=>true){
  if(row.visible===false||row.opacity<=0||row.locked||!clipContains(row,point))return false;
  if(row.erasures?.some(s=>hitsStroke(s,point,width,height)))return false;
  if(row.type==='tint')return row.points?pointInPolygon(point,row.points):true;
  if(row.type==='brush')return row.strokes.some(s=>hitsStroke(s,point,width,height));
  const g=layerGeometry(row,width,height),dx=point[0]*width-g.x,dy=point[1]*height-g.y;
  let x=dx*Math.cos(g.rotation)+dy*Math.sin(g.rotation),y=-dx*Math.sin(g.rotation)+dy*Math.cos(g.rotation);
  if(row.flipX)x=-x;if(row.flipY)y=-y;
  if(Math.abs(x)>g.width/2||Math.abs(y)>g.height/2)return false;
  return row.type!=='decal'||alphaSample(row,(x/g.width+.5),(y/g.height+.5))*row.opacity>8;
}

function strokePath(ctx,stroke,w,h){const pts=stroke.points;if(!pts.length)return;ctx.lineWidth=stroke.width*w;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();ctx.moveTo(pts[0][0]*w,pts[0][1]*h);if(pts.length===1){ctx.arc(pts[0][0]*w,pts[0][1]*h,stroke.width*w/2,0,Math.PI*2);ctx.fill();}else{for(const p of pts.slice(1))ctx.lineTo(p[0]*w,p[1]*h);ctx.stroke();}}
export function renderDocument(doc,canvas,scratch,resolveClip=()=>[]){
  const w=canvas.width,h=canvas.height,ctx=canvas.getContext('2d');
  ctx.setTransform(1,0,0,1,0,0);ctx.globalCompositeOperation='source-over';ctx.globalAlpha=1;ctx.clearRect(0,0,w,h);ctx.drawImage(doc.sourceBase,0,0,w,h);
  if(scratch.width!==w)scratch.width=w;if(scratch.height!==h)scratch.height=h;
  const s=scratch.getContext('2d');
  for(const row of doc.layers){
    if(row.visible===false||row.opacity<=0)continue;
    s.setTransform(1,0,0,1,0,0);s.globalAlpha=1;s.globalCompositeOperation='source-over';s.clearRect(0,0,w,h);s.save();
    if(row.clipParts?.length){const polys=resolveClip(row.clipParts,doc.materialName);if(!polys.length){s.restore();continue;}s.beginPath();for(const p of polys){s.moveTo(p[0][0]*w,p[0][1]*h);for(const v of p.slice(1))s.lineTo(v[0]*w,v[1]*h);s.closePath();}s.clip();}
    if(row.type==='tint'){
      s.fillStyle=row.color;if(row.points){s.beginPath();row.points.forEach((p,i)=>i?s.lineTo(p[0]*w,p[1]*h):s.moveTo(p[0]*w,p[1]*h));s.closePath();s.fill();}else s.fillRect(0,0,w,h);
    }else if(row.type==='brush'){
      for(const stroke of row.strokes){s.strokeStyle=s.fillStyle=stroke.color||row.color;strokePath(s,stroke,w,h);}
    }else{
      const g=layerGeometry(row,w,h);s.translate(g.x,g.y);s.rotate(g.rotation);s.scale(row.flipX?-1:1,row.flipY?-1:1);
      if(row.type==='decal')s.drawImage(row.image,-g.width/2,-g.height/2,g.width,g.height);
      else if(row.type==='shape'){s.fillStyle=row.color;s.fillRect(-g.width/2,-g.height/2,g.width,g.height);}
      else {s.fillStyle=row.color;s.font=`${row.bold?'700':'400'} ${row.fontSize*w}px "${row.font}"`;s.textAlign='center';s.textBaseline='middle';const lines=row.text.split('\n'),lineHeight=row.fontSize*w*1.25;lines.forEach((line,i)=>s.fillText(line,0,(i-(lines.length-1)/2)*lineHeight));}
    }
    s.restore();
    if(row.erasures?.length){s.save();s.globalCompositeOperation='destination-out';s.fillStyle=s.strokeStyle='#000';for(const stroke of row.erasures)strokePath(s,stroke,w,h);s.restore();}
    ctx.save();ctx.globalAlpha=row.opacity;ctx.globalCompositeOperation=row.type==='tint'?row.blend:'source-over';ctx.drawImage(scratch,0,0);ctx.restore();
  }
  return canvas;
}

function validatePoints(points,max=20000){return Array.isArray(points)&&points.length>0&&points.length<=max&&points.every(p=>Array.isArray(p)&&p.length===2&&p.every(n=>finite(n)&&n>=0&&n<=1));}
function validateStrokes(strokes){if(!Array.isArray(strokes)||strokes.length>1024)throw new Error('笔刷记录过多');let total=0;for(const s of strokes){total+=s.points?.length||0;if(!finite(s.width)||s.width<=0||s.width>1||!validatePoints(s.points)||s.color&&!/^#[0-9a-f]{6}$/i.test(s.color))throw new Error('笔刷记录无效');}if(total>200000)throw new Error('笔刷点数超过限制');}
export function validateLayer(row){
  if(!row||!Object.hasOwn(TYPES,row.type)||typeof row.id!=='string'||!/^[-A-Za-z0-9_.:]{1,128}$/.test(row.id)||typeof row.name!=='string'||!row.name.trim()||row.name.length>120||!finite(row.opacity)||row.opacity<0||row.opacity>1)throw new Error('图层基本信息无效');
  if(!Object.hasOwn(ORIGINS,row.origin||'imported'))throw new Error('图层来源标记无效');
  for(const key of ['clipParts','part_refs'])if(row[key]&&(!Array.isArray(row[key])||row[key].length>2000||!row[key].every(p=>typeof p==='string'&&p.length<256)))throw new Error('图层部件范围无效');
  for(const key of ['visible','locked','flipX','flipY','bold','manually_adjusted'])if(row[key]!==undefined&&typeof row[key]!=='boolean')throw new Error('图层开关无效');
  if(row.erasures)validateStrokes(row.erasures);
  if(['decal','text','shape'].includes(row.type)){
    if(![row.x,row.y,row.rotation].every(finite)||Math.abs(row.x)>2||Math.abs(row.y)>2||Math.abs(row.rotation)>360)throw new Error('图层位置或角度超出范围');
    if(row.type!=='text'&&(!finite(row.width)||row.width<=0||row.width>2))throw new Error('图层宽度无效');
  }
  if(['tint','text','shape','brush'].includes(row.type)&&!/^#[0-9a-f]{6}$/i.test(row.color))throw new Error('图层颜色无效');
  if(row.type==='tint'){if(!BLENDS.includes(row.blend)||(row.points?(!validatePoints(row.points,1024)||row.points.length<3):!row.clipParts?.length))throw new Error('调色范围无效');}
  if(row.type==='shape'&&(!finite(row.height)||row.height<=0||row.height>2))throw new Error('色块高度无效');
  if(row.type==='text'&&(typeof row.text!=='string'||!row.text.trim()||row.text.length>500||!FONTS.includes(row.font)||!finite(row.fontSize)||row.fontSize<=0||row.fontSize>1))throw new Error('文字设置无效');
  if(row.type==='brush')validateStrokes(row.strokes);
  if(row.type==='decal'&&(typeof row.src!=='string'||!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(row.src)))throw new Error('图案必须是内嵌 PNG');
  return row;
}
