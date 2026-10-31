#!/usr/bin/env python3
"""Pin the public components shared by every platform: loader, Pongo and static tools.

Kernels are not pinned here: build.py takes every platform's kernel from
orchard's cache, or from --kernel-dir. This records operator-selected inputs,
not a signature/trust verification service. Verify their supplied
provenance/receipts before selecting them.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from orchard.image.integrity import sha

ROLES = ('loader', 'splash', 'pongo', 'busybox', 'dropbear', 'dropbearkey', 'wpa-supplicant', 'wpa-cli', 'iw')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in (*ROLES, 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new component output directory')
    sources = {name.replace('-', '_'): getattr(args, name.replace('-', '_')) for name in ROLES}
    for path in sources.values():
        if path.is_symlink() or not path.is_file():
            parser.error(f'Explicit input must be a regular file: {path}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.components-', dir=args.output.parent) as tmp:
        output = Path(tmp) / 'components'
        output.mkdir()
        files = {}
        for name, source in sources.items():
            target = output / name
            shutil.copyfile(source, target)
            if sha(source) != sha(target):
                raise ValueError('Component changed while copying: ' + name)
            files[name] = {'path': str((args.output / name).resolve()),
                           'bytes': target.stat().st_size, 'sha256': sha(target)}
        (output / 'inputs.json').write_text(json.dumps({'schema': 2, 'files': files}, indent=2) + '\n')
        os.rename(output, args.output)
    print('Independent public components:', args.output / 'inputs.json')


if __name__ == '__main__':
    main()
