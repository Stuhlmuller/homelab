#!/usr/bin/env python3
"""Local publication contracts; never connect to a registry or run Docker."""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("publish", ROOT / "scripts/ci/restore-image-publish.py")
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)
SHA = "a" * 40


class Contracts(unittest.TestCase):
    def test_workflow_keeps_existing_protected_gate_and_minimal_permissions(self):
        workflow = json.loads(subprocess.check_output([
            "yq", "-o=json", ".", str(ROOT / ".github/workflows/restore-image-publish.yml")
        ], text=True))
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(set(workflow["on"]["workflow_dispatch"]["inputs"]), {"expected_sha"})
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(workflow["concurrency"], {"group": "restore-image-publication", "cancel-in-progress": False})
        prepare, publish = workflow["jobs"]["prepare"], workflow["jobs"]["publish"]
        self.assertEqual(prepare["permissions"], {"contents": "read"})
        self.assertEqual(publish["permissions"], {"contents": "read", "packages": "write"})
        self.assertEqual(publish["environment"], {"name": "homelab-production"})
        self.assertEqual(publish["needs"], "prepare")
        for job in (prepare, publish):
            self.assertEqual(job["if"], "github.ref == 'refs/heads/main'")
            for step in job["steps"]:
                if "uses" in step:
                    self.assertTrue(step["uses"].startswith(("actions/checkout@", "cachix/install-nix-action@")))
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertFalse(step["with"]["persist-credentials"])

    def test_local_invocation_cannot_reach_publication(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/ci/restore-image-publish.py"),
                                 "--expected-sha", SHA, "--publish", "--expected-digest", "sha256:" + "0" * 64],
                                env={}, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no deployment is authorized", result.stderr)

    def test_exact_main_context_and_rejections(self):
        context = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                   "GITHUB_REPOSITORY": PUBLISH.REPO, "GITHUB_REF": "refs/heads/main",
                   "GITHUB_SHA": SHA, "GITHUB_WORKFLOW_REF": PUBLISH.WORKFLOW}
        PUBLISH.context_guard(SHA, context)
        for key, value in (("GITHUB_ACTIONS", "false"), ("GITHUB_EVENT_NAME", "pull_request"),
                           ("GITHUB_REPOSITORY", "other/homelab"), ("GITHUB_REF", "refs/heads/test"),
                           ("GITHUB_SHA", "b" * 40), ("GITHUB_WORKFLOW_REF", "other.yml@main")):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                PUBLISH.context_guard(SHA, {**context, key: value})
        with self.assertRaises(RuntimeError):
            PUBLISH.context_guard("main", context)

    def test_stale_or_dirty_source_fails_before_image_work(self):
        context = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                   "GITHUB_REPOSITORY": PUBLISH.REPO, "GITHUB_REF": "refs/heads/main",
                   "GITHUB_SHA": SHA, "GITHUB_WORKFLOW_REF": PUBLISH.WORKFLOW,
                   "GH_TOKEN": "test"}
        with patch.dict(os.environ, context, clear=True):
            for current, dirty, accepted in ((SHA, "", True), ("b" * 40, "", False),
                                             (SHA, "?? injected-file\n", False)):
                response = io.BytesIO(json.dumps({"object": {"sha": current}}).encode())
                commands = [SimpleNamespace(stdout=SHA + "\n"), SimpleNamespace(stdout=dirty)]
                with self.subTest(current=current, dirty=bool(dirty)), \
                        patch.object(PUBLISH, "run", side_effect=commands), \
                        patch.object(PUBLISH, "request", return_value=response) as request:
                    if accepted:
                        PUBLISH.verify_main(SHA)
                    else:
                        with self.assertRaises(RuntimeError):
                            PUBLISH.verify_main(SHA)
                    if dirty:
                        request.assert_not_called()

    def test_schema2_content_source_platform_and_tested_image_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Path(directory)

            def write_blob(value):
                body = json.dumps(value, sort_keys=True).encode()
                digest = "sha256:" + hashlib.sha256(body).hexdigest()
                (layout / digest[7:]).write_bytes(body)
                return digest

            config = {"architecture": "amd64", "os": "linux", "config": {"Labels": {
                "org.opencontainers.image.source": PUBLISH.SOURCE,
                "org.opencontainers.image.revision": SHA}}}
            config_id = write_blob(config)
            manifest = {"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                        "config": {"digest": config_id}, "layers": [{"digest": write_blob({"synthetic": "layer"})}]}
            digest = write_blob(manifest)
            (layout / "manifest.json").write_bytes((layout / digest[7:]).read_bytes())
            image = SimpleNamespace(image_id=config_id, source_sha=SHA)
            self.assertEqual(PUBLISH.verified_manifest(layout, image)[0], digest)
            for changed in (SimpleNamespace(image_id="sha256:" + "f" * 64, source_sha=SHA),
                            SimpleNamespace(image_id=config_id, source_sha="b" * 40)):
                with self.assertRaises(RuntimeError):
                    PUBLISH.verified_manifest(layout, changed)
            config["architecture"] = "arm64"
            manifest["config"]["digest"] = write_blob(config)
            digest = write_blob(manifest)
            (layout / "manifest.json").write_bytes((layout / digest[7:]).read_bytes())
            with self.assertRaises(RuntimeError):
                PUBLISH.verified_manifest(layout, SimpleNamespace(image_id=manifest["config"]["digest"], source_sha=SHA))
            # Even a supported format conversion with equivalent labels must not
            # substitute rewritten config bytes for the tested image identity.
            rewritten = {**config, "architecture": "amd64", "extra": "converted"}
            manifest["config"]["digest"] = write_blob(rewritten)
            digest = write_blob(manifest)
            (layout / "manifest.json").write_bytes((layout / digest[7:]).read_bytes())
            with self.assertRaises(RuntimeError):
                PUBLISH.verified_manifest(layout, image)
            (layout / manifest["config"]["digest"][7:]).write_bytes(b"corrupt")
            with self.assertRaises(RuntimeError):
                PUBLISH.verified_manifest(layout, SimpleNamespace(
                    image_id=manifest["config"]["digest"], source_sha=SHA))

    def test_builder_cleanup_and_config_identity_before_load(self):
        boundary = PUBLISH.load_boundary()
        image_id = "sha256:" + "a" * 64
        for failure in (None, "build", "metadata", "load"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                scratch = Path(directory)
                commands = []

                def command(*args, **kwargs):
                    commands.append(args)
                    if args[:3] == ("docker", "buildx", "build"):
                        if failure == "build":
                            raise RuntimeError("synthetic build failure")
                        (scratch / "build-metadata.json").write_text(json.dumps({
                            "containerimage.config.digest": "invalid" if failure == "metadata" else image_id,
                            "containerimage.digest": "sha256:" + "b" * 64}))
                    if args[:2] == ("docker", "load") and failure == "load":
                        raise RuntimeError("synthetic load failure")

                with patch.object(boundary, "run", side_effect=command):
                    if failure:
                        with self.assertRaises(RuntimeError):
                            boundary.build_image(scratch, scratch, "test-tag", SHA)
                    else:
                        self.assertEqual(boundary.build_image(scratch, scratch, "test-tag", SHA), image_id)
                builder = commands[0][commands[0].index("--name") + 1]
                self.assertEqual(commands[-1], ("docker", "buildx", "rm", "--force", builder))
                if failure in ("build", "metadata"):
                    self.assertFalse(any(args[:2] == ("docker", "load") for args in commands))

    def test_absence_readback_conflict_and_idempotency(self):
        candidate = ("sha256:" + "a" * 64, b"exact manifest")
        registry = Mock()
        push = Mock()
        registry.manifest.side_effect = [None, candidate, candidate]
        PUBLISH.publish_candidate(registry, "fixed-tag", candidate, push)
        push.assert_called_once_with()
        push.reset_mock()
        registry.manifest.side_effect = [candidate, candidate, candidate]
        PUBLISH.publish_candidate(registry, "fixed-tag", candidate, push)
        push.assert_not_called()
        registry.manifest.side_effect = [("sha256:" + "b" * 64, b"changed")]
        with self.assertRaises(RuntimeError):
            PUBLISH.publish_candidate(registry, "fixed-tag", candidate, push)
        push.assert_not_called()
        registry.manifest.side_effect = [None, (candidate[0], b"modified")]
        with self.assertRaises(RuntimeError):
            PUBLISH.publish_candidate(registry, "fixed-tag", candidate, push)

    def test_only_explicit_registry_absence_is_allowed(self):
        registry = object.__new__(PUBLISH.Registry)
        registry.token = "test"
        for status, code, absent in ((404, "MANIFEST_UNKNOWN", True), (404, "NAME_UNKNOWN", True),
                                     (404, "DENIED", False), (401, "UNAUTHORIZED", False),
                                     (403, "DENIED", False), (500, "UNKNOWN", False)):
            error = urllib.error.HTTPError("https://ghcr.io/fixture", status, "fixture", {},
                                           io.BytesIO(json.dumps({"errors": [{"code": code}]}).encode()))
            with self.subTest(status=status, code=code), patch.object(PUBLISH, "request", side_effect=error):
                if absent:
                    self.assertIsNone(registry.manifest("fixed"))
                else:
                    with self.assertRaises(RuntimeError):
                        registry.manifest("fixed")

    def test_registry_digest_header_must_match_bytes(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"actual manifest"
        response.headers = {"Docker-Content-Digest": "sha256:" + "0" * 64}
        registry = object.__new__(PUBLISH.Registry)
        registry.token = "test"
        with patch.object(PUBLISH, "request", return_value=response), self.assertRaises(RuntimeError):
            registry.manifest("fixed")


if __name__ == "__main__":
    unittest.main()
