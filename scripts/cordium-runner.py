#!/usr/bin/env python3
"""Provision one disposable Cordium canary runner using a file-backed App key."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("github_operator", ROOT / "scripts/policy-bot-webhook.py")
github_operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(github_operator)


def kube(*arguments, input=None):
    return github_operator.command("kubectl", "--request-timeout=15s", *arguments, input=input)


def enforcer_config(spec):
    containers = spec.get("containers", [])
    if len(containers) != 1 or not containers[0]["image"].endswith("@sha256:c671f98e444825d57c590c92da1b5e66070917c4d3dff1f9279775e6b73254fe"):
        return False
    args = containers[0].get("args", [])
    return all([arg for arg in args if arg == key or arg.startswith(key + "=")] == [key + "=" + value]
               for key, value in (("--fail-open", "false"), ("--strict-mode", "true"), ("--disable-nri", "false")))


def isolation_backend(pool):
    server = kube("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}").decode().strip()
    if server != pool["kubernetes_api_server"]:
        raise RuntimeError("Kubernetes context differs from the declared homelab API")
    daemon = json.loads(kube("get", "daemonset", "kube-network-policies", "-n", "kube-system", "-o", "json"))
    status = daemon["status"]
    template = daemon["spec"]["template"]["spec"]
    if (status.get("observedGeneration") != daemon["metadata"]["generation"]
            or status.get("desiredNumberScheduled", 0) <= 0
            or status.get("numberReady") != status["desiredNumberScheduled"]
            or not enforcer_config(template)):
        raise RuntimeError("The reviewed NRI policy enforcer is not fully ready")
    pods = json.loads(kube("get", "pods", "-n", "kube-system", "-l", "app=kube-network-policies",
                          "--field-selector", "spec.nodeName=" + pool["worker_node"], "-o", "json"))["items"]
    if len(pods) != 1 or not enforcer_config(pods[0]["spec"]) or not any(condition.get("type") == "Ready" and condition.get("status") == "True"
                                  for condition in pods[0].get("status", {}).get("conditions", [])):
        raise RuntimeError("Policy enforcement is not ready on the Cordium worker")


def workspace_policy(metadata):
    uid = metadata.get("uid")
    if not isinstance(uid, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", uid):
        raise RuntimeError("Workspace UID is invalid; refusing a broad network selector")
    policy = json.loads((ROOT / ".cordium/runner-network-policy.json").read_text())
    policy["metadata"]["name"] = "cordium-runner-" + uid
    policy["metadata"]["labels"]["homelab.rst.io/runner-workspace-uid"] = uid
    policy["spec"]["podSelector"]["matchLabels"]["octelium.com/workspace-uid"] = uid
    return policy


def policy_matches(live, expected):
    spec = live.get("spec", {})
    spec.setdefault("ingress", [])  # Kubernetes omits empty ingress lists on readback.
    return (live.get("metadata", {}).get("labels") == expected["metadata"]["labels"]
            and spec == expected["spec"])


def workspace_pods(uid):
    return json.loads(kube("get", "pods", "-n", "cordium", "-l", "octelium.com/workspace-uid=" + uid,
                          "-o", "json"))["items"]


def retire_policy(policy):
    name = policy["metadata"]["name"]
    data = kube("get", "networkpolicy", name, "-n", "cordium", "--ignore-not-found", "-o", "json")
    if not data.strip():
        return
    if not policy_matches(json.loads(data), policy):
        raise RuntimeError("Retained policy differs from this runner; refusing to delete it")
    kube("delete", "networkpolicy", name, "-n", "cordium", "--ignore-not-found", "--wait=true")
    if kube("get", "networkpolicy", name, "-n", "cordium", "--ignore-not-found", "-o", "json").strip():
        raise RuntimeError("Runner policy deletion is not yet verified")


def runner_present(api, repository, identifier):
    try:
        api("GET", f"/repos/{repository}/actions/runners/{identifier}")
        return True
    except RuntimeError as error:
        if str(error) == "GitHub request failed with HTTP 404; response withheld":
            return False
        raise


def installation_client(pool, key_file):
    if key_file.stat().st_mode & 0o077:
        raise RuntimeError("App key file must not be readable by group or others")
    app = github_operator.github_client(github_operator.app_jwt(pool["app_id"], key_file.read_bytes()))
    if str(app("GET", "/app")["id"]) != pool["app_id"]:
        raise RuntimeError("GitHub App identity differs from the declared runner App")
    token = app("POST", f"/app/installations/{pool['installation_id']}/access_tokens", {
        "repositories": ["homelab"],
        "permissions": {"administration": "write", "actions": "read", "metadata": "read"},
    })["token"]
    api = github_operator.github_client(token)
    if [item["full_name"] for item in api("GET", "/installation/repositories")["repositories"]] != [pool["repository"]]:
        raise RuntimeError("Runner token is not restricted to the homelab repository")
    return api


def native_identity(pool, client):
    status = json.loads(github_operator.command("octelium", *client[1:], "status", "-o", "json"))
    if (status.get("domain") != "stinkyboi.com" or status.get("user", {}).get("metadata", {}).get("name") != pool["cordium_user"]
            or status.get("user", {}).get("spec", {}).get("type") != "WORKLOAD"
            or status["user"]["spec"].get("authorization", {}).get("policies") != ["homelab-cordium-runner-execution"]):
        raise RuntimeError("Native login is not the dedicated policy-bound runner identity")


def queued_jobs(api, pool):
    available = {label.casefold() for label in pool["labels"]}
    seen = set()
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        page = 1
        while True:
            response = api("GET", f"/repos/{pool['repository']}/actions/runs?status={status}&per_page=100&page={page}")
            if response.get("total_count", 0) >= 1000:
                raise RuntimeError("Queue reaches GitHub's filtered-search cap; partition the inventory before provisioning")
            runs = response["workflow_runs"]
            for run in runs:
                identifier = run["id"]
                if type(identifier) is not int or identifier <= 0:
                    raise RuntimeError("GitHub returned an invalid workflow run ID")
                if identifier in seen:
                    continue
                seen.add(identifier)
                job_page = 1
                while True:
                    jobs = api("GET", f"/repos/{pool['repository']}/actions/runs/{identifier}/jobs?filter=latest&per_page=100&page={job_page}")["jobs"]
                    for job in jobs:
                        labels = job.get("labels")
                        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
                            raise RuntimeError("GitHub returned invalid runner labels")
                        if job["status"] == "queued" and labels and {label.casefold() for label in labels} <= available:
                            return True
                    if len(jobs) < 100:
                        break
                    job_page += 1
            if len(runs) < 100:
                break
            page += 1
    return False


def serve(pool, key_file, client, checkout):
    while True:
        # A changed main requires a reviewed deployment refresh, not stale code.
        github_operator.verify_reviewed_main(checkout)
        native_identity(pool, client)
        api = installation_client(pool, key_file)
        if queued_jobs(api, pool):
            provision(api, client, checkout)
        time.sleep(30)


def provision(api, client, checkout):
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    repository = pool["repository"]
    workspace = runner_id = None
    creation_attempted = False
    registration_attempted = False
    policy = None

    def call(*arguments, timeout=45, input=None, capture=True):
        return subprocess.run(client + list(arguments), input=input, timeout=timeout, check=True,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.PIPE if capture else subprocess.DEVNULL)

    def inventory():
        return json.loads(call("get", "workspace", "--out", "json").stdout).get("items", [])

    try:
        isolation_backend(pool)
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
        policy = workspace_policy(response["metadata"])
        kube("create", "-f", "-", "-o", "json", input=json.dumps(policy).encode())
        live = json.loads(kube("get", "networkpolicy", policy["metadata"]["name"], "-n", "cordium", "-o", "json"))
        if not policy_matches(live, policy):
            raise RuntimeError("Runner network policy readback differs from its declaration")
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
        uid = response["metadata"]["uid"]
        pods = workspace_pods(uid)
        if (len(pods) != 1 or pods[0]["spec"].get("nodeName") != pool["worker_node"]
                or pods[0]["spec"].get("automountServiceAccountToken") is not False
                or any(pods[0]["spec"].get(flag) is True for flag in ("hostNetwork", "hostPID", "hostIPC"))):
            raise RuntimeError("Runner Pod placement or credential boundary differs from its declaration")
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
                if policy:
                    uid = response["metadata"]["uid"]
                    deadline = time.monotonic() + 60
                    while (workspace_pods(uid) or kube("get", "deployment", "ws-" + workspace, "-n", "cordium",
                                                       "--ignore-not-found", "-o", "json").strip()
                           or kube("get", "persistentvolumeclaim", "ws-" + uid, "-n", "cordium",
                                                       "--ignore-not-found", "-o", "json").strip()):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Runner Deployment/Pod/PVC deletion is not yet verified; retaining isolation")
                        time.sleep(2)
                    retire_policy(policy)
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
    parser.add_argument("--serve", action="store_true", help="Poll compatible queued jobs serially; stop on drift or any lifecycle failure")
    args = parser.parse_args()
    github_operator.verify_reviewed_main(args.expected_sha)
    github_operator.command("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/cordium-runner.py")
    pool = json.loads((ROOT / ".cordium/runner-pool.json").read_text())
    if pool["enabled"] is not True:
        raise RuntimeError("Runner registration is disabled until live network isolation is verified")
    version = github_operator.command("cordium", "version").decode()
    if not re.search(r"(?m)^gitCommit:\s*e12b0b16d5fe94716e414fca7cfdc10b21014f2c\s*$", version):
        raise RuntimeError("Install the pinned Cordium v0.12.7 client before runner provisioning")
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    client = ["cordium", "--homedir", str(args.homedir.resolve()), "--domain", "stinkyboi.com"]
    if args.serve:
        with open(args.homedir / "runner-controller.lock", "a", opener=lambda path, flags: os.open(path, flags, 0o600)) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            serve(pool, args.app_key_file, client, args.expected_sha)
    else:
        native_identity(pool, client)
        provision(installation_client(pool, args.app_key_file), client, args.expected_sha)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit("Runner provisioning or cleanup failed; private output withheld") from None
