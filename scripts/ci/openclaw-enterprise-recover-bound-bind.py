#!/usr/bin/env python3
"""Attest a bound Installation, receipt a failed binding Job, then remove only that Job.

This protected recovery deliberately never calls the normal binding CAS callback.
The source-bound verifier Pod can observe an unbound Secret, but no runner in this
stage can patch it; that outcome fails before the old Job is removed.
"""

from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "oce_failed_bind_cleanup", ROOT / "scripts/ci/openclaw-enterprise-cleanup-failed-bind.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
journal = cleanup.journal
require = journal.require

INSTALLATION_ID = re.compile(r"ins_[A-Za-z0-9_-]+\Z")
RV = cleanup.RV
HASH = re.compile(r"[0-9a-f]{64}\Z")
VERIFIER_NAME = re.compile(
    r"oce-journal-bind-installation-([1-9][0-9]{0,19})-([1-9][0-9]{0,4})\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def timestamp(value):
    require(isinstance(value, str), "binding Pod timestamp is invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise journal.Blocked("binding Pod timestamp is invalid") from None


def proof_from_pod(namespace, pod, expected_sha, job_name, uid, version, identity,
                   already_bound):
    metadata = pod["metadata"]
    status = pod["status"]
    states = status.get("containerStatuses")
    require(isinstance(states, list) and len(states) == 1 and
            isinstance(states[0], dict) and
            isinstance(states[0].get("state"), dict) and
            isinstance(states[0]["state"].get("terminated"), dict),
            "binding Pod did not terminate with a single container")
    finished = timestamp(states[0]["state"]["terminated"].get("finishedAt"))
    created = timestamp(metadata.get("creationTimestamp"))
    raw = journal.command(["kubectl", "--request-timeout=15s", "-n", namespace,
                           "logs", "pod/" + metadata["name"], "-c", "operator",
                           "--tail=20", "--limit-bytes=4096"])
    require(len(raw.encode()) <= 4096, "binding Pod proof log is oversized")
    lines = [line for line in raw.splitlines() if line.startswith("OCE_BIND_READY:")]
    require(len(lines) == 1, "binding Pod proof is missing or ambiguous")
    try:
        proof = json.loads(lines[0][len("OCE_BIND_READY:"):])
    except ValueError:
        raise journal.Blocked("binding Pod proof is invalid") from None
    require(isinstance(proof, dict) and set(proof) == {
        "schema", "expectedSha", "jobName", "installationId", "secretUid",
        "secretResourceVersion", "alreadyBound", "issuedAt"} and
        type(proof["schema"]) is int and proof["schema"] == 1 and
        proof["expectedSha"] == expected_sha and proof["jobName"] == job_name and
        proof["installationId"] == identity and proof["secretUid"] == uid and
        proof["secretResourceVersion"] == version and
        proof["alreadyBound"] is already_bound and
        type(proof["issuedAt"]) is int and
        created - 5 <= proof["issuedAt"] <= finished + 5 and
        proof["issuedAt"] <= time.time() + 300,
        "binding Pod proof differs from the exact Job or Secret witness")
    return digest(proof), hashlib.sha256(raw.encode()).hexdigest()


def prove_bound_secret(operator, baseline, uid, bound_rv, identity):
    namespace = operator["namespace"]
    observed = journal.binding_secret_baseline(namespace)
    require(observed[journal.BINDING_UID] == uid and
            observed[journal.BINDING_VERSION] == bound_rv and
            bound_rv != baseline[journal.BINDING_VERSION] and
            uid == baseline[journal.BINDING_UID] and
            observed[journal.BINDING_DIGEST] == baseline[journal.BINDING_DIGEST],
            "startup Secret binding identity or version changed")
    candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
    name = "occ-installation-startup-" + hashlib.sha256(candidate).hexdigest()[:32]
    secret = journal.kubectl_json("-n", namespace, "get", "secret", name, "-o=json")
    metadata = secret.get("metadata", {}) if isinstance(secret, dict) else {}
    require(metadata.get("uid") == uid and
            metadata.get("resourceVersion") == bound_rv and
            metadata.get("annotations") == {
                "homelab.stuhlmuller.dev/installation-sha256": baseline[journal.BINDING_DIGEST],
                "openclaw.dev/installation-id": identity} and
            not metadata.get("deletionTimestamp") and not metadata.get("ownerReferences"),
            "startup Secret is not exactly bound to the proven Installation")
    return observed


def prove_failed_source(source_sha, run_id, attempt, job_uid, pod_uid,
                        uid, bound_rv, identity, config, operator):
    namespace = operator["namespace"]
    name = f"oce-journal-bind-installation-{run_id}-{attempt}"
    jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
    target = cleanup.prove_jobs(jobs.get("items") if isinstance(jobs, dict) else None,
                                name, job_uid)
    baseline = cleanup.baseline_from_job(target)
    projection = journal.config_projection(config, source_sha, operator)
    intended = journal.build_job("bind-installation", source_sha, run_id, operator,
                                 projection, attempt, baseline=baseline)
    job_rv = cleanup.prove_failed_job(target, intended, job_uid)
    projection_id = cleanup.prove_projection(projection)
    pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
    items = pods.get("items") if isinstance(pods, dict) else None
    matches = cleanup.matching_pods(items, name, job_uid)
    require(len(matches) == 1, "failed binding Pod is absent or ambiguous")
    for pod in items:
        if pod is matches[0]:
            continue
        metadata = pod.get("metadata", {}) if isinstance(pod, dict) else {}
        labels = metadata.get("labels", {}) if isinstance(metadata, dict) else {}
        status = pod.get("status", {}) if isinstance(pod, dict) else {}
        require(isinstance(labels, dict) and isinstance(status, dict) and
                (labels.get("app.kubernetes.io/name") != "oce-journal-operator" or
                 (status.get("phase") not in ("Pending", "Running", "Unknown") and
                  not metadata.get("deletionTimestamp"))),
                "another operator Pod is active or terminating")
    pod = matches[0]
    cleanup.prove_pod(pod, intended, job_uid, pod_uid, operator)
    proof_hash, log_hash = proof_from_pod(namespace, pod, source_sha, name,
                                          uid, baseline[journal.BINDING_VERSION],
                                          identity, False)
    prove_bound_secret(operator, baseline, uid, bound_rv, identity)
    storage = cleanup.prove_retained_storage(operator)
    return {"name": name, "jobRv": job_rv, "baseline": baseline,
            "projection": projection, "projectionId": projection_id,
            "storage": storage, "jobHash": digest(target), "podHash": digest(pod),
            "proofHash": proof_hash, "logHash": log_hash}


def verify_without_cas(expected, run_id, attempt, old_name, old_uid,
                       uid, bound_rv, identity, config, operator, environ):
    """Create a normal binder Pod, but never call the runner's patch callback."""
    namespace = operator["namespace"]
    projection = journal.config_projection(config, expected, operator)
    baseline = journal.binding_secret_baseline(namespace)
    require(baseline[journal.BINDING_UID] == uid and
            baseline[journal.BINDING_VERSION] == bound_rv,
            "bound-only verifier Secret changed before Job creation")
    job = journal.build_job("bind-installation", expected, run_id, operator,
                            projection, attempt, baseline=baseline)
    name = job["metadata"]["name"]
    require(name != old_name, "bound-only verifier would reuse the failed Job")
    jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
    cleanup.prove_jobs(jobs.get("items") if isinstance(jobs, dict) else None,
                       old_name, old_uid)
    existing = [item for item in jobs["items"]
                if item.get("metadata", {}).get("name") == name]
    require(len(existing) <= 1, "bound-only verifier Job identity is ambiguous")
    journal.exact_main(expected, environ)
    journal.prove_or_create_projection(projection)
    projection_id = cleanup.prove_projection(projection)
    if not existing:
        journal.exact_main(expected, environ)
        try:
            journal.command(["kubectl", "--request-timeout=15s", "create", "-f", "-"],
                            body=json.dumps(job), timeout=30)
        except journal.Blocked:
            # A lost create response can mean a Job now exists. Never create twice.
            pass
    actual = journal.kubectl_json("-n", namespace, "get", "job", name, "-o=json")
    job_uid = actual.get("metadata", {}).get("uid") if isinstance(actual, dict) else None
    require(isinstance(job_uid, str) and journal.UID.fullmatch(job_uid) and
            journal.job_identity(actual, job) and
            not actual["metadata"].get("deletionTimestamp"),
            "bound-only verifier Job was not created from reviewed source")
    # The verifier Pod's JobBridge never patches the Secret. No call to
    # bind_proof_and_patch() or dispatch(ready=...) is permitted here.
    journal.command(["kubectl", "--request-timeout=15s", "-n", namespace,
                     "wait", "--for=condition=complete", "job/" + name,
                     "--timeout=35m"], timeout=2160)
    final = journal.kubectl_json("-n", namespace, "get", "job", name, "-o=json")
    conditions = final.get("status", {}).get("conditions") or []
    require(journal.job_identity(final, job) and
            final.get("metadata", {}).get("uid") == job_uid and
            final.get("status", {}).get("succeeded") == 1 and
            any(c.get("type") == "Complete" and c.get("status") == "True"
                for c in conditions) and
            not any(c.get("type") == "Failed" and c.get("status") == "True"
                    for c in conditions),
            "bound-only verifier Job completion is unproven")
    pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
    matches = cleanup.matching_pods(pods.get("items") if isinstance(pods, dict) else None,
                                    name, job_uid)
    require(len(matches) == 1, "bound-only verifier Pod is absent or ambiguous")
    pod = matches[0]
    pod_uid = pod.get("metadata", {}).get("uid")
    cleanup.prove_pod(pod, job, job_uid, pod_uid, operator, succeeded=True)
    proof_hash, log_hash = proof_from_pod(namespace, pod, expected, name,
                                          uid, bound_rv, identity, True)
    require(journal.binding_secret_baseline(namespace) == baseline,
            "bound-only verifier changed the startup Secret")
    return {"name": name, "jobUid": job_uid, "podUid": pod_uid,
            "jobHash": digest(final), "podHash": digest(pod),
            "proofHash": proof_hash, "logHash": log_hash,
            "projectionUid": projection_id[0], "projectionRv": projection_id[1]}


def receipt_object(expected, old, verifier, source_sha, run_id, attempt,
                   job_uid, pod_uid, uid, bound_rv, identity, namespace,
                   recovery_run_id, recovery_attempt):
    require(bool(cleanup.RUN_ID.fullmatch(recovery_run_id)) and
            bool(cleanup.ATTEMPT.fullmatch(recovery_attempt)),
            "recovery receipt run identity is invalid")
    name = ("oce-bound-bind-" + job_uid.replace("-", "")[:16] +
            "-" + recovery_run_id + "-" + recovery_attempt)
    require(len(name) <= 63, "recovery receipt name is invalid")
    data = {"schema": 1, "expectedSha": expected,
            "failed": {"sourceSha": source_sha, "runId": run_id,
                       "attempt": attempt, "jobUid": job_uid, "podUid": pod_uid,
                       "jobRv": old["jobRv"], "jobHash": old["jobHash"],
                       "podHash": old["podHash"], "proofHash": old["proofHash"],
                       "logHash": old["logHash"],
                       "projectionUid": old["projectionId"][0],
                       "projectionRv": old["projectionId"][1],
                       "storageHash": old["storage"]},
            "binding": {"secretUid": uid,
                        "originalRv": old["baseline"][journal.BINDING_VERSION],
                        "boundRv": bound_rv, "installationId": identity,
                        "candidateSha256": old["baseline"][journal.BINDING_DIGEST]},
            "verifier": verifier}
    return {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": namespace,
                         "labels": {"app.kubernetes.io/part-of": "openclaw-enterprise",
                                    "homelab.stuhlmuller.dev/stage": "bound-bind-recovery"}},
            "immutable": True,
            "data": {"receipt.json": json.dumps(data, sort_keys=True, separators=(",", ":"))}}


def prove_receipt(namespace, intended):
    actual = journal.kubectl_json("-n", namespace, "get", "configmap",
                                  intended["metadata"]["name"], "-o=json")
    metadata = actual.get("metadata", {}) if isinstance(actual, dict) else {}
    require(actual.get("kind") == "ConfigMap" and
            metadata.get("name") == intended["metadata"]["name"] and
            metadata.get("namespace") == namespace and
            metadata.get("labels") == intended["metadata"]["labels"] and
            isinstance(metadata.get("uid"), str) and
            journal.UID.fullmatch(metadata["uid"]) and
            isinstance(metadata.get("resourceVersion"), str) and
            RV.fullmatch(metadata["resourceVersion"]) and
            not metadata.get("deletionTimestamp") and
            not metadata.get("ownerReferences") and
            actual.get("immutable") is True and
            actual.get("data") == intended["data"] and
            not actual.get("binaryData"),
            "durable bound-binding recovery receipt differs from private proof")
    return metadata["uid"], metadata["resourceVersion"]


def save_receipt(expected, environ, intended, namespace):
    journal.exact_main(expected, environ)
    try:
        journal.command(["kubectl", "--request-timeout=15s", "create", "-f", "-"],
                        body=json.dumps(intended), timeout=30)
    except journal.Blocked:
        # A lost response or already-present exact receipt is resolved by readback.
        pass
    first = prove_receipt(namespace, intended)
    require(prove_receipt(namespace, intended) == first,
            "durable recovery receipt changed during readback")
    return first


def prove_old_absent(namespace, old_name, job_uid, pod_uid):
    """A completed recovery cannot coexist with an old or replacement writer."""
    jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
    items = jobs.get("items") if isinstance(jobs, dict) else None
    require(isinstance(items, list), "post-recovery Job list is invalid")
    for job in items:
        metadata = job.get("metadata", {}) if isinstance(job, dict) else {}
        name = metadata.get("name") if isinstance(metadata, dict) else None
        labels = metadata.get("labels") or {} if isinstance(metadata, dict) else {}
        require(name != old_name and metadata.get("uid") != job_uid,
                "failed binding Job is present or was replaced")
        if not (isinstance(name, str) and name.startswith("oce-journal-") or
                isinstance(labels, dict) and
                labels.get("app.kubernetes.io/name") == "oce-journal-operator"):
            continue
        match = journal.JOB_NAME.fullmatch(name) if isinstance(name, str) else None
        status = job.get("status", {}) if isinstance(job, dict) else {}
        conditions = status.get("conditions") or [] if isinstance(status, dict) else []
        require(bool(match) and isinstance(labels, dict) and
                labels.get("app.kubernetes.io/name") == "oce-journal-operator" and
                labels.get("homelab.stuhlmuller.dev/stage") == match.group(1) and
                bool(journal.SHA.fullmatch(
                    labels.get("homelab.stuhlmuller.dev/source-sha", ""))) and
                not metadata.get("deletionTimestamp") and
                isinstance(status, dict) and status.get("active") in (None, 0) and
                any(isinstance(c, dict) and c.get("type") == "Complete" and
                    c.get("status") == "True" for c in conditions) and
                not any(isinstance(c, dict) and c.get("type") == "Failed" and
                        c.get("status") == "True" for c in conditions),
                "another operator Job is failed, active or ambiguous")
    pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
    pod_items = pods.get("items") if isinstance(pods, dict) else None
    require(isinstance(pod_items, list) and
            not cleanup.matching_pods(pod_items, old_name, job_uid),
            "failed binding Pod remains after recovery")
    for pod in pod_items:
        metadata = pod.get("metadata", {}) if isinstance(pod, dict) else {}
        labels = metadata.get("labels") or {} if isinstance(metadata, dict) else {}
        status = pod.get("status", {}) if isinstance(pod, dict) else {}
        require(metadata.get("uid") != pod_uid and
                isinstance(labels, dict) and isinstance(status, dict) and
                (labels.get("app.kubernetes.io/name") != "oce-journal-operator" or
                 (status.get("phase") not in ("Pending", "Running", "Unknown") and
                  not metadata.get("deletionTimestamp"))),
                "old or active operator Pod remains after recovery")
    return items, pod_items


def completed_receipts(namespace, source_sha, run_id, attempt, job_uid,
                       pod_uid, uid, bound_rv, identity):
    prefix = "oce-bound-bind-" + job_uid.replace("-", "")[:16] + "-"
    listing = journal.kubectl_json("-n", namespace, "get", "configmaps", "-o=json")
    items = listing.get("items") if isinstance(listing, dict) else None
    require(isinstance(items, list), "bound recovery receipt list is invalid")
    found = []
    seen = set()
    for item in items:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if not (isinstance(name, str) and name.startswith(prefix)):
            continue
        suffix = name[len(prefix):]
        match = re.fullmatch(r"([1-9][0-9]{0,19})-([1-9][0-9]{0,4})", suffix)
        require(bool(match) and name not in seen,
                "bound recovery receipt name is ambiguous")
        seen.add(name)
        data = item.get("data") if isinstance(item, dict) else None
        require(isinstance(data, dict) and set(data) == {"receipt.json"} and
                isinstance(data["receipt.json"], str),
                "bound recovery receipt data is incomplete")
        try:
            receipt = json.loads(data["receipt.json"])
        except ValueError:
            raise journal.Blocked("bound recovery receipt is invalid") from None
        require(isinstance(receipt, dict) and set(receipt) == {
            "schema", "expectedSha", "failed", "binding", "verifier"} and
            type(receipt["schema"]) is int and receipt["schema"] == 1 and
            isinstance(receipt["expectedSha"], str) and
            journal.SHA.fullmatch(receipt["expectedSha"]),
            "bound recovery receipt schema is invalid")
        failed, binding, verifier = (receipt["failed"], receipt["binding"],
                                     receipt["verifier"])
        require(isinstance(failed, dict) and set(failed) == {
            "sourceSha", "runId", "attempt", "jobUid", "podUid", "jobRv",
            "jobHash", "podHash", "proofHash", "logHash", "projectionUid",
            "projectionRv", "storageHash"} and
            isinstance(binding, dict) and set(binding) == {
                "secretUid", "originalRv", "boundRv", "installationId",
                "candidateSha256"} and
            isinstance(verifier, dict) and set(verifier) == {
                "name", "jobUid", "podUid", "jobHash", "podHash",
                "proofHash", "logHash", "projectionUid", "projectionRv"} and
            failed["sourceSha"] == source_sha and failed["runId"] == run_id and
            failed["attempt"] == attempt and failed["jobUid"] == job_uid and
            failed["podUid"] == pod_uid and
            binding["secretUid"] == uid and binding["boundRv"] == bound_rv and
            binding["installationId"] == identity and
            bool(RV.fullmatch(failed["jobRv"])) and
            bool(RV.fullmatch(failed["projectionRv"])) and
            bool(RV.fullmatch(binding["originalRv"])) and
            bool(RV.fullmatch(verifier["projectionRv"])) and
            binding["originalRv"] != bound_rv and
            all(isinstance(value, str) and HASH.fullmatch(value) for value in (
                failed["jobHash"], failed["podHash"], failed["proofHash"],
                failed["logHash"], failed["storageHash"],
                binding["candidateSha256"], verifier["jobHash"],
                verifier["podHash"], verifier["proofHash"], verifier["logHash"])) and
            all(isinstance(value, str) and journal.UID.fullmatch(value) for value in (
                failed["projectionUid"], verifier["jobUid"], verifier["podUid"],
                verifier["projectionUid"])) and
            isinstance(verifier["name"], str) and
            VERIFIER_NAME.fullmatch(verifier["name"]) and
            VERIFIER_NAME.fullmatch(verifier["name"]).group(1) == match.group(1) and
            VERIFIER_NAME.fullmatch(verifier["name"]).group(2) == match.group(2),
            "bound recovery receipt identities differ from the failed binding")
        old = {"jobRv": failed["jobRv"], "jobHash": failed["jobHash"],
               "podHash": failed["podHash"], "proofHash": failed["proofHash"],
               "logHash": failed["logHash"], "storage": failed["storageHash"],
               "projectionId": (failed["projectionUid"], failed["projectionRv"]),
               "baseline": {
                   journal.BINDING_VERSION: binding["originalRv"],
                   journal.BINDING_DIGEST: binding["candidateSha256"]}}
        intended = receipt_object(receipt["expectedSha"], old, verifier,
                                  source_sha, run_id, attempt, job_uid, pod_uid,
                                  uid, bound_rv, identity, namespace,
                                  match.group(1), match.group(2))
        require(item.get("kind") == "ConfigMap" and
                item.get("immutable") is True and
                metadata.get("labels") == intended["metadata"]["labels"] and
                item.get("data") == intended["data"] and
                not item.get("binaryData"),
                "bound recovery receipt list entry differs from exact receipt")
        receipt_id = prove_receipt(namespace, intended)
        require(receipt_id == (metadata.get("uid"), metadata.get("resourceVersion")),
                "bound recovery receipt changed during readback")
        found.append((receipt, intended, receipt_id))
    require(found, "bound recovery has no durable private receipt")
    return found


def prove_completed_recovery(expected, source_sha, run_id, attempt, job_uid,
                             pod_uid, uid, bound_rv, identity, config,
                             operator, environ):
    """Resolve a canceled post-DELETE run with reads only; never re-create/delete."""
    namespace = operator["namespace"]
    old_name = f"oce-journal-bind-installation-{run_id}-{attempt}"
    prove_old_absent(namespace, old_name, job_uid, pod_uid)
    receipts = completed_receipts(namespace, source_sha, run_id, attempt,
                                  job_uid, pod_uid, uid, bound_rv, identity)
    for receipt, intended_receipt, receipt_id in receipts:
        prior = receipt["expectedSha"]
        cleanup.source_contract(expected, prior)
        failed, binding, verifier = (receipt["failed"], receipt["binding"],
                                     receipt["verifier"])
        baseline = {journal.BINDING_UID: uid,
                    journal.BINDING_VERSION: binding["originalRv"],
                    journal.BINDING_DIGEST: binding["candidateSha256"],
                    journal.BINDING_IMMUTABLE: "true"}
        prove_bound_secret(operator, baseline, uid, bound_rv, identity)
        require(cleanup.prove_retained_storage(operator) == failed["storageHash"],
                "retained storage changed after completed recovery")
        historical_projection = journal.config_projection(config, source_sha, operator)
        require(cleanup.prove_projection(historical_projection) ==
                (failed["projectionUid"], failed["projectionRv"]),
                "failed binding source projection changed after recovery")
        projection = journal.config_projection(config, prior, operator)
        require(cleanup.prove_projection(projection) ==
                (verifier["projectionUid"], verifier["projectionRv"]),
                "bound-only verifier projection changed after recovery")
        name_match = VERIFIER_NAME.fullmatch(verifier["name"])
        bound_baseline = {**baseline, journal.BINDING_VERSION: bound_rv}
        intended_job = journal.build_job("bind-installation", prior,
                                         name_match.group(1), operator, projection,
                                         name_match.group(2), baseline=bound_baseline)
        require(intended_job["metadata"]["name"] == verifier["name"],
                "bound-only verifier name changed after recovery")
        actual = journal.kubectl_json("-n", namespace, "get", "job",
                                      verifier["name"], "-o=json")
        conditions = actual.get("status", {}).get("conditions") or []
        require(journal.job_identity(actual, intended_job) and
                actual.get("metadata", {}).get("uid") == verifier["jobUid"] and
                not actual.get("metadata", {}).get("deletionTimestamp") and
                actual.get("status", {}).get("succeeded") == 1 and
                any(c.get("type") == "Complete" and c.get("status") == "True"
                    for c in conditions) and
                not any(c.get("type") == "Failed" and c.get("status") == "True"
                        for c in conditions) and
                digest(actual) == verifier["jobHash"],
                "bound-only verifier Job identity or outcome changed")
        pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
        matches = cleanup.matching_pods(
            pods.get("items") if isinstance(pods, dict) else None,
            verifier["name"], verifier["jobUid"])
        require(len(matches) == 1 and
                matches[0].get("metadata", {}).get("uid") == verifier["podUid"],
                "bound-only verifier Pod was replaced or removed")
        pod = matches[0]
        cleanup.prove_pod(pod, intended_job, verifier["jobUid"],
                          verifier["podUid"], operator, succeeded=True)
        proof_hash, log_hash = proof_from_pod(namespace, pod, prior,
                                              verifier["name"], uid, bound_rv,
                                              identity, True)
        require(digest(pod) == verifier["podHash"] and
                proof_hash == verifier["proofHash"] and
                log_hash == verifier["logHash"] and
                prove_receipt(namespace, intended_receipt) == receipt_id,
                "bound-only verifier proof or recovery receipt changed")
        prove_bound_secret(operator, baseline, uid, bound_rv, identity)
        require(cleanup.prove_retained_storage(operator) == failed["storageHash"] and
                cleanup.prove_projection(historical_projection) ==
                (failed["projectionUid"], failed["projectionRv"]) and
                cleanup.prove_projection(projection) ==
                (verifier["projectionUid"], verifier["projectionRv"]),
                "retained source or storage changed during completed recovery proof")
    prove_old_absent(namespace, old_name, job_uid, pod_uid)
    require(completed_receipts(namespace, source_sha, run_id, attempt,
                               job_uid, pod_uid, uid, bound_rv, identity) == receipts,
            "bound recovery receipts changed during completed proof")
    journal.exact_main(expected, environ)


def observe_delete(namespace, old_name, job_uid, pod_uid, operator, old,
                   uid, bound_rv, identity, receipt, receipt_id):
    for _ in range(30):
        jobs = journal.kubectl_json("-n", namespace, "get", "jobs", "-o=json")
        items = jobs.get("items") if isinstance(jobs, dict) else None
        require(isinstance(items, list), "post-delete Job list is invalid")
        named = [job for job in items if job.get("metadata", {}).get("name") == old_name]
        require(len(named) <= 1 and
                (not named or named[0].get("metadata", {}).get("uid") == job_uid),
                "failed binding Job was replaced during deletion")
        pods = journal.kubectl_json("-n", namespace, "get", "pods", "-o=json")
        matches = cleanup.matching_pods(pods.get("items") if isinstance(pods, dict) else None,
                                        old_name, job_uid)
        require(all(pod.get("metadata", {}).get("uid") == pod_uid for pod in matches),
                "failed binding Pod was replaced during deletion")
        prove_bound_secret(operator, old["baseline"], uid, bound_rv, identity)
        require(cleanup.prove_projection(old["projection"]) == old["projectionId"] and
                cleanup.prove_retained_storage(operator) == old["storage"] and
                prove_receipt(namespace, receipt) == receipt_id,
                "retained recovery state changed during deletion")
        if not named and not matches:
            return
        time.sleep(2)
    raise journal.Blocked("failed binding foreground deletion remains incomplete")


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    try:
        require(len(argv) == 8, "bound recovery requires exact failed binding reference")
        source_sha, run_id, attempt, job_uid, pod_uid, uid, bound_rv, identity = argv
        require(bool(journal.SHA.fullmatch(source_sha)) and
                bool(cleanup.RUN_ID.fullmatch(run_id)) and
                bool(cleanup.ATTEMPT.fullmatch(attempt)) and
                bool(journal.UID.fullmatch(job_uid)) and
                bool(journal.UID.fullmatch(pod_uid)) and
                bool(journal.UID.fullmatch(uid)) and
                bool(RV.fullmatch(bound_rv)) and
                bool(INSTALLATION_ID.fullmatch(identity)),
                "bound recovery reference is invalid")
        expected = environ.get("EXPECTED_SHA", "")
        journal.exact_main(expected, environ)
        cleanup.source_contract(expected, source_sha)
        own = "scripts/ci/openclaw-enterprise-recover-bound-bind.py"
        require(journal.command(["git", "show", expected + ":" + own]) ==
                (ROOT / own).read_text(), "bound recovery source differs from current main")
        journal.prove_committed_inputs(expected)
        config = json.loads(journal.CONFIG.read_text())
        operator = journal.contract(config, "bind-installation", expected)
        journal.prove_image_source(operator, expected)
        journal.prove_claims(operator)
        old_name = f"oce-journal-bind-installation-{run_id}-{attempt}"
        jobs = journal.kubectl_json("-n", operator["namespace"], "get", "jobs", "-o=json")
        items = jobs.get("items") if isinstance(jobs, dict) else None
        require(isinstance(items, list), "failed binding Job list is invalid")
        if not any(item.get("metadata", {}).get("name") == old_name
                   for item in items):
            prove_completed_recovery(expected, source_sha, run_id, attempt,
                                     job_uid, pod_uid, uid, bound_rv, identity,
                                     config, operator, environ)
            print("Bound Installation final state verified from private receipt")
            return 0
        first = prove_failed_source(source_sha, run_id, attempt, job_uid, pod_uid,
                                    uid, bound_rv, identity, config, operator)
        second = prove_failed_source(source_sha, run_id, attempt, job_uid, pod_uid,
                                     uid, bound_rv, identity, config, operator)
        require(first == second, "failed binding state changed between checks")
        verifier = verify_without_cas(expected, environ.get("GITHUB_RUN_ID", ""),
                                      environ.get("GITHUB_RUN_ATTEMPT", ""),
                                      first["name"], job_uid, uid, bound_rv,
                                      identity, config, operator, environ)
        final = prove_failed_source(source_sha, run_id, attempt, job_uid, pod_uid,
                                    uid, bound_rv, identity, config, operator)
        require(final == first, "failed binding state changed during verification")
        receipt = receipt_object(expected, first, verifier, source_sha, run_id,
                                 attempt, job_uid, pod_uid, uid, bound_rv,
                                 identity, operator["namespace"],
                                 environ.get("GITHUB_RUN_ID", ""),
                                 environ.get("GITHUB_RUN_ATTEMPT", ""))
        receipt_id = save_receipt(expected, environ, receipt, operator["namespace"])
        require(prove_failed_source(source_sha, run_id, attempt, job_uid, pod_uid,
                                    uid, bound_rv, identity, config, operator) == first and
                prove_receipt(operator["namespace"], receipt) == receipt_id,
                "failed binding or recovery receipt changed before deletion")
        accepted = cleanup.delete_once(operator["namespace"], first["name"],
                                       job_uid, first["jobRv"], expected, environ)
        observe_delete(operator["namespace"], first["name"], job_uid, pod_uid,
                       operator, first, uid, bound_rv, identity, receipt, receipt_id)
        require(accepted or prove_receipt(operator["namespace"], receipt) == receipt_id,
                "failed binding DELETE outcome is uncertain")
    except (journal.Blocked, OSError, ValueError, KeyError, TypeError, AttributeError,
            subprocess.SubprocessError):
        print("Bound Installation recovery blocked; private diagnostics withheld", file=sys.stderr)
        return 1
    print("Bound Installation verified; failed Job removed; private receipt retained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
