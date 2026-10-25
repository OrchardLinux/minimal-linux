import importlib.machinery
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'system/overlay/usr/libexec/minimal-console'
loader = importlib.machinery.SourceFileLoader('console_keys', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
console = importlib.util.module_from_spec(spec)
loader.exec_module(console)


class ConsoleKeys(unittest.TestCase):
    def test_only_volume_down_function_bindings_are_muted(self):
        writes = []
        def ioctl(fd, operation, entry, mutate=False):
            table, code, value = struct.unpack('BBH', entry)
            self.assertEqual(code, 114)
            if operation == 0x4b46:
                entry[:] = struct.pack('BBH', table, code, 0x10d if table in (0, 1, 4) else 0x200)
            else:
                self.assertEqual(operation, 0x4b47)
                writes.append((table, code, value))
        with patch.object(console.fcntl, 'ioctl', side_effect=ioctl):
            self.assertEqual(console.mute_demo_keys(9), 3)
        self.assertEqual(writes, [(0, 114, 0x200), (1, 114, 0x200), (4, 114, 0x200)])

    def test_existing_holes_and_absent_maps_are_not_created(self):
        def ioctl(fd, operation, entry, mutate=False):
            self.assertEqual(operation, 0x4b46)
            table, code, _ = struct.unpack('BBH', entry)
            entry[:] = struct.pack('BBH', table, code, 0x27f if table % 2 else 0x200)
        with patch.object(console.fcntl, 'ioctl', side_effect=ioctl):
            self.assertEqual(console.mute_demo_keys(9), 0)


if __name__ == '__main__':unittest.main()
