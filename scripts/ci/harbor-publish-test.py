#!/usr/bin/env python3
"""Exercise production refusal paths without contacting credentials or services."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
SHA = "f76c27834ff987aa1dfad81d0c9ff273be7dd3cd"
# checkov:skip=CKV_SECRET_6: Inert test sentinel for credential leak detection.
SECRET_SENTINEL = "private-test-credential-must-never-appear"


class HarborPublicationGates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="harbor-gates-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("scripts/ci", "scripts/config", "bin", "home", "runner"):
            (self.root / directory).mkdir(parents=True)
        shutil.copyfile(ROOT / "scripts/ci/harbor-publish.sh", self.root / "scripts/ci/harbor-publish.sh")
        self.manifest = json.loads((ROOT / "scripts/config/harbor-migration.json").read_text())
        self.calls = self.root / "external-calls"
        self.env = {
            "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "HOME": str(self.root / "home"),
            "RUNNER_TEMP": str(self.root / "runner"),
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "Stuhlmuller/homelab",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": SHA,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_ACTOR": "migration-test",
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "EXPECTED_SHA": SHA,
            "GITHUB_TOKEN": SECRET_SENTINEL,
            "OCTELIUM_AUTH_TOKEN": SECRET_SENTINEL,
            "KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com",
        }
        self.executable("uname", "printf '%s\\n' Linux\n")
        self.executable("git", f"printf '%s\\n' {SHA}\n")
        for command in ("aws", "skopeo", "docker", "kubectl", "sudo", "curl"):
            self.executable(command, f"printf '%s\\n' {command} >>'{self.calls}'\nexit 97\n")

    def executable(self, name, body):
        script = self.root / "bin" / name
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)

    def run_helper(self, mode="migrate"):
        (self.root / "scripts/config/harbor-migration.json").write_text(json.dumps(self.manifest))
        result = subprocess.run(
            ["bash", str(self.root / "scripts/ci/harbor-publish.sh"), mode],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr)
        return result

    def rejected(self, mode="migrate"):
        result = self.run_helper(mode)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists(), "A refusal path reached a credential or service command")
        return result

    def transport_mocks(self, failure=None):
        """Replace service clients and runner sudo; never modify real host routing."""
        manifests = {
            image["name"]: json.dumps({"schemaVersion": 2, "test_artifact": image["name"]})
            for image in self.manifest["images"]
        }
        for image in self.manifest["images"]:
            image["digest"] = "sha256:" + hashlib.sha256(manifests[image["name"]].encode()).hexdigest()
        fixture = {
            "root": str(self.root),
            "failure": failure,
            "manifests": manifests,
            "digests": {image["name"]: image["digest"] for image in self.manifest["images"]},
        }
        mock = "#!/usr/bin/env python3\nFIXTURE = " + repr(fixture) + "\n" + textwrap.dedent('''\
            import json
            import os
            from pathlib import Path
            import signal
            import sys
            import time

            root = Path(FIXTURE["root"])
            command = Path(sys.argv[0]).name
            args = sys.argv[1:]
            with (root / "external-calls").open("a") as log:
                # The real kubeconfig helper supplies its token to kubectl.
                safe_args = ["[credential]" if arg.startswith("--token=") else arg for arg in args]
                log.write(json.dumps({"command": command, "args": safe_args}) + "\\n")
            if command == "sudo":
                args = args[1:]  # -n
                if args[0] == "tee":
                    (root / "host-route").write_text(sys.stdin.read())
                elif args[0] == "sed":
                    (root / "host-route").unlink(missing_ok=True)
                elif args[0] != "setcap":
                    raise SystemExit(96)
            elif command == "kubectl":
                if args[0] == "config":
                    (root / "home/.kube/config").write_text("private mock kubeconfig")
                    if FIXTURE["failure"] == "kubeconfig":
                        raise SystemExit(12)
                elif "port-forward" in args:
                    (root / "forward-pid").write_text(str(os.getpid()))
                    if FIXTURE["failure"] == "forward":
                        raise SystemExit(13)
                    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
                    while True:
                        time.sleep(0.1)
            elif command == "timeout":
                # Keep the real port-forward process lifecycle, without a network socket.
                os.execv(args[3], args[3:])
            elif command == "curl":
                if FIXTURE["failure"] == "forward":
                    time.sleep(0.2)
                    raise SystemExit(7)
                print("401", end="")
            elif command == "aws":
                print("private-test-credential-must-never-appear")
            elif command == "skopeo":
                if args[0] == "login":
                    assert sys.stdin.read().strip() == "private-test-credential-must-never-appear"
                    authfile = Path(args[args.index("--authfile") + 1])
                    username = args[args.index("--username") + 1]
                    if FIXTURE["failure"] == "pull-auth" and username == "robot$homelab+pull":
                        raise SystemExit(14)
                    authfile.write_text(json.dumps({"username": username}))
                    assert authfile.stat().st_mode & 0o077 == 0
                elif args[0] == "inspect":
                    if args[-1].startswith("dir:"):
                        sys.stdout.write((Path(args[-1][4:]) / "manifest.json").read_text())
                        raise SystemExit(0)
                    name = args[-1].rsplit("/", 1)[1].split("@", 1)[0].split(":", 1)[0]
                    raw = FIXTURE["manifests"][name]
                    if "--no-creds" in args:
                        authfile = Path(args[args.index("--authfile") + 1])
                        assert json.loads(authfile.read_text()) == {"auths": {}}
                        if FIXTURE["failure"] != "anonymous":
                            message = ("connection refused" if FIXTURE["failure"] == "anonymous-network"
                                       else "unauthorized: authentication required")
                            print(message, file=sys.stderr)
                            raise SystemExit(1)
                    if FIXTURE["failure"] == "digest" and name.endswith("frontend"):
                        raw += "corruption"
                    sys.stdout.write(raw)
                elif args[0] == "copy" and args[-1].startswith("dir:"):
                    authfile = Path(args[args.index("--src-authfile") + 1])
                    assert json.loads(authfile.read_text()) == {"username": "robot$homelab+pull"}
                    name = args[-2].rsplit("/", 1)[1].split("@", 1)[0]
                    raw = FIXTURE["manifests"][name]
                    if FIXTURE["failure"] == "pull-digest" and name.endswith("frontend"):
                        raw += "corrupted download"
                    if FIXTURE["failure"] == "pull" and name.endswith("frontend"):
                        raise SystemExit(15)
                    directory = Path(args[-1][4:])
                    assert list(directory.iterdir()) == []
                    (directory / "manifest.json").write_text(raw)
                    (directory / "blob").write_text("downloaded image content")
                elif args[0] != "copy":
                    raise SystemExit(95)
            elif command == "docker":
                if "login" in args:
                    assert sys.stdin.read().strip() == "private-test-credential-must-never-appear"
                elif args[:2] == ["image", "inspect"]:
                    repository = args[-1].split(":", 1)[0]
                    name = repository.rsplit("/", 1)[1]
                    print(json.dumps([repository + "@" + FIXTURE["digests"][name]]))
            else:
                raise SystemExit(94)
            ''')
        for command in ("aws", "skopeo", "docker", "kubectl", "sudo", "curl", "timeout"):
            path = self.root / "bin" / command
            path.write_text(mock)
            path.chmod(0o700)
        shutil.copyfile(ROOT / "scripts/ci/install-kubeconfig.sh", self.root / "scripts/ci/install-kubeconfig.sh")

    def assert_cleaned(self):
        self.assertFalse((self.root / "host-route").exists())
        self.assertFalse((self.root / "home/.kube/config").exists())
        self.assertEqual(list((self.root / "runner").iterdir()), [])
        pidfile = self.root / "forward-pid"
        if pidfile.exists():
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)

    def calls_for(self, command):
        return [
            call["args"] for call in map(json.loads, self.calls.read_text().splitlines())
            if call["command"] == command
        ]

    def test_feature_branch_cannot_reach_credentials(self):
        self.env["GITHUB_REF"] = "refs/heads/codex/unreviewed"
        self.rejected()

    def test_wrong_repository_cannot_reach_credentials(self):
        self.env["GITHUB_REPOSITORY"] = "untrusted/homelab"
        self.rejected()

    def test_stale_dispatch_cannot_reach_credentials(self):
        self.env["EXPECTED_SHA"] = "a" * 40
        self.rejected()

    def test_main_advanced_cannot_reach_credentials(self):
        self.executable("git", f'if [ "$1" = rev-parse ]; then echo {SHA}; else echo {"a" * 40}; fi\n')
        self.rejected()

    def test_unknown_repository_in_inventory_is_rejected(self):
        self.manifest["images"][0]["name"] = "unreviewed-image"
        self.rejected()

    def test_duplicate_package_is_rejected(self):
        self.manifest["images"][1] = self.manifest["images"][0].copy()
        self.rejected()

    def test_mutable_tag_instead_of_digest_is_rejected(self):
        self.manifest["images"][0]["digest"] = "latest"
        self.rejected()

    def test_unknown_destination_key_is_rejected(self):
        self.manifest["images"][0]["destination"] = "untrusted.example/package"
        self.rejected()

    def test_migration_requires_explicit_dispatch(self):
        self.env["GITHUB_EVENT_NAME"] = "push"
        self.rejected()

    def test_valid_inventory_reaches_missing_credential_gate(self):
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected()
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_publisher_rejects_pull_request_execution(self):
        self.env["GITHUB_EVENT_NAME"] = "pull_request"
        self.rejected(mode="publish")

    def test_migration_copies_exact_digests_and_cleans_credentials(self):
        self.transport_mocks()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo")
                  if args[0] == "copy" and args[-2].startswith("docker://ghcr.io/")]
        self.assertEqual(len(copies), 2)
        for args, artifact in zip(copies, self.manifest["images"]):
            self.assertIn("--all", args)
            self.assertIn("--preserve-digests", args)
            self.assertEqual(args[-2], f"docker://ghcr.io/stuhlmuller/{artifact['name']}@{artifact['digest']}")
            self.assertEqual(args[-1], f"docker://harbor.stinkyboi.com/homelab/{artifact['name']}:homelab-{SHA}")
        pulls = [args for args in self.calls_for("skopeo") if args[0] == "copy" and args[-1].startswith("dir:")]
        self.assertEqual(len(pulls), 2)
        for args, artifact in zip(pulls, self.manifest["images"]):
            self.assertIn("--all", args)
            self.assertIn("--preserve-digests", args)
            self.assertEqual(Path(args[args.index("--src-authfile") + 1]).name, "pull-auth.json")
            self.assertEqual(args[-2], f"docker://harbor.stinkyboi.com/homelab/{artifact['name']}@{artifact['digest']}")
        anonymous = [args for args in self.calls_for("skopeo") if "--no-creds" in args]
        self.assertEqual(len(anonymous), 2)
        parameters = [args[args.index("--name") + 1] for args in self.calls_for("aws")]
        self.assertEqual(parameters, ["/homelab/harbor/robot-push-password", "/homelab/nofx/harbor-pull-password"])
        summary = (self.root / "summary").read_text().splitlines()
        self.assertEqual(summary, [
            f"harbor.stinkyboi.com/homelab/{image['name']}@{image['digest']}"
            for image in self.manifest["images"]
        ])
        self.assert_cleaned()

    def test_publisher_uses_fixed_harbor_destinations_and_cleans(self):
        self.transport_mocks()
        self.env["GITHUB_EVENT_NAME"] = "push"
        result = self.run_helper(mode="publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        pushes = [args[-1] for args in self.calls_for("docker") if "push" in args]
        self.assertEqual(pushes, [
            f"harbor.stinkyboi.com/homelab/{image['name']}:homelab-{SHA}"
            for image in self.manifest["images"]
        ])
        self.assert_cleaned()

    def test_digest_mismatch_withholds_summary_and_cleans(self):
        self.transport_mocks(failure="digest")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_pull_robot_authentication_failure_withholds_summary_and_cleans(self):
        self.transport_mocks(failure="pull-auth")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_full_pull_failure_withholds_summary_and_cleans(self):
        self.transport_mocks(failure="pull")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_downloaded_digest_mismatch_withholds_summary_and_cleans(self):
        self.transport_mocks(failure="pull-digest")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_anonymous_access_withholds_summary_and_cleans(self):
        self.transport_mocks(failure="anonymous")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_anonymous_network_error_is_not_accepted_as_access_denial(self):
        self.transport_mocks(failure="anonymous-network")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_kubeconfig_failure_cleans_partial_credentials(self):
        self.transport_mocks(failure="kubeconfig")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls_for("aws"))
        self.assert_cleaned()

    def test_forward_failure_cleans_host_route_and_kubeconfig(self):
        self.transport_mocks(failure="forward")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls_for("aws"))
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main()
