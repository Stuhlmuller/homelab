#!/usr/bin/env python3
"""Offline contract tests for the private SC-001 hourly slot evaluator."""

import copy
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/renovate-acceptance-schedule.py"
SPEC = importlib.util.spec_from_file_location("renovate_schedule", SCRIPT)
SCHEDULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEDULE)
START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


class Schedule(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="renovate-schedule-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "evidence"
        source.mkdir(mode=0o700)
        self.doc = self.make_document()
        self.refresh_sources()

    def make_document(self):
        slots = []
        for index in range(168):
            at = START + timedelta(hours=index)
            slots.append({
                "slotAt": timestamp(at),
                "collectedAt": timestamp(at + timedelta(hours=1, minutes=1)),
                "collection": {},
                "runs": [{
                    "jobUid": f"job-{index}",
                    "podUid": f"pod-{index}",
                    "jobStartedAt": timestamp(at + timedelta(minutes=1)),
                    "discoveryCompletedAt": timestamp(at + timedelta(minutes=6)),
                    "finishedAt": timestamp(at + timedelta(minutes=10)),
                    "phase": "succeeded",
                }],
            })
        return {"schema": 1, "windowStart": timestamp(START),
                "windowEnd": timestamp(START + timedelta(days=7)), "slots": slots}

    def refresh_sources(self):
        for index, slot in enumerate(self.doc["slots"]):
            def source(name, kind, claim):
                path = self.root / "evidence" / name
                body = {"schema": 1, "kind": kind, "slotAt": slot["slotAt"],
                        "claim": claim, "material": {"readOnlySource": "test-fixture"}}
                data = json.dumps(body, sort_keys=True).encode()
                path.write_bytes(data)
                path.chmod(0o600)
                return {"source": f"evidence/{name}",
                        "sha256": hashlib.sha256(data).hexdigest()}

            slot["collection"] = source(f"slot-{index}.json", "slot-collection",
                                        {"collectedAt": slot["collectedAt"],
                                         "runs": slot["runs"]})
            if "exclusion" in slot:
                exclusion = slot["exclusion"]
                exclusion.update(source(f"exclusion-{index}.json", "slot-exclusion",
                                        {key: exclusion[key] for key in
                                         ("kind", "impact", "reviewedAt")}))

    def evaluate(self):
        self.refresh_sources()
        return SCHEDULE.evaluate(self.doc, self.root)

    def exclude(self, index, kind="maintenance"):
        self.doc["slots"][index]["exclusion"] = {
            "kind": kind,
            "impact": "Reviewed unavailable hourly discovery window",
            "reviewedAt": timestamp(START + timedelta(hours=index + 1)),
        }

    def test_exact_fifteen_minute_boundary_is_timely(self):
        slot = self.doc["slots"][0]
        slot["runs"][0]["discoveryCompletedAt"] = timestamp(START + timedelta(minutes=15))
        slot["runs"][0]["finishedAt"] = timestamp(START + timedelta(minutes=20))
        report = self.evaluate()
        self.assertEqual((report["planned"], report["denominator"], report["timely"]),
                         (168, 168, 168))
        self.assertEqual(report["status"], "review-required")

    def test_completion_after_deadline_without_exact_start_is_inconclusive(self):
        self.doc["slots"][0]["runs"][0]["discoveryCompletedAt"] = timestamp(
            START + timedelta(minutes=15, seconds=1))
        self.doc["slots"][0]["runs"][0]["finishedAt"] = timestamp(
            START + timedelta(minutes=20))
        report = self.evaluate()
        self.assertEqual((report["timely"], report["unknown"]), (167, 1))
        self.assertEqual(report["status"], "inconclusive")

    def test_exact_late_start_is_counted_late(self):
        run = self.doc["slots"][0]["runs"][0]
        run["discoveryStartedAt"] = timestamp(START + timedelta(minutes=15, seconds=1))
        run["discoveryCompletedAt"] = timestamp(START + timedelta(minutes=16))
        run["finishedAt"] = timestamp(START + timedelta(minutes=20))
        report = self.evaluate()
        self.assertEqual((report["timely"], report["late"], report["unknown"]),
                         (167, 1, 0))

    def test_exact_on_time_start_with_late_completion_is_timely(self):
        run = self.doc["slots"][0]["runs"][0]
        run["discoveryStartedAt"] = timestamp(START + timedelta(minutes=15))
        run["discoveryCompletedAt"] = timestamp(START + timedelta(minutes=16))
        run["finishedAt"] = timestamp(START + timedelta(minutes=20))
        report = self.evaluate()
        self.assertEqual((report["timely"], report["unknown"]), (168, 0))

    def test_integer_ninety_five_percent_threshold(self):
        for index in range(8):
            self.doc["slots"][index]["runs"] = []
        report = self.evaluate()
        self.assertEqual((report["timely"], report["missing"]), (160, 8))
        self.assertEqual(report["status"], "review-required")
        self.doc["slots"][8]["runs"] = []
        report = self.evaluate()
        self.assertEqual((report["timely"], report["missing"]), (159, 9))
        self.assertEqual(report["status"], "criteria-not-met")

    def test_exact_ninety_five_percent_after_exclusions(self):
        for index in range(148):
            self.exclude(index)
        self.doc["slots"][148]["runs"] = []
        report = self.evaluate()
        self.assertEqual((report["denominator"], report["timely"], report["missing"]),
                         (20, 19, 1))
        self.assertEqual(report["status"], "review-required")
        self.doc["slots"][149]["runs"] = []
        self.assertEqual(self.evaluate()["status"],
                         "criteria-not-met")

    def test_missing_run_is_failure_but_missing_slot_evidence_is_inconclusive(self):
        self.doc["slots"][7]["runs"] = []
        self.assertEqual(self.evaluate()["missing"], 1)
        del self.doc["slots"][7]
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "missing-slot-evidence"):
            self.evaluate()

    def test_duplicate_slot_or_job_identity_is_ambiguous(self):
        self.doc["slots"][2] = copy.deepcopy(self.doc["slots"][1])
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "duplicate-or-outside-slot"):
            self.evaluate()
        self.doc = self.make_document()
        self.doc["slots"][2]["runs"][0]["jobUid"] = "job-1"
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "duplicate-or-missing-identity"):
            self.evaluate()

    def test_two_nonoverlapping_cycles_in_one_slot_fail(self):
        second = copy.deepcopy(self.doc["slots"][0]["runs"][0])
        second.update({"jobUid": "extra-job", "podUid": "extra-pod",
                       "jobStartedAt": timestamp(START + timedelta(minutes=19)),
                       "discoveryStartedAt": timestamp(START + timedelta(minutes=20)),
                       "discoveryCompletedAt": timestamp(START + timedelta(minutes=21)),
                       "finishedAt": timestamp(START + timedelta(minutes=25))})
        self.doc["slots"][0]["runs"].append(second)
        report = self.evaluate()
        self.assertEqual(report["duplicateCycles"], 1)
        self.assertEqual(report["overlaps"], 0)
        self.assertEqual(report["status"], "criteria-not-met")

    def test_overlap_across_slots_fails_even_if_one_is_excluded(self):
        first = self.doc["slots"][0]
        first["collectedAt"] = timestamp(START + timedelta(hours=2))
        first["runs"][0]["finishedAt"] = timestamp(START + timedelta(hours=1, minutes=7))
        self.exclude(0, "cluster-outage")
        report = self.evaluate()
        self.assertEqual((report["excluded"], report["denominator"], report["overlaps"]),
                         (1, 167, 1))
        self.assertEqual(report["status"], "criteria-not-met")

    def test_touching_discovery_intervals_do_not_overlap(self):
        first = self.doc["slots"][0]
        first["collectedAt"] = timestamp(START + timedelta(hours=2))
        first["runs"][0]["finishedAt"] = self.doc["slots"][1]["runs"][0][
            "jobStartedAt"]
        report = self.evaluate()
        self.assertEqual(report["overlaps"], 0)
        self.assertEqual(report["status"], "review-required")

    def test_excluded_outage_subtracts_denominator_and_requires_receipt(self):
        self.exclude(4, "github-outage")
        report = self.evaluate()
        self.assertEqual((report["planned"], report["excluded"], report["denominator"],
                          report["timely"]), (168, 1, 167, 167))
        self.assertEqual(report["status"], "review-required")
        self.doc["slots"][4]["exclusion"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "source-hash-mismatch"):
            SCHEDULE.evaluate(self.doc, self.root)

    def test_matching_hash_cannot_hide_a_mismatched_claim(self):
        reference = self.doc["slots"][0]["collection"]
        path = self.root / reference["source"]
        proof = json.loads(path.read_text())
        proof["claim"]["runs"] = []
        data = json.dumps(proof).encode()
        path.write_bytes(data)
        path.chmod(0o600)
        reference["sha256"] = hashlib.sha256(data).hexdigest()
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "source-claim-mismatch"):
            SCHEDULE.evaluate(self.doc, self.root)

    def test_missing_source_and_malformed_kind_are_inconclusive(self):
        (self.root / self.doc["slots"][0]["collection"]["source"]).unlink()
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "missing-source-file"):
            SCHEDULE.evaluate(self.doc, self.root)
        self.doc = self.make_document()
        self.exclude(0)
        self.doc["slots"][0]["exclusion"]["kind"] = []
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "invalid-exclusion"):
            self.evaluate()

    def test_all_excluded_and_failed_run_are_inconclusive(self):
        for index in range(168):
            self.exclude(index)
        self.assertEqual(self.evaluate()["status"], "inconclusive")
        self.doc = self.make_document()
        self.doc["slots"][0]["runs"][0]["phase"] = "failed"
        self.assertEqual(self.evaluate()["status"], "inconclusive")

    def test_gaps_non_utc_and_unfinished_run_are_ambiguous(self):
        self.doc["slots"][0]["collectedAt"] = timestamp(START + timedelta(minutes=59))
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "premature-collection"):
            self.evaluate()
        self.doc = self.make_document()
        self.doc["slots"][0]["runs"][0]["finishedAt"] = timestamp(START + timedelta(hours=2))
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "invalid-run-interval"):
            self.evaluate()
        self.doc = self.make_document()
        self.doc["windowStart"] = "2026-10-01T00:00:00+00:00"
        with self.assertRaisesRegex(SCHEDULE.EvidenceError, "invalid-utc-time"):
            self.evaluate()

    def test_cli_emits_aggregate_only_and_enforces_private_mode(self):
        private = self.root / "slots.json"
        private.write_text(json.dumps(self.doc), encoding="utf-8")
        private.chmod(0o600)
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(private)],
                                check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "review-required")
        self.assertNotIn("job-0", result.stdout)
        self.assertNotIn("evidence/", result.stdout)
        private.chmod(0o644)
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(private)],
                                check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "unsafe-private-file")

    def test_duplicate_json_key_is_inconclusive(self):
        private = self.root / "slots.json"
        private.write_text(json.dumps(self.doc).replace('"schema": 1,',
                        '"schema": 1, "schema": 1,', 1), encoding="utf-8")
        private.chmod(0o600)
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(private)],
                                check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "duplicate-json-key")


if __name__ == "__main__":
    unittest.main()
