#!/usr/bin/env python3
"""Exercise publication and mirror gates without contacting services."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA = "f76c27834ff987aa1dfad81d0c9ff273be7dd3cd"
# checkov:skip=CKV_SECRET_6: Inert test sentinel for credential leak detection.
SECRET_SENTINEL = "private-test-credential-must-never-appear"


class HarborPublicationGates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="harbor-gates-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ("scripts/ci", "scripts/config", "clusters/homelab/apps/harbor", "bin", "home", "runner"):
            (self.root / directory).mkdir(parents=True)
        shutil.copyfile(ROOT / "scripts/ci/harbor-publish.sh", self.root / "scripts/ci/harbor-publish.sh")
        shutil.copyfile(ROOT / "clusters/homelab/apps/harbor/signing-job.yaml",
                        self.root / "clusters/homelab/apps/harbor/signing-job.yaml")
        (self.root / "scripts/config/harbor-signing.json").write_text(json.dumps({
            "public_key_sha256": hashlib.sha256(b"test public key\n").hexdigest(),
        }))
        self.mirror_manifest = {"images": [{"source": "docker.io/library/busybox:1@sha256:" + "a" * 64}]}
        self.fleet_mirror_manifest = None
        self.bazarr_mirror_manifest = None
        self.mastodon_mirror_manifest = None
        self.traefik_mirror_manifest = None
        self.chainguard_mirror_manifest = None
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
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "GITHUB_OUTPUT": str(self.root / "outputs"),
            "EXPECTED_SHA": SHA,
            "OCTELIUM_AUTH_TOKEN": SECRET_SENTINEL,
            "KUBE_API_SERVER_URL": "https://kubernetes-api-ci.stinkyboi.com",
        }
        self.executable("uname", "printf '%s\\n' Linux\n")
        self.executable("git", f"printf '%s\\n' {SHA}\n")
        for command in ("aws", "skopeo", "docker", "kubectl", "sudo", "curl", "cosign"):
            self.executable(command, f"printf '%s\\n' {command} >>'{self.calls}'\nexit 97\n")

    def executable(self, name, body):
        script = self.root / "bin" / name
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)

    def run_helper(self, mode="publish"):
        (self.root / "scripts/config/harbor-images.json").write_text(json.dumps(self.mirror_manifest))
        fleet_manifest_path = self.root / "scripts/config/harbor-fleet-images.json"
        if self.fleet_mirror_manifest is None:
            fleet_manifest_path.unlink(missing_ok=True)
        else:
            fleet_manifest_path.write_text(json.dumps(self.fleet_mirror_manifest))
        bazarr_manifest_path = self.root / "scripts/config/harbor-bazarr-images.json"
        if self.bazarr_mirror_manifest is None:
            bazarr_manifest_path.unlink(missing_ok=True)
        else:
            bazarr_manifest_path.write_text(json.dumps(self.bazarr_mirror_manifest))
        mastodon_manifest_path = self.root / "scripts/config/harbor-mastodon-images.json"
        if self.mastodon_mirror_manifest is None:
            mastodon_manifest_path.unlink(missing_ok=True)
        else:
            mastodon_manifest_path.write_text(json.dumps(self.mastodon_mirror_manifest))
        traefik_manifest_path = self.root / "scripts/config/harbor-traefik-images.json"
        if self.traefik_mirror_manifest is None:
            traefik_manifest_path.unlink(missing_ok=True)
        else:
            traefik_manifest_path.write_text(json.dumps(self.traefik_mirror_manifest))
        chainguard_path = self.root / "scripts/config/harbor-chainguard-images.json"
        if self.chainguard_mirror_manifest is None:
            chainguard_path.unlink(missing_ok=True)
        else:
            chainguard_path.write_text(json.dumps(self.chainguard_mirror_manifest))
        result = subprocess.run(
            ["bash", str(self.root / "scripts/ci/harbor-publish.sh"), mode],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        public_status = self.root / "runner/harbor-mirror-status"
        self.public_status = public_status.read_text() if public_status.exists() else ""
        if public_status.exists():
            self.assertEqual(public_status.stat().st_mode & 0o777, 0o600)
            public_status.unlink()  # Workflow prints this safe file and removes it on exit.
        self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr + self.public_status)
        return result

    def rejected(self, mode="publish"):
        result = self.run_helper(mode)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists(), "A refusal path reached a credential or service command")
        return result

    def transport_mocks(self, failure=None, mirror=False, resume=False,
                        missing_error="manifest unknown", registries=("docker.io", "quay.io"),
                        source_error="toomanyrequests", core=False):
        """Replace service clients and runner sudo; never modify real host routing."""
        manifests = {}
        names = ["homelab-harbor-core"] if core else ["homelab-nofx-backend", "homelab-nofx-frontend"]
        if core:
            self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-core-images.yml@refs/heads/main"
        published_manifests = {name: json.dumps({"schemaVersion": 2, "current_build": name}) for name in names}
        self.published_digests = {
            name: "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
            for name, raw in published_manifests.items()
        }
        if mirror:
            (self.root / "published-images.json").unlink(missing_ok=True)
            self.mirror_manifest = {"images": []}
            for registry, name in zip(registries, names):
                digest = self.published_digests[name]
                source = f"{registry}/library/{name}:stable@{digest}"
                self.mirror_manifest["images"].append({"source": source})
                destination = f"harbor.stinkyboi.com/mirror/{registry}/library/{name}"
                manifests[f"{registry}/library/{name}@{digest}"] = published_manifests[name]
                manifests[f"{destination}@{digest}"] = published_manifests[name]
                manifests[f"{destination}:{digest.removeprefix('sha256:')}"] = published_manifests[name]
                manifests[f"{destination}:stable"] = published_manifests[name]
        fixture = {
            "root": str(self.root),
            "failure": failure,
            "manifests": manifests,
            "published_manifests": published_manifests,
            "published_digests": self.published_digests,
            "mirror": mirror,
            "resume": resume,
            "missing_error": missing_error,
            "source_error": source_error,
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
                elif "create" in args:
                    job = json.loads(Path(args[args.index("-f") + 1]).read_text())
                    pod = job["spec"]["template"]["spec"]
                    sign = pod["initContainers"][1]
                    assert sign["name"] == "sign"
                    for flag in ("--tlog-upload=false", "--use-signing-config=false",
                                 "--new-bundle-format=false", "--oidc-disable-ambient-providers"):
                        assert flag in sign["args"]
                    expected = ["harbor.stinkyboi.com/homelab/" + name + "@" + digest
                                for name, digest in sorted(FIXTURE["published_digests"].items())]
                    assert sign["args"][-len(expected):] == expected
                    assert not pod["automountServiceAccountToken"]
                    assert job["spec"]["backoffLimit"] == 0
                    assert job["spec"]["activeDeadlineSeconds"] == 300
                    assert job["spec"]["ttlSecondsAfterFinished"] == 600
                    (root / "signing-job.json").write_text(json.dumps(job))
                    print(json.dumps({"metadata": {"name": "harbor-sign-abcde",
                                                  "uid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}}))
                elif "wait" in args:
                    if FIXTURE["failure"] == "sign":
                        raise SystemExit(16)
                elif "get" in args:
                    assert "pods" in args, "CI must never read the signing Secret"
                    assert "batch.kubernetes.io/controller-uid=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in args
                    owner = "wrong-owner" if FIXTURE["failure"] == "signer-owner" else "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                    print(json.dumps({"items": [{"metadata": {"ownerReferences": [{"kind": "Job", "uid": owner}]},
                        "status": {"containerStatuses": [{"name": "public-key", "state": {"terminated": {
                            "exitCode": 0, "message": "test public key\\n"}}}]}}]}))
                elif "port-forward" in args:
                    # Cleanup can interrupt startup; never expose a partial PID file.
                    (root / "forward-pid.tmp").write_text(str(os.getpid()))
                    (root / "forward-pid.tmp").replace(root / "forward-pid")
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
                assert args[0] == "ssm", "No cloud signing calls allowed"
                print("private-test-credential-must-never-appear")
            elif command == "cosign":
                assert args[0] == "verify", "Signing must happen inside the cluster"
                assert args[-1].startswith("harbor.stinkyboi.com/homelab/")
                assert "@sha256:" in args[-1]
                assert os.environ["DOCKER_CONFIG"]
                assert "--new-bundle-format=false" in args
                assert "--insecure-ignore-tlog" in args
                assert Path(args[args.index("--key") + 1]).read_text().strip() == "test public key"
                if FIXTURE["failure"] == "verify":
                    raise SystemExit(16)
            elif command == "skopeo":
                if args[0] == "login":
                    assert sys.stdin.read().strip() == "private-test-credential-must-never-appear"
                    authfile = Path(args[args.index("--authfile") + 1])
                    username = args[args.index("--username") + 1]
                    assert username in {"robot$homelab+publisher", "robot$mirror+publisher", "robot$mirror+pull"}
                    authfile.write_text(json.dumps({"username": username}))
                    assert authfile.stat().st_mode & 0o077 == 0
                elif args[0] == "inspect":
                    if args[-1].startswith("dir:"):
                        sys.stdout.write((Path(args[-1][4:]) / "manifest.json").read_text())
                        raise SystemExit(0)
                    reference = args[-1].removeprefix("docker://")
                    name = reference.rsplit("/", 1)[1].split("@", 1)[0].split(":", 1)[0]
                    published_file = root / "published-images.json"
                    published = json.loads(published_file.read_text()) if published_file.exists() else {}
                    if FIXTURE["mirror"] and reference.startswith("harbor.stinkyboi.com/"):
                        assert "--no-creds" not in args
                        authfile = Path(args[args.index("--authfile") + 1])
                        assert json.loads(authfile.read_text()) == {"username": "robot$mirror+pull"}
                    if FIXTURE["mirror"] and ":" in reference and not reference.endswith(":stable"):
                        if FIXTURE["failure"] == "mirror-lookup":
                            print("connection refused private-test-credential-must-never-appear", file=sys.stderr)
                            raise SystemExit(18)
                        if not FIXTURE["resume"] and reference not in published:
                            artifact = reference.removeprefix("harbor.stinkyboi.com/")
                            print(FIXTURE["missing_error"].format(artifact=artifact, repository=artifact.rsplit(":", 1)[0]),
                                  file=sys.stderr)
                            raise SystemExit(1)
                    raw = published.get(reference) or FIXTURE["manifests"][reference]
                    if "--no-creds" in args:
                        authfile = Path(args[args.index("--authfile") + 1])
                        assert json.loads(authfile.read_text()) == {"auths": {}}
                    if FIXTURE["failure"] in ("digest", "mirror-existing-digest") and name.endswith("frontend"):
                        raw += "corruption"
                    if FIXTURE["failure"] == "mirror-tag" and reference.endswith(":stable"):
                        raw += "tag corruption"
                    sys.stdout.write(raw)
                elif args[0] == "copy" and args[-1].startswith("dir:"):
                    reference = args[-2].removeprefix("docker://")
                    upstream = FIXTURE["mirror"] and not reference.startswith("harbor.stinkyboi.com/")
                    authfile = Path(args[args.index("--src-authfile") + 1])
                    expected_auth = (
                        {"auths": {}} if FIXTURE["mirror"] and upstream
                        else {"username": "robot$mirror+pull"} if FIXTURE["mirror"]
                        else {"username": "robot$homelab+publisher"}
                    )
                    assert json.loads(authfile.read_text()) == expected_auth
                    if FIXTURE["mirror"] and upstream:
                        assert "--src-no-creds" in args
                    elif FIXTURE["mirror"]:
                        assert "--src-no-creds" not in args
                    name = reference.rsplit("/", 1)[1].split("@", 1)[0]
                    if upstream and FIXTURE["failure"] == "mirror-source":
                        print(FIXTURE["source_error"] + " private-test-credential-must-never-appear", file=sys.stderr)
                        raise SystemExit(17)
                    raw = FIXTURE["manifests"][reference] if FIXTURE["mirror"] else FIXTURE["published_manifests"][name]
                    if upstream and FIXTURE["failure"] == "upstream-digest":
                        raw += "corrupted upstream index"
                    if FIXTURE["failure"] == "pull-digest" and not upstream and name.endswith(("frontend", "core")):
                        raw += "corrupted download"
                    if FIXTURE["failure"] == "pull" and not upstream and name.endswith(("frontend", "core")):
                        raise SystemExit(15)
                    directory = Path(args[-1][4:])
                    assert list(directory.iterdir()) == []
                    (directory / "manifest.json").write_text(raw)
                    (directory / "blob").write_text("downloaded image content")
                elif args[0] == "copy" and FIXTURE["mirror"]:
                    if not args[-2].startswith("dir:"):
                        assert ":" not in args[-2].removeprefix("docker://").split("@")[0], "Skopeo rejects tag@digest"
                    source = args[-2]
                    authfile = Path(args[args.index("--src-authfile") + 1])
                    expected_auth = {"auths": {}} if source.startswith("dir:") else {"username": "robot$mirror+pull"}
                    assert json.loads(authfile.read_text()) == expected_auth
                    if source.startswith("dir:"):
                        assert "--src-no-creds" in args
                    else:
                        assert "--src-no-creds" not in args
                    authfile = Path(args[args.index("--dest-authfile") + 1])
                    assert json.loads(authfile.read_text()) == {"username": "robot$mirror+publisher"}
                    if args[-2].startswith("dir:"):
                        source_directory = Path(args[-2][4:])
                        assert (source_directory / "blob").is_file()
                        assert (source_directory / "manifest.json").read_text() == FIXTURE["manifests"][args[-1].removeprefix("docker://")]
                        if FIXTURE["failure"] == "mirror-destination":
                            print("502 Bad Gateway private-test-credential-must-never-appear", file=sys.stderr)
                            raise SystemExit(20)
                    if FIXTURE["failure"] == "mirror-alias" and args[-1].endswith(":stable"):
                        print("connection reset private-test-credential-must-never-appear", file=sys.stderr)
                        raise SystemExit(19)
                    reference = args[-1].removeprefix("docker://")
                    path = root / "published-images.json"
                    published = json.loads(path.read_text()) if path.exists() else {}
                    published[reference] = FIXTURE["manifests"][reference]
                    path.write_text(json.dumps(published))
                elif args[0] != "copy":
                    raise SystemExit(95)
            elif command == "docker":
                if "login" in args:
                    assert sys.stdin.read().strip() == "private-test-credential-must-never-appear"
                elif "push" in args:
                    reference = args[-1]
                    name = reference.rsplit("/", 1)[1].split(":", 1)[0]
                    path = root / "published-images.json"
                    published = json.loads(path.read_text()) if path.exists() else {}
                    assert reference not in published, "current build was published twice"
                    published[reference] = FIXTURE["published_manifests"][name]
                    path.write_text(json.dumps(published))
                elif args[:2] == ["image", "inspect"]:
                    repository = args[-1].split(":", 1)[0]
                    name = repository.rsplit("/", 1)[1]
                    print(json.dumps([repository + "@" + FIXTURE["published_digests"][name]]))
            else:
                raise SystemExit(94)
            ''')
        for command in ("aws", "skopeo", "docker", "kubectl", "sudo", "curl", "timeout", "cosign"):
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

    def assert_mirror_copy_credentials(self, copies):
        for args in copies:
            self.assertIn("--all", args)
            self.assertIn("--preserve-digests", args)
            source = args[-2]
            source_auth = Path(args[args.index("--src-authfile") + 1]).name
            if source.startswith("docker://harbor.stinkyboi.com/"):
                self.assertNotIn("--src-no-creds", args)
                self.assertEqual(source_auth, "mirror-pull-auth.json")
            else:
                self.assertIn("--src-no-creds", args)
                self.assertEqual(source_auth, "anonymous-auth.json")
            if args[-1].startswith("docker://"):
                destination_auth = Path(args[args.index("--dest-authfile") + 1]).name
                self.assertEqual(destination_auth, "mirror-publisher-auth.json")

    def test_cert_manager_pkcs8_key_import_and_public_key_handoff(self):
        # Exercise the real pinned CLI's file/password contract without services.
        private = self.root / "tls.key"
        prefix = self.root / "cosign"
        public = self.root / "termination-message"
        env = {**os.environ, "COSIGN_PASSWORD": SECRET_SENTINEL}
        commands = [
            ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(private)],
            ["cosign", "import-key-pair", "--key", str(private), "--output-key-prefix", str(prefix)],
            ["cosign", "public-key", "--key", str(prefix) + ".key", "--outfile", str(public)],
        ]
        for command in commands:
            result = subprocess.run(command, env=env, capture_output=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, "Local signing key conversion failed")
            self.assertNotIn(SECRET_SENTINEL.encode(), result.stdout + result.stderr)
        expected = subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout"],
                                  capture_output=True, check=True).stdout
        self.assertEqual(public.read_bytes(), expected)
        self.assertLess(public.stat().st_size, 4096)

    def test_feature_branch_cannot_reach_credentials(self):
        self.env["GITHUB_REF"] = "refs/heads/codex/unreviewed"
        self.rejected()

    def test_mirror_rejects_invalid_catalog_before_credentials(self):
        valid = self.mirror_manifest["images"][0]
        invalid = [
            {"images": []},
            {"images": [valid, valid]},
            {"images": [valid], "destination": "other"},
            {"images": [{**valid, "destination": "other"}]},
            {"images": [{"source": "docker.io/library/busybox:latest"}]},
            {"images": [{"source": "localhost/internal@sha256:" + "a" * 64}]},
            {"images": [{"source": "docker.io/library/../private@sha256:" + "a" * 64}]},
            {"images": [valid, {"source": valid["source"].replace("a" * 64, "b" * 64)}]},
        ]
        for catalog in invalid:
            with self.subTest(catalog=catalog):
                self.mirror_manifest = catalog
                self.rejected(mode="mirror")

    def test_mirror_requires_current_main_dispatch_before_credentials(self):
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror")
                self.env[key] = previous

    def test_fleet_scope_rejects_missing_or_unreviewed_catalog_before_credentials(self):
        valid = self.mirror_manifest["images"][0]
        for catalog in (
            None,
            {"images": []},
            {"images": [valid, valid]},
            {"images": [{"source": valid["source"].replace("a" * 64, "b" * 64)}]},
            {"images": [{"source": valid["source"].replace("busybox", "unreviewed")}]},
            {"images": [valid], "destination": "other"},
        ):
            with self.subTest(catalog=catalog):
                self.fleet_mirror_manifest = catalog
                self.rejected(mode="mirror-fleet")
        self.fleet_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-fleet")

    def test_fleet_scope_retains_dispatch_guards_and_rejects_arbitrary_modes(self):
        self.fleet_mirror_manifest = self.mirror_manifest
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-fleet")
                self.env[key] = previous
        self.rejected(mode="mirror-fleet:docker.io/library/busybox")

    def test_fleet_scope_excludes_unrelated_images_and_verifies_complete_pulls(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.fleet_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-fleet")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = "harbor.stinkyboi.com/mirror/" + repository
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 4)
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assertEqual(copies[1][-2:], [copies[0][-1], f"docker://{destination}:{digest[7:]}"])
        self.assertEqual(copies[2][-2:], [f"docker://{destination}@{digest}",
                                        f"docker://{destination}:stable"])
        self.assertEqual(copies[3][-2], f"docker://{destination}@{digest}")
        self.assertTrue(copies[3][-1].startswith("dir:"))
        self.assert_mirror_copy_credentials(copies)
        unrelated = self.mirror_manifest["images"][0]["source"].split("/")[-1].split(":")[0]
        self.assertNotIn(unrelated, self.calls.read_text())
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_fleet_scope_retains_digest_and_anonymous_pull_failure_gates(self):
        for failure in ("digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                self.fleet_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
                result = self.run_helper(mode="mirror-fleet")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_bazarr_scope_rejects_missing_or_unreviewed_catalog_before_credentials(self):
        valid = self.mirror_manifest["images"][0]
        for catalog in (
            None,
            {"images": []},
            {"images": [valid, valid]},
            {"images": [{"source": valid["source"].replace("a" * 64, "b" * 64)}]},
            {"images": [{"source": valid["source"].replace("busybox", "unreviewed")}]},
            {"images": [valid], "destination": "other"},
        ):
            with self.subTest(catalog=catalog):
                self.bazarr_mirror_manifest = catalog
                self.rejected(mode="mirror-bazarr")
        self.bazarr_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-bazarr")

    def test_bazarr_scope_retains_dispatch_guards_and_rejects_arbitrary_modes(self):
        self.bazarr_mirror_manifest = self.mirror_manifest
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-bazarr")
                self.env[key] = previous
        self.rejected(mode="mirror-bazarr:docker.io/library/busybox")

    def test_bazarr_scope_excludes_unrelated_images_and_verifies_complete_pulls(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.bazarr_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-bazarr")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = "harbor.stinkyboi.com/mirror/" + repository
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 4)
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assertEqual(copies[1][-2:], [copies[0][-1], f"docker://{destination}:{digest[7:]}"])
        self.assertEqual(copies[2][-2:], [f"docker://{destination}@{digest}",
                                        f"docker://{destination}:stable"])
        self.assertEqual(copies[3][-2], f"docker://{destination}@{digest}")
        self.assertTrue(copies[3][-1].startswith("dir:"))
        self.assert_mirror_copy_credentials(copies)
        unrelated = self.mirror_manifest["images"][0]["source"].split("/")[-1].split(":")[0]
        self.assertNotIn(unrelated, self.calls.read_text())
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_bazarr_scope_retains_digest_and_anonymous_pull_failure_gates(self):
        for failure in ("digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                self.bazarr_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
                result = self.run_helper(mode="mirror-bazarr")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_mastodon_scope_rejects_missing_or_unreviewed_catalog_before_credentials(self):
        valid = self.mirror_manifest["images"][0]
        for catalog in (
            None,
            {"images": []},
            {"images": [valid, valid]},
            {"images": [{"source": valid["source"].replace("a" * 64, "b" * 64)}]},
            {"images": [{"source": valid["source"].replace("busybox", "unreviewed")}]},
            {"images": [valid], "destination": "other"},
        ):
            with self.subTest(catalog=catalog):
                self.mastodon_mirror_manifest = catalog
                self.rejected(mode="mirror-mastodon")
        self.mastodon_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-mastodon")

    def test_mastodon_scope_retains_dispatch_guards_and_rejects_arbitrary_modes(self):
        self.mastodon_mirror_manifest = self.mirror_manifest
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-mastodon")
                self.env[key] = previous
        self.rejected(mode="mirror-mastodon:docker.io/library/busybox")

    def test_mastodon_scope_excludes_unrelated_images_and_verifies_complete_pulls(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.mastodon_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-mastodon")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = "harbor.stinkyboi.com/mirror/" + repository
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 4)
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assertEqual(copies[1][-2:], [copies[0][-1], f"docker://{destination}:{digest[7:]}"])
        self.assertEqual(copies[2][-2:], [f"docker://{destination}@{digest}",
                                        f"docker://{destination}:stable"])
        self.assertEqual(copies[3][-2], f"docker://{destination}@{digest}")
        self.assertTrue(copies[3][-1].startswith("dir:"))
        self.assert_mirror_copy_credentials(copies)
        unrelated = self.mirror_manifest["images"][0]["source"].split("/")[-1].split(":")[0]
        self.assertNotIn(unrelated, self.calls.read_text())
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_mastodon_scope_retains_digest_and_anonymous_pull_failure_gates(self):
        for failure in ("digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                self.mastodon_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
                result = self.run_helper(mode="mirror-mastodon")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_traefik_scope_declares_ingress_and_native_node_pull_prerequisites(self):
        selected = json.loads((ROOT / "scripts/config/harbor-traefik-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        self.assertEqual(set(selected), {"images"})
        self.assertEqual(len(selected["images"]), 2)
        self.assertTrue(selected["images"][0]["source"].startswith("docker.io/library/traefik:"))
        self.assertTrue(selected["images"][1]["source"].startswith("registry.k8s.io/pause:3.10@"))
        for image in selected["images"]:
            self.assertEqual(set(image), {"source"})
            self.assertIn(image, catalog["images"])

    def test_traefik_scope_rejects_missing_or_unreviewed_catalog_before_credentials(self):
        valid = self.mirror_manifest["images"][0]
        for catalog in (
            None,
            {"images": []},
            {"images": [valid, valid]},
            {"images": [{"source": valid["source"].replace("a" * 64, "b" * 64)}]},
            {"images": [{"source": valid["source"].replace("busybox", "unreviewed")}]},
            {"images": [valid], "destination": "other"},
        ):
            with self.subTest(catalog=catalog):
                self.traefik_mirror_manifest = catalog
                self.rejected(mode="mirror-traefik")
        self.traefik_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-traefik")

    def test_traefik_scope_retains_dispatch_guards_and_rejects_arbitrary_modes(self):
        self.traefik_mirror_manifest = self.mirror_manifest
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-traefik")
                self.env[key] = previous
        self.rejected(mode="mirror-traefik:docker.io/library/busybox")

    def test_traefik_scope_excludes_unrelated_images_and_verifies_complete_pulls(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.traefik_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-traefik")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = "harbor.stinkyboi.com/mirror/" + repository
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 4)
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assertEqual(copies[1][-2:], [copies[0][-1], f"docker://{destination}:{digest[7:]}"])
        self.assertEqual(copies[2][-2:], [f"docker://{destination}@{digest}",
                                        f"docker://{destination}:stable"])
        self.assertEqual(copies[3][-2], f"docker://{destination}@{digest}")
        self.assertTrue(copies[3][-1].startswith("dir:"))
        self.assert_mirror_copy_credentials(copies)
        unrelated = self.mirror_manifest["images"][0]["source"].split("/")[-1].split(":")[0]
        self.assertNotIn(unrelated, self.calls.read_text())
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_traefik_scope_retains_digest_and_anonymous_pull_failure_gates(self):
        for failure in ("digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                self.traefik_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
                result = self.run_helper(mode="mirror-traefik")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_chainguard_scope_rejects_unreviewed_content_before_credentials(self):
        valid = {"source": "cgr.dev/chainguard/python:latest@sha256:" + "a" * 64}
        self.mirror_manifest = {"images": [valid]}
        for catalog in (None, {"images": []}, {"images": [valid, valid]},
                        {"images": [{"source": valid["source"].replace("a" * 64, "b" * 64)}]}):
            with self.subTest(catalog=catalog):
                self.chainguard_mirror_manifest = catalog
                self.rejected(mode="mirror-chainguard")
        self.chainguard_mirror_manifest = {"images": [valid]}
        shutil.copyfile(ROOT / "scripts/ci/install-kubeconfig.sh",
                        self.root / "scripts/ci/install-kubeconfig.sh")
        result = self.run_helper(mode="mirror-chainguard")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.calls.exists(), "Reviewed cgr.dev digest did not reach credential gate")

    def test_chainguard_scope_preserves_complete_pull_and_failure_gates(self):
        for failure in (None, "digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True, registries=("docker.io", "cgr.dev"))
                selected = self.mirror_manifest["images"][1]
                self.chainguard_mirror_manifest = {"images": [selected]}
                result = self.run_helper(mode="mirror-chainguard")
                self.assertEqual(result.returncode == 0, failure is None, result.stderr)
                copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
                if failure is None:
                    self.assertEqual(len(copies), 4)
                    self.assertTrue(copies[-1][-1].startswith("dir:"))
                    self.assert_mirror_copy_credentials(copies)
                self.assert_cleaned()

    def test_mirror_copies_anonymous_sources_and_verifies_authenticated_complete_pulls(self):
        self.transport_mocks(mirror=True)
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo")
                  if args[0] == "copy" and args[-1].startswith("docker:")]
        self.assertEqual(len(copies), 4)
        for index, item in enumerate(self.mirror_manifest["images"]):
            source, digest = item["source"].split("@")
            destination = "harbor.stinkyboi.com/mirror/" + source.split(":")[0]
            for args, tag in zip(copies[index * 2:index * 2 + 2], (digest[7:], "stable")):
                self.assertIn("--all", args)
                self.assertIn("--preserve-digests", args)
                self.assertEqual(args[-1], f"docker://{destination}:{tag}")
                if tag == digest[7:]:
                    self.assertTrue(args[-2].startswith("dir:"))
                    self.assertIn("--src-no-creds", args)
                    self.assertEqual(Path(args[args.index("--src-authfile") + 1]).name, "anonymous-auth.json")
                else:
                    self.assertEqual(args[-2], f"docker://{destination}@{digest}")
                    self.assertNotIn("--src-no-creds", args)
                    self.assertEqual(Path(args[args.index("--src-authfile") + 1]).name, "mirror-pull-auth.json")
                self.assertEqual(Path(args[args.index("--dest-authfile") + 1]).name,
                                 "mirror-publisher-auth.json")
        pulls = [args for args in self.calls_for("skopeo") if args[0] == "copy" and args[-1].startswith("dir:") and args[-2].startswith("docker://harbor.stinkyboi.com/")]
        self.assertEqual(len(pulls), 2)
        self.assertEqual(len({args[-1] for args in pulls}), 2)
        for args in pulls:
            self.assertIn("--all", args)
            self.assertIn("--preserve-digests", args)
            self.assertNotIn("--src-no-creds", args)
            self.assertEqual(Path(args[args.index("--src-authfile") + 1]).name, "mirror-pull-auth.json")
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 2)
        parameters = [args[args.index("--name") + 1] for args in self.calls_for("aws")]
        self.assertEqual(parameters, [
            "/homelab/harbor/mirror-robot-push-password",
            "/homelab/harbor/mirror-robot-pull-password",
        ])
        destination_inspections = [args for args in self.calls_for("skopeo")
                                   if args[0] == "inspect" and args[-1].startswith("docker://harbor.stinkyboi.com/")]
        self.assertTrue(destination_inspections)
        for args in destination_inspections:
            self.assertNotIn("--no-creds", args)
            self.assertEqual(Path(args[args.index("--authfile") + 1]).name, "mirror-pull-auth.json")
        self.assertEqual(self.calls_for("docker"), [])
        self.assertEqual(self.calls_for("cosign"), [])
        self.assert_cleaned()

    def test_mirror_accepts_only_expected_harbor_missing_content(self):
        for message, accepted in (
            ("unknown: artifact {artifact} not found", True),
            ("unknown: repository {repository} not found", True),
            ("unknown: artifact {artifact}0 not found", False),
            ("unknown: repository unrelated/{repository} not found", False),
            ("unknown: status code 404 (Not Found)", False),
            ("unauthorized: authentication required", False),
        ):
            with self.subTest(message=message):
                self.calls.unlink(missing_ok=True)
                (self.root / "summary").unlink(missing_ok=True)
                self.transport_mocks(mirror=True, missing_error=message)
                result = self.run_helper(mode="mirror")
                copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(len(copies), 8)
                    self.assertEqual(sum(args[-1].startswith("dir:") for args in copies), 4)
                    self.assertEqual(sum(args[-1].startswith("dir:") and args[-2].startswith("docker://harbor.stinkyboi.com/") for args in copies), 2)
                    self.assertEqual(len((self.root / "summary").read_text().splitlines()), 2)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(copies, [])
                    self.assertIn("phase=digest-lookup\n", self.public_status)
                    self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_mirror_error_capture_preserves_failure_and_cleans_plaintext(self):
        helper = self.root / "scripts/ci/harbor-encrypt-diagnostic.py"
        helper.write_text("from pathlib import Path\nimport sys\n"
                          "assert Path(sys.argv[1]).read_bytes()\n"
                          "Path(sys.argv[2]).write_bytes(b'ciphertext fixture')\n")
        self.transport_mocks(failure="mirror-source", mirror=True)
        result = self.run_helper(mode="mirror")
        self.assertNotEqual(result.returncode, 0)
        artifact = self.root / "runner/harbor-publication-error.gpg"
        self.assertEqual(artifact.read_bytes(), b"ciphertext fixture")
        artifact.unlink()
        self.assert_cleaned()
        artifact.write_bytes(b"stale ciphertext")
        helper.write_text("import sys\nsys.exit(1)\n")
        result = self.run_helper(mode="mirror")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(artifact.exists())
        self.assert_cleaned()

    def test_mirror_failures_withhold_acceptance_and_clean_credentials(self):
        for failure in ("mirror-source", "mirror-alias", "mirror-lookup", "digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                result = self.run_helper(mode="mirror")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                phases = {"mirror-source": "upstream-download", "mirror-alias": "alias-copy", "mirror-lookup": "digest-lookup",
                          "digest": "digest-verify", "mirror-tag": "alias-verify", "pull": "authenticated-pull", "pull-digest": "pull-verify"}
                categories = {"mirror-source": "rate-limited", "mirror-alias": "transport-failed", "mirror-lookup": "transport-failed",
                              "digest": "digest-mismatch", "mirror-tag": "digest-mismatch", "pull-digest": "digest-mismatch"}
                status = dict(line.split("=", 1) for line in self.public_status.splitlines())
                self.assertIn(status["source"], [image["source"] for image in self.mirror_manifest["images"]])
                self.assertEqual(status["phase"], phases[failure])
                self.assertEqual(status["category"], categories.get(failure, "command-failed"))
                self.assertEqual(status["exit_status"], str(result.returncode))
                self.assertEqual(set(status), {"source", "phase", "category", "exit_status"})
                self.assert_cleaned()

    def test_mirror_http_failure_categories_are_private_and_fail_closed(self):
        for message, category in (
            ("403 Forbidden", "http-forbidden"),
            ("received unexpected HTTP status: 403", "http-forbidden"),
            ("received unexpected HTTP status: 413", "request-too-large"),
            ("received unexpected HTTP status: 500", "server-error"),
            ("502 Bad Gateway", "server-error"),
            ("project quota exceeded", "quota-exceeded"),
            ("status code: 429", "rate-limited"),
            ("unrecognized private failure", "command-failed"),
        ):
            with self.subTest(message=message):
                self.transport_mocks(failure="mirror-source", mirror=True, source_error=message)
                result = self.run_helper(mode="mirror")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                status = dict(line.split("=", 1) for line in self.public_status.splitlines())
                self.assertEqual(status["category"], category)
                self.assertEqual(status["phase"], "upstream-download")
                self.assertNotIn(message, self.public_status)
                self.assert_cleaned()

    def test_staged_source_and_destination_failures_remain_private(self):
        for failure, phase, category in (
            ("upstream-digest", "upstream-verify", "digest-mismatch"),
            ("mirror-destination", "destination-copy", "server-error"),
        ):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                result = self.run_helper(mode="mirror")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                status = dict(line.split("=", 1) for line in self.public_status.splitlines())
                self.assertEqual(status["phase"], phase)
                self.assertEqual(status["category"], category)
                self.assertEqual(set(status), {"source", "phase", "category", "exit_status"})
                copies = [a for a in self.calls_for("skopeo") if a[0] == "copy"]
                if failure == "upstream-digest":
                    self.assertFalse(any(a[-1].startswith("docker://") for a in copies))
                self.assertNotIn("private-test-credential-must-never-appear", self.public_status)
                self.assert_cleaned()

    def test_mirror_resume_avoids_upstream_but_rechecks_aliases_and_complete_pulls(self):
        self.transport_mocks(mirror=True, resume=True)
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 4)
        self.assertTrue(all(args[-2].startswith("docker://harbor.stinkyboi.com/mirror/") for args in copies))
        self.assertEqual(sum(args[-1].startswith("dir:") for args in copies), 2)
        self.assertEqual(sum(args[-1].endswith(":stable") for args in copies), 2)
        self.assert_mirror_copy_credentials(copies)
        inspections = [args[-1] for args in self.calls_for("skopeo") if args[0] == "inspect"]
        self.assertEqual(sum(reference.endswith(":stable") for reference in inspections), 2)
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 2)
        self.assertEqual(self.public_status, "")
        self.assert_cleaned()

    def test_mirror_existing_digest_mismatch_fails_without_overwriting(self):
        self.transport_mocks(failure="mirror-existing-digest", mirror=True, resume=True)
        result = self.run_helper(mode="mirror")
        self.assertNotEqual(result.returncode, 0)
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertFalse(any("frontend" in args[-2] for args in copies))
        self.assertFalse(any(not args[-2].startswith("docker://harbor.stinkyboi.com/") for args in copies))
        self.assertIn("phase=digest-verify\n", self.public_status)
        self.assertIn("category=digest-mismatch\n", self.public_status)
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_mirror_digest_only_sources_do_not_create_mutable_aliases(self):
        self.transport_mocks(mirror=True)
        for item in self.mirror_manifest["images"]:
            item["source"] = item["source"].replace(":stable@", "@")
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo")
                  if args[0] == "copy" and args[-1].startswith("docker:")]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(len(args[-1].rsplit(":", 1)[-1]) == 64 for args in copies))
        self.assert_cleaned()

    def test_wrong_repository_cannot_reach_credentials(self):
        self.env["GITHUB_REPOSITORY"] = "untrusted/homelab"
        self.rejected()

    def test_stale_dispatch_cannot_reach_credentials(self):
        self.env["EXPECTED_SHA"] = "a" * 40
        self.rejected()

    def test_main_advanced_cannot_reach_credentials(self):
        self.executable("git", f'if [ "$1" = rev-parse ]; then echo {SHA}; else echo {"a" * 40}; fi\n')
        self.rejected()

    def test_valid_inventory_reaches_missing_credential_gate(self):
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected()
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_publisher_rejects_pull_request_execution(self):
        self.env["GITHUB_EVENT_NAME"] = "pull_request"
        self.rejected(mode="publish")

    def test_publisher_requires_output_file_before_credentials(self):
        del self.env["GITHUB_OUTPUT"]
        self.rejected(mode="publish")

    def test_publisher_uses_fixed_harbor_destinations_and_cleans(self):
        self.transport_mocks()
        self.env["GITHUB_EVENT_NAME"] = "push"
        result = self.run_helper(mode="publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        parameters = [args[args.index("--name") + 1] for args in self.calls_for("aws")]
        self.assertEqual(parameters, ["/homelab/harbor/robot-push-password"])
        pushes = [args[-1] for args in self.calls_for("docker") if "push" in args]
        self.assertEqual(pushes, [
            f"harbor.stinkyboi.com/homelab/{name}:homelab-{SHA}"
            for name in sorted(self.published_digests)
        ])
        pulls = [args for args in self.calls_for("skopeo") if args[0] == "copy" and args[-1].startswith("dir:")]
        self.assertEqual(len(pulls), 2)
        self.assertTrue(all("--all" in args and "--preserve-digests" in args and "--src-authfile" in args for args in pulls))
        self.assertEqual([args[-2] for args in pulls], [
            f"docker://harbor.stinkyboi.com/homelab/{name}@{digest}"
            for name, digest in sorted(self.published_digests.items())
        ])
        self.assertEqual((self.root / "summary").read_text().splitlines(), [
            f"harbor.stinkyboi.com/homelab/{name}:homelab-{SHA}@{digest}"
            for name, digest in sorted(self.published_digests.items())
        ])
        self.assertEqual((self.root / "outputs").read_text().splitlines(), [
            f"{name.removeprefix('homelab-nofx-')}=harbor.stinkyboi.com/homelab/{name}:homelab-{SHA}@{digest}"
            for name, digest in sorted(self.published_digests.items())
        ])
        self.assert_cleaned()

    def test_publisher_digest_failure_withholds_outputs(self):
        self.transport_mocks(failure="digest")
        result = self.run_helper(mode="publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "outputs").exists())
        self.assertFalse((self.root / "summary").exists())
        self.assert_cleaned()

    def test_core_publication_has_one_fixed_subject_and_complete_pull(self):
        self.transport_mocks(core=True)
        result = self.run_helper(mode="publish-harbor-core")
        self.assertEqual(result.returncode, 0, result.stderr)
        reference = f"harbor.stinkyboi.com/homelab/homelab-harbor-core:homelab-{SHA}@{self.published_digests['homelab-harbor-core']}"
        self.assertEqual((self.root / "outputs").read_text().splitlines(), ["core=" + reference])
        self.assertEqual([a[-1] for a in self.calls_for("cosign")], [reference.split(":homelab-")[0] + "@" + reference.split("@")[1]])
        copies = [a for a in self.calls_for("skopeo") if a[0] == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertIn("--all", copies[0])
        self.assertIn("--preserve-digests", copies[0])
        job = json.loads((self.root / "signing-job.json").read_text())
        pod = job["spec"]["template"]["spec"]
        for container in pod["initContainers"] + pod["containers"]:
            self.assertEqual(container["image"], "harbor.stinkyboi.com/mirror/cgr.dev/chainguard/cosign:latest@sha256:3fad8be83b93869051c08bb98f36612afe81dabe06c288e70e41ce09a037ba18")
        self.assert_cleaned()

    def test_core_refuses_implicit_push_publication_before_credentials(self):
        self.env["GITHUB_EVENT_NAME"] = "push"
        self.rejected(mode="publish-harbor-core")

    def test_core_requires_exact_head_and_enrolled_signer_before_credentials(self):
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-core-images.yml@refs/heads/main"
        self.env["EXPECTED_SHA"] = "0" * 40
        self.rejected(mode="publish-harbor-core")
        self.env["EXPECTED_SHA"] = SHA
        (self.root / "scripts/config/harbor-signing.json").write_text('{}')
        self.rejected(mode="publish-harbor-core")

    def test_core_refuses_another_workflow_before_credentials(self):
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/nofx-images.yml@refs/heads/main"
        self.rejected(mode="publish-harbor-core")

    def test_core_pull_or_signature_failure_withholds_outputs(self):
        for failure in ("pull", "pull-digest", "sign", "verify", "signer-owner"):
            with self.subTest(failure=failure):
                self.transport_mocks(core=True, failure=failure)
                result = self.run_helper(mode="publish-harbor-core")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "outputs").exists())
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()
                (self.root / "published-images.json").unlink(missing_ok=True)

    def test_publisher_incomplete_pull_withholds_signing_and_outputs(self):
        for failure in ("pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.calls.unlink(missing_ok=True)
                self.transport_mocks(failure=failure)
                result = self.run_helper(mode="publish")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "outputs").exists())
                self.assertFalse((self.root / "summary").exists())
                self.assertFalse(self.calls_for("cosign"))
                self.assertFalse(any("create" in args for args in self.calls_for("kubectl")))
                self.assert_cleaned()

    def test_publisher_signs_and_verifies_each_digest_privately(self):
        self.transport_mocks()
        result = self.run_helper(mode="publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls_for("cosign")
        self.assertEqual([args[0] for args in calls], ["verify", "verify"])
        expected = [f"harbor.stinkyboi.com/homelab/{name}@{digest}"
                    for name, digest in sorted(self.published_digests.items())]
        job = json.loads((self.root / "signing-job.json").read_text())
        self.assertEqual(job["spec"]["template"]["spec"]["initContainers"][1]["args"][-2:], expected)
        self.assertEqual([args[-1] for args in calls if args[0] == "verify"], expected)
        self.assert_cleaned()

    def test_unenrolled_or_changed_signer_withholds_outputs(self):
        for fingerprint in (None, "0" * 64):
            with self.subTest(fingerprint=fingerprint):
                self.transport_mocks()
                (self.root / "scripts/config/harbor-signing.json").write_text(
                    json.dumps({"public_key_sha256": fingerprint}))
                result = self.run_helper(mode="publish")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assertFalse((self.root / "outputs").exists())
                if fingerprint is None:
                    self.assertFalse(self.calls.exists())
                else:
                    self.assertEqual(self.calls_for("cosign"), [])
                self.assert_cleaned()

    def test_signing_failure_withholds_success_and_cleans(self):
        for failure in ("sign", "verify", "signer-owner"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure)
                result = self.run_helper(mode="publish")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()
                (self.root / "published-images.json").unlink(missing_ok=True)

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


class PublishedDigestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(ROOT / ".github/workflows/nofx-images.yml")], text=True,
        ))
        cls.job = workflow["jobs"]["published-digests"]
        cls.script = cls.job["steps"][0]["run"]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nofx-report-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "nofx-published-images.txt"
        self.backend = f"harbor.stinkyboi.com/homelab/homelab-nofx-backend:homelab-{SHA}@sha256:{'a' * 64}"
        self.frontend = f"harbor.stinkyboi.com/homelab/homelab-nofx-frontend:homelab-{SHA}@sha256:{'b' * 64}"
        self.env = {
            "PATH": os.environ["PATH"], "GITHUB_SHA": SHA, "RUNNER_TEMP": str(self.root),
            "BACKEND_REFERENCE": self.backend, "FRONTEND_REFERENCE": self.frontend,
        }

    def run_report(self):
        result = subprocess.run(
            ["bash", "-c", self.script], env=self.env, cwd=self.root,
            capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr)
        return result

    def test_report_job_has_no_credentials_and_uploads_one_exact_file(self):
        self.assertEqual(self.job["needs"], ["publish"])
        self.assertEqual(self.job["permissions"], {})
        self.assertNotIn("environment", self.job)
        self.assertNotIn("secrets.", json.dumps(self.job))
        self.assertEqual(len(self.job["steps"]), 2)
        upload = self.job["steps"][1]
        self.assertEqual(upload["uses"], "chainguard-actions/actions-upload-artifact@ebf8f2543b7189e9a67dcac1af8cabbc5d7a3fd6")
        self.assertNotIn("if", upload)
        self.assertEqual(upload["with"], {
            "name": "nofx-published-images-${{ github.sha }}",
            "path": "${{ runner.temp }}/nofx-published-images.txt",
            "if-no-files-found": "error", "retention-days": 30, "include-hidden-files": False,
        })

    def test_report_contains_only_two_current_verified_references(self):
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), f"{self.backend}\n{self.frontend}\n")
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stdout, "")

    def test_untrusted_or_incomplete_references_create_no_report(self):
        invalid = [
            self.backend.replace(SHA, "c" * 40),
            self.backend.replace("harbor.stinkyboi.com", "untrusted.example"),
            self.backend.replace("homelab-nofx-backend", "other-package"),
            self.backend.split("@")[0],
            self.frontend,
            self.backend + "\n" + self.frontend,
            SECRET_SENTINEL,
            "",
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.env["BACKEND_REFERENCE"] = value
                self.assertNotEqual(self.run_report().returncode, 0)
                self.assertFalse(self.output.exists())
        self.env["BACKEND_REFERENCE"] = self.backend
        self.env["FRONTEND_REFERENCE"] = self.backend
        self.assertNotEqual(self.run_report().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_report_cannot_overwrite_an_existing_file(self):
        self.output.write_text("existing file")
        self.assertNotEqual(self.run_report().returncode, 0)
        self.assertEqual(self.output.read_text(), "existing file")


class NativeStagingTests(unittest.TestCase):
    def test_directory_staging_preserves_all_platforms_and_repeated_descriptors(self):
        with tempfile.TemporaryDirectory(prefix="harbor-native-staging-") as temporary:
            root = Path(temporary)
            layout = root / "source"
            blobs = layout / "blobs/sha256"
            blobs.mkdir(parents=True)
            (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')

            def blob(value, kind):
                data = json.dumps(value, separators=(",", ":")).encode()
                digest = hashlib.sha256(data).hexdigest()
                (blobs / digest).write_bytes(data)
                return {"mediaType": "application/vnd.oci.image." + kind + ".v1+json",
                        "digest": "sha256:" + digest, "size": len(data)}

            children = []
            for architecture in ("amd64", "arm64"):
                config = blob({"architecture": architecture, "os": "linux",
                               "rootfs": {"type": "layers", "diff_ids": []}}, "config")
                child = blob({"schemaVersion": 2,
                              "mediaType": "application/vnd.oci.image.manifest.v1+json",
                              "config": config, "layers": []}, "manifest")
                child["platform"] = {"architecture": architecture, "os": "linux"}
                children.append(child)
            descriptor = blob({"schemaVersion": 2,
                               "mediaType": "application/vnd.oci.image.index.v1+json",
                               "manifests": [children[0], children[0], children[1]]}, "index")
            descriptor["annotations"] = {"org.opencontainers.image.ref.name": "fixture"}
            (layout / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [descriptor]}))
            policy = root / "policy.json"
            # Trust only generated local fixtures; reject every network transport.
            policy.write_text(json.dumps({"default": [{"type": "reject"}], "transports": {
                "oci": {"": [{"type": "insecureAcceptAnything"}]},
                "dir": {"": [{"type": "insecureAcceptAnything"}]}}}))
            source = "oci:" + str(layout) + ":fixture"
            for name in ("stage", "pulled"):
                destination = root / name
                destination.mkdir()
                result = subprocess.run(["skopeo", "--policy", str(policy), "copy", "--all",
                                         "--preserve-digests", source, "dir:" + str(destination)],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = (destination / "manifest.json").read_bytes()
                self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), descriptor["digest"])
                for child in children:
                    raw = (destination / (child["digest"].split(":")[1] + ".manifest.json")).read_bytes()
                    self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(), child["digest"])
                source = "dir:" + str(destination)


class MirrorProjectQueue(unittest.TestCase):
    def test_public_mirrors_serialize_without_private_publication_queue(self):
        def workflow(name):
            return json.loads(subprocess.check_output([
                "yq", "-o=json", ".", str(ROOT / ".github/workflows" / name),
            ], text=True))
        mirror = workflow("harbor-mirror.yml")["jobs"]["mirror"]
        self.assertEqual(mirror["concurrency"], {
            "group": "harbor-mirror-production", "cancel-in-progress": False,
        })
        for name in ("nofx-images.yml", "harbor-core-images.yml"):
            jobs = workflow(name)["jobs"]
            private = [job["concurrency"]["group"] for job in jobs.values() if "concurrency" in job]
            self.assertIn("harbor-packages-production", private)
            self.assertNotIn(mirror["concurrency"]["group"], private)


class MirrorWorkflowStatusPin(unittest.TestCase):
    def test_safe_status_requires_current_reviewed_publisher(self):
        digest = hashlib.sha256((ROOT / "scripts/ci/harbor-publish.sh").read_bytes()).hexdigest()
        workflow = (ROOT / ".github/workflows/harbor-mirror.yml").read_text()
        self.assertIn(
            f"sha256sum --check --status <<<'{digest}  scripts/ci/harbor-publish.sh'",
            workflow,
        )
        for name in ("policy/workflows.rego", "policy/workflows_test.rego"):
            self.assertIn(digest, (ROOT / name).read_text())


if __name__ == "__main__":
    unittest.main()
