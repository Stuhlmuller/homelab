#!/usr/bin/env python3
"""Exercise the native image policy in disposable Kind; never use homelab access."""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE_IMAGE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
CLUSTER = f"image-policy-check-{os.getpid()}"
POLICY = "harbor-only-images"
WARNING = f"ValidatingAdmissionPolicy '{POLICY}' with binding '{POLICY}'"


def invoke(*args, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True)


def run(*args, input=None):
    result = invoke(*args, input=input)
    if result.returncode:
        raise AssertionError(f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def output(result):
    return f"{result.stdout}\n{result.stderr}"


def expect_clean(result):
    assert result.returncode == 0, output(result)
    assert WARNING not in output(result), output(result)


def expect_denied(result):
    assert result.returncode != 0, output(result)
    assert POLICY in output(result) and "Harbor" in output(result), output(result)


def wait_for(description, check):
    deadline = time.monotonic() + 30
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last is not None:
            return last
        time.sleep(0.2)
    raise AssertionError(f"{description} did not converge: {last}")


def pod(name="admission-proof", namespace="image-policy-test"):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "automountServiceAccountToken": False,
            "nodeName": "image-policy-unscheduled",
            "containers": [{
                "name": "workload",
                "image": "harbor.stinkyboi.com/mirror/proof:latest",
                "imagePullPolicy": "Never",
            }],
        },
    }


def main():
    cluster_attempted = False
    if not shutil.which("docker"):
        raise AssertionError("Docker is required for the disposable Kind test.")
    run("docker", "info")
    with tempfile.TemporaryDirectory(prefix="image-policy-check-") as directory:
        kubeconfig = str(Path(directory) / "kubeconfig")
        kubectl = ("kubectl", "--kubeconfig", kubeconfig)
        try:
            cluster_attempted = True
            run("kind", "create", "cluster", "--name", CLUSTER, "--image", NODE_IMAGE,
                "--kubeconfig", kubeconfig, "--wait", "120s")
            run(*kubectl, "apply", "-k", str(ROOT / "clusters/homelab/platform/image-policy"))

            def type_checked():
                policy_resource = json.loads(run(*kubectl, "get", "validatingadmissionpolicy", POLICY, "-o", "json"))
                status = policy_resource.get("status", {})
                if status.get("observedGeneration") != policy_resource["metadata"]["generation"]:
                    return None
                type_checking = status.get("typeChecking")
                if type_checking is None:
                    return None
                assert not type_checking.get("expressionWarnings"), type_checking
                return policy_resource

            policy_resource = wait_for("native policy type checking", type_checked)
            binding = json.loads(run(*kubectl, "get", "validatingadmissionpolicybinding", POLICY, "-o", "json"))
            spec = policy_resource["spec"]
            assert spec["failurePolicy"] == "Fail", spec
            assert spec["matchConstraints"]["resourceRules"] == [{
                "apiGroups": [""],
                "apiVersions": ["v1"],
                "operations": ["CREATE", "UPDATE"],
                "resources": ["pods", "pods/ephemeralcontainers"],
                "scope": "*",
            }], spec
            assert [item["name"] for item in spec["variables"]] == [
                "nodeMirror", "systemNetworkImages"], spec
            assert "matchConditions" not in spec, spec
            assert binding["spec"] == {
                "policyName": POLICY,
                "validationActions": ["Deny", "Audit"],
            }, binding["spec"]
            assert "matchResources" not in binding["spec"], binding["spec"]

            run(*kubectl, "create", "namespace", "image-policy-test")
            for namespace in ("image-policy-test", "kube-system"):
                for account in ("flannel", "kube-proxy"):
                    if invoke(*kubectl, "-n", namespace, "get", "serviceaccount", account).returncode:
                        run(*kubectl, "-n", namespace, "create", "serviceaccount", account)

            def create(candidate):
                return invoke(*kubectl, "create", "--dry-run=server", "-f", "-",
                              input=json.dumps(candidate))

            public = pod()
            public["spec"]["containers"][0]["image"] = "busybox:latest"

            def policy_active():
                result = create(public)
                return result if result.returncode != 0 and POLICY in output(result) else None

            wait_for("native policy admission", policy_active)
            expect_clean(create(pod()))

            cases = 1
            for image in (
                "busybox:latest",
                "cgr.dev/chainguard/busybox:latest",
                "harbor.stinkyboi.com.evil.example/proof:latest",
                "harbor.stinkyboi.com:443/mirror/proof:latest",
            ):
                candidate = pod()
                candidate["spec"]["containers"][0]["image"] = image
                expect_denied(create(candidate))
                cases += 1

            internal_init = pod()
            internal_init["spec"]["initContainers"] = [{
                "name": "init",
                "image": "harbor.stinkyboi.com/mirror/init:latest",
                "imagePullPolicy": "Never",
            }]
            expect_clean(create(internal_init))
            public_init = copy.deepcopy(internal_init)
            public_init["spec"]["initContainers"][0]["image"] = "busybox:latest"
            expect_denied(create(public_init))
            cases += 2

            kube_system = pod(namespace="kube-system")
            kube_system["spec"]["containers"][0]["image"] = "registry.k8s.io/pause:latest"
            expect_denied(create(kube_system))
            cases += 1

            for account, image in (("flannel", "ghcr.io/siderolabs/flannel:v0.27.4"),
                                   ("kube-proxy", "registry.k8s.io/kube-proxy:v1.34.11")):
                system = pod(namespace="kube-system")
                system["spec"]["serviceAccountName"] = account
                system["spec"]["containers"][0]["image"] = image
                expect_clean(create(system))
                system["spec"]["serviceAccountName"] = "default"
                expect_denied(create(system))
                system["metadata"]["namespace"] = "image-policy-test"
                system["spec"]["serviceAccountName"] = account
                expect_denied(create(system))
                cases += 3

            mirror = pod(namespace="kube-system")
            mirror["metadata"]["annotations"] = {"kubernetes.io/config.mirror": "proof"}
            mirror["spec"]["containers"][0]["image"] = "busybox:latest"
            expect_denied(create(mirror))
            node = json.loads(run(*kubectl, "get", "nodes", "-o", "json"))["items"][0]
            mirror["spec"]["nodeName"] = node["metadata"]["name"]
            expect_clean(invoke(*kubectl, "--as=system:node:" + node["metadata"]["name"],
                                "--as-group=system:nodes", "--as-group=system:authenticated",
                                "create", "--dry-run=server", "-f", "-", input=json.dumps(mirror)))
            cases += 2

            run(*kubectl, "create", "-f", "-", input=json.dumps(pod(name="proof")))
            update = invoke(*kubectl, "-n", "image-policy-test", "patch", "pod", "proof",
                            "--type=json", "--patch", json.dumps([{
                                "op": "replace", "path": "/spec/containers/0/image",
                                "value": "busybox:latest",
                            }]), "--dry-run=server")
            expect_denied(update)
            cases += 1

            current = json.loads(run(*kubectl, "-n", "image-policy-test", "get", "pod", "proof", "-o", "json"))
            for image, allowed in (
                ("harbor.stinkyboi.com/mirror/debug:latest", True),
                ("busybox:latest", False),
            ):
                candidate = copy.deepcopy(current)
                candidate["spec"]["ephemeralContainers"] = [{
                    "name": "debug",
                    "image": image,
                    "imagePullPolicy": "Never",
                }]
                debug = invoke(*kubectl, "replace", "--raw",
                               "/api/v1/namespaces/image-policy-test/pods/proof/ephemeralcontainers?dryRun=All",
                               "-f", "-", input=json.dumps(candidate))
                if allowed:
                    expect_clean(debug)
                else:
                    expect_denied(debug)
                cases += 1

            print(f"Native image admission: {cases} allowed/denied cases passed; no workload images pulled")
        finally:
            if cluster_attempted:
                cleanup = invoke("kind", "delete", "cluster", "--name", CLUSTER)
                if cleanup.returncode and sys.exc_info()[0] is None:
                    raise AssertionError(f"Kind cleanup failed:\n{output(cleanup)}")


if __name__ == "__main__":
    main()
