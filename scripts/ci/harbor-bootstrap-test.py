#!/usr/bin/env python3
"""Exercise the Harbor bootstrap against a local HTTP API, without credentials."""

import base64
import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("harbor_bootstrap", ROOT / "clusters/homelab/apps/harbor/bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)
ADMIN = "TestAdmin1-do-not-log"
PASSWORDS = {"pull": "TestPull1-do-not-log", "publisher": "TestPush1-do-not-log"}


class HarborAPI:
    def __init__(self):
        self.config = {"self_registration": {"value": True},
                       "project_creation_restriction": {"value": "everyone"},
                       "robot_name_prefix": {"value": "robot$"}}
        self.project = None
        self.robots = {}
        self.passwords = {}
        self.requests = []
        self.override = None

    def respond(self, method, path, body):
        self.requests.append((method, path, copy.deepcopy(body)))
        if self.override:
            result = self.override(method, path, body)
            if result:
                return result
        if path == "/configurations":
            if method == "PUT":
                for key, value in body.items():
                    self.config[key]["value"] = value
                return 200, b"", {}
            return 200, self.config, {}
        if path == "/projects" and method == "POST":
            if self.project:
                return 409, {"error": "already exists"}, {}
            self.project = {"name": body["project_name"], "project_id": 7,
                            "metadata": copy.deepcopy(body["metadata"])}
            return 201, b"", {}
        if path == "/projects/homelab":
            if not self.project:
                return 404, {}, {}
            if method == "PUT":
                self.project["metadata"].update(body["metadata"])
                return 200, b"", {}
            return 200, self.project, {}
        if path.startswith("/robots?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            if query.get("q") != ["Level=project,ProjectID=7"]:
                return 400, {"error": "incorrect project robot query"}, {}
            return 200, list(self.robots.values()) or None, {"X-Total-Count": str(len(self.robots))}
        if path == "/robots" and method == "POST":
            identifier = max(self.robots, default=0) + 1
            name = bootstrap.robot_name(body["name"])
            if any(robot["name"] == name for robot in self.robots.values()):
                return 409, {"error": "already exists"}, {}
            self.robots[identifier] = {**copy.deepcopy(body), "id": identifier, "name": name, "editable": True}
            # Harbor 2.15.2 ignores caller-supplied creation secrets.
            self.passwords[identifier] = "Generated-do-not-log1"
            return 201, {"id": identifier, "name": name, "secret": self.passwords[identifier]}, {}
        if path.startswith("/robots/"):
            identifier = int(path.rsplit("/", 1)[1])
            if identifier not in self.robots:
                return 404, {}, {}
            if method == "GET":
                return 200, self.robots[identifier], {}
            if method == "PUT":
                self.robots[identifier].update(copy.deepcopy(body))
                return 200, b"", {}
            if method == "PATCH":
                self.passwords[identifier] = body["secret"]
                return 200, {"secret": ""}, {}
        return 400, {"error": "unsupported operation"}, {}


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.api = HarborAPI()
        api = self.api

        class Handler(BaseHTTPRequestHandler):
            def handle_api(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(body) if body else None
                auth = base64.b64encode(f"admin:{ADMIN}".encode()).decode()
                if self.headers.get("Authorization") != f"Basic {auth}":
                    status, document, headers = 401, {"credential": ADMIN}, {}
                else:
                    path = self.path.removeprefix("/api/v2.0")
                    status, document, headers = api.respond(self.command, path, body)
                payload = document if isinstance(document, bytes) else json.dumps(document).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = handle_api

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.client = bootstrap.Client(ADMIN, self.endpoint)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def reconcile(self):
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.reconcile(self.client, PASSWORDS)

    def main(self):
        output = io.StringIO()
        client_class = bootstrap.Client
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "admin-password").write_text(ADMIN)
            for name, filename in bootstrap.SECRET_FILES.items():
                (directory / filename).write_text(PASSWORDS[name])
            with patch.object(bootstrap, "SECRET_DIRECTORY", directory), \
                    patch.object(bootstrap, "Client", lambda password: client_class(password, self.endpoint)), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = bootstrap.main()
        self.assert_no_credentials(output.getvalue())
        return result, output.getvalue()

    def assert_no_credentials(self, text):
        for secret in (ADMIN, *PASSWORDS.values(), "Generated-do-not-log1"):
            self.assertNotIn(secret, text)
            self.assertNotIn(base64.b64encode(f"admin:{secret}".encode()).decode(), text)

    def mutations(self):
        return [(method, path, body) for method, path, body in self.api.requests if method != "GET"]

    def test_initial_bootstrap_and_repeat_preserve_identities_and_least_privilege(self):
        self.assertEqual(self.main()[0], 0)
        self.assertEqual(self.api.project["metadata"]["public"], "false")
        self.assertFalse(self.api.config["self_registration"]["value"])
        self.assertEqual(self.api.config["project_creation_restriction"]["value"], "adminonly")
        original = copy.deepcopy(self.api.robots)
        self.assertEqual(len(original), 2)
        for name in bootstrap.ROBOTS:
            robot = next(robot for robot in original.values() if robot["name"] == bootstrap.robot_name(name))
            self.assertEqual(robot["permissions"], bootstrap.permissions(name))
            self.assertEqual(self.api.passwords[robot["id"]], PASSWORDS[name])
        self.api.requests.clear()
        self.reconcile()
        self.assertEqual(self.api.robots, original)
        self.assertEqual([(method, path) for method, path, _ in self.mutations()],
                         [("PATCH", "/robots/1"), ("PATCH", "/robots/2")])

    def test_reconciles_public_project_and_robot_drift_without_touching_other_robots(self):
        self.reconcile()
        self.api.project["metadata"].update(public="true", auto_scan="true")
        self.api.robots[1]["disable"] = True
        self.api.robots[1]["permissions"][0]["access"].append(
            {"resource": "repository", "action": "delete", "effect": "allow"})
        other = copy.deepcopy(self.api.robots[2])
        other.update(id=30, name="robot$homelab+other")
        self.api.robots[30] = other
        self.api.requests.clear()
        self.reconcile()
        self.assertEqual(self.api.robots[30], other)
        self.assertEqual(self.api.project["metadata"], {"public": "false", "auto_scan": "true"})
        self.assertEqual(self.api.robots[1]["permissions"], bootstrap.permissions("pull"))
        self.assertFalse(self.api.robots[1]["disable"])
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.mutations()))

    def test_denied_admin_and_unexpected_response_never_log_credentials(self):
        for status in (401, 403, 500):
            with self.subTest(status=status):
                self.api.requests.clear()
                self.api.override = lambda *_args: (status, {"secret": ADMIN}, {})
                result, output = self.main()
                self.assertEqual(result, 1)
                self.assertIn(f"HTTP {status}", output)
                self.assertEqual(self.mutations(), [])

    def test_malformed_configuration_and_wrong_prefix_fail_before_mutation(self):
        for document in ([], {}, {**self.api.config, "self_registration": {"value": "false"}},
                         {**self.api.config, "robot_name_prefix": {"value": "unexpected$"}},
                         b"malformed " + ADMIN.encode()):
            with self.subTest(document_type=type(document).__name__):
                self.api.requests.clear()
                self.api.override = lambda *_args: (200, document, {})
                self.assertEqual(self.main()[0], 1)
                self.assertEqual(self.mutations(), [])

    def test_redirect_is_rejected_without_forwarding_credentials(self):
        self.api.override = lambda *_args: (302, {}, {"Location": self.endpoint + "/sink"})
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(len(self.api.requests), 1)

    def test_ambiguous_robot_listing_fails_before_mutation(self):
        self.reconcile()
        robot = self.api.robots[1]
        self.api.requests.clear()
        self.api.override = lambda method, path, body: (
            (200, [robot, {**robot, "id": 99}], {"X-Total-Count": "2"}) if path.startswith("/robots?") else None)
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])

    def test_malformed_or_truncated_robot_listing_fails_before_mutation(self):
        self.reconcile()
        for document, count in (({}, "1"), (None, "1"), ([], "1"), ([], "invalid"), ([], "1001")):
            with self.subTest(count=count):
                self.api.requests.clear()
                self.api.override = lambda method, path, body: (
                    (200, document, {"X-Total-Count": count}) if path.startswith("/robots?") else None)
                self.assertEqual(self.main()[0], 1)
                self.assertEqual(self.mutations(), [])

    def test_wrong_project_or_robot_scope_fails_before_mutation(self):
        self.reconcile()
        self.api.requests.clear()
        self.api.project["name"] = "another-project"
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])
        self.api.project["name"] = "homelab"
        self.api.robots[1]["permissions"][0]["namespace"] = "another-project"
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])

    def test_robot_id_read_must_match_expected_name_and_id(self):
        self.reconcile()
        for replacement in ({"name": "robot$homelab+other"}, {"id": 99}):
            with self.subTest(replacement=replacement):
                self.api.requests.clear()
                self.api.override = lambda method, path, body: (
                    (200, {**self.api.robots[1], **replacement}, {}) if path == "/robots/1" else None)
                self.assertEqual(self.main()[0], 1)
                self.assertEqual(self.mutations(), [])

    def test_project_privacy_is_verified_before_robot_creation(self):
        self.api.project = {"project_id": 7, "name": "homelab", "metadata": {"public": "true"}}
        self.api.override = lambda method, path, body: (
            (200, b"", {}) if method == "PUT" and path == "/projects/homelab" else None)
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.api.robots, {})

    def test_invalid_secret_fails_without_network_or_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for value in ("short", "lowercaseonly", "WITH-NO-lower-1\n", "a" * 129):
                (directory / "robot-pull-password").write_text(value)
                with patch.object(bootstrap, "SECRET_DIRECTORY", directory):
                    with self.assertRaises(bootstrap.BootstrapError) as caught:
                        bootstrap.read_secret("robot-pull-password")
                    self.assertNotIn(value, str(caught.exception))
        self.assertEqual(self.api.requests, [])


if __name__ == "__main__":
    unittest.main()
