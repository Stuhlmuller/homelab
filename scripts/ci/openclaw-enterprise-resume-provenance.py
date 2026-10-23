#!/usr/bin/env python3
"""Bind a timed-out legacy restore worker to its protected GitHub run."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
ARCHIVE_REF = re.compile(r"[0-9a-f]{40}/[1-9][0-9]{0,19}\Z")
WORKFLOW = ".github/workflows/openclaw-enterprise-operations.yml"
JOB = "Protected Legacy Retention"
STAGE_STEP = "Run Legacy Stage"
PRIOR_RUN_ID = "39988927652"
PRIOR_SOURCE_SHA = "28d2402285ed8dad373bf22a22ea82411beca9b1"
PUBLISHED_ARCHIVE_REF = "9f64b56a15c8a1c1b81606e0fa751157b09f47fb/39501240221"
UNCHANGED = (
    "scripts/config/openclaw-enterprise.json",
    "scripts/openclaw-retirement-status.py",
    "clusters/homelab/apps/openclaw/retirement/retirement.py",
)


class Blocked(RuntimeError):
    pass


def require(condition):
    if not condition:
        raise Blocked("prior restore provenance is unavailable or changed")


def command(*args, limit=8 * 1024 * 1024):
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=90,
                                check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked("prior restore provenance is unavailable or changed") from None
    require(result.returncode == 0 and len(result.stdout) <= limit)
    return result.stdout


def parse_run(run, prior_id):
    require(isinstance(run, dict) and run.get("id") == int(prior_id) and
            run.get("event") == "workflow_dispatch" and
            run.get("path") == WORKFLOW and
            run.get("head_branch") == "main" and
            run.get("status") == "completed" and
            run.get("conclusion") == "timed_out" and
            run.get("run_attempt") == 1 and
            isinstance(run.get("head_sha"), str) and
            SHA.fullmatch(run["head_sha"]))
    return run["head_sha"]


def parse_job(jobs):
    require(isinstance(jobs, dict) and type(jobs.get("total_count")) is int and
            isinstance(jobs.get("jobs"), list) and
            len(jobs["jobs"]) == jobs["total_count"])
    matches = [job for job in jobs["jobs"] if job.get("name") == JOB]
    require(len(matches) == 1 and type(matches[0].get("id")) is int and
            matches[0].get("status") == "completed" and
            matches[0].get("conclusion") == "timed_out")
    return matches[0]["id"]


def parse_log(log, archive_ref):
    require(len(log) <= 8 * 1024 * 1024)
    found = {"RUN_STAGE": [], "ARCHIVE_REF": []}
    for line in log.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3 or fields[:2] != [JOB, STAGE_STEP]:
            continue
        for key in found:
            match = re.fullmatch(r"[^\t]*Z +" + key + r": ([^\s]+)", fields[2])
            if match:
                found[key].append(match.group(1))
    require(found == {"RUN_STAGE": ["prepare-restore"],
                      "ARCHIVE_REF": [archive_ref]})


def prove_source(prior_sha, current_sha):
    require(prior_sha != current_sha)
    command("git", "merge-base", "--is-ancestor", prior_sha, current_sha, limit=0)
    for path in UNCHANGED:
        require(command("git", "show", f"{prior_sha}:{path}") ==
                (ROOT / path).read_bytes())
    old_script = command("git", "show", f"{prior_sha}:scripts/ci/openclaw-enterprise-operations.sh").decode()
    new_script = (ROOT / "scripts/ci/openclaw-enterprise-operations.sh").read_text()
    delimiter = '\n}\n\ncase "$stage" in'
    def launcher(source):
        require(source.count("verify_restored_archive() {") == 1)
        body = source.split("verify_restored_archive() {", 1)[1]
        require(delimiter in body)
        return body.split(delimiter, 1)[0]
    require(launcher(old_script) == launcher(new_script))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-run-id", required=True)
    parser.add_argument("--archive-ref", required=True)
    parser.add_argument("--current-sha", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(RUN_ID.fullmatch(args.prior_run_id) and
                ARCHIVE_REF.fullmatch(args.archive_ref) and
                args.prior_run_id == PRIOR_RUN_ID and
                args.archive_ref == PUBLISHED_ARCHIVE_REF and
                SHA.fullmatch(args.current_sha) and
                os.environ.get("GITHUB_ACTIONS") == "true" and
                os.environ.get("GITHUB_REPOSITORY") == "Stuhlmuller/homelab" and
                os.environ.get("GITHUB_SHA") == args.current_sha and
                os.environ.get("GH_TOKEN"))
        require(command("git", "rev-parse", "HEAD").decode().strip() == args.current_sha)
        require(command("gh", "api", "repos/Stuhlmuller/homelab/git/ref/heads/main",
                        "--jq", ".object.sha").decode().strip() == args.current_sha)
        run = json.loads(command("gh", "api", f"repos/Stuhlmuller/homelab/actions/runs/{args.prior_run_id}"))
        prior_sha = parse_run(run, args.prior_run_id)
        require(prior_sha == PRIOR_SOURCE_SHA)
        jobs = json.loads(command("gh", "api", f"repos/Stuhlmuller/homelab/actions/runs/{args.prior_run_id}/jobs?per_page=100"))
        job_id = parse_job(jobs)
        parse_log(command("gh", "run", "view", args.prior_run_id, "--job", str(job_id), "--log").decode(),
                  args.archive_ref)
        prove_source(prior_sha, args.current_sha)
        require(args.receipt.is_absolute() and not args.receipt.exists() and
                not args.receipt.is_symlink() and args.receipt.parent.is_dir())
        payload = json.dumps({"priorRunId": args.prior_run_id,
                              "priorSourceSha": prior_sha,
                              "archiveRef": args.archive_ref,
                              "currentSha": args.current_sha},
                             sort_keys=True, separators=(",", ":")).encode()
        descriptor = os.open(args.receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except (Blocked, ValueError, OSError, UnicodeError):
        print("Prior restore provenance blocked", file=sys.stderr)
        return 1
    print("Prior timed-out restore run verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
