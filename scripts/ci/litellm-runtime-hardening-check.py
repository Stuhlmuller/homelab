"""Render the declared LiteLLM chart and check runtime controls and gateway placement."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "clusters/homelab/apps/litellm/values.yaml"
STACK = ROOT / "IaC/homelab/us-west-2/apps/litellm/stack.hcl"
CHART_VERSION = "0.1.832"


def check(objects):
    accounts = [item for item in objects if item["kind"] == "ServiceAccount"]
    assert len(accounts) == 1 and accounts[0]["metadata"]["name"] == "litellm"
    assert accounts[0].get("automountServiceAccountToken") is False
    deployments = [item for item in objects if item["kind"] == "Deployment"]
    assert len(deployments) == 1
    deployment = deployments[0]["spec"]
    assert deployment["replicas"] == 1
    # The pinned chart omits strategy, retaining Kubernetes RollingUpdate defaults.
    strategy = deployment.get("strategy", {})
    assert strategy.get("type", "RollingUpdate") == "RollingUpdate"
    rolling = strategy.get("rollingUpdate", {})
    assert rolling.get("maxSurge", "25%") == "25%"
    assert rolling.get("maxUnavailable", "25%") == "25%"
    pod = deployment["template"]["spec"]
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "acer"}
    assert not pod.get("affinity")
    assert pod["serviceAccountName"] == "litellm"
    assert pod.get("automountServiceAccountToken") is not True
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert not any(
        "serviceAccountToken" in source
        for volume in pod.get("volumes", [])
        for source in volume.get("projected", {}).get("sources", [])
    )
    containers = pod["containers"]
    assert len(containers) == 1 and containers[0]["name"] == "litellm"
    assert containers[0]["resources"] == {"requests": {"memory": "1Gi"}}
    security = containers[0]["securityContext"]
    assert security.get("privileged") is not True
    assert security["allowPrivilegeEscalation"] is False
    assert security["capabilities"] == {"drop": ["ALL"]}
    assert "seccompProfile" not in security, "Do not override the pod seccomp profile"
    # Phase 2 needs a new writable-path proof for native database startup.
    for context in (pod["securityContext"], security):
        assert not {"runAsUser", "runAsGroup", "runAsNonRoot", "readOnlyRootFilesystem"} & context.keys()
    assert not pod.get("initContainers")
    assert not any(item["kind"] in {"Job", "StatefulSet"} for item in objects)


def main():
    expected = f'''
    {{
      repoURL = "ghcr.io/berriai"
      chart = "litellm-helm"
      path = "."
      targetRevision = "{CHART_VERSION}"
      helm = {{
        releaseName = "litellm"
        valueFiles = ["$values/clusters/homelab/apps/litellm/values.yaml"]
      }}
    }}
    '''
    assert " ".join(STACK.read_text().split()).count(" ".join(expected.split())) == 1, \
        "LiteLLM chart source changed: update the runtime render fixture"

    with tempfile.TemporaryDirectory(prefix="litellm-runtime-") as directory:
        scratch = Path(directory)
        docker = scratch / "docker"
        docker.mkdir()
        registry = docker / "config.json"
        registry.write_text('{"auths": {}}\n')
        # Public chart verification must not use workstation registry credentials.
        subprocess.run([
            "helm", "pull", "oci://ghcr.io/berriai/litellm-helm",
            "--version", CHART_VERSION, "--destination", str(scratch),
            "--registry-config", str(registry),
        ], env={**os.environ, "DOCKER_CONFIG": str(docker)}, check=True)
        chart = scratch / f"litellm-helm-{CHART_VERSION}.tgz"
        subprocess.run(["helm", "lint", str(chart), "--values", str(VALUES)], check=True)
        rendered = subprocess.check_output([
            "helm", "template", "litellm", str(chart), "--namespace", "ai",
            "--values", str(VALUES),
        ], text=True)
    objects = json.loads(subprocess.check_output([
        "yq", "ea", "-o=json", "-I=0", "[.]", "-",
    ], input=rendered, text=True))
    check(objects)
    controls = (
        "token", "seccomp", "privileged", "escalation", "capabilities",
        "missing-request", "low-request", "unmeasured-limit", "missing-placement",
        "wrong-node", "recreate", "replicas", "unavailable",
    )
    for control in controls:
        changed = copy.deepcopy(objects)
        account = next(item for item in changed if item["kind"] == "ServiceAccount")
        deployment = next(item for item in changed if item["kind"] == "Deployment")["spec"]
        pod = deployment["template"]["spec"]
        if control == "token":
            account["automountServiceAccountToken"] = True
        elif control == "seccomp":
            pod["securityContext"]["seccompProfile"] = {"type": "Unconfined"}
        elif control == "privileged":
            pod["containers"][0]["securityContext"]["privileged"] = True
        elif control == "escalation":
            pod["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
        elif control == "capabilities":
            pod["containers"][0]["securityContext"]["capabilities"] = {}
        elif control == "missing-request":
            pod["containers"][0]["resources"] = {}
        elif control == "low-request":
            pod["containers"][0]["resources"]["requests"]["memory"] = "512Mi"
        elif control == "unmeasured-limit":
            pod["containers"][0]["resources"]["limits"] = {"memory": "1Gi"}
        elif control == "missing-placement":
            pod["nodeSelector"] = {}
        elif control == "wrong-node":
            pod["nodeSelector"]["kubernetes.io/hostname"] = "zimaboard-2"
        elif control == "recreate":
            deployment["strategy"] = {"type": "Recreate"}
        elif control == "replicas":
            deployment["replicas"] = 2
        else:
            deployment["strategy"] = {"rollingUpdate": {"maxUnavailable": 1}}
        try:
            check(changed)
        except AssertionError:
            continue
        raise AssertionError(f"Unsafe LiteLLM {control} control accepted")
    print(f"LiteLLM: pinned chart lint/render and {len(controls)} negative runtime/placement checks passed")


if __name__ == "__main__":
    main()
