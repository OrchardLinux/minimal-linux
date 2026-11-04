"""Which kernels a release uses: what orchard.inputs resolved, or an explicit bundle; no builds or devices."""
import importlib.util
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_build', PROJECT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

RESOLVED = {'platforms': {'apple-16k': {'kernel': '/cache/apple-16k', 'boards': {'j71b': 't8010-j71b'}},
                          'apple-4k': {'kernel': '/cache/apple-4k', 'boards': {'n71': 's8000-n71'}}}}


class CachedKernelTests(unittest.TestCase):
    def test_a_release_covers_every_resolved_platform(self):
        self.assertEqual(build.kernels(RESOLVED), {'apple-16k': Path('/cache/apple-16k'),
                                                   'apple-4k': Path('/cache/apple-4k')})

    def test_an_explicit_bundle_replaces_the_resolved_one(self):
        self.assertEqual(build.kernels(RESOLVED, ['apple-16k=/explicit'])['apple-16k'], Path('/explicit'))

    def test_unknown_platforms_are_refused(self):
        for explicit in (['apple-64k=/x'], ['/x']):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(ValueError, 'apple-16k'):
                build.kernels(RESOLVED, explicit)


if __name__ == '__main__':
    unittest.main()
