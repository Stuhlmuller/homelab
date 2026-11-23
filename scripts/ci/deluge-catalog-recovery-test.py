#!/usr/bin/env python3
"""Exercise the recovery path boundary without Deluge or libtorrent installed."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
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


class ResumeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.current = self.root / 'torrents.fastresume'
        for name, value in (('FASTRESUME', self.current), ('ARCHIVE_DIR', self.root),
                            ('decode_resume_data', json.loads)):
            patcher = patch.object(RECOVERY, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def archive(self, name, data, modified):
        path = self.root / name
        with tarfile.open(path, 'w:xz') as archive:
            member = tarfile.TarInfo('state/torrents.fastresume')
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        os.utime(path, (modified, modified))
        return path

    def test_complete_current_source_never_opens_archives(self):
        data = b'{"abc": "resume"}'
        self.current.write_bytes(data)
        self.archive('old.tar.xz', b'invalid', 1)
        with patch.object(RECOVERY.tarfile, 'open', side_effect=AssertionError('archive opened')):
            self.assertEqual(RECOVERY.load_complete_resume_data({'abc'}), ({'abc': 'resume'}, data))

    def test_truncated_newest_archive_falls_back_to_complete_older_source(self):
        data = b'{"abc": "resume"}'
        self.current.write_bytes(b'invalid')
        self.archive('older.tar.xz', data, 1)
        newest = self.archive('newest.tar.xz', b'x' * (2 * 1024 * 1024), 2)
        contents = newest.read_bytes()
        newest.write_bytes(contents[:len(contents) // 2])
        os.utime(newest, (2, 2))
        self.assertEqual(RECOVERY.load_complete_resume_data({'abc'}), ({'abc': 'resume'}, data))

    def test_incomplete_sources_fail_without_changing_current_data(self):
        data = b'{"other": "resume"}'
        self.current.write_bytes(data)
        self.archive('old.tar.xz', b'invalid', 1)
        with self.assertRaisesRegex(ValueError, 'refusing partial recovery'):
            RECOVERY.load_complete_resume_data({'abc'})
        self.assertEqual(self.current.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
