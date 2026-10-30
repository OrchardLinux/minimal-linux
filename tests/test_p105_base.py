"""Host-only checks for the signed P105 recovery base exporter."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p105_base_test', PROJECT / 'p105/build-base.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class P105Base(unittest.TestCase):
    def test_export_receipt_binds_image_recipe_and_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'base.tar'
            image = 'sha256:' + 'a' * 64
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if command[1] == 'build':
                    Path(command[command.index('--iidfile') + 1]).write_text(image + '\n')
                elif command[1] == 'run':
                    kwargs['stdout'].write(b'fixture base')
            with patch('sys.argv', ['build-base', '--output', str(output)]), \
                 patch.object(base.subprocess, 'run', side_effect=run), \
                 patch.object(base.subprocess, 'check_output', return_value=image + '\n'):
                base.main()
            receipt = json.loads(output.with_suffix('.json').read_text())
            self.assertEqual(receipt['image'], image)
            self.assertEqual(receipt['architecture'], 'armv7h')
            self.assertTrue(receipt['signed_apk'])
            self.assertEqual(receipt['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(receipt['recipe_sha256'], hashlib.sha256((PROJECT / 'p105/Containerfile').read_bytes()).hexdigest())
            self.assertEqual([command[1] for command in commands], ['build', 'run'])
            self.assertNotIn('-t', commands[0])
            self.assertNotIn('--tag', commands[0])
            self.assertNotIn('--no-cache', commands[0])
            self.assertEqual(commands[1][commands[1].index('none') + 1], image)
            self.assertIn('--network', commands[1])
            self.assertIn('none', commands[1])

    def test_no_cache_uses_image_id_and_leaves_existing_tags_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'base.tar'
            image = 'sha256:' + 'a' * 64
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if command[1] == 'build':
                    Path(command[command.index('--iidfile') + 1]).write_text(image + '\n')
                elif command[1] == 'run':
                    kwargs['stdout'].write(b'fixture base')
            with patch('sys.argv', ['build-base', '--output', str(output), '--no-cache']), \
                 patch.object(base.subprocess, 'run', side_effect=run), \
                 patch.object(base.subprocess, 'check_output', return_value=image.removeprefix('sha256:') + '\n') as inspect:
                base.main()
            self.assertIn('--no-cache', commands[0])
            self.assertNotIn('-t', commands[0])
            self.assertNotIn('--tag', commands[0])
            self.assertEqual(inspect.call_args.args[0][3], image)
            self.assertEqual(json.loads(output.with_suffix('.json').read_text())['image'], image)

    def test_mismatched_inspection_is_rejected_before_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'base.tar'
            image = 'sha256:' + 'a' * 64
            def build(command, **_kwargs):
                Path(command[command.index('--iidfile') + 1]).write_text(image + '\n')
            with patch('sys.argv', ['build-base', '--output', str(output)]), \
                 patch.object(base.subprocess, 'run', side_effect=build) as run, \
                 patch.object(base.subprocess, 'check_output', return_value='b' * 64 + '\n'):
                with self.assertRaises(SystemExit):
                    base.main()
            self.assertEqual(run.call_count, 1)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix('.json').exists())

    def test_existing_output_or_receipt_stops_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'base.tar'
            for present in (output, output.with_suffix('.json')):
                with self.subTest(present=present):
                    present.write_bytes(b'existing')
                    with patch('sys.argv', ['build-base', '--output', str(output)]), \
                         patch.object(base.subprocess, 'run') as run:
                        with self.assertRaises(SystemExit):
                            base.main()
                    run.assert_not_called()
                    self.assertEqual(present.read_bytes(), b'existing')
                    present.unlink()
            receipt = output.with_suffix('.json')
            receipt.symlink_to(Path(temporary) / 'missing')
            with patch('sys.argv', ['build-base', '--output', str(output)]), \
                 patch.object(base.subprocess, 'run') as run:
                with self.assertRaises(SystemExit):
                    base.main()
            run.assert_not_called()
            self.assertTrue(receipt.is_symlink())

    def test_recipe_pins_images_and_uses_verified_armv7_packages(self):
        recipe = (PROJECT / 'p105/Containerfile').read_text()
        images = [line for line in recipe.splitlines() if line.startswith('FROM ')]
        self.assertEqual(len(images), 2)
        self.assertTrue(all('@sha256:' in line for line in images))
        self.assertIn('--arch armv7', recipe)
        self.assertIn('--no-scripts', recipe)
        self.assertIn('/etc/apk/keys', recipe)


if __name__ == '__main__':
    unittest.main()
