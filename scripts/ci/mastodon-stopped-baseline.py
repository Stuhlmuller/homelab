#!/usr/bin/env python3
"""Read-only proof of the narrow Mastodon emergency-stop drift."""
import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

APP_PATH = "clusters/homelab/apps/mastodon"
NAMES = {"mastodon-web", "mastodon-sidekiq", "mastodon-streaming"}
DATASTORES = {"mastodon-postgres", "mastodon-redis"}
REPO = "https://github.com/Stuhlmuller/homelab.git"
SHA = re.compile(r"[0-9a-f]{40}\Z")


class Failure(ValueError):
    """Fixed public failure codes, never raw API diagnostics."""


def require(condition, code):
    if not condition:
        raise Failure("stopped baseline: " + code)


def run(*args, **kwargs):
    return subprocess.run(args, capture_output=True, check=True, timeout=30, **kwargs).stdout


def trusted_source(base_ref):
    # The protected plan checks out the pull merge and fetches the upstream base.
    # Never render HEAD: the proposed change must not define its own baseline.
    require(base_ref == "origin/main", "default-branch base required")
    revision = run("git", "rev-parse", "--verify", "origin/main^{commit}", text=True).strip()
    require(SHA.fullmatch(revision), "invalid base revision")
    archive = run("git", "archive", "--format=tar", revision, APP_PATH)
    with tempfile.TemporaryDirectory(prefix="mastodon-base-") as temporary:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
            require(all((item.isfile() or item.isdir()) and not Path(item.name).is_absolute()
                        and ".." not in Path(item.name).parts for item in tree.getmembers()),
                    "unsupported source member")
            tree.extractall(temporary, filter="data")
        manifests = run("kubectl", "kustomize", str(Path(temporary) / APP_PATH), text=True)
        documents = json.loads(run("yq", "eval-all", "-o=json",
                                   ". as $doc ireduce ([]; . + [$doc])", "-",
                                   input=manifests, text=True))
    require(isinstance(documents, list) and documents, "empty source inventory")
    return revision, documents


def resource_id(item):
    meta = item["metadata"]
    return (item["apiVersion"].split("/")[0] if "/" in item["apiVersion"] else "",
            item["kind"], meta.get("namespace", ""), meta["name"])


def identity(item, kind, namespace, name):
    meta = item["metadata"]
    require(item["kind"] == kind and meta["name"] == name
            and meta.get("namespace", "") == namespace and not meta.get("deletionTimestamp")
            and isinstance(meta.get("uid"), str) and re.fullmatch(r"[0-9a-f-]{36}", meta["uid"])
            and isinstance(meta.get("resourceVersion"), str) and meta["resourceVersion"].isdigit()
            and int(meta["resourceVersion"]) > 0,
            "resource identity")
    return meta["uid"]


def inventory(read, plural, kind):
    group = "apps/v1" if kind in {"Deployment", "ReplicaSet", "StatefulSet"} else "v1"
    if kind == "Job":
        group = "batch/v1"
    prefix = "/api/" if group == "v1" else "/apis/"
    value = read(prefix + group + "/namespaces/mastodon/" + plural)
    require(value.get("kind") == kind + "List" and isinstance(value.get("items"), list)
            and isinstance(value.get("metadata", {}).get("resourceVersion"), str)
            and value["metadata"]["resourceVersion"].isdigit()
            and int(value["metadata"]["resourceVersion"]) > 0
            and not value["metadata"].get("continue"), "incomplete " + plural)
    names = [item["metadata"]["name"] for item in value["items"]]
    require(len(names) == len(set(names)), "duplicate " + plural)
    for item in value["items"]:
        identity(item, kind, "mastodon", item["metadata"]["name"])
    return value["items"]


def owner(item):
    owners = item["metadata"].get("ownerReferences", [])
    controllers = [entry for entry in owners if entry.get("controller") is True]
    require(len(controllers) == 1, "controller identity")
    return controllers[0]


def strip_defaults(live, expected):
    """Remove only known API defaults absent from the reviewed Deployment spec."""
    live = copy.deepcopy(live)

    def default(value, declared, key, wanted):
        if key not in declared and type(value.get(key)) is type(wanted) and value.get(key) == wanted:
            value.pop(key, None)

    for key, wanted in (("progressDeadlineSeconds", 600), ("revisionHistoryLimit", 10)):
        default(live, expected, key, wanted)
    template, original = live["template"], expected["template"]
    default(template["metadata"], original["metadata"], "creationTimestamp", None)
    pod, source = template["spec"], original["spec"]
    for key, wanted in (("dnsPolicy", "ClusterFirst"), ("restartPolicy", "Always"),
                        ("schedulerName", "default-scheduler"), ("enableServiceLinks", True),
                        ("serviceAccount", source.get("serviceAccountName"))):
        default(pod, source, key, wanted)
    for field in ("containers", "initContainers"):
        require(len(pod.get(field, [])) == len(source.get(field, [])), "container inventory")
        for container, declared in zip(pod.get(field, []), source.get(field, [])):
            for key, wanted in (("terminationMessagePath", "/dev/termination-log"),
                                ("terminationMessagePolicy", "File")):
                default(container, declared, key, wanted)
            require(len(container.get("ports", [])) == len(declared.get("ports", [])), "port inventory")
            for port, original_port in zip(container.get("ports", []), declared.get("ports", [])):
                default(port, original_port, "protocol", "TCP")
            for name in ("startupProbe", "readinessProbe", "livenessProbe"):
                if name not in container or name not in declared:
                    continue
                probe, original_probe = container[name], declared[name]
                for key, wanted in (("timeoutSeconds", 1), ("successThreshold", 1),
                                    ("failureThreshold", 3), ("periodSeconds", 10)):
                    default(probe, original_probe, key, wanted)
                if "httpGet" in probe and "httpGet" in original_probe:
                    default(probe["httpGet"], original_probe["httpGet"], "scheme", "HTTP")
    require(len(pod.get("volumes", [])) == len(source.get("volumes", [])), "volume inventory")
    for volume, declared in zip(pod.get("volumes", []), source.get("volumes", [])):
        for field in ("secret", "configMap"):
            if field in volume and field in declared:
                default(volume[field], declared[field], "defaultMode", 420)
    return live


def deployment_metadata(live, expected):
    annotations = dict(live.get("annotations", {}))
    for key in ("deployment.kubernetes.io/revision", "kubectl.kubernetes.io/last-applied-configuration"):
        if key not in expected.get("annotations", {}):
            annotations.pop(key, None)
    tracking = annotations.pop("argocd.argoproj.io/tracking-id", None)
    require(tracking is None or tracking == "mastodon:apps/Deployment:mastodon/" + live["name"],
            "deployment tracking identity")
    labels = dict(live.get("labels", {}))
    for key in ("app.kubernetes.io/instance", "argocd.argoproj.io/instance"):
        if key not in expected.get("labels", {}) and key in labels:
            require(labels.pop(key) == "mastodon", "deployment tracking identity")
    require(annotations == expected.get("annotations", {}) and labels == expected.get("labels", {})
            and live.get("ownerReferences", []) == expected.get("ownerReferences", [])
            and live.get("finalizers", []) == expected.get("finalizers", []), "deployment metadata drift")


def application(item, revision, documents, now):
    identity(item, "Application", "argocd", "mastodon")
    spec, status = item["spec"], item["status"]
    wanted = {"repoURL": REPO, "targetRevision": "main", "path": APP_PATH}
    require(spec.get("sources") == [wanted] and not spec.get("source")
            and spec.get("project") == "homelab"
            and spec["destination"].get("server") == "https://kubernetes.default.svc"
            and spec["destination"].get("name", "") == ""
            and spec["destination"].get("namespace") == "mastodon"
            and not spec.get("ignoreDifferences"), "application source or destination")
    policy = spec["syncPolicy"]
    require(policy.get("automated") == {"enabled": False, "prune": True,
                                        "selfHeal": True, "allowEmpty": False}
            and policy.get("syncOptions") == ["CreateNamespace=true", "ServerSideApply=true"],
            "automatic sync not explicitly stopped or comparison policy changed")
    require(item.get("operation") is None
            and status.get("operationState", {}).get("phase") not in {"Running", "Terminating"}
            and not any(c.get("type", "").endswith("Error") for c in status.get("conditions", [])),
            "active operation or application error")
    sync = status["sync"]
    compared = sync["comparedTo"]
    require(sync.get("status") == "OutOfSync" and status["health"].get("status") == "Healthy"
            and sync.get("revisions") == [revision]
            and compared.get("sources") == [wanted] and compared.get("destination") == spec["destination"]
            and not compared.get("ignoreDifferences"), "stale or unrelated comparison")
    reconciled = datetime.fromisoformat(status["reconciledAt"].replace("Z", "+00:00"))
    require(reconciled.tzinfo is not None and now - timedelta(minutes=5) <= reconciled <= now,
            "stale reconciliation")
    expected = {resource_id(d) for d in documents
                if not d.get("metadata", {}).get("annotations", {}).get("argocd.argoproj.io/hook")}
    resources = [r for r in status["resources"] if not r.get("hook")]
    actual = [(r.get("group", ""), r["kind"], r.get("namespace", ""), r["name"]) for r in resources]
    require(len(actual) == len(set(actual)) and set(actual) == expected, "resource inventory drift")
    drift = set()
    for entry, key in zip(resources, actual):
        require(entry.get("health", {}).get("status", "Healthy") in {"Healthy", "Suspended"},
                "unhealthy tracked resource")
        if entry.get("status") != "Synced":
            require(entry.get("status") == "OutOfSync", "unknown resource comparison")
            drift.add(key)
    require(drift == {("apps", "Deployment", "mastodon", name) for name in NAMES},
            "unexpected resource drift")


def verify(item, revision, documents, now, read):
    application(item, revision, documents, now)
    declared = {d["metadata"]["name"]: d for d in documents if d["kind"] == "Deployment"}
    require(set(declared) == NAMES, "source deployment inventory")
    snapshots = {}

    def snapshot(plural, kind):
        snapshots[(plural, kind)] = inventory(read, plural, kind)
        return snapshots[(plural, kind)]

    deployments = snapshot("deployments", "Deployment")
    require({d["metadata"]["name"] for d in deployments} == NAMES, "live deployment inventory")
    ids = {}
    for deployment in deployments:
        name = deployment["metadata"]["name"]
        ids[name] = deployment["metadata"]["uid"]
        deployment_metadata(deployment["metadata"], declared[name]["metadata"])
        expected = copy.deepcopy(declared[name]["spec"])
        expected["replicas"] = 0
        require(type(deployment["spec"].get("replicas")) is int
                and strip_defaults(deployment["spec"], expected) == expected, "deployment spec drift")
        status = deployment["status"]
        require(status.get("observedGeneration") == deployment["metadata"].get("generation")
                and type(status.get("observedGeneration")) is int
                and type(deployment["metadata"].get("generation")) is int
                and status["observedGeneration"] > 0
                and all(type(status.get(k, 0)) is int and status.get(k, 0) == 0
                        for k in ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas",
                                  "unavailableReplicas", "terminatingReplicas")), "deployment not stopped")
    for replica in snapshot("replicasets", "ReplicaSet"):
        parent = owner(replica)
        require(parent.get("kind") == "Deployment" and parent.get("name") in ids
                and ids[parent["name"]] == parent.get("uid")
                and type(replica["spec"].get("replicas")) is int and replica["spec"]["replicas"] == 0
                and replica["status"].get("observedGeneration") == replica["metadata"].get("generation")
                and type(replica["status"].get("observedGeneration")) is int
                and type(replica["metadata"].get("generation")) is int
                and replica["status"]["observedGeneration"] > 0
                and all(type(replica["status"].get(k, 0)) is int and replica["status"].get(k, 0) == 0 for k in
                        ("replicas", "readyReplicas", "availableReplicas", "terminatingReplicas")),
                "replica set not stopped or foreign")
    stores = snapshot("statefulsets", "StatefulSet")
    require({s["metadata"]["name"] for s in stores} == DATASTORES, "datastore inventory")
    declared_stores = {d["metadata"]["name"]: d for d in documents if d["kind"] == "StatefulSet"}
    require(set(declared_stores) == DATASTORES, "source datastore inventory")
    store_ids = {s["metadata"]["name"]: s["metadata"]["uid"] for s in stores}
    store_revisions = {}
    for store in stores:
        name, status = store["metadata"]["name"], store["status"]
        require(type(declared_stores[name]["spec"].get("replicas")) is int
                and declared_stores[name]["spec"]["replicas"] == 1
                and type(store["spec"].get("replicas")) is int and store["spec"]["replicas"] == 1
                and type(store["metadata"].get("generation")) is int
                and type(status.get("observedGeneration")) is int and status["observedGeneration"] > 0
                and status["observedGeneration"] == store["metadata"]["generation"]
                and all(type(status.get(k)) is int and status[k] == 1 for k in
                        ("replicas", "currentReplicas", "updatedReplicas", "readyReplicas"))
                and isinstance(status.get("currentRevision"), str)
                and status["currentRevision"].startswith(name + "-")
                and len(status["currentRevision"]) > len(name) + 1
                and status["currentRevision"] == status.get("updateRevision"), "datastore not ready")
        store_revisions[name] = status["currentRevision"]
    for job in snapshot("jobs", "Job"):
        require(not job.get("status", {}).get("active")
                and any(c.get("type") in {"Complete", "Failed"} and c.get("status") == "True"
                        for c in job.get("status", {}).get("conditions", [])), "unfinished job")
    ready_stores = set()
    for pod in snapshot("pods", "Pod"):
        if pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        parent = owner(pod)
        require(parent.get("kind") == "StatefulSet" and parent.get("name") in store_ids
                and store_ids[parent["name"]] == parent.get("uid")
                and pod.get("status", {}).get("phase") == "Running", "active application or foreign pod")
        name = parent["name"]
        ready = [condition for condition in pod["status"].get("conditions", []) if condition.get("type") == "Ready"]
        require(name not in ready_stores and pod["metadata"]["name"] == name + "-0"
                and pod["metadata"].get("labels", {}).get("controller-revision-hash") == store_revisions[name]
                and len(ready) == 1 and ready[0].get("status") == "True", "datastore pod not ready")
        ready_stores.add(name)
    require(ready_stores == DATASTORES, "missing ready datastore pod")
    # Bracket complete inventories, including their identities, specs and status.
    # A new writer or a concurrent controller update requires a fresh attempt.
    def by_name(values):
        return sorted(values, key=lambda value: value["metadata"]["name"])

    for (plural, kind), original in snapshots.items():
        current = inventory(read, plural, kind)
        require(by_name(current) == by_name(original), "changed " + plural)
    after = read("/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/mastodon")
    application(after, revision, documents, now)
    require(after["metadata"]["uid"] == item["metadata"]["uid"] and after["spec"] == item["spec"]
            and after["status"]["sync"] == item["status"]["sync"]
            and after["status"]["resources"] == item["status"]["resources"], "application changed")


def check(item, base_ref, now):
    revision, documents = trusted_source(base_ref)

    def read(path):
        return json.loads(run("kubectl", "--request-timeout=15s", "get", "--raw", path, text=True))

    verify(item, revision, documents, now, read)
    require(run("git", "rev-parse", "--verify", "origin/main^{commit}", text=True).strip() == revision,
            "base changed")
