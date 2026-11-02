#!/usr/bin/env python3
"""Exercise revision, ownership, rollout, interruption and safe-output boundaries offline."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_gitops", ROOT / "scripts/verify-gitops.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
REVISION = CHECK.REVISION


def metadata(name, namespace, number):
    return {"name": name, "namespace": namespace, "uid": f"00000000-0000-4000-8000-{number:012d}",
            "resourceVersion": str(number), "generation": 3}


def owner(kind, item):
    return [{"kind": kind, "uid": item["metadata"]["uid"], "name": item["metadata"]["name"], "controller": True}]


def fixtures(multiple=False):
    source = {"repoURL": "https://github.com/Stuhlmuller/homelab.git", "path": "clusters/homelab/apps/example",
              "targetRevision": "main"}
    destination = {"server": "https://kubernetes.default.svc", "namespace": "monitoring"}
    declared = {"sources": [{"repoURL": "https://charts.example.invalid", "chart": "example", "targetRevision": "1.2.3"},
                            {"repoURL": "https://github.com/Stuhlmuller/homelab.git", "targetRevision": "main", "ref": "values"},
                            source]} if multiple else {"source": source}
    versions = {"revisions": ["1.2.3", SHA, SHA]} if multiple else {"revision": SHA}
    app = {"kind": "Application", "metadata": metadata("example", "argocd", 1),
           "spec": {**declared, "destination": destination},
           "status": {"sync": {"status": "Synced", **versions,
                               "comparedTo": {**copy.deepcopy(declared), "destination": destination}},
                      "health": {"status": "Healthy"},
                      "operationState": {"phase": "Succeeded", "finishedAt": "2026-11-01T00:00:00Z",
                                         "syncResult": {**copy.deepcopy(declared), **versions}},
                      "resources": [{"group": "apps", "kind": "Deployment", "namespace": "monitoring",
                                     "name": "example", "status": "Synced"}]}}
    deployment = {"kind": "Deployment", "metadata": {**metadata("example", "monitoring", 2),
                                                      "annotations": {REVISION: "2"}},
                  "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "example"}},
                           "template": {"spec": {"containers": [{"name": "app", "image": "example.invalid/app@" + DIGEST}]}}},
                  "status": {"observedGeneration": 3, "replicas": 1, "updatedReplicas": 1,
                             "readyReplicas": 1, "availableReplicas": 1,
                             "conditions": [{"type": "Available", "status": "True"},
                                            {"type": "Progressing", "status": "True"}]}}
    rs = {"kind": "ReplicaSet", "metadata": {**metadata("example-abc", "monitoring", 3),
                                             "annotations": {REVISION: "2"},
                                             "ownerReferences": owner("Deployment", deployment)},
          "spec": {"replicas": 1, "template": copy.deepcopy(deployment["spec"]["template"])},
          "status": {"observedGeneration": 3, "replicas": 1, "readyReplicas": 1, "availableReplicas": 1}}
    pod = {"kind": "Pod", "metadata": {**metadata("example-abc-def", "monitoring", 4),
                                       "ownerReferences": owner("ReplicaSet", rs)},
           "spec": copy.deepcopy(rs["spec"]["template"]["spec"]),
           "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                      "containerStatuses": [{"name": "app", "ready": True, "state": {"running": {}},
                                             "imageID": "example.invalid/app@" + DIGEST}]}}
    return app, deployment, rs, pod


class Reader:
    def __init__(self, multiple=False):
        self.app, self.deployment, self.rs, self.pod = fixtures(multiple)
        self.calls = []

    def __call__(self, namespace, kind, *arguments):
        self.calls.append((namespace, kind, *arguments))
        if kind == "application":
            return copy.deepcopy(self.app)
        if kind == "deployment":
            return copy.deepcopy(self.deployment)
        self.assert_selection(namespace, arguments)
        item, resource_kind = (self.rs, "ReplicaSet") if kind == "replicasets" else (self.pod, "Pod")
        return {"kind": resource_kind + "List", "metadata": {}, "items": [copy.deepcopy(item)]}

    @staticmethod
    def assert_selection(namespace, arguments):
        assert namespace == "monitoring" and arguments == ("-l", "app=example")


def run(reader):
    return CHECK.verify("example", SHA, ["monitoring/example"], reader)


class VerifyTests(unittest.TestCase):
    def test_single_and_multiple_sources(self):
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                receipt = run(Reader(multiple))
                self.assertTrue(receipt["controller_verified"])
                self.assertFalse(receipt["functional_acceptance"])
                self.assertEqual(receipt["application"]["homelab_source_positions"], [2, 3] if multiple else [1])
                self.assertEqual(receipt["deployments"][0]["pods"][0]["image_digests"], {"app": DIGEST})

    def test_wrong_current_revision_or_invalid_operation_version(self):
        for field in ("sync", "operation"):
            for position in range(3):
                with self.subTest(field=field, position=position):
                    reader = Reader(True)
                    data = reader.app["status"]["sync"] if field == "sync" else reader.app["status"]["operationState"]["syncResult"]
                    data["revisions"] = list(data["revisions"])
                    data["revisions"][position] = "c" * 40 if field == "sync" else "unresolved-ref"
                    with self.assertRaises(CHECK.Failure):
                        run(reader)

    def test_noop_main_advance_preserves_last_apply_evidence(self):
        for multiple in (False, True):
            with self.subTest(multiple=multiple):
                reader = Reader(multiple)
                applied = ["1.2.3", "c" * 40, "c" * 40] if multiple else ["c" * 40]
                result = reader.app["status"]["operationState"]["syncResult"]
                result["revisions" if multiple else "revision"] = applied if multiple else applied[0]
                receipt = run(reader)["application"]
                self.assertEqual(receipt["operation_revisions"], applied)
                self.assertEqual(receipt["revisions"], ["1.2.3", SHA, SHA] if multiple else [SHA])
                if multiple:
                    result["revisions"][0] = "1.2.2"
                    with self.assertRaisesRegex(CHECK.Failure, "operation_revisions"):
                        run(reader)

    def test_application_failures(self):
        mutations = [
            lambda app: app.update(operation={"sync": {}}),
            lambda app: app.update(operation={}),
            lambda app: app["metadata"].update(deletionTimestamp="now"),
            lambda app: app["status"]["operationState"].update(phase="Failed"),
            lambda app: app["status"]["operationState"].update(phase="Running"),
            lambda app: app["status"]["operationState"].pop("finishedAt"),
            lambda app: app["status"]["operationState"].update(operation={"sync": {"dryRun": True}}),
            lambda app: app["status"]["sync"].update(status="OutOfSync"),
            lambda app: app["status"]["health"].update(status="Progressing"),
            lambda app: app["status"].update(conditions=[{"type": "ComparisonError", "message": "private"}]),
            lambda app: app["status"]["sync"]["comparedTo"]["source"].update(path="changed"),
            lambda app: app["status"]["operationState"]["syncResult"]["source"].update(targetRevision="other"),
            lambda app: app["status"].update(resources=[]),
            lambda app: app["spec"]["source"].update(targetRevision="other"),
            lambda app: app["spec"]["destination"].update(server="https://other.invalid"),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                reader = Reader()
                mutation(reader.app)
                with self.assertRaises(CHECK.Failure):
                    run(reader)

    def test_external_source_requires_immutable_revision(self):
        reader = Reader(True)
        reader.app["spec"]["sources"][0]["targetRevision"] = ">=1.2.3"
        with self.assertRaisesRegex(CHECK.Failure, "external_source_not_pinned"):
            run(reader)

    def test_kubectl_generic_list_preserves_item_and_completeness_checks(self):
        for case in ("valid", "wrong-kind", "empty", "partial"):
            with self.subTest(case=case):
                reader = Reader()
                def generic(namespace, kind, *args):
                    value = reader(namespace, kind, *args)
                    if kind in ("replicasets", "pods"):
                        value["kind"] = "List"
                        if case == "wrong-kind":
                            value["items"][0]["kind"] = "ConfigMap"
                        elif case == "empty":
                            value["items"] = []
                        elif case == "partial":
                            value["metadata"]["continue"] = "more"
                    return value
                if case == "valid":
                    self.assertTrue(run(generic)["controller_verified"])
                else:
                    with self.assertRaises(CHECK.Failure):
                        run(generic)

    def test_partial_duplicate_and_old_replica_inventory(self):
        for case in ("partial", "duplicate", "old-replicas", "old-pods"):
            with self.subTest(case=case):
                reader = Reader()
                def bad_inventory(namespace, kind, *args):
                    value = reader(namespace, kind, *args)
                    if kind == "replicasets":
                        if case == "partial":
                            value["metadata"]["continue"] = "more"
                        elif case == "duplicate":
                            value["items"].append(copy.deepcopy(reader.rs))
                        elif case == "old-replicas":
                            old = copy.deepcopy(reader.rs)
                            old["metadata"]["annotations"][REVISION] = "1"
                            value["items"].append(old)
                    if kind == "pods" and case == "old-pods":
                        value["items"].append(copy.deepcopy(reader.pod))
                    return value
                with self.assertRaises(CHECK.Failure):
                    run(bad_inventory)

    def test_terminal_old_pods_are_not_active_replicas(self):
        for phase in ("Succeeded", "Failed", "Running", "Pending", "Unknown"):
            with self.subTest(phase=phase):
                reader = Reader()
                old_rs = copy.deepcopy(reader.rs)
                old_rs["metadata"].update(name="example-old", uid="00000000-0000-4000-8000-000000000009")
                old_rs["metadata"]["annotations"][REVISION] = "1"
                old_rs["spec"]["replicas"] = 0
                old_rs["status"].update(replicas=0, readyReplicas=0, availableReplicas=0)
                old_pod = copy.deepcopy(reader.pod)
                old_pod["metadata"].update(name="example-old-pod", ownerReferences=owner("ReplicaSet", old_rs))
                old_pod["status"]["phase"] = phase
                def retained(namespace, kind, *args):
                    value = reader(namespace, kind, *args)
                    if kind == "replicasets":
                        value["items"].append(old_rs)
                    elif kind == "pods":
                        value["items"].append(old_pod)
                    return value
                if phase in ("Succeeded", "Failed"):
                    receipt = run(retained)
                    self.assertTrue(receipt["controller_verified"])
                    self.assertEqual(receipt["deployments"][0]["retained_terminal_pods"], 1)
                    self.assertEqual(len(receipt["deployments"][0]["pods"]), 1)
                else:
                    with self.assertRaises(CHECK.Failure):
                        run(retained)

    def test_deployment_pod_and_ownership_failures(self):
        for target, key, value in [("deployment", "observedGeneration", 2), ("deployment", "updatedReplicas", 0),
                                   ("deployment", "replicas", 2), ("deployment", "availableReplicas", 0),
                                   ("rs", "observedGeneration", 2), ("pod", "phase", "Failed")]:
            with self.subTest(target=target, key=key):
                reader = Reader()
                getattr(reader, target)["status"][key] = value
                with self.assertRaises(CHECK.Failure):
                    run(reader)
        mutations = [
            lambda r: r.deployment["spec"].update(replicas=0),
            lambda r: r.rs["metadata"]["annotations"].update({REVISION: "1"}),
            lambda r: r.rs["metadata"].update(ownerReferences=[]),
            lambda r: r.pod["metadata"].update(ownerReferences=[]),
            lambda r: r.pod["metadata"].update(deletionTimestamp="now"),
            lambda r: r.pod["status"]["containerStatuses"][0].update(ready=False),
            lambda r: r.pod["status"]["containerStatuses"][0].update(imageID="no-digest"),
            lambda r: r.pod["spec"]["containers"][0].update(image="foreign"),
            lambda r: r.deployment["spec"]["selector"].update(matchExpressions=[{}]),
            lambda r: r.deployment["status"]["conditions"].append({"type": "ReplicaFailure", "status": "True"}),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                reader = Reader()
                mutation(reader)
                with self.assertRaises(CHECK.Failure):
                    run(reader)

    def test_readback_detects_changed_application_or_deployment(self):
        for kind in ("application", "deployment"):
            with self.subTest(kind=kind):
                reader = Reader()
                counts = {}
                def changing(namespace, resource, *args):
                    result = reader(namespace, resource, *args)
                    counts[resource] = counts.get(resource, 0) + 1
                    if resource == kind and counts[resource] == 2:
                        result["metadata"]["uid"] = "00000000-0000-4000-8000-000000000999"
                    return result
                with self.assertRaises(CHECK.Failure):
                    run(changing)

    def test_final_application_must_still_track_synced_deployment(self):
        for case in ("missing", "out-of-sync"):
            with self.subTest(case=case):
                reader = Reader()
                count = 0
                def changing(namespace, kind, *args):
                    nonlocal count
                    value = reader(namespace, kind, *args)
                    if kind == "application":
                        count += 1
                        if count == 2:
                            if case == "missing":
                                value["status"]["resources"] = []
                            else:
                                value["status"]["resources"][0]["status"] = "OutOfSync"
                    return value
                with self.assertRaisesRegex(CHECK.Failure, "deployment_not_tracked"):
                    run(changing)

    def test_interrupted_observation_repeats_only_reads(self):
        reader = Reader()
        def interrupted(namespace, kind, *args):
            if kind == "pods":
                raise subprocess.TimeoutExpired("kubectl", 20, stderr="private")
            return reader(namespace, kind, *args)
        with self.assertRaises(subprocess.TimeoutExpired):
            run(interrupted)
        first, second = run(reader), run(reader)
        first.pop("observed_at")
        second.pop("observed_at")
        self.assertEqual(first, second)

    def test_failed_rollout_then_restored_healthy_fixture(self):
        reader = Reader()
        healthy_deployment = copy.deepcopy(reader.deployment)
        reader.deployment["status"]["availableReplicas"] = 0
        reader.deployment["status"]["conditions"][1] = {
            "type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}
        with self.assertRaises(CHECK.Failure):
            run(reader)
        # Simulate an external GitOps rollback restoring the retained healthy fixture.
        reader.deployment = healthy_deployment
        self.assertTrue(run(reader)["controller_verified"])
        self.assertTrue(all(call[1] in ("application", "deployment", "replicasets", "pods")
                            for call in reader.calls))

    def test_invalid_arguments_never_read(self):
        for name, sha, deployments in [("--all", SHA, ["monitoring/example"]), ("example", "main", ["monitoring/example"]),
                                       ("example", SHA, ["monitoring/example;touch /tmp/test"]),
                                       ("example", SHA, ["monitoring/../../example"]),
                                       ("example", SHA, ["monitoring/example", "monitoring/example"]),
                                       ("example", SHA, [])]:
            reader = Reader()
            with self.assertRaises(CHECK.Failure):
                CHECK.verify(name, sha, deployments, reader)
            self.assertFalse(reader.calls)

    def test_cli_sanitizes_private_errors_and_malformed_evidence(self):
        args = ["--application", "example", "--expected-sha", SHA, "--deployment", "monitoring/example"]
        for result in ({}, {"kind": "Application", "metadata": None}, "private invalid JSON"):
            with patch.object(CHECK.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(result))), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(CHECK.main(args), 1)
                self.assertEqual(json.loads(output.getvalue())["blocker"], "invalid_evidence")
        with patch.object(CHECK.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "private", stderr="secret")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(CHECK.main(args), 1)
            self.assertEqual(json.loads(output.getvalue())["blocker"], "kubernetes_read_unavailable")
            self.assertNotIn("secret", output.getvalue())

    def test_cli_only_bounded_get_argv(self):
        reader = Reader()
        def command(argv, **kwargs):
            self.assertEqual(argv[:3], ["kubectl", "--request-timeout=15s", "-n"])
            self.assertEqual(argv[4], "get")
            self.assertEqual(argv[-2:], ["-o", "json"])
            self.assertNotIn("shell", kwargs)
            self.assertLessEqual(kwargs["timeout"], 20)
            return subprocess.CompletedProcess(argv, 0, json.dumps(reader(argv[3], argv[5], *argv[6:-2])))
        with patch.object(CHECK.subprocess, "run", side_effect=command), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(CHECK.main(["--application", "example", "--expected-sha", SHA,
                                         "--deployment", "monitoring/example"]), 0)
            self.assertTrue(json.loads(output.getvalue())["controller_verified"])

    def test_expired_deadline_does_not_start_another_read(self):
        with patch.object(CHECK.time, "monotonic", side_effect=[0, 121]), \
                patch.object(CHECK.subprocess, "run") as command, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(CHECK.main(["--application", "example", "--expected-sha", SHA,
                                         "--deployment", "monitoring/example"]), 1)
            self.assertEqual(json.loads(output.getvalue())["blocker"], "deadline_exceeded")
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
