"""Build reproducible source comparisons; suspicious alpha regions are never deleted."""
from pathlib import Path
import argparse, hashlib, json
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def components(mask):
    # Optional SciPy accelerates large plates; fallback uses the same 4-connectivity.
    try:
        from scipy.ndimage import label
        labels,count=label(mask)
        return sorted(np.bincount(labels.ravel())[1:].tolist())
    except ImportError:
        seen=np.zeros(mask.shape,bool); sizes=[]; h,w=mask.shape
        for y,x in zip(*np.nonzero(mask)):
            if seen[y,x]:continue
            stack=[(x,y)];seen[y,x]=True;n=0
            while stack:
                xx,yy=stack.pop();n+=1
                for nx,ny in ((xx-1,yy),(xx+1,yy),(xx,yy-1),(xx,yy+1)):
                    if 0<=nx<w and 0<=ny<h and mask[ny,nx] and not seen[ny,nx]:seen[ny,nx]=True;stack.append((nx,ny))
            sizes.append(n)
        return sorted(sizes)

def audit(root,out):
    if out.exists():raise FileExistsError(out)
    rows=json.loads((root/'assets/catalog.json').read_bytes())['assets']; out.mkdir(parents=True)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20) if Path('C:/Windows/Fonts/arial.ttf').exists() else ImageFont.load_default()
    report=[]
    for row in rows:
        p=root/row['file']; digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest!=row['sha256']:raise ValueError('Catalog hash mismatch: '+row['id'])
        im=Image.open(p).convert('RGBA'); a=np.asarray(im); alpha=a[:,:,3]
        source=Image.open(root/row.get('source_file',row['file'])).convert('RGBA')
        solid=alpha>=128; sizes=components(solid)
        from scipy.ndimage import binary_fill_holes
        holes=binary_fill_holes(solid)&~solid
        fringe=(alpha>0)&(alpha<128)
        hue=a[:,:,:3].max(axis=2).astype(int)-a[:,:,:3].min(axis=2)
        entry={'id':row['id'],'sha256':digest,'size':list(im.size),'kind':row['kind'],'transparent_pixels':int((alpha==0).sum()),
               'opaque_components':len(sizes),'small_components_under_8px':sum(n<8 for n in sizes),'component_sizes':sizes,
               'native_alpha_values':len(np.unique(alpha)),'enclosed_gap_pixels':int(holes.sum()),
               'enclosed_gap_components':len(components(holes)),
               'saturated_fringe_suspects':int((fringe&(hue>48)).sum()),
               'known_text_to_compare':row.get('known_text',[]),
               'text_review':'pending','topology_review':'pending','user_review':row['user_review'],
               'machine_result':'suspicions_only; wear and thin lines are not automatically removed'}
        # Four sources at their native dimensions, then native and enlarged detail.
        board=Image.new('RGB',(1600,1050),'#e5e3de');draw=ImageDraw.Draw(board)
        panels=[(source,'SOURCE / native master',(30,65),'#ddd9d0'),(im,'CANDIDATE / light',(820,65),'#ddd9d0'),
                (im,'CANDIDATE / dark',(30,400),'#161b20'),(im,'ALPHA / checker',(820,400),None)]
        for pic,title,(x,y),bg in panels:
            draw.text((x,y-30),title,font=font,fill='#262b30');pic=pic.copy();pic.thumbnail((750,285))
            canvas=Image.new('RGBA',(750,285),bg or '#afafaf')
            if bg is None:
                cd=ImageDraw.Draw(canvas)
                for yy in range(0,285,20):
                    for xx in range(0,750,20):
                        if (xx//20+yy//20)%2:cd.rectangle((xx,yy,xx+19,yy+19),fill='#ddd')
            canvas.alpha_composite(pic,((750-pic.width)//2,(285-pic.height)//2));board.paste(canvas.convert('RGB'),(x,y))
        points=np.argwhere(solid)
        y,x=points[0] if len(points) else (0,0);x=max(0,int(x)-40);y=max(0,int(y)-40)
        detail=im.crop((x,y,min(im.width,x+350),min(im.height,y+140))).resize((700,280),Image.Resampling.NEAREST)
        canvas=Image.new('RGBA',detail.size,'#ddd9d0');canvas.alpha_composite(detail);board.paste(canvas.convert('RGB'),(30,740))
        draw.text((820,755),row['id'],font=font,fill='#222');draw.text((820,800),'2x native edge detail (left)',font=font,fill='#222')
        draw.text((820,845),f"Components: {len(sizes)} / tiny: {entry['small_components_under_8px']}",font=font,fill='#222')
        draw.text((820,890),'Text / topology / visual: PENDING',font=font,fill='#222')
        board.save(out/(row['id']+'.png'));im.save(out/(row['id']+'-native.png'));report.append(entry)
    (out/'audit.json').write_text(json.dumps({'assets':report,'auto_removed_pixels':0,'visual_approval_inferred':False},indent=2),encoding='utf-8')
    return {'assets':len(report),'output':str(out),'auto_removed_pixels':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args()
    print(json.dumps(audit(a.root,a.out)))
