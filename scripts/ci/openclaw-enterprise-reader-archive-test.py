#!/usr/bin/env python3
"""Offline producer/consumer fixtures for private Enterprise reader archives."""

import copy
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


READER = module("oce_reader_archive", "scripts/ci/openclaw-enterprise-reader-archive.py")
FIXTURE = module("oce_capture_fixture", "scripts/ci/openclaw-enterprise-capture-test.py")
CAPTURE = FIXTURE.CAPTURE
SHA = FIXTURE.SHA
UIDS = FIXTURE.UIDS


class ReaderArchive(unittest.TestCase):
    def setUp(self):
        self.fixture = FIXTURE.CaptureAssembler(
            "test_assembles_complete_private_tree_without_authorizing_publication")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.roots = {
            "operator": {"journal": self.root / "source/journal",
                         "bootstrap": self.root / "source/bootstrap"},
            "tenant": {"state": self.root / "source/gateway"},
        }
        for kind in self.roots:
            for source in self.roots[kind].values():
                source.mkdir(parents=True, mode=0o700)
        for name, data in self.fixture.operator_files.items():
            self.write_source("operator", name, data)
        for name, data in self.fixture.tenant_files.items():
            self.write_source("tenant", name, data)
        (self.roots["tenant"]["state"] / "workspace/empty").mkdir(
            parents=True, mode=0o700)
        self.observations = {
            "operator": {
                "schemaVersion": 1, "sourceSha": SHA,
                "readerPod": self.fixture.operator_pod,
                "claims": {key: self.fixture.claims[key]
                           for key in ("journal", "bootstrap")},
            },
            "tenant": {
                "schemaVersion": 1, "sourceSha": SHA,
                "readerPod": self.fixture.tenant_pod,
                "claims": {"gateway": self.fixture.claims["gateway"]},
                "tenantPods": self.fixture.observations["duringTenantPods"],
            },
        }
        self.expected = {
            "operator": {"journal": UIDS["journal"], "bootstrap": UIDS["bootstrap"]},
            "tenant": {"gateway": UIDS["gateway"]},
        }

    def write_source(self, kind, name, data):
        label, relative = name.split("/", 1)
        target = self.roots[kind][label] / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        target.chmod(0o600)
        return target

    def emit(self, kind, *, observation=None, expected=None, pod_uid=None, output=None):
        output = output or io.BytesIO()
        READER.emit(kind, SHA, pod_uid or UIDS[kind + "Pod"],
                    expected or self.expected[kind],
                    observation or self.observations[kind],
                    self.roots[kind], output)
        return output.getvalue()

    def archive(self, kind):
        path = self.root / (kind + ".tar")
        path.write_bytes(self.emit(kind))
        path.chmod(0o600)
        return path

    def test_both_reader_archives_feed_capture_without_authorizing_publication(self):
        operator = self.archive("operator")
        tenant = self.archive("tenant")
        marker = CAPTURE.assemble(self.fixture.config, SHA, self.fixture.observations,
                                  operator, tenant, self.fixture.output)
        self.assertFalse(marker["continuousFenceVerified"])
        self.assertEqual(marker["operatorReaderPodUid"], UIDS["operatorPod"])
        self.assertEqual(marker["tenantReaderPodUid"], UIDS["tenantPod"])
        self.assertEqual((self.fixture.output / "agent/state/state/openclaw.sqlite").read_bytes(),
                         b"SQLite fixture")
        self.assertTrue((self.fixture.output / "agent/state/workspace/empty").is_dir())

    def test_wrong_namespace_pod_and_claim_uid_block_before_streaming(self):
        for kind in ("operator", "tenant"):
            altered = copy.deepcopy(self.observations[kind])
            altered["readerPod"]["metadata"]["namespace"] = "foreign"
            output = io.BytesIO()
            with self.assertRaises(READER.Blocked):
                self.emit(kind, observation=altered, output=output)
            self.assertEqual(output.getvalue(), b"")

            output = io.BytesIO()
            with self.assertRaises(READER.Blocked):
                self.emit(kind, pod_uid=UIDS["bootstrap"], output=output)
            self.assertEqual(output.getvalue(), b"")

            altered = copy.deepcopy(self.observations[kind])
            key = next(iter(self.expected[kind]))
            altered["claims"][key]["metadata"]["uid"] = UIDS["operatorPod"]
            output = io.BytesIO()
            with self.assertRaises(READER.Blocked):
                self.emit(kind, observation=altered, output=output)
            self.assertEqual(output.getvalue(), b"")

    def test_foreign_or_continued_tenant_pod_list_blocks(self):
        for change in ("foreign", "continued", "no-resource-version"):
            altered = copy.deepcopy(self.observations["tenant"])
            listing = altered["tenantPods"]
            if change == "foreign":
                listing["items"].append({"metadata": {"uid": UIDS["operatorPod"]}})
            elif change == "continued":
                listing["metadata"]["continue"] = "next"
            else:
                listing["metadata"].pop("resourceVersion")
            output = io.BytesIO()
            with self.assertRaises(READER.Blocked):
                self.emit("tenant", observation=altered, output=output)
            self.assertEqual(output.getvalue(), b"")

    def test_subpath_mount_blocks_before_streaming(self):
        for kind in ("operator", "tenant"):
            for field in ("subPath", "subPathExpr"):
                with self.subTest(kind=kind, field=field):
                    altered = copy.deepcopy(self.observations[kind])
                    altered["readerPod"]["spec"]["containers"][0]["volumeMounts"][0][field] = "partial"
                    output = io.BytesIO()
                    with self.assertRaises(READER.Blocked):
                        self.emit(kind, observation=altered, output=output)
                    self.assertEqual(output.getvalue(), b"")

    def test_symlink_hardlink_and_missing_required_file_block(self):
        source = self.roots["operator"]["journal"] / "journal.json"
        shortcut = source.parent / "shortcut"
        shortcut.symlink_to(source)
        with self.assertRaises(READER.Blocked):
            self.emit("operator")
        shortcut.unlink()
        os.link(source, shortcut)
        with self.assertRaises(READER.Blocked):
            self.emit("operator")
        shortcut.unlink()
        source.unlink()
        with self.assertRaises(READER.Blocked):
            self.emit("operator")

    def test_changed_source_bytes_block_even_if_size_is_unchanged(self):
        source = self.roots["tenant"]["state"] / "state/openclaw.sqlite"
        original = READER.HashingReader.read
        changed = False

        def mutate_after_read(reader, count):
            nonlocal changed
            data = original(reader, count)
            if data and not changed:
                source.write_bytes(b"SQLite altered")
                changed = True
            return data

        with patch.object(READER.HashingReader, "read", mutate_after_read):
            with self.assertRaises(READER.Blocked):
                self.emit("tenant")
        self.assertTrue(changed)

    def test_cli_error_has_fixed_stderr_and_no_secret_bytes(self):
        altered = copy.deepcopy(self.observations["operator"])
        altered["private"] = "BootstrapPassword1"
        stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(altered).encode()))
        stdout = SimpleNamespace(buffer=io.BytesIO())
        stderr = io.StringIO()
        argv = ["--kind", "operator", "--source-sha", SHA,
                "--reader-pod-uid", UIDS["operatorPod"],
                "--journal-claim-uid", UIDS["journal"],
                "--bootstrap-claim-uid", UIDS["bootstrap"]]
        with patch.object(READER.sys, "stdin", stdin), \
             patch.object(READER.sys, "stdout", stdout), \
             redirect_stderr(stderr):
            self.assertEqual(READER.main(argv), 1)
        self.assertEqual(stderr.getvalue(),
                         "Enterprise private reader archive blocked\n")
        self.assertEqual(stdout.buffer.getvalue(), b"")
        self.assertNotIn("BootstrapPassword1", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
