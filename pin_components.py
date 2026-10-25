#!/usr/bin/env python3
"""Copy explicit public component inputs into an independent, hash-pinned directory.

This records operator-selected inputs, not a signature/trust verification service.
Verify their supplied provenance/receipts before selecting them.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from orchard_hardware.image.integrity import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    roles = ('loader', 'pongo', 'kernel', 'dtb', 'busybox', 'dropbear', 'dropbearkey')
    for name in (*roles, 'modules-dir', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new component output directory')
    sources = {name: getattr(args, name) for name in roles}
    sources['kernel_release'] = args.modules_dir.parent.parent / 'kernel.release'
    if any(p.is_symlink() or not p.is_file() for p in sources.values()):
        parser.error('Component inputs must be regular files')
    if args.modules_dir.is_symlink() or not args.modules_dir.is_dir() or any(p.is_symlink() for p in args.modules_dir.rglob('*')):
        parser.error('Module input must be a link-free directory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.components-', dir=args.output.parent) as tmp:
        output = Path(tmp) / 'components'
        output.mkdir()
        shutil.copytree(args.modules_dir, output / 'kernel/lib/modules')
        files = {}
        for name, source in sources.items():
            relative = {'kernel': 'kernel/Image.gz', 'dtb': 'kernel/j71b.dtb',
                        'kernel_release': 'kernel/kernel.release'}.get(name, name)
            target = output / relative
            shutil.copyfile(source, target)
            if sha(source) != sha(target):
                raise ValueError('Component changed while copying: ' + name)
            files[name] = {'path': str((args.output / relative).resolve()),
                           'bytes': target.stat().st_size, 'sha256': sha(target)}
        modules = output / 'kernel/lib/modules'
        record = {'files': files, 'modules': {'path': str((args.output / 'kernel/lib/modules').resolve()),
            'files': {p.relative_to(modules).as_posix(): sha(p) for p in modules.rglob('*') if p.is_file()}}}
        (output / 'inputs.json').write_text(json.dumps(record, indent=2) + '\n')
        os.rename(output, args.output)
    print('Independent public components:', args.output / 'inputs.json')


if __name__ == '__main__':
    main()
