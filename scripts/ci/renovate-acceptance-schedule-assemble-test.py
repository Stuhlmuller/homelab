#!/usr/bin/env python3
"""Offline continuity and log-binding tests for SC-001 snapshot assembly."""

import copy
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/renovate-acceptance-schedule-assemble.py"
SPEC = importlib.util.spec_from_file_location("schedule_assemble", SCRIPT)
ASSEMBLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSEMBLER)
START = datetime(2026, 10, 25, tzinfo=timezone.utc)
JOB = "11111111-1111-1111-1111-111111111111"
POD = "22222222-2222-2222-2222-222222222222"
CRON = "33333333-3333-3333-3333-333333333333"


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


class Assemble(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="renovate-assemble-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "schedule"
        self.source.mkdir(mode=0o700)
        (self.source / "snapshots").mkdir(mode=0o700)
        (self.source / "logs").mkdir(mode=0o700)
        self.snapshots = self.empty_snapshots()

    def empty_snapshots(self):
        snapshots = []
        for index in range(673):
            at = START + timedelta(minutes=5 + 15 * index)
            snapshots.append({
                "schema": 1,
                "startedAt": stamp(at),
                "finishedAt": stamp(at + timedelta(minutes=1)),
                "cronjob": {"uid": CRON, "resourceVersion": str(index + 1),
                            "generation": 1, "schedule": "0 * * * *",
                            "timeZone": "Etc/UTC", "suspend": False,
                            "concurrencyPolicy": "Forbid",
                            "startingDeadlineSeconds": 900,
                            "successfulJobsHistoryLimit": 3,
                            "failedJobsHistoryLimit": 3,
                            "lastScheduleTime": None},
                "jobsResourceVersion": str(index + 1),
                "podsResourceVersion": str(index + 1),
                "jobs": [], "pods": [],
            })
        return snapshots

    def add_job(self, *, failed=False, before_renovate=False, ambiguous=False):
        at = START
        started = stamp(at)
        finished = stamp(at + timedelta(minutes=4))
        log = ("2026-10-25T00:00:30.123456789Z  INFO: Renovate started\n"
               "2026-10-25T00:02:00.123456789Z  INFO: Autodiscovered repositories\n")
        if before_renovate:
            log = "2026-10-25T00:00:20Z  ERROR: App token failed\n"
        elif ambiguous:
            log = "2026-10-25T00:00:30.123456789Z  INFO: Renovate started\n"
        data = log.encode()
        digest = hashlib.sha256(data).hexdigest()
        name = f"{POD}-{digest}.log"
        log_path = self.source / "logs" / name
        log_path.write_bytes(data)
        log_path.chmod(0o600)
        markers = ASSEMBLER.log_markers(data)
        job = {"name": "renovate-29900000", "uid": JOB, "scheduledAt": started,
               "createdAt": started, "startedAt": started, "finishedAt": finished,
               "phase": "failed" if failed else "succeeded"}
        pod = {"name": "renovate-29900000-example", "uid": POD, "jobUid": JOB,
               "createdAt": started, "phase": "Failed" if failed else "Succeeded",
               "startedAt": started, "containerStartedAt": started,
               "log": {"file": f"logs/{name}", "sha256": digest,
                       "bytes": len(data), **markers}}
        for index in range(5):
            self.snapshots[index]["jobs"].append(copy.deepcopy(job))
            self.snapshots[index]["pods"].append(copy.deepcopy(pod))
        return log_path

    def write_snapshots(self):
        for index, snapshot in enumerate(self.snapshots):
            path = self.source / "snapshots" / f"capture-{index:04d}.json"
            path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
            path.chmod(0o600)

    def test_assembles_private_slot_evidence_from_complete_capture(self):
        self.add_job()
        self.write_snapshots()
        document, evidence = ASSEMBLER.build_document(self.source, START)
        self.assertEqual(len(document["slots"]), 168)
        self.assertEqual(len(evidence), 168)
        self.assertEqual(document["slots"][0]["runs"][0]["discoveryCompletedAt"],
                         "2026-10-25T00:02:00.123456Z")
        output = self.root / "assembled"
        report = ASSEMBLER.write_output(output, document, evidence)
        self.assertEqual((report["timely"], report["missing"], report["unknown"]),
                         (1, 167, 0))
        self.assertEqual(report["status"], "criteria-not-met")
        self.assertEqual(stat.S_IMODE((output / "slots.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((output / "evidence").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((output / "evidence/slot-000.json").stat().st_mode),
                         0o600)
        material = json.loads((output / "evidence/slot-000.json").read_text())["material"]
        self.assertEqual(len(material["snapshots"]), 5)
        self.assertEqual(material["prestartFailures"], [])

    def test_missing_capture_is_inconclusive(self):
        self.write_snapshots()
        (self.source / "snapshots/capture-0170.json").unlink()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError,
                                    "missing-fifteen-minute-snapshot"):
            ASSEMBLER.build_document(self.source, START)

    def test_duplicate_or_late_capture_is_inconclusive(self):
        self.write_snapshots()
        duplicate = self.source / "snapshots/duplicate.json"
        duplicate.write_text(json.dumps(self.snapshots[1]), encoding="utf-8")
        duplicate.chmod(0o600)
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "duplicate-snapshot"):
            ASSEMBLER.build_document(self.source, START)
        duplicate.unlink()
        self.snapshots[1]["startedAt"] = stamp(START + timedelta(minutes=25, seconds=1))
        self.snapshots[1]["finishedAt"] = stamp(START + timedelta(minutes=26))
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "late-snapshot"):
            ASSEMBLER.build_document(self.source, START)

    def test_changed_retained_log_is_inconclusive(self):
        log = self.add_job()
        self.write_snapshots()
        log.write_bytes(log.read_bytes() + b"changed")
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "changed-or-ambiguous-log"):
            ASSEMBLER.build_document(self.source, START)

    def test_output_is_atomic_when_source_claim_is_wrong(self):
        self.write_snapshots()
        document, evidence = ASSEMBLER.build_document(self.source, START)
        document["slots"][0]["collection"]["sha256"] = "0" * 64
        output = self.root / "assembled"
        with self.assertRaisesRegex(ASSEMBLER.SCHEDULE.EvidenceError,
                                    "source-hash-mismatch"):
            ASSEMBLER.write_output(output, document, evidence)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".assembled.*")), [])

    def test_prestart_failure_is_private_material_and_empty_run(self):
        self.add_job(failed=True, before_renovate=True)
        self.write_snapshots()
        document, evidence = ASSEMBLER.build_document(self.source, START)
        self.assertEqual(document["slots"][0]["runs"], [])
        proof = json.loads(evidence["slot-000.json"])
        self.assertEqual(proof["material"]["prestartFailures"][0]["jobUid"], JOB)
        self.assertEqual(proof["claim"]["runs"], [])

    def test_global_start_without_discovery_completion_is_ambiguous(self):
        self.add_job(failed=True, ambiguous=True)
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "ambiguous-discovery-marker"):
            ASSEMBLER.build_document(self.source, START)

    def test_changed_cronjob_identity_or_suspension_is_inconclusive(self):
        self.snapshots[200]["cronjob"]["uid"] = "other-uid"
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "changed-cronjob-identity"):
            ASSEMBLER.build_document(self.source, START)
        self.snapshots[200]["cronjob"]["uid"] = CRON
        self.snapshots[200]["cronjob"]["suspend"] = True
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "changed-or-suspended-cronjob"):
            ASSEMBLER.build_document(self.source, START)
        self.snapshots[200]["cronjob"]["suspend"] = False
        self.snapshots[200]["cronjob"]["generation"] = 2
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "changed-cronjob-identity"):
            ASSEMBLER.build_document(self.source, START)
        self.snapshots[200]["cronjob"]["generation"] = 1
        self.snapshots[200]["cronjob"]["failedJobsHistoryLimit"] = 0
        self.write_snapshots()
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "changed-or-suspended-cronjob"):
            ASSEMBLER.build_document(self.source, START)


if __name__ == "__main__":
    unittest.main()
