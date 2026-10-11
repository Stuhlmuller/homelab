"""Validate a private complete scan of the exact derived runtime; print no findings."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys


def verify(report, image_id):
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
    assert report["source"]["type"] == "image"
    target = report["source"]["target"]
    assert target["imageID"] == image_id and target["os"] == "linux"
    assert target["architecture"] == "amd64" and target["layers"] and target["imageSize"] > 0
    assert report["distro"]["name"] == "wolfi"
    descriptor = report["descriptor"]
    assert descriptor["name"] == "grype" and descriptor["version"] == "0.112.0"
    assert descriptor["db"]["status"]["valid"] is True
    now = datetime.now(timezone.utc)
    for value, age in ((descriptor["timestamp"], timedelta(hours=1)),
                       (descriptor["db"]["status"]["built"], timedelta(hours=48))):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert now - age <= timestamp <= now + timedelta(minutes=5)
    config = descriptor["configuration"]
    assert config["only-fixed"] is False and config["only-notfixed"] is False
    assert not config["ignore-wontfix"] and not config["ignore"] and not config["exclude"] and not config["vex-documents"]
    assert config["search"]["scope"] == "squashed" and not report.get("ignoredMatches")
    assert isinstance(report["matches"], list)
    for match in report["matches"]:
        state = match["vulnerability"]["fix"]["state"]
        assert state in {"fixed", "not-fixed", "unknown", "wont-fix"}
        assert state != "fixed", "Private runtime remediation remains required"


if __name__ == "__main__":
    assert len(sys.argv) == 3
    verify(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2])
