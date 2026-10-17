#!/usr/bin/env python3
"""Exercise the direct RPC coroutine without Deluge or Twisted installed."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "clusters/homelab/apps/deluge/daemon-status.py"
PRIVATE = "PRIVATE_DETAIL_DO_NOT_PRINT"


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.connect.return_value = "connecting"
        self.client.core.get_torrents_status.return_value = "querying"
        self.client.disconnect.return_value = "disconnecting"
        modules = {
            "deluge": SimpleNamespace(),
            "deluge.ui": SimpleNamespace(),
            "deluge.ui.client": SimpleNamespace(client=self.client),
            "twisted": SimpleNamespace(),
            "twisted.internet": SimpleNamespace(
                defer=SimpleNamespace(inlineCallbacks=lambda function: function),
                task=SimpleNamespace(react=Mock()),
            ),
        }
        spec = importlib.util.spec_from_file_location("daemon_status", SCRIPT)
        self.helper = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch("logging.disable"):
            spec.loader.exec_module(self.helper)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.stdout))
        self.enterContext(contextlib.redirect_stderr(self.stderr))
        self.auth = self.enterContext(patch("builtins.open", mock_open(
            read_data="# comment\nother:ignored:5\nlocalclient:{}:10\n".format(PRIVATE))))

    def assert_failed(self, generator):
        with self.assertRaises(SystemExit) as raised:
            generator.send(None)
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(self.stderr.getvalue(), "Deluge daemon RPC health check failed\n")
        self.assertNotIn(PRIVATE, self.stdout.getvalue() + self.stderr.getvalue())
        self.client.disconnect.assert_called_once_with()

    def connected(self):
        generator = self.helper.status(None)
        self.assertEqual(next(generator), "connecting")
        self.client.connect.assert_called_once_with("127.0.0.1", 58846, "localclient", PRIVATE)
        self.auth.assert_called_once_with("/config/auth", encoding="utf-8")
        self.assertEqual(generator.send(10), "querying")
        self.client.core.get_torrents_status.assert_called_once_with({}, ["state"])
        return generator

    def test_success_counts_only_after_disconnect(self):
        generator = self.connected()
        self.assertEqual(generator.send({
            PRIVATE: {"state": "Error"}, "other": {"state": "Seeding"},
        }), "disconnecting")
        self.assertEqual(self.stdout.getvalue(), "")
        with self.assertRaises(StopIteration):
            generator.send(None)
        self.assertEqual(self.stdout.getvalue(), "Total torrents: 2\nError: 1\n")
        self.assertEqual(self.stderr.getvalue(), "")
        self.client.disconnect.assert_called_once_with()

    def test_empty_catalog_is_healthy(self):
        generator = self.connected()
        self.assertEqual(generator.send({}), "disconnecting")
        with self.assertRaises(StopIteration):
            generator.send(None)
        self.assertEqual(self.stdout.getvalue(), "Total torrents: 0\nError: 0\n")

    def test_auth_failures_disconnect_without_connecting(self):
        for data in ("other:ignored:5\n", "localclient:broken\n", "localclient::10\n"):
            with self.subTest(data=data), patch("builtins.open", mock_open(read_data=data)):
                self.client.reset_mock()
                self.stderr.truncate(0)
                self.stderr.seek(0)
                generator = self.helper.status(None)
                self.assertEqual(next(generator), "disconnecting")
                self.assert_failed(generator)
                self.client.connect.assert_not_called()

    def test_missing_auth_file_fails(self):
        with patch("builtins.open", side_effect=FileNotFoundError(PRIVATE)):
            generator = self.helper.status(None)
            self.assertEqual(next(generator), "disconnecting")
            self.assert_failed(generator)
            self.client.connect.assert_not_called()

    def test_connection_failure_is_redacted_and_disconnects(self):
        generator = self.helper.status(None)
        self.assertEqual(next(generator), "connecting")
        self.assertEqual(generator.throw(ConnectionError(PRIVATE)), "disconnecting")
        self.assert_failed(generator)
        self.client.core.get_torrents_status.assert_not_called()

    def test_query_failure_or_timeout_is_redacted_and_disconnects(self):
        for error in (RuntimeError(PRIVATE), TimeoutError(PRIVATE)):
            with self.subTest(error=type(error).__name__):
                self.client.reset_mock()
                self.auth.reset_mock()
                self.stderr.truncate(0)
                self.stderr.seek(0)
                generator = self.connected()
                self.assertEqual(generator.throw(error), "disconnecting")
                self.assert_failed(generator)

    def test_malformed_status_does_not_report_health(self):
        generator = self.connected()
        self.assertEqual(generator.send({PRIVATE: {}}), "disconnecting")
        self.assert_failed(generator)

    def test_disconnect_failure_does_not_report_health(self):
        generator = self.connected()
        self.assertEqual(generator.send({}), "disconnecting")
        with self.assertRaises(SystemExit) as raised:
            generator.throw(ConnectionError(PRIVATE))
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(self.stderr.getvalue(), "Deluge daemon RPC health check failed\n")


if __name__ == "__main__":
    unittest.main()
