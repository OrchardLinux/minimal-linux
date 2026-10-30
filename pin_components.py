#!/usr/bin/env python3
"""Pin public components, resolving omitted kernel inputs through Orchard's cache.

This records operator-selected inputs, not a signature/trust verification service.
Verify their supplied provenance/receipts before selecting them.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from orchard.image.integrity import sha


def resolve_kernel(args):
    """Keep explicit kernel inputs; otherwise share the RAM builder's cache."""
    supplied = [getattr(args, name) is not None for name in ('kernel', 'dtb', 'modules_dir')]
    if any(supplied):
        if not all(supplied):
            raise ValueError('Provide --kernel, --dtb and --modules-dir together, or omit all three')
        return
    from orchard.build import prepare_kernel
    # This image is J71b's (build.py's profile); the device layer generalizes it.
    device = 'j71b'
    kernel = prepare_kernel(device=device)
    args.kernel = kernel / 'Image.gz'
    args.dtb = kernel / (device + '.dtb')
    args.modules_dir = kernel / 'lib/modules'
    return device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    roles = ('loader', 'pongo', 'kernel', 'dtb', 'busybox', 'dropbear', 'dropbearkey')
    for name in (*roles, 'modules-dir', 'output'):
        parser.add_argument('--' + name, type=Path,
                            required=name not in ('kernel', 'dtb', 'modules-dir'))
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new component output directory')
    # Validate supplied files before resolving a potentially expensive cache miss.
    for name in roles:
        path = getattr(args, name)
        if path is not None and (path.is_symlink() or not path.is_file()):
            parser.error(f'Explicit input must be a regular file: {path}')
    try:
        device = resolve_kernel(args) or 'j71b'
    except ValueError as error:
        parser.error(str(error))
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
            relative = {'kernel': 'kernel/Image.gz', 'dtb': 'kernel/' + device + '.dtb',
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
