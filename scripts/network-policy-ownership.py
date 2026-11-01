#!/usr/bin/env python3
"""Capture and independently approve a private, exact-node firewall snapshot."""

import argparse
import base64
import hashlib
import json
import os
import re
import runpy
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
PLATFORM = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
QUALIFY = runpy.run_path(str(ROOT / "scripts/network-policy-qualification.py"))
PREFIX = "openclaw-enterprise/platform"
MAX_CAPTURE = 5 * CLEANUP["MAX_SNAPSHOT"] + 65536
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"[1-9][0-9]*\Z")
OWNER_ACTOR_ID = "57728706"


def require_owner_attestation():
    if (os.environ.get("GITHUB_ACTOR_ID") != OWNER_ACTOR_ID or
            os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise ValueError("firewall ownership approval requires a fresh owner dispatch")


class PrivateStore:
    def __init__(self, bucket):
        self.store = PLATFORM["DurableReceipts"]({
            "account_id": "716182248480", "region": "us-east-1", "bucket": bucket,
        })

    def call(self, operation, arguments=()):
        return self.store.call("s3api", operation, arguments)

    def version(self, key, required):
        result = self.call("list-object-versions", [
            "--prefix", key, "--no-paginate",
        ])
        versions = result.get("Versions", [])
        if (result.get("IsTruncated") is not False or result.get("DeleteMarkers") or
                not isinstance(versions, list) or len(versions) != int(required) or
                any(item.get("Key") != key or item.get("IsLatest") is not True or
                    not isinstance(item.get("VersionId"), str) or
                    item["VersionId"] in ("", "null") for item in versions)):
            raise ValueError("private firewall evidence history is incomplete or ambiguous")
        return versions[0]["VersionId"] if required else None

    def read(self, key, limit):
        version = self.version(key, True)
        with tempfile.TemporaryDirectory(prefix="firewall-evidence-") as directory:
            path = Path(directory) / "receipt.json"
            metadata = self.call("get-object", [
                "--key", key, "--version-id", version, "--checksum-mode", "ENABLED",
                str(path),
            ])
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > limit):
                raise ValueError("private firewall evidence is oversized or unsafe")
            content = path.read_bytes()
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
        if (not content or metadata.get("VersionId") != version or
                metadata.get("ContentLength") != len(content) or
                metadata.get("ChecksumSHA256") != checksum or
                metadata.get("ServerSideEncryption") != "aws:kms"):
            raise ValueError("private firewall evidence checksum or encryption differs")
        return content

    def write_once(self, key, record, limit):
        content = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
        if len(content) > limit:
            raise ValueError("private firewall evidence exceeds reviewed bound")
        self.version(key, False)
        with tempfile.TemporaryDirectory(prefix="firewall-evidence-") as directory:
            path = Path(directory) / "receipt.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(content)
            checksum = base64.b64encode(hashlib.sha256(content).digest()).decode()
            response = self.call("put-object", [
                "--key", key, "--body", str(path), "--if-none-match", "*",
                "--checksum-algorithm", "SHA256", "--checksum-sha256", checksum,
                "--server-side-encryption", "aws:kms", "--ssekms-key-id",
                "arn:aws:kms:us-east-1:716182248480:alias/aws/s3",
                "--bucket-key-enabled",
            ])
        version = response.get("VersionId")
        if (not isinstance(version, str) or version in ("", "null") or
                response.get("ChecksumSHA256") != checksum or
                self.version(key, True) != version or self.read(key, limit) != content):
            raise ValueError("private firewall evidence write was not verified")


def placement_and_qualification(store, evidence_sha, node_name, qualification_run_id,
                                admission_run_id):
    if not RUN_ID.fullmatch(admission_run_id or ""):
        raise ValueError("selected canary admission run ID is invalid")
    admission = json.loads(store.read(
        f"{PREFIX}/{evidence_sha}/{admission_run_id}/canary-admit.json", 1048576))
    placement_run_id = admission.get("placementRunId") if isinstance(admission, dict) else None
    placement_version = admission.get("placementVersionId") if isinstance(admission, dict) else None
    if (not isinstance(admission, dict) or admission.get("format") != 1 or
            admission.get("stage") != "canary-admit" or
            admission.get("status") != "verified" or admission.get("verified") is not True or
            admission.get("sourceSha") != evidence_sha or
            admission.get("runId") != admission_run_id or
            admission.get("node") != node_name or
            not isinstance(admission.get("nodeUid"), str) or
            not admission["nodeUid"] or
            not isinstance(admission.get("bootID"), str) or
            not admission["bootID"] or
            not isinstance(placement_run_id, str) or not RUN_ID.fullmatch(placement_run_id) or
            not isinstance(placement_version, str) or placement_version in ("", "null")):
        raise ValueError("verified selected canary admission is missing")
    placement_key = f"{PREFIX}/receipts/{evidence_sha}/placement/{placement_run_id}.json"
    if store.version(placement_key, True) != placement_version:
        raise ValueError("selected placement version differs from admission")
    placement = json.loads(store.read(placement_key, 1048576))
    if store.version(placement_key, True) != placement_version:
        raise ValueError("selected placement version changed during review")
    qualification_bytes = store.read(
        f"{PREFIX}/{evidence_sha}/{qualification_run_id}/qualification.json", 1048576)
    qualification = json.loads(qualification_bytes)
    if (not isinstance(placement, dict) or placement.get("format") != 1 or
            placement.get("verified") is not True or
            placement.get("sourceSha") != evidence_sha or
            placement.get("node") != node_name or
            placement.get("firewallBaselineEmpty") is not True or
            placement.get("placementRunId") != placement_run_id or
            placement.get("nodeUid") != admission["nodeUid"] or
            placement.get("bootID") != admission["bootID"] or
            placement.get("fixtureNode") != QUALIFY["FIXTURE_NODE"] or
            not isinstance(placement.get("fixtureNodeUid"), str) or
            not placement["fixtureNodeUid"] or
            not isinstance(placement.get("fixtureBootID"), str) or
            not placement["fixtureBootID"]):
        raise ValueError("verified pre-enable placement is missing")
    expected_cases = [
        {"source": source, "target": target, "port": port, "protocol": protocol,
         "permitted": permitted, "observed": "NPQ_ALLOWED" if permitted else "NPQ_DENIED"}
        for source, target, port, protocol, permitted in QUALIFY["CASES"]
    ] + [{"source": "npq-client", "target": "kube-dns", "port": 53,
          "protocol": protocol, "permitted": True, "observed": "NPQ_DNS_ALLOWED"}
         for protocol in ("TCP", "UDP")]
    if (not isinstance(qualification, dict) or qualification.get("format") != 1 or
            qualification.get("result") != "traffic-probe-passed-lifecycle-unverified" or
            qualification.get("sourceSha") != evidence_sha or
            qualification.get("node") != node_name or
            qualification.get("nodeUid") != placement["nodeUid"] or
            qualification.get("bootID") != placement["bootID"] or
            qualification.get("fixtureNode") != placement["fixtureNode"] or
            qualification.get("fixtureNodeUid") != placement["fixtureNodeUid"] or
            qualification.get("fixtureBootID") != placement["fixtureBootID"] or
            qualification.get("fixturePodNodes") != {
                "npq-client": node_name,
                "npq-allowed": placement["fixtureNode"],
                "npq-denied": placement["fixtureNode"]} or
            qualification.get("cases") != expected_cases or
            qualification.get("unverifiedLifecycleScenarios") !=
            list(QUALIFY["LIFECYCLE_SCENARIOS"])):
        raise ValueError("successful source-bound canary traffic probe is missing")
    return placement, hashlib.sha256(qualification_bytes).hexdigest(), {
        "admissionRunId": admission_run_id, "placementRunId": placement_run_id,
        "placementVersionId": placement_version,
    }


def capture(store, source_sha, evidence_sha, run_id, qualification_run_id,
            admission_run_id, config):
    CLEANUP["require_firewall_removal_transition"](evidence_sha, source_sha)
    node_name = config["canary"]["node"]
    placement, qualification_sha, selection = placement_and_qualification(
        store, evidence_sha, node_name, qualification_run_id, admission_run_id)
    pod, pod_uid = CLEANUP["inspect_cluster"](config, placement)
    state = CLEANUP["snapshot"](pod)
    _, chains, sets = CLEANUP["cleanup_plan"](state)
    CLEANUP["require_current_main"](source_sha)
    record = {"format": 1, "stage": "firewall-ownership-capture", "verified": False,
              "sourceSha": source_sha, "evidenceSourceSha": evidence_sha,
              "node": node_name,
              "nodeUid": placement["nodeUid"], "bootID": placement["bootID"],
              "cleanupPodUid": pod_uid, "qualificationRunId": qualification_run_id,
              "qualificationSha256": qualification_sha,
              **selection,
              "snapshotSha256": CLEANUP["snapshot_sha256"](state),
              "snapshot": state, "ownedChains": chains, "ownedSets": sets,
              "capturedAt": datetime.now(timezone.utc).isoformat()}
    store.write_once(f"{PREFIX}/{source_sha}/{run_id}/firewall-capture.json",
                     record, MAX_CAPTURE)


def approve(store, source_sha, capture_run_id, reviewed_sha, config):
    require_owner_attestation()
    capture_bytes = store.read(
        f"{PREFIX}/{source_sha}/{capture_run_id}/firewall-capture.json", MAX_CAPTURE)
    candidate = json.loads(capture_bytes)
    node_name = config["canary"]["node"]
    if (not isinstance(candidate, dict) or candidate.get("format") != 1 or
            candidate.get("stage") != "firewall-ownership-capture" or
            candidate.get("verified") is not False or
            candidate.get("sourceSha") != source_sha or
            not isinstance(candidate.get("evidenceSourceSha"), str) or
            candidate.get("node") != node_name or
            not isinstance(candidate.get("qualificationRunId"), str) or
            not RUN_ID.fullmatch(candidate["qualificationRunId"]) or
            not isinstance(candidate.get("admissionRunId"), str) or
            not RUN_ID.fullmatch(candidate["admissionRunId"]) or
            not isinstance(candidate.get("placementRunId"), str) or
            not RUN_ID.fullmatch(candidate["placementRunId"]) or
            not isinstance(candidate.get("placementVersionId"), str) or
            candidate["placementVersionId"] in ("", "null") or
            candidate.get("snapshotSha256") != reviewed_sha or
            candidate.get("snapshotSha256") !=
            CLEANUP["snapshot_sha256"](candidate.get("snapshot"))):
        raise ValueError("reviewed firewall capture is missing or differs")
    evidence_sha = candidate["evidenceSourceSha"]
    CLEANUP["require_firewall_removal_transition"](evidence_sha, source_sha)
    placement, qualification_sha, selection = placement_and_qualification(
        store, evidence_sha, node_name, candidate["qualificationRunId"],
        candidate["admissionRunId"])
    if (candidate.get("nodeUid") != placement["nodeUid"] or
            candidate.get("bootID") != placement["bootID"] or
            candidate.get("qualificationSha256") != qualification_sha or
            any(candidate.get(key) != value for key, value in selection.items())):
        raise ValueError("capture differs from reviewed placement or qualification")
    _, chains, sets = CLEANUP["cleanup_plan"](candidate["snapshot"])
    if (chains, sets) != (candidate.get("ownedChains"), candidate.get("ownedSets")):
        raise ValueError("capture ownership plan differs")
    pod, pod_uid = CLEANUP["inspect_cluster"](config, placement)
    if (pod_uid != candidate.get("cleanupPodUid") or
            CLEANUP["snapshot"](pod) != candidate["snapshot"]):
        raise ValueError("live firewall or cleanup Pod changed after review")
    CLEANUP["require_current_main"](source_sha)
    receipt = {"format": 1, "verified": True, "sourceSha": source_sha,
               "evidenceSourceSha": evidence_sha,
               "node": node_name, "nodeUid": placement["nodeUid"],
               "bootID": placement["bootID"], "snapshotSha256": reviewed_sha,
               "captureRunId": capture_run_id,
               "qualificationRunId": candidate["qualificationRunId"],
               **selection,
               "reviewedAt": datetime.now(timezone.utc).isoformat()}
    store.write_once(f"{PREFIX}/receipts/{source_sha}/firewall-ownership/{capture_run_id}.json",
                     receipt, 1048576)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("capture", "approve"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--qualification-run-id")
    parser.add_argument("--admission-run-id")
    parser.add_argument("--evidence-source-sha")
    parser.add_argument("--capture-run-id")
    parser.add_argument("--reviewed-snapshot-sha256")
    args = parser.parse_args()
    try:
        if args.stage == "approve":
            require_owner_attestation()
        if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
            raise ValueError("firewall ownership requires committed config and source")
        config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
        if config["activationEnabled"] is not True or config["canary"]["node"] is None:
            raise ValueError("no admitted canary")
        PLATFORM["protected_context"](args.expected_sha)
        CLEANUP["require_current_main"](args.expected_sha)
        store = PrivateStore(args.bucket)
        store.store.check()
        if args.stage == "capture":
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            if (not RUN_ID.fullmatch(run_id) or
                    not RUN_ID.fullmatch(args.qualification_run_id or "") or
                    not RUN_ID.fullmatch(args.admission_run_id or "") or
                    not PLATFORM["SHA"].fullmatch(args.evidence_source_sha or "") or
                    args.capture_run_id or args.reviewed_snapshot_sha256):
                raise ValueError("unreviewed capture inputs")
            capture(store, args.expected_sha, args.evidence_source_sha,
                    run_id, args.qualification_run_id, args.admission_run_id, config)
        else:
            if (not RUN_ID.fullmatch(args.capture_run_id or "") or
                    not SHA256.fullmatch(args.reviewed_snapshot_sha256 or "") or
                    args.qualification_run_id or args.admission_run_id or
                    args.evidence_source_sha):
                raise ValueError("unreviewed approval inputs")
            approve(store, args.expected_sha, args.capture_run_id,
                    args.reviewed_snapshot_sha256, config)
        print("Private firewall ownership stage completed; evidence withheld")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Private firewall ownership stage blocked; inspect private evidence",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
