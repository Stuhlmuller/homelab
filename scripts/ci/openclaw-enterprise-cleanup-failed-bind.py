#!/usr/bin/env python3
"""Remove one proven failed pre-binding Job through a protected workflow only."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from urllib import request


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/ci/openclaw-enterprise-journal-operator.py"
spec = importlib.util.spec_from_file_location("oce_journal_operator", SOURCE)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)

HISTORICAL_FILES = (
    "scripts/ci/openclaw-enterprise-stage.sh",
    "scripts/ci/openclaw-enterprise-journal-operator.py",
    "scripts/openclaw-enterprise.py",
    "scripts/openclaw-enterprise-bind-installation.py",
    "scripts/openclaw-enterprise-startup.py",
    "scripts/config/openclaw-enterprise.json",
    "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
    "clusters/homelab/apps/openclaw-enterprise/values.yaml",
)
INSTALLATION_ID = "openclaw.dev/installation-id"
UID = journal.UID
RV = re.compile(r"[1-9][0-9]*\Z")
RUN_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
ATTEMPT = re.compile(r"[1-9][0-9]{0,4}\Z")


def require(condition, reason):
    journal.require(condition, reason)


def source_contract(current_sha, source_sha):
    require(bool(journal.SHA.fullmatch(source_sha)), "failed binding source is invalid")
    journal.command(["git", "merge-base", "--is-ancestor", source_sha, current_sha])
    for name in HISTORICAL_FILES:
        historical = journal.command(["git", "show", source_sha + ":" + name])
        committed = journal.command(["git", "show", current_sha + ":" + name])
        require(historical == committed == (ROOT / name).read_text(),
                "binding source or reviewed candidate changed")
    own = "scripts/ci/openclaw-enterprise-cleanup-failed-bind.py"
    require(journal.command(["git", "show", current_sha + ":" + own]) ==
            (ROOT / own).read_text(), "cleanup source differs from current main")


def baseline_from_job(actual):
    template = actual.get("spec", {}).get("template", {})
    metadata = template.get("metadata", {}) if isinstance(template, dict) else {}
    baseline = metadata.get("annotations") if isinstance(metadata, dict) else None
    candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
    require(isinstance(baseline, dict) and set(baseline) == {
        journal.BINDING_UID, journal.BINDING_VERSION,
        journal.BINDING_DIGEST, journal.BINDING_IMMUTABLE} and
        isinstance(baseline[journal.BINDING_UID], str) and
        UID.fullmatch(baseline[journal.BINDING_UID]) and
        isinstance(baseline[journal.BINDING_VERSION], str) and
        RV.fullmatch(baseline[journal.BINDING_VERSION]) and
        baseline[journal.BINDING_DIGEST] == hashlib.sha256(candidate).hexdigest() and
        baseline[journal.BINDING_IMMUTABLE] == "true",
        "failed binding has no valid pre-Job Secret witness")
    return baseline


def prove_secret(operator, baseline):
    namespace = operator["namespace"]
    observed = journal.binding_secret_baseline(namespace)
    require(observed == baseline, "startup Secret changed since binding Job creation")
    candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
    name = "occ-installation-startup-" + hashlib.sha256(candidate).hexdigest()[:32]
    secret = journal.kubectl_json("-n", namespace, "get", "secret", name, "-o=json")
    metadata = secret.get("metadata", {}) if isinstance(secret, dict) else {}
    annotations = metadata.get("annotations") if isinstance(metadata, dict) else None
    require(isinstance(annotations, dict) and INSTALLATION_ID not in annotations and
            metadata.get("uid") == baseline[journal.BINDING_UID] and
            metadata.get("resourceVersion") == baseline[journal.BINDING_VERSION] and
            not metadata.get("deletionTimestamp") and
            secret.get("immutable") is True and secret.get("type") == "Opaque" and
            secret.get("data") == {"installation.yaml": base64.b64encode(candidate).decode()},
            "startup Secret was bound, replaced or changed")


def prove_retained_storage(operator):
    journal.prove_claims(operator)
    namespace = operator["namespace"]
    snapshot = []
    for kind, name, expected_uid in (
        ("pvc", operator["journalClaim"], operator["journalClaimUid"]),
        ("pvc", operator["bootstrapClaim"], operator["bootstrapClaimUid"]),
        ("pv", operator["journalClaim"], operator["journalVolumeUid"]),
    ):
        args = ("-n", namespace, "get", kind, name, "-o=json") if kind == "pvc" else (
            "get", kind, name, "-o=json")
        obj = journal.kubectl_json(*args)
        metadata = obj.get("metadata", {}) if isinstance(obj, dict) else {}
        require(metadata.get("uid") == expected_uid and
                not metadata.get("ownerReferences") and
                not metadata.get("deletionTimestamp"),
                "retained volume or claim ownership changed")
        snapshot.append((kind, name, metadata["uid"], obj.get("spec"),
                         obj.get("status", {}).get("phase")))
    bootstrap = journal.kubectl_json("-n", namespace, "get", "pvc",
                                     operator["bootstrapClaim"], "-o=json")
    volume_name = bootstrap.get("spec", {}).get("volumeName")
    require(isinstance(volume_name, str), "bootstrap volume name is invalid")
    volume = journal.kubectl_json("get", "pv", volume_name, "-o=json")
    metadata = volume.get("metadata", {}) if isinstance(volume, dict) else {}
    require(metadata.get("uid") == operator["bootstrapVolumeUid"] and
            not metadata.get("ownerReferences") and
            not metadata.get("deletionTimestamp"),
            "retained bootstrap volume ownership changed")
    snapshot.append(("pv", volume_name, metadata["uid"], volume.get("spec"),
                     volume.get("status", {}).get("phase")))
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def matching_pods(items, name, job_uid):
    require(isinstance(items, list), "binding Pod list is invalid")
    matches = []
    for pod in items:
        metadata = pod.get("metadata", {}) if isinstance(pod, dict) else {}
        labels = (metadata.get("labels") or {}) if isinstance(metadata, dict) else {}
        owners = (metadata.get("ownerReferences") or []) if isinstance(metadata, dict) else []
        require(isinstance(labels, dict) and isinstance(owners, list),
                "binding Pod metadata is invalid")
        if (metadata.get("name", "").startswith(name + "-") or
                labels.get("batch.kubernetes.io/job-name") == name or
                labels.get("batch.kubernetes.io/controller-uid") == job_uid or
                any(isinstance(owner, dict) and owner.get("uid") == job_uid
                    for owner in owners)):
            matches.append(pod)
    return matches


def prove_pod(pod, intended, job_uid, pod_uid, operator):
    metadata = pod.get("metadata", {}) if isinstance(pod, dict) else {}
    actual = pod.get("spec", {}) if isinstance(pod, dict) else {}
    status = pod.get("status", {}) if isinstance(pod, dict) else {}
    wanted = intended["spec"]["template"]["spec"]
    name = intended["metadata"]["name"]
    labels = metadata.get("labels") if isinstance(metadata, dict) else None
    owners = metadata.get("ownerReferences") if isinstance(metadata, dict) else None
    annotations = metadata.get("annotations") if isinstance(metadata, dict) else None
    containers = actual.get("containers") if isinstance(actual, dict) else None
    states = status.get("containerStatuses") if isinstance(status, dict) else None
    terminated = (states[0].get("state", {}).get("terminated")
                  if isinstance(states, list) and len(states) == 1 and
                  isinstance(states[0], dict) and
                  isinstance(states[0].get("state"), dict) else None)
    require(isinstance(metadata, dict) and metadata.get("uid") == pod_uid and
            metadata.get("namespace") == operator["namespace"] and
            isinstance(metadata.get("name"), str) and
            metadata["name"].startswith(name + "-") and
            not metadata.get("deletionTimestamp") and
            isinstance(labels, dict) and
            labels.get("batch.kubernetes.io/job-name") == name and
            labels.get("batch.kubernetes.io/controller-uid") == job_uid and
            all(labels.get(key) == value for key, value in
                intended["spec"]["template"]["metadata"]["labels"].items()) and
            annotations == intended["spec"]["template"]["metadata"]["annotations"] and
            isinstance(owners, list) and len(owners) == 1 and
            owners[0].get("controller") is True and
            owners[0].get("kind") == "Job" and
            owners[0].get("name") == name and owners[0].get("uid") == job_uid and
            isinstance(actual, dict) and
            actual.get("serviceAccountName") == wanted["serviceAccountName"] and
            actual.get("automountServiceAccountToken") is False and
            actual.get("restartPolicy") == "Never" and
            actual.get("nodeSelector") == wanted["nodeSelector"] and
            actual.get("nodeName") == operator["node"] and
            actual.get("securityContext") == wanted["securityContext"] and
            actual.get("volumes") == wanted["volumes"] and
            not actual.get("initContainers") and not actual.get("ephemeralContainers") and
            not actual.get("hostNetwork") and not actual.get("hostPID") and
            not actual.get("hostIPC") and not actual.get("shareProcessNamespace") and
            not actual.get("hostUsers") and not actual.get("tolerations") and
            not actual.get("hostAliases") and not actual.get("dnsConfig") and
            not actual.get("runtimeClassName") and
            actual.get("dnsPolicy") in (None, "ClusterFirst") and
            actual.get("schedulerName") in (None, "default-scheduler") and
            isinstance(containers, list) and len(containers) == 1 and
            isinstance(containers[0], dict) and
            all(containers[0].get(key) == wanted["containers"][0][key] for key in
                ("name", "image", "imagePullPolicy", "command", "args", "env",
                 "terminationMessagePath", "terminationMessagePolicy", "volumeMounts",
                 "securityContext", "resources")) and
            not containers[0].get("envFrom") and
            not containers[0].get("lifecycle") and
            not containers[0].get("ports") and
            not containers[0].get("volumeDevices") and
            isinstance(status, dict) and status.get("phase") == "Failed" and
            isinstance(states, list) and len(states) == 1 and
            states[0].get("name") == "operator" and
            isinstance(terminated, dict) and
            type(terminated.get("exitCode")) is int and
            terminated["exitCode"] != 0,
            "failed binding Pod identity or termination is unproven")


def prove_failed_job(job, intended, job_uid):
    metadata = job.get("metadata", {}) if isinstance(job, dict) else {}
    status = job.get("status", {}) if isinstance(job, dict) else {}
    conditions = status.get("conditions") if isinstance(status, dict) else None
    require(isinstance(metadata, dict) and metadata.get("uid") == job_uid and
            metadata.get("namespace") == intended["metadata"]["namespace"] and
            not metadata.get("ownerReferences") and
            not metadata.get("deletionTimestamp") and
            isinstance(metadata.get("resourceVersion"), str) and
            RV.fullmatch(metadata["resourceVersion"]) and
            journal.job_identity(job, intended) and
            isinstance(status, dict) and status.get("active") in (None, 0) and
            status.get("succeeded") in (None, 0) and
            isinstance(conditions, list) and
            any(isinstance(item, dict) and item.get("type") == "Failed" and
                item.get("status") == "True" for item in conditions) and
            not any(isinstance(item, dict) and item.get("type") == "Complete" and
                    item.get("status") == "True" for item in conditions),
            "binding Job is not the terminal failed source-bound Job")
    return metadata["resourceVersion"]


def prove_jobs(items, target_name, target_uid):
    require(isinstance(items, list), "operator Job list is invalid")
    target = None
    for item in items:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        labels = metadata.get("labels") or {} if isinstance(metadata, dict) else {}
        name = metadata.get("name", "") if isinstance(metadata, dict) else ""
        if not (isinstance(name, str) and name.startswith("oce-journal-") or
                isinstance(labels, dict) and
                labels.get("app.kubernetes.io/name") == "oce-journal-operator"):
            continue
        require(bool(journal.JOB_NAME.fullmatch(name)) and isinstance(labels, dict) and
                labels.get("app.kubernetes.io/name") == "oce-journal-operator" and
                labels.get("homelab.stuhlmuller.dev/stage") ==
                journal.JOB_NAME.fullmatch(name).group(1) and
                bool(journal.SHA.fullmatch(
                    labels.get("homelab.stuhlmuller.dev/source-sha", ""))),
                "operator Job identity is ambiguous")
        if name == target_name:
            require(target is None and metadata.get("uid") == target_uid,
                    "failed binding Job was replaced")
            target = item
            continue
        status = item.get("status", {})
        conditions = status.get("conditions") or [] if isinstance(status, dict) else []
        require(any(isinstance(condition, dict) and
                    condition.get("type") == "Complete" and
                    condition.get("status") == "True" for condition in conditions) and
                status.get("active") in (None, 0),
                "another operator Job is active or failed")
    require(target is not None, "failed binding Job is absent")
    return target


def prove_predelete(source_sha, run_id, attempt, job_uid, pod_uid,
                    config, operator):
    namespace = operator["namespace"]
    name = f"oce-journal-bind-installation-{run_id}-{attempt}"
    jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
    target = prove_jobs(jobs.get("items") if isinstance(jobs, dict) else None,
                        name, job_uid)
    baseline = baseline_from_job(target)
    projection = journal.config_projection(config, source_sha, operator)
    intended = journal.build_job("bind-installation", source_sha, run_id, operator,
                                 projection, attempt, baseline=baseline)
    job_rv = prove_failed_job(target, intended, job_uid)
    pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
    matches = matching_pods(pods.get("items") if isinstance(pods, dict) else None,
                            name, job_uid)
    require(len(matches) == 1, "failed binding Pod is absent or ambiguous")
    for pod in pods["items"]:
        if pod is matches[0]:
            continue
        metadata = pod.get("metadata") or {}
        labels = metadata.get("labels") or {}
        status = pod.get("status") or {}
        require(isinstance(labels, dict) and isinstance(status, dict),
                "operator Pod metadata is invalid")
        require(labels.get("app.kubernetes.io/name") != "oce-journal-operator" or
                (status.get("phase") not in ("Pending", "Running", "Unknown") and
                 not metadata.get("deletionTimestamp")),
                "another operator Pod is active or terminating")
    prove_pod(matches[0], intended, job_uid, pod_uid, operator)
    prove_secret(operator, baseline)
    storage = prove_retained_storage(operator)
    return name, job_rv, baseline, storage


def delete_once(namespace, name, job_uid, job_rv, expected, environ):
    """One foreground REST DELETE; caller must resolve any uncertain response."""
    process = subprocess.Popen(
        ["kubectl", "proxy", "--address=127.0.0.1", "--port=0",
         "--accept-hosts=^127\\.0\\.0\\.1$"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1)
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        require(bool(readable), "local Kubernetes proxy did not start")
        line = process.stdout.readline()
        match = re.fullmatch(r"Starting to serve on 127\.0\.0\.1:([1-9][0-9]*)\n?", line)
        require(bool(match) and process.poll() is None,
                "local Kubernetes proxy address is invalid")
        endpoint = (f"http://127.0.0.1:{match.group(1)}/apis/batch/v1/"
                    f"namespaces/{namespace}/jobs/{name}")
        payload = json.dumps({"apiVersion": "v1", "kind": "DeleteOptions",
                              "preconditions": {"uid": job_uid,
                                                "resourceVersion": job_rv},
                              "propagationPolicy": "Foreground"},
                             separators=(",", ":")).encode()
        action = request.Request(endpoint, data=payload, method="DELETE",
                                 headers={"Content-Type": "application/json"})
        opener = request.build_opener(request.ProxyHandler({}))
        journal.exact_main(expected, environ)
        try:
            with opener.open(action, timeout=15) as response:
                return 200 <= response.status < 300
        except Exception:
            # Once open() begins, any error may follow an accepted DELETE.
            return False
    finally:
        try:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            # Proxy shutdown must not hide a DELETE response or readback path.
            pass


def observe_deletion(namespace, name, job_uid, pod_uid, operator, baseline, storage,
                     *, uncertain):
    for _ in range(30):
        jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
        items = jobs.get("items") if isinstance(jobs, dict) else None
        require(isinstance(items, list), "post-delete Job list is invalid")
        named = [job for job in items if job.get("metadata", {}).get("name") == name]
        require(len(named) <= 1, "post-delete Job identity is ambiguous")
        if named:
            metadata = named[0]["metadata"]
            require(metadata.get("uid") == job_uid,
                    "failed binding Job was replaced during deletion")
            require(not uncertain or metadata.get("deletionTimestamp"),
                    "failed binding DELETE outcome is uncertain")
        pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
        matches = matching_pods(pods.get("items") if isinstance(pods, dict) else None,
                                name, job_uid)
        require(all(pod.get("metadata", {}).get("uid") == pod_uid for pod in matches),
                "failed binding Pod was replaced during deletion")
        prove_secret(operator, baseline)
        require(prove_retained_storage(operator) == storage,
                "retained volume or claim changed during deletion")
        if not named and not matches:
            return
        time.sleep(2)
    raise journal.Blocked("failed binding foreground deletion remains incomplete")


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    try:
        require(len(argv) == 5, "cleanup requires exact failed binding reference")
        source_sha, run_id, attempt, job_uid, pod_uid = argv
        require(bool(journal.SHA.fullmatch(source_sha)) and
                bool(RUN_ID.fullmatch(run_id)) and bool(ATTEMPT.fullmatch(attempt)) and
                bool(UID.fullmatch(job_uid)) and bool(UID.fullmatch(pod_uid)),
                "failed binding reference is invalid")
        expected = environ.get("EXPECTED_SHA", "")
        journal.exact_main(expected, environ)
        source_contract(expected, source_sha)
        journal.prove_committed_inputs(expected)
        config = json.loads(journal.CONFIG.read_text())
        operator = journal.contract(config, "bind-installation", expected)
        journal.prove_image_source(operator, expected)
        _, first_job_rv, first_baseline, first_storage = prove_predelete(
            source_sha, run_id, attempt, job_uid, pod_uid, config, operator)
        # A second complete read closes the proof-to-delete interval. The
        # Kubernetes preconditions close the final Job identity/version race.
        name, job_rv, baseline, storage = prove_predelete(
            source_sha, run_id, attempt, job_uid, pod_uid, config, operator)
        require(job_rv == first_job_rv and baseline == first_baseline and
                storage == first_storage,
                "failed binding state changed between checks")
        accepted = delete_once(operator["namespace"], name, job_uid, job_rv,
                               expected, environ)
        observe_deletion(operator["namespace"], name, job_uid, pod_uid,
                         operator, baseline, storage, uncertain=not accepted)
    except (journal.Blocked, OSError, ValueError, KeyError, TypeError, AttributeError,
            subprocess.SubprocessError):
        print("Failed binding cleanup blocked; private diagnostics withheld", file=sys.stderr)
        return 1
    print("Failed binding Job and Pod removed; retained state verified privately")
    return 0


if __name__ == "__main__":
    sys.exit(main())
