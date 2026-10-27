#!/usr/bin/env python3
"""Deliver one reviewed private Renovate acceptance input without publishing it."""

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import base64
import binascii
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SECRET = "renovate-acceptance-review"
JOB = "renovate-acceptance-inventory"
OUTCOME_SECRET = "renovate-acceptance-outcome-review"
OUTCOME_JOB = "renovate-acceptance-outcome-amend"
OUTCOME_PREFLIGHT_JOB = "renovate-acceptance-outcome-preflight"
OUTCOME_JOB_UID_ANNOTATION = "renovate.stuhlmuller.net/outcome-job-uid"
OUTCOME_PREFLIGHT_UID_ANNOTATION = "renovate.stuhlmuller.net/outcome-preflight-uid"
NAMESPACE = "automation"
API = "https://10.1.0.199:6443"
LIMIT = 900 * 1024


class Failure(Exception):
    """Only fixed diagnostics may cross the private input boundary."""


def command(*args, input_data=None):
    result = subprocess.run(args, cwd=ROOT, input=input_data,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise Failure("Operator command failed; details withheld")
    return result.stdout.strip()


def reviewed_main(expected):
    if not re.fullmatch(r"[0-9a-f]{40}", expected or ""):
        raise Failure("Expected a full reviewed main SHA")
    if (command("git", "branch", "--show-current") != "main"
            or command("git", "rev-parse", "HEAD") != expected
            or command("git", "status", "--porcelain", "--untracked-files=all")
            or command("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                       "refs/heads/main").split() != [expected, "refs/heads/main"]
            or command("gh", "api", f"repos/Stuhlmuller/homelab/commits/{expected}",
                       "--jq", ".commit.verification.verified") != "true"):
        raise Failure("Run from clean, signed, current main after protected merge")
    if command("kubectl", "config", "view", "--minify", "-o",
               "jsonpath={.clusters[0].cluster.server}") != API:
        raise Failure("Kubernetes API target differs from the reviewed homelab endpoint")


def private_review(path, kind="inventory"):
    source = Path(path)
    if not source.is_absolute():
        raise Failure("Review input must be an absolute file outside a Git checkout")
    resolved = source.resolve()
    parent = resolved.parent
    probe = subprocess.run(["git", "-C", str(parent), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, timeout=10,
                           env={key: value for key, value in os.environ.items()
                                if not key.startswith("GIT_")})
    if (resolved.is_relative_to(ROOT)
            or any(os.path.lexists(directory / ".git") for directory in (parent, *parent.parents))
            or (probe.returncode == 0 and probe.stdout.strip() == "true")):
        raise Failure("Review input must be an absolute file outside a Git checkout")
    if source.is_symlink():
        raise Failure("Review input must be a private, bounded, owner-only regular file")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077
                or not 0 < metadata.st_size <= LIMIT):
            raise Failure("Review input must be a private, bounded, owner-only regular file")
        raw = stream.read(LIMIT + 1)
        if len(raw) != metadata.st_size:
            raise Failure("Review input changed during validation")
    try:
        review = json.loads(raw)
        if (not isinstance(review, dict) or review.get("schema") != 1
                or review.get("owner") != "Stuhlmuller"
                or not isinstance(review.get("classifications"), list)):
            raise ValueError
        if kind == "inventory":
            if not isinstance(review.get("repositories"), list):
                raise ValueError
        elif kind == "outcomes":
            if (not isinstance(review.get("inventorySha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", review["inventorySha256"])
                    or not isinstance(review.get("reviewSha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", review["reviewSha256"])
                    or not isinstance(review.get("configSha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", review["configSha256"])
                    or not isinstance(review.get("windowStart"), str)
                    or not isinstance(review.get("windowEnd"), str)
                    or not review["classifications"]):
                raise ValueError
        else:
            raise ValueError
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Failure("Review input schema is invalid") from None
    return raw


def secret(name=SECRET):
    output = command("kubectl", "-n", NAMESPACE, "get", "secret", name,
                     "--ignore-not-found=true", "-o", "json")
    try:
        result = json.loads(output) if output else None
    except ValueError:
        raise Failure("Review Secret metadata could not be read") from None
    if result and (result.get("metadata", {}).get("name") != name
                   or result.get("metadata", {}).get("namespace") != NAMESPACE
                   or result.get("type") != "Opaque"
                   or result.get("immutable") is not True
                   or set(result.get("data", {})) != {"review.json"}):
        raise Failure("Existing review Secret has an invalid shape")
    if result and name == OUTCOME_SECRET:
        delivered_uid(result, OUTCOME_JOB_UID_ANNOTATION)
        delivered_uid(result, OUTCOME_PREFLIGHT_UID_ANNOTATION)
    return result


def delivered_uid(review_secret, annotation):
    try:
        uid = review_secret["metadata"]["annotations"][annotation]
    except (KeyError, TypeError):
        raise Failure("Outcome input has no bound Job identity") from None
    if not isinstance(uid, str) or not uid:
        raise Failure("Outcome input has no bound Job identity")
    return uid


def suspended_outcome_job(job_name=OUTCOME_JOB):
    output = command("kubectl", "-n", NAMESPACE, "get", "job", job_name,
                     "--ignore-not-found=true", "-o", "json")
    try:
        job = json.loads(output) if output else None
        status = job.get("status", {}) if job else {}
        if (not job or job.get("metadata", {}).get("name") != job_name
                or job.get("metadata", {}).get("namespace") != NAMESPACE
                or job.get("spec", {}).get("suspend") is not True
                or status.get("startTime")
                or any(status.get(field, 0) for field in ("active", "succeeded", "failed"))
                or any(condition.get("type") in ("Complete", "Failed")
                       and condition.get("status") == "True"
                       for condition in status.get("conditions", []))):
            raise ValueError
        uid = job["metadata"]["uid"]
        if not isinstance(uid, str) or not uid:
            raise ValueError
        created_at = datetime.fromisoformat(
            job["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        return created_at, uid
    except (KeyError, TypeError, ValueError):
        raise Failure("Outcome Job must be reconciled suspended before input delivery") from None


def install(raw, execute, name=SECRET):
    outcome_job = suspended_outcome_job() if name == OUTCOME_SECRET else None
    preflight_job = suspended_outcome_job(OUTCOME_PREFLIGHT_JOB) if outcome_job else None
    existing = secret(name)
    if existing:
        if outcome_job:
            try:
                installed_at = datetime.fromisoformat(
                    existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                raise Failure("Existing outcome input creation time is unavailable") from None
            if (outcome_job[0] > installed_at or preflight_job[0] > installed_at
                    or delivered_uid(existing, OUTCOME_JOB_UID_ANNOTATION) != outcome_job[1]
                    or delivered_uid(existing, OUTCOME_PREFLIGHT_UID_ANNOTATION)
                    != preflight_job[1]):
                raise Failure("Outcome Job was replaced after input delivery")
        try:
            actual = base64.b64decode(existing["data"]["review.json"], validate=True)
        except (KeyError, ValueError, TypeError, binascii.Error):
            raise Failure("Existing review Secret has an invalid shape") from None
        if actual != raw:
            raise Failure("Existing review Secret differs; refusing to replace it")
        print("Review Secret already contains the same private input; value withheld.")
        return
    if not execute:
        print("Private review input and target verified; use --execute to install.")
        return
    manifest = {"apiVersion": "v1", "kind": "Secret",
                "metadata": {"name": name, "namespace": NAMESPACE}, "type": "Opaque",
                "immutable": True,
                "data": {"review.json": base64.b64encode(raw).decode("ascii")}}
    if outcome_job:
        manifest["metadata"]["annotations"] = {
            OUTCOME_JOB_UID_ANNOTATION: outcome_job[1],
            OUTCOME_PREFLIGHT_UID_ANNOTATION: preflight_job[1]}
    command("kubectl", "create", "-f", "-", input_data=json.dumps(manifest))
    created = secret(name)
    try:
        actual = base64.b64decode(created["data"]["review.json"], validate=True)
    except (TypeError, KeyError, ValueError, binascii.Error):
        raise Failure("Review Secret creation could not be verified") from None
    if hashlib.sha256(actual).digest() != hashlib.sha256(raw).digest():
        raise Failure("Review Secret digest mismatch; inspect before retrying")
    if outcome_job and (delivered_uid(created, OUTCOME_JOB_UID_ANNOTATION) != outcome_job[1]
                        or delivered_uid(created, OUTCOME_PREFLIGHT_UID_ANNOTATION)
                        != preflight_job[1]
                        or suspended_outcome_job() != outcome_job
                        or suspended_outcome_job(OUTCOME_PREFLIGHT_JOB) != preflight_job):
        raise Failure("Outcome Job identity changed during input delivery")
    print("Private review input delivered to the fixed automation Secret; value withheld.")


def retire(execute, name=SECRET, job_name=JOB):
    existing = secret(name)
    if not existing:
        print("Review Secret already absent.")
        return
    try:
        job = json.loads(command("kubectl", "-n", NAMESPACE, "get", "job", job_name, "-o", "json"))
    except ValueError:
        raise Failure("Review target Job status could not be read") from None
    try:
        installed_at = datetime.fromisoformat(
            existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        started_at = datetime.fromisoformat(
            job["status"]["startTime"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        raise Failure("Review target Job and Secret creation times are unavailable") from None
    if (job.get("metadata", {}).get("name") != job_name or started_at <= installed_at
            or job.get("status", {}).get("succeeded", 0) < 1
            or job.get("status", {}).get("active", 0)):
        raise Failure("Review target Job has not completed successfully")
    if (name == OUTCOME_SECRET and
            job.get("metadata", {}).get("uid") !=
            delivered_uid(existing, OUTCOME_JOB_UID_ANNOTATION)):
        raise Failure("Outcome Job identity differs from delivered input")
    if not execute:
        print("Review target Job succeeded; use --execute to retire the input Secret.")
        return
    command("kubectl", "-n", NAMESPACE, "delete", "secret", name,
            "--ignore-not-found=true", "--wait=true")
    if secret(name):
        raise Failure("Review Secret retirement could not be verified")
    print("Review Secret retired; frozen private ledger remains for acceptance review.")


def retract(execute, name=SECRET, job_name=JOB):
    existing = secret(name)
    if not existing:
        print("Review Secret already absent.")
        return
    output = command("kubectl", "-n", NAMESPACE, "get", "job", job_name,
                     "--ignore-not-found=true", "-o", "json")
    try:
        job = json.loads(output) if output else None
        installed_at = datetime.fromisoformat(
            existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        if name == OUTCOME_SECRET:
            if not job:
                raise ValueError
            created_at = datetime.fromisoformat(
                job["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
            if (created_at > installed_at or
                    job["metadata"].get("uid") !=
                    delivered_uid(existing, OUTCOME_JOB_UID_ANNOTATION)):
                raise ValueError
        if job:
            if job.get("metadata", {}).get("name") != job_name:
                raise ValueError
            status = job.get("status", {})
            started_at = datetime.fromisoformat(status["startTime"].replace("Z", "+00:00")) \
                if status.get("startTime") else None
            terminal_failed = any(condition.get("type") == "Failed"
                                  and condition.get("status") == "True"
                                  for condition in status.get("conditions", []))
            if (name == OUTCOME_SECRET and
                    (started_at or any(status.get(field, 0) for field in
                                       ("active", "succeeded", "failed"))
                     or any(condition.get("type") in ("Complete", "Failed")
                            and condition.get("status") == "True"
                            for condition in status.get("conditions", []))
                     or not job.get("spec", {}).get("suspend", False))):
                raise ValueError
            # Only inventory input may retract after a terminal failed attempt;
            # outcome input above refuses every started or unsuspended Job.
            if (status.get("active", 0)
                    or (status.get("succeeded", 0)
                        and (not started_at or started_at >= installed_at))
                    or (not job.get("spec", {}).get("suspend", False)
                        and not terminal_failed)):
                raise ValueError
    except (KeyError, ValueError, TypeError):
        raise Failure("Review target Job is active or has consumed the input") from None
    if not execute:
        print("No successful target Job used this input; use --execute to retract it.")
        return
    command("kubectl", "-n", NAMESPACE, "delete", "secret", name,
            "--ignore-not-found=true", "--wait=true")
    if secret(name):
        raise Failure("Review Secret retraction could not be verified")
    print("Review Secret retracted; existing ledger files were not changed.")


def verify_preflight():
    existing = secret(OUTCOME_SECRET)
    if not existing:
        raise Failure("Outcome review input is absent")
    writer_created_at, writer_uid = suspended_outcome_job()
    try:
        installed_at = datetime.fromisoformat(
            existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        preflight = json.loads(command("kubectl", "-n", NAMESPACE, "get", "job",
                                         OUTCOME_PREFLIGHT_JOB, "-o", "json"))
        status = preflight["status"]
        preflight_created_at = datetime.fromisoformat(
            preflight["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        started_at = datetime.fromisoformat(status["startTime"].replace("Z", "+00:00"))
        pod = preflight["spec"]["template"]["spec"]
        container, = pod["containers"]
        mounts = {mount["mountPath"]: mount for mount in container["volumeMounts"]}
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        code_name = volumes["code"]["configMap"]["name"]
        if not re.fullmatch(r"renovate-acceptance-observer-[a-z0-9]{10}", code_name):
            raise ValueError
        code_map = json.loads(command("kubectl", "-n", NAMESPACE, "get", "configmap",
                                      code_name, "-o", "json"))
        code_dir = ROOT / "clusters/homelab/apps/renovate"
        expected_mounts = {
            "/usr/src/app/acceptance-outcome-amend.js": ("code", "acceptance-outcome-amend.js"),
            "/usr/src/app/acceptance-observer.js": ("code", "acceptance-observer.js")}
        if (writer_created_at > installed_at or
                writer_uid != delivered_uid(existing, OUTCOME_JOB_UID_ANNOTATION) or
                preflight_created_at > installed_at or started_at <= installed_at or
                preflight["metadata"]["name"] != OUTCOME_PREFLIGHT_JOB or
                preflight["metadata"]["namespace"] != NAMESPACE or
                preflight["metadata"]["uid"] !=
                delivered_uid(existing, OUTCOME_PREFLIGHT_UID_ANNOTATION) or
                status.get("succeeded") != 1 or status.get("active", 0) or
                status.get("failed", 0) or
                not any(condition.get("type") == "Complete" and
                        condition.get("status") == "True"
                        for condition in status.get("conditions", [])) or
                pod.get("automountServiceAccountToken") is not False or
                container.get("command") != ["node", "/usr/src/app/acceptance-outcome-amend.js",
                                             "--check-only"] or
                preflight["spec"]["template"]["metadata"]["labels"].get(
                    "app.kubernetes.io/component") != "acceptance-outcome-amend" or
                len(container["volumeMounts"]) != 4 or len(mounts) != 4 or
                any(mounts.get(mount_path, {}).get("name") != name or
                    mounts.get(mount_path, {}).get("subPath") != subpath or
                    mounts.get(mount_path, {}).get("readOnly") is not True
                    for mount_path, (name, subpath) in expected_mounts.items()) or
                mounts.get("/review", {}).get("name") != "review" or
                mounts.get("/review", {}).get("readOnly") is not True or
                mounts.get("/ledger", {}).get("name") != "ledger" or
                mounts.get("/ledger", {}).get("readOnly") is not True or
                pod.get("securityContext", {}).get("fsGroup") is not None or
                len(pod["volumes"]) != 3 or set(volumes) != {"code", "review", "ledger"} or
                code_map.get("metadata", {}).get("name") != code_name or
                code_map.get("metadata", {}).get("namespace") != NAMESPACE or
                any(code_map.get("data", {}).get(script) != (code_dir / script).read_text()
                    for script in ("acceptance-outcome-amend.js", "acceptance-observer.js")) or
                volumes["review"].get("secret", {}).get("secretName") != OUTCOME_SECRET or
                volumes["review"]["secret"].get("items") !=
                [{"key": "review.json", "path": "review.json"}] or
                volumes["ledger"].get("persistentVolumeClaim", {}).get("claimName") !=
                "renovate-acceptance-ledger" or
                volumes["ledger"]["persistentVolumeClaim"].get("readOnly") is not True):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise Failure("Outcome preflight has not verified the current private input") from None
    print("Bound read-only outcome preflight completed after input delivery; writer remains suspended.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "retire", "retract", "verify-preflight"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--private-file")
    parser.add_argument("--kind", choices=("inventory", "outcomes"), default="inventory")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    name, job_name = ((SECRET, JOB) if args.kind == "inventory"
                      else (OUTCOME_SECRET, OUTCOME_JOB))
    try:
        reviewed_main(args.expected_sha)
        if args.operation == "install":
            if not args.private_file:
                raise Failure("Install requires --private-file")
            raw = private_review(args.private_file, args.kind)
            install(raw, args.execute, name)
        elif args.private_file:
            raise Failure("Only install accepts a private file")
        elif args.operation == "verify-preflight":
            if args.kind != "outcomes" or args.execute:
                raise Failure("Preflight verification is read-only for outcome input")
            verify_preflight()
        elif args.operation == "retire":
            retire(args.execute, name, job_name)
        else:
            retract(args.execute, name, job_name)
    except (Failure, OSError, RuntimeError, subprocess.TimeoutExpired):
        raise SystemExit("Private review operation failed; details withheld") from None


if __name__ == "__main__":
    main()
