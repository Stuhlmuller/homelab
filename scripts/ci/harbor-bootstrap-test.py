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
PASSWORDS = {("homelab", "pull"): "TestPull1-do-not-log",
             ("homelab", "publisher"): "TestPush1-do-not-log",
             ("mirror", "publisher"): "TestMirrorPush1-do-not-log"}


class HarborAPI:
    def __init__(self):
        self.config = {"self_registration": {"value": True},
                       "project_creation_restriction": {"value": "everyone"},
                       "robot_name_prefix": {"value": "robot$"}}
        self.projects = {}
        self.robots = {}
        self.passwords = {}
        self.repositories = []
        self.artifacts = {}
        self.registries = {"cgr.dev": {"id": 42, "name": "cgr.dev", "url": "https://cgr.dev",
                                        "type": "docker-registry", "insecure": False}}
        self.replication_policies = {}
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
        if path.startswith("/registries?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            registry = self.registries.get(query.get("name", [""])[0])
            return 200, ([registry] if registry else []), {}
        if path.startswith("/registries/"):
            identifier = int(path.rsplit("/", 1)[1])
            registry = next((item for item in self.registries.values() if item["id"] == identifier), None)
            if registry is None:
                return 404, {}, {}
            if method == "PUT":
                registry.update({key: copy.deepcopy(value) for key, value in body.items() if key != "credential"})
                return 200, b"", {}
            return 200, registry, {}
        if path == "/registries" and method == "POST":
            identifier = max((item["id"] for item in self.registries.values()), default=0) + 1
            self.registries[body["name"]] = {**copy.deepcopy(body), "id": identifier}
            return 201, self.registries[body["name"]], {}
        if path.startswith("/replication/policies?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            policy = self.replication_policies.get(query.get("name", [""])[0])
            return 200, ([policy] if policy else []), {}
        if path == "/replication/policies" and method == "POST":
            identifier = max(self.replication_policies.values(), key=lambda item: item["id"], default={"id": 0})["id"] + 1
            self.replication_policies[body["name"]] = {**copy.deepcopy(body), "id": identifier}
            return 201, self.replication_policies[body["name"]], {}
        if path.startswith("/replication/policies/"):
            identifier = int(path.rsplit("/", 1)[1])
            policy = next((item for item in self.replication_policies.values() if item["id"] == identifier), None)
            if policy is None:
                return 404, {}, {}
            if method == "PUT":
                policy.clear()
                policy.update({**copy.deepcopy(body), "id": identifier})
                return 200, b"", {}
            return 200, policy, {}
        if path == "/projects" and method == "POST":
            name = body["project_name"]
            if name in self.projects:
                return 409, {"error": "already exists"}, {}
            self.projects[name] = {"name": name, "project_id": len(self.projects) + 7,
                                  "metadata": copy.deepcopy(body["metadata"])}
            return 201, b"", {}
        if path.startswith("/projects/homelab/repositories"):
            parsed = urllib.parse.urlsplit(path)
            query = urllib.parse.parse_qs(parsed.query)
            parts = parsed.path.split("/")
            if len(parts) == 4:
                objects = self.repositories
            else:
                name = urllib.parse.unquote(urllib.parse.unquote(parts[4]))
                objects = self.artifacts.get(name, [])
                if len(parts) > 6:
                    artifact = next(item for item in objects if item["digest"] == parts[6])
                    if method == "POST" and parts[-1] == "scan":
                        artifact["scan_overview"] = {"vulnerability": {"scan_status": "Pending"}}
                        return 202, b"", {}
                    return 200, artifact, {}
            page = int(query.get("page", ["1"])[0])
            size = int(query.get("page_size", ["100"])[0])
            return 200, objects[(page - 1) * size:page * size], {"X-Total-Count": str(len(objects))}
        if path.startswith("/projects/"):
            project = self.projects.get(path.rsplit("/", 1)[1])
            if not project:
                return 404, {}, {}
            if method == "PUT":
                project["metadata"].update(body["metadata"])
                return 200, b"", {}
            return 200, project, {}
        if path.startswith("/robots?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            project = next((project for project in self.projects.values() if query.get("q") ==
                            [f"Level=project,ProjectID={project['project_id']}"]), None)
            if project is None:
                return 400, {"error": "incorrect project robot query"}, {}
            # Scope fixture robots by name so malformed permissions remain visible
            # to the identity checks exercised below.
            robots = [robot for robot in self.robots.values()
                      if robot["name"].startswith(f"robot${project['name']}+")]
            return 200, robots or None, {"X-Total-Count": str(len(robots))}
        if path == "/robots" and method == "POST":
            identifier = max(self.robots, default=0) + 1
            name = bootstrap.robot_name(body["name"], body["permissions"][0]["namespace"])
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

    def test_chainguard_policy_is_exact_hourly_and_non_destructive(self):
        self.assertTrue(bootstrap.validate_replication_policy())
        desired = bootstrap.desired_replication_policy(bootstrap.CHAINGUARD_REPLICATION["rules"][0], 42)
        self.assertEqual(desired["src_registry"], {"id": 42})
        self.assertEqual(desired["trigger"]["trigger_settings"], {"cron": "0 * * * *"})
        self.assertFalse(desired["replicate_deletion"])
        self.assertTrue(desired["override"])
        self.assertTrue(desired["enabled"])
        bad = copy.deepcopy(bootstrap.CHAINGUARD_REPLICATION)
        bad["rules"] = ({**bad["rules"][0], "delete": True},)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_replication_policy(bad)

    def test_paused_policy_disables_native_rules(self):
        rule = bootstrap.CHAINGUARD_REPLICATION["rules"][0]
        desired = bootstrap.desired_replication_policy(rule, 42, paused=True)
        self.assertFalse(desired["enabled"])

    def test_empty_or_duplicate_replication_rules_are_rejected(self):
        empty = copy.deepcopy(bootstrap.CHAINGUARD_REPLICATION)
        empty["rules"] = ()
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_replication_policy(empty)
        duplicate = copy.deepcopy(bootstrap.CHAINGUARD_REPLICATION)
        duplicate["rules"] = (duplicate["rules"][0], duplicate["rules"][0])
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_replication_policy(duplicate)

    def test_native_replication_reconciles_exact_rules_without_deletes(self):
        class Client:
            def __init__(self):
                self.calls = []
                self.policies = {}

            def request(self, method, path, body=None, expected=(200,), json_response=True):
                self.calls.append((method, path, body))
                if path == "/registries?name=cgr.dev":
                    return [{"id": 42, "name": "cgr.dev", "url": "https://cgr.dev",
                             "type": "docker-registry", "insecure": False}], {}
                if path == "/registries/42":
                    return {"id": 42, "name": "cgr.dev", "url": "https://cgr.dev",
                            "type": "docker-registry", "insecure": False}, {}
                if path.startswith("/replication/policies?name=chainguard-"):
                    name = path.split("=", 1)[1]
                    return ([self.policies[name]] if name in self.policies else []), {}
                if path == "/replication/policies" and method == "POST":
                    policy = {**body, "id": 7 + len(self.policies)}
                    self.policies[body["name"]] = policy
                    return policy, {}
                if path.startswith("/replication/policies/") and method == "GET":
                    identifier = int(path.rsplit("/", 1)[1])
                    return next(policy for policy in self.policies.values() if policy["id"] == identifier), {}
                raise AssertionError((method, path))

        client = Client()
        bootstrap.reconcile_replication(client, bootstrap.CHAINGUARD_REPLICATION)
        self.assertEqual([call[0:2] for call in client.calls], [
            ("GET", "/registries?name=cgr.dev"),
            ("GET", "/registries/42"),
            ("GET", "/replication/policies?name=chainguard-python"),
            ("POST", "/replication/policies"),
            ("GET", "/replication/policies/7"),
            ("GET", "/replication/policies?name=chainguard-curl"),
            ("POST", "/replication/policies"),
            ("GET", "/replication/policies/8"),
        ])
        policy = client.policies["chainguard-python"]
        self.assertEqual(policy["trigger"]["trigger_settings"], {"cron": "0 * * * *"})
        self.assertFalse(policy["replicate_deletion"])
        self.assertTrue(policy["override"])
        self.assertFalse(policy["filters"][0].get("flatten", False))
        client.calls.clear()
        bootstrap.reconcile_replication(client, bootstrap.CHAINGUARD_REPLICATION)
        self.assertFalse(any(method in {"POST", "PUT", "DELETE"} for method, _, _ in client.calls))
        self.assertFalse(any(method == "DELETE" for method, _, _ in client.calls))

    def test_missing_chainguard_registry_is_created_before_policy_use(self):
        class Client:
            def __init__(self):
                self.calls = []
                self.registry = None

            def request(self, method, path, body=None, expected=(200,), json_response=True):
                self.calls.append((method, path))
                if path == "/registries?name=cgr.dev":
                    return ([] if self.registry is None else [self.registry]), {}
                if path == "/registries" and method == "POST":
                    self.registry = {**body, "id": 42}
                    return self.registry, {}
                if path == "/registries/42":
                    return self.registry, {}
                raise AssertionError((method, path))

        client = Client()
        registry = bootstrap.reconcile_registry(client, "cgr.dev")
        self.assertEqual(registry["name"], "cgr.dev")
        self.assertEqual(client.calls, [
            ("GET", "/registries?name=cgr.dev"),
            ("POST", "/registries"),
            ("GET", "/registries/42"),
        ])

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
            replication = directory / "chainguard-replication.json"
            replication.write_text(json.dumps(bootstrap.CHAINGUARD_REPLICATION))
            with patch.object(bootstrap, "SECRET_DIRECTORY", directory), \
                    patch.object(bootstrap, "REPLICATION_FILE", replication), \
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
        self.assertEqual(self.api.projects["homelab"]["metadata"], {"public": "false", "auto_scan": "true"})
        self.assertFalse(self.api.config["self_registration"]["value"])
        self.assertEqual(self.api.config["project_creation_restriction"]["value"], "adminonly")
        original = copy.deepcopy(self.api.robots)
        self.assertEqual(len(original), 3)
        self.assertEqual(self.api.projects["mirror"]["metadata"], {"public": "true", "auto_scan": "true"})
        for project_name, settings in bootstrap.PROJECTS.items():
            for name in settings["robots"]:
                robot = next(robot for robot in original.values()
                             if robot["name"] == bootstrap.robot_name(name, project_name))
                self.assertEqual(robot["permissions"], bootstrap.permissions(name, project_name))
                self.assertEqual(self.api.passwords[robot["id"]], PASSWORDS[(project_name, name)])
        self.assertNotEqual(self.api.passwords[2], self.api.passwords[3])
        self.api.requests.clear()
        self.reconcile()
        self.assertEqual(self.api.robots, original)
        self.assertEqual([(method, path) for method, path, _ in self.mutations()],
                         [("PATCH", "/robots/1"), ("PATCH", "/robots/2"), ("PATCH", "/robots/3")])

    def test_reconciles_public_project_and_robot_drift_without_touching_other_robots(self):
        self.reconcile()
        self.api.projects["homelab"]["metadata"].update(public="true", auto_scan="true")
        self.api.robots[1]["disable"] = True
        self.api.robots[1]["permissions"][0]["access"].append(
            {"resource": "repository", "action": "delete", "effect": "allow"})
        other = copy.deepcopy(self.api.robots[2])
        other.update(id=30, name="robot$homelab+other")
        self.api.robots[30] = other
        self.api.requests.clear()
        self.reconcile()
        self.assertEqual(self.api.robots[30], other)
        self.assertEqual(self.api.projects["homelab"]["metadata"], {"public": "false", "auto_scan": "true"})
        self.assertEqual(self.api.robots[1]["permissions"], bootstrap.permissions("pull", "homelab"))
        self.assertFalse(self.api.robots[1]["disable"])
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.mutations()))

    def test_mirror_repair_preserves_private_project_and_rejects_cross_project_scope(self):
        self.reconcile()
        self.api.projects["mirror"]["metadata"].update(public="false", auto_scan="false")
        homelab = copy.deepcopy(self.api.projects["homelab"])
        private_robots = copy.deepcopy({key: self.api.robots[key] for key in (1, 2)})
        self.reconcile()
        self.assertEqual(self.api.projects["mirror"]["metadata"], {"public": "true", "auto_scan": "true"})
        self.assertEqual(self.api.projects["homelab"], homelab)
        self.assertEqual({key: self.api.robots[key] for key in (1, 2)}, private_robots)
        mirror_robot = self.api.robots[3]
        self.assertEqual(mirror_robot["name"], "robot$mirror+publisher")
        self.assertEqual(mirror_robot["permissions"], [{"kind": "project", "namespace": "mirror", "access": [
            {"resource": "repository", "action": "pull", "effect": "allow"},
            {"resource": "repository", "action": "push", "effect": "allow"}]}])
        mirror_robot["permissions"][0]["namespace"] = "homelab"
        self.api.requests.clear()
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])

    def test_existing_proxy_cache_project_fails_before_mutation(self):
        self.reconcile()
        self.api.projects["mirror"]["registry_id"] = 12
        self.api.requests.clear()
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])

    def test_enables_missing_or_disabled_scanning_and_preserves_other_metadata(self):
        for metadata in ({"public": "false"}, {"public": "false", "auto_scan": "false"}):
            with self.subTest(metadata=metadata):
                self.api.projects["homelab"] = {"project_id": 7, "name": "homelab",
                                                 "metadata": {**metadata, "severity": "high"}}
                self.reconcile()
                self.assertEqual(self.api.projects["homelab"]["metadata"],
                                 {"public": "false", "auto_scan": "true", "severity": "high"})

    def test_ignored_scanning_update_fails_verification(self):
        self.api.projects["homelab"] = {"project_id": 7, "name": "homelab",
                                         "metadata": {"public": "false", "auto_scan": "false"}}
        self.api.override = lambda method, path, body: (
            (200, b"", {}) if method == "PUT" and path == "/projects/homelab" else None)
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.api.robots, {})

    def image(self, identifier, **changes):
        return {"id": identifier, "type": "IMAGE", "digest": f"sha256:{identifier:064x}",
                "media_type": "application/vnd.oci.image.config.v1+json",
                "extra_attrs": {"os": "linux", "architecture": "amd64"}, **changes}

    def test_backfill_only_missing_private_image_scans_and_repeat_skips_pending(self):
        self.api.repositories = [{"id": 1, "name": "homelab/nested/app"}]
        artifacts = [self.image(1), self.image(2, scan_overview={}),
                     self.image(3, scan_overview=None, media_type="application/vnd.docker.container.image.v1+json")]
        artifacts += [self.image(index, scan_overview={"vulnerability": {"scan_status": status}})
                      for index, status in enumerate(("Success", "Running", "Pending", "Error"), 4)]
        artifacts += [self.image(8, type="CHART"),
                      self.image(9, media_type="application/vnd.oci.image.index.v1+json"),
                      self.image(10, media_type="application/vnd.in-toto+json"),
                      self.image(11, extra_attrs={"os": "unknown", "architecture": "unknown"}),
                      self.image(12, extra_attrs={}), self.image(13),
                      self.image(14, accessories=[{"artifact_id": 13}],
                                 scan_overview={"vulnerability": {"scan_status": "Success"}})]
        self.api.artifacts["nested/app"] = artifacts
        self.reconcile()
        scans = [(path, body) for method, path, body in self.api.requests if path.endswith("/scan")]
        self.assertEqual(scans, [(f"/projects/homelab/repositories/nested%252Fapp/artifacts/sha256:{i:064x}/scan",
                                 {"scan_type": "vulnerability"}) for i in (1, 2, 3)])
        self.assertFalse(any(path.startswith("/projects/mirror/repositories") for _, path, _ in self.api.requests))
        self.api.requests.clear()
        self.reconcile()
        self.assertFalse(any(path.endswith("/scan") for _, path, _ in self.api.requests))

    def test_backfill_paginates_repositories_and_artifacts(self):
        self.api.repositories = [{"id": i, "name": f"homelab/app{i}"} for i in range(1, 102)]
        self.api.artifacts["app101"] = [self.image(i, scan_overview={"vulnerability": {"scan_status": "Success"}})
                                        for i in range(1, 101)] + [self.image(101)]
        bootstrap.backfill_scans(self.client)
        scans = [path for _, path, _ in self.api.requests if path.endswith("/scan")]
        self.assertEqual(scans, [f"/projects/homelab/repositories/app101/artifacts/sha256:{101:064x}/scan"])
        self.assertTrue(any(path.startswith("/projects/homelab/repositories?") and "page=2" in path
                            for _, path, _ in self.api.requests))
        self.assertTrue(any("/app101/artifacts?" in path and "page=2" in path
                            for _, path, _ in self.api.requests))

    def test_backfill_scans_missing_image_after_one_thousand_artifacts(self):
        self.api.repositories = [{"id": 1, "name": "homelab/app"}]
        self.api.artifacts["app"] = [self.image(i, scan_overview={"vulnerability": {"scan_status": "Success"}})
                                     for i in range(1, 1001)] + [self.image(1001)]
        bootstrap.backfill_scans(self.client)
        scans = [path for _, path, _ in self.api.requests if path.endswith("/scan")]
        self.assertEqual(scans, [f"/projects/homelab/repositories/app/artifacts/sha256:{1001:064x}/scan"])
        self.assertTrue(any("/app/artifacts?" in path and "page=11" in path
                            for _, path, _ in self.api.requests))

    def test_backfill_rechecks_reports_before_requesting_scan(self):
        self.api.repositories = [{"id": 1, "name": "homelab/app"}]
        self.api.artifacts["app"] = [self.image(1)]
        self.api.override = lambda method, path, body: (
            (200, self.image(1, scan_overview={"vulnerability": {"scan_status": "Running"}}), {})
            if "?with_scan_overview=true" in path else None)
        bootstrap.backfill_scans(self.client)
        self.assertEqual(self.mutations(), [])

    def test_backfill_rejects_incomplete_inventory_before_scanning(self):
        self.api.repositories = [{"id": 1, "name": "homelab/app"}]
        for document, count in (([self.image(1)], "2"), ([self.image(1), self.image(1)], "2"),
                                ([], "invalid"), ([], "1001")):
            with self.subTest(count=count):
                self.api.requests.clear()
                self.api.override = lambda method, path, body: (
                    (200, document, {"X-Total-Count": count}) if "/artifacts?" in path else None)
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.backfill_scans(self.client)
                self.assertEqual(self.mutations(), [])

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
        self.api.projects["homelab"]["name"] = "another-project"
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.mutations(), [])
        self.api.projects["homelab"]["name"] = "homelab"
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
        self.api.projects["homelab"] = {"project_id": 7, "name": "homelab", "metadata": {"public": "true"}}
        self.api.override = lambda method, path, body: (
            (200, b"", {}) if method == "PUT" and path == "/projects/homelab" else None)
        self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.api.robots, {})

    def test_shared_publisher_secret_fails_before_network(self):
        with patch.dict(PASSWORDS, {("mirror", "publisher"): PASSWORDS[("homelab", "publisher")]}):
            self.assertEqual(self.main()[0], 1)
        self.assertEqual(self.api.requests, [])

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
