#!/usr/bin/env python3
"""Fail-closed checks for the Talos/Kubernetes maintenance decision boundary."""

import copy
import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
SCRIPT = ROOT / "scripts/platform-maintenance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("platform_maintenance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlatformMaintenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.config = json.loads(CONFIG.read_text())

    def setUp(self):
        self.machine_state_function = self.module.active_machine_state
        self.mirror_tag_function = self.module.verify_kubernetes_mirror_tags
        self.istio_target_function = self.module.verify_live_istio_target
        mirrors = {registry: {"endpoints": [
            f"https://harbor.stinkyboi.com/v2/mirror/{registry}"],
            "overridePath": True, "skipFallback": True}
            for registry in ("ghcr.io", "factory.talos.dev")}
        for name, kwargs in (
            ("active_machine_state", {"return_value": {"role": "worker", "disk": "/dev/sda",
                                                       "mirrors": mirrors}}),
            ("verify_kubernetes_mirror_routes", {}),
            ("verify_kubernetes_mirror_tags", {}),
            ("verify_live_istio_target", {}),
        ):
            replacement = patch.object(self.module, name, **kwargs)
            replacement.start()
            self.addCleanup(replacement.stop)

    def prerequisites(self, sha, config=None):
        config = config or self.config
        captured = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "placement": {"sourceSha": sha, "verified": True,
                          "canaryNode": config["canary"]["node"], "measured": True,
                          "isolatedTaint": config["canary"]["taint"]},
            "direct-recovery": {"sourceSha": sha, "verified": True,
                                "capturedAt": captured, "transport": "direct-lan-authenticated-talos",
                                "endpoint": "10.1.0.199:50000", "nodes": list(self.module.NODES),
                                "talosMtls": True},
            "off-node-etcd-backup": {"sourceSha": sha, "verified": True,
                                     "capturedAt": captured, "offNode": True,
                                     "offlineRestoreVerified": True,
                                     "snapshotSha256": "a" * 64, "objectVersionId": "version-1"},
            "artifact-publication": {"sourceSha": sha, "verified": True,
                                     "talosImages": {f"talos-{item['to']}": item["installerImage"]
                                                     for item in config["talosStages"]},
                                     "kubernetesImages": config["kubernetesStage"]["images"]},
        }

    def write_publication(self, directory, sha):
        for name, record in self.prerequisites(sha).items():
            path = Path(directory) / f"{name}.json"
            path.write_text(json.dumps(record))
            path.chmod(0o600)
        receipt = Path(directory) / "artifact-publication.json"
        return receipt

    def test_committed_ladder_is_valid_but_not_activated(self):
        self.module.validate_config(self.config)
        self.assertFalse(self.config["activationEnabled"])
        self.assertIsNone(self.config["canary"]["node"])
        for stage in self.config["talosStages"]:
            patch_file = ROOT / f'.talos/patches/talos-{stage["to"]}.yaml'
            self.assertEqual([line.strip().removeprefix("image: ")
                              for line in patch_file.read_text().splitlines()
                              if line.strip().startswith("image: ")],
                             [stage["installerImage"]])

    def test_rejects_unsupported_hops_order_and_image_substitution(self):
        for change in (
            lambda c: c["talosStages"][0].update(to="1.12.12"),
            lambda c: c["talosStages"][1].update(**{"from": "1.11.3"}),
            lambda c: c["istioStages"][0].update(to="1.29.9"),
            lambda c: c["kubernetesStage"].update(to="1.36.0"),
            lambda c: c["nodeOrder"].reverse(),
            lambda c: c["expectedStart"]["nodes"]["acer"].update(address="10.1.0.216"),
            lambda c: c.update(protectedTalosEndpoint="10.1.0.199"),
            lambda c: c["talosStages"][0].update(installerImage="ghcr.io/siderolabs/installer:v1.11.6"),
            lambda c: c["istioStages"][0]["images"].update(pilot="docker.io/istio/pilot:latest"),
        ):
            candidate = copy.deepcopy(self.config)
            change(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.module.validate_config(candidate)

    def test_exact_main_stage_and_recovery_receipts_are_required(self):
        sha = "a" * 40
        candidate = copy.deepcopy(self.config)
        candidate["activationEnabled"] = True
        candidate["canary"]["node"] = "zimaboard-0"
        receipts = self.prerequisites(sha, candidate)
        self.module.authorize_stage(candidate, "talos-1.11.6", sha, sha, receipts)
        for stage, expected, current, evidence in (
            ("talos-1.12.12", sha, sha, receipts),
            ("talos-1.11.6", sha, "b" * 40, receipts),
            ("talos-1.11.6", "b" * 40, sha, receipts),
            ("talos-1.11.6", sha, sha, {**receipts, "placement": {"sourceSha": sha, "verified": False}}),
            ("talos-1.11.6", sha, sha, {k: v for k, v in receipts.items() if k != "off-node-etcd-backup"}),
        ):
            with self.subTest(stage=stage, expected=expected, current=current), self.assertRaises(ValueError):
                self.module.authorize_stage(candidate, stage, expected, current, evidence)

    def test_unadmitted_canary_blocks_execution(self):
        sha = "a" * 40
        receipts = self.prerequisites(sha)
        with self.assertRaises(ValueError):
            self.module.authorize_stage(self.config, "talos-1.11.6", sha, sha, receipts)

    def test_later_stage_requires_verified_prior_receipt_from_its_own_reviewed_sha(self):
        sha = "a" * 40
        candidate = copy.deepcopy(self.config)
        candidate["activationEnabled"] = True
        candidate["canary"]["node"] = "zimaboard-0"
        receipts = self.prerequisites(sha, candidate)
        receipts["talos-1.11.6"] = {"sourceSha": "b" * 40, "verified": True}
        self.module.authorize_stage(candidate, "talos-1.12.12", sha, sha, receipts)
        receipts["talos-1.11.6"]["verified"] = False
        with self.assertRaises(ValueError):
            self.module.authorize_stage(candidate, "talos-1.12.12", sha, sha, receipts)

    def test_kubernetes_stage_requires_ladder_bound_istio_receipts(self):
        sha = "a" * 40
        candidate = copy.deepcopy(self.config)
        candidate["activationEnabled"] = True
        candidate["canary"]["node"] = "zimaboard-0"
        receipts = self.prerequisites(sha, candidate)
        for item in candidate["talosStages"]:
            receipts[f"talos-{item['to']}"] = {"sourceSha": sha, "verified": True}
        for item in candidate["istioStages"]:
            stage = f"istio-{item['to']}"
            receipts[stage] = {"sourceSha": "b" * 40, "verified": True,
                               "stage": stage, "pinSha256": self.module.PIN_SHA256,
                               "observedVersion": item["to"]}
        stage = "kubernetes-1.35.9"
        self.module.authorize_stage(candidate, stage, sha, sha, receipts)
        receipts["istio-1.29.9"]["pinSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Istio stage"):
            self.module.authorize_stage(candidate, stage, sha, sha, receipts)

    def test_retry_never_guesses_after_interruption_or_node_substitution(self):
        decide = self.module.node_action
        sha = "a" * 40
        stage = "talos-1.11.6"
        self.assertEqual(decide("zimaboard-0", "1.11.3", "1.11.6", "1.11.3", "boot", None,
                                sha, stage), "upgrade")
        with self.assertRaises(ValueError):
            decide("zimaboard-0", "1.11.3", "1.11.6", "1.11.3", None, None, sha, stage)
        complete = {"format": 1, "node": "zimaboard-0", "from": "1.11.3",
                    "to": "1.11.6", "sourceSha": sha, "stage": stage,
                    "pinSha256": self.module.PIN_SHA256,
                    "verified": True, "status": "verified", "evidence": {
                        "observedVersion": "1.11.6", "ready": True,
                        "clusterHealth": True, "bootID": "boot"}}
        self.assertEqual(decide("zimaboard-0", "1.11.3", "1.11.6", "1.11.6", "boot", complete,
                                sha, stage), "skip")
        self.assertEqual(decide("zimaboard-0", "1.11.3", "1.11.6", "1.11.6", "boot",
                                {**complete, "sourceSha": "b" * 40}, sha, stage), "skip")
        for observed, receipt in (
            ("1.11.6", None),
            ("1.11.3", {**complete, "verified": False}),
            ("1.11.4", None),
            ("1.11.6", {**complete, "node": "zimaboard-1"}),
            ("1.11.6", {**complete, "sourceSha": "invalid"}),
            ("1.11.6", {**complete, "pinSha256": "0" * 64}),
            ("1.11.6", {**complete, "stage": "talos-1.12.12"}),
            ("1.11.6", {**complete, "from": "9.9.9"}),
        ):
            with self.subTest(observed=observed, receipt=receipt), self.assertRaises(ValueError):
                decide("zimaboard-0", "1.11.3", "1.11.6", observed, "boot", receipt,
                       sha, stage)
        with self.assertRaises(ValueError):
            decide("zimaboard-0", "1.11.3", "1.11.6", "1.11.6", "new-boot", complete,
                   sha, stage)

    def test_read_only_commands_never_use_upgrade_dry_run(self):
        source = SCRIPT.read_text()
        self.assertNotIn("upgrade-k8s --dry-run", source)
        self.assertNotIn('"upgrade-k8s", "--dry-run"', source)
        self.assertNotIn('"upgrade", "--dry-run"', source)

    def test_inspection_records_exact_nodes_with_read_only_clients(self):
        nodes = []
        for name, node in self.config["expectedStart"]["nodes"].items():
            nodes.append({"metadata": {"name": name}, "status": {
                "addresses": [{"type": "InternalIP", "address": node["address"]}],
                "nodeInfo": {"kubeletVersion": "v1.34.11", "osImage": "Talos (v1.11.3)",
                             "bootID": "boot-id"},
                "conditions": [{"type": "Ready", "status": "True"}],
                "capacity": {"cpu": "4"}, "allocatable": {"cpu": "3"},
            }})
        commands = []
        extension_payload = ["[]"]

        def fake_run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["kubectl", "get", "nodes"]:
                return subprocess.CompletedProcess(command, 0, json.dumps({"items": nodes}), "")
            if command[0] == "talosctl" and command[-2:] == ["version", "--short"]:
                return subprocess.CompletedProcess(command, 0,
                                                   "Client:\nTalos v1.11.3\nServer:\nTalos v1.11.3\n", "")
            if command[0] == "talosctl" and command[-4:] == ["get", "extensionstatus", "-o", "json"]:
                return subprocess.CompletedProcess(command, 0, extension_payload[0], "")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            talosconfig = path / "talosconfig"
            talosconfig.write_text("fixture")
            talosconfig.chmod(0o600)
            with patch.object(self.module.subprocess, "run", side_effect=fake_run):
                receipt = self.module.read_only_inspection(self.config, talosconfig)
            self.assertEqual(set(receipt["nodes"]), set(self.config["nodeOrder"]))
            self.assertTrue(all(node["ready"] for node in receipt["nodes"].values()))
            self.assertEqual(len(commands), 9)
            output = path / "inspection.json"
            self.module.save_inspection(output, receipt)
            self.assertEqual(json.loads(output.read_text())["nodes"], receipt["nodes"])
            with self.assertRaises(FileExistsError):
                self.module.save_inspection(output, receipt)
            nodes[0]["status"]["addresses"][0]["address"] = "10.1.0.216"
            with patch.object(self.module.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(ValueError):
                    self.module.read_only_inspection(self.config, talosconfig)
            nodes[0]["status"]["addresses"][0]["address"] = self.config["expectedStart"]["nodes"][nodes[0]["metadata"]["name"]]["address"]
            extension_payload[0] = '[{"metadata":{"id":"extra"}}]'
            with patch.object(self.module.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(ValueError):
                    self.module.read_only_inspection(self.config, talosconfig)

    def test_private_machine_configs_are_strictly_rendered_without_live_mutation(self):
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            self.assertTrue(kwargs["check"])
            if command[1:3] == ["machineconfig", "patch"]:
                return subprocess.CompletedProcess(command, 0, "version: v1alpha1\n", "")
            if command[1] == "validate":
                self.assertEqual(command[-3:], ["--mode", "metal", "--strict"])
                return subprocess.CompletedProcess(command, 0, "valid\n", "")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "controlplane.yaml"
            worker = Path(directory) / "worker.yaml"
            for path in (control, worker):
                path.write_text("version: v1alpha1\n")
                path.chmod(0o600)
            with patch.object(self.module.subprocess, "run", side_effect=fake_run):
                self.module.validate_rendered_configs(self.config, control, worker)
            self.assertEqual(len(commands), 22)
            self.assertEqual(sum(command[1:3] == ["machineconfig", "patch"]
                                 for command in commands), 10)
            worker.chmod(0o644)
            with self.assertRaises(ValueError):
                self.module.validate_rendered_configs(self.config, control, worker)

    def test_validate_cli_checks_declaration_without_external_commands(self):
        output = StringIO()
        with patch.object(self.module.sys, "argv", [str(SCRIPT), "validate", "--config", str(CONFIG)]), \
                patch.object(self.module.subprocess, "run", side_effect=AssertionError("external command")) as run, \
                redirect_stdout(output):
            self.assertEqual(self.module.main(), 0)
        run.assert_not_called()
        self.assertIn("declaration validated only", output.getvalue())
        self.assertIn("live readiness unverified", output.getvalue())

    def test_execute_rejects_local_config_override_before_talos_or_receipts(self):
        sha = "a" * 40
        with patch.object(self.module.subprocess, "check_output", return_value=CONFIG.read_bytes()) as committed:
            self.assertEqual(self.module.require_reviewed_execution_config(CONFIG, sha),
                             CONFIG.read_bytes())
        committed.assert_called_once_with(
            ["git", "--no-replace-objects", "show",
             sha + ":scripts/config/platform-maintenance.json"],
            cwd=ROOT, timeout=15)
        with tempfile.TemporaryDirectory() as directory:
            override = Path(directory) / "platform-maintenance.json"
            candidate = copy.deepcopy(self.config)
            candidate["activationEnabled"] = True
            candidate["canary"]["node"] = "zimaboard-0"
            override.write_text(json.dumps(candidate))
            self.module.validate_config(candidate)
            with self.assertRaisesRegex(ValueError, "not repository-owned"):
                self.module.require_reviewed_execution_config(override, sha)
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true",
                                         "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": sha}), \
                    patch.object(self.module.sys, "argv", [str(SCRIPT), "execute", "--config",
                                                            str(override), "--stage", "talos-1.11.6",
                                                            "--expected-sha", sha,
                                                            "--control-plane-config", "/tmp/control.yaml",
                                                            "--worker-config", "/tmp/worker.yaml",
                                                            "--receipt-dir", "/tmp/receipts"]), \
                    patch.object(self.module, "validate_rendered_configs") as talos, \
                    patch.object(self.module, "receipt_target") as receipts, \
                    redirect_stderr(StringIO()):
                self.assertEqual(self.module.main(), 1)
            talos.assert_not_called()
            receipts.assert_not_called()
        with patch.object(self.module.subprocess, "check_output", return_value=b"changed"):
            with self.assertRaisesRegex(ValueError, "differs from exact reviewed commit"):
                self.module.require_reviewed_execution_config(CONFIG, sha)

    def test_execute_parses_verified_bytes_without_reopening_config(self):
        sha = "a" * 40
        changed = copy.deepcopy(self.config)
        changed["activationEnabled"] = True
        changed["canary"]["node"] = "zimaboard-0"
        self.module.validate_config(changed)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true",
                                     "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": sha}), \
                patch.object(self.module.sys, "argv", [str(SCRIPT), "execute", "--config",
                                                        str(CONFIG), "--stage", "talos-1.11.6",
                                                        "--expected-sha", sha,
                                                        "--control-plane-config", "/tmp/control.yaml",
                                                        "--worker-config", "/tmp/worker.yaml",
                                                        "--receipt-dir", "/tmp/receipts"]), \
                patch.object(self.module.subprocess, "check_output", return_value=CONFIG.read_bytes()), \
                patch.object(Path, "read_text", return_value=json.dumps(changed)) as second_read, \
                patch.object(self.module, "validate_rendered_configs",
                             side_effect=ValueError("stop before Talos")) as talos, \
                redirect_stderr(StringIO()):
            self.assertEqual(self.module.main(), 1)
        talos.assert_called_once()
        self.assertEqual(talos.call_args.args[0], self.config)
        second_read.assert_not_called()

    def test_execute_ignores_local_git_replacement_for_reviewed_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "scripts/config/platform-maintenance.json"
            config.parent.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(root)], check=True)

            def commit(contents, message):
                config.write_text(contents)
                subprocess.run(["git", "-C", str(root), "add", str(config)], check=True)
                subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                                "-c", "user.email=test@example.invalid",
                                "-c", "commit.gpgsign=false", "commit", "-qm", message],
                               check=True)
                return subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

            reviewed = commit('{"activationEnabled":false}', "reviewed")
            replacement = commit('{"activationEnabled":true}', "unreviewed")
            subprocess.run(["git", "-C", str(root), "replace", reviewed, replacement],
                           check=True)
            with patch.object(self.module, "ROOT", root), \
                    self.assertRaisesRegex(ValueError, "differs from exact reviewed commit"):
                self.module.require_reviewed_execution_config(config, reviewed)

    def test_validate_cli_rejects_one_private_role_config(self):
        for flag in ("--control-plane-config", "--worker-config"):
            with self.subTest(flag=flag), \
                    patch.object(self.module.sys, "argv", [str(SCRIPT), "validate", "--config",
                                                            str(CONFIG), flag, "/tmp/unused-private.yaml"]), \
                    patch.object(self.module.subprocess, "run", side_effect=AssertionError("external command")) as run, \
                    redirect_stderr(StringIO()):
                self.assertEqual(self.module.main(), 1)
                run.assert_not_called()

    def test_validate_cli_strictly_checks_both_private_role_configs(self):
        with tempfile.TemporaryDirectory(prefix="talos-cli-validation-", dir="/tmp") as directory:
            subprocess.run(
                ["talosctl", "gen", "config", "validation-only", "https://10.1.0.199:6443",
                 "--output-dir", directory],
                check=True, capture_output=True, text=True, timeout=60,
            )
            control = Path(directory) / "controlplane.yaml"
            worker = Path(directory) / "worker.yaml"
            control.chmod(0o600)
            worker.chmod(0o600)
            output = StringIO()
            real_run = subprocess.run
            with patch.object(self.module.sys, "argv", [str(SCRIPT), "validate", "--config",
                                                        str(CONFIG), "--control-plane-config", str(control),
                                                        "--worker-config", str(worker)]), \
                    patch.object(self.module.subprocess, "run", wraps=real_run) as run, \
                    redirect_stdout(output):
                self.assertEqual(self.module.main(), 0)
            self.assertEqual(run.call_count, 22)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(all(command[0] == "talosctl" for command in commands))
            self.assertEqual(sum(command[1] == "validate" and command[-1] == "--strict"
                                 for command in commands), 12)
            self.assertIn("validated offline", output.getvalue())
            self.assertIn("live readiness unverified", output.getvalue())

    def test_private_receipts_refuse_world_readable_and_linked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            receipt = path / "placement.json"
            receipt.write_text(json.dumps({"sourceSha": "a" * 40, "verified": True}))
            receipt.chmod(0o600)
            self.assertTrue(self.module.read_receipts(path)["placement"]["verified"])
            receipt.chmod(0o644)
            with self.assertRaises(ValueError):
                self.module.read_receipts(path)
            receipt.chmod(0o600)
            receipt.unlink()
            receipt.symlink_to(CONFIG)
            with self.assertRaises(ValueError):
                self.module.read_receipts(path)

    def test_generated_role_configs_pass_all_strict_offline_patches(self):
        with tempfile.TemporaryDirectory(prefix="talos-validation-", dir="/tmp") as directory:
            subprocess.run(
                ["talosctl", "gen", "config", "validation-only", "https://10.1.0.199:6443",
                 "--output-dir", directory],
                check=True, capture_output=True, text=True, timeout=60,
            )
            control = Path(directory) / "controlplane.yaml"
            worker = Path(directory) / "worker.yaml"
            control.chmod(0o600)
            worker.chmod(0o600)
            self.module.validate_rendered_configs(self.config, control, worker)

    def test_per_node_receipt_stays_pending_across_interrupted_upgrade(self):
        sha, stage, node = "a" * 40, "talos-1.11.6", "zimaboard-0"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.module.start_node_receipt(path, stage, node, "1.11.3", "1.11.6", sha)
            pending = self.module.read_node_receipt(path, stage, node)
            self.assertFalse(pending["verified"])
            with self.assertRaises(ValueError):
                self.module.node_action(node, "1.11.3", "1.11.6", "1.11.3", "boot",
                                        pending, "b" * 40, stage)
            with self.assertRaises(FileExistsError):
                self.module.start_node_receipt(path, stage, node, "1.11.3", "1.11.6", sha)
            with self.assertRaises(ValueError):
                self.module.complete_node_receipt(path, stage, node, sha, {})
            complete = self.module.complete_node_receipt(
                path, stage, node, sha, {"observedVersion": "1.11.6", "ready": True,
                                        "clusterHealth": True, "bootID": "new-boot"})
            self.assertEqual(self.module.node_action(node, "1.11.3", "1.11.6", "1.11.6",
                                                     "new-boot", complete, sha, stage), "skip")
            with self.assertRaises(ValueError):
                self.module.complete_node_receipt(path, stage, node, sha, {})

    def test_durable_node_markers_restore_and_refuse_ambiguous_history(self):
        stage, node, sha = "talos-1.11.6", "zimaboard-0", "a" * 40
        target = self.module.receipt_target()
        store = self.module.DurableReceipts(target)
        objects = {}
        unknown = [False]

        def fake_call(service, operation, arguments=()):
            if operation == "list-object-versions":
                prefix = arguments[arguments.index("--prefix") + 1]
                return {"IsTruncated": False, "Versions": [
                    {"Key": key, "VersionId": version, "IsLatest": True}
                    for key, (_, version) in objects.items() if key.startswith(prefix)]}
            key = arguments[arguments.index("--key") + 1]
            if operation == "put-object":
                self.assertEqual(arguments[arguments.index("--if-none-match") + 1], "*")
                self.assertEqual(arguments[arguments.index("--server-side-encryption") + 1],
                                 "aws:kms")
                self.assertNotIn(key, objects)
                content = Path(arguments[arguments.index("--body") + 1]).read_bytes()
                checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
                self.assertEqual(arguments[arguments.index("--checksum-sha256") + 1], checksum)
                version = f"version-{len(objects) + 1}"
                objects[key] = (content, version)
                if unknown[0]:
                    raise ValueError("unknown write outcome")
                return {"VersionId": version, "ChecksumSHA256": checksum}
            if operation == "get-object":
                content, version = objects[key]
                self.assertEqual(arguments[arguments.index("--version-id") + 1], version)
                Path(arguments[-1]).write_bytes(content)
                return {"VersionId": version, "ContentLength": len(content),
                        "ChecksumSHA256": base64.b64encode(hashlib.sha256(content).digest()).decode(),
                        "ServerSideEncryption": "aws:kms"}
            raise AssertionError(operation)

        with tempfile.TemporaryDirectory() as directory, \
                tempfile.TemporaryDirectory() as retry_directory, \
                patch.object(store, "call", side_effect=fake_call):
            path = Path(directory)
            unknown[0] = True
            with self.assertRaisesRegex(ValueError, "unknown write outcome"):
                self.module.start_node_receipt(path, stage, node, "1.11.3", "1.11.6", sha,
                                               store)
            unknown[0] = False
            store.restore(stage, Path(retry_directory))
            pending = self.module.read_node_receipt(Path(retry_directory), stage, node)
            with self.assertRaisesRegex(ValueError, "unknown node state"):
                self.module.node_action(node, "1.11.3", "1.11.6", "1.11.3", "boot", pending,
                                        sha, stage)
            self.module.complete_node_receipt(path, stage, node, sha, {
                "observedVersion": "1.11.6", "ready": True,
                "clusterHealth": True, "bootID": "new-boot"}, store)
            with tempfile.TemporaryDirectory() as complete_directory:
                store.restore(stage, Path(complete_directory))
                complete = self.module.read_node_receipt(Path(complete_directory), stage, node)
                self.assertEqual(self.module.node_action(
                    node, "1.11.3", "1.11.6", "1.11.6", "new-boot", complete, sha, stage), "skip")
            objects[store.key(stage, node, "started")] = (
                objects[store.key(stage, node, "started")][0], "null")
            with tempfile.TemporaryDirectory() as ambiguous_directory, \
                    self.assertRaisesRegex(ValueError, "ambiguous"):
                store.restore(stage, Path(ambiguous_directory))

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(store, "call", return_value={"IsTruncated": False,
                                                          "Versions": []}):
            self.module.start_node_receipt(Path(directory), stage, node,
                                           "1.11.3", "1.11.6", sha)
            with self.assertRaisesRegex(ValueError, "no durable copy"):
                store.restore(stage, Path(directory))

    def test_durable_aws_call_binds_reviewed_endpoint_and_bucket_owner(self):
        target = self.module.receipt_target()
        store = self.module.DurableReceipts(target)
        result = subprocess.CompletedProcess([], 0, "{}", "")
        with patch.object(self.module.subprocess, "run", return_value=result) as run:
            store.call("s3api", "list-object-versions", ["--prefix", "fixed/"])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--endpoint-url") + 1],
                         "https://s3.us-east-1.amazonaws.com")
        self.assertEqual(command[command.index("--bucket") + 1], target["bucket"])
        self.assertEqual(command[command.index("--expected-bucket-owner") + 1],
                         target["account_id"])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        with self.assertRaisesRegex(ValueError, "unreviewed platform receipt destination"):
            self.module.DurableReceipts({**target, "bucket": "another-bucket"})

    def test_kubernetes_completion_requires_durable_stage_start(self):
        target = self.module.receipt_target()
        store = self.module.DurableReceipts(target)
        stage = "kubernetes-1.35.9"
        key = store.key(stage, None, "verified")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(store, "versions", return_value={key: "version-1"}), \
                patch.object(store, "download", return_value=b"{}"), \
                self.assertRaisesRegex(ValueError, "no durable start marker"):
            store.restore(stage, Path(directory))

    def test_durable_start_failure_prevents_talos_command(self):
        sha, stage = "a" * 40, "talos-1.11.6"
        state = {node: {"talos": "1.11.3", "kubelet": "v1.34.11", "ready": True,
                        "bootID": "boot"} for node in self.config["nodeOrder"]}
        commands = []
        store = unittest.mock.Mock()
        store.write.side_effect = ValueError("durable write unknown")
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                     "GITHUB_SHA": sha}), \
                patch.object(self.module, "read_only_inspection", return_value={"nodes": state}), \
                patch.object(self.module, "cluster_health"), \
                patch.object(self.module, "current_main_sha", return_value=sha), \
                patch.object(self.module.subprocess, "run", side_effect=commands.append):
            self.write_publication(directory, sha)
            with self.assertRaisesRegex(ValueError, "durable write unknown"):
                self.module.execute_talos_stage(
                    self.config, stage, sha, Path("/private/talosconfig"), Path(directory), store)
        self.assertEqual(commands, [])

    def test_durable_start_failure_prevents_kubernetes_command(self):
        sha, stage = "a" * 40, "kubernetes-1.35.9"
        state = {node: {"talos": "1.14.4", "kubelet": "v1.34.11", "ready": True,
                        "bootID": "boot"} for node in self.config["nodeOrder"]}
        commands = []
        store = unittest.mock.Mock()
        store.write.side_effect = ValueError("durable write unknown")
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                     "GITHUB_SHA": sha}), \
                patch.object(self.module, "read_only_inspection", return_value={"nodes": state}), \
                patch.object(self.module, "kubernetes_server_version", return_value="1.34.11"), \
                patch.object(self.module, "cluster_health"), \
                patch.object(self.module, "current_main_sha", return_value=sha), \
                patch.object(self.module.subprocess, "run", side_effect=commands.append):
            self.write_publication(directory, sha)
            with self.assertRaisesRegex(ValueError, "durable write unknown"):
                self.module.execute_kubernetes_stage(
                    self.config, stage, sha, Path("/private/talosconfig"), Path(directory), store)
        self.assertEqual(commands, [])

    def test_restored_talos_completion_must_match_before_next_upgrade(self):
        sha, stage, node = "a" * 40, "talos-1.11.6", "zimaboard-0"
        for mismatch, completed_node in (("from", node), ("bootID", node),
                                         ("pinSha256", node),
                                         ("later-node", "zimaboard-1"),
                                         ("later-not-ready", "zimaboard-1")):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                state = {name: {"talos": "1.11.3", "kubelet": "v1.34.11", "ready": True,
                                "bootID": "boot"} for name in self.config["nodeOrder"]}
                state[completed_node]["talos"] = "1.11.6"
                path = Path(directory)
                self.write_publication(path, sha)
                self.module.start_node_receipt(path, stage, completed_node,
                                               "1.11.3", "1.11.6", sha)
                self.module.complete_node_receipt(path, stage, completed_node, sha, {
                    "observedVersion": "1.11.6", "ready": True,
                    "clusterHealth": True, "bootID": "boot"})
                if mismatch in ("from", "later-node", "pinSha256"):
                    receipt = self.module.node_receipt_path(path, stage, completed_node)
                    record = json.loads(receipt.read_text())
                    record["pinSha256" if mismatch == "pinSha256" else "from"] = (
                        "0" * 64 if mismatch == "pinSha256" else "9.9.9")
                    receipt.write_text(json.dumps(record))
                elif mismatch == "bootID":
                    state[completed_node]["bootID"] = "later-boot"
                else:
                    state[completed_node]["ready"] = False
                commands = []
                with patch.dict(os.environ, {"GITHUB_ACTIONS": "true",
                                              "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": sha}), \
                        patch.object(self.module, "read_only_inspection",
                                     return_value={"nodes": state}), \
                        patch.object(self.module, "cluster_health"), \
                        patch.object(self.module, "current_main_sha", return_value=sha), \
                        patch.object(self.module.subprocess, "run", side_effect=commands.append):
                    with self.assertRaisesRegex(
                            ValueError, "baseline" if mismatch == "later-not-ready"
                            else "recovery review"):
                        self.module.execute_talos_stage(
                            self.config, stage, sha, Path("/private/talosconfig"), path)
                self.assertEqual(commands, [])

    def test_talos_command_uses_only_ordered_node_and_pinned_image(self):
        for node, address in zip(self.config["nodeOrder"],
                                 ("10.1.0.200", "10.1.0.201", "10.1.0.202", "10.1.0.199")):
            command = self.module.talos_upgrade_command(
                self.config, "talos-1.11.6", node, Path("/private/talosconfig"))
            self.assertEqual(command[:7], ["talosctl", "--talosconfig", "/private/talosconfig",
                                           "--endpoints", self.config["protectedTalosEndpoint"],
                                           "--nodes", address])
            self.assertEqual(command[7:9], ["upgrade", "--image"])
            self.assertEqual(command[9], self.config["talosStages"][0]["installerImage"])
            self.assertNotIn("--force", command)
            self.assertNotIn("--insecure", command)
        with self.assertRaises(ValueError):
            self.module.talos_upgrade_command(self.config, "talos-1.13.11", "unknown",
                                              Path("/private/talosconfig"))

    def test_kubernetes_command_uses_version_appending_bases_bound_to_catalog_digests(self):
        catalog = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())
        command = self.module.kubernetes_upgrade_command(
            self.config, Path("/private/talosconfig"), catalog)
        self.assertIn("upgrade-k8s", command)
        self.assertEqual(command[command.index("--from") + 1], "1.34.11")
        self.assertEqual(command[command.index("--to") + 1], "1.35.9")
        self.assertEqual(command[command.index("--apiserver-image") + 1],
                         "registry.k8s.io/kube-apiserver")
        self.assertNotIn("--dry-run", command)
        self.assertTrue(all("@sha256:" not in argument for argument in command))
        catalog["images"] = [item for item in catalog["images"]
                             if item["source"] != self.config["kubernetesStage"]["images"]["kubelet"]]
        with self.assertRaises(ValueError):
            self.module.kubernetes_upgrade_command(self.config, Path("/private/talosconfig"), catalog)

    def test_publication_receipt_binds_every_platform_image(self):
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            receipt = json.loads(self.write_publication(directory, sha).read_text())
            self.module.require_publication(self.config, sha, receipt)
            receipt["kubernetesImages"]["kubelet"] = "ghcr.io/siderolabs/kubelet:latest"
            with self.assertRaises(ValueError):
                self.module.require_publication(self.config, sha, receipt)
            receipt = json.loads((Path(directory) / "artifact-publication.json").read_text())
            receipt["talosImages"]["talos-1.14.4"] = "factory.talos.dev/metal-installer:latest"
            with self.assertRaises(ValueError):
                self.module.require_publication(self.config, sha, receipt)

    def test_talos_stage_upgrades_serially_and_publishes_only_after_all_nodes(self):
        sha, stage = "a" * 40, "talos-1.11.6"
        state = {node: {"talos": "1.11.3", "kubelet": "v1.34.11", "ready": True,
                        "bootID": f"boot-{node}"} for node in self.config["nodeOrder"]}
        commands = []
        events = []
        store = unittest.mock.Mock()
        store.write.side_effect = lambda _stage, node, status, _path: events.append((node, status))

        def inspect(*args):
            return {"nodes": copy.deepcopy(state)}

        def upgrade(command, **kwargs):
            self.assertEqual(command[7], "upgrade")
            commands.append(command)
            node = next(name for name, value in self.config["expectedStart"]["nodes"].items()
                        if value["address"] == command[6])
            events.append((node, "upgrade"))
            state[node]["talos"] = "1.11.6"
            state[node]["bootID"] = f"upgraded-{node}"
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                     "GITHUB_SHA": sha}), \
                patch.object(self.module, "read_only_inspection", side_effect=inspect), \
                patch.object(self.module, "cluster_health"), \
                patch.object(self.module, "current_main_sha", return_value=sha), \
                patch.object(self.module.subprocess, "run", side_effect=upgrade):
            self.write_publication(directory, sha)
            receipt = self.module.execute_talos_stage(
                self.config, stage, sha, Path("/private/talosconfig"), Path(directory), store)
            self.assertTrue(receipt["verified"])
            self.assertEqual([command[6] for command in commands],
                             [self.config["expectedStart"]["nodes"][node]["address"]
                              for node in self.config["nodeOrder"]])
            self.assertEqual(len(receipt["nodes"]), 4)
            self.assertEqual(events, [event for node in self.config["nodeOrder"]
                                      for event in ((node, "started"), (node, "upgrade"),
                                                    (node, "verified"))] + [(None, "verified")])
            self.assertTrue(all(self.module.read_node_receipt(Path(directory), stage, node)["verified"]
                                for node in self.config["nodeOrder"]))
            self.module.verify_stage_receipt(self.config, stage, receipt, Path(directory))
            changed = self.module.node_receipt_path(Path(directory), stage, "zimaboard-0")
            changed.write_text(changed.read_text() + " ")
            with self.assertRaises(ValueError):
                self.module.verify_stage_receipt(self.config, stage, receipt,
                                                 Path(directory))

    def test_talos_stage_resumes_verified_nodes_after_main_advances(self):
        old_sha, new_sha, stage = "a" * 40, "b" * 40, "talos-1.11.6"
        first = self.config["nodeOrder"][0]
        state = {node: {"talos": "1.11.3", "kubelet": "v1.34.11", "ready": True,
                        "bootID": f"boot-{node}"} for node in self.config["nodeOrder"]}
        state[first]["talos"] = "1.11.6"
        state[first]["bootID"] = "upgraded-first"
        commands = []

        def upgrade(command, **kwargs):
            node = next(name for name, value in self.config["expectedStart"]["nodes"].items()
                        if value["address"] == command[6])
            commands.append(node)
            state[node]["talos"] = "1.11.6"
            state[node]["bootID"] = f"upgraded-{node}"
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write_publication(path, new_sha)
            self.module.start_node_receipt(path, stage, first, "1.11.3", "1.11.6", old_sha)
            self.module.complete_node_receipt(path, stage, first, old_sha, {
                "observedVersion": "1.11.6", "ready": True,
                "clusterHealth": True, "bootID": "upgraded-first"})
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                         "GITHUB_SHA": new_sha}), \
                    patch.object(self.module, "read_only_inspection",
                                 side_effect=lambda *args: {"nodes": copy.deepcopy(state)}), \
                    patch.object(self.module, "cluster_health"), \
                    patch.object(self.module, "current_main_sha", return_value=new_sha), \
                    patch.object(self.module.subprocess, "run", side_effect=upgrade):
                receipt = self.module.execute_talos_stage(
                    self.config, stage, new_sha, Path("/private/talosconfig"), path)
            self.assertEqual(commands, list(self.config["nodeOrder"][1:]))
            self.assertEqual(receipt["sourceSha"], new_sha)
            self.assertEqual(self.module.read_node_receipt(path, stage, first)["sourceSha"], old_sha)
            self.module.verify_stage_receipt(self.config, stage, receipt, path)

    def test_failed_upgrade_leaves_pending_receipt_and_refuses_retry(self):
        sha, stage, node = "a" * 40, "talos-1.11.6", "zimaboard-0"
        state = {name: {"talos": "1.11.3", "kubelet": "v1.34.11", "ready": True,
                        "bootID": "boot"} for name in self.config["nodeOrder"]}
        attempts = []

        def fail(command, **kwargs):
            attempts.append(command)
            raise subprocess.CalledProcessError(1, command)

        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                     "GITHUB_SHA": sha}), \
                patch.object(self.module, "read_only_inspection", return_value={"nodes": state}), \
                patch.object(self.module, "cluster_health"), \
                patch.object(self.module, "current_main_sha", return_value=sha), \
                patch.object(self.module.subprocess, "run", side_effect=fail):
            self.write_publication(directory, sha)
            with self.assertRaises(subprocess.CalledProcessError):
                self.module.execute_talos_stage(
                    self.config, stage, sha, Path("/private/talosconfig"), Path(directory))
            self.assertFalse(self.module.read_node_receipt(Path(directory), stage, node)["verified"])
            with self.assertRaises(ValueError):
                self.module.execute_talos_stage(
                    self.config, stage, sha, Path("/private/talosconfig"), Path(directory))
            self.assertEqual(len(attempts), 1)

    def test_kubernetes_stage_binds_publication_and_records_all_nodes(self):
        sha, stage = "a" * 40, "kubernetes-1.35.9"
        state = {node: {"talos": "1.14.4", "kubelet": "v1.34.11", "ready": True,
                        "bootID": f"boot-{node}"} for node in self.config["nodeOrder"]}
        server = ["1.34.11"]
        commands = []
        events = []
        store = unittest.mock.Mock()
        store.write.side_effect = lambda _stage, node, status, _path: events.append((node, status))

        def run(command, **kwargs):
            commands.append(command)
            self.assertIn("upgrade-k8s", command)
            events.append((None, "upgrade"))
            server[0] = "1.35.9"
            for node in state.values():
                node["kubelet"] = "v1.35.9"
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write_publication(path, sha)
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                         "GITHUB_SHA": sha}), \
                    patch.object(self.module, "read_only_inspection",
                                 side_effect=lambda *args: {"nodes": copy.deepcopy(state)}), \
                    patch.object(self.module, "kubernetes_server_version",
                                 side_effect=lambda: server[0]), \
                    patch.object(self.module, "cluster_health"), \
                    patch.object(self.module, "current_main_sha", return_value=sha), \
                    patch.object(self.module.subprocess, "run", side_effect=run):
                receipt = self.module.execute_kubernetes_stage(
                    self.config, stage, sha, Path("/private/talosconfig"), path, store)
            self.assertEqual(len(commands), 1)
            self.assertEqual(events[:2], [(None, "started"), (None, "upgrade")])
            self.assertEqual(events[-1], (None, "verified"))
            self.assertTrue(receipt["verified"])
            self.module.verify_stage_receipt(self.config, stage, receipt, path)
            self.assertEqual(len(receipt["nodes"]), 4)

    def test_kubernetes_interruption_cannot_reinvoke_upgrade(self):
        sha, stage = "a" * 40, "kubernetes-1.35.9"
        state = {node: {"talos": "1.14.4", "kubelet": "v1.34.11", "ready": True,
                        "bootID": "boot"} for node in self.config["nodeOrder"]}
        attempts = []

        def fail(command, **kwargs):
            attempts.append(command)
            raise subprocess.CalledProcessError(1, command)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write_publication(path, sha)
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                                         "GITHUB_SHA": sha}), \
                    patch.object(self.module, "read_only_inspection", return_value={"nodes": state}), \
                    patch.object(self.module, "kubernetes_server_version", return_value="1.34.11"), \
                    patch.object(self.module, "cluster_health"), \
                    patch.object(self.module, "current_main_sha", return_value=sha), \
                    patch.object(self.module.subprocess, "run", side_effect=fail):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.module.execute_kubernetes_stage(
                        self.config, stage, sha, Path("/private/talosconfig"), path)
                self.assertFalse(self.module.read_private_json(path / f"{stage}.json")["verified"])
                with self.assertRaises(ValueError):
                    self.module.execute_kubernetes_stage(
                        self.config, stage, sha, Path("/private/talosconfig"), path)
            self.assertEqual(len(attempts), 1)

    def test_current_sha_prerequisites_are_restored_from_one_verified_version(self):
        sha = "a" * 40
        target = self.module.receipt_target()
        store = self.module.DurableReceipts(target)
        records = self.prerequisites(sha)

        def versions(_service, operation, arguments=()):
            self.assertEqual(operation, "list-object-versions")
            key = arguments[-1]
            return {"IsTruncated": False, "Versions": [
                {"Key": key, "VersionId": "version-1", "IsLatest": True}]}

        def download(key, version, _directory):
            self.assertEqual(version, "version-1")
            return json.dumps(records[Path(key).stem]).encode()

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(store, "call", side_effect=versions), \
                patch.object(store, "download", side_effect=download):
            store.load_prerequisites(sha, Path(directory))
            self.assertEqual(self.module.read_receipts(Path(directory)), records)
            with self.assertRaisesRegex(ValueError, "differs"):
                (Path(directory) / "placement.json").write_text("{}")
                store.load_prerequisites(sha, Path(directory))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(store, "call", return_value={"IsTruncated": False,
                    "Versions": [{"Key": f"{self.module.PREREQUISITE_PREFIX}/{sha}/placement.json",
                                  "VersionId": "v1", "IsLatest": False}]}), \
                self.assertRaisesRegex(ValueError, "ambiguous"):
            store.load_prerequisites(sha, Path(directory))

    def test_recovery_prerequisites_require_fresh_direct_and_off_node_proof(self):
        sha = "a" * 40
        receipts = self.prerequisites(sha)
        self.module.verify_prerequisites(self.config, sha, receipts)
        for name, field, value in (
            ("direct-recovery", "transport", "octelium"),
            ("direct-recovery", "capturedAt", "2000-01-01T00:00:00Z"),
            ("off-node-etcd-backup", "offlineRestoreVerified", False),
            ("off-node-etcd-backup", "objectVersionId", "null"),
            ("placement", "measured", False),
        ):
            changed = copy.deepcopy(receipts)
            changed[name][field] = value
            with self.subTest(name=name, field=field), self.assertRaises(ValueError):
                self.module.verify_prerequisites(self.config, sha, changed)

    def test_active_machine_state_requires_role_disk_and_persistent_parity(self):
        machine = {"type": "worker", "install": {"disk": "/dev/sda"},
                   "registries": {"mirrors": {}}}
        resources = [{"metadata": {"id": "v1alpha1", "namespace": "config",
                                   "type": "MachineConfigs.config.talos.dev", "phase": "running",
                                   "version": 1},
                      "spec": "active"}]

        def run(command, **kwargs):
            if command[0] == "talosctl":
                return subprocess.CompletedProcess(command, 0,
                    "\n".join(json.dumps(resource) for resource in resources), "")
            self.assertEqual(command[0], "yq")
            decoded = copy.deepcopy(machine)
            if kwargs.get("input") == "changed":
                decoded["install"]["disk"] = "/dev/nvme0n1"
            return subprocess.CompletedProcess(command, 0,
                json.dumps([{"version": "v1alpha1", "machine": decoded}]), "")

        with patch.object(self.module.subprocess, "run", side_effect=run):
            state = self.machine_state_function(self.config, Path("/private/talosconfig"),
                                                "zimaboard-0")
            self.assertEqual((state["role"], state["disk"]), ("worker", "/dev/sda"))
            machine["install"]["disk"] = ""
            with self.assertRaisesRegex(ValueError, "install disk"):
                self.machine_state_function(self.config, Path("/private/talosconfig"),
                                            "zimaboard-0")
            machine["install"]["disk"] = "/dev/sda"
            resources.append({**resources[0], "metadata": {**resources[0]["metadata"],
                              "id": "persistent"}, "spec": "changed"})
            with self.assertRaisesRegex(ValueError, "differ"):
                self.machine_state_function(self.config, Path("/private/talosconfig"),
                                            "zimaboard-0")

    def test_kubernetes_mirror_tags_require_reviewed_digest_and_immutable_flag(self):
        sources = list(self.config["kubernetesStage"]["images"].values())
        expected = [source.rsplit("@", 1)[1] for source in sources]
        calls = []

        def open_tag(url, **_kwargs):
            calls.append(url)
            digest = expected[len(calls) - 1]
            return io.BytesIO(json.dumps({"digest": digest, "tags": [
                {"name": "v1.35.9", "immutable": True}]}).encode())

        with patch.object(self.module.urllib.request, "urlopen", side_effect=open_tag):
            self.mirror_tag_function(self.config)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all("with_immutable_status=true" in url for url in calls))

        def unlocked(_url, **_kwargs):
            return io.BytesIO(json.dumps({"digest": expected[0], "tags": [
                {"name": "v1.35.9", "immutable": False}]}).encode())

        with patch.object(self.module.urllib.request, "urlopen", side_effect=unlocked), \
                self.assertRaisesRegex(ValueError, "not locked"):
            self.mirror_tag_function(self.config)

    def test_kubernetes_preflight_requires_live_istio_target_and_readiness(self):
        target = self.config["istioStages"][-1]["images"]
        components = (
            ("Deployment", "istiod", "pilot"),
            ("Deployment", "istio-ingressgateway", "proxyv2"),
            ("Deployment", "octelium-api-ingressgateway", "proxyv2"),
            ("DaemonSet", "istio-cni-node", "install-cni"),
            ("DaemonSet", "ztunnel", "ztunnel"),
        )
        items = []
        for kind, name, component in components:
            image = "auto" if name.endswith("ingressgateway") else target[component]
            status = {"observedGeneration": 1}
            if kind == "Deployment":
                status.update(replicas=1, updatedReplicas=1, readyReplicas=1,
                              availableReplicas=1)
            else:
                status.update(desiredNumberScheduled=4, updatedNumberScheduled=4,
                              numberReady=4, numberAvailable=4, numberMisscheduled=0)
            items.append({"kind": kind, "metadata": {"name": name, "generation": 1},
                          "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                                   "template": {"spec": {
                              "containers": [{"image": image}]}}}, "status": status})
        gateway_image = target["proxyv2"]
        pods = [{"metadata": {"labels": {"app": name}},
                 "spec": {"containers": [{"image": gateway_image}]},
                 "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
                for name in ("istio-ingressgateway", "octelium-api-ingressgateway")]

        def inspect(command, **_kwargs):
            self.assertEqual(command[:4], ["kubectl", "-n", "istio-system", "get"])
            self.assertEqual(command[-2:], ["-o", "json"])
            payload = pods if command[4] == "pods" else items
            return subprocess.CompletedProcess(command, 0, json.dumps({"items": payload}), "")

        with patch.object(self.module.subprocess, "run", side_effect=inspect):
            self.istio_target_function(self.config)
            pods[0]["spec"]["containers"][0]["image"] = (
                gateway_image.split("@sha256:", 1)[0])
            with self.assertRaisesRegex(ValueError, "gateway Pods"):
                self.istio_target_function(self.config)
            pods[0]["spec"]["containers"][0]["image"] = "docker.io/istio/proxyv2:1.27.3"
            with self.assertRaisesRegex(ValueError, "gateway Pods"):
                self.istio_target_function(self.config)
            pods[0]["spec"]["containers"][0]["image"] = gateway_image
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = (
                target["pilot"].replace("1.30.6", "1.27.3"))
            with self.assertRaisesRegex(ValueError, "image differs"):
                self.istio_target_function(self.config)
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = (
                target["pilot"].split("@sha256:", 1)[0])
            with self.assertRaisesRegex(ValueError, "image differs"):
                self.istio_target_function(self.config)
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = (
                target["pilot"].split("@sha256:", 1)[0] + "@sha256:" + "0" * 64)
            with self.assertRaisesRegex(ValueError, "image differs"):
                self.istio_target_function(self.config)
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = target["pilot"]
            items[0]["status"]["replicas"] = 2
            with self.assertRaisesRegex(ValueError, "not fully ready"):
                self.istio_target_function(self.config)
            items[0]["status"]["replicas"] = 1
            items[3]["status"]["numberReady"] = 3
            with self.assertRaisesRegex(ValueError, "not fully ready"):
                self.istio_target_function(self.config)
            items[3]["status"]["numberReady"] = 4
            items.pop()
            with self.assertRaisesRegex(ValueError, "is missing"):
                self.istio_target_function(self.config)

    def test_target_patches_only_change_pinned_images_for_each_role(self):
        self.module.validate_target_patches(self.config)
        changed = copy.deepcopy(self.config)
        changed["kubernetesStage"]["offlineRenderPatches"]["worker"] = (
            changed["kubernetesStage"]["offlineRenderPatches"]["controlPlane"])
        with self.assertRaisesRegex(ValueError, "worker target patch"):
            self.module.validate_target_patches(changed)

    def test_installer_requires_no_fallback_mirror_on_the_selected_node(self):
        machine = {"mirrors": {"ghcr.io": {"endpoints": [
            "https://harbor.stinkyboi.com/v2/mirror/ghcr.io"],
            "overridePath": True, "skipFallback": True}}}
        self.module.verify_installer_mirror_route(machine,
            self.config["talosStages"][0]["installerImage"])
        machine["mirrors"]["ghcr.io"]["skipFallback"] = False
        with self.assertRaisesRegex(ValueError, "no-fallback"):
            self.module.verify_installer_mirror_route(machine,
                self.config["talosStages"][0]["installerImage"])


if __name__ == "__main__":
    unittest.main()
