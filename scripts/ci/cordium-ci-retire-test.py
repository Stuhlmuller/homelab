#!/usr/bin/env python3
"""Verify the fixed retirement scope and fail-closed rollback checks."""
import contextlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("retire", pathlib.Path(__file__).resolve().parents[1] / "cordium-ci-retire.py")
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class Retirement(unittest.TestCase):
    def exercise(self, *, declared=False, stuck=False, unavailable=False, execute=True, already_absent=False, native_errors=True, bad_client=False, broken_carrier=False, terminate=False):
        deleted = []
        self.native_calls = []
        self.carrier_active = False
        self.carrier_closed = False
        environment = {"HTTPS_PROXY": "http://127.0.0.1:43123", "NO_PROXY": ""}

        @contextlib.contextmanager
        def transport(directory):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            if broken_carrier:
                raise RuntimeError("Verified carrier could not start")
            self.carrier_active = True
            try:
                yield environment
            finally:
                self.carrier_active = False
                self.carrier_closed = True

        def run(command, **kwargs):
            output, error, code = "", "", 0
            if command[0] == "yq":
                output = json.dumps([{"kind": kind, "metadata": {"name": name}} for kind, name in retire.TARGETS] if declared else [])
            else:
                self.assertEqual(command[0], "/pinned/octeliumctl")
                self.assertTrue(self.carrier_active, "Native operation escaped the verified carrier")
                self.assertEqual(kwargs["env"], environment)
                self.native_calls.append(command)
                if terminate:
                    registered.call_args.args[1](retire.signal.SIGTERM, None)
                operation, kind, name = command[5:8]
                if unavailable:
                    code, error = 1, "rpc error: code = Unavailable"
                elif operation == "delete":
                    deleted.append((kind, name))
                elif already_absent or ((kind, name) in deleted and not stuck):
                    code = 1
                    if native_errors:
                        output = f"gRPC error NotFound: core.v1.{kind} {name} does not exist\n"
                        error = "Usage: octeliumctl get [flags]"
                    else:
                        error = "rpc error: code = NotFound desc = not found"
                else:
                    output = json.dumps({"metadata": {"name": name}})
            return subprocess.CompletedProcess(command, code, output, error)

        argv = ["retire", "--homedir", "/tmp/operator"] + (["--execute"] if execute else [])
        with patch.object(sys, "argv", argv), patch.object(retire.subprocess, "run", side_effect=run), patch.object(pathlib.Path, "exists", return_value=False), patch.object(retire.native, "verify_reviewed_main"), patch.object(retire.native, "run"), patch.object(retire.native, "verified_client", side_effect=RuntimeError("Unpinned client") if bad_client else None, return_value="/pinned/octeliumctl") as verified, patch.object(retire.native, "native_transport", side_effect=transport) as carrier, patch.object(retire.signal, "signal") as registered:
            try:
                retire.main()
                success = True
            except RuntimeError:
                success = False
            self.verified_calls = verified.call_count
            self.carrier_calls = carrier.call_count
        return success, deleted

    def test_only_fixed_targets_are_deleted_and_verified(self):
        success, deleted = self.exercise()
        self.assertTrue(success)
        self.assertEqual(deleted, [(kind.lower(), name) for kind, name in retire.TARGETS])

    def test_absent_resources_are_skipped_with_native_cli_output(self):
        self.assertEqual(self.exercise(already_absent=True), (True, []))
        self.assertTrue(self.exercise(native_errors=False)[0])

    def test_catalog_removal_is_required(self):
        self.assertEqual(self.exercise(declared=True), (False, []))

    def test_dry_run_never_deletes(self):
        self.assertEqual(self.exercise(execute=False), (True, []))
        self.assertEqual(self.native_calls, [])
        self.assertEqual(self.verified_calls, 0)
        self.assertEqual(self.carrier_calls, 0)

    def test_pinned_client_and_carrier_wrap_all_reads_and_deletes(self):
        self.assertTrue(self.exercise()[0])
        self.assertEqual(self.verified_calls, 1)
        self.assertEqual(self.carrier_calls, 1)
        self.assertTrue(self.carrier_closed)
        self.assertEqual(len(self.native_calls), 9)

    def test_client_or_carrier_failure_prevents_native_operations(self):
        for failure in ({"bad_client": True}, {"broken_carrier": True}):
            with self.subTest(failure=failure):
                self.assertEqual(self.exercise(**failure), (False, []))
                self.assertEqual(self.native_calls, [])

    def test_failed_inspection_still_closes_carrier(self):
        self.assertEqual(self.exercise(unavailable=True), (False, []))
        self.assertTrue(self.carrier_closed)

    def test_sigterm_closes_carrier_before_exit(self):
        with self.assertRaises(SystemExit) as stopped:
            self.exercise(terminate=True)
        self.assertEqual(stopped.exception.code, 143)
        self.assertTrue(self.carrier_closed)

    def test_unavailable_is_not_absent_and_stuck_delete_fails(self):
        self.assertEqual(self.exercise(unavailable=True), (False, []))
        self.assertFalse(self.exercise(stuck=True)[0])

    def test_execute_requires_reviewed_main_before_catalog_or_deletion(self):
        with patch.object(sys, "argv", ["retire", "--homedir", "/tmp/operator", "--execute"]), \
                patch.object(retire.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "expected-sha"):
                retire.main()
            command.assert_not_called()

    def test_unmerged_retirement_stops_before_catalog_or_deletion(self):
        with patch.object(sys, "argv", ["retire", "--homedir", "/tmp/operator", "--execute", "--expected-sha", "a" * 40]), \
                patch.object(retire.native, "verify_reviewed_main", side_effect=RuntimeError("remote main differs")) as verify, \
                patch.object(retire.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "remote main"):
                retire.main()
            verify.assert_called_once_with("a" * 40)
            command.assert_not_called()

    def test_clean_checkout_behind_remote_main_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = pathlib.Path(temporary) / "checkout"
            subprocess.run(["git", "clone", "--quiet", "--shared", str(retire.ROOT), str(checkout)], check=True)
            expected = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            real_run = subprocess.run

            def run(command, **kwargs):
                if tuple(command[:2]) == ("git", "ls-remote"):
                    return subprocess.CompletedProcess(command, 0, "b" * 40 + "\trefs/heads/main\n", "")
                self.assertEqual(command[0], "git", "Catalog or native call occurred before main verification")
                return real_run(command, **kwargs)

            with patch.object(sys, "argv", ["retire", "--homedir", "/unused", "--execute", "--expected-sha", expected]), \
                    patch.object(retire, "ROOT", checkout), patch.object(retire.native, "ROOT", checkout), \
                    patch.object(retire.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "remote main"):
                    retire.main()


if __name__ == "__main__":
    unittest.main()
