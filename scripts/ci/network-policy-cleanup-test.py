#!/usr/bin/env python3
"""Keep owned firewall rollback narrow across kube-router and foreign rules."""

import argparse
import runpy
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
    def test_unadmitted_config_refuses_before_any_cluster_command(self):
        with self.assertRaisesRegex(ValueError, "no admitted canary"):
            SUT["execute"](argparse.Namespace(
                config=ROOT / "scripts/config/platform-maintenance.json",
                expected_sha="0" * 40, receipt_dir=Path("/unused"), output=Path("/unused")))

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
        placement = {"format": 1, "verified": True, "sourceSha": source_sha,
                     "node": "zimaboard-1", "nodeUid": "uid", "bootID": "boot",
                     "firewallBaselineEmpty": True}
        checks = iter((source_sha, source_sha, "b" * 40))
        operations = []
        records = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            platform = SUT["PLATFORM"]
            replacements = {"validate_config": lambda _: {"canary": {"node": "zimaboard-1"}},
                            "current_main_sha": lambda: next(checks),
                            "private_directory": lambda value: value,
                            "private_output": lambda value: value,
                            "read_private_json": lambda value: placement if value.name ==
                            "placement.json" else {}}
            globals_ = {"command": lambda *args: source_sha,
                        "inspect_cluster": lambda *_: ("cleanup-pod", "pod-uid"),
                        "snapshot": lambda *_: {"backend": "nft", "nft": "snapshot"},
                        "cleanup_plan": lambda *_: ([("iptables-nft", "-D", "first"),
                                                     ("iptables-nft", "-F", "second")], 1, 0),
                        "require_ownership": lambda *_: None,
                        "exec_cleanup": lambda _pod, *args: operations.append(args),
                        "write_record": lambda _path, record, replace=False:
                        records.append(record.copy())}
            with patch.dict(platform, replacements), patch.dict(SUT["execute"].__globals__,
                                                             globals_):
                args = argparse.Namespace(config=ROOT / "scripts/config/platform-maintenance.json",
                                          expected_sha=source_sha, receipt_dir=path,
                                          output=path / "cleanup.json")
                with self.assertRaisesRegex(ValueError, "exact current main"):
                    SUT["execute"](args)
        self.assertEqual(operations, [("iptables-nft", "-D", "first")])
        self.assertEqual([record["status"] for record in records],
                         ["started", "interrupted"])

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
                "command": lambda *args: '{"status":{"desiredNumberScheduled":0}}'}, clear=False):
            with self.assertRaisesRegex(ValueError, "DaemonSet still exists"):
                SUT["inspect_cluster"]({"canary": {"node": "zimaboard-1"}}, placement)

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
