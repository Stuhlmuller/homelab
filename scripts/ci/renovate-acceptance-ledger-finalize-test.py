#!/usr/bin/env python3
"""Exercise the staged PVC-mounted ledger finalizer against disposable files."""

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
MANIFEST = ROOT / "clusters/homelab/apps/renovate/acceptance-ledger-finalize-job.yaml"
PLACEHOLDER = "REPLACE_WITH_REVIEWED_LEDGER_SHA256"


def documents():
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
        raise RuntimeError("GNU coreutils is required for the finalizer fixture")
    return str(Path(found[0]).parent)


class LedgerFinalize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.policy = documents()
        cls.script = cls.manifest["spec"]["template"]["spec"]["containers"][0]["args"][0]
        cls.gnu = coreutils()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="renovate-ledger-finalize-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ledger = self.base / "ledger"
        self.ledger.mkdir(mode=0o700)
        self.private = self.ledger / "private"
        self.private.mkdir(mode=0o700)
        self.digest = hashlib.sha256(b"reviewed-ledger\n").hexdigest()
        self.marker = self.ledger / f".renovate-acceptance-cleanup-{self.digest}"
        self.marker.write_text(self.digest + "\n")
        self.marker.chmod(0o600)
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

    def run_finalizer(self, expected=None):
        script = self.script.replace("root=/ledger", f"root={shlex.quote(str(self.ledger))}")
        script = script.replace("mountinfo=/proc/self/mountinfo",
                                f"mountinfo={shlex.quote(str(self.mountinfo))}")
        script = script.replace("12021:12021:700", f"{os.getuid()}:{os.getgid()}:700")
        script = script.replace("12021", str(os.getuid()))
        if expected is not None:
            script = script.replace(PLACEHOLDER, expected)
        self.assertNotIn("root=/ledger", script)
        return subprocess.run(
            ["/bin/sh", "-ec", script], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{self.bin}:{self.gnu}:{os.environ['PATH']}"},
            timeout=10)

    def test_staged_scope_and_pod_boundary(self):
        self.assertTrue(self.manifest["spec"]["suspend"])
        self.assertNotIn(MANIFEST.name, (MANIFEST.parent / "kustomization.yaml").read_text())
        pod = self.manifest["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["nodeSelector"], {"kubernetes.io/hostname": "acer"})
        self.assertEqual(pod["securityContext"]["runAsUser"], 12021)
        self.assertEqual([volume["persistentVolumeClaim"]["claimName"] for volume in pod["volumes"]],
                         ["renovate-acceptance-ledger"])
        self.assertNotIn("hostPath", json.dumps(pod))
        self.assertEqual(pod["containers"][0]["volumeMounts"][0]["mountPath"], "/ledger")
        self.assertEqual(self.policy["kind"], "NetworkPolicy")
        self.assertEqual(self.policy["spec"]["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(self.policy["spec"]["ingress"], [])
        self.assertEqual(self.policy["spec"]["egress"], [])

    def test_matching_marker_and_empty_private_finalize_then_replay(self):
        first = self.run_finalizer(self.digest)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("ledger-root-empty", first.stdout)
        self.assertEqual(list(self.ledger.iterdir()), [])
        replay = self.run_finalizer(self.digest)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertIn("already-empty-prior-receipt-required", replay.stdout)
        self.assertNotIn("ledger-root-empty", replay.stdout)

    def test_missing_wrong_or_placeholder_digest_refuses(self):
        for expected in (None, "a" * 64):
            with self.subTest(expected=expected):
                self.assertNotEqual(self.run_finalizer(expected).returncode, 0)
                self.assertTrue(self.marker.exists())
                self.assertTrue(self.private.exists())
        self.marker.write_text("wrong\n")
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.private.exists())
        self.marker.write_text(self.digest + "\n\n")
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.private.exists())
        self.marker.unlink()
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.private.exists())

    def test_unknown_entry_and_nonempty_private_refuse_before_erasure(self):
        outside = self.base / "outside"
        outside.write_text("keep\n")
        sibling = self.ledger / "preserve-me"
        sibling.symlink_to(outside)
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertEqual(outside.read_text(), "keep\n")
        self.assertTrue(self.marker.exists())
        sibling.unlink()
        (self.private / "ledger.json").write_text("private\n")
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())
        self.assertTrue((self.private / "ledger.json").exists())

    def test_hidden_root_entry_and_failed_find_refuse_before_erasure(self):
        hidden = self.ledger / ".unexpected"
        hidden.write_text("keep\n")
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())
        hidden.unlink()
        find = self.bin / "find"
        find.write_text("#!/bin/sh\nexit 7\n")
        find.chmod(0o700)
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())
        self.assertTrue(self.private.exists())

    def test_marker_and_private_symlinks_refuse_before_erasure(self):
        outside_marker = self.base / "outside-marker"
        outside_marker.write_text(self.digest + "\n")
        outside_marker.chmod(0o600)
        self.marker.unlink()
        self.marker.symlink_to(outside_marker)
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertEqual(outside_marker.read_text(), self.digest + "\n")
        self.assertTrue(self.private.exists())

        self.marker.unlink()
        self.marker.write_text(self.digest + "\n")
        self.marker.chmod(0o600)
        outside_private = self.base / "outside-private"
        outside_private.mkdir(mode=0o700)
        self.private.rmdir()
        self.private.symlink_to(outside_private, target_is_directory=True)
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())
        self.assertTrue(outside_private.is_dir())

    def test_marker_only_partial_retry_and_empty_replay(self):
        self.private.rmdir()
        result = self.run_finalizer(self.digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.ledger.iterdir()), [])
        replay = self.run_finalizer(self.digest)
        self.assertIn("already-empty-prior-receipt-required", replay.stdout)

    def test_nested_mount_and_wrong_permissions_refuse(self):
        for mounted in (self.private, self.private / "nested"):
            with self.subTest(mounted=mounted):
                self.mountinfo.write_text(f"1 2 3 4 {mounted} 6 7\n")
                self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
                self.assertTrue(self.marker.exists())
                self.assertTrue(self.private.exists())
        self.mountinfo.write_text("")
        self.private.chmod(0o755)
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())
        self.private.chmod(0o700)
        self.mountinfo.unlink()
        self.assertNotEqual(self.run_finalizer(self.digest).returncode, 0)
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
