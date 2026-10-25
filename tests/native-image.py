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

sys.path.insert(0, '/usr/libexec/orchard-j71b')
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

# Exercise the actual platform checker's checksum command with Alpine's tools,
# without bypassing its real hardware preconditions in the shipped checker.
checksum = Path('/usr/libexec/j71b-check-platform').read_text().splitlines()[-1]
assert checksum == 'sha256sum -c /usr/share/ipadlinux/hardware.SHA256SUMS >/dev/null'
Path('/tmp/checksum-data').write_bytes(b'known data')
Path('/tmp/checksums').write_text(hashlib.sha256(b'known data').hexdigest() + '  /tmp/checksum-data\n')
check = checksum.replace('/usr/share/ipadlinux/hardware.SHA256SUMS', '/tmp/checksums')
subprocess.run(['sh', '-c', check], check=True)
Path('/tmp/checksum-data').write_bytes(b'corrupted')
assert subprocess.run(['sh', '-c', check], capture_output=True).returncode != 0
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
subprocess.run(['ip', 'address', 'add', '172.16.42.1/32', 'dev', 'lo'], check=True)
subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/client'], check=True)
key = ' '.join(Path('/tmp/client.pub').read_text().split()[:2])
request = base64.urlsafe_b64encode(json.dumps({'protocol': 1, 'public_key': key}).encode()).decode()
first = json.loads(subprocess.check_output(['/usr/bin/orchard-device', 'bootstrap', request]))['result']
pid = Path('/run/recovery/dropbear.pid').read_text()
second = json.loads(subprocess.check_output(['/usr/bin/orchard-device', 'bootstrap', request]))['result']
assert first == second and Path('/run/recovery/dropbear.pid').read_text() == pid
Path('/tmp/known_hosts').write_text(first['host'] + ' ' + first['host_key'] + '\n')
ssh = ['ssh', '-F', '/dev/null', '-i', '/tmp/client', '-o', 'IdentitiesOnly=yes',
       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/tmp/known_hosts',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3', 'root@' + first['host']]
status = json.loads(subprocess.check_output([*ssh, '/usr/bin/orchard-device status']))
assert status['result']['release'] == receipt['release']
assert status['result']['ready'] is False
diag = json.loads(subprocess.check_output([*ssh, '/usr/bin/orchard-device diagnostics']))['result']
assert diag['ready'] is False and isinstance(diag['logs'], dict)
assert 'journalctl' not in diag['logs']
subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/unauthorized'], check=True)
wrong = list(ssh)
wrong[wrong.index('-i') + 1] = '/tmp/unauthorized'
assert subprocess.run([*wrong, 'true'], capture_output=True).returncode != 0
# Exercise actual OpenRC start/stop around the finished-image diagnostics helper.
subprocess.run(['kill', pid.strip()], check=True)
# The container's --init reaper adopts the daemon, just as BusyBox PID 1 does.
end = time.monotonic() + 5
while Path('/proc/' + pid.strip()).exists():
    if time.monotonic() >= end:
        raise AssertionError('Container did not reap the bootstrap daemon')
    time.sleep(.02)
# Handoff's only credential transfer: the current ephemeral public key in /run.
# Do not call real storage/handoff operations in a container.
Path('/run/recovery/authorized_keys').write_bytes(Path('/root/.ssh/authorized_keys').read_bytes())
# The recovery root is discarded at handoff; the installed root starts without keys.
Path('/root/.ssh/authorized_keys').unlink()
Path('/run/openrc').mkdir(exist_ok=True)
Path('/run/openrc/softlevel').write_text('default\n')
subprocess.run(['ip', 'address', 'del', '172.16.42.1/32', 'dev', 'lo'], check=True)
subprocess.run(['ip', 'link', 'add', 'usb0', 'type', 'dummy'], check=True)
subprocess.run(['ip', 'address', 'add', '172.16.42.1/30', 'dev', 'usb0'], check=True)
subprocess.run(['ip', 'link', 'set', 'usb0', 'up'], check=True)
for name in ('orchard-session', 'orchard-diagnostics', 'orchard-dhcp'):
    subprocess.run(['rc-service', name, 'start'], check=True)
subprocess.check_output([*ssh, 'true'])
subprocess.run(['rc-service', 'orchard-diagnostics', 'status'], check=True)
dhcp = Path('/proc') / Path('/run/orchard-dhcp.pid').read_text().strip()
assert str((dhcp / 'exe').readlink()) == '/usr/libexec/minimal-linux/busybox'
assert any(line.split()[1].endswith(':0043') for line in Path('/proc/net/udp').read_text().splitlines()[1:])
# Real hardware verification must fail in this container, never manufacture ready.
platform = subprocess.run(['rc-service', 'orchard-platform', 'start'], capture_output=True)
assert platform.returncode != 0
assert not policy.ready()
subprocess.run(['rc-service', 'orchard-diagnostics', 'stop'], check=True)
subprocess.run(['rc-service', 'orchard-dhcp', 'stop'], check=True)
print(json.dumps({'native_musl': True, 'real_stream_extraction': True,
                  'image_policy_validation': True, 'pinned_key_only_ssh': True,
                  'bootstrap_idempotent': True, 'openrc_diagnostics_start_stop': True,
                  'unauthorized_key_rejected': True, 'non_systemd_diagnostics': True,
                  'portable_checksum_accepts_valid_rejects_corruption': True,
                  'dhcp_process_alive_and_udp67_bound': True,
                  'packaged_brightness_and_toggle_helpers': True,
                  'wrong_platform_rejected': True, 'ready_on_wrong_platform': False,
                  'hardware_checked': False, 'physical_device_operations_performed': False}))
