#!/usr/bin/env python3
"""Offline image integrity and anonymous-client contracts; never pull a real image."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("anonymous", Path(__file__).with_name("restore-image-anonymous-pull.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class AnonymousContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.layout = self.root / "layout"
        self.layout.mkdir()
        self.config = {"architecture": "amd64", "os": "linux", "config": {"Labels": {
            "org.opencontainers.image.source": MODULE.SOURCE,
            "org.opencontainers.image.revision": "1" * 40}}}
        self.manifest = {"schemaVersion": 2, "mediaType": next(iter(MODULE.FORMATS)), "layers": []}
        config_type, layer_types = MODULE.FORMATS[self.manifest["mediaType"]]
        self.manifest["config"] = self.store(json.dumps(self.config).encode(), config_type)
        self.manifest["layers"] = [self.store(b"first synthetic blob", next(iter(layer_types))),
                                   self.store(b"second synthetic blob", next(iter(layer_types)))]
        self.contract = {"version": 1, "image": "registry.example.invalid/reviewed/image@" + "sha256:" + "0" * 64,
                         "config_digest": self.manifest["config"]["digest"], "source_commit": "1" * 40,
                         "source_url": MODULE.SOURCE, "os": "linux", "architecture": "amd64",
                         "publication": {"run_id": 123, "run_attempt": 1}}
        self.save_manifest()

    def store(self, raw, media_type):
        value = digest(raw)
        (self.layout / value.split(":")[1]).write_bytes(raw)
        return {"digest": value, "size": len(raw), "mediaType": media_type}

    def save_manifest(self):
        raw = json.dumps(self.manifest).encode()
        (self.layout / "manifest.json").write_bytes(raw)
        self.contract["image"] = "registry.example.invalid/reviewed/image@" + digest(raw)

    def test_complete_schema2_and_oci_images_pass(self):
        for media_type, (config_type, layer_types) in MODULE.FORMATS.items():
            with self.subTest(media_type=media_type):
                self.manifest["mediaType"] = media_type
                self.manifest["config"]["mediaType"] = config_type
                for layer in self.manifest["layers"]:
                    layer["mediaType"] = next(iter(layer_types))
                self.save_manifest()
                self.assertTrue(MODULE.verify_layout(self.layout, self.contract)["anonymous_pull_verified"])

    def test_manifest_config_and_each_layer_tamper_rejected(self):
        paths = [self.layout / "manifest.json", *[self.layout / d["digest"].split(":")[1]
                 for d in [self.manifest["config"], *self.manifest["layers"]]]]
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(b"tampered")
                with self.assertRaises(ValueError):
                    MODULE.verify_layout(self.layout, self.contract)
                path.write_bytes(original)

    def test_missing_blob_and_symlink_rejected(self):
        blob = self.layout / self.manifest["layers"][-1]["digest"].split(":")[1]
        original = blob.read_bytes()
        blob.unlink()
        with self.assertRaises(ValueError):
            MODULE.verify_layout(self.layout, self.contract)
        target = self.root / "outside"
        target.write_bytes(original)
        blob.symlink_to(target)
        with self.assertRaises(ValueError):
            MODULE.verify_layout(self.layout, self.contract)

    def test_descriptor_sizes_and_foreign_urls_rejected(self):
        original = copy.deepcopy(self.manifest)
        for change in ({"size": 999}, {"size": True}, {"digest": "sha256:../../outside"},
                       {"urls": ["https://other.example.invalid/blob"]}, {"data": "inline"},
                       {"mediaType": "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip"}):
            with self.subTest(change=change):
                self.manifest = copy.deepcopy(original)
                self.manifest["layers"][0].update(change)
                self.save_manifest()
                with self.assertRaises(ValueError):
                    MODULE.verify_layout(self.layout, self.contract)

    def test_wrong_source_platform_and_reviewed_config_rejected(self):
        for field, value in (("architecture", "arm64"), ("os", "windows"),
                             ("source_commit", "2" * 40), ("source_url", "https://other.invalid/repo"),
                             ("config_digest", "sha256:" + "3" * 64)):
            with self.subTest(field=field):
                contract = {**self.contract, field: value}
                with self.assertRaises(ValueError):
                    MODULE.verify_layout(self.layout, contract)

    def test_index_and_unknown_manifest_rejected(self):
        for media in ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                      "unknown"):
            self.manifest["mediaType"] = media
            self.save_manifest()
            with self.assertRaises(ValueError):
                MODULE.verify_layout(self.layout, self.contract)

    def test_contract_rejects_tags_transport_credentials_and_unknown_fields(self):
        for change in ({"image": "registry.example.invalid/reviewed/image:latest"},
                       {"image": "docker://" + self.contract["image"]},
                       {"image": "user:password@" + self.contract["image"]},
                       {"image": self.contract["image"] + "\n"}, {"version": True},
                       {"architecture": "arm64"}, {"source_commit": "main"}, {"extra": "ignored?"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                MODULE.parse_contract(json.dumps({**self.contract, **change}))
        with self.assertRaises(ValueError):
            MODULE.parse_contract('{"version":1,"version":1}')

    def test_missing_or_invalid_pin_precedes_git_and_pull(self):
        with patch.object(MODULE.subprocess, "run") as command, patch.object(MODULE, "pull") as pull:
            with self.assertRaises(ValueError):
                MODULE.read_contract(self.root)
            pin = self.root / MODULE.PIN
            pin.parent.mkdir(parents=True)
            pin.write_text("{}")
            with self.assertRaises(ValueError):
                MODULE.read_contract(self.root)
        command.assert_not_called()
        pull.assert_not_called()

    def test_real_git_pin_requires_committed_clean_bytes(self):
        def git(*args):
            subprocess.run(["git", *args], cwd=self.root, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        git("init", "--quiet")
        pin = self.root / MODULE.PIN
        pin.parent.mkdir(parents=True)
        raw = json.dumps(self.contract)
        pin.write_text(raw)
        with self.assertRaises(subprocess.CalledProcessError):
            MODULE.read_contract(self.root)
        git("add", str(MODULE.PIN))
        git("-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "core.hooksPath=/dev/null", "commit", "--no-gpg-sign", "--quiet", "-m", "test: fixture pin")
        self.assertEqual(MODULE.read_contract(self.root), self.contract)
        pin.write_text(raw + "\n")
        with self.assertRaises(ValueError):
            MODULE.read_contract(self.root)
        git("add", str(MODULE.PIN))
        pin.write_text(raw)  # Matching HEAD with a different staged version also fails.
        with self.assertRaises(ValueError):
            MODULE.read_contract(self.root)

    def test_pull_client_is_anonymous_isolated_and_downloads_before_verifying(self):
        def copied(command, **kwargs):
            env = kwargs["env"]
            self.assertEqual(set(env), {"PATH", "HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "LANG", "TMPDIR"})
            self.assertNotEqual(env["HOME"], "/credential-home")
            auth = Path(command[command.index("--src-authfile") + 1])
            self.assertEqual(json.loads(auth.read_text()), {"auths": {}})
            registry_conf = Path(env["HOME"]) / ".config/containers/registries.conf"
            self.assertEqual(registry_conf.read_text(), 'unqualified-search-registries = []\n')
            self.assertEqual(list(registry_conf.with_name("registries.conf.d").iterdir()), [])
            self.assertEqual(list(Path(command[command.index("--src-cert-dir") + 1]).iterdir()), [])
            policy = json.loads(Path(command[command.index("--policy") + 1]).read_text())
            self.assertEqual(policy["default"], [{"type": "reject"}])
            self.assertEqual(set(policy["transports"]["docker"]), {self.contract["image"].split("@")[0]})
            for flag in ("copy", "--src-no-creds", "--src-tls-verify=true", "--preserve-digests"):
                self.assertIn(flag, command)
            self.assertEqual(command[-2], "docker://" + self.contract["image"])
            self.assertTrue(command[-1].startswith("dir:"))
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 620)
            target = Path(command[-1].removeprefix("dir:"))
            target.mkdir()
            for source in self.layout.iterdir():
                (target / source.name).write_bytes(source.read_bytes())
        dirty_env = {"HOME": "/credential-home", "GH_TOKEN": "synthetic", "REGISTRY_AUTH_FILE": "/secret",
                     "HTTPS_PROXY": "https://credentials.invalid", "SSL_CERT_FILE": "/unreviewed"}
        with patch.dict(os.environ, dirty_env), patch.object(MODULE.shutil, "which", return_value="/tool/skopeo"), \
                patch.object(MODULE.subprocess, "run", side_effect=copied):
            self.assertTrue(MODULE.pull(self.contract)["anonymous_pull_verified"])

    def publication_metadata(self):
        return {"id": 123, "run_attempt": 1, "head_sha": self.contract["source_commit"],
                "head_branch": "main", "event": "workflow_dispatch", "path": MODULE.WORKFLOW,
                "status": "completed", "conclusion": "success", "repository": {"full_name": MODULE.REPO},
                "head_repository": {"full_name": MODULE.REPO}}

    def test_publication_contract_requires_exact_positive_identifiers(self):
        for publication in ({}, {"run_id": 123}, {"run_id": True, "run_attempt": 1},
                            {"run_id": 123, "run_attempt": 0}, {"run_id": 123, "run_attempt": "1"},
                            {"run_id": 123, "run_attempt": 1, "url": "https://other.invalid"}):
            with self.subTest(publication=publication), self.assertRaises(ValueError):
                MODULE.parse_contract(json.dumps({**self.contract, "publication": publication}))

    def test_publication_metadata_requires_successful_exact_main_source_attempt(self):
        metadata = self.publication_metadata()
        MODULE.check_publication_metadata(metadata, self.contract)
        for field, value in (("id", 124), ("run_attempt", 2), ("head_sha", "2" * 40),
                             ("head_branch", "unreviewed"), ("event", "pull_request"),
                             ("path", ".github/workflows/other.yml"), ("status", "in_progress"),
                             ("conclusion", "failure"), ("repository", {"full_name": "other/repo"}),
                             ("head_repository", {"full_name": "other/repo"})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                MODULE.check_publication_metadata({**metadata, field: value}, self.contract)
        with self.assertRaises(ValueError):
            MODULE.check_publication_metadata({}, self.contract)

    def test_publication_http_is_anonymous_bounded_and_rejects_redirects(self):
        statuses = ["200", "302", "307", "401", "403", "404", "500"]
        def fetch(command, **kwargs):
            self.assertEqual(command[1], "--disable")
            self.assertNotIn("--location", command)
            self.assertNotIn("--netrc", command)
            self.assertEqual(command[command.index("--noproxy") + 1], "*")
            self.assertEqual(command[command.index("--proto") + 1], "=https")
            self.assertEqual(command[command.index("--max-filesize") + 1], "1048576")
            self.assertEqual(set(kwargs["env"]), {"PATH", "HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "LANG", "TMPDIR"})
            self.assertNotEqual(kwargs["env"]["HOME"], "/credential-home")
            self.assertEqual(command[-1], "https://api.github.com/repos/Stuhlmuller/homelab/actions/runs/123/attempts/1")
            Path(command[command.index("--output") + 1]).write_text(json.dumps(self.publication_metadata()))
            return subprocess.CompletedProcess(command, 0, status, "")
        original = dict(os.environ)
        with patch.dict(os.environ, {"HOME": "/credential-home", "GH_TOKEN": "synthetic",
                                     "HTTPS_PROXY": "https://credentials.invalid", "CURL_HOME": "/secret"}), \
                patch.object(MODULE.shutil, "which", return_value="/tool/curl"), \
                patch.object(MODULE.subprocess, "run", side_effect=fetch):
            for status in statuses:
                with self.subTest(status=status):
                    if status == "200":
                        MODULE.verify_publication(self.contract)
                    else:
                        with self.assertRaises(ValueError):
                            MODULE.verify_publication(self.contract)
        self.assertEqual(dict(os.environ), original)

    def test_default_orders_contract_metadata_and_full_pull(self):
        with patch.object(MODULE, "read_contract", return_value=self.contract), \
                patch.object(MODULE, "verify_publication", side_effect=ValueError("bad metadata")), \
                patch.object(MODULE, "pull") as pull, patch("sys.argv", ["verifier"]):
            with self.assertRaises(ValueError):
                MODULE.main()
            pull.assert_not_called()

    def test_copy_failure_never_reports_success_or_verifies_partial_layout(self):
        for failure in (subprocess.CalledProcessError(1, ["skopeo"]), subprocess.TimeoutExpired(["skopeo"], 620)):
            with patch.object(MODULE.shutil, "which", return_value="/tool/skopeo"), \
                    patch.object(MODULE.subprocess, "run", side_effect=failure), \
                    patch.object(MODULE, "verify_layout") as verify:
                with self.assertRaises(subprocess.SubprocessError):
                    MODULE.pull(self.contract)
                verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
