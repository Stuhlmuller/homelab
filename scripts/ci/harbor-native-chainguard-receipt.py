#!/usr/bin/env python3
"""Validate fixed native Chainguard imports without writing registry state."""

import argparse
import base64
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "clusters/homelab/apps/harbor/image-automation.json"
DEFAULT_REPLICATION = ROOT / "clusters/homelab/apps/harbor/chainguard-replication.json"
DEFAULT_CATALOG = ROOT / "scripts/config/harbor-chainguard-images.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
MAX_SCAN_RESPONSE_BYTES = 4 * 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^chainguard-[a-z0-9][a-z0-9-]{0,62}$")
PLATFORM = re.compile(r"^linux/(amd64|arm64)$")
SOURCE = re.compile(r"^cgr\.dev/(chainguard/[a-z0-9][a-z0-9.-]*):latest$")
CATALOG_SOURCE = re.compile(r"^cgr\.dev/chainguard/[a-z0-9][a-z0-9.-]*:[A-Za-z0-9][A-Za-z0-9.-]*$")
DESTINATION = re.compile(r"^harbor\.stinkyboi\.com/homelab/(chainguard-[a-z0-9][a-z0-9-]*):latest$")
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
SCAN_IMAGE_MEDIA_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
HARBOR_SCAN_ENDPOINT = "https://harbor.stinkyboi.com/api/v2.0"
SCAN_REPORT_TYPE = "application/vnd.security.vulnerability.report; version=1.1"


class ReceiptError(ValueError):
    """A fixed verification invariant did not hold."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HarborScanClient:
    """Read exact child scan summaries using the artifact-read robot only."""

    def __init__(self, password, endpoint=HARBOR_SCAN_ENDPOINT):
        if not isinstance(password, str) or not password or any(character.isspace() for character in password):
            raise ReceiptError("Harbor scan credential is invalid")
        encoded = base64.b64encode(f"robot$homelab+scan:{password}".encode()).decode()
        self.endpoint = endpoint
        self.headers = {"Authorization": f"Basic {encoded}", "Accept": "application/json"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def artifact(self, repository, digest):
        encoded = urllib.parse.quote(urllib.parse.quote(repository, safe=""), safe="")
        request = urllib.request.Request(
            f"{self.endpoint}/projects/homelab/repositories/{encoded}/artifacts/{digest}?with_scan_overview=true",
            headers=self.headers,
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise ReceiptError("Harbor scan receipt request was rejected")
                body = response.read(MAX_SCAN_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            raise ReceiptError("Harbor scan receipt request was rejected") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReceiptError("Harbor scan receipt connection failed") from None
        if len(body) > MAX_SCAN_RESPONSE_BYTES:
            raise ReceiptError("Harbor scan receipt response exceeded its limit")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ReceiptError("Harbor scan receipt response is malformed") from None


def read_json(path, limit=MAX_JSON_BYTES):
    raw = Path(path).read_bytes()
    if len(raw) > limit:
        raise ReceiptError("verification input exceeds the fixed size limit")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptError("verification input is not valid JSON") from error
    return value


def canonical_digest(value):
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def bytes_digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ReceiptError(message)


def config_images(config):
    require(isinstance(config, dict), "automation configuration is not an object")
    images = config.get("images")
    require(config.get("schema_version") == 1 and isinstance(images, list) and images,
            "automation configuration is incomplete")
    result = {}
    fields = {"image_id", "source", "destination", "access_class", "required_platforms", "release_recipe"}
    for image in images:
        require(isinstance(image, dict) and set(image) == fields,
                "automation image fields are not fixed")
        image_id = image["image_id"]
        source = image["source"]
        destination = image["destination"]
        require(isinstance(image_id, str) and IMAGE_ID.fullmatch(image_id) and image_id not in result,
                "automation image identifier is invalid")
        source_match = SOURCE.fullmatch(source) if isinstance(source, str) else None
        destination_match = DESTINATION.fullmatch(destination) if isinstance(destination, str) else None
        require(source_match is not None and destination_match is not None,
                "native source or destination is not fixed")
        repository = source_match.group(1)
        image_name = repository.rsplit("/", 1)[1]
        require(image_id == f"chainguard-{image_name}" and destination_match.group(1) == image_id,
                "native source and destination do not agree")
        platforms = image["required_platforms"]
        require(isinstance(platforms, list) and platforms and len(platforms) == len(set(platforms))
                and all(isinstance(platform, str) and PLATFORM.fullmatch(platform) for platform in platforms),
                "required platforms are invalid")
        require(image["access_class"] == "public", "native source access class is not public")
        result[image_id] = {
            "image_id": image_id,
            "source_ref": source,
            "destination_ref": destination,
            "source_repository": f"cgr.dev/{repository}",
            "destination_repository": destination.rsplit(":", 1)[0],
            "repository": repository,
            "required_platforms": sorted(platforms),
        }
    return result


def catalog_digests(catalog):
    require(isinstance(catalog, dict) and set(catalog) == {"images"}
            and isinstance(catalog["images"], list), "Chainguard catalog is malformed")
    result = {}
    for item in catalog["images"]:
        require(isinstance(item, dict) and set(item) == {"source"} and isinstance(item["source"], str),
                "Chainguard catalog entry is malformed")
        try:
            source, digest = item["source"].rsplit("@", 1)
        except ValueError as error:
            raise ReceiptError("Chainguard catalog entry lacks a digest") from error
        require(CATALOG_SOURCE.fullmatch(source) is not None and SHA256.fullmatch(digest) is not None
                and source not in result, "Chainguard catalog source is invalid")
        result[source] = digest
    return result


def replication_rules(replication):
    fields = {"schema_version", "paused", "schedule", "source_registry", "rules"}
    require(isinstance(replication, dict) and set(replication) == fields
            and replication.get("schema_version") == 1 and replication.get("paused") is False
            and replication.get("schedule") == "0 0 * * * *" and replication.get("source_registry") == "cgr.dev"
            and isinstance(replication.get("rules"), list), "Chainguard replication configuration is malformed")
    result = {}
    rule_fields = {"repository", "source_tag", "destination", "override", "delete", "flatten", "access_class"}
    for rule in replication["rules"]:
        require(isinstance(rule, dict) and set(rule) == rule_fields,
                "Chainguard replication rule fields are not fixed")
        repository = rule["repository"]
        destination = rule["destination"]
        require(isinstance(repository, str) and isinstance(destination, str)
                and SOURCE.fullmatch(f"cgr.dev/{repository}:latest") is not None
                and re.fullmatch(r"homelab/chainguard-[a-z0-9][a-z0-9-]*", destination) is not None
                and rule["source_tag"] == "latest" and rule["override"] is True
                and rule["delete"] is False and rule["flatten"] is False
                and rule["access_class"] == "public" and repository not in result,
                "Chainguard replication rule is invalid")
        result[repository] = {
            "repository": repository,
            "source_tag": rule["source_tag"],
            "destination": destination,
            "override": rule["override"],
            "delete": rule["delete"],
            "flatten": rule["flatten"],
            "access_class": rule["access_class"],
        }
    return result


def build_plan(config, replication, catalog):
    images = config_images(config)
    catalogs = catalog_digests(catalog)
    rules = replication_rules(replication)
    plan = []
    for image_id, image in sorted(images.items()):
        require(image["source_ref"] in catalogs, "native source is not in the reviewed Chainguard catalog")
        expected_destination = "homelab/" + image_id
        rule = rules.get(image["repository"])
        require(rule is not None and rule["destination"] == expected_destination,
                "native replication rule does not match automation configuration")
        source_digest = catalogs[image["source_ref"]]
        contract = {
            "image_id": image["image_id"],
            "source_ref": image["source_ref"],
            "destination_ref": image["destination_ref"],
            "required_platforms": image["required_platforms"],
            "source_digest": source_digest,
            "replication_rule": rule,
        }
        plan.append({**image, "source_digest": source_digest,
                     "config_digest": canonical_digest(contract)})
    require(len(plan) == len(rules), "native replication has an unmanaged rule")
    return plan


def selected_plan(config, replication, catalog, image_id):
    require(isinstance(image_id, str) and IMAGE_ID.fullmatch(image_id) is not None,
            "native image identifier is invalid")
    for item in build_plan(config, replication, catalog):
        if item["image_id"] == image_id:
            return item
    raise ReceiptError("native image is not configured")


def index_platforms(raw, required_platforms):
    require(len(raw) <= MAX_INDEX_BYTES, "image index exceeds the fixed size limit")
    try:
        index = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptError("image index is not valid JSON") from error
    require(isinstance(index, dict) and index.get("schemaVersion") == 2
            and index.get("mediaType") in INDEX_MEDIA_TYPES and isinstance(index.get("manifests"), list),
            "image index is malformed")
    result = {}
    wanted = set(required_platforms)
    for descriptor in index["manifests"]:
        if not isinstance(descriptor, dict):
            raise ReceiptError("image index descriptor is malformed")
        platform = descriptor.get("platform")
        if not isinstance(platform, dict):
            continue
        key = f"{platform.get('os')}/{platform.get('architecture')}"
        if key not in wanted:
            continue
        digest = descriptor.get("digest")
        require(descriptor.get("mediaType") in MANIFEST_MEDIA_TYPES and isinstance(digest, str)
                and SHA256.fullmatch(digest) is not None and key not in result,
                "image index required platform is ambiguous")
        result[key] = digest
    require(set(result) == wanted, "image index lacks a required platform")
    return dict(sorted(result.items()))


def scan_complete(artifact, digest, platform):
    os_name, architecture = platform.split("/", 1)
    require(isinstance(artifact, dict) and artifact.get("type") == "IMAGE"
            and artifact.get("digest") == digest and artifact.get("media_type") in SCAN_IMAGE_MEDIA_TYPES,
            "Harbor returned the wrong image artifact")
    attributes = artifact.get("extra_attrs")
    require(isinstance(attributes, dict) and attributes.get("os") == os_name
            and attributes.get("architecture") == architecture,
            "Harbor returned an artifact for the wrong platform")
    overview = artifact.get("scan_overview")
    require(isinstance(overview, dict) and set(overview) == {SCAN_REPORT_TYPE},
            "Harbor scan overview is missing or ambiguous")
    report = overview[SCAN_REPORT_TYPE]
    require(isinstance(report, dict) and report.get("scan_status") == "Success",
            "Harbor scan is not complete")
    summary = report.get("summary")
    counts = summary.get("summary") if isinstance(summary, dict) else None
    require(isinstance(counts, dict) and all(type(count) is int and count == 0 for count in counts.values()),
            "Harbor scan still reports CVEs")


def scan_receipt(plan, destination_digest, platforms, password, client_type=HarborScanClient):
    require(SHA256.fullmatch(destination_digest) is not None
            and destination_digest == plan["source_digest"],
            "destination index digest does not match the reviewed native contract")
    require(set(platforms) == set(plan["required_platforms"])
            and all(SHA256.fullmatch(digest) is not None for digest in platforms.values()),
            "required platform digests are invalid")
    repository = plan["destination_repository"].removeprefix("harbor.stinkyboi.com/homelab/")
    client = client_type(password)
    for platform, digest in sorted(platforms.items()):
        scan_complete(client.artifact(repository, digest), digest, platform)
    return {
        "schema_version": 1,
        "kind": "native-chainguard-scan-v1",
        "image_id": plan["image_id"],
        "config_digest": plan["config_digest"],
        "destination_digest": destination_digest,
        "platforms": dict(sorted(platforms.items())),
        "scan_status": {platform: "Success" for platform in sorted(platforms)},
    }


def validate_scan_receipt(value, plan, platforms):
    required = {"schema_version", "kind", "image_id", "config_digest", "destination_digest", "platforms", "scan_status"}
    require(isinstance(value, dict) and set(value) == required
            and value.get("schema_version") == 1 and value.get("kind") == "native-chainguard-scan-v1"
            and value.get("image_id") == plan["image_id"]
            and value.get("config_digest") == plan["config_digest"]
            and value.get("destination_digest") == plan["source_digest"]
            and value.get("platforms") == platforms
            and isinstance(value.get("scan_status"), dict)
            and set(value["scan_status"]) == set(platforms)
            and all(status == "Success" for status in value["scan_status"].values()),
            "native scan receipt is invalid")


def receipt_for(plan, repository_sha, source_index, destination_index, pulled_index, scan_receipt):
    require(isinstance(repository_sha, str) and SHA.fullmatch(repository_sha) is not None,
            "repository revision is invalid")
    source_digest = bytes_digest(source_index)
    require(source_digest == plan["source_digest"], "source index differs from the reviewed catalog digest")
    require(destination_index == source_index and pulled_index == source_index,
            "native Harbor index bytes differ from the source")
    platforms = index_platforms(source_index, plan["required_platforms"])
    require(index_platforms(destination_index, plan["required_platforms"]) == platforms
            and index_platforms(pulled_index, plan["required_platforms"]) == platforms,
            "native Harbor platform descriptors differ from the source")
    validate_scan_receipt(scan_receipt, plan, platforms)
    return {
        "schema_version": 1,
        "kind": "native-chainguard-v1",
        "repository_sha": repository_sha,
        "config_digest": plan["config_digest"],
        "image_id": plan["image_id"],
        "source_ref": plan["source_ref"],
        "source_digest": source_digest,
        "destination_ref": plan["destination_ref"],
        "destination_digest": source_digest,
        "platforms": platforms,
        "scan_status": dict(sorted(scan_receipt["scan_status"].items())),
        "consumer_access": True,
    }


def verify_native_receipt(plan, receipt):
    fields = {"schema_version", "kind", "repository_sha", "config_digest", "image_id", "source_ref",
              "source_digest", "destination_ref", "destination_digest", "platforms", "scan_status",
              "consumer_access"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        return False, "native receipt fields are incomplete or unknown"
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "native-chainguard-v1":
        return False, "native receipt schema is invalid"
    if not isinstance(receipt.get("repository_sha"), str) or SHA.fullmatch(receipt["repository_sha"]) is None:
        return False, "native receipt repository revision is invalid"
    expected = {key: plan[key] for key in ("config_digest", "image_id", "source_ref", "source_digest", "destination_ref")}
    if any(receipt.get(key) != value for key, value in expected.items()):
        return False, "native receipt does not match the configured image"
    if receipt.get("destination_digest") != plan["source_digest"]:
        return False, "native receipt destination digest does not match the source"
    platforms = receipt.get("platforms")
    if (not isinstance(platforms, dict) or set(platforms) != set(plan["required_platforms"])
            or any(not isinstance(digest, str) or SHA256.fullmatch(digest) is None
                   for digest in platforms.values())):
        return False, "native receipt platforms are invalid"
    scan_status = receipt.get("scan_status")
    if (not isinstance(scan_status, dict) or set(scan_status) != set(platforms)
            or any(status != "Success" for status in scan_status.values())):
        return False, "native receipt scans are incomplete"
    if receipt.get("consumer_access") is not True:
        return False, "native receipt does not prove an authenticated pull"
    return True, "native receipt matches the configured image"


def write_json(path, value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    Path(path).write_text(encoded, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "platforms", "scan", "verify", "check-receipt"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--replication", type=Path, default=DEFAULT_REPLICATION)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--image-id")
    parser.add_argument("--repository-sha")
    parser.add_argument("--source-index", type=Path)
    parser.add_argument("--destination-index", type=Path)
    parser.add_argument("--pulled-index", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--config-digest")
    parser.add_argument("--destination-digest")
    parser.add_argument("--scan-password-file", type=Path)
    parser.add_argument("--scan-receipt", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = read_json(args.config)
    replication = read_json(args.replication)
    catalog = read_json(args.catalog)
    if args.command == "plan":
        result = {"schema_version": 1, "images": build_plan(config, replication, catalog)}
    else:
        if not args.image_id:
            raise ReceiptError(f"{args.command} requires --image-id")
        plan = selected_plan(config, replication, catalog, args.image_id)
        if args.command == "platforms":
            if args.index is None:
                raise ReceiptError("platforms requires --index")
            raw = args.index.read_bytes()
            require(bytes_digest(raw) == plan["source_digest"],
                    "source index differs from the reviewed catalog digest")
            result = {"platforms": index_platforms(raw, plan["required_platforms"])}
        elif args.command == "check-receipt":
            if args.receipt is None:
                raise ReceiptError("check-receipt requires --receipt")
            valid, reason = verify_native_receipt(plan, read_json(args.receipt))
            result = {"verified": valid, "reason": reason}
            if not valid:
                raise ReceiptError(reason)
        elif args.command == "scan":
            if (not args.config_digest or not args.destination_digest or args.scan_password_file is None
                    or args.index is None):
                raise ReceiptError("scan requires configuration, digest, index, and a password file")
            require(args.config_digest == plan["config_digest"] and args.destination_digest == plan["source_digest"],
                    "scan does not match the reviewed native plan")
            raw_index = args.index.read_bytes()
            require(bytes_digest(raw_index) == plan["source_digest"],
                    "scan index differs from the reviewed catalog digest")
            platforms = index_platforms(raw_index, plan["required_platforms"])
            try:
                password = args.scan_password_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                raise ReceiptError("scan credential is unavailable") from None
            result = scan_receipt(plan, args.destination_digest, platforms, password)
        else:
            paths = (args.source_index, args.destination_index, args.pulled_index, args.scan_receipt)
            if not args.repository_sha or any(path is None for path in paths):
                raise ReceiptError("verify requires repository, index, and scan receipt inputs")
            result = receipt_for(plan, args.repository_sha, args.source_index.read_bytes(),
                                 args.destination_index.read_bytes(), args.pulled_index.read_bytes(),
                                 read_json(args.scan_receipt))
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (ReceiptError, OSError) as error:
        sys.exit(str(error))
