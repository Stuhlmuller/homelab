#!/usr/bin/env python3
"""Provision one disposable Cordium canary runner using a file-backed App key."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import importlib.util
import json
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("github_operator", ROOT / "scripts/policy-bot-webhook.py")
github_operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github_operator)


def runner_present(api, repository, identifier):
    try:
        api("GET", f"/repos/{repository}/actions/runners/{identifier}")
        return True
    except RuntimeError as error:
        if str(error) == "GitHub request failed with HTTP 404; response withheld":
            return False
        raise


def provision(api, client, checkout):
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    repository = pool["repository"]
    workspace = runner_id = None
    creation_attempted = False
    registration_attempted = False

    def call(*arguments, timeout=45, input=None, capture=True):
        return subprocess.run(client + list(arguments), input=input, timeout=timeout, check=True,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.PIPE if capture else subprocess.DEVNULL)

    def inventory():
        return json.loads(call("get", "workspace", "--out", "json").stdout).get("items", [])

    try:
        if inventory():
            raise RuntimeError("Dedicated runner identity has retained Workspaces; inspect before creating another")
        creation_attempted = True
        response = json.loads(call("create", "workspace", "--file", str(ROOT / ".cordium/runner-workspace.json"),
                                   "--dockerfile", str(ROOT / "builds/cordium-runner/Dockerfile"),
                                   "--checkout", checkout, "--ephemeral", "--out", "json").stdout)
        name = response["metadata"]["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name):
            raise RuntimeError("Creation returned an invalid Workspace name; inspect the dedicated identity")
        workspace = name
        call("start", workspace)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = json.loads(call("get", "workspace", workspace, "--out", "json").stdout)["status"]["state"]
            if state == "RUNNING":
                break
            if state in ("STOPPED", "FAILED"):
                raise RuntimeError("Runner Workspace failed to start")
            time.sleep(5)
        else:
            raise RuntimeError("Runner Workspace did not become ready in five minutes")
        actual = call("exec", workspace, "--no-stdin", "--workdir", "/workspace/repo", "--",
                      "git", "rev-parse", "HEAD").stdout.decode().strip()
        if actual != checkout:
            raise RuntimeError("Runner bootstrap checkout differs from reviewed main")
        registration_attempted = True
        jit = api("POST", f"/repos/{repository}/actions/runners/generate-jitconfig", {
            "name": "cordium-" + workspace, "runner_group_id": pool["runner_group_id"],
            "labels": pool["labels"], "work_folder": "_work",
        })
        identifier = jit["runner"]["id"]
        if (not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0
                or jit["runner"].get("name") != "cordium-" + workspace):
            raise RuntimeError("GitHub returned an invalid runner ID; inspect repository registrations")
        runner_id = identifier
        encoded = jit["encoded_jit_config"]
        if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9+/=]{1,131072}", encoded):
            raise RuntimeError("GitHub returned an invalid JIT configuration")
        print(f"Canary runner {runner_id} in Cordium Workspace {workspace}", flush=True)
        # Only the one-job configuration enters stdin; App credentials stay outside.
        call("exec", workspace, "--root", "--workdir", "/workspace/repo", "--",
             "bash", "scripts/ci/cordium-runner-probe.sh", "runner", timeout=1800,
             input=encoded.encode(), capture=False)
    finally:
        cleanup_failed = False
        if workspace:
            try:
                call("delete", "workspace", workspace)
                deadline = time.monotonic() + 60
                while any(item["metadata"]["name"] == workspace for item in inventory()):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Runner Workspace deletion is not yet verified")
                    time.sleep(2)
                print(f"Verified deletion of runner Workspace {workspace}", flush=True)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
                cleanup_failed = True
        elif creation_attempted:
            print("Workspace creation result unknown; inspect the dedicated identity before retrying", file=sys.stderr)
        if runner_id is not None:
            # One-job runners normally unregister themselves. Delete only our ID.
            try:
                if runner_present(api, repository, runner_id):
                    api("DELETE", f"/repos/{repository}/actions/runners/{runner_id}")
                if runner_present(api, repository, runner_id):
                    raise RuntimeError("GitHub runner deletion is not yet verified")
            except (OSError, ValueError, KeyError, RuntimeError):
                cleanup_failed = True
        elif registration_attempted:
            print("Runner registration result unknown; inspect repository runners before retrying", file=sys.stderr)
        if cleanup_failed:
            raise RuntimeError("Runner cleanup is incomplete; inspect the dedicated identity and repository runner")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-key-file", required=True, type=Path)
    parser.add_argument("--homedir", required=True, type=Path, help="Dedicated runner identity login; never a human/agent login")
    parser.add_argument("--expected-sha", required=True, help="Exact current reviewed main commit")
    args = parser.parse_args()
    github_operator.verify_reviewed_main(args.expected_sha)
    github_operator.command("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/cordium-runner.py")
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    if pool["enabled"] is not True:
        raise RuntimeError("Runner registration is disabled until live network isolation is verified")
    version = github_operator.command("cordium", "version").decode()
    if not re.search(r"(?m)^gitCommit:\s*e12b0b16d5fe94716e414fca7cfdc10b21014f2c\s*$", version):
        raise RuntimeError("Install the pinned Cordium v0.12.7 client before runner provisioning")
    if args.app_key_file.stat().st_mode & 0o077:
        raise RuntimeError("App key file must not be readable by group or others")
    app = github_operator.github_client(github_operator.app_jwt(pool["app_id"], args.app_key_file.read_bytes()))
    if str(app("GET", "/app")["id"]) != pool["app_id"]:
        raise RuntimeError("GitHub App identity differs from the declared runner App")
    token = app("POST", f"/app/installations/{pool['installation_id']}/access_tokens", {
        "repositories": ["homelab"],
        "permissions": {"administration": "write", "actions": "read", "metadata": "read"},
    })["token"]
    api = github_operator.github_client(token)
    if [item["full_name"] for item in api("GET", "/installation/repositories")["repositories"]] != [pool["repository"]]:
        raise RuntimeError("Runner token is not restricted to the homelab repository")
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    provision(api, ["cordium", "--homedir", str(args.homedir.resolve()), "--domain", "stinkyboi.com"], args.expected_sha)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit("Runner provisioning or cleanup failed; private output withheld") from None
