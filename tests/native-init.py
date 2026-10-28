"""Boot the finished BusyBox/OpenRC userspace in an isolated container.

Only ephemeral authentication and a dummy USB interface are fixtures. Hardware
checks are NOT mocked: they must fail, and readiness must remain false.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image')
args = parser.parse_args()
setup = r'''
set -eu
ip link add usb0 type dummy
ip address add 172.16.42.1/30 dev usb0
ip link set usb0 up
ssh-keygen -q -t ed25519 -N '' -f /tmp/client
mkdir -p /root/.ssh /run/recovery /run/orchard
chmod 700 /root/.ssh
cp /tmp/client.pub /run/recovery/authorized_keys
chmod 600 /run/recovery/authorized_keys
/usr/bin/dropbearkey -t ed25519 -f /run/recovery/ssh_host_ed25519_key >/dev/null 2>&1
exec /sbin/init
'''
cid = subprocess.check_output(['podman', 'create', '--network', 'none', '--cap-add', 'NET_ADMIN',
                               '--cap-add', 'NET_RAW', '--cap-add', 'SYS_ADMIN',
                               '--tmpfs', '/run:rw,nodev,nosuid',
                               args.image, '/bin/sh', '-c', setup], text=True).strip()
try:
    subprocess.run(['podman', 'start', cid], check=True, stdout=subprocess.DEVNULL)
    end = time.monotonic() + 15
    check = "from pathlib import Path; assert Path('/run/openrc/started/orchard-diagnostics').exists(); assert Path('/run/openrc/started/orchard-dhcp').exists(); assert Path('/run/orchard-platform.log').exists(); p=Path('/proc')/Path('/run/orchard-dhcp.pid').read_text().strip(); assert str((p/'exe').readlink()) == '/usr/libexec/minimal-linux/busybox'; assert any(line.split()[1].endswith(':0043') for line in Path('/proc/net/udp').read_text().splitlines()[1:])"
    while True:
        probe = subprocess.run(['podman', 'exec', cid, '/usr/bin/python3', '-c', check], capture_output=True)
        if probe.returncode == 0:
            break
        if time.monotonic() >= end:
            raise RuntimeError(subprocess.check_output(['podman', 'logs', cid], stderr=subprocess.STDOUT, text=True))
        time.sleep(.1)
    verify = r'''
import json,subprocess
from pathlib import Path
assert str(Path('/proc/1/exe').readlink()) == '/usr/bin/busybox'
assert Path('/proc/1/cmdline').read_bytes().split(b'\0')[0] in (b'/sbin/init', b'init')
assert subprocess.run(['/usr/libexec/minimal-check-platform'], capture_output=True).returncode != 0
status=json.loads(subprocess.check_output(['/usr/bin/orchard-device','status']))['result']
assert status['ready'] is False
assert not Path('/run/minimal-linux-ready.json').exists()
assert not Path('/run/openrc/started/orchard-ready').exists()
print(json.dumps({'busybox_pid1':True,'openrc_booted':True,'diagnostics_started':True,
 'dhcp_started':True,'dhcp_process_alive_and_udp67_bound':True,'hardware_gate_failed_as_expected':True,'ready':False,
 'fixtures':'Ephemeral public-key session and dummy USB NIC only',
 'physical_device_operations_performed':False}))
'''
    print(subprocess.check_output(['podman', 'exec', cid, '/usr/bin/python3', '-c', verify], text=True))
finally:
    subprocess.run(['podman', 'rm', '-f', cid], check=True, stdout=subprocess.DEVNULL)
