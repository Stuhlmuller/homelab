#!/usr/bin/env python3
"""Run the staged homelab checks on its isolated Linux builder; export results."""

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("offline-tests", "manifest-policy")

CANCEL_SCRIPT = r"""
set -eu
group_alive() {
    for member in /proc/[0-9]*/stat; do
        fields=$(cat "$member" 2>/dev/null || true)
        [ -n "$fields" ] || continue
        fields=${fields##*) }
        set -- $fields
        [ "$3" = "$pid" ] && [ "$1" != Z ] && return 0
    done
    return 1
}
found=0
for proc in /proc/[0-9]*; do
    [ "$(cat "$proc/comm" 2>/dev/null || true)" = timeout ] || continue
    command=$(cat "$proc/cmdline" 2>/dev/null | tr '\000' ' ')
    [ "$command" = EXPECTED ] || continue
    pid=${proc##*/}
    fields=$(cat "$proc/stat")
    fields=${fields##*) }
    set -- $fields
    [ "$3" = "$pid" ] || { echo 'Refusing non-isolated process group' >&2; exit 1; }
    kill -TERM "-$pid"
    remaining=10
    while group_alive && [ "$remaining" -gt 0 ]; do
        sleep 1
        remaining=$((remaining - 1))
    done
    if group_alive; then kill -KILL "-$pid"; fi
    remaining=10
    while group_alive && [ "$remaining" -gt 0 ]; do
        sleep 1
        remaining=$((remaining - 1))
    done
    if group_alive; then echo "Cancellation unconfirmed for group $pid" >&2; exit 1; fi
    if [ "$(cat /workspace/offline-check.lock/owner 2>/dev/null || true)" = "$pid" ]; then
        rm /workspace/offline-check.lock/owner
        rmdir /workspace/offline-check.lock
    fi
    echo "Cancelled offline check process group $pid"
    found=1
done
[ "$found" = 1 ] || echo 'No matching offline check supervisor remains; retained locks require review'
"""


def build_command(policy):
    return ["nix", "build",
            "--print-build-logs", "--no-link", "--print-out-paths", "--no-update-lock-file",
            "--option", "sandbox", "true", "--option", "require-sigs", "true",
            "--option", "max-substitution-jobs", "1",
            "--option", "extra-substituters", policy["url"],
            "--option", "extra-trusted-public-keys", policy["publicKey"],
            ".#checks.x86_64-linux.offline-tests", ".#checks.x86_64-linux.manifest-policy"]


def cancel(policy, pod, uid):
    # Confirm group termination even when the supervisor exits before a child.
    current = json.loads(subprocess.check_output([
        "kubectl", "--request-timeout=15s", "get", "pod", pod, "--namespace", "nix-builder", "-o", "json"],
        text=True, timeout=20))
    if current["metadata"]["uid"] != uid:
        raise ValueError("Refusing cancellation against a replacement pod")
    command = " ".join(attempt_command(policy)) + " "
    subprocess.run([
        "kubectl", "--request-timeout=15s", "exec", "-i", "--namespace", "nix-builder",
        pod, "--container", "nix", "--", "sh", "-s"],
        input=CANCEL_SCRIPT.replace("EXPECTED", shlex.quote(command)), text=True,
        cwd=ROOT, check=True, timeout=40)


def memory_bytes(value):
    for suffix, multiplier in (("Ki", 1024), ("Mi", 1024 ** 2), ("Gi", 1024 ** 3)):
        if value.endswith(suffix):
            return int(value[:-len(suffix)]) * multiplier
    return int(value)


def verify_preflight(nodes, leases, metrics, pod, now):
    for node in nodes["items"]:
        name = node["metadata"]["name"]
        conditions = {item["type"]: item["status"] for item in node["status"]["conditions"]}
        if conditions.get("Ready") != "True" or any(
                conditions.get(condition) != "False" for condition in ("MemoryPressure", "DiskPressure", "PIDPressure")):
            raise ValueError(f"Node not ready or under pressure: {name}")
        lease = next(item for item in leases["items"] if item["metadata"]["name"] == name)
        renewed = datetime.fromisoformat(lease["spec"]["renewTime"].replace("Z", "+00:00"))
        if not 0 <= (now - renewed).total_seconds() <= 75:
            raise ValueError(f"Stale node lease: {name}")
    if pod["metadata"].get("deletionTimestamp") or not any(
            item["type"] == "Ready" and item["status"] == "True" for item in pod["status"].get("conditions", [])):
        raise ValueError("Builder pod is not Ready")
    container = next(item for item in pod["spec"]["containers"] if item["name"] == "nix")
    if any(memory_bytes(container["resources"][kind]["memory"]) != 1024 ** 3 for kind in ("limits", "requests")):
        raise ValueError("Builder must retain its 1 GiB memory reservation and limit")
    node_name = pod["spec"]["nodeName"]
    node = next(item for item in nodes["items"] if item["metadata"]["name"] == node_name)
    metric = next(item for item in metrics["items"] if item["metadata"]["name"] == node_name)
    measured = datetime.fromisoformat(metric["timestamp"].replace("Z", "+00:00"))
    if not 0 <= (now - measured).total_seconds() <= 120:
        raise ValueError("Builder node memory metrics are stale")
    headroom = memory_bytes(node["status"]["allocatable"]["memory"]) - memory_bytes(metric["usage"]["memory"])
    if headroom < 1536 * 1024 ** 2:
        raise ValueError("Builder node needs at least 1.5 GiB measured allocatable memory headroom")


def preflight():
    def read(*args):
        return json.loads(subprocess.check_output(["kubectl", "--request-timeout=15s", *args], text=True, timeout=20))
    pods = read("get", "pods", "--namespace", "nix-builder", "--selector", "app.kubernetes.io/name=nix-builder", "-o", "json")["items"]
    if len(pods) != 1:
        raise ValueError("Expected exactly one idle builder pod")
    pod = pods[0]
    verify_preflight(read("get", "nodes", "-o", "json"),
                     read("get", "leases", "--namespace", "kube-node-lease", "-o", "json"),
                     read("get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"), pod, datetime.now(timezone.utc))
    return pod["metadata"]["name"], pod["metadata"]["uid"]


def attempt_command(policy):
    script = """
set -eu
trap '' TERM INT
test "$(cat /sys/fs/cgroup/memory.max)" = 1073741824
mkdir /workspace/offline-check.lock
printf '%s\n' "$PPID" > /workspace/offline-check.lock/owner
trap 'rm /workspace/offline-check.lock/owner; rmdir /workspace/offline-check.lock' EXIT
for proc in /proc/[0-9]*; do
    [ "${proc##*/}" = "$PPID" ] && continue
    case "$(cat "$proc/comm" 2>/dev/null || true)" in
        nix|timeout) echo 'Builder already has an active check process' >&2; exit 1 ;;
    esac
done
test "$(nix eval --impure --raw --expr builtins.currentSystem)" = x86_64-linux
job="$(mktemp -d /workspace/check.XXXXXX)"
trap 'if [ -d "$job" ]; then rm -rf -- "$job"; fi; rm /workspace/offline-check.lock/owner; rmdir /workspace/offline-check.lock' EXIT
mkdir "$job/source"
tar -x -C "$job/source"
cd "$job/source"
COMMAND > "$job/outputs"
nix copy --to "file://$job/cache" $(cat "$job/outputs")
tar -c -C "$job/cache" .
""".replace("COMMAND", shlex.join(build_command(policy)))
    return ["timeout", "--kill-after=10s", "1800s", "sh", "-ec", script, "homelab-offline-attempt"]


def export(destination, policy):
    subprocess.run(["git", "diff", "--quiet"], cwd=ROOT, check=True)
    tree = subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "archive", tree], cwd=ROOT)
    expected = {
        subprocess.check_output(["nix", "eval", "--raw", "--no-update-lock-file",
                                 f".#checks.x86_64-linux.{check}.outPath"], cwd=ROOT, text=True).strip()
        for check in CHECKS
    }
    pod, uid = preflight()
    print(f"Builder attempt uses pod {pod} UID {uid}", file=sys.stderr)
    try:
        archive = subprocess.check_output([
            "kubectl", "exec", "-i", "--namespace", "nix-builder",
            pod, "--container", "nix", "--", *attempt_command(policy)],
            input=source, cwd=ROOT, timeout=1860)
    except BaseException:
        cancel(policy, pod, uid)
        raise
    unpack(archive, destination)
    actual = set()
    for info in destination.glob("*.narinfo"):
        fields = dict(line.split(": ", 1) for line in info.read_text().splitlines() if ": " in line)
        actual.add(fields["StorePath"])
        if fields.get("References", ""):
            raise ValueError("Check output unexpectedly references other store objects")
    if actual != expected:
        raise ValueError("Builder returned outputs for different source inputs")
    return sorted(expected)


def unpack(archive, destination):
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or not (member.isdir() or member.isfile()):
                raise ValueError("Unsafe builder archive entry")
            path = destination / relative
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(member).read())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output-directory", type=Path)
    action.add_argument("--cancel", action="store_true", help="Stop only matching offline checks on the declared builder")
    parser.add_argument("--pod", help="Original pod name, required for cancellation")
    parser.add_argument("--pod-uid", help="Original pod UID printed when the attempt started")
    args = parser.parse_args()
    policy = json.loads((ROOT / "scripts/config/nix-cache.json").read_text())
    if args.cancel:
        if not args.pod or not args.pod.startswith("nix-builder-") or not args.pod_uid:
            parser.error("Cancellation requires the original --pod nix-builder-... and --pod-uid")
        cancel(policy, args.pod, args.pod_uid)
        raise SystemExit(0)
    if args.output_directory.exists():
        parser.error("Output directory must be new")
    args.output_directory.mkdir(mode=0o700, parents=True)
    print("\n".join(export(args.output_directory, policy)))
