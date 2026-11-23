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
        shutil.copyfile(ROOT / "scripts/ci/cordium-publication-source.sh",
                        self.root / "scripts/ci/cordium-publication-source.sh")
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
        self.harbor_mirror_manifest = None
        self.renovate_mirror_manifest = None
        self.n8n_mirror_manifest = None
        self.chainguard_mirror_manifest = None
        self.dns_mirror_manifest = None
        self.litellm_mirror_manifest = None
        self.prometheus_mirror_manifest = None
        self.home_assistant_mirror_manifest = None
        self.uptime_kuma_mirror_manifest = None
        self.adguard_mirror_manifest = None
        self.cilium_mirror_manifest = None
        self.kagent_mirror_manifest = None
        self.homepage_mirror_manifest = None
        self.canary_mirror_manifest = None
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
        for command in ("aws", "skopeo", "regctl", "docker", "kubectl", "sudo", "curl", "cosign"):
            self.executable(command, f"printf '%s\\n' {command} >>'{self.calls}'\nexit 97\n")

    def executable(self, name, body):
        script = self.root / "bin" / name
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)

    def run_helper(self, mode="publish", *, tailnet=False):
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
        harbor_path = self.root / "scripts/config/harbor-runtime-images.json"
        if self.harbor_mirror_manifest is None:
            harbor_path.unlink(missing_ok=True)
        else:
            harbor_path.write_text(json.dumps(self.harbor_mirror_manifest))
        renovate_path = self.root / "scripts/config/harbor-renovate-images.json"
        if self.renovate_mirror_manifest is None:
            renovate_path.unlink(missing_ok=True)
        else:
            renovate_path.write_text(json.dumps(self.renovate_mirror_manifest))
        n8n_path = self.root / "scripts/config/harbor-n8n-images.json"
        if self.n8n_mirror_manifest is not None:
            n8n_path.write_text(json.dumps(self.n8n_mirror_manifest))
        dns_path = self.root / "scripts/config/harbor-dns-images.json"
        if self.dns_mirror_manifest is None:
            dns_path.unlink(missing_ok=True)
        else:
            dns_path.write_text(json.dumps(self.dns_mirror_manifest))
        litellm_path = self.root / "scripts/config/harbor-litellm-images.json"
        if self.litellm_mirror_manifest is None:
            litellm_path.unlink(missing_ok=True)
        else:
            litellm_path.write_text(json.dumps(self.litellm_mirror_manifest))
        prometheus_path = self.root / "scripts/config/harbor-prometheus-images.json"
        if self.prometheus_mirror_manifest is None:
            prometheus_path.unlink(missing_ok=True)
        else:
            prometheus_path.write_text(json.dumps(self.prometheus_mirror_manifest))
        home_assistant_path = self.root / "scripts/config/harbor-home-assistant-images.json"
        if self.home_assistant_mirror_manifest is None:
            home_assistant_path.unlink(missing_ok=True)
        else:
            home_assistant_path.write_text(json.dumps(self.home_assistant_mirror_manifest))
        uptime_kuma_path = self.root / "scripts/config/harbor-uptime-kuma-images.json"
        if self.uptime_kuma_mirror_manifest is None:
            uptime_kuma_path.unlink(missing_ok=True)
        else:
            uptime_kuma_path.write_text(json.dumps(self.uptime_kuma_mirror_manifest))
        adguard_path = self.root / "scripts/config/harbor-adguard-images.json"
        if self.adguard_mirror_manifest is None:
            adguard_path.unlink(missing_ok=True)
        else:
            adguard_path.write_text(json.dumps(self.adguard_mirror_manifest))
        cilium_path = self.root / "scripts/config/harbor-cilium-images.json"
        if self.cilium_mirror_manifest is None:
            cilium_path.unlink(missing_ok=True)
        else:
            cilium_path.write_text(json.dumps(self.cilium_mirror_manifest))
        kagent_path = self.root / "scripts/config/harbor-kagent-images.json"
        if self.kagent_mirror_manifest is None:
            kagent_path.unlink(missing_ok=True)
        else:
            kagent_path.write_text(json.dumps(self.kagent_mirror_manifest))
        homepage_path = self.root / "scripts/config/harbor-homepage-images.json"
        if self.homepage_mirror_manifest is None:
            homepage_path.unlink(missing_ok=True)
        else:
            homepage_path.write_text(json.dumps(self.homepage_mirror_manifest))
        canary_path = self.root / "scripts/config/harbor-image-updater-canary.json"
        if self.canary_mirror_manifest is None:
            canary_path.unlink(missing_ok=True)
        else:
            canary_path.write_text(json.dumps(self.canary_mirror_manifest))
        result = subprocess.run(
            ["bash", str(self.root / "scripts/ci/harbor-publish.sh"), mode] + (["--tailscale"] if tailnet else []),
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

    def rejected(self, mode="publish", *, tailnet=False):
        result = self.run_helper(mode, tailnet=tailnet)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists(), "A refusal path reached a credential or service command")
        return result

    def transport_mocks(self, failure=None, mirror=False, resume=False, oci_index=False,
                        missing_error="manifest unknown", registries=("docker.io", "quay.io"),
                        source_error="toomanyrequests", destination_error="502 Bad Gateway",
                        core=False, cordium=False, enterprise=False,
                        forward_start_delay=0, canary=False, home_assistant=False):
        """Replace service clients and runner sudo; never modify real host routing."""
        manifests = {}
        names = ["homelab-harbor-core"] if core else ["homelab-nofx-backend", "homelab-nofx-frontend"]
        if canary:
            names = ["busybox"]
        if cordium:
            names = ["homelab-cordium-runner", "homelab-cordium-controller"]
            self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/cordium-runner-publish.yml@refs/heads/main"
            self.executable("git", f'if [ "$1" = ls-remote ]; then printf "%s\\trefs/heads/main\\n" {SHA}; '
                            f'else printf "%s\\n" {SHA}; fi\n')
        if enterprise:
            names = ["homelab-oce-controller", "homelab-oce-runtime", "homelab-oce-cli",
                     "homelab-oce-operator"]
            self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/openclaw-enterprise-images.yml@refs/heads/main"
        if core:
            self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-core-images.yml@refs/heads/main"
        published_manifests = {name: json.dumps({"schemaVersion": 2, "current_build": name,
            **({"canary_variant": canary} if canary else {}),
            **({"mediaType": "application/vnd.oci.image.index.v1+json"} if oci_index else {})}) for name in names}
        self.published_digests = {
            name: "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
            for name, raw in published_manifests.items()
        }
        if mirror:
            (self.root / "published-images.json").unlink(missing_ok=True)
            self.mirror_manifest = {"images": []}
            for registry, name in zip(registries, names):
                digest = self.published_digests[name]
                repository = "ghcr.io/home-assistant/home-assistant" if home_assistant else f"{registry}/library/{name}"
                source = f"{repository}:stable@{digest}"
                self.mirror_manifest["images"].append({"source": source})
                destination = f"harbor.stinkyboi.com/mirror/{repository}"
                manifests[f"{repository}@{digest}"] = published_manifests[name]
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
            "destination_error": destination_error,
            "forward_start_delay": forward_start_delay,
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
            def fail_read(kind, messages, partial=None):
                failure = FIXTURE["failure"]
                if failure not in messages:
                    return
                marker = root / (kind + "-failed")
                if failure.endswith("-once") and marker.exists():
                    return
                if failure.endswith("-four"):
                    failures = int(marker.read_text()) if marker.exists() else 0
                    if failures == 4:
                        return
                    marker.write_text(str(failures + 1))
                else:
                    marker.touch()
                if partial is not None:
                    (partial / "partial").write_text("incomplete")
                print(messages[failure] + " private-test-credential-must-never-appear", file=sys.stderr)
                raise SystemExit(22)
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
                    if FIXTURE["failure"] == "enterprise-cleanup":
                        raise SystemExit(23)
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
                                for name, digest in FIXTURE["published_digests"].items()]
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
                    with (root / "forward-pids").open("a") as recorded:
                        recorded.write(str(os.getpid()) + "\\n")
                    if FIXTURE["failure"] == "forward":
                        print("x" * 70000 + "private port-forward fixture", file=sys.stderr)
                        raise SystemExit(13)
                    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
                    while True:
                        time.sleep(0.1)
            elif command == "timeout":
                # Keep the real port-forward process lifecycle, without a network socket.
                time.sleep(FIXTURE["forward_start_delay"])
                os.execv(args[3], args[3:])
            elif command == "curl":
                if FIXTURE["failure"] == "forward":
                    print("private readiness fixture", file=sys.stderr)
                    time.sleep(0.2)
                    raise SystemExit(7)
                # Real TLS readiness cannot succeed until the background forward
                # listens. Wait for this fixture's current live process too.
                for _ in range(500):
                    try:
                        os.kill(int((root / "forward-pid").read_text()), 0)
                        break
                    except (FileNotFoundError, ProcessLookupError, ValueError):
                        time.sleep(0.01)
                else:
                    raise SystemExit(7)
                if FIXTURE["failure"] in ("mirror-regctl-restart-readiness-once",
                                          "mirror-regctl-restart-readiness-always") and \
                        (root / "regctl-pull-failed").exists():
                    for _ in range(50):
                        if len((root / "forward-pids").read_text().splitlines()) >= 2:
                            break
                        time.sleep(0.01)
                    launches = len((root / "forward-pids").read_text().splitlines())
                    if launches == 2 or (FIXTURE["failure"] == "mirror-regctl-restart-readiness-always" and launches > 2):
                        print("private restarted-forward readiness fixture", file=sys.stderr)
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
                    if args[-1].startswith("oci:"):
                        directory = Path(args[-1].removeprefix("oci:").removesuffix(":mirror"))
                        sys.stdout.write((directory / "manifest.json").read_text())
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
                    if FIXTURE["mirror"] and reference.endswith(":stable"):
                        if FIXTURE["failure"] == "mirror-alias-lookup":
                            print("connection refused private-test-credential-must-never-appear", file=sys.stderr)
                            raise SystemExit(18)
                        fail_read("alias-lookup", {
                            "mirror-alias-lookup-once": "connection reset",
                            "mirror-alias-lookup-auth": "unauthorized; connection reset",
                        })
                        if not FIXTURE["resume"] and reference not in published:
                            print("manifest unknown", file=sys.stderr)
                            raise SystemExit(1)
                        if reference in published:
                            fail_read("alias", {
                                "mirror-alias-verify-once": "connection reset",
                                "mirror-alias-verify-auth": "unauthorized; connection reset",
                                "mirror-alias-verify-missing": "manifest unknown; connection reset",
                                "mirror-alias-verify-digest": "digest mismatch; connection reset",
                            })
                    if reference.endswith(":issue-1846-canary") and reference not in published:
                        print("manifest unknown", file=sys.stderr)
                        raise SystemExit(1)
                    raw = published.get(reference) or FIXTURE["manifests"][reference]
                    if "--no-creds" in args:
                        authfile = Path(args[args.index("--authfile") + 1])
                        assert json.loads(authfile.read_text()) == {"auths": {}}
                    if FIXTURE["failure"] in ("digest", "mirror-existing-digest") and name.endswith(("frontend", "controller")):
                        raw += "corruption"
                    if FIXTURE["failure"] == "mirror-tag" and reference.endswith(":stable"):
                        raw += "tag corruption"
                    if FIXTURE["failure"] in ("mirror-existing-alias", "mirror-oci-alias") and reference.endswith(":stable") and reference not in published:
                        raw += "stale alias"
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
                    if upstream and FIXTURE["failure"] in ("mirror-oci-index", "mirror-regctl-pull", "mirror-regctl-digest", "mirror-regctl-pull-once", "mirror-regctl-pull-server-once", "mirror-regctl-pull-server-always", "mirror-regctl-restart-readiness-once", "mirror-regctl-restart-readiness-always", "mirror-regctl-pull-four", "mirror-regctl-pull-always", "mirror-regctl-pull-auth", "mirror-regctl-forward-dies"):
                        print('Manifest list must be converted to type OCI index; Instructed to preserve digests',
                              file=sys.stderr)
                        raise SystemExit(17)
                    if upstream and FIXTURE["failure"] == "mirror-source":
                        print(FIXTURE["source_error"] + " private-test-credential-must-never-appear", file=sys.stderr)
                        raise SystemExit(17)
                    raw = FIXTURE["manifests"][reference] if FIXTURE["mirror"] else FIXTURE["published_manifests"][name]
                    if upstream and FIXTURE["failure"] == "upstream-digest":
                        raw += "corrupted upstream index"
                    if FIXTURE["failure"] == "pull-digest" and not upstream and name.endswith(("frontend", "core", "controller")):
                        raw += "corrupted download"
                    if FIXTURE["failure"] == "pull" and not upstream and name.endswith(("frontend", "core", "controller")):
                        raise SystemExit(15)
                    directory = Path(args[-1][4:])
                    assert list(directory.iterdir()) == []
                    if FIXTURE["mirror"] and not upstream:
                        fail_read("skopeo-pull", {
                            "mirror-pull-once": "unexpected EOF",
                            "mirror-pull-http2-once": "stream error: stream ID 19; INTERNAL_ERROR; received from peer",
                            "mirror-pull-server-once": "received unexpected HTTP status: 500",
                            "mirror-pull-server-always": "received unexpected HTTP status: 500",
                            "mirror-pull-always": "unexpected EOF",
                            "mirror-pull-auth": "unauthorized; unexpected EOF",
                            "mirror-pull-forbidden": "403 Forbidden; unexpected EOF",
                            "mirror-pull-missing": "manifest unknown; unexpected EOF",
                            "mirror-pull-http-missing": "HTTP status code: 404; unexpected EOF",
                            "mirror-pull-digest": "digest mismatch; unexpected EOF",
                            "mirror-pull-preserve": "Instructed to preserve digests; unexpected EOF",
                        }, directory)
                    (directory / "manifest.json").write_text(raw)
                    (directory / "blob").write_text("downloaded image content")
                elif args[0] == "copy" and FIXTURE["mirror"]:
                    if not args[-2].startswith("dir:"):
                        assert ":" not in args[-2].removeprefix("docker://").split("@")[0], "Skopeo rejects tag@digest"
                    source = args[-2]
                    authfile = Path(args[args.index("--src-authfile") + 1])
                    upstream = not source.startswith(("dir:", "docker://harbor.stinkyboi.com/"))
                    expected_auth = {"auths": {}} if source.startswith("dir:") or upstream else {"username": "robot$mirror+pull"}
                    assert json.loads(authfile.read_text()) == expected_auth
                    if source.startswith("dir:") or upstream:
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
                            print(FIXTURE["destination_error"] + " private-test-credential-must-never-appear", file=sys.stderr)
                            raise SystemExit(20)
                        if FIXTURE["failure"] == "mirror-oci-destination":
                            print('Manifest list must be converted to type OCI index; Instructed to preserve digests',
                                  file=sys.stderr)
                            raise SystemExit(17)
                        if FIXTURE["failure"] == "mirror-index-child-notfound":
                            target = args[-1].removeprefix("docker://")
                            repository, tag = target.rsplit(":", 1)
                            print(f'not found [http 404]: artifact {repository.removeprefix("harbor.stinkyboi.com/")}@sha256:{tag} not found',
                                  file=sys.stderr)
                            raise SystemExit(17)
                    if FIXTURE["failure"] == "mirror-alias" and args[-1].endswith(":stable"):
                        print("connection reset private-test-credential-must-never-appear", file=sys.stderr)
                        raise SystemExit(19)
                    if FIXTURE["failure"] == "mirror-oci-alias" and args[-1].endswith(":stable"):
                        print('Manifest list must be converted to type OCI index; Instructed to preserve digests',
                              file=sys.stderr)
                        raise SystemExit(17)
                    reference = args[-1].removeprefix("docker://")
                    path = root / "published-images.json"
                    published = json.loads(path.read_text()) if path.exists() else {}
                    published[reference] = FIXTURE["manifests"][reference]
                    path.write_text(json.dumps(published))
                elif args[0] != "copy":
                    raise SystemExit(95)
            elif command == "regctl":
                config = Path(os.environ["REGCTL_CONFIG"])
                docker_config = Path(os.environ["DOCKER_CONFIG"]) / "config.json"
                assert json.loads(docker_config.read_text()) == {"auths": {}}
                if args[:2] == ["registry", "login"]:
                    assert sys.stdin.read().strip() == "private-test-credential-must-never-appear"
                    assert "--pass-stdin" in args and "--skip-check" in args
                    user = args[args.index("--user") + 1]
                    assert user in {"robot$mirror+publisher", "robot$mirror+pull"}
                    config.write_text(json.dumps({"username": user}))
                    assert config.stat().st_mode & 0o077 == 0
                elif args[:2] == ["registry", "set"]:
                    assert config.name == "regctl-chunked-publisher.json"
                    assert json.loads(config.read_text()) == {"username": "robot$mirror+publisher"}
                    assert args[2:] == ["harbor.stinkyboi.com", "--blob-chunk", "8388608", "--blob-max", "8388608"]
                    config.write_text(json.dumps({"username": "robot$mirror+publisher", "blob_chunk": 8388608}))
                elif args[:2] == ["image", "copy"]:
                    source, target = args[-2:]
                    config_data = json.loads(config.read_text())
                    if source.startswith("ghcr.io/home-assistant/home-assistant@"):
                        assert config_data == {}
                        assert args[2:-2] == ["--force-recursive"] and target.startswith("ocidir://")
                        directory = Path(target.removeprefix("ocidir://").removesuffix(":mirror"))
                        raw = FIXTURE["manifests"][source]
                        if FIXTURE["failure"] == "upstream-digest":
                            raw += "corrupted upstream index"
                        (directory / "manifest.json").write_text(raw)
                        raise SystemExit(0)
                    if source.startswith("ocidir://"):
                        assert config_data == {"username": "robot$mirror+publisher", "blob_chunk": 8388608}
                        assert args[2:-2] == ["--force-recursive"]
                        assert target.startswith("harbor.stinkyboi.com/mirror/ghcr.io/home-assistant/home-assistant:")
                        directory = Path(source.removeprefix("ocidir://").removesuffix(":mirror"))
                        assert (directory / "manifest.json").read_text() == FIXTURE["manifests"][target]
                        if FIXTURE["failure"] == "mirror-destination":
                            print("failed to send blob chunk private-test-credential-must-never-appear", file=sys.stderr)
                            raise SystemExit(20)
                        (root / "published-images.json").write_text(json.dumps({target: FIXTURE["manifests"][target]}))
                        raise SystemExit(0)
                    assert "@sha256:" in source
                    user = config_data["username"]
                    if target.startswith("ocidir://"):
                        assert user == "robot$mirror+pull"
                        assert args[2:-2] == ["--force-recursive"]
                        if FIXTURE["failure"] == "mirror-regctl-pull":
                            raise SystemExit(21)
                        directory = Path(target.removeprefix("ocidir://").split(":", 1)[0])
                        contents = list(directory.iterdir())
                        assert contents == [] or contents == [directory / "partial"]
                        if FIXTURE["failure"] == "mirror-regctl-forward-dies":
                            marker = root / "regctl-forward-failed"
                            if not marker.exists():
                                marker.touch()
                                os.kill(int((root / "forward-pid").read_text()), signal.SIGTERM)
                                print("connection reset private-test-credential-must-never-appear", file=sys.stderr)
                                raise SystemExit(22)
                        fail_read("regctl-pull", {
                            "mirror-regctl-pull-once": "TLS handshake timeout",
                            "mirror-regctl-pull-server-once": "502 Bad Gateway",
                            "mirror-regctl-pull-server-always": "502 Bad Gateway",
                            "mirror-regctl-restart-readiness-once": "TLS handshake timeout",
                            "mirror-regctl-restart-readiness-always": "TLS handshake timeout",
                            "mirror-regctl-pull-four": "TLS handshake timeout",
                            "mirror-regctl-pull-always": "TLS handshake timeout",
                            "mirror-regctl-pull-auth": "unauthorized; TLS handshake timeout",
                        }, directory)
                        (directory / "digest").write_text(source.rsplit("@", 1)[1])
                    else:
                        assert args[2:-2] == []
                        assert user == "robot$mirror+publisher"
                        assert target.startswith("harbor.stinkyboi.com/mirror/")
                        reference = target
                        path = root / "published-images.json"
                        published = json.loads(path.read_text()) if path.exists() else {}
                        selected = source if reference.endswith(":issue-1846-canary") else reference
                        published[reference] = FIXTURE["manifests"][selected]
                        path.write_text(json.dumps(published))
                elif args[:2] == ["image", "digest"]:
                    assert json.loads(config.read_text()) == {"username": "robot$mirror+pull"}
                    digest = Path(args[2].removeprefix("ocidir://").split(":", 1)[0], "digest").read_text()
                    print("sha256:" + "0" * 64 if FIXTURE["failure"] == "mirror-regctl-digest" else digest)
                else:
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
        for command in ("aws", "skopeo", "regctl", "docker", "kubectl", "sudo", "curl", "timeout", "cosign"):
            path = self.root / "bin" / command
            path.write_text(mock)
            path.chmod(0o700)
        # Readiness polling calls sleep up to 90 times. Record each delay
        # without launching a Python interpreter for every simulated wait.
        self.executable("sleep", f"""test "$#" -eq 1 || exit 96
case "$1" in
    ''|*[!0-9]*) exit 96 ;;
esac
printf '{{"command": "sleep", "args": ["%s"]}}\\n' "$1" >>'{self.calls}'
""")
        shutil.copyfile(ROOT / "scripts/ci/install-kubeconfig.sh", self.root / "scripts/ci/install-kubeconfig.sh")

    def assert_cleaned(self):
        self.assertFalse((self.root / "host-route").exists())
        self.assertFalse((self.root / "home/.kube/config").exists())
        self.assertEqual(list((self.root / "runner").iterdir()), [])
        pidfile = self.root / "forward-pids"
        if pidfile.exists():
            for pid in pidfile.read_text().splitlines():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid), 0)

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
            {"images": [{"source": "docker.io/library/busybox:issue-1846-canary@sha256:" + "a" * 64}]},
            {"images": [{"source": "docker.io/library/busybox:latest"}]},
            {"images": [{"source": "localhost/internal@sha256:" + "a" * 64}]},
            {"images": [{"source": "codeberg.org.evil/k8s-gateway/k8s_gateway:1.9.0@sha256:" + "a" * 64}]},
            {"images": [{"source": "docker.io/library/../private@sha256:" + "a" * 64}]},
            {"images": [valid, {"source": valid["source"].replace("a" * 64, "b" * 64)}]},
        ]
        for catalog in invalid:
            with self.subTest(catalog=catalog):
                self.mirror_manifest = catalog
                self.rejected(mode="mirror")

    def test_image_updater_canary_rejects_other_artifacts_before_credentials(self):
        source = "docker.io/library/busybox@sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e"
        first = {"source": source}
        second = {"source": "docker.io/library/busybox@sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d"}
        self.mirror_manifest = {"images": [first, second]}
        for entries in ([], [first, second], [{"source": source.replace("busybox", "alpine")}],
                        [{"source": source[:-1] + "0"}], [{**first, "destination": "shared:latest"}]):
            with self.subTest(entries=entries):
                self.canary_mirror_manifest = {"images": entries}
                self.rejected("mirror-image-updater-canary", tailnet=True)
        self.canary_mirror_manifest = {"images": [first]}
        self.rejected("mirror-image-updater-canary")
        self.mirror_manifest = self.canary_mirror_manifest = {"images": [second]}
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-mirror.yml@refs/heads/main"
        del self.env["RUNNER_TEMP"]
        accepted = self.rejected("mirror-image-updater-canary", tailnet=True)
        self.assertIn("RUNNER_TEMP must be set", accepted.stderr)

    def test_image_updater_canary_pulls_before_a_single_alias_write(self):
        helper = self.root / "scripts/ci/harbor-publish.sh"
        original = helper.read_text()
        destination = "harbor.stinkyboi.com/mirror/docker.io/library/busybox"
        published = self.root / "published-images.json"
        previous = None
        for variant, fixture_digest in (
            ("A", "sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e"),
            ("B", "sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d"),
        ):
            with self.subTest(variant=variant):
                self.tailnet_mocks(resume=True, canary=variant)
                digest = self.published_digests["busybox"]
                self.canary_mirror_manifest = {"images": [{"source": f"docker.io/library/busybox@{digest}"}]}
                # Substitute local artifact content while preserving both scoped-digest checks.
                code = original.replace(fixture_digest, digest, 1)
                if previous:
                    prior_digest, prior_publication = previous
                    code = code.replace(
                        "sha256:fd7dc98638c8e305f4dc34e979f1c0fdfdcaeb0fbf8fcff77ae834b6da3d7e6e",
                        prior_digest, 1)
                    helper.write_text(code)
                    result = self.run_helper("mirror-image-updater-canary", tailnet=True)
                    self.assertNotEqual(result.returncode, 0, "B needs an established A")
                    self.assertFalse(published.exists())
                    self.calls.write_text("")
                    published.write_text(prior_publication)
                helper.write_text(code)
                if not previous:
                    checked_main = self.root / "checked-main"
                    self.executable("git", f"""if [ "$1" = ls-remote ]; then
  if [ -e {str(checked_main)!r} ]; then printf '%s\n' {'0' * 40}; exit 0; fi
  touch {str(checked_main)!r}
fi
printf '%s\n' {SHA}
""")
                    result = self.run_helper("mirror-image-updater-canary", tailnet=True)
                    self.assertNotEqual(result.returncode, 0, "main advanced before the alias write")
                    self.assertIn("phase=alias-copy", self.public_status)
                    self.assertFalse(published.exists())
                    self.assertFalse(any(args[:2] == ["image", "copy"] for args in self.calls_for("regctl")))
                    self.calls.write_text("")
                    self.executable("git", f"printf '%s\n' {SHA}\n")
                result = self.run_helper("mirror-image-updater-canary", tailnet=True)
                self.assertEqual(result.returncode, 0, result.stderr + self.public_status)
                copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
                self.assertEqual(len(copies), 1)
                self.assertTrue(copies[0][-1].startswith("dir:"))
                self.assertEqual(copies[0][-2], f"docker://{destination}@{digest}")
                self.assert_mirror_copy_credentials(copies)
                self.assertEqual([args for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]],
                                 [["image", "copy", f"{destination}@{digest}", f"{destination}:issue-1846-canary"]])
                calls = map(json.loads, self.calls.read_text().splitlines())
                copy_order = [call["command"] for call in calls if
                              (call["command"] == "skopeo" and call["args"][0] == "copy") or
                              (call["command"] == "regctl" and call["args"][:2] == ["image", "copy"])]
                self.assertEqual(copy_order, ["skopeo", "regctl"])

                self.assertIn(f"{destination}:issue-1846-canary@{digest}\n",
                              (self.root / "summary").read_text())

                publication = published.read_text()
                self.calls.write_text("")
                result = self.run_helper("mirror-image-updater-canary", tailnet=True)
                self.assertEqual(result.returncode, 0, result.stderr + self.public_status)
                self.assertFalse(any(args[:2] == ["image", "copy"] for args in self.calls_for("regctl")))
                self.assertFalse(any(args[0] == "copy" and args[-1].startswith("docker://")
                                     for args in self.calls_for("skopeo")))
                self.assertEqual(published.read_text(), publication)
                previous = (digest, publication)

        self.tailnet_mocks(resume=True, canary="A")
        self.calls.write_text("")
        published.write_text(publication)
        self.canary_mirror_manifest = {"images": [{"source": f"docker.io/library/busybox@{prior_digest}"}]}
        result = self.run_helper("mirror-image-updater-canary", tailnet=True)
        self.assertNotEqual(result.returncode, 0, "A must not overwrite B")
        self.assertIn("phase=alias-lookup", self.public_status)
        self.assertFalse(any(args[:2] == ["image", "copy"] for args in self.calls_for("regctl")))
        self.assertFalse(any(args[0] == "copy" and args[-1].startswith("docker://")
                             for args in self.calls_for("skopeo")))
        self.assertEqual(published.read_text(), publication)

    def test_dns_scope_declares_one_fixed_reviewed_image(self):
        source = "codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4"
        selected = json.loads((ROOT / "scripts/config/harbor-dns-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        self.assertEqual(selected, {"images": [{"source": source}]})
        self.assertIn(selected["images"][0], catalog["images"])

    def test_dns_scope_rejects_missing_extra_or_changed_image_before_credentials(self):
        source = "codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4"
        valid = {"source": source}
        self.mirror_manifest = {"images": [valid]}
        for scope in (None, {"images": []}, {"images": [valid, valid]},
                      {"images": [valid, {"source": "docker.io/library/busybox:1@sha256:" + "a" * 64}]},
                      {"images": [{"source": source.replace("0b556", "0b557")}]},
                      {"images": [{"source": source.replace("k8s_gateway", "other")}]},
                      {"images": [valid], "destination": "other"}):
            with self.subTest(scope=scope):
                self.dns_mirror_manifest = scope
                self.rejected(mode="mirror-dns")
        self.dns_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-dns")

    def test_dns_scope_retains_dispatch_guards(self):
        source = "codeberg.org/k8s-gateway/k8s_gateway:1.9.0@sha256:0b556f261d46873d7d2e86e5d345bb99db30de6b3869b83e32d273a466e980e4"
        self.dns_mirror_manifest = {"images": [{"source": source}]}
        self.mirror_manifest = self.dns_mirror_manifest
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-dns")
                self.env[key] = previous
        self.rejected(mode="mirror-dns:codeberg.org/k8s-gateway/k8s_gateway")
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-dns")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_litellm_scope_pins_exact_amd64_child_and_consumer(self):
        source = "ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8"
        selected = json.loads((ROOT / "scripts/config/harbor-litellm-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        workflow = (ROOT / ".github/workflows/harbor-mirror.yml").read_text()
        self.assertEqual(selected, {"images": [{"source": source}]})
        self.assertIn(selected["images"][0], catalog["images"])
        digest = source.split("@", 1)[1]
        self.assertIn("harbor.stinkyboi.com/mirror/" + source.split("@", 1)[0],
                      (ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text())
        self.assertIn(digest.removeprefix("sha256:") + "@" + digest,
                      (ROOT / "clusters/homelab/apps/litellm/values.yaml").read_text())
        self.assertNotIn("3305291fc9fa1b53196e21567a97f4c51e3a38bdc4e19704e38a551ee7712cd8",
                         json.dumps(catalog))
        self.assertIn("bash scripts/ci/harbor-publish.sh mirror-litellm", workflow)
        self.assertIn("all|fleet|bazarr|mastodon|traefik|chainguard|harbor|renovate|n8n|dns|litellm|prometheus|uptime-kuma|adguard|cilium|kagent|image-updater-canary|bazel-cache|home-assistant|homepage)", workflow)

    def test_litellm_scope_rejects_tampering_before_credentials(self):
        source = "ghcr.io/berriai/litellm-database@sha256:2791e3241d7fa59ad942c54c237fb0d53a140b52fad2bd4b40c14a873dbc14a8"
        valid = {"source": source}
        self.mirror_manifest = {"images": [valid]}
        for scope in (None, {"images": []}, {"images": [valid, valid]},
                      {"images": [{"source": source.replace("2791e", "2791f")}]},
                      {"images": [{"source": source.replace("litellm-database", "other")}]},
                      {"images": [valid], "destination": "other"}):
            with self.subTest(scope=scope):
                self.litellm_mirror_manifest = scope
                self.rejected(mode="mirror-litellm")
        self.litellm_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-litellm")

    def test_prometheus_scope_declares_one_fixed_reviewed_image(self):
        source = "quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d"
        selected = json.loads((ROOT / "scripts/config/harbor-prometheus-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        workflow = (ROOT / ".github/workflows/harbor-mirror.yml").read_text()
        self.assertEqual(selected, {"images": [{"source": source}]})
        self.assertIn(selected["images"][0], catalog["images"])
        self.assertIn("bash scripts/ci/harbor-publish.sh mirror-prometheus", workflow)
        self.assertIn("all|fleet|bazarr|mastodon|traefik|chainguard|harbor|renovate|n8n|dns|litellm|prometheus|uptime-kuma|adguard|cilium|kagent|image-updater-canary|bazel-cache|home-assistant|homepage)", workflow)

    def test_prometheus_scope_rejects_tampering_and_invalid_dispatch_before_credentials(self):
        source = "quay.io/prometheus/prometheus:v3.11.3-distroless@sha256:cff72a3f49918f41c4b5c8a6174dd8433036bebf7878120da538b3720ba3fa0d"
        valid = {"source": source}
        self.mirror_manifest = {"images": [valid]}
        for scope in (None, {"images": []}, {"images": [valid, valid]},
                      {"images": [{"source": source.replace("cff72", "cff73")}]},
                      {"images": [{"source": source.replace("prometheus/prometheus", "prometheus/other")}]},
                      {"images": [valid], "destination": "other"}):
            with self.subTest(scope=scope):
                self.prometheus_mirror_manifest = scope
                self.rejected(mode="mirror-prometheus")
        self.prometheus_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-prometheus")
        self.mirror_manifest = {"images": [valid]}
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-prometheus")
                self.env[key] = previous
        self.rejected(mode="mirror-prometheus:quay.io/prometheus/prometheus")
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-prometheus")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_home_assistant_scope_requires_the_exact_catalog_reference(self):
        source = "ghcr.io/home-assistant/home-assistant:2026.11.2@sha256:493a07e8f6530fc640223f4a0a5248f20a61ca2f718bb1d31efbf08a2c5ea28f"
        valid = {"source": source}
        selected = json.loads((ROOT / "scripts/config/harbor-home-assistant-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        self.assertEqual(selected, {"images": [valid]})
        self.assertIn(valid, catalog["images"])
        self.mirror_manifest = {"images": [valid]}
        for scope in (None, {"images": []}, {"images": [valid, valid]},
                      {"images": [{"source": source.replace("493a0", "493a1")}]}):
            with self.subTest(scope=scope):
                self.home_assistant_mirror_manifest = scope
                self.rejected(mode="mirror-home-assistant")
        self.home_assistant_mirror_manifest = selected
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-home-assistant")
        self.mirror_manifest = {"images": [valid]}
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-home-assistant")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_home_assistant_mirror_uploads_verified_local_oci_layout_in_chunks(self):
        self.transport_mocks(mirror=True, registries=("ghcr.io",), oci_index=True, home_assistant=True)
        result = self.run_helper("mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls_for("regctl")
        copies = [args for args in calls if args[:2] == ["image", "copy"]]
        self.assertEqual(len(copies), 4)
        self.assertTrue(copies[0][-1].startswith("ocidir://"))
        self.assertEqual(copies[0][-1], copies[1][-2])
        self.assertTrue(copies[-1][-1].startswith("ocidir://"))
        self.assertTrue((self.root / "summary").is_file())
        self.assert_cleaned()

    def test_home_assistant_mirror_refuses_corrupt_staging_before_upload(self):
        self.transport_mocks(failure="upstream-digest", mirror=True, registries=("ghcr.io",),
                             oci_index=True, home_assistant=True)
        result = self.run_helper("mirror")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len([args for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]), 1)
        self.assertFalse((self.root / "summary").exists())
        self.assertIn("category=digest-mismatch\n", self.public_status)
        self.assert_cleaned()

    def test_home_assistant_mirror_stops_without_receipt_on_chunked_upload_error(self):
        self.transport_mocks(failure="mirror-destination", mirror=True, registries=("ghcr.io",),
                             oci_index=True, home_assistant=True)
        result = self.run_helper("mirror")
        self.assertEqual(result.returncode, 20)
        self.assertEqual(len([args for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]), 2)
        self.assertFalse((self.root / "summary").exists())
        self.assertIn("phase=destination-copy\n", self.public_status)
        self.assertIn("category=blob-upload-failed\n", self.public_status)
        self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr + self.public_status)
        self.assert_cleaned()

    def test_homepage_scope_only_accepts_the_reviewed_catalog_image(self):
        source = (
            "ghcr.io/gethomepage/homepage:v2.8.0@"
            "sha256:019d8f063a7299e7c1c51ee4a70b692291809af3244894fbec2c2ac7d1f71b18"
        )
        entry = {"source": source}
        selected = json.loads((ROOT / "scripts/config/harbor-homepage-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        self.assertEqual(selected, {"images": [entry]})
        self.assertIn(entry, catalog["images"])

        tampered = {"source": source.replace("019d8f", "119d8f")}
        self.mirror_manifest = {"images": [entry, tampered]}
        for scope in (None, {"images": [tampered]}, {"images": [entry, tampered]}):
            with self.subTest(scope=scope):
                self.homepage_mirror_manifest = scope
                self.rejected(mode="mirror-homepage")

        self.homepage_mirror_manifest = selected
        self.mirror_manifest = {"images": [tampered]}
        self.rejected(mode="mirror-homepage")
        self.mirror_manifest = selected
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-homepage")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_uptime_kuma_scope_declares_one_fixed_reviewed_image(self):
        source = "docker.io/louislam/uptime-kuma:2.5.11@sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9"
        selected = json.loads((ROOT / "scripts/config/harbor-uptime-kuma-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        workflow = (ROOT / ".github/workflows/harbor-mirror.yml").read_text()
        self.assertEqual(selected, {"images": [{"source": source}]})
        self.assertIn(selected["images"][0], catalog["images"])
        self.assertIn("bash scripts/ci/harbor-publish.sh mirror-uptime-kuma", workflow)
        self.assertIn("all|fleet|bazarr|mastodon|traefik|chainguard|harbor|renovate|n8n|dns|litellm|prometheus|uptime-kuma|adguard|cilium|kagent|image-updater-canary|bazel-cache|home-assistant|homepage)", workflow)

    def test_uptime_kuma_scope_rejects_tampering_and_invalid_dispatch_before_credentials(self):
        source = "docker.io/louislam/uptime-kuma:2.5.11@sha256:7554dba313c84e44fee921ef3b5626ba1c711e412e82815e8c957517026112a9"
        valid = {"source": source}
        self.mirror_manifest = {"images": [valid]}
        for scope in (None, {"images": []}, {"images": [valid, valid]},
                      {"images": [{"source": source.replace("7554d", "7554e")}]},
                      {"images": [{"source": source.replace("louislam/uptime-kuma", "louislam/other")}]},
                      {"images": [valid], "destination": "other"}):
            with self.subTest(scope=scope):
                self.uptime_kuma_mirror_manifest = scope
                self.rejected(mode="mirror-uptime-kuma")
        self.uptime_kuma_mirror_manifest = {"images": [valid]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-uptime-kuma")
        self.mirror_manifest = {"images": [valid]}
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-uptime-kuma")
                self.env[key] = previous
        self.rejected(mode="mirror-uptime-kuma:quay.io/prometheus/prometheus")
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-uptime-kuma")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_adguard_scope_declares_fixed_reviewed_images(self):
        source = 'docker.io/adguard/adguardhome:v0.107.80@sha256:e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c'
        init = {'source': 'docker.io/library/python:3.14.7-alpine3.23@sha256:218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d'}
        selected = json.loads((ROOT / "scripts/config/harbor-adguard-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        workflow = (ROOT / ".github/workflows/harbor-mirror.yml").read_text()
        self.assertEqual(selected, {"images": [{"source": source}, init]})
        for entry in selected["images"]:
            self.assertIn(entry, catalog["images"])
        self.assertIn("bash scripts/ci/harbor-publish.sh mirror-adguard", workflow)
        self.assertIn("all|fleet|bazarr|mastodon|traefik|chainguard|harbor|renovate|n8n|dns|litellm|prometheus|uptime-kuma|adguard|cilium|kagent|image-updater-canary|bazel-cache|home-assistant|homepage)", workflow)

    def test_adguard_scope_rejects_tampering_and_invalid_dispatch_before_credentials(self):
        source = 'docker.io/adguard/adguardhome:v0.107.80@sha256:e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c'
        init = {'source': 'docker.io/library/python:3.14.7-alpine3.23@sha256:218761489de417a6eb0808e264cbdd7043ec6659fe5a61898815e9848536541d'}
        valid = {"source": source}
        self.mirror_manifest = {"images": [valid, init]}
        for scope in (None, {"images": []}, {"images": [valid]}, {"images": [init]}, {"images": [valid, valid]},
                      {"images": [{"source": source.replace("e2e1b", "e2e1c")}, init]},
                      {"images": [valid, {"source": init["source"].replace("218761", "218762")}]},
                      {"images": [{"source": source.replace("adguard/adguardhome", "adguard/other")}]},
                      {"images": [valid], "destination": "other"}):
            with self.subTest(scope=scope):
                self.adguard_mirror_manifest = scope
                self.rejected(mode="mirror-adguard")
        self.adguard_mirror_manifest = {"images": [valid, init]}
        self.mirror_manifest = {"images": []}
        self.rejected(mode="mirror-adguard")
        self.mirror_manifest = {"images": [valid, init]}
        for key, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/test"),
                           ("EXPECTED_SHA", "b" * 40)):
            with self.subTest(key=key):
                previous = self.env[key]
                self.env[key] = value
                self.rejected(mode="mirror-adguard")
                self.env[key] = previous
        self.rejected(mode="mirror-adguard:quay.io/prometheus/prometheus")
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-adguard")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_cilium_scope_requires_the_complete_reviewed_bundle(self):
        selected = json.loads((ROOT / "scripts/config/harbor-cilium-images.json").read_text())
        self.assertEqual(len(selected["images"]), 3)
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        for entry in selected["images"]:
            self.assertIn(entry, catalog["images"])
        self.mirror_manifest = selected
        self.cilium_mirror_manifest = {"images": selected["images"][:-1]}
        self.rejected(mode="mirror-cilium")
        self.cilium_mirror_manifest = selected
        self.mirror_manifest = {"images": selected["images"][:-1]}
        self.rejected(mode="mirror-cilium")
        self.mirror_manifest = selected
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-cilium")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_kagent_scope_requires_the_complete_catalog_bundle(self):
        selected = json.loads((ROOT / "scripts/config/harbor-kagent-images.json").read_text())
        self.assertEqual(len(selected["images"]), 6)
        self.mirror_manifest = selected
        self.kagent_mirror_manifest = {"images": selected["images"][:-1]}
        self.rejected(mode="mirror-kagent")
        self.kagent_mirror_manifest = selected
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-kagent")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_codeberg_registry_uses_anonymous_copy_and_complete_harbor_pull(self):
        self.transport_mocks(mirror=True, registries=("docker.io", "codeberg.org"))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertTrue(any("docker://codeberg.org/" in args[-2] for args in copies))
        self.assertTrue(any(args[-1].startswith("dir:") and
                            "harbor.stinkyboi.com/mirror/codeberg.org/" in args[-2]
                            for args in copies))
        self.assert_mirror_copy_credentials(copies)
        self.assert_cleaned()

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

    def test_harbor_runtime_scope_has_nine_reviewed_components(self):
        selected = json.loads((ROOT / "scripts/config/harbor-runtime-images.json").read_text())["images"]
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())["images"]
        self.assertEqual(len(selected), 9)
        self.assertTrue(all(item in catalog and item["source"].startswith("docker.io/goharbor/")
                            and ":v2.15.4@" in item["source"] for item in selected))

    def test_harbor_runtime_scope_rejects_unreviewed_and_verifies_selected_pull(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.harbor_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-harbor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len([args for args in self.calls_for("skopeo") if args[0] == "copy"]), 4)
        self.assert_cleaned()
        self.calls.unlink()
        self.harbor_mirror_manifest = {"images": [{"source": selected["source"].split("@", 1)[0]
                                                   + "@sha256:" + "0" * 64}]}
        self.rejected(mode="mirror-harbor")

    def test_n8n_scope_rejects_unreviewed_digests_and_other_repositories(self):
        selected = json.loads((ROOT / "scripts/config/harbor-n8n-images.json").read_text())
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        other = self.mirror_manifest["images"][0]
        self.assertEqual(len(selected["images"]), 1)
        self.assertIn(selected["images"][0], catalog["images"])
        self.n8n_mirror_manifest = selected
        self.rejected(mode="mirror-n8n")
        self.mirror_manifest = {"images": [*selected["images"], other]}
        self.n8n_mirror_manifest = {"images": [other]}
        self.rejected(mode="mirror-n8n")
        self.n8n_mirror_manifest = selected
        del self.env["OCTELIUM_AUTH_TOKEN"]
        result = self.rejected(mode="mirror-n8n")
        self.assertIn("The production Octelium CI credential is required", result.stderr)

    def test_renovate_scope_has_eight_reviewed_sources(self):
        selected = json.loads((ROOT / "scripts/config/harbor-renovate-images.json").read_text())["images"]
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())["images"]
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(item in catalog for item in selected))
        self.assertEqual(len({item["source"].split("@", 1)[0] for item in selected}), len(selected))
        for item in selected:
            alias = item["source"].split("@", 1)[0]
            self.assertEqual(next(entry["source"] for entry in reversed(catalog)
                                  if entry["source"].split("@", 1)[0] == alias), item["source"])
        self.assertEqual(sum(item["source"].startswith("ghcr.io/renovatebot/renovate:")
                             for item in selected), 1)

    def test_renovate_scope_rejects_unreviewed_and_verifies_selected_pull(self):
        self.transport_mocks(mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.renovate_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len([args for args in self.calls_for("skopeo") if args[0] == "copy"]), 4)
        self.assert_cleaned()
        self.calls.unlink()
        self.renovate_mirror_manifest = {"images": [{"source": selected["source"].split("@", 1)[0]
                                                    + "@sha256:" + "0" * 64}]}
        self.rejected(mode="mirror-renovate")

    def test_renovate_oci_index_uses_regctl_with_authenticated_pull(self):
        self.transport_mocks(failure="mirror-oci-index", mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.renovate_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = f"harbor.stinkyboi.com/mirror/{repository}"
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(self.calls_for("timeout")[0][2], "19800")
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assert_mirror_copy_credentials(copies)
        regctl_copies = [args[2:] for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]
        self.assertEqual(regctl_copies[:2], [
            [f"{repository}@{digest}", f"{destination}:{digest[7:]}"],
            [f"{destination}@{digest}", f"{destination}:stable"],
        ])
        self.assertEqual(len(regctl_copies), 3)
        self.assertEqual(regctl_copies[-1][-2], f"{destination}@{digest}")
        self.assertTrue(regctl_copies[-1][-1].startswith("ocidir://"))
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_oci_destination_conversion_uses_regctl_after_verified_staging(self):
        self.transport_mocks(failure="mirror-oci-destination", mirror=True)
        selected = self.mirror_manifest["images"][1]
        self.renovate_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        repository = source.split(":")[0]
        destination = f"harbor.stinkyboi.com/mirror/{repository}"
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 2)
        self.assertEqual(copies[0][-2], f"docker://{repository}@{digest}")
        self.assertTrue(copies[0][-1].startswith("dir:"))
        self.assertTrue(copies[1][-2].startswith("dir:"))
        self.assertEqual(copies[1][-1], f"docker://{destination}:{digest[7:]}")
        self.assert_mirror_copy_credentials(copies)
        regctl_copies = [args[2:] for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]
        self.assertEqual(regctl_copies[:2], [
            [f"{repository}@{digest}", f"{destination}:{digest[7:]}"],
            [f"{destination}@{digest}", f"{destination}:stable"],
        ])
        self.assertEqual(len(regctl_copies), 3)
        self.assertEqual(regctl_copies[-1][-2], f"{destination}@{digest}")
        self.assertTrue(regctl_copies[-1][-1].startswith("ocidir://"))
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_harbor_missing_index_child_retries_with_regctl_only_for_index(self):
        self.transport_mocks(failure="mirror-index-child-notfound", mirror=True, oci_index=True)
        selected = self.mirror_manifest["images"][1]
        self.renovate_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len([args for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]), 3)
        self.assert_cleaned()
        self.calls.unlink()

        self.transport_mocks(failure="mirror-index-child-notfound", mirror=True)
        self.renovate_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse([args for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]])
        self.assert_cleaned()

    def test_oci_alias_retry_uses_regctl_and_authenticated_pull(self):
        self.transport_mocks(failure="mirror-oci-alias", mirror=True, resume=True)
        selected = self.mirror_manifest["images"][1]
        self.renovate_mirror_manifest = {"images": [selected]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        source, digest = selected["source"].split("@")
        destination = f"harbor.stinkyboi.com/mirror/{source.split(':')[0]}"
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0][-2], f"docker://{destination}@{digest}")
        self.assertEqual(copies[0][-1], f"docker://{destination}:stable")
        self.assert_mirror_copy_credentials(copies)
        regctl_copies = [args[2:] for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]
        self.assertEqual(regctl_copies[0], [f"{destination}@{digest}", f"{destination}:stable"])
        self.assertEqual(len(regctl_copies), 2)
        self.assertEqual(regctl_copies[-1][-2], f"{destination}@{digest}")
        self.assertTrue(regctl_copies[-1][-1].startswith("ocidir://"))
        self.assertEqual((self.root / "summary").read_text().splitlines(),
                         [f"{destination}:{digest[7:]}@{digest}"])
        self.assert_cleaned()

    def test_renovate_oci_index_rejects_incomplete_or_wrong_pull(self):
        for failure in ("mirror-regctl-pull", "mirror-regctl-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                self.renovate_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
                result = self.run_helper(mode="mirror-renovate")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_renovate_existing_oci_index_uses_complete_regctl_pull(self):
        self.transport_mocks(mirror=True, resume=True, oci_index=True)
        self.renovate_mirror_manifest = {"images": [self.mirror_manifest["images"][1]]}
        result = self.run_helper(mode="mirror-renovate")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args[2:] for args in self.calls_for("regctl") if args[:2] == ["image", "copy"]]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0][-1].startswith("ocidir://"))
        self.assertFalse([args for args in self.calls_for("skopeo") if args[0] == "copy"])
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

    def test_mirror_accepts_anonymous_talos_image_factory(self):
        self.transport_mocks(mirror=True, registries=("factory.talos.dev", "docker.io"))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        sources = [image["source"] for image in self.mirror_manifest["images"]]
        self.assertTrue(any(image.startswith("factory.talos.dev/") for image in sources))
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

    def test_mirror_transport_logs_are_bounded_and_private(self):
        helper = self.root / "scripts/ci/harbor-encrypt-diagnostic.py"
        helper.write_text("from pathlib import Path\nimport sys\n"
                          "data = Path(sys.argv[1]).read_bytes()\n"
                          "assert b'private port-forward fixture' in data\n"
                          "assert b'private readiness fixture' in data\n"
                          "assert len(data) < 66000\n"
                          "Path(sys.argv[2]).write_bytes(b'ciphertext fixture')\n")
        self.transport_mocks(failure="forward", mirror=True)
        result = self.run_helper(mode="mirror")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("private port-forward fixture", result.stdout + result.stderr)
        self.assertNotIn("private readiness fixture", result.stdout + result.stderr)
        artifact = self.root / "runner/harbor-publication-error.gpg"
        self.assertEqual(artifact.read_bytes(), b"ciphertext fixture")
        artifact.unlink()
        self.assert_cleaned()

    def test_mirror_setup_failure_keeps_only_encrypted_diagnostic(self):
        helper = self.root / "scripts/ci/harbor-encrypt-diagnostic.py"
        helper.write_text("from pathlib import Path\nimport sys\n"
                          f"assert {SECRET_SENTINEL!r}.encode() in Path(sys.argv[1]).read_bytes()\n"
                          "Path(sys.argv[2]).write_bytes(b'ciphertext fixture')\n")
        self.transport_mocks(mirror=True)
        self.executable("aws", f"printf '%s\\n' '{SECRET_SENTINEL}' >&2\nexit 17\n")
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 17)
        self.assertIn("phase=setup\n", self.public_status)
        artifact = self.root / "runner/harbor-publication-error.gpg"
        self.assertEqual(artifact.read_bytes(), b"ciphertext fixture")
        artifact.unlink()
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

    def test_mirror_verification_retries_one_retryable_read_failure(self):
        for failure, phase in (("mirror-alias-lookup-once", "alias"),
                               ("mirror-alias-verify-once", "alias"),
                               ("mirror-pull-once", "skopeo"),
                               ("mirror-pull-http2-once", "skopeo"),
                               ("mirror-pull-server-once", "skopeo"),
                               ("mirror-regctl-pull-once", "regctl"),
                               ("mirror-regctl-pull-server-once", "regctl")):
            with self.subTest(failure=failure):
                self.calls.unlink(missing_ok=True)
                (self.root / "summary").unlink(missing_ok=True)
                (self.root / "skopeo-pull-failed").unlink(missing_ok=True)
                (self.root / "regctl-pull-failed").unlink(missing_ok=True)
                self.transport_mocks(failure=failure, mirror=True)
                result = self.run_helper(mode="mirror")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len((self.root / "summary").read_text().splitlines()), 2)
                if phase == "alias":
                    reads = [args[-1] for args in self.calls_for("skopeo")
                             if args[0] == "inspect" and args[-1].endswith(":stable")]
                    self.assertEqual(len(reads), 5)  # Two lookups, two verifications, one retry.
                elif phase == "skopeo":
                    reads = [args[-1] for args in self.calls_for("skopeo")
                             if args[0] == "copy" and args[-2].startswith("docker://harbor.stinkyboi.com/")
                             and args[-1].startswith("dir:")]
                    self.assertEqual(len(reads), 3)
                    self.assertEqual(len(set(reads)), 3)
                    self.assertEqual(len([args for args in self.calls_for("kubectl")
                                          if "port-forward" in args]), 2)
                    self.assertEqual(len(self.calls_for("curl")), 2)
                else:
                    reads = [args[-1] for args in self.calls_for("regctl")
                             if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
                    self.assertEqual(len(reads), 3)
                    self.assertEqual(reads[0], reads[1])
                    self.assertEqual(len(set(reads)), 2)
                    self.assertEqual(len([args for args in self.calls_for("kubectl")
                                          if "port-forward" in args]), 2)
                    self.assertEqual(len(self.calls_for("curl")), 2)
                self.assert_cleaned()

    def test_mirror_index_pull_restarts_dead_forward_before_retry(self):
        self.transport_mocks(failure="mirror-regctl-forward-dies", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        pulls = [args for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 2)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 2)
        self.assertEqual(len(self.calls_for("curl")), 2)
        sudo_calls = self.calls_for("sudo")
        self.assertEqual(len([args for args in sudo_calls if "tee" in args]), 1)
        self.assertEqual(len([args for args in sudo_calls if "sed" in args]), 1)
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 1)
        self.assert_cleaned()

    def test_mirror_index_pull_retries_failed_forward_readiness(self):
        self.transport_mocks(failure="mirror-regctl-restart-readiness-once", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        pulls = [args for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 2)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 3)
        sudo_calls = self.calls_for("sudo")
        self.assertEqual(len([args for args in sudo_calls if "tee" in args]), 1)
        self.assertEqual(len([args for args in sudo_calls if "sed" in args]), 1)
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 1)
        self.assert_cleaned()

    def test_mirror_index_pull_stops_after_bounded_forward_readiness_failures(self):
        self.transport_mocks(failure="mirror-regctl-restart-readiness-always", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertNotEqual(result.returncode, 0)
        pulls = [args for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 1)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 4)
        self.assertFalse((self.root / "summary").exists())
        self.assertIn("phase=authenticated-pull\n", self.public_status)
        self.assertIn("category=transport-failed\n", self.public_status)
        self.assert_cleaned()

    def test_mirror_index_pull_recovers_after_four_transport_failures(self):
        self.transport_mocks(failure="mirror-regctl-pull-four", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        pulls = [args[-1] for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 5)
        self.assertEqual(len(set(pulls)), 1)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 5)
        self.assertEqual(len(self.calls_for("curl")), 5)
        self.assertEqual([args[0] for args in self.calls_for("sleep")], ["2", "4", "8", "16"])
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 1)
        self.assert_cleaned()

    def test_mirror_index_pull_stops_after_five_transport_failures(self):
        self.transport_mocks(failure="mirror-regctl-pull-always", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 22)
        pulls = [args[-1] for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 5)
        self.assertEqual(len(set(pulls)), 1)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 5)
        self.assertEqual(len(self.calls_for("curl")), 5)
        self.assertEqual([args[0] for args in self.calls_for("sleep")], ["2", "4", "8", "16"])
        self.assertFalse((self.root / "summary").exists())
        self.assertIn("phase=authenticated-pull\n", self.public_status)
        self.assertIn("category=transport-retries-exhausted\n", self.public_status)
        self.assert_cleaned()

    def test_mirror_index_pull_stops_after_five_server_failures(self):
        self.transport_mocks(failure="mirror-regctl-pull-server-always", mirror=True,
                             registries=("docker.io",))
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 22)
        pulls = [args for args in self.calls_for("regctl")
                 if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
        self.assertEqual(len(pulls), 5)
        self.assertEqual(len([args for args in self.calls_for("kubectl")
                              if "port-forward" in args]), 5)
        self.assertFalse((self.root / "summary").exists())
        self.assertIn("phase=authenticated-pull\n", self.public_status)
        self.assertIn("category=server-error\n", self.public_status)
        self.assert_cleaned()

    def test_mirror_verification_does_not_retry_hard_failures(self):
        for failure, phase, count in (
            ("mirror-alias-lookup-auth", "alias-lookup", 1),
            ("mirror-alias-verify-auth", "alias-verify", 2),
            ("mirror-alias-verify-missing", "alias-verify", 2),
            ("mirror-alias-verify-digest", "alias-verify", 2),
            ("mirror-pull-auth", "authenticated-pull", 1),
            ("mirror-pull-forbidden", "authenticated-pull", 1),
            ("mirror-pull-missing", "authenticated-pull", 1),
            ("mirror-pull-http-missing", "authenticated-pull", 1),
            ("mirror-pull-digest", "authenticated-pull", 1),
            ("mirror-pull-preserve", "authenticated-pull", 1),
            ("mirror-regctl-pull-auth", "authenticated-pull", 1),
            ("mirror-pull-always", "authenticated-pull", 3),
            ("mirror-pull-server-always", "authenticated-pull", 3),
        ):
            with self.subTest(failure=failure):
                self.calls.unlink(missing_ok=True)
                (self.root / "summary").unlink(missing_ok=True)
                self.transport_mocks(failure=failure, mirror=True,
                                     forward_start_delay=1 if failure == "mirror-pull-server-always" else 0)
                result = self.run_helper(mode="mirror")
                self.assertEqual(result.returncode, 22)
                self.assertFalse((self.root / "summary").exists())
                self.assertIn(f"phase={phase}\n", self.public_status)
                if failure.startswith("mirror-alias"):
                    reads = [args for args in self.calls_for("skopeo")
                             if args[0] == "inspect" and args[-1].endswith(":stable")]
                elif failure.startswith("mirror-regctl"):
                    reads = [args for args in self.calls_for("regctl")
                             if args[:2] == ["image", "copy"] and args[-1].startswith("ocidir://")]
                else:
                    reads = [args for args in self.calls_for("skopeo")
                             if args[0] == "copy" and args[-2].startswith("docker://harbor.stinkyboi.com/")
                             and args[-1].startswith("dir:")]
                self.assertEqual(len(reads), count)
                if failure in ("mirror-pull-always", "mirror-pull-server-always"):
                    self.assertEqual(len([args for args in self.calls_for("kubectl")
                                          if "port-forward" in args]), 3)
                    self.assertEqual(len(self.calls_for("curl")), 3)
                if failure == "mirror-pull-server-always":
                    self.assertIn("category=server-error\n", self.public_status)
                self.assert_cleaned()

    def test_mirror_failures_withhold_acceptance_and_clean_credentials(self):
        for failure in ("mirror-source", "mirror-alias", "mirror-lookup", "mirror-alias-lookup", "digest", "mirror-tag", "pull", "pull-digest"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure, mirror=True)
                result = self.run_helper(mode="mirror")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                phases = {"mirror-source": "upstream-download", "mirror-alias": "alias-copy", "mirror-lookup": "digest-lookup", "mirror-alias-lookup": "alias-lookup",
                          "digest": "digest-verify", "mirror-tag": "alias-verify", "pull": "authenticated-pull", "pull-digest": "pull-verify"}
                categories = {"mirror-source": "rate-limited", "mirror-alias": "transport-failed", "mirror-lookup": "transport-failed", "mirror-alias-lookup": "transport-failed",
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

    def test_destination_copy_stage_categories_are_fixed_and_fail_closed(self):
        for message, category in (
            ("writing blob: private upload error", "blob-upload-failed"),
            ("writing manifest: private registry error", "manifest-upload-failed"),
            ("unclassified private copy error", "command-failed"),
        ):
            with self.subTest(message=message):
                self.transport_mocks(failure="mirror-destination", mirror=True,
                                     destination_error=message)
                result = self.run_helper(mode="mirror")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(dict(line.split("=", 1) for line in self.public_status.splitlines()), {
                    "source": self.mirror_manifest["images"][0]["source"],
                    "phase": "destination-copy",
                    "exit_status": str(result.returncode),
                    "category": category,
                })
                self.assertNotIn(message, self.public_status)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()

    def test_mirror_resume_avoids_upstream_but_rechecks_aliases_and_complete_pulls(self):
        self.transport_mocks(mirror=True, resume=True)
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(args[-2].startswith("docker://harbor.stinkyboi.com/mirror/") for args in copies))
        self.assertEqual(sum(args[-1].startswith("dir:") for args in copies), 2)
        self.assertEqual(sum(args[-1].endswith(":stable") for args in copies), 0)
        self.assert_mirror_copy_credentials(copies)
        inspections = [args[-1] for args in self.calls_for("skopeo") if args[0] == "inspect"]
        self.assertEqual(sum(reference.endswith(":stable") for reference in inspections), 4)
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

    def test_mirror_stale_alias_is_replaced_from_verified_digest(self):
        self.transport_mocks(failure="mirror-existing-alias", mirror=True, resume=True)
        result = self.run_helper(mode="mirror")
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [args for args in self.calls_for("skopeo") if args[0] == "copy"]
        self.assertEqual(sum(args[-1].endswith(":stable") for args in copies), 2)
        self.assertEqual(sum(args[-1].startswith("dir:") for args in copies), 2)
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

    def test_enterprise_images_and_cli_publish_only_from_its_workflow(self):
        self.transport_mocks(enterprise=True)
        result = self.run_helper(mode="publish-openclaw-enterprise")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.root / "outputs").read_text()
        for name, key in (("homelab-oce-controller", "controller"),
                          ("homelab-oce-runtime", "runtime"),
                          ("homelab-oce-cli", "cli"),
                          ("homelab-oce-operator", "operator")):
            self.assertIn(f"{key}=harbor.stinkyboi.com/homelab/{name}:homelab-{SHA}@", output)
        self.assertEqual(len(self.calls_for("cosign")), 4)
        pulls = [args for args in self.calls_for("skopeo")
                 if args[0] == "copy" and args[-1].startswith("dir:")]
        self.assertEqual(len(pulls), 4)
        self.assert_cleaned()

    def test_enterprise_failure_reports_only_fixed_public_phase(self):
        for failure, phase in (("pull", "authenticated-pull-controller"),
                               ("sign", "signing-wait")):
            with self.subTest(failure=failure):
                self.transport_mocks(enterprise=True, failure=failure)
                result = self.run_helper(mode="publish-openclaw-enterprise")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "outputs").exists())
                self.assertEqual((self.root / "summary").read_text().splitlines(), [
                    f"Enterprise image publication failed at phase: {phase}"
                ])
                self.assert_cleaned()
                (self.root / "summary").unlink()
                (self.root / "published-images.json").unlink(missing_ok=True)

    def test_enterprise_public_phase_annotation_redacts_untrusted_summary(self):
        workflow = (ROOT / ".github/workflows/openclaw-enterprise-images.yml").read_text()
        phase_block = workflow.split("            phase=unclassified\n", 1)[1].split(
            "            exit 1\n", 1)[0]
        phase_script = "phase=unclassified\n" + textwrap.dedent(phase_block)
        summary = self.root / "summary"
        for contents, expected in (
            ("Enterprise image publication failed at phase: push-controller\n",
             "push-controller"),
            ("verified digest receipt\nEnterprise image publication failed at phase: cleanup\n",
             "cleanup"),
            (f"Enterprise image publication failed at phase: {SECRET_SENTINEL}\n",
             "unclassified"),
            (f"Enterprise image publication failed at phase: push-controller\n"
             f"::error::{SECRET_SENTINEL}\n", "unclassified"),
        ):
            with self.subTest(expected=expected):
                summary.write_text(contents)
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c", phase_script],
                    env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
                    capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(),
                                 "::error::Enterprise image publication failed at phase: "
                                 f"{expected}; private transport and registry output withheld.")
                self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr)
        summary.unlink()
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", phase_script],
            env={**os.environ, "GITHUB_STEP_SUMMARY": str(summary)},
            capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("phase: unclassified;", result.stdout)

    def test_enterprise_preflight_and_cleanup_failures_have_fixed_phases(self):
        self.transport_mocks(enterprise=True)
        self.env["EXPECTED_SHA"] = "0" * 40
        result = self.run_helper(mode="publish-openclaw-enterprise")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())
        self.assertEqual((self.root / "summary").read_text().splitlines(), [
            "Enterprise image publication failed at phase: preflight"
        ])
        (self.root / "summary").unlink()
        self.env["EXPECTED_SHA"] = SHA

        self.transport_mocks(enterprise=True, failure="enterprise-cleanup")
        result = self.run_helper(mode="publish-openclaw-enterprise")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "summary").read_text().splitlines()[-1],
                         "Enterprise image publication failed at phase: cleanup")
        self.assert_cleaned()

    def test_enterprise_pair_refuses_other_workflow_before_credentials(self):
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/nofx-images.yml@refs/heads/main"
        self.rejected(mode="publish-openclaw-enterprise")

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

    def test_cordium_publication_uses_only_fixed_pair_and_signed_outputs(self):
        self.transport_mocks(cordium=True)
        result = self.run_helper(mode="publish-cordium")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.root / "outputs").read_text()
        self.assertIn("runner=harbor.stinkyboi.com/homelab/homelab-cordium-runner:", output)
        self.assertIn("controller=harbor.stinkyboi.com/homelab/homelab-cordium-controller:", output)
        self.assertNotIn("homelab-nofx", output)
        self.assertEqual(len(self.calls_for("cosign")), 2)
        self.assert_cleaned()

    def test_cordium_push_cannot_reach_credentials_or_publication(self):
        self.env["GITHUB_EVENT_NAME"] = "push"
        self.rejected(mode="publish-cordium")

    def test_cordium_publication_rejects_a_different_workflow(self):
        self.transport_mocks(cordium=True)
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-mirror.yml@refs/heads/main"
        result = self.rejected(mode="publish-cordium")
        self.assertIn("Invalid Cordium publication dispatch context", result.stderr)

    def test_cordium_digest_or_signing_failure_withholds_success(self):
        for failure in ("digest", "pull", "pull-digest", "sign", "verify"):
            self.transport_mocks(cordium=True, failure=failure)
            result = self.run_helper(mode="publish-cordium")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "outputs").exists())
            self.assert_cleaned()
            (self.root / "published-images.json").unlink(missing_ok=True)

    def test_signing_failure_withholds_success_and_cleans(self):
        for failure in ("sign", "verify", "signer-owner"):
            with self.subTest(failure=failure):
                self.transport_mocks(failure=failure)
                result = self.run_helper(mode="publish")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "summary").exists())
                self.assert_cleaned()
                (self.root / "published-images.json").unlink(missing_ok=True)

    def tailnet_mocks(self, status="401", failure=None, readiness_failures=None, **kwargs):
        self.transport_mocks(mirror=True, failure=failure, **kwargs)
        self.env.pop("OCTELIUM_AUTH_TOKEN", None)
        self.env.pop("KUBE_API_SERVER_URL", None)
        self.calls.touch(exist_ok=True)
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/harbor-mirror.yml@refs/heads/main"
        self.executable("curl", f"""exec python3 - "$@" <<'PYMOCK'
import json, sys
from pathlib import Path
args = sys.argv[1:]
assert "--insecure" not in args and "--resolve" not in args
assert args[-1] == "https://harbor.stinkyboi.com/v2/"
calls = Path({str(self.calls)!r})
attempt = 1 + sum(json.loads(line)["command"] == "curl" for line in calls.read_text().splitlines())
with calls.open("a") as f:
    f.write(json.dumps({{"command":"curl","args":args}})+"\\n")
failure = {readiness_failures or {}!r}.get(attempt)
if failure:
    print("private tailnet readiness fixture", file=sys.stderr)
    raise SystemExit(failure)
print({status!r},end="")
PYMOCK
""")

    def test_tailnet_mirror_needs_no_kubernetes_or_host_mutation(self):
        self.tailnet_mocks()
        config = self.root / "home/.kube/config"
        config.parent.mkdir(parents=True)
        config.write_text("existing inert kubeconfig")
        result = self.run_helper("mirror", tailnet=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_for("kubectl"), [])
        self.assertEqual(self.calls_for("sudo"), [])
        self.assertFalse((self.root / "host-route").exists())
        self.assertEqual(config.read_text(), "existing inert kubeconfig")
        self.assertNotIn(SECRET_SENTINEL, result.stdout + result.stderr)
        self.assertTrue(self.calls_for("skopeo"))

    def test_tailnet_challenge_failure_stops_before_credentials(self):
        for status in ("200", "403"):
            with self.subTest(status=status):
                self.tailnet_mocks(status=status)
                result = self.run_helper("mirror", tailnet=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls_for("aws"), [])
                self.assertEqual(self.calls_for("kubectl"), [])

    def test_tailnet_authenticated_retry_recovers_after_connection_failure(self):
        self.tailnet_mocks(failure="mirror-pull-once", readiness_failures={2: 7})
        result = self.run_helper("mirror", tailnet=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls_for("curl")), 3)
        self.assertEqual(self.calls_for("kubectl"), [])
        self.assertEqual(self.calls_for("sudo"), [])
        self.assertEqual(len((self.root / "summary").read_text().splitlines()), 2)
        self.assertNotIn("private tailnet readiness fixture", result.stdout + result.stderr)

    def test_tailnet_connection_readiness_retries_are_bounded(self):
        self.tailnet_mocks(failure="mirror-pull-once", readiness_failures={2: 7, 3: 7, 4: 7})
        result = self.run_helper("mirror", tailnet=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(self.calls_for("curl")), 4)
        self.assertIn("phase=authenticated-pull\n", self.public_status)
        self.assertIn("category=transport-failed\n", self.public_status)
        self.assertFalse((self.root / "summary").exists())
        self.assertNotIn("private tailnet readiness fixture", result.stdout + result.stderr + self.public_status)

    def test_tailnet_tls_error_stops_without_retrying(self):
        self.tailnet_mocks(readiness_failures={1: 60})
        result = self.run_helper("mirror", tailnet=True)
        self.assertEqual(result.returncode, 60)
        self.assertEqual(len(self.calls_for("curl")), 1)
        self.assertEqual(self.calls_for("aws"), [])

    def test_tailnet_mode_rejects_another_workflow(self):
        self.tailnet_mocks()
        self.env["GITHUB_WORKFLOW_REF"] = "Stuhlmuller/homelab/.github/workflows/unrelated.yml@refs/heads/main"
        self.assertNotEqual(self.run_helper("mirror", tailnet=True).returncode, 0)
        self.assertEqual(self.calls_for("aws"), [])

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

    def test_publisher_uses_private_traefik_transport(self):
        self.transport_mocks()
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        forwards = [args for args in self.calls_for("kubectl") if "port-forward" in args]
        self.assertEqual(len(forwards), 1)
        self.assertIn("--namespace", forwards[0])
        self.assertEqual(forwards[0][forwards[0].index("--namespace") + 1], "traefik")
        self.assertIn("service/traefik-private", forwards[0])
        self.assertEqual(forwards[0][forwards[0].index("--address") + 1], "127.0.0.1")
        self.assertIn("443:443", forwards[0])
        self.assertNotIn("istio-ingressgateway", forwards[0])
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
        canary_group = "harbor-mirror-image-updater-canary-production"
        ordinary_group = "harbor-mirror-production"
        self.assertEqual(mirror["concurrency"], {
            "group": "${{ inputs.image_scope == 'image-updater-canary' && "
                     f"'{canary_group}' || '{ordinary_group}' }}}}",
            "cancel-in-progress": False,
        })
        for name in ("nofx-images.yml", "harbor-core-images.yml"):
            jobs = workflow(name)["jobs"]
            private = [job["concurrency"]["group"] for job in jobs.values() if "concurrency" in job]
            self.assertIn("harbor-packages-production", private)
            self.assertTrue({canary_group, ordinary_group}.isdisjoint(private))


class TailnetMirrorWorkflow(unittest.TestCase):
    def test_production_only_tailnet_wiring(self):
        path = ROOT / ".github/workflows/harbor-mirror.yml"
        workflow = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(path)], text=True))
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        job = workflow["jobs"]["mirror"]
        self.assertEqual(job["environment"]["name"], "homelab-production")
        steps = {step["name"]: step for step in job["steps"]}
        join = steps["Join Production Tailnet"]
        self.assertEqual(join["env"], {"TAILSCALE_AUTH_KEY": "${{ secrets.TAILSCALE_AUTH_KEY }}"})
        self.assertEqual(join["run"].count("--accept-routes"), 1)
        self.assertIn("--accept-routes=false --accept-dns=true", join["run"])
        self.assertIn('--auth-key=file:/dev/stdin', join["run"])
        self.assertIn('.Self.Tags == ["tag:homelab-ci-apply"]', join["run"])
        self.assertEqual(steps["Leave Production Tailnet"]["if"], "always() && steps.join.outcome != 'skipped'")
        self.assertNotIn("OCTELIUM", path.read_text())
        copy = steps["Copy And Verify Fixed Public Digests"]
        for line in copy["run"].splitlines():
            if "bash scripts/ci/harbor-publish.sh mirror" in line:
                self.assertTrue(line.endswith(" --tailscale"))

    def test_native_enrollment_and_cleanup_without_services(self):
        workflow = json.loads(subprocess.check_output([
            "yq", "-o=json", ".", str(ROOT / ".github/workflows/harbor-mirror.yml"),
        ], text=True))
        steps = {s["name"]: s for s in workflow["jobs"]["mirror"]["steps"]}
        phases = ["Verify Current Main Commit Before Credentials", "Install Verified Tailscale Client",
                  "Join Production Tailnet", "Configure AWS Credentials", "Copy And Verify Fixed Public Digests",
                  "Leave Production Tailnet"]
        self.assertEqual([name for name in steps if name in phases], phases)
        for name in phases[1:-1]:
            self.assertNotIn("if", steps[name])  # GitHub skips these steps after failure.
        self.assertNotIn("env", steps["Leave Production Tailnet"])

        # Intercept every privileged command. Only the fake daemon creates a local socket.
        for failure in ("", "enroll", "wrong-tag", "crash", "logout", "stop", "cleanup"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir="/tmp") as temporary:
                root = Path(temporary)
                state = root / "tailscale-state"
                state.mkdir()
                sudo = root / "sudo"
                sudo.write_text(textwrap.dedent("""\
                    #!/usr/bin/env python3
                    import json, os, pathlib, shutil, socket, sys
                    root = pathlib.Path(os.environ["RUNNER_TEMP"])
                    state = root / "tailscale-state"
                    args = sys.argv[1:]
                    if args[:2] == ["timeout", "20"]:
                        args = args[2:]
                    name, arguments = pathlib.Path(args[0]).name, args[1:]
                    assert "TAILSCALE_AUTH_KEY" not in os.environ
                    assert all("inert-wrapped-fixture" not in v for v in os.environ.values())
                    with (root / "calls").open("a") as log:
                        print(json.dumps([name, *arguments]), file=log)
                    failure = os.environ["FAIL_AT"]
                    if name == "systemd-run":
                        sock = socket.socket(socket.AF_UNIX)
                        sock.bind(str(state / "tailscaled.sock"))
                    elif name == "tailscale" and "up" in arguments:
                        assert sys.stdin.read() == "inert-wrapped-fixture"
                        print("private-fixture-diagnostic", file=sys.stderr)
                        sys.exit(failure == "enroll")
                    elif name == "tailscale" and "status" in arguments:
                        tag = "other" if failure == "wrong-tag" else "homelab-ci-apply"
                        print(json.dumps({"BackendState":"Running", "Self":{"Tags":["tag:"+tag]}}))
                    elif name == "tailscale" and "logout" in arguments:
                        sys.exit(failure == "logout")
                    elif name == "systemctl" and arguments == ["stop", "harbor-mirror-tailscaled"]:
                        sys.exit(failure in ("stop", "crash"))
                    elif name == "tailscaled" and arguments == ["--cleanup"]:
                        sys.exit(failure == "cleanup")
                    elif name == "rm" and arguments == ["-rf", "--", str(state)]:
                        shutil.rmtree(state)
                    else:
                        sys.exit("unexpected invocation")
                    """))
                sudo.chmod(0o700)
                env = {"PATH": str(root) + os.pathsep + os.environ["PATH"], "RUNNER_TEMP": str(root),
                       "GITHUB_RUN_ID": "11", "GITHUB_RUN_ATTEMPT": "2", "FAIL_AT": failure,
                       "key": "inherited-export", "SHELLOPTS": "allexport"}
                fixture_value = "inert-wrapped-fixture"
                def execute(name, extra):
                    result = subprocess.run(["bash", "-c", steps[name]["run"]], env=env | extra,
                                            capture_output=True, text=True, timeout=10)
                    for private in (fixture_value, "private-fixture-diagnostic"):
                        self.assertNotIn(private, result.stdout + result.stderr)
                    return result.returncode
                joined = execute("Join Production Tailnet", {"TAILSCALE_AUTH_KEY": fixture_value})
                self.assertEqual(joined == 0, failure not in ("enroll", "wrong-tag"))
                if failure == "crash":
                    (state / "tailscaled.sock").unlink()
                left = execute("Leave Production Tailnet", {})
                self.assertEqual(left == 0, failure not in ("logout", "stop", "cleanup", "crash"))
                calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
                self.assertEqual(calls[1], ["tailscale", "--socket=" + str(state / "tailscaled.sock"), "up",
                    "--auth-key=file:/dev/stdin", "--hostname=harbor-mirror-11-2", "--accept-routes=false",
                    "--accept-dns=true", "--timeout=2m"])
                self.assertEqual([c[0] for c in calls[-3:]], ["systemctl", "tailscaled", "rm"])
                self.assertEqual(any("logout" in c for c in calls), failure != "crash")
                self.assertFalse(state.exists())


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


class CordiumPublicationSource(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cordium-publication-source-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.main = root / "main"
        self.main.mkdir()
        self.checkout = root / "checkout"
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
        self.git(self.main, "init", "--initial-branch=main")
        self.commit("flake.lock", "pinned source")
        self.sha = self.git(self.main, "rev-parse", "HEAD").strip()
        self.git(root, "clone", "--depth=1", self.main.as_uri(), str(self.checkout))
        self.git(self.checkout, "config", f"url.{self.main.as_uri()}.insteadOf",
                 "https://github.com/Stuhlmuller/homelab.git")
        self.env.update(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="Stuhlmuller/homelab",
                        GITHUB_REF="refs/heads/main", GITHUB_SHA=self.sha,
                        EXPECTED_SHA=self.sha, GITHUB_EVENT_NAME="workflow_dispatch",
                        GITHUB_WORKFLOW_REF="Stuhlmuller/homelab/.github/workflows/"
                                            "cordium-runner-publish.yml@refs/heads/main")

    def git(self, cwd, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "commit.gpgsign=false", *args], cwd=cwd, env=self.env, stderr=subprocess.PIPE, text=True,
        )

    def commit(self, path, contents):
        target = self.main / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        self.git(self.main, "add", "--", path)
        self.git(self.main, "commit", "-m", "update " + path)

    def verify(self):
        return subprocess.run(["bash", str(ROOT / "scripts/ci/cordium-publication-source.sh")],
                              cwd=self.checkout, env=self.env, capture_output=True, text=True, timeout=10)

    def test_same_commit_and_prose_only_descendant_keep_original_checkout(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.commit("docs/guide.md", "updated prose")
        self.commit("openwiki/runbooks/guide.md", "updated runbook")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD").strip(), self.sha)

    def test_publication_inputs_and_non_prose_docs_fail_closed(self):
        self.commit("docs/example.yaml", "modified configuration")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("publication inputs changed", result.stderr)
        self.git(self.main, "reset", "--hard", self.sha)
        self.commit("flake.lock", "different inputs")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("publication inputs changed", result.stderr)

    def test_rewritten_main_and_wrong_dispatch_are_rejected(self):
        self.git(self.main, "checkout", "--orphan", "rewritten")
        self.commit("README.md", "new branch")
        self.git(self.main, "branch", "-M", "main")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no longer an ancestor", result.stderr)
        self.env["EXPECTED_SHA"] = "0" * 40
        self.assertIn("Invalid Cordium publication dispatch context", self.verify().stderr)


if __name__ == "__main__":
    unittest.main()
