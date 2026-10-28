#!/usr/bin/env python3
"""Offline fault cases for the protected Istio component handoff."""

import copy
import contextlib
import base64
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "istio-upgrade.py"
SPEC = importlib.util.spec_from_file_location("istio_upgrade", SOURCE)
UPGRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE)
BASELINE = json.loads((Path(__file__).parent / "fixtures/istio-application-1.27.3.json").read_text())
SHA = "a" * 40
HEX = "a" * 64


def started(phase=1):
    chart_receipt = {"sourceSha": SHA, "destination": "harbor.stinkyboi.com/mirror/helm",
                     "charts": []}
    return {"format": 1, "stage": UPGRADE.STAGE, "phase": phase,
            "component": UPGRADE.GATE.COMPONENTS[phase - 1][1],
            "sourceSha": SHA, "runId": "123", "status": "started", "verified": False,
            "bundleSha256": HEX, "chartReceipt": chart_receipt,
            "chartReceiptSha256": UPGRADE.digest(chart_receipt),
            "planSha256": HEX, "targetManifestSha256": HEX,
            "beforeApplication": {"uid": "app-uid", "generation": 5,
                                  "sourcesSha256": HEX, "specSha256": HEX},
            "beforeWorkloads": {name: {} for _, name, _ in UPGRADE.WORKLOADS},
            "beforeCrds": {"crdsSha256": HEX},
            "beforePdb": {"uid": "pdb-uid", "specSha256": HEX},
            "beforeAdmission": {"validationRejected": True, "sidecarInjected": True,
                                "sidecarImage": "old-digest"}}


def verified(before):
    return {"format": 1, "stage": UPGRADE.STAGE, "phase": before["phase"],
            "component": before["component"], "sourceSha": before["sourceSha"],
            "applyRunId": before["runId"],
            "verificationSha": SHA, "runId": "456", "status": "verified", "verified": True,
            "startedSha256": UPGRADE.digest(before), "bundleSha256": before["bundleSha256"],
            "chartReceiptSha256": before["chartReceiptSha256"],
            "verificationBundleSha256": HEX,
            "nodeSha256": HEX, "application": {"uid": "app-uid"},
            "workloads": {name: {} for _, name, _ in UPGRADE.WORKLOADS},
            "crds": {"webhooks": [name for _, name in UPGRADE.WEBHOOKS]},
            "pdb": before["beforePdb"],
            "admission": before["beforeAdmission"],
            "xds": {"acked": True}, "hbone": {"tls": True, "database": "ok"},
            "pathProbe": {"fixture": "checked by platform probe"}}


class IstioUpgradeTest(unittest.TestCase):
    def setUp(self):
        bundle = mock.patch.object(UPGRADE, "source_bundle_at", return_value=HEX)
        bundle.start()
        self.addCleanup(bundle.stop)

    def test_chart_receipt_binds_protected_run_package_and_oci_digest(self):
        candidate = json.loads(UPGRADE.GATE.CANDIDATE.read_text())
        candidate.update(phase=1, activationEnabled=True, priorRunId="11",
                         harborRunId="12", chartRunId="13",
                         chartManifestDigests={chart: "sha256:" + str(index + 1) * 64
                                               for index, chart in enumerate(sorted({
                                                   item[0] for item in UPGRADE.GATE.COMPONENTS}))})
        run = {"id": 13, "head_sha": SHA, "run_attempt": 1,
               "name": f"Helm charts @ {SHA}", "display_title": f"Helm charts @ {SHA}",
               "path": ".github/workflows/harbor-helm-charts.yml",
               "event": "workflow_dispatch", "head_branch": "main",
               "status": "completed", "conclusion": "success"}
        receipt = {"sourceSha": SHA, "destination": "harbor.stinkyboi.com/mirror/helm",
                   "charts": [{"chart": chart, "version": "1.28.10",
                               "packageSha256": archive,
                               "manifestDigest": candidate["chartManifestDigests"][chart]}
                              for chart, _, archive in UPGRADE.GATE.COMPONENTS
                              if chart != "gateway"]}
        receipt["charts"].append({"chart": "gateway", "version": "1.28.10",
                                  "packageSha256": UPGRADE.GATE.COMPONENTS[4][2],
                                  "manifestDigest": candidate["chartManifestDigests"]["gateway"]})

        def fetch(*args, **_kwargs):
            if args[:2] == ("gh", "api"):
                return json.dumps(run)
            self.assertEqual(args[:3], ("gh", "run", "download"))
            Path(args[-1], "harbor-istio-charts-receipt.json").write_text(json.dumps(receipt))
            return ""

        with mock.patch.object(UPGRADE, "command", side_effect=fetch), \
             mock.patch.object(UPGRADE, "harbor_chart_readback") as readback:
            self.assertEqual(UPGRADE.chart_publication_receipt(candidate), receipt)
            readback.assert_called_once_with(receipt)
            candidate["chartManifestDigests"]["base"] = "sha256:" + "f" * 64
            with self.assertRaises(ValueError):
                UPGRADE.chart_publication_receipt(candidate)
            candidate["chartManifestDigests"]["base"] = receipt["charts"][0]["manifestDigest"]
            receipt["sourceSha"] = "b" * 40
            with self.assertRaises(ValueError):
                UPGRADE.chart_publication_receipt(candidate)
            receipt["sourceSha"] = SHA
            run["conclusion"] = "failure"
            with self.assertRaises(ValueError):
                UPGRADE.chart_publication_receipt(candidate)

    def test_saved_chart_receipt_survives_artifact_expiry_after_apply(self):
        candidate = json.loads(UPGRADE.GATE.CANDIDATE.read_text())
        candidate.update(phase=1, activationEnabled=True, priorRunId="11",
                         harborRunId="12", chartRunId="13",
                         chartManifestDigests={chart: "sha256:" + str(index + 1) * 64
                                               for index, chart in enumerate(sorted({
                                                   item[0] for item in UPGRADE.GATE.COMPONENTS}))})
        receipt = {"sourceSha": SHA, "destination": "harbor.stinkyboi.com/mirror/helm",
                   "charts": [{"chart": chart, "version": "1.28.10",
                               "packageSha256": archive,
                               "manifestDigest": candidate["chartManifestDigests"][chart]}
                              for chart, _, archive in UPGRADE.GATE.COMPONENTS
                              if chart != "gateway"]}
        receipt["charts"].append({"chart": "gateway", "version": "1.28.10",
                                  "packageSha256": UPGRADE.GATE.COMPONENTS[4][2],
                                  "manifestDigest": candidate["chartManifestDigests"]["gateway"]})
        before = started()
        before["chartReceipt"] = receipt
        before["chartReceiptSha256"] = UPGRADE.digest(receipt)
        with mock.patch.object(UPGRADE, "candidate_at", return_value=candidate), \
             mock.patch.object(UPGRADE, "chart_publication_run",
                               return_value={"head_sha": SHA}), \
             mock.patch.object(UPGRADE, "harbor_chart_readback") as readback:
            self.assertEqual(UPGRADE.saved_chart_publication_receipt(before, candidate),
                             receipt)
            readback.assert_called_once_with(receipt)
            changed = copy.deepcopy(candidate)
            changed["chartManifestDigests"]["base"] = "sha256:" + "f" * 64
            with self.assertRaises(ValueError):
                UPGRADE.saved_chart_publication_receipt(before, changed)
            before["chartReceiptSha256"] = "0" * 64
            with self.assertRaises(ValueError):
                UPGRADE.saved_chart_publication_receipt(before, candidate)

    def test_verifier_after_unrelated_merge_uses_original_publications(self):
        before = started()
        current_sha = "b" * 40
        original = json.loads(UPGRADE.GATE.CANDIDATE.read_text())
        original.update(phase=1, activationEnabled=True, priorRunId="11",
                        harborRunId="12", chartRunId="13",
                        chartManifestDigests={chart: "sha256:" + "1" * 64
                                              for chart, _, _ in UPGRADE.GATE.COMPONENTS})
        current = copy.deepcopy(original)
        manifest = UPGRADE.GATE.expected_manifest(current, 1)
        before["targetManifestSha256"] = UPGRADE.digest(manifest)
        app = {"uid": before["beforeApplication"]["uid"], "generation": 6}
        store = mock.Mock()
        store.active_started.return_value = before
        args = SimpleNamespace(phase=1, expected_sha=current_sha,
                               receipt_dir=Path("/tmp"), talosconfig=Path("/tmp/talosconfig"))
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, GITHUB_RUN_ID="777"))
            def patch(target, name, **kwargs):
                return stack.enter_context(mock.patch.object(target, name, **kwargs))
            patch(UPGRADE, "protected_source", return_value=(current, {}, 1))
            patch(UPGRADE, "Receipts", return_value=store)
            patch(UPGRADE, "prerequisites")
            patch(UPGRADE, "candidate_at", return_value=original)
            publications = patch(UPGRADE, "public_runs")
            patch(UPGRADE, "saved_chart_publication_receipt")
            patch(UPGRADE, "successful_apply_run")
            patch(UPGRADE, "source_bundle", return_value="b" * 64)
            patch(UPGRADE, "verify_nodes", return_value=HEX)
            patch(UPGRADE, "command", return_value=json.dumps({
                "inputs": {"manifest": manifest}}))
            patch(UPGRADE.GATE, "check_sources")
            patch(UPGRADE.GATE, "check_referenced_content")
            patch(UPGRADE, "app_proof", return_value=app)
            patch(UPGRADE, "live_components", return_value=(
                {name: {} for _, name, _ in UPGRADE.WORKLOADS}, []))
            patch(UPGRADE, "crd_and_webhook_proof", return_value={})
            patch(UPGRADE, "pdb_proof", return_value=before["beforePdb"])
            patch(UPGRADE, "admission_proof", return_value={})
            patch(UPGRADE.PLAT, "inter_node_path_probe", return_value={})
            patch(UPGRADE, "xds_proof", return_value={"acked": True})
            patch(UPGRADE, "hbone_proof", return_value={"tls": True})
            patch(UPGRADE.PLAT, "current_main_sha", return_value=current_sha)
            patch(UPGRADE, "validate_verified_receipt")
            publish = patch(UPGRADE, "publish_or_reuse_verification",
                            side_effect=lambda _store, _phase, _before, record: record)
            patch(UPGRADE.PLAT, "save_inspection")
            patch(UPGRADE.subprocess, "run",
                  return_value=SimpleNamespace(returncode=0))
            UPGRADE.verify(args)
            publications.assert_called_once_with(original, SHA)
            record = publish.call_args.args[3]
            self.assertEqual(record["sourceSha"], SHA)
            self.assertEqual(record["verificationSha"], current_sha)
            self.assertEqual(record["bundleSha256"], HEX)
            self.assertEqual(record["verificationBundleSha256"], "b" * 64)

    def test_private_harbor_digest_pull_rejects_mutated_manifest_or_layer(self):
        archive = b"reviewed chart archive bytes"
        package_sha = UPGRADE.hashlib.sha256(archive).hexdigest()
        manifest = {"schemaVersion": 2, "layers": [{
            "mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
            "digest": "sha256:" + package_sha}]}
        body = UPGRADE.canonical(manifest)
        row = {"chart": "base", "version": "1.28.10",
               "packageSha256": package_sha,
               "manifestDigest": "sha256:" + UPGRADE.hashlib.sha256(body).hexdigest()}
        state = {"manifest": body, "archive": archive}

        class Response:
            def __init__(self, status, headers, payload):
                self.status, self._headers, self._payload = status, headers, payload

            def read(self, _limit):
                return self._payload

            def getheaders(self):
                return list(self._headers.items())

        class Connection:
            def __init__(self, *_args, **_kwargs):
                self.path = None
                self.headers = None

            def request(self, _method, path, headers=None):
                self.path, self.headers = path, headers or {}

            def getresponse(self):
                if self.path.startswith("/service/token?"):
                    return Response(200, {}, b'{"token":"reviewed"}')
                if "/blobs/" in self.path:
                    return Response(200, {}, state["archive"])
                if "Authorization" not in self.headers:
                    return Response(401, {"WWW-Authenticate":
                        'Bearer realm="https://harbor.stinkyboi.com/service/token",'
                        'service="harbor-registry",scope="repository:mirror/helm/base:pull"'},
                        b"")
                return Response(200, {"Docker-Content-Digest": row["manifestDigest"]},
                                state["manifest"])

            def close(self):
                pass

        with mock.patch.object(UPGRADE, "command", return_value="reader-password\n"), \
             mock.patch.object(UPGRADE, "argo_oci_credential_proof"), \
             mock.patch.object(UPGRADE, "port_forward", return_value=(mock.Mock(), 2345)), \
             mock.patch.object(UPGRADE, "stop_forward"), \
             mock.patch.object(UPGRADE.ssl, "create_default_context"), \
             mock.patch.object(UPGRADE.http.client, "HTTPSConnection", Connection):
            UPGRADE.harbor_chart_readback({"charts": [row]})
            state["manifest"] = b"changed manifest"
            with self.assertRaises(ValueError):
                UPGRADE.harbor_chart_readback({"charts": [row]})
            state["manifest"] = body
            state["archive"] = b"changed archive"
            with self.assertRaises(ValueError):
                UPGRADE.harbor_chart_readback({"charts": [row]})

    def test_argo_oci_reader_requires_reconciled_secret_and_same_password(self):
        external = {"metadata": {"uid": "external-uid", "generation": 3},
                    "status": {"syncedResourceVersion": "3-reviewed",
                               "conditions": [{"type": "Ready", "status": "True"}]},
                    "spec": {"secretStoreRef": {"kind": "ClusterSecretStore", "name": "aws-ssm"},
                             "target": {"name": "argocd-harbor-istio-oci",
                                        "creationPolicy": "Owner", "template": {
                                            "type": "Opaque", "metadata": {"labels": {
                                                "argocd.argoproj.io/secret-type": "repo-creds"}},
                                            "data": {"url": UPGRADE.GATE.NEW_REPOSITORY,
                                                     "type": "oci", "project": "homelab",
                                                     "username": "robot$mirror+pull",
                                                     "password": "{{ .password }}"}}},
                             "data": [{"secretKey": "password", "remoteRef": {
                                 "key": "/homelab/harbor/mirror-robot-pull-password",
                                 "conversionStrategy": "Default", "decodingStrategy": "None",
                                 "metadataPolicy": "None"}}]}}
        values = {"url": UPGRADE.GATE.NEW_REPOSITORY, "type": "oci",
                  "project": "homelab", "username": "robot$mirror+pull",
                  "password": "private-reader"}
        secret = {"metadata": {"uid": "secret-uid", "ownerReferences": [
            {"uid": "external-uid", "kind": "ExternalSecret"}],
            "labels": {"argocd.argoproj.io/secret-type": "repo-creds"}},
            "type": "Opaque", "data": {
                key: base64.b64encode(value.encode()).decode() for key, value in values.items()}}

        def read(*args):
            return external if "externalsecret" in args else secret

        with mock.patch.object(UPGRADE.PLAT, "_kubectl_json", side_effect=read):
            UPGRADE.argo_oci_credential_proof("private-reader")
            for variant in ("unready", "generation", "password", "repo-type"):
                old_external, old_secret = copy.deepcopy(external), copy.deepcopy(secret)
                if variant == "unready":
                    external["status"]["conditions"][0]["status"] = "False"
                elif variant == "generation":
                    external["status"]["syncedResourceVersion"] = "2-stale"
                elif variant == "password":
                    secret["data"]["password"] = base64.b64encode(b"wrong").decode()
                else:
                    secret["data"]["type"] = base64.b64encode(b"helm").decode()
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    UPGRADE.argo_oci_credential_proof("private-reader")
                external.clear()
                external.update(old_external)
                secret.clear()
                secret.update(old_secret)

    def test_live_workload_rejects_tag_only_updated_template_or_pod(self):
        config = json.loads((UPGRADE.ROOT / "scripts/config/platform-maintenance.json").read_text())
        target = config["istioStages"][0]["images"]
        items, pods = [], []
        for kind, name, key in UPGRADE.WORKLOADS:
            updated = name == "istiod"
            expected = UPGRADE.digest_image(target[key]) if updated else (
                "docker.io/istio/" + key + ":1.27.3-distroless")
            template_image = "auto" if key == "proxyv2" else expected
            status = {"observedGeneration": 1}
            if kind == "Deployment":
                status.update(replicas=1, updatedReplicas=1, readyReplicas=1,
                              availableReplicas=1)
            else:
                status.update(desiredNumberScheduled=1, updatedNumberScheduled=1,
                              numberReady=1, numberAvailable=1, numberMisscheduled=0)
            items.append({"kind": kind, "metadata": {"name": name, "uid": name,
                                                        "generation": 1},
                          "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                                   "template": {"metadata": {"annotations": {}},
                                                "spec": {"containers": [{
                                                    "image": template_image}]}}},
                          "status": status})
            image_digest = (target[key].split("@sha256:")[1] if updated else
                            UPGRADE.OLD_IMAGE_DIGESTS[key])
            pods.append({"metadata": {"name": name + "-pod", "uid": name + "-pod",
                                      "labels": {"app": name}},
                         "spec": {"containers": [{"image": expected}]},
                         "status": {"conditions": [{"type": "Ready", "status": "True"}],
                                    "containerStatuses": [{"ready": True,
                                                           "imageID": "image@sha256:" +
                                                           image_digest}]}})

        def read(*args):
            return {"items": pods if args[-1] == "pods" else items}

        with mock.patch.object(UPGRADE.PLAT, "_kubectl_json", side_effect=read), \
             mock.patch.object(UPGRADE.PLAT, "NODES", ("worker",)):
            self.assertEqual(len(UPGRADE.live_components(2, config)[0]), 5)
            pods[0]["spec"]["containers"][0]["image"] = \
                "docker.io/istio/pilot:1.28.10-distroless"
            with self.assertRaises(ValueError):
                UPGRADE.live_components(2, config)
            pods[0]["spec"]["containers"][0]["image"] = \
                UPGRADE.digest_image(target["pilot"])
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = \
                "docker.io/istio/pilot:1.28.10-distroless"
            with self.assertRaises(ValueError):
                UPGRADE.live_components(2, config)
            items[0]["spec"]["template"]["spec"]["containers"][0]["image"] = \
                UPGRADE.digest_image(target["pilot"])
            pods[3]["spec"]["containers"][0]["image"] = UPGRADE.OLD_PROXY_IMAGE
            self.assertEqual(len(UPGRADE.live_components(2, config)[0]), 5)
            pods[3]["status"]["containerStatuses"][0]["imageID"] = \
                "image@sha256:" + target["proxyv2"].split("@sha256:")[1]
            with self.assertRaises(ValueError):
                UPGRADE.live_components(2, config)

    def test_started_phase_never_reapplies_after_interruption(self):
        for status in ("started", "verified"):
            with self.subTest(status=status):
                store = mock.Mock()
                store.load.side_effect = lambda phase, state, required=False: (
                    {"format": 1} if state == status else None)
                with self.assertRaisesRegex(ValueError, "already started"):
                    UPGRADE.admit_unstarted(store, 1)
                store.write.assert_not_called()

    def test_post_write_failure_reuses_only_same_protected_run(self):
        before = started()
        record = verified(before)
        durable = {"verified": None}
        store = mock.Mock()
        store.load.side_effect = lambda phase, status, required=False: durable[status]

        def interrupted_write(_phase, _status, value):
            durable["verified"] = copy.deepcopy(value)
            raise ValueError("simulated failure after durable write")

        store.write.side_effect = interrupted_write
        with mock.patch.object(UPGRADE.PLAT, "verify_path_probe"):
            with self.assertRaisesRegex(ValueError, "after durable write"):
                UPGRADE.publish_or_reuse_verification(store, 1, before, record)
            self.assertEqual(UPGRADE.publish_or_reuse_verification(store, 1, before, record),
                             durable["verified"])
            self.assertEqual(store.write.call_count, 1)
            changed_run = {**record, "runId": "789", "verificationSha": "b" * 40}
            store.attestation_key.side_effect = UPGRADE.Receipts.attestation_key
            store.load_key.return_value = None
            adopted = UPGRADE.publish_or_reuse_verification(store, 1, before, changed_run)
            self.assertEqual(adopted["attestsSha256"], UPGRADE.digest(record))
            self.assertEqual(adopted["verificationSha"], "b" * 40)
            self.assertEqual(store.write_key.call_count, 1)
            wrong_bundle = {**changed_run, "bundleSha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "different source bundle"):
                UPGRADE.publish_or_reuse_verification(store, 1, before, wrong_bundle)

    def test_phase_six_summary_recovers_after_post_write_failure(self):
        records = {(phase, "started"): started(phase) for phase in range(1, 7)}
        records.update({(phase, "verified"): verified(records[(phase, "started")])
                        for phase in range(1, 7)})
        store = mock.Mock()
        store.load.side_effect = lambda phase, status: records[(phase, status)]
        store.active_started.side_effect = lambda phase: records[(phase, "started")]
        summary = {"value": None}
        store.load_key.side_effect = lambda key, required=False: summary["value"]

        def interrupted_write(_key, value):
            summary["value"] = copy.deepcopy(value)
            raise ValueError("simulated failure after summary write")

        store.write_key.side_effect = interrupted_write
        with mock.patch.object(UPGRADE.PLAT, "verify_path_probe"):
            with self.assertRaisesRegex(ValueError, "after summary write"):
                UPGRADE.publish_or_reuse_summary(store)
            UPGRADE.publish_or_reuse_summary(store)
            self.assertEqual(store.write_key.call_count, 1)
            summary["value"]["sourceSha"] = "b" * 40
            with self.assertRaisesRegex(ValueError, "different source"):
                UPGRADE.publish_or_reuse_summary(store)

    def test_failed_no_apply_after_main_merge_requires_abort_before_retry(self):
        original = started()
        next_attempt = copy.deepcopy(original)
        next_attempt.update(sourceSha="b" * 40, runId="789",
                            bundleSha256="b" * 64)
        app = {**original["beforeApplication"], "revisionSha256": "c" * 64}
        workloads, crds, pdb, admission = (
            original["beforeWorkloads"], original["beforeCrds"],
            original["beforePdb"], original["beforeAdmission"])

        class FakeStore:
            attempt_key = staticmethod(UPGRADE.Receipts.attempt_key)

            def __init__(self):
                self.aborted = False
                self.attempt = None
                self.fail_after_abort = True

            def load(self, _phase, status, required=False):
                return original if status == "started" else None

            def active_started(self, _phase, required=False):
                return None if self.aborted else original

            def load_key(self, _key, required=False):
                return self.attempt

            def write_key(self, key, value):
                if key.endswith("/aborted.json"):
                    self.aborted = True
                    if self.fail_after_abort:
                        raise ValueError("simulated merge after abort receipt")
                else:
                    self.attempt = value

        store = FakeStore()
        with mock.patch.object(UPGRADE, "failed_apply_run", return_value="failure"), \
             mock.patch.object(UPGRADE, "source_bundle_at", return_value=HEX), \
             mock.patch.object(UPGRADE, "source_bundle", return_value="b" * 64):
            with self.assertRaisesRegex(ValueError, "after abort receipt"):
                UPGRADE.begin_or_resume_apply(store, 1, next_attempt, app, workloads, crds,
                                              pdb, admission)
            self.assertTrue(store.aborted)
            store.fail_after_abort = False
            UPGRADE.begin_or_resume_apply(store, 1, next_attempt, app, workloads, crds,
                                          pdb, admission)
            self.assertEqual(store.attempt["rootStartedSha256"], UPGRADE.digest(original))
            self.assertEqual(store.attempt["sourceSha"], "b" * 40)
            changed = {**next_attempt, "runId": "790"}
            with self.assertRaisesRegex(ValueError, "reviewed recovery"):
                UPGRADE.begin_or_resume_apply(store, 1, changed, app,
                                              {**workloads, "ztunnel": {"uid": "changed"}}, crds,
                                              pdb, admission)

    def test_failed_phase_six_run_needs_successful_fresh_attestation(self):
        before = started(6)
        original = verified(before)
        adopted = {**original, "runId": "789", "verificationSha": "b" * 40,
                   "attestsSha256": UPGRADE.digest(original)}
        key = UPGRADE.Receipts.attestation_key(6, "789")
        store = mock.Mock()
        store.call.return_value = {"IsTruncated": False, "Versions": [
            {"Key": key, "VersionId": "v1", "IsLatest": True}]}
        store.download.return_value = json.dumps(adopted).encode()

        def run(args, **_kwargs):
            response = mock.Mock()
            response.returncode = 0
            if args[:2] == ["gh", "api"]:
                identifier = args[-1].rsplit("/", 1)[-1]
                sha = SHA if identifier == "456" else "b" * 40
                response.stdout = json.dumps({
                    "id": int(identifier), "head_sha": sha, "head_branch": "main",
                    "event": "workflow_dispatch", "status": "completed",
                    "conclusion": "failure" if identifier == "456" else "success",
                    "run_attempt": 1, "path": ".github/workflows/platform-maintenance.yml",
                    "name": f"Platform istio-1.28.10-phase-6 @ {sha}",
                    "display_title": f"Platform istio-1.28.10-phase-6 @ {sha}"})
            return response

        summary = {"sourceSha": SHA, "runId": "456"}
        with mock.patch.dict(os.environ, GITHUB_SHA="b" * 40), \
             mock.patch.object(UPGRADE.PLAT.subprocess, "run", side_effect=run), \
             mock.patch.object(UPGRADE.PLAT, "verify_path_probe"):
            UPGRADE.PLAT.verify_istio_completion_run(summary, store, Path("/tmp"), original)
            store.call.return_value = {"IsTruncated": False, "Versions": []}
            with self.assertRaisesRegex(ValueError, "successful protected run"):
                UPGRADE.PLAT.verify_istio_completion_run(summary, store, Path("/tmp"), original)

    def test_ambiguous_or_paginated_s3_history_fails_closed(self):
        key = UPGRADE.Receipts.key(1, "started")
        receipt = UPGRADE.Receipts.__new__(UPGRADE.Receipts)
        receipt.store = mock.Mock()
        for result in (
            {"IsTruncated": True, "Versions": []},
            {"IsTruncated": False, "DeleteMarkers": [{"Key": key}], "Versions": []},
            {"IsTruncated": False, "Versions": [
                {"Key": key, "VersionId": "v1", "IsLatest": True},
                {"Key": key, "VersionId": "v2", "IsLatest": False}]},
            {"IsTruncated": False, "Versions": [
                {"Key": key + ".other", "VersionId": "v1", "IsLatest": True}]},
        ):
            with self.subTest(result=result):
                receipt.store.call.return_value = result
                with self.assertRaises(ValueError):
                    receipt.version(key)
                self.assertIn("--no-paginate", receipt.store.call.call_args.args[2])

    def test_started_and_verified_records_bind_phase_source_and_paths(self):
        before = started()
        record = verified(before)
        with mock.patch.object(UPGRADE.PLAT, "verify_path_probe") as probe:
            UPGRADE.validate_verified_receipt(record, before, 1)
            probe.assert_called_once_with(record["pathProbe"],
                                          "istio-1.28.10-phase-1", "stage", SHA)
            for mutation in (
                lambda value: value.update(startedSha256="0" * 64),
                lambda value: value["xds"].update(acked=False),
                lambda value: value["hbone"].update(tls=False),
                lambda value: value["hbone"].update(database="down"),
                lambda value: value.update(verificationSha="changed"),
                lambda value: value["workloads"].pop("ztunnel"),
            ):
                invalid = copy.deepcopy(record)
                mutation(invalid)
                with self.assertRaises(ValueError):
                    UPGRADE.validate_verified_receipt(invalid, before, 1)
        with self.assertRaises(ValueError):
            UPGRADE.validate_started_receipt({**before, "planSha256": "changed"}, 1)

    def test_live_application_requires_exact_held_spec_and_synced_sources(self):
        live = copy.deepcopy(BASELINE)
        live["spec"]["destination"].pop("name")
        live["spec"]["syncPolicy"]["retry"]["limit"] = 5
        live["spec"]["syncPolicy"]["retry"]["backoff"]["factor"] = 2
        live["spec"]["revisionHistoryLimit"] = 10
        live["metadata"]["uid"] = "app-uid"
        live["metadata"]["generation"] = 5
        live["status"] = {"sync": {"status": "Synced", "revisions": ["1.27.3"] * 6 + [SHA, SHA]},
                          "health": {"status": "Healthy"},
                          "operationState": {"phase": "Succeeded"}}
        project = {"spec": {"sourceRepos": [
            UPGRADE.GATE.NEW_REPOSITORY + "/" + chart
            for chart, _, _ in UPGRADE.GATE.COMPONENTS]}}

        def read(*args):
            return project if "appproject" in args else live

        candidate = json.loads(UPGRADE.GATE.CANDIDATE.read_text())
        with mock.patch.object(UPGRADE.PLAT, "_kubectl_json", side_effect=read):
            self.assertEqual(UPGRADE.app_proof(0, BASELINE["spec"], candidate)["uid"],
                             "app-uid")
            for mutation in (
                lambda: live["status"]["health"].update(status="Degraded"),
                lambda: live["spec"]["sources"][0].update(targetRevision="1.28.10"),
                lambda: project["spec"].update(sourceRepos=[]),
            ):
                changed_live = copy.deepcopy(live)
                changed_project = copy.deepcopy(project)
                mutation()
                with self.assertRaises(ValueError):
                    UPGRADE.app_proof(0, BASELINE["spec"], candidate)
                live, project = changed_live, changed_project

    def test_xds_requires_all_ztunnels_both_gateways_and_ack(self):
        names = ["ztunnel-a", "ztunnel-b", "istio-ingressgateway-a",
                 "octelium-api-ingressgateway-a"]
        pods = [{"metadata": {"name": name, "labels": {"app": name.rsplit("-", 1)[0]}}}
                for name in ["istiod-a", *names]]
        proxies = [{"proxy": f"{name}.istio-system", "istio_version": "1.27.3",
                    "resources": {"cluster": {"sent": "v1", "acked": "v1"}}}
                   for name in names]
        with mock.patch.object(UPGRADE, "port_forward", return_value=(mock.Mock(), 1234)), \
             mock.patch.object(UPGRADE, "stop_forward"), \
             mock.patch.object(UPGRADE.urllib.request, "urlopen",
                               side_effect=lambda *_args, **_kwargs: io.BytesIO(json.dumps(proxies).encode())):
            self.assertTrue(UPGRADE.xds_proof(pods, 1)["acked"])
            pods.append({"metadata": {"name": "istio-ingressgateway-b",
                                      "labels": {"app": "istio-ingressgateway"}}})
            with self.assertRaises(ValueError):
                UPGRADE.xds_proof(pods, 1)
            pods.pop()
            for change in ("nack", "lost-ztunnel", "lost-gateway", "wrong-version"):
                broken = copy.deepcopy(proxies)
                if change == "nack":
                    broken[0]["resources"]["cluster"]["acked"] = "v0"
                elif change == "lost-ztunnel":
                    broken.pop(0)
                elif change == "lost-gateway":
                    broken.pop(2)
                else:
                    broken[0]["istio_version"] = "1.28.10"
                proxies[:] = broken
                with self.subTest(change=change), self.assertRaises(ValueError):
                    UPGRADE.xds_proof(pods, 1)
                proxies[:] = [{"proxy": f"{name}.istio-system", "istio_version": "1.27.3",
                               "resources": {"cluster": {"sent": "v1", "acked": "v1"}}}
                              for name in names]

    def test_admission_dry_run_requires_validator_and_injected_digest(self):
        result = {"metadata": {"name": "istio-injection-probe", "namespace": "istio-system",
                               "annotations": {"sidecar.istio.io/status":
                                               json.dumps({"revision": "default"})}},
                  "spec": {"initContainers": [{"name": "istio-init"},
                                               {"name": "istio-proxy",
                                                "image": UPGRADE.OLD_PROXY_IMAGE}]}}
        rejected = mock.Mock(returncode=1, stderr=(
            'admission webhook "validation.istio.io" denied the request: '
            'error parsing regexp'), stdout="")
        mutated = mock.Mock(returncode=0, stderr="", stdout=json.dumps(result))
        with mock.patch.object(UPGRADE.subprocess, "run", side_effect=[rejected, mutated]):
            proof = UPGRADE.admission_proof(2, {})
        self.assertEqual(proof["sidecarImage"], UPGRADE.OLD_PROXY_IMAGE)
        for variant in ("validator-bypassed", "proxy-missing", "mutable-image"):
            broken = copy.deepcopy(result)
            bad_reject = rejected
            if variant == "validator-bypassed":
                bad_reject = mock.Mock(returncode=1, stderr="schema rejected", stdout="")
            elif variant == "proxy-missing":
                broken["spec"]["initContainers"].pop()
            else:
                broken["spec"]["initContainers"][1]["image"] = \
                    "docker.io/istio/proxyv2:1.27.3-distroless"
            with self.subTest(variant=variant), \
                 mock.patch.object(UPGRADE.subprocess, "run", side_effect=[
                     bad_reject, mock.Mock(returncode=0, stderr="", stdout=json.dumps(broken))]):
                with self.assertRaises(ValueError):
                    UPGRADE.admission_proof(2, {})

    def test_webhook_config_requires_fail_policy_tls_and_fixed_endpoint(self):
        ca = base64.b64encode(b"A" * 512).decode()
        crds = {"items": [{"metadata": {"name": name, "uid": name},
                           "status": {"conditions": [{"type": "Established", "status": "True"}]}}
                          for name in UPGRADE.CRDS]}
        service = {"metadata": {"uid": "service-uid"}}
        slices = {"items": [{"endpoints": [{"conditions": {"ready": True}}]}]}
        names = {
            "istio-validator-istio-system": ["rev.validation.istio.io"],
            "istiod-default-validator": ["validation.istio.io"],
            "istio-sidecar-injector": [
                "rev.namespace.sidecar-injector.istio.io",
                "rev.object.sidecar-injector.istio.io",
                "namespace.sidecar-injector.istio.io",
                "object.sidecar-injector.istio.io"],
        }
        hooks = {name: {"metadata": {"uid": name}, "webhooks": [{
            "name": hook, "failurePolicy": "Fail",
            "clientConfig": {"service": {"name": "istiod", "namespace": "istio-system",
                                         "path": "/inject" if "injector" in name else "/validate",
                                         "port": 443}, "caBundle": ca}}
            for hook in entries]} for name, entries in names.items()}

        def read(*args):
            if "crds" in args:
                return crds
            if "endpointslices" in args:
                return slices
            if "service" in args:
                return service
            return hooks[args[-1]]

        with mock.patch.object(UPGRADE.PLAT, "_kubectl_json", side_effect=read):
            self.assertEqual(len(UPGRADE.crd_and_webhook_proof()["webhooks"]), 3)
            for name, field, value in (
                ("istiod-default-validator", "failurePolicy", "Ignore"),
                ("istiod-default-validator", "caBundle", ""),
                ("istio-sidecar-injector", "path", "/wrong"),
            ):
                with self.subTest(field=field):
                    changed = copy.deepcopy(hooks)
                    if field == "path":
                        hooks[name]["webhooks"][0]["clientConfig"]["service"][field] = value
                    elif field == "caBundle":
                        hooks[name]["webhooks"][0]["clientConfig"][field] = value
                    else:
                        hooks[name]["webhooks"][0][field] = value
                    with self.assertRaises(ValueError):
                        UPGRADE.crd_and_webhook_proof()
                    hooks.clear()
                    hooks.update(changed)


if __name__ == "__main__":
    unittest.main()
