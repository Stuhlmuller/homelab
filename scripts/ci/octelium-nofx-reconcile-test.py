#!/usr/bin/env python3
"""Verify the fixed Service scope and failure/convergence gates."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import shutil
import os
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("nofx", pathlib.Path(__file__).resolve().parents[1] / "octelium-nofx-reconcile.py")
nofx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nofx)


class Reconciliation(unittest.TestCase):
    def exercise(self, *, execute=True, apply_error=False, no_convergence=False, anonymous=False, wrong_identity=False, absent=False, auth_failure=False, still_absent=False, authorization_mode="PASS"):
        applied = []
        reads = 0
        desired = {"kind": "Service", "metadata": {"name": "nofx"},
                   "spec": {"isAnonymous": False, "config": {"http": {"header": {"authorizationMode": "PASS"}}}}}

        def run(*command, **_kwargs):
            nonlocal reads
            if "get" in command:
                reads += 1
                if auth_failure:
                    raise subprocess.CalledProcessError(1, command, "", "rpc error: code = Unauthenticated")
                if still_absent or (absent and reads == 1):
                    raise subprocess.CalledProcessError(1, command, "gRPC error NotFound: core.v1.Service nofx.default does not exist", "")
                output = json.dumps({"metadata": {"name": "other.default" if wrong_identity else "nofx.default"},
                                     "spec": {"isAnonymous": reads == 1 or anonymous,
                                              "authorization": {"policies": ["homelab-human-web-access"]},
                                              "config": {"http": {"header": {"authorizationMode": authorization_mode}}}}})
            else:
                self.assertEqual(command[1:4], ("apply", "--include", "Service"))
                value = json.loads(pathlib.Path(command[-1]).read_text())
                self.assertEqual(value["metadata"]["name"], "nofx.default")
                self.assertIs(value["spec"]["isAnonymous"], False)
                applied.append(value)
                output = "Could not update Service" if apply_error else (
                    "Updated Service" if no_convergence or len(applied) == 1 else "No applied changes in Cluster Core resources")
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as directory, patch.object(nofx, "run", side_effect=run):
            try:
                nofx.reconcile(["octeliumctl"], {}, desired, pathlib.Path(directory), execute)
                success = True
            except (RuntimeError, subprocess.SubprocessError):
                success = False
        return success, len(applied)

    def test_read_only_never_applies(self):
        self.assertEqual(self.exercise(execute=False), (True, 0))

    def test_fixed_service_converges_and_is_verified(self):
        self.assertEqual(self.exercise(), (True, 2))

    def test_reported_errors_and_unconverged_state_fail(self):
        self.assertEqual(self.exercise(apply_error=True), (False, 1))
        self.assertFalse(self.exercise(no_convergence=True)[0])
        self.assertFalse(self.exercise(anonymous=True)[0])

    def test_missing_service_can_be_recreated_but_auth_failure_blocks_writes(self):
        self.assertEqual(self.exercise(absent=True), (True, 2))
        self.assertEqual(self.exercise(absent=True, execute=False), (True, 0))
        self.assertEqual(self.exercise(auth_failure=True), (False, 0))
        self.assertEqual(self.exercise(still_absent=True), (False, 2))

    def test_declared_catalog_requires_authorization_passthrough(self):
        service = {"kind": "Service", "metadata": {"name": "nofx"},
                   "spec": {"isAnonymous": False,
                            "authorization": {"policies": ["homelab-human-web-access"]}}}
        with patch.object(nofx, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(service), "")):
            with self.assertRaises(RuntimeError):
                nofx.declared_service()
        service["spec"]["config"] = {"http": {"header": {"authorizationMode": "PASS"}}}
        with patch.object(nofx, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(service), "")):
            self.assertEqual(nofx.declared_service(), service)

    def test_authorization_passthrough_must_persist(self):
        for mode in (None, "STRIP", ""):
            with self.subTest(mode=mode):
                self.assertFalse(self.exercise(authorization_mode=mode)[0])

    def test_shadowed_stdlib_is_never_imported_by_operator_entrypoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            scripts = pathlib.Path(temporary)
            helper = scripts / "octelium-nofx-reconcile.py"
            shutil.copyfile(nofx.ROOT / "scripts/octelium-nofx-reconcile.py", helper)
            marker = scripts / "unreviewed-code-ran"
            (scripts / "json.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
                "raise RuntimeError('unreviewed module imported')\n")
            result = subprocess.run([sys.executable, str(helper), "--execute", "--expected-sha", "a" * 40],
                                    capture_output=True, text=True, timeout=10)
            self.assertFalse(marker.exists())
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("python3 -I", result.stderr)
            result = subprocess.run([sys.executable, "-I", str(helper), "--help"],
                                    cwd=scripts, env={**os.environ, "PYTHONPATH": str(scripts)},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())

    def test_wrong_identity_prevents_apply(self):
        self.assertEqual(self.exercise(wrong_identity=True), (False, 0))

    def test_client_release_and_commit_are_required(self):
        with patch.object(nofx.shutil, "which", return_value=None):
            with self.assertRaises(RuntimeError):
                nofx.verified_client()
        good = "releaseVersion: v0.35.0\ngitCommit: 5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce\n"
        with patch.object(nofx.shutil, "which", return_value="/pinned/octeliumctl"):
            for output in [good, good.replace("v0.35.0", "v0.36.0"), good.replace("5e4eb3", "000000")]:
                with patch.object(nofx, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                    if output == good:
                        self.assertEqual(nofx.verified_client(), "/pinned/octeliumctl")
                    else:
                        with self.assertRaises(RuntimeError):
                            nofx.verified_client()

    def test_unsafe_native_overrides_fail_before_opening_transport(self):
        for overrides in ({"OCTELIUM_INSECURE_TLS": "true"},
                          {"OCTELIUM_AUTH_PROXY_SOCKET": "/private/proxy.sock"}):
            with self.subTest(overrides=overrides), \
                    patch.dict(nofx.os.environ, overrides, clear=True), \
                    patch.object(nofx.importlib.util, "spec_from_file_location",
                                 side_effect=AssertionError("Transport opened before override rejection")):
                with self.assertRaisesRegex(RuntimeError, "TLS or authentication"):
                    with nofx.native_transport(pathlib.Path("/unused")):
                        self.fail("Unsafe transport override accepted")

    def test_reviewed_commit_is_required(self):
        with self.assertRaises(RuntimeError):
            nofx.verify_reviewed_main(None)
        def mismatched_commit(*command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, "" if "status" in command else "b" * 40, "")

        with patch.object(nofx, "run", side_effect=mismatched_commit):
            with self.assertRaises(RuntimeError):
                nofx.verify_reviewed_main("a" * 40)

    def test_dirty_checkout_fails_before_catalog_or_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary) / "checkout"
            nofx.run("git", "clone", "--quiet", "--shared", str(nofx.ROOT), str(checkout))
            expected = nofx.run("git", "-C", str(checkout), "rev-parse", "HEAD").stdout.strip()
            real_run = nofx.run

            def run(*command, **kwargs):
                if command[:2] == ("git", "ls-remote"):
                    return subprocess.CompletedProcess(command, 0, f"{expected}\trefs/heads/main\n", "")
                return real_run(*command, **kwargs)

            with patch.object(nofx, "ROOT", checkout), patch.object(nofx, "run", side_effect=run):
                nofx.verify_reviewed_main(expected)
                for relative, staged in [("flake.nix", False), ("flake.lock", True),
                                         ("scripts/unreviewed.py", False)]:
                    with self.subTest(path=relative, staged=staged):
                        target = checkout / relative
                        original = target.read_bytes() if target.exists() else None
                        target.write_bytes((original or b"") + b"\n# unreviewed fixture change\n")
                        if staged:
                            real_run("git", "-C", str(checkout), "add", "--", relative)
                        with patch("sys.argv", ["reconcile", "--execute", "--expected-sha", expected]), \
                                patch.object(nofx, "declared_service") as catalog, \
                                patch.object(nofx, "native_transport") as transport:
                            with self.assertRaisesRegex(RuntimeError, "clean checkout"):
                                nofx.main()
                            catalog.assert_not_called()
                            transport.assert_not_called()
                        if original is None:
                            target.unlink()
                        else:
                            real_run("git", "-C", str(checkout), "restore", "--staged", "--worktree", "--", relative)
                nofx.verify_reviewed_main(expected)


class Installer(unittest.TestCase):
    def exercise(self, *, platform="Linux", checksum_tool="sha256sum", checksum_valid=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for command in ("mktemp", "install", "rm"):
                (commands / command).symlink_to(shutil.which(command))

            def executable(name, source):
                path = commands / name
                path.write_text(f"#!{sys.executable}\n" + source)
                path.chmod(0o755)

            executable("uname", f"import sys\nprint({platform!r} if sys.argv[1] == '-s' else {'aarch64' if platform == 'Linux' else 'arm64'!r})\n")
            executable("curl", "import pathlib,sys\npathlib.Path(sys.argv[sys.argv.index('--output')+1]).write_bytes(b'fixture')\n")
            executable("tar", "import pathlib,sys\np=pathlib.Path(sys.argv[sys.argv.index('-C')+1])/'octeliumctl'\n"
                       "p.write_text('#!/bin/sh\\necho pinned-fixture\\n')\np.chmod(0o755)\n")
            if checksum_tool:
                flags = ["--check", "-"] if checksum_tool == "sha256sum" else ["-a", "256", "--check", "-"]
                executable(checksum_tool, "import sys\n" +
                           f"assert sys.argv[1:] == {flags!r}\n" +
                           "assert len(sys.stdin.read().split()[0]) == 64\n" +
                           f"sys.exit({0 if checksum_valid else 1})\n")
            destination = root / "installed"
            result = subprocess.run(["/bin/bash", str(nofx.ROOT / "scripts/install-octeliumctl.sh"), str(destination)],
                                    env={**os.environ, "PATH": str(commands)},
                                    capture_output=True, text=True, timeout=15)
            return result, (destination / "octeliumctl").exists()

    def test_linux_coreutils_and_darwin_fallback(self):
        for platform, tool in (("Linux", "sha256sum"), ("Darwin", "shasum")):
            with self.subTest(platform=platform, tool=tool):
                result, installed = self.exercise(platform=platform, checksum_tool=tool)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(installed)

    def test_missing_or_failed_checksum_never_installs(self):
        for options in ({"checksum_tool": None}, {"checksum_valid": False}):
            with self.subTest(options=options):
                result, installed = self.exercise(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(installed)


if __name__ == "__main__":
    unittest.main()
