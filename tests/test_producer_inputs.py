"""The release consumes architecture-aware producer records as one root."""
import unittest
import producer_inputs


def document():
    tools = {name: '/cache/tools/' + name for name in producer_inputs.TOOLS}
    return {'architecture': 'arm64', 'shared': {'pongo': '/cache/pongo'},
            'platforms': {name: {'architecture': 'arm64', 'image': 'Image.gz',
                'loader': {'kind': 'm1n1', 'file': '/cache/m1n1'}, 'tools': dict(tools)}
                for name in ('apple-4k', 'apple-16k')}}


class ProducerInputsTests(unittest.TestCase):
    def test_current_records_resolve_shared_components(self):
        result = producer_inputs.components(document())
        self.assertEqual(result['m1n1'], '/cache/m1n1')
        self.assertEqual(result['pongo'], '/cache/pongo')
        self.assertEqual(result['tools']['busybox'], '/cache/tools/busybox')

    def test_mixed_architectures_fail_before_root_assembly(self):
        data = document()
        data['platforms']['apple-4k']['architecture'] = 'arm'
        with self.assertRaisesRegex(ValueError, 'ARM64 release root'):
            producer_inputs.components(data)

    def test_armv7_release_requires_its_own_root_path(self):
        data = document()
        data['architecture'] = 'arm'
        with self.assertRaisesRegex(ValueError, 'armv7/build-base.py'):
            producer_inputs.components(data)

    def test_different_tools_fail_before_component_pinning(self):
        data = document()
        data['platforms']['apple-4k']['tools']['busybox'] = '/other/busybox'
        with self.assertRaisesRegex(ValueError, 'same loader and static tools'):
            producer_inputs.components(data)

    def test_wrong_loader_and_incomplete_tools_are_rejected(self):
        for field, value in [('loader', {'kind': 'cascadia', 'file': '/cache/cascadia'}), ('tools', {})]:
            data = document()
            data['platforms']['apple-4k'][field] = value
            with self.assertRaises(ValueError):
                producer_inputs.components(data)

    def test_older_snapshot_components_still_resolve(self):
        data = document()
        row = data['platforms']['apple-4k']
        data['shared'].update(m1n1=row['loader']['file'], tools=row['tools'])
        data.pop('architecture')
        for row in data['platforms'].values():
            for key in ('architecture', 'image', 'loader', 'tools'):
                row.pop(key)
        self.assertEqual(producer_inputs.components(data)['m1n1'], '/cache/m1n1')
