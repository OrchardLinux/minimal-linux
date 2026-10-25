import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
HELPERS = PROJECT / 'system/overlay/usr/libexec'


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(HELPERS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


buttons = load('minimal-buttons')
toggle = load('minimal-screen-toggle').toggle


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.backlights = self.root / 'backlights'
        self.device = self.backlights / '20e200080.backlight'
        self.device.mkdir(parents=True)
        (self.device / 'brightness').write_text('731\n')
        (self.device / 'max_brightness').write_text('2047\n')

    def test_original_toggle_round_trip_restores_exact_raw_value(self):
        self.assertEqual(toggle(self.device, self.runtime), 0)
        self.assertEqual(toggle(self.device, self.runtime), 731)
        (self.device / 'brightness').write_text('139\n')
        self.assertEqual(toggle(self.device, self.runtime), 0)
        self.assertEqual(toggle(self.device, self.runtime), 139)

    def test_original_toggle_private_state_rejects_symlink(self):
        other = self.root / 'other'
        other.write_text('unchanged')
        (self.runtime / 'minimal-screen-brightness').symlink_to(other)
        with self.assertRaises(OSError):toggle(self.device, self.runtime)
        self.assertEqual(other.read_text(), 'unchanged')
        self.assertEqual((self.device / 'brightness').read_text(), '731\n')

    def test_original_toggle_visible_fallback_and_clamping(self):
        for value, expected in (('invalid', 1023), ('0', 1023), ('9999', 2047)):
            (self.device / 'brightness').write_text('0\n')
            (self.runtime / 'minimal-screen-brightness').write_text(value)
            self.assertEqual(toggle(self.device, self.runtime), expected)

    def brightness(self, step):
        result = subprocess.run(['bash', str(HELPERS / 'minimal-brightness-display'), '--no-osd', step],
            env={**os.environ, 'IPADLINUX_BACKLIGHT_DIR': str(self.backlights)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout), int((self.device / 'brightness').read_text())

    def test_original_brightness_math_and_bounds(self):
        self.assertEqual(self.brightness('+5%'), (41, (2047 * 41 + 50) // 100))
        (self.device / 'brightness').write_text('1\n')
        self.assertEqual(self.brightness('-5%'), (1, (2047 + 50) // 100))
        (self.device / 'brightness').write_text('2047\n')
        self.assertEqual(self.brightness('+5%'), (100, 2047))

    def test_volume_press_repeat_and_release(self):
        actions = []
        binding = buttons.Bindings(actions.append)
        for value in (1, 2, 0):binding.handle(1, 115, value)
        binding.handle(1, 114, 1)
        self.assertEqual(actions, ['up', 'up', 'down'])

    def test_power_release_only_without_repeat(self):
        actions = []
        binding = buttons.Bindings(actions.append)
        for value in (0, 1, 2, 2, 0, 0):binding.handle(1, 116, value)
        self.assertEqual(actions, ['toggle'])

    def test_other_keys_and_touch_are_ignored(self):
        actions = []
        binding = buttons.Bindings(actions.append)
        for event in ((1, 172, 1), (3, 116, 1), (0, 0, 0)):binding.handle(*event)
        self.assertEqual(actions, [])

    def test_actual_gpio_key_bitmap_and_abi(self):
        bits = buttons.key_bits('100000000000 1c000000000000 0')
        self.assertTrue(all(bits & (1 << key) for key in (114, 115, 116)))
        self.assertEqual(buttons.EVENT.size, 24)

    def test_device_selection_is_unique_and_not_touch(self):
        for event, name in (('event0', 'gpio-keys'), ('event1', 'touchscreen')):
            device = self.root / 'input' / event / 'device'
            (device / 'capabilities').mkdir(parents=True)
            (device / 'name').write_text(name)
            (device / 'capabilities/key').write_text('100000000000 1c000000000000 0')
        self.assertEqual(buttons.find_keys(self.root / 'input'), Path('/dev/input/event0'))
        (self.root / 'input/event1/device/name').write_text('gpio-keys')
        with self.assertRaises(ValueError):buttons.find_keys(self.root / 'input')


if __name__ == '__main__':unittest.main()
