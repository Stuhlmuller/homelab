#!/usr/bin/env python3
"""Inspect or reconcile only the three repository-owned Cordium CI identities."""
import argparse
import importlib.util
import json
import pathlib
import re
import signal
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "docs/examples/octelium/homelab-services.yaml"
# Restrict the policy before enabling the provider and attaching its workload User.
TARGETS = (
    ("Policy", "homelab-cordium-ci-execution"),
    ("IdentityProvider", "homelab-cordium-ci-oidc"),
    ("User", "homelab-cordium-ci"),
)
spec = importlib.util.spec_from_file_location("native", ROOT / "scripts/octelium-nofx-reconcile.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def declared_resources():
    records = json.loads(native.run("yq", "ea", "-o=json", "-I=0", "[.]", str(CATALOG)).stdout)
    selected = [item for item in records if isinstance(item, dict)
                and (item.get("kind"), item.get("metadata", {}).get("name")) in TARGETS]
    if len(selected) != len(TARGETS):
        raise RuntimeError("Catalog must declare exactly the three Cordium CI resources")
    result = []
    for kind, name in TARGETS:
        matches = [item for item in selected if (item["kind"], item["metadata"]["name"]) == (kind, name)]
        if len(matches) != 1 or not isinstance(matches[0].get("spec"), dict):
            raise RuntimeError("Missing, duplicate, or invalid Cordium CI resource")
        result.append(matches[0])
    if not (ROOT / ".github/workflows/cordium-check.yml").is_file():
        raise RuntimeError("The reviewed Cordium CI dispatch workflow must exist")
    return result


def inspect(client, environment, desired):
    kind, name = desired["kind"], desired["metadata"]["name"]
    result = subprocess.run([*client, "get", kind.lower(), name, "-o", "json"],
                            env=environment, capture_output=True, text=True, timeout=45)
    if result.returncode:
        if (re.search(r"^gRPC error NotFound:", result.stdout, re.MULTILINE)
                or re.search(r"\bcode = NotFound\b", result.stderr)):
            return None
        raise RuntimeError("Native inspection failed; absence is not established")
    value = json.loads(result.stdout)
    if (value.get("metadata", {}).get("name") != name
            or value.get("kind", kind) != kind):
        raise RuntimeError("Native inspection returned an unexpected resource identity")
    return value


def reconcile(client, environment, desired, directory, execute):
    before = [inspect(client, environment, item) for item in desired]
    for item, current in zip(desired, before):
        matches = current is not None and current.get("spec") == item["spec"]
        print(f'{item["kind"]} {item["metadata"]["name"]}: present={current is not None}, declared_spec_matches={matches}')
    if not execute:
        print("Read-only check; no native catalog resources changed")
        return
    manifests = []
    for item in desired:
        path = directory / f'{item["kind"].lower()}.json'
        path.write_text(json.dumps(item))
        path.chmod(0o600)
        manifests.append(path)
    for pass_number in range(2):
        for item, path in zip(desired, manifests):
            result = native.run(*client, "apply", "--include", item["kind"], str(path), env=environment)
            if re.search(r"Could not (list|create|update|apply)|gRPC error", result.stdout + result.stderr):
                raise RuntimeError("Native catalog apply reported a failure")
            if pass_number == 1 and "No applied changes in Cluster Core resources" not in result.stdout:
                raise RuntimeError("Second catalog apply did not prove convergence")
    for item in desired:
        current = inspect(client, environment, item)
        if current is None or current.get("spec") != item["spec"]:
            raise RuntimeError("Native resource does not match its reviewed specification")
    print("Verified the three Cordium CI resources and repeated-apply convergence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homedir", help="Private existing operator login directory")
    parser.add_argument("--execute", action="store_true", help="Apply and verify only the three fixed resources")
    parser.add_argument("--expected-sha", help="Exact reviewed main commit required for execution")
    args = parser.parse_args()
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    if args.execute:
        native.verify_reviewed_main(args.expected_sha)
        native.run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/cordium-ci-reconcile.py")
    desired = declared_resources()
    client = [native.verified_client(), "--domain", "stinkyboi.com"]
    if args.homedir:
        client += ["--homedir", str(pathlib.Path(args.homedir).resolve())]
    with tempfile.TemporaryDirectory(prefix="cordium-ci-catalog-") as temporary:
        directory = pathlib.Path(temporary)
        with native.native_transport(directory) as environment:
            reconcile(client, environment, desired, directory, args.execute)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.SubprocessError, OSError):
        raise SystemExit("Cordium CI reconciliation failed; private native-client output withheld") from None
