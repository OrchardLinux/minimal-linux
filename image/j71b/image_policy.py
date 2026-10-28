"""Alpine/OpenRC policy. No desktop or systemd dependencies."""
import json
import os
from pathlib import Path
import stat
import subprocess

DIAGNOSTICS_EXECUTABLE = '/usr/sbin/dropbear'


def stop_diagnostics():
    subprocess.run(['rc-service', 'orchard-diagnostics', 'stop'],
                   check=True, capture_output=True, timeout=15)

INIT = '/sbin/init'
RECORD = Path('/run/minimal-linux-ready.json')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
PROC = Path('/proc')
CONFIG = Path('/etc/orchard/release.json')
INSTALLED = Path('/.orchard-install.json')
STARTED = Path('/run/openrc/started')
SERVICES = ('orchard-platform', 'orchard-diagnostics', 'orchard-dhcp', 'orchard-buttons')


def process(pid, executable):
    path = PROC / str(int(pid))
    return path.stat().st_uid == 0 and str((path / 'exe').readlink()) == executable


def ready(*, ssh_revoked=False):
    try:
        info = RECORD.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            return False
        record = json.loads(RECORD.read_text())
        return (record['boot_id'] == BOOT_ID.read_text().strip() and
                record['release'] == json.loads(CONFIG.read_text())['release'] and
                all((STARTED / name).exists() for name in SERVICES
                    if not (ssh_revoked and name == 'orchard-diagnostics')) and
                process(1, '/usr/bin/busybox') and
                (ssh_revoked or process(record['diagnostics_pid'], DIAGNOSTICS_EXECUTABLE)) and
                process(record['dhcp_pid'], '/usr/libexec/minimal-linux/busybox') and
                process(record['buttons_pid'], str(Path('/usr/bin/python3').resolve())) and
                json.loads(INSTALLED.read_text())['release'] == record['release'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate_handoff(root):
    # /lib aliases /usr/lib using Alpine's officially supported merge-usr.
    if (root / 'lib').readlink().as_posix() != 'usr/lib':
        raise ValueError('Alpine image must use the supported merged-/usr layout')
    if (root / 'usr/sbin/init').readlink().as_posix() != '/bin/busybox':
        raise ValueError('Alpine PID 1 must be BusyBox init')
    for name in ('usr/bin/busybox', 'usr/bin/python3', 'usr/sbin/openrc',
                 'usr/sbin/openrc-run', 'usr/sbin/dropbear',
                 'usr/libexec/minimal-check-platform',
                 'usr/libexec/minimal-ready', 'usr/libexec/minimal-clear-splash',
                 'usr/libexec/minimal-console', 'usr/libexec/minimal-buttons',
                 'usr/libexec/minimal-screen-toggle', 'usr/libexec/minimal-brightness-display',
                 'usr/bin/bash',
                 'usr/libexec/minimal-linux/busybox',
                 'usr/sbin/recovery-start-ssh'):
        if not os.access(root / name, os.X_OK):
            raise ValueError('Missing Alpine handoff executable: ' + name)
    for name in (*SERVICES, 'orchard-session', 'orchard-ready'):
        if not os.access(root / 'etc/init.d' / name, os.X_OK):
            raise ValueError('Missing OpenRC service: ' + name)
    if (root / 'usr/lib/systemd/systemd').exists():
        raise ValueError('Minimal Alpine must not contain systemd')


def validate_root(root, release):
    validate_handoff(root)
    if json.loads((root / 'etc/orchard/release.json').read_text())['release'] != release['release']:
        raise ValueError('Root/recovery release mismatch')
    if not (root / 'etc/alpine-release').is_file():
        raise ValueError('Missing Alpine release identity')


def verify_privileges(root):
    """This root deliberately ships no setuid/setgid files or sudo policy."""
    for path in root.rglob('*'):
        info = path.lstat()
        if not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o6000:
            raise ValueError('Unexpected privileged mode in minimal image: ' + str(path))


def verify_session_access(root):
    # Headless key-only root diagnostics, not a desktop/unprivileged user ABI.
    for name in ('root', 'etc/shadow'):
        path = root / name
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('Private Alpine session path is not private: ' + name)
    shadow = (root / 'etc/shadow').read_text().splitlines()
    if not any(row.startswith(('root:!:', 'root:*:')) for row in shadow):
        raise ValueError('Root password must be locked')
    if (root / 'root/.ssh').exists():
        raise ValueError('Public root must not contain session credentials')


def diagnostics():
    logs = {}
    for name in ('minimal-linux-ready.json', 'orchard-platform.log'):
        path = Path('/run') / name
        try:
            if path.is_file() and not path.is_symlink():
                logs[name] = path.read_bytes()[-12000:].decode(errors='replace')
        except OSError:
            pass
    return logs
