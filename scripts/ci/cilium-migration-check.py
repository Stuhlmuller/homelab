#!/usr/bin/env python3
"""Exercise mixed Flannel and Cilium pod routing in a disposable Kind cluster."""

import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
CLUSTER = "cilium-migration-check"
CONTROL = CLUSTER + "-control-plane"
WORKER = CLUSTER + "-worker"
NODE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
PYTHON = "cgr.dev/chainguard/python:latest@sha256:5d7edd76101b0b8112b723072125f428dbfd291d7cc56a6418a5f619023e2542"
FLANNEL = "https://raw.githubusercontent.com/flannel-io/flannel/v0.27.4/Documentation/kube-flannel.yml"
CHART = "https://helm.cilium.io/cilium-1.20.5.tgz"
SELECTOR = "io.cilium.migration/cilium-default"


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop("timeout", 300), **kwargs)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {result.stderr or result.stdout}")
    return result.stdout


def download(url, destination, expected_hash):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"Unexpected content hash for {url}")
    destination.write_bytes(data)


def apply(kubectl, obj):
    run(*kubectl, "apply", "-f", "-", input=json.dumps(obj))


def endpoint(kubectl, name, node):
    apply(kubectl, {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": {"fixture": name}},
        "spec": {
            "nodeName": node,
            "automountServiceAccountToken": False,
            "containers": [{
                "name": "http",
                "image": PYTHON,
                "command": ["/usr/bin/python3", "-m", "http.server", "8080"],
                "readinessProbe": {"httpGet": {"port": 8080, "path": "/"}},
            }],
        },
    })
    run(*kubectl, "wait", f"pod/{name}", "--for=condition=Ready", "--timeout=180s")
    return ipaddress.ip_address(run(*kubectl, "get", f"pod/{name}", "-o", "jsonpath={.status.podIP}"))


def probe(kubectl, source, address, port):
    run(*kubectl, "exec", source, "--", "/usr/bin/python3", "-c",
        "import sys,urllib.request; urllib.request.urlopen(sys.argv[1],timeout=8).read()",
        f"http://{address}:{port}/", timeout=30)


def qualify(kubectl, chart, flannel):
    run(*kubectl, "apply", "-f", str(flannel))
    run(*kubectl, "-n", "kube-flannel", "rollout", "status", "ds/kube-flannel-ds", "--timeout=180s")
    run(*kubectl, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=180s")
    flannel_ip = endpoint(kubectl, "legacy", CONTROL)
    worker_ip = endpoint(kubectl, "worker", WORKER)
    probe(kubectl, "legacy", worker_ip, 8080)

    # Kind supplies neither mount. The Talos values use mounts supplied by Talos.
    rendered = run("helm", "template", "cilium", str(chart), "-n", "kube-system",
                   "--kube-version", "1.34.0", "-f",
                   str(ROOT / "clusters/homelab/platform/cilium/values-migration.yaml"),
                   "--set", "bpf.autoMount.enabled=true", "--set", "cgroup.autoMount.enabled=true")
    run(*kubectl, "apply", "-f", "-", input=rendered)
    run(*kubectl, "-n", "kube-system", "rollout", "status", "ds/cilium", "--timeout=240s")
    run(*kubectl, "wait", "--for=condition=Established", "crd/ciliumnodeconfigs.cilium.io", "--timeout=30s")
    apply(kubectl, {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumNodeConfig",
        "metadata": {"name": "migration-worker", "namespace": "kube-system"},
        "spec": {
            "nodeSelector": {"matchLabels": {SELECTOR: "true"}},
            "defaults": {
                "write-cni-conf-when-ready": "/host/etc/cni/net.d/05-cilium.conflist",
                "custom-cni-conf": "false",
                "cni-chaining-mode": "none",
                "cni-exclusive": "false",
            },
        },
    })
    run(*kubectl, "delete", "pod/worker", "--wait=true", "--timeout=90s")
    run(*kubectl, "label", "node", WORKER, SELECTOR + "=true")
    run(*kubectl, "-n", "kube-system", "delete", "pod", "-l", "k8s-app=cilium",
        "--field-selector", "spec.nodeName=" + WORKER, "--wait=true", "--timeout=90s")
    deadline = time.monotonic() + 180
    while subprocess.run(("docker", "exec", WORKER, "test", "-s", "/etc/cni/net.d/05-cilium.conflist"),
                         timeout=10).returncode != 0:
        if time.monotonic() >= deadline:
            raise RuntimeError("Cilium never installed the worker CNI configuration")
        time.sleep(2)
    run("docker", "restart", WORKER, timeout=120)
    run(*kubectl, "wait", "--for=condition=Ready", "node/" + WORKER, "--timeout=180s")
    run(*kubectl, "-n", "kube-system", "rollout", "status", "ds/cilium", "--timeout=240s")
    cilium_ip = endpoint(kubectl, "migrated", WORKER)
    if flannel_ip not in ipaddress.ip_network("10.244.0.0/16") or cilium_ip not in ipaddress.ip_network("10.245.0.0/16"):
        raise AssertionError(f"Expected one pod on each overlay, found {flannel_ip} and {cilium_ip}")
    run(*kubectl, "get", "ciliumendpoint/migrated")
    run(*kubectl, "expose", "pod/legacy", "--port=80", "--target-port=8080")
    probe(kubectl, "legacy", cilium_ip, 8080)
    probe(kubectl, "migrated", flannel_ip, 8080)
    probe(kubectl, "migrated", "legacy.default.svc.cluster.local", 80)
    print("Passed bidirectional mixed-overlay pod traffic and DNS-backed Service access", flush=True)


def main():
    if CLUSTER in run("kind", "get", "clusters").splitlines():
        raise RuntimeError("Refusing to reuse an existing Kind cluster")
    with tempfile.TemporaryDirectory(prefix=CLUSTER + "-") as directory:
        path = Path(directory)
        config, kubeconfig = path / "kind.json", path / "kubeconfig"
        flannel, chart = path / "flannel.yaml", path / "cilium.tgz"
        download(FLANNEL, flannel, "2242ee218f3c3e724e4efe5f31826a3e38cfdabf334de41aee2b12b48fd4818d")
        download(CHART, chart, "0c7592eb75179ecf46dd3ec22145916f0164c4401214ea15afb5b230b1d11a21")
        config.write_text(json.dumps({
            "kind": "Cluster",
            "apiVersion": "kind.x-k8s.io/v1alpha4",
            "networking": {"disableDefaultCNI": True, "podSubnet": "10.244.0.0/16"},
            "nodes": [{"role": "control-plane"}, {"role": "worker"}],
        }))
        kubectl = ("kubectl", "--kubeconfig", str(kubeconfig), "--context", "kind-" + CLUSTER,
                   "--request-timeout=300s")
        try:
            run("kind", "create", "cluster", "--name", CLUSTER, "--config", str(config),
                "--image", NODE, "--kubeconfig", str(kubeconfig), timeout=420)
            qualify(kubectl, chart, flannel)
        except Exception:
            if kubeconfig.exists():
                for args in (("get", "pods", "-A", "-o", "wide"), ("get", "events", "-A")):
                    result = subprocess.run((*kubectl, *args), capture_output=True, text=True, timeout=30)
                    print(result.stdout or result.stderr, flush=True)
            raise
        finally:
            run("kind", "delete", "cluster", "--name", CLUSTER, "--kubeconfig", str(kubeconfig))


if __name__ == "__main__":
    main()
