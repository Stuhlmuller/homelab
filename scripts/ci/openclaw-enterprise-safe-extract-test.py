#!/usr/bin/env python3
"""Verify the dormant restore runtime rejects unsafe tar members before writing."""

import io
import gzip
import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = ROOT / "builds/openclaw-enterprise-restore/safe-extract.py"


def archive(extra=(), omit=()):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for name in ("database.dump", "database-bootstrap.sql", "SHA256SUMS",
                     "material/", "material/recovery.json"):
            if name in omit:
                continue
            item = tarfile.TarInfo(name)
            if name.endswith("/"):
                item.type = tarfile.DIRTYPE
                tar.addfile(item)
            else:
                content = name.encode()
                item.size = len(content)
                tar.addfile(item, io.BytesIO(content))
        for item in extra:
            content = b"evil" if item.isreg() else None
            item.size = len(content) if content else 0
            tar.addfile(item, io.BytesIO(content) if content else None)
    return output.getvalue()


def member(name, kind=tarfile.REGTYPE, linkname=""):
    item = tarfile.TarInfo(name)
    item.type = kind
    item.linkname = linkname
    return item


class SafeExtract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oce-safe-extract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, mode, payload, limit="1048576"):
        return subprocess.run(["python3", str(EXTRACTOR), mode, limit,
                               str(self.root / "restore")], input=payload,
                              capture_output=True, check=False, timeout=20)

    def test_valid_archive_can_be_checked_then_extracted(self):
        payload = archive()
        self.assertEqual(self.invoke("check", payload).returncode, 0)
        self.assertFalse((self.root / "restore").exists())
        self.assertEqual(self.invoke("extract", payload).returncode, 0)
        self.assertEqual((self.root / "restore/database.dump").read_bytes(),
                         b"database.dump")
        self.assertEqual((self.root / "restore/material/recovery.json").read_bytes(),
                         b"material/recovery.json")
        self.assertEqual((self.root / "restore/database.dump").stat().st_mode & 0o777,
                         0o600)

    def test_traversal_links_devices_sparse_and_duplicates_are_rejected(self):
        sparse = member("material/sparse")
        sparse.pax_headers = {"GNU.sparse.map": "0,4"}
        for name, extra in (
            ("traversal", member("material/../../escaped")),
            ("absolute", member("/tmp/escaped")),
            ("symlink", member("material/link", tarfile.SYMTYPE, "../../escaped")),
            ("hardlink", member("material/link", tarfile.LNKTYPE, "database.dump")),
            ("fifo", member("material/fifo", tarfile.FIFOTYPE)),
            ("device", member("material/device", tarfile.CHRTYPE)),
            ("sparse", sparse),
            ("duplicate", member("database.dump")),
            ("overlong-path", member("material/" + "a" * 5000)),
        ):
            with self.subTest(name=name):
                payload = archive((extra,))
                result = self.invoke("check", payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "restore").exists())
                self.assertFalse((self.root / "escaped").exists())

    def test_unexpected_roots_missing_files_and_oversize_are_rejected(self):
        for name, payload, limit in (
            ("unexpected-root", archive((member("unexpected"),)), "1048576"),
            ("missing-checksums", archive(omit=("SHA256SUMS",)), "1048576"),
            ("oversize", archive(), "1"),
            ("compressed-not-produced", gzip.compress(archive()), "1048576"),
        ):
            with self.subTest(name=name):
                self.assertNotEqual(self.invoke("check", payload, limit).returncode, 0)
                self.assertFalse((self.root / "restore").exists())

    def test_direct_extraction_does_not_follow_traversal(self):
        payload = archive((member("material/../../escaped"),))
        self.assertNotEqual(self.invoke("extract", payload).returncode, 0)
        self.assertFalse((self.root / "escaped").exists())

    def test_overdeep_and_overlong_components_fail_in_both_modes(self):
        for name, path in (
            ("depth", "material/" + "d/" * 64 + "file"),
            ("component", "material/" + "x" * 256),
        ):
            with self.subTest(name=name):
                payload = archive((member(path),))
                self.assertNotEqual(self.invoke("check", payload).returncode, 0)
                self.assertNotEqual(self.invoke("extract", payload).returncode, 0)
                self.assertEqual(
                    [item.name for item in (self.root / "restore/material").iterdir()],
                    ["recovery.json"])

    def test_aggregate_name_budget_is_enforced(self):
        spec = importlib.util.spec_from_file_location("safe_extract", EXTRACTOR)
        extractor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extractor)

        class Stdin:
            def __init__(self, payload):
                self.buffer = io.BytesIO(payload)

        payload = archive((member("material/extra-1"), member("material/extra-2")))
        with patch.object(extractor, "MAX_AGGREGATE_PATH_BYTES", 100), \
             patch.object(sys, "stdin", Stdin(payload)):
            with self.assertRaisesRegex(ValueError, "path budget"):
                extractor.process("check", 1048576, str(self.root / "restore"))
        self.assertFalse((self.root / "restore").exists())


if __name__ == "__main__":
    unittest.main()
