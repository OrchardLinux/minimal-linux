#!/usr/bin/env python3
"""orchard's boot splash (docs/boot-contract.md) from the m1n1 artwork header.

The same masks and colours as m1n1/patches/0002-alpine-splash.patch draws, so
install (our m1n1) and orchard launch (the boot entry's splash) look alike.
"""
import argparse
from pathlib import Path
import re
import struct

BLUE, WHITE, BLACK = (0x0d, 0x59, 0x7f), (0xff, 0xff, 0xff), (0, 0, 0)


def masks(header):
    size = int(re.search(r'#define ALPINE_LOGO_SIZE (\d+)u', header).group(1))
    planes = {}
    for name in ('alpine_logo_blue', 'alpine_logo_white'):
        body = re.search(name + r'\[\] = \{(.*?)\};', header, re.S).group(1)
        planes[name] = bytes(int(value, 16) for value in re.findall(r'0x([0-9a-f]{2})', body))
    return size, planes['alpine_logo_blue'], planes['alpine_logo_white']


def splash(header):
    size, blue, white = masks(header)
    pixels = bytearray()
    for bit in range(size * size):
        on = lambda plane: plane[bit // 8] & (0x80 >> (bit % 8))
        pixels += bytes((*(BLUE if on(blue) else WHITE if on(white) else BLACK), 0))
    return struct.pack('<4sII', b'OSPL', size, size) + pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('header', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(splash(args.header.read_text()))


if __name__ == '__main__':
    main()
