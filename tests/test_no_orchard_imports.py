"""orchard's distribution contract: this image's build runs orchard's commands, never imports its Python."""
import ast
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def scripts():
    for path in sorted(PROJECT.rglob('*')):
        relative = path.relative_to(PROJECT)
        if not path.is_file() or relative.parts[0] in ('tests', '.orchard', '.venv', 'out', '.git'):
            continue
        if path.suffix == '.py' or (not path.suffix and path.read_bytes()[:30].startswith(b'#!/usr/bin/env python')):
            yield path


class NoOrchardImports(unittest.TestCase):
    def test_no_build_script_imports_orchard(self):
        checked = 0
        for path in scripts():
            checked += 1
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else [])
                for name in names:
                    with self.subTest(script=str(path.relative_to(PROJECT)), imports=name):
                        self.assertNotEqual(name.split('.')[0], 'orchard')
        self.assertGreater(checked, 5)


if __name__ == '__main__':
    unittest.main()
