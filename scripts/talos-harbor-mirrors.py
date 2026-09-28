#!/usr/bin/env python3
"""Validate or apply the reviewed Harbor mirror patch to one Ready Talos node."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
NODES = {"10.1.0.199": "acer", "10.1.0.200": "zimaboard-0",
         "10.1.0.201": "zimaboard-1", "10.1.0.202": "zimaboard-2"}
REPOSITORY = "Stuhlmuller/homelab"


def run(*command, binary=False):
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True,
                          text=not binary, timeout=180).stdout


def verify_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Execution requires the full reviewed main SHA")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"):
        raise RuntimeError("Execution requires a clean checkout")
    if (run("git", "rev-parse", "HEAD").strip() != expected or
            run("git", "ls-remote", f"https://github.com/{REPOSITORY}.git",
                "refs/heads/main").split()[0] != expected):
        raise RuntimeError("Checkout and current main must match the reviewed SHA")


def verify_copies(expected):
    runs = json.loads(run("gh", "run", "list", "--repo", REPOSITORY, "--workflow", "harbor-mirror.yml",
                          "--commit", expected, "--branch", "main", "--event", "workflow_dispatch",
                          "--json", "headSha,status,conclusion", "--limit", "20"))
    if not any(item["headSha"] == expected and item["status"] == "completed" and
               item["conclusion"] == "success" for item in runs):
        raise RuntimeError("No successful Harbor mirror workflow for this revision")
    images = json.loads((ROOT / "scripts/config/harbor-images.json").read_text())["images"]
    if not images:
        raise RuntimeError("Mirror inventory is empty")
    curl = ("curl", "--disable", "--fail", "--silent", "--show-error", "--noproxy", "*",
            "--max-time", "30", "--doh-url", "https://1.1.1.1/dns-query", "--proto", "=https")
    accept = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                        "application/vnd.docker.distribution.manifest.list.v2+json",
                        "application/vnd.docker.distribution.manifest.v2+json"))
    with tempfile.TemporaryDirectory(prefix="harbor-manifests-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        headers = directory / "headers"
        headers.touch(mode=0o600)
        for image in images:
            source, digest = image["source"].split("@")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise RuntimeError("Mirror inventory requires SHA-256 digests")
            repository, separator, tag = source.rpartition(":")
            if not separator or "/" in tag:
                repository, tag = source, ""
            query = urllib.parse.urlencode({"service": "harbor-registry", "scope": f"repository:mirror/{repository}:pull"})
            token = json.loads(run(*curl, "https://harbor.stinkyboi.com/service/token?" + query)).get("token")
            if not isinstance(token, str) or not 1 <= len(token) <= 16384 or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token):
                raise RuntimeError("Harbor returned an invalid anonymous Bearer token")
            headers.write_text(f"Authorization: Bearer {token}\nAccept: {accept}\n")
            destination = "https://harbor.stinkyboi.com/v2/mirror/" + urllib.parse.quote(repository, safe="/")
            for reference in (digest[7:], *([tag] if tag else [])):
                manifest = run(*curl, "--header", "@" + str(headers),
                               destination + "/manifests/" + urllib.parse.quote(reference, safe=""), binary=True)
                if "sha256:" + hashlib.sha256(manifest).hexdigest() != digest:
                    raise RuntimeError("Harbor destination manifest digest differs")


def documents(path):
    value = json.loads(run("yq", "ea", "-o=json", "-I=0",
                          ". as $item ireduce ([]; . + [$item])", str(path)))
    if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("Invalid Talos document stream")
    return value


def mirrors_only(before, after, wanted):
    original, candidate = copy.deepcopy(before), copy.deepcopy(after)
    for stream in (original, candidate):
        configs = [item for item in stream if item.get("version") == "v1alpha1"]
        if len(configs) != 1:
            raise RuntimeError("Expected exactly one v1alpha1 document")
        registries = configs[0]["machine"].setdefault("registries", {})
        if stream is candidate and registries.get("mirrors") != wanted:
            raise RuntimeError("Rendered registry mirrors do not match the declared patch")
        registries.pop("mirrors", None)
    if original != candidate:
        raise RuntimeError("Refusing changes outside machine.registries.mirrors")


def ready(node):
    document = json.loads(run("kubectl", "get", "node", NODES[node], "-o", "json"))
    status = document["status"]
    if (document["metadata"]["name"] != NODES[node] or
            not any(item["type"] == "InternalIP" and item["address"] == node for item in status["addresses"]) or
            not any(item["type"] == "Ready" and item["status"] == "True" for item in status["conditions"])):
        raise RuntimeError("Target node identity or Ready check failed")
    boot = status["nodeInfo"]["bootID"]
    if not boot:
        raise RuntimeError("Target node boot identity is unavailable")
    return boot


def talos_boot(client):
    boot = run(*client, "read", "/proc/sys/kernel/random/boot_id").strip()
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot):
        raise RuntimeError("Talos boot identity is unavailable")
    return boot


def reconcile(node, execute, expected, rollback, talosconfig=None):
    talosconfig = Path(talosconfig or ROOT / ".talos/talosconfig").expanduser().resolve()
    if not talosconfig.is_file():
        raise RuntimeError("The selected Talos client configuration is unavailable")
    if not re.search(r"^Talos v1\.11\.3$", run("talosctl", "version", "--client", "--short"), re.MULTILINE):
        raise RuntimeError("This rollout requires talosctl 1.11.3")
    if execute:
        verify_main(expected)
        if not rollback:
            verify_copies(expected)
    client = ["talosctl", "--talosconfig", str(talosconfig), "--endpoints", "10.1.0.199", "--nodes", node]
    # Recovery must work while Harbor-dependent Kubernetes components are down.
    def check_boot():
        return talos_boot(client) if rollback else ready(node)

    boot = check_boot()
    patch = ROOT / (".talos/patches/harbor-mirrors-rollback.yaml" if rollback else
                    ".talos/patches/harbor-mirrors.yaml")
    wanted = documents(patch)[0]["machine"]["registries"]["mirrors"]
    with tempfile.TemporaryDirectory(prefix="talos-harbor-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        original, normalized, candidate = (directory / name for name in ("original.yaml", "normalized.yaml", "candidate.yaml"))

        def capture(path):
            resource = json.loads(run(*client, "get", "machineconfig", "persistent", "-o", "json"))
            if resource["metadata"]["id"] != "persistent" or not isinstance(resource["spec"], str):
                raise RuntimeError("Expected the full persistent machine configuration")
            path.write_text(resource["spec"])
            path.chmod(0o600)

        capture(original)
        # Normalize defaults with the same local parser, preserving every document.
        run("talosctl", "machineconfig", "patch", str(original), "--patch", "[]", "--output", str(normalized))
        before = documents(normalized)
        configs = [item for item in before if item.get("version") == "v1alpha1"]
        if len(configs) != 1:
            raise RuntimeError("Expected exactly one v1alpha1 document")
        # Strategic merge appends endpoint lists; JSON Patch replaces them on repeat/rollback.
        operations = [] if "registries" in configs[0]["machine"] else [
            {"op": "add", "path": "/machine/registries", "value": {}}]
        operations.append({"op": "add", "path": "/machine/registries/mirrors", "value": wanted})
        run("talosctl", "machineconfig", "patch", str(normalized), "--patch", json.dumps(operations), "--output", str(candidate))
        after = documents(candidate)
        mirrors_only(before, after, wanted)
        run("talosctl", "validate", "--config", str(candidate), "--mode", "metal", "--strict")
        if execute:
            verify_main(expected)
            if check_boot() != boot:
                raise RuntimeError("Node rebooted during preflight")
            capture(original)
            run("talosctl", "machineconfig", "patch", str(original), "--patch", "[]", "--output", str(normalized))
            if documents(normalized) != before:
                raise RuntimeError("Machine configuration changed during preflight")
            run(*client, "apply-config", "--mode", "no-reboot", "--file", str(candidate))
            if not rollback:
                run("kubectl", "wait", "--for=condition=Ready", "node/" + NODES[node], "--timeout=120s")
            capture(original)
            run("talosctl", "machineconfig", "patch", str(original), "--patch", "[]", "--output", str(normalized))
            if documents(normalized) != after or check_boot() != boot:
                raise RuntimeError("Post-apply configuration or no-reboot verification failed")
            if not rollback:
                run(*client, "image", "pull", "--namespace", "cri", "registry.k8s.io/pause:3.10")
    print(f"{NODES[node]}: {'config applied; no reboot verified' if execute else 'config validated only'} Harbor {'rollback' if rollback else 'mirrors'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=NODES)
    parser.add_argument("--talosconfig", type=Path, default=ROOT / ".talos/talosconfig",
                        help="Private Talos client config (default: repository .talos/talosconfig)")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    reconcile(args.node, args.execute, args.expected_sha, args.rollback, args.talosconfig)


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, OSError):
        raise SystemExit("Talos Harbor mirror operation failed; private command output withheld") from None
