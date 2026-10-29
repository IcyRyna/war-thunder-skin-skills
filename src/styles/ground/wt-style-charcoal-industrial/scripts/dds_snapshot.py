"""Read-only inspection of real legacy/DX10 DDS payloads; not a delivery approval."""
from __future__ import annotations
import hashlib
from io import BytesIO
import struct
import numpy as np
from PIL import Image
from dds_variant import mip_sizes, _single_mip_header

DXGI={28:("rgba8",4,"linear"),29:("rgba8",4,"srgb"),
      71:("bc1",8,"linear"),72:("bc1",8,"srgb"),
      74:("bc2",16,"linear"),75:("bc2",16,"srgb"),
      77:("bc3",16,"linear"),78:("bc3",16,"srgb"),
      98:("bc7",16,"linear"),99:("bc7",16,"srgb")}
LINEAR_DXGI={72:71,75:74,78:77,99:98}


def parse_header(header,total_bytes):
    if len(header)<128 or header[:4]!=b"DDS ":
        raise ValueError("Missing/truncated DDS header")
    h=struct.unpack_from("<31I",header,4)
    if h[0]!=124 or h[18]!=32 or h[5] not in (0,1) or h[27]!=0:
        raise ValueError("Unsupported DDS header/volume/cube")
    sizes=mip_sizes(h[3],h[2])
    count=h[6] or 1
    if count!=len(sizes):raise ValueError("Actual DDS has incomplete chain to 1x1")
    fourcc=header[84:88]
    dxgi=None;offset=128;alpha_mode=None
    if fourcc==b"DX10":
        if len(header)<148:raise ValueError("Truncated DX10 header")
        dxgi,dimension,misc,array_size,alpha_mode=struct.unpack_from("<5I",header,128)
        if dimension!=3 or misc!=0 or array_size!=1 or dxgi not in DXGI:
            raise ValueError("Unsupported actual DDS format/array/cube")
        codec,unit,space=DXGI[dxgi];offset=148
    elif fourcc in (b"DXT1",b"DXT3",b"DXT5"):
        codec,unit={b"DXT1":("bc1",8),b"DXT3":("bc2",16),b"DXT5":("bc3",16)}[fourcc]
        space="legacy_unspecified"
    elif fourcc==b"\0\0\0\0" and h[21]==32 and h[19]&0x40:
        codec,unit,space="legacy_rgba8",4,"legacy_unspecified"
        masks=h[22:26]
        nonzero=[mask for mask in masks if mask]
        if len(nonzero)!=len(set(nonzero)) or any(mask not in (0xff,0xff00,0xff0000,0xff000000) for mask in nonzero) or not all(masks[:3]):
            raise ValueError("Unsupported legacy channel masks")
    else:
        raise ValueError("Unsupported legacy DDS encoding")
    counts=[w*height*4 if codec in {"rgba8","legacy_rgba8"} else max(1,(w+3)//4)*max(1,(height+3)//4)*unit
            for w,height in sizes]
    if total_bytes!=offset+sum(counts):
        raise ValueError(f"DDS payload size mismatch: expected {offset+sum(counts)}, actual {total_bytes}")
    return {"width":h[3],"height":h[2],"mip_count":count,"codec":codec,"dxgi":dxgi,
            "color_space_tag":space,"alpha_mode":alpha_mode,"channel_masks":list(h[22:26]),
            "header_bytes":offset,"mip_sizes":sizes,"mip_bytes":counts,
            "evidence_boundary":"actual container decoded; shader semantics and delivery limits remain separate"}


def decode_mip(chunk,width,height,meta):
    codec=meta["codec"]
    if codec=="rgba8":return np.frombuffer(chunk,np.uint8).reshape(height,width,4).copy()
    if codec=="legacy_rgba8":
        values=np.frombuffer(chunk,"<u4").reshape(height,width)
        channels=[]
        for mask in meta["channel_masks"]:
            if not mask:channels.append(np.full(values.shape,255,np.uint8))
            else:
                shift=(mask & -mask).bit_length()-1
                channels.append(((values & mask)>>shift).astype(np.uint8))
        return np.stack(channels,axis=-1)
    dxgi=meta["dxgi"] or {"bc1":71,"bc2":74,"bc3":77}[codec]
    wrapper=_single_mip_header(width,height,LINEAR_DXGI.get(dxgi,dxgi))
    with Image.open(BytesIO(wrapper+chunk)) as image:
        return np.array(image.convert("RGBA"))


def inspect_stream(stream,total_bytes,decode=True):
    header=stream.read(min(148,total_bytes))
    meta=parse_header(header,total_bytes)
    remainder=header[meta["header_bytes"]:]
    digest=hashlib.sha256();digest.update(header)
    records=[]
    for level,((width,height),count) in enumerate(zip(meta["mip_sizes"],meta["mip_bytes"])):
        take=min(count,len(remainder));pieces=[remainder[:take]];remainder=remainder[take:]
        needed=count-take
        while needed:
            block=stream.read(min(needed,1048576))
            if not block:raise ValueError("Truncated DDS payload")
            digest.update(block);pieces.append(block);needed-=len(block)
        chunk=b"".join(pieces)
        row={"level":level,"size":[width,height],"payload_bytes":count,
             "payload_sha256":hashlib.sha256(chunk).hexdigest()}
        if decode:
            pixels=decode_mip(chunk,width,height,meta)
            row["decoded_rgba_sha256"]=hashlib.sha256(pixels.tobytes()).hexdigest()
        records.append(row)
    if remainder or stream.read(1):raise ValueError("Unexpected DDS trailing payload")
    return {**meta,"actual_file_sha256":digest.hexdigest(),"mips":records,"decoded":bool(decode)}


def read_top(stream,total_bytes):
    header=stream.read(min(148,total_bytes));meta=parse_header(header,total_bytes)
    remainder=header[meta["header_bytes"]:]
    count=meta["mip_bytes"][0];chunks=[remainder[:count]]
    left=count-len(chunks[0])
    while left:
        chunk=stream.read(min(left,1048576))
        if not chunk:raise ValueError("Truncated top mip")
        chunks.append(chunk);left-=len(chunk)
    return meta,decode_mip(b"".join(chunks),meta["width"],meta["height"],meta)



def main():
    import argparse,json,zipfile
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("--member",help="Exact DDS member inside an existing ZIP")
    parser.add_argument("--structure-only",action="store_true")
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    if args.member:
        with zipfile.ZipFile(args.source) as z:
            info=z.getinfo(args.member)
            with z.open(info) as stream:report=inspect_stream(stream,info.file_size,not args.structure_only)
    else:
        with args.source.open("rb") as stream:report=inspect_stream(stream,args.source.stat().st_size,not args.structure_only)
    if args.out:
        with args.out.open("x",encoding="utf-8") as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
