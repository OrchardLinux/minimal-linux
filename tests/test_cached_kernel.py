"""Which kernels a release uses: every platform, explicit bundles or orchard's cache; no builds or devices."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from orchard.image import platform

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_build', PROJECT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class CachedKernelTests(unittest.TestCase):
    def test_a_release_covers_every_platform_from_the_cache(self):
        with patch.object(platform, 'kernel', side_effect=lambda name: Path('/cache') / name):
            bundles = build.kernels()
        self.assertEqual(sorted(bundles), platform.platforms())

    def test_explicit_bundles_are_not_built_and_development_may_take_fewer(self):
        with patch.object(platform, 'kernel') as cached:
            bundles = build.kernels(['apple-16k'], ['apple-16k=/explicit'])
        self.assertEqual(bundles, {'apple-16k': Path('/explicit')})
        cached.assert_not_called()

    def test_unknown_platforms_are_refused_before_any_build(self):
        for selected, explicit in ((None, ['apple-64k=/x']), (None, ['/x']), (['apple-64k'], [])):
            with self.subTest(selected=selected, explicit=explicit), patch.object(platform, 'kernel') as cached, \
                    self.assertRaisesRegex(ValueError, 'apple-16k'):
                build.kernels(selected, explicit)
            cached.assert_not_called()


if __name__ == '__main__':
    unittest.main()
