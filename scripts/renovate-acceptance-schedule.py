#!/usr/bin/env python3
"""Aggregate private hourly Renovate schedule evidence for SC-001.

This deliberately does not collect or attest Kubernetes evidence. A reviewer
must check the source files before treating a numerically passing report as
acceptance.
"""

import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


UTC_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXCLUSION_KINDS = {"maintenance", "cluster-outage", "github-outage", "registry-outage"}
WINDOW = timedelta(days=7)
HOUR = timedelta(hours=1)
DEADLINE = timedelta(minutes=15)


class EvidenceError(ValueError):
    """Private evidence is incomplete or ambiguous."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate-json-key")
        result[key] = value
    return result


def utc(value):
    if not isinstance(value, str) or not UTC_TIME.fullmatch(value):
        raise EvidenceError("invalid-utc-time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise EvidenceError("invalid-utc-time") from error
    return parsed.astimezone(timezone.utc)


def evidence_file(root, reference, kind, slot_at, claim):
    if not isinstance(reference, dict) or set(reference) != {"source", "sha256"}:
        raise EvidenceError("missing-source-reference")
    source, digest = reference["source"], reference["sha256"]
    if (not isinstance(source, str) or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)):
        raise EvidenceError("invalid-source-reference")
    relative = Path(source)
    if (len(relative.parts) != 2 or relative.parts[0] != "evidence"
            or relative.is_absolute() or relative.name in {".", ".."}
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", relative.name)):
        raise EvidenceError("invalid-source-path")
    directory = root / "evidence"
    path = directory / relative.name
    try:
        directory_mode = directory.lstat().st_mode
        file_stat = path.lstat()
    except OSError as error:
        raise EvidenceError("missing-source-file") from error
    if (not stat.S_ISDIR(directory_mode) or stat.S_IMODE(directory_mode) != 0o700
            or not stat.S_ISREG(file_stat.st_mode)
            or stat.S_IMODE(file_stat.st_mode) != 0o600):
        raise EvidenceError("unsafe-source-file")
    if file_stat.st_size > 16 * 1024 * 1024:
        raise EvidenceError("oversize-source-file")
    with path.open("rb") as handle:
        data = handle.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise EvidenceError("oversize-source-file")
    if hashlib.sha256(data).hexdigest() != digest:
        raise EvidenceError("source-hash-mismatch")
    try:
        proof = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError("unreadable-source-file") from error
    if (not isinstance(proof, dict) or set(proof) != {
            "schema", "kind", "slotAt", "claim", "material"}
            or type(proof["schema"]) is not int or proof["schema"] != 1
            or proof["kind"] != kind or proof["slotAt"] != slot_at
            or proof["claim"] != claim or not isinstance(proof["material"], dict)
            or not proof["material"]):
        raise EvidenceError("source-claim-mismatch")


def evaluate(document, root):
    if not isinstance(document, dict) or set(document) != {
            "schema", "windowStart", "windowEnd", "slots"} or type(document["schema"]) is not int \
            or document["schema"] != 1:
        raise EvidenceError("invalid-document")
    start, end = utc(document["windowStart"]), utc(document["windowEnd"])
    if start.minute or start.second or start.microsecond or end - start != WINDOW:
        raise EvidenceError("invalid-window")
    slots = document["slots"]
    if not isinstance(slots, list) or len(slots) != 168:
        raise EvidenceError("missing-slot-evidence")

    expected = {start + index * HOUR for index in range(168)}
    seen_slots = set()
    seen_sources = set()
    seen_jobs = set()
    seen_pods = set()
    intervals = []
    counts = {"planned": 168, "excluded": 0, "timely": 0, "late": 0,
              "missing": 0, "failed": 0, "duplicateCycles": 0, "overlaps": 0}

    for slot in slots:
        if not isinstance(slot, dict) or not {"slotAt", "collectedAt", "collection", "runs"} <= set(slot) \
                or set(slot) - {"slotAt", "collectedAt", "collection", "runs", "exclusion"}:
            raise EvidenceError("invalid-slot-evidence")
        slot_at, collected_at = utc(slot["slotAt"]), utc(slot["collectedAt"])
        if slot_at not in expected or slot_at in seen_slots:
            raise EvidenceError("duplicate-or-outside-slot")
        seen_slots.add(slot_at)
        if collected_at < slot_at + HOUR:
            raise EvidenceError("premature-collection")
        collection = slot["collection"]

        exclusion = slot.get("exclusion")
        if exclusion is not None:
            if (not isinstance(exclusion, dict) or set(exclusion) != {
                    "kind", "impact", "reviewedAt", "source", "sha256"}
                    or not isinstance(exclusion["kind"], str)
                    or exclusion["kind"] not in EXCLUSION_KINDS
                    or not isinstance(exclusion["impact"], str)
                    or not exclusion["impact"].strip()):
                raise EvidenceError("invalid-exclusion")
            if utc(exclusion["reviewedAt"]) < slot_at + HOUR:
                raise EvidenceError("premature-exclusion-review")
            evidence_file(root, {"source": exclusion["source"],
                                 "sha256": exclusion["sha256"]},
                          "slot-exclusion", slot["slotAt"],
                          {"kind": exclusion["kind"], "impact": exclusion["impact"],
                           "reviewedAt": exclusion["reviewedAt"]})
            if exclusion["source"] in seen_sources:
                raise EvidenceError("reused-source-file")
            seen_sources.add(exclusion["source"])
            counts["excluded"] += 1

        runs = slot["runs"]
        if not isinstance(runs, list):
            raise EvidenceError("invalid-runs")
        evidence_file(root, collection, "slot-collection", slot["slotAt"],
                      {"collectedAt": slot["collectedAt"], "runs": runs})
        if collection["source"] in seen_sources:
            raise EvidenceError("reused-source-file")
        seen_sources.add(collection["source"])
        if len(runs) > 1 and exclusion is None:
            counts["duplicateCycles"] += len(runs) - 1
        if not runs and exclusion is None:
            counts["missing"] += 1
        starts = []
        for run in runs:
            if not isinstance(run, dict) or set(run) != {
                    "jobUid", "podUid", "discoveryStartedAt", "finishedAt", "phase"}:
                raise EvidenceError("invalid-run")
            job, pod = run["jobUid"], run["podUid"]
            if (not isinstance(job, str) or not job or not isinstance(pod, str) or not pod
                    or job in seen_jobs or pod in seen_pods):
                raise EvidenceError("duplicate-or-missing-identity")
            seen_jobs.add(job)
            seen_pods.add(pod)
            began, finished = utc(run["discoveryStartedAt"]), utc(run["finishedAt"])
            if (began < slot_at or finished <= began or finished > collected_at
                    or not isinstance(run["phase"], str)
                    or run["phase"] not in {"succeeded", "failed"}):
                raise EvidenceError("invalid-run-interval")
            intervals.append((began, finished))
            if exclusion is None:
                if run["phase"] == "failed":
                    counts["failed"] += 1
                starts.append(began)
        if starts:
            if min(starts) <= slot_at + DEADLINE:
                counts["timely"] += 1
            else:
                counts["late"] += 1

    if seen_slots != expected:
        raise EvidenceError("missing-slot-evidence")
    intervals.sort()
    latest_end = None
    for began, finished in intervals:
        if latest_end is not None and began < latest_end:
            counts["overlaps"] += 1
        latest_end = max(latest_end, finished) if latest_end else finished

    denominator = counts["planned"] - counts["excluded"]
    counts["denominator"] = denominator
    counts["ratePercentFloor"] = counts["timely"] * 10000 // denominator / 100 \
        if denominator else None
    if not denominator or counts["failed"]:
        counts["status"] = "inconclusive"
    elif (counts["timely"] * 100 < denominator * 95 or counts["overlaps"]
          or counts["duplicateCycles"]):
        counts["status"] = "criteria-not-met"
    else:
        counts["status"] = "review-required"
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_file", type=Path,
                        help="mode-0600 JSON record beside protected evidence/")
    args = parser.parse_args(argv)
    try:
        mode = args.private_file.lstat().st_mode
        if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o600:
            raise EvidenceError("unsafe-private-file")
        if args.private_file.stat().st_size > 16 * 1024 * 1024:
            raise EvidenceError("oversize-private-file")
        document = json.loads(args.private_file.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_object)
        report = evaluate(document, args.private_file.parent)
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceError) as error:
        code = str(error) if isinstance(error, EvidenceError) else "unreadable-private-evidence"
        report = {"status": "inconclusive", "reason": code}
    print(json.dumps(report, sort_keys=True))
    return {"review-required": 0, "criteria-not-met": 1, "inconclusive": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
