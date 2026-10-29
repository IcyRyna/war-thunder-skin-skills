"""Decode historical DDS and re-encode a new DX10 semantic mip chain."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
from dds_snapshot import inspect_stream,read_top
from dds_variant import write_rgba8_mips,decode_mips
from ground_dds import semantic_mips
from skill_contract import sha

def convert(source,out,role,alpha_semantics,color_space):
    source=Path(source).resolve(strict=True);out=Path(out).absolute()
    if out.exists() or out==source:raise ValueError("Historical import output must be a new directory")
    allowed={"color":({"fixed_rgb","opacity"},"srgb"),"normal":({"packed_data"},"linear"),"ao":({"scalar_data"},"linear")}
    if role not in allowed or alpha_semantics not in allowed[role][0] or color_space!=allowed[role][1]:
        raise ValueError("Explicit native shader role/alpha/color-space required")
    with source.open("rb") as f:history=inspect_stream(f,source.stat().st_size)
    with source.open("rb") as f:meta,top=read_top(f,source.stat().st_size)
    mips=semantic_mips(Image.fromarray(top),alpha_semantics,color_space)
    out.mkdir(parents=True)
    canonical=out/"canonical.png";Image.fromarray(top).save(canonical)
    target=out/"texture.dds";write_rgba8_mips(target,mips,"color" if role=="color" else "data")
    _,decoded=decode_mips(target)
    if len(decoded)!=len(mips) or any(not np.array_equal(a,b) for a,b in zip(decoded,mips)):
        raise ValueError("Re-encoded DDS differs from semantic mip pixels")
    report={"source":str(source),"source_sha256":sha(source),"source_format":meta["codec"],
            "source_mips":history["mips"],"role":role,"alpha_semantics":alpha_semantics,
            "color_space":color_space,"canonical_sha256":sha(canonical),"output_sha256":sha(target),
            "new_format":"DX10 RGBA8","all_mips_exact":True,"game_validation":"not_run",
            "delivery_budget":"must be checked separately; BC3 production encoding may be required"}
    (out/"import-receipt.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("source",type=Path);p.add_argument("--out",type=Path,required=True)
    p.add_argument("--role",choices=["color","normal","ao"],required=True);p.add_argument("--alpha-semantics",required=True);p.add_argument("--color-space",required=True)
    a=p.parse_args();r=convert(a.source,a.out,a.role,a.alpha_semantics,a.color_space)
    print(json.dumps({k:v for k,v in r.items() if k!="source_mips"},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
