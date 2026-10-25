import importlib.machinery
import importlib.util
from pathlib import Path
import struct
import unittest

PATH = Path(__file__).resolve().parents[1] / 'system/overlay/usr/libexec/minimal-clear-splash'
loader = importlib.machinery.SourceFileLoader('clear_splash', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


def layout(width=4, height=3, stride=20, alpha=False):
    variable, fixed = bytearray(160), bytearray(80)
    struct.pack_into('<8I', variable, 0, width, height, width, height, 0, 0, 32, 0)
    for offset, shift in ((32, 16), (44, 8), (56, 0)):
        struct.pack_into('<3I', variable, offset, shift, 8, 0)
    if alpha:
        struct.pack_into('<3I', variable, 68, 24, 8, 0)
    fixed[:16] = b'simpledrmdrmfb\0\0\0'
    struct.pack_into('<I', fixed, 24, stride * height)
    struct.pack_into('<3I', fixed, 28, 0, 0, 2)
    struct.pack_into('<I', fixed, 48, stride)
    return variable, fixed


class Framebuffer(unittest.TestCase):
    def test_padded_rows_are_black_without_overrun(self):
        frame, info = module.black_frame(*layout())
        self.assertEqual(frame, b'\0' * 60)
        self.assertEqual(info['bytes'], 60)

    def test_alpha_is_opaque(self):
        frame, _ = module.black_frame(*layout(alpha=True))
        self.assertEqual(frame[:16], b'\0\0\0\xff' * 4)
        self.assertEqual(frame[16:20], b'\0' * 4)

    def test_rejects_short_mapping(self):
        variable, fixed = layout()
        struct.pack_into('<I', fixed, 24, 59)
        with self.assertRaises(ValueError):module.black_frame(variable, fixed)

    def test_rejects_wrong_device_or_format(self):
        for offset, value in ((28, 1), (36, 3), (48, 12)):
            variable, fixed = layout()
            struct.pack_into('<I', fixed, offset, value)
            with self.assertRaises(ValueError):module.black_frame(variable, fixed)
        variable, fixed = layout()
        fixed[:16] = b'wrong-driver\0\0\0\0'
        with self.assertRaises(ValueError):module.black_frame(variable, fixed)

    def test_rejects_out_of_bounds_viewport(self):
        variable, fixed = layout()
        struct.pack_into('<I', variable, 16, 1)
        with self.assertRaises(ValueError):module.black_frame(variable, fixed)

    def test_rejects_overlapping_channels(self):
        variable, fixed = layout()
        struct.pack_into('<3I', variable, 44, 16, 8, 0)
        with self.assertRaises(ValueError):module.black_frame(variable, fixed)


if __name__ == '__main__':unittest.main()
