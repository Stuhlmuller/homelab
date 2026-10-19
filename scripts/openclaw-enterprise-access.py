#!/usr/bin/env python3
"""Reconcile only the reviewed Octelium namespace and OpenClaw Enterprise Services."""
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit("Run this operator command with python3 -I")

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
TARGETS = {("Namespace", "oce"), ("Service", "console.oce"), ("Service", "openclaw")}
LIVE_NAMES = {("Namespace", "oce"), ("Service", "console.oce"), ("Service", "openclaw.default")}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60, **kwargs)


def reviewed_main(expected):
    if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("A full reviewed main SHA is required")
    if run("git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all",
           "--ignore-submodules=none").stdout:
        raise RuntimeError("Execution requires a clean checkout")
    head = run("git", "-C", str(ROOT), "rev-parse", "HEAD").stdout.strip()
    remote = run("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                 "refs/heads/main").stdout.split()[0]
    if head != expected or remote != expected:
        raise RuntimeError("Checkout and remote main must match the reviewed SHA")


def declared():
    all_resources = json.loads(run("yq", "ea", "-o=json", "-I=0", "[.]", str(CATALOG)).stdout)
    chosen = [obj for obj in all_resources if (obj.get("kind"), obj.get("metadata", {}).get("name")) in TARGETS]
    if len(chosen) != 3 or {(obj["kind"], obj["metadata"]["name"]) for obj in chosen} != TARGETS:
        raise RuntimeError("Octelium Enterprise catalog targets are missing or duplicate")
    namespace = next(obj for obj in chosen if obj["kind"] == "Namespace")
    console = next(obj for obj in chosen if obj["metadata"]["name"] == "console.oce")
    redirect = next(obj for obj in chosen if obj["metadata"]["name"] == "openclaw")
    if namespace["spec"] != {"authorization": {"policies": ["homelab-human-web-access"]}}:
        raise RuntimeError("Enterprise namespace authorization changed")
    for service in (console, redirect):
        spec = service["spec"]
        if (spec.get("isPublic") is not True or spec.get("isAnonymous") is not False
                or spec.get("authorization", {}).get("policies") != ["homelab-human-web-access"]
                or spec.get("mode") != "WEB" or spec.get("port") != 80):
            raise RuntimeError("Enterprise Service authorization changed")
    console_config = console["spec"].get("config", {})
    console_header = console_config.get("http", {}).get("header", {})
    if (console_config.get("upstream", {}).get("url") !=
            "http://openclaw-enterprise-api.openclaw-system.svc.cluster.local:8080"
            or console_header.get("host") != {"preserve": True}
            or console_header.get("removeRequestHeaders") != [
                "Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Port",
                "X-Forwarded-Proto", "X-Real-IP"]):
        raise RuntimeError("Enterprise console proxy contract changed")
    direct = redirect["spec"].get("config", {}).get("http", {}).get("plugins")
    if ("upstream" in redirect["spec"].get("config", {}) or direct != [{
            "name": "enterprise-redirect", "phase": "POST_AUTH", "condition": {"matchAny": True},
            "direct": {"statusCode": 303, "headers": [
                {"key": "Location", "value": "https://console.oce.stinkyboi.com/"},
                {"key": "Cache-Control", "value": "no-store"}]}}]):
        raise RuntimeError("Legacy URL must redirect only after Octelium authentication")
    return [namespace, console, redirect]


def apply(client, environment, directory, resources, expected):
    manifest = directory / "openclaw-enterprise-access.yaml"
    explicit = [({**obj, "metadata": {**obj["metadata"], "name": "openclaw.default"}}
                 if obj["metadata"]["name"] == "openclaw" else obj) for obj in resources]
    manifest.write_text("\n---\n".join(json.dumps(obj) for obj in explicit) + "\n")
    manifest.chmod(0o600)
    for attempt in range(2):
        reviewed_main(expected)
        result = run(*client, "apply", "--include", "Namespace", "--include", "Service",
                     str(manifest), env=environment)
        if re.search(r"Could not (parse Resource|list|create|update|apply)|Skipping this object|gRPC error",
                     result.stdout + result.stderr):
            raise RuntimeError("Octelium reported an apply failure")
        if attempt == 1 and "No applied changes in Cluster Core resources" not in result.stdout:
            raise RuntimeError("Repeated Enterprise access apply did not converge")
    for kind, name in sorted(LIVE_NAMES):
        live = json.loads(run(*client, "get", kind.lower(), name, "-o", "json", env=environment).stdout)
        if live.get("metadata", {}).get("name") != name:
            raise RuntimeError("Enterprise access readback identity mismatch")
        spec = live.get("spec", {})
        if kind == "Namespace":
            if spec.get("authorization", {}).get("policies") != ["homelab-human-web-access"]:
                raise RuntimeError("Enterprise namespace authorization did not converge")
            continue
        if (spec.get("isAnonymous") is not False or spec.get("isPublic") is not True
                or spec.get("authorization", {}).get("policies") != ["homelab-human-web-access"]):
            raise RuntimeError("Enterprise Service authorization did not converge")
        config = spec.get("config", {})
        if name == "console.oce":
            if (config.get("upstream", {}).get("url") !=
                    "http://openclaw-enterprise-api.openclaw-system.svc.cluster.local:8080"
                    or config.get("http", {}).get("header", {}).get("host", {}).get("preserve") is not True):
                raise RuntimeError("Enterprise console upstream did not converge")
        else:
            plugins = config.get("http", {}).get("plugins", [])
            if ("upstream" in config or not isinstance(plugins, list) or len(plugins) != 1
                    or plugins[0].get("phase") != "POST_AUTH"
                    or plugins[0].get("direct", {}).get("statusCode") != 303
                    or {item.get("key"): item.get("value") for item in plugins[0]["direct"].get("headers", [])}.get("Location")
                    != "https://console.oce.stinkyboi.com/"):
                raise RuntimeError("Legacy URL redirect did not converge")
    print("Octelium Enterprise namespace and Services converged; legacy route cutover remains separate")


def main():
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--homedir", help="Existing private Octelium operator login directory")
    args = parser.parse_args()
    if args.execute:
        reviewed_main(args.expected_sha)
    resources = declared()
    if not args.execute:
        print("Reviewed Octelium Enterprise access catalog contains exactly three scoped targets")
        return
    source = importlib.util.spec_from_file_location("native_transport", ROOT / "scripts/octelium-nofx-reconcile.py")
    helper = importlib.util.module_from_spec(source)
    source.loader.exec_module(helper)
    client = [helper.verified_client(), "--domain", "stinkyboi.com"]
    if args.homedir:
        client += ["--homedir", str(pathlib.Path(args.homedir).resolve())]
    with tempfile.TemporaryDirectory(prefix="octelium-openclaw-enterprise-") as temporary:
        directory = pathlib.Path(temporary)
        with helper.native_transport(directory) as environment:
            apply(client, environment, directory, resources, args.expected_sha)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, IndexError, AttributeError, TypeError,
            subprocess.SubprocessError, OSError):
        raise SystemExit("Octelium Enterprise access reconciliation failed; private output withheld") from None
