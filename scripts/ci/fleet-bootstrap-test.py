#!/usr/bin/env python3
"""Exercise Fleet first-run API, credential redaction, and ingress boundaries."""

import contextlib
import importlib.util
import io
import json
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/fleet"
SPEC = importlib.util.spec_from_file_location("fleet_bootstrap", APP / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
PASSWORD = "Aa1!PRIVATE_PASSWORD_DO_NOT_LOG".ljust(44, "x")
TOKEN = "PRIVATE_SESSION_DO_NOT_LOG"
PRIVATE = "PRIVATE_RESPONSE_DO_NOT_LOG"


class FleetAPI:
    def __init__(self):
        self.initialized = False
        self.session = False
        self.requests = []
        self.overrides = {}

    def respond(self, method, path, body, authorization):
        self.requests.append((method, path, body, authorization))
        if (method, path) in self.overrides:
            return self.overrides[(method, path)]
        if (method, path) == ("POST", "/api/v1/setup"):
            if self.initialized:
                return 404, {"error": PRIVATE}, {}
            self.initialized = self.session = True
            return 200, {"admin": {"email": bootstrap.ADMIN_EMAIL,
                                    "global_role": "admin"}, "token": TOKEN}, {}
        if authorization != "Bearer " + TOKEN or not self.session:
            return 401, {"error": PRIVATE}, {}
        if (method, path) == ("GET", "/api/v1/fleet/me"):
            return 200, {"user": {"email": bootstrap.ADMIN_EMAIL,
                                   "global_role": "admin"}}, {}
        if (method, path) == ("POST", "/api/v1/fleet/logout"):
            self.session = False
            return 200, {}, {}
        return 404, {"error": PRIVATE}, {}


class BootstrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def handle_api(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw) if raw else None
                status, document, headers = self.server.fixture.respond(
                    self.command, self.path, body, self.headers.get("Authorization"))
                payload = document if isinstance(document, bytes) else json.dumps(document).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PATCH = handle_api

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
        self.api = FleetAPI()
        self.server.fixture = self.api

    def run_main(self, password=PASSWORD):
        output = io.StringIO()
        with patch.object(bootstrap, "ENDPOINT", self.endpoint), \
                patch.object(bootstrap.Path, "read_text", return_value=password), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = bootstrap.main()
        text = output.getvalue()
        for sentinel in (PASSWORD, TOKEN, PRIVATE):
            self.assertNotIn(sentinel, text)
        self.assertNotIn("Traceback", text)
        return status, text

    def routes(self):
        return [(method, path) for method, path, *_ in self.api.requests]

    def test_initial_setup_authenticates_and_revokes_session(self):
        status, output = self.run_main()
        self.assertEqual(status, 0)
        self.assertIn("session revoked", output)
        self.assertEqual(self.routes(), [
            ("POST", "/api/v1/setup"), ("GET", "/api/v1/fleet/me"),
            ("POST", "/api/v1/fleet/logout")])
        request = self.api.requests[0]
        self.assertEqual(request[2]["admin"]["password"], PASSWORD)
        self.assertEqual(request[2]["server_url"], bootstrap.SERVER_URL)
        self.assertIsNone(request[3])
        self.assertFalse(self.api.session)

    def test_repeat_setup_preserves_existing_configuration_and_users(self):
        self.api.initialized = True
        status, output = self.run_main()
        self.assertEqual(status, 0)
        self.assertIn("existing accounts preserved", output)
        self.assertEqual(self.routes(), [
            ("POST", "/api/v1/setup"), ("GET", "/api/v1/fleet/me")])
        self.assertFalse(self.api.session)

    def test_closed_setup_requires_authenticated_api_challenge(self):
        self.api.initialized = True
        for status in (200, 302, 403, 404, 500):
            with self.subTest(status=status):
                self.api.overrides[("GET", "/api/v1/fleet/me")] = (status, {}, {})
                self.assertEqual(self.run_main()[0], 1)

    def test_setup_errors_and_malformed_responses_are_redacted(self):
        responses = [(500, {"error": PRIVATE}, {}), (200, b"not-json:" + PRIVATE.encode(), {}),
                     (200, None, {}), (200, [], {}), (200, {"token": None}, {}),
                     (200, {"token": ""}, {}), (200, {"token": 7}, {})]
        for response in responses:
            with self.subTest(response_type=type(response[1]).__name__):
                self.api.overrides[("POST", "/api/v1/setup")] = response
                self.assertEqual(self.run_main()[0], 1)

    def test_invalid_admin_response_still_revokes_returned_session(self):
        for admin in (None, [], {"email": bootstrap.ADMIN_EMAIL, "global_role": "observer"}):
            with self.subTest(admin_type=type(admin).__name__):
                self.api.session = True
                self.api.overrides[("POST", "/api/v1/setup")] = (
                    200, {"token": TOKEN, "admin": admin}, {})
                self.assertEqual(self.run_main()[0], 1)
                self.assertEqual(self.routes()[-1], ("POST", "/api/v1/fleet/logout"))
                self.assertFalse(self.api.session)

    def test_authentication_failure_revokes_session(self):
        for user in (None, [], {"email": "someone@example.com", "global_role": "admin"}):
            with self.subTest(user_type=type(user).__name__):
                self.api.initialized = False
                self.api.overrides[("GET", "/api/v1/fleet/me")] = (200, {"user": user}, {})
                self.assertEqual(self.run_main()[0], 1)
                self.assertFalse(self.api.session)
                self.assertNotIn(("PATCH", "/api/v1/fleet/config"), self.routes())

    def test_logout_failure_cannot_report_success(self):
        self.api.overrides[("POST", "/api/v1/fleet/logout")] = (500, {"error": TOKEN}, {})
        status, output = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("session cleanup failed", output)

    def test_redirect_does_not_forward_password_or_session(self):
        self.api.overrides[("POST", "/api/v1/setup")] = (
            307, {}, {"Location": self.endpoint + "/stolen"})
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.routes(), [("POST", "/api/v1/setup")])

    def test_oversized_response_is_rejected(self):
        self.api.overrides[("POST", "/api/v1/setup")] = (
            200, b"x" * (bootstrap.MAX_RESPONSE + 1), {})
        self.assertEqual(self.run_main()[0], 1)

    def test_missing_password_stops_before_network(self):
        for password in ("", "REPLACE_ME", "short"):
            self.assertEqual(self.run_main(password)[0], 1)
        self.assertEqual(self.api.requests, [])

    def test_transport_and_file_exceptions_withhold_private_details(self):
        with patch.object(bootstrap.urllib.request.OpenerDirector, "open",
                          side_effect=OSError(PRIVATE)):
            self.assertEqual(self.run_main()[0], 1)
        output = io.StringIO()
        with patch.object(bootstrap.Path, "read_text", side_effect=OSError(PRIVATE)), \
                contextlib.redirect_stderr(output):
            self.assertEqual(bootstrap.main(), 1)
        self.assertNotIn(PRIVATE, output.getvalue())


class RoutingTest(unittest.TestCase):
    def test_bootstrap_uses_private_admin_secret_without_kubernetes_access(self):
        job = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(APP / "bootstrap-job.yaml")], text=True))
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        pod = job["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "fleet-bootstrap")
        self.assertIs(pod["automountServiceAccountToken"], False)
        self.assertEqual([volume["secret"]["secretName"] for volume in pod["volumes"]
                          if "secret" in volume], ["fleet-admin"])
        container = pod["containers"][0]
        self.assertEqual(container["command"], ["python3", "-I", "-B", "/scripts/bootstrap.py"])
        self.assertIs(container["securityContext"]["readOnlyRootFilesystem"], True)
        self.assertTrue(all(mount.get("readOnly") is True for mount in container["volumeMounts"]))

    def test_setup_aliases_are_blocked_without_blocking_setup_experience(self):
        route = json.loads(subprocess.check_output(
            ["yq", "-o=json", ".", str(APP / "virtualservice.yaml")], text=True))
        self.assertEqual(route["spec"]["hosts"], ["fleet.stinkyboi.com"])
        rules = route["spec"]["http"]

        def matched_rule(path):
            for rule in rules:
                if not rule.get("match"):
                    return rule
                for match in rule["match"]:
                    uri = match.get("uri", {})
                    if uri.get("exact") == path or ("prefix" in uri and path.startswith(uri["prefix"])):
                        return rule
            return None

        for path in ("/api/v1/setup", "/api/setup", "/setup",
                     "/api/v1/setup/", "/api/setup/", "/setup/new"):
            with self.subTest(path=path):
                self.assertEqual(matched_rule(path).get("directResponse"), {"status": 404})
        for path in ("/setup_experience", "/api/v1/setup_experience", "/api/setup_experience",
                     "/api/v1/fleet/setup_experience", "/api/v1/fleet/login", "/mdm/apple/mdm"):
            with self.subTest(path=path):
                self.assertEqual(matched_rule(path)["route"][0]["destination"], {
                    "host": "fleet.fleet.svc.cluster.local", "port": {"number": 8080}})


if __name__ == "__main__":
    unittest.main()
