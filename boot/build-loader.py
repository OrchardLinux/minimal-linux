#!/usr/bin/env python3
"""Supply Alpine artwork to the installed, distro-neutral m1n1 producer."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
from orchard.hardware import ROOT as HARDWARE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--logo-header', type=Path, help='pre-generated matching artwork header (CI)')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='alpine-loader-') as temporary:
        header = args.logo_header or Path(temporary) / 'alpine-logo.h'
        if not args.logo_header:
            subprocess.run([sys.executable, str(here / 'generate-logo.py'),
                            '--output', str(header)], check=True)
        command = [str(HARDWARE / 'boot/m1n1/build'),
                   'j71b', '--output', str(args.output), '--work-dir',
                   str(here / 'm1n1/.work/j71b'), '--extra-patch',
                   str(here / 'm1n1/patches/0002-alpine-splash.patch'),
                   '--include-header', str(header), '--extra-cflags', '-DALPINE_SPLASH']
        if args.resume:
            command.append('--resume')
        subprocess.run(command, check=True)


if __name__ == '__main__':main()
