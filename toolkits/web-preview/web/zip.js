const table=Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
export function crc32(bytes){let crc=0xffffffff;for(const byte of bytes)crc=table[(crc^byte)&255]^(crc>>>8);return (crc^0xffffffff)>>>0;}
function header(size,values){const bytes=new Uint8Array(size),view=new DataView(bytes.buffer);for(const [offset,value,width] of values)width===2?view.setUint16(offset,value,true):view.setUint32(offset,value,true);return bytes;}
export async function zipBlob(files){
  if(files.length>64)throw new Error('一次最多导出 64 张贴图');const chunks=[],central=[];let offset=0;
  for(const file of files){const name=new TextEncoder().encode(file.name),data=new Uint8Array(await file.blob.arrayBuffer()),crc=crc32(data);if(data.length>256*1024*1024||offset+data.length>1024*1024*1024)throw new Error('导出包太大，请分批导出');
    const local=header(30,[[0,0x04034b50,4],[4,20,2],[6,0x800,2],[14,crc,4],[18,data.length,4],[22,data.length,4],[26,name.length,2]]);
    chunks.push(local,name,data);const record=header(46,[[0,0x02014b50,4],[4,20,2],[6,20,2],[8,0x800,2],[16,crc,4],[20,data.length,4],[24,data.length,4],[28,name.length,2],[42,offset,4]]);central.push(record,name);offset+=local.length+name.length+data.length;
  }
  const centralSize=central.reduce((n,b)=>n+b.length,0),end=header(22,[[0,0x06054b50,4],[8,files.length,2],[10,files.length,2],[12,centralSize,4],[16,offset,4]]);
  return new Blob([...chunks,...central,end],{type:'application/zip'});
}
export async function downloadZip(files,name){const blob=await zipBlob(files),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
