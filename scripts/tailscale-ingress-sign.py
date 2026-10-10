#!/usr/bin/env python3
"""Sign only the three repository-owned ingress proxies with the existing local signer."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

import argparse
import importlib.util
import ipaddress
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guards", ROOT / "scripts/entra-ci-configure.py")
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)
TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TAILNET = "tail67beb.ts.net"
TARGETS = (
    ("svc", "traefik-private", "homelab-ingress", "tag:homelab-ingress"),
    ("ingress", "n8n-webhook", "n8n-webhook", "tag:homelab-funnel"),
    ("ingress", "policy-bot-hook", "policy-bot-hook", "tag:homelab-funnel"),
)


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


def validate_target(target, source, pod, status, lock, signer):
    kind, name, hostname, tag = target
    metadata = pod["metadata"]
    labels = metadata.get("labels", {})
    expected = {"tailscale.com/managed": "true", "tailscale.com/parent-resource": name,
                "tailscale.com/parent-resource-ns": "traefik", "tailscale.com/parent-resource-type": kind,
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


def inspect_target(target, signer):
    kind, name, _, _ = target
    source = GUARDS.read_json(["kubectl", "-n", "traefik", "get", kind, name, "-o", "json"], "ingress resource")
    selector = ("tailscale.com/managed=true,tailscale.com/parent-resource-ns=traefik,"
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


def reconcile(execute):
    revision = GUARDS.verify_main() if execute else None
    server = GUARDS.command(["kubectl", "config", "view", "--minify", "-o",
                             "jsonpath={.clusters[0].cluster.server}"], "Kubernetes context").strip()
    require(server == "https://10.1.0.199:6443", "Signing requires the authenticated local homelab Kubernetes API")
    signer = local_signer()
    targets = [inspect_target(target, signer) for target in TARGETS]
    if not execute:
        for target in targets:
            print(target["dns"] + (": already signed" if target["signed"] else ": signature required"))
        return
    require(GUARDS.verify_main() == revision, "Current main changed during signing preflight")
    for target, expected in zip(TARGETS, targets):
        current = inspect_target(target, local_signer())
        require(current == expected, "Proxy identity changed during preflight; rerun the preview")
        if not current["signed"]:
            GUARDS.command([TAILSCALE, "lock", "sign", current["node_key"], current["rotation_key"]],
                           "fixed ingress node signing")
    for attempt in range(16):
        signer = local_signer()
        current = [inspect_target(target, signer) for target in TARGETS]
        require(all({k: v for k, v in a.items() if k != "signed"}
                    == {k: v for k, v in b.items() if k != "signed"}
                    for a, b in zip(current, targets)), "Proxy identity changed during signature verification")
        if all(target["signed"] for target in current):
            print("Verified all three ingress signatures; Tailnet Lock remains enabled.")
            return
        if attempt < 15:
            time.sleep(2)
    raise GUARDS.Failure("Signature propagation is incomplete; rerun preview before retrying")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Sign only the verified fixed ingress nodes")
    args = parser.parse_args(argv)
    try:
        reconcile(args.execute)
    except GUARDS.Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - Kubernetes and CLI output stays inside the private boundary.
        print("Ingress signing failed; private details withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
