#!/usr/bin/env python3
"""orchard build's entry (orchard.toml [release]): the loader and Alpine base, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all] [--arch aarch64|armv7]` in this checkout. A release has one
root, of one architecture: the selected platforms' (apple-armv7: armv7), else --arch, else aarch64. The loader and base land in out/components/NAME/KEY/, keyed
by the files they are made from, so a build redoes only what changed.
orchard supplies m1n1, Pongo, the static tools and every platform's kernel
from its shared cache; the Alpine artwork is data for orchard's m1n1. The release itself is always assembled anew.
How orchard got them (built, reused, or downloaded from a nightly) stays in
out/releases/VERSION.orchard-inputs.json, beside the release.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import snapshot  # noqa: E402  orchard's snapshot and commands; none of its Python
# What each component is made from, relative to this checkout.
INPUTS = {
    'base': ['build_base.py', 'system/Containerfile', 'system/install-base'],
    'base-armv7': ['build_base.py', 'system/armv7/Containerfile', 'system/armv7/install-base'],
    'artwork': ['boot/build-artwork.py', 'boot/generate-logo.py', 'boot/splash.py', 'boot/artwork'],
}


def python(*argv):
    print('+', sys.executable, ' '.join(map(str, argv)), flush=True)
    subprocess.run([sys.executable, *map(str, argv)], cwd=PROJECT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    parser.add_argument('--arch', choices=sorted(set(snapshot.ARCHITECTURES.values())),
                        help="the root's architecture (default: the selected platforms', else aarch64)")
    parser.add_argument('--orchard', type=Path, help='orchard snapshot (default: ORCHARD_CHECKOUT, then .orchard)')
    args = parser.parse_args()
    orchard = snapshot.root(args.orchard)
    if 'all' in args.platform and len(args.platform) > 1:
        parser.error('--platform all builds every platform and combines with no other')
    known = snapshot.platforms(orchard)
    named = [name for name in args.platform if name != 'all']
    unknown = sorted(set(named) - set(known))
    if unknown:
        parser.error(f'unknown platform {", ".join(unknown)}; orchard describes {", ".join(known)}')
    architectures = {known[name] for name in named} | ({args.arch} if args.arch else set())
    if len(architectures) > 1:
        parser.error('one release has one root: choose platforms of one architecture')
    arch = architectures.pop() if architectures else 'aarch64'
    if not named and arch != 'aarch64':
        named = sorted(name for name, value in known.items() if value == arch)
    # Without names, orchard's inputs cover every arm64 platform.
    selected = [part for name in named for part in ('--platform', name)]

    if arch == 'aarch64':
        base = snapshot.component('base', INPUTS['base'],
                                  lambda path, work: python('build_base.py', '--output', path), artifact='base.tar.gz')
    else:
        base = snapshot.component(f'base-{arch}', INPUTS[f'base-{arch}'],
                                  lambda path, work: python('build_base.py', '--arch', arch, '--output', path),
                                  artifact='base.tar.gz')
    artwork = snapshot.component('artwork', INPUTS['artwork'],
                                 lambda path, work: python('boot/build-artwork.py', '--output', path),
                                 artifact='artwork')
    (PROJECT / 'out').mkdir(exist_ok=True)
    # What orchard supplies finished: kernels, boards, m1n1, Pongo, tools (orchard.inputs). Kept beside the
    # release, not in it (its paths are this host's): under "produced" it says how orchard got each one.
    resolved = args.output.parent / f'{args.output.name}.orchard-inputs.json'
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.inputs-', dir=PROJECT / 'out') as temporary:
        snapshot.command(orchard, 'inputs', '--output', resolved, *selected)
        inputs = Path(temporary) / 'public'
        pinned = ['--splash', artwork / 'splash', '--logo', artwork / 'logo.bin']
        if arch == 'aarch64':
            # orchard's static arm64 tools; an armv7 root has Alpine's packages of them.
            shared = json.loads(resolved.read_text())['shared']
            tools = {name: Path(path) for name, path in shared['tools'].items()}
            pinned += ['--loader', shared['m1n1'], '--pongo', shared['pongo'],
                       '--busybox', tools['busybox'], '--dropbear', tools['dropbear'],
                       '--dropbearkey', tools['dropbearkey'], '--wpa-supplicant', tools['wpa_supplicant'],
                       '--wpa-cli', tools['wpa_cli'], '--iw', tools['iw']]
        python('pin_components.py', *pinned, '--output', inputs)
        python('build.py', '--arch', arch, '--base', base, '--base-receipt', base.with_name(base.name + '.json'),
               '--inputs', inputs / 'inputs.json', '--orchard-inputs', resolved, '--orchard', orchard,
               '--version', args.version, '--output', args.output)
    python('audit.py', args.output, '--orchard', orchard)
    # install.sh and orchard-install.pyz, with orchard's launch loaders.
    snapshot.command(orchard, 'installer', 'release', args.output)


if __name__ == '__main__':
    main()
