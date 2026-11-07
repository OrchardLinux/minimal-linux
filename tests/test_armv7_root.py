"""The armv7 root: built by arm64 tools only, released on its own from orchard's 32-bit index. No builds."""
import gzip
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import snapshot  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, PROJECT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('minimal_build_armv7', 'build.py')
audit = load('minimal_audit_armv7', 'audit.py')
base = load('minimal_base_armv7', 'build_base.py')


def elf(arch):
    """The first bytes of an executable of ARCH."""
    header = bytearray(64)
    header[:4] = b'\x7fELF'
    header[4] = audit.ARCHITECTURES[arch]['class']
    header[5:7] = b'\x01\x01'
    struct.pack_into('<HH', header, 16, 2, audit.ARCHITECTURES[arch]['machine'])
    return bytes(header)


class Recipe(unittest.TestCase):
    def test_runs_no_armv7_code(self):
        """Packages are unpacked by the arm64 apk without their scripts; nothing chroots into the root."""
        recipe = (PROJECT / 'system/armv7/install-base').read_text()
        self.assertIn('--arch armv7', recipe)
        self.assertIn('--no-scripts', recipe)
        self.assertNotIn('chroot', recipe)
        self.assertNotIn('qemu', recipe.lower())
        self.assertNotIn('binfmt', recipe)
        containerfile = (PROJECT / 'system/armv7/Containerfile').read_text()
        self.assertEqual(containerfile.split('FROM ')[1].split()[0],
                         (PROJECT / 'system/Containerfile').read_text().split('FROM ')[1].split()[0],
                         'both roots come from the one pinned arm64 Alpine image')

    def test_same_services_as_the_arm64_root(self):
        """The armv7 root carries the arm64 root's packages, plus Alpine's dropbear and udhcpd."""
        def packages(path):
            text = (PROJECT / path).read_text().replace('\\\n', ' ')
            line = next(line for line in text.splitlines() if ' add ' in line and 'apk ' in line)
            return set(line.split(' add ', 1)[1].split()) - {'--no-cache'}
        arm64 = packages('system/install-base') - {'merge-usr'}
        self.assertLessEqual(arm64, packages('system/armv7/install-base'))
        self.assertLessEqual({'dropbear', 'busybox-extras'}, packages('system/armv7/install-base'))


class Selection(unittest.TestCase):
    def test_platform_descriptors_name_the_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'platforms').mkdir()
            for name, arch in (('apple-16k', 'arm64'), ('apple-armv7', 'arm')):
                (Path(directory) / 'platforms' / f'{name}.toml').write_text(f'[kernel]\narch = "{arch}"\n')
            self.assertEqual(snapshot.platforms(directory), {'apple-16k': 'aarch64', 'apple-armv7': 'armv7'})

    def test_base_receipt_records_the_architecture(self):
        self.assertEqual(base.ARCHITECTURES['armv7']['recipe'], 'system/armv7')
        self.assertEqual(base.ARCHITECTURES['armv7']['root'], '/armroot')

    def test_pinning_without_orchards_arm64_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('splash', 'logo', 'loader'):
                (root / name).write_bytes(name.encode())
            command = [sys.executable, str(PROJECT / 'pin_components.py'), '--splash', root / 'splash',
                       '--logo', root / 'logo']
            result = subprocess.run([*map(str, command), '--output', str(root / 'out')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(json.loads((root / 'out/inputs.json').read_text())['files']), ['logo', 'splash'])
            partial = subprocess.run([*map(str, command), '--loader', str(root / 'loader'),
                                      '--output', str(root / 'other')], capture_output=True, text=True)
            self.assertNotEqual(partial.returncode, 0)


class Root(unittest.TestCase):
    def base(self, directory, arch='armv7'):
        path = directory / 'base.tar.gz'
        with gzip.open(path, 'wb') as raw, tarfile.open(fileobj=raw, mode='w') as archive:
            for name, data in (('usr/bin/busybox-extras', elf('armv7')), ('etc/apk/arch', b'armv7\n')):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o755
                archive.addfile(member, io.BytesIO(data))
        receipt = directory / 'base.tar.gz.json'
        receipt.write_text(json.dumps({'bytes': path.stat().st_size, 'sha256': snapshot.sha(path),
                                       'architecture': arch}))
        return path, receipt

    def hardware(self, directory):
        script = directory / 'orchard/boot/initramfs/recovery/capture-adt'
        script.parent.mkdir(parents=True)
        script.write_text('#!/bin/sh\n')
        return directory / 'orchard'

    def test_armv7_root_has_alpines_tools_not_orchards(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path, receipt = self.base(directory)
            components = {'splash': directory / 'base.tar.gz.json'}
            output = directory / 'release'
            output.mkdir()
            record = build.root_archive(path, receipt, components, output, '1', self.hardware(directory), 'armv7')
            self.assertEqual(record['architecture'], 'armv7')
            with tarfile.open(output / 'rootfs.tar.gz') as archive:
                names = archive.getnames()
                copied = archive.extractfile('usr/libexec/minimal-linux/busybox').read()
            self.assertEqual(copied, elf('armv7'))
            self.assertNotIn('usr/sbin/dropbear', names, "orchard's arm64 dropbear stays out")

    def test_an_arm64_base_is_refused_for_an_armv7_root(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path, receipt = self.base(directory, arch='aarch64')
            with self.assertRaisesRegex(ValueError, 'not armv7'):
                build.root_archive(path, receipt, {}, directory, '1', self.hardware(directory), 'armv7')

    def test_elf_files_must_match_the_root(self):
        self.assertTrue(audit.check_elf_arch(elf('armv7'), 'armv7'))
        self.assertFalse(audit.check_elf_arch(b'#!/bin/sh\n', 'armv7'))
        with self.assertRaises(AssertionError):
            audit.check_elf_arch(elf('aarch64'), 'armv7')


class Manifest(unittest.TestCase):
    def test_loaders_and_boards_come_from_the_32_bit_index(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in ('root.blocks.zst', 'root.map.json', 'cascadia-p105.bin', 'install-tools-armv7.tar.gz',
                         'platform-apple-armv7.tar.gz'):
                (source / name).write_bytes(name.encode())
            root = {**build.receipt(source / 'root.blocks.zst'), 'compression': 'zstd', 'format': 'blocks',
                    'expanded_bytes': 100, 'members': 3, 'map': build.receipt(source / 'root.map.json')}
            # orchard's platforms-armv7.toml: a Cascadia loader per board.
            offered = {'architecture': 'arm', 'loaders': {'cascadia': {'p105': build.receipt(source / 'cascadia-p105.bin')}},
                       'install_tools': build.receipt(source / 'install-tools-armv7.tar.gz'),
                       'platforms': {'apple-armv7': {**build.receipt(source / 'platform-apple-armv7.tar.gz'),
                                                     'compression': 'gzip', 'expanded_bytes': 10, 'members': 2,
                                                     'kernel_release': '6.12-armv7', 'boards': ['p105']}}}
            manifest = tomllib.loads(build.manifests(source, '1', root, offered,
                                                     {'commit': 'c' * 40, 'modified': False}, 'armv7').read_text())
            self.assertEqual(manifest['boot_method'], 'recovery-autogo')
            self.assertEqual(manifest['cascadia']['p105']['file'], 'cascadia-p105.bin')
            self.assertNotIn('logo', manifest)
            self.assertNotIn('pongo', manifest)
            self.assertNotIn('m1n1', manifest)
            self.assertEqual(manifest['platforms']['apple-armv7']['boards'], ['p105'])
            self.assertEqual(manifest['root']['file'], 'root.blocks.zst')


if __name__ == '__main__':
    unittest.main()
