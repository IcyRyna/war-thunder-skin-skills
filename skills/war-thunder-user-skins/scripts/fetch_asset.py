#!/usr/bin/env python3
"""Download a selected public image for a skin project and retain provenance.

The agent searches and chooses the source first. This helper does not scrape a
catalog or decide licensing. --page + --link selects an observed source-page
link by filename substring; --url uses an already observed direct media URL.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urljoin,urlparse
import requests
from PIL import Image


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            for name,value in attrs:
                if name.lower()=='href' and value:
                    self.links.append(value)


def download(url: str, destination: Path, limit: int):
    if urlparse(url).scheme!='https':
        raise ValueError('Use an HTTPS source URL')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise ValueError(f'Asset already exists: {destination}')
    temp=None
    try:
        with requests.get(url,stream=True,timeout=(10,45),headers={'User-Agent':'WarThunderSkinWorkshop/1.0'}) as response:
            response.raise_for_status()
            if urlparse(response.url).scheme!='https':
                raise ValueError('Redirect changed to a non-HTTPS source')
            length=response.headers.get('Content-Length')
            if length and int(length)>limit:
                raise ValueError('Asset exceeds configured byte limit')
            count=0
            with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as handle:
                temp=Path(handle.name)
                for chunk in response.iter_content(65536):
                    count+=len(chunk)
                    if count>limit:
                        raise ValueError('Asset exceeds configured byte limit')
                    handle.write(chunk)
            final_url=response.url
        with Image.open(temp) as bitmap:
            bitmap.verify()
        temp.replace(destination); temp=None
        return final_url,count
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url')
    p.add_argument('--page',required=True)
    p.add_argument('--link',help='Filename substring to select from the already inspected page')
    p.add_argument('--name',required=True)
    p.add_argument('--credit',required=True)
    p.add_argument('--license-note',default='Source terms recorded on the source page; verify for the requested destination.')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--max-mb',type=int,default=25)
    args=p.parse_args()
    try:
        if Path(args.name).name!=args.name or args.name in {'.','..'}:
            raise ValueError('--name must be a basename')
        if not 1<=args.max_mb<=100:
            raise ValueError('--max-mb must be 1..100')
        url=args.url
        if not url:
            if not args.link:
                raise ValueError('Provide --url or --link')
            response=requests.get(args.page,timeout=(10,30))
            response.raise_for_status()
            parser=Links(); parser.feed(response.text)
            candidates=sorted({urljoin(response.url,h) for h in parser.links if args.link in h})
            if len(candidates)!=1:
                raise ValueError(f'Source link is ambiguous: {len(candidates)} matches')
            url=candidates[0]
        destination=args.out.resolve()/args.name
        final_url,count=download(url,destination,args.max_mb*1024*1024)
        with Image.open(destination) as bitmap:
            width,height=bitmap.size; mode=bitmap.mode
            # Lossless format conversion is for Composa compatibility; all
            # actual crop, cutout, styling and composition remain editor work.
            proxy=destination.with_suffix('.png') if destination.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'} else destination
            if proxy!=destination:
                bitmap.convert('RGBA').save(proxy)
        record={'source_page':args.page,'direct_url':final_url,'credit':args.credit,
                'license_note':args.license_note,'file':str(destination),'editor_file':str(proxy),
                'bytes':count,'width':width,'height':height,'mode':mode,
                'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                'retrieved_utc':datetime.now(timezone.utc).isoformat()}
        manifest=destination.with_suffix(destination.suffix+'.source.json')
        manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,requests.RequestException) as exc:
        print(f'Asset fetch failed: {exc}',file=__import__('sys').stderr);return 1


if __name__=='__main__':
    raise SystemExit(main())
