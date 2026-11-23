#!/usr/bin/env python3
"""Test the actual catalog with Octelium's pinned parser and policy evaluator."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.35.0"
REVISION = "5e4eb3e36911ba4f66f5f43df2cc4b264211c4ce"  # v0.35.0 release commit
ARCHIVE_SHA256 = "8e468ceb9d2867759a73440545bb20a756618821d4ce077d68f6924798a9216f"


def main():
    # This is the server bootstrap/upgrade version passed to octops, not the
    # client/connector version. A server upgrade requires a new native fixture.
    bootstrap = (ROOT / "scripts/octelium-cluster-bootstrap.sh").read_text()
    assert re.findall(r'^version="([^"]+)"$', bootstrap, re.MULTILINE) == [VERSION], \
        "Octelium server version changed: update the pinned native policy fixture"
    assert 'action+=(--version "$version")' in bootstrap, "Review Octelium server version forwarding"
    documents = json.loads(subprocess.check_output([
        "yq", "ea", "-o=json", "-I=0", "[.]",
        str(ROOT / "docs/examples/octelium/homelab-services.yaml"),
    ], text=True))
    policies = [item for item in documents if item and item.get("kind") == "Policy"
                and item.get("metadata", {}).get("name") == "homelab-private-kubernetes-access"]
    assert len(policies) == 1, "Expected exactly one private Kubernetes policy"
    policy = policies[0]
    assert not policy["spec"].get("isDisabled"), "Private Kubernetes policy is disabled"
    assert not policy["spec"].get("enforcementRules"), "Review new policy enforcement rules"
    with tempfile.TemporaryDirectory(prefix="octelium-policy-") as directory:
        scratch = Path(directory)
        archive = scratch / "upstream.tar.gz"
        subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "120",
            f"https://codeload.github.com/octelium/octelium/tar.gz/{REVISION}",
            "--output", str(archive),
        ], check=True)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA256, "Upstream archive changed"
        with tarfile.open(archive) as source:
            source.extractall(scratch, filter="data")
        upstream = scratch / f"octelium-{REVISION}"
        package = upstream / "cluster/octovigil"
        shutil.copyfile(ROOT / "scripts/ci/fixtures/octelium_cordium_policy_test.go",
                        package / "octovigil/homelab_cordium_policy_test.go")
        executable = scratch / "policy.test"
        subprocess.run(["go", "test", "-p=2", "-c", "-o", str(executable), "./octovigil"],
                       cwd=package, check=True, timeout=600)
        candidate = scratch / "policy.json"
        # Test input/cache environment is process plumbing, never desired state or
        # credentials. All policy inputs come from the repository catalog above.
        env = {**os.environ, "HOMELAB_POLICY_FIXTURE": str(candidate)}
        candidate.write_text(json.dumps(policy))
        command = [str(executable), "-test.run=^TestHomelabCordiumBoundary$", "-test.timeout=60s"]
        subprocess.run(command, env=env, check=True, timeout=90)
        # Prove the corpus catches the original broad read boundary, not just
        # syntax errors. Preserve the real identity gates and remove only the
        # resource/API/namespace restriction from the resource ALLOW rule.
        broad = copy.deepcopy(policy)
        rule = next(rule for rule in broad["spec"]["rules"] if rule["name"] == "cordium-read-only-resources")
        rule["condition"]["all"]["of"] = rule["condition"]["all"]["of"][:7]
        candidate.write_text(json.dumps(broad))
        rejected = subprocess.run(command, env=env, capture_output=True, text=True, timeout=90)
        assert rejected.returncode == 1 and "allow=true, want false" in rejected.stdout, \
            "Native fixture failed to reject the original broad read regression"
    print("Octelium: pinned native parser/CEL boundary and broad-read regression passed")


if __name__ == "__main__":
    main()
