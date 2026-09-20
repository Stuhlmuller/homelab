#!/usr/bin/env python3
"""Reconcile the fixed homelab Harbor project and project-scoped robots.

Run only as the repository-owned PostSync Job. Credentials come from mounted
Secret files; desired state is code, never process environment or CLI input.
Harbor 2.15.2 advertises RobotCreate.secret but ignores it in the handler, so
creation is followed by PATCH of the supplied secret. Every sync reapplies that
same secret because Harbor never returns existing password hashes for comparison.
"""

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ENDPOINT = "http://harbor-core.harbor.svc.cluster.local"
SECRET_DIRECTORY = Path("/secrets")
PROJECT = "homelab"
PREFIX = "robot$"
SETTINGS = {"self_registration": False, "project_creation_restriction": "adminonly"}
ROBOTS = {"pull": ("pull",), "publisher": ("pull", "push")}
SECRET_FILES = {"pull": "robot-pull-password", "publisher": "robot-push-password"}
MAX_RESPONSE_BYTES = 1024 * 1024


class BootstrapError(Exception):
    """Safe diagnostic assembled from repository-owned text only."""


class APIError(BootstrapError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Harbor API returned HTTP {status}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Basic credential to another endpoint.
        return None


class Client:
    def __init__(self, admin_password, endpoint=ENDPOINT):
        self.endpoint = endpoint
        credential = base64.b64encode(f"admin:{admin_password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {credential}", "Accept": "application/json"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None, expected=(200,), json_response=True):
        headers = dict(self.headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.endpoint + "/api/v2.0" + path,
                                     data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=10) as response:
                status = response.status
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                response_headers = response.headers
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            if status == 404 and 404 in expected:
                return None, {}
            raise APIError(status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise BootstrapError("Harbor API connection failed") from None
        if status not in expected:
            raise APIError(status)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BootstrapError("Harbor API response exceeded the size limit")
        if not json_response:
            return None, response_headers
        try:
            return json.loads(raw), response_headers
        except (ValueError, UnicodeError):
            raise BootstrapError("Harbor API returned malformed JSON") from None


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise BootstrapError("Harbor returned an invalid object ID")
    return value


def config_values(document):
    if not isinstance(document, dict):
        raise BootstrapError("Harbor configuration response is not an object")
    values = {}
    for key in (*SETTINGS, "robot_name_prefix"):
        entry = document.get(key)
        if not isinstance(entry, dict) or "value" not in entry:
            raise BootstrapError("Harbor configuration response lacks required settings")
        values[key] = entry["value"]
    if type(values["self_registration"]) is not bool or values["project_creation_restriction"] not in (
        "adminonly", "everyone"
    ):
        raise BootstrapError("Harbor configuration response has invalid setting types")
    if values["robot_name_prefix"] != PREFIX:
        raise BootstrapError("Harbor robot prefix does not match the declared credential contract")
    return values


def read_project(client):
    project, _ = client.request("GET", f"/projects/{PROJECT}", expected=(200, 404))
    if project is None:
        return None
    if not isinstance(project, dict) or project.get("name") != PROJECT:
        raise BootstrapError("Harbor returned the wrong project")
    positive_id(project.get("project_id"))
    metadata = project.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("public") not in ("true", "false"):
        raise BootstrapError("Harbor project lacks a valid privacy setting")
    return project


def robot_name(name):
    return f"{PREFIX}{PROJECT}+{name}"


def read_robots(client, project_id):
    robots = {}
    seen_ids = set()
    expected_total = None
    count = 0
    for page in range(1, 11):
        # Harbor defaults /robots to system robots; project filtering is explicit.
        query = urllib.parse.urlencode({"q": f"Level=project,ProjectID={project_id}",
                                        "page": page, "page_size": 100})
        document, headers = client.request("GET", "/robots?" + query)
        try:
            total = int(headers.get("X-Total-Count", ""))
        except (ValueError, TypeError):
            raise BootstrapError("Harbor robot list lacks a valid total count") from None
        if total < 0 or total > 1000 or (expected_total is not None and total != expected_total):
            raise BootstrapError("Harbor robot listing changed or exceeded its bounded limit")
        expected_total = total
        # Harbor's Go handler serializes an empty result slice as null.
        if document is None and total == 0:
            document = []
        if not isinstance(document, list) or len(document) > 100:
            raise BootstrapError("Harbor robot listing is malformed")
        for robot in document:
            if not isinstance(robot, dict) or not isinstance(robot.get("name"), str):
                raise BootstrapError("Harbor robot listing contains an invalid object")
            identifier = positive_id(robot.get("id"))
            if identifier in seen_ids or robot["name"] in robots:
                raise BootstrapError("Harbor robot listing is ambiguous")
            seen_ids.add(identifier)
            robots[robot["name"]] = robot
        count += len(document)
        if count == total:
            return robots
        if not document or count > total:
            raise BootstrapError("Harbor robot pagination is inconsistent")
    raise BootstrapError("Harbor robot listing exceeded its bounded limit")


def permissions(name):
    return [{"kind": "project", "namespace": PROJECT,
             "access": [{"resource": "repository", "action": action, "effect": "allow"}
                        for action in ROBOTS[name]]}]


def validate_robot(robot, name, identifier=None):
    if not isinstance(robot, dict) or robot.get("name") != robot_name(name):
        raise BootstrapError("Harbor returned the wrong robot name")
    actual_id = positive_id(robot.get("id"))
    if identifier is not None and actual_id != identifier:
        raise BootstrapError("Harbor returned the wrong robot ID")
    if robot.get("level") != "project" or robot.get("editable") is not True:
        raise BootstrapError("Harbor robot is not an editable project robot")
    scopes = robot.get("permissions")
    if not isinstance(scopes, list) or len(scopes) != 1 or not isinstance(scopes[0], dict):
        raise BootstrapError("Harbor robot has an ambiguous permission scope")
    if scopes[0].get("kind") != "project" or scopes[0].get("namespace") != PROJECT:
        raise BootstrapError("Harbor robot belongs to a different permission scope")
    access = scopes[0].get("access")
    if not isinstance(access, list) or any(not isinstance(item, dict) for item in access):
        raise BootstrapError("Harbor robot permissions are malformed")
    return actual_id


def desired_robot(name):
    return {"name": robot_name(name), "level": "project", "duration": -1,
            "description": f"Repository-managed homelab {name} robot", "disable": False,
            "permissions": permissions(name)}


def robot_matches(robot, desired):
    # API permission order is not stable; implicit effect means allow.
    actual = robot["permissions"][0]["access"]
    wanted = desired["permissions"][0]["access"]
    def normalize(items):
        return sorted(json.dumps({**item, "effect": item.get("effect") or "allow"},
                                 sort_keys=True) for item in items)
    return all(robot.get(key) == value for key, value in desired.items() if key != "permissions") and (
        normalize(actual) == normalize(wanted)
    )


def reconcile(client, robot_passwords):
    # Finish the relevant read-only identity and schema checks before writing.
    config, _ = client.request("GET", "/configurations")
    current = config_values(config)
    project = read_project(client)
    robots = read_robots(client, project["project_id"]) if project else {}
    for name in ROBOTS:
        robot = robots.get(robot_name(name))
        if robot:
            validate_robot(robot, name)

    changes = {key: value for key, value in SETTINGS.items() if current[key] != value}
    if changes:
        client.request("PUT", "/configurations", changes, json_response=False)
    if project is None:
        client.request("POST", "/projects", {"project_name": PROJECT, "metadata": {"public": "false"}},
                       expected=(201,), json_response=False)
    elif project["metadata"]["public"] != "false":
        client.request("PUT", f"/projects/{PROJECT}", {"metadata": {"public": "false"}},
                       json_response=False)
    project = read_project(client)
    if project is None or project["metadata"]["public"] != "false":
        raise BootstrapError("Harbor private project verification failed")

    for name in ROBOTS:
        desired = desired_robot(name)
        robot = robots.get(robot_name(name))
        if robot is None:
            created, _ = client.request("POST", "/robots", {**desired, "name": name}, expected=(201,))
            if not isinstance(created, dict) or created.get("name") != robot_name(name):
                raise BootstrapError("Harbor created an unexpected robot")
            identifier = positive_id(created.get("id"))
        else:
            identifier = validate_robot(robot, name)
        path = f"/robots/{identifier}"
        # Re-read by immutable ID before mutating credentials or permissions.
        robot, _ = client.request("GET", path)
        validate_robot(robot, name, identifier)
        if not robot_matches(robot, desired):
            client.request("PUT", path, desired, json_response=False)
        client.request("PATCH", path, {"secret": robot_passwords[name]})
        verified, _ = client.request("GET", path)
        validate_robot(verified, name, identifier)
        if not robot_matches(verified, desired):
            raise BootstrapError("Harbor robot desired-state verification failed")

    config, _ = client.request("GET", "/configurations")
    current = config_values(config)
    if any(current[key] != value for key, value in SETTINGS.items()):
        raise BootstrapError("Harbor configuration verification failed")
    print("Harbor homelab project is private; pull and publisher robots reconciled.")


def read_secret(name):
    try:
        value = (SECRET_DIRECTORY / name).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise BootstrapError("A required Harbor credential file is unavailable") from None
    if not 8 <= len(value) <= 128 or any(char.isspace() for char in value):
        raise BootstrapError("A Harbor credential has an invalid length or whitespace")
    if name != "admin-password" and not all(re.search(pattern, value) for pattern in ("[a-z]", "[A-Z]", "[0-9]")):
        raise BootstrapError("A Harbor robot credential lacks required character classes")
    return value


def main():
    try:
        admin_password = read_secret("admin-password")
        passwords = {name: read_secret(filename) for name, filename in SECRET_FILES.items()}
        client = Client(admin_password)
        # Retry only transient reads. Auth/schema/write failures never trigger a
        # fallback identity or a retry that might duplicate a created resource.
        for attempt in range(12):
            try:
                config, _ = client.request("GET", "/configurations")
                config_values(config)
                break
            except APIError as error:
                if error.status not in (502, 503, 504) or attempt == 11:
                    raise
            except BootstrapError as error:
                if str(error) != "Harbor API connection failed" or attempt == 11:
                    raise
            time.sleep(5)
        reconcile(client, passwords)
    except BootstrapError as error:
        print(f"Harbor bootstrap failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Do not print exception repr, response bodies, headers, or tracebacks:
        # all can contain credentials supplied by Harbor or mounted secrets.
        print("Harbor bootstrap failed: unexpected local error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
