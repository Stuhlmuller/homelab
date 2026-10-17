#!/usr/bin/env python3
"""Exercise the recovery path boundary without Deluge or libtorrent installed."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'clusters/homelab/apps/deluge/recover-torrent-catalog.py'
SPEC = importlib.util.spec_from_file_location('catalog_recovery', SCRIPT)
RECOVERY = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {
    'libtorrent': SimpleNamespace(), 'deluge': SimpleNamespace(),
    'deluge.core': SimpleNamespace(),
    'deluge.core.torrentmanager': SimpleNamespace(TorrentManagerState=object, TorrentState=object),
}):
    SPEC.loader.exec_module(RECOVERY)


class PathTests(unittest.TestCase):
    def test_download_roots_and_nested_paths(self):
        for path in ('/downloads', '/downloads/complete/series', '/downloads/series name'):
            self.assertEqual(RECOVERY.validated_download_path(path.encode()), path)

    def test_parent_traversal_and_outside_paths_are_rejected(self):
        for path in ('/downloads/../../config', '/downloads/a/../b', '/downloads/..',
                     '/downloads-other/file', '/config', 'downloads/file', ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                RECOVERY.validated_download_path(path.encode())


if __name__ == '__main__':
    unittest.main()
