"""Render the declared LiteLLM chart and check its Phase 1 runtime controls."""

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
    pod = deployments[0]["spec"]["template"]["spec"]
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
    for control in ("token", "seccomp", "privileged", "escalation", "capabilities"):
        changed = copy.deepcopy(objects)
        account = next(item for item in changed if item["kind"] == "ServiceAccount")
        pod = next(item for item in changed if item["kind"] == "Deployment")["spec"]["template"]["spec"]
        if control == "token":
            account["automountServiceAccountToken"] = True
        elif control == "seccomp":
            pod["securityContext"]["seccompProfile"] = {"type": "Unconfined"}
        elif control == "privileged":
            pod["containers"][0]["securityContext"]["privileged"] = True
        elif control == "escalation":
            pod["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
        else:
            pod["containers"][0]["securityContext"]["capabilities"] = {}
        try:
            check(changed)
        except AssertionError:
            continue
        raise AssertionError(f"Unsafe LiteLLM {control} control accepted")
    print("LiteLLM: pinned chart lint/render and five negative runtime-control checks passed")


if __name__ == "__main__":
    main()
