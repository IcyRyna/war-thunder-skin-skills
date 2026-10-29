"""Bind recorded visual judgements to current artifact identities and real images.

This validates evidence freshness and the stated verdict, not artistic quality.
"""
from PIL import Image
from skill_contract import checked_file,require_text,read_json


def artifact_binding(data,base_only=False):
    if base_only:
        textures={t['id']:t['base_c']['sha256'] for t in data.get('textures',[])}
        kind='base_color'
    else:
        textures={r['id']:r['dds']['sha256'] for r in data.get('runtime_textures',[])}
        kind='runtime_dds'
    if not textures:raise ValueError('Visual observation needs the actual current texture inventory')
    return {'model_sha256':data['model']['sha256'],'texture_kind':kind,'texture_sha256':textures}


def audit_visual_record(root,record,label,data=None,*,base_only=False):
    if record.get('verdict')!='satisfactory':
        raise ValueError('Visual finding is unresolved or needs correction: '+label)
    require_text(record.get('observation'),label+' actual observation')
    images=record.get('images')
    if not isinstance(images,list) or not images:raise ValueError('Visual observation requires actual images: '+label)
    seen=set()
    for entry in images:
        path=checked_file(root,entry,label+' image')
        if path in seen:raise ValueError('Duplicate visual evidence image')
        seen.add(path)
        try:
            with Image.open(path) as image:
                if image.format not in {'PNG','JPEG','WEBP'} or min(image.size)<8:
                    raise ValueError('Usable rendered/captured image required: '+label)
                image.verify()
        except OSError as error:
            raise ValueError('Visual evidence is not a decodable image: '+label) from error
    if data is not None and record.get('artifact_binding')!=artifact_binding(data,base_only):
        raise ValueError('Visual evidence does not bind the current model/textures: '+label)
    if data is not None:
        proof=read_json(checked_file(root,record.get('render_receipt'),label+' actual render receipt'))
        expected=artifact_binding(data,base_only)
        mapping='bound_base_colors' if base_only else 'bound_runtime_dds'
        if proof.get('model_sha256')!=expected['model_sha256'] or proof.get(mapping)!=expected['texture_sha256']:
            raise ValueError('Actual render receipt does not bind the current model/textures: '+label)
        if type(proof.get('exit_code')) is not int or proof['exit_code']!=0:
            raise ValueError('Actual rendering did not complete successfully: '+label)
        checked_file(root,proof.get('script'),label+' render script')
        checked_file(root,proof.get('run_log'),label+' render log')
        rendered={}
        for row in proof.get('renders',[]):
            path=checked_file(root,row,label+' rendered image')
            key=(path,row['sha256'])
            if key in rendered:raise ValueError('Repeated rendered image in receipt')
            rendered[key]=row.get('texture_kind')
        for entry in images:
            path=checked_file(root,entry,label+' selected image')
            if rendered.get((path,entry['sha256']))!=expected['texture_kind']:
                raise ValueError('Selected image is not a matching actual render output: '+label)
    return {'verdict':'satisfactory','actual_images':len(images),'artifact_binding_checked':data is not None,
            'actual_render_receipt_checked':data is not None,
            'scope':'recorded local judgement linked to actual current render outputs, not automatic art approval'}
