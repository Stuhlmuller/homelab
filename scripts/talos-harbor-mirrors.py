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
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
NODES = {"10.1.0.199": "acer", "10.1.0.200": "zimaboard-0",
         "10.1.0.201": "zimaboard-1", "10.1.0.202": "zimaboard-2"}
REPOSITORY = "Stuhlmuller/homelab"
TALOSCTL = "talosctl"


def run(*command, binary=False):
    if command[0] == "talosctl":
        command = (TALOSCTL, *command[1:])
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
    pages = json.loads(run("gh", "api", "--paginate", "--slurp",
                           f"repos/{REPOSITORY}/actions/workflows/harbor-mirror.yml/runs"
                           "?branch=main&event=workflow_dispatch&status=success&per_page=100"))
    published = False
    for item in (item for page in pages for item in page["workflow_runs"]):
        if (not isinstance(item, dict) or item.get("head_branch") != "main" or
                item.get("event") != "workflow_dispatch" or item.get("status") != "completed" or
                item.get("conclusion") != "success" or not isinstance(item.get("head_sha"), str) or
                not re.fullmatch(r"[0-9a-f]{40}", item["head_sha"])):
            continue
        revision = item["head_sha"]
        if item.get("display_title") != f"Mirror all @ {revision}":
            continue
        try:
            run("git", "merge-base", "--is-ancestor", revision, expected)
            published = all(run("git", "show", f"{revision}:{path}", binary=True) ==
                            run("git", "show", f"{expected}:{path}", binary=True) for path in (
                                "scripts/config/harbor-images.json", ".github/workflows/harbor-mirror.yml",
                                "scripts/ci/harbor-publish.sh", "scripts/ci/install-kubeconfig.sh",
                                "flake.nix", "flake.lock"))
        except subprocess.CalledProcessError:
            continue  # Missing local history or blobs cannot establish publication provenance.
        if published:
            break
    if not published:
        raise RuntimeError("No successful full-catalog Harbor mirror workflow for this publication bundle")
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


def registry_hosts(entries, declaration, rollback):
    if declaration != [{"ip": "10.96.0.50", "aliases": ["harbor.stinkyboi.com"]}]:
        raise RuntimeError("Unexpected private registry host declaration")
    result = []
    for entry in entries:
        aliases = entry["aliases"]
        if "harbor.stinkyboi.com" not in aliases:
            result.append(copy.deepcopy(entry))
            continue
        if entry["ip"] != declaration[0]["ip"]:
            raise RuntimeError("Conflicting Harbor host mapping; refusing to replace operator state")
        aliases = [alias for alias in aliases if alias != "harbor.stinkyboi.com"]
        if aliases:
            result.append({**entry, "aliases": aliases})
    return result if rollback else result + copy.deepcopy(declaration)


def hosts_only(before, after, wanted):
    original, candidate = copy.deepcopy(before), copy.deepcopy(after)
    for stream in (original, candidate):
        configs = [item for item in stream if item.get("version") == "v1alpha1"]
        if len(configs) != 1:
            raise RuntimeError("Expected exactly one v1alpha1 document")
        machine = configs[0]["machine"]
        network = machine.setdefault("network", {})
        if stream is candidate and network.get("extraHostEntries", []) != wanted:
            raise RuntimeError("Rendered Harbor hostname entries do not match the declared patch")
        network.pop("extraHostEntries", None)
        if not network:
            machine.pop("network")
    if original != candidate:
        raise RuntimeError("Refusing changes outside machine.network.extraHostEntries")


def verify_registry_route():
    service = json.loads(run("kubectl", "-n", "traefik", "get", "service", "traefik-registry", "-o", "json"))
    config = service["spec"]
    if (config.get("clusterIP") != "10.96.0.50" or config.get("type") != "ClusterIP"
            or config.get("externalIPs") or len(config.get("ports", [])) != 1
            or config["ports"][0]["port"] != 443 or config["ports"][0]["targetPort"] != 9443
            or config.get("selector", {}).get("app.kubernetes.io/name") != "traefik"):
        raise RuntimeError("Private registry Service does not match its fixed node-access contract")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="harbor-node-route-") as temporary:
        with (Path(temporary) / "forward.log").open("wb") as log:
            forward = subprocess.Popen(["kubectl", "-n", "traefik", "port-forward", "--address", "127.0.0.1",
                                        "service/traefik-registry", f"{port}:443"], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 30
                while True:
                    if forward.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Private registry TLS port-forward did not become ready")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=1):
                            break
                    except OSError:
                        time.sleep(0.2)
                curl = ("curl", "--disable", "--silent", "--show-error", "--noproxy", "*", "--max-time", "15",
                        "--proto", "=https", "--connect-to", f"harbor.stinkyboi.com:443:127.0.0.1:{port}")
                headers = run(*curl, "--dump-header", "-", "--output", "/dev/null", "https://harbor.stinkyboi.com/v2/")
                if (not re.search(r"^HTTP/\S+ 401\b", headers, re.MULTILINE)
                        or not re.search(r'^www-authenticate:\s*Bearer [^\r\n]*realm="https://harbor\.stinkyboi\.com/service/token"', headers, re.IGNORECASE | re.MULTILINE)):
                    raise RuntimeError("Private registry route did not preserve Harbor's TLS Bearer challenge")
                token = json.loads(run(*curl, "--fail", "https://harbor.stinkyboi.com/service/token?service=harbor-registry&scope=repository:mirror/registry.k8s.io/pause:pull"))
                if not isinstance(token.get("token"), str) or not token["token"]:
                    raise RuntimeError("Private registry token route failed")
                for url in ("https://harbor.stinkyboi.com/", "https://harbor.stinkyboi.com/api/v2.0/projects",
                            "https://grafana.stinkyboi.com/"):
                    code = run(*curl, "--connect-to", f"grafana.stinkyboi.com:443:127.0.0.1:{port}",
                               "--output", "/dev/null", "--write-out", "%{http_code}", url)
                    if code != "404":
                        raise RuntimeError("Private registry entrypoint exposes a non-registry route")
            finally:
                forward.terminate()
                try:
                    forward.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forward.kill()
                    forward.wait()


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


def reconcile(node, execute, expected, rollback, talosconfig=None, registry_host_only=False):
    talosconfig = Path(talosconfig or ROOT / ".talos/talosconfig").expanduser().resolve()
    if not talosconfig.is_file():
        raise RuntimeError("The selected Talos client configuration is unavailable")
    if not re.search(r"^Talos v1\.11\.3$", run("talosctl", "version", "--client", "--short"), re.MULTILINE):
        raise RuntimeError("This rollout requires talosctl 1.11.3")
    if execute:
        verify_main(expected)
        if not rollback and not registry_host_only:
            verify_copies(expected)
        elif not rollback:
            verify_registry_route()
    client = ["talosctl", "--talosconfig", str(talosconfig), "--endpoints", "10.1.0.199", "--nodes", node]
    # Recovery must work while Harbor-dependent Kubernetes components are down.
    def check_boot():
        return talos_boot(client) if rollback else ready(node)

    boot = check_boot()
    patch = ROOT / (".talos/patches/harbor-registry-host.yaml" if registry_host_only else
                    ".talos/patches/harbor-mirrors-rollback.yaml" if rollback else
                    ".talos/patches/harbor-mirrors.yaml")
    declaration = documents(patch)[0]["machine"]
    wanted = declaration["network"]["extraHostEntries"] if registry_host_only else declaration["registries"]["mirrors"]
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
        section = "network" if registry_host_only else "registries"
        field = "extraHostEntries" if registry_host_only else "mirrors"
        if registry_host_only:
            wanted = registry_hosts(configs[0]["machine"].get("network", {}).get("extraHostEntries", []), wanted, rollback)
        operations = [] if section in configs[0]["machine"] else [
            {"op": "add", "path": f"/machine/{section}", "value": {}}]
        operations.append({"op": "add", "path": f"/machine/{section}/{field}", "value": wanted})
        run("talosctl", "machineconfig", "patch", str(normalized), "--patch", json.dumps(operations), "--output", str(candidate))
        after = documents(candidate)
        (hosts_only if registry_host_only else mirrors_only)(before, after, wanted)
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
                image = "harbor.stinkyboi.com/mirror/registry.k8s.io/pause:3.10" if registry_host_only else "registry.k8s.io/pause:3.10"
                run(*client, "image", "pull", "--namespace", "system", image)
    print(f"{NODES[node]}: {'config applied; no reboot verified' if execute else 'config validated only'} Harbor {'hostname' if registry_host_only else 'mirrors'}{' rollback' if rollback else ''}")


def main():
    global TALOSCTL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=NODES)
    parser.add_argument("--talosconfig", type=Path, default=ROOT / ".talos/talosconfig",
                        help="Private Talos client config (default: repository .talos/talosconfig)")
    parser.add_argument("--talosctl", default="talosctl", help="Talos 1.11.3 executable (default: talosctl on PATH)")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--registry-host-only", action="store_true",
                        help="Change only Harbor's private node hostname mapping; preserve all registry mirrors")
    args = parser.parse_args()
    TALOSCTL = args.talosctl
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    reconcile(args.node, args.execute, args.expected_sha, args.rollback, args.talosconfig, args.registry_host_only)


if __name__ == "__main__":
    if not sys.flags.isolated:
        raise SystemExit("Run this operator command with python3 -I")
    try:
        main()
    except (RuntimeError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError, OSError):
        raise SystemExit("Talos Harbor mirror operation failed; private command output withheld") from None
