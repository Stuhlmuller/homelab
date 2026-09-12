#!/usr/bin/env python3
"""Exercise the real retirement engine with a stateful, entirely offline API."""

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "codeql_retirement", Path(__file__).with_name("codeql-retire-legacy-actions.py")
)
retire = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retire)
MAIN = "c" * 40
PREFIX = "repos/Stuhlmuller/homelab"
ANALYSES = PREFIX + "/code-scanning/analyses"
FAILURES = (RuntimeError, ValueError, KeyError, TypeError)


class FakeAPI:
    """Model GitHub pagination, deletability, responses and uncertain writes.

    The normal scenario models one server deletion chain. split_chains models
    separate server sets; the engine must use server responses to confirm each.
    """

    def __init__(self, scope, receipt=None, split_chains=False):
        self.main = MAIN
        self.calls = []
        self.deleted = []
        self.receipt = receipt
        self.split_chains = split_chains
        self.response_override = None
        self.page_override = None
        self.before_delete = None
        self.after_delete = None
        self.detail_override = None
        self.on_last = None
        self.workflow = (ROOT / ".github/workflows/codeql.yml").read_bytes()
        self.rows = {r["id"]: copy.deepcopy(r) for r in scope["analyses"]}
        self.approved = set(self.rows)
        template = copy.deepcopy(scope["analyses"][0])
        for offset in range(5):
            row = copy.deepcopy(template)
            row.update(id=2000000000 + offset, commit_sha=MAIN,
                       category=".github/workflows/codeql.yml:analyze-actions",
                       analysis_key=".github/workflows/codeql.yml:analyze-actions",
                       environment="{}", error="", warning="", rules_count=17)
            if offset == 1:
                row["tool"]["version"] = "2.26.3"
                row["commit_sha"] = "b" * 40
            elif offset == 2:
                row.update(ref="refs/pull/445/merge", category="/language:actions",
                           analysis_key=".github/workflows/codeql.yml:analyze")
            elif offset == 3:
                row["tool"]["name"] = "Other scanner"
            elif offset == 4:
                row["ref"] = "refs/heads/another-branch"
            self.rows[row["id"]] = row
        self.protected = {i: copy.deepcopy(r) for i, r in self.rows.items() if i not in self.approved}

    def chain(self, row):
        rows = [r for i, r in self.rows.items() if i in self.approved]
        if self.split_chains:
            rows = [r for r in rows if r["tool"] == row["tool"]]
        return sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)

    def rendered(self, row):
        result = copy.deepcopy(row)
        chain = self.chain(row)
        result["deletable"] = bool(chain and chain[0]["id"] == row["id"])
        return result

    def request(self, method, path):
        self.calls.append((method, path))
        if path == PREFIX + "/git/ref/heads/main" and method == "GET":
            return {"object": {"sha": self.main}}
        if path == PREFIX + "/contents/.github/workflows/codeql.yml?ref=" + self.main and method == "GET":
            return {"type": "file", "encoding": "base64", "content": base64.b64encode(self.workflow).decode()}
        parsed = urlsplit(path)
        if parsed.path == ANALYSES and method == "GET":
            query = parse_qs(parsed.query)
            assert query["per_page"] == ["100"]
            page = int(query["page"][0])
            rows = [self.rendered(self.rows[i]) for i in sorted(self.rows, reverse=True)]
            if "ref" in query:
                assert query["ref"] == ["refs/heads/main"]
                rows = [row for row in rows if row["ref"] == "refs/heads/main"]
            batch = rows[(page - 1) * 100:page * 100]
            return self.page_override(page, batch) if self.page_override else batch
        assert parsed.path.startswith(ANALYSES + "/"), "Engine followed an unapproved API route"
        analysis_id = int(parsed.path.removeprefix(ANALYSES + "/"))
        assert analysis_id in self.approved, "Engine accessed a protected analysis detail"
        row = self.rows[analysis_id]
        if method == "GET":
            result = self.rendered(row)
            return self.detail_override(result) if self.detail_override else result
        assert method == "DELETE", "Unexpected API mutation"
        assert self.receipt is not None and self.receipt.exists(), "DELETE preceded durable intent"
        receipt = json.loads(self.receipt.read_text())
        assert receipt["attempts"][str(analysis_id)] == "pending", "DELETE lacked pending receipt"
        assert stat.S_IMODE(self.receipt.stat().st_mode) == 0o600
        chain = self.chain(row)
        assert chain[0]["id"] == analysis_id, "Engine deleted out of order"
        if self.before_delete:
            self.before_delete(analysis_id)
        final = len(chain) == 1
        if final and not parsed.query:
            if self.on_last:
                self.on_last(analysis_id)
            raise retire.LastAnalysis("offline GitHub last-in-set response")
        assert parsed.query == ("confirm_delete=true" if final else ""), "Incorrect final-delete consent"
        del self.rows[analysis_id]
        self.deleted.append(analysis_id)
        if self.after_delete:
            self.after_delete(analysis_id)
        if final:
            response = {"next_analysis_url": None, "confirm_delete_url": None}
        else:
            url = "https://api.github.com/" + ANALYSES + "/" + str(chain[1]["id"])
            response = {"next_analysis_url": url, "confirm_delete_url": url + "?confirm_delete"}
        return self.response_override(response) if self.response_override else response


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.scope = retire.load_scope(ROOT)
        self.temporary = tempfile.TemporaryDirectory(prefix="codeql-retirement-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.receipt = self.directory / "receipt.json"
        self.api = FakeAPI(self.scope, self.receipt)

    def execute(self, approved=None, consent=True):
        with patch.object(retire, "execution_guard"):
            return retire.execute(self.scope, self.api, self.receipt,
                                  approved or retire.scope_digest(self.scope), MAIN, consent)

    def assert_no_writes(self):
        self.assertFalse(any(method != "GET" for method, _ in self.api.calls))

    def test_public_preview_cli_is_read_only_and_private(self):
        output = self.directory / "preview.json"
        with patch.object(sys, "argv", ["retire", "preview", "--output", str(output)]), \
                patch.object(retire, "API", return_value=self.api), contextlib.redirect_stdout(io.StringIO()):
            retire.main()
        state = json.loads(output.read_text())
        expected = hashlib.sha256(json.dumps(self.scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(state["scope_sha256"], expected)
        self.assertEqual(set(state["remaining"]), self.api.approved)
        self.assertEqual(set(state["retained"]), set(self.api.protected))
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertTrue(any("page=2" in path for _, path in self.api.calls))
        self.assert_no_writes()

    def test_scope_cannot_select_active_foreign_or_incomplete_history(self):
        for key, value in (("ref", "refs/pull/445/merge"), ("analysis_key", retire.CURRENT),
                           ("category", retire.CURRENT), ("environment", "{}")):
            with self.subTest(field=key):
                scope = copy.deepcopy(self.scope)
                scope["analyses"][0][key] = value
                with self.assertRaises(FAILURES):
                    retire.validate_scope(scope)
        for mutation in (lambda s: s["analyses"].pop(),
                         lambda s: s["analyses"].__setitem__(1, copy.deepcopy(s["analyses"][0])),
                         lambda s: s["analyses"][0].pop("commit_sha")):
            scope = copy.deepcopy(self.scope)
            mutation(scope)
            with self.assertRaises(FAILURES):
                retire.validate_scope(scope)

    def test_missing_scope_and_changed_remote_workflow_fail_closed(self):
        with self.assertRaises(RuntimeError):
            retire.load_scope(self.directory)
        self.api.workflow += b"\n# scanning configuration changed\n"
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assert_no_writes()

    def test_pagination_failure_duplicate_and_malformed_page_abort(self):
        def unavailable(page, batch):
            if page == 2:
                raise RuntimeError("simulated unavailable second page")
            return batch
        duplicate = self.api.rendered(self.api.rows[max(self.api.rows)])
        for override in (unavailable, lambda page, batch: [duplicate] if page == 2 else batch,
                         lambda page, batch: {"items": batch}):
            with self.subTest(override=override):
                self.api.page_override = override
                with self.assertRaises(FAILURES):
                    retire.preview(self.scope, self.api)
                self.assert_no_writes()

    def test_missing_new_and_changed_legacy_rows_abort_before_delete(self):
        selected = self.scope["analyses"][0]["id"]
        for mutation in (lambda rows: rows.pop(selected),
                         lambda rows: rows.__setitem__(3000000000, dict(rows[selected], id=3000000000)),
                         lambda rows: rows[selected].__setitem__("commit_sha", "e" * 40),
                         lambda rows: rows[selected].pop("environment")):
            with self.subTest(mutation=mutation):
                self.api = FakeAPI(self.scope, self.receipt)
                mutation(self.api.rows)
                with self.assertRaises(FAILURES):
                    self.execute()
                self.assert_no_writes()

    def test_current_main_analysis_must_exist_and_succeed(self):
        for mutation in (lambda row: row.update(error="analysis failed"),
                         lambda row: row.update(warning="incomplete"),
                         lambda row: row.update(commit_sha="d" * 40),
                         lambda row: row.update(rules_count=0),
                         lambda row: row.update(category="other"),
                         lambda row: row.pop("rules_count")):
            with self.subTest(mutation=mutation):
                self.api = FakeAPI(self.scope, self.receipt)
                mutation(self.api.rows[2000000000])
                with self.assertRaises(FAILURES):
                    self.execute()
                self.assert_no_writes()

    def test_scope_hash_and_explicit_history_loss_consent_precede_writes(self):
        for arguments in ({"approved": "0" * 64}, {"consent": False}):
            with self.subTest(arguments=arguments), self.assertRaises(FAILURES):
                self.execute(**arguments)
            self.assert_no_writes()
        self.assertFalse(self.receipt.exists())

    def test_actual_detail_is_rechecked_before_mutation(self):
        for key, value in (("deletable", False), ("ref", "refs/pull/445/merge"),
                           ("category", retire.CURRENT), ("commit_sha", "f" * 40)):
            with self.subTest(key=key):
                self.api.detail_override = lambda row: dict(row, **{key: value})
                with self.assertRaises(FAILURES):
                    self.execute()
                self.assert_no_writes()

    def test_complete_single_chain_preserves_all_foreign_and_active_rows(self):
        result = self.execute()
        self.assertEqual(result["completed"], 97)
        self.assertEqual(self.api.rows, self.api.protected)
        self.assertEqual(self.api.deleted, [r["id"] for r in self.scope["analyses"]])
        deletes = [path for method, path in self.api.calls if method == "DELETE"]
        self.assertEqual(sum("confirm_delete=true" in path for path in deletes), 1)
        self.assertTrue(deletes[-1].endswith("?confirm_delete=true"))
        before = list(self.api.deleted)
        self.execute()
        self.assertEqual(self.api.deleted, before, "completed resume must not repeat DELETE")

    def test_complete_two_server_sets_requires_two_confirmations(self):
        self.api.split_chains = True
        result = self.execute()
        self.assertEqual(result["completed"], 97)
        self.assertEqual(self.api.rows, self.api.protected)
        confirmations = [path for method, path in self.api.calls
                         if method == "DELETE" and path.endswith("?confirm_delete=true")]
        self.assertEqual(len(confirmations), 2)
        for confirmed in confirmations:
            first = ("DELETE", confirmed.removesuffix("?confirm_delete=true"))
            self.assertIn(first, self.api.calls)
            self.assertLess(self.api.calls.index(first), self.api.calls.index(("DELETE", confirmed)))

    def test_only_exact_documented_http_400_can_request_confirmation(self):
        api = retire.API()
        path = ANALYSES + "/" + str(self.scope["analyses"][0]["id"])
        message = retire.LAST_ANALYSIS_MESSAGE
        def response(status, text):
            return (f"HTTP/2.0 {status} response\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"message": text})).encode()
        with patch.object(retire, "command", return_value=(1, response(400, message))):
            with self.assertRaises(retire.LastAnalysis):
                api.request("DELETE", path)
        for method, status, text, code in (("DELETE", 400, "Analysis specified is not deletable.", 1),
                                           ("DELETE", 403, message, 1), ("GET", 400, message, 1),
                                           ("DELETE", 400, message, 0)):
            with self.subTest(method=method, status=status, text=text, code=code), \
                    patch.object(retire, "command", return_value=(code, response(status, text))):
                with self.assertRaises(RuntimeError) as caught:
                    api.request(method, path)
                self.assertNotIsInstance(caught.exception, retire.LastAnalysis)

    def test_revalidation_stops_confirmation_after_drift(self):
        for key, value in (("deletable", False), ("ref", "refs/pull/445/merge"),
                           ("commit_sha", "e" * 40), ("category", retire.CURRENT)):
            with self.subTest(key=key):
                self.receipt.unlink(missing_ok=True)
                self.api = FakeAPI(self.scope, self.receipt, split_chains=True)
                def drift(selected):
                    self.api.detail_override = lambda row: dict(row, **{key: value}) if row["id"] == selected else row
                self.api.on_last = drift
                with self.assertRaises(FAILURES):
                    self.execute()
                self.assertFalse(any("confirm_delete=true" in path for _, path in self.api.calls))

    def test_unknown_delete_error_never_escalates_to_confirmation(self):
        def unknown(_analysis_id):
            raise RuntimeError("unknown HTTP 400")
        self.api.before_delete = unknown
        with self.assertRaises(FAILURES):
            self.execute()
        self.assertFalse(any("confirm_delete=true" in path for _, path in self.api.calls))
        self.assertFalse(self.api.deleted)

    def test_returned_urls_cannot_escape_scope(self):
        approved = self.scope["analyses"][1]["id"]
        urls = ("https://attacker.invalid/" + ANALYSES + "/" + str(approved),
                "https://api.github.com/repos/Other/repo/code-scanning/analyses/" + str(approved),
                "https://api.github.com/" + ANALYSES + "/2000000000",
                "https://api.github.com/" + ANALYSES + "/" + str(approved) + "?extra=true")
        for key in ("next_analysis_url", "confirm_delete_url"):
            for url in urls:
                with self.subTest(key=key, url=url):
                    self.receipt.unlink(missing_ok=True)
                    self.api = FakeAPI(self.scope, self.receipt)
                    self.api.response_override = lambda response: dict(response, **{key: url})
                    with self.assertRaises(FAILURES):
                        self.execute()
                    self.assertEqual(len(self.api.deleted), 1)
                    self.assertEqual(sum(method == "DELETE" for method, _ in self.api.calls), 1)
                    self.assertFalse(any(path == url for _, path in self.api.calls))

    def test_invalid_success_response_is_not_retried_as_transport_uncertainty(self):
        for malformed in ({}, {"next_analysis_url": None}, [], None):
            with self.subTest(response=malformed):
                self.receipt.unlink(missing_ok=True)
                self.api = FakeAPI(self.scope, self.receipt)
                self.api.response_override = lambda _response: malformed
                with self.assertRaises(RuntimeError):
                    self.execute()
                self.assertEqual(len(self.api.deleted), 1)
                self.assertEqual(sum(method == "DELETE" for method, _ in self.api.calls), 1)

    def test_uncertain_success_reconciles_without_repeating_deleted_id(self):
        def lost_response(_analysis_id):
            self.api.after_delete = None
            raise RuntimeError("response lost after server mutation")
        self.api.after_delete = lost_response
        self.execute()
        first = self.scope["analyses"][0]["id"]
        self.assertEqual(json.loads(self.receipt.read_text())["attempts"][str(first)], "complete")
        self.assertEqual(self.api.deleted.count(first), 1)
        self.assertEqual(self.api.calls.count(("DELETE", ANALYSES + "/" + str(first))), 1)
        self.assertEqual(self.api.rows, self.api.protected)

    def test_uncertain_request_retries_only_revalidated_same_id(self):
        def lost_request(_analysis_id):
            self.api.before_delete = None
            raise RuntimeError("request lost before server mutation")
        self.api.before_delete = lost_request
        self.execute()
        first = self.scope["analyses"][0]["id"]
        path = ANALYSES + "/" + str(first)
        attempts = [i for i, call in enumerate(self.api.calls) if call == ("DELETE", path)]
        self.assertEqual(len(attempts), 2)
        between = self.api.calls[attempts[0] + 1:attempts[1]]
        self.assertIn(("GET", path), between)
        self.assertIn(("GET", PREFIX + "/git/ref/heads/main"), between)
        self.assertTrue(any("per_page=100&page=2" in route for _, route in between))
        self.assertEqual(self.api.deleted.count(first), 1)
        self.assertEqual(self.api.rows, self.api.protected)

    def test_persistently_uncertain_request_stops_after_three_attempts(self):
        def lost_request(_analysis_id):
            raise RuntimeError("request remains unavailable")
        self.api.before_delete = lost_request
        with self.assertRaises(RuntimeError):
            self.execute()
        first = self.scope["analyses"][0]["id"]
        deletes = [path for method, path in self.api.calls if method == "DELETE"]
        self.assertEqual(deletes, [ANALYSES + "/" + str(first)] * 3)
        self.assertFalse(self.api.deleted)
        self.assertEqual(json.loads(self.receipt.read_text())["attempts"], {str(first): "pending"})

    def test_uncertain_response_with_incomplete_inventory_stops_then_resumes(self):
        def unavailable(page, batch):
            if page == 2:
                raise RuntimeError("readback pagination incomplete")
            return batch
        def lost_response(_analysis_id):
            self.api.after_delete = None
            self.api.page_override = unavailable
            raise RuntimeError("response lost after server mutation")
        self.api.after_delete = lost_response
        with self.assertRaises(RuntimeError):
            self.execute()
        first = self.scope["analyses"][0]["id"]
        self.assertEqual(self.api.deleted, [first])
        self.assertEqual(json.loads(self.receipt.read_text())["attempts"], {str(first): "pending"})
        self.api.page_override = None
        self.execute()
        self.assertEqual(self.api.deleted.count(first), 1)
        self.assertEqual(self.api.rows, self.api.protected)

    def test_uncertain_response_cannot_excuse_another_id_disappearing(self):
        other = self.scope["analyses"][1]["id"]
        def unrelated_loss(_analysis_id):
            del self.api.rows[other]
            raise RuntimeError("response unavailable and unrelated analysis disappeared")
        self.api.after_delete = unrelated_loss
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.api.deleted, [self.scope["analyses"][0]["id"]])
        self.assertEqual(sum(method == "DELETE" for method, _ in self.api.calls), 1)

    def test_uncertain_still_present_id_cannot_retry_after_identity_drift(self):
        for key, value in (("deletable", False), ("ref", "refs/pull/445/merge"),
                           ("commit_sha", "e" * 40), ("category", retire.CURRENT)):
            with self.subTest(key=key):
                self.receipt.unlink(missing_ok=True)
                self.api = FakeAPI(self.scope, self.receipt)
                def lost_request(_analysis_id):
                    self.api.detail_override = lambda row: dict(row, **{key: value})
                    raise RuntimeError("request lost before server mutation")
                self.api.before_delete = lost_request
                with self.assertRaises(RuntimeError):
                    self.execute()
                self.assertEqual(sum(method == "DELETE" for method, _ in self.api.calls), 1)
                self.assertFalse(self.api.deleted)

    def test_partial_execution_resumes_pending_id_that_was_not_deleted(self):
        def interrupted(_analysis_id):
            if len(self.api.deleted) == 2:
                raise RuntimeError("request failed before server mutation")
        self.api.before_delete = interrupted
        with self.assertRaises(FAILURES):
            self.execute()
        self.api.before_delete = None
        self.execute()
        self.assertEqual(self.api.deleted, [r["id"] for r in self.scope["analyses"]])
        self.assertEqual(self.api.rows, self.api.protected)

    def test_newly_observed_current_analysis_must_remain_preserved(self):
        new_id = 3000000001
        def concurrent_scan(_analysis_id):
            if len(self.api.deleted) == 1:
                self.api.rows[new_id] = dict(self.api.protected[2000000000], id=new_id)
            elif len(self.api.deleted) == 2:
                del self.api.rows[new_id]
        self.api.after_delete = concurrent_scan
        with self.assertRaises(FAILURES):
            self.execute()
        self.assertEqual(len(self.api.deleted), 2)
        self.assertIn(new_id, json.loads(self.receipt.read_text())["retained_main"])

    def test_main_filtered_response_cannot_smuggle_foreign_ref(self):
        foreign = self.api.rendered(self.api.rows[2000000002])
        def wrong_ref(_page, batch):
            return [foreign, *batch[1:]] if "&ref=" in self.api.calls[-1][1] else batch
        self.api.page_override = wrong_ref
        with self.assertRaises(FAILURES):
            self.execute()
        self.assertLessEqual(len(self.api.deleted), 1)

    def test_partial_execution_does_not_excuse_unattempted_missing_id(self):
        def stop(_analysis_id):
            if len(self.api.deleted) == 2:
                raise RuntimeError("simulated interruption before next write")
        self.api.before_delete = stop
        with self.assertRaises(FAILURES):
            self.execute()
        self.api.before_delete = None
        unattempted = self.scope["analyses"][5]["id"]
        del self.api.rows[unattempted]
        before = list(self.api.deleted)
        with self.assertRaises(FAILURES):
            self.execute()
        self.assertEqual(self.api.deleted, before)

    def test_resume_rejects_retained_loss_main_drift_and_receipt_tampering(self):
        def stopped(_analysis_id):
            raise RuntimeError("simulated interruption")
        self.api.before_delete = stopped
        with self.assertRaises(FAILURES):
            self.execute()
        pristine = self.receipt.read_bytes()
        for mutation in (lambda: self.api.rows.pop(2000000002),
                         lambda: setattr(self.api, "main", "e" * 40),
                         lambda: self.receipt.write_text(pristine.decode().replace(retire.scope_digest(self.scope), "0" * 64))):
            with self.subTest(mutation=mutation):
                self.api = FakeAPI(self.scope, self.receipt)
                self.receipt.write_bytes(pristine)
                mutation()
                with self.assertRaises(FAILURES):
                    self.execute()
                self.assert_no_writes()

    def test_execution_guard_checks_ci_clean_exact_head_and_workflow(self):
        files = (retire.SCOPE_PATH, "scripts/ci/codeql-retire-legacy-actions.py", ".github/workflows/codeql.yml")
        committed = {name: (ROOT / name).read_bytes() for name in files}
        for name, data in committed.items():
            path = self.directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        environment = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                       "GITHUB_REPOSITORY": "Stuhlmuller/homelab", "GH_TOKEN": "offline-test-token"}
        answers = {"dirty": b"", "head": MAIN}
        def git(args):
            if args[1] == "status":
                return answers["dirty"]
            if args[1] == "rev-parse":
                return answers["head"].encode()
            self.assertEqual(args[:2], ["git", "show"])
            return committed[args[2].removeprefix("HEAD:")]
        with patch.dict(os.environ, environment, clear=True), patch.object(retire, "command", side_effect=git):
            retire.execution_guard(self.directory, self.api, MAIN, self.scope)
            for key, value in (("dirty", b"?? changed-file\n"), ("head", "d" * 40)):
                original = answers[key]
                answers[key] = value
                with self.assertRaises(FAILURES):
                    retire.execution_guard(self.directory, self.api, MAIN, self.scope)
                answers[key] = original
            self.api.main = "e" * 40
            with self.assertRaises(FAILURES):
                retire.execution_guard(self.directory, self.api, MAIN, self.scope)
            self.api.main = MAIN
            workflow = ".github/workflows/codeql.yml"
            committed[workflow] += b"\n# changed workflow\n"
            (self.directory / workflow).write_bytes(committed[workflow])
            with self.assertRaises(FAILURES):
                retire.execution_guard(self.directory, self.api, MAIN, self.scope)
        with patch.dict(os.environ, {}, clear=True), patch.object(retire, "command", side_effect=AssertionError("unexpected git")):
            with self.assertRaises(FAILURES):
                retire.execution_guard(self.directory, self.api, MAIN, self.scope)

    def test_receipts_reject_public_permissions_and_symlinks(self):
        self.receipt.write_text("{}")
        self.receipt.chmod(0o644)
        with self.assertRaises(RuntimeError):
            retire.read_receipt(self.receipt, self.scope)
        self.receipt.unlink()
        self.receipt.symlink_to(self.directory / "missing-receipt")
        with self.assertRaises(RuntimeError):
            retire.read_receipt(self.receipt, self.scope)
        with self.assertRaises(RuntimeError):
            retire.persist(self.receipt, {})

    def test_git_environment_cannot_redirect_real_child_command(self):
        with patch.dict(os.environ, {"GIT_DIR": "/offline/foreign-repository", "GIT_WORK_TREE": "/offline/tree"}):
            output = retire.command([sys.executable, "-c", "import os; print(any(k.startswith('GIT_') for k in os.environ))"])
        self.assertEqual(output, b"False\n")


if __name__ == "__main__":
    unittest.main()
