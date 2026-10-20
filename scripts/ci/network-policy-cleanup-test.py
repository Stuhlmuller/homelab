#!/usr/bin/env python3
"""Keep owned firewall rollback narrow across kube-router and foreign rules."""

import argparse
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SUT = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
PREFIX = "KUBE-POD-FW-AAAAAAAAAAAAAAAA"
POLICY = "KUBE-NWPLCY-BBBBBBBBBBBBBBBB"
SET = "KUBE-SRC-CCCCCCCCCCCCCCCC"


def firewall():
    lines = ["*nat", ":PREROUTING ACCEPT [0:0]", ":KUBE-SERVICES - [0:0]",
             "-A PREROUTING -j KUBE-SERVICES", "COMMIT", "*filter",
             ":INPUT ACCEPT [0:0]", ":FORWARD ACCEPT [0:0]", ":OUTPUT ACCEPT [0:0]",
             ":KUBE-FIREWALL - [0:0]", "-A FORWARD -j KUBE-FIREWALL"]
    lines += [f":{chain} - [0:0]" for chain in sorted({*SUT["FIXED_CHAINS"], PREFIX, POLICY})]
    for builtin, chain in SUT["ROOT_CHAINS"].items():
        comment = SUT["top_jump_comment"](builtin, chain)
        lines.append(f'-A {builtin} -m comment --comment "{comment}" -j {chain}')
    lines += [f"-A KUBE-ROUTER-INPUT -j {PREFIX}",
              f"-A {PREFIX} -j {POLICY}",
              f"-A {POLICY} -m set --match-set {SET} src -j MARK",
              "-A KUBE-NWPLCY-TAIL -m set ! --match-set kube-router-local-pods src -j REJECT",
              "COMMIT"]
    return "\n".join(lines) + "\n"


def state():
    empty = "*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\nCOMMIT\n"
    return {"backend": "nft", "nft": firewall(), "legacy": empty,
            "ip6nft": empty, "ip6legacy": empty,
            "ipset": (f"create {SET} hash:ip family inet hashsize 1024 maxelem 65536\n"
                      "create kube-router-local-pods hash:ip family inet hashsize 1024 maxelem 65536\n"
                      f"add {SET} 10.0.0.1\n")}


class FirewallCleanupTests(unittest.TestCase):
    def test_pre_removal_evidence_requires_exact_fixture_then_firewall_prune(self):
        manifest = "clusters/homelab/platform/network-policy/kustomization.yaml"
        application = "IaC/platform-network-policy/stack.hcl"
        canary_manifest = "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
        canary_application = "IaC/platform-network-policy-canary/stack.hcl"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (manifest, application, canary_manifest, canary_application,
                         "clusters/homelab/platform/network-policy/daemonset.yaml"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            dormant = "        enabled = false\n        prune   = false\n"
            active = "        enabled = true\n        prune   = true\n"
            empty_active = ("        enabled    = true\n        prune      = true\n"
                            "        allowEmpty = true\n")
            for name, variants in ((application, (dormant, empty_active)),
                                   (canary_application, (dormant, active, empty_active))):
                target = root / name
                source = target.read_text()
                matches = [variant for variant in variants if source.count(variant) == 1]
                self.assertEqual(len(matches), 1, f"unreviewed source state: {name}")
                target.write_text(source.replace(matches[0], dormant))
            (root / manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
                "resources:\n  - daemonset.yaml\n")
            (root / canary_manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True).stdout.strip()
            def commit(message):
                git("add", "-A")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", message)
                return git("rev-parse", "HEAD")
            def document(name, contents):
                target = root / "docs" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents)
            def prune_fixtures():
                (root / canary_manifest).write_text(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
                original = (root / canary_application).read_text()
                (root / canary_application).write_text(original.replace(
                    "        enabled = true\n        prune   = true\n",
                    "        enabled    = true\n        prune      = true\n        allowEmpty = true\n"))
            def prune_firewall():
                (root / manifest).write_text(
                    "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
                original = (root / application).read_text()
                (root / application).write_text(original.replace(
                    "        enabled = false\n        prune   = false\n",
                    "        enabled    = true\n        prune      = true\n        allowEmpty = true\n"))
            def wiki_update(name):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("native OpenWiki update\n")
            git("init", "-q")
            (root / canary_manifest).write_text(
                "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - fixtures.yaml\n")
            original = (root / canary_application).read_text()
            (root / canary_application).write_text(original.replace(
                "        enabled = false\n        prune   = false\n",
                "        enabled = true\n        prune   = true\n"))
            qualify_sha = commit("qualify with fixtures")
            document("unrelated.md", "before\n")
            commit("unrelated change before fixture prune")
            prune_fixtures()
            wiki_update("openwiki/unreviewed.md")
            commit("fixture prune with unreviewed wiki change")
            prune_firewall()
            drift_sha = commit("firewall prune")
            transition = SUT["require_firewall_removal_transition"]
            with patch.dict(transition.__globals__, {"ROOT": root}):
                with self.assertRaisesRegex(ValueError, "fixture removal differs"):
                    transition(qualify_sha, drift_sha)
                git("reset", "--hard", qualify_sha)
                document("unrelated.md", "before\n")
                commit("unrelated before valid prunes")
                prune_fixtures()
                wiki_update("openwiki/runbooks/runtime-isolation.md")
                wiki_update("openwiki/.last-update.json")
                fixture_sha = commit("fixture prune with reviewed wiki update")
                with self.assertRaisesRegex(ValueError, "both reviewed GitOps prune"):
                    transition(qualify_sha, fixture_sha)
                document("unrelated.md", "between\n")
                middle_sha = commit("unrelated change between prunes")
                prune_firewall()
                document("unrelated.md", "drift\n")
                drift_sha = commit("firewall prune with unrelated change")
                with self.assertRaisesRegex(ValueError, "firewall removal differs"):
                    transition(qualify_sha, drift_sha)
                git("reset", "--hard", middle_sha)
                prune_firewall()
                wiki_update("openwiki/workloads/inventory.md")
                wiki_update("openwiki/.claims/workloads/inventory.json")
                wiki_update("openwiki/.page-manifest.json")
                removal_sha = commit("firewall prune with reviewed wiki update")
                transition(qualify_sha, removal_sha)
                document("unrelated.md", "after\n")
                later_sha = commit("unrelated change after prunes")
                transition(qualify_sha, later_sha)
                main_branch = git("branch", "--show-current")
                git("checkout", "-qb", "unrelated-topic", qualify_sha)
                document("side-topic.md", "side branch\n")
                side_sha = commit("unrelated side branch")
                git("checkout", "-q", main_branch)
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "merge", "-q", "--no-ff", "-m",
                    "merge unrelated side branch", side_sha)
                transition(qualify_sha, git("rev-parse", "HEAD"))
                with self.assertRaisesRegex(ValueError, "first-parent history"):
                    transition(side_sha, git("rev-parse", "HEAD"))
                git("mv", "clusters/homelab/platform/network-policy/daemonset.yaml",
                    "renamed-unrelated.yaml")
                commit("rename protected policy source")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", "HEAD~1")
                protected = root / "scripts/network-policy-qualification.py"
                protected.parent.mkdir(parents=True)
                protected.write_text("changed\n")
                commit("change protected policy source")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                protected.unlink()
                commit("revert protected policy source")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", "HEAD~2")
                root_stack = root / "IaC/terragrunt.stack.hcl"
                root_stack.write_text("unreviewed root registration\n")
                commit("change root Application registration")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", "HEAD~1")
                project = root / "clusters/homelab/argocd/self-management/appproject.yaml"
                project.parent.mkdir(parents=True, exist_ok=True)
                project.write_text("unreviewed AppProject permissions\n")
                commit("change canary AppProject permissions")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", "HEAD~1")
                gate = root / "scripts/ci/network-policy-registration-test.py"
                gate.parent.mkdir(parents=True, exist_ok=True)
                gate.write_text("weakened static phase check\n")
                commit("change protected static gate")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", "HEAD~1")
                anchor = git("rev-parse", "HEAD")
                for name in (
                        "IaC/application-backup-storage.hcl",
                        "IaC/unrelated-unit/stack.hcl",
                        "clusters/unrelated-app/kustomization.yaml",
                        "scripts/unrelated-helper.py",
                        ".github/actions/unrelated/action.yml",
                        ".talos/unrelated.yaml",
                        "builds/unrelated/Dockerfile",
                        "policy/unrelated.rego",
                        "recovery/unrelated.json",
                        "flake.nix", "flake.lock", ".unexpected-policy.toml",
                        ".argocd-values-ref-placeholder.yaml", ".checkov.yaml",
                        "docs/examples/octelium/runtime.yaml"):
                    with self.subTest(protected_path=name):
                        git("reset", "--hard", anchor)
                        protected = root / name
                        protected.parent.mkdir(parents=True, exist_ok=True)
                        protected.write_text("unreviewed operational source\n")
                        commit("change operational source")
                        with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                            transition(qualify_sha, git("rev-parse", "HEAD"))
                git("reset", "--hard", anchor)
                newline_name = "clusters/homelab/apps/unreviewed/bad\nmanifest.yaml"
                protected = root / newline_name
                protected.parent.mkdir(parents=True, exist_ok=True)
                protected.write_text("unreviewed manifest\n")
                commit("change source with a quoted Git path")
                with self.assertRaisesRegex(ValueError, "policy cleanup source changed"):
                    transition(qualify_sha, git("rev-parse", "HEAD"))

    def test_unadmitted_config_refuses_before_any_cluster_command(self):
        with patch.dict(SUT["PLATFORM"], {
                "validate_config": lambda _: {"canary": {"node": None}}}):
            with self.assertRaisesRegex(ValueError, "no admitted canary"):
                SUT["execute"](argparse.Namespace(
                    config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha="0" * 40, capture_run_id="8",
                    receipt_dir=Path("/unused"), output=Path("/unused")))

    def test_admitted_cleanup_requires_protected_workflow_before_cluster_access(self):
        with patch.dict(SUT["PLATFORM"], {
                "validate_config": lambda _: {"canary": {"node": "zimaboard-1"}},
                "protected_context": lambda _: (_ for _ in ()).throw(
                    ValueError("protected current-main workflow required"))}):
            with self.assertRaisesRegex(ValueError, "protected current-main"):
                SUT["execute"](argparse.Namespace(
                    config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha="a" * 40, capture_run_id="8", receipt_dir=Path("/unused"),
                    output=Path("/unused")))

    def test_plan_targets_only_owned_ipv4_objects(self):
        commands, chains, sets = SUT["cleanup_plan"](state())
        self.assertEqual(chains, 8)
        self.assertEqual(sets, 2)
        self.assertEqual(len([item for item in commands if "-D" in item]), 3)
        self.assertEqual(len([item for item in commands if "-F" in item]), 8)
        self.assertEqual(len([item for item in commands if "-X" in item]), 8)
        self.assertEqual(len([item for item in commands if item[0] == "ipset"]), 2)
        self.assertFalse(any("KUBE-FIREWALL" in item or "KUBE-SERVICES" in item
                             for command in commands for item in command))
        self.assertTrue(all(command[0] in {"iptables-nft", "ipset"} for command in commands))

    def test_foreign_jump_or_ipset_reference_blocks_cleanup(self):
        for extra in (f"-A KUBE-FIREWALL -j {PREFIX}\n",
                      f"-A KUBE-FIREWALL -m set --match-set {SET} src -j ACCEPT\n",
                      "-A INPUT -j KUBE-ROUTER-INPUT\n"):
            with self.subTest(extra=extra):
                candidate = state()
                candidate["nft"] = candidate["nft"].removesuffix("COMMIT\n") + extra + "COMMIT\n"
                with self.assertRaises(ValueError):
                    SUT["cleanup_plan"](candidate)

    def test_foreign_set_extension_references_block_cleanup(self):
        for option in ("--add-set", "--del-set", "--map-set"):
            with self.subTest(option=option):
                candidate = state()
                extra = f"-A KUBE-FIREWALL -j SET {option} {SET} src\n"
                candidate["nft"] = candidate["nft"].removesuffix("COMMIT\n") + extra + "COMMIT\n"
                with self.assertRaisesRegex(ValueError, "reference to owned ipset"):
                    SUT["cleanup_plan"](candidate)

    def test_main_drift_before_second_delete_records_interrupted(self):
        source_sha = "a" * 40
        evidence_sha = "b" * 40
        placement = {"format": 1, "verified": True, "sourceSha": evidence_sha,
                     "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
                     "firewallBaselineEmpty": True}
        ownership = {"evidenceSourceSha": evidence_sha, "captureRunId": "8"}
        checks = iter((source_sha, source_sha, "b" * 40))
        operations = []
        records = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            platform = SUT["PLATFORM"]
            replacements = {"validate_config": lambda _: {"canary": {"node": "zimaboard-1"}},
                            "protected_context": lambda _: None,
                            "current_main_sha": lambda: next(checks),
                            "private_directory": lambda value: value,
                            "private_output": lambda value: value,
                            "read_private_json": lambda value: placement if value.name ==
                            "placement.json" else ownership}
            globals_ = {"command": lambda *args: source_sha,
                        "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                        "snapshot": lambda *_: {"backend": "nft", "nft": "snapshot"},
                        "cleanup_plan": lambda *_: ([("iptables-nft", "-D", "first"),
                                                     ("iptables-nft", "-F", "second")], 1, 0),
                        "require_firewall_removal_transition": lambda *_: None,
                        "require_ownership": lambda *_: None,
                        "exec_cleanup": lambda _pod, *args: operations.append(args),
                        "write_record": lambda _path, record, replace=False:
                        records.append(record.copy())}
            with patch.dict(platform, replacements), patch.dict(SUT["execute"].__globals__,
                                                             globals_):
                args = argparse.Namespace(config=ROOT / "scripts/config/platform-maintenance.json",
                                          expected_sha=source_sha, capture_run_id="8", receipt_dir=path,
                                          output=path / "cleanup.json")
                with self.assertRaisesRegex(ValueError, "exact current main"):
                    SUT["execute"](args)
        self.assertEqual(operations, [("iptables-nft", "-D", "first")])
        self.assertEqual([record["status"] for record in records],
                         ["started", "interrupted"])

    def test_zero_object_review_records_verified_noop(self):
        source_sha, evidence_sha = "a" * 40, "b" * 40
        empty = state()["legacy"]
        snapshot = {"backend": "nft", "nft": empty, "legacy": empty,
                    "ip6nft": empty, "ip6legacy": empty, "ipset": "\n"}
        placement = {"format": 1, "verified": True, "sourceSha": evidence_sha,
                     "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
                     "firewallBaselineEmpty": True}
        ownership = {"format": 1, "verified": True, "sourceSha": source_sha,
                     "evidenceSourceSha": evidence_sha, "captureRunId": "9",
                     "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
                     "snapshotSha256": SUT["snapshot_sha256"](snapshot),
                     "reviewedAt": "2026-10-19T00:00:00Z"}
        records, operations = [], []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            platform = SUT["PLATFORM"]
            replacements = {"validate_config": lambda _: {"canary": {"node": "zimaboard-1"}},
                            "protected_context": lambda _: None,
                            "current_main_sha": lambda: source_sha,
                            "private_directory": lambda value: value,
                            "private_output": lambda value: value,
                            "read_private_json": lambda value: placement if value.name ==
                            "placement.json" else ownership}
            globals_ = {"command": lambda *args: source_sha,
                        "require_firewall_removal_transition": lambda *_: None,
                        "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                        "snapshot": lambda *_: snapshot,
                        "exec_cleanup": lambda _pod, *args: operations.append(args),
                        "write_record": lambda _path, record, replace=False:
                        records.append(record.copy())}
            with patch.dict(platform, replacements), patch.dict(SUT["execute"].__globals__,
                                                             globals_):
                result = SUT["execute"](argparse.Namespace(
                    config=ROOT / "scripts/config/platform-maintenance.json",
                    expected_sha=source_sha, capture_run_id="9", receipt_dir=path,
                    output=path / "cleanup.json"))
        self.assertEqual(result["status"], "verified")
        self.assertEqual([record["status"] for record in records], ["started", "verified"])
        self.assertEqual(operations, [])

    def test_reviewed_snapshot_blocks_foreign_rule_or_set_added_later(self):
        placement = {"nodeUid": "uid", "bootID": "boot"}
        original = state()
        ownership = {"format": 1, "verified": True, "sourceSha": "a" * 40,
                     "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
                     "reviewedAt": "2026-10-19T00:00:00Z",
                     "snapshotSha256": SUT["snapshot_sha256"](original)}
        SUT["require_ownership"](ownership, placement, original, "a" * 40,
                                 "zimaboard-1")
        for changed in ("rule", "set"):
            with self.subTest(changed=changed):
                candidate = state()
                if changed == "rule":
                    candidate["nft"] = candidate["nft"].removesuffix("COMMIT\n") + \
                        "-A KUBE-ROUTER-INPUT -s 203.0.113.7 -j ACCEPT\nCOMMIT\n"
                else:
                    candidate["ipset"] += ("create KUBE-SRC-DDDDDDDDDDDDDDDD hash:ip "
                                            "family inet hashsize 1024 maxelem 65536\n")
                with self.assertRaisesRegex(ValueError, "ownership snapshot"):
                    SUT["require_ownership"](ownership, placement, candidate,
                                             "a" * 40, "zimaboard-1")

    def test_enforcer_daemonset_must_be_absent_even_if_zero_scheduled(self):
        canary = SUT["CANARY"]
        node = {"metadata": {"uid": "uid", "labels": {canary: "true"}},
                "status": {"nodeInfo": {"bootID": "boot"},
                           "conditions": [{"type": "Ready", "status": "True"}]},
                "spec": {"taints": [{"key": canary, "value": "true",
                                     "effect": "NoSchedule"}]}}
        placement = {"nodeUid": "uid", "bootID": "boot"}
        with patch.dict(SUT["inspect_cluster"].__globals__, {
                "kubernetes_json": lambda *args: node if "node" in args else
                {"metadata": {}, "items": []},
                "command": lambda *args: '{"status":{"desiredNumberScheduled":0}}'}, clear=False):
            with self.assertRaisesRegex(ValueError, "DaemonSet still exists"):
                SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}}, placement)

    def test_fixture_namespace_must_be_gone_before_firewall_review_or_cleanup(self):
        canary, cleanup = SUT["CANARY"], SUT["CLEANUP"]
        node = {"metadata": {"uid": "uid", "labels": {canary: "true"}},
                "status": {"nodeInfo": {"bootID": "boot"},
                           "conditions": [{"type": "Ready", "status": "True"}]},
                "spec": {"taints": [{"key": canary, "value": "true",
                                     "effect": "NoSchedule"}]}}
        daemonset = {"metadata": {"name": cleanup, "uid": "ds-uid"},
                     "status": {"desiredNumberScheduled": 1, "numberReady": 1},
                     "spec": {"selector": {"matchLabels": {"app.kubernetes.io/name": cleanup}},
                              "template": {"spec": {
                                  "nodeSelector": {canary: "true"},
                                  "automountServiceAccountToken": False,
                                  "hostNetwork": True,
                                  "containers": [{"image": SUT["IMAGE"],
                                                  "command": ["/bin/sh", "-c"],
                                                  "args": ["sleep 86400"],
                                                  "securityContext": {"privileged": True}}]}}}}
        pod = {"metadata": {"namespace": "kube-system", "name": "cleanup-pod",
                            "uid": "pod-uid", "ownerReferences": [{"kind": "DaemonSet",
                            "name": cleanup, "uid": "ds-uid", "controller": True}]},
               "status": {"conditions": [{"type": "Ready", "status": "True"}]},
               "spec": {"nodeName": "zimaboard-1", "hostNetwork": True,
                        "containers": [{"image": SUT["IMAGE"]}]}}
        system = {"metadata": {"namespace": "kube-system", "name": "flannel-pod",
                               "uid": "system-uid", "ownerReferences": [{"kind": "DaemonSet",
                               "name": "flannel", "controller": True}]},
                  "spec": {"nodeName": "zimaboard-1"}}
        placement = {"nodeUid": "uid", "bootID": "boot", "systemDaemonSetPods": [
            {"namespace": "kube-system", "name": "flannel-pod", "uid": "system-uid"}]}
        fixture = {"kind": "Pod", "metadata": {
            "name": "npq-client", "namespace": SUT["FIXTURE_NAMESPACE"]},
            "status": {"phase": "Running"}}
        for namespace, fixture_items, expected_error in (
                ('{"kind":"Namespace"}', [], "fixture namespace must be absent"),
                ("", [fixture], "fixture workload still exists"),
                ("", [], None)):
            with self.subTest(namespace_present=bool(namespace),
                              fixture_present=bool(fixture_items)):
                responses = iter((node, {"metadata": {}, "items": fixture_items},
                                  {"metadata": {}, "items": []}, daemonset,
                                  {"metadata": {}, "items": [pod]},
                                  {"metadata": {}, "items": [system, pod]}))
                def command(*args):
                    if "namespace" in args:
                        self.assertIn("--ignore-not-found", args)
                        return namespace
                    return ""
                with patch.dict(SUT["inspect_cluster"].__globals__, {
                        "kubernetes_json": lambda *args: next(responses),
                        "command": command}):
                    if expected_error:
                        with self.assertRaisesRegex(ValueError, expected_error):
                            SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}},
                                                   placement)
                    else:
                        self.assertEqual(
                            SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}},
                                                   placement), ("cleanup-pod", "pod-uid"))
        foreign = {"metadata": {"namespace": "default", "name": "tolerating-app",
                                "uid": "foreign-uid", "ownerReferences": [{
                                    "kind": "ReplicaSet", "name": "app"}]},
                   "spec": {"nodeName": "zimaboard-1"}}
        responses = iter((node, {"metadata": {}, "items": []},
                          {"metadata": {}, "items": []}, daemonset,
                          {"metadata": {}, "items": [pod]}, {"metadata": {},
                                             "items": [system, pod, foreign]}))
        with patch.dict(SUT["inspect_cluster"].__globals__, {
                "kubernetes_json": lambda *args: next(responses),
                "command": lambda *args: ""}):
            with self.assertRaisesRegex(ValueError, "unreviewed Pod"):
                SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}}, placement)

    def test_canary_node_inventory_rejects_unreviewed_or_incomplete_pods(self):
        cleanup = {"metadata": {"namespace": "kube-system", "name": "cleanup-pod",
                                "uid": "cleanup-uid", "ownerReferences": [{
                                    "kind": "DaemonSet", "name": SUT["CLEANUP"],
                                    "uid": "cleanup-ds-uid", "controller": True}]},
                   "spec": {"nodeName": "zimaboard-1"}}
        system = {"metadata": {"namespace": "kube-system", "name": "flannel-pod",
                               "uid": "system-uid", "ownerReferences": [{
                                   "kind": "DaemonSet", "name": "flannel",
                                   "controller": True}]},
                  "spec": {"nodeName": "zimaboard-1"}}
        placement = {"systemDaemonSetPods": [{"namespace": "kube-system",
                                               "name": "flannel-pod", "uid": "system-uid"}]}
        foreign = {"metadata": {"namespace": "default", "name": "tolerating-app",
                                "uid": "foreign-uid", "ownerReferences": [{
                                    "kind": "ReplicaSet", "name": "app"}]},
                   "spec": {"nodeName": "zimaboard-1", "tolerations": [{
                       "key": SUT["CANARY"], "operator": "Exists"}]}}
        cases = (({"metadata": {}, "items": [system, cleanup]}, True),
                 ({"metadata": {}, "items": [system, cleanup, foreign]}, False),
                 ({"metadata": {}, "items": [cleanup]}, False),
                 ({"metadata": {}, "items": [system | {"metadata": system["metadata"] |
                            {"uid": "replacement"}}, cleanup]}, False),
                 ({"items": [system, cleanup], "metadata": {"continue": "next"}}, False),
                 ({"items": [system, cleanup]}, False),
                 ({"metadata": {}}, False))
        for listing, allowed in cases:
            with self.subTest(listing=listing):
                def inventory(*args):
                    self.assertIn("--chunk-size=0", args)
                    self.assertIn("spec.nodeName=zimaboard-1", args)
                    return listing
                with patch.dict(SUT["require_reviewed_node_pods"].__globals__, {
                        "kubernetes_json": inventory}):
                    if allowed:
                        SUT["require_reviewed_node_pods"](
                            "zimaboard-1", placement, cleanup, "cleanup-ds-uid")
                    else:
                        with self.assertRaisesRegex(ValueError, "canary node"):
                            SUT["require_reviewed_node_pods"](
                                "zimaboard-1", placement, cleanup, "cleanup-ds-uid")

    def test_unknown_prefix_other_backend_and_nonfilter_reference_block(self):
        for field, value in (("nft", ":KUBE-POD-FW-UNKNOWN - [0:0]\n"),
                             ("legacy", ":KUBE-ROUTER-INPUT - [0:0]\n"),
                             ("ip6nft", f"-A INPUT -j {PREFIX}\n"),
                             ("nft", f"-A PREROUTING -j {PREFIX}\n")):
            with self.subTest(field=field, value=value):
                candidate = state()
                if "PREROUTING" in value:
                    candidate[field] = candidate[field].replace("-A PREROUTING -j KUBE-SERVICES\n",
                                                                 value)
                else:
                    candidate[field] = candidate[field].replace("COMMIT\n", value + "COMMIT\n", 1)
                with self.assertRaises(ValueError):
                    SUT["cleanup_plan"](candidate)

    def test_ipv6_owned_ipset_and_foreign_set_block(self):
        candidate = state()
        candidate["ipset"] += "create inet6:KUBE-SRC-DDDDDDDDDDDDDDDD hash:ip family inet6\n"
        with self.assertRaises(ValueError):
            SUT["cleanup_plan"](candidate)
        candidate = state()
        candidate["ipset"] = candidate["ipset"].replace("family inet", "family inet6", 1)
        with self.assertRaises(ValueError):
            SUT["cleanup_plan"](candidate)
        candidate = state()
        candidate["ipset"] += ("create foreign-list list:set family inet\n"
                               f"add foreign-list {SET}\n")
        with self.assertRaises(ValueError):
            SUT["cleanup_plan"](candidate)
        candidate = state()
        candidate["nft"] = candidate["nft"].replace(f"--match-set {SET}",
                                                    "--match-set foreign-set")
        with self.assertRaises(ValueError):
            SUT["cleanup_plan"](candidate)

    def test_active_enterprise_objects_block_but_legacy_reader_does_not(self):
        SUT["ensure_quiesced"]([{
            "kind": "Pod", "metadata": {"namespace": "ai", "name": "openclaw-retirement-reader"},
            "status": {"phase": "Running"}}])
        for kind, spec, status in (("Pod", {}, {"phase": "Running"}),
                                   ("Deployment", {"replicas": 1}, {}),
                                   ("Job", {"completions": 1}, {"active": 0}),
                                   ("CronJob", {"suspend": False}, {})):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    SUT["ensure_quiesced"]([{
                        "kind": kind, "metadata": {"namespace": "openclaw-system",
                                                "name": "openclaw-enterprise-api"},
                        "spec": spec, "status": status}])


if __name__ == "__main__":
    unittest.main()
