#!/usr/bin/env python3
"""The Alpine boot artwork as data for orchard's m1n1: the boot splash and the m1n1 logo.

  boot/build-artwork.py --output DIR [--logo-header alpine-logo.h]

DIR/splash is orchard's boot splash (docs/boot-contract.md), which m1n1
paints for an installed boot entry. DIR/logo.bin is m1n1's custom logo
payload (m1n1_logo_256128: RGBA on black, 256x256 then 128x128), which the
recovery's assembly puts directly after m1n1 (assemble.py --logo). Needs
rsvg-convert and ImageMagick; no m1n1 build.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
LOGO_MAGIC = b'm1n1_logo_256128'


def rgba(size):
    png = subprocess.check_output(['rsvg-convert', '-w', str(size), '-h', str(size),
                                   str(HERE / 'artwork/alpine-mark.svg')])
    pixels = subprocess.run(['magick', 'png:-', '-background', 'black', '-flatten', '-depth', '8', 'rgba:-'],
                            input=png, capture_output=True, check=True).stdout
    if len(pixels) != size * size * 4:
        raise ValueError(f'Unexpected {size}x{size} raster size')
    return pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--logo-header', type=Path, help='pre-generated artwork header (CI)')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output directory')
    args.output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='alpine-artwork-') as temporary:
        header = args.logo_header or Path(temporary) / 'alpine-logo.h'
        if not args.logo_header:
            subprocess.run([sys.executable, str(HERE / 'generate-logo.py'), '--output', str(header)], check=True)
        subprocess.run([sys.executable, str(HERE / 'splash.py'), str(header), str(args.output / 'splash')],
                       check=True)
    (args.output / 'logo.bin').write_bytes(LOGO_MAGIC + rgba(256) + rgba(128))
    print(f'Built {args.output}/splash and {args.output}/logo.bin')


if __name__ == '__main__':
    main()
