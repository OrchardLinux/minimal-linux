"""Validate Orchard producer records against the shared Alpine release root."""
from pathlib import Path

TOOLS = ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw')


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
        records.append((str(Path(loader['file'])), {key: str(Path(tools[key])) for key in TOOLS}))
    if any(record != records[0] for record in records[1:]):
        raise ValueError('Platforms in one release need the same loader and static tools')
    if not isinstance(shared.get('pongo'), str) or not shared['pongo']:
        raise ValueError('The ARM64 release needs its Pongo input')
    loader, tools = records[0]
    return {'m1n1': loader, 'pongo': shared['pongo'], 'tools': tools}
