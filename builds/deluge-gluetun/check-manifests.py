"""Render and check the staged Gluetun handoff and rollback resources."""

import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/deluge"
PROFILE = APP / "gluetun-failover"
STACK_DIR = ROOT / "IaC/homelab/us-west-2/apps/deluge"
HELPER_IMAGE = "harbor.stinkyboi.com/homelab/homelab-deluge-vpn"
PUBLISHED_IMAGE = re.compile(re.escape(HELPER_IMAGE) + r":homelab-[a-f0-9]{40}@sha256:[a-f0-9]{64}")


def render(*command):
    output = subprocess.check_output(command, text=True)
    return {(obj["kind"], obj["metadata"]["name"]): obj for obj in yaml.safe_load_all(output) if obj}


def helm(version, *overrides):
    values = [flag for file in (APP / "values.yaml", *overrides) for flag in ("-f", file)]
    return render("helm", "template", "deluge", "app-template", "--namespace", "media",
                  "--repo", "https://bjw-s-labs.github.io/helm-charts", "--version", version, *values)


def helper_images(pod_spec):
    containers = pod_spec["containers"] + pod_spec.get("initContainers", [])
    return {c["image"] for c in containers if c["image"].startswith(HELPER_IMAGE + ":")}


def require_registration_safety(stack, gateway, client):
    path = PROFILE.relative_to(ROOT).as_posix()
    registered = f'"{path}"' in stack
    stopped = f'"{path}-stopped"' in stack
    quiescing = f'"$values/{path}/quiesce-values.yaml"' in stack
    active = f'"$values/{path}/values.yaml"' in stack

    assert not (registered and stopped), "Select one gateway overlay"
    assert not (quiescing and active), "Select one Deluge values overlay"
    assert not registered or active or quiescing, "Quiesce the original Gluetun before registering gateways"
    assert not active or registered or stopped, "The active client requires the gateway resources"
    if registered or stopped:
        bootstrap = (STACK_DIR / "terragrunt.stack.hcl").read_text()
        assert re.search(r'enabled\s*=\s*true', bootstrap), "Bootstrap the scoped Lease and EndpointSlice"
        references = helper_images(gateway)
        if active:
            references |= helper_images(client)
        assert len(references) == 1 and PUBLISHED_IMAGE.fullmatch(next(iter(references))), (
            "Use the same published immutable helper image on the client and gateway"
        )


def check_gateway(resources, original_gluetun):
    service = resources["Service", "deluge-gluetun"]["spec"]
    assert "selector" not in service and service["clusterIP"] == "10.96.10.61"
    assert service["ports"] == [{"name": "transit", "port": 51820, "targetPort": 51820, "protocol": "UDP"}]
    role = resources["Role", "deluge-gluetun"]
    assert role["rules"] == [
        {"apiGroups": ["coordination.k8s.io"], "resources": ["leases"],
         "resourceNames": ["deluge-gluetun"], "verbs": ["get", "update"]},
        {"apiGroups": ["discovery.k8s.io"], "resources": ["endpointslices"],
         "resourceNames": ["deluge-gluetun"], "verbs": ["get", "update"]},
    ]
    deployment = resources["Deployment", "deluge-gluetun"]["spec"]
    assert deployment["replicas"] == 2
    assert deployment["strategy"]["rollingUpdate"] == {"maxSurge": 0, "maxUnavailable": 1}
    pod = deployment["template"]["spec"]
    assert not pod["automountServiceAccountToken"]
    replicas = pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert replicas == [{
        "topologyKey": "kubernetes.io/hostname",
        "labelSelector": {"matchLabels": deployment["selector"]["matchLabels"]},
    }]
    containers = {c["name"]: c for c in pod["containers"] + pod["initContainers"]}
    assert set(containers) == {"leader", "gluetun", "gateway-guard"}
    assert containers["gluetun"]["image"] == original_gluetun["image"]
    assert containers["gateway-guard"]["command"][-1] == "gateway-init"
    assert {v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v} == {"deluge-vpn"}
    assert {c["name"] for c in containers.values() if
            any(m["name"] == "kube-api" for m in c["volumeMounts"])} == {"leader"}
    assert {c["name"] for c in containers.values() if
            any(m["name"] == "profile" for m in c["volumeMounts"])} == {"gateway-guard", "gluetun"}
    assert "Lease" not in {kind for kind, _ in resources}
    assert "EndpointSlice" not in {kind for kind, _ in resources}
    return pod


def check_client(resources, original_app):
    deployment = resources["Deployment", "deluge"]["spec"]
    assert deployment["replicas"] == 1 and deployment["strategy"]["type"] == "Recreate"
    pod = deployment["template"]["spec"]
    assert [c["name"] for c in pod["initContainers"]] == ["vpn-guard", "download-dirs"]
    assert pod["initContainers"][0]["command"][-1] == "client-init"
    assert not pod["automountServiceAccountToken"]
    assert pod["dnsPolicy"] == "None" and pod["dnsConfig"] == {"nameservers": ["127.0.0.1"]}
    assert not any("hostPath" in volume for volume in pod["volumes"])
    assert {volume["secret"]["secretName"] for volume in pod["volumes"] if "secret" in volume} == {"deluge-vpn"}
    assert {volume["persistentVolumeClaim"]["claimName"] for volume in pod["volumes"]
            if "persistentVolumeClaim" in volume} == {"deluge-config-local", "media-downloads"}
    app = next(c for c in pod["containers"] if c["name"] == "app")
    assert app["image"] == original_app["image"] and app["command"] == original_app["command"]
    for container in pod["containers"] + pod["initContainers"]:
        cap = container["securityContext"]["capabilities"]
        if container["name"] in {"vpn-guard", "vpn-health"}:
            assert cap["drop"] == ["ALL"] and "NET_ADMIN" in cap["add"]
        else:
            assert {"NET_ADMIN", "NET_RAW"} <= set(cap["drop"]) and not cap.get("add")
    for name, port, publish_unready in (("deluge", 8112, False), ("deluge-metrics", 9797, True)):
        service = resources["Service", name]["spec"]
        assert service["ports"][0]["port"] == port and len(service["ports"]) == 1
        assert service.get("publishNotReadyAddresses", False) == publish_unready
        assert service["selector"] == deployment["selector"]["matchLabels"]
    return pod


def main():
    stack = (STACK_DIR / "stack.hcl").read_text()
    chart_version = re.search(r'targetRevision\s*=\s*"([0-9.]+)"', stack)[1]
    original = helm(chart_version)["Deployment", "deluge"]["spec"]["template"]["spec"]
    original_gluetun = next(container for container in original["initContainers"] if container["name"] == "gluetun")
    original_app = next(container for container in original["containers"] if container["name"] == "app")

    quiesce = helm(chart_version, PROFILE / "quiesce-values.yaml")
    assert quiesce["Deployment", "deluge"]["spec"]["replicas"] == 0
    client = check_client(helm(chart_version, PROFILE / "values.yaml"), original_app)
    gateways = render("kustomize", "build", PROFILE)
    gateway = check_gateway(gateways, original_gluetun)
    stopped = render("kustomize", "build", PROFILE.with_name("gluetun-failover-stopped"))
    assert stopped["Deployment", "deluge-gluetun"]["spec"]["replicas"] == 0
    assert not gateways.keys() & render("kustomize", "build", APP).keys()

    require_registration_safety(stack, gateway, client)
    print("Staged Deluge Gluetun quiesce, handoff, and rollback manifests passed")


if __name__ == "__main__":
    main()
