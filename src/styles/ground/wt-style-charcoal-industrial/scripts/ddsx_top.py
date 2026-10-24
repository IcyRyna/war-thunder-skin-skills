"""Bounded top-level DDS extraction from an already decompressed DDSx payload.

Header ordering follows Gaijin's prog/engine/sharedInclude/3d/ddsxTex.h.
The caller supplies native decompression; this module never reinterprets N channels.
"""
from __future__ import annotations
import io,struct
from PIL import Image

def decode_top(payload: bytes, header: bytes) -> tuple[bytes,dict]:
    if len(header)!=32:raise ValueError('DDSx header must be exactly 32 bytes')
    label,fmt,flags,width,height,levels,hq,depth,bpp,quality,shift,mem_size,packed=struct.unpack('<4s4sIHHBBHHBBII',header)
    if label!=b'DDSx' or not 1<=width<=16384 or not 1<=height<=16384 or not 1<=levels<=32:raise ValueError('Invalid DDSx header')
    if depth>1 or flags&(0x800|0x1000|0x200000|0x100000):raise ValueError('Only ordinary desktop 2D BC textures are supported')
    if flags&0x20000:raise ValueError('Paired base texture is required; isolated payload cannot be decoded')
    if len(payload)!=mem_size or mem_size>512*1024*1024:raise ValueError('Decompressed payload size is inconsistent or too large')
    block={b'DXT1':8,b'DXT3':16,b'DXT5':16,b'BC7 ':16}.get(fmt)
    if block is None:raise ValueError('Unsupported compression format '+repr(fmt))
    sizes=[max(1,(max(1,width>>i)+3)//4)*max(1,(max(1,height>>i)+3)//4)*block for i in range(levels)]
    if flags&(0x2000|0x4000):
        tail=12 if flags&0x4000 else 0
        if len(payload)!=sizes[0]+tail:raise ValueError('Unexpected generated-mip payload length')
        top=payload[:sizes[0]];source_mips='runtime-generated; only original top exported'
    else:
        if len(payload)!=sum(sizes):raise ValueError('Stored mip byte counts do not match header')
        top=payload[-sizes[0]:] if flags&0x40000 else payload[:sizes[0]];source_mips='stored; only original top exported'
    d=[0]*31;d[:7]=[124,0x81007,height,width,sizes[0],0,1];d[18:21]=[32,4,int.from_bytes(b'DX10' if fmt==b'BC7 ' else fmt,'little')];d[26]=0x1000
    result=b'DDS '+struct.pack('<31I',*d)+(struct.pack('<5I',98,3,0,1,0) if fmt==b'BC7 ' else b'')+top
    with Image.open(io.BytesIO(result)) as image:
        image.load()
        if image.size!=(width,height):raise ValueError('Independent decoder dimension mismatch')
    return result,{'width':width,'height':height,'format':fmt.decode('ascii'),'source_mips':source_mips,'source_levels':levels,'source_hq_levels':hq,'exported_mips':1,'payload_bytes_unchanged':True,'dimension_order':'DDSx w,h -> DDS height,width'}
