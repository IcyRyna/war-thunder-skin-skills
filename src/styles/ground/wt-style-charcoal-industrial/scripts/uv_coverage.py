"""Check full UV role masks and immutable protected RGBA; emit review diagnostics."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image

def check(occupied,paint,protected,before,after,shared=None):
 arrays=[np.asarray(x) for x in (occupied,paint,protected)];shape=arrays[0].shape
 if len(shape)!=2 or any(x.shape!=shape or not np.isin(x,[0,1,255]).all() for x in arrays):raise ValueError('Same-size binary role masks required')
 b,a=np.asarray(before),np.asarray(after)
 if b.shape!=a.shape or b.shape!=shape+(4,) or b.dtype!=np.uint8 or a.dtype!=np.uint8:raise ValueError('Matching RGBA8 originals and outputs required')
 o,p,r=[x>0 for x in arrays]
 if not o.any():raise ValueError('Occupied mask is empty')
 if shared is None:s=np.zeros(shape,bool)
 else:
  s=np.asarray(shared)
  if s.shape!=shape or not np.isin(s,[0,1,255]).all():raise ValueError('Same-size binary shared-UV mask required')
  s=s>0
 shared_paint=s&p
 missing=o&~(p|r);overlap=p&r;outside=(p|r)&~o;changed=np.any(a!=b,axis=2);bad=r&changed;unchanged=p&~changed
 counts={name:int(x.sum()) for name,x in [('occupied',o),('paint',p),('protected',r),('unclassified',missing),('overlap',overlap),('outside_occupied',outside),('protected_changed',bad),('unchanged_paint_review',unchanged)]}
 counts['shared_paint']=int(shared_paint.sum())
 return {'counts':counts,'sharing_checked':shared is not None,'technical_pass':not any(x.any() for x in [missing,overlap,outside,bad,shared_paint]),'visual_review':'pending; unchanged paint is a suspicion, not automatic failure'}, {'unclassified':missing,'overlap':overlap,'outside-occupied':outside,'protected-changed':bad,'unchanged-paint':unchanged,'shared-paint':shared_paint}

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['occupied','paint','protected','before','after','out']:p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--shared',type=Path)
 a=p.parse_args()
 if a.out.exists():raise FileExistsError(a.out)
 masks=[np.asarray(Image.open(getattr(a,n)).convert('L')) for n in ['occupied','paint','protected']]
 shared=np.asarray(Image.open(a.shared).convert('L')) if a.shared else None
 report,diagnostics=check(*masks,*[np.asarray(Image.open(getattr(a,n)).convert('RGBA')) for n in ['before','after']],shared=shared)
 a.out.mkdir(parents=True)
 for name,mask in diagnostics.items():Image.fromarray(np.uint8(mask)*255).save(a.out/(name+'.png'))
 (a.out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report));return 0 if report['technical_pass'] else 2
if __name__=='__main__':raise SystemExit(main())
