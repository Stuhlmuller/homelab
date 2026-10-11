#!/usr/bin/env python3
"""Release layout preserves signatures and rejects unsigned or unsafe entries."""

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cache", ROOT / "scripts/nix-cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)
spec = importlib.util.spec_from_file_location("builder", ROOT / "scripts/nix-builder.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CacheLayoutTests(unittest.TestCase):
    def test_builder_archive_rejects_escape_and_symlinks(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as stream:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    stream.addfile(member)
                with self.assertRaises(ValueError):
                    builder.unpack(archive.getvalue(), Path(temporary))

    def test_shared_nar_preserves_signed_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nar").mkdir()
            (root / "nar/shared.nar.xz").write_bytes(b"fixture")
            fields = "StorePath: /nix/store/fixture\nNarHash: sha256:fixture\nNarSize: 7\nReferences: \nSig: fixture:signature\n"
            for name in ("a", "b"):
                (root / f"{name}.narinfo").write_text("URL: nar/shared.nar.xz\n" + fields)
            cache.flatten(root)
            for name in ("a", "b"):
                self.assertEqual((root / f"{name}.narinfo").read_text(), "URL: shared.nar.xz\n" + fields)
            self.assertEqual((root / "shared.nar.xz").read_bytes(), b"fixture")

    def test_unsigned_and_traversal_are_rejected(self):
        for entry in ("URL: nar/file.nar.xz\n", "URL: ../private\nSig: fixture:signature\n"):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "a.narinfo").write_text(entry)
                with self.assertRaises(ValueError):
                    cache.flatten(root)


if __name__ == "__main__":
    unittest.main()
