#!/usr/bin/env python3
"""Audit actual root/recovery payloads without extracting links on the host."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import struct
import tarfile
import tomllib

from orchard.image.integrity import sha
from orchard.hardware import ROOT as HARDWARE


def newc(data):
    result = {}
    offset = 0
    while True:
        header = data[offset:offset + 110]
        if len(header) != 110 or header[:6] != b'070701':
            raise ValueError('Invalid newc header')
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        start = offset + 110
        name = data[start:start + namesize - 1].decode()
        if namesize < 1 or data[start + namesize - 1] != 0:
            raise ValueError('Invalid newc name')
        start = (start + namesize + 3) & ~3
        payload = data[start:start + size]
        if len(payload) != size:
            raise ValueError('Truncated newc member')
        offset = (start + size + 3) & ~3
        if name == 'TRAILER!!!':
            return result
        if name.startswith('/') or '..' in PurePosixPath(name).parts or name in result:
            raise ValueError('Unsafe/duplicate newc member')
        result[name] = (payload, mode)


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


def audit_recovery(image, release, kernel_release, layer):
    framing = json.loads(Path(str(image) + '.json').read_text())
    assert sha(image) == framing['image_sha256']
    components, dtbs = {}, 0
    with image.open('rb') as stream:
        for row in framing['components']:
            stream.seek(row['offset'])
            payload = stream.read(row['bytes'])
            assert len(payload) == row['bytes'] and hashlib.sha256(payload).hexdigest() == row['sha256']
            dtbs += row['name'] == 'dtb'
            components[row['name']] = payload
    profile = HARDWARE / 'boot/initramfs/recovery/boot.json'
    assert components['bootargs'] == json.loads(profile.read_text())['bootargs'].encode(), 'Recovery must preserve the tested standard boot profile'
    recovery = newc(gzip.decompress(components['initramfs']))
    config = json.loads(recovery['etc/orchard/release.json'][0])
    assert (config['release'], config['kernel_release']) == (release, kernel_release)
    # The recovery runs the kernel the installed entry boots: the same modules and regulatory data.
    shared = 0
    for name, data in layer.items():
        if name.startswith(('usr/lib/modules/', 'usr/lib/firmware/')) and not name.endswith(('/vmlinuz', '/initrd')) \
                and '/dtb/' not in name:
            assert recovery[name][0] == data, name
            shared += 1
    for data, mode in recovery.values():
        if stat.S_ISREG(mode):
            check_elf_pages(data)
    for name in ('usr/bin/python3', 'usr/bin/orchard-device', 'init'):
        assert name in recovery
    for name in ('blkid', 'sfdisk', 'mke2fs'):
        data, mode = recovery['usr/sbin/' + name]
        assert stat.S_ISREG(mode) and mode & 0o111 == 0o111 and data.startswith(b'\x7fELF')
    assert recovery['etc/mke2fs.conf'][0]
    for name in ('device.py', 'identity.py', 'adt.py', 'storage-fence'):
        assert 'usr/libexec/orchard/' + name in recovery
    assert not any(name.startswith('root/.ssh') or name.startswith('run/recovery/') for name in recovery)
    return {'members': len(recovery), 'dtbs': dtbs, 'shared_with_layer': shared}


def audit(directory):
    manifest = tomllib.loads((directory / 'release.toml').read_text())
    assert manifest['schema'] == 2 and manifest['distro'] == 'minimal-linux'
    record = json.loads((directory / 'rootfs.json').read_text())
    rootfile = directory / 'rootfs.tar.gz'
    assert rootfile.stat().st_size == record['bytes'] and sha(rootfile) == record['sha256']
    assert manifest['root']['sha256'] == record['sha256']
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
    for name in ('usr/sbin/dropbear', 'usr/sbin/recovery-start-ssh', 'etc/init.d/orchard-diagnostics',
                 'etc/init.d/orchard-dhcp'):
        assert name in entries, name
    assert json.loads(entries['etc/orchard/release.json'][0])['release'] == record['release']
    assert 'usr/libexec/minimal-linux/image_policy.py' in entries
    users = [line.split(':') for line in entries['etc/passwd'][0].decode().splitlines()]
    assert [row[0] for row in users if 1000 <= int(row[2]) < 60000] == ['tablet']
    platforms = {}
    for name, files in sorted(manifest['platforms'].items()):
        for role in ('boot', 'layer'):
            path = directory / files[role]['file']
            assert path.stat().st_size == files[role]['bytes'] and sha(path) == files[role]['sha256']
        layer, description = audit_layer(directory / files['layer']['file'], name, files['layer'])
        assert sorted(description['boards']) == sorted(files['boards'])
        # The installer refuses a layer file the root already has.
        assert not (layer.keys() & {n for n, (data, _, _) in entries.items() if data is not None})
        result = audit_recovery(directory / files['boot']['file'], record['release'],
                                files['layer']['kernel_release'], layer)
        assert result['dtbs'] == len(set(description['boards'].values()))
        platforms[name] = {'boards': sorted(description['boards']), 'recovery': result}
    return {'root_sha256': record['sha256'], 'root_bytes': record['bytes'],
            'expanded_bytes': size, 'root_members': len(entries), 'platforms': platforms,
            'elf_16k_compatible_load_segments': elf_loads,
            'standard_recovery_boot_profile': True, 'signed_regulatory_database_present': True,
            'init': 'BusyBox PID 1 + OpenRC',
            'libc': 'musl', 'compression': 'gzip', 'systemd': False,
            'physical_device_operations_performed': False, 'hardware_validated': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    (args.directory / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
