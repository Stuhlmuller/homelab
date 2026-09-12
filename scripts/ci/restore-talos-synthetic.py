#!/usr/bin/env python3
"""Fixed synthetic Talos gate; no image override, real data, or local credential fallback."""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "scripts/ci/restore-talos"
PIN_PATH = "images/postgres-restore-egress/published-image.json"
PIN = ROOT / PIN_PATH
REPO = "Stuhlmuller/homelab"
WORKFLOW = f"{REPO}/.github/workflows/restore-talos-synthetic.yml@refs/heads/main"
LAUNCHER = "/usr/local/bin/restore-no-network"
GATE = "homelab.rst.io/restore-profile-reviewed"
NAME_PREFIX = "restore-runtime-"
PROFILE = json.loads((DIRECTORY / "profile.json").read_text())
IMAGE_SOURCE_PREFIXES = (
    "images/postgres-restore-egress/", "scripts/ci/restore-", "scripts/ci/octelium-restore-",
    ".github/workflows/restore-", "clusters/homelab/apps/octelium-storage/",
)
IMAGE_SOURCE_FILES = ("flake.nix", "flake.lock")


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def run(*command, input=None, timeout=30, text=True):
    result = subprocess.run(command, input=input, check=False, text=text,
                            capture_output=True, timeout=timeout, cwd=ROOT)
    require(result.returncode == 0, "Required command failed; output withheld")
    require(len(result.stdout) <= 2 * 1024 * 1024, "Command output exceeded its bound")
    return result.stdout


def anonymous_module():
    # Check absence before imports, subprocesses, GitHub metadata, or credentials.
    require(PIN.is_file() and not PIN.is_symlink(), "Committed published image pin is absent; runtime validation is blocked")
    path = ROOT / "scripts/ci/restore-image-anonymous-pull.py"
    require(path.is_file(), "Reviewed anonymous-pull verifier prerequisite is absent")
    spec = importlib.util.spec_from_file_location("restore_anonymous", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_inventory(revision):
    raw = run("git", "ls-tree", "--full-tree", "-r", "-z", revision, text=False)
    require(raw.endswith(b"\0"), "Published source inventory is empty or malformed")
    inventory = {}
    for record in raw[:-1].split(b"\0"):
        details, path = record.split(b"\t", 1)
        path = path.decode()
        if path == PIN_PATH or not (path in IMAGE_SOURCE_FILES or path.startswith(IMAGE_SOURCE_PREFIXES) or
                                    path + "/" in IMAGE_SOURCE_PREFIXES):
            continue
        mode, kind, blob = details.decode("ascii").split()
        require(kind == "blob" and mode in ("100644", "100755") and
                re.fullmatch(r"[0-9a-f]{40}", blob) is not None,
                "Published source inventory contains a nonregular entry")
        require(path not in inventory, "Published source inventory has duplicate paths")
        inventory[path] = (mode, kind, blob)
    require(inventory, "Published source inventory has no bound files")
    return inventory


def contract(expected):
    verifier = anonymous_module()
    pin = verifier.read_contract(root=ROOT)
    require(re.fullmatch(r"[0-9a-f]{40}", expected) is not None, "Expected source must be a full commit")
    require(run("git", "rev-parse", "HEAD").strip() == expected, "Checkout differs from expected source")
    require(not run("git", "status", "--porcelain=v1", "--untracked-files=all"), "Reviewed checkout must be clean")
    run("git", "merge-base", "--is-ancestor", pin["source_commit"], expected)
    inventory = source_inventory(pin["source_commit"])
    require(inventory == source_inventory(expected), "Published source inventory differs from current source")
    for path, (mode, _, blob) in inventory.items():
        current = ROOT / path
        metadata = current.lstat()
        require(stat.S_ISREG(metadata.st_mode) and current.resolve() == ROOT.resolve() / path,
                "Working source is not a regular nonsymlink file")
        require(bool(metadata.st_mode & stat.S_IXUSR) == (mode == "100755"), "Working source executable mode changed")
        previous = run("git", "cat-file", "blob", blob, text=False)
        require(previous == current.read_bytes(), "Published image source or fixture ABI differs from current source")
    return pin, verifier


def fixture_files():
    stores = run("nix", "build", ".#restore-egress-tools", ".#restore-talos-fault",
                 "--no-link", "--print-out-paths", timeout=600).splitlines()
    def binary(name):
        files = [Path(store) / "bin" / name for store in stores if (Path(store) / "bin" / name).is_file()]
        require(len(files) == 1, "Fixture tool output is ambiguous")
        data = files[0].read_bytes()
        require(data[:6] == b"\x7fELF\x02\x01" and data[18:20] == b"\x3e\x00",
                "Fixture tool is not a little-endian Linux amd64 ELF")
        return data
    files = {"probe": binary("restore-network-probe"), "fault": binary("restore-talos-fault"),
             "talos.sh": (DIRECTORY / "run.sh").read_bytes(),
             "postgres.sh": (ROOT / "scripts/ci/restore-egress/postgres.sh").read_bytes()}
    require(sum(map(len, files.values())) <= 512 * 1024, "Synthetic fixture ConfigMap exceeds its bound")
    return files


def manifest(pin, name):
    require(re.fullmatch(NAME_PREFIX + r"[0-9a-f]{32}", name) is not None, "Invalid owned Job name")
    pod = {
        "automountServiceAccountToken": False, "enableServiceLinks": False,
        "restartPolicy": "Never", "terminationGracePeriodSeconds": 60,
        "schedulerName": "default-scheduler", "schedulingGates": [{"name": GATE}],
        "preemptionPolicy": "PreemptLowerPriority",
        "tolerations": [{"key": key, "operator": "Exists", "effect": "NoExecute", "tolerationSeconds": 300}
                        for key in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")],
        "nodeSelector": {"kubernetes.io/hostname": PROFILE["node"], "kubernetes.io/arch": "amd64", "kubernetes.io/os": "linux"},
        "securityContext": {"runAsUser": 65534, "runAsGroup": 65534, "fsGroup": 65534,
                            "runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": "synthetic", "image": pin["image"], "imagePullPolicy": "Always",
                        "terminationMessagePath": "/root/restore-termination-log", "terminationMessagePolicy": "File",
                        "command": [LAUNCHER, "/bin/sh", "/tests/talos.sh"], "workingDir": "/work",
                        "resources": PROFILE["resources"],
                        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                            "capabilities": {"drop": ["ALL"]}},
                        "volumeMounts": [{"name": "fixtures", "mountPath": "/tests", "readOnly": True},
                                         {"name": "scratch", "mountPath": "/work"}]}],
        "volumes": [{"name": "fixtures", "configMap": {"name": name, "defaultMode": 0o555}},
                    {"name": "scratch", "emptyDir": PROFILE["scratch"]}],
    }
    metadata = {"labels": {"app.kubernetes.io/name": "restore-runtime-validation"},
                "annotations": {"sidecar.istio.io/inject": "false", "ambient.istio.io/redirection": "disabled"}}
    return deepcopy({"apiVersion": "batch/v1", "kind": "Job",
                     "metadata": {"name": name, "namespace": PROFILE["namespace"], **deepcopy(metadata)},
                     "spec": {**PROFILE["job"], "template": {"metadata": metadata, "spec": pod}}})


def configmap(name, job_uid, files):
    return {"apiVersion": "v1", "kind": "ConfigMap", "immutable": True,
            "metadata": {"name": name, "namespace": PROFILE["namespace"],
                         "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": name,
                                              "uid": job_uid, "controller": True, "blockOwnerDeletion": True}]},
            "binaryData": {key: base64.b64encode(data).decode() for key, data in files.items()}}


def validate_spec(spec, pin, name, gated):
    # API-returned Job templates are never an expected-value source.
    expected = manifest(pin, name)["spec"]["template"]["spec"]
    require(spec.get("schedulingGates", []) == ([{"name": GATE}] if gated else []), "Pod scheduling gate changed")
    require(not spec.get("nodeName") if gated else spec.get("nodeName") in (None, "", PROFILE["node"]), "Pod bypassed fixed-worker scheduling")
    for key in ("automountServiceAccountToken", "enableServiceLinks", "restartPolicy", "terminationGracePeriodSeconds",
                "schedulerName", "nodeSelector", "securityContext", "volumes", "preemptionPolicy", "tolerations"):
        require(spec.get(key) == expected[key], "Admitted Pod profile changed")
    pod_defaults = {"serviceAccountName": "default", "serviceAccount": "default",
                    "dnsPolicy": "ClusterFirst", "priority": 0}
    for key, value in spec.items():
        require(key in expected or key == "nodeName" or
                (key in pod_defaults and value == pod_defaults[key]), "Admitted Pod has extra execution or placement configuration")
    require(len(spec.get("containers", [])) == 1, "Admitted container inventory changed")
    container, wanted = spec["containers"][0], expected["containers"][0]
    for key, value in wanted.items():
        require(container.get(key) == value, "Admitted container profile changed")
    for key, value in container.items():
        require(key in wanted, "Admitted container has extra execution configuration")


def identity(obj, name):
    metadata = obj["metadata"]
    require(metadata.get("name") == name and metadata.get("namespace") == PROFILE["namespace"], "Resource identity changed")
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", metadata.get("uid", "")) is not None,
            "Resource UID is absent or invalid")
    return metadata["uid"]


def validate_metadata(metadata, pin, name, job_uid, kind, terminal=False):
    local = manifest(pin, name)
    wanted = local["metadata"] if kind == "job" else local["spec"]["template"]["metadata"]
    labels = metadata.get("labels", {})
    require(isinstance(labels, dict), "Admitted labels are malformed")
    for key, value in wanted["labels"].items():
        require(labels.get(key) == value, "Admitted committed labels changed")
    generated = {} if kind == "job" else {
        "controller-uid": job_uid, "job-name": name,
        "batch.kubernetes.io/controller-uid": job_uid, "batch.kubernetes.io/job-name": name}
    require(labels == {**wanted["labels"], **generated}, "Admitted metadata has changed controller or policy labels")
    require(metadata.get("annotations") == wanted["annotations"], "Admitted annotations changed")
    if kind == "template":
        require(set(metadata) <= {"labels", "annotations", "creationTimestamp"} and
                metadata.get("creationTimestamp") is None, "Admitted template metadata changed")
        return
    allowed = {"name", "namespace", "uid", "resourceVersion", "creationTimestamp", "deletionTimestamp",
               "generation", "managedFields", "labels", "annotations"}
    if kind == "pod":
        allowed.update(("generateName", "ownerReferences", "finalizers"))
        require(metadata.get("generateName", name + "-") == name + "-", "Pod generated name changed")
        expected_finalizers = ["batch.kubernetes.io/job-tracking"]
        allowed_finalizers = [[], expected_finalizers] if terminal else [expected_finalizers]
        require(metadata.get("finalizers", []) in allowed_finalizers,
                "Pod has an unexpected finalizer")
    require(set(metadata) <= allowed, "Admitted resource metadata changed")


def validate_job(job, pin, name):
    job_uid = identity(job, name)
    require(not job["metadata"].get("deletionTimestamp"), "Job is deleting")
    validate_metadata(job["metadata"], pin, name, job_uid, "job")
    spec = job["spec"]
    for key, value in PROFILE["job"].items():
        require(spec.get(key) == value, "Admitted Job execution bound changed")
    defaults = {"suspend": False, "manualSelector": False, "completionMode": "NonIndexed",
                "selector": {"matchLabels": {"batch.kubernetes.io/controller-uid": job_uid}}}
    for key, value in spec.items():
        require(key in PROFILE["job"] or key == "template" or (key in defaults and value == defaults[key]),
                "Admitted Job controller behavior changed")
    validate_spec(spec["template"]["spec"], pin, name, gated=True)
    validate_metadata(spec["template"].get("metadata", {}), pin, name, job_uid, "template")
    return job_uid


def validate_pod(pod, pin, name, job_uid, gated, image_status=False):
    metadata, spec = pod["metadata"], pod["spec"]
    owner = [{"apiVersion": "batch/v1", "kind": "Job", "name": name,
              "uid": job_uid, "controller": True, "blockOwnerDeletion": True}]
    require(metadata.get("ownerReferences") == owner and not metadata.get("deletionTimestamp"), "Pod owner or lifetime changed")
    require(metadata.get("namespace") == PROFILE["namespace"], "Pod namespace changed")
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", metadata.get("uid", "")) is not None,
            "Pod UID is absent or invalid")
    terminal = not gated and pod.get("status", {}).get("phase") in ("Succeeded", "Failed")
    validate_metadata(metadata, pin, name, job_uid, "pod", terminal=terminal)
    validate_spec(spec, pin, name, gated)
    if gated:
        require(pod.get("status", {}).get("phase") in (None, "Pending") and
                not pod.get("status", {}).get("containerStatuses"), "Gated Pod already has process startup evidence")
    if image_status:
        statuses = pod.get("status", {}).get("containerStatuses", [])
        require(len(statuses) == 1 and statuses[0].get("name") == "synthetic", "Runtime container identity is absent or ambiguous")
        require(statuses[0].get("imageID") == pin["image"], "Runtime imageID does not exactly match the published manifest reference")
        require(statuses[0].get("restartCount") == 0, "Synthetic container restarted")
        require(spec.get("nodeName") == PROFILE["node"], "Observed worker differs from committed placement")
    return metadata["uid"]


def quantity(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([numkKMGTPE]|[KMGTPE]i)?", str(value))
    require(match is not None, "Unsupported capacity quantity")
    number, unit = match.groups()
    factors = {None: 1, "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "k": 1000}
    factors.update({unit: 1000 ** (index + 1) for index, unit in enumerate("KMGTPE")})
    factors.update({unit + "i": 1024 ** (index + 1) for index, unit in enumerate("KMGTPE")})
    return Decimal(number) * factors[unit]


def validate_capacity(node, description, stats):
    require(node["metadata"]["name"] == PROFILE["node"] and not node["metadata"].get("deletionTimestamp"), "Worker identity changed")
    require(not node.get("spec", {}).get("unschedulable") and not node.get("spec", {}).get("taints"), "Worker is not eligible")
    require(node["metadata"].get("uid") and node["status"]["nodeInfo"].get("bootID"), "Worker identity evidence is incomplete")
    for key, value in PROFILE["nodeInfo"].items():
        require(node["status"]["nodeInfo"].get(key) == value, "Worker runtime differs from reviewed profile")
    labels = node["metadata"].get("labels", {})
    for key, value in (("kubernetes.io/hostname", PROFILE["node"]), ("kubernetes.io/arch", "amd64"), ("kubernetes.io/os", "linux")):
        require(labels.get(key) == value, "Worker scheduling label changed")
    conditions = {condition["type"]: condition["status"] for condition in node["status"].get("conditions", [])}
    require(all(conditions.get(key) == value for key, value in {"Ready": "True", "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False"}.items()), "Worker condition evidence is missing or unhealthy")
    # kubectl uses PodRequestsAndLimits, including init containers and overhead.
    section = description.split("Allocated resources:\n")
    require(len(section) == 2, "Allocated resource projection is unavailable")
    requests = {}
    for line in section[1].split("Events:", 1)[0].splitlines():
        fields = line.split()
        if fields and fields[0] in ("cpu", "memory", "ephemeral-storage"):
            require(len(fields) >= 3 and fields[0] not in requests, "Allocated resource projection is malformed")
            requests[fields[0]] = quantity(fields[1])
    remaining = {}
    for resource in ("cpu", "memory", "ephemeral-storage"):
        require(resource in requests, "Allocated resource evidence is incomplete")
        remaining[resource] = quantity(node["status"]["allocatable"][resource]) - requests[resource]
        require(remaining[resource] >= quantity(PROFILE["capacity"][resource]), "Worker request headroom is insufficient")
    fs = stats["node"]["fs"]
    require(stats["node"]["nodeName"] == PROFILE["node"], "Nodefs evidence belongs to another worker")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(fs["time"].replace("Z", "+00:00"))).total_seconds()
    require(-30 <= age <= PROFILE["capacity"]["maximumStatsAgeSeconds"], "Nodefs evidence is stale")
    require(type(fs.get("availableBytes")) is int and fs["availableBytes"] >= PROFILE["capacity"]["minimumNodefsBytes"], "Available nodefs evidence is missing or insufficient")
    return {"requestHeadroom": {key: str(value) for key, value in remaining.items()}, "nodefsAvailableBytes": fs["availableBytes"]}


def verify_main(expected, live=False):
    context = os.environ
    require(context.get("GITHUB_ACTIONS") == "true" and context.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and
            context.get("GITHUB_REPOSITORY") == REPO and context.get("GITHUB_REF") == "refs/heads/main" and
            context.get("GITHUB_SHA") == expected and context.get("GITHUB_WORKFLOW_REF") == WORKFLOW,
            "Only the declared workflow at exact reviewed main may proceed")
    if live:
        require(context.get("GITHUB_JOB") == "validate", "Live validation requires the protected job")
    require(context.get("GH_TOKEN"), "GitHub metadata credential is unavailable")
    current = run("gh", "api", f"repos/{REPO}/git/ref/heads/main", "--jq", ".object.sha").strip()
    require(current == expected, "Dispatch is stale; current main changed")


class Kubernetes:
    def call(self, *args, input=None):
        return run("kubectl", "--request-timeout=15s", *args, input=input)

    def get(self, kind, name):
        scope = [] if kind in ("node", "namespace") else ["-n", PROFILE["namespace"]]
        raw = self.call(*scope, "get", kind, name, "--ignore-not-found", "-o", "json")
        return json.loads(raw) if raw.strip() else None

    def create(self, obj):
        return json.loads(self.call("create", "-f", "-", "-o", "json", input=json.dumps(obj)))

    def pods(self, job_uid):
        raw = self.call("-n", PROFILE["namespace"], "get", "pods", "-l",
                        f"batch.kubernetes.io/controller-uid={job_uid}", "-o", "json")
        result = json.loads(raw)
        require(isinstance(result.get("items"), list), "Pod inventory is malformed")
        return result["items"]

    def delete_uid(self, kind, name, uid):
        require(kind in ("jobs", "configmaps"), "Unsupported cleanup resource")
        require(re.fullmatch(NAME_PREFIX + r"[0-9a-f]{32}", name) is not None, "Unsupported cleanup name")
        prefix = "/apis/batch/v1" if kind == "jobs" else "/api/v1"
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid}, "propagationPolicy": "Foreground"}
        self.call("delete", "--raw", f'{prefix}/namespaces/{PROFILE["namespace"]}/{kind}/{name}',
                  "-f", "-", input=json.dumps(body))

    def release(self, pod):
        patch = [{"op": "test", "path": "/metadata/uid", "value": pod["metadata"]["uid"]},
                 {"op": "test", "path": "/metadata/resourceVersion", "value": pod["metadata"]["resourceVersion"]},
                 {"op": "test", "path": "/spec/schedulingGates", "value": [{"name": GATE}]},
                 {"op": "remove", "path": "/spec/schedulingGates"}]
        self.call("-n", PROFILE["namespace"], "patch", "pod", pod["metadata"]["name"], "--type=json", "-p", json.dumps(patch))

    def capacity(self):
        node = self.get("node", PROFILE["node"])
        require(node is not None, "Committed worker is absent")
        description = self.call("describe", "node", PROFILE["node"])
        stats = json.loads(self.call("get", "--raw", f'/api/v1/nodes/{PROFILE["node"]}/proxy/stats/summary'))
        return node, validate_capacity(node, description, stats)


def verify_configmap(actual, expected):
    require(actual is not None and actual.get("immutable") is True and
            actual.get("binaryData") == expected["binaryData"] and not actual.get("data"), "Fixture ConfigMap content changed")
    for key, value in expected["metadata"].items():
        require(actual["metadata"].get(key) == value, "Fixture ConfigMap ownership changed")
    require(not actual["metadata"].get("deletionTimestamp"), "Fixture ConfigMap is deleting")
    return actual["metadata"]["uid"]


def cleanup(client, pin, name, job_uid, config_uid, uncertain_create, pod_name=None, pod_uid=None, uncertain_config=False):
    # Never retry creation or adopt a replacement UID. Controller cleanup is not
    # a hard guarantee during outages; incomplete evidence fails the whole run.
    current = client.get("job", name)
    if job_uid is None and current is not None:
        job_uid = validate_job(current, pin, name)
    if current is not None:
        require(current["metadata"]["uid"] == job_uid, "Owned Job was replaced; cleanup unverified")
        client.delete_uid("jobs", name, job_uid)
    elif uncertain_create and job_uid is None:
        raise RuntimeError("Create response was uncertain; cleanup remains unverified")
    if config_uid is not None:
        current_config = client.get("configmap", name)
        if current_config is not None:
            require(current_config["metadata"]["uid"] == config_uid, "Owned ConfigMap was replaced; cleanup unverified")
            client.delete_uid("configmaps", name, config_uid)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        current = client.get("job", name)
        cm = client.get("configmap", name)
        pods = client.pods(job_uid) if job_uid is not None else []
        captured = client.get("pod", pod_name) if pod_name else None
        require(captured is None or captured["metadata"]["uid"] == pod_uid, "Captured Pod was replaced during cleanup")
        if current is None and cm is None and not pods and captured is None:
            require(not (uncertain_config and config_uid is None), "ConfigMap create response was uncertain; cleanup remains unverified")
            return
        require(current is None or current["metadata"]["uid"] == job_uid, "Job replacement appeared during cleanup")
        require(cm is None or config_uid is None or cm["metadata"]["uid"] == config_uid, "ConfigMap replacement appeared during cleanup")
        time.sleep(2)
    raise RuntimeError("Owned dependents remain; cleanup unverified")


def execute(pin, files, expected, client):
    namespace = client.get("namespace", PROFILE["namespace"])
    require(namespace is not None and not namespace["metadata"].get("deletionTimestamp"), "Synthetic namespace is unavailable")
    labels = namespace["metadata"].get("labels", {})
    require(not any(key in labels for key in ("istio-injection", "istio.io/rev", "istio.io/dataplane-mode")), "Namespace injection profile changed")
    node, headroom = client.capacity()
    name = NAME_PREFIX + uuid.uuid4().hex
    local_job = manifest(pin, name)
    job_uid = config_uid = pod_uid = pod_name = None
    uncertain_create = False
    uncertain_config = False
    try:
        verify_main(expected, live=True)
        uncertain_create = True
        try:
            job = client.create(local_job)
            # A successful create proves this returned identity is ours even if
            # admission changed its content. Capture it before acceptance checks.
            job_uid = identity(job, name)
        except (RuntimeError, subprocess.TimeoutExpired):
            require(job_uid is None, "Created Job identity could not be accepted")
            job = client.get("job", name)
            require(job is not None, "Job creation was uncertain; refusing another create")
            job_uid = validate_job(job, pin, name)
        validate_job(job, pin, name)
        uncertain_create = False
        cm_expected = configmap(name, job_uid, files)
        uncertain_config = True
        try:
            cm = client.create(cm_expected)
            config_uid = identity(cm, name)
        except (RuntimeError, subprocess.TimeoutExpired):
            require(config_uid is None, "Created ConfigMap identity could not be accepted")
            cm = client.get("configmap", name)
        config_uid = verify_configmap(cm, cm_expected)
        uncertain_config = False
        deadline = time.monotonic() + PROFILE["job"]["activeDeadlineSeconds"] + 60
        while True:
            require(time.monotonic() < deadline, "Synthetic validation exceeded its deadline")
            current_job = client.get("job", name)
            require(current_job is not None and validate_job(current_job, pin, name) == job_uid, "Job identity changed")
            conditions = {item["type"]: item["status"] for item in current_job.get("status", {}).get("conditions", [])}
            require(conditions.get("Failed") != "True", "Synthetic Job failed")
            pods = client.pods(job_uid)
            require(len(pods) <= 1, "Additional or replacement Pods appeared")
            if not pods:
                require(pod_uid is None, "Captured Pod disappeared")
                time.sleep(2)
                continue
            pod = pods[0]
            if pod_uid is None:
                pod_uid = validate_pod(pod, pin, name, job_uid, gated=True)
                pod_name = pod["metadata"]["name"]
                verify_configmap(client.get("configmap", name), cm_expected)
                client.release(pod)
                # Admission can change allowed fields during gate removal. The
                # following reads detect drift, not prevent that execution.
                continue
            require(validate_pod(pod, pin, name, job_uid, gated=False) == pod_uid, "Captured Pod was replaced")
            statuses = pod.get("status", {}).get("containerStatuses", [])
            if statuses and statuses[0].get("imageID"):
                validate_pod(pod, pin, name, job_uid, gated=False, image_status=True)
            if conditions.get("Complete") == "True":
                require(current_job["status"].get("succeeded") == 1, "Job completion count is invalid")
                validate_pod(pod, pin, name, job_uid, gated=False, image_status=True)
                terminated = statuses[0].get("state", {}).get("terminated", {})
                require(terminated.get("exitCode") == 0, "Container did not terminate successfully")
                require(not terminated.get("message", ""), "Synthetic termination message is not empty")
                break
            time.sleep(2)
        output = client.call("-n", PROFILE["namespace"], "logs", pod["metadata"]["name"], "-c", "synthetic", "--limit-bytes=65536")
        lines = output.splitlines()
        require(lines.count("RESTORE_TALOS_SYNTHETIC_PASSED") == 1, "Synthetic completion marker missing")
        profiles = [json.loads(line.removeprefix("RESTORE_PROFILE ")) for line in lines if line.startswith("RESTORE_PROFILE ")]
        require(len(profiles) == 1, "Process profile evidence missing or ambiguous")
        profile = profiles[0]
        require(set(profile) == {"uid", "gid", "capabilities", "no_new_privs", "seccomp", "filters"} and
                all(type(profile[key]) is int and profile[key] == value for key, value in {"uid": 65534, "gid": 65534, "capabilities": 0, "no_new_privs": 1, "seccomp": 2}.items()) and
                type(profile["filters"]) is int and profile["filters"] >= 2, "Process profile evidence is invalid")
        observed_node, _ = client.capacity()
        require(observed_node["metadata"]["uid"] == node["metadata"]["uid"] and
                observed_node["status"]["nodeInfo"].get("bootID") == node["status"]["nodeInfo"].get("bootID"), "Worker identity changed during validation")
        receipt = {"source_commit": expected, "published_image": pin, "job_uid": job_uid, "pod_uid": pod_uid,
                   "imageID": statuses[0]["imageID"], "node": PROFILE["node"], "runtime": PROFILE["nodeInfo"],
                   "process": profile, "capacity_before": headroom,
                   "fixture_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}}
    finally:
        cleanup(client, pin, name, job_uid, config_uid, uncertain_create, pod_name, pod_uid, uncertain_config)
    return receipt


def credential_path():
    require(os.environ.get("OCTELIUM_AUTH_TOKEN"), "Protected CI Kubernetes credential is unavailable")
    require(not os.environ.get("KUBECONFIG"), "Refusing an inherited KUBECONFIG")
    kubeconfig = Path.home() / ".kube/config"
    require(not kubeconfig.exists() and not kubeconfig.is_symlink() and not kubeconfig.parent.is_symlink(),
            "Refusing to overwrite an existing kubeconfig or follow a kubeconfig symlink")
    return kubeconfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--run", action="store_true", help="Only the protected workflow may create the fixed synthetic Job")
    options = parser.parse_args()
    pin, verifier = contract(options.expected_sha)
    verify_main(options.expected_sha, live=options.run)
    verifier.verify_publication(pin)
    verifier.pull(pin)
    files = fixture_files()
    if not options.run:
        print("Committed pin, publication metadata, anonymous bytes and synthetic fixtures verified; no cluster access")
        return
    kubeconfig = credential_path()
    try:
        run("bash", "scripts/ci/install-kubeconfig.sh")
        receipt = execute(pin, files, options.expected_sha, Kubernetes())
    finally:
        kubeconfig.unlink(missing_ok=True)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(f"Talos synthetic validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
