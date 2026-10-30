"""Minimal image publication uses immutable URLs and exact local receipts."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import tomllib

from orchard_hardware.image.publish import publish


def pin(path):
    return f'file="{path.name}"\nbytes={path.stat().st_size}\nsha256="{hashlib.sha256(path.read_bytes()).hexdigest()}"\n'


class Publication(unittest.TestCase):
    def test_minimal_manifest_is_rewritten_and_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'release'
            source.mkdir()
            manifest = ('schema=1\nkind="orchard.install"\ndistro="minimal-linux"\n'
                        'device="j71b"\nboot_method="checkm8-pongo"\n')
            for role in ('root', 'boot', 'pongo'):
                path = source / (role + '.bin')
                path.write_bytes(role.encode())
                manifest += '[' + role + ']\n' + pin(path)
            target = source / 'j71b.toml'
            target.write_text(manifest)
            (source / 'index.toml').write_text('schema=1\nkind="orchard.index"\ndistro="minimal-linux"\n'
                '[devices.j71b.checkm8-pongo]\n' + pin(target))
            output = root / 'hosted'
            result = publish(source, 'v0.1.0', output, distro='minimal-linux')
            index = tomllib.loads(result.read_text())
            receipt = index['devices']['j71b']['checkm8-pongo']
            self.assertEqual(receipt['url'], 'https://github.com/OrchardLinux/minimal-linux/releases/download/v0.1.0/j71b.toml')
            self.assertEqual(receipt['sha256'], hashlib.sha256((output / 'j71b.toml').read_bytes()).hexdigest())
            hosted = tomllib.loads((output / 'j71b.toml').read_text())
            for role in ('root', 'boot', 'pongo'):
                self.assertNotIn('file', hosted[role])
                self.assertEqual((output / (role + '.bin')).read_bytes(), role.encode())
            self.assertEqual(target.read_text(), manifest)
            with self.assertRaises(FileExistsError):
                publish(source, 'v0.1.0', output, distro='minimal-linux')

    def test_repository_path_cannot_escape_the_distro_name(self):
        with self.assertRaisesRegex(ValueError, 'Invalid distro'):
            publish(Path('/unused'), 'v1.0.0', Path('/unused'), distro='../other')


if __name__ == '__main__':
    unittest.main()
