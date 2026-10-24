"""Build an allowlisted, presentation-only site; local editor sources stay local."""
from pathlib import Path
import argparse
import json
import shutil

FILES=['preview.js','preview.css','reflection.js','vendor/three.module.js','vendor/three.core.js','vendor/LICENSE.txt','vendor/provenance.json','vendor/addons/controls/OrbitControls.js','vendor/addons/loaders/GLTFLoader.js','vendor/addons/utils/BufferGeometryUtils.js']
ROOT=Path(__file__).resolve().parents[1]

def build(output):
    output=Path(output)
    if output.exists():raise FileExistsError('Online build output must be a new directory')
    output.mkdir(parents=True)
    for relative in FILES:
        target=output/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'web'/relative,target)
    shutil.copyfile(ROOT/'web/preview.html',output/'index.html')
    print(json.dumps({'kind':'presentation-only','files':len(FILES)+1,'output':str(output)}))
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();build(args.out)
