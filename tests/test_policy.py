import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('minimal_policy', HERE / 'system/image_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class Readiness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('RECORD', 'BOOT_ID', 'CONFIG', 'STARTED'):
            p = patch.object(policy, name, self.root / name)
            p.start()
            self.addCleanup(p.stop)
        policy.BOOT_ID.write_text('current-boot\n')
        policy.CONFIG.write_text(json.dumps({'release': 'test'}))
        policy.STARTED.mkdir()
        for service in policy.SERVICES:
            (policy.STARTED / service).touch()
        self.record = {'release': 'test', 'boot_id': 'current-boot',
                       'ssh_pid': 2, 'usb_pid': 4, 'buttons_pid': 5}
        self.save()
        # Tests run on macOS as an unprivileged developer. Root metadata and
        # live Linux executables are checked separately in the native image.
        p = patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=0o100600, st_uid=0))
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(policy, 'process', return_value=True)
        self.process = p.start()
        self.addCleanup(p.stop)

    def save(self):
        policy.RECORD.write_text(json.dumps(self.record))

    def test_current_boot_with_all_services_is_ready(self):
        self.assertTrue(policy.ready())
        self.assertEqual(self.process.call_count, 4)

    def test_no_ssh_server_is_not_ready(self):
        self.process.side_effect = lambda pid, exe: pid != 2
        self.assertFalse(policy.ready())

    def test_prior_boot_is_not_ready(self):
        self.record['boot_id'] = 'previous-boot'
        self.save()
        self.assertFalse(policy.ready())

    def test_wrong_release_is_not_ready(self):
        self.record['release'] = 'other'
        self.save()
        self.assertFalse(policy.ready())

    def test_different_installed_release_is_not_ready(self):
        policy.CONFIG.write_text('{"release":"other"}')
        self.assertFalse(policy.ready())

    def test_missing_service_is_not_ready(self):
        (policy.STARTED / 'orchard-usb').unlink()
        self.assertFalse(policy.ready())

    def test_dead_or_different_process_is_not_ready(self):
        self.process.return_value = False
        self.assertFalse(policy.ready())

    def test_missing_marker_is_not_ready(self):
        policy.RECORD.unlink()
        self.assertFalse(policy.ready())

    def test_writable_or_symlink_marker_is_not_ready(self):
        for mode in (0o100666, 0o120600):
            with patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=mode, st_uid=0)):
                self.assertFalse(policy.ready())

    def test_unprivileged_marker_is_not_ready(self):
        with patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=0o100600, st_uid=1000)):
            self.assertFalse(policy.ready())

    def test_malformed_marker_is_not_ready(self):
        policy.RECORD.write_text('not json')
        self.assertFalse(policy.ready())


class Composition(unittest.TestCase):
    def test_services_do_not_reset_hardware_or_mount_pseudo_filesystems(self):
        overlay = HERE / 'system/overlay'
        for p in (overlay / 'etc/init.d').glob('*'):
            source = p.read_text()
            self.assertTrue(source.startswith('#!/sbin/openrc-run\n'))
            for forbidden in ('modprobe', 'insmod', 'usb-gadget', 'recovery-usb', 'mount -t', 'udevadm'):
                self.assertNotIn(forbidden, source)

    def test_installer_preserves_standard_recovery_profile(self):
        source = (HERE / 'build.py').read_text()
        self.assertNotIn("'--verbose'", source)
        self.assertNotIn('ignore_loglevel', source)

    def test_ready_needs_all_required_services(self):
        source = (HERE / 'system/overlay/etc/init.d/orchard-ready').read_text()
        for name in policy.SERVICES:
            self.assertIn(name, source)


if __name__ == '__main__':
    unittest.main()
