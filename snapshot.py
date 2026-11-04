"""orchard as this image's builds use it: a snapshot of its files and its commands, never its Python.

orchard's distribution contract (docs/distribution-contract.md in orchard):
its producers run as commands from an orchard snapshot, a checkout or a
release's orchard-source.tar.gz unpacked, with PYTHONPATH=SNAPSHOT/src. The
snapshot is ORCHARD_CHECKOUT (orchard build sets it), else --orchard DIR,
else .orchard here (where ci/dependencies clones it).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent


def root(explicit=None):
    """The orchard snapshot's directory."""
    for candidate in (explicit, os.environ.get('ORCHARD_CHECKOUT'), PROJECT / '.orchard'):
        if candidate and (Path(candidate) / 'src/orchard').is_dir():
            return Path(candidate).resolve()
    raise SystemExit('No orchard snapshot: run under orchard build, set ORCHARD_CHECKOUT, or pass --orchard DIR '
                     '(an orchard checkout or a release\'s orchard-source.tar.gz unpacked)')


def command(snapshot, module, *argv, **kwargs):
    """Run orchard's producer MODULE (orchard.NAME) from SNAPSHOT."""
    argv = [sys.executable, '-m', f'orchard.{module}', *map(str, argv)]
    print('+', ' '.join(argv), flush=True)
    environment = {**os.environ, 'PYTHONPATH': str(Path(snapshot) / 'src'), 'ORCHARD_CHECKOUT': str(snapshot)}
    return subprocess.run(argv, env=environment, check=True, **kwargs)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


_NAME = re.compile(r'[a-z0-9][a-z0-9._-]*')


def component(name, inputs, produce, *, artifact, keep=2):
    """A build product of this image keyed by its inputs: out/components/NAME/KEY/ARTIFACT.

    INPUTS are paths relative to the checkout whose files and modes decide the
    result. With the same inputs the earlier result is reused; otherwise
    PRODUCE(path, work) makes ARTIFACT at path. KEEP results per name stay.
    """
    if not _NAME.fullmatch(name) or '/' in artifact or artifact in ('', '.', '..'):
        raise ValueError('Invalid component name or artifact')
    entries = {}
    for relative in inputs:
        top = PROJECT / relative
        files = [top] if top.is_file() else sorted(p for p in top.rglob('*') if p.is_file()
                                                   and '__pycache__' not in p.parts)
        for path in files:
            entries[str(path.relative_to(PROJECT))] = f'{path.stat().st_mode & 0o777}:{sha(path)}'
    if not entries:
        raise ValueError(f'{name}: no input files under {", ".join(inputs)}')
    key = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    directory = PROJECT / 'out/components' / name
    target = directory / key[:16]
    if (target / artifact).exists():
        print(f'Reusing {name}: {target.relative_to(PROJECT)}', flush=True)
        os.utime(target)
        return target / artifact
    print(f'Building {name}: {target.relative_to(PROJECT)}', flush=True)
    partial = directory / f'.partial-{key[:16]}'
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    work = PROJECT / 'out/components/.work' / f'{name}-{key[:16]}'
    work.mkdir(parents=True, exist_ok=True)
    produce(partial / artifact, work)
    if not (partial / artifact).exists():
        raise ValueError(f'{name}: the build made no {artifact}')
    shutil.rmtree(target, ignore_errors=True)
    os.replace(partial, target)
    older = sorted((p for p in directory.iterdir() if p.is_dir() and p != target and not p.name.startswith('.')),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for path in older[max(keep - 1, 0):]:
        shutil.rmtree(path)
    shutil.rmtree(work, ignore_errors=True)
    return target / artifact
