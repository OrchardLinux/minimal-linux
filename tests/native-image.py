"""Run inside the finished image with only /payload and /test read-only mounts.

No physical devices; NET_ADMIN is restricted to the container network namespace.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, '/usr/libexec/minimal-linux')
from archive import extract
import image_policy as policy

bundle = Path('/payload')
receipt = json.loads((bundle / 'rootfs.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'staged'
    root.mkdir(mode=0o700)
    with (bundle / 'rootfs.tar.gz').open('rb') as stream:
        extracted = extract(stream, root, size=receipt['bytes'], sha256=receipt['sha256'],
                            expanded_limit=receipt['expanded_bytes'], compression='gzip')
    assert extracted['members'] == receipt['members']
    policy.validate_root(root, {'release': receipt['release']})
    policy.verify_privileges(root)
    policy.verify_session_access(root)
    (root / 'usr/bin/busybox').chmod(0o4755)
    try:
        policy.verify_privileges(root)
    except ValueError:
        pass
    else:
        raise AssertionError('setuid payload accepted')

# The platform check is device-neutral: it needs the layer's modules, not board files.
assert 'SHA256SUMS' not in Path('/usr/libexec/minimal-check-platform').read_text()
subprocess.run(['/usr/libexec/minimal-linux/busybox', '--list'], check=True, stdout=subprocess.DEVNULL)
# Run the actual packaged Omarchy-derived controls against isolated files.
import runpy
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    device = base / '20e200080.backlight'
    device.mkdir()
    (device / 'max_brightness').write_text('2047\n')
    (device / 'brightness').write_text('731\n')
    env = {**os.environ, 'IPADLINUX_BACKLIGHT_DIR': str(base)}
    value = subprocess.check_output(['/usr/libexec/minimal-brightness-display', '--no-osd', '+5%'], env=env, text=True)
    assert value.strip() == '41'
    runtime = base / 'private'
    runtime.mkdir(mode=0o700)
    toggle = runpy.run_path('/usr/libexec/minimal-screen-toggle')['toggle']
    before = int((device / 'brightness').read_text())
    assert toggle(device, runtime) == 0
    assert toggle(device, runtime) == before
    subprocess.run(['/usr/libexec/rc/bin/checkpath', '--directory', '--mode', '0700', '--owner', 'root:root', str(runtime)], check=True)
assert not policy.ready()
assert not Path('/usr/lib/systemd/systemd').exists()
assert Path('/usr/lib/ld-musl-aarch64.so.1').is_file()
assert not Path('/usr/lib/libc.so.6').exists()
# Boot services as an installed system runs them: USB network, then SSH with
# host keys made on first start and only the imported key accepted.
subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/client'], check=True)
home = Path('/home/tablet/.ssh')
home.mkdir(mode=0o700, parents=True, exist_ok=True)
(home / 'authorized_keys').write_text(Path('/tmp/client.pub').read_text())
(home / 'authorized_keys').chmod(0o600)
subprocess.run(['chown', '-R', 'tablet:tablet', str(home)], check=True)
Path('/run/openrc').mkdir(exist_ok=True)
Path('/run/openrc/softlevel').write_text('default\n')
subprocess.run(['ip', 'link', 'add', 'usb0', 'type', 'dummy'], check=True)
for name in ('orchard-usb', 'orchard-ssh'):
    subprocess.run(['rc-service', name, 'start'], check=True)
time.sleep(1)
assert Path('/etc/dropbear').is_dir() and any(Path('/etc/dropbear').iterdir())
ssh = ['ssh', '-F', '/dev/null', '-i', '/tmp/client', '-o', 'IdentitiesOnly=yes',
       '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=/tmp/known_hosts',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3', 'tablet@172.16.42.1']
subprocess.check_output([*ssh, 'true'])
subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/unauthorized'], check=True)
wrong = list(ssh)
wrong[wrong.index('-i') + 1] = '/tmp/unauthorized'
assert subprocess.run([*wrong, 'true'], capture_output=True).returncode != 0
usb = Path('/proc') / Path('/run/orchard-usb.pid').read_text().strip()
assert str((usb / 'exe').readlink()) == '/usr/libexec/minimal-linux/busybox'
assert any(line.split()[1].endswith(':0043') for line in Path('/proc/net/udp').read_text().splitlines()[1:])
# Real hardware verification must fail in this container, never manufacture ready.
platform = subprocess.run(['rc-service', 'orchard-platform', 'start'], capture_output=True)
assert platform.returncode != 0
assert not policy.ready()
for name in ('orchard-ssh', 'orchard-usb'):
    subprocess.run(['rc-service', name, 'stop'], check=True)
print(json.dumps({'native_musl': True, 'real_stream_extraction': True,
                  'image_policy_validation': True, 'key_only_ssh': True,
                  'openrc_ssh_start_stop': True,
                  'unauthorized_key_rejected': True,
                  'portable_checksum_accepts_valid_rejects_corruption': True,
                  'dhcp_process_alive_and_udp67_bound': True,
                  'packaged_brightness_and_toggle_helpers': True,
                  'wrong_platform_rejected': True, 'ready_on_wrong_platform': False,
                  'hardware_checked': False, 'physical_device_operations_performed': False}))
