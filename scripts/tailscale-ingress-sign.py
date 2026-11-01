#!/usr/bin/env python3
"""Sign only the fixed repository-owned Tailscale proxies with the existing local signer."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import stat
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guards", ROOT / "scripts/entra-ci-configure.py")
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)
OAUTH_SPEC = importlib.util.spec_from_file_location("oauth", ROOT / "scripts/tailscale-operator-oauth-rotate.py")
OAUTH = importlib.util.module_from_spec(OAUTH_SPEC)
OAUTH_SPEC.loader.exec_module(OAUTH)
TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TAILNET = "tail67beb.ts.net"
OAUTH_DIRECTORY = Path.home() / ".config/homelab/tailscale"
TARGETS = (
    ("traefik", "svc", "traefik-private", "homelab-ingress", "tag:homelab-ingress"),
    ("traefik", "ingress", "n8n-webhook", "n8n-webhook", "tag:homelab-funnel"),
    ("traefik", "ingress", "policy-bot-hook", "policy-bot-hook", "tag:homelab-funnel"),
    ("traefik", "ingress", "bulldozer-hook", "bulldozer-hook", "tag:homelab-funnel"),
    ("tailnet-dns", "svc", "tailnet-dns", "homelab-dns", "tag:homelab-ingress"),
)
CANARY = ("traefik", "statefulset", "traefik-sidecar-canary", "homelab-ingress-canary",
          "tag:homelab-ingress-canary")
CANARY_IMAGES = {
    "traefik": "docker.io/library/traefik:v3.7.14@sha256:575fa15b135078fe5e50aa847987d96dbddd7b093c172429618404df73f3fa7c",
    "tailscale": "harbor.stinkyboi.com/mirror/docker.io/tailscale/tailscale:v1.102.3@sha256:8c42c4574ab066384fcb72f69e086a2ff1dd3652eb6f56856cee34bcf0d2f680",
}
CANARY_SAFE_DESTINATIONS = {
    "10.1.0.0/24", "autogroup:member", "tag:ci", "tag:homelab-ci-apply",
    "tag:homelab-ci-cordium", "tag:homelab-ci-plan", "tag:homelab-funnel",
    "tag:homelab-ingress", "tag:k8s", "tag:k8s-operator",
}


def require(condition, message):
    if not condition:
        raise GUARDS.Failure(message)


def local_signer():
    status = GUARDS.read_json([TAILSCALE, "status", "--json"], "local tailnet status")
    lock = GUARDS.read_json([TAILSCALE, "lock", "status", "--json"], "local lock status")
    require(status.get("BackendState") == "Running"
            and status.get("Self", {}).get("Online") is True
            and status.get("CurrentTailnet", {}).get("MagicDNSSuffix") == TAILNET
            and lock.get("Enabled") is True and lock.get("NodeKeySigned") is True
            and lock.get("PublicKey") in {key.get("Public") for key in lock.get("TrustedKeys", [])},
            "The existing local device must be online and already trusted to sign this locked tailnet")
    return lock


def read_oauth_credentials():
    directory = OAUTH_DIRECTORY.lstat()
    require(stat.S_ISDIR(directory.st_mode) and stat.S_IMODE(directory.st_mode) == 0o700,
            "Private Tailscale OAuth directory must be mode 0700")
    values = []
    for suffix in ("id", "secret"):
        path = OAUTH_DIRECTORY / f"terragrunt-oauth-client-{suffix}"
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600,
                "Private Tailscale OAuth files must be regular and mode 0600")
        value = path.read_text().strip()
        require(bool(value) and len(value) < 4096 and "\n" not in value,
                "Private Tailscale OAuth credential is invalid")
        values.append(value)
    return values


def validate_canary_policy(source, live):
    require(isinstance(source, dict) and live == source
            and source.get("tagOwners", {}).get(CANARY[4]) == ["tag:k8s-operator"]
            and source.get("acls") == [] and isinstance(source.get("grants"), list)
            and all(isinstance(grant, dict) and isinstance(grant.get("dst"), list)
                    and all(destination in CANARY_SAFE_DESTINATIONS for destination in grant["dst"])
                    for grant in source["grants"]),
            "Tailnet policy must match reviewed source and deny canary destinations")


def verify_canary_policy():
    source = json.loads((ROOT / "scripts/config/tailscale-policy.json").read_text())
    validate_canary_policy(source, source)
    # The existing Terragrunt OAuth client is separate from the operator Secret.
    client_id, client_secret = read_oauth_credentials()
    token = OAUTH.api_request("/oauth/token", method="POST", basic=(client_id, client_secret),
                              body=[("grant_type", "client_credentials"), ("scope", "policy_file")])
    require(isinstance(token.get("access_token"), str) and bool(token["access_token"])
            and str(token.get("token_type", "")).lower() == "bearer",
            "Tailnet policy read credential did not return a bearer token")
    live = OAUTH.api_request("/tailnet/-/acl", bearer=token["access_token"])
    validate_canary_policy(source, live)


def validate_target(target, source, pod, status, lock, signer):
    namespace, kind, name, hostname, tag = target
    metadata = pod["metadata"]
    labels = metadata.get("labels", {})
    expected = {"tailscale.com/managed": "true", "tailscale.com/parent-resource": name,
                "tailscale.com/parent-resource-ns": namespace, "tailscale.com/parent-resource-type": kind,
                "app": source["metadata"]["uid"]}
    require(all(labels.get(key) == value for key, value in expected.items())
            and not metadata.get("deletionTimestamp")
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in pod.get("status", {}).get("conditions", [])),
            "Proxy must be Ready and belong to the exact declared Kubernetes resource")
    own = status.get("Self", {})
    dns = hostname + "." + TAILNET
    addresses = own.get("TailscaleIPs", [])
    require(status.get("BackendState") == "Running" and own.get("Online") is True
            and status.get("CurrentTailnet", {}).get("MagicDNSSuffix") == TAILNET
            and own.get("DNSName", "").rstrip(".") == dns and own.get("Tags") == [tag]
            and lock.get("Enabled") is True and lock.get("NodeKey") == own.get("PublicKey")
            and re.fullmatch(r"nodekey:[0-9a-f]{64}", lock.get("NodeKey", ""))
            and re.fullmatch(r"tlpub:[0-9a-f]{64}", lock.get("PublicKey", "")),
            "Proxy tailnet, hostname, tag or public signing keys differ from the declared target")
    require(bool(addresses) and len(set(addresses)) == len(addresses)
            and all(any(ipaddress.ip_address(address) in network for network in
                        (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")))
                    for address in addresses), "Proxy addresses must be unique Tailscale addresses")
    published = source.get("status", {}).get("loadBalancer", {}).get("ingress", [])
    require(any(entry.get("hostname") == dns for entry in published)
            and all(entry["ip"] in addresses for entry in published if "ip" in entry),
            "Controller-published ingress identity differs from the proxy")
    peers = [p for p in (signer.get("VisiblePeers") or []) + (signer.get("FilteredPeers") or [])
             if p.get("ID") == own.get("ID")]
    require(len(peers) == 1 and peers[0].get("NodeKey") == lock["NodeKey"]
            and peers[0].get("DNSName", "").rstrip(".") == dns
            and set(peers[0].get("TailscaleIPs", [])) == set(addresses),
            "Local lock peer must match public keys read directly from the Kubernetes proxy")
    return {"dns": dns, "node_key": lock["NodeKey"], "rotation_key": lock["PublicKey"],
            "pod_uid": metadata["uid"], "signed": lock.get("NodeKeySigned") is True}


def validate_canary(source, pod, state_uid, status, lock, serve, signer):
    namespace, _, name, hostname, tag = CANARY
    metadata = source["metadata"]
    source_status = source["status"]
    require(metadata.get("name") == name and metadata.get("namespace") == namespace
            and metadata.get("uid") and not metadata.get("deletionTimestamp")
            and source["spec"].get("replicas") == 1
            and source["spec"].get("serviceName") == name
            and source_status.get("observedGeneration") == metadata.get("generation")
            and source_status.get("readyReplicas") == 1
            and source_status.get("currentRevision")
            and source_status.get("currentRevision") == source_status.get("updateRevision"),
            "Canary StatefulSet must be the current ready single-replica source")
    pod_meta = pod["metadata"]
    labels = pod_meta.get("labels", {})
    expected_labels = {"app.kubernetes.io/name": name, "app.kubernetes.io/instance": name,
                       "controller-revision-hash": source_status["currentRevision"]}
    owners = pod_meta.get("ownerReferences", [])
    require(pod_meta.get("name") == name + "-0" and pod_meta.get("namespace") == namespace
            and pod_meta.get("uid") and not pod_meta.get("deletionTimestamp")
            and all(labels.get(key) == value for key, value in expected_labels.items())
            and len(owners) == 1 and all(owners[0].get(key) == value for key, value in {
                "apiVersion": "apps/v1", "kind": "StatefulSet", "name": name,
                "uid": metadata["uid"], "controller": True}.items())
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in pod.get("status", {}).get("conditions", [])),
            "Canary Pod must be Ready and owned by the exact current StatefulSet")
    spec = pod["spec"]
    template_spec = source["spec"]["template"]["spec"]
    containers = {c["name"]: c for c in spec["containers"]}
    container_statuses = pod.get("status", {}).get("containerStatuses", [])
    require(spec.get("nodeName") == "acer" and spec.get("nodeSelector") == {"kubernetes.io/hostname": "acer"}
            and template_spec.get("nodeSelector") == spec["nodeSelector"]
            and spec.get("serviceAccountName") == "traefik-sidecar-canary"
            and template_spec.get("serviceAccountName") == spec["serviceAccountName"]
            and len(spec["containers"]) == len(CANARY_IMAGES)
            and set(containers) == set(CANARY_IMAGES)
            and {name: c["image"] for name, c in containers.items()} == CANARY_IMAGES
            and len(container_statuses) == len(containers)
            and {c.get("name") for c in container_statuses if c.get("ready") is True} == set(containers),
            "Canary placement, ServiceAccount, images, or container readiness differ")
    tailscale = containers["tailscale"]
    traefik = containers["traefik"]
    require(tailscale.get("command") == ["/usr/local/bin/tailscaled"]
            and tailscale.get("args") == ["--tun=userspace-networking",
                                           "--state=kube:traefik-sidecar-canary-state",
                                           "--statedir=/var/lib/tailscale",
                                           "--socket=/run/tailscale/tailscaled.sock"]
            and "--entrypoints.websecure.address=127.0.0.1:8443" in traefik.get("args", [])
            and "--providers.file.directory=/etc/traefik/dynamic" in traefik.get("args", []),
            "Canary daemon state or private TLS listener differs")
    dynamic = [v for v in spec.get("volumes", []) if v.get("name") == "dynamic"]
    require(len(dynamic) == 1
            and any(item.get("secret", {}).get("name") == "traefik-tls"
                    for item in dynamic[0].get("projected", {}).get("sources", []))
            and any(m.get("name") == "dynamic" and m.get("mountPath") == "/etc/traefik/dynamic"
                    and m.get("readOnly") is True for m in traefik.get("volumeMounts", []))
            and re.fullmatch(r"[0-9a-f-]{36}", state_uid or ""),
            "Canary TLS Secret mount or persistent Tailscale state Secret is missing")
    own = status.get("Self", {})
    dns = hostname + "." + TAILNET
    addresses = own.get("TailscaleIPs", [])
    require(status.get("BackendState") == "Running" and own.get("Online") is True
            and isinstance(own.get("ID"), str) and bool(own["ID"])
            and own.get("Expired") is not True
            and status.get("CurrentTailnet", {}).get("MagicDNSSuffix") == TAILNET
            and own.get("DNSName", "").rstrip(".") == dns and own.get("Tags") == [tag]
            and lock.get("Enabled") is True and lock.get("NodeKey") == own.get("PublicKey")
            and re.fullmatch(r"nodekey:[0-9a-f]{64}", lock.get("NodeKey", ""))
            and re.fullmatch(r"tlpub:[0-9a-f]{64}", lock.get("PublicKey", ""))
            and bool(addresses) and len(set(addresses)) == len(addresses)
            and all(any(ipaddress.ip_address(address) in network for network in
                        (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")))
                    for address in addresses),
            "Canary tailnet, tag, public node identity, or Tailscale addresses differ")
    require(serve == {"TCP": {"443": {"TCPForward": "127.0.0.1:8443"}}},
            "Canary must serve only raw TCP 443 to its loopback TLS listener")
    peers = [p for p in (signer.get("VisiblePeers") or []) + (signer.get("FilteredPeers") or [])
             if p.get("ID") == own.get("ID")]
    require(len(peers) == 1 and peers[0].get("NodeKey") == lock["NodeKey"]
            and peers[0].get("DNSName", "").rstrip(".") == dns
            and peers[0].get("Tags") == [tag]
            and peers[0].get("Expired") is not True
            and set(peers[0].get("TailscaleIPs", [])) == set(addresses),
            "Local lock peer must match the exact canary Pod identity")
    return {"dns": dns, "node_key": lock["NodeKey"], "rotation_key": lock["PublicKey"],
            "source_uid": metadata["uid"], "pod_uid": pod_meta["uid"], "state_uid": state_uid,
            "device_id": own["ID"], "signed": lock.get("NodeKeySigned") is True}


def inspect_canary(_, signer):
    namespace, _, name, _, _ = CANARY
    source = GUARDS.read_json(["kubectl", "-n", namespace, "get", "statefulset", name, "-o", "json"],
                              "canary StatefulSet")
    selector = f"app.kubernetes.io/name={name},app.kubernetes.io/instance={name}"
    pods = GUARDS.read_json(["kubectl", "-n", namespace, "get", "pods", "-l", selector,
                             "-o", "json"], "canary Pod lookup")["items"]
    require(len(pods) == 1, "Exactly one canary Pod must exist")
    state_uid = GUARDS.command(["kubectl", "-n", namespace, "get", "secret", name + "-state",
                                "-o", "jsonpath={.metadata.uid}"], "canary state Secret metadata").strip()
    prefix = ["kubectl", "-n", namespace, "exec", pods[0]["metadata"]["name"],
              "-c", "tailscale", "--", "tailscale", "--socket=/run/tailscale/tailscaled.sock"]
    status = GUARDS.read_json([*prefix, "status", "--json"], "canary public node identity")
    lock = GUARDS.read_json([*prefix, "lock", "status", "--json"], "canary public lock identity")
    serve = GUARDS.read_json([*prefix, "serve", "status", "--json"], "canary Serve configuration")
    return validate_canary(source, pods[0], state_uid, status, lock, serve, signer)


def inspect_target(target, signer):
    namespace, kind, name, _, _ = target
    source = GUARDS.read_json(["kubectl", "-n", namespace, "get", kind, name, "-o", "json"], "ingress resource")
    selector = (f"tailscale.com/managed=true,tailscale.com/parent-resource-ns={namespace},"
                f"tailscale.com/parent-resource={name},tailscale.com/parent-resource-type={kind}")
    pods = GUARDS.read_json(["kubectl", "-n", "tailscale", "get", "pods", "-l", selector, "-o", "json"],
                           "controller proxy lookup")["items"]
    require(len(pods) == 1, "Exactly one controller proxy must exist for each fixed ingress target")
    pod = pods[0]
    pod_name = pod["metadata"]["name"]
    require(re.fullmatch(r"ts-[a-z0-9-]+", pod_name), "Unexpected proxy pod name")
    prefix = ["kubectl", "-n", "tailscale", "exec", pod_name, "-c", "tailscale", "--", "tailscale"]
    status = GUARDS.read_json([*prefix, "status", "--json"], "proxy public node identity")
    lock = GUARDS.read_json([*prefix, "lock", "status", "--json"], "proxy public lock identity")
    return validate_target(target, source, pod, status, lock, signer)


def reconcile(execute, dns_only=False, canary_only=False):
    revision = GUARDS.verify_main() if execute else None
    server = GUARDS.command(["kubectl", "config", "view", "--minify", "-o",
                             "jsonpath={.clusters[0].cluster.server}"], "Kubernetes context").strip()
    require(server == "https://10.1.0.199:6443", "Signing requires the authenticated local homelab Kubernetes API")
    if execute and canary_only:
        verify_canary_policy()
    signer = local_signer()
    selected = (CANARY,) if canary_only else TARGETS[-1:] if dns_only else TARGETS
    inspect = inspect_canary if canary_only else inspect_target
    targets = [inspect(target, signer) for target in selected]
    if not execute:
        for target in targets:
            print(target["dns"] + (": already signed" if target["signed"] else ": signature required"))
        return
    require(GUARDS.verify_main() == revision, "Current main changed during signing preflight")
    for target, expected in zip(selected, targets):
        current = inspect(target, local_signer())
        require(current == expected, "Proxy identity changed during preflight; rerun the preview")
        if canary_only:
            verify_canary_policy()
        if not current["signed"]:
            GUARDS.command([TAILSCALE, "lock", "sign", current["node_key"], current["rotation_key"]],
                           "fixed ingress node signing")
    for attempt in range(16):
        signer = local_signer()
        current = [inspect(target, signer) for target in selected]
        require(all({k: v for k, v in a.items() if k != "signed"}
                    == {k: v for k, v in b.items() if k != "signed"}
                    for a, b in zip(current, targets)), "Proxy identity changed during signature verification")
        if all(target["signed"] for target in current):
            print("Verified selected fixed proxy signatures; Tailnet Lock remains enabled.")
            return
        if attempt < 15:
            time.sleep(2)
    raise GUARDS.Failure("Signature propagation is incomplete; rerun preview before retrying")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Sign only the verified fixed ingress nodes")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--dns-only", action="store_true", help="Inspect or sign only the fixed homelab-dns proxy")
    target.add_argument("--canary-only", action="store_true", help="Inspect or sign only the fixed Traefik sidecar canary")
    args = parser.parse_args(argv)
    try:
        reconcile(args.execute, args.dns_only, args.canary_only)
    except GUARDS.Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - Kubernetes and CLI output stays inside the private boundary.
        print("Ingress signing failed; private details withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
