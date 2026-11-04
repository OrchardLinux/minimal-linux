#!/usr/bin/env python3
"""One Alpine/OpenRC release for every platform: the root, per platform a recovery and orchard's layer.

The root holds no kernel; orchard's platform layer brings kernel, initrd, DTBs
and modules at install, and orchard writes the boot entry.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

from snapshot import command as orchard_command, root as orchard_root, sha

PROJECT = Path(__file__).resolve().parent
POLICY = PROJECT / 'system/image_policy.py'


def verify_inputs(path):
    spec = json.loads(path.read_text())
    result = {}
    for name, row in spec['files'].items():
        p = Path(row['path'])
        if p.is_symlink() or p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
            raise ValueError('Component differs from receipt: ' + name)
        result[name] = p
    return result, spec


def kernels(resolved, explicit=()):
    """{platform: staged kernel bundle} of orchard.inputs' RESOLVED platforms; --kernel-dir overrides one."""
    known = resolved['platforms']
    given = {}
    for value in explicit:
        name, separator, path = value.partition('=')
        if not separator or name not in known:
            raise ValueError(f'Use --kernel-dir PLATFORM=DIRECTORY with a platform of: {", ".join(known)}')
        given[name] = Path(path)
    return {name: given.get(name) or Path(row['kernel']) for name, row in known.items()}


def overlay():
    result = {}
    for path in (PROJECT / 'system/overlay').rglob('*'):
        if path.is_symlink():
            raise ValueError('Source overlay must not contain links')
        if path.is_file():
            name = path.relative_to(PROJECT / 'system/overlay').as_posix()
            mode = 0o755 if name.startswith(('etc/init.d/', 'usr/libexec/')) else 0o644
            result[name] = (path.read_bytes(), mode)
    return result


def root_archive(base, base_receipt, components, output, version, hardware):
    receipt = json.loads(base_receipt.read_text())
    if base.is_symlink() or base.stat().st_size != receipt['bytes'] or sha(base) != receipt['sha256']:
        raise ValueError('Alpine base differs from receipt')
    additions = overlay()
    additions['usr/libexec/minimal-linux/image_policy.py'] = (POLICY.read_bytes(), 0o644)
    for source, target in (('busybox', 'usr/libexec/minimal-linux/busybox'),
                           ('dropbear', 'usr/sbin/dropbear'), ('dropbearkey', 'usr/bin/dropbearkey')):
        additions[target] = (components[source].read_bytes(), 0o755)
    # m1n1 paints it when the entry starts, before the kernel (orchard docs/boot-contract.md).
    additions['usr/share/orchard/splash'] = (components['splash'].read_bytes(), 0o644)
    additions['usr/sbin/capture-adt'] = ((hardware / 'boot/initramfs/recovery/capture-adt').read_bytes(), 0o755)
    additions.update({
        'etc/orchard/release.json': (json.dumps({'protocol': 1, 'release': version}).encode(), 0o644),
        # root stays locked; the installer gives the user its password.
        'etc/shadow': (b'root:!:0:0:99999:7:::\ntablet:!:0:0:99999:7:::\n', 0o600),
        'etc/hostname': (b'orchard-minimal\n', 0o644),
        'etc/hosts': (b'127.0.0.1 localhost\n::1 localhost\n', 0o644),
        'etc/resolv.conf': (b'# Configure DNS with your network; no baked-in host state.\n', 0o644),
        'etc/issue': (b'Minimal Alpine (Orchard)\n', 0o644),
    })
    seen, dirs, privileged = set(), set(), []
    expanded = count = 0
    path = output / 'rootfs.tar.gz'
    with path.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=1) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as target:
            def add(member, data=None):
                nonlocal expanded, count
                if member.name in seen:
                    raise ValueError('Duplicate output member: ' + member.name)
                seen.add(member.name)
                if member.isdir():
                    dirs.add(member.name)
                expanded += member.size
                count += 1
                target.addfile(member, io.BytesIO(data) if data is not None else None)

            with tarfile.open(base, 'r|gz') as source:
                for member in source:
                    name = str(PurePosixPath(member.name))
                    if name == '.':
                        continue
                    if name.startswith('/') or '..' in PurePosixPath(name).parts:
                        raise ValueError('Unsafe base member')
                    if name.startswith('usr/lib/modules/'):
                        raise ValueError("The Alpine base has kernel modules; orchard's platform layer provides them")
                    if (name in additions or name.startswith('etc/runlevels/') or
                            any(name.startswith(p + '/') for p in ('dev', 'proc', 'sys', 'run'))):
                        continue
                    if name.startswith('root/.ssh') or name.startswith('.orchard-'):
                        raise ValueError('Private/reserved input member')
                    if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                        raise ValueError('Special base member: ' + name)
                    member.name = name
                    if member.mode & 0o6000:
                        privileged.append(name)
                        member.mode &= ~0o6000
                    if name == 'root':
                        member.mode = 0o700
                    data = source.extractfile(member).read() if member.isfile() else None
                    add(member, data)

            def parents(name):
                for parent in reversed(PurePosixPath(name).parents):
                    parent = str(parent)
                    if parent == '.':
                        continue
                    if parent in seen:
                        if parent not in dirs:
                            raise ValueError('Non-directory overlay parent: ' + parent)
                        continue
                    member = tarfile.TarInfo(parent)
                    member.type, member.mode = tarfile.DIRTYPE, 0o755
                    add(member)

            for name, (data, mode) in sorted(additions.items()):
                parents(name)
                member = tarfile.TarInfo(name)
                member.mode, member.size = mode, len(data)
                add(member, data)
            for service in ('orchard-platform', 'orchard-usb', 'orchard-ssh', 'orchard-buttons',
                            'orchard-splash', 'orchard-ready'):
                name = 'etc/runlevels/default/' + service
                parents(name)
                member = tarfile.TarInfo(name)
                member.type, member.mode, member.linkname = tarfile.SYMTYPE, 0o777, '/etc/init.d/' + service
                add(member)
            for level in ('sysinit', 'boot', 'shutdown'):
                parents('etc/runlevels/' + level + '/placeholder')
            # Standard OpenRC cgroup setup only; no stock device/driver reprobe.
            member = tarfile.TarInfo('etc/runlevels/sysinit/cgroups')
            member.type, member.mode, member.linkname = tarfile.SYMTYPE, 0o777, '/etc/init.d/cgroups'
            add(member)
    record = {'schema': 2, 'kind': 'rootfs', 'release': version,
              'bytes': path.stat().st_size, 'sha256': sha(path), 'compression': 'gzip',
              'expanded_bytes': expanded, 'members': count,
              'base_sha256': receipt['sha256'], 'removed_privileged_modes': privileged}
    (output / 'rootfs.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def table(name, row):
    return '\n[' + name + ']\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in row.items())


def receipt(path):
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def manifests(output, version, root, platforms, orchard):
    """release.toml (orchard's schema 2, every platform) and the index that pins it."""
    document = ('schema = 2\nkind = "orchard.install"\ndistro = "minimal-linux"\n'
                'name = "Minimal Alpine"\nversion = ' + json.dumps(version) + '\n'
                'boot_method = "checkm8-pongo"\nmin_orchard = "0.2.0"\nprotocol = 1\n')
    document += table('orchard', orchard)
    # The one regular user gets its password at install; no lock screen, so no PIN.
    # The ready file is minimal-ready's, once services and the splash are done.
    document += table('install', {'default_root': '/minimal', 'ready': '/run/orchard-ready'})
    document += table('install.account', {'user': 'tablet', 'password': True, 'pin': False,
                                          'passwordless_sudo': False})
    row = receipt(output / 'rootfs.tar.gz')
    row.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
    document += table('root', row) + table('pongo', receipt(output / 'pongo.bin'))
    for name, files in sorted(platforms.items()):
        document += f'\n[platforms.{name}]\nboards = {json.dumps(files["boards"])}\n'
        document += table(f'platforms.{name}.boot', files['boot']) + table(f'platforms.{name}.layer', files['layer'])
    path = output / 'release.toml'
    path.write_text(document)
    (output / 'index.toml').write_text('schema = 2\nkind = "orchard.index"\ndistro = "minimal-linux"\n'
                                       + table('release', receipt(path)))
    return path


def recovery(orchard, output, base, base_receipt, components, platform_name, bundle, boards):
    """The platform's RAM recovery, which starts every board of it."""
    dtbs = [bundle / 'dtbs' / (dtb + '.dtb') for dtb in sorted(set(boards.values()))]
    image = output / f'recovery-{platform_name}.bin'
    command = [*(f'--dtb={path}' for path in dtbs),
               '--base', str(base), '--base-receipt', str(base_receipt),
               '--kernel', str(bundle / 'Image.gz'), '--modules-dir', str(bundle / 'lib/modules')]
    for name in ('loader', 'busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw'):
        command += ['--' + name.replace('_', '-'), str(components[name])]
    command += ['--logo', str(components['logo'])]  # the Alpine mark, drawn by orchard's m1n1
    command += ['--root-receipt', str(output / 'rootfs.json'), '--output', str(image)]
    orchard_command(orchard, 'image.recovery', *command)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in ('base', 'base-receipt', 'inputs', 'orchard-inputs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--orchard', type=Path, help='orchard snapshot (default: ORCHARD_CHECKOUT, then .orchard)')
    parser.add_argument('--kernel-dir', action='append', default=[], metavar='PLATFORM=DIRECTORY',
                        help="a platform's staged kernel bundle instead of the one orchard.inputs names")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new output directory')
    orchard = orchard_root(args.orchard)
    components, inputs = verify_inputs(args.inputs)
    resolved = json.loads(args.orchard_inputs.read_text())
    try:
        bundles = kernels(resolved, args.kernel_dir)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.minimal-build-', dir=args.output.parent) as temp:
        output = Path(temp) / 'release'
        output.mkdir()
        root = root_archive(args.base, args.base_receipt, components, output, args.version, orchard)
        platforms = {}
        for name, bundle in bundles.items():
            layer_receipt = Path(temp) / f'layer-{name}.json'
            orchard_command(orchard, 'image.platform', name, '--output', output, '--kernel-dir', bundle,
                            '--busybox', components['busybox'], '--receipt', layer_receipt, stdout=subprocess.DEVNULL)
            layer = json.loads(layer_receipt.read_text())
            image = recovery(orchard, output, args.base, args.base_receipt, components, name, bundle,
                             resolved['platforms'][name]['boards'])
            platforms[name] = {'boards': layer.pop('boards'), 'layer': layer, 'boot': receipt(image)}
        shutil.copyfile(components['pongo'], output / 'pongo.bin')
        revision = resolved['orchard']
        manifests(output, args.version, root, platforms, revision)
        public_inputs = {**inputs, 'files': {name: {k: v for k, v in row.items() if k != 'path'}
                                             for name, row in inputs['files'].items()}}
        (output / 'build-receipt.json').write_text(json.dumps({'distro': 'minimal-linux',
            'version': args.version, 'orchard': revision, 'platforms': platforms,
            'base': json.loads(args.base_receipt.read_text()), 'inputs': public_inputs,
            'physical_device_operations_performed': False, 'hardware_validated': False}, indent=2) + '\n')
        shutil.rmtree(output / '.work', ignore_errors=True)
        os.rename(output, args.output)
    print('Candidate assembled, not hardware-qualified:', args.output)


if __name__ == '__main__':
    main()
