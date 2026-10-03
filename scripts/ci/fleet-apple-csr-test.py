#!/usr/bin/env python3
"""Exercise the Apple CSR operator command against a local synthetic API."""

import base64
import contextlib
import importlib.util
import io
import json
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fleet_csr", ROOT / "scripts/fleet-download-apple-csr.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
PASSWORD = "Aa1!PRIVATE_PASSWORD_DO_NOT_LOG".ljust(44, "x")
TOKEN = "PRIVATE_SESSION_DO_NOT_LOG"
PRIVATE = "PRIVATE_RESPONSE_DO_NOT_LOG"
CSR = base64.b64encode(b"synthetic signed Apple CSR artifact")


class CSRTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def handle_api(self):
                fixture = self.server.fixture
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw) if raw else None
                fixture.calls.append((self.command, self.path, body, dict(self.headers)))
                headers = {}
                if self.path in fixture.overrides:
                    status, value, headers = fixture.overrides[self.path]
                elif self.headers.get("User-Agent") != "Fleet-Apple-Setup/1.0":
                    status, value = 403, {"error": PRIVATE}
                elif self.path == "/api/v1/fleet/login":
                    if body != {"email": helper.ADMIN_EMAIL, "password": PASSWORD}:
                        status, value = 401, {"error": PRIVATE}
                    else:
                        status, value = 200, {"token": TOKEN}
                elif self.headers.get("Authorization") != "Bearer " + TOKEN:
                    status, value = 401, {"error": PRIVATE}
                elif self.path == "/api/v1/fleet/mdm/apple/request_csr":
                    status, value = 200, {"csr": base64.b64encode(CSR).decode()}
                elif self.path == "/api/v1/fleet/logout":
                    status, value = 200, {}
                else:
                    status, value = 404, {"error": PRIVATE}
                payload = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = handle_api

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "fleet-mdm-apple.csr"
        self.calls, self.overrides = [], {}
        self.server.fixture = self
        self.credentials = json.dumps({"data": {
            "admin-password": base64.b64encode(PASSWORD.encode()).decode()}}).encode()

    def run_command(self, credential_error=None):
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 0, self.credentials, b"")
        with patch.object(helper, "FLEET_URL", self.endpoint), \
                patch.object(helper.subprocess, "run", return_value=result,
                             side_effect=credential_error) as kubectl, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = helper.main(["--output", str(self.output)])
        text = output.getvalue()
        for secret in (PASSWORD, TOKEN, PRIVATE, CSR.decode()):
            self.assertNotIn(secret, text)
        self.assertNotIn("Traceback", text)
        return status, text, kubectl

    def assert_logged_out(self):
        self.assertEqual(self.calls[-1][0:2], ("POST", "/api/v1/fleet/logout"))
        self.assertEqual(self.calls[-1][3]["Authorization"], "Bearer " + TOKEN)

    def test_decodes_once_writes_private_file_and_logs_out(self):
        status, _, kubectl = self.run_command()
        self.assertEqual(status, 0)
        self.assertEqual(self.output.read_bytes(), CSR)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual([call[0:2] for call in self.calls], [
            ("POST", "/api/v1/fleet/login"),
            ("GET", "/api/v1/fleet/mdm/apple/request_csr"),
            ("POST", "/api/v1/fleet/logout")])
        self.assert_logged_out()
        self.assertTrue(all(call[3]["User-Agent"] == "Fleet-Apple-Setup/1.0" for call in self.calls))
        kubectl.assert_called_once_with(
            ["kubectl", "-n", "fleet", "get", "secret", "fleet-admin", "-o", "json"],
            capture_output=True, check=True, timeout=30)

    def test_existing_file_is_preserved_before_credentials_or_api(self):
        self.output.write_bytes(b"existing")
        status, _, kubectl = self.run_command()
        self.assertEqual(status, 1)
        self.assertEqual(self.output.read_bytes(), b"existing")
        kubectl.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_existing_symlink_is_preserved_without_api(self):
        target = self.output.parent / "target"
        target.write_bytes(b"existing")
        self.output.symlink_to(target)
        status, _, kubectl = self.run_command()
        self.assertEqual(status, 1)
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(target.read_bytes(), b"existing")
        kubectl.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_csr_errors_are_redacted_and_session_is_revoked(self):
        cases = [(500, {"error": PRIVATE}, {}), (200, {"csr": "invalid-base64!"}, {}),
                 (200, {"csr": None}, {}), (200, {"csr": ""}, {}),
                 (200, b"invalid-json:" + PRIVATE.encode(), {}),
                 (200, b"x" * (helper.MAX_RESPONSE + 1), {})]
        for response in cases:
            with self.subTest(status=response[0], payload_type=type(response[1]).__name__):
                self.calls.clear()
                self.overrides["/api/v1/fleet/mdm/apple/request_csr"] = response
                self.assertEqual(self.run_command()[0], 1)
                self.assertFalse(self.output.exists())
                self.assert_logged_out()

    def test_logout_failure_removes_incomplete_output_and_reports_failure(self):
        self.overrides["/api/v1/fleet/logout"] = (500, {"error": TOKEN}, {})
        status, _, _ = self.run_command()
        self.assertEqual(status, 1)
        self.assertFalse(self.output.exists())
        self.assert_logged_out()

    def test_csr_and_logout_failure_do_not_expose_either_response(self):
        self.overrides["/api/v1/fleet/mdm/apple/request_csr"] = (500, {"error": PASSWORD}, {})
        self.overrides["/api/v1/fleet/logout"] = (500, {"error": TOKEN}, {})
        self.assertEqual(self.run_command()[0], 1)
        self.assertFalse(self.output.exists())
        self.assert_logged_out()

    def test_redirect_does_not_forward_session(self):
        self.overrides["/api/v1/fleet/mdm/apple/request_csr"] = (
            302, {}, {"Location": self.endpoint + "/stolen"})
        self.assertEqual(self.run_command()[0], 1)
        self.assertNotIn("/stolen", [call[1] for call in self.calls])
        self.assertFalse(self.output.exists())
        self.assert_logged_out()

    def test_private_subprocess_failure_has_no_api_or_output_file(self):
        error = subprocess.CalledProcessError(1, ["kubectl"], output=PASSWORD, stderr=PRIVATE)
        self.assertEqual(self.run_command(error)[0], 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
