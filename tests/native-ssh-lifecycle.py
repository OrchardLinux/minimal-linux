#!/usr/bin/python3
"""Inside an isolated image container: real bind mount, SSH and OpenRC teardown.

No physical devices and no fabricated hardware/readiness success markers.
"""
import base64
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, '/usr/libexec/minimal-linux')
import image_policy as policy
import ssh_access

SYSTEMD = '--systemd' in sys.argv


def run(*argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} exited {result.returncode}: {result.stdout}\n{result.stderr}')
    return result


run('ip', 'link', 'add', 'usb0', 'type', 'dummy')
run('ip', 'addr', 'add', '172.16.42.1/24', 'dev', 'usb0')
run('ip', 'link', 'set', 'usb0', 'up')
if SYSTEMD:
    assert Path('/proc/1/exe').readlink().name == 'systemd'
else:
    Path('/run/openrc').mkdir(exist_ok=True)
    Path('/run/openrc/softlevel').write_text('default')
Path('/run/orchard').mkdir(mode=0o700, exist_ok=True)
Path('/run/recovery').mkdir(mode=0o700, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    identity = tmp / 'identity'
    run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(identity))
    authorization = Path('/run/recovery/authorized_keys')
    authorization.write_text(' '.join(identity.with_suffix('.pub').read_text().split()[:2]) + '\n')
    authorization.chmod(0o600)
    # The host key normally arrives from recovery; create the same ephemeral material here.
    run('dropbearkey', '-t', 'ed25519', '-f', '/run/recovery/ssh_host_ed25519_key')
    public = next(row for row in run('dropbearkey', '-y', '-f', '/run/recovery/ssh_host_ed25519_key').stdout.splitlines() if row.startswith('ssh-ed25519 '))
    Path('/run/recovery/ssh_host_ed25519_key.pub').write_text(' '.join(public.split()[:2])+'\n')
    if SYSTEMD:
        run('systemctl', 'start', 'omarchy-diagnostics.service')
    else:
        run('rc-service', 'orchard-session', 'start')
        run('rc-service', 'orchard-diagnostics', 'start')
    deadline = time.monotonic() + 8
    while True:
        try:
            with socket.create_connection(('172.16.42.1', 22), timeout=0.2):break
        except OSError:
            if time.monotonic() > deadline:raise
            time.sleep(0.05)
    assert authorization.samefile('/root/.ssh/authorized_keys')
    # A non-recursive parent bind exposes the DISK placeholder beneath the RAM bind.
    disk_view = tmp / 'disk-view'
    disk_view.mkdir()
    run('mount', '--bind', '/root/.ssh', str(disk_view))
    try:assert (disk_view / 'authorized_keys').read_bytes() == b''
    finally:run('umount', str(disk_view))
    hosts = tmp / 'known_hosts'
    hosts.write_text('172.16.42.1 ' + Path('/run/recovery/ssh_host_ed25519_key.pub').read_text())
    ssh = ['ssh', '-i', str(identity), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile='+str(hosts), 'root@172.16.42.1']
    assert run(*ssh, 'echo access-retained').stdout.strip() == 'access-retained'
    release = json.loads(Path('/etc/orchard/release.json').read_text())['release']
    request = base64.urlsafe_b64encode(json.dumps({'protocol':1,'release':release,
                                      'boot_id':ssh_access.BOOT_ID.read_text().strip()}).encode()).decode()
    rejected = subprocess.run([*ssh, '/usr/bin/orchard-device revoke-ssh '+request], capture_output=True, text=True)
    assert rejected.returncode != 0 and 'verified system readiness' in rejected.stdout
    assert run(*ssh, 'echo still-retained-after-failed-readiness').returncode == 0
    # Keep a second real connection open; it must be disconnected, not merely denied on reconnect.
    other = subprocess.Popen([*ssh, 'echo opened; sleep 120'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == 'opened'
        # Test the teardown primitive directly, WITHOUT faking a successful hardware gate.
        code = "import sys,json;sys.path.insert(0,'/usr/libexec/minimal-linux');import ssh_access,image_policy;print(json.dumps(ssh_access.revoke("+repr(release)+",image_policy.DIAGNOSTICS_EXECUTABLE,image_policy.stop_diagnostics)))"
        result = json.loads(run(*ssh, 'python3 -c '+shlex.quote(code)).stdout)
        assert result['ssh_access'] == 'revoked'
        assert other.wait(timeout=5) != 0
    finally:
        if other.poll() is None:other.kill();other.wait()
        other.stdout.close();other.stderr.close()
    assert ssh_access.revoked(release)
    assert not ssh_access.server_pids(str(Path(policy.DIAGNOSTICS_EXECUTABLE).resolve()))
    assert not Path('/root/.ssh/authorized_keys').exists()
    for name in ('authorized_keys','ssh_host_ed25519_key','ssh_host_ed25519_key.pub'):
        assert not (Path('/run/recovery')/name).exists()
    try:
        with socket.create_connection(('172.16.42.1',22),timeout=0.5):raise AssertionError('SSH listener remains')
    except ConnectionRefusedError:pass
    restart = subprocess.run(['/sbin/recovery-start-ssh'],capture_output=True,text=True)
    assert restart.returncode != 0 and 'retired for this boot' in restart.stderr
    reauthorize = subprocess.run(['/sbin/authorize-key'],input=identity.with_suffix('.pub').read_text(),capture_output=True,text=True)
    assert reauthorize.returncode != 0 and 'retired for this boot' in reauthorize.stderr
print(json.dumps({'init': 'systemd' if SYSTEMD else 'OpenRC', 'real_ssh':True,'ram_bind_only_no_persisted_public_key':True,
    'failed_readiness_preserves_access':True,'final_rpc_receipt_received':True,
    'other_connection_closed':True,'listener_stopped':True,'ram_credentials_removed':True,
    'restart_and_reauthorization_blocked':True,'physical_device_operations_performed':False}))
