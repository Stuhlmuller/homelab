#!/usr/bin/env python3
"""Validate GitHub's private manifest response; publish to declared SSM placeholders."""

import argparse
import json
from pathlib import Path
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/homelab/multica/github-app/"


def values(document):
    manifest = json.loads((ROOT / "clusters/homelab/apps/multica/github-app-manifest.json").read_text())
    if document.get("slug") != manifest["name"]:
        raise ValueError("App slug does not match the reviewed manifest")
    app_id = document.get("id")
    if type(app_id) is not int or app_id <= 0:
        raise ValueError("App ID must be a positive integer")
    for key in ("pem", "webhook_secret"):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise ValueError("Missing private key or webhook secret")
    if len(document["webhook_secret"]) < 32:
        raise ValueError("Webhook secret must contain at least 32 characters")
    result = subprocess.run(
        ["openssl", "rsa", "-check", "-noout"], input=document["pem"],
        text=True, capture_output=True, timeout=10,
    )
    if result.returncode:
        raise ValueError("Invalid RSA private key")
    return {"slug": document["slug"], "id": str(app_id),
            "private-key": document["pem"], "webhook-secret": document["webhook_secret"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credentials", type=Path, help="Private JSON from GitHub App manifest conversion")
    parser.add_argument("--apply", action="store_true", help="Replace existing SSM placeholders on reviewed main")
    args = parser.parse_args()
    if stat.S_IMODE(args.credentials.stat().st_mode) & 0o077:
        raise ValueError("Credential file must be owner-only (chmod 600)")
    parameters = values(json.loads(args.credentials.read_text()))
    if not args.apply:
        print("Validated dedicated Multica App credentials; no writes performed.")
        return
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(ROOT), *arguments], text=True).strip()
    remote = subprocess.check_output(
        ["gh", "api", "repos/Stuhlmuller/homelab/git/ref/heads/main", "--jq", ".object.sha"], text=True,
    ).strip()
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != remote:
        raise ValueError("Publication requires clean, exact reviewed origin main")
    # Check every declared target before the first write. Never create ad hoc parameters.
    for key in parameters:
        response = subprocess.check_output([
            "aws", "ssm", "describe-parameters", "--region", "us-west-2",
            "--parameter-filters", f"Key=Name,Option=Equals,Values={PREFIX}{key}",
            "--output", "json",
        ], text=True)
        metadata = json.loads(response)["Parameters"]
        if len(metadata) != 1 or metadata[0]["Type"] != "SecureString" or metadata[0].get("KeyId") != "alias/aws/ssm":
            raise ValueError("Apply the declared SecureString placeholders before publishing")
    for key, value in parameters.items():
        result = subprocess.run([
            "aws", "ssm", "put-parameter", "--region", "us-west-2",
            "--cli-input-json", "file:///dev/stdin",
        ], input=json.dumps({"Name": PREFIX + key, "Value": value,
                            "Type": "SecureString", "KeyId": "alias/aws/ssm", "Overwrite": True}),
            text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(f"SSM write failed for {key}; rerun with the same file to finish")
    print("Published four Multica App parameters. Activate GitOps only after all four writes succeed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, KeyError):
        raise SystemExit("Multica credential validation/publication failed; values were not printed. Check the input, AWS access, and clean-main prerequisite.")
