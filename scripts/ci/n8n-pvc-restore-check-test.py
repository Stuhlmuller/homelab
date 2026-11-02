#!/usr/bin/env python3
"""Offline PVC archive restoration and secret-boundary fixtures."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from importlib.machinery import SourceFileLoader


ROOT = Path(__file__).resolve().parents[2]
verify = SourceFileLoader("n8n_pvc_restore", str(ROOT / "scripts/ci/n8n-pvc-restore-check.py")).load_module().verify


def archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as stream:
        for name, body in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(body)
            stream.addfile(entry, io.BytesIO(body))


class RestoreTests(unittest.TestCase):
    def test_restores_config_and_binary_data_without_disclosing_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "n8n.tar"
            key = "private-test-encryption-key"
            archive(path, {"./config": json.dumps({"encryptionKey": key}).encode(),
                           "./binaryData/blob": b"test-payload"})
            result = verify(path)
            self.assertEqual(result["files"], 2)
            self.assertEqual(len(result["config_sha256"]), 64)
            self.assertNotIn(key, json.dumps(result))

    def test_rejects_missing_persisted_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "n8n.tar"
            archive(path, {"./config": b"{}"})
            with self.assertRaises(ValueError):
                verify(path)

    def test_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "n8n.tar"
            archive(path, {"./config": b'{"encryptionKey":"example"}',
                           "../escape": b"bad"})
            with self.assertRaises(ValueError):
                verify(path)

    def test_rejects_absolute_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "n8n.tar"
            with tarfile.open(path, "w") as stream:
                config = b'{"encryptionKey":"example"}'
                entry = tarfile.TarInfo("./config")
                entry.size = len(config)
                stream.addfile(entry, io.BytesIO(config))
                link = tarfile.TarInfo("./outside")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                stream.addfile(link)
            with self.assertRaises((ValueError, tarfile.FilterError)):
                verify(path)


if __name__ == "__main__":
    unittest.main()
