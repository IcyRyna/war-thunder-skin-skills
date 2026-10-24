"""Export lossless native RGB views; leave the DDS and its alpha untouched."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

from artifact_io import ArtifactTransaction
from tank_core import load_image


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def export_rgb(sources: list[Path], output: Path) -> dict:
    if not sources:
        raise ValueError('At least one DDS source is required')
    sources = [p.resolve(strict=True) for p in sources]
    names = [p.stem + '-rgb-native.png' for p in sources]
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError('Inputs would produce duplicate output names.')
    if any(p.suffix.lower() != '.dds' for p in sources):
        raise ValueError('Every input must be a DDS file.')
    output = output.resolve()
    if output.exists():
        raise FileExistsError('Output directory already exists; use a fresh output directory.')
    outputs = [output / n for n in names]
    receipt = output / 'rgb-export.json'
    checks = []
    with ArtifactTransaction(outputs + [receipt], sources, label='native-rgb-export') as transaction:
        for source, target in zip(sources, outputs):
            staged = transaction.stage(target)
            source_hash = sha256(source)
            rgba = load_image(source)
            alpha_range = rgba.getchannel('A').getextrema()
            rgb = rgba.convert('RGB')
            rgb.save(staged, format='PNG')
            with Image.open(staged) as reopened:
                if reopened.mode != 'RGB' or reopened.size != rgb.size:
                    raise RuntimeError(f'Unexpected exported image format: {target}')
                if ImageChops.difference(rgb, reopened).getbbox() is not None:
                    raise RuntimeError(f'RGB pixels changed during export: {target}')
            if sha256(source) != source_hash:
                raise RuntimeError(f'Source changed during export: {source}')
            checks.append(dict(source=str(source), source_sha256=source_hash,
                               output=target.name, output_sha256=sha256(staged),
                               width=rgb.width, height=rgb.height,
                               source_alpha_range=alpha_range, rgb_exact=True,
                               purpose='RGB viewing copy; not a replacement game texture'))
        transaction.stage(receipt).write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        transaction.commit()
    return dict(exported=len(checks), receipt=str(receipt), all_rgb_exact=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dds', type=Path, nargs='+')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_rgb(args.dds, args.out)))


if __name__ == '__main__':
    main()
