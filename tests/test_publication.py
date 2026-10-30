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
    """A fake release: one root, Pongo, and a recovery and layer per platform."""
    for name in ('rootfs.tar.gz', 'pongo.bin', 'recovery-apple-16k.bin', 'platform-apple-16k.tar.gz',
                 'recovery-apple-4k.bin', 'platform-apple-4k.tar.gz'):
        (source / name).write_bytes(name.encode())
    platforms = {}
    for name, boards in (('apple-16k', ['j71b']), ('apple-4k', ['n61'])):
        layer = build.receipt(source / f'platform-{name}.tar.gz')
        layer.update(compression='gzip', expanded_bytes=10, members=2, kernel_release='7.3-' + name)
        platforms[name] = {'boards': boards, 'boot': build.receipt(source / f'recovery-{name}.bin'), 'layer': layer}
    return build.manifests(source, '0.1.0', {'compression': 'gzip', 'expanded_bytes': 100, 'members': 3},
                           platforms, {'commit': 'c' * 40, 'modified': False})


class Publication(unittest.TestCase):
    def test_one_manifest_for_every_platform_with_the_account(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            manifest = tomllib.loads(release(source).read_text())
            validate(manifest), validate(tomllib.loads((source / 'index.toml').read_text()))
            self.assertEqual(manifest['install'], {'default_root': '/minimal', 'account': True})
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
            for row in (hosted['root'], hosted['pongo'], *(files[role] for files in hosted['platforms'].values()
                                                          for role in ('boot', 'layer'))):
                self.assertNotIn('file', row)
                self.assertIn('/releases/download/v0.1.0/', row['url'])
            self.assertEqual((output / 'pongo.bin').read_bytes(), b'pongo.bin')
            self.assertEqual(target.read_text(), original)
            with self.assertRaises(FileExistsError):
                publish(source, 'v0.1.0', output, distro='minimal-linux')

    def test_repository_path_cannot_escape_the_distro_name(self):
        with self.assertRaisesRegex(ValueError, 'Invalid distro'):
            publish(Path('/unused'), 'v1.0.0', Path('/unused'), distro='../other')


if __name__ == '__main__':
    unittest.main()
