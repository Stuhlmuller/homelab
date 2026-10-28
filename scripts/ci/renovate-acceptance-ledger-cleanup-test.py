#!/usr/bin/env python3
"""Exercise the staged cleanup Job against an isolated local ledger fixture."""

import glob
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "clusters/homelab/apps/renovate/acceptance-ledger-cleanup-job.yaml"
PLACEHOLDER = "REPLACE_WITH_REVIEWED_LEDGER_SHA256"


def job():
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e",
         'print JSON.generate(YAML.load_stream(File.read(ARGV.fetch(0))))', str(MANIFEST)],
        check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def coreutils():
    candidate = shutil.which("stat")
    if candidate and "GNU coreutils" in subprocess.run(
            [candidate, "--version"], capture_output=True, text=True).stdout:
        return str(Path(candidate).parent)
    found = sorted(glob.glob("/nix/store/*-coreutils-*/bin/stat"))
    if not found:
        raise RuntimeError("GNU coreutils is required for the cleanup fixture")
    return str(Path(found[0]).parent)


class LedgerCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = job()
        cls.manifest = cls.documents[0]
        cls.script = cls.manifest["spec"]["template"]["spec"]["containers"][0]["args"][0]
        cls.gnu = coreutils()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="renovate-ledger-cleanup-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ledger = self.base / "ledger"
        self.ledger.mkdir(mode=0o700)
        self.private = self.ledger / "private"
        self.private.mkdir(mode=0o700)
        self.input = self.private / "ledger.json"
        self.input.write_bytes(b'{"private":"fixture"}\n')
        self.input.chmod(0o600)
        self.sibling = self.ledger / "preserve-me"
        self.sibling.write_text("keep\n")
        self.digest = hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.mountinfo = self.base / "mountinfo"
        self.mountinfo.write_text("")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        stat = self.bin / "stat"
        stat.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = -c ] && [ \"$2\" = %m ]; then\n"
            f"  case \"$3\" in {shlex.quote(str(self.ledger))}|"
            f"{shlex.quote(str(self.private))}) printf '%s\\n' "
            f"{shlex.quote(str(self.ledger))}; exit 0;; esac\n"
            "fi\n"
            f"exec {shlex.quote(self.gnu + '/stat')} \"$@\"\n")
        stat.chmod(0o700)

    def run_cleanup(self, expected=None):
        script = self.script.replace("root=/ledger", f"root={shlex.quote(str(self.ledger))}")
        script = script.replace("mountinfo=/proc/self/mountinfo",
                                f"mountinfo={shlex.quote(str(self.mountinfo))}")
        script = script.replace("12021:12021:700",
                                f"{os.getuid()}:{os.getgid()}:700")
        script = script.replace("12021", str(os.getuid()))
        if expected is not None:
            script = script.replace(PLACEHOLDER, expected)
        self.assertNotIn("root=/ledger", script)
        return subprocess.run(
            ["/bin/sh", "-ec", script], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.bin}:{self.gnu}:{os.environ['PATH']}"},
            timeout=10)

    def test_staged_job_has_only_ledger_access(self):
        self.assertTrue(self.manifest["spec"]["suspend"])
        pod = self.manifest["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual([v["persistentVolumeClaim"]["claimName"] for v in pod["volumes"]],
                         ["renovate-acceptance-ledger"])
        self.assertEqual([v["mountPath"] for v in pod["containers"][0]["volumeMounts"]],
                         ["/ledger"])
        self.assertNotIn("acceptance-ledger-cleanup-job.yaml",
                         (MANIFEST.parent / "kustomization.yaml").read_text())
        policy = self.documents[1]
        self.assertEqual(policy["kind"], "NetworkPolicy")
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["spec"]["egress"], [])
        self.assertEqual(policy["spec"]["podSelector"]["matchLabels"], {
            "app.kubernetes.io/name": "renovate",
            "app.kubernetes.io/component": "acceptance-ledger-cleanup"})
        self.assertLess(int(policy["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
                        int(self.manifest["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))

    def test_placeholder_and_wrong_digest_refuse_without_erasure(self):
        for digest in (None, "a" * 64):
            with self.subTest(digest=digest):
                result = self.run_cleanup(digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.input.exists())
                self.assertTrue(self.sibling.exists())

    def test_erases_only_private_tree_and_retry_is_idempotent(self):
        outside = self.base / "outside"
        outside.write_text("keep\n")
        (self.private / "outside-link").symlink_to(outside)
        for _ in range(2):
            result = self.run_cleanup(self.digest)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(self.private.iterdir()), [])
            self.assertEqual(self.sibling.read_text(), "keep\n")
            self.assertEqual(outside.read_text(), "keep\n")
        marker = self.ledger / f".renovate-acceptance-cleanup-{self.digest}"
        self.assertEqual(marker.read_text(), self.digest + "\n")

    def test_partial_deletion_resumes_only_with_valid_marker(self):
        marker = self.ledger / f".renovate-acceptance-cleanup-{self.digest}"
        marker.write_text(self.digest + "\n")
        marker.chmod(0o600)
        self.input.unlink()
        (self.private / "remaining").write_text("private\n")
        result = self.run_cleanup(self.digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_retry_recreates_private_directory_after_interruption(self):
        marker = self.ledger / f".renovate-acceptance-cleanup-{self.digest}"
        marker.write_text(self.digest + "\n")
        marker.chmod(0o600)
        self.input.unlink()
        self.private.rmdir()
        result = self.run_cleanup(self.digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_wrong_mount_or_permissions_refuse(self):
        self.private.chmod(0o755)
        result = self.run_cleanup(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.private.chmod(0o700)
        self.mountinfo.unlink()
        result = self.run_cleanup(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.input.exists())

    def test_invalid_marker_and_private_symlink_refuse(self):
        marker = self.ledger / f".renovate-acceptance-cleanup-{self.digest}"
        marker.write_text("wrong\n")
        marker.chmod(0o600)
        result = self.run_cleanup(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.input.exists())
        marker.unlink()
        outside = self.base / "outside"
        outside.mkdir()
        self.input.unlink()
        self.private.rmdir()
        self.private.symlink_to(outside)
        result = self.run_cleanup(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(outside.exists())

    def test_nested_mount_refuses(self):
        self.mountinfo.write_text(f"1 2 3 4 {self.private}/nested 6 7\n")
        result = self.run_cleanup(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.input.exists())


if __name__ == "__main__":
    unittest.main()
