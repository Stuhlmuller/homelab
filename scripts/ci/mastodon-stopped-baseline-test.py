#!/usr/bin/env python3
"""Offline adversarial snapshots for the narrow stopped-Mastodon baseline."""
import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch
import uuid

SPEC = importlib.util.spec_from_file_location(
    "stopped", Path(__file__).with_name("mastodon-stopped-baseline.py"))
stopped = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stopped)
NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
REVISION = "a" * 40
APP_PATH = "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/mastodon"
PATHS = {
    "Deployment": "/apis/apps/v1/namespaces/mastodon/deployments",
    "ReplicaSet": "/apis/apps/v1/namespaces/mastodon/replicasets",
    "StatefulSet": "/apis/apps/v1/namespaces/mastodon/statefulsets",
    "Job": "/apis/batch/v1/namespaces/mastodon/jobs",
    "Pod": "/api/v1/namespaces/mastodon/pods",
}


def put(value, keys, replacement):
    for key in keys[:-1]:
        value = value[key]
    value[keys[-1]] = replacement


class Snapshot:
    def __init__(self, documents=None):
        self.serial = 0
        self.documents = documents or [self.declared(name) for name in sorted(stopped.NAMES)] + [
            {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {
                "name": name, "namespace": "mastodon"}, "spec": {"replicas": 1}}
            for name in sorted(stopped.DATASTORES)] + [
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {
                "name": "mastodon-config", "namespace": "mastodon"}, "data": {"value": "reviewed"}},
            {"apiVersion": "batch/v1", "kind": "Job", "metadata": {
                "name": "mastodon-migrate", "namespace": "mastodon",
                "annotations": {"argocd.argoproj.io/hook": "Sync"}}}]
        deployments = []
        replicas = []
        for document in self.documents:
            if document["kind"] != "Deployment":
                continue
            deployment = self.live(document)
            deployment["spec"]["replicas"] = 0
            deployment["status"] = {"observedGeneration": 2, "replicas": 0}
            deployment["metadata"].setdefault("annotations", {}).update({
                "deployment.kubernetes.io/revision": "3",
                "argocd.argoproj.io/tracking-id": "mastodon:apps/Deployment:mastodon/" +
                deployment["metadata"]["name"]})
            deployment["metadata"].setdefault("labels", {})["app.kubernetes.io/instance"] = "mastodon"
            deployments.append(deployment)
            replica = self.live({"apiVersion": "apps/v1", "kind": "ReplicaSet", "metadata": {
                "name": document["metadata"]["name"] + "-abcdef", "namespace": "mastodon"},
                "spec": {"replicas": 0}, "status": {"observedGeneration": 2, "replicas": 0}})
            replica["metadata"]["ownerReferences"] = [self.owner(deployment)]
            replicas.append(replica)
        stores = [self.live(d) for d in self.documents if d["kind"] == "StatefulSet"]
        for store in stores:
            revision = store["metadata"]["name"] + "-abc123"
            store["status"] = {"observedGeneration": 2, "replicas": 1, "currentReplicas": 1,
                               "updatedReplicas": 1, "readyReplicas": 1,
                               "currentRevision": revision, "updateRevision": revision}
        pods = [self.live({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": s["metadata"]["name"] + "-0", "namespace": "mastodon",
            "labels": {"controller-revision-hash": s["status"]["currentRevision"]},
            "ownerReferences": [self.owner(s)]}, "status": {"phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}]}}) for s in stores]
        job = self.live({"apiVersion": "batch/v1", "kind": "Job", "metadata": {
            "name": "mastodon-backup-123", "namespace": "mastodon"}, "status": {
                "conditions": [{"type": "Complete", "status": "True"}]}})
        self.responses = {
            PATHS[kind]: {"apiVersion": "v1", "kind": kind + "List", "metadata": {
                "resourceVersion": "100"}, "items": items}
            for kind, items in (("Deployment", deployments), ("ReplicaSet", replicas),
                                ("StatefulSet", stores), ("Pod", pods), ("Job", [job]))}
        wanted = {"repoURL": stopped.REPO, "targetRevision": "main", "path": stopped.APP_PATH}
        destination = {"server": "https://kubernetes.default.svc", "namespace": "mastodon"}
        resources = []
        for document in self.documents:
            if document["metadata"].get("annotations", {}).get("argocd.argoproj.io/hook"):
                continue
            group, kind, namespace, name = stopped.resource_id(document)
            resources.append({"group": group, "kind": kind, "namespace": namespace, "name": name,
                              "status": "OutOfSync" if kind == "Deployment" else "Synced"})
        self.app = self.live({"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": "mastodon", "namespace": "argocd"}, "spec": {
                "project": "homelab", "sources": [wanted], "destination": destination,
                "syncPolicy": {"automated": {"enabled": False, "prune": True, "selfHeal": True,
                                             "allowEmpty": False},
                               "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}},
            "status": {"sync": {"status": "OutOfSync", "revisions": [REVISION], "comparedTo": {
                "sources": copy.deepcopy([wanted]), "destination": copy.deepcopy(destination)}},
                "health": {"status": "Healthy"}, "reconciledAt": "2026-11-04T11:59:00Z",
                "operationState": {"phase": "Succeeded"}, "resources": resources}})
        self.responses[APP_PATH] = self.app
        self.reads = {}
        self.on_read = None

    @staticmethod
    def declared(name):
        labels = {"app.kubernetes.io/name": name}
        return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {
            "name": name, "namespace": "mastodon", "labels": labels,
            "annotations": {"argocd.argoproj.io/sync-wave": "3"}}, "spec": {
                "replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": labels},
                "template": {"metadata": {"labels": labels, "annotations": {"runtime": "v2"}},
                    "spec": {"serviceAccountName": "mastodon", "automountServiceAccountToken": False,
                        "containers": [{"name": name, "image": "example.invalid/app@sha256:" + "b" * 64,
                            "command": ["app"], "ports": [{"containerPort": 3000}],
                            "readinessProbe": {"httpGet": {"path": "/health", "port": 3000}},
                            "securityContext": {"allowPrivilegeEscalation": False}}],
                        "volumes": [{"name": "runtime", "secret": {"secretName": "mastodon-runtime"}}]}}}}

    def live(self, document):
        self.serial += 1
        # API objects have no YAML/Python alias sharing between labels/selectors.
        document = json.loads(json.dumps(document))
        document["metadata"].update(uid=str(uuid.UUID(int=self.serial)), resourceVersion="100", generation=2)
        return document

    @staticmethod
    def owner(item):
        return {"apiVersion": item["apiVersion"], "kind": item["kind"], "name": item["metadata"]["name"],
                "uid": item["metadata"]["uid"], "controller": True}

    def items(self, kind):
        return self.responses[PATHS[kind]]["items"]

    def read(self, path):
        self.reads[path] = self.reads.get(path, 0) + 1
        if self.on_read:
            self.on_read(path, self.reads[path])
        return copy.deepcopy(self.responses[path])

    def verify(self):
        stopped.verify(copy.deepcopy(self.app), REVISION, self.documents, NOW, self.read)


class StoppedBaselineTest(unittest.TestCase):
    def test_exact_stop_passes_with_all_inventories_read_twice(self):
        snapshot = Snapshot()
        snapshot.verify()
        self.assertEqual(snapshot.reads, {**{path: 2 for path in PATHS.values()}, APP_PATH: 1})

    def test_real_default_branch_manifests_can_supply_stopped_baseline(self):
        # Rendering is entirely local; no Kubernetes API or credential is used.
        revision, documents = stopped.trusted_source("origin/main")
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        Snapshot(documents).verify()

    def test_explicit_api_defaults_and_terminal_pods_pass(self):
        snapshot = Snapshot()
        spec = snapshot.items("Deployment")[0]["spec"]
        spec.update(progressDeadlineSeconds=600, revisionHistoryLimit=10)
        spec["template"]["metadata"]["creationTimestamp"] = None
        pod = spec["template"]["spec"]
        pod.update(dnsPolicy="ClusterFirst", restartPolicy="Always", schedulerName="default-scheduler",
                   enableServiceLinks=True, serviceAccount="mastodon")
        container = pod["containers"][0]
        container.update(terminationMessagePath="/dev/termination-log", terminationMessagePolicy="File")
        container["ports"][0]["protocol"] = "TCP"
        container["readinessProbe"].update(timeoutSeconds=1, successThreshold=1,
                                            failureThreshold=3, periodSeconds=10)
        container["readinessProbe"]["httpGet"]["scheme"] = "HTTP"
        pod["volumes"][0]["secret"]["defaultMode"] = 420
        for phase in ("Succeeded", "Failed"):
            snapshot.items("Pod").append(snapshot.live({"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": "terminal-" + phase.lower(), "namespace": "mastodon"},
                "status": {"phase": phase}}))
        snapshot.verify()

    def test_source_pause_and_comparison_must_all_match(self):
        cases = [
            (["spec", "sources", 0, "repoURL"], "https://example.invalid/untrusted.git"),
            (["spec", "sources", 0, "path"], "other"),
            (["spec", "sources", 0, "targetRevision"], REVISION),
            (["spec", "project"], "default"),
            (["spec", "destination", "namespace"], "other"),
            (["spec", "ignoreDifferences"], [{"kind": "Deployment", "jsonPointers": ["/spec"]}]),
            (["spec", "syncPolicy", "automated"], {"enabled": True}),
            (["spec", "syncPolicy", "automated"], {}),
            (["spec", "syncPolicy", "syncOptions"], ["RespectIgnoreDifferences=true"]),
            (["status", "sync", "revisions"], ["c" * 40]),
            (["status", "sync", "comparedTo", "sources", 0, "path"], "other"),
            (["status", "sync", "comparedTo", "destination", "namespace"], "other"),
            (["status", "health", "status"], "Degraded"),
            (["operation"], {"sync": {}}),
            (["status", "operationState", "phase"], "Running"),
            (["status", "operationState", "phase"], "Terminating"),
            (["status", "conditions"], [{"type": "ComparisonError", "message": "PRIVATE"}]),
        ]
        for keys, value in cases:
            with self.subTest(keys=keys, value=value):
                snapshot = Snapshot()
                put(snapshot.app, keys, value)
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()

    def test_comparison_freshness_and_resource_drift_fail_closed(self):
        for timestamp in ("2026-11-04T11:54:59Z", "2026-11-04T12:00:01Z", "2026-11-04T11:59:00"):
            with self.subTest(timestamp=timestamp):
                snapshot = Snapshot()
                snapshot.app["status"]["reconciledAt"] = timestamp
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()
        for change in ("missing", "extra", "duplicate", "non-deployment-drift", "unknown", "unhealthy", "synced"):
            with self.subTest(change=change):
                snapshot = Snapshot()
                resources = snapshot.app["status"]["resources"]
                if change == "missing":
                    resources.pop()
                elif change in {"extra", "duplicate"}:
                    resources.append(copy.deepcopy(resources[0]))
                    if change == "extra":
                        resources[-1]["name"] = "foreign"
                elif change == "non-deployment-drift":
                    resources[-1]["status"] = "OutOfSync"
                elif change == "unhealthy":
                    resources[0]["health"] = {"status": "Degraded"}
                else:
                    resources[0]["status"] = "Unknown" if change == "unknown" else "Synced"
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()

    def test_only_replica_drift_is_allowed_on_deployments(self):
        cases = [
            (["spec", "replicas"], 1), (["spec", "replicas"], False),
            (["spec", "template", "spec", "containers", 0, "image"], "example.invalid/other:latest"),
            (["spec", "template", "spec", "containers", 0, "command"], ["other"]),
            (["spec", "template", "spec", "containers", 0, "env"], [{"name": "X", "value": "changed"}]),
            (["spec", "template", "spec", "containers", 0, "securityContext", "allowPrivilegeEscalation"], True),
            (["spec", "template", "spec", "containers", 0, "readinessProbe", "timeoutSeconds"], True),
            (["spec", "template", "spec", "volumes", 0, "secret", "secretName"], "other"),
            (["spec", "template", "spec", "enableServiceLinks"], False),
            (["spec", "template", "metadata", "annotations", "runtime"], "v3"),
            (["metadata", "annotations", "foreign"], "changed"),
            (["metadata", "labels", "app.kubernetes.io/instance"], "other"),
            (["metadata", "annotations", "argocd.argoproj.io/tracking-id"], "other"),
            (["metadata", "finalizers"], ["foreign"]),
            (["metadata", "deletionTimestamp"], "2026-11-04T11:59:00Z"),
        ]
        for keys, value in cases:
            with self.subTest(keys=keys):
                snapshot = Snapshot()
                put(snapshot.items("Deployment")[0], keys, value)
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()

    def test_controller_generations_and_zero_counts_are_strict(self):
        for kind in ("Deployment", "ReplicaSet"):
            for generation in (None, 0, -1, True, "2"):
                with self.subTest(kind=kind, generation=generation):
                    snapshot = Snapshot()
                    item = snapshot.items(kind)[0]
                    item["metadata"]["generation"] = generation
                    item["status"]["observedGeneration"] = generation
                    with self.assertRaises(stopped.Failure):
                        snapshot.verify()
            for keys, value in ((["status", "observedGeneration"], 1), (["status", "replicas"], 1),
                                (["status", "readyReplicas"], True), (["status", "terminatingReplicas"], 1)):
                with self.subTest(kind=kind, keys=keys):
                    snapshot = Snapshot()
                    put(snapshot.items(kind)[0], keys, value)
                    with self.assertRaises(stopped.Failure):
                        snapshot.verify()

    def test_active_or_foreign_writers_are_rejected(self):
        for change in ("extra-deployment", "extra-store", "foreign-rs", "unowned-rs", "running-rs",
                       "app-pod", "foreign-store-pod", "pending-pod", "terminating-pod", "active-job", "pending-job"):
            with self.subTest(change=change):
                snapshot = Snapshot()
                if change.startswith("extra-"):
                    kind = "Deployment" if change == "extra-deployment" else "StatefulSet"
                    extra = copy.deepcopy(snapshot.items(kind)[0])
                    extra["metadata"]["name"] = "foreign"
                    snapshot.items(kind).append(extra)
                elif change == "foreign-rs":
                    snapshot.items("ReplicaSet")[0]["metadata"]["ownerReferences"][0]["uid"] = "wrong"
                elif change == "unowned-rs":
                    snapshot.items("ReplicaSet")[0]["metadata"]["ownerReferences"] = []
                elif change == "running-rs":
                    snapshot.items("ReplicaSet")[0]["spec"]["replicas"] = 1
                elif change == "app-pod":
                    snapshot.items("Pod")[0]["metadata"]["ownerReferences"] = [snapshot.owner(snapshot.items("ReplicaSet")[0])]
                elif change == "foreign-store-pod":
                    snapshot.items("Pod")[0]["metadata"]["ownerReferences"][0]["uid"] = "wrong"
                elif change == "pending-pod":
                    snapshot.items("Pod")[0]["status"]["phase"] = "Pending"
                elif change == "terminating-pod":
                    snapshot.items("Pod")[0]["metadata"]["deletionTimestamp"] = "2026-11-04T11:59:00Z"
                elif change == "active-job":
                    snapshot.items("Job")[0]["status"]["active"] = 1
                else:
                    snapshot.items("Job")[0]["status"] = {}
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()

    def test_partial_lists_and_invalid_identities_cannot_pass(self):
        for kind in PATHS:
            for keys, value in ((["metadata", "continue"], "next-page"), (["metadata", "resourceVersion"], "0"),
                                (["kind"], "OtherList"), (["items", 0, "metadata", "uid"], "")):
                with self.subTest(kind=kind, keys=keys):
                    snapshot = Snapshot()
                    put(snapshot.responses[PATHS[kind]], keys, value)
                    with self.assertRaises(stopped.Failure):
                        snapshot.verify()

    def test_datastores_require_current_ready_controllers_and_pods(self):
        cases = [
            ("StatefulSet", ["spec", "replicas"], 0),
            ("StatefulSet", ["status", "replicas"], 0),
            ("StatefulSet", ["status", "currentReplicas"], 0),
            ("StatefulSet", ["status", "readyReplicas"], 0),
            ("StatefulSet", ["status", "updatedReplicas"], True),
            ("StatefulSet", ["status", "observedGeneration"], 1),
            ("StatefulSet", ["metadata", "generation"], "2"),
            ("StatefulSet", ["status", "currentRevision"], "old"),
            ("StatefulSet", ["status", "updateRevision"], "new"),
            ("Pod", ["status", "conditions"], []),
            ("Pod", ["status", "conditions", 0, "status"], "False"),
            ("Pod", ["metadata", "labels", "controller-revision-hash"], "old"),
        ]
        for kind, keys, value in cases:
            with self.subTest(kind=kind, keys=keys):
                snapshot = Snapshot()
                put(snapshot.items(kind)[0], keys, value)
                with self.assertRaises(stopped.Failure):
                    snapshot.verify()
        snapshot = Snapshot()
        snapshot.items("Pod").pop()
        with self.assertRaisesRegex(stopped.Failure, "missing ready datastore pod"):
            snapshot.verify()
        for value in (None, 0, True):
            snapshot = Snapshot()
            store = snapshot.items("StatefulSet")[0]
            store["metadata"]["generation"] = store["status"]["observedGeneration"] = value
            with self.subTest(generation=value), self.assertRaises(stopped.Failure):
                snapshot.verify()

    def test_second_inventory_detects_new_or_changed_objects(self):
        for kind, path in PATHS.items():
            for change in ("added", "changed", "removed"):
                with self.subTest(kind=kind, change=change):
                    snapshot = Snapshot()

                    def racing(read_path, count):
                        if read_path != path or count != 2:
                            return
                        items = snapshot.items(kind)
                        if change == "removed":
                            items.pop()
                        elif change == "changed":
                            items[0]["metadata"]["resourceVersion"] = "101"
                        else:
                            extra = copy.deepcopy(items[0])
                            extra["metadata"]["name"] = "new-writer"
                            items.append(extra)

                    snapshot.on_read = racing
                    with self.assertRaisesRegex(stopped.Failure, "changed"):
                        snapshot.verify()

    def test_second_application_read_detects_new_operation(self):
        snapshot = Snapshot()

        def racing(path, _count):
            if path == APP_PATH:
                snapshot.app["operation"] = {"sync": {}}

        snapshot.on_read = racing
        with self.assertRaises(stopped.Failure):
            snapshot.verify()

    def test_trusted_source_archives_resolved_default_branch_never_head(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            member = tarfile.TarInfo(stopped.APP_PATH + "/kustomization.yaml")
            member.size = len(b"resources: []\n")
            archive.addfile(member, io.BytesIO(b"resources: []\n"))
        documents = Snapshot().documents
        with patch.object(stopped, "run", side_effect=[REVISION + "\n", data.getvalue(), "rendered", json.dumps(documents)]) as run:
            self.assertEqual(stopped.trusted_source("origin/main"), (REVISION, documents))
        self.assertEqual(run.call_args_list[0].args, ("git", "rev-parse", "--verify", "origin/main^{commit}"))
        self.assertEqual(run.call_args_list[1].args, ("git", "archive", "--format=tar", REVISION, stopped.APP_PATH))
        self.assertNotIn("HEAD", repr(run.call_args_list))
        for ref in ("HEAD", "main", "origin/proposed", REVISION):
            with self.subTest(ref=ref), patch.object(stopped, "run") as run:
                with self.assertRaises(stopped.Failure):
                    stopped.trusted_source(ref)
                run.assert_not_called()

    def test_base_ref_change_during_collection_is_rejected(self):
        snapshot = Snapshot()

        def run(*args, **_kwargs):
            if args[0] == "git":
                return "c" * 40 + "\n"
            self.assertEqual(args[:4], ("kubectl", "--request-timeout=15s", "get", "--raw"))
            return json.dumps(snapshot.read(args[4]))

        with patch.object(stopped, "trusted_source", return_value=(REVISION, snapshot.documents)), patch.object(stopped, "run", side_effect=run):
            with self.assertRaisesRegex(stopped.Failure, "base changed"):
                stopped.check(snapshot.app, "origin/main", NOW)


if __name__ == "__main__":
    unittest.main()
