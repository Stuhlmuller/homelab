#!/usr/bin/env python3
"""Dispatch one source-bound Enterprise Job; never stream its private output."""

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "scripts/config/openclaw-enterprise.json"
STAGES = {"reconcile": "reconcile", "stop": "stop", "verification": "verify"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
UID = re.compile(r"[0-9a-f-]{36}\Z")
IMAGE = re.compile(r"harbor\.stinkyboi\.com/homelab/homelab-oce-operator@sha256:[0-9a-f]{64}\Z")
NODE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
JOB_NAME = re.compile(r"oce-journal-(reconcile|stop|verification)-[1-9][0-9]{0,19}-[1-9][0-9]{0,4}\Z")


class Blocked(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def command(args, *, body=None, timeout=30):
    try:
        result = subprocess.run(args, input=body, text=True, capture_output=True,
                                timeout=timeout, cwd=ROOT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Blocked("operator control read or write is unavailable") from None
    if result.returncode:
        raise Blocked("operator control read or write failed")
    if len(result.stdout) > 4 * 1048576:
        raise Blocked("operator control response is oversized")
    return result.stdout


def kubectl_json(*args):
    try:
        return json.loads(command(["kubectl", "--request-timeout=15s", *args]))
    except ValueError:
        raise Blocked("operator Kubernetes response is invalid JSON") from None


def exact_main(expected, environ):
    require(bool(SHA.fullmatch(expected)) and environ.get("GITHUB_ACTIONS") == "true" and
            environ.get("GITHUB_REPOSITORY") == "Stuhlmuller/homelab" and
            environ.get("GITHUB_REF") == "refs/heads/main" and
            environ.get("GITHUB_SHA") == expected,
            "operator requires the exact protected main dispatch")
    require(command(["git", "rev-parse", "HEAD"]).strip() == expected,
            "operator checkout changed")
    require(command(["git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                     "refs/heads/main"]).split() == [expected, "refs/heads/main"],
            "operator dispatch is no longer current main")


def prove_committed_inputs(expected):
    for name in ("scripts/config/openclaw-enterprise.json",
                 "scripts/openclaw-enterprise.py",
                 "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
                 "clusters/homelab/apps/openclaw-enterprise/values.yaml"):
        require(command(["git", "show", expected + ":" + name]) ==
                (ROOT / name).read_text(),
                "operator current-main source differs from checkout")


def contract(config, stage, expected):
    require(config.get("schemaVersion") == 1 and
            config.get("privateJournal") == {
                "required": True, "sourceBound": True, "durable": True,
                "mountPath": "/private/openclaw-enterprise/journal.json",
                "mode": "0600", "lockRequired": True},
            "operator journal contract changed")
    operator = config.get("journalOperator")
    require(isinstance(operator, dict) and set(operator) == {
        "enabled", "namespace", "serviceAccount", "journalClaim", "journalClaimUid",
        "journalVolumeUid", "journalPath", "bootstrapClaim", "bootstrapClaimUid",
        "node", "runAsUser", "image", "imageSourceSha"},
        "operator declaration is invalid")
    require(operator["enabled"] is True, "operator remains disabled pending placement and credential proofs")
    require(operator["namespace"] == "openclaw-system" and
            operator["serviceAccount"] == "oce-journal-operator" and
            operator["journalClaim"] == "occ-operator-journal" and
            operator["bootstrapClaim"] == "occ-bootstrap-admin-password" and
            type(operator["runAsUser"]) is int and operator["runAsUser"] == 10001 and
            isinstance(operator["journalClaimUid"], str) and
            UID.fullmatch(operator["journalClaimUid"]) and
            isinstance(operator["journalVolumeUid"], str) and
            UID.fullmatch(operator["journalVolumeUid"]) and
            isinstance(operator["bootstrapClaimUid"], str) and
            UID.fullmatch(operator["bootstrapClaimUid"]) and
            isinstance(operator["node"], str) and NODE.fullmatch(operator["node"]) and
            isinstance(operator["journalPath"], str) and
            operator["journalPath"].startswith("/var/lib/openclaw-enterprise/") and
            ".." not in Path(operator["journalPath"]).parts and
            isinstance(operator["image"], str) and IMAGE.fullmatch(operator["image"]) and
            isinstance(operator["imageSourceSha"], str) and
            SHA.fullmatch(operator["imageSourceSha"]),
            "operator placement or pinned source is incomplete")
    require(stage != "reconcile" or config.get("activationEnabled") is False,
            "active reconciliation needs a separate model credential handoff")
    return operator


def prove_image_source(operator, expected):
    source = operator["imageSourceSha"]
    command(["git", "merge-base", "--is-ancestor", source, expected])
    # These are the only repository files the embedded reconciler reads.
    for name in ("scripts/openclaw-enterprise.py",
                 "clusters/homelab/apps/openclaw-enterprise/installation.yaml",
                 "clusters/homelab/apps/openclaw-enterprise/values.yaml"):
        require(command(["git", "show", source + ":" + name]) ==
                (ROOT / name).read_text(),
                "operator image source differs from current reviewed logic")


def config_projection(config, expected, operator):
    # Use the committed bytes, not a reserialization that might change a hash.
    encoded = CONFIG.read_text()
    require(json.loads(encoded) == config, "operator reviewed config changed")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    receipt = {"expectedSha": expected, "imageSourceSha": operator["imageSourceSha"],
               "configSha256": digest}
    name = "oce-journal-config-" + expected
    labels = {"app.kubernetes.io/name": "oce-journal-operator-config",
              "homelab.stuhlmuller.dev/source-sha": expected}
    return {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": operator["namespace"], "labels": labels},
            "immutable": True,
            "data": {"openclaw-enterprise.json": encoded,
                     "receipt.json": json.dumps(receipt, sort_keys=True, separators=(",", ":"))}}


def prove_or_create_projection(projection):
    namespace = projection["metadata"]["namespace"]
    name = projection["metadata"]["name"]
    listing = kubectl_json("-n", namespace, "get", "configmaps", "-l",
                           "app.kubernetes.io/name=oce-journal-operator-config", "-o=json")
    require(isinstance(listing.get("items"), list), "operator source projection list is invalid")
    for item in listing["items"]:
        if item.get("metadata", {}).get("name") == name:
            require(item.get("metadata", {}).get("labels") == projection["metadata"]["labels"] and
                    item.get("immutable") is True and item.get("data") == projection["data"],
                    "operator source projection changed")
            return
    command(["kubectl", "--request-timeout=15s", "create", "-f", "-"],
            body=json.dumps(projection), timeout=30)


def prove_claims(operator):
    namespace = operator["namespace"]
    journal = kubectl_json("-n", namespace, "get", "pvc", operator["journalClaim"], "-o=json")
    bootstrap = kubectl_json("-n", namespace, "get", "pvc", operator["bootstrapClaim"], "-o=json")
    require(journal.get("metadata", {}).get("uid") == operator["journalClaimUid"] and
            journal.get("status", {}).get("phase") == "Bound" and
            journal.get("spec", {}).get("volumeName") == operator["journalClaim"] and
            journal.get("spec", {}).get("storageClassName") == "openclaw-enterprise-journal-local" and
            journal.get("spec", {}).get("accessModes") == ["ReadWriteOnce"] and
            bootstrap.get("metadata", {}).get("uid") == operator["bootstrapClaimUid"] and
            bootstrap.get("status", {}).get("phase") == "Bound" and
            bootstrap.get("spec", {}).get("storageClassName") == "openclaw-enterprise-bootstrap-local" and
            bootstrap.get("spec", {}).get("accessModes") == ["ReadWriteOnce"] and
            isinstance(bootstrap.get("spec", {}).get("volumeName"), str) and
            bool(NODE.fullmatch(bootstrap["spec"]["volumeName"])) and
            len(bootstrap["spec"]["volumeName"]) <= 253,
            "operator claim identity or binding changed")
    volume = kubectl_json("get", "pv", operator["journalClaim"], "-o=json")
    bootstrap_volume = kubectl_json("get", "pv", bootstrap["spec"]["volumeName"], "-o=json")
    terms = volume.get("spec", {}).get("nodeAffinity", {}).get("required", {}).get("nodeSelectorTerms")
    expected_terms = [{"matchExpressions": [{"key": "kubernetes.io/hostname",
                                              "operator": "In", "values": [operator["node"]]}]}]
    require(volume.get("metadata", {}).get("uid") == operator["journalVolumeUid"] and
            volume.get("spec", {}).get("claimRef", {}).get("uid") == operator["journalClaimUid"] and
            volume.get("spec", {}).get("claimRef", {}).get("namespace") == namespace and
            volume.get("spec", {}).get("claimRef", {}).get("name") == operator["journalClaim"] and
            volume.get("spec", {}).get("persistentVolumeReclaimPolicy") == "Retain" and
            volume.get("spec", {}).get("storageClassName") == "openclaw-enterprise-journal-local" and
            volume.get("spec", {}).get("hostPath") == {
                "path": operator["journalPath"], "type": "Directory"} and terms == expected_terms,
            "operator retained volume identity or placement changed")
    require(bootstrap_volume.get("metadata", {}).get("name") == bootstrap["spec"]["volumeName"] and
            bootstrap_volume.get("spec", {}).get("claimRef", {}).get("uid") ==
            operator["bootstrapClaimUid"] and
            bootstrap_volume.get("spec", {}).get("claimRef", {}).get("namespace") == namespace and
            bootstrap_volume.get("spec", {}).get("claimRef", {}).get("name") ==
            operator["bootstrapClaim"] and
            bootstrap_volume.get("spec", {}).get("persistentVolumeReclaimPolicy") == "Retain" and
            bootstrap_volume.get("spec", {}).get("storageClassName") ==
            "openclaw-enterprise-bootstrap-local" and
            bootstrap_volume.get("spec", {}).get("hostPath", {}).get("type") == "Directory" and
            bootstrap_volume.get("spec", {}).get("nodeAffinity", {}).get("required", {}).get(
                "nodeSelectorTerms") == expected_terms,
            "operator bootstrap volume identity or placement changed")


def build_job(stage, expected, run_id, operator, projection, attempt="1"):
    require(stage in STAGES and re.fullmatch(r"[1-9][0-9]{0,19}", run_id) and
            re.fullmatch(r"[1-9][0-9]{0,4}", attempt),
            "operator stage, run ID or attempt is invalid")
    name = f"oce-journal-{stage}-{run_id}-{attempt}"
    require(len(name) <= 63, "operator Job name is too long")
    labels = {"app.kubernetes.io/name": "oce-journal-operator",
              "homelab.stuhlmuller.dev/source-sha": expected,
              "homelab.stuhlmuller.dev/stage": stage}
    receipt = json.loads(projection["data"]["receipt.json"])
    require(receipt["expectedSha"] == expected and
            receipt["imageSourceSha"] == operator["imageSourceSha"] and
            receipt["configSha256"] == hashlib.sha256(
                projection["data"]["openclaw-enterprise.json"].encode()).hexdigest(),
            "operator projected source receipt changed")
    args = [STAGES[stage], "--config", "/etc/oce-operator-config/openclaw-enterprise.json",
            "--expected-sha", expected, "--operator-source-sha",
            operator["imageSourceSha"], "--reviewed-config-sha256", receipt["configSha256"]]
    if stage != "verification":
        args += ["--credential-file",
                 "/private/openclaw-enterprise/bootstrap/initial-admin-service-key.json"]
    return {"apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": name, "namespace": operator["namespace"], "labels": labels},
            "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 1800,
                     "template": {"metadata": {"labels": labels}, "spec": {
                         "serviceAccountName": operator["serviceAccount"],
                         "automountServiceAccountToken": False,
                         "restartPolicy": "Never",
                         "nodeSelector": {"kubernetes.io/hostname": operator["node"]},
                         "securityContext": {"runAsUser": operator["runAsUser"],
                                             "runAsGroup": operator["runAsUser"],
                                             "runAsNonRoot": True,
                                             "seccompProfile": {"type": "RuntimeDefault"}},
                         "containers": [{"name": "operator", "image": operator["image"],
                                         "imagePullPolicy": "IfNotPresent",
                                         "command": ["python3", "-I",
                                                     "/opt/homelab/scripts/openclaw-enterprise.py"],
                                         "args": args,
                                         "env": [{"name": "KUBECONFIG",
                                                  "value": "/etc/oce-operator-kubeconfig/config"}],
                                         "terminationMessagePath": "/dev/termination-log",
                                         "terminationMessagePolicy": "File",
                                         "securityContext": {"allowPrivilegeEscalation": False,
                                                             "readOnlyRootFilesystem": True,
                                                             "capabilities": {"drop": ["ALL"]}},
                                         "resources": {"requests": {"cpu": "25m", "memory": "64Mi"},
                                                       "limits": {"cpu": "250m", "memory": "256Mi"}},
                                         "volumeMounts": [
                                             {"name": "journal", "mountPath": "/private/openclaw-enterprise"},
                                             {"name": "bootstrap", "mountPath":
                                              "/private/openclaw-enterprise/bootstrap",
                                              "readOnly": True},
                                             {"name": "kubeconfig", "mountPath":
                                              "/etc/oce-operator-kubeconfig", "readOnly": True},
                                             {"name": "config", "mountPath":
                                              "/etc/oce-operator-config", "readOnly": True},
                                             {"name": "api", "mountPath":
                                              "/var/run/oce-operator-api", "readOnly": True}]}],
                         "volumes": [
                             {"name": "journal", "persistentVolumeClaim": {
                                 "claimName": operator["journalClaim"]}},
                             {"name": "bootstrap", "persistentVolumeClaim": {
                                 "claimName": operator["bootstrapClaim"], "readOnly": True}},
                             {"name": "kubeconfig", "configMap": {
                                 "name": "oce-journal-operator-kubeconfig", "defaultMode": 292}},
                             {"name": "config", "configMap": {
                                 "name": projection["metadata"]["name"], "defaultMode": 292}},
                             {"name": "api", "projected": {"sources": [
                                 {"serviceAccountToken": {"path": "token",
                                                          "expirationSeconds": 3600}},
                                 {"configMap": {"name": "kube-root-ca.crt", "items": [
                                     {"key": "ca.crt", "path": "ca.crt"}]}}]}}]}}}}


def job_identity(actual, intended):
    spec = actual.get("spec", {})
    template = spec.get("template", {})
    pod = template.get("spec", {})
    wanted = intended["spec"]["template"]["spec"]
    labels = template.get("metadata", {}).get("labels", {})
    expected_labels = intended["spec"]["template"]["metadata"]["labels"]
    allowed_labels = set(expected_labels) | {"batch.kubernetes.io/controller-uid",
                                              "batch.kubernetes.io/job-name",
                                              "controller-uid", "job-name"}
    containers = pod.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        return False
    container = containers[0]
    expected_container = wanted["containers"][0]
    return (actual.get("metadata", {}).get("name") == intended["metadata"]["name"] and
            actual.get("metadata", {}).get("labels") == intended["metadata"]["labels"] and
            isinstance(labels, dict) and set(labels) <= allowed_labels and
            all(labels.get(key) == value for key, value in expected_labels.items()) and
            spec.get("backoffLimit") == 0 and spec.get("activeDeadlineSeconds") == 1800 and
            pod.get("serviceAccountName") == wanted["serviceAccountName"] and
            pod.get("nodeSelector") == wanted["nodeSelector"] and
            pod.get("automountServiceAccountToken") is False and
            pod.get("restartPolicy") == "Never" and
            pod.get("securityContext") == wanted["securityContext"] and
            not pod.get("hostNetwork") and not pod.get("hostPID") and
            not pod.get("hostIPC") and not pod.get("shareProcessNamespace") and
            not pod.get("nodeName") and not pod.get("hostUsers") and
            not pod.get("tolerations") and not pod.get("hostAliases") and
            not pod.get("dnsConfig") and not pod.get("runtimeClassName") and
            pod.get("dnsPolicy") in (None, "ClusterFirst") and
            pod.get("schedulerName") in (None, "default-scheduler") and
            not pod.get("initContainers") and not pod.get("ephemeralContainers") and
            all(container.get(key) == expected_container[key] for key in
                ("name", "image", "imagePullPolicy", "command", "args", "env",
                 "securityContext", "resources", "terminationMessagePath",
                 "terminationMessagePolicy",
                 "volumeMounts")) and
            not container.get("envFrom") and not container.get("lifecycle") and
            not container.get("ports") and
            pod.get("volumes") == wanted["volumes"])


def dispatch(job):
    namespace = job["metadata"]["namespace"]
    name = job["metadata"]["name"]
    listing = kubectl_json("-n", namespace, "get", "jobs", "-o=json")
    require(isinstance(listing.get("items"), list), "operator Job list is invalid")
    existing = None
    for item in listing["items"]:
        metadata = item.get("metadata", {})
        item_name = metadata.get("name", "")
        labels = metadata.get("labels") or {}
        if not (item_name.startswith("oce-journal-") or
                labels.get("app.kubernetes.io/name") == "oce-journal-operator"):
            continue
        match = JOB_NAME.fullmatch(item_name)
        require(bool(match) and
                labels.get("app.kubernetes.io/name") == "oce-journal-operator" and
                labels.get("homelab.stuhlmuller.dev/stage") == match.group(1) and
                bool(SHA.fullmatch(labels.get("homelab.stuhlmuller.dev/source-sha", ""))),
                "operator Job identity is ambiguous")
        conditions = item.get("status", {}).get("conditions") or []
        complete = any(entry.get("type") == "Complete" and entry.get("status") == "True"
                       for entry in conditions)
        failed = any(entry.get("type") == "Failed" and entry.get("status") == "True"
                     for entry in conditions)
        require(not failed, "prior operator Job failed; inspect private state before retry")
        require(complete or item_name == name,
                "another operator Job is still running or uncertain")
        if item_name == name:
            require(job_identity(item, job), "existing operator Job identity changed")
            existing = item
    if existing is None:
        command(["kubectl", "--request-timeout=15s", "create", "-f", "-"],
                body=json.dumps(job), timeout=30)
    if existing is None or not any(
            entry.get("type") == "Complete" and entry.get("status") == "True"
            for entry in existing.get("status", {}).get("conditions") or []):
        command(["kubectl", "--request-timeout=15s", "-n", namespace,
                 "wait", "--for=condition=complete", "job/" + name,
                 "--timeout=35m"], timeout=2160)
    final = kubectl_json("-n", namespace, "get", "job", name, "-o=json")
    require(job_identity(final, job) and final.get("status", {}).get("succeeded") == 1 and
            any(entry.get("type") == "Complete" and entry.get("status") == "True"
                for entry in final.get("status", {}).get("conditions") or []),
            "operator Job completion is unproven")


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    try:
        require(len(argv) == 1 and argv[0] in STAGES, "unsupported operator stage")
        stage = argv[0]
        expected = environ.get("EXPECTED_SHA", "")
        exact_main(expected, environ)
        prove_committed_inputs(expected)
        config = json.loads(CONFIG.read_text())
        operator = contract(config, stage, expected)
        prove_image_source(operator, expected)
        prove_claims(operator)
        projection = config_projection(config, expected, operator)
        exact_main(expected, environ)
        prove_or_create_projection(projection)
        job = build_job(stage, expected, environ.get("GITHUB_RUN_ID", ""),
                        operator, projection, environ.get("GITHUB_RUN_ATTEMPT", ""))
        exact_main(expected, environ)
        dispatch(job)
    except (Blocked, OSError, ValueError, KeyError, TypeError):
        print("Enterprise operator blocked; private diagnostics withheld", file=sys.stderr)
        return 1
    print("Enterprise operator Job completed; private diagnostics withheld")
    return 0


if __name__ == "__main__":
    sys.exit(main())
