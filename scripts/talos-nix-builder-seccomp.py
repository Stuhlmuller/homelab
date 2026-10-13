#!/usr/bin/env python3
"""Install only the reviewed Nix builder seccomp profile on an eligible worker."""
import argparse
import copy
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "nix-builder-containerd-2.1.4.json"
NODES = ("10.1.0.200", "10.1.0.201")
spec = importlib.util.spec_from_file_location("talos_operator", ROOT / "scripts/talos-harbor-mirrors.py")
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


def profiles(before, wanted, rollback):
    result = copy.deepcopy(before)
    configs = [item for item in result if item.get("version") == "v1alpha1"]
    if len(configs) != 1:
        raise RuntimeError("Expected one machine configuration")
    machine = configs[0]["machine"]
    existing = machine.get("seccompProfiles", [])
    ours = [item for item in existing if item.get("name") == NAME]
    if len(ours) > 1 or (ours and ours != [wanted]):
        raise RuntimeError("Refusing conflicting profile content")
    if rollback and not ours:
        return result
    updated = [item for item in existing if item.get("name") != NAME]
    if not rollback:
        # Preserve order on an idempotent apply.
        if ours:
            return result
        updated.append(copy.deepcopy(wanted))
    if updated:
        machine["seccompProfiles"] = updated
    else:
        machine.pop("seccompProfiles", None)
    return result


def capture(client, directory):
    stream = operator.run(*client, "get", "machineconfig", "-o", "json").strip()
    resources = {}
    decoder = json.JSONDecoder()
    while stream:
        item, end = decoder.raw_decode(stream)
        metadata = item["metadata"]
        identity = metadata["id"]
        if (identity not in ("v1alpha1", "persistent") or identity in resources
                or metadata.get("namespace") != "config"
                or metadata.get("type") != "MachineConfigs.config.talos.dev"
                or metadata.get("phase") != "running"):
            raise RuntimeError("Unexpected machine configuration resource")
        resources[identity] = item
        stream = stream[end:].strip()
    if set(resources) != {"v1alpha1", "persistent"}:
        raise RuntimeError("Active and persistent configurations required")
    rendered = []
    for identity in ("v1alpha1", "persistent"):
        source, normalized = directory / (identity + ".yaml"), directory / (identity + ".normalized.yaml")
        source.write_text(resources[identity]["spec"])
        operator.run("talosctl", "machineconfig", "patch", str(source), "--patch", "[]", "--output", str(normalized))
        rendered.append(operator.documents(normalized))
    if rendered[0] != rendered[1]:
        raise RuntimeError("Active and persistent configurations differ")
    return rendered[0]


def ready(node):
    boot = operator.ready(node)
    data = json.loads(operator.run("kubectl", "get", "node", operator.NODES[node], "-o", "json"))
    info = data["status"]["nodeInfo"]
    if info["containerRuntimeVersion"] != "containerd://2.1.4" or info["osImage"] != "Talos (v1.11.3)":
        raise RuntimeError("Profile requires reviewed Talos/containerd versions")
    conditions = {item["type"]: item["status"] for item in data["status"]["conditions"]}
    if any(conditions.get(kind) != "False" for kind in
           ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")):
        raise RuntimeError("Node reports pressure or unavailable networking")
    return boot


def reconcile(args):
    if not re.search(r"^Talos v1\.11\.3$", operator.run("talosctl", "version", "--client", "--short"), re.MULTILINE):
        raise RuntimeError("Requires talosctl 1.11.3")
    if args.execute:
        operator.verify_main(args.expected_sha)
    if args.rollback:
        pods = json.loads(operator.run("kubectl", "get", "pods", "--all-namespaces", "-o", "json"))
        for pod in pods["items"]:
            contexts = [pod["spec"].get("securityContext", {})]
            for kind in ("containers", "initContainers", "ephemeralContainers"):
                contexts += [item.get("securityContext", {}) for item in pod["spec"].get(kind, [])]
            if any(context.get("seccompProfile", {}).get("localhostProfile") == "profiles/" + NAME
                   for context in contexts):
                raise RuntimeError("Revert workload selection before removing the profile")
    wanted = operator.documents(ROOT / ".talos/patches/nix-builder-seccomp.yaml")[0]["machine"]["seccompProfiles"]
    if len(wanted) != 1 or wanted[0]["name"] != NAME or wanted[0]["value"]["defaultAction"] != "SCMP_ACT_ERRNO":
        raise RuntimeError("Unexpected profile declaration")
    wanted = wanted[0]
    client = ["talosctl", "--talosconfig", str(args.talosconfig.resolve()), "--endpoints", "10.1.0.199", "--nodes", args.node]
    boot = ready(args.node)
    with tempfile.TemporaryDirectory(prefix="talos-nix-seccomp-") as temporary:
        directory = Path(temporary)
        before = capture(client, directory)
        after = profiles(before, wanted, args.rollback)
        candidate = directory / "candidate.yaml"
        candidate.write_text("\n---\n".join(json.dumps(item) for item in after))
        operator.run("talosctl", "validate", "--config", str(candidate), "--mode", "metal", "--strict")
        if args.execute:
            operator.verify_main(args.expected_sha)
            if capture(client, directory) != before or ready(args.node) != boot:
                raise RuntimeError("Node/configuration changed during validation")
            if after != before:
                operator.run(*client, "apply-config", "--mode", "no-reboot", "--file", str(candidate))
            if capture(client, directory) != after or ready(args.node) != boot:
                raise RuntimeError("Post-apply configuration/boot verification failed")
            if not args.rollback:
                actual = json.loads(operator.run(*client, "read", "/var/lib/seccomp/profiles/" + NAME))
                if actual != wanted["value"]:
                    raise RuntimeError("Installed profile differs from reviewed content")
    print(f"{operator.NODES[args.node]}: profile {'reconciled' if args.execute else 'validated only'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=NODES)
    parser.add_argument("--talosconfig", required=True, type=Path)
    parser.add_argument("--talosctl", default="talosctl", help="Talos 1.11.3 executable")
    parser.add_argument("--expected-sha")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    operator.TALOSCTL = args.talosctl
    os.umask(0o077)
    reconcile(args)


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run with python3 -I")
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, OSError):
        raise SystemExit("Talos Nix profile operation failed; private command output withheld") from None
