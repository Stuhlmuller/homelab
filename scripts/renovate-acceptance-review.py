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


def private_review(path):
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
                or not isinstance(review.get("repositories"), list)
                or not isinstance(review.get("classifications"), list)):
            raise ValueError
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Failure("Review input schema is invalid") from None
    return raw


def secret():
    output = command("kubectl", "-n", NAMESPACE, "get", "secret", SECRET,
                     "--ignore-not-found=true", "-o", "json")
    try:
        result = json.loads(output) if output else None
    except ValueError:
        raise Failure("Review Secret metadata could not be read") from None
    if result and (result.get("metadata", {}).get("name") != SECRET
                   or result.get("metadata", {}).get("namespace") != NAMESPACE
                   or result.get("type") != "Opaque"
                   or result.get("immutable") is not True
                   or set(result.get("data", {})) != {"review.json"}):
        raise Failure("Existing review Secret has an invalid shape")
    return result


def install(raw, execute):
    existing = secret()
    if existing:
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
                "metadata": {"name": SECRET, "namespace": NAMESPACE}, "type": "Opaque",
                "immutable": True,
                "data": {"review.json": base64.b64encode(raw).decode("ascii")}}
    command("kubectl", "create", "-f", "-", input_data=json.dumps(manifest))
    created = secret()
    try:
        actual = base64.b64decode(created["data"]["review.json"], validate=True)
    except (TypeError, KeyError, ValueError, binascii.Error):
        raise Failure("Review Secret creation could not be verified") from None
    if hashlib.sha256(actual).digest() != hashlib.sha256(raw).digest():
        raise Failure("Review Secret digest mismatch; inspect before retrying")
    print("Private review input delivered to the fixed automation Secret; value withheld.")


def retire(execute):
    existing = secret()
    if not existing:
        print("Review Secret already absent.")
        return
    try:
        job = json.loads(command("kubectl", "-n", NAMESPACE, "get", "job", JOB, "-o", "json"))
    except ValueError:
        raise Failure("Inventory Job status could not be read") from None
    try:
        installed_at = datetime.fromisoformat(
            existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        started_at = datetime.fromisoformat(
            job["status"]["startTime"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise Failure("Inventory Job and Secret creation times are unavailable") from None
    if (job.get("metadata", {}).get("name") != JOB or started_at <= installed_at
            or job.get("status", {}).get("succeeded", 0) < 1
            or job.get("status", {}).get("active", 0)):
        raise Failure("Inventory Job has not completed successfully")
    if not execute:
        print("Inventory Job succeeded; use --execute to retire the input Secret.")
        return
    command("kubectl", "-n", NAMESPACE, "delete", "secret", SECRET,
            "--ignore-not-found=true", "--wait=true")
    if secret():
        raise Failure("Review Secret retirement could not be verified")
    print("Review Secret retired; frozen private ledger remains for acceptance review.")


def retract(execute):
    existing = secret()
    if not existing:
        print("Review Secret already absent.")
        return
    output = command("kubectl", "-n", NAMESPACE, "get", "job", JOB,
                     "--ignore-not-found=true", "-o", "json")
    try:
        job = json.loads(output) if output else None
        installed_at = datetime.fromisoformat(
            existing["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        if job:
            if job.get("metadata", {}).get("name") != JOB:
                raise ValueError
            status = job.get("status", {})
            started_at = datetime.fromisoformat(status["startTime"].replace("Z", "+00:00")) \
                if status.get("startTime") else None
            terminal_failed = any(condition.get("type") == "Failed"
                                  and condition.get("status") == "True"
                                  for condition in status.get("conditions", []))
            # A pending unsuspended Job may have no active Pod yet. Retract only
            # before activation or after a terminal failed attempt.
            if (status.get("active", 0)
                    or (status.get("succeeded", 0)
                        and (not started_at or started_at >= installed_at))
                    or (not job.get("spec", {}).get("suspend", False)
                        and not terminal_failed)):
                raise ValueError
    except (KeyError, ValueError, TypeError):
        raise Failure("Inventory Job is active or has seeded after delivery") from None
    if not execute:
        print("No successful inventory Job used this input; use --execute to retract it.")
        return
    command("kubectl", "-n", NAMESPACE, "delete", "secret", SECRET,
            "--ignore-not-found=true", "--wait=true")
    if secret():
        raise Failure("Review Secret retraction could not be verified")
    print("Review Secret retracted; existing ledger files were not changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "retire", "retract"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--private-file")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        reviewed_main(args.expected_sha)
        if args.operation == "install":
            if not args.private_file:
                raise Failure("Install requires --private-file")
            raw = private_review(args.private_file)
            install(raw, args.execute)
        elif args.private_file:
            raise Failure("Only install accepts a private file")
        elif args.operation == "retire":
            retire(args.execute)
        else:
            retract(args.execute)
    except (Failure, OSError, RuntimeError, subprocess.TimeoutExpired):
        raise SystemExit("Private review operation failed; details withheld") from None


if __name__ == "__main__":
    main()
