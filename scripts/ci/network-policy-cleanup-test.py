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
            for name in (manifest, application, canary_manifest, canary_application):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True).stdout.strip()
            def commit(message):
                git("add", "-A")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", message)
                return git("rev-parse", "HEAD")
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
                prune_fixtures()
                wiki_update("openwiki/runbooks/runtime-isolation.md")
                wiki_update("openwiki/.last-update.json")
                fixture_sha = commit("fixture prune with reviewed wiki update")
                with self.assertRaisesRegex(ValueError, "two direct commits"):
                    transition(qualify_sha, fixture_sha)
                prune_firewall()
                (root / "unrelated.txt").write_text("drift\n")
                drift_sha = commit("firewall prune with unrelated change")
                with self.assertRaisesRegex(ValueError, "firewall removal differs"):
                    transition(qualify_sha, drift_sha)
                git("reset", "--hard", fixture_sha)
                prune_firewall()
                wiki_update("openwiki/workloads/inventory.md")
                wiki_update("openwiki/.claims/workloads/inventory.json")
                wiki_update("openwiki/.page-manifest.json")
                removal_sha = commit("firewall prune with reviewed wiki update")
                transition(qualify_sha, removal_sha)
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "unrelated", "--allow-empty")
                with self.assertRaisesRegex(ValueError, "two direct commits"):
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
                "kubernetes_json": lambda *args: node if "node" in args else {"items": []},
                "command": lambda *args: "" if "namespace" in args else
                '{"status":{"desiredNumberScheduled":0}}'}, clear=False):
            with self.assertRaisesRegex(ValueError, "DaemonSet still exists"):
                SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}}, placement)

    def test_live_canary_fixture_must_be_absent_before_ownership_snapshot(self):
        canary = SUT["CANARY"]
        node = {"metadata": {"uid": "uid", "labels": {canary: "true"}},
                "status": {"nodeInfo": {"bootID": "boot"},
                           "conditions": [{"type": "Ready", "status": "True"}]},
                "spec": {"taints": [{"key": canary, "value": "true",
                                     "effect": "NoSchedule"}]}}
        placement = {"nodeUid": "uid", "bootID": "boot"}
        fixture_pod = {"kind": "Pod", "metadata": {
            "name": "npq-client", "namespace": SUT["FIXTURE_NAMESPACE"]},
            "status": {"phase": "Running"}}
        for namespace, workloads, message in (
                ('{"kind":"Namespace"}', [], "fixture namespace still exists"),
                ("", [fixture_pod], "fixture workload still exists")):
            with self.subTest(message=message):
                def command(*args):
                    if "namespace" in args:
                        return namespace
                    self.fail("inspection passed fixture absence gate")
                with patch.dict(SUT["inspect_cluster"].__globals__, {
                        "kubernetes_json": lambda *args: node if "node" in args else
                        {"items": workloads}, "command": command}, clear=False):
                    with self.assertRaisesRegex(ValueError, message):
                        SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}},
                                               placement)

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
