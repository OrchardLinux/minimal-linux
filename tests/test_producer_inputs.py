"""The release consumes architecture-aware producer records as one root."""
import unittest
from pathlib import Path
import struct
import tempfile
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

    def helper(self, temporary, *, kind=1, machine=183):
        path = Path(temporary) / 'orchard-lwvm'
        data = bytearray(136)
        data[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', data, 16, 2, machine, 1)
        struct.pack_into('<Q', data, 32, 64)
        struct.pack_into('<HHH', data, 52, 64, 56, 1)
        struct.pack_into('<II6Q', data, 64, kind, 5, 120, 0, 0, 16, 16, 8)
        path.write_bytes(data)
        return path

    def test_lwvm_platform_validates_its_mapper_and_rescue_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.helper(temporary)
            data = document()
            row = data['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            row['tools']['lwvm'] = str(path)
            producer_inputs.components(data)
            self.assertEqual(producer_inputs.lwvm_helper(row), str(path))
            self.assertIsNone(producer_inputs.validate_backend(row))
            self.assertIsNone(producer_inputs.validate_backend(data['platforms']['apple-16k']))

    def test_lwvm_missing_mapper_fails_before_build(self):
        row = document()['platforms']['apple-4k']
        row['root_format'] = 'lwvm'
        with self.assertRaisesRegex(ValueError, 'absolute mapper'):
            producer_inputs.validate_backend(row)

    def test_lwvm_rejects_foreign_or_dynamic_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = document()['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            for kind, machine in ((1, 40), (3, 183), (2, 183)):
                path = self.helper(temporary, kind=kind, machine=machine)
                if kind == 2:
                    data = bytearray(path.read_bytes())
                    struct.pack_into('<QQ', data, 120, 1, 0)
                    path.write_bytes(data)
                row['tools']['lwvm'] = str(path)
                with self.subTest(kind=kind, machine=machine), self.assertRaises(ValueError):
                    producer_inputs.validate_backend(row)

    def test_lwvm_rejects_a_header_without_loadable_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = document()['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            row['tools']['lwvm'] = str(self.helper(temporary, kind=0))
            with self.assertRaisesRegex(ValueError, 'no loadable ELF segment'):
                producer_inputs.validate_backend(row)

    def test_lwvm_entry_must_reach_executable_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = document()['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            for flags, length, memory, entry in ((4, 16, 16, 0), (5, 0, 16, 0),
                                                  (5, 16, 16, 16), (5, 16, 8, 0)):
                path = self.helper(temporary)
                raw = bytearray(path.read_bytes())
                struct.pack_into('<Q', raw, 24, entry)
                struct.pack_into('<II6Q', raw, 64, 1, flags, 120, 0, 0, length, memory, 8)
                path.write_bytes(raw)
                row['tools']['lwvm'] = str(path)
                with self.subTest(flags=flags, length=length, memory=memory, entry=entry), \
                        self.assertRaises(ValueError):
                    producer_inputs.validate_backend(row)

    def test_lwvm_dynamic_table_must_end_with_null(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'orchard-lwvm'
            row = document()['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            row['tools']['lwvm'] = str(path)
            raw = bytearray(208)
            raw[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI', raw, 16, 2, 183, 1)
            struct.pack_into('<Q', raw, 32, 64)
            struct.pack_into('<HHH', raw, 52, 64, 56, 2)
            struct.pack_into('<II6Q', raw, 64, 1, 5, 176, 0, 0, 16, 16, 8)
            struct.pack_into('<II6Q', raw, 120, 2, 4, 192, 16, 0, 16, 16, 8)
            struct.pack_into('<QQ', raw, 192, 7, 0)
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'unterminated dynamic table'):
                producer_inputs.validate_backend(row)
            struct.pack_into('<QQ', raw, 192, 0, 0)
            path.write_bytes(raw)
            self.assertIsNone(producer_inputs.validate_backend(row))

    def test_lwvm_rejects_truncation_and_split_rescue_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            row = document()['platforms']['apple-4k']
            row['root_format'] = 'lwvm'
            path = self.helper(temporary)
            row['tools']['lwvm'] = str(path)
            row['tools']['dropbearkey'] = '/other/dropbearkey'
            with self.assertRaisesRegex(ValueError, 'share a directory'):
                producer_inputs.validate_backend(row)
            path.write_bytes(path.read_bytes()[:100])
            with self.assertRaisesRegex(ValueError, 'program headers'):
                producer_inputs.validate_backend(row)
