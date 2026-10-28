"""Public archive and ARM dependency checks for the P105 root composer."""
import importlib.util
import argparse
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('p105_root_composer',Path(__file__).resolve().parents[1]/'p105/prepare-recovery.py')
composer=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(composer)


class P105Root(unittest.TestCase):
    def test_output_inside_owner_source_is_rejected_before_reading_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory).resolve()/'owner';source.mkdir()
            args=argparse.Namespace(output=source/'output',initramfs=source)
            with self.assertRaisesRegex(ValueError,'outside its owner input'):
                composer.prepare(args)
            self.assertEqual(list(source.iterdir()),[])

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);archive=base/'base.tar';root=base/'root';root.mkdir()
            with tarfile.open(archive,'w') as stream:
                member=tarfile.TarInfo('../escape');member.size=1
                stream.addfile(member,io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError,'Unsafe'):composer.extract(archive,root)
            self.assertFalse((base/'escape').exists())

    def test_archive_parent_link_cannot_write_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'root';root.mkdir();outside=base/'outside';outside.mkdir()
            (root/'lib').symlink_to(outside,target_is_directory=True)
            archive=base/'base.tar'
            with tarfile.open(archive,'w') as stream:
                member=tarfile.TarInfo('lib/escape');member.size=1
                stream.addfile(member,io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError,'escapes'):composer.extract(archive,root)
            self.assertFalse((outside/'escape').exists())

    def test_absolute_guest_symlink_stays_in_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'root';root.mkdir();archive=base/'base.tar'
            with tarfile.open(archive,'w') as stream:
                member=tarfile.TarInfo('bin/sh');member.type=tarfile.SYMTYPE;member.linkname='/bin/busybox'
                stream.addfile(member)
            composer.extract(archive,root)
            self.assertEqual((root/'bin/sh').readlink(),Path('busybox'))

    def test_target_dependency_parser_rejects_host_executables(self):
        with self.assertRaisesRegex(ValueError,'ARM32'):composer.needed32(b'\x7fELF\x02\x01'+b'\0'*100)


if __name__ == '__main__':unittest.main()
