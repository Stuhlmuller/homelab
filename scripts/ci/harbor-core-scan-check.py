"""Validate a private complete scan of the exact derived runtime; print no findings."""

from datetime import datetime, timedelta, timezone
from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
import re
import sys


def verify(report, image_id, require_zero_matches=False):
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image_id), "identity"
    assert report["source"]["type"] == "image", "identity"
    target = report["source"]["target"]
    assert target["imageID"] == image_id and target["layers"] and target["imageSize"] > 0, "identity"
    raw_config = base64.b64decode(target["config"], validate=True)
    assert "sha256:" + hashlib.sha256(raw_config).hexdigest() == image_id, "identity"
    config_identity = json.loads(raw_config)
    assert config_identity["os"] == "linux" and config_identity["architecture"] == "amd64", "identity"
    # Docker archives omit these summary fields; the hashed config remains authoritative.
    assert target["os"] in ("", config_identity["os"]), "identity"
    assert target["architecture"] in ("", config_identity["architecture"]), "identity"
    assert report["distro"]["name"] == "photon" and report["distro"]["version"] == "5.0", "identity"
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
    try:
        require_zero_matches = len(args) == 3 and args[-1] == "--require-zero-matches"
        if require_zero_matches:
            args = args[:-1]
        assert len(args) == 2, "schema"
        raw_report = Path(args[0]).read_bytes()
        report = json.loads(raw_report)
        verify(report, args[1], require_zero_matches=require_zero_matches)
    except AssertionError as error:
        category = str(error)
        if category not in {"identity", "scanner", "database", "freshness", "filtering", "schema", "remediation", "clearance"}:
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
    print("Private report validation failed: " + category + "; findings withheld.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
