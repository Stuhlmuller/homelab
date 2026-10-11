#!/usr/bin/env python3
"""Validate or reconcile NRI on the fixed worker canary through reviewed main."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
NODE = "10.1.0.202"
NAME = "zimaboard-2"
CRI = "/etc/cri/conf.d/cri.toml"


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


harbor = module("harbor", "talos-harbor-mirrors.py")
nri = module("nri", "talos-nri-config.py")
effective = module("effective", "talos-nri-effective-check.py")


def run(*args):
    return harbor.run(*args)


def engine_absent():
    # Keep the declared policy engine out of the NRI plumbing stage.
    for kind in ("pods", "daemonsets"):
        resources = json.loads(run("kubectl", "get", kind, "-A", "-o", "json"))
        for item in resources["items"]:
            spec = item.get("spec", {})
            spec = spec.get("template", {}).get("spec", spec)
            images = [c.get("image", "") for c in spec.get("containers", []) + spec.get("initContainers", [])]
            if any("kube-network-policies" in image for image in images):
                raise ValueError("Withdraw the policy engine through GitOps before NRI runtime changes")


def identity(client, rollback=False):
    config = json.loads(run("kubectl", "config", "view", "--minify", "-o", "json"))
    if (config.get("current-context") != "admin@homelab" or
            len(config.get("clusters", [])) != 1 or
            config["clusters"][0]["cluster"]["server"] != "https://10.1.0.199:6443"):
        raise ValueError("Unexpected Kubernetes operator context")
    node = json.loads(run("kubectl", "get", "node", NAME, "-o", "json"))
    labels = node["metadata"].get("labels", {})
    if any(key in labels for key in ("node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master")):
        raise ValueError("The NRI canary must be a worker")
    boot = harbor.talos_boot(client)
    if (node["status"]["nodeInfo"]["bootID"] != boot or
            not any(a["type"] == "InternalIP" and a["address"] == NODE for a in node["status"]["addresses"])):
        raise ValueError("Unexpected canary node identity")
    if not rollback and harbor.ready(NODE) != boot:
        raise ValueError("Kubernetes and Talos boot identities differ")
    nodes = json.loads(run("kubectl", "get", "nodes", "-o", "json"))["items"]
    if (len(nodes) != len(harbor.NODES) or
            {n["metadata"]["name"] for n in nodes} != set(harbor.NODES.values()) or
            any(not any(c["type"] == "Ready" and c["status"] == "True"
                        for c in n["status"]["conditions"]) for n in nodes
                if not rollback or n["metadata"]["name"] != NAME)):
        raise ValueError("All declared nodes must be Ready before a canary runtime change")
    return boot


def healthy(client):
    resource = json.loads(run(*client, "get", "service", "cri", "-o", "json"))
    state = resource.get("spec", {})
    return state.get("running") is True and state.get("healthy") is True and state.get("unknown") is False


def dataplane_ready():
    pods = json.loads(run("kubectl", "get", "pods", "-A", "--field-selector", "spec.nodeName=" + NAME, "-o", "json"))["items"]
    for owner in ("kube-flannel", "istio-cni-node", "ztunnel"):
        selected = [p for p in pods if any(o.get("kind") == "DaemonSet" and o.get("name") == owner
                                          for o in p["metadata"].get("ownerReferences", []))]
        if (not selected or any(p["metadata"].get("deletionTimestamp") or
                not any(condition["type"] == "Ready" and condition["status"] == "True"
                        for condition in p.get("status", {}).get("conditions", [])) for p in selected)):
            return False
    return True


def merged(client):
    return tomllib.loads(run(*client, "read", CRI))


def wait(check):
    deadline = time.monotonic() + 120
    while True:
        try:
            if check():
                return
        except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError("Canary convergence timed out; leave the worker cordoned")
        time.sleep(3)


def reconcile(talosconfig, talosctl, execute=False, expected=None, rollback=False, release=False):
    harbor.TALOSCTL = talosctl
    talosconfig = talosconfig.expanduser().resolve()
    if not talosconfig.is_file():
        raise ValueError("Authenticated Talos client configuration is unavailable")
    if not re.search(r"^Talos v1\.11\.3$", run("talosctl", "version", "--client", "--short"), re.MULTILINE):
        raise ValueError("The canary requires talosctl 1.11.3")
    if release and not execute:
        raise ValueError("Scheduling release requires explicit execution")
    if execute:
        harbor.verify_main(expected)
        if not rollback:
            harbor.verify_copies(expected)
    client = ["talosctl", "--talosconfig", str(talosconfig), "--endpoints", "10.1.0.199", "--nodes", NODE]
    boot = identity(client, rollback)
    engine_absent()
    if (not rollback or release) and not healthy(client):
        raise ValueError("CRI must be running and healthy before the canary")
    with tempfile.TemporaryDirectory(prefix="nri-canary-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        original, candidate, readback = (root / name for name in ("before.yaml", "candidate.yaml", "after.yaml"))
        harbor.capture(client, original)
        before = nri.documents(original)
        config = [d for d in before if d.get("version") == "v1alpha1"]
        if len(config) != 1 or config[0]["machine"]["type"] != "worker":
            raise ValueError("Machine configuration is not a worker")
        before_cri = merged(client)
        nri.prepare(original, candidate, rollback, talosctl)
        wanted = nri.documents(candidate)
        if release:
            if before != wanted:
                raise ValueError("Scheduling release requires the declared active NRI configuration")
            effective.verify(before_cri, before_cri, rollback)
            harbor.verify_main(expected)
            if identity(client, rollback) != boot:
                raise ValueError("Canary boot changed")
            engine_absent()
            if not healthy(client):
                raise ValueError("CRI health changed")
            if not dataplane_ready():
                raise ValueError("Canary dataplane Pods must be Ready before scheduling release")
            harbor.verify_main(expected)
            run("kubectl", "uncordon", NAME)
            print("Canary scheduling released; NRI registration and policy enforcement remain separate gates")
            return
        if not execute:
            print("Canary identity, configuration and CRI health verified; candidate validated; no live mutation")
            return
        harbor.verify_main(expected)
        if identity(client, rollback) != boot:
            raise ValueError("Canary boot changed during preparation")
        harbor.capture(client, readback)
        if nri.documents(readback) != before or merged(client) != before_cri:
            raise ValueError("Canary configuration changed during preparation")
        engine_absent()
        # Respect PDBs and refuse unmanaged Pods or emptyDir data deletion.
        run("kubectl", "drain", NAME, "--ignore-daemonsets", "--timeout=120s")
        harbor.verify_main(expected)
        if harbor.talos_boot(client) != boot:
            raise ValueError("Canary rebooted during drain")
        harbor.capture(client, readback)
        if nri.documents(readback) != before or merged(client) != before_cri:
            raise ValueError("Canary configuration changed during drain")
        engine_absent()
        run(*client, "apply-config", "--mode", "no-reboot", "--file", str(candidate))

        def configuration_matches():
            harbor.capture(client, readback)
            if nri.documents(readback) != wanted:
                return False
            effective.verify(before_cri, merged(client), rollback)
            return True

        wait(configuration_matches)
        if harbor.talos_boot(client) != boot:
            raise ValueError("Canary rebooted after configuration change")
        harbor.verify_main(expected)
        engine_absent()
        run(*client, "service", "cri", "restart")
        wait(lambda: healthy(client))
        wait(lambda: harbor.ready(NODE) == boot)
        wait(dataplane_ready)
        if not configuration_matches() or harbor.talos_boot(client) != boot:
            raise ValueError("Canary post-restart verification failed")
    print("Declared NRI state and CRI health verified without reboot; worker remains cordoned")
    print("Use the guarded scheduling-release action after canary acceptance; no policy enforcement claim")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--talosconfig", required=True, type=Path)
    parser.add_argument("--talosctl", default="talosctl")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--release-scheduling", action="store_true")
    args = parser.parse_args()
    try:
        reconcile(args.talosconfig, args.talosctl, args.execute, args.expected_sha,
                  args.rollback, args.release_scheduling)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AssertionError, subprocess.SubprocessError):
        raise SystemExit("NRI canary failed; private output withheld; after drain keep the worker cordoned and use the reviewed rollback path") from None


if __name__ == "__main__":
    main()
