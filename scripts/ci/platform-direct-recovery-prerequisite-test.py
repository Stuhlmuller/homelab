#!/usr/bin/env python3
"""Offline fixtures for the direct-LAN Talos recovery candidate."""

import importlib.util
import json
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "platform_direct_recovery_prerequisite",
    ROOT / "scripts/platform-direct-recovery-prerequisite.py")
target = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(target)
SHA = "a" * 40
PUBLICATION_ID = "b" * 32
NOW = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
NODES = {
    "acer": {"address": "10.1.0.199", "role": "control-plane"},
    "zimaboard-0": {"address": "10.1.0.200", "role": "worker"},
    "zimaboard-1": {"address": "10.1.0.201", "role": "worker"},
    "zimaboard-2": {"address": "10.1.0.202", "role": "worker"},
}


class TalosRunner:
    def __init__(self, role="os:admin", expiry="2026-10-30T10:00:00Z",
                 client_only=None, wrong_node=None, failed_node=None):
        self.calls = []
        self.role = role
        self.expiry = expiry
        self.client_only = client_only
        self.wrong_node = wrong_node
        self.failed_node = failed_node

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs == {"capture_output": True, "text": True,
                          "timeout": 15 if command[3:] == ["config", "info", "-o", "json"] else 30,
                          "check": False}
        assert command[:2] == ["talosctl", "--talosconfig"]
        assert "--insecure" not in command
        if command[3:] == ["config", "info", "-o", "json"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "roles": [self.role], "certNotAfter": self.expiry,
            }), stderr="")
        assert command[3] == "--endpoints" and command[5] == "--nodes"
        assert command[7] == "version"
        address = command[4]
        assert address == command[6]
        if address == self.failed_node:
            return SimpleNamespace(returncode=1, stdout="private failure detail", stderr="")
        if address == self.client_only:
            return SimpleNamespace(returncode=0, stdout="Client:\n  Tag: v1.11.3\n", stderr="")
        seen = self.wrong_node if address == "10.1.0.201" and self.wrong_node else address
        return SimpleNamespace(returncode=0, stdout=(
            f"Client:\n  Tag: v1.11.3\nServer:\n  NODE: {seen}\n"
            "  Tag: v1.11.3\n"), stderr="")


class LocalSocket:
    def __init__(self, address):
        self.address = address

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getsockname(self):
        return (self.address, 41234)


class DirectRecoveryCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.talosconfig = self.directory / "talosconfig"
        self.talosconfig.write_text("private fixture config")
        self.talosconfig.chmod(0o600)
        self.guard = mock.patch.object(target, "reviewed_context", return_value=NODES)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def stage(self, runner):
        def connector(target_address, timeout):
            self.assertEqual(timeout, 5)
            self.assertIn(target_address[0], target.platform.ADDRESSES)
            self.assertEqual(target_address[1], 50000)
            return LocalSocket("10.1.0.50")

        return target.stage(SHA, self.talosconfig, self.directory,
                            runner=runner, connector=connector, now=NOW,
                            publication_id=PUBLICATION_ID)

    def failure_record(self):
        path = self.directory / f"direct-recovery-{PUBLICATION_ID}-failure.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse((self.directory / target.RECEIPT).exists())
        return json.loads(path.read_text())

    def test_probes_each_committed_node_directly_and_stages_private_candidate(self):
        runner = TalosRunner()
        result = self.stage(runner)
        self.assertEqual(result, (self.directory / target.RECEIPT).resolve())
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o600)
        record = json.loads(result.read_text())
        self.assertEqual(record["sourceSha"], SHA)
        self.assertEqual(record["publicationId"], PUBLICATION_ID)
        self.assertEqual(record["nodes"], list(target.platform.NODES))
        self.assertEqual(record["endpoint"], "10.1.0.199:50000")
        self.assertEqual(record["transport"], "direct-lan-authenticated-talos")
        self.assertFalse(record["verified"])
        self.assertTrue(record["candidateVerified"] and record["talosMtls"])
        self.assertEqual(record["clientRole"], "os:admin")
        self.assertEqual(record["serverVersions"], {
            name: "v1.11.3" for name in target.platform.NODES
        })
        self.assertEqual(record["lanSourceAddress"], "10.1.0.50")
        self.assertNotIn("private fixture config", result.read_text())
        self.assertEqual(len(runner.calls), 5)
        self.assertEqual([call[4] for call in runner.calls[1:]],
                         list(target.platform.ADDRESSES))
        with self.assertRaises(ValueError):
            self.stage(TalosRunner())

    def test_client_only_version_success_cannot_claim_a_node(self):
        with self.assertRaises(target.ProbeFailure):
            self.stage(TalosRunner(client_only="10.1.0.201"))
        self.assertEqual(self.failure_record()["node"], "zimaboard-1")

    def test_wrong_server_identity_cannot_claim_a_node(self):
        with self.assertRaises(target.ProbeFailure):
            self.stage(TalosRunner(wrong_node="10.1.0.216"))
        self.assertEqual(self.failure_record()["category"], "talos-server-response-invalid")

    def test_one_failed_node_keeps_diagnostics_private_without_raw_output(self):
        with self.assertRaises(target.ProbeFailure):
            self.stage(TalosRunner(failed_node="10.1.0.202"))
        record = self.failure_record()
        self.assertEqual(record["node"], "zimaboard-2")
        self.assertNotIn("private failure detail", json.dumps(record))

    def test_reader_role_and_short_expiry_fail_before_node_probe(self):
        for runner in (TalosRunner(role="os:reader"),
                       TalosRunner(expiry="2026-10-28T09:59:59Z")):
            with self.subTest(runner=runner.role + runner.expiry):
                with tempfile.TemporaryDirectory() as name:
                    private = Path(name)
                    config = private / "talosconfig"
                    config.write_text("private fixture config")
                    config.chmod(0o600)
                    with self.assertRaises(target.ProbeFailure):
                        target.stage(SHA, config, private, runner=runner,
                                     connector=lambda *_args, **_kwargs: LocalSocket("10.1.0.50"),
                                     now=NOW, publication_id=PUBLICATION_ID)
                    self.assertEqual(len(runner.calls), 1)
                    self.assertFalse((private / target.RECEIPT).exists())

    def test_talosconfig_symlink_and_loose_mode_fail_without_talos(self):
        runner = TalosRunner()
        self.talosconfig.chmod(0o644)
        with self.assertRaises(target.ProbeFailure):
            self.stage(runner)
        self.talosconfig.chmod(0o600)
        link = self.directory / "link"
        link.symlink_to(self.talosconfig)
        with self.assertRaises(target.ProbeFailure):
            target.stage(SHA, link, self.directory, runner=runner,
                         connector=lambda *_args, **_kwargs: LocalSocket("10.1.0.50"),
                         now=NOW, publication_id=PUBLICATION_ID)
        self.assertEqual(runner.calls, [])

    def test_tunnel_source_cannot_be_called_direct_lan(self):
        runner = TalosRunner()
        with self.assertRaises(target.ProbeFailure):
            target.stage(SHA, self.talosconfig, self.directory, runner=runner,
                         connector=lambda *_args, **_kwargs: LocalSocket("100.64.0.5"),
                         now=NOW, publication_id=PUBLICATION_ID)
        self.assertEqual(self.failure_record()["category"], "direct-lan-source-invalid")
        self.assertEqual(len(runner.calls), 1)

    def test_rejects_wrong_committed_node_address_before_talos(self):
        self.guard.stop()
        config = json.loads((ROOT / "scripts/config/platform-maintenance.json").read_text())
        config["expectedStart"]["nodes"]["acer"]["address"] = "10.1.0.216"
        with mock.patch.object(target.platform, "require_reviewed_execution_config",
                                  return_value=json.dumps(config).encode()), \
                mock.patch.object(target.platform, "validate_config"):
            with self.assertRaisesRegex(ValueError, "node addresses differ"):
                target.reviewed_context(SHA)
        self.guard.start()

    def test_reviewed_context_binds_clean_commit_helper_and_current_main(self):
        self.guard.stop()
        config = (ROOT / "scripts/config/platform-maintenance.json").read_bytes()
        calls = []

        def git(command, **_kwargs):
            calls.append(command)
            if command == ["git", "rev-parse", "HEAD"]:
                return SimpleNamespace(stdout=SHA + "\n")
            if command == ["git", "status", "--porcelain", "--untracked-files=all"]:
                return SimpleNamespace(stdout="")
            if command[:3] == ["git", "--no-replace-objects", "show"]:
                return SimpleNamespace(stdout=(ROOT / command[3].split(":", 1)[1]).read_bytes())
            if command[:2] == ["git", "ls-remote"]:
                return SimpleNamespace(stdout=f"{SHA}\trefs/heads/main\n")
            self.fail(f"unreviewed Git command: {command}")

        with mock.patch.object(target.platform, "require_reviewed_execution_config",
                                  return_value=config), \
                mock.patch.object(target.subprocess, "run", side_effect=git):
            self.assertEqual(target.reviewed_context(SHA), NODES)
        self.assertEqual(len(calls), 5)
        self.guard.start()

    def test_dirty_source_fails_before_talos(self):
        self.guard.stop()
        config = (ROOT / "scripts/config/platform-maintenance.json").read_bytes()

        def git(command, **_kwargs):
            if command == ["git", "rev-parse", "HEAD"]:
                return SimpleNamespace(stdout=SHA + "\n")
            if command == ["git", "status", "--porcelain", "--untracked-files=all"]:
                return SimpleNamespace(stdout="?? untracked-helper.py\n")
            self.fail(f"unexpected Git command after dirty source: {command}")

        with mock.patch.object(target.platform, "require_reviewed_execution_config",
                                  return_value=config), \
                mock.patch.object(target.subprocess, "run", side_effect=git):
            with self.assertRaisesRegex(ValueError, "source differs"):
                target.reviewed_context(SHA)
        self.guard.start()

    def test_rejects_invalid_source_revision_before_any_reads(self):
        self.guard.stop()
        with self.assertRaisesRegex(ValueError, "invalid reviewed source revision"):
            target.reviewed_context("not-a-sha")
        self.guard.start()


if __name__ == "__main__":
    unittest.main()
