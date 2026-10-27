#!/usr/bin/env python3
"""Private review delivery rejects unsafe files and never puts values in command args."""

import importlib.util
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase, main, mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "renovate_acceptance_review", ROOT / "scripts/renovate-acceptance-review.py")
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ReviewDeliveryTests(TestCase):
    def test_operator_requires_signed_exact_remote_main_and_fixed_api(self):
        expected = "a" * 40
        replies = {
            ("git", "branch", "--show-current"): "main",
            ("git", "rev-parse", "HEAD"): expected,
            ("git", "status", "--porcelain", "--untracked-files=all"): "",
            ("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
             "refs/heads/main"): f"{expected}\trefs/heads/main",
            ("gh", "api", f"repos/Stuhlmuller/homelab/commits/{expected}",
             "--jq", ".commit.verification.verified"): "true",
            ("kubectl", "config", "view", "--minify", "-o",
             "jsonpath={.clusters[0].cluster.server}"): REVIEW.API,
        }
        with mock.patch.object(REVIEW, "command", side_effect=lambda *args: replies[args]):
            REVIEW.reviewed_main(expected)
            for key in (("git", "ls-remote", "https://github.com/Stuhlmuller/homelab.git",
                         "refs/heads/main"),
                        ("gh", "api", f"repos/Stuhlmuller/homelab/commits/{expected}",
                         "--jq", ".commit.verification.verified")):
                saved = replies[key]
                replies[key] = "false"
                with self.assertRaises(REVIEW.Failure):
                    REVIEW.reviewed_main(expected)
                replies[key] = saved
            replies[("kubectl", "config", "view", "--minify", "-o",
                     "jsonpath={.clusters[0].cluster.server}")] = "https://other.invalid"
            with self.assertRaises(REVIEW.Failure):
                REVIEW.reviewed_main(expected)

    def test_private_review_file_is_bounded_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "review.json"
            raw = json.dumps({"schema": 1, "owner": "Stuhlmuller",
                              "repositories": [], "classifications": []}).encode()
            source.write_bytes(raw)
            source.chmod(0o600)
            self.assertEqual(REVIEW.private_review(str(source)), raw)
            source.chmod(0o644)
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(source))
            source.chmod(0o600)
            link = Path(directory) / "link.json"
            link.symlink_to(source)
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(link))
            source.write_bytes(b"x" * (REVIEW.LIMIT + 1))
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(source))
            fifo = Path(directory) / "pipe.json"
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(fifo))

    def test_outcome_review_is_a_distinct_fixed_private_target(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "review.json"
            payload = {"schema": 1, "owner": "Stuhlmuller",
                       "inventorySha256": "a" * 64, "reviewSha256": "b" * 64,
                       "configSha256": "d" * 64,
                       "windowStart": "2026-10-17T00:00:00.000Z",
                       "windowEnd": "2026-10-24T00:00:00.000Z",
                       "classifications": [{"key": "c" * 64}]}
            source.write_text(json.dumps(payload))
            source.chmod(0o600)
            raw = REVIEW.private_review(str(source), "outcomes")
            job_uid = "971ca1f1-4479-45c4-8d0a-96ed6f11aa14"
            preflight_uid = "6792c831-4bf4-45b2-a959-6b245db66b9e"
            job = {"metadata": {"name": REVIEW.OUTCOME_JOB,
                                "namespace": REVIEW.NAMESPACE,
                                "uid": job_uid,
                                "creationTimestamp": "2026-10-19T18:00:00Z"},
                   "spec": {"suspend": True}, "status": {}}
            preflight = {**job, "metadata": {**job["metadata"],
                                             "name": REVIEW.OUTCOME_PREFLIGHT_JOB,
                                             "uid": preflight_uid}}
            with (mock.patch.object(REVIEW, "secret", side_effect=[None, {
                    "metadata": {"annotations": {
                        REVIEW.OUTCOME_JOB_UID_ANNOTATION: job_uid,
                        REVIEW.OUTCOME_PREFLIGHT_UID_ANNOTATION: preflight_uid}},
                    "data": {"review.json": base64.b64encode(raw).decode()}}]),
                  mock.patch.object(REVIEW, "command", side_effect=lambda *args, **_kwargs:
                      json.dumps(preflight if REVIEW.OUTCOME_PREFLIGHT_JOB in args else job)
                      if "get" in args else "") as run,
                  mock.patch("builtins.print")):
                REVIEW.install(raw, True, REVIEW.OUTCOME_SECRET)
            create = next(call for call in run.call_args_list
                          if call.args[:3] == ("kubectl", "create", "-f"))
            manifest = json.loads(create.kwargs["input_data"])
            self.assertEqual(manifest["metadata"]["name"], REVIEW.OUTCOME_SECRET)
            self.assertEqual(manifest["metadata"]["annotations"],
                             {REVIEW.OUTCOME_JOB_UID_ANNOTATION: job_uid,
                              REVIEW.OUTCOME_PREFLIGHT_UID_ANNOTATION: preflight_uid})
            self.assertNotIn(raw.decode(), " ".join(create.args))
            payload["inventorySha256"] = "invalid"
            source.write_text(json.dumps(payload))
            with self.assertRaises(REVIEW.Failure):
                REVIEW.private_review(str(source), "outcomes")

    def test_secret_creation_passes_private_value_only_on_stdin(self):
        raw = b'{"schema":1,"owner":"Stuhlmuller"}'
        existing = {"data": {"review.json": "eyJzY2hlbWEiOjEsIm93bmVyIjoiU3R1aGxtdWxsZXIifQ=="}}
        with (mock.patch.object(REVIEW, "secret", side_effect=[None, existing]),
              mock.patch.object(REVIEW, "command", return_value="") as run,
              mock.patch("builtins.print")):
            REVIEW.install(raw, True)
        args = run.call_args.args
        self.assertEqual(args, ("kubectl", "create", "-f", "-"))
        self.assertNotIn(raw.decode(), " ".join(args))
        manifest = json.loads(run.call_args.kwargs["input_data"])
        self.assertEqual(manifest["metadata"], {
            "name": REVIEW.SECRET, "namespace": REVIEW.NAMESPACE})
        self.assertIs(manifest["immutable"], True)
        self.assertEqual(manifest["data"]["review.json"], existing["data"]["review.json"])

    def test_private_review_rejects_other_checkout_and_linked_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "other-repository"
            worktree = Path(directory) / "linked-worktree"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test",
                            "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                            "commit", "--allow-empty", "-q", "-m", "seed"], check=True)
            subprocess.run(["git", "-C", str(repository), "worktree", "add", "-q",
                            "-b", "test-worktree", str(worktree)], check=True)
            raw = json.dumps({"schema": 1, "owner": "Stuhlmuller",
                              "repositories": [], "classifications": []}).encode()
            for checkout in (repository, worktree):
                source = checkout / "review.json"
                source.write_bytes(raw)
                source.chmod(0o600)
                with self.assertRaises(REVIEW.Failure):
                    REVIEW.private_review(str(source))

    def test_retirement_rejects_a_successful_job_from_before_delivery(self):
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z"}}
        job = {"metadata": {"name": REVIEW.JOB},
               "status": {"startTime": "2026-10-19T18:00:00Z", "succeeded": 1}}
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", return_value=json.dumps(job))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.retire(True)

    def test_retraction_rejects_active_or_successful_job_and_allows_failed_input(self):
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z"}}
        base = {"metadata": {"name": REVIEW.JOB}}
        for status in ({"startTime": "2026-10-19T19:01:00Z", "active": 1},
                       {"startTime": "2026-10-19T19:01:00Z", "succeeded": 1},
                       {"succeeded": 1}, {}):
            with (self.subTest(status=status),
                  mock.patch.object(REVIEW, "secret", return_value=existing),
                  mock.patch.object(REVIEW, "command", return_value=json.dumps({**base, "status": status}))):
                with self.assertRaises(REVIEW.Failure):
                    REVIEW.retract(True)

        failed = {**base, "status": {"startTime": "2026-10-19T19:01:00Z", "failed": 1,
                                     "conditions": [{"type": "Failed", "status": "True"}]}}
        calls = []

        def command(*args, **_kwargs):
            calls.append(args)
            return json.dumps(failed) if "get" in args else ""

        with (mock.patch.object(REVIEW, "secret", side_effect=[existing, None]),
              mock.patch.object(REVIEW, "command", side_effect=command),
              mock.patch("builtins.print")):
            REVIEW.retract(True)
        self.assertEqual(calls[-1], ("kubectl", "-n", REVIEW.NAMESPACE, "delete", "secret",
                                     REVIEW.SECRET, "--ignore-not-found=true", "--wait=true"))

    def test_outcome_retraction_rejects_even_a_terminal_failed_started_job(self):
        uid = "971ca1f1-4479-45c4-8d0a-96ed6f11aa14"
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z",
                                 "annotations": {REVIEW.OUTCOME_JOB_UID_ANNOTATION: uid}}}
        failed = {"metadata": {"name": REVIEW.OUTCOME_JOB,
                               "uid": uid,
                               "creationTimestamp": "2026-10-19T18:00:00Z"},
                  "spec": {"suspend": False},
                  "status": {"startTime": "2026-10-19T19:01:00Z", "failed": 1,
                             "conditions": [{"type": "Failed", "status": "True"}]}}
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", return_value=json.dumps(failed))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.retract(True, REVIEW.OUTCOME_SECRET, REVIEW.OUTCOME_JOB)

    def test_outcome_retraction_requires_same_suspended_job_before_secret(self):
        uid = "971ca1f1-4479-45c4-8d0a-96ed6f11aa14"
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z",
                                 "annotations": {REVIEW.OUTCOME_JOB_UID_ANNOTATION: uid}}}
        before = {"metadata": {"name": REVIEW.OUTCOME_JOB,
                               "uid": uid,
                               "creationTimestamp": "2026-10-19T18:00:00Z"},
                  "spec": {"suspend": True}, "status": {}}
        replaced = {**before, "metadata": {"name": REVIEW.OUTCOME_JOB,
                                           "uid": "16656a3a-92e3-4abc-907f-85ad05a6caa4",
                                           "creationTimestamp": "2026-10-19T20:00:00Z"}}
        replaced_old_timestamp = {**before, "metadata": {**before["metadata"],
                                                         "uid": replaced["metadata"]["uid"]}}
        completed_without_counter = {**before, "status": {"conditions": [
            {"type": "Complete", "status": "True"}]}}
        for output in ("", json.dumps(replaced), json.dumps(replaced_old_timestamp),
                       json.dumps(completed_without_counter)):
            with (self.subTest(output=output),
                  mock.patch.object(REVIEW, "secret", return_value=existing),
                  mock.patch.object(REVIEW, "command", return_value=output)):
                with self.assertRaises(REVIEW.Failure):
                    REVIEW.retract(True, REVIEW.OUTCOME_SECRET, REVIEW.OUTCOME_JOB)
        calls = []

        def command(*args, **_kwargs):
            calls.append(args)
            return json.dumps(before) if "get" in args else ""

        with (mock.patch.object(REVIEW, "secret", side_effect=[existing, None]),
              mock.patch.object(REVIEW, "command", side_effect=command),
              mock.patch("builtins.print")):
            REVIEW.retract(True, REVIEW.OUTCOME_SECRET, REVIEW.OUTCOME_JOB)
        self.assertEqual(calls[-1], ("kubectl", "-n", REVIEW.NAMESPACE,
                                     "delete", "secret", REVIEW.OUTCOME_SECRET,
                                     "--ignore-not-found=true", "--wait=true"))

    def test_outcome_input_replay_and_retirement_reject_replaced_job_uid(self):
        delivered_uid = "971ca1f1-4479-45c4-8d0a-96ed6f11aa14"
        replacement_uid = "16656a3a-92e3-4abc-907f-85ad05a6caa4"
        preflight_uid = "6792c831-4bf4-45b2-a959-6b245db66b9e"
        raw = b'{"schema":1}'
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z",
                                 "annotations": {REVIEW.OUTCOME_JOB_UID_ANNOTATION:
                                                 delivered_uid,
                                                 REVIEW.OUTCOME_PREFLIGHT_UID_ANNOTATION:
                                                 preflight_uid}},
                    "data": {"review.json": base64.b64encode(raw).decode()}}
        pending = {"metadata": {"name": REVIEW.OUTCOME_JOB,
                                "namespace": REVIEW.NAMESPACE,
                                "uid": replacement_uid,
                                "creationTimestamp": "2026-10-19T18:00:00Z"},
                   "spec": {"suspend": True}, "status": {}}
        pending_preflight = {**pending, "metadata": {**pending["metadata"],
                                                     "name": REVIEW.OUTCOME_PREFLIGHT_JOB,
                                                     "uid": preflight_uid}}
        def response(*args, **_kwargs):
            return json.dumps(pending_preflight if REVIEW.OUTCOME_PREFLIGHT_JOB in args
                              else pending)
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", side_effect=response)):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.install(raw, True, REVIEW.OUTCOME_SECRET)
        same_second = {**pending, "metadata": {**pending["metadata"],
                                                "uid": delivered_uid,
                                                "creationTimestamp": "2026-10-19T19:00:00Z"}}
        def same_response(*args, **_kwargs):
            return json.dumps(pending_preflight if REVIEW.OUTCOME_PREFLIGHT_JOB in args
                              else same_second)
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", side_effect=same_response),
              mock.patch("builtins.print")):
            REVIEW.install(raw, True, REVIEW.OUTCOME_SECRET)
        terminal_without_counter = {**same_second, "status": {"conditions": [
            {"type": "Failed", "status": "True"}]}}
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", side_effect=lambda *args, **_kwargs:
                  json.dumps(pending_preflight if REVIEW.OUTCOME_PREFLIGHT_JOB in args
                             else terminal_without_counter))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.install(raw, True, REVIEW.OUTCOME_SECRET)
        finished = {**pending, "spec": {"suspend": False},
                    "status": {"startTime": "2026-10-19T19:01:00Z", "succeeded": 1}}
        with (mock.patch.object(REVIEW, "secret", return_value=existing),
              mock.patch.object(REVIEW, "command", return_value=json.dumps(finished))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.retire(True, REVIEW.OUTCOME_SECRET, REVIEW.OUTCOME_JOB)

    def test_preflight_gate_requires_current_input_and_read_only_completed_job(self):
        writer_uid = "971ca1f1-4479-45c4-8d0a-96ed6f11aa14"
        preflight_uid = "6792c831-4bf4-45b2-a959-6b245db66b9e"
        code_name = "renovate-acceptance-observer-9k4tg5c8fh"
        existing = {"metadata": {"creationTimestamp": "2026-10-19T19:00:00Z",
                                 "annotations": {
                                     REVIEW.OUTCOME_JOB_UID_ANNOTATION: writer_uid,
                                     REVIEW.OUTCOME_PREFLIGHT_UID_ANNOTATION: preflight_uid}}}
        writer = {"metadata": {"name": REVIEW.OUTCOME_JOB,
                               "namespace": REVIEW.NAMESPACE, "uid": writer_uid,
                               "creationTimestamp": "2026-10-19T18:00:00Z"},
                  "spec": {"suspend": True}, "status": {}}
        preflight = {"metadata": {"name": REVIEW.OUTCOME_PREFLIGHT_JOB,
                                  "namespace": REVIEW.NAMESPACE,
                                  "uid": preflight_uid,
                                  "creationTimestamp": "2026-10-19T18:00:00Z"},
                     "spec": {"template": {"metadata": {"labels": {
                         "app.kubernetes.io/component": "acceptance-outcome-amend"}},
                         "spec": {
                         "automountServiceAccountToken": False,
                         "containers": [{"command": ["node",
                             "/usr/src/app/acceptance-outcome-amend.js", "--check-only"],
                             "volumeMounts": [
                                 {"name": "code", "mountPath":
                                  "/usr/src/app/acceptance-outcome-amend.js",
                                  "subPath": "acceptance-outcome-amend.js", "readOnly": True},
                                 {"name": "code", "mountPath":
                                  "/usr/src/app/acceptance-observer.js",
                                  "subPath": "acceptance-observer.js", "readOnly": True},
                                 {"name": "review", "mountPath": "/review", "readOnly": True},
                                 {"name": "ledger", "mountPath": "/ledger",
                                  "readOnly": True}]}],
                         "volumes": [{"name": "code", "configMap": {
                             "name": code_name}},
                                     {"name": "review", "secret": {
                                         "secretName": REVIEW.OUTCOME_SECRET,
                                         "items": [{"key": "review.json", "path": "review.json"}]}},
                                     {"name": "ledger", "persistentVolumeClaim": {
                                         "claimName": "renovate-acceptance-ledger",
                                         "readOnly": True}}]}}},
                     "status": {"startTime": "2026-10-19T19:01:00Z", "succeeded": 1,
                                "conditions": [{"type": "Complete", "status": "True"}]}}
        code_dir = ROOT / "clusters/homelab/apps/renovate"
        code_map = {"metadata": {"name": code_name, "namespace": REVIEW.NAMESPACE},
                    "data": {name: (code_dir / name).read_text() for name in (
                        "acceptance-outcome-amend.js", "acceptance-observer.js")}}

        def check(case, configmap=code_map):
            def response(*args, **_kwargs):
                if "configmap" in args:
                    return json.dumps(configmap)
                return json.dumps(case if REVIEW.OUTCOME_PREFLIGHT_JOB in args else writer)
            with (mock.patch.object(REVIEW, "secret", return_value=existing),
                  mock.patch.object(REVIEW, "command", side_effect=response),
                  mock.patch("builtins.print")):
                REVIEW.verify_preflight()

        check(preflight)
        with (mock.patch.object(REVIEW, "secret", return_value=None),
              mock.patch.object(REVIEW, "command", side_effect=lambda *args, **_kwargs:
                  json.dumps(preflight if REVIEW.OUTCOME_PREFLIGHT_JOB in args else writer))):
            with self.assertRaises(REVIEW.Failure):
                REVIEW.install(b'{"schema":1}', False, REVIEW.OUTCOME_SECRET)
        stale = copy.deepcopy(preflight)
        stale["status"]["startTime"] = "2026-10-19T18:59:00Z"
        replaced = copy.deepcopy(preflight)
        replaced["metadata"]["uid"] = "other"
        failed = copy.deepcopy(preflight)
        failed["status"]["succeeded"] = 0
        writable_pvc = copy.deepcopy(preflight)
        writable_pvc["spec"]["template"]["spec"]["volumes"][2]["persistentVolumeClaim"][
            "readOnly"] = False
        writable_mount = copy.deepcopy(preflight)
        writable_mount["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][3][
            "readOnly"] = False
        wrong_code = copy.deepcopy(preflight)
        wrong_code["spec"]["template"]["spec"]["volumes"][0]["configMap"]["name"] = "other"
        wrong_review = copy.deepcopy(preflight)
        wrong_review["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][2][
            "readOnly"] = False
        for case in (stale, replaced, failed, writable_pvc, writable_mount,
                     wrong_code, wrong_review):
            with self.subTest(case=case):
                with self.assertRaises(REVIEW.Failure):
                    check(case)
        wrong_bytes = copy.deepcopy(code_map)
        wrong_bytes["data"]["acceptance-outcome-amend.js"] = "stale"
        with self.assertRaises(REVIEW.Failure):
            check(preflight, wrong_bytes)


if __name__ == "__main__":
    main()
