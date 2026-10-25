#!/usr/bin/env python3
"""Qualify the private Traefik ingress boundary from two declared Harbor Pods."""

import argparse
import ipaddress
import json
import os
import runpy
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = runpy.run_path(str(ROOT / "scripts/network-policy-inventory.py"))
PROBES = {"allow": "traefik-policy-allow", "deny": "traefik-policy-deny"}
REPO_URL = "https://github.com/Stuhlmuller/homelab.git"
APPLICATIONS = {
    "harbor": ("https://helm.goharbor.io", "harbor", "1.19.2"),
    "traefik": ("https://bjw-s-labs.github.io/helm-charts", "app-template", "4.4.0"),
}
IMAGE = ("harbor.stinkyboi.com/mirror/cgr.dev/chainguard/python:"
         "1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394"
         "@sha256:1c4deeea85db49ab5f6bcd9e7fc0bf3fd8439e99f7bde45330f40400685eb394")
PROBE_CODE = """import socket,ssl,sys
address,mode=sys.argv[1:]
port=15008 if mode=='control' else 8443
try:
 connection=socket.create_connection((address,port),timeout=3)
except OSError:
 if mode=='deny': print('DENIED'); sys.exit(0)
 sys.exit(7)
with connection:
 if mode=='deny': print('REACHABLE'); sys.exit(8)
 if mode=='control': print('CONTROL'); sys.exit(0)
 with ssl.create_default_context().wrap_socket(connection,server_hostname='harbor.stinkyboi.com') as tls:
  tls.settimeout(3)
  tls.sendall(b'GET /v2/ HTTP/1.1\\r\\nHost: harbor.stinkyboi.com\\r\\nConnection: close\\r\\n\\r\\n')
  line=b''
  while b'\\r\\n' not in line and len(line)<128:
   chunk=tls.recv(128-len(line))
   if not chunk: break
   line+=chunk
  if b'\\r\\n' not in line or not line.startswith(b'HTTP/1.1 401 '): sys.exit(9)
print('ALLOWED')
"""


def command(*args, timeout=25):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    if len(result.stdout) > 1048576:
        raise ValueError("Kubernetes read exceeds reviewed bound")
    return result.stdout


def kubernetes_json(*args):
    return json.loads(command("kubectl", "--request-timeout=15s", *args, "-o", "json"))


def items(listing):
    if (not isinstance(listing, dict) or not isinstance(listing.get("items"), list) or
            listing.get("metadata", {}).get("continue")):
        raise ValueError("Kubernetes inventory is incomplete")
    return listing["items"]


def ready(object_):
    return any(condition.get("type") == "Ready" and condition.get("status") == "True"
               for condition in object_.get("status", {}).get("conditions", []))


def identity(object_):
    metadata = object_.get("metadata", {})
    uid, name = metadata.get("uid"), metadata.get("name")
    if not isinstance(uid, str) or not uid or not isinstance(name, str) or not name:
        raise ValueError("Kubernetes object identity is missing")
    return {"name": name, "uid": uid}


def reviewed_application(application, name, source_sha):
    repo, chart, version = APPLICATIONS[name]
    sources = application.get("spec", {}).get("sources", [])
    sync = application.get("status", {}).get("sync", {})
    health = application.get("status", {}).get("health", {})
    if (application.get("metadata", {}).get("name") != name or
            not isinstance(sources, list) or len(sources) != 3 or
            not all(isinstance(source, dict) for source in sources) or
            any(sources[0].get(key) != value for key, value in
                (("repoURL", repo), ("chart", chart), ("targetRevision", version))) or
            any(sources[1].get(key) != value for key, value in
                (("repoURL", REPO_URL), ("path", "."), ("ref", "values"),
                 ("targetRevision", "main"))) or
            any(sources[2].get(key) != value for key, value in
                (("repoURL", REPO_URL), ("path", f"clusters/homelab/apps/{name}"),
                 ("targetRevision", "main"))) or
            sync.get("status") != "Synced" or health.get("status") != "Healthy" or
            sync.get("revisions") != [version, source_sha, source_sha]):
        raise ValueError("GitOps source is not current and Healthy")
    return identity(application)


def pod_identity(pod):
    spec, status = pod.get("spec", {}), pod.get("status", {})
    value = identity(pod)
    address = status.get("podIP")
    try:
        if ipaddress.ip_address(address).version != 4:
            raise ValueError("Pod address is not IPv4")
    except (TypeError, ValueError) as error:
        raise ValueError("Pod address is invalid") from error
    if not spec.get("nodeName") or status.get("phase") != "Running" or not ready(pod):
        raise ValueError("Pod is not Ready on a named node")
    return {**value, "node": spec["nodeName"], "ip": address}


def protected_source():
    source_sha = os.environ.get("GITHUB_SHA", "")
    platform = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
    platform["protected_context"](source_sha)
    if (command("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() != source_sha or
            platform["current_main_sha"]() != source_sha):
        raise ValueError("probe source is not exact current main")
    kustomization = (ROOT / "clusters/homelab/apps/harbor/kustomization.yaml").read_text()
    if "  - traefik-network-policy-probes.yaml\n" not in kustomization:
        raise ValueError("GitOps probe fixture is not active")
    return source_sha


def inspect_policies(probes, traefik, harbor_namespace):
    selector_matches = INVENTORY["selector_matches"]
    policy_types = INVENTORY["policy_types"]
    normalize = INVENTORY["normalized_policy"]
    fingerprint = INVENTORY["policy_fingerprint"]
    harbor_policies = items(kubernetes_json("-n", "harbor", "get", "networkpolicies", "--chunk-size=0"))
    denied_labels = probes["deny"]["metadata"].get("labels", {})
    allowed_labels = probes["allow"]["metadata"].get("labels", {})
    def selected(labels):
        return [policy for policy in harbor_policies
                if "Egress" in policy_types(policy.get("spec", {})) and
                selector_matches(policy["spec"]["podSelector"], labels)]
    if selected(denied_labels):
        raise ValueError("denied source has an Egress NetworkPolicy")
    allowed_policies = selected(allowed_labels)
    if [policy.get("metadata", {}).get("name") for policy in allowed_policies] != ["harbor-image-signing"]:
        raise ValueError("allowed source Egress policy differs")
    signer = allowed_policies[0]
    peer = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "traefik"}},
            "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}
    if not any(rule.get("to") == [peer] and rule.get("ports") == [{"protocol": "TCP", "port": 8443}]
               for rule in signer["spec"].get("egress", [])):
        raise ValueError("signer Egress does not allow exact Traefik Pod port")
    if harbor_namespace.get("metadata", {}).get("labels", {}).get("istio.io/dataplane-mode") == "ambient":
        raise ValueError("Harbor source became ambient")
    traefik_policies = items(kubernetes_json("-n", "traefik", "get", "networkpolicies", "--chunk-size=0"))
    matching = [policy for policy in traefik_policies
                if "Ingress" in policy_types(policy.get("spec", {})) and
                selector_matches(policy["spec"]["podSelector"], traefik["metadata"].get("labels", {}))]
    if len(matching) != 1 or matching[0].get("metadata", {}).get("name") != "traefik":
        raise ValueError("Traefik ingress policy selection differs")
    source = json.loads(command("yq", "-o=json", ".",
                                str(ROOT / "clusters/homelab/apps/traefik/networkpolicy.yaml")))
    normalized = normalize(matching[0])
    if normalized != normalize(source):
        raise ValueError("live Traefik ingress policy differs from reviewed source")
    identities = [identity(policy) for policy in (matching[0], signer)]
    for item, policy in zip(identities, (matching[0], signer)):
        metadata = policy["metadata"]
        if (type(metadata.get("generation")) is not int or
                not isinstance(metadata.get("resourceVersion"), str) or
                not metadata["resourceVersion"]):
            raise ValueError("NetworkPolicy version identity is missing")
        item.update(generation=metadata["generation"],
                    resourceVersion=metadata["resourceVersion"])
    return {"traefik": {**identities[0], "sha256": fingerprint(normalized)},
            "harborSigner": {**identities[1], "sha256": fingerprint(normalize(signer))}}


def inspect(source_sha):
    applications = {}
    for name in ("harbor", "traefik"):
        application = kubernetes_json("-n", "argocd", "get", "application", name)
        applications[name] = reviewed_application(application, name, source_sha)
    harbor_namespace = kubernetes_json("get", "namespace", "harbor")
    traefik_namespace = kubernetes_json("get", "namespace", "traefik")
    if traefik_namespace.get("metadata", {}).get("labels", {}).get("istio.io/dataplane-mode") != "ambient":
        raise ValueError("Traefik is not in reviewed ambient namespace")
    traefik_pods = items(kubernetes_json("-n", "traefik", "get", "pods", "-l",
                                        "app.kubernetes.io/name=traefik", "--chunk-size=0"))
    # shortcut: one Traefik replica; update the probe before scaling ingress.
    if len(traefik_pods) != 1:
        raise ValueError("expected one Ready Traefik Pod")
    traefik, = traefik_pods
    target = pod_identity(traefik)
    if (target["node"] != "zimaboard-0" or traefik["spec"].get("hostNetwork") or
            traefik.get("metadata", {}).get("deletionTimestamp")):
        raise ValueError("Traefik placement changed")
    probes = {mode: kubernetes_json("-n", "harbor", "get", "pod", name)
              for mode, name in PROBES.items()}
    sources = {}
    for mode, pod in probes.items():
        source = pod_identity(pod)
        spec = pod.get("spec", {})
        labels = pod.get("metadata", {}).get("labels", {})
        if (pod.get("metadata", {}).get("name") != PROBES[mode] or
                pod.get("metadata", {}).get("deletionTimestamp") or
                pod.get("metadata", {}).get("ownerReferences") or
                labels.get("app.kubernetes.io/name") !=
                ("harbor-image-signing" if mode == "allow" else "traefik-policy-deny") or
                labels.get("istio.io/dataplane-mode") == "ambient" or
                source["node"] != "zimaboard-1" or spec.get("hostNetwork") or
                spec.get("serviceAccountName") != "default" or
                spec.get("automountServiceAccountToken") is not False or
                len(spec.get("containers", [])) != 1 or
                spec["containers"][0].get("image") != IMAGE or
                spec["containers"][0].get("command") !=
                ["/usr/bin/python3", "-c", "import time; time.sleep(86400)"]):
            raise ValueError("source probe differs from reviewed fixture")
        sources[mode] = source
    if ({key: value for key, value in probes["allow"]["metadata"].get("labels", {}).items()
         if key != "app.kubernetes.io/name"} !=
            {key: value for key, value in probes["deny"]["metadata"].get("labels", {}).items()
             if key != "app.kubernetes.io/name"}):
        raise ValueError("probe labels differ beyond the reviewed signer selector")
    nodes = {}
    for name in {target["node"], sources["allow"]["node"], sources["deny"]["node"]}:
        node = kubernetes_json("get", "node", name)
        if not ready(node) or node.get("metadata", {}).get("name") != name:
            raise ValueError("probe or Traefik node is not Ready")
        nodes[name] = {**identity(node), "bootID": node.get("status", {}).get("nodeInfo", {}).get("bootID")}
        if not nodes[name]["bootID"]:
            raise ValueError("node boot identity is missing")
    daemonset = kubernetes_json("-n", "kube-system", "get", "daemonset", "kube-router-network-policy")
    if daemonset.get("metadata", {}).get("deletionTimestamp"):
        raise ValueError("firewall DaemonSet is being removed")
    source_daemonset = json.loads(command(
        "yq", "-o=json", 'select(.kind == "DaemonSet")',
        str(ROOT / "clusters/homelab/platform/network-policy/daemonset.yaml")))
    source_container, = source_daemonset["spec"]["template"]["spec"]["containers"]
    live_container, = daemonset["spec"]["template"]["spec"]["containers"]
    if (live_container.get("image") != source_container.get("image") or
            live_container.get("args") != source_container.get("args") or
            "--run-firewall=true" not in live_container["args"]):
        raise ValueError("firewall DaemonSet image or mode differs from reviewed source")
    status = daemonset.get("status", {})
    if (status.get("observedGeneration") != daemonset.get("metadata", {}).get("generation") or
            not status.get("desiredNumberScheduled") or
            status.get("updatedNumberScheduled") != status["desiredNumberScheduled"] or
            status.get("numberReady") != status["desiredNumberScheduled"]):
        raise ValueError("firewall DaemonSet has not converged")
    firewall_pods = items(kubernetes_json("-n", "kube-system", "get", "pods", "-l",
                                         "app.kubernetes.io/name=kube-router-network-policy", "--chunk-size=0"))
    on_target = [pod for pod in firewall_pods if pod.get("spec", {}).get("nodeName") == target["node"]]
    if len(on_target) != 1 or not ready(on_target[0]):
        raise ValueError("firewall is not Ready on Traefik node")
    firewall, = on_target
    if firewall.get("metadata", {}).get("deletionTimestamp"):
        raise ValueError("firewall Pod is being removed")
    pod_container, = firewall["spec"]["containers"]
    if (pod_container.get("image") != live_container["image"] or
            pod_container.get("args") != live_container["args"]):
        raise ValueError("firewall Pod differs from converged DaemonSet")
    owners = firewall.get("metadata", {}).get("ownerReferences", [])
    if (len(owners) != 1 or owners[0].get("kind") != "DaemonSet" or
            owners[0].get("name") != "kube-router-network-policy" or
            owners[0].get("uid") != daemonset.get("metadata", {}).get("uid") or
            owners[0].get("controller") is not True):
        raise ValueError("firewall Pod owner differs")
    policies = inspect_policies(probes, traefik, harbor_namespace)
    return {"applications": applications, "traefik": target, "sources": sources, "nodes": nodes,
            "firewall": {**pod_identity(firewall), "daemonSetUid": daemonset["metadata"]["uid"]},
            "policies": policies}


def probe(mode, address):
    result = subprocess.run(
        ["kubectl", "--request-timeout=15s", "-n", "harbor", "exec",
         PROBES["deny" if mode == "control" else mode],
         "--", "/usr/bin/python3", "-c", PROBE_CODE, address, mode],
        capture_output=True, text=True, timeout=25,
    )
    expected = {"allow": "ALLOWED", "deny": "DENIED", "control": "CONTROL"}[mode]
    if result.returncode != 0 or result.stdout.strip() != expected:
        raise ValueError(f"{mode} Traefik PodIP probe failed")


def qualify():
    source_sha = protected_source()
    before = inspect(source_sha)
    address = before["traefik"]["ip"]
    for mode in ("allow", "control", "deny", "control", "allow"):
        probe(mode, address)
    if inspect(source_sha) != before:
        raise ValueError("probe identity or policy changed during qualification")
    return {"format": 1, "stage": "traefik-qualify", "verified": True,
            "sourceSha": source_sha, "observedAt": datetime.now(timezone.utc).isoformat(),
            **before, "checks": ["allow-v2-401", "deny-control-15008", "deny-tcp-8443",
                                 "deny-control-15008", "allow-v2-401"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = qualify()
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    args.output.chmod(0o600)


if __name__ == "__main__":
    main()
