#!/usr/bin/env python3
"""orchard build's entry (distro.toml): the loader and Alpine base, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all]` in this checkout. The loader and base land in out/components/NAME/KEY/, keyed
by the files they are made from, so a build redoes only what changed.
orchard supplies m1n1, Pongo, the static tools and every platform's kernel
from its shared cache; the Alpine artwork is data for orchard's m1n1. The release itself is always assembled anew.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from orchard.distro import component
from orchard.build import prepare_shared

PROJECT = Path(__file__).resolve().parents[1]
# What each component is made from, relative to this checkout.
INPUTS = {
    'base': ['build_base.py', 'system/Containerfile', 'system/install-base'],
    'artwork': ['boot/build-artwork.py', 'boot/generate-logo.py', 'boot/splash.py', 'boot/artwork'],
}


def python(*argv):
    print('+', sys.executable, ' '.join(map(str, argv)), flush=True)
    subprocess.run([sys.executable, *map(str, argv)], cwd=PROJECT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    args = parser.parse_args()
    if 'all' in args.platform and len(args.platform) > 1:
        parser.error('--platform all builds every platform and combines with no other')
    # The release builder builds every platform when it is given none.
    selected = [part for name in args.platform if name != 'all' for part in ('--platform', name)]

    base, _ = component(PROJECT, 'base', INPUTS['base'],
                        lambda path, work: python('build_base.py', '--output', path), artifact='base.tar.gz')
    artwork, _ = component(PROJECT, 'artwork', INPUTS['artwork'],
                           lambda path, work: python('boot/build-artwork.py', '--output', path), artifact='artwork')
    shared = prepare_shared()
    tools = shared['tools']
    (PROJECT / 'out').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.inputs-', dir=PROJECT / 'out') as temporary:
        inputs = Path(temporary) / 'public'
        python('pin_components.py', '--loader', shared['loader'], '--splash', artwork / 'splash',
               '--logo', artwork / 'logo.bin', '--pongo', shared['pongo'],
               '--busybox', tools / 'busybox', '--dropbear', tools / 'dropbear', '--dropbearkey', tools / 'dropbearkey',
               '--wpa-supplicant', tools / 'wpa_supplicant', '--wpa-cli', tools / 'wpa_cli', '--iw', tools / 'iw',
               '--output', inputs)
        python('build.py', '--base', base, '--base-receipt', base.with_name(base.name + '.json'),
               '--inputs', inputs / 'inputs.json', '--version', args.version, *selected,
               '--output', args.output)
    python('audit.py', args.output)
    # install.sh and orchard-install.pyz, with orchard's launch loaders from its cache.
    python('-m', 'orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
