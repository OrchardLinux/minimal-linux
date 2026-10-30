#!/usr/bin/env python3
"""Export signed Alpine ARMv7 packages for the P105 RAM recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-cache', action='store_true', help='refresh the package build without cached layers')
    args = parser.parse_args()
    output = args.output.absolute()
    receipt = output.with_suffix('.json')
    if output.exists() or output.is_symlink() or receipt.exists() or receipt.is_symlink():
        parser.error('Choose a fresh base output')
    output.parent.mkdir(parents=True, exist_ok=True)
    recipe = Path(__file__).with_name('Containerfile')
    with tempfile.TemporaryDirectory(prefix='p105-recovery-base-') as temporary:
        image_file = Path(temporary)/'image.id'
        command = ['podman', 'build', '--iidfile', str(image_file)]
        if args.no_cache:
            command.append('--no-cache')
        subprocess.run([*command, '-f', str(recipe), str(recipe.parent)], check=True)
        image = image_file.read_text().strip()
        if not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', image):
            parser.error('Podman returned an invalid base image ID')
        observed = subprocess.check_output(['podman', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
        if observed.removeprefix('sha256:') != image.removeprefix('sha256:'):
            parser.error('Podman image inspection differs from the build output')
        with output.open('xb') as stream:
            subprocess.run(['podman', 'run', '--rm', '--network', 'none', image,
                            'tar', '-C', '/armroot', '-cf', '-', '.'], stdout=stream, check=True)
        with receipt.open('x') as stream:
            stream.write(json.dumps({'schema': 1, 'architecture': 'armv7h',
                'signed_apk': True, 'image': image, 'bytes': output.stat().st_size,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'recipe_sha256': hashlib.sha256(recipe.read_bytes()).hexdigest()}, indent=2)+'\n')


if __name__ == '__main__':
    main()
