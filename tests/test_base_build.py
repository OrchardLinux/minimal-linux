"""Native base preparation uses the pinned OCI and restores host-only DNS data."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('base_builder', Path(__file__).resolve().parents[1] / 'build_base.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class NativeBase(unittest.TestCase):
    def exercise(self, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if command[0] == 'umoci':
                    resolver = work / 'bundle/rootfs/etc/resolv.conf'
                    resolver.parent.mkdir(parents=True)
                    resolver.write_text('original OCI resolver\n')
                if command[0] == 'chroot' and fail:
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(base.os, 'geteuid', return_value=0), \
                 patch.object(base.platform, 'system', return_value='Linux'), \
                 patch.object(base.platform, 'machine', return_value='aarch64'), \
                 patch.object(base.shutil, 'which', return_value='/tool'), \
                 patch.object(base.os, 'mknod', side_effect=lambda path, *_: Path(path).touch(), create=True), \
                 patch.object(base.subprocess, 'run', side_effect=run):
                if fail:
                    with self.assertRaises(subprocess.CalledProcessError):
                        base.native_root(work)
                else:
                    root, image = base.native_root(work)
                    self.assertIn('@sha256:', image)
                    self.assertEqual(root, work / 'bundle/rootfs')
            self.assertEqual((work / 'bundle/rootfs/etc/resolv.conf').read_text(), 'original OCI resolver\n')
            self.assertEqual([c[0] for c in commands],
                             ['skopeo', 'umoci', 'mount', 'mount', 'mount', 'chroot', 'umount', 'umount', 'umount'])
            self.assertIn('--override-arch', commands[0])
            self.assertIn('apk add --no-cache', commands[5][-1])
            self.assertEqual([Path(c[-1]).name for c in commands[-3:]], ['sys', 'proc', 'dev'])

    def test_native_base_uses_the_shared_install_recipe(self):
        self.exercise()

    def test_dns_is_restored_even_when_package_installation_fails(self):
        self.exercise(fail=True)

    def test_native_base_refuses_non_root_before_fetching(self):
        with patch.object(base.os, 'geteuid', return_value=1000), \
             patch.object(base.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'as root'):
                base.native_root(Path('/unused'))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
