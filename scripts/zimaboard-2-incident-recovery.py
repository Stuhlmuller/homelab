#!/usr/bin/env python3
"""One-shot recovery for the 2026-11-02 zimaboard-2 incident; never a general reboot tool."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import pwd
import runpy
import subprocess
import socket
import stat
import tempfile
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
BACKUP = runpy.run_path(str(ROOT / "scripts/talos-etcd-backup.py"))
CAPACITY = runpy.run_path(str(ROOT / "scripts/network-policy-candidate-report.py"))
GITOPS = runpy.run_path(str(ROOT / "scripts/verify-gitops.py"))
INCIDENT = "zimaboard-2-2026-11-02"
NODE = "zimaboard-2"
ADDRESS = "10.1.0.202"
NODE_UID = "30e383bf-7a29-436e-b02c-e2b9687f2cb5"
BOOT = "5644f3a6-2785-42d8-ac4d-8c0f7f9b3891"
PEERS = {"acer": "10.1.0.199", "zimaboard-0": "10.1.0.200", "zimaboard-1": "10.1.0.201"}
GIB = 1024 ** 3
SHA = re.compile(r"[0-9a-f]{40}\Z")
ATTEMPT = INCIDENT + ".attempt.json"
COMPLETE = INCIDENT + ".complete.json"
# Exact platform ownership/path contracts; root access is limited to Multus.
DAEMONS = {
    ("istio-system", "istio-cni-node"): {"/opt/cni/bin", "/proc", "/var/run/ztunnel", "/etc/cni/net.d", "/var/run/istio-cni", "/var/run/netns"},
    ("istio-system", "ztunnel"): {"/var/run/ztunnel"},
    ("kube-system", "kube-flannel"): {"/run/flannel", "/opt/cni/bin", "/etc/cni/net.d"},
    ("kube-system", "kube-multus-ds"): {"/", "/run", "/etc/cni/net.d", "/opt/cni/bin", "/var/lib/cni/multus", "/var/lib/kubelet", "/run/k8s.cni.cncf.io", "/run/netns", "/etc/cni/multus/net.d"},
    ("kube-system", "kube-proxy"): {"/usr/lib/modules", "/etc/ssl/certs"},
}
# Exact observed propagation contracts; unknown container/path/mode combinations fail.
PROPAGATION = {
    ("istio-system", "istio-cni-node", "containers", "install-cni", "/var/run/netns", "/host/var/run/netns", "HostToContainer"),
    ("kube-system", "kube-multus-ds", "containers", "kube-multus", "/var/lib/kubelet", "/var/lib/kubelet", "HostToContainer"),
    ("kube-system", "kube-multus-ds", "containers", "kube-multus", "/run/netns", "/var/run/netns", "HostToContainer"),
    ("kube-system", "kube-multus-ds", "containers", "kube-multus", "/", "/hostroot", "HostToContainer"),
    ("kube-system", "kube-multus-ds", "initContainers", "install-multus-binary", "/opt/cni/bin", "/host/opt/cni/bin", "Bidirectional"),
}
DEPLOYMENTS = {("ai", "litellm"), ("cert-manager", "cert-manager-cainjector"),
               ("cert-manager", "cert-manager-webhook"), ("harbor", "harbor-exporter"),
               ("harbor", "harbor-vulnerability-exporter"), ("kube-system", "coredns"),
               ("kube-system", "metrics-server"), ("tailnet-dns", "tailnet-dns-k8s-gateway"),
               ("tailscale", "operator")}
TAILSCALE_IMAGE = "harbor.stinkyboi.com/mirror/docker.io/tailscale/tailscale@sha256:8c42c4574ab066384fcb72f69e086a2ff1dd3652eb6f56856cee34bcf0d2f680"


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def age(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, "timestamp_timezone_missing")
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def fresh(value, maximum):
    require(0 <= age(value) <= maximum, "stale_or_future_evidence")


def condition(obj, name):
    entries = [entry for entry in obj.get("status", {}).get("conditions", []) if entry.get("type") == name]
    require(len(entries) == 1, "ambiguous_condition")
    return entries[0]


def controller(obj):
    owners = [item for item in obj["metadata"].get("ownerReferences", []) if item.get("controller") is True]
    require(len(owners) == 1 and owners[0].get("uid"), "ambiguous_controller")
    return owners[0]


def listing(obj):
    require(isinstance(obj.get("items"), list) and not obj.get("metadata", {}).get("continue"), "incomplete_inventory")
    return obj["items"]


def streams(text):
    decoder, result = json.JSONDecoder(), []
    while text.strip():
        item, length = decoder.raw_decode(text.lstrip())
        result.append(item)
        text = text.lstrip()[length:]
    return result


def executable_hash(path):
    require(path.is_file() and os.access(path, os.X_OK), "talos_client_not_executable")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def talos_client(path, run):
    # Reuse the backup helper's explicit absolute/executable client contract.
    require(path.is_absolute(), "absolute_talos_client_required")
    path = path.resolve(strict=True)
    fingerprint = executable_hash(path)
    output = run([str(path), "version", "--client"])
    versions = re.findall(r"(?m)^\s*Tag:\s*(\S+)\s*$", output)
    require(versions == ["v1.11.3"], "matched_talos_v1_11_3_client_required")
    require(executable_hash(path) == fingerprint, "talos_client_changed_during_validation")
    return {"path": str(path), "version": versions[0], "sha256": fingerprint}


class Reader:
    def __init__(self, args):
        self.args = args
        self.env = {key: value for key, value in os.environ.items()
                    if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
        self.client = talos_client(args.talosctl, self.run)
        self.kube = ["kubectl", "--kubeconfig", str(args.kubeconfig), "--context", args.context,
                     "--request-timeout=15s"]
        config = json.loads(self.run(self.kube + ["config", "view", "--minify", "-o", "json"]))
        validate_kubeconfig(config, args.context)

    def run(self, command, timeout=25):
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout, env=self.env)
        require(len(result.stdout) <= 16 * 1024 * 1024, "response_too_large")
        return result.stdout

    def get(self, namespace, kind, *arguments):
        return json.loads(self.run(self.kube + (["-n", namespace] if namespace else []) +
                                  ["get", kind, *arguments, "-o", "json"]))

    def client_matches(self):
        require(executable_hash(Path(self.client["path"])) == self.client["sha256"], "approved_talos_client_changed")

    def talos(self, address, *arguments, timeout=25):
        self.client_matches()
        return self.run([self.client["path"], "--talosconfig", str(self.args.talosconfig), "--endpoints", address,
                         "--nodes", address, *arguments], timeout)

    def secret_uid(self, name):
        # kubectl jsonpath filters a full Secret locally. Use metadata content
        # negotiation through the native client's private Unix-socket proxy.
        require(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name), "invalid_identity_name")
        path = "/api/v1/namespaces/tailscale/secrets/" + name
        with tempfile.TemporaryDirectory(prefix="incident-metadata-") as directory:
            endpoint = Path(directory) / "api.sock"
            command = self.kube + ["proxy", "--unix-socket", str(endpoint), "--accept-hosts=^localhost$",
                                   "--accept-paths=^" + re.escape(path) + "$",
                                   "--reject-methods=^(POST|PUT|PATCH|DELETE|CONNECT|TRACE|OPTIONS|HEAD)$"]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env)
            connection = None
            try:
                deadline = time.monotonic() + 5
                while not endpoint.exists():
                    require(process.poll() is None and time.monotonic() < deadline, "metadata_proxy_unavailable")
                    time.sleep(0.02)
                info = endpoint.lstat()
                require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), "unsafe_metadata_socket")
                endpoint.chmod(0o600)
                connection = http.client.HTTPConnection("localhost", timeout=15)
                connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.sock.settimeout(15)
                connection.sock.connect(str(endpoint))
                connection.request("GET", path, headers={
                    "Accept": "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"})
                response = connection.getresponse()
                require(response.status == 200, "identity_metadata_unavailable")
                payload = response.read(1048577)
                require(len(payload) <= 1048576, "identity_metadata_too_large")
                value = json.loads(payload)
                require(value.get("kind") == "PartialObjectMetadata" and value.get("apiVersion") == "meta.k8s.io/v1"
                        and set(value) <= {"kind", "apiVersion", "metadata"}, "full_secret_response_rejected")
                meta = value["metadata"]
                require(meta.get("name") == name and meta.get("namespace") == "tailscale"
                        and re.fullmatch(r"[0-9a-f-]{36}", meta.get("uid", ""))
                        and not meta.get("deletionTimestamp"), "identity_secret_missing_or_deleting")
                return meta["uid"]
            finally:
                if connection is not None:
                    connection.close()
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def validate_kubeconfig(config, context):
    """Inspect redacted client configuration before any authenticated request."""
    require(config.get("current-context") == context and len(config.get("contexts", [])) == 1
            and len(config.get("clusters", [])) == 1 and len(config.get("users", [])) == 1,
            "ambiguous_client_config")
    selected = config["contexts"][0]
    cluster, user = config["clusters"][0], config["users"][0]
    require(selected["name"] == context and selected["context"].get("cluster") == cluster["name"]
            and selected["context"].get("user") == user["name"], "client_reference_mismatch")
    connection, auth = cluster["cluster"], user["user"]
    require(set(connection) <= {"server", "certificate-authority-data", "disable-compression"}
            and connection.get("server") == "https://10.1.0.199:6443"
            and bool(connection.get("certificate-authority-data")), "direct_trusted_endpoint_required")
    require(set(auth) in ({"client-certificate-data", "client-key-data"}, {"token"})
            and all(auth.values()), "embedded_nonexec_credentials_required")


def source_guard(args):
    require(SHA.fullmatch(args.reviewed_sha or ""), "reviewed_main_revision_missing")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(actual == args.reviewed_sha, "reviewed_revision_mismatch")
    main = subprocess.check_output(["git", "rev-parse", "refs/remotes/origin/main"], cwd=ROOT, text=True).strip()
    require(main == actual, "reviewed_main_tracking_revision_mismatch")
    require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT),
            "checkout_not_clean")
    for path in (args.kubeconfig, args.talosconfig):
        info = path.lstat()
        require(path.is_absolute() and not path.is_symlink() and path.is_file()
                and info.st_uid == os.getuid() and info.st_mode & 0o777 == 0o600, "private_config_required")


def replacement_uids(deployment, pods, read):
    namespace = deployment["metadata"]["namespace"]
    sets = listing(read.get(namespace, "replicasets"))
    owned = {item["metadata"]["uid"] for item in sets if any(ref.get("uid") == deployment["metadata"]["uid"]
             and ref.get("controller") is True for ref in item["metadata"].get("ownerReferences", []))}
    ready = sorted(item["metadata"]["uid"] for item in pods
                   if item["metadata"]["namespace"] == namespace
                   and item["spec"].get("nodeName") in PEERS
                   and not item["metadata"].get("deletionTimestamp")
                   and item["status"].get("phase") == "Running"
                   and any(ref.get("uid") in owned and ref.get("controller") is True
                           for ref in item["metadata"].get("ownerReferences", []))
                   and condition(item, "Ready")["status"] == "True")
    require(len(ready) >= max(1, deployment["spec"].get("replicas", 1)), "replacement_pods_unavailable")
    return ready


def classify_pod(pod, all_pods, read):
    """Classify every bound Pod, including deleting/terminal Pods and init mounts."""
    meta, spec = pod["metadata"], pod["spec"]
    namespace, owner = meta["namespace"], controller(pod)
    require(owner.get("kind") in {"DaemonSet", "ReplicaSet", "StatefulSet"}
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", owner.get("name", "")),
            "unclassified_controller_reference")
    if owner["kind"] == "StatefulSet":
        require(namespace == "tailscale" and owner["name"] == "ts-bulldozer-hook-tccs6", "unclassified_stateful_owner")
    control = read.get(namespace, owner["kind"], owner["name"])
    require(control["metadata"]["uid"] == owner["uid"] and not control["metadata"].get("deletionTimestamp"),
            "controller_changed")
    category, allowed_paths, identity_uid, replacements = None, set(), None, []
    if owner["kind"] == "DaemonSet":
        require((namespace, owner["name"]) in DAEMONS, "unclassified_daemon")
        category, allowed_paths = "platform-daemon", DAEMONS[(namespace, owner["name"])]
    elif owner["kind"] == "ReplicaSet":
        parent = controller(control)
        require(parent["kind"] == "Deployment" and (namespace, parent["name"]) in DEPLOYMENTS
                and bool(meta.get("deletionTimestamp")), "unclassified_application_writer")
        deployment = read.get(namespace, "deployment", parent["name"])
        require(deployment["metadata"]["uid"] == parent["uid"]
                and deployment["status"].get("observedGeneration") == deployment["metadata"]["generation"]
                and not deployment["metadata"].get("deletionTimestamp")
                and deployment["status"].get("availableReplicas", 0) >= max(1, deployment["spec"].get("replicas", 1)),
                "replacement_unavailable")
        replacements = replacement_uids(deployment, all_pods, read)
        category = "terminating-replaced-deployment"
    elif owner["kind"] == "StatefulSet":
        # Tailscale v1.102.3 sts.go uses TS_KUBE_SECRET=$(POD_NAME): one ordinal,
        # same retained identity Secret. No scaling, deletion or reauthentication.
        labels = control["metadata"].get("labels", {})
        expected = {"tailscale.com/managed": "true", "tailscale.com/parent-resource": "bulldozer-hook",
                    "tailscale.com/parent-resource-ns": "traefik", "tailscale.com/parent-resource-type": "ingress"}
        require(namespace == "tailscale" and all(labels.get(k) == v for k, v in expected.items())
                and all(meta.get("labels", {}).get(k) == v for k, v in expected.items())
                and control["spec"].get("replicas") == 1
                and control["spec"].get("podManagementPolicy") == "OrderedReady"
                and control["status"].get("observedGeneration") == control["metadata"]["generation"]
                and bool(control["status"].get("currentRevision"))
                and control["status"].get("currentRevision") == control["status"].get("updateRevision")
                and control["spec"].get("updateStrategy", {}).get("type") == "RollingUpdate"
                and control["spec"].get("updateStrategy", {}).get("rollingUpdate", {}).get("partition", 0) == 0
                and meta["name"] == owner["name"] + "-0" and bool(meta.get("deletionTimestamp")),
                "stateful_identity_unclassified")
        siblings = [item for item in all_pods if any(ref.get("uid") == owner["uid"]
                    for ref in item["metadata"].get("ownerReferences", []))]
        require(len(siblings) == 1 and siblings[0]["metadata"]["uid"] == meta["uid"], "second_identity_writer")
        for candidate in (spec, control["spec"]["template"]["spec"]):
            containers = candidate.get("containers", [])
            require(len(containers) == 1 and not candidate.get("initContainers")
                    and containers[0]["image"] == TAILSCALE_IMAGE
                    and not containers[0].get("command") and not containers[0].get("args"),
                    "tailscale_identity_contract_changed")
            env = containers[0].get("env", [])
            pod_names = [i for i, item in enumerate(env) if item.get("name") == "POD_NAME"]
            secrets = [i for i, item in enumerate(env) if item.get("name") == "TS_KUBE_SECRET"]
            require(len(pod_names) == len(secrets) == 1 and pod_names[0] < secrets[0]
                    and env[pod_names[0]] == {"name": "POD_NAME", "valueFrom": {
                        "fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.name"}}}
                    and env[secrets[0]] == {"name": "TS_KUBE_SECRET", "value": "$(POD_NAME)"},
                    "tailscale_identity_expansion_changed")
        for other in all_pods:
            if other["metadata"]["namespace"] != namespace or other["metadata"]["uid"] == meta["uid"]:
                continue
            require(not all(other["metadata"].get("labels", {}).get(k) == v for k, v in expected.items()),
                    "second_identity_parent")
            for item in [*other["spec"].get("containers", []), *other["spec"].get("initContainers", []),
                         *other["spec"].get("ephemeralContainers", [])]:
                require(not any(env.get("name") == "TS_KUBE_SECRET" and env.get("value") == meta["name"]
                                for env in item.get("env", [])), "second_identity_secret_writer")
        parent = read.get("traefik", "ingress", "bulldozer-hook")
        require(not parent["metadata"].get("deletionTimestamp"), "tailscale_parent_deleting")
        identity_uid = read.secret_uid(meta["name"])
        category = "single-tailscale-identity"
    require(category is not None, "unclassified_writer")
    volumes = {item["name"]: item for item in spec.get("volumes", [])}
    require(len(volumes) == len(spec.get("volumes", [])), "duplicate_volume")
    for volume in volumes.values():
        kinds = set(volume) - {"name"}
        require(len(kinds) == 1 and kinds <= {"secret", "configMap", "projected", "emptyDir", "hostPath"},
                "persistent_or_unclassified_volume")
        if "hostPath" in volume:
            require(volume["hostPath"].get("path") in allowed_paths, "unclassified_hostpath")
    require(not spec.get("ephemeralContainers"), "ephemeral_writer_requires_review")
    require(bool(spec.get("containers")), "containers_missing")
    for container_class in ("containers", "initContainers"):
        for container in spec.get(container_class, []):
            require(not container.get("volumeDevices"), "block_device_writer")
            for mount in container.get("volumeMounts", []):
                require(mount.get("name") in volumes, "unclassified_mount")
                path = volumes[mount["name"]].get("hostPath", {}).get("path")
                if path in {"/proc", "/usr/lib/modules", "/etc/ssl/certs"}:
                    require(mount.get("readOnly") is True, "readonly_hostpath_changed")
                propagation = mount.get("mountPropagation", "None")
                require(propagation == "None" or
                        (namespace, owner["name"], container_class, container["name"], path,
                         mount.get("mountPath"), propagation) in PROPAGATION, "unclassified_propagation")
    return {"uid": meta["uid"], "namespace": namespace, "name": meta["name"], "class": category,
            "owner_uid": owner["uid"], "pod_spec_sha256": digest(spec),
            "controller_spec_sha256": digest(control["spec"]), "identity_secret_uid": identity_uid,
            "replacement_pod_uids": replacements}


def service_health(resources, names):
    services = {item["metadata"]["id"]: item["spec"] for item in resources}
    require(all(name in services and services[name].get("running") is True
                and services[name].get("healthy") is True and services[name].get("unknown") is False
                for name in names), "talos_services_unhealthy")


def capacity_inventory(pods):
    return sorted([{"uid": pod["metadata"]["uid"], "namespace": pod["metadata"]["namespace"],
                    "owners": pod["metadata"].get("ownerReferences", []),
                    "deleting": pod["metadata"].get("deletionTimestamp"),
                    "memory_request": CAPACITY["pod_memory_request"](pod)} for pod in pods
                   if pod["spec"].get("nodeName") == "acer"
                   and pod["status"].get("phase") not in ("Succeeded", "Failed")], key=lambda item: item["uid"])


def recurring_reservation(read, bound_pods, acer):
    """Conservatively budget all unsuspended Acer-eligible recurring templates."""
    cron = read.get("automation", "cronjob", "renovate")
    declared = json.loads(read.run(["yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/renovate/cronjob.yaml")]))
    for obj in (cron, declared):
        require(obj["spec"].get("suspend") is False and obj["spec"].get("schedule") == "0 * * * *"
                and obj["spec"].get("concurrencyPolicy") == "Forbid"
                and obj["spec"]["jobTemplate"]["spec"]["template"]["spec"].get("nodeSelector") == {"kubernetes.io/hostname": "acer"}
                and CAPACITY["pod_memory_request"](obj["spec"]["jobTemplate"]["spec"]["template"]) == 512 * 1024 ** 2,
                "recurring_workload_contract_changed")
    jobs = listing(read.get(None, "jobs", "-A", "--chunk-size=0"))
    crons = listing(read.get(None, "cronjobs", "-A", "--chunk-size=0"))
    require(sum(item["metadata"]["uid"] == cron["metadata"]["uid"] for item in crons) == 1,
            "recurring_inventory_incomplete")
    reserve = 0
    for item in crons:
        if item["spec"].get("suspend", False):
            continue
        job_spec = item["spec"]["jobTemplate"]["spec"]
        template = job_spec["template"]
        spec = template["spec"]
        if spec.get("nodeName") not in (None, "", "acer") or any(
                acer["metadata"].get("labels", {}).get(key) != value
                for key, value in spec.get("nodeSelector", {}).items()):
            continue
        # Ignoring affinity/taints/windows over-reserves rather than inventing
        # proof that backup jobs cannot overlap the gateway rollout.
        require(item["spec"].get("concurrencyPolicy") == "Forbid"
                and spec.get("schedulerName", "default-scheduler") == "default-scheduler",
                "unbounded_recurring_overlap")
        require(job_spec.get("parallelism", 1) == 1 and job_spec.get("completions", 1) == 1
                and job_spec.get("completionMode", "NonIndexed") == "NonIndexed",
                "parallel_recurring_job_unclassified")
        wanted = CAPACITY["pod_memory_request"](template)
        require(wanted > 0, "recurring_memory_request_missing")
        namespace, uid = item["metadata"]["namespace"], item["metadata"]["uid"]
        owned = {job["metadata"]["uid"] for job in jobs if job["metadata"]["namespace"] == namespace
                 and any(ref.get("uid") == uid and ref.get("controller") is True
                         for ref in job["metadata"].get("ownerReferences", []))}
        for job in jobs:
            if job["metadata"]["uid"] in owned and not job.get("status", {}).get("completionTime"):
                require(job["spec"].get("parallelism", 1) == 1 and job["spec"].get("completions", 1) == 1
                        and job["spec"].get("completionMode", "NonIndexed") == "NonIndexed",
                        "active_parallel_recurring_job_unclassified")
        present = sum(CAPACITY["pod_memory_request"](pod) for pod in bound_pods
                      if not pod["metadata"].get("deletionTimestamp")
                      and pod["metadata"]["namespace"] == namespace and
                      any(ref.get("uid") in owned and ref.get("controller") is True
                          for ref in pod["metadata"].get("ownerReferences", [])))
        reserve += max(0, wanted - present)
    return reserve


def inspect(args, read, *, recovered=False):
    """Collect fresh facts; failures become public blocker codes, never fabricated receipts."""
    started = time.monotonic()
    blockers, proof = [], {"incident": INCIDENT, "source_sha": args.reviewed_sha, "talos_client": read.client}
    def gate(name, action):
        try:
            value = action()
            proof[name] = value
            return value
        except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException, subprocess.SubprocessError):
            blockers.append(name + "_unverified")
            return None
    gate("api", lambda: require(read.run(read.kube + ["get", "--raw", "/readyz"]).strip() == "ok", "api_unhealthy"))
    nodes = gate("nodes", lambda: listing(read.get(None, "nodes")))
    pods = gate("pods", lambda: listing(read.get(None, "pods", "-A", "--chunk-size=0")))
    leases = gate("leases", lambda: listing(read.get("kube-node-lease", "leases")))
    # Raw Kubernetes objects stay in memory. Only selected identities/digests leave.
    for key in ("nodes", "pods", "leases"):
        proof.pop(key, None)
    def identity():
        indexed = {item["metadata"]["name"]: item for item in nodes}
        lease_map = {item["metadata"]["name"]: item for item in leases}
        target = indexed[NODE]
        require(target["metadata"]["uid"] == NODE_UID and not target["metadata"].get("deletionTimestamp")
                and any(item.get("address") == ADDRESS and item.get("type") == "InternalIP"
                        for item in target["status"]["addresses"])
                and "v1.11.3" in target["status"]["nodeInfo"]["osImage"]
                and "octelium.com/node-mode-dataplane" not in target["metadata"].get("labels", {}), "target_changed")
        boot = read.talos(ADDRESS, "read", "/proc/sys/kernel/random/boot_id").strip()
        require(boot == target["status"]["nodeInfo"]["bootID"] and (boot != BOOT if recovered else boot == BOOT), "boot_changed")
        require(condition(target, "Ready")["status"] == ("True" if recovered else "Unknown"), "target_state_changed")
        if recovered:
            fresh(lease_map[NODE]["spec"]["renewTime"], 60)
        else:
            require(condition(target, "Ready").get("reason") == "NodeStatusUnknown"
                    and age(lease_map[NODE]["spec"]["renewTime"]) > 60
                    and any(taint.get("key") == "node.kubernetes.io/unreachable"
                            and taint.get("effect") == "NoSchedule" for taint in target["spec"].get("taints", [])), "incident_no_longer_matches")
        for name in PEERS:
            require(condition(indexed[name], "Ready")["status"] == "True", "peer_unready")
            require(condition(indexed[name], "MemoryPressure")["status"] == "False", "peer_memory_pressure")
            fresh(lease_map[name]["spec"]["renewTime"], 60)
        return {"node_uid": NODE_UID, "boot_id": boot, "peers": {name: indexed[name]["metadata"]["uid"] for name in PEERS}}
    if nodes is not None and leases is not None:
        gate("identity", identity)
    def talos_health():
        machine = streams(read.talos(ADDRESS, "get", "machinestatus", "-o", "json"))
        require(len(machine) == 1 and machine[0]["spec"].get("stage") == "running", "machine_sequence_in_progress")
        services = streams(read.talos(ADDRESS, "get", "services", "-o", "json"))
        service_health(services, ["apid", "machined", "containerd", "cri"] + (["kubelet"] if recovered else []))
        if not recovered:
            require(any(item["metadata"]["id"] == "kubelet" and item["spec"].get("healthy") is False
                        for item in services), "kubelet_no_longer_matches")
        for address in PEERS.values():
            service_health(streams(read.talos(address, "get", "services", "-o", "json")), ["apid", "machined", "containerd", "cri", "kubelet"])
        service_health(streams(read.talos("10.1.0.199", "get", "services", "-o", "json")), ["etcd"])
        return True
    gate("talos_health", talos_health)
    def critical_services():
        result = {}
        for namespace, name in (("kube-system", "coredns"), ("istio-system", "istiod"),
                                ("octelium", "emergency-octelium-admin-api"),
                                ("octelium", "emergency-octelium-auth-api"),
                                ("octelium", "emergency-octelium-ingress")):
            item = read.get(namespace, "deployment", name)
            require(not item["metadata"].get("deletionTimestamp")
                    and item["status"].get("observedGeneration") == item["metadata"]["generation"]
                    and item["status"].get("availableReplicas", 0) >= max(1, item["spec"].get("replicas", 1)),
                    "critical_service_unavailable")
            result[namespace + "/" + name] = {"deployment_uid": item["metadata"]["uid"],
                                                    "ready_pod_uids": replacement_uids(item, pods, read)}
        return result
    if pods is not None:
        gate("critical_services", critical_services)
    def prevention():
        application = read.get("argocd", "application", "litellm")
        GITOPS["application"](application, "litellm", args.reviewed_sha)
        deploy = read.get("ai", "deployment", "litellm")
        template = deploy["spec"]["template"]["spec"]
        require(deploy["spec"].get("replicas") == 1 and template.get("nodeSelector") == {"kubernetes.io/hostname": "acer"}
                and len(template["containers"]) == 1
                and template["containers"][0].get("resources", {}).get("requests", {}).get("memory") == "1Gi"
                and deploy["status"].get("observedGeneration") == deploy["metadata"]["generation"]
                and deploy["status"].get("availableReplicas", 0) == 1, "prevention_not_delivered")
        declared = json.loads(read.run(["yq", "-o=json", ".", str(ROOT / "clusters/homelab/apps/litellm/values.yaml")]))
        require(declared.get("nodeSelector") == template["nodeSelector"]
                and declared.get("resources", {}).get("requests", {}).get("memory") == "1Gi", "prevention_source_missing")
        sets = listing(read.get("ai", "replicasets"))
        owned = {item["metadata"]["uid"] for item in sets if any(ref.get("uid") == deploy["metadata"]["uid"]
                 for ref in item["metadata"].get("ownerReferences", []))}
        current = [item for item in sets if item["metadata"]["uid"] in owned
                   and item["spec"].get("replicas") == 1 and item["spec"]["template"]["spec"] == template]
        require(len(current) == 1, "current_replicaset_missing")
        ready = [pod for pod in pods if any(ref.get("uid") == current[0]["metadata"]["uid"]
                 for ref in pod["metadata"].get("ownerReferences", [])) and not pod["metadata"].get("deletionTimestamp")]
        require(len(ready) == 1 and ready[0]["spec"].get("nodeName") == "acer"
                and condition(ready[0], "Ready")["status"] == "True"
                and ready[0]["spec"].get("nodeSelector") == template["nodeSelector"]
                and len(ready[0]["spec"].get("containers", [])) == 1
                and ready[0]["spec"]["containers"][0]["image"] == template["containers"][0]["image"]
                and CAPACITY["pod_memory_request"](ready[0]) >= GIB, "gateway_replacement_unready")
        acer_gateway = [pod for pod in pods if pod["spec"].get("nodeName") == "acer"
                        and pod["status"].get("phase") not in ("Succeeded", "Failed")
                        and any(ref.get("uid") in owned for ref in pod["metadata"].get("ownerReferences", []))]
        require(len(acer_gateway) == 1 and acer_gateway[0]["metadata"]["uid"] == ready[0]["metadata"]["uid"],
                "additional_gateway_overlap_unreviewed")
        acer = next(node for node in nodes if node["metadata"]["name"] == "acer")
        other = [pod for pod in pods if pod["spec"].get("nodeName") == "acer"
                 and pod["status"]["phase"] not in ("Succeeded", "Failed")
                 and not any(ref.get("uid") in owned for ref in pod["metadata"].get("ownerReferences", []))]
        reserve = CAPACITY["memory_bytes"](acer["status"]["allocatable"]["memory"]) - sum(CAPACITY["pod_memory_request"](pod) for pod in other)
        recurring = recurring_reservation(read, other, acer)
        reserve -= recurring
        require(reserve >= 2 * GIB, "sustainable_overlap_capacity_missing")
        # MemAvailable includes reclaimable cache; require room for a complete
        # two-Pod gateway budget even while one gateway is already running.
        memory = read.talos("10.1.0.199", "read", "/proc/meminfo")
        available = re.findall(r"^MemAvailable:\s+(\d+) kB$", memory, re.MULTILINE)
        require(len(available) == 1 and int(available[0]) * 1024 >= 2 * GIB + recurring,
                "actual_memory_margin_missing")
        return {"deployment_uid": deploy["metadata"]["uid"], "replica_set_uid": current[0]["metadata"]["uid"],
                "pod_uid": ready[0]["metadata"]["uid"], "capacity_for_two_bytes": reserve, "recurring_reservation_bytes": recurring,
                "mem_available_bytes": int(available[0]) * 1024,
                "capacity_pods_sha256": digest(capacity_inventory(pods))}
    if nodes is not None and pods is not None:
        gate("prevention_and_capacity", prevention)
        if not recovered:
            gate("writers", lambda: sorted([classify_pod(pod, pods, read) for pod in pods
                 if pod["spec"].get("nodeName") == NODE], key=lambda item: item["uid"]))
        else:
            gate("placement", lambda: require(not any(pod["metadata"]["namespace"] == "ai"
                 and pod["spec"].get("nodeName") == NODE and pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "litellm"
                 and not pod["metadata"].get("deletionTimestamp") for pod in pods), "gateway_returned_to_worker"))
    def snapshot():
        require(args.snapshot_dir is not None, "fresh_snapshot_missing")
        record = BACKUP["verify"](args.snapshot_dir)
        fresh(record["created_at"], 6 * 60 * 60)
        require(record["source_node"] == "10.1.0.199", "wrong_snapshot_source")
        return {"sha256": record["integrity"]["sha256"], "created_at": record["created_at"]}
    if not recovered:
        gate("snapshot", snapshot)
    if time.monotonic() - started > 120:
        blockers.append("inspection_exceeded_freshness_window")
    proof["observed_at"] = datetime.now(timezone.utc).isoformat()
    proof["blockers"] = sorted(set(blockers))
    return proof


def receipt_directory(path):
    # A caller cannot choose another directory to reset the consumed attempt.
    # This is one operator-account registry, not a distributed lock.
    expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/homelab/incident-recovery"
    require(path == expected and not any(part.is_symlink() for part in (path, *path.parents)),
            "fixed_persistent_registry_required")
    return MAINTENANCE["private_directory"](path)


def execute(args, read, directory):
    plan = MAINTENANCE["read_private_json"](args.plan)
    require(plan.get("incident") == INCIDENT and plan.get("source_sha") == args.reviewed_sha
            and not plan.get("blockers") and args.approve_plan_sha256 == digest(plan), "explicit_plan_approval_required")
    fresh(plan["observed_at"], 300)
    attempt = directory / ATTEMPT
    require(not attempt.exists() and not attempt.is_symlink(), "attempt_already_consumed")
    current = inspect(args, read)
    require(not current["blockers"], "fresh_preconditions_failed")
    for key in ("identity", "writers", "snapshot", "critical_services", "talos_client"):
        require(current.get(key) == plan.get(key), "approved_evidence_changed")
    for key in ("deployment_uid", "replica_set_uid", "pod_uid", "capacity_pods_sha256"):
        require(current["prevention_and_capacity"][key] == plan["prevention_and_capacity"][key], "prevention_changed")
    fresh(current["observed_at"], 10)
    fresh(plan["observed_at"], 300)
    require(read.talos(ADDRESS, "read", "/proc/sys/kernel/random/boot_id").strip() == BOOT,
            "last_moment_boot_changed")
    latest = read.get(None, "node", NODE)
    require(latest["metadata"]["uid"] == NODE_UID and latest["status"]["nodeInfo"]["bootID"] == BOOT
            and condition(latest, "Ready")["status"] == "Unknown",
            "last_moment_node_changed")
    latest_pods = listing(read.get(None, "pods", "-A", "--chunk-size=0"))
    require(digest(capacity_inventory(latest_pods)) == current["prevention_and_capacity"]["capacity_pods_sha256"],
            "last_moment_capacity_changed")
    ready_uids = {pod["metadata"]["uid"] for pod in latest_pods
                  if not pod["metadata"].get("deletionTimestamp") and pod["status"].get("phase") == "Running"
                  and pod["spec"].get("nodeName") in PEERS and condition(pod, "Ready")["status"] == "True"}
    required_ready = {current["prevention_and_capacity"]["pod_uid"]}
    for service in current["critical_services"].values():
        required_ready.update(service["ready_pod_uids"])
    require(required_ready <= ready_uids, "last_moment_service_readiness_changed")
    latest_writers = sorted([classify_pod(pod, latest_pods, read) for pod in latest_pods
                             if pod["spec"].get("nodeName") == NODE], key=lambda item: item["uid"])
    require(latest_writers == current["writers"], "last_moment_writers_changed")
    fresh(current["observed_at"], 60)
    fresh(plan["observed_at"], 300)
    lease_items = listing(read.get("kube-node-lease", "leases"))
    boundary_leases = {lease["metadata"]["name"]: lease for lease in lease_items}
    require(len(boundary_leases) == len(lease_items) and set(PEERS) | {NODE} <= set(boundary_leases),
            "boundary_lease_inventory_incomplete")
    require(age(boundary_leases[NODE]["spec"]["renewTime"]) > 60, "target_lease_recovered")
    for peer in PEERS:
        fresh(boundary_leases[peer]["spec"]["renewTime"], 60)
    require(read.talos(ADDRESS, "read", "/proc/sys/kernel/random/boot_id").strip() == BOOT,
            "last_moment_boot_changed")
    read.client_matches()
    MAINTENANCE["save_inspection"](attempt, {"talos_client": read.client, "incident": INCIDENT, "source_sha": args.reviewed_sha,
        "plan_sha256": digest(plan), "before_boot_id": BOOT, "status": "submitted-or-unknown"})
    # The durable attempt is consumed even if this call fails before submission.
    read.talos(ADDRESS, "reboot", "--mode=default", "--wait", "--timeout=10m", timeout=630)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute", "verify"))
    parser.add_argument("--reviewed-sha", required=True)
    parser.add_argument("--kubeconfig", required=True, type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--talosconfig", required=True, type=Path)
    parser.add_argument("--talosctl", required=True, type=Path, help="Absolute path to the reviewed Talos v1.11.3 client")
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--approve-plan-sha256")
    args = parser.parse_args(argv)
    try:
        source_guard(args)
        directory = receipt_directory(args.receipt_dir)
        read = Reader(args)
        if args.command == "execute":
            require(args.plan is not None, "private_plan_required")
            execute(args, read, directory)
            print("Reboot command returned; run read-only verify. Authorization remains consumed.")
            return 0
        if args.command == "verify":
            attempt = MAINTENANCE["read_private_json"](directory / ATTEMPT)
            require(attempt.get("incident") == INCIDENT and attempt.get("source_sha") == args.reviewed_sha
                    and attempt.get("before_boot_id") == BOOT and attempt.get("talos_client") == read.client,
                    "attempt_identity_mismatch")
        report = inspect(args, read, recovered=args.command == "verify")
        if args.command == "prepare":
            require(args.plan is not None and args.plan.parent.resolve() == directory, "plan_must_use_receipt_directory")
            MAINTENANCE["save_inspection"](args.plan, report)
        elif not report["blockers"]:
            path = directory / COMPLETE
            if path.exists():
                old = MAINTENANCE["read_private_json"](path)
                require(old["identity"] == report["identity"], "completed_boot_changed")
            else:
                MAINTENANCE["save_inspection"](path, report)
        print(json.dumps({"incident": INCIDENT, "blockers": report["blockers"], "plan_sha256": digest(report),
                          "operation_submitted": False, "functional_acceptance": False}))
        return int(bool(report["blockers"]))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        print("Recovery gate failed; no automatic retry. Retain private plan/attempt evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
