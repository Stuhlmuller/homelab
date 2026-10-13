#!/usr/bin/env python3
"""Retire one public WEB Service removed from the reviewed repository catalog."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run with python3 -I")

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("native", ROOT / "scripts/octelium-nofx-reconcile.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
CATALOG = "docs/examples/octelium/homelab-services.yaml"


def removed_service(name):
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ValueError("Use an unqualified default-namespace Service name")
    def catalog(source):
        return json.loads(native.run("yq", "ea", "-o=json", "-I=0", "[.]", "-", input=source).stdout)
    current = catalog((ROOT / CATALOG).read_text())
    previous = catalog(native.run("git", "-C", str(ROOT), "show", f"HEAD^:{CATALOG}").stdout)
    def matches(rows):
        return [row for row in rows if row.get("kind") == "Service" and row.get("metadata", {}).get("name") == name]
    old = matches(previous)
    if matches(current) or len(old) != 1 or old[0].get("spec", {}).get("mode") != "WEB" or old[0]["spec"].get("isPublic") is not True:
        raise ValueError("Service must be a public WEB entry removed by the current commit")
    return name + ".default"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True)
    parser.add_argument("--homedir", required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        native.verify_reviewed_main(args.expected_sha)
        native.run("git", "-C", str(ROOT), "cat-file", "-e", "HEAD:scripts/octelium-service-retire.py")
    name = removed_service(args.service)
    if not args.execute:
        print(f"Dry run: retire Service {name}")
        return
    client = [native.verified_client(), "--homedir", str(pathlib.Path(args.homedir).resolve()), "--domain", "stinkyboi.com"]
    with tempfile.TemporaryDirectory(prefix="octelium-service-retire-") as directory:
        with native.native_transport(pathlib.Path(directory)) as environment:
            def get():
                result = subprocess.run(client + ["get", "service", name, "-o", "json"], env=environment, capture_output=True, text=True, timeout=30)
                if result.returncode:
                    if re.search(r"^gRPC error NotFound:|\bcode = NotFound\b", result.stdout + result.stderr, re.MULTILINE):
                        return None
                    raise RuntimeError("Service inspection failed; private output withheld")
                value = json.loads(result.stdout)
                if value.get("metadata", {}).get("name") != name or value.get("spec", {}).get("mode") != "WEB" or value["spec"].get("isPublic") is not True:
                    raise RuntimeError("Live Service does not match the reviewed public WEB identity")
                return value
            if get() is not None:
                subprocess.run(client + ["delete", "service", name], env=environment, capture_output=True, text=True, timeout=30, check=True)
                if get() is not None:
                    raise RuntimeError("Service still exists after retirement")
    print(f"Verified retirement: Service {name}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(type(error).__name__ + ": retirement failed", file=sys.stderr)
        sys.exit(1)
