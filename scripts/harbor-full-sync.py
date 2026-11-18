#!/usr/bin/env python3
"""Inspect or recover a timed-out Harbor sync using git, yq, kubectl and argocd."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import socket
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_gitops", ROOT / "scripts/verify-gitops.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
Failure = VERIFY.Failure
require = VERIFY.require
REPOSITORY = "https://github.com/Stuhlmuller/homelab.git"
CHART = "1.19.2"
SOURCES = [
    {"repoURL": "https://helm.goharbor.io", "chart": "harbor", "path": ".", "targetRevision": CHART,
     "helm": {"releaseName": "harbor", "valueFiles": ["$values/clusters/homelab/apps/harbor/values.yaml"]}},
    {"repoURL": REPOSITORY, "path": ".", "targetRevision": "main", "ref": "values",
     "directory": {"include": ".argocd-values-ref-placeholder.yaml"}},
    {"repoURL": REPOSITORY, "path": "clusters/homelab/apps/harbor", "targetRevision": "main"},
]
DEPLOYMENTS = ["harbor/harbor-core", "harbor/harbor-vulnerability-exporter"]
HOOKS = {"harbor-bootstrap", "harbor-postgres-backup-initial"}
TIMEOUT_MESSAGE = re.compile(
    r"Operation terminated, triggered by controller sync timeout(?: \(retried [1-9][0-9]* times\)\.)?\Z")


def run(*command, timeout=30):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            check=True, timeout=timeout)
    require(len(result.stdout) <= 4 * 1024 * 1024, "response_too_large")
    return result.stdout


def read(namespace, kind, *arguments):
    return json.loads(run("kubectl", "--request-timeout=15s", "-n", namespace,
                          "get", kind, *arguments, "-o", "json", timeout=20))


def verify_main(expected):
    require(bool(VERIFY.SHA.fullmatch(expected)), "invalid_revision")
    require(not run("git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"),
            "checkout_not_clean")
    require(run("git", "rev-parse", "HEAD").strip() == expected, "checkout_revision")
    require(run("git", "ls-remote", REPOSITORY, "refs/heads/main").strip()
            == expected + "\trefs/heads/main", "main_revision")


def core_image():
    image = json.loads(run("yq", "-o=json", ".core.image", "clusters/homelab/apps/harbor/values.yaml"))
    require(image.get("repository") == "harbor.stinkyboi.com/homelab/homelab-harbor-core"
            and isinstance(image.get("tag"), str)
            and re.fullmatch(r"homelab-[0-9a-f]{40}@sha256:[0-9a-f]{64}", image["tag"]),
            "declared_core_image")
    return image["repository"] + ":" + image["tag"]


def kube_context():
    config = json.loads(run("kubectl", "config", "view", "--minify", "-o", "json"))
    contexts = config["contexts"]
    require(len(contexts) == 1 and contexts[0]["name"] == config["current-context"], "kube_context")
    context = contexts[0]["context"]
    require(all(isinstance(value, str) and value for value in
                (config["current-context"], context.get("cluster"), context.get("user"))), "kube_context")
    return {"name": config["current-context"], "cluster": context["cluster"], "user": context["user"]}


@contextmanager
def argocd_server(expected, expected_uid):
    require(kube_context() == expected, "kube_context_changed")
    # v3.3.6 dashboard prints port zero instead of its allocated port. Select an
    # ephemeral port explicitly; a competing bind fails closed during startup.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    endpoint = "127.0.0.1:" + str(port)
    with tempfile.TemporaryDirectory(prefix="harbor-full-sync-") as directory:
        # An absent config prevents a user's stored core-mode setting from
        # starting another headless server. No kubeconfig is copied or changed.
        config = str(Path(directory) / "absent-config")
        # Append mode keeps child writes independent of readiness polling seeks.
        with (Path(directory) / "server.log").open(mode="a+t") as output:
            process = subprocess.Popen(
                ["argocd", "admin", "dashboard", "--namespace", "argocd",
                 "--context", expected["name"], "--address", "127.0.0.1",
                 "--port", str(port), "--config", config], cwd=ROOT,
                stdout=output, stderr=output, start_new_session=True)
            try:
                deadline = time.monotonic() + 90
                while True:
                    require(process.poll() is None, "argocd_server_exited")
                    require(time.monotonic() < deadline, "argocd_server_timeout")
                    output.seek(0)
                    logs = output.read(1024 * 1024 + 1)
                    require(len(logs) <= 1024 * 1024, "argocd_server_output_limit")
                    if "Argo CD UI is available at http://" in logs:
                        require("Argo CD UI is available at http://" + endpoint + "\n" in logs,
                                "argocd_server_endpoint")
                        break
                    time.sleep(0.2)
                flags = ("--server", endpoint, "--plaintext", "--config", config)
                # Prove the transport reaches the intended Application before
                # repeating all live preconditions immediately before mutation.
                app = json.loads(run("argocd", "app", "get", "harbor", *flags, "-o", "json"))
                # Argo RPC JSON omits Kubernetes type metadata.
                metadata = app["metadata"]
                require(metadata.get("name") == "harbor" and metadata.get("namespace") == "argocd"
                        and not metadata.get("deletionTimestamp")
                        and app.get("kind", "Application") == "Application", "argocd_application_identity")
                require(metadata.get("uid") == expected_uid, "argocd_application_uid")
                yield flags
            finally:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)


def contract(app, expected):
    VERIFY.identity(app, "Application", "argocd", "harbor")
    spec, status = app["spec"], app["status"]
    require(spec.get("sources") == SOURCES and not spec.get("source")
            and spec.get("project") == "homelab"
            and spec["destination"] == {"server": "https://kubernetes.default.svc", "namespace": "harbor"},
            "application_contract")
    sync = status["sync"]
    compared = sync["comparedTo"]
    require(compared.get("sources") == SOURCES and compared["destination"] == spec["destination"]
            and compared.get("ignoreDifferences", []) == spec.get("ignoreDifferences", []),
            "stale_comparison")
    require(app.get("operation") is None and sync["status"] == "Synced"
            and status["health"]["status"] == "Healthy"
            and sync["revisions"] == [CHART, expected, expected], "application_not_ready")
    require(not any(item["type"].endswith("Error") for item in status.get("conditions", [])),
            "application_error")
    VERIFY.tracked_deployments(app, [target.split("/") for target in DEPLOYMENTS])


def runtime(expected_image):
    proofs = [VERIFY.deployment(read, *target.split("/")) for target in DEPLOYMENTS]
    core = read("harbor", "deployment", "harbor-core")
    require(VERIFY.images(core["spec"]["template"]) == {"core": expected_image}, "core_image_mismatch")
    digest = expected_image.rsplit("@", 1)[1]
    require(all(pod["image_digests"] == {"core": digest} for pod in proofs[0]["pods"]),
            "core_digest_mismatch")
    return proofs


def preflight(expected):
    verify_main(expected)
    context = kube_context()
    image = core_image()
    app = read("argocd", "application", "harbor")
    contract(app, expected)
    operation = app["status"]["operationState"]
    require(operation["phase"] == "Failed" and operation.get("finishedAt") and operation.get("startedAt")
            and TIMEOUT_MESSAGE.fullmatch(operation.get("message", "")), "not_completed_sync_timeout")
    require(not operation.get("operation", {}).get("sync", {}).get("dryRun", False),
            "dry_run_operation")
    runtime(image)
    require(kube_context() == context, "kube_context_changed")
    return {"uid": app["metadata"]["uid"], "context": context, "operation_started": operation["startedAt"],
            "operation_finished": operation["finishedAt"], "image": image}


def postflight(expected, before):
    receipt = VERIFY.verify("harbor", expected, DEPLOYMENTS, read)
    app = read("argocd", "application", "harbor")
    contract(app, expected)
    operation = app["status"]["operationState"]
    require(app["metadata"]["uid"] == before["uid"] and operation["phase"] == "Succeeded"
            and operation.get("finishedAt") and operation.get("startedAt")
            and operation["startedAt"] != before["operation_started"]
            and operation["syncResult"]["revisions"] == [CHART, expected, expected],
            "recovery_operation_unverified")
    hooks = [item for item in operation["syncResult"]["resources"]
             if item.get("kind") == "Job" and item.get("namespace") == "harbor"
             and item.get("name") in HOOKS]
    require(len(hooks) == len(HOOKS) and {item["name"] for item in hooks} == HOOKS
            and all(item.get("group") == "batch" and item.get("hookType") == "PostSync"
                    and item.get("syncPhase") == "PostSync" and item.get("hookPhase") == "Succeeded"
                    for item in hooks), "postsync_hooks_unverified")
    runtime(before["image"])
    verify_main(expected)
    return receipt


def recover(expected, execute=False):
    before = preflight(expected)
    if not execute:
        return {"ready": True, "executed": False, "expected_sha": expected}
    with argocd_server(before["context"], before["uid"]) as flags:
        # Server startup can take time; repeat every precondition after readiness.
        require(preflight(expected) == before, "preflight_changed")
        run("argocd", "app", "sync", "harbor", *flags,
            "--revisions", CHART, "--source-positions", "1",
            "--revisions", expected, "--source-positions", "2",
            "--revisions", expected, "--source-positions", "3",
            "--timeout", "900", timeout=930)
        run("argocd", "app", "wait", "harbor", *flags,
            "--sync", "--health", "--operation", "--timeout", "900", timeout=930)
    require(kube_context() == before["context"], "kube_context_changed")
    postflight(expected, before)
    return {"ready": True, "executed": True, "controller_verified": True,
            "postsync_hooks_verified": True, "functional_acceptance": False, "expected_sha": expected}


def interrupted(_signal, _frame):
    raise Failure("interrupted")


def main(argv=None):
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        parser = VERIFY.Parser(description=__doc__)
        parser.add_argument("--expected-sha", required=True)
        parser.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        print(json.dumps(recover(args.expected_sha, args.execute), sort_keys=True))
        return 0
    except Failure as error:
        code = str(error)
    except KeyboardInterrupt:
        code = "interrupted"
    except (OSError, subprocess.SubprocessError):
        code = "command_unavailable_or_failed"
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        code = "invalid_evidence"
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps({"ready": False, "blocker": code, "functional_acceptance": False}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
