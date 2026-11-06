"""Validate selected inputs before root assembly, then hand them to Orchard's index producer."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import producer_inputs

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_release_inputs', PROJECT / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def document():
    tools = {name: '/cache/tools/' + name for name in producer_inputs.TOOLS}
    return {
        'architecture': 'arm64',
        'orchard': {'commit': 'c' * 40, 'modified': False},
        'shared': {'pongo': '/cache/pongo', 'm1n1': '/cache/m1n1', 'tools': dict(tools)},
        'platforms': {
            'apple-4k': {
                'architecture': 'arm64',
                'image': 'Image.gz',
                'loader': {'kind': 'm1n1', 'file': '/cache/m1n1'},
                'tools': dict(tools),
            },
        },
    }


class ReleaseInputs(unittest.TestCase):
    def invoke(self, root, selected, command):
        inputs = root / 'orchard-inputs.json'
        inputs.write_text(json.dumps(selected))
        logo = root / 'logo.bin'
        logo.write_bytes(b'logo')
        base_receipt = root / 'base.json'
        base_receipt.write_text('{}')
        argv = ['build.py', '--base', str(root / 'base.tar.gz'),
                '--base-receipt', str(base_receipt), '--inputs', str(root / 'public.json'),
                '--orchard-inputs', str(inputs), '--version', 'test', '--output', str(root / 'release')]
        with patch.object(sys, 'argv', argv), \
                patch.object(build, 'orchard_root', return_value=Path('/snapshot')), \
                patch.object(build, 'verify_inputs', return_value=({'logo': logo}, {'files': {}})), \
                patch.object(build, 'root_archive') as assemble_root, \
                patch.object(build, 'orchard_command', side_effect=command), \
                patch.object(build, 'manifests'):
            try:
                build.main()
            finally:
                self.assemble_root = assemble_root
        return inputs

    def test_mixed_architecture_stops_before_root_or_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = document()
            selected['platforms']['apple-4k']['architecture'] = 'arm'
            with patch.object(build, 'orchard_command') as unused:
                with self.assertRaises(SystemExit) as error:
                    self.invoke(root, selected, unused)
            self.assertEqual(error.exception.code, 2)
            self.assemble_root.assert_not_called()
            unused.assert_not_called()
            self.assertFalse((root / 'release').exists())

    def test_foreign_lwvm_mapper_stops_before_root_or_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapper = root / 'orchard-lwvm'
            raw = bytearray(136)
            raw[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI', raw, 16, 2, 40, 1)
            mapper.write_bytes(raw)
            selected = document()
            selected['platforms']['apple-4k'].update(root_format='lwvm')
            selected['platforms']['apple-4k']['tools']['lwvm'] = str(mapper)
            with patch.object(build, 'orchard_command') as unused:
                with self.assertRaises(SystemExit) as error:
                    self.invoke(root, selected, unused)
            self.assertEqual(error.exception.code, 2)
            self.assemble_root.assert_not_called()
            unused.assert_not_called()
            self.assertFalse((root / 'release').exists())

    def test_selected_inputs_reach_index_and_root_image_producers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            selected = document()

            def produce(snapshot, module, *argv, **kwargs):
                calls.append((snapshot, module, argv))
                if module == 'image.platforms_index':
                    self.assertEqual(snapshot, Path('/snapshot'))
                    self.assertEqual(argv[1:], ('--inputs', root / 'orchard-inputs.json'))
                    self.assertEqual(json.loads(argv[2].read_text()), selected)
                    (argv[0] / 'platforms.toml').write_text('commit = "' + 'c' * 40 + '"\n[platforms]\n')
                elif module == 'image.root_image':
                    self.assertEqual(argv[0].name, 'rootfs.tar.gz')
                    self.assertEqual(argv[1], '--output')
                    (argv[2] / 'root-image.json').write_text('{}')
                else:
                    self.fail('Unexpected producer: ' + module)

            self.invoke(root, selected, produce)
            self.assemble_root.assert_called_once()
            self.assertEqual([row[1] for row in calls], ['image.platforms_index', 'image.root_image'])
            self.assertTrue((root / 'release/build-receipt.json').is_file())


if __name__ == '__main__':
    unittest.main()
