#!/usr/bin/env python3
"""Exercise delivery decisions and interruption-safe branch ownership."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("delivery", Path(__file__).resolve().parents[1] / "pr-delivery.py")
DELIVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DELIVERY)
HEAD = "a" * 40
BASE = "b" * 40


def pull(number, **changes):
    value = {"number": number, "body": "", "state": "open", "draft": False,
             "head": {"ref": f"branch-{number}", "sha": HEAD,
                      "repo": {"full_name": DELIVERY.REPO}},
             "base": {"ref": "main", "sha": BASE}, "merged_at": None,
             "mergeable": True, "mergeable_state": "clean", "checks": {"gate": "success"}}
    value.update(changes)
    return value


def snapshot(*prs):
    return {"required_checks": [{"context": "gate", "integration_id": 1}],
            "pull_requests": list(prs)}


class DeliveryTests(unittest.TestCase):
    def actions(self, data, roots=None, records=None):
        return DELIVERY.make_plan(data, roots, records)["actions"]

    def test_conflicting_draft_ancestor_is_repaired_before_child(self):
        parent = pull(1, draft=True, mergeable=False)
        child = pull(2, base={"ref": "branch-1", "sha": HEAD})
        rows = self.actions(snapshot(child, parent, pull(3)), [2])
        self.assertEqual([(r["number"], r["action"]) for r in rows],
                         [(1, "repair-conflicts"), (2, "wait-parent")])

    def test_parent_merge_restacks_child_then_refreshes_checks(self):
        parent = pull(1, state="closed", merged_at="2026-11-01")
        child = pull(2, base={"ref": "branch-1", "sha": HEAD})
        self.assertEqual(self.actions(snapshot(parent, child), [2])[0]["action"], "restack")
        child["base"] = {"ref": "main", "sha": BASE}
        child["checks"] = {}
        self.assertEqual(self.actions(snapshot(parent, child), [2])[0]["action"], "inspect-missing-checks")
        child["checks"] = {"gate": "success"}
        self.assertEqual(self.actions(snapshot(parent, child), [2])[0]["action"], "verify-and-merge")

    def test_failed_pending_missing_and_recovered_checks(self):
        for checks, expected in [({"gate": "failure"}, "repair-checks"),
                                 ({"gate": "queued"}, "wait-checks"),
                                 ({}, "inspect-missing-checks"),
                                 ({"gate": "success"}, "verify-and-merge")]:
            with self.subTest(checks=checks):
                self.assertEqual(self.actions(snapshot(pull(1, checks=checks)))[0]["action"], expected)

    def test_draft_and_explicit_hold_never_become_merge_candidates(self):
        self.assertEqual(self.actions(snapshot(pull(1, draft=True)))[0]["action"], "review-draft")
        self.assertEqual(self.actions(snapshot(pull(1, labels=[{"name": "delivery/hold"}])))[0]["action"], "external-hold")

    def test_cycles_missing_closed_and_malformed_dependencies_stop(self):
        cases = [snapshot(pull(1, body="Depends-On: #2"), pull(2, body="Depends-On: #1")),
                 snapshot(pull(1, body="Depends-On: #2")),
                 snapshot(pull(1, body="Depends-On: #2"), pull(2, state="closed")),
                 snapshot(pull(1, body="Depends-On: $(touch /tmp/unsafe)"))]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.actions(case)

    def test_merge_into_feature_branch_is_not_delivery_to_main(self):
        parent = pull(1, state="closed", merged_at="2026-11-01",
                      base={"ref": "another-feature", "sha": BASE})
        child = pull(2, body="Depends-On: #1")
        with self.assertRaisesRegex(ValueError, "merged off main"):
            self.actions(snapshot(parent, child), [2])

    def test_other_mentions_do_not_create_dependencies(self):
        self.assertEqual(len(self.actions(snapshot(pull(1, body="Compare #999. `$(anything)`")))), 1)

    def test_fork_unknown_base_and_missing_rules_are_not_ready(self):
        fork = pull(1)
        fork["head"]["repo"] = None
        self.assertEqual(self.actions(snapshot(fork))[0]["action"], "inspect-fork")
        with self.assertRaises(ValueError):
            self.actions(snapshot(pull(1, base={"ref": "unknown", "sha": BASE})))
        with self.assertRaises(ValueError):
            self.actions({"pull_requests": [pull(1)], "required_checks": []})

    def test_checkpoint_survives_restart_and_prevents_competing_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            DELIVERY.checkpoint(directory, 1, HEAD, "owner-a", "wait for gate", "CI", HEAD, BASE)
            saved = json.loads((directory / "state.json").read_text())
            self.assertEqual(saved["1"]["next_action"], "wait for gate")
            with self.assertRaises(ValueError):
                DELIVERY.checkpoint(directory, 1, HEAD, "owner-b", "edit", "none", HEAD, BASE)
            self.assertEqual(json.loads((directory / "state.json").read_text()), saved)
            with self.assertRaises(ValueError):
                DELIVERY.release(directory, 1, "owner-b")
            DELIVERY.release(directory, 1, "owner-a")
            DELIVERY.checkpoint(directory, 1, HEAD, "owner-b", "edit", "none", HEAD, BASE)

    def test_stale_head_refuses_checkpoint_and_marks_old_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(ValueError):
                DELIVERY.checkpoint(directory, 1, HEAD, "owner", "merge", "none", "c" * 40)
            self.assertFalse((directory / "state.json").exists())
        row = self.actions(snapshot(pull(1)), records={"1": {"head": "c" * 40, "base": BASE}})[0]
        self.assertTrue(row["checkpoint_stale"])

    def test_same_name_status_and_check_must_both_pass(self):
        for status, check, expected in [
            ("success", "failure", "repair-checks"),
            ("failure", "success", "repair-checks"),
            ("pending", "failure", "repair-checks"),
            ("failure", "in_progress", "repair-checks"),
            ("success", "in_progress", "wait-checks"),
            ("pending", "success", "wait-checks"),
            ("success", "success", "verify-and-merge"),
        ]:
            pr = pull(1)
            run = {"id": 2, "name": "gate", "conclusion": None if check == "in_progress" else check,
                   "status": check}
            older = {"id": 1, "name": "gate", "conclusion": "failure", "status": "completed"}
            responses = [[pr], pr, [{"context": "gate", "state": status}],
                         [{"type": "required_status_checks", "parameters": {
                             "required_status_checks": [{"context": "gate"}]}}]]
            with self.subTest(status=status, check=check), \
                    patch.object(DELIVERY, "api", side_effect=responses), \
                    patch.object(DELIVERY, "command", return_value=json.dumps([{"check_runs": [older, run]}])):
                self.assertEqual(self.actions(DELIVERY.live_snapshot([1]))[0]["action"], expected)

    def test_fetches_pages_and_rejects_head_changed_during_inspection(self):
        with patch.object(DELIVERY, "command", return_value='[[1,2],[3]]') as command:
            self.assertEqual(DELIVERY.api("pulls", True), [1, 2, 3])
            self.assertIn("--paginate", command.call_args.args)
        old, new = pull(1), pull(1)
        new["head"] = copy.deepcopy(new["head"])
        new["head"]["sha"] = "c" * 40
        with patch.object(DELIVERY, "api", side_effect=[[old], new]), self.assertRaises(ValueError):
            DELIVERY.live_snapshot([1])


if __name__ == "__main__":
    unittest.main()
