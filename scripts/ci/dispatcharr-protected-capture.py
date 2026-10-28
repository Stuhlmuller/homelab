#!/usr/bin/env python3
"""Hold one whole-namespace Pod watch around a reviewed Dispatcharr capture.

Only a protected fixed-operation workflow may run this module. The result is
private Pod-continuity evidence, never an offsite backup or restore receipt.
"""

import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
MEDIA = "/api/v1/namespaces/media"
PODS = MEDIA + "/pods"
SHA = re.compile(r"[0-9a-f]{40}\Z")
NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?\Z")
MAX_JSON = 4 * 1024 * 1024
JOB_NAME = "dispatcharr-paired-capture"
JOB_SPEC_SHA256 = "e51710e6539cacccb480fbf409ff0a6397f1f7b2032ed6373618db24efc345ca"
BARRIER_SPEC_SHA256 = "ab49194d045ebfd7906cb1bc8ff58fe390731e2f69fca0c20bbb628de476541b"
WRITER_CLAIMS = {"dispatcharr", "data-dispatcharr-postgres-0"}
WRITER_SECRET = "dispatcharr-postgres-env"


class Blocked(RuntimeError):
    """Required identity or continuous observation could not be proved."""


def require(value):
    if not value:
        raise Blocked("Dispatcharr capture fence changed or is incomplete")


def spec_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def metadata(obj):
    value = obj.get("metadata") if isinstance(obj, dict) else None
    require(isinstance(value, dict) and isinstance(value.get("uid"), str)
            and value["uid"] and isinstance(value.get("name"), str))
    return value


def ready(pod):
    conditions = pod.get("status", {}).get("conditions", [])
    return (pod.get("status", {}).get("phase") == "Running" and
            any(c.get("type") == "Ready" and c.get("status") == "True"
                for c in conditions if isinstance(c, dict)))


def uses_writer_state(pod):
    if _uses_source_template(pod):
        return True
    labels = metadata(pod).get("labels", {})
    return (isinstance(labels, dict) and
            labels.get("app.kubernetes.io/name", "").startswith("dispatcharr"))


def _pod_list(value):
    meta = value.get("metadata") if isinstance(value, dict) else None
    require(value.get("kind") == "PodList" and isinstance(meta, dict) and
            isinstance(meta.get("resourceVersion"), str) and
            meta["resourceVersion"] not in ("", "0") and
            meta.get("continue") in (None, "") and
            "remainingItemCount" not in meta and isinstance(value.get("items"), list))
    for pod in value["items"]:
        require(pod.get("kind") == "Pod" and
                metadata(pod).get("namespace") == "media")
    return meta["resourceVersion"]


def _uses_source_template(template):
    spec = template.get("spec") if isinstance(template, dict) else None
    if not isinstance(spec, dict):
        return True
    for volume in spec.get("volumes", []):
        if not isinstance(volume, dict):
            return True
        claim = volume.get("persistentVolumeClaim", {})
        secret = volume.get("secret", {})
        if (isinstance(claim, dict) and claim.get("claimName") in WRITER_CLAIMS or
                isinstance(secret, dict) and secret.get("secretName") == WRITER_SECRET):
            return True
    for container in spec.get("containers", []) + spec.get("initContainers", []):
        if not isinstance(container, dict):
            return True
        for item in container.get("env", []):
            if (isinstance(item, dict) and
                    item.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == WRITER_SECRET):
                return True
        for item in container.get("envFrom", []):
            if (isinstance(item, dict) and
                    item.get("secretRef", {}).get("name") == WRITER_SECRET):
                return True
    return False


def _controller_inventory(client, expected_job_uid=None):
    inventory = {}
    paths = {
        "Deployment": "/apis/apps/v1/namespaces/media/deployments",
        "StatefulSet": "/apis/apps/v1/namespaces/media/statefulsets",
        "DaemonSet": "/apis/apps/v1/namespaces/media/daemonsets",
        "CronJob": "/apis/batch/v1/namespaces/media/cronjobs",
        "Job": "/apis/batch/v1/namespaces/media/jobs",
    }
    for kind, path in paths.items():
        listing = client.get(path)
        require(listing.get("kind") == kind + "List" and
                listing.get("metadata", {}).get("continue") in (None, "") and
                isinstance(listing.get("items"), list))
        for item in listing["items"]:
            meta = metadata(item)
            require(item.get("kind") == kind and meta.get("namespace") == "media")
            name = meta["name"]
            spec = item.get("spec", {})
            template = (spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
                        if kind == "CronJob" else spec.get("template", {}))
            writer = _uses_source_template(template) or "dispatcharr" in name
            if writer:
                key = (kind, name)
                require(key in {("Deployment", "dispatcharr"),
                                ("StatefulSet", "dispatcharr-postgres")} or
                        (key == ("Job", JOB_NAME) and expected_job_uid == meta["uid"]))
                inventory[key] = (meta["uid"], meta.get("generation"))
    require(("Deployment", "dispatcharr") in inventory and
            ("StatefulSet", "dispatcharr-postgres") in inventory)
    if expected_job_uid is not None:
        require(inventory.get(("Job", JOB_NAME), (None,))[0] == expected_job_uid)
    return inventory


def _stable_workloads(client, expected_job_uid=None):
    deployment = client.get("/apis/apps/v1/namespaces/media/deployments/dispatcharr")
    stateful = client.get("/apis/apps/v1/namespaces/media/statefulsets/dispatcharr-postgres")
    dep_meta, db_meta = metadata(deployment), metadata(stateful)
    require(deployment.get("kind") == "Deployment" and
            deployment.get("spec", {}).get("replicas") == 0 and
            deployment.get("status", {}).get("replicas", 0) == 0 and
            deployment.get("status", {}).get("readyReplicas", 0) == 0 and
            deployment.get("status", {}).get("observedGeneration", 0) >=
            dep_meta.get("generation", 1))
    db_status = stateful.get("status", {})
    require(stateful.get("kind") == "StatefulSet" and
            stateful.get("spec", {}).get("replicas") == 1 and
            db_status.get("readyReplicas") == 1 and
            db_status.get("observedGeneration", 0) >= db_meta.get("generation", 1) and
            db_status.get("currentRevision") == db_status.get("updateRevision"))
    controllers = _controller_inventory(client, expected_job_uid)
    claims = {}
    for name in sorted(WRITER_CLAIMS | {"dispatcharr-paired-backup"}):
        claim = client.get(MEDIA + "/persistentvolumeclaims/" + name)
        claim_meta = metadata(claim)
        volume_name = claim.get("spec", {}).get("volumeName")
        require(claim.get("kind") == "PersistentVolumeClaim" and
                claim.get("status", {}).get("phase") == "Bound" and
                isinstance(volume_name, str) and NAME.fullmatch(volume_name))
        volume = client.get("/api/v1/persistentvolumes/" + volume_name)
        volume_meta = metadata(volume)
        reference = volume.get("spec", {}).get("claimRef", {})
        require(volume.get("kind") == "PersistentVolume" and
                reference.get("namespace") == "media" and
                reference.get("name") == name and
                reference.get("uid") == claim_meta["uid"])
        claims[name] = (claim_meta["uid"], volume_name, volume_meta["uid"])
    return {"deployment": (dep_meta["uid"], dep_meta.get("generation")),
            "postgres": (db_meta["uid"], db_meta.get("generation"),
                         db_status.get("currentRevision")),
            "claims": claims, "controllers": controllers}


def _initial_pods(listing, stateful_uid):
    _pod_list(listing)
    postgres = []
    for pod in listing["items"]:
        owner = metadata(pod).get("ownerReferences", [])
        if any(ref.get("uid") == stateful_uid and ref.get("kind") == "StatefulSet"
               for ref in owner if isinstance(ref, dict)):
            postgres.append(pod)
        elif uses_writer_state(pod):
            raise Blocked("Dispatcharr writer Pod remains")
    require(len(postgres) == 1 and ready(postgres[0]) and
            metadata(postgres[0])["name"] == "dispatcharr-postgres-0")
    return metadata(postgres[0])["uid"]


def _final_pods(listing, initial_uids, db_uid, capture_uid, job_uid, barriers):
    _pod_list(listing)
    by_uid = {metadata(pod)["uid"]: pod for pod in listing["items"]}
    barrier_uids = {metadata(pod)["uid"] for pod in barriers}
    require(len(by_uid) == len(listing["items"]) and
            set(by_uid) == initial_uids | {capture_uid} | barrier_uids and
            db_uid in by_uid and capture_uid in by_uid and
            ready(by_uid[db_uid]))
    capture = by_uid[capture_uid]
    require(capture.get("status", {}).get("phase") == "Succeeded" and
            any(ref.get("uid") == job_uid and ref.get("kind") == "Job" for ref in
                metadata(capture).get("ownerReferences", []) if isinstance(ref, dict)) and
            all(item.get("restartCount", 0) == 0 for item in
                capture.get("status", {}).get("containerStatuses", [])
                if isinstance(item, dict)))
    for barrier in barriers:
        pod = by_uid[metadata(barrier)["uid"]]
        require(pod.get("spec", {}).get("schedulingGates") ==
                barrier.get("spec", {}).get("schedulingGates") and
                pod.get("status", {}).get("phase", "Pending") == "Pending")


def _barrier(run_id, phase):
    value = {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "dispatcharr-fence-" + run_id[:16] + "-" + phase,
                         "namespace": "media",
                         "labels": {"homelab.dev/dispatcharr-fence": run_id,
                                    "homelab.dev/fence-phase": phase}},
            "spec": {"automountServiceAccountToken": False,
                     "restartPolicy": "Never",
                     "schedulingGates": [{"name": "homelab.dev/dispatcharr-fence"}],
                     "containers": [{"name": "never-scheduled",
                                     "image": "registry.k8s.io/pause:3.10@sha256:ee6521f290b2168b6e0935a181d4cff9be1ac3f505666ef0e3c98fae8199917a"}]}}
    require(spec_hash(value["spec"]) == BARRIER_SPEC_SHA256)
    return value


def _capture_job(client, source_sha, run_id):
    source = ROOT / "clusters/homelab/apps/dispatcharr/recovery-capture-candidate"
    values = client.local_yaml(source.parent / "values.yaml")
    require(values.get("controllers", {}).get("dispatcharr", {}).get("replicas") == 0)
    candidate = client.local_job(source)
    require(spec_hash(candidate.get("spec")) == JOB_SPEC_SHA256)
    require(candidate.get("kind") == "Job" and
            candidate.get("metadata", {}).get("name") == JOB_NAME and
            candidate.get("metadata", {}).get("namespace") == "media" and
            candidate.get("spec", {}).get("suspend") is True and
            candidate.get("spec", {}).get("backoffLimit") == 0 and
            candidate.get("spec", {}).get("activeDeadlineSeconds") == 3600)
    pod = candidate["spec"]["template"]["spec"]
    require(pod.get("automountServiceAccountToken") is False and
            pod.get("restartPolicy") == "Never" and
            len(pod.get("containers", [])) == 1 and
            pod["containers"][0].get("name") == "capture")
    env = pod["containers"][0].get("env", [])
    fence = [item for item in env if item.get("name") == "FENCE_REF"]
    require(len(fence) == 1 and fence[0].get("value") == "REPLACE_WITH_SIGNED_FENCE_COMMIT")
    config_maps = [volume.get("configMap", {}).get("name") for volume in pod.get("volumes", [])
                   if isinstance(volume, dict) and "configMap" in volume]
    require(len(config_maps) == 1 and
            config_maps[0].startswith("dispatcharr-paired-capture-"))
    active_config = client.get(MEDIA + "/configmaps/" + config_maps[0])
    require(active_config.get("kind") == "ConfigMap" and
            active_config.get("data", {}).get("capture.sh") ==
            (source / "capture.sh").read_text())
    fence[0]["value"] = source_sha
    candidate["spec"]["suspend"] = False
    candidate["metadata"].setdefault("annotations", {})["homelab.dev/source-sha"] = source_sha
    candidate["metadata"]["annotations"]["homelab.dev/fence-id"] = run_id
    candidate["spec"]["template"]["metadata"].setdefault("annotations", {})["homelab.dev/fence-id"] = run_id
    return candidate


class Kubectl:
    def __init__(self, kubeconfig):
        path = Path(kubeconfig)
        require(path.is_absolute() and not path.is_symlink() and path.is_file() and
                stat.S_IMODE(path.stat().st_mode) & 0o077 == 0)
        self.config = path
        info = path.stat()
        self.identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def check_identity(self):
        info = self.config.stat()
        require(not self.config.is_symlink() and
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == self.identity)

    def _command(self, *args, stdin=None, timeout=30):
        self.check_identity()
        result = subprocess.run(["kubectl", "--kubeconfig", str(self.config), *args],
                                input=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        require(result.returncode == 0 and len(result.stdout) <= MAX_JSON)
        return json.loads(result.stdout)

    def get(self, path):
        return self._command("--request-timeout=15s", "get", "--raw", path)

    def local_job(self, path):
        rendered = subprocess.run(["kubectl", "kustomize", str(path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=30, check=False)
        require(rendered.returncode == 0 and len(rendered.stdout) <= MAX_JSON)
        result = subprocess.run(["yq", "ea", "-o=json", "-I=0",
                                 'select(.kind == "Job")', "-"], input=rendered.stdout,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=15, check=False)
        require(result.returncode == 0 and len(result.stdout) <= MAX_JSON)
        return json.loads(result.stdout)

    def local_yaml(self, path):
        result = subprocess.run(["yq", "-o=json", "-I=0", ".", str(path)],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=15, check=False)
        require(result.returncode == 0 and len(result.stdout) <= MAX_JSON)
        return json.loads(result.stdout)

    def create(self, value):
        return self._command("--request-timeout=30s", "create", "-f", "-", "-o", "json",
                             stdin=json.dumps(value).encode())

    def delete_barrier(self, value):
        name, uid = metadata(value)["name"], metadata(value)["uid"]
        current = self.get(PODS + "/" + name)
        require(metadata(current)["uid"] == uid and
                metadata(current).get("labels", {}) == metadata(value).get("labels", {}) and
                current.get("spec", {}).get("schedulingGates") ==
                value.get("spec", {}).get("schedulingGates") and
                not current.get("spec", {}).get("volumes") and
                not metadata(current).get("ownerReferences"))
        options = {"apiVersion": "meta.k8s.io/v1", "kind": "DeleteOptions",
                   "preconditions": {"uid": uid}}
        self._command("--request-timeout=30s", "delete", "--raw=" + PODS + "/" + name,
                      "-f", "-", stdin=json.dumps(options).encode())


class PodWatch:
    def __init__(self, client, resource_version):
        require(isinstance(resource_version, str) and resource_version not in ("", "0"))
        client.check_identity()
        path = (PODS + "?watch=1&resourceVersion=" + resource_version +
                "&allowWatchBookmarks=true&timeoutSeconds=7200")
        self.process = subprocess.Popen(["kubectl", "--kubeconfig", str(client.config),
                                         "--request-timeout=0", "get", "--raw", path],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""
        self.parser = json.JSONDecoder()
        self.allowed = {}
        self.capture_job = None
        self.capture_pod = None
        self.postgres_uid = None
        self.client = client

    def close(self):
        self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def next_event(self, deadline):
        while True:
            candidate = self.buffer.lstrip()
            if candidate:
                try:
                    value, consumed = self.parser.raw_decode(candidate)
                    self.buffer = candidate[consumed:]
                    return value
                except json.JSONDecodeError:
                    pass
            elif self.buffer:
                self.buffer = ""
            self.client.check_identity()
            require(len(self.buffer.encode()) < MAX_JSON and self.process.poll() is None)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                return None
            chunk = os.read(self.process.stdout.fileno(), 65536)
            require(chunk)
            self.buffer += self.decoder.decode(chunk)

    def scan(self, timeout, target=None):
        target_uid = metadata(target)["uid"] if target else None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.next_event(deadline)
            if event is None:
                return False
            kind = event.get("type") if isinstance(event, dict) else None
            obj = event.get("object") if isinstance(event, dict) else None
            require(kind in ("ADDED", "MODIFIED", "DELETED", "BOOKMARK") and
                    isinstance(obj, dict))
            if kind == "BOOKMARK":
                require(obj.get("kind") in ("PartialObjectMetadata", "Pod"))
                continue
            meta = metadata(obj)
            require(obj.get("kind") == "Pod" and meta.get("namespace") == "media")
            if meta["uid"] == target_uid:
                require(kind == "ADDED" and meta["name"] == metadata(target)["name"] and
                        meta.get("labels", {}) == metadata(target).get("labels", {}) and
                        obj.get("spec", {}).get("schedulingGates") ==
                        target.get("spec", {}).get("schedulingGates"))
                return True
            if meta["uid"] in self.allowed:
                require(meta["name"] == self.allowed[meta["uid"]] and
                        kind == "MODIFIED" and
                        (meta["uid"] == self.postgres_uid and ready(obj) or
                         meta["uid"] != self.postgres_uid and
                         (self.capture_pod and meta["uid"] == self.capture_pod[0] or
                          not uses_writer_state(obj))) and
                        (not self.capture_pod or meta["uid"] != self.capture_pod[0] or
                         all(item.get("restartCount", 0) == 0 for item in
                             obj.get("status", {}).get("containerStatuses", [])
                             if isinstance(item, dict))))
                continue
            owner = meta.get("ownerReferences", [])
            if (self.capture_job is not None and
                    any(ref.get("kind") == "Job" and
                        ref.get("uid") == self.capture_job["uid"] for ref in owner
                        if isinstance(ref, dict))):
                require(kind == "ADDED" and self.capture_pod is None and
                        meta.get("labels", {}).get("job-name") == JOB_NAME and
                        not obj.get("spec", {}).get("automountServiceAccountToken", True))
                self.capture_pod = (meta["uid"], meta["name"])
                self.allowed[meta["uid"]] = meta["name"]
                continue
            raise Blocked("Unexpected media Pod event during Dispatcharr capture")
        return False

    def until(self, target):
        require(self.scan(120, target))


def capture(client, source_sha, run_id):
    require(isinstance(source_sha, str) and SHA.fullmatch(source_sha) and
            isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id))
    baseline = _stable_workloads(client)
    candidate = _capture_job(client, source_sha, run_id)
    listing = client.get(PODS)
    rv = _pod_list(listing)
    initial_uids = {metadata(pod)["uid"] for pod in listing["items"]}
    db_pod_uid = _initial_pods(listing, baseline["postgres"][0])
    barriers = []
    watch = PodWatch(client, rv)
    watch.allowed = {metadata(pod)["uid"]: metadata(pod)["name"]
                     for pod in listing["items"]}
    watch.postgres_uid = db_pod_uid
    try:
        first = client.create(_barrier(run_id, "start"))
        barriers.append(first)
        watch.until(first)
        watch.allowed[metadata(first)["uid"]] = metadata(first)["name"]
        client.check_identity()
        job = client.create(candidate)
        job_meta = metadata(job)
        require(job.get("kind") == "Job" and job_meta["name"] == JOB_NAME)
        watch.capture_job = job_meta
        deadline = time.monotonic() + 3600
        while True:
            require(watch.process.poll() is None and time.monotonic() < deadline)
            current = client.get("/apis/batch/v1/namespaces/media/jobs/" + JOB_NAME)
            require(metadata(current)["uid"] == job_meta["uid"] and
                    current.get("status", {}).get("failed", 0) == 0)
            if (current.get("status", {}).get("succeeded") == 1 and
                    current.get("status", {}).get("active", 0) == 0):
                break
            watch.scan(5)
        final = client.create(_barrier(run_id, "end"))
        barriers.append(final)
        watch.until(final)
        require(watch.capture_pod is not None)
        final_state = _stable_workloads(client, job_meta["uid"])
        final_state["controllers"].pop(("Job", JOB_NAME))
        require(final_state == baseline)
        after = client.get(PODS)
        _final_pods(after, initial_uids, db_pod_uid, watch.capture_pod[0],
                    job_meta["uid"], barriers)
        return {"scope": "dispatcharr-pod-fence-capture-only", "publishable": False,
                "sourceSha": source_sha, "runId": run_id,
                "deploymentUid": baseline["deployment"][0],
                "postgresUid": baseline["postgres"][0],
                "postgresPodUid": db_pod_uid,
                "sourceClaims": baseline["claims"],
                "jobUid": job_meta["uid"], "jobPodUid": watch.capture_pod[0],
                "barrierUids": [metadata(item)["uid"] for item in barriers]}
    finally:
        watch.close()
        for barrier in reversed(barriers):
            client.delete_barrier(barrier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--kubeconfig", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        parent = args.receipt.parent.lstat()
        require(args.receipt.is_absolute() and not args.receipt.exists() and
                stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid() and
                stat.S_IMODE(parent.st_mode) == 0o700)
        require(subprocess.check_output(["git", "rev-parse", "HEAD"],
                                        cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip() ==
                args.expected_sha)
        receipt = capture(Kubectl(args.kubeconfig), args.expected_sha, uuid.uuid4().hex)
        descriptor, temporary = tempfile.mkstemp(prefix=".dispatcharr-fence-", dir=args.receipt.parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(json.dumps(receipt, sort_keys=True).encode())
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, args.receipt, follow_symlinks=False)
        Path(temporary).unlink()
    except (Blocked, OSError, subprocess.SubprocessError, ValueError):
        raise SystemExit("Dispatcharr protected capture blocked; private diagnostics withheld") from None


if __name__ == "__main__":
    main()
