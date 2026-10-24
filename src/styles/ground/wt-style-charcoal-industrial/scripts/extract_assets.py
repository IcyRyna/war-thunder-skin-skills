"""Reproduce source-pixel cutouts from the frozen original DDS archive's directory."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
from PIL import Image,ImageDraw,ImageOps

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def extract(source:Path,recipe:Path,out:Path):
    if out.exists():raise FileExistsError('Choose a new output directory')
    data=json.loads(recipe.read_text(encoding='utf-8'))
    images={}
    for entry in data['sources']:
        name=entry['file']
        if Path(name).name!=name:raise ValueError('Source names must be basenames')
        path=source/name
        if sha(path)!=entry['sha256']:raise ValueError('Source archive texture hash differs: '+name)
        with Image.open(path) as im:
            if max(im.size)>8192:raise ValueError('Texture dimension limit exceeded')
            images[name]=im.convert('RGB')
    ids=set()
    for item in data['assets']:
        name=item['id']
        if not name.replace('-','').isalnum() or name.casefold() in ids:raise ValueError('Invalid/duplicate asset ID')
        ids.add(name.casefold())
        x,y,r,b=item['box_xyxy'];w,h=images[item['source']].size
        if not 0<=x<r<=w or not 0<=y<b<=h:raise ValueError('Crop exceeds source texture')
        if any(not (0<=px<r-x and 0<=py<b-y) for px,py in item['polygon_px']):raise ValueError('Mask outside crop')
    for folder in ('raw','cutouts','masks','aligned'):(out/folder).mkdir(parents=True)
    report=[]
    for item in data['assets']:
        name=item['id'];rgb=images[item['source']].crop(item['box_xyxy'])
        mask=Image.new('L',rgb.size);ImageDraw.Draw(mask).polygon([tuple(p) for p in item['polygon_px']],fill=255)
        cut=rgb.convert('RGBA');cut.putalpha(mask)
        aligned=cut.crop(mask.getbbox())
        if item.get('mirror_horizontal'):aligned=ImageOps.mirror(aligned)
        if item.get('rotate'):
            aligned=cut.rotate(item['rotate'],Image.Resampling.BICUBIC,expand=True)
            aligned=aligned.crop(aligned.getchannel('A').getbbox())
        rgb.save(out/'raw'/(name+'.png'));cut.save(out/'cutouts'/(name+'.png'))
        mask.save(out/'masks'/(name+'.png'));aligned.save(out/'aligned'/(name+'.png'))
        exact=np.array_equal(np.asarray(cut)[:,:,:3],np.asarray(rgb))
        report.append({'id':name,'native_rgb_exact':bool(exact),'cutout_sha256':sha(out/'cutouts'/(name+'.png')),
                       'aligned_sha256':sha(out/'aligned'/(name+'.png'))})
    (out/'extraction-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return {'assets':len(report),'all_native_rgb_exact':all(r['native_rgb_exact'] for r in report)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--recipe',type=Path,default=Path(__file__).resolve().parents[1]/'references/extraction-recipe.json')
    a=p.parse_args();print(json.dumps(extract(a.source,a.recipe,a.out),indent=2))

if __name__=='__main__':main()
