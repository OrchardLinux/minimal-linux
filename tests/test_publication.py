"""Minimal image publication uses immutable URLs and exact local receipts."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import tomllib

from orchard.image.publish import publish
from orchard.manifests import validate

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_build', PROJECT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def release(source):
    """A fake release: the root image, its logo, and what orchard offers."""
    for name in ('root.blocks.zst', 'root.map.json', 'logo.bin', 'pongo.bin', 'm1n1.bin', 'install-tools.tar.gz',
                 'platform-apple-16k.tar.gz', 'platform-apple-4k.tar.gz'):
        (source / name).write_bytes(name.encode())
    platforms = {name: {**build.receipt(source / f'platform-{name}.tar.gz'), 'compression': 'gzip', 'expanded_bytes': 10,
                        'members': 2, 'kernel_release': '7.3-' + name, 'boards': boards}
                 for name, boards in (('apple-16k', ['j71b']), ('apple-4k', ['n61']))}
    root = {**build.receipt(source / 'root.blocks.zst'), 'compression': 'zstd', 'format': 'blocks', 'expanded_bytes': 100,
            'members': 3, 'map': build.receipt(source / 'root.map.json')}
    offered = {'loaders': {'pongo': build.receipt(source / 'pongo.bin'), 'm1n1': build.receipt(source / 'm1n1.bin')},
               'install_tools': build.receipt(source / 'install-tools.tar.gz'), 'platforms': platforms}
    return build.manifests(source, '0.1.0', root, offered, {'commit': 'c' * 40, 'modified': False})


def armv7_release(source):
    """A fake 32-bit release: its root image, and what orchard's platforms-armv7.toml offers."""
    for name in ('root.blocks.zst', 'root.map.json', 'cascadia-p105.bin', 'install-tools-armv7.tar.gz',
                 'platform-apple-armv7.tar.gz'):
        (source / name).write_bytes(b'armv7 ' + name.encode())
    root = {**build.receipt(source / 'root.blocks.zst'), 'compression': 'zstd', 'format': 'blocks', 'expanded_bytes': 100,
            'members': 3, 'map': build.receipt(source / 'root.map.json')}
    offered = {'architecture': 'arm', 'loaders': {'cascadia': {'p105': build.receipt(source / 'cascadia-p105.bin')}},
               'install_tools': build.receipt(source / 'install-tools-armv7.tar.gz'),
               'platforms': {'apple-armv7': {**build.receipt(source / 'platform-apple-armv7.tar.gz'),
                                             'compression': 'gzip', 'expanded_bytes': 10, 'members': 2,
                                             'kernel_release': '6.12-armv7', 'boards': ['p105'], 'architecture': 'arm'}}}
    return build.manifests(source, '0.1.0', root, offered, {'commit': 'c' * 40, 'modified': False}, 'armv7')


class Publication(unittest.TestCase):
    def test_one_manifest_for_every_platform_with_the_account(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            manifest = tomllib.loads(release(source).read_text())
            validate(manifest), validate(tomllib.loads((source / 'index.toml').read_text()))
            self.assertEqual(manifest['install'], {
                'default_root': '/minimal', 'ready': '/run/orchard-ready',
                'account': {'user': 'tablet', 'password': True, 'pin': False, 'passwordless_sudo': False}})
            self.assertEqual(sorted(manifest['platforms']), ['apple-16k', 'apple-4k'])

    def test_minimal_manifest_is_rewritten_and_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'release'
            source.mkdir()
            target = release(source)
            original = target.read_text()
            output = root / 'hosted'
            result = publish(source, 'v0.1.0', output, distro='minimal-linux')
            receipt = tomllib.loads(result.read_text())['release']
            self.assertEqual(receipt['url'], 'https://github.com/OrchardLinux/minimal-linux/releases/download/v0.1.0/release.toml')
            self.assertEqual(receipt['sha256'], hashlib.sha256((output / 'release.toml').read_bytes()).hexdigest())
            hosted = tomllib.loads((output / 'release.toml').read_text())
            for row in (hosted['root'], hosted['root']['map'], hosted['logo'], hosted['pongo'], hosted['m1n1'],
                        hosted['install_tools'], *(files['layer'] for files in hosted['platforms'].values())):
                self.assertNotIn('file', row)
                self.assertIn('/releases/download/v0.1.0/', row['url'])
            self.assertEqual((output / 'pongo.bin').read_bytes(), b'pongo.bin')
            self.assertEqual(target.read_text(), original)
            with self.assertRaises(FileExistsError):
                publish(source, 'v0.1.0', output, distro='minimal-linux')

    def test_both_roots_publish_as_one_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arm64, armv7 = root / 'release', root / 'release-armv7'
            arm64.mkdir(), armv7.mkdir()
            release(arm64), armv7_release(armv7)
            output = root / 'hosted'
            index = tomllib.loads(publish([arm64, armv7], 'v0.1.0', output, distro='minimal-linux').read_text())
            validate(index)
            base = 'https://github.com/OrchardLinux/minimal-linux/releases/download/v0.1.0/'
            self.assertEqual(index['release']['url'], base + 'release.toml')
            self.assertEqual(index['releases']['armv7']['url'], base + 'release-armv7.toml')
            hosted = tomllib.loads((output / 'release-armv7.toml').read_text())
            validate(hosted)
            self.assertEqual(hosted['root']['url'], base + 'root-armv7.blocks.zst')
            self.assertEqual((output / 'root-armv7.blocks.zst').read_bytes(), b'armv7 root.blocks.zst')
            self.assertEqual((output / 'root.blocks.zst').read_bytes(), b'root.blocks.zst')

    def test_repository_path_cannot_escape_the_distro_name(self):
        with self.assertRaisesRegex(ValueError, 'Invalid distro'):
            publish(Path('/unused'), 'v1.0.0', Path('/unused'), distro='../other')


if __name__ == '__main__':
    unittest.main()
