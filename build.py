#!/usr/bin/env python3
"""Compose Alpine/OpenRC with an installed hardware package and pinned public inputs."""
import argparse
import gzip
import hashlib
from importlib.metadata import version as package_version
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

from orchard_hardware.image.integrity import sha
from orchard_hardware.image.runtime import files as runtime_files
import orchard_hardware

PROJECT = Path(__file__).resolve().parent
POLICY = PROJECT / 'image/j71b'


def verify_inputs(path):
    spec = json.loads(path.read_text())
    result = {}
    for name, row in spec['files'].items():
        p = Path(row['path'])
        if p.is_symlink() or p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
            raise ValueError('Component differs from receipt: ' + name)
        result[name] = p
    modules = Path(spec['modules']['path'])
    actual = {p.relative_to(modules).as_posix(): sha(p) for p in modules.rglob('*') if p.is_file()}
    if any(p.is_symlink() for p in modules.rglob('*')) or actual != spec['modules']['files']:
        raise ValueError('Module tree differs from receipt')
    result['modules_dir'] = modules
    return result, spec


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


def root_archive(base, base_receipt, components, output, version):
    receipt = json.loads(base_receipt.read_text())
    if base.is_symlink() or base.stat().st_size != receipt['bytes'] or sha(base) != receipt['sha256']:
        raise ValueError('Alpine base differs from receipt')
    kernel_release, additions = runtime_files(components['modules_dir'], POLICY)
    additions.update(overlay())
    hardware = Path(orchard_hardware.__file__).parent
    for source, target in (('busybox', 'usr/libexec/minimal-linux/busybox'),
                           ('dropbear', 'usr/sbin/dropbear'), ('dropbearkey', 'usr/bin/dropbearkey')):
        additions[target] = (components[source].read_bytes(), 0o755)
    for name, target in (('start-ssh', 'usr/sbin/recovery-start-ssh'),
                         ('authorize-key', 'usr/sbin/authorize-key'),
                         ('capture-adt', 'usr/sbin/capture-adt')):
        additions[target] = ((hardware / 'boot/initramfs/recovery' / name).read_bytes(), 0o755)
    additions['etc/udhcpd.conf'] = ((hardware / 'boot/initramfs/recovery/udhcpd.conf').read_bytes(), 0o644)
    additions.update({
        'etc/orchard/release.json': (json.dumps({'protocol': 1, 'release': version, 'profile': 'j71b',
            'kernel_release': kernel_release}).encode(), 0o644),
        'etc/shadow': (b'root:!:0:0:99999:7:::\n', 0o600),
        'etc/hostname': (b'orchard-minimal\n', 0o644),
        'etc/hosts': (b'127.0.0.1 localhost\n::1 localhost\n', 0o644),
        'etc/resolv.conf': (b'# Configure DNS with your network; no baked-in host state.\n', 0o644),
        'etc/issue': (b'Orchard minimal Linux: Alpine / OpenRC\nKey-only access over USB SSH.\n', 0o644),
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
            for service in ('orchard-session', 'orchard-platform', 'orchard-diagnostics',
                            'orchard-dhcp', 'orchard-buttons', 'orchard-ready'):
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
    record = {'schema': 1, 'kind': 'rootfs', 'profile': 'j71b', 'release': version,
              'bytes': path.stat().st_size, 'sha256': sha(path), 'compression': 'gzip',
              'expanded_bytes': expanded, 'members': count, 'kernel_release': kernel_release,
              'base_sha256': receipt['sha256'], 'removed_privileged_modes': privileged}
    (output / 'rootfs.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def manifests(output, version, root):
    document = ('schema = 1\nkind = "orchard.install"\ndistro = "minimal-linux"\n'
                'name = "Minimal Alpine"\nversion = ' + json.dumps(version) + '\n'
                'device = "j71b"\nboot_method = "checkm8-pongo"\nmin_orchard = "0.1.11"\nprotocol = 1\n'
                '\n[install]\ndefault_root = "/minimal"\n')
    for role, name in (('root', 'rootfs.tar.gz'), ('boot', 'recovery.bin'), ('pongo', 'pongo.bin')):
        p = output / name
        row = {'file': name, 'bytes': p.stat().st_size, 'sha256': sha(p)}
        if role == 'root':
            row.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
        document += '\n[' + role + ']\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in row.items())
    path = output / 'j71b-checkm8-pongo.toml'
    path.write_text(document)
    pin = {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}
    (output / 'index.toml').write_text('schema = 1\nkind = "orchard.index"\ndistro = "minimal-linux"\n'
        '\n[devices.j71b.checkm8-pongo]\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in pin.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-receipt', 'inputs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new output directory')
    components, inputs = verify_inputs(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.minimal-build-', dir=args.output.parent) as temp:
        output = Path(temp) / 'release'
        output.mkdir()
        root = root_archive(args.base, args.base_receipt, components, output, args.version)
        command = [sys.executable, '-m', 'orchard_hardware.image.recovery']
        for name in ('base', 'base_receipt'):
            command += ['--' + name.replace('_', '-'), str(getattr(args, name))]
        for name in ('loader', 'kernel', 'dtb', 'busybox', 'dropbear', 'dropbearkey', 'modules_dir'):
            command += ['--' + name.replace('_', '-'), str(components[name])]
        command += ['--policy-dir', str(POLICY), '--root-receipt', str(output / 'rootfs.json'),
                    '--output', str(output / 'recovery.bin')]
        subprocess.run(command, check=True)
        shutil.copyfile(components['pongo'], output / 'pongo.bin')
        manifests(output, args.version, root)
        public_inputs = {**inputs,
            'files': {name: {k: v for k, v in row.items() if k != 'path'}
                      for name, row in inputs['files'].items()},
            'modules': {'files': inputs['modules']['files']}}
        (output / 'build-receipt.json').write_text(json.dumps({'distro': 'minimal-linux',
            'version': args.version, 'hardware_package': package_version('orchard-hardware'),
            'base': json.loads(args.base_receipt.read_text()), 'inputs': public_inputs,
            'physical_device_operations_performed': False, 'hardware_validated': False}, indent=2) + '\n')
        shutil.rmtree(output / '.work', ignore_errors=False)
        os.rename(output, args.output)
    print('Candidate assembled, not hardware-qualified:', args.output)


if __name__ == '__main__':
    main()
