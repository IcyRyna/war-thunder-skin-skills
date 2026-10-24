#!/usr/bin/env python3
"""把 AI 的分层涂装方案装配成可由人接手的自包含工程。"""
from __future__ import annotations
import argparse
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys
import uuid

KINDS={'decal','tint','text','shape','brush'}
CATEGORIES={'车身','炮塔','炮管','轮履与悬挂','武器','附加装甲','灯具与观察设备','随车附件','待分类'}


def read_json(path):
    def invalid(value):raise ValueError('JSON 不能包含 '+value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),parse_constant=invalid)


def write_new(path,data):
    path=Path(path)
    if path.exists():raise FileExistsError('输出已存在，请选择新文件：'+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)


def source_scene(path):
    path=Path(path).resolve()
    if path.is_dir():path/='scene.json'
    scene=read_json(path)
    if scene.get('schema_version')!=1 or not scene.get('source_obj_sha256'):raise ValueError('请选择 preview.py 准备出的场景清单')
    return path,scene


def identity(row):
    return {'name':row['name'],'source_sha256':row.get('source_sha256'),'source_size':row.get('source_size'),
            'view_mode':row.get('view_mode','fixed-color-rgb'),'camo_sha256':row.get('camo_sha256')}


def asset_path(root,name):
    if not isinstance(name,str) or not name:raise ValueError('图案需要 file 字段')
    path=(root/name).resolve()
    if not path.is_relative_to(root) or path.suffix.lower()!='.png' or not path.is_file():raise ValueError('图案必须是素材目录内的 PNG：'+name)
    if path.stat().st_size>16*1024*1024:raise ValueError('单个图案超过 16 MiB')
    return path


def png_data(path,convert_rgb=False):
    from PIL import Image
    data=path.read_bytes()
    with Image.open(BytesIO(data)) as image:
        if image.format!='PNG' or max(image.size)>8192:raise ValueError('只支持最大边长 8192 的 PNG')
        size=image.size
        image.load()
        if convert_rgb:
            out=BytesIO();image.convert('RGB').save(out,format='PNG');data=out.getvalue()
    return 'data:image/png;base64,'+base64.b64encode(data).decode(),size,hashlib.sha256(data).hexdigest()


def valid_points(points):
    return isinstance(points,list) and 0<len(points)<=20000 and all(isinstance(p,list) and len(p)==2 and all(type(n) in (int,float) and math.isfinite(n) and 0<=n<=1 for n in p) for p in points)


def prepare_layer(raw,assets_root):
    if raw.get('type') not in KINDS:raise ValueError('不支持的图层类型：'+str(raw.get('type')))
    row={**raw,'id':raw.get('id') or str(uuid.uuid4()),'origin':'ai','manually_adjusted':False,
         'name':raw.get('name') or {'decal':'AI 装饰图','tint':'AI 区域改色','text':'AI 文字','shape':'AI 色块','brush':'AI 修补'}[raw['type']],
         'opacity':raw.get('opacity',1),'visible':raw.get('visible',True),'locked':raw.get('locked',False)}
    if not isinstance(row['name'],str) or not row['name'].strip() or len(row['name'])>120:raise ValueError('图层名称必须在 1–120 字之间')
    if not isinstance(row['id'],str) or not re.fullmatch(r'[-A-Za-z0-9_.:]{1,128}',row['id']):raise ValueError('图层编号无效')
    for key in ('visible','locked','flipX','flipY','bold'):
        if key in row and type(row[key]) is not bool:raise ValueError('图层开关无效')
    for key in ('part_refs','clipParts'):
        if key in row and (not isinstance(row[key],list) or len(row[key])>2000 or any(not isinstance(v,str) or len(v)>=256 for v in row[key])):raise ValueError('图层部件范围无效')
    if type(row['opacity']) not in (int,float) or not math.isfinite(row['opacity']) or not 0<=row['opacity']<=1:raise ValueError('不透明度应在 0–1 之间')
    if row['type'] in {'decal','text','shape'}:
        for key,value in {'x':.5,'y':.5,'rotation':0}.items():row.setdefault(key,value)
        if any(type(row[key]) not in (int,float) or not math.isfinite(row[key]) for key in ('x','y','rotation')) or abs(row['x'])>2 or abs(row['y'])>2 or abs(row['rotation'])>360:raise ValueError('图案位置或角度超出范围')
    if row['type']=='decal':
        path=asset_path(assets_root,row.pop('file',None));row['src'],size,row['asset_sha256']=png_data(path)
        row['asset_name']=path.name;row['asset_size']=list(size);row.setdefault('width',.15)
    if row['type']=='shape':row.setdefault('width',.25);row.setdefault('height',.04)
    if row['type'] in {'decal','shape'}:
        if type(row['width']) not in (int,float) or not 0<row['width']<=2:raise ValueError('宽度应在 0–2 之间')
    if row['type']=='shape' and (type(row['height']) not in (int,float) or not 0<row['height']<=2):raise ValueError('色块高度无效')
    if row['type'] in {'tint','text','shape','brush'}:
        row.setdefault('color','#d6ad41')
        if not isinstance(row['color'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',row['color']):raise ValueError('颜色使用 #RRGGBB')
    if row['type']=='text':
        row.setdefault('text','涂装标识');row.setdefault('font','Microsoft YaHei');row.setdefault('fontSize',.04)
        if not isinstance(row['text'],str) or not row['text'].strip() or len(row['text'])>500 or row['font'] not in {'Microsoft YaHei','Arial','sans-serif','serif','monospace'} or type(row['fontSize']) not in (int,float) or not 0<row['fontSize']<=1:raise ValueError('文字内容、字体或字号无效')
    if row['type']=='tint':
        row.setdefault('blend','color')
        if row['blend'] not in {'color','source-over','multiply'} or (row.get('points') is not None and (not valid_points(row['points']) or not 3<=len(row['points'])<=1024)) or (not row.get('clipParts') and not row.get('points')):raise ValueError('区域改色需要多边形 points 或 clipParts')
    for key in ('strokes','erasures'):
        if key in row:
            if not isinstance(row[key],list) or len(row[key])>1024:raise ValueError('笔刷记录过多')
            for stroke in row[key]:
                if not valid_points(stroke.get('points')) or type(stroke.get('width')) not in (int,float) or not 0<stroke['width']<=1:raise ValueError('笔刷轨迹或宽度无效')
                if stroke.get('color') is not None and (not isinstance(stroke['color'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',stroke['color'])):raise ValueError('笔刷颜色无效')
    if row['type']=='brush':row.setdefault('strokes',[])
    return row


def build(scene_path,plan_path,out,assets_root=None):
    scene_path,scene=source_scene(scene_path);plan_path=Path(plan_path).resolve();plan=read_json(plan_path)
    if plan.get('kind')!='wt-paint-plan' or plan.get('schema_version')!=1:raise ValueError('方案应使用 wt-paint-plan 格式')
    if plan.get('model')!=scene['source_obj_sha256']:raise ValueError('AI 方案与场景模型不匹配')
    root=Path(assets_root).resolve() if assets_root else plan_path.parent
    entries=plan.get('materials',[])
    if not isinstance(entries,list) or len(entries)>64:raise ValueError('贴图数量无效')
    materials=[];names=set()
    for entry in entries:
        if not entry.get('layers'):continue
        if entry['name'] in names:raise ValueError('同一张贴图重复出现')
        names.add(entry['name']);source=next((r for r in scene['materials'] if r['name']==entry['name']),None)
        if not source:raise ValueError('模型没有这张贴图：'+entry['name'])
        if len(entry['layers'])>64:raise ValueError('单张贴图最多 64 层')
        override=entry.get('base_file')
        if override:base,size,base_sha=png_data(asset_path(root,override),True)
        else:
            if source.get('source_quality')=='thumbnail-only':raise ValueError('这张贴图只有缩略级，请提供原尺寸 base_file：'+entry['name'])
            name=source.get('native_file','')
            if not re.fullmatch(r'native-color-\d+\.png',name):raise ValueError('场景没有可编辑原图')
            path=scene_path.parent/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=source.get('native_sha256'):raise ValueError('场景原图哈希变化')
            base,size,base_sha=png_data(path)
        long_edge=entry.get('long_edge',plan.get('long_edge',4096))
        if long_edge not in (0,512,1024,2048,4096):raise ValueError('分辨率应为 0/512/1024/2048/4096')
        width,height=size;scale=long_edge/max(size) if long_edge else 1
        layers=[prepare_layer(layer,root) for layer in entry['layers']]
        if len({r['id'] for r in layers})!=len(layers):raise ValueError('图层编号重复')
        materials.append({'name':source['name'],'identity':identity(source),'native_width':width,'native_height':height,
                          'width':max(1,round(width*scale)),'height':max(1,round(height*scale)),'long_edge':long_edge,
                          'base':base,'base_png_sha256':base_sha,'layers':layers})
    parts={}
    for key,row in plan.get('parts',{}).items():
        if row.get('category') not in CATEGORIES or not isinstance(row.get('label'),str) or not 0<len(row['label'])<=80:raise ValueError('部件分类建议无效')
        parts[key]={'label':row['label'],'category':row['category'],'confirmed':False}
    if not materials and not parts:raise ValueError('方案中没有图层或部件分类建议')
    project={'schema_version':2,'kind':'wt-web-creative','producer':'ai','model':scene['source_obj_sha256'],
             'parts':parts,'materials':materials,'output':'RGB color PNG; C alpha/N/AO unchanged','game':'not_run'}
    write_new(out,project)
    return {'ok':True,'materials':len(materials),'layers':sum(len(row['layers']) for row in materials),'output':str(Path(out).resolve())}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    template=sub.add_parser('template',help='列出模型可用贴图，生成可填写的 AI 方案');template.add_argument('--scene',type=Path,required=True);template.add_argument('--out',type=Path,required=True)
    builder=sub.add_parser('build',help='把 AI 的图层、PNG 素材和原图装成可编辑工程');builder.add_argument('--scene',type=Path,required=True);builder.add_argument('--plan',type=Path,required=True);builder.add_argument('--out',type=Path,required=True);builder.add_argument('--assets-root',type=Path)
    a=p.parse_args()
    try:
        if a.command=='template':
            _,scene=source_scene(a.scene);write_new(a.out,{'schema_version':1,'kind':'wt-paint-plan','model':scene['source_obj_sha256'],'long_edge':4096,'parts':{},'materials':[{'name':row['name'],'layers':[]} for row in scene['materials'] if row.get('native_file') and row.get('source_quality')!='thumbnail-only']});print(json.dumps({'ok':True,'output':str(a.out)},ensure_ascii=False))
        else:print(json.dumps(build(a.scene,a.plan,a.out,a.assets_root),ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
