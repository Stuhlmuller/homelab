#!/usr/bin/env python3
"""Run the staged homelab checks on its isolated Linux builder; export results."""

import argparse
import io
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("offline-tests", "manifest-policy")

CANCEL_SCRIPT = r"""
set -eu
found=0
for proc in /proc/[0-9]*; do
    [ "$(cat "$proc/comm" 2>/dev/null || true)" = nix ] || continue
    case "$(readlink "$proc/cwd" 2>/dev/null || true)" in
        /workspace/check.??????/source) ;;
        *) continue ;;
    esac
    command=$(cat "$proc/cmdline" 2>/dev/null | tr '\000' ' ')
    [ "$command" = EXPECTED ] || continue
    pid=${proc##*/}
    kill -TERM "$pid"
    echo "Cancellation requested for offline checks PID $pid"
    found=1
done
[ "$found" = 1 ] || echo 'No matching offline check process remains'
"""


def cancel(policy):
    # Match the complete declared command and workspace before signalling it.
    command = " ".join((
        "nix build --print-build-logs --no-link --print-out-paths --no-update-lock-file",
        "--option sandbox true --option require-sigs true",
        "--option extra-substituters", policy["url"],
        "--option extra-trusted-public-keys", policy["publicKey"],
        ".#checks.x86_64-linux.offline-tests .#checks.x86_64-linux.manifest-policy")) + " "
    subprocess.run([
        "kubectl", "--request-timeout=15s", "exec", "-i", "--namespace", "nix-builder",
        "deployment/nix-builder", "--container", "nix", "--", "sh", "-s"],
        input=CANCEL_SCRIPT.replace("EXPECTED", shlex.quote(command)), text=True,
        cwd=ROOT, check=True, timeout=30)


def export(destination, policy):
    subprocess.run(["git", "diff", "--quiet"], cwd=ROOT, check=True)
    tree = subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "archive", tree], cwd=ROOT)
    expected = {
        subprocess.check_output(["nix", "eval", "--raw", "--no-update-lock-file",
                                 f".#checks.x86_64-linux.{check}.outPath"], cwd=ROOT, text=True).strip()
        for check in CHECKS
    }
    flags = " ".join(shlex.quote(value) for value in (
        "--option", "extra-substituters", policy["url"],
        "--option", "extra-trusted-public-keys", policy["publicKey"]))
    script = """
set -eu
test "$(nix eval --impure --raw --expr builtins.currentSystem)" = x86_64-linux
job="$(mktemp -d /workspace/check.XXXXXX)"
trap 'if [ -d "$job" ]; then rm -rf -- "$job"; fi' EXIT
mkdir "$job/source"
tar -x -C "$job/source"
cd "$job/source"
nix build --print-build-logs --no-link --print-out-paths --no-update-lock-file \
  --option sandbox true --option require-sigs true FLAGS \
  .#checks.x86_64-linux.offline-tests .#checks.x86_64-linux.manifest-policy > "$job/outputs"
nix copy --to "file://$job/cache" $(cat "$job/outputs")
tar -c -C "$job/cache" .
""".replace("FLAGS", flags)
    archive = subprocess.check_output([
        "kubectl", "exec", "-i", "--namespace", "nix-builder",
        "deployment/nix-builder", "--container", "nix", "--", "sh", "-ec", script],
        input=source, cwd=ROOT, timeout=3600)
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
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output-directory", type=Path)
    action.add_argument("--cancel", action="store_true", help="Stop only matching offline checks on the declared builder")
    args = parser.parse_args()
    policy = json.loads((ROOT / "scripts/config/nix-cache.json").read_text())
    if args.cancel:
        cancel(policy)
        raise SystemExit(0)
    if args.output_directory.exists():
        parser.error("Output directory must be new")
    args.output_directory.mkdir(mode=0o700, parents=True)
    print("\n".join(export(args.output_directory, policy)))
