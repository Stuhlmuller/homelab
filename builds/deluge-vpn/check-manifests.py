"""Check the staged Deluge VPN resources and the proposed Deluge chart cutover."""

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/deluge"
OVERLAY = APP / "active-active"
STACK = ROOT / "IaC/homelab/us-west-2/apps/deluge/stack.hcl"
SSM = ROOT / "IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl"
REQUIRED_POD_LABELS = ("app.kubernetes.io/controller", "app.kubernetes.io/instance", "app.kubernetes.io/name")
VPN_IMAGE = "harbor.stinkyboi.com/homelab/homelab-deluge-vpn"
PUBLISHED_IMAGE = re.compile(re.escape(VPN_IMAGE) + r":homelab-[0-9a-f]{40}@sha256:[0-9a-f]{64}")
# The running image bundles libtorrent 1.1.5 with one wildcard UDP socket.
INCOMPATIBLE_DELUGE_DIGEST = "sha256:0ac8716243944d28890565f759c7cedfc9e36a3fd5a827c9d0927abc0c8f97c9"


def render(*command):
    output = subprocess.check_output(command, text=True)
    json_output = subprocess.check_output(
        ["yq", "eval", "-o=json", "-I=0", ".", "-"], input=output, text=True,
    )
    documents = [json.loads(line) for line in json_output.splitlines() if line]
    return {(item["kind"], item["metadata"]["name"]): item for item in documents if item}


def helm(version, values):
    values_args = [part for file in values for part in ("-f", file)]
    return render("helm", "template", "deluge", "app-template", "--namespace", "media",
                  "--repo", "https://bjw-s-labs.github.io/helm-charts", "--version", version, *values_args)


def check_secret_bindings(resources):
    declarations = re.findall(r'^\s*"(/homelab/deluge/[^"]+)"\s*=\s*\{([^}]+)\}', SSM.read_text(), re.M)
    readers = {path for path, content in declarations if "reader_access = false" not in content}
    for (kind, _), item in resources.items():
        if kind == "ExternalSecret":
            assert item["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "aws-ssm"}
            assert {source["remoteRef"]["key"] for source in item["spec"]["data"]} <= readers


def vpn_images(resources):
    result = set()
    for (kind, _), resource in resources.items():
        if kind == "Deployment":
            pod = resource["spec"]["template"]["spec"]
            for container in pod.get("initContainers", []) + pod["containers"]:
                if container["image"].startswith(VPN_IMAGE + ":"):
                    result.add(container["image"])
    return result


def check_registration(stack, gateways, canary, active):
    overlay = OVERLAY.relative_to(ROOT).as_posix()
    gateway_registered = f'"{overlay}"' in stack
    canary_registered = f'"{overlay}/canary"' in stack
    active_registered = f'$values/{overlay}/values.yaml"' in stack
    assert not (canary_registered and active_registered), "Canary and Deluge cannot share active transit keys"
    assert gateway_registered or not (canary_registered or active_registered)

    registered = ((gateway_registered, gateways), (canary_registered, canary), (active_registered, active))
    if gateway_registered:
        images = set().union(*(vpn_images(resources) for enabled, resources in registered if enabled))
        assert len(images) == 1 and PUBLISHED_IMAGE.fullmatch(next(iter(images))), (
            "Argo CD sources must use the same published immutable Harbor image"
        )
    if active_registered:
        pod = active["Deployment", "deluge"]["spec"]["template"]["spec"]
        app = next(container for container in pod["containers"] if container["name"] == "app")
        assert not app["image"].endswith(f"@{INCOMPATIBLE_DELUGE_DIGEST}"), (
            "The current Deluge image cannot open per-address UDP listeners"
        )


def main():
    stack = STACK.read_text()
    version = re.search(r'targetRevision\s*=\s*"([0-9.]+)"', stack)[1]
    baseline = helm(version, [APP / "values.yaml"])
    active = helm(version, [APP / "values.yaml", OVERLAY / "values.yaml"])
    stages = render("kustomize", "build", OVERLAY)
    canary = render("kustomize", "build", OVERLAY / "canary")
    check_registration(stack, stages, canary, active)

    if "active-active/" not in stack:
        assert not stages.keys() & render("kustomize", "build", APP).keys()
        assert any(container["name"] == "gluetun" for container in
                   baseline["Deployment", "deluge"]["spec"]["template"]["spec"]["initContainers"])

    for path, node, ip in (("a", "zimaboard-1", "10.96.10.61"), ("b", "zimaboard-2", "10.96.10.62")):
        name = f"deluge-vpn-{path}"
        service = stages["Service", name]["spec"]
        deploy = stages["Deployment", name]["spec"]
        pod = deploy["template"]["spec"]
        assert service["clusterIP"] == ip
        assert service["selector"] == deploy["template"]["metadata"]["labels"]
        assert service["ports"] == [{"name": "transit", "port": 51820, "protocol": "UDP", "targetPort": "transit"}]
        assert deploy["replicas"] == 1 and deploy["strategy"]["type"] == "Recreate"
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": node}
        assert pod["containers"][0]["command"][-1] == path
        assert {volume["secret"]["secretName"] for volume in pod["volumes"] if "secret" in volume} == {
            f"{name}-airvpn", f"{name}-transit",
        }
    check_secret_bindings(stages)

    deploy = active["Deployment", "deluge"]
    pod = deploy["spec"]["template"]["spec"]
    assert deploy["spec"]["replicas"] == 1 and deploy["spec"]["strategy"]["type"] == "Recreate"
    assert pod["dnsPolicy"] == "None" and pod["dnsConfig"] == {"nameservers": ["127.0.0.1"]}
    assert [container["name"] for container in pod["initContainers"]] == [
        "vpn-guard", "vpn-client-preflight", "download-dirs",
    ]
    app = next(container for container in pod["containers"] if container["name"] == "app")
    preflight = pod["initContainers"][1]
    assert preflight["image"] == app["image"]
    assert preflight["command"] == ["python3", "-B", "/scripts/vpn-client-preflight.py"]
    assert {mount["mountPath"] for mount in preflight["volumeMounts"] if mount["readOnly"]} == {"/config", "/scripts"}
    assert {volume["persistentVolumeClaim"]["claimName"] for volume in pod["volumes"]
            if "persistentVolumeClaim" in volume} == {"deluge-config-local", "media-downloads"}
    for container in pod["initContainers"] + pod["containers"]:
        name = container["name"]
        capabilities = container["securityContext"]["capabilities"]
        if name in {"vpn-guard", "vpn-health"}:
            assert any(mount["name"] == "vpn-transit" and mount["readOnly"]
                       for mount in container["volumeMounts"])
        else:
            assert "ALL" in capabilities["drop"] or {"NET_RAW", "NET_ADMIN"} <= set(capabilities["drop"])
            assert not {"NET_RAW", "NET_ADMIN"} & set(capabilities.get("add", []))

    labels = deploy["spec"]["template"]["metadata"]["labels"]
    expected_selector = {key: labels[key] for key in REQUIRED_POD_LABELS}
    for name, ports, publish_not_ready in (("deluge", {8112}, False), ("deluge-metrics", {9797, 9798}, True)):
        service = active["Service", name]["spec"]
        assert service["selector"] == expected_selector
        assert service.get("publishNotReadyAddresses", False) == publish_not_ready
        assert {port["port"] for port in service["ports"]} == ports

    for pod in (pod, canary["Deployment", "deluge-vpn-canary"]["spec"]["template"]["spec"],
                *(stages["Deployment", f"deluge-vpn-{path}"]["spec"]["template"]["spec"] for path in ("a", "b"))):
        assert pod["imagePullSecrets"] == [{"name": "deluge-vpn-harbor-pull"}]
        assert not pod["automountServiceAccountToken"]
    print("Deluge VPN staging, activation, and rollback manifests passed")


if __name__ == "__main__":
    main()
