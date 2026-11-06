#!/usr/bin/env python3
"""Audit the actual root and platform layers without extracting links on the host."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import tarfile
import tomllib

from snapshot import root as orchard_root, sha

HARDWARE = None  # the orchard snapshot; main() sets it, else orchard_root() finds it


def check_elf_pages(data):
    """The real J71b kernel uses 16 KiB pages; the container kernel may not."""
    if data[:6] != b'\x7fELF\x02\x01':
        return 0
    assert struct.unpack_from('<H', data, 18)[0] == 183  # AArch64
    offset = struct.unpack_from('<Q', data, 32)[0]
    stride, count = struct.unpack_from('<HH', data, 54)
    loads = 0
    for i in range(count):
        kind, _, file_offset, virtual, _, _, _, alignment = struct.unpack_from('<IIQQQQQQ', data, offset + i * stride)
        if kind == 1:
            assert alignment >= 16384 and file_offset % 16384 == virtual % 16384
            loads += 1
    return loads


def audit_layer(path, platform, row):
    """orchard's platform layer: root-owned files under usr/, of this platform and kernel."""
    files, expanded = {}, 0
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            assert member.isfile() and member.name.startswith('usr/') and member.uid == 0, member.name
            assert member.name not in files and '..' not in PurePosixPath(member.name).parts
            files[member.name] = archive.extractfile(member).read()
            expanded += member.size
    assert (len(files), expanded) == (row['members'], row['expanded_bytes'])
    description = json.loads(files['usr/lib/orchard/platform.json'])
    assert (description['platform'], description['kernel_release']) == (platform, row['kernel_release'])
    base = f'usr/lib/modules/{row["kernel_release"]}/'
    assert base + 'vmlinuz' in files and base + 'initrd' in files
    for line in files['usr/lib/orchard/platform.SHA256SUMS'].decode().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256(files[name.lstrip('/')]).hexdigest() == digest, name
    return files, description


def audit(directory):
    manifest = tomllib.loads((directory / 'release.toml').read_text())
    assert manifest['schema'] == 2 and manifest['distro'] == 'minimal-linux'
    record = json.loads((directory / 'rootfs.json').read_text())
    rootfile = directory / 'rootfs.tar.gz'
    assert rootfile.stat().st_size == record['bytes'] and sha(rootfile) == record['sha256']
    # The checks read the tree the image was made from; orchard.image.root_image made it, and checks it.
    for row in (manifest['root'], manifest['root']['map'], manifest['logo'], manifest['pongo'], manifest['m1n1'],
                manifest['install_tools']):
        path = directory / row['file']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['file']
    entries = {}
    size = elf_loads = 0
    with tarfile.open(rootfile, 'r|gz') as archive:
        for m in archive:
            assert m.name not in entries
            assert not m.name.startswith('/') and '..' not in PurePosixPath(m.name).parts
            assert m.isfile() or m.isdir() or m.issym() or m.islnk()
            # Everything is root's but the one user's home.
            assert m.uid == 0 or m.name == 'home/tablet' or m.name.startswith('home/tablet/'), m.name
            assert m.issym() or not m.mode & 0o6000
            assert not m.name.startswith(('etc/omarchy', 'usr/lib/systemd',
                                          'usr/bin/sudo', 'usr/libexec/omarchy-', 'usr/lib/modules/'))
            data = archive.extractfile(m).read() if m.isfile() else None
            if data is not None:
                elf_loads += check_elf_pages(data)
            entries[m.name] = (data, m.mode, m.linkname)
            size += m.size
    assert len(entries) == record['members'] and size == record['expanded_bytes']
    assert entries['lib'][2] == 'usr/lib'
    assert entries['usr/sbin/init'][2] == '/bin/busybox'
    assert entries['usr/lib/ld-musl-aarch64.so.1'][0].startswith(b'\x7fELF')
    assert 'usr/lib/libc.so.6' not in entries
    assert entries['etc/shadow'][0].startswith(b'root:!:')
    assert 'root/.ssh/authorized_keys' not in entries
    assert 'etc/machine-id' not in entries
    assert b'/sbin/openrc default' in entries['etc/inittab'][0]
    # Every boot is reachable over USB: a serial console login and session SSH.
    assert b'ttyGS0::respawn:/sbin/getty' in entries['etc/inittab'][0]
    assert 'usr/share/orchard/splash' in entries, 'the boot splash for orchard launch'
    for name in ('usr/sbin/dropbear', 'etc/init.d/orchard-ssh', 'etc/init.d/orchard-usb',
                 'etc/runlevels/default/orchard-ssh', 'etc/runlevels/default/orchard-usb',
                 'etc/init.d/orchard-splash', 'etc/orchard/udhcpd.conf'):
        assert name in entries, name
    assert json.loads(entries['etc/orchard/release.json'][0])['release'] == record['release']
    assert 'usr/libexec/minimal-linux/image_policy.py' in entries
    users = [line.split(':') for line in entries['etc/passwd'][0].decode().splitlines()]
    assert [row[0] for row in users if 1000 <= int(row[2]) < 60000] == ['tablet']
    platforms = {}
    for name, files in sorted(manifest['platforms'].items()):
        path = directory / files['layer']['file']
        assert path.stat().st_size == files['layer']['bytes'] and sha(path) == files['layer']['sha256']
        layer, description = audit_layer(directory / files['layer']['file'], name, files['layer'])
        assert sorted(description['boards']) == sorted(files['boards'])
        # The installer refuses a layer file the root already has.
        assert not (layer.keys() & {n for n, (data, _, _) in entries.items() if data is not None})
        platforms[name] = {'boards': sorted(description['boards'])}
    return {'root_sha256': record['sha256'], 'root_bytes': record['bytes'],
            'expanded_bytes': size, 'root_members': len(entries), 'platforms': platforms,
            'elf_16k_compatible_load_segments': elf_loads,
            'signed_regulatory_database_present': True,
            'init': 'BusyBox PID 1 + OpenRC',
            'libc': 'musl', 'compression': 'gzip', 'systemd': False,
            'physical_device_operations_performed': False, 'hardware_validated': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--orchard', type=Path, help='orchard snapshot (default: ORCHARD_CHECKOUT, then .orchard)')
    args = parser.parse_args()
    HARDWARE = orchard_root(args.orchard)
    result = audit(args.directory)
    (args.directory / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
