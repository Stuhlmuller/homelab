#!/usr/bin/env python3
"""Exercise mixed Flannel and Cilium pod routing in a disposable Kind cluster."""

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import tarfile
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


def endpoint(kubectl, name, node, attachment=False, ports=(8080,)):
    metadata = {"name": name, "labels": {"fixture": name}}
    if attachment:
        metadata["annotations"] = {"k8s.v1.cni.cncf.io/networks": "secondary"}
    apply(kubectl, {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": metadata,
        "spec": {
            "nodeName": node,
            "automountServiceAccountToken": False,
            "containers": [{
                "name": f"http-{port}",
                "image": PYTHON,
                "command": ["/usr/bin/python3", "-m", "http.server", str(port)],
                "readinessProbe": {"httpGet": {"port": port, "path": "/"}},
            } for port in ports],
        },
    })
    run(*kubectl, "wait", f"pod/{name}", "--for=condition=Ready", "--timeout=180s")
    pod = json.loads(run(*kubectl, "get", f"pod/{name}", "-o", "json"))
    if attachment:
        networks = json.loads(pod["metadata"]["annotations"]["k8s.v1.cni.cncf.io/network-status"])
        secondary = [entry for entry in networks if entry["name"] == "default/secondary"]
        if len(secondary) != 1 or secondary[0].get("default") or not secondary[0].get("ips"):
            raise AssertionError(f"{name} has no non-default Multus attachment")
        run(*kubectl, "exec", name, "--", "/usr/bin/python3", "-c",
            "import socket,sys; assert sys.argv[1] in dict(socket.if_nameindex()).values()",
            secondary[0]["interface"])
    return ipaddress.ip_address(pod["status"]["podIP"])


def probe(kubectl, source, address, port):
    run(*kubectl, "exec", source, "--", "/usr/bin/python3", "-c",
        "import sys,urllib.request; urllib.request.urlopen(sys.argv[1],timeout=8).read()",
        f"http://{address}:{port}/", timeout=30)


def install_cilium(kubectl, chart, *settings):
    # Kind needs the mounting init containers that Talos supplies at boot.
    rendered = run("helm", "template", "cilium", str(chart), "-n", "kube-system",
                   "--kube-version", "1.34.0", "-f",
                   str(ROOT / "clusters/homelab/platform/cilium/values-migration.yaml"),
                   "--set", "bpf.autoMount.enabled=true", "--set", "cgroup.autoMount.enabled=true",
                   *settings)
    run(*kubectl, "apply", "-f", "-", input=rendered)
    run(*kubectl, "-n", "kube-system", "rollout", "status", "ds/cilium", "--timeout=240s")


def install_flannel_plugins(directory):
    archive = directory / "cni-plugins.tgz"
    download(
        "https://github.com/containernetworking/plugins/releases/download/v1.8.0/cni-plugins-linux-amd64-v1.8.0.tgz",
        archive,
        "ab3bda535f9d90766cccc90d3dddb5482003dd744d7f22bcf98186bf8eea8be6",
    )
    with tarfile.open(archive) as plugins:
        for name in ("bridge", "host-local", "portmap"):
            path = directory / name
            with plugins.extractfile("./" + name) as source:
                path.write_bytes(source.read())
            path.chmod(0o755)
            for node in (CONTROL, WORKER):
                run("docker", "cp", str(path), f"{node}:/opt/cni/bin/{name}")


def install_multus(kubectl):
    manifest = (ROOT / "clusters/homelab/platform/multus/multus.yaml").read_text()
    manifest = manifest.replace(
        "harbor.stinkyboi.com/mirror/ghcr.io/k8snetworkplumbingwg/",
        "ghcr.io/k8snetworkplumbingwg/",
    )
    run(*kubectl, "apply", "-f", "-", input=manifest)
    run(*kubectl, "wait", "--for=condition=Established",
        "crd/network-attachment-definitions.k8s.cni.cncf.io", "--timeout=60s")
    run(*kubectl, "-n", "kube-system", "rollout", "status", "ds/kube-multus-ds", "--timeout=180s")
    apply(kubectl, {
        "apiVersion": "k8s.cni.cncf.io/v1",
        "kind": "NetworkAttachmentDefinition",
        "metadata": {"name": "secondary", "namespace": "default"},
        "spec": {"config": json.dumps({
            "cniVersion": "0.3.1",
            "type": "bridge",
            "name": "secondary",
            "bridge": "fixture-net1",
            "ipam": {"type": "host-local", "subnet": "192.0.2.0/24"},
        })},
    })


def wait_for_multus_default(node):
    # Containerd reloads CNI independently of the DaemonSet readiness check.
    # The first fixture needs the Multus shim before its Pod starts.
    deadline = time.monotonic() + 45
    while True:
        runtime = json.loads(run("docker", "exec", node, "crictl", "info", timeout=5))
        networks = runtime.get("cniconfig", {}).get("Networks") or []
        for network in networks:
            if network["IFName"] == "eth0" and any(
                plugin["Network"]["type"] == "multus-shim" for plugin in network["Config"]["Plugins"]
            ):
                return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{node} did not load Multus as its default CNI")
        time.sleep(1)


def qualify(kubectl, chart, flannel):
    run(*kubectl, "apply", "-f", str(flannel))
    run(*kubectl, "-n", "kube-flannel", "rollout", "status", "ds/kube-flannel-ds", "--timeout=180s")
    run(*kubectl, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=180s")
    flannel_ip = endpoint(kubectl, "legacy", CONTROL)
    install_multus(kubectl)
    wait_for_multus_default(WORKER)
    worker_ip = endpoint(kubectl, "worker", WORKER, attachment=True)
    probe(kubectl, "legacy", worker_ip, 8080)

    install_cilium(kubectl, chart)
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
    cilium_ip = endpoint(kubectl, "migrated", WORKER, attachment=True)
    if flannel_ip not in ipaddress.ip_network("10.244.0.0/16") or cilium_ip not in ipaddress.ip_network("10.245.0.0/16"):
        raise AssertionError(f"Expected one pod on each overlay, found {flannel_ip} and {cilium_ip}")
    run(*kubectl, "get", "ciliumendpoint/migrated")
    run(*kubectl, "expose", "pod/legacy", "--port=80", "--target-port=8080")
    probe(kubectl, "legacy", cilium_ip, 8080)
    probe(kubectl, "migrated", flannel_ip, 8080)
    probe(kubectl, "migrated", "legacy.default.svc.cluster.local", 80)
    print("Passed mixed-overlay pod traffic, DNS-backed Service access and Multus attachments", flush=True)

    run(*kubectl, "delete", "pod/migrated", "--wait=true", "--timeout=90s")
    run(*kubectl, "label", "node", WORKER, SELECTOR + "-")
    primary_config = "/etc/cni/net.d/05-cilium.conflist"
    payload = json.loads(run("docker", "exec", WORKER, "cat", primary_config))
    if not any(plugin.get("type") == "cilium-cni" for plugin in payload.get("plugins", [])):
        raise AssertionError("Rollback refused to move an unexpected CNI file")
    run("docker", "exec", WORKER, "mv", primary_config, "/var/tmp/05-cilium.cutover-backup")
    run("docker", "restart", WORKER, timeout=120)
    run(*kubectl, "wait", "--for=condition=Ready", "node/" + WORKER, "--timeout=180s")
    run(*kubectl, "-n", "kube-system", "rollout", "status", "ds/kube-multus-ds", "--timeout=180s")
    run(*kubectl, "-n", "kube-flannel", "rollout", "status", "ds/kube-flannel-ds", "--timeout=180s")
    # CoreDNS may have been recreated on the trial overlay during the worker
    # restart. Reattach those DNS endpoints to the restored primary network.
    run(*kubectl, "-n", "kube-system", "rollout", "restart", "deployment/coredns")
    run(*kubectl, "-n", "kube-system", "rollout", "status", "deployment/coredns", "--timeout=180s")
    dns = json.loads(run(*kubectl, "-n", "kube-system", "get", "pods", "-l", "k8s-app=kube-dns", "-o", "json"))
    addresses = [pod["status"]["podIP"] for pod in dns["items"] if not pod["metadata"].get("deletionTimestamp")]
    flannel_pool = ipaddress.ip_network("10.244.0.0/16")
    if not addresses or any(ipaddress.ip_address(address) not in flannel_pool for address in addresses):
        raise AssertionError("CoreDNS endpoints did not return to Flannel after rollback")
    restored = endpoint(kubectl, "restored", WORKER, attachment=True)
    if restored not in flannel_pool:
        raise AssertionError(f"Restored Pod did not receive a Flannel address: {restored}")
    probe(kubectl, "legacy", restored, 8080)
    probe(kubectl, "restored", flannel_ip, 8080)
    probe(kubectl, "restored", "legacy.default.svc.cluster.local", 80)
    print("Passed rollback to Flannel with Multus and restored connectivity", flush=True)


def qualify_egress(kubectl, chart):
    install_cilium(kubectl, chart, "--set", "cni.customConf=false",
                   "--set", "policyEnforcementMode=default")
    run(*kubectl, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=180s")
    endpoint(kubectl, "source", WORKER)
    allowed = endpoint(kubectl, "allowed", CONTROL, ports=(8080, 8081))
    blocked = endpoint(kubectl, "blocked", CONTROL)
    for target in (allowed, blocked):
        probe(kubectl, "source", target, 8080)
    probe(kubectl, "source", allowed, 8081)

    policy_path = ROOT / "clusters/homelab/platform/cilium/egress-default-deny.yaml"
    baseline = json.loads(run("yq", "-o=json", ".", str(policy_path)))
    if baseline["spec"]["endpointSelector"] != {}:
        raise AssertionError("Expected a cluster-wide workload selector")
    # Limit the test to the fixture client so DNS and system pods keep working.
    baseline["spec"]["endpointSelector"] = {"matchLabels": {"fixture": "source"}}
    apply(kubectl, baseline)

    def wait_for_denial(address, port=8080):
        deadline = time.monotonic() + 60
        while True:
            result = subprocess.run((*kubectl, "exec", "source", "--", "/usr/bin/python3", "-c",
                                     "import socket,sys\n"
                                     "try: socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=2).close()\n"
                                     "except TimeoutError: sys.exit(7)",
                                     str(address), str(port)), capture_output=True, text=True, timeout=15)
            if result.returncode == 7:
                return
            if result.returncode or time.monotonic() >= deadline:
                raise RuntimeError(f"Egress denial not observed for {address}:{port}: {result.stderr}")
            time.sleep(1)

    for target in (allowed, blocked):
        wait_for_denial(target)
    apply(kubectl, {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumNetworkPolicy",
        "metadata": {"name": "fixture-allowed"},
        "spec": {
            "endpointSelector": {"matchLabels": {"fixture": "source"}},
            "egress": [{"toEndpoints": [{"matchLabels": {"fixture": "allowed"}}],
                        "toPorts": [{"ports": [{"port": "8080", "protocol": "TCP"}]}]}],
        },
    })
    deadline = time.monotonic() + 60
    while True:
        try:
            probe(kubectl, "source", allowed, 8080)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    wait_for_denial(blocked)
    wait_for_denial(allowed, 8081)
    print("Passed Cilium default deny, destination and port allowlisting", flush=True)


def report_cilium_working_set():
    required = {(node, name) for node in (CONTROL, WORKER)
                for name in ("cilium-agent", "cilium-envoy")}
    recorded = set()
    deadline = time.monotonic() + 30
    while required - recorded and time.monotonic() < deadline:
        for node in (CONTROL, WORKER):
            sample = json.loads(run("docker", "exec", node, "crictl", "stats", "-o", "json"))
            for entry in sample["stats"]:
                attributes = entry["attributes"]
                name = attributes["metadata"]["name"]
                pod = attributes.get("labels", {}).get("io.kubernetes.pod.name", "")
                key = node, name
                if not pod.startswith("cilium-") or key not in required or key in recorded:
                    continue
                memory = entry.get("memory") or {}
                size = (memory.get("workingSetBytes") or {}).get("value")
                if size is not None:
                    print(f"{node} {pod} {name}: {int(size) // (1024 * 1024)} MiB working set",
                          flush=True)
                    recorded.add(key)
        if required - recorded:
            time.sleep(2)
    for node, name in sorted(required - recorded):
        print(f"{node} {name}: working-set sample unavailable", flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--egress", action="store_true", help="test native Cilium default-deny policy")
    args = parser.parse_args()
    if CLUSTER in run("kind", "get", "clusters").splitlines():
        raise RuntimeError("Refusing to reuse an existing Kind cluster")
    with tempfile.TemporaryDirectory(prefix=CLUSTER + "-") as directory:
        path = Path(directory)
        config, kubeconfig = path / "kind.json", path / "kubeconfig"
        flannel, chart = path / "flannel.yaml", path / "cilium.tgz"
        if not args.egress:
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
            if args.egress:
                qualify_egress(kubectl, chart)
            else:
                install_flannel_plugins(path)
                qualify(kubectl, chart, flannel)
            report_cilium_working_set()
        except Exception:
            if kubeconfig.exists():
                for args in (
                    ("get", "pods", "-A", "-o", "wide"),
                    ("get", "events", "-A"),
                    ("-n", "kube-flannel", "logs", "-l", "app=flannel",
                     "-c", "kube-flannel", "--prefix", "--tail=80"),
                    ("-n", "kube-system", "logs", "-l", "name=multus",
                     "-c", "kube-multus", "--prefix", "--tail=80"),
                    ("-n", "kube-system", "logs", "-l", "k8s-app=cilium",
                     "-c", "cilium-agent", "--prefix", "--tail=80"),
                ):
                    result = subprocess.run((*kubectl, *args), capture_output=True, text=True, timeout=30)
                    print(result.stdout or result.stderr, flush=True)
            raise
        finally:
            run("kind", "delete", "cluster", "--name", CLUSTER, "--kubeconfig", str(kubeconfig))


if __name__ == "__main__":
    main()
