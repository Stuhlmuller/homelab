"""Validate a private complete scan of the exact derived runtime; print no findings."""

from datetime import datetime, timedelta, timezone
from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile


INDEX_TYPES = {"application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json"}


def verify_archive_config(archive_path, inspect_id):
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", inspect_id), "identity-archive-inspect-id"

    def read_member(archive, name, size_limit, category):
        try:
            member = archive.getmember(name)
            assert member.isfile() and 0 < member.size < size_limit, category
            source = archive.extractfile(member)
            assert source is not None, category
            return source.read()
        except (KeyError, OSError, tarfile.TarError) as error:
            raise AssertionError(category) from error

    def read_json(archive, name, size_limit, category):
        try:
            return json.loads(read_member(archive, name, size_limit, category))
        except (TypeError, ValueError) as error:
            raise AssertionError(category) from error

    def read_blob(archive, descriptor):
        category = "identity-archive-descriptor"
        assert isinstance(descriptor, dict), category
        digest = descriptor.get("digest")
        assert isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest), category
        raw = read_member(archive, "blobs/sha256/" + digest[7:], 16 * 1024 * 1024, category)
        assert hashlib.sha256(raw).hexdigest() == digest[7:], category
        assert descriptor.get("size") == len(raw), category
        return raw

    try:
        archive = tarfile.open(archive_path, mode="r:")
    except (OSError, tarfile.TarError) as error:
        raise AssertionError("identity-archive-structure") from error
    with archive:
        manifest = read_json(archive, "manifest.json", 1024 * 1024, "identity-archive-structure")
        assert isinstance(manifest, list) and len(manifest) == 1, "identity-archive-structure"
        try:
            config_name = manifest[0]["Config"]
        except (KeyError, TypeError) as error:
            raise AssertionError("identity-archive-structure") from error
        assert isinstance(config_name, str) and re.fullmatch(
            r"(?:[0-9a-f]{64}\.json|blobs/sha256/[0-9a-f]{64})", config_name
        ), "identity-archive-structure"
        raw_config = read_member(archive, config_name, 16 * 1024 * 1024, "identity-archive-structure")
        config_digest = config_name[:-5] if config_name.endswith(".json") else config_name[len("blobs/sha256/"):]
        assert hashlib.sha256(raw_config).hexdigest() == config_digest, "identity-archive-config-hash"
        config_id = "sha256:" + config_digest
        if config_id == inspect_id:
            # The classic image store uses the config digest as the inspected ID.
            return config_id

        # The containerd image store uses the OCI index or manifest descriptor
        # digest as the inspected ID. Docker save by ID keeps that descriptor
        # in index.json; manifest.json points to the selected host platform.
        index = read_json(archive, "index.json", 1024 * 1024, "identity-archive-inspect-id")
        assert isinstance(index, dict) and isinstance(index.get("manifests"), list), "identity-archive-inspect-id"
        assert len(index["manifests"]) == 1, "identity-archive-inspect-id"
        root = index["manifests"][0]
        assert isinstance(root, dict) and root.get("digest") == inspect_id, "identity-archive-inspect-id"
        root_type = root.get("mediaType")
        assert root_type in INDEX_TYPES | MANIFEST_TYPES, "identity-archive-descriptor"
        try:
            root_data = json.loads(read_blob(archive, root))
        except (TypeError, ValueError) as error:
            raise AssertionError("identity-archive-descriptor") from error
        assert isinstance(root_data, dict), "identity-archive-descriptor"
        if root_type in INDEX_TYPES:
            children = root_data.get("manifests")
            assert isinstance(children, list), "identity-archive-descriptor"
            selected = [item for item in children if isinstance(item, dict) and
                        isinstance(item.get("platform"), dict) and
                        item["platform"].get("os") == "linux" and
                        item["platform"].get("architecture") == "amd64"]
            assert len(selected) == 1, "identity-archive-descriptor"
            child = selected[0]
            assert child.get("mediaType") in MANIFEST_TYPES, "identity-archive-descriptor"
            try:
                selected_manifest = json.loads(read_blob(archive, child))
            except (TypeError, ValueError) as error:
                raise AssertionError("identity-archive-descriptor") from error
        else:
            selected_manifest = root_data
        assert isinstance(selected_manifest, dict), "identity-archive-descriptor"
        descriptor = selected_manifest.get("config")
        assert isinstance(descriptor, dict) and descriptor.get("digest") == config_id, "identity-archive-descriptor"
        assert descriptor.get("size") == len(raw_config), "identity-archive-descriptor"
        return config_id


def verify(report, image_id, require_zero_matches=False):
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image_id), "identity"
    assert report["source"]["type"] == "image", "identity-source"
    target = report["source"]["target"]
    assert target["layers"] and target["imageSize"] > 0, "identity-archive"
    raw_config = base64.b64decode(target["config"], validate=True)
    assert "sha256:" + hashlib.sha256(raw_config).hexdigest() == image_id, "identity-report-config"
    assert target["imageID"] == image_id, "identity-image-id"
    config_identity = json.loads(raw_config)
    assert config_identity["os"] == "linux" and config_identity["architecture"] == "amd64", "identity-platform"
    # Docker archives omit these summary fields; the hashed config remains authoritative.
    assert target["os"] in ("", config_identity["os"]), "identity-platform"
    assert target["architecture"] in ("", config_identity["architecture"]), "identity-platform"
    assert report["distro"]["name"] == "photon" and report["distro"]["version"] == "5.0", "identity-distro"
    descriptor = report["descriptor"]
    assert descriptor["name"] == "grype" and descriptor["version"] == "0.112.0", "scanner"
    assert descriptor["db"]["status"]["valid"] is True, "database"
    now = datetime.now(timezone.utc)
    for value, age in ((descriptor["timestamp"], timedelta(hours=1)),
                       (descriptor["db"]["status"]["built"], timedelta(hours=48))):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert now - age <= timestamp <= now + timedelta(minutes=5), "freshness"
    config = descriptor["configuration"]
    assert config["only-fixed"] is False and config["only-notfixed"] is False, "filtering"
    assert not config["ignore-wontfix"] and not config["ignore"] and not config["exclude"] and not config["vex-documents"], "filtering"
    assert config["search"]["scope"] == "squashed" and not report.get("ignoredMatches"), "filtering"
    assert isinstance(report["matches"], list), "schema"
    for match in report["matches"]:
        assert match["vulnerability"]["severity"] in {"Negligible", "Low", "Medium", "High", "Critical", "Unknown"}, "schema"
        fix = match["vulnerability"]["fix"]
        state = fix["state"]
        if state == "":
            # Grype serializes unset provider fix state as an empty string.
            assert isinstance(fix["versions"], list), "schema"
            assert not fix["versions"] and not fix.get("available"), "remediation"
            state = "unknown"
        assert state in {"fixed", "not-fixed", "unknown", "wont-fix"}, "schema"
        assert state != "fixed", "remediation"
        assert not fix.get("versions") and not fix.get("available"), "remediation"
    if require_zero_matches:
        assert not report["matches"], "clearance"


def main(args):
    diagnostic_file = None
    if len(args) >= 2 and args[0] == "--diagnostic-file":
        diagnostic_file = Path(args[1])
        args = args[2:]
    archive_path = None
    if len(args) >= 2 and args[0] == "--archive":
        archive_path = Path(args[1])
        args = args[2:]
    try:
        require_zero_matches = len(args) == 3 and args[-1] == "--require-zero-matches"
        if require_zero_matches:
            args = args[:-1]
        assert len(args) == 2, "schema"
        raw_report = Path(args[0]).read_bytes()
        report = json.loads(raw_report)
        config_id = verify_archive_config(archive_path, args[1]) if archive_path is not None else args[1]
        verify(report, config_id, require_zero_matches=require_zero_matches)
    except AssertionError as error:
        category = str(error)
        if category not in {"identity-source", "identity-image-id", "identity-archive", "identity-archive-structure",
                            "identity-archive-config-hash", "identity-archive-inspect-id",
                            "identity-archive-descriptor", "identity-report-config",
                            "identity-platform", "identity-distro", "scanner", "database", "freshness",
                            "filtering", "schema", "remediation", "clearance"}:
            category = "schema"
    except (KeyError, TypeError, ValueError, OSError):
        category = "schema"
    else:
        if require_zero_matches:
            print("Complete private runtime audit passed; zero matches required for publication.")
        else:
            print("Complete private runtime audit passed; " + str(len(report["matches"])) + " unresolved matches retained; this is not CVE clearance.")
        print("Runtime audit receipt: " + json.dumps({
            "image_id": args[1], "report_sha256": hashlib.sha256(raw_report).hexdigest(),
            "scanner": report["descriptor"]["version"], "db_built": report["descriptor"]["db"]["status"]["built"],
            "matches": len(report["matches"]), "severity_counts": dict(Counter(m["vulnerability"]["severity"] for m in report["matches"])),
            "cve_clearance": False}, sort_keys=True))
        return 0
    if diagnostic_file is not None:
        diagnostic_file.write_text("validation:" + category + "\n")
    print("Private report validation failed: " + category + "; findings withheld.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
