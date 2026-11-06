"""Validate Orchard producer records against the shared Alpine release root."""
from pathlib import Path
import struct

TOOLS = ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw')


def lwvm_helper(row):
    """Validate an optional mapper before starting the shared ARM64 root build."""
    root_format = row.get('root_format', 'gpt')
    if root_format not in ('gpt', 'lwvm'):
        raise ValueError('Unsupported platform root format')
    value = row.get('tools', {}).get('lwvm')
    if root_format == 'gpt':
        if value is not None:
            raise ValueError('A GPT platform cannot supply an LwVM mapper')
        return None
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('An LwVM platform needs an absolute mapper path')
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The LwVM mapper must be a regular file')
    data = path.read_bytes()
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('The LwVM mapper must match the ARM64 release root')
    if struct.unpack_from('<H', data, 16)[0] not in (2, 3):
        raise ValueError('The LwVM mapper must be an ELF executable')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if not count or size < 56 or offset < 64 or offset + size * count > len(data):
        raise ValueError('The LwVM mapper has invalid ELF program headers')
    entry = struct.unpack_from('<Q', data, 24)[0]
    loadable = False
    executable_entry = False
    for index in range(count):
        kind, flags, start, virtual, _, length, memory, _ = struct.unpack_from('<II6Q', data, offset + index * size)
        if start + length > len(data):
            raise ValueError('The LwVM mapper has a truncated ELF segment')
        if kind == 1:
            if memory < length:
                raise ValueError('The LwVM mapper has an invalid loadable ELF segment')
            loadable |= length > 0
            executable_entry |= bool(flags & 1 and virtual <= entry < virtual + length)
        if kind == 3:
            raise ValueError('The LwVM mapper must be static')
        if kind == 2:
            if length % 16:
                raise ValueError('The LwVM mapper has an invalid dynamic table')
            for position in range(start, start + length, 16):
                tag, _ = struct.unpack_from('<QQ', data, position)
                if tag == 0:
                    break
                if tag == 1:
                    raise ValueError('The LwVM mapper must be static')
            else:
                raise ValueError('The LwVM mapper has an unterminated dynamic table')
    if not loadable:
        raise ValueError('The LwVM mapper has no loadable ELF segment')
    if not executable_entry:
        raise ValueError('The LwVM mapper entry is outside executable file bytes')
    return str(path)


def validate_backend(row):
    """Check a backend's mapper and rescue pair before handing inputs to Orchard."""
    helper = lwvm_helper(row)
    if helper is None:
        return
    tools = row['tools']
    parents = {Path(tools[name]).parent for name in ('dropbear', 'dropbearkey')}
    if len(parents) != 1:
        raise ValueError('The LwVM rescue tools must share a directory')


def components(document):
    """Return one coherent m1n1/tool set for the existing ARM64 release."""
    if document.get('architecture', 'arm64') != 'arm64':
        raise ValueError('The release needs an ARM64 base; build ARMv7 recovery bases with armv7/build-base.py')
    platforms = document.get('platforms', {})
    if not platforms:
        raise ValueError('Orchard inputs name no platforms')
    shared = document.get('shared', {})
    records = []
    for name, row in platforms.items():
        if row.get('architecture', 'arm64') != 'arm64' or row.get('image', 'Image.gz') != 'Image.gz':
            raise ValueError('Platform ' + name + ' does not match the ARM64 release root')
        loader = row.get('loader', {'kind': 'm1n1', 'file': shared.get('m1n1')})
        if loader.get('kind') != 'm1n1' or not loader.get('file'):
            raise ValueError('Platform ' + name + ' needs an m1n1 loader')
        tools = row.get('tools', shared.get('tools', {}))
        if any(not isinstance(tools.get(key), str) or not tools[key] for key in TOOLS):
            raise ValueError('Platform ' + name + ' has incomplete static tools')
        validate_backend(row)
        records.append((str(Path(loader['file'])), {key: str(Path(tools[key])) for key in TOOLS}))
    if any(record != records[0] for record in records[1:]):
        raise ValueError('Platforms in one release need the same loader and static tools')
    if not isinstance(shared.get('pongo'), str) or not shared['pongo']:
        raise ValueError('The ARM64 release needs its Pongo input')
    loader, tools = records[0]
    return {'m1n1': loader, 'pongo': shared['pongo'], 'tools': tools}
