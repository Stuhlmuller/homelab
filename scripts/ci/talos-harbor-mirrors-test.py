#!/usr/bin/env python3
"""Check the fixed Talos mirror rollout without credentials or live mutations."""
import contextlib
import copy
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rollout", ROOT / "scripts/talos-harbor-mirrors.py")
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)
SHA = "a" * 40
PRIOR_SHA = "b" * 40
MANIFEST = '{"schemaVersion":2}'
DIGEST = hashlib.sha256(MANIFEST.encode()).hexdigest()
MIRRORS = {"docker.io": {"endpoints": ["https://harbor.stinkyboi.com/v2/mirror/docker.io"],
                         "overridePath": True, "skipFallback": True}}
ORIGINAL = [{"version": "v1alpha1", "machine": {"type": "worker"},
             "cluster": {"secret": "PrivateSecret-do-not-log", "controlPlane": {"endpoint": "https://10.1.0.199:6443"}}},
            {"apiVersion": "v1alpha1", "kind": "UserVolumeConfig", "name": "keep-this-volume"}]


def resource_stream(current, *, persistent=True, version=1, mismatch=False):
    resources = []
    for identity in ("v1alpha1", "persistent") if persistent else ("v1alpha1",):
        value = copy.deepcopy(current)
        if identity == "persistent" and mismatch:
            value[1]["name"] = "pending-volume-change"
        resources.append(json.dumps({"metadata": {
            "id": identity, "namespace": "config", "phase": "running",
            "type": "MachineConfigs.config.talos.dev", "version": version,
        }, "spec": json.dumps(value)}))
    return "\n".join(resources)


def patch_operations(test, command):
    test.assertEqual(command[4], "--patch")
    value = command[5]
    if value == "[]":
        return []
    test.assertTrue(value.startswith("@"))
    path = Path(value[1:])
    test.assertEqual(path.stat().st_mode & 0o777, 0o600)
    test.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
    return json.loads(path.read_text())


class RolloutTest(unittest.TestCase):
    def test_private_registry_preflight_rejects_tls_redirects_and_dashboard_exposure(self):
        for failure in (None, "tls", "dashboard", "service"):
            with self.subTest(failure=failure):
                service = {"spec": {"type": "LoadBalancer" if failure == "service" else "ClusterIP",
                           "clusterIP": "10.96.0.50", "ports": [{"port": 443, "targetPort": 9443}],
                           "selector": {"app.kubernetes.io/name": "traefik"}}}

                def run(*command, binary=False):
                    if command[0] == "kubectl":
                        return json.dumps(service)
                    self.assertEqual(command[0], "curl")
                    self.assertNotIn("--insecure", command)
                    self.assertNotIn("--doh-url", command)
                    self.assertIn("harbor.stinkyboi.com:443:127.0.0.1:50443", command)
                    if command[-1].endswith("/v2/"):
                        return 'HTTP/2 302\n' if failure == "tls" else 'HTTP/2 401\nwww-authenticate: Bearer realm="https://harbor.stinkyboi.com/service/token",service="harbor-registry"\n'
                    if "/service/token?" in command[-1]:
                        return '{"token":"test"}'
                    return "200" if failure == "dashboard" else "404"

                with patch.object(rollout, "run", run), patch.object(rollout.subprocess, "Popen") as process, \
                        patch.object(rollout.socket, "socket") as listener, \
                        patch.object(rollout.socket, "create_connection"):
                    listener.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 50443)
                    process.return_value.poll.return_value = None
                    if failure:
                        with self.assertRaises(RuntimeError):
                            rollout.verify_registry_route()
                    else:
                        rollout.verify_registry_route()
                    if failure == "service":
                        process.assert_not_called()
                    else:
                        process.return_value.terminate.assert_called_once()
                        process.return_value.wait.assert_called_once_with(timeout=5)

    def test_registry_hosts_preserve_unrelated_entries_and_refuse_conflicts(self):
        declaration = [{"ip": "10.96.0.50", "aliases": ["harbor.stinkyboi.com"]}]
        other = {"ip": "10.1.0.2", "aliases": ["nas.example.test"]}
        shared = {"ip": "10.96.0.50", "aliases": ["harbor.stinkyboi.com", "other.example.test"]}
        desired = [other, {"ip": "10.96.0.50", "aliases": ["other.example.test"]}, *declaration]
        self.assertEqual(rollout.registry_hosts([other, shared], declaration, False), desired)
        self.assertEqual(rollout.registry_hosts(desired, declaration, False), desired)
        self.assertEqual(rollout.registry_hosts(desired, declaration, True), desired[:-1])
        with self.assertRaisesRegex(RuntimeError, "Conflicting"):
            rollout.registry_hosts([{"ip": "10.1.0.10", "aliases": ["harbor.stinkyboi.com"]}], declaration, False)
        candidate = copy.deepcopy(ORIGINAL)
        candidate[0]["machine"]["network"] = {"extraHostEntries": declaration}
        rollout.hosts_only(ORIGINAL, candidate, declaration)
        candidate[0]["machine"]["registries"] = {"mirrors": MIRRORS}
        with self.assertRaisesRegex(RuntimeError, "outside"):
            rollout.hosts_only(ORIGINAL, candidate, declaration)

    def test_hosts_only_apply_and_rollback_never_change_mirror_configuration(self):
        for execute, rollback in ((False, False), (True, False), (True, True)):
            with self.subTest(execute=execute, rollback=rollback), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / ".talos/patches").mkdir(parents=True)
                (root / ".talos/talosconfig").touch()
                declaration = [{"ip": "10.96.0.50", "aliases": ["harbor.stinkyboi.com"]}]
                (root / ".talos/patches/harbor-registry-host.yaml").write_text(json.dumps(
                    {"machine": {"network": {"extraHostEntries": declaration}}}))
                current = copy.deepcopy(ORIGINAL)
                current[0]["machine"]["registries"] = {"mirrors": MIRRORS}
                other = {"ip": "10.1.0.2", "aliases": ["nas.example.test"]}
                current[0]["machine"]["network"] = {"extraHostEntries": [other] + (declaration if rollback else [])}
                calls = []

                def run(*command, binary=False):
                    nonlocal current
                    calls.append(command)
                    if command == ("talosctl", "version", "--client", "--short"):
                        return "Client:\nTalos v1.11.3\n"
                    if command[-4:] == ("get", "machineconfig", "-o", "json"):
                        return resource_stream(current)
                    if command[:3] == ("talosctl", "machineconfig", "patch"):
                        value = json.loads(Path(command[3]).read_text())
                        for operation in patch_operations(self, command):
                            self.assertEqual(operation["path"], "/machine/network/extraHostEntries")
                            value[0]["machine"]["network"]["extraHostEntries"] = operation["value"]
                        Path(command[-1]).write_text(json.dumps(value))
                    elif "apply-config" in command:
                        self.assertIn("no-reboot", command)
                        current = json.loads(Path(command[-1]).read_text())
                    elif "image" in command:
                        self.assertEqual(command[-1], "harbor.stinkyboi.com/mirror/registry.k8s.io/pause:3.10")
                    elif command[:2] not in (("talosctl", "validate"), ("kubectl", "wait")):
                        raise AssertionError(command)
                    return ""

                def documents(path):
                    value = json.loads(path.read_text())
                    return value if isinstance(value, list) else [value]

                with patch.object(rollout, "ROOT", root), patch.object(rollout, "run", run), \
                        patch.object(rollout, "documents", documents), patch.object(rollout, "verify_main"), \
                        patch.object(rollout, "verify_copies") as copies, \
                        patch.object(rollout, "verify_registry_route") as route, \
                        patch.object(rollout, "ready", return_value="stable"), \
                        patch.object(rollout, "talos_boot", return_value="stable"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rollout.reconcile("10.1.0.202", execute, SHA, rollback, registry_host_only=True)
                copies.assert_not_called()
                self.assertEqual(route.call_count, int(execute and not rollback))
                self.assertEqual(current[0]["machine"]["registries"], {"mirrors": MIRRORS})
                self.assertEqual(current[0]["machine"]["network"]["extraHostEntries"],
                                 [other] + (declaration if execute and not rollback else []))
                self.assertEqual(any("image" in command for command in calls), execute and not rollback)

    def test_registry_auth_is_private_scoped_and_rollback_removes_only_owned_auth(self):
        password = "fixture"
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "repo"
            private = base / "private"
            (root / "scripts/config").mkdir(parents=True)
            (root / ".talos/patches").mkdir(parents=True)
            (root / ".talos/talosconfig").touch()
            private.mkdir()
            private.chmod(0o700)
            credential = private / "mirror-auth.json"
            credential.write_text(json.dumps({"username": rollout.REGISTRY_USERNAME, "password": password}))
            credential.chmod(0o600)
            auth = {"username": rollout.REGISTRY_USERNAME, "password": password}
            self.assertEqual(rollout.read_registry_auth(credential), auth)
            credential.chmod(0o640)
            with self.assertRaises(RuntimeError):
                rollout.read_registry_auth(credential)
            credential.chmod(0o600)
            link = private / "link"
            os.symlink(credential, link)
            with self.assertRaises(RuntimeError):
                rollout.read_registry_auth(link)

            other_config = {"registry.example": {"auth": {"username": "other", "password": "keep"}},
                            rollout.REGISTRY_HOST: {"tls": {"insecureSkipVerify": False}}}
            configured = rollout.registry_auth_config({"config": other_config}, auth, False)
            self.assertEqual(configured, {
                "registry.example": {"auth": {"username": "other", "password": "keep"}},
                rollout.REGISTRY_HOST: {"tls": {"insecureSkipVerify": False}, "auth": auth},
            })
            self.assertEqual(rollout.registry_auth_config({"config": configured}, None, True), other_config)
            self.assertEqual(rollout.owned_registry_auth({"config": configured}), auth)
            self.assertIsNone(rollout.owned_registry_auth({"config": other_config}))
            self.assertIs(rollout.registry_auth_config({"config": {
                rollout.REGISTRY_HOST: {"auth": {"username": "unrelated", "password": "keep"}}}}, None, True),
                          rollout._UNCHANGED)
            with self.assertRaisesRegex(RuntimeError, "unrelated"):
                rollout.registry_auth_config({"config": {
                    rollout.REGISTRY_HOST: {"auth": {"username": "unrelated", "password": "keep"}}}}, auth, False)

            (root / ".talos/patches/harbor-mirrors.yaml").write_text(json.dumps(
                {"machine": {"registries": {"mirrors": MIRRORS}}}))
            rollback_mirrors = {"docker.io": {"endpoints": ["https://registry-1.docker.io/v2"],
                                               "overridePath": True, "skipFallback": False}}
            (root / ".talos/patches/harbor-mirrors-rollback.yaml").write_text(json.dumps(
                {"machine": {"registries": {"mirrors": rollback_mirrors}}}))
            current = copy.deepcopy(ORIGINAL)
            current[0]["machine"]["registries"] = {"mirrors": {"old.example": {}}, "config": copy.deepcopy(other_config)}
            calls, private_patches, operations_seen = [], [], []

            def run(*command, binary=False):
                nonlocal current
                calls.append(command)
                self.assertNotIn(password, " ".join(command))
                if command == ("talosctl", "version", "--client", "--short"):
                    return "Client:\nTalos v1.11.3\n"
                if command[-4:] == ("get", "machineconfig", "-o", "json"):
                    return resource_stream(current)
                if command == ("talosctl", "--talosconfig", str((root / ".talos/talosconfig").resolve()),
                               "--endpoints", "10.1.0.199", "--nodes", "10.1.0.202", "read",
                               "/proc/sys/kernel/random/boot_id"):
                    return "12345678-0000-0000-0000-000000000000"
                if command[0] == "yq":
                    value = json.loads(Path(command[-1]).read_text())
                    return json.dumps(value if isinstance(value, list) else [value])
                if command[:3] == ("talosctl", "machineconfig", "patch"):
                    value = json.loads(Path(command[3]).read_text())
                    operations = patch_operations(self, command)
                    if operations:
                        private_patches.append(Path(command[5][1:]))
                        operations_seen.append(copy.deepcopy(operations))
                    for operation in operations:
                        if operation["path"] == "/machine/registries/mirrors":
                            value[0]["machine"].setdefault("registries", {})["mirrors"] = operation["value"]
                        elif operation["path"] == "/machine/registries/config":
                            value[0]["machine"].setdefault("registries", {})["config"] = operation["value"]
                        else:
                            raise AssertionError(operation)
                    Path(command[-1]).write_text(json.dumps(value))
                    return ""
                if command[:2] == ("kubectl", "get"):
                    return json.dumps({"metadata": {"name": "zimaboard-2"}, "status": {
                        "addresses": [{"type": "InternalIP", "address": "10.1.0.202"}],
                        "conditions": [{"type": "Ready", "status": "True"}], "nodeInfo": {"bootID": "stable"}}})
                if command[:2] == ("talosctl", "validate"):
                    return ""
                raise AssertionError(command)

            output = io.StringIO()
            with patch.object(rollout, "ROOT", root), patch.object(rollout, "run", run), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                rollout.reconcile("10.1.0.202", False, SHA, False, registry_auth_file=credential)
                current[0]["machine"]["registries"]["config"] = copy.deepcopy(configured)
                rollout.reconcile("10.1.0.202", False, SHA, True)
                with self.assertRaisesRegex(RuntimeError, "cannot be combined"):
                    rollout.reconcile("10.1.0.202", False, SHA, False, registry_host_only=True,
                                      registry_auth_file=credential)
            self.assertNotIn(password, output.getvalue())
            self.assertEqual(len(private_patches), 2)
            self.assertTrue(all(not path.exists() for path in private_patches))
            self.assertEqual(operations_seen[0][-1], {
                "op": "add", "path": "/machine/registries/config", "value": configured,
            })
            self.assertEqual(operations_seen[1][-1], {
                "op": "add", "path": "/machine/registries/config", "value": other_config,
            })

    def test_authenticated_receipt_uses_a_private_header_file(self):
        password = "fixture"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "scripts/config").mkdir(parents=True)
            (root / "scripts/config/harbor-images.json").write_text(json.dumps(
                {"images": [{"source": f"docker.io/library/alpine:3.22@sha256:{DIGEST}"}]}))
            calls, headers = [], []

            def run(*command, binary=False):
                calls.append(command)
                self.assertNotIn(password, " ".join(command))
                self.assertNotIn("Authorization: Basic", " ".join(command))
                if command[0] == "gh":
                    return json.dumps([{"workflow_runs": [{"head_sha": SHA, "head_branch": "main",
                        "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
                        "display_title": f"Mirror all @ {SHA}"}]}])
                if command[:2] == ("git", "merge-base"):
                    return ""
                if command[:2] == ("git", "show"):
                    return b"same"
                if command[0] == "curl":
                    if "/service/token?" in command[-1]:
                        path = Path(command[command.index("--header") + 1].removeprefix("@"))
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                        self.assertEqual(base64.b64decode(path.read_text().split()[-1]),
                                         f"{rollout.REGISTRY_USERNAME}:{password}".encode())
                        headers.append(path)
                        return json.dumps({"token": "test.anonymous-token"})
                    path = Path(command[command.index("--header") + 1].removeprefix("@"))
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertIn("Authorization: Bearer test.anonymous-token", path.read_text())
                    headers.append(path)
                    self.assertTrue(binary)
                    return MANIFEST.encode()
                raise AssertionError(command)

            with patch.object(rollout, "ROOT", root), patch.object(rollout, "run", run):
                rollout.verify_copies(SHA, {"username": rollout.REGISTRY_USERNAME, "password": password})
            self.assertTrue(headers)
            self.assertTrue(all(not path.exists() for path in headers))

    def test_dry_run_execution_and_fail_closed_gates(self):
        for scenario in ("dry", "apply", "rollback", "unready", "wrong-client", "dirty", "workflow",
                         "digest", "scope", "multidoc", "race", "reboot", "readback", "rollback-reboot", "custom-config", "missing-config", "pull-failure", "token-injection",
                         "prior-success", "later-page-success", "bundle-changed", "non-ancestor", "missing-history", "missing-blob",
                         "wrong-branch", "wrong-event", "wrong-status", "wrong-conclusion", "short-sha",
                         "fleet-only", "bazarr-only", "traefik-only", "untitled", "wrong-title-sha",
                         "fresh-boot", "pending-config", "try-without-persistent", "config-read-error",
                         "duplicate-config", "missing-active", "missing-reader-auth", "existing-reader-auth"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                root = base / "repo"
                (root / "scripts/config").mkdir(parents=True)
                (root / ".talos/patches").mkdir(parents=True)
                private = base / "private"
                private.mkdir()
                private.chmod(0o700)
                credential = private / "mirror-auth.json"
                credential.write_text(json.dumps({"username": rollout.REGISTRY_USERNAME,
                                                  "password": "fixture-reader"}))
                credential.chmod(0o600)
                registry_auth_file = credential if scenario in (
                    "apply", "reboot", "readback", "custom-config", "pull-failure",
                    "prior-success", "later-page-success", "fresh-boot") else None
                talosconfig = root / ("private-talosconfig" if scenario == "custom-config" else ".talos/talosconfig")
                if scenario != "missing-config":
                    talosconfig.write_text("private test fixture")
                config_argument = talosconfig if scenario == "custom-config" else None
                (root / "scripts/config/harbor-images.json").write_text(json.dumps(
                    {"images": [{"source": f"docker.io/library/alpine:3.22@sha256:{DIGEST}"}]}))
                wanted = copy.deepcopy(MIRRORS)
                if scenario.startswith("rollback"):
                    wanted["docker.io"].update(endpoints=["https://registry-1.docker.io/v2"], skipFallback=False)
                for name in ("harbor-mirrors.yaml", "harbor-mirrors-rollback.yaml"):
                    (root / ".talos/patches" / name).write_text(json.dumps({"machine": {"registries": {"mirrors": wanted}}}))
                current = copy.deepcopy(ORIGINAL)
                if scenario == "existing-reader-auth":
                    current[0]["machine"]["registries"] = {"config": {
                        rollout.REGISTRY_HOST: {"auth": {"username": rollout.REGISTRY_USERNAME,
                                                          "password": "test"}}}}
                calls, captures = [], []
                applied = False

                def run(*command, binary=False):
                    nonlocal current, applied
                    calls.append(command)
                    if command[0] == "talosctl" and any(action in command for action in ("get", "read", "apply-config", "image")):
                        self.assertIn("--talosconfig", command)
                        self.assertEqual(command[command.index("--talosconfig") + 1], str(talosconfig.resolve()))
                    if command[:2] == ("git", "status"):
                        return " M unsafe\n" if scenario == "dirty" else ""
                    if command[:2] in (("git", "rev-parse"), ("git", "ls-remote")):
                        return SHA + "\n"
                    if command[:2] == ("git", "merge-base"):
                        self.assertEqual(command[2], "--is-ancestor")
                        self.assertEqual(command[-1], SHA)
                        if scenario in ("non-ancestor", "missing-history") or command[-2] == "c" * 40:
                            raise subprocess.CalledProcessError(1 if scenario == "non-ancestor" else 128, command)
                        return ""
                    if command[:2] == ("git", "show"):
                        self.assertTrue(binary)
                        revision, path = command[2].split(":", 1)
                        if revision == PRIOR_SHA and path == "flake.lock":
                            if scenario == "missing-blob":
                                raise subprocess.CalledProcessError(128, command)
                            if scenario == "bundle-changed":
                                return b"changed lockfile"
                        return path.encode()
                    if command[0] == "gh":
                        self.assertEqual(command[:4], ("gh", "api", "--paginate", "--slurp"))
                        self.assertEqual(command[-1], "repos/Stuhlmuller/homelab/actions/workflows/harbor-mirror.yml/runs"
                                         "?branch=main&event=workflow_dispatch&status=success&per_page=100")
                        item = {"head_sha": PRIOR_SHA if scenario in ("prior-success", "later-page-success", "bundle-changed", "non-ancestor", "missing-history", "missing-blob") else SHA,
                                "head_branch": "feature" if scenario == "wrong-branch" else "main",
                                "event": "push" if scenario == "wrong-event" else "workflow_dispatch",
                                "status": "in_progress" if scenario == "wrong-status" else "completed",
                                "conclusion": "failure" if scenario == "wrong-conclusion" else "success"}
                        if scenario == "short-sha":
                            item["head_sha"] = SHA[:7]
                        item["display_title"] = f"Mirror all @ {item['head_sha']}"
                        if scenario in ("fleet-only", "bazarr-only", "traefik-only"):
                            item["display_title"] = f"Mirror {scenario.removesuffix('-only')} @ {item['head_sha']}"
                        elif scenario == "untitled":
                            item.pop("display_title")
                        elif scenario == "wrong-title-sha":
                            item["display_title"] = f"Mirror all @ {PRIOR_SHA}"
                        if scenario == "later-page-success":
                            return json.dumps([{"workflow_runs": [{**item, "head_sha": "c" * 40, "display_title": f"Mirror all @ {'c' * 40}"}] * 100},
                                               {"workflow_runs": [item]}])
                        return json.dumps([{"workflow_runs": [] if scenario == "workflow" else [item]}])
                    if command[0] == "curl":
                        self.assertEqual(command[1], "--disable")
                        self.assertIn("--fail", command)
                        self.assertEqual(command[command.index("--max-time") + 1], "30")
                        self.assertEqual(command[command.index("--doh-url") + 1], "https://1.1.1.1/dns-query")
                        self.assertNotIn("--insecure", command)
                        self.assertNotIn("--location", command)
                        self.assertNotIn("test.anonymous-token", " ".join(command))
                        if "/service/token?" in command[-1]:
                            if scenario == "existing-reader-auth":
                                header = Path(command[command.index("--header") + 1].removeprefix("@"))
                                self.assertEqual(base64.b64decode(header.read_text().split()[-1]),
                                                 b"robot$mirror+pull:test")
                            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(command[-1]).query),
                                             {"service": ["harbor-registry"], "scope": ["repository:mirror/docker.io/library/alpine:pull"]})
                            return json.dumps({"token": "unsafe\r\nInjected: header" if scenario == "token-injection" else "test.anonymous-token"})
                        headers = Path(command[command.index("--header") + 1].removeprefix("@"))
                        self.assertEqual(headers.stat().st_mode & 0o777, 0o600)
                        self.assertEqual(headers.parent.stat().st_mode & 0o777, 0o700)
                        self.assertIn("Authorization: Bearer test.anonymous-token\n", headers.read_text())
                        self.assertIn("application/vnd.oci.image.index.v1+json", headers.read_text())
                        self.assertIn("application/vnd.docker.distribution.manifest.list.v2+json", headers.read_text())
                        self.assertIn(command[-1], (f"https://harbor.stinkyboi.com/v2/mirror/docker.io/library/alpine/manifests/{DIGEST}",
                                                   "https://harbor.stinkyboi.com/v2/mirror/docker.io/library/alpine/manifests/3.22"))
                        self.assertTrue(binary)
                        return b"wrong digest" if scenario == "digest" else MANIFEST.encode()
                    if command[:2] == ("kubectl", "get"):
                        return json.dumps({"metadata": {"name": "zimaboard-2"}, "status": {
                            "addresses": [{"type": "InternalIP", "address": "10.1.0.202"}],
                            "conditions": [{"type": "Ready", "status": "False" if scenario == "unready" else "True"}],
                            "nodeInfo": {"bootID": "different" if applied and scenario == "reboot" else "stable"}}})
                    if command[:2] == ("kubectl", "wait"):
                        return ""
                    if command[0] == "yq":
                        value = json.loads(Path(command[-1]).read_text())
                        return json.dumps(value if isinstance(value, list) else [value])
                    if command == ("talosctl", "version", "--client", "--short"):
                        return "Client:\nTalos v1.13.0\n" if scenario == "wrong-client" else "Client:\nTalos v1.11.3\n"
                    if "read" in command:
                        return "87654321-0000-0000-0000-000000000000" if applied and scenario == "rollback-reboot" else "12345678-0000-0000-0000-000000000000"
                    if command[-4:] == ("get", "machineconfig", "-o", "json"):
                        captures.append(command)
                        if scenario == "race" and len(captures) == 2:
                            current[0]["machine"]["unrelated"] = True
                        if scenario == "config-read-error":
                            raise RuntimeError("Configuration read failed")
                        result = resource_stream(
                            current, persistent=applied or scenario not in ("fresh-boot", "try-without-persistent"),
                            version=2 if scenario == "try-without-persistent" or applied else 1,
                            mismatch=scenario == "pending-config")
                        if scenario == "duplicate-config":
                            result += "\n" + result
                        if scenario == "missing-active":
                            result = result.splitlines()[1]
                        return result
                    if command[:3] == ("talosctl", "machineconfig", "patch"):
                        path = Path(command[3])
                        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                        value = json.loads(path.read_text())
                        operations = patch_operations(self, command)
                        if operations:
                            for operation in operations:
                                if operation["path"] == "/machine/registries":
                                    self.assertEqual(operation["value"], {})
                                    value[0]["machine"].setdefault("registries", {})
                                elif operation["path"] == "/machine/registries/mirrors":
                                    self.assertEqual(operation["value"], wanted)
                                    value[0]["machine"].setdefault("registries", {})["mirrors"] = operation["value"]
                                elif operation["path"] == "/machine/registries/config":
                                    value[0]["machine"].setdefault("registries", {})["config"] = operation["value"]
                                else:
                                    raise AssertionError(operation)
                            if scenario == "scope":
                                value[0]["cluster"]["secret"] = "changed"
                            if scenario == "multidoc":
                                value.pop()
                        Path(command[-1]).write_text(json.dumps(value))
                        return ""
                    if command[:2] == ("talosctl", "validate"):
                        self.assertEqual(command[-3:], ("--mode", "metal", "--strict"))
                        return ""
                    if "image" in command:
                        self.assertEqual(command[-5:], ("image", "pull", "--namespace", "system", "registry.k8s.io/pause:3.10"))
                        self.assertTrue(applied)
                        self.assertEqual(len(captures), 3, "Pull follows active/persistent configuration readback")
                        self.assertEqual(calls[-2][:2], ("kubectl", "get"), "Pull follows node health check")
                        if scenario == "pull-failure":
                            raise RuntimeError("Native image pull failed")
                        return ""
                    if "apply-config" in command:
                        self.assertIn("no-reboot", command)
                        applied = True
                        if scenario != "readback":
                            current = json.loads(Path(command[-1]).read_text())
                        return ""
                    raise AssertionError(f"Unexpected command: {command[0]}")

                output = io.StringIO()
                with patch.object(rollout, "ROOT", root), patch.object(rollout, "run", run), \
                        contextlib.redirect_stdout(output):
                    if scenario in ("dry", "apply", "rollback", "custom-config", "prior-success", "later-page-success", "fresh-boot", "existing-reader-auth"):
                        rollout.reconcile("10.1.0.202", scenario != "dry", SHA, scenario.startswith("rollback"), config_argument,
                                          registry_auth_file=registry_auth_file)
                    else:
                        with self.assertRaises(RuntimeError):
                            rollout.reconcile("10.1.0.202", True, SHA, scenario.startswith("rollback"), config_argument,
                                              registry_auth_file=registry_auth_file)
                self.assertNotIn("PrivateSecret", output.getvalue())
                if scenario in ("prior-success", "later-page-success"):
                    self.assertEqual({call[2].split(":", 1)[1] for call in calls if call[:2] == ("git", "show")},
                                     {"scripts/config/harbor-images.json", ".github/workflows/harbor-mirror.yml",
                                      "scripts/ci/harbor-publish.sh", "scripts/ci/install-kubeconfig.sh", "flake.nix", "flake.lock"})
                if scenario in ("bundle-changed", "non-ancestor", "missing-history", "missing-blob", "wrong-branch",
                                "wrong-event", "wrong-status", "wrong-conclusion", "short-sha",
                                "fleet-only", "bazarr-only", "traefik-only", "untitled", "wrong-title-sha"):
                    self.assertFalse(any(call[0] == "curl" for call in calls))
                if scenario in ("fleet-only", "bazarr-only", "traefik-only", "untitled", "wrong-title-sha"):
                    self.assertFalse(any(call[:2] == ("git", "merge-base") for call in calls))
                if scenario == "missing-config":
                    self.assertEqual(calls, [])
                self.assertEqual(applied, scenario in ("apply", "rollback", "reboot", "readback", "rollback-reboot", "custom-config", "pull-failure", "prior-success", "later-page-success", "fresh-boot", "existing-reader-auth"))
                self.assertEqual(any("image" in call for call in calls), scenario in ("apply", "custom-config", "pull-failure", "prior-success", "later-page-success", "fresh-boot", "existing-reader-auth"))
                if scenario == "missing-reader-auth":
                    self.assertFalse(any(call[0] in ("gh", "curl") for call in calls))
                    self.assertFalse(any(call[:3] == ("talosctl", "machineconfig", "patch")
                                         and call[call.index("--patch") + 1].startswith("@")
                                         for call in calls))
                if scenario in ("dry", "rollback", "rollback-reboot"):
                    self.assertFalse(any(call[0] in ("gh", "curl") for call in calls))
                if scenario.startswith("rollback"):
                    self.assertFalse(any(call[0] == "kubectl" for call in calls))
                self.assertFalse(any("patch" in call and "machineconfig" not in call for call in calls))
                for call in calls:
                    if call[0] == "curl" and "--header" in call:
                        self.assertFalse(Path(call[call.index("--header") + 1].removeprefix("@")).exists(),
                                         "Private token header must be removed")
                    if call[:3] == ("talosctl", "machineconfig", "patch"):
                        self.assertFalse(Path(call[-1]).exists(), "Private temporary config must be removed")
                        if call[5].startswith("@"):
                            self.assertFalse(Path(call[5][1:]).exists(), "Private JSON patch must be removed")


if __name__ == "__main__":
    unittest.main()
