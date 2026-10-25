#!/usr/bin/env python3
"""Assemble private SC-001 slot evidence from retained read-only snapshots.

The input is the sealed acceptance schedule directory produced during the
window. This command never queries Kubernetes or a package service.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import timedelta
from pathlib import Path


SCRIPT = Path(__file__).with_name("renovate-acceptance-schedule.py")
SPEC = importlib.util.spec_from_file_location("renovate_schedule", SCRIPT)
SCHEDULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEDULE)

QUARTER = timedelta(minutes=15)
CAPTURE_OFFSET = timedelta(minutes=5)
CAPTURE_DEADLINE = timedelta(minutes=5)
CAPTURE_DURATION = timedelta(minutes=3)
HOUR = timedelta(hours=1)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LOG_PATH = re.compile(r"^logs/([0-9a-f-]{36})-([0-9a-f]{64})\.log$")
LOG_MARKER = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z)\s+INFO: "
    r"(Renovate started|Autodiscovered repositories)(?:\s|$)"
)


class AssemblyError(SCHEDULE.EvidenceError):
    """The read-only capture cannot support an exhaustive seven-day report."""


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def utc(value):
    try:
        return SCHEDULE.utc(value)
    except SCHEDULE.EvidenceError as error:
        raise AssemblyError("invalid-capture-time") from error


def checked_dir(path):
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise AssemblyError("missing-capture-directory") from error
    if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700:
        raise AssemblyError("unsafe-capture-directory")


def checked_bytes(path, maximum):
    try:
        info = path.lstat()
    except OSError as error:
        raise AssemblyError("missing-capture-file") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise AssemblyError("unsafe-capture-file")
    if info.st_size > maximum:
        raise AssemblyError("oversize-capture-file")
    try:
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
    except OSError as error:
        raise AssemblyError("unreadable-capture-file") from error
    if len(data) > maximum:
        raise AssemblyError("oversize-capture-file")
    return data


def checked_json(path):
    data = checked_bytes(path, 4 * 1024 * 1024)
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=SCHEDULE.unique_object)
    except (UnicodeError, json.JSONDecodeError, SCHEDULE.EvidenceError) as error:
        raise AssemblyError("invalid-capture-json") from error
    return value, hashlib.sha256(data).hexdigest()


def normalized_marker_time(value):
    if "." in value:
        prefix, fraction = value[:-1].split(".", 1)
        value = f"{prefix}.{fraction[:6]}Z"
    utc(value)
    return value


def log_markers(data):
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise AssemblyError("invalid-retained-log") from error
    global_times = []
    discovery_times = []
    for line in lines:
        match = LOG_MARKER.match(line)
        if match:
            at = normalized_marker_time(match[1])
            (global_times if match[2] == "Renovate started" else discovery_times).append(at)
    return {
        "globalStartedAt": global_times[0] if len(global_times) == 1 else None,
        "discoveryCompletedAt": discovery_times[0] if len(discovery_times) == 1 else None,
        "globalMarkerCount": len(global_times),
        "discoveryMarkerCount": len(discovery_times),
    }


def verify_log(schedule_dir, pod, cache):
    log = pod["log"]
    if log is None:
        return
    fields = {"file", "sha256", "bytes", "globalStartedAt", "discoveryCompletedAt",
              "globalMarkerCount", "discoveryMarkerCount"}
    if not isinstance(log, dict) or set(log) != fields:
        raise AssemblyError("invalid-log-reference")
    match = LOG_PATH.fullmatch(log["file"]) if isinstance(log["file"], str) else None
    if (not match or match[1] != pod["uid"] or not isinstance(log["sha256"], str)
            or not SHA256.fullmatch(log["sha256"]) or match[2] != log["sha256"]
            or type(log["bytes"]) is not int or log["bytes"] < 0):
        raise AssemblyError("invalid-log-reference")
    if log["file"] not in cache:
        data = checked_bytes(schedule_dir / log["file"], 16 * 1024 * 1024)
        cache[log["file"]] = (len(data), hashlib.sha256(data).hexdigest(),
                              log_markers(data))
    size, digest, markers = cache[log["file"]]
    if size != log["bytes"] or digest != log["sha256"] or markers != {
            key: log[key] for key in markers}:
        raise AssemblyError("changed-or-ambiguous-log")


def read_snapshots(schedule_dir, window_start):
    checked_dir(schedule_dir)
    snapshot_dir = schedule_dir / "snapshots"
    checked_dir(snapshot_dir)
    checked_dir(schedule_dir / "logs")
    first_capture = window_start + CAPTURE_OFFSET
    last_capture = first_capture + 672 * QUARTER
    selected = {}
    for path in sorted(snapshot_dir.glob("*.json")):
        snapshot, digest = checked_json(path)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("startedAt"), str):
            raise AssemblyError("invalid-snapshot")
        began = utc(snapshot["startedAt"])
        if began < first_capture or began >= last_capture + CAPTURE_DEADLINE:
            continue
        index = (began - first_capture) // QUARTER
        planned = first_capture + index * QUARTER
        if index > 672 or began > planned + CAPTURE_DEADLINE:
            raise AssemblyError("late-snapshot")
        if index in selected:
            raise AssemblyError("duplicate-snapshot")
        selected[index] = (snapshot, {"source": f"snapshots/{path.name}",
                                      "sha256": digest})
    if set(selected) != set(range(673)):
        raise AssemblyError("missing-fifteen-minute-snapshot")
    return selected


def validate_snapshot(snapshot, index, window_start):
    fields = {"schema", "startedAt", "finishedAt", "cronjob", "jobsResourceVersion",
              "podsResourceVersion", "jobs", "pods"}
    if not isinstance(snapshot, dict) or set(snapshot) != fields or type(snapshot["schema"]) is not int \
            or snapshot["schema"] != 1:
        raise AssemblyError("invalid-snapshot")
    planned = window_start + CAPTURE_OFFSET + index * QUARTER
    began, finished = utc(snapshot["startedAt"]), utc(snapshot["finishedAt"])
    if not planned <= began <= planned + CAPTURE_DEADLINE or not began <= finished <= began + CAPTURE_DURATION:
        raise AssemblyError("invalid-snapshot-time")
    cron = snapshot["cronjob"]
    if (not isinstance(cron, dict) or not {
            "uid", "schedule", "timeZone", "suspend", "concurrencyPolicy",
            "startingDeadlineSeconds", "successfulJobsHistoryLimit",
            "failedJobsHistoryLimit"} <= set(cron)
            or not isinstance(cron["uid"], str) or not cron["uid"]
            or type(cron.get("generation")) is not int or cron["generation"] < 1
            or cron["schedule"] != "0 * * * *" or cron["timeZone"] != "Etc/UTC"
            or cron["suspend"] is not False or cron["concurrencyPolicy"] != "Forbid"
            or type(cron["startingDeadlineSeconds"]) is not int
            or cron["startingDeadlineSeconds"] != 900
            or type(cron["successfulJobsHistoryLimit"]) is not int
            or cron["successfulJobsHistoryLimit"] != 3
            or type(cron["failedJobsHistoryLimit"]) is not int
            or cron["failedJobsHistoryLimit"] != 3):
        raise AssemblyError("changed-or-suspended-cronjob")
    if (not isinstance(snapshot["jobsResourceVersion"], str) or not snapshot["jobsResourceVersion"]
            or not isinstance(snapshot["podsResourceVersion"], str) or not snapshot["podsResourceVersion"]
            or not isinstance(snapshot["jobs"], list) or not isinstance(snapshot["pods"], list)):
        raise AssemblyError("incomplete-snapshot")
    return cron["uid"], cron["generation"]


def validate_job(job):
    fields = {"name", "uid", "scheduledAt", "createdAt", "startedAt", "finishedAt", "phase"}
    if (not isinstance(job, dict) or set(job) != fields
            or not isinstance(job["name"], str) or not re.fullmatch(r"renovate-\d+", job["name"])
            or not isinstance(job["uid"], str) or not job["uid"]
            or not isinstance(job["phase"], str)
            or job["phase"] not in {"active", "succeeded", "failed"}):
        raise AssemblyError("invalid-job")
    if job["scheduledAt"] is None:
        raise AssemblyError("missing-scheduled-hour")
    scheduled, created = utc(job["scheduledAt"]), utc(job["createdAt"])
    started = utc(job["startedAt"]) if job["startedAt"] is not None else None
    finished = utc(job["finishedAt"]) if job["finishedAt"] is not None else None
    if (scheduled.minute or scheduled.second or scheduled.microsecond or created < scheduled
            or (started and started < created) or (finished and started and finished < started)
            or (job["phase"] == "active" and finished)
            or (job["phase"] != "active" and not finished)):
        raise AssemblyError("invalid-job-time")
    return scheduled


def validate_pod(pod):
    fields = {"name", "uid", "jobUid", "createdAt", "phase", "startedAt",
              "containerStartedAt", "log"}
    if (not isinstance(pod, dict) or set(pod) != fields
            or not isinstance(pod["name"], str) or not pod["name"]
            or not isinstance(pod["uid"], str) or not pod["uid"]
            or not isinstance(pod["jobUid"], str) or not pod["jobUid"]
            or not isinstance(pod["phase"], str)):
        raise AssemblyError("invalid-pod")
    utc(pod["createdAt"])
    if pod["startedAt"] is not None:
        utc(pod["startedAt"])
    if pod["containerStartedAt"] is not None:
        utc(pod["containerStartedAt"])


def stable_records(records, keys):
    first = records[0][1]
    for _, record in records[1:]:
        if any(record[key] != first[key] for key in keys):
            raise AssemblyError("changed-resource-identity")


def build_document(schedule_dir, window_start):
    selected = read_snapshots(schedule_dir, window_start)
    jobs = {}
    pods = {}
    log_cache = {}
    cron_identity = None
    for index in range(673):
        snapshot = selected[index][0]
        current_identity = validate_snapshot(snapshot, index, window_start)
        captured_at = utc(snapshot["finishedAt"])
        if cron_identity is None:
            cron_identity = current_identity
        elif current_identity != cron_identity:
            raise AssemblyError("changed-cronjob-identity")
        local_jobs = set()
        for job in snapshot["jobs"]:
            scheduled = validate_job(job)
            if (scheduled > captured_at or any(
                    utc(job[field]) > captured_at for field in ("createdAt", "startedAt", "finishedAt")
                    if job[field] is not None)):
                raise AssemblyError("future-job-in-snapshot")
            if job["uid"] in local_jobs:
                raise AssemblyError("duplicate-job")
            local_jobs.add(job["uid"])
            jobs.setdefault(job["uid"], []).append((index, job))
        local_pods = set()
        for pod in snapshot["pods"]:
            validate_pod(pod)
            if any(utc(pod[field]) > captured_at for field in
                   ("createdAt", "startedAt", "containerStartedAt") if pod[field] is not None):
                raise AssemblyError("future-pod-in-snapshot")
            if pod["uid"] in local_pods or pod["jobUid"] not in local_jobs:
                raise AssemblyError("orphan-or-duplicate-pod")
            local_pods.add(pod["uid"])
            verify_log(schedule_dir, pod, log_cache)
            if pod["log"] and any(utc(pod["log"][field]) > captured_at for field in
                                  ("globalStartedAt", "discoveryCompletedAt")
                                  if pod["log"][field] is not None):
                raise AssemblyError("future-log-in-snapshot")
            pods.setdefault(pod["uid"], []).append((index, pod))

    for records in jobs.values():
        stable_records(records, ("name", "uid", "scheduledAt", "createdAt"))
        if len({job["startedAt"] for _, job in records if job["startedAt"] is not None}) > 1:
            raise AssemblyError("changed-job-start")
    pods_by_job = {}
    for records in pods.values():
        stable_records(records, ("name", "uid", "jobUid", "createdAt"))
        pods_by_job.setdefault(records[0][1]["jobUid"], []).append(records)

    slots = []
    sources = {}
    for slot_index in range(168):
        at = window_start + slot_index * HOUR
        capture_indices = range(slot_index * 4, slot_index * 4 + 5)
        runs = []
        prestart_failures = []
        for records in jobs.values():
            scheduled = validate_job(records[0][1])
            if scheduled != at:
                continue
            stable_records(records, ("name", "uid", "scheduledAt", "createdAt"))
            relevant = [(index, job) for index, job in records if index in capture_indices]
            if not relevant:
                raise AssemblyError("job-outside-capture-window")
            terminal = [(index, job) for index, job in relevant if job["phase"] != "active"]
            if not terminal:
                raise AssemblyError("unterminated-job")
            job = terminal[-1][1]
            if any(other["phase"] != job["phase"] or other["finishedAt"] != job["finishedAt"]
                   for _, other in terminal):
                raise AssemblyError("changed-job-result")
            pod_records = pods_by_job.get(job["uid"], [])
            if len(pod_records) != 1:
                raise AssemblyError("missing-or-multiple-job-pods")
            matching_pods = [(index, pod) for index, pod in pod_records[0] if index in capture_indices]
            terminal_pods = [(index, pod) for index, pod in matching_pods
                             if pod["phase"] in {"Succeeded", "Failed"} and pod["log"]]
            if not terminal_pods:
                raise AssemblyError("missing-terminal-pod-log")
            pod = terminal_pods[-1][1]
            if (job["phase"] == "succeeded" and pod["phase"] != "Succeeded") or (
                    job["phase"] == "failed" and pod["phase"] != "Failed"):
                raise AssemblyError("job-pod-result-mismatch")
            log = pod["log"]
            if log["discoveryMarkerCount"] == 1 and log["globalMarkerCount"] == 1:
                if job["startedAt"] is None:
                    raise AssemblyError("missing-job-start")
                runs.append({"jobUid": job["uid"], "podUid": pod["uid"],
                             "jobStartedAt": job["startedAt"],
                             "discoveryCompletedAt": log["discoveryCompletedAt"],
                             "finishedAt": job["finishedAt"], "phase": job["phase"]})
            elif (job["phase"] == "failed" and log["bytes"] > 0
                  and log["globalMarkerCount"] == 0 and log["discoveryMarkerCount"] == 0):
                prestart_failures.append({"jobUid": job["uid"], "podUid": pod["uid"],
                                          "log": {"file": log["file"], "sha256": log["sha256"]}})
            else:
                raise AssemblyError("ambiguous-discovery-marker")

        collected_at = selected[slot_index * 4 + 4][0]["finishedAt"]
        slot_at = stamp(at)
        claim = {"collectedAt": collected_at, "runs": runs}
        material = {
            "cronjobUid": cron_identity[0],
            "cronjobGeneration": cron_identity[1],
            "snapshots": [selected[index][1] for index in capture_indices],
            "prestartFailures": prestart_failures,
        }
        proof = {"schema": 1, "kind": "slot-collection", "slotAt": slot_at,
                 "claim": claim, "material": material}
        filename = f"slot-{slot_index:03d}.json"
        data = (json.dumps(proof, sort_keys=True, separators=(",", ":")) + "\n").encode()
        sources[filename] = data
        slots.append({"slotAt": slot_at, "collectedAt": collected_at,
                      "collection": {"source": f"evidence/{filename}",
                                     "sha256": hashlib.sha256(data).hexdigest()},
                      "runs": runs})
    document = {"schema": 1, "windowStart": stamp(window_start),
                "windowEnd": stamp(window_start + timedelta(days=7)), "slots": slots}
    return document, sources


def write_output(directory, document, sources):
    if directory.exists() or directory.is_symlink():
        raise AssemblyError("output-exists")
    staging = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=directory.parent))
    try:
        evidence = staging / "evidence"
        evidence.mkdir(mode=0o700)
        for name, data in sources.items():
            descriptor = os.open(evidence / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
        target = staging / "slots.json"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        report = SCHEDULE.evaluate(document, staging)
        if directory.exists() or directory.is_symlink():
            raise AssemblyError("output-exists")
        staging.rename(directory)
        return report
    except BaseException:
        shutil.rmtree(staging)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="protected schedule directory with snapshots/ and logs/")
    parser.add_argument("--window-start", required=True,
                        help="UTC hour at the beginning of the seven-day window")
    parser.add_argument("--output", required=True, type=Path,
                        help="new owner-only directory for slots.json and evidence/")
    args = parser.parse_args(argv)
    try:
        start = utc(args.window_start)
        if start.minute or start.second or start.microsecond:
            raise AssemblyError("invalid-window-start")
        document, sources = build_document(args.source, start)
        report = write_output(args.output, document, sources)
    except (OSError, ValueError, AssemblyError) as error:
        reason = str(error) if isinstance(error, AssemblyError) else "unreadable-capture"
        print(json.dumps({"status": "inconclusive", "reason": reason}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return {"review-required": 0, "criteria-not-met": 1, "inconclusive": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
