#!/usr/bin/env python3
"""Export signed Alpine ARMv7 packages for the P105 RAM recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.absolute()
    receipt = output.with_suffix('.json')
    if output.exists() or output.is_symlink() or receipt.exists():
        parser.error('Choose a fresh base output')
    output.parent.mkdir(parents=True, exist_ok=True)
    recipe = Path(__file__).with_name('Containerfile')
    tag = 'localhost/orchard-p105-recovery-base:alpine'
    subprocess.run(['podman', 'build', '-t', tag, '-f', str(recipe), str(recipe.parent)], check=True)
    image = subprocess.check_output(['podman', 'image', 'inspect', tag, '--format', '{{.Id}}'], text=True).strip()
    with output.open('xb') as stream:
        subprocess.run(['podman', 'run', '--rm', '--network', 'none', image,
                        'tar', '-C', '/armroot', '-cf', '-', '.'], stdout=stream, check=True)
    receipt.write_text(json.dumps({'schema': 1, 'architecture': 'armv7h',
        'signed_apk': True, 'image': image, 'bytes': output.stat().st_size,
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'recipe_sha256': hashlib.sha256(recipe.read_bytes()).hexdigest()}, indent=2)+'\n')


if __name__ == '__main__':
    main()
