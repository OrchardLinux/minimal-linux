"""Input pinning shares Orchard's kernel cache without changing image policy."""
import argparse
from contextlib import redirect_stderr
import io
import importlib.util
import itertools
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_pin_components', PROJECT / 'pin_components.py')
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)


class CachedKernelTests(unittest.TestCase):
    def args(self, supplied=(False, False, False)):
        return argparse.Namespace(**{
            name: Path('/explicit') / name if present else None
            for name, present in zip(('kernel', 'dtb', 'modules_dir'), supplied)
        }, loader=Path('/branded/loader'), pongo=Path('/branded/pongo'))

    def test_omitted_bundle_uses_generic_builder_and_preserves_branding(self):
        api = ModuleType('orchard_cli.build')
        api.prepare_kernel = Mock(return_value=Path('/shared/kernel'))
        args = self.args()
        with patch.dict(sys.modules, {'orchard_cli.build': api}):
            pin.resolve_kernel(args)
        api.prepare_kernel.assert_called_once_with(device='j71b')
        self.assertEqual(args.kernel, Path('/shared/kernel/Image.gz'))
        self.assertEqual(args.dtb, Path('/shared/kernel/j71b.dtb'))
        self.assertEqual(args.modules_dir, Path('/shared/kernel/lib/modules'))
        self.assertEqual(args.loader, Path('/branded/loader'))
        self.assertEqual(args.pongo, Path('/branded/pongo'))

    def test_explicit_bundle_does_not_import_cached_builder(self):
        args = self.args((True, True, True))
        before = vars(args).copy()
        with patch.dict(sys.modules, {'orchard_cli.build': None}):
            pin.resolve_kernel(args)
        self.assertEqual(vars(args), before)

    def test_partial_bundle_is_rejected_without_importing_builder(self):
        for supplied in itertools.product((False, True), repeat=3):
            if not any(supplied) or all(supplied):
                continue
            with self.subTest(supplied=supplied), \
                    patch.dict(sys.modules, {'orchard_cli.build': None}), \
                    self.assertRaisesRegex(ValueError, 'together'):
                pin.resolve_kernel(self.args(supplied))

    def test_missing_explicit_input_fails_before_resolving_kernel(self):
        for role in ('loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                argv = ['pin_components']
                for name in ('loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey'):
                    path = root / name
                    if name != role:
                        path.write_text('fixture')
                    argv += ['--' + name, str(path)]
                argv += ['--output', str(root / 'pinned')]
                with patch.object(sys, 'argv', argv), \
                        patch.object(pin, 'resolve_kernel') as resolve, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    pin.main()
                self.assertEqual(error.exception.code, 2)
                resolve.assert_not_called()

    def test_pin_exports_independent_kernel_copies_with_existing_receipt_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kernel = root / 'cached-kernel'
            modules = kernel / 'lib/modules/test-release'
            modules.mkdir(parents=True)
            (modules / 'test.ko').write_bytes(b'module fixture')
            for name in ('Image.gz', 'j71b.dtb', 'kernel.release'):
                (kernel / name).write_text(name)
            argv = ['pin_components']
            for name in ('loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey'):
                path = root / name
                path.write_text(name)
                argv += ['--' + name, str(path)]
            argv += ['--output', str(root / 'pinned')]
            api = ModuleType('orchard_cli.build')
            api.prepare_kernel = Mock(return_value=kernel)
            with patch.object(sys, 'argv', argv), \
                    patch.dict(sys.modules, {'orchard_cli.build': api}):
                pin.main()
            api.prepare_kernel.assert_called_once_with(device='j71b')
            self.assertEqual((root / 'pinned/kernel/Image.gz').read_bytes(), b'Image.gz')
            (kernel / 'Image.gz').write_bytes(b'later change')
            self.assertEqual((root / 'pinned/kernel/Image.gz').read_bytes(), b'Image.gz')
            self.assertTrue((root / 'pinned/inputs.json').is_file())
