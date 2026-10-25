#!/usr/bin/env python3
"""Rasterize distro-owned Alpine artwork to bounded blue/white C masks."""
import argparse
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=json.loads((HERE / 'artwork/presentation.json').read_text())['size'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    size = args.size
    if size <= 0 or size > 2048 or size % 8:
        parser.error('Size must be a positive multiple of 8, at most 2048')
    png = subprocess.check_output(['rsvg-convert', '-w', str(size), '-h', str(size),
                                   str(HERE / 'artwork/alpine-mark.svg')])
    pixels = subprocess.run(['magick', 'png:-', '-depth', '8', 'rgba:-'], input=png,
                            capture_output=True, check=True).stdout
    if len(pixels) != size * size * 4:
        raise ValueError('Unexpected raster size')
    blue, white = bytearray(size * size // 8), bytearray(size * size // 8)
    for i in range(size * size):
        r, g, b, alpha = pixels[i * 4:i * 4 + 4]
        if alpha >= 128:
            plane = white if r >= 128 else blue
            plane[i // 8] |= 1 << (7 - i % 8)
    lines = ['/* Generated from distro-owned Alpine artwork; do not edit. */',
             '#pragma once', '#include <stdint.h>', '#define ALPINE_LOGO_SIZE ' + str(size) + 'u']
    for name, data in (('alpine_logo_blue', blue), ('alpine_logo_white', white)):
        lines.append('static const uint8_t ' + name + '[] = {')
        lines += ['    ' + ', '.join('0x%02x' % b for b in data[i:i + 16]) + ','
                  for i in range(0, len(data), 16)]
        lines.append('};')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines) + '\n')
    print('Generated', size, 'pixel Alpine mark:', args.output)


if __name__ == '__main__':main()
