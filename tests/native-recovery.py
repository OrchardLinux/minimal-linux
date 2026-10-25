"""Execute Python/API from the candidate's actual initramfs, not a rebuilt root."""
import argparse
import gzip
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import audit, newc

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
audit(args.directory)
framing = json.loads((args.directory / 'recovery.bin.json').read_text())
part = next(p for p in framing['components'] if p['name'] == 'initramfs')
with (args.directory / 'recovery.bin').open('rb') as stream:
    stream.seek(part['offset'])
    entries = newc(gzip.decompress(stream.read(part['bytes'])))
with tempfile.TemporaryDirectory(prefix='minimal-recovery-probe-') as temporary:
    archive = Path(temporary) / 'recovery.tar.gz'
    with tarfile.open(archive, 'w:gz') as target:
        for name, (data, mode) in entries.items():
            member = tarfile.TarInfo(name)
            member.mode = stat.S_IMODE(mode)
            if stat.S_ISDIR(mode):
                member.type = tarfile.DIRTYPE
            elif stat.S_ISLNK(mode):
                member.type, member.linkname = tarfile.SYMTYPE, data.decode()
            elif stat.S_ISREG(mode):
                member.size = len(data)
            else:
                raise ValueError('Unexpected initramfs type')
            target.addfile(member, io.BytesIO(data) if member.isfile() else None)
    tag = 'localhost/orchard-minimal-recovery-probe:' + json.loads((args.directory / 'rootfs.json').read_text())['release']
    subprocess.run(['podman', 'import', str(archive), tag], check=True, stdout=subprocess.DEVNULL)
    code = "import gzip,ssl,ctypes,json,subprocess; r=json.loads(subprocess.check_output(['/usr/bin/orchard-device','status']))['result']; assert r['ready'] is False; print(json.dumps({'actual_initramfs_python':True,'actual_api_status':True,'ready':False,'libc':'musl','physical_device_operations_performed':False}))"
    command = '/bin/busybox --install -s; exec /usr/bin/python3 -c ' + __import__('shlex').quote(code)
    print(subprocess.check_output(['podman', 'run', '--rm', '--network', 'none', tag,
                                   '/bin/busybox', 'sh', '-c', command], text=True))
