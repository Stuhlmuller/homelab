#!/usr/bin/env python3
"""Validate or apply the repository-owned Wazuh Talos settings, one node at a time."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NODES = {"10.1.0.199": "acer", "10.1.0.200": "zimaboard-0",
         "10.1.0.201": "zimaboard-1", "10.1.0.202": "zimaboard-2"}
CONTROL_PLANE = "10.1.0.199"
REPOSITORY = "Stuhlmuller/homelab"
PATCHES = ROOT / ".talos/patches"
TALOSCTL = "talosctl"


def run(*command):
    if command[0] == "talosctl":
        command = (TALOSCTL, *command[1:])
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True,
                          text=True, timeout=180).stdout


def documents(path):
    result = json.loads(run("yq", "ea", "-o=json", "-I=0",
                            ". as $item ireduce ([]; . + [$item])", str(path)))
    if not result or any(not isinstance(item, dict) for item in result):
        raise RuntimeError("Invalid Talos document stream")
    return result


def machine_config(items):
    matches = [item for item in items if item.get("version") == "v1alpha1"]
    if len(matches) != 1:
        raise RuntimeError("Expected one Talos v1alpha1 machine configuration")
    return matches[0]


def normalize(source, target):
    # Talos 1.11 rejects JSON6902 (even []) for multi-document configurations.
    run("talosctl", "machineconfig", "patch", str(source), "--patch",
        "version: v1alpha1\nmachine: {}", "--output", str(target))


def desired(before, phase, rollback):
    """Preserve every unrelated setting and document; upsert the owned destination."""
    after = copy.deepcopy(before)
    machine = machine_config(after)["machine"]
    if phase == "indexer":
        patch = documents(PATCHES / ("wazuh-indexer-rollback.yaml" if rollback else "wazuh-indexer.yaml"))[0]
        machine.setdefault("sysctls", {}).update(patch["machine"]["sysctls"])
        return after
    destination = documents(PATCHES / "wazuh-logging.yaml")[0]["machine"]["logging"]["destinations"][0]
    logging = machine.setdefault("logging", {})
    retained = [item for item in logging.get("destinations", [])
                if item.get("endpoint") != destination["endpoint"]]
    logging["destinations"] = retained if rollback else [*retained, destination]
    if not logging["destinations"]:
        logging.pop("destinations")
    if not logging:
        machine.pop("logging")
    kernel = documents(PATCHES / "wazuh-kernel-logging.yaml")[0]
    after = [item for item in after if not (item.get("kind") == kernel["kind"] and
                                          item.get("name") == kernel["name"])]
    if not rollback:
        after.append(kernel)
    return after


def verify_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Execution requires the full reviewed main SHA")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        raise RuntimeError("Execution requires a clean checkout")
    if (run("git", "rev-parse", "HEAD").strip() != expected or
            run("git", "ls-remote", f"https://github.com/{REPOSITORY}.git",
                "refs/heads/main").split()[0] != expected):
        raise RuntimeError("Checkout and current main must match the reviewed SHA")


def ready(node):
    current = json.loads(run("kubectl", "--request-timeout=20s", "get", "node", NODES[node], "-o", "json"))
    status = current["status"]
    if (current["metadata"]["name"] != NODES[node] or
            not any(item["type"] == "InternalIP" and item["address"] == node for item in status["addresses"]) or
            not any(item["type"] == "Ready" and item["status"] == "True" for item in status["conditions"])):
        raise RuntimeError("Node identity or Ready check failed")
    return status["nodeInfo"]["bootID"]


def collector_ready():
    deployment = json.loads(run("kubectl", "--request-timeout=20s", "-n", "wazuh", "get",
                                "deployment", "wazuh-collector", "-o", "json"))
    status = deployment.get("status", {})
    if (status.get("observedGeneration", 0) < deployment["metadata"]["generation"] or
            status.get("availableReplicas", 0) < 1):
        raise RuntimeError("Wazuh Talos collector is not available")
    service = json.loads(run("kubectl", "--request-timeout=20s", "-n", "wazuh", "get",
                             "service", "wazuh-collector", "-o", "json"))
    if not any(port.get("nodePort") == 30517 and port.get("protocol") == "TCP"
               for port in service["spec"]["ports"]):
        raise RuntimeError("Wazuh Talos collector NodePort differs from declared endpoint")
    with socket.create_connection((CONTROL_PLANE, 30517), timeout=5):
        pass


def audit_safe(client):
    # Talos already emits Kubernetes Metadata audit records to /var/log/audit/kube.
    # Verify the live policy rather than restarting the single API server to rewrite it.
    policy = run(*client, "read", "/system/config/kubernetes/kube-apiserver/auditpolicy.yaml")
    result = subprocess.run(["yq", "-o=json", "."], input=policy, capture_output=True,
                            text=True, check=True, timeout=20)
    value = json.loads(result.stdout)
    rules = value.get("rules", [])
    if (value.get("apiVersion") != "audit.k8s.io/v1" or value.get("kind") != "Policy" or
            not rules or any(rule.get("level") != "Metadata" for rule in rules) or
            any(key in rules[-1] for key in ("users", "userGroups", "verbs", "resources", "namespaces", "nonResourceURLs"))):
        raise RuntimeError("Audit policy must retain catch-all Metadata coverage without request bodies")


def rollback_safe():
    indexer = json.loads(run("kubectl", "--request-timeout=20s", "-n", "wazuh", "get",
                             "statefulset", "wazuh-indexer", "-o", "json"))
    if indexer["spec"].get("replicas", 1) != 0 or indexer.get("status", {}).get("replicas", 0) != 0:
        raise RuntimeError("Scale the indexer to zero through GitOps before sysctl rollback")


def reconcile(node, phase, execute, expected, rollback, talosconfig):
    if phase == "indexer" and node != CONTROL_PLANE:
        raise RuntimeError("Indexer sysctl is restricted to acer")
    talosconfig = talosconfig.expanduser().resolve()
    if not talosconfig.is_file() or not talosconfig.stat().st_size:
        raise RuntimeError("The selected Talos client configuration is unavailable")
    if not re.search(r"^Talos v1\.11\.3$", run("talosctl", "version", "--client", "--short"), re.MULTILINE):
        raise RuntimeError("This rollout requires talosctl 1.11.3")
    if execute:
        verify_main(expected)
    client = ["talosctl", "--talosconfig", str(talosconfig), "--endpoints", CONTROL_PLANE, "--nodes", node]
    boot = ready(node)
    if phase == "logs" and not rollback and node == CONTROL_PLANE:
        audit_safe(client)
    if execute:
        if phase == "logs" and not rollback:
            collector_ready()
        if phase == "indexer" and rollback:
            rollback_safe()
    with tempfile.TemporaryDirectory(prefix="wazuh-talos-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        original, normalized, candidate = (directory / name for name in ("original.yaml", "normalized.yaml", "candidate.yaml"))

        def capture():
            resource = json.loads(run(*client, "get", "machineconfig", "persistent", "-o", "json"))
            if resource["metadata"]["id"] != "persistent" or not isinstance(resource["spec"], str):
                raise RuntimeError("Expected the full persistent machine configuration")
            original.write_text(resource["spec"])
            original.chmod(0o600)
            normalize(original, normalized)
            return documents(normalized)

        before = capture()
        after = desired(before, phase, rollback)
        candidate.write_text("\n---\n".join(json.dumps(item) for item in after) + "\n")
        candidate.chmod(0o600)
        run("talosctl", "validate", "--config", str(candidate), "--mode", "metal", "--strict")
        # Normalize the candidate exactly as persistent readback will be normalized.
        normalize(candidate, normalized)
        after = documents(normalized)
        if execute:
            verify_main(expected)
            if ready(node) != boot or capture() != before:
                raise RuntimeError("Node boot or machine configuration changed during preflight")
            run(*client, "apply-config", "--mode", "no-reboot", "--file", str(candidate))
            run("kubectl", "--request-timeout=130s", "wait", "--for=condition=Ready", "node/" + NODES[node], "--timeout=120s")
            if capture() != after or ready(node) != boot:
                raise RuntimeError("Post-apply configuration or no-reboot verification failed")
            if phase == "indexer":
                if run(*client, "read", "/proc/sys/vm/max_map_count").strip() != machine_config(after)["machine"]["sysctls"]["vm.max_map_count"]:
                    raise RuntimeError("Runtime indexer sysctl differs from committed setting")
    print(f"{NODES[node]}: Wazuh {phase} {'rollback ' if rollback else ''}"
          f"{'applied; no reboot verified' if execute else 'strict validation passed; no change applied'}")


def main():
    global TALOSCTL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=NODES)
    parser.add_argument("--phase", required=True, choices=("indexer", "logs"))
    parser.add_argument("--talosconfig", required=True, type=Path, help="Private authenticated Talos client config")
    parser.add_argument("--talosctl", default="talosctl", help="Talos 1.11.3 executable (Nix may provide a newer client)")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    TALOSCTL = args.talosctl
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    reconcile(args.node, args.phase, args.execute, args.expected_sha, args.rollback, args.talosconfig)


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, OSError):
        raise SystemExit("Wazuh Talos operation failed; private command output withheld") from None
