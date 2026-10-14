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


def expect_warning(result):
    assert result.returncode == 0, output(result)
    assert WARNING in output(result) and "Harbor" in output(result), output(result)


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


def pod(name="proof", namespace="image-policy-test"):
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
            assert "variables" not in spec and "matchConditions" not in spec, spec
            assert binding["spec"] == {
                "policyName": POLICY,
                "validationActions": ["Warn", "Audit"],
            }, binding["spec"]
            assert "matchResources" not in binding["spec"], binding["spec"]

            run(*kubectl, "create", "namespace", "image-policy-test")

            def create(candidate):
                return invoke(*kubectl, "create", "--dry-run=server", "-f", "-",
                              input=json.dumps(candidate))

            public = pod()
            public["spec"]["containers"][0]["image"] = "busybox:latest"

            def policy_active():
                result = create(public)
                return result if result.returncode == 0 and WARNING in output(result) else None

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
                expect_warning(create(candidate))
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
            expect_warning(create(public_init))
            cases += 2

            kube_system = pod(namespace="kube-system")
            kube_system["spec"]["containers"][0]["image"] = "registry.k8s.io/pause:latest"
            expect_warning(create(kube_system))
            cases += 1

            run(*kubectl, "create", "-f", "-", input=json.dumps(pod()))
            update = invoke(*kubectl, "-n", "image-policy-test", "patch", "pod", "proof",
                            "--type=merge", "--patch", json.dumps({"spec": {"containers": [{
                                "name": "workload", "image": "busybox:latest",
                            }]}}), "--dry-run=server")
            expect_warning(update)
            cases += 1

            current = json.loads(run(*kubectl, "-n", "image-policy-test", "get", "pod", "proof", "-o", "json"))
            for image, warning in (
                ("harbor.stinkyboi.com/mirror/debug:latest", None),
                ("busybox:latest", True),
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
                if warning:
                    expect_warning(debug)
                else:
                    expect_clean(debug)
                cases += 1

            deny_binding = {
                "apiVersion": "admissionregistration.k8s.io/v1",
                "kind": "ValidatingAdmissionPolicyBinding",
                "metadata": {"name": POLICY},
                "spec": {"policyName": POLICY, "validationActions": ["Deny"]},
            }
            run(*kubectl, "apply", "-f", "-", input=json.dumps(deny_binding))

            def policy_denies():
                result = create(public)
                return result if result.returncode != 0 and POLICY in output(result) else None

            wait_for("native policy denial", policy_denies)
            expect_denied(create(public_init))
            cases += 2

            denied_update = invoke(*kubectl, "-n", "image-policy-test", "patch", "pod", "proof",
                                   "--type=merge", "--patch", json.dumps({"spec": {"containers": [{
                                       "name": "workload", "image": "busybox:latest",
                                   }]}}), "--dry-run=server")
            expect_denied(denied_update)
            cases += 1

            denied_debug = copy.deepcopy(current)
            denied_debug["spec"]["ephemeralContainers"] = [{
                "name": "debug",
                "image": "busybox:latest",
                "imagePullPolicy": "Never",
            }]
            expect_denied(invoke(
                *kubectl, "replace", "--raw",
                "/api/v1/namespaces/image-policy-test/pods/proof/ephemeralcontainers?dryRun=All",
                "-f", "-", input=json.dumps(denied_debug)))
            cases += 1

            print(f"Native image admission: {cases} Warn/Audit and Deny cases passed; no workload images pulled")
        finally:
            if cluster_attempted:
                cleanup = invoke("kind", "delete", "cluster", "--name", CLUSTER)
                if cleanup.returncode and sys.exc_info()[0] is None:
                    raise AssertionError(f"Kind cleanup failed:\n{output(cleanup)}")


if __name__ == "__main__":
    main()
