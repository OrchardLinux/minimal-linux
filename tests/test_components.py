import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_build', PROJECT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class Components(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.modules = self.root / 'source/kernel/lib/modules/test-release'
        self.modules.mkdir(parents=True)
        (self.modules / 'test.ko').write_bytes(b'module fixture')
        (self.root / 'source/kernel/kernel.release').write_text('test-release\n')
        self.args = [sys.executable, str(PROJECT / 'pin_components.py')]
        for role in ('loader', 'pongo', 'kernel', 'dtb', 'busybox', 'dropbear', 'dropbearkey'):
            p = self.root / 'source' / role
            # The kernel *file* is separate from the fixture kernel directory.
            if role == 'kernel':
                p = self.root / 'source/Image.gz'
            p.write_bytes(role.encode())
            self.args += ['--' + role, str(p)]
        self.args += ['--modules-dir', str(self.modules.parent), '--output', str(self.root / 'copied')]

    def run_pin(self):
        return subprocess.run(self.args, capture_output=True, text=True)

    def test_independent_copies_and_digest_verification(self):
        result = self.run_pin()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.root / 'copied/inputs.json'
        files, record = build.verify_inputs(receipt)
        original = self.root / 'source/loader'
        original.write_bytes(b'changed after pinning')
        self.assertEqual(files['loader'].read_bytes(), b'loader')
        files['loader'].write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            build.verify_inputs(receipt)

    def test_rejects_symlink_inputs(self):
        p = self.root / 'source/loader'
        p.unlink()
        p.symlink_to('pongo')
        self.assertNotEqual(self.run_pin().returncode, 0)
        self.assertFalse((self.root / 'copied').exists())

    def test_refuses_overwriting_existing_output(self):
        self.assertEqual(self.run_pin().returncode, 0)
        self.assertNotEqual(self.run_pin().returncode, 0)


if __name__ == '__main__':
    unittest.main()
