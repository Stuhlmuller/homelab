#!/usr/bin/env python3
"""Reconcile the fixed Harbor projects and project-scoped robots.

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
REPLICATION_FILE = Path("/replication/chainguard-replication.json")
PREFIX = "robot$"
PROJECTS = {
    "homelab": {"metadata": {"public": "false", "auto_scan": "true"}, "robots": ("pull", "publisher")},
    "mirror": {"metadata": {"public": "true", "auto_scan": "true"}, "robots": ("publisher",)},
}
SETTINGS = {"self_registration": False, "project_creation_restriction": "adminonly"}
CHAINGUARD_REPLICATION = {
    "schedule": "0 * * * *",
    "source_registry": "cgr.dev",
    "paused": False,
    "rules": (
        {"repository": "chainguard/python", "source_tag": "latest",
         "destination": "homelab/chainguard-python", "override": True,
         "delete": False, "flatten": False, "access_class": "public"},
        {"repository": "chainguard/curl", "source_tag": "latest",
         "destination": "homelab/chainguard-curl", "override": True,
         "delete": False, "flatten": False, "access_class": "public"},
    ),
}
CHAINGUARD_REGISTRY = {
    "name": "cgr.dev",
    "url": "https://cgr.dev",
    "type": "docker-registry",
    "insecure": False,
    "credential": {"type": "basic", "access_key": "", "access_secret": ""},
}
ROBOTS = {"pull": ("pull",), "publisher": ("pull", "push")}
SECRET_FILES = {
    ("homelab", "pull"): "robot-pull-password",
    ("homelab", "publisher"): "robot-push-password",
    ("mirror", "publisher"): "mirror-robot-push-password",
}
MAX_RESPONSE_BYTES = 1024 * 1024


class BootstrapError(Exception):
    """Safe diagnostic assembled from repository-owned text only."""


class APIError(BootstrapError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Harbor API returned HTTP {status}")


def validate_replication_policy(policy=CHAINGUARD_REPLICATION):
    """Validate exact-name, non-destructive Chainguard replication intent."""
    if policy.get("source_registry") != "cgr.dev" or policy.get("schedule") != "0 * * * *":
        raise BootstrapError("Chainguard replication schedule/source changed")
    if type(policy.get("paused")) is not bool or not isinstance(policy.get("rules"), (list, tuple)):
        raise BootstrapError("Chainguard replication policy is malformed")
    if not policy["rules"]:
        raise BootstrapError("Chainguard replication policy has no rules")
    repositories = set()
    destinations = set()
    for rule in policy["rules"]:
        if set(rule) != {"repository", "source_tag", "destination", "override", "delete", "flatten", "access_class"}:
            raise BootstrapError("Chainguard replication rule fields are not explicit")
        if not re.fullmatch(r"chainguard/[a-z0-9][a-z0-9.-]*", rule["repository"]):
            raise BootstrapError("Chainguard replication repository is not exact")
        if rule["repository"] in repositories or rule["destination"] in destinations:
            raise BootstrapError("Chainguard replication rules must be unique")
        repositories.add(rule["repository"])
        destinations.add(rule["destination"])
        if rule["source_tag"] != "latest" or rule["access_class"] not in {"public", "restricted"}:
            raise BootstrapError("Chainguard replication must use stable exact tags")
        if type(rule["override"]) is not bool or type(rule["delete"]) is not bool or type(rule["flatten"]) is not bool:
            raise BootstrapError("Chainguard replication flags are malformed")
        if rule["delete"] or rule["flatten"] or not rule["override"]:
            raise BootstrapError("Chainguard replication must preserve content and paths")
    return True


def desired_replication_policy(rule, source_registry_id, paused=None):
    """Build Harbor's native policy payload from one reviewed exact rule."""
    if paused is None:
        paused = CHAINGUARD_REPLICATION["paused"]
    validate_replication_policy({**CHAINGUARD_REPLICATION, "paused": paused, "rules": (rule,)})
    if type(source_registry_id) is not int or source_registry_id <= 0:
        raise BootstrapError("Chainguard source registry ID is required")
    return {
        "name": f"chainguard-{rule['repository'].split('/', 1)[1]}",
        "description": "Repository-managed Chainguard import; exact stable tag",
        "dest_namespace": rule["destination"].split("/", 1)[0],
        "dest_registry": {"id": 0},
        "src_registry": {"id": source_registry_id},
        "trigger": {"type": "scheduled", "trigger_settings": {"cron": "0 * * * *"}},
        "enabled": not paused,
        "replicate_deletion": False,
        "override": True,
        "filters": [{"type": "name", "value": rule["repository"]},
                     {"type": "tag", "value": rule["source_tag"]}],
    }


def read_replication_policy(path=None):
    path = REPLICATION_FILE if path is None else path
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise BootstrapError("Chainguard replication policy is unavailable") from None
    validate_replication_policy(policy)
    return policy


def desired_registry(name):
    if name != CHAINGUARD_REGISTRY["name"]:
        raise BootstrapError("unsupported replication registry")
    return CHAINGUARD_REGISTRY


def registry_matches(actual, desired):
    """Compare Harbor registry fields after its null-to-default normalization."""
    for key, value in desired.items():
        if key == "credential":
            continue
        actual_value = actual.get(key)
        if key == "insecure" and actual_value is None:
            actual_value = False
        if actual_value != value:
            return False
    return True


def reconcile_registry(client, name):
    desired = desired_registry(name)
    query = urllib.parse.urlencode({"name": name})
    registries, _ = client.request("GET", "/registries?" + query)
    if not isinstance(registries, list) or len(registries) > 1:
        raise BootstrapError("Chainguard source registry is ambiguous")
    if not registries:
        registry, _ = client.request("POST", "/registries", desired, expected=(201,))
        if not isinstance(registry, dict):
            raise BootstrapError("Harbor created an invalid source registry")
    else:
        registry = registries[0]
        if not isinstance(registry, dict) or registry.get("name") != name:
            raise BootstrapError("Harbor returned the wrong source registry")
        identifier = positive_id(registry.get("id"))
        if not registry_matches(registry, desired):
            client.request("PUT", f"/registries/{identifier}", desired, json_response=False)
    identifier = positive_id(registry.get("id"))
    verified, _ = client.request("GET", f"/registries/{identifier}")
    if not isinstance(verified, dict) or not registry_matches(verified, desired):
        raise BootstrapError("Harbor source registry verification failed")
    return verified


def replication_matches(actual, desired):
    return all(actual.get(key) == value for key, value in desired.items())


def reconcile_replication(client, policy):
    """Reconcile exact native Harbor rules without deleting other policies."""
    validate_replication_policy(policy)
    source = reconcile_registry(client, policy["source_registry"])
    for rule in policy["rules"]:
        desired = desired_replication_policy(rule, source["id"], policy["paused"])
        query = urllib.parse.urlencode({"name": desired["name"]})
        policies, _ = client.request("GET", "/replication/policies?" + query)
        if not isinstance(policies, list) or len(policies) > 1:
            raise BootstrapError("Chainguard replication policy is missing or ambiguous")
        if not policies:
            created, _ = client.request("POST", "/replication/policies", desired, expected=(201,))
            if not isinstance(created, dict):
                raise BootstrapError("Harbor created an invalid replication policy")
            identifier = positive_id(created.get("id"))
        else:
            current = policies[0]
            identifier = positive_id(current.get("id"))
            if not replication_matches(current, desired):
                client.request("PUT", f"/replication/policies/{identifier}", desired, json_response=False)
        verified, _ = client.request("GET", f"/replication/policies/{identifier}")
        if not isinstance(verified, dict) or not replication_matches(verified, desired):
            raise BootstrapError("Harbor replication policy verification failed")


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


def read_project(client, project_name):
    project, _ = client.request("GET", f"/projects/{project_name}", expected=(200, 404))
    if project is None:
        return None
    if not isinstance(project, dict) or project.get("name") != project_name:
        raise BootstrapError("Harbor returned the wrong project")
    positive_id(project.get("project_id"))
    if project.get("registry_id") not in (None, 0):
        raise BootstrapError("Harbor project must not be a proxy cache")
    metadata = project.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("public") not in ("true", "false"):
        raise BootstrapError("Harbor project lacks a valid privacy setting")
    return project


def robot_name(name, project_name):
    return f"{PREFIX}{project_name}+{name}"


def read_pages(client, path, parameters, max_count=None):
    objects = []
    seen_ids = set()
    expected_total = None
    count = 0
    page = 1
    while True:
        query = urllib.parse.urlencode({**parameters, "page": page, "page_size": 100})
        document, headers = client.request("GET", path + "?" + query)
        try:
            total = int(headers.get("X-Total-Count", ""))
        except (ValueError, TypeError):
            raise BootstrapError("Harbor object list lacks a valid total count") from None
        if total < 0 or (max_count is not None and total > max_count) or (
            expected_total is not None and total != expected_total
        ):
            raise BootstrapError("Harbor object listing changed or exceeded its bounded limit")
        expected_total = total
        # Harbor's Go handler serializes an empty result slice as null.
        if document is None and total == 0:
            document = []
        if not isinstance(document, list) or len(document) > 100:
            raise BootstrapError("Harbor object listing is malformed")
        for item in document:
            if not isinstance(item, dict):
                raise BootstrapError("Harbor object listing contains an invalid object")
            identifier = positive_id(item.get("id"))
            if identifier in seen_ids:
                raise BootstrapError("Harbor object listing is ambiguous")
            seen_ids.add(identifier)
            objects.append(item)
        count += len(document)
        if count == total:
            return objects
        if not document or count > total:
            raise BootstrapError("Harbor object pagination is inconsistent")
        page += 1


def read_robots(client, project_id):
    # Harbor defaults /robots to system robots; project filtering is explicit.
    robots = {}
    for robot in read_pages(client, "/robots", {"q": f"Level=project,ProjectID={project_id}"}, max_count=1000):
        name = robot.get("name")
        if not isinstance(name, str) or name in robots:
            raise BootstrapError("Harbor robot listing is ambiguous")
        robots[name] = robot
    return robots


def unscanned_image(artifact):
    attributes = artifact.get("extra_attrs") or {}
    return (artifact.get("type") == "IMAGE" and artifact.get("media_type") in (
        "application/vnd.oci.image.config.v1+json", "application/vnd.docker.container.image.v1+json"
    ) and isinstance(attributes, dict) and all(
        isinstance(attributes.get(key), str) and attributes[key] not in ("", "unknown")
        for key in ("os", "architecture")
    ) and artifact.get("scan_overview") in (None, {}))


def backfill_scans(client):
    # Only private application image manifests: scanning an index would also
    # rescan its already-scanned children. Signatures/attestations are excluded.
    pending = []
    for repository in read_pages(client, "/projects/homelab/repositories", {"sort": "id"}):
        name = repository.get("name")
        if not isinstance(name, str) or not name.startswith("homelab/") or not name[8:]:
            raise BootstrapError("Harbor returned the wrong image repository")
        encoded = urllib.parse.quote(urllib.parse.quote(name[8:], safe=""), safe="")
        path = f"/projects/homelab/repositories/{encoded}/artifacts"
        artifacts = read_pages(client, path, {"sort": "id", "with_scan_overview": "true",
                                              "with_accessory": "true", "with_tag": "false"})
        accessories = {item["artifact_id"] for artifact in artifacts
                       for item in (artifact.get("accessories") or [])}
        for artifact in artifacts:
            if artifact["id"] in accessories or not unscanned_image(artifact):
                continue
            digest = artifact.get("digest")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise BootstrapError("Harbor returned an invalid image digest")
            pending.append((f"{path}/{digest}", artifact["id"]))
    queued = 0
    for path, identifier in pending:
        # A push or another bootstrap may have started scanning since listing.
        artifact, _ = client.request("GET", path + "?with_scan_overview=true")
        if not isinstance(artifact, dict) or artifact.get("id") != identifier or (
            artifact.get("digest") != path.rsplit("/", 1)[1]
        ):
            raise BootstrapError("Harbor returned the wrong image artifact")
        if unscanned_image(artifact):
            client.request("POST", path + "/scan", {"scan_type": "vulnerability"},
                           expected=(202,), json_response=False)
            queued += 1
    print(f"Harbor queued {queued} missing homelab image vulnerability scans.")


def permissions(name, project_name):
    return [{"kind": "project", "namespace": project_name,
             "access": [{"resource": "repository", "action": action, "effect": "allow"}
                        for action in ROBOTS[name]]}]


def validate_robot(robot, name, project_name, identifier=None):
    if not isinstance(robot, dict) or robot.get("name") != robot_name(name, project_name):
        raise BootstrapError("Harbor returned the wrong robot name")
    actual_id = positive_id(robot.get("id"))
    if identifier is not None and actual_id != identifier:
        raise BootstrapError("Harbor returned the wrong robot ID")
    if robot.get("level") != "project" or robot.get("editable") is not True:
        raise BootstrapError("Harbor robot is not an editable project robot")
    scopes = robot.get("permissions")
    if not isinstance(scopes, list) or len(scopes) != 1 or not isinstance(scopes[0], dict):
        raise BootstrapError("Harbor robot has an ambiguous permission scope")
    if scopes[0].get("kind") != "project" or scopes[0].get("namespace") != project_name:
        raise BootstrapError("Harbor robot belongs to a different permission scope")
    access = scopes[0].get("access")
    if not isinstance(access, list) or any(not isinstance(item, dict) for item in access):
        raise BootstrapError("Harbor robot permissions are malformed")
    return actual_id


def desired_robot(name, project_name):
    return {"name": robot_name(name, project_name), "level": "project", "duration": -1,
            "description": f"Repository-managed {project_name} {name} robot", "disable": False,
            "permissions": permissions(name, project_name)}


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


def reconcile(client, robot_passwords, replication_policy=None):
    # Finish the relevant read-only identity and schema checks before writing.
    config, _ = client.request("GET", "/configurations")
    current = config_values(config)
    projects = {}
    project_robots = {}
    for project_name, settings in PROJECTS.items():
        project = read_project(client, project_name)
        projects[project_name] = project
        robots = read_robots(client, project["project_id"]) if project else {}
        project_robots[project_name] = robots
        for name in settings["robots"]:
            robot = robots.get(robot_name(name, project_name))
            if robot:
                validate_robot(robot, name, project_name)

    changes = {key: value for key, value in SETTINGS.items() if current[key] != value}
    if changes:
        client.request("PUT", "/configurations", changes, json_response=False)
    for project_name, settings in PROJECTS.items():
        project = projects[project_name]
        metadata = settings["metadata"]
        if project is None:
            client.request("POST", "/projects", {"project_name": project_name, "metadata": metadata},
                           expected=(201,), json_response=False)
        elif any(project["metadata"].get(key) != value for key, value in metadata.items()):
            client.request("PUT", f"/projects/{project_name}", {"metadata": metadata},
                           json_response=False)
        project = read_project(client, project_name)
        if project is None or any(project["metadata"].get(key) != value for key, value in metadata.items()):
            raise BootstrapError("Harbor project privacy or automatic scanning verification failed")

        robots = project_robots[project_name]
        for name in settings["robots"]:
            desired = desired_robot(name, project_name)
            robot = robots.get(robot_name(name, project_name))
            if robot is None:
                created, _ = client.request("POST", "/robots", {**desired, "name": name}, expected=(201,))
                if not isinstance(created, dict) or created.get("name") != robot_name(name, project_name):
                    raise BootstrapError("Harbor created an unexpected robot")
                identifier = positive_id(created.get("id"))
            else:
                identifier = validate_robot(robot, name, project_name)
            path = f"/robots/{identifier}"
            # Re-read by immutable ID before mutating credentials or permissions.
            robot, _ = client.request("GET", path)
            validate_robot(robot, name, project_name, identifier)
            if not robot_matches(robot, desired):
                client.request("PUT", path, desired, json_response=False)
            client.request("PATCH", path, {"secret": robot_passwords[(project_name, name)]})
            verified, _ = client.request("GET", path)
            validate_robot(verified, name, project_name, identifier)
            if not robot_matches(verified, desired):
                raise BootstrapError("Harbor robot desired-state verification failed")

    config, _ = client.request("GET", "/configurations")
    current = config_values(config)
    if any(current[key] != value for key, value in SETTINGS.items()):
        raise BootstrapError("Harbor configuration verification failed")
    if replication_policy is not None:
        reconcile_replication(client, replication_policy)
    backfill_scans(client)
    print("Harbor homelab is private, mirror is public; project-scoped robots reconciled.")


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
        read_replication_policy()
        admin_password = read_secret("admin-password")
        passwords = {name: read_secret(filename) for name, filename in SECRET_FILES.items()}
        if passwords[("homelab", "publisher")] == passwords[("mirror", "publisher")]:
            raise BootstrapError("Harbor publishers require separate credentials")
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
        reconcile(client, passwords, read_replication_policy())
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
