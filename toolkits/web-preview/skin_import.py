#!/usr/bin/env python3
"""只读导入战雷涂装 ZIP／文件夹，按实际资源索引识别并提取模型。"""
from __future__ import annotations
import argparse
import contextlib
import fnmatch
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
ALLOWED={'.blk','.dds','.tga','.png','.zip','.grp'}
MAX_FILES=1024
MAX_UNPACKED=1024*1024*1024


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.partial');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def progress(path,stage,message):
    if path:write_json(path,{'stage':stage,'message':message})


def safe_relative(name):
    portable=name.replace('\\','/');parts=portable.split('/');win=PureWindowsPath(name)
    if not portable or win.drive or win.root or portable.startswith('/') or any(p in {'','..','.'} or ':' in p or p.endswith((' ','.')) for p in parts):raise ValueError('压缩包路径不安全：'+name)
    if any(p.split('.')[0].casefold() in {'con','prn','aux','nul',*[f'com{i}' for i in range(1,10)],*[f'lpt{i}' for i in range(1,10)]} for p in parts):raise ValueError('压缩包含 Windows 保留名称')
    if len(portable)>1000:raise ValueError('压缩包路径过长')
    return Path(*parts)


def unpack_zip(source,out):
    if out.exists():raise FileExistsError('解包输出必须是新目录')
    records=[];seen=set();total=0
    with zipfile.ZipFile(source) as archive:
        members=[entry for entry in archive.infolist() if not entry.is_dir()]
        if len(members)>MAX_FILES:raise ValueError('压缩包文件数超过 1024')
        for entry in members:
            relative=safe_relative(entry.filename);key=relative.as_posix().casefold()
            if key in seen:raise ValueError('压缩包含重名或仅大小写不同的文件')
            seen.add(key)
            mode=entry.external_attr>>16
            if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (stat.S_IFREG,0):raise ValueError('压缩包不能包含链接或特殊文件')
            if entry.flag_bits&1:raise ValueError('暂不支持加密压缩包，请先解密')
            total+=entry.file_size
            if total>MAX_UNPACKED:raise ValueError('解包数据超过 1 GiB，请只选一套涂装')
            if relative.suffix.casefold() not in ALLOWED:continue
            records.append((entry,relative))
        out.mkdir(parents=True)
        for entry,relative in records:
            target=out/relative;target.parent.mkdir(parents=True,exist_ok=True);written=0
            with archive.open(entry) as src,target.open('xb') as dst:
                for block in iter(lambda:src.read(1048576),b''):
                    written+=len(block)
                    if written>entry.file_size or written>MAX_UNPACKED:raise ValueError('解包数据与目录声明不一致')
                    dst.write(block)
            if written!=entry.file_size:raise ValueError('压缩成员不完整')
    return len(records)


def copy_folder(source,out):
    source=source.resolve();out=out.resolve()
    if out==source or out.is_relative_to(source):raise ValueError('导入输出不能放在原涂装文件夹里面')
    if out.exists():raise FileExistsError('导入输出必须是新目录')
    files=[];total=0
    for folder,dirs,names in os.walk(source,followlinks=False):
        for name in [*dirs,*names]:
            path=Path(folder)/name;meta=path.lstat()
            if stat.S_ISLNK(meta.st_mode) or getattr(meta,'st_file_attributes',0)&0x400:raise ValueError('涂装文件夹不能通过链接指向其它目录')
        for name in names:
            path=Path(folder)/name
            if path.suffix.lower() not in ALLOWED:continue
            total+=path.stat().st_size;files.append(path)
            if len(files)>MAX_FILES or total>MAX_UNPACKED:raise ValueError('涂装文件夹超过文件数或大小限制')
    out.mkdir(parents=True)
    for path in files:
        target=out/safe_relative(path.relative_to(source).as_posix());target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    return len(files)


def blk_rules(path):
    data=Path(path).read_bytes()
    if len(data)>1024*1024:raise ValueError('涂装配置超过 1 MiB')
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:text=data.decode('gb18030')
    pattern=re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\\r\n])*"|[{}=]|[A-Za-z_][A-Za-z0-9_:.\-]*|[-+0-9.eE]+')
    tokens=[];position=0
    for match in pattern.finditer(text):
        if text[position:match.start()].strip():raise ValueError('涂装配置含不支持的语法')
        position=match.end();value=match.group()
        if value.isspace() or value.startswith('//') or value.startswith('/*'):continue
        tokens.append(value)
    if text[position:].strip() or len(tokens)>50000:raise ValueError('涂装配置格式无效')
    cursor=0
    def parse(depth=0):
        nonlocal cursor
        if depth>20:raise ValueError('涂装配置嵌套过深')
        entries=[]
        while cursor<len(tokens) and tokens[cursor]!='}':
            name=tokens[cursor];cursor+=1
            if cursor>=len(tokens):raise ValueError('涂装配置缺少值或大括号')
            token=tokens[cursor];cursor+=1
            if token=='{':
                children=parse(depth+1)
                if cursor>=len(tokens) or tokens[cursor]!='}':raise ValueError('涂装配置括号未闭合')
                cursor+=1;entries.append((name,children))
            elif token=='=':
                if cursor>=len(tokens):raise ValueError('涂装配置缺少字段值')
                value=tokens[cursor];cursor+=1
                if value.startswith('"'):value=re.sub(r'\\(["\\])',r'\1',value[1:-1])
                entries.append((name,value))
            else:raise ValueError('涂装配置只支持字段和块，不执行 include 或脚本')
        return entries
    document=parse()
    if cursor!=len(tokens):raise ValueError('涂装配置有多余括号')
    rules=[]
    for kind,children in document:
        if kind not in ('replace_tex','set_tex'):continue
        if not isinstance(children,list):raise ValueError('纹理替换块格式无效')
        fields=dict(children)
        if not isinstance(fields.get('from:t'),str) or not isinstance(fields.get('to:t'),str):raise ValueError('纹理替换块缺少 from/to')
        rules.append({'kind':kind,'from':fields['from:t'],'to':fields['to:t'],'param':fields.get('param:t')})
    if not rules:raise ValueError('配置里没有可读取的纹理替换关系')
    return rules


def canonical(value):
    value=Path(value).stem.lower()
    value=re.sub(r'^(?:template_|user_)','',value)
    value=re.sub(r'^(?:germ|ger|cn|china|ussr|us|usa|uk|fr|it|jp|sw|il|israel)_','',value)
    value=re.sub(r'_(?:dds|tga)$','',value)
    return value


def choose_models(blk,rules,catalog):
    filename=canonical(blk.name);scores={}
    for row in catalog:
        model=row['name'];normal=canonical(model);score=0;reason=[]
        if filename==normal:score=1000;reason.append('配置文件车型名与游戏模型索引一致')
        elif filename.replace('_','')==normal.replace('_',''):score=900;reason.append('车型标识一致，分隔符不同')
        for rule in rules:
            resource=rule['from'].rstrip('*').lower()
            if resource.startswith(model.lower()+'_') or canonical(resource).startswith(normal+'_'):score+=40;reason.append('纹理资源前缀匹配')
        if score:scores[model]={**row,'score':score,'reason':list(dict.fromkeys(reason))}
    ranked=sorted(scores.values(),key=lambda r:(-r['score'],r['name']))
    if not ranked:return [],None
    filename_matches=[r for r in ranked if any('配置文件' in reason or '车型标识' in reason for reason in r['reason'])]
    if len(filename_matches)==1:return ranked,filename_matches[0]['name']
    top=ranked[0];family=canonical(top['name'])
    variants=[row for row in catalog if canonical(row['name']).startswith(family) and row['name'] not in scores]
    if variants:
        ranked += [{**row,'score':top['score']-1,'reason':['同家族子型号，不能只凭共用纹理排除']} for row in variants]
    return ranked,top['name'] if len(ranked)==1 else None


def catalog_models(game,extractor):
    sys.path.insert(0,str(Path(extractor).resolve().parent))
    from wt_assets import game_packs
    from archives import GrpArchive
    found={};errors=[]
    for pack in game_packs(game):
        try:
            for entry in GrpArchive(pack).entries:
                if entry.class_id==0xB4B7D9C4:found.setdefault(entry.name,{'name':entry.name,'pack':str(pack)})
        except (OSError,ValueError) as error:errors.append({'pack':str(pack),'error':str(error)})
    if not found:raise ValueError('游戏目录中没有读取到模型资源索引')
    return list(found.values()),errors


def scan(source,out,game,extractor,blk=None,progress_file=None):
    source=Path(source).resolve();out=Path(out).resolve();game=Path(game).resolve()
    if out==game or out.is_relative_to(game):raise ValueError('输出不能在战雷游戏目录内')
    if out.exists():raise FileExistsError('扫描输出必须是新目录')
    progress(progress_file,'unpacking','正在读取涂装配置和贴图…')
    skin=out/'skin'
    count=copy_folder(source,skin) if source.is_dir() else unpack_zip(source,skin)
    configs=sorted(skin.rglob('*.blk'))+sorted(p for p in skin.rglob('*.BLK') if p not in skin.rglob('*.blk'))
    configs=list(dict.fromkeys(configs))
    if len(configs)>32:raise ValueError('包内涂装配置超过 32 套，请只选择一套涂装文件夹')
    if not configs:
        nested=list(skin.rglob('*.zip'))
        if len(nested)==1:
            unpack_zip(nested[0],out/'nested');skin=out/'nested';configs=sorted(skin.rglob('*.blk'))
    if not configs:raise ValueError('没有找到涂装 .blk 配置；请导入游戏用涂装包，而不是只有宣传图的包')
    if blk:
        selected=(skin/blk).resolve()
        if not selected.is_relative_to(skin) or selected not in configs:raise ValueError('指定的配置不在涂装包内')
    else:selected=configs[0] if len(configs)==1 else None
    progress(progress_file,'indexing','正在查找本机战雷文件夹里的真实车型索引…')
    catalog,errors=catalog_models(game,extractor)
    from archives import GrpArchive
    bundled={}
    for pack in skin.rglob('*.grp'):
        for entry in GrpArchive(pack).entries:
            if entry.class_id==0xB4B7D9C4:
                if entry.name in bundled:raise ValueError('包内有多个同名车型模型，需要先保留一套配套模型')
                bundled[entry.name]=pack
    for row in catalog:
        if row['name'] in bundled:row.update(bundled_pack=str(bundled[row['name']]),model_origin='package')
    known={row['name'] for row in catalog}
    catalog.extend({'name':name,'pack':str(pack),'bundled_pack':str(pack),'model_origin':'package'} for name,pack in bundled.items() if name not in known)
    options=[]
    for path in configs:
        rules=blk_rules(path)
        for rule in rules:
            target=(path.parent/rule['to'].replace('\\','/')).resolve()
            if not target.is_relative_to(skin) or not target.is_file() or target.suffix.lower() not in {'.dds','.tga','.png'}:raise ValueError('配置引用的贴图缺失或越界：'+rule['to'])
        candidates,automatic=choose_models(path,rules,catalog)
        options.append({'blk':path.relative_to(skin).as_posix(),'rules':rules,'candidates':candidates,'automatic_vehicle':automatic})
    manifest={'schema_version':1,'input':str(source),'input_sha256':sha(source) if source.is_file() else None,'skin_root':str(skin),'files':count,
              'game_dir':str(game),'extractor':str(Path(extractor).resolve()),'configs':options,'selected_blk':selected.relative_to(skin).as_posix() if selected else None,'index_errors':errors}
    write_json(out/'discovery.json',manifest)
    return out/'discovery.json',manifest


def matching_rule(rules,resource,kind=None):
    selected=None
    for rule in rules:
        if (kind is None or rule['kind']==kind) and fnmatch.fnmatchcase(resource.rstrip('*').lower(),rule['from'].lower()):selected=rule
    return selected


def build(discovery,out,vehicle=None,blk=None,lod=1,progress_file=None):
    from PIL import Image,ImageStat
    import preview
    data=read_json(discovery);skin=Path(data['skin_root']);config=next((r for r in data['configs'] if r['blk']==(blk or data.get('selected_blk'))),None)
    if not config:raise ValueError('需要先选择包里哪一套涂装')
    vehicle=vehicle or config['automatic_vehicle'];choice=next((r for r in config['candidates'] if r['name']==vehicle),None)
    if not choice:raise ValueError('需要确认车型；只允许选择实际游戏索引中的候选')
    out=Path(out).resolve()
    if out.exists():raise FileExistsError('模型准备输出必须是新目录')
    if out.is_relative_to(Path(data['game_dir'])):raise ValueError('输出不能在游戏目录内')
    out.mkdir(parents=True);extractor=Path(data['extractor']);sys.path.insert(0,str(extractor.parent));sys.path.insert(0,str(ROOT/'tools'))
    progress(progress_file,'extracting','已识别 '+vehicle+'，正在从游戏文件夹提取模型…')
    import wt_assets
    model_dir=out/'model';model_dir.mkdir()
    model_pack=Path(choice['pack']);model_origin='game-folder'
    if choice.get('bundled_pack'):
        model_origin='package';model_source=out/'model-source/content/base/res';(model_source/'tanks').mkdir(parents=True)
        model_pack=model_source/'tanks'/Path(choice['bundled_pack']).name;shutil.copyfile(choice['bundled_pack'],model_pack)
        game=Path(data['game_dir'])
        for relative in ['content/base/res/dynModelDesc.bin','patch/content/base/res/dynModelDesc.bin']:
            path=game/relative
            if path.is_file():
                target=out/'model-source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    with (out/'model-extraction.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        wt_assets.export_model(model_pack,vehicle,lod,model_dir,'*',None)
    progress(progress_file,'textures','正在读取原车材质与颜色底图…')
    spec=importlib.util.spec_from_file_location('import_auto_textures',ROOT/'tools/auto_textures.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    old_argv=sys.argv
    with (out/'texture-extraction.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:sys.argv=[str(ROOT/'tools/auto_textures.py'),'--extractor',str(extractor),'--client',data['game_dir'],'--model-dir',str(model_dir),'--out',str(out/'stock-colors')];helper.main()
        finally:sys.argv=old_argv
    stock_bind=out/'stock-colors/bindings.json';preview.prepare(model_dir,out/'stock-scene',stock_bind,1024)
    stock=read_json(out/'stock-scene/scene.json');materials=read_json(model_dir/'materials.json')['materials'];used={r['name'] for r in stock['materials']};rules=config['rules'];config_dir=skin/Path(config['blk']).parent
    binding={'materials':{},'source_quality':{}};report=[];warnings=[];baked=out/'imported-colors';baked.mkdir()
    progress(progress_file,'binding','正在把导入涂装绑定到实际材质槽…')
    unique={}
    for row in materials:
        if row['obj_name'] in used:unique.setdefault(row['obj_name'],row)
    for number,source in enumerate(unique.values()):
        name=source['obj_name'];slots=source.get('texture_slots',[]);color=slots[0] if slots else None;baseline=next(row for row in stock['materials'] if row['name']==name)
        base=None
        if baseline.get('native_file'):
            with Image.open(out/'stock-scene'/baseline['native_file']) as image:base=image.convert('RGB')
        replace=matching_rule(rules,color,'replace_tex') if color else None
        overlay=matching_rule(rules,color,'set_tex') if color else None
        camo=matching_rule(rules,slots[1],'replace_tex') if len(slots)>1 and slots[1] else None
        sources=[];quality=baseline.get('source_quality','unclassified')
        if replace:
            path=(config_dir/replace['to'].replace('\\','/')).resolve()
            with Image.open(path) as image:raw=image.convert('RGBA');base=raw.convert('RGB')
            sources.append({'file':str(path.relative_to(skin)),'sha256':sha(path),'binding':'replace_tex'})
            if source.get('shader')=='dynamic_masked_tank' and (camo or baseline.get('camo_mean_rgb')):
                if camo:
                    with Image.open(config_dir/camo['to']) as image:paint=tuple(round(n) for n in ImageStat.Stat(image.convert('RGB')).mean)
                else:paint=tuple(baseline['camo_mean_rgb'])
                base=Image.composite(Image.new('RGB',base.size,paint),base,raw.getchannel('A'))
            quality='user-supplied'
        elif camo and source.get('shader')=='dynamic_masked_tank':
            stock_map=read_json(stock_bind).get('materials',{}).get(name)
            if stock_map:
                with Image.open(stock_bind.parent/stock_map) as image:raw=image.convert('RGBA')
                with Image.open(config_dir/camo['to']) as image:paint=tuple(round(n) for n in ImageStat.Stat(image.convert('RGB')).mean)
                base=Image.composite(Image.new('RGB',raw.size,paint),raw.convert('RGB'),raw.getchannel('A'))
                warnings.append('平铺迷彩暂以平均色近似；未还原第二套迷彩 UV 图案')
        if overlay:
            if overlay.get('param')!='camo_skin_tex':warnings.append('有 set_tex 使用了尚未支持的参数：'+str(overlay.get('param')))
            else:
                path=(config_dir/overlay['to'].replace('\\','/')).resolve()
                with Image.open(path) as image:paint=image.convert('RGBA')
                if base is None:
                    if paint.getchannel('A').getextrema()==(255,255):base=Image.new('RGB',paint.size)
                    else:raise ValueError('半透明固定涂装需要原车底图，但资源未能读取：'+name)
                if base.size!=paint.size:base=base.resize(paint.size,Image.Resampling.LANCZOS)
                base=Image.composite(paint.convert('RGB'),base,paint.getchannel('A'));quality='user-supplied'
                sources.append({'file':str(path.relative_to(skin)),'sha256':sha(path),'binding':'set_tex/camo_skin_tex'})
        if base is not None:
            path=baked/f'color-{number:03d}.png';base.save(path);binding['materials'][name]=path.name;binding['source_quality'][name]=quality
        report.append({'material':name,'resource':color,'sources':sources,'dimensions':list(base.size) if base else None})
    if not any(row['sources'] for row in report) and not any(matching_rule(rules,row['texture_slots'][1]) for row in materials if len(row.get('texture_slots',[]))>1 and row['texture_slots'][1]):raise ValueError('涂装配置未匹配到所选模型的颜色材质，请检查车型')
    binding_path=baked/'bindings.json';write_json(binding_path,binding)
    progress(progress_file,'preparing','正在生成轻量模型和可编辑颜色图…')
    final=preview.prepare(model_dir,out/'scene',binding_path,1024)
    material_data=[r for r in rules if re.search(r'_(?:n|ao)\*?$',r['from'])]
    if material_data:warnings.append(f'已保留 {len(material_data)} 项法线／材质／AO 替换，当前仅预览颜色')
    if model_origin=='package':warnings.append('已使用包内配套模型；没有替换游戏安装文件')
    final['imported_skin']={'vehicle':vehicle,'config':config['blk'],'model_lod':lod,'model_origin':model_origin,'model_pack_sha256':sha(model_pack),'warnings':list(dict.fromkeys(warnings)),'flattened':True,'source_files_preserved':True,
                            'note':'导入的游戏贴图已合并，不能自动拆出旧装饰；新增图层可独立编辑。反射/法线/AO 原文件保留，当前未接入材质显示。'}
    write_json(out/'scene/scene.json',final);write_json(out/'skin-bindings.json',{'materials':report,'warnings':final['imported_skin']['warnings']})
    progress(progress_file,'ready','涂装与模型已经准备好')
    return {'ok':True,'vehicle':vehicle,'scene':str(out/'scene'),'config':config['blk'],'model_origin':model_origin,'warnings':final['imported_skin']['warnings']}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    imp=sub.add_parser('import');imp.add_argument('--input',type=Path,required=True);imp.add_argument('--out',type=Path,required=True);imp.add_argument('--game-dir',type=Path,required=True);imp.add_argument('--extractor',type=Path,required=True);imp.add_argument('--vehicle');imp.add_argument('--blk');imp.add_argument('--lod',type=int,choices=range(4),default=1);imp.add_argument('--progress',type=Path)
    resume=sub.add_parser('build');resume.add_argument('--discovery',type=Path,required=True);resume.add_argument('--out',type=Path,required=True);resume.add_argument('--vehicle');resume.add_argument('--blk');resume.add_argument('--lod',type=int,choices=range(4),default=1);resume.add_argument('--progress',type=Path)
    args=p.parse_args()
    try:
        if args.command=='build':result=build(args.discovery,args.out,args.vehicle,args.blk,args.lod,args.progress)
        else:
            discovery,data=scan(args.input,args.out/'scan',args.game_dir,args.extractor,args.blk,args.progress)
            chosen=next((r for r in data['configs'] if r['blk']==data['selected_blk']),None)
            if not chosen or not(args.vehicle or chosen['automatic_vehicle']):
                result={'ok':False,'needs_selection':True,'discovery':str(discovery),'configs':[{'blk':r['blk'],'automatic_vehicle':r['automatic_vehicle'],'candidates':[{'name':c['name'],'reason':c['reason']} for c in r['candidates'][:100]]} for r in data['configs']]}
            else:result=build(discovery,args.out/'result',args.vehicle,args.blk,args.lod,args.progress)
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as error:
        if getattr(args,'progress',None):progress(args.progress,'error',str(error))
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
