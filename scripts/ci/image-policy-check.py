#!/usr/bin/env python3
"""Exercise the real image policy in an isolated Kind cluster; never use homelab access."""

import copy
import json
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE_IMAGE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
CLUSTER = "image-policy-check"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def main():
    run("docker", "info")
    with tempfile.TemporaryDirectory(prefix="image-policy-check-") as directory:
        kubeconfig = str(Path(directory) / "kubeconfig")
        kubectl = ["kubectl", "--kubeconfig", kubeconfig]
        try:
            run("kind", "create", "cluster", "--name", CLUSTER, "--image", NODE_IMAGE,
                "--kubeconfig", kubeconfig, "--wait", "120s")
            run(*kubectl, "apply", "-k", str(ROOT / "clusters/homelab/platform/image-policy"))
            deadline = time.monotonic() + 30
            while True:
                policy = json.loads(run(*kubectl, "get", "validatingadmissionpolicy", "harbor-only-images", "-o", "json"))
                status = policy.get("status", {})
                if "typeChecking" in status and status.get("observedGeneration") == policy["metadata"]["generation"]:
                    assert not status["typeChecking"].get("expressionWarnings"), status["typeChecking"]
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("Native policy type checking did not converge")
                time.sleep(0.2)
            run(*kubectl, "create", "namespace", "image-policy-test")
            for namespace in ("image-policy-test", "kube-system"):
                run(*kubectl, "-n", namespace, "create", "serviceaccount", "flannel")
            run(*kubectl, "-n", "image-policy-test", "create", "serviceaccount", "fixture")
            pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "proof", "namespace": "image-policy-test"},
                   "spec": {"nodeName": "image-policy-unscheduled", "serviceAccountName": "fixture", "automountServiceAccountToken": False,
                            "containers": [{"name": "workload", "image": "harbor.stinkyboi.com/mirror/proof:latest", "imagePullPolicy": "Never"}]}}
            count = 0

            def check(candidate, allowed, *identity):
                nonlocal count
                result = subprocess.run([*kubectl, *identity, "create", "--dry-run=server", "-f", "-"],
                                        input=json.dumps(candidate), text=True, capture_output=True)
                if allowed:
                    assert result.returncode == 0, result.stderr
                else:
                    assert result.returncode != 0 and "harbor-only-images" in result.stderr, (candidate["metadata"], result.returncode, result.stderr)
                count += 1

            # Type checking is separate from admission informer propagation.
            probe = copy.deepcopy(pod)
            probe["spec"]["containers"][0]["image"] = "busybox:latest"
            deadline = time.monotonic() + 30
            while True:
                result = subprocess.run([*kubectl, "create", "--dry-run=server", "-f", "-"],
                                        input=json.dumps(probe), text=True, capture_output=True)
                if result.returncode:
                    assert "harbor-only-images" in result.stderr, result.stderr
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("Public-image rejection did not become active")
                time.sleep(0.2)
            check(pod, True)
            for image in ("busybox:latest", "cgr.dev/chainguard/busybox:latest", "harbor.stinkyboi.com.evil.example/proof:latest"):
                candidate = copy.deepcopy(pod)
                candidate["spec"]["containers"][0]["image"] = image
                check(candidate, False)
            for image, allowed in (("harbor.stinkyboi.com/mirror/init:latest", True), ("busybox:latest", False)):
                candidate = copy.deepcopy(pod)
                candidate["spec"]["initContainers"] = [{"name": "init", "image": image}]
                check(candidate, allowed)
            for account, image in (("flannel", "ghcr.io/siderolabs/flannel:v0.27.4"), ("kube-proxy", "registry.k8s.io/kube-proxy:v1.34.11")):
                candidate = copy.deepcopy(pod)
                candidate["metadata"]["namespace"] = "kube-system"
                candidate["spec"]["serviceAccountName"] = account
                candidate["spec"]["containers"][0]["image"] = image
                check(candidate, True)
                candidate["spec"]["serviceAccountName"] = "default"
                check(candidate, False)
            candidate = copy.deepcopy(pod)
            candidate["spec"]["serviceAccountName"] = "flannel"
            candidate["spec"]["containers"][0]["image"] = "ghcr.io/siderolabs/flannel:v0.27.4"
            check(candidate, False)
            candidate["metadata"]["namespace"] = "kube-system"
            candidate["spec"].pop("serviceAccountName")
            candidate["metadata"]["annotations"] = {"kubernetes.io/config.mirror": "proof"}
            check(candidate, False)
            node = json.loads(run(*kubectl, "get", "nodes", "-o", "json"))["items"][0]
            candidate["spec"]["nodeName"] = node["metadata"]["name"]
            candidate["metadata"]["ownerReferences"] = [{"apiVersion": "v1", "kind": "Node", "name": node["metadata"]["name"], "uid": node["metadata"]["uid"], "controller": True}]
            check(candidate, True, "--as=system:node:" + node["metadata"]["name"], "--as-group=system:nodes", "--as-group=system:authenticated")
            run(*kubectl, "create", "-f", "-", input=json.dumps(pod))
            current = json.loads(run(*kubectl, "-n", "image-policy-test", "get", "pod", "proof", "-o", "json"))
            for image, allowed in (("harbor.stinkyboi.com/mirror/debug:latest", True), ("busybox:latest", False)):
                candidate = copy.deepcopy(current)
                candidate["spec"]["ephemeralContainers"] = [{"name": "debug", "image": image, "imagePullPolicy": "Never"}]
                result = subprocess.run([*kubectl, "replace", "--raw", "/api/v1/namespaces/image-policy-test/pods/proof/ephemeralcontainers?dryRun=All", "-f", "-"],
                                        input=json.dumps(candidate), text=True, capture_output=True)
                assert (result.returncode == 0) if allowed else (result.returncode != 0 and "harbor-only-images" in result.stderr), result.stderr
                count += 1
            print(f"Native image admission: {count} allowed/denied cases passed; no workload images pulled")
        finally:
            run("kind", "delete", "cluster", "--name", CLUSTER)


if __name__ == "__main__":
    main()
