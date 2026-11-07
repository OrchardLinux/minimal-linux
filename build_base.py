#!/usr/bin/env python3
"""Build a signed-package Alpine base with Podman locally or native OCI/chroot in CI."""
import argparse
import gzip
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile

from snapshot import sha

PROJECT = Path(__file__).resolve().parent
# Per userspace architecture: its recipe directory, where the recipe leaves the root inside the
# build image, and the receipt's description. Both are built by arm64 tools: the armv7 recipe
# unpacks signed ARMv7 packages with the native apk and runs none of their code.
ARCHITECTURES = {
    'aarch64': {'recipe': 'system', 'root': '/',
                'base': 'Alpine 3.24.3 arm64, official merged-/usr, signed APK repositories'},
    'armv7': {'recipe': 'system/armv7', 'root': '/armroot',
              'base': 'Alpine 3.24 armv7, unpacked by arm64 apk without package scripts, merged-/usr, '
                      'signed APK repositories'},
}


def native_root(work, arch='aarch64'):
    if os.geteuid() != 0 or platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise ValueError('Native base builds require Linux ARM64 as root')
    for tool in ('skopeo', 'umoci', 'chroot', 'tar', 'mount', 'umount'):
        if not shutil.which(tool):
            raise ValueError('Missing native base tool: ' + tool)
    recipe = PROJECT / ARCHITECTURES[arch]['recipe']
    containerfile = (recipe / 'Containerfile').read_text()
    matches = re.findall(r'^FROM (\S+@sha256:[0-9a-f]{64})$', containerfile, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError('Expected one digest-pinned Alpine base')
    image = matches[0]
    oci = str(work / 'oci') + ':base'
    subprocess.run(['skopeo', 'copy', '--override-arch', 'arm64', 'docker://' + image, 'oci:' + oci], check=True)
    subprocess.run(['umoci', 'unpack', '--image', oci, str(work / 'bundle')], check=True)
    root = work / 'bundle/rootfs'
    resolver = root / 'etc/resolv.conf'
    backup = work / 'resolv.conf'
    present = resolver.exists() or resolver.is_symlink()
    if present:
        resolver.rename(backup)
    mounted = []
    try:
        resolver.write_bytes(Path('/etc/resolv.conf').read_bytes())
        # Match a build container's pseudo-filesystems without exposing host
        # block devices. These mounts are retired before the public tar export.
        for name, filesystem, options in (('dev', 'tmpfs', 'mode=755,nosuid,noexec'),
                                           ('proc', 'proc', 'ro,nosuid,nodev,noexec'),
                                           ('sys', 'sysfs', 'ro,nosuid,nodev,noexec')):
            target = root / name
            target.mkdir(exist_ok=True)
            subprocess.run(['mount', '-t', filesystem, '-o', options, filesystem, str(target)], check=True)
            mounted.append(target)
        for name, minor in (('null', 3), ('zero', 5), ('random', 8), ('urandom', 9)):
            os.mknod(root / 'dev' / name, stat.S_IFCHR | 0o666, os.makedev(1, minor))
        subprocess.run(['chroot', str(root), '/bin/sh', '-ec',
                        (recipe / 'install-base').read_text()], check=True)
    finally:
        try:
            errors = []
            for target in reversed(mounted):
                try:
                    subprocess.run(['umount', str(target)], check=True)
                except subprocess.CalledProcessError as error:
                    errors.append(error)
            if errors:
                raise RuntimeError('Failed to retire native base mounts') from errors[0]
        finally:
            resolver.unlink(missing_ok=True)
            if present:
                backup.rename(resolver)
    return root / ARCHITECTURES[arch]['root'].lstrip('/'), image


def export(command, path):
    with path.open('xb') as raw, gzip.GzipFile(fileobj=raw, filename='', mode='wb', mtime=0, compresslevel=1) as compressed:
        process = subprocess.Popen(command, stdout=subprocess.PIPE)
        try:
            while chunk := process.stdout.read(1048576):
                compressed.write(chunk)
        finally:
            process.stdout.close()
            result = process.wait()
        if result:
            raise RuntimeError('Base export failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', action='store_true', help='use pinned OCI extraction and native chroot, without Podman')
    parser.add_argument('--arch', choices=sorted(ARCHITECTURES), default='aarch64', help='userspace architecture')
    args = parser.parse_args()
    target = ARCHITECTURES[args.arch]
    recipe = PROJECT / target['recipe']
    receipt = args.output.with_suffix(args.output.suffix + '.json')
    if args.output.exists() or args.output.is_symlink() or receipt.exists() or receipt.is_symlink():
        parser.error('Choose a new base output path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cid = None
    try:
        with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='.alpine-base-') as temp:
            work = Path(temp)
            if args.native:
                root, image = native_root(work, args.arch)
                command = ['tar', '--numeric-owner', '--one-file-system', '-C', str(root), '-cf', '-', '.']
            else:
                tag = 'localhost/orchard-minimal-alpine:3.24.3' + ('' if args.arch == 'aarch64' else '-' + args.arch)
                subprocess.run(['podman', 'build', '-t', tag, '-f', str(recipe / 'Containerfile'), str(recipe)], check=True)
                image = subprocess.check_output(['podman', 'image', 'inspect', '--format', '{{.Id}}', tag], text=True).strip()
                if args.arch == 'aarch64':
                    cid = subprocess.check_output(['podman', 'create', '--network', 'none', tag], text=True).strip()
                    command = ['podman', 'export', cid]
                else:   # only the root the recipe made, not the arm64 image around it
                    command = ['podman', 'run', '--rm', '--network', 'none', image,
                               'tar', '--numeric-owner', '-C', target['root'], '-cf', '-', '.']
            path = work / 'base.tar.gz'
            export(command, path)
            record = {'bytes': path.stat().st_size, 'sha256': sha(path), 'container_image': image,
                      'architecture': args.arch,
                      'containerfile_sha256': sha(recipe / 'Containerfile'),
                      'install_recipe_sha256': sha(recipe / 'install-base'),
                      'base': target['base']}
            os.rename(path, args.output)
            receipt.write_text(json.dumps(record, indent=2) + '\n')
    finally:
        if cid is not None:
            subprocess.run(['podman', 'rm', '-f', cid], check=True)
    print('Base exported:', args.output)


if __name__ == '__main__':
    main()
