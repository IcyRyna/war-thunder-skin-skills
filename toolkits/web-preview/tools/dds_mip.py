"""Read an existing DDS mip for display; never rewrite the game texture."""
from io import BytesIO
from pathlib import Path
import struct
from PIL import Image


def open_display(path,long_edge):
    path=Path(path)
    if path.suffix.lower()!='.dds' or not long_edge:return Image.open(path)
    with path.open('rb') as source:
        header=bytearray(source.read(128))
        if len(header)!=128 or header[:4]!=b'DDS ':return Image.open(path)
        height,width=struct.unpack_from('<II',header,12);depth,mips=struct.unpack_from('<II',header,24);caps2=struct.unpack_from('<I',header,112)[0]
        if not width or not height or depth>1 or caps2&0x20fe00:return Image.open(path)
        original=[width,height];fourcc=bytes(header[84:88]);bits=struct.unpack_from('<I',header,88)[0];offset=128;block=None;mode=None
        if fourcc==b'DX10':
            extra=source.read(20)
            if len(extra)!=20:raise ValueError('DDS DX10 header truncated')
            dxgi,dimension,misc,array_size,_=struct.unpack('<IIIII',extra)
            if dimension!=3 or array_size!=1 or misc&4:return Image.open(path)
            block=8 if dxgi in (71,72,80,81) else 16 if dxgi in (74,75,77,78,83,84,95,96,98,99) else None
            if block is None:return Image.open(path)
            header.extend(extra);offset=148
        elif fourcc in (b'DXT1',b'ATI1',b'BC4U'):block=8
        elif fourcc in (b'DXT3',b'DXT5',b'ATI2',b'BC5U'):block=16
        elif fourcc==b'\0'*4:
            masks=struct.unpack_from('<IIII',header,92)
            raw_modes={(0xff,0xff00,0xff0000,0xff000000):'RGBA',(0xff0000,0xff00,0xff,0xff000000):'BGRA',
                       (0xff,0xff00,0xff0000,0):'RGBX',(0xff0000,0xff00,0xff,0):'BGRX'}
            if bits==32:mode=raw_modes.get(masks)
            elif bits==24 and masks==(0xff0000,0xff00,0xff,0):mode='BGR'
            elif bits==24 and masks==(0xff,0xff00,0xff0000,0):mode='RGB'
            if not mode or struct.unpack_from('<I',header,20)[0] not in (0,width*(bits//8)):return Image.open(path)
        else:return Image.open(path)
        def size(w,h):return max(1,(w+3)//4)*max(1,(h+3)//4)*block if block else w*h*(bits//8)
        level=0
        while max(width,height)>long_edge and level<max(1,mips)-1:
            offset+=size(width,height);width=max(1,width//2);height=max(1,height//2);level+=1
        count=size(width,height)
        if offset+count>path.stat().st_size:raise ValueError('DDS mip data truncated')
        source.seek(offset);payload=source.read(count)
    if mode:
        target='RGB' if mode in ('RGB','BGR') else 'RGBA'
        if mode in ('RGBX','BGRX'):
            image=Image.frombytes('RGB',(width,height),payload,'raw',mode).convert('RGBA')
        else:image=Image.frombytes(target,(width,height),payload,'raw',mode)
    else:
        struct.pack_into('<II',header,12,height,width);struct.pack_into('<I',header,20,count);struct.pack_into('<I',header,28,1)
        struct.pack_into('<I',header,8,struct.unpack_from('<I',header,8)[0]&~0x20000)
        struct.pack_into('<I',header,108,0x1000)
        image=Image.open(BytesIO(header+payload));image.load()
    image.info.update(original_dds_size=original,display_mip=level)
    return image
