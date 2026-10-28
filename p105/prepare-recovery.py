#!/usr/bin/env python3
"""Compose an owner-bound ARMv7 recovery root from signed Alpine packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tarfile

import orchard_hardware


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(archive, root):
    """Normalize guest links, and refuse archive writes through outside paths."""
    with tarfile.open(archive) as stream:
        for member in stream:
            name = member.name.removeprefix('./')
            if name in ('', '.'):
                continue
            if name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('Unsafe base archive path')
            path = root/name
            if not path.parent.resolve().is_relative_to(root.resolve()):
                raise ValueError('Base archive parent escapes its root')
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                path.mkdir(exist_ok=True)
            elif member.issym():
                target = root/member.linkname.lstrip('/') if member.linkname.startswith('/') else path.parent/member.linkname
                if not target.resolve().is_relative_to(root.resolve()):
                    raise ValueError('Base archive link escapes its root')
                if path.is_dir() and not path.is_symlink():
                    raise ValueError('Base archive would replace a directory with a link')
                path.unlink(missing_ok=True)
                path.symlink_to(os.path.relpath(target, path.parent))
            elif member.isfile():
                if path.is_symlink():
                    path.unlink()
                with stream.extractfile(member) as source, path.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
                path.chmod(member.mode & 0o777)
            elif member.islnk():
                target = root/member.linkname.removeprefix('./')
                if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
                    raise ValueError('Unsafe base archive hard link')
                path.unlink(missing_ok=True)
                shutil.copyfile(target, path)
            else:
                raise ValueError('Special file in recovery base')


def needed32(data):
    if data[:7] != b'\x7fELF\x01\x01\x01' or data[18:20] != b'\x28\x00':
        raise ValueError('Expected ARM32 ELF')
    offset = struct.unpack_from('<I', data, 28)[0]
    size, count = struct.unpack_from('<HH', data, 42)
    loads, dynamic = [], None
    for index in range(count):
        kind, start, virtual, _, length, _, _, _ = struct.unpack_from('<IIIIIIII', data, offset+index*size)
        if kind == 1:
            loads.append((virtual, start, length))
        elif kind == 2:
            dynamic = start, length
    names, strings = [], None
    if dynamic is None:
        return set()
    for index in range(dynamic[0], sum(dynamic), 8):
        tag, value = struct.unpack_from('<II', data, index)
        if tag == 0:
            break
        if tag == 1:
            names.append(value)
        if tag == 5:
            strings = value
    for virtual, start, length in loads:
        if strings is not None and virtual <= strings < virtual+length:
            start += strings-virtual
            return {data[start+name:data.index(b'\0', start+name)].decode('ascii') for name in names}
    if names:
        raise ValueError('ELF strings outside load segments')
    return set()


def ssh_closure(root):
    output = root/'usr/libexec/orchard-p105/ssh'
    (output/'lib').mkdir(parents=True)
    binary = root/'usr/sbin/dropbear'
    shutil.copyfile(binary, output/'dropbear')
    (output/'dropbear').chmod(0o755)
    pending = needed32(binary.read_bytes()) | {'ld-musl-armhf.so.1'}
    done = set()
    while pending:
        name = pending.pop()
        if '/' in name:
            raise ValueError('Unexpected SSH library name')
        candidates = [p for directory in ('lib', 'usr/lib') if (p := root/directory/name).is_file()]
        if not candidates:
            raise ValueError('Missing ARMv7 SSH library: '+name)
        source = candidates[0]
        shutil.copyfile(source, output/'lib'/name)
        (output/'lib'/name).chmod(0o755)
        done.add(name)
        pending |= needed32(source.read_bytes())-done
    return sorted(done)


def prepare(args):
    root = args.output.expanduser().absolute()
    project = Path(__file__).resolve().parents[1]
    if root.exists() or root.is_symlink() or root.resolve().is_relative_to(project):
        raise ValueError('Choose a fresh private root outside the project')
    if root.resolve().is_relative_to(args.initramfs.resolve()):
        raise ValueError('Keep the recovery output outside its owner input tree')
    receipt = json.loads(args.base_receipt.read_text())
    if (receipt.get('architecture') != 'armv7h' or not receipt.get('signed_apk') or
            args.base.stat().st_size != receipt['bytes'] or sha(args.base) != receipt['sha256']):
        raise ValueError('Recovery base differs from its signed-package receipt')
    target = json.loads(args.target.read_text())
    if isinstance(target.get('ecid'), str) and re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)', target['ecid']):
        target['ecid'] = int(target['ecid'], 16 if target['ecid'].lower().startswith('0x') else 10)
    if type(target.get('ecid')) is not int or not 0 < target['ecid'] < 2**64:
        raise ValueError('Expected the owner target identity')
    calibration = args.calibration.read_bytes()
    if not calibration or (args.initramfs/'lib/firmware/mtcal.bin').read_bytes() != calibration:
        raise ValueError('Recovery root and owner calibration differ')
    os.umask(0o077)
    shutil.copytree(args.initramfs, root, symlinks=True)
    extract(args.base, root)
    for relative in ('root/.ssh', 'etc/dropbear'):
        path = root/relative
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    for directory in ('dev','proc','sys','run','tmp','root','.ssh','etc/orchard'):
        (root/directory).mkdir(parents=True, exist_ok=True)
    (root/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
    (root/'etc/group').write_text('root:x:0:\n')
    (root/'etc/shadow').write_text('root:*:0:0:99999:7:::\n')
    (root/'etc/shadow').chmod(0o600)
    for name in ('sh','mount','umount','ip','mkdir','cat','chmod','date','ln','basename','touch',
                 'kill','sleep','ls','mv','cp','chown','grep','awk','sha256sum','hostname','head','getty'):
        path = root/'bin'/name
        path.unlink(missing_ok=True)
        path.symlink_to('busybox.static')
    resources = Path(orchard_hardware.__file__).parent/'runtime/p105/recovery'
    runtime = root/'usr/libexec/orchard-p105'
    runtime.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resources/'device.py', runtime/'device.py')
    wrapper = root/'usr/bin/orchard-device'
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/libexec/orchard-p105/device.py "$@"\n')
    wrapper.chmod(0o755)
    config = {'schema': 1, 'profile': 'p105', 'ecid': target['ecid'], 'release': args.release,
              'calibration_sha256': hashlib.sha256(calibration).hexdigest(),
              'base_sha256': receipt['sha256']}
    (root/'etc/orchard/p105.json').write_text(json.dumps(config)+'\n')
    libraries = ssh_closure(root)
    needed32((root/'usr/bin/python3').read_bytes())
    result = {'schema':1, 'private':True, 'publishable':False, 'profile':'p105',
              'architecture':'armv7h', 'ecid':target['ecid'], 'base':receipt,
              'ssh_libraries':libraries, 'release':args.release}
    (root.parent/(root.name+'.json')).write_text(json.dumps(result,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base','base-receipt','initramfs','calibration','target','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--release', default='p105-recovery-dev')
    args = parser.parse_args()
    prepare(args)


if __name__ == '__main__':
    main()
