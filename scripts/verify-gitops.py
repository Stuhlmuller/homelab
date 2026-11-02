#!/usr/bin/env python3
"""Read-only, revision-bound Argo CD and Deployment evidence; no functional acceptance."""

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import time

REPOSITORIES = {"https://github.com/Stuhlmuller/homelab", "https://github.com/Stuhlmuller/homelab.git"}
NAME = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"(?:^|[@/])(sha256:[0-9a-f]{64})\Z")
REVISION = "deployment.kubernetes.io/revision"


class Failure(ValueError):
    """Only fixed, public failure codes cross the CLI output boundary."""


def require(condition, code):
    if not condition:
        raise Failure(code)


def identity(item, kind, namespace, name):
    meta = item["metadata"]
    require(NAME.fullmatch(name) and NAME.fullmatch(namespace)
            and item["kind"] == kind and meta["name"] == name and meta["namespace"] == namespace
            and not meta.get("deletionTimestamp"), "resource_identity")
    require(isinstance(meta.get("uid"), str) and re.fullmatch(r"[0-9a-f-]{36}", meta["uid"])
            and isinstance(meta.get("resourceVersion"), str)
            and meta["resourceVersion"].isdigit(), "resource_identity")
    return {key: meta[key] for key in ("namespace", "name", "uid", "resourceVersion")}


def sources(value):
    return value["sources"] if value.get("sources") else [value["source"]]


def revisions(value, multiple):
    return value["revisions"] if multiple else [value["revision"]]


def application(item, name, expected):
    receipt = identity(item, "Application", "argocd", name)
    spec, status = item["spec"], item["status"]
    destination = spec["destination"]
    require(destination.get("server") == "https://kubernetes.default.svc"
            or destination.get("name") == "in-cluster", "remote_destination_unsupported")
    declared = sources(spec)
    require(isinstance(declared, list) and 0 < len(declared) <= 16, "application_sources")
    wanted, positions = [], []
    for position, source in enumerate(declared, 1):
        target = source["targetRevision"]
        if source["repoURL"] in REPOSITORIES:
            require(target == "main", "application_sources")
            wanted.append(expected)
            positions.append(position)
        else:
            require(isinstance(target, str) and
                    (bool(SHA.fullmatch(target)) or
                     (bool(source.get("chart")) and bool(re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", target)))),
                    "external_source_not_pinned")
            wanted.append(target)
    require(positions, "application_sources")
    sync = status["sync"]
    compared = sync["comparedTo"]
    require(sources(compared) == declared and compared["destination"] == spec["destination"]
            and compared.get("ignoreDifferences", []) == spec.get("ignoreDifferences", []), "stale_comparison")
    require(sync["status"] == "Synced" and status["health"]["status"] == "Healthy"
            and item.get("operation") is None, "application_not_ready")
    require(not any(condition["type"].endswith("Error") for condition in status.get("conditions", [])),
            "application_error")
    operation = status["operationState"]
    require(operation["phase"] == "Succeeded" and operation.get("finishedAt")
            and not operation.get("operation", {}).get("sync", {}).get("dryRun", False), "operation_not_succeeded")
    result = operation["syncResult"]
    require(revisions(sync, bool(spec.get("sources"))) == wanted, "revision_mismatch")
    require(sources(result) == declared, "stale_operation_sources")
    applied = revisions(result, bool(spec.get("sources")))
    require(isinstance(applied, list) and len(applied) == len(wanted), "operation_revisions")
    # A no-op main advance updates comparison without starting another sync.
    require(all(isinstance(revision, str) and
                (bool(SHA.fullmatch(revision)) if position in positions else revision == wanted[position - 1])
                for position, revision in enumerate(applied, 1)), "operation_revisions")
    receipt.update(revisions=wanted, operation_revisions=applied, homelab_source_positions=positions)
    return receipt


def owned(item, kind, uid):
    owners = [owner for owner in item["metadata"].get("ownerReferences", []) if owner.get("controller") is True]
    return len(owners) == 1 and owners[0].get("kind") == kind and owners[0].get("uid") == uid


def images(item):
    containers = item["spec"]["containers"]
    result = {container["name"]: container["image"] for container in containers}
    require(bool(result) and len(result) == len(containers)
            and all(isinstance(name, str) and len(name) <= 63 and NAME.fullmatch(name) for name in result),
            "container_identity")
    return result


def rollout(item, namespace, name):
    receipt = identity(item, "Deployment", namespace, name)
    meta, spec, status = item["metadata"], item["spec"], item["status"]
    desired = spec.get("replicas", 1)
    require(type(desired) is int and desired > 0 and type(meta["generation"]) is int
            and type(status["observedGeneration"]) is int and status["observedGeneration"] == meta["generation"]
            and all(type(status.get(field)) is int and status.get(field) == desired for field in
                    ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas"))
            and status.get("unavailableReplicas", 0) == 0, "deployment_not_ready")
    conditions = {value["type"]: value for value in status.get("conditions", [])}
    require(conditions.get("Available", {}).get("status") == "True"
            and conditions.get("Progressing", {}).get("status") == "True"
            and conditions.get("ReplicaFailure", {}).get("status") != "True", "deployment_failed")
    revision = meta["annotations"][REVISION]
    require(isinstance(revision, str) and revision.isdigit(), "deployment_revision")
    receipt.update(generation=meta["generation"], revision=revision, replicas=desired)
    return receipt


def items(value, kind):
    require(value["kind"] in (kind + "List", "List") and isinstance(value["items"], list)
            and all(item.get("kind") == kind for item in value["items"])
            and not value.get("metadata", {}).get("continue"), "incomplete_inventory")
    return value["items"]


def deployment(read, namespace, name):
    item = read(namespace, "deployment", name)
    receipt = rollout(item, namespace, name)
    selector = item["spec"]["selector"]
    # shortcut: matchLabels only; add expression support when a selected Deployment needs it.
    require(not selector.get("matchExpressions") and isinstance(selector.get("matchLabels"), dict)
            and selector["matchLabels"], "unsupported_selector")
    labels = selector["matchLabels"]
    require(all(isinstance(key, str) and isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9_./-]+", key) and re.fullmatch(r"[A-Za-z0-9_.-]*", value)
                for key, value in labels.items()), "unsupported_selector")
    selection = ",".join(f"{key}={value}" for key, value in sorted(labels.items()))
    replicasets = items(read(namespace, "replicasets", "-l", selection), "ReplicaSet")
    owned_sets = [rs for rs in replicasets if owned(rs, "Deployment", receipt["uid"])]
    current = [rs for rs in owned_sets if rs["metadata"].get("annotations", {}).get(REVISION) == receipt["revision"]]
    require(len(current) == 1, "replicaset_identity")
    current = current[0]
    rs_identity = identity(current, "ReplicaSet", namespace, current["metadata"]["name"])
    desired = receipt["replicas"]
    require(current["spec"].get("replicas") == desired
            and type(current["metadata"]["generation"]) is int
            and type(current["status"]["observedGeneration"]) is int
            and current["status"]["observedGeneration"] == current["metadata"]["generation"]
            and all(type(current["status"].get(field)) is int and current["status"].get(field) == desired
                    for field in ("replicas", "readyReplicas", "availableReplicas"))
            and all(rs["spec"].get("replicas", 0) == 0 and rs.get("status", {}).get("replicas", 0) == 0
                    for rs in owned_sets if rs is not current), "replicaset_not_ready")
    expected_images = images(item["spec"]["template"])
    require(images(current["spec"]["template"]) == expected_images, "replicaset_images")
    inventory = items(read(namespace, "pods", "-l", selection), "Pod")
    # Terminal Pods can remain until PodGC; they are not active Deployment replicas.
    pods = [pod for pod in inventory if pod.get("status", {}).get("phase") not in ("Succeeded", "Failed")]
    require(len(pods) == desired, "pod_inventory")
    proof = []
    for pod in pods:
        pod_identity = identity(pod, "Pod", namespace, pod["metadata"]["name"])
        require(owned(pod, "ReplicaSet", rs_identity["uid"]) and images(pod) == expected_images
                and pod["status"]["phase"] == "Running"
                and any(condition["type"] == "Ready" and condition["status"] == "True"
                        for condition in pod["status"]["conditions"]), "pod_not_ready")
        states = pod["status"]["containerStatuses"]
        require(len(states) == len(expected_images) and {state["name"] for state in states} == set(expected_images),
                "container_identity")
        digests = {}
        for state in states:
            digest = DIGEST.search(state["imageID"])
            require(state["ready"] is True and "running" in state["state"] and digest, "container_not_ready")
            digests[state["name"]] = digest[1]
        proof.append({**pod_identity, "image_digests": digests})
    after = read(namespace, "deployment", name)
    require(after["spec"] == item["spec"] and after["metadata"]["uid"] == receipt["uid"]
            and after["metadata"]["generation"] == receipt["generation"], "deployment_changed")
    require(rollout(after, namespace, name)["revision"] == receipt["revision"], "deployment_changed")
    receipt.update(replica_set=rs_identity, pods=proof, retained_terminal_pods=len(inventory) - len(pods))
    return receipt


def tracked_deployments(app, targets):
    for namespace, target in targets:
        require(sum(resource.get("group") == "apps" and resource.get("kind") == "Deployment"
                    and resource.get("namespace") == namespace and resource.get("name") == target
                    and resource.get("status") == "Synced" for resource in app["status"]["resources"]) == 1,
                "deployment_not_tracked")


def verify(name, expected, deployments, read):
    require(bool(NAME.fullmatch(name)) and bool(SHA.fullmatch(expected)), "invalid_arguments")
    require(1 <= len(deployments) <= 4 and len(set(deployments)) == len(deployments), "invalid_arguments")
    targets = [target.split("/") for target in deployments]
    require(all(len(target) == 2 and len(target[0]) <= 63
                and all(NAME.fullmatch(part) for part in target) for target in targets), "invalid_arguments")
    app = read("argocd", "application", name)
    app_receipt = application(app, name, expected)
    tracked_deployments(app, targets)
    proofs = []
    for namespace, target in targets:
        proofs.append(deployment(read, namespace, target))
    after = read("argocd", "application", name)
    after_receipt = application(after, name, expected)
    tracked_deployments(after, targets)
    require(after["spec"] == app["spec"] and after_receipt["uid"] == app_receipt["uid"], "application_changed")
    return {"schema_version": 1, "controller_verified": True, "functional_acceptance": False,
            "observed_at": datetime.now(timezone.utc).isoformat(), "expected_sha": expected,
            "application": after_receipt, "deployments": proofs}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure("invalid_arguments")


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--application", required=True)
        parser.add_argument("--expected-sha", required=True)
        parser.add_argument("--deployment", action="append", required=True, metavar="NAMESPACE/NAME")
        args = parser.parse_args(argv)
        deadline = time.monotonic() + 120

        def read(namespace, kind, *arguments):
            remaining = deadline - time.monotonic()
            require(remaining > 0, "deadline_exceeded")
            result = subprocess.run(["kubectl", "--request-timeout=15s", "-n", namespace,
                                     "get", kind, *arguments, "-o", "json"],
                                    capture_output=True, text=True, check=True, timeout=min(20, remaining))
            require(len(result.stdout) <= 4 * 1024 * 1024, "response_too_large")
            return json.loads(result.stdout)

        print(json.dumps(verify(args.application, args.expected_sha, args.deployment, read), sort_keys=True))
        return 0
    except Failure as error:
        code = str(error)
    except (OSError, subprocess.SubprocessError):
        code = "kubernetes_read_unavailable"
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        code = "invalid_evidence"
    print(json.dumps({"controller_verified": False, "functional_acceptance": False, "blocker": code}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
