#!/usr/bin/env python3
"""Materialize the fixed Harbor mirror pull credential outside the checkout."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Stuhlmuller/homelab"
PARAMETER = "/homelab/harbor/mirror-robot-pull-password"
REGION = "us-west-2"
USERNAME = "robot$mirror+pull"
FILENAME = "harbor-mirror-registry-auth.json"
PROXY_ENVIRONMENT_NAMES = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


class CredentialError(Exception):
    """Only fixed diagnostics may leave credential-handling code."""


def command(arguments, *, timeout=60):
    # Botocore honors standard proxy variables; decrypted SSM reads must go directly to AWS.
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("AWS_") and key.lower() not in PROXY_ENVIRONMENT_NAMES
    }
    environment.update(AWS_PAGER="", AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true")
    try:
        result = subprocess.run(arguments, cwd=ROOT, env=environment, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        raise CredentialError("Private command failed") from None
    if result.returncode:
        raise CredentialError("Private command failed")
    return result.stdout


def verify_main(expected):
    if not re.fullmatch(r"[0-9a-f]{40}", expected or ""):
        raise CredentialError("A full reviewed main SHA is required")
    if command(["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"]):
        raise CredentialError("Execution requires a clean checkout")
    if (command(["git", "rev-parse", "HEAD"]).strip() != expected
            or command(["git", "ls-remote", f"https://github.com/{REPOSITORY}.git", "refs/heads/main"]).split()
            != [expected, "refs/heads/main"]):
        raise CredentialError("Checkout and current main must match the reviewed SHA")


def private_directory(path):
    path = Path(path)
    if not path.is_absolute():
        raise CredentialError("Credential destination must be absolute")
    path = Path(os.path.abspath(path))
    try:
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError:
        raise CredentialError("Credential destination is unavailable") from None
    if (resolved != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise CredentialError("Credential destination must be an owner-only directory")
    if (resolved.is_relative_to(ROOT)
            or any((parent / ".git").exists() for parent in (resolved, *resolved.parents))):
        raise CredentialError("Credential destination must be outside Git checkouts")
    return resolved


def password(profile):
    if not re.fullmatch(r"[A-Za-z0-9_+=,.@-]{1,128}", profile):
        raise CredentialError("Invalid AWS profile name")
    try:
        value = json.loads(command([
            "aws", "--profile", profile, "--region", REGION, "--no-cli-pager", "--no-cli-auto-prompt",
            "ssm", "get-parameter", "--name", PARAMETER, "--with-decryption", "--output", "json",
        ]))
        parameter = value["Parameter"]
        secret = parameter["Value"]
    except (CredentialError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise CredentialError("Declared Harbor mirror credential is unavailable") from None
    if (not isinstance(parameter, dict) or parameter.get("Name") != PARAMETER
            or parameter.get("Type") != "SecureString" or not isinstance(secret, str) or not secret
            or len(secret.encode("utf-8")) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in secret)):
        raise CredentialError("Declared Harbor mirror credential is invalid")
    return secret


def sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_credential(directory, secret):
    directory = private_directory(directory)
    if (not isinstance(secret, str) or not secret or len(secret.encode("utf-8")) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in secret)):
        raise CredentialError("Credential value is invalid")
    target = directory / FILENAME
    try:
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata is not None:
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
                raise CredentialError("Existing credential file is unsafe")
        temporary = directory / f".{FILENAME}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"username": USERNAME, "password": secret}, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        sync_directory(directory)
        return target
    except CredentialError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise CredentialError("Credential file could not be written safely") from None
    finally:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)


def materialize(profile, directory, expected):
    directory = private_directory(directory)
    verify_main(expected)
    secret = password(profile)
    verify_main(expected)
    return write_credential(directory, secret)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Existing named AWS profile with this parameter read grant")
    parser.add_argument("--directory", type=Path, required=True,
                        help=f"Existing private destination directory; writes {FILENAME}")
    parser.add_argument("--expected-sha", required=True, help="Exact reviewed current main SHA")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        materialize(args.profile, args.directory, args.expected_sha)
    except Exception:  # AWS and parsing errors can contain the robot password.
        print("Harbor mirror credential materialization failed; private details withheld.", file=sys.stderr)
        return 1
    print("Harbor mirror credential materialized in the requested private directory.")
    return 0


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    sys.exit(main())
