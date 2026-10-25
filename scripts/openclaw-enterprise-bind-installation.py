#!/usr/bin/env python3
"""Bind the bootstrapped Installation ID to the reviewed immutable startup Secret.

This source-only entrypoint requires a protected, exact-main dispatch and a
private file-backed bootstrap service key. It changes one Secret annotation;
it never creates a Secret, changes its data, or activates an agent.
"""

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
ANNOTATION = "openclaw.dev/installation-id"
ANNOTATION_PATH = "/metadata/annotations/openclaw.dev~1installation-id"
INSTALLATION_ID = re.compile(r"ins_[A-Za-z0-9_-]+\Z")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


startup = load("openclaw_enterprise_startup", "openclaw-enterprise-startup.py")
oce = load("openclaw_enterprise_reconciler", "openclaw-enterprise.py")


def _identity(installation):
    identity = installation.get("id") if isinstance(installation, dict) else None
    if not isinstance(identity, str) or not INSTALLATION_ID.fullmatch(identity):
        raise oce.Blocked("Enterprise Installation identity is invalid")
    return identity


def _secret(snapshot, candidate, identity):
    secret = snapshot.get("secret") if isinstance(snapshot, dict) else None
    if not isinstance(secret, dict) or not isinstance(secret.get("metadata"), dict):
        raise oce.Blocked("startup Secret identity or ownership is ambiguous")
    metadata = secret["metadata"]
    annotations = metadata.get("annotations")
    labels = metadata.get("labels")
    if (labels != {"app.kubernetes.io/part-of": "openclaw-enterprise"} or
            not isinstance(annotations, dict) or
            not set(annotations) <= {"homelab.stuhlmuller.dev/installation-sha256",
                                     ANNOTATION} or
            (ANNOTATION in annotations and annotations[ANNOTATION] != identity) or
            not isinstance(metadata.get("uid"), str) or not metadata["uid"] or
            not isinstance(metadata.get("resourceVersion"), str) or
            not metadata["resourceVersion"]):
        raise oce.Blocked("startup Secret identity or ownership is ambiguous")
    try:
        startup.verify_secret(secret, candidate)
    except (AttributeError, KeyError, TypeError) as error:
        raise oce.Blocked("startup Secret identity or ownership is ambiguous") from error
    return secret


def _proof(candidate, digest, image, identity, before, after, *, unbound):
    first = _secret(before, candidate, identity)
    second = _secret(after, candidate, identity)
    if not unbound and (first["metadata"]["annotations"].get(ANNOTATION) != identity or
                        second["metadata"]["annotations"].get(ANNOTATION) != identity):
        raise oce.Blocked("startup Secret Installation ID is unbound")
    if unbound:
        # Reuse the full reconciler proof without trusting a self-declared ID.
        # Only the missing annotation is supplied in the proof copies.
        before, after = deepcopy(before), deepcopy(after)
        before["secret"]["metadata"]["annotations"][ANNOTATION] = identity
        after["secret"]["metadata"]["annotations"][ANNOTATION] = identity
    return oce.attest_stable_installation(candidate, digest, identity,
                                         before, after, image)


def _same_workloads(before, after):
    for field in ("installationId", "installationChecksum", "secretUid",
                  "deploymentUids", "replicaSetUids", "podUids",
                  "deploymentResourceVersions", "replicaSetResourceVersions",
                  "podResourceVersions"):
        if before[field] != after[field]:
            raise oce.Blocked("Installation workload changed during binding")


def bind(expected_sha, config, api, kube, bridge=None):
    if bridge is None:
        startup.reviewed_main(expected_sha)
    oce._validate_config(config)
    candidate, digest, image = oce.reviewed_installation(config)
    if digest != startup.DIGEST:
        raise oce.Blocked("startup Secret version differs from reviewed source")

    before = kube.snapshot(digest)
    identity = _identity(api.get("/installation"))
    after = kube.snapshot(digest)
    prior = _proof(candidate, digest, image, identity, before, after, unbound=True)
    secret = after["secret"]
    metadata = secret["metadata"]
    was_bound = metadata["annotations"].get(ANNOTATION) == identity

    if not was_bound and _identity(api.get("/installation")) != identity:
        raise oce.Blocked("Enterprise Installation identity changed before binding")
    if bridge is not None:
        bridge.ready_and_wait(identity, metadata, was_bound)
    else:
        # Keep the exact-main check adjacent to the only write.
        startup.reviewed_main(expected_sha)
    if not was_bound and bridge is None:
        operations = [
            {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion",
             "value": metadata["resourceVersion"]},
            {"op": "add", "path": ANNOTATION_PATH, "value": identity},
        ]
        # kubectl captures the Secret response; neither it nor the patch is logged.
        startup.kube("-n", startup.NAMESPACE, "patch", "secret", startup.NAME,
                     "--type=json", "-p", json.dumps(operations, separators=(",", ":")))

    confirmed_before = kube.snapshot(digest)
    if _identity(api.get("/installation")) != identity:
        raise oce.Blocked("Enterprise Installation identity changed during binding")
    confirmed_after = kube.snapshot(digest)
    current = _proof(candidate, digest, image, identity, confirmed_before,
                     confirmed_after, unbound=False)
    _same_workloads(prior, current)
    if was_bound and prior["secretResourceVersion"] != current["secretResourceVersion"]:
        raise oce.Blocked("startup Secret changed during idempotent binding")
    if not was_bound and prior["secretResourceVersion"] == current["secretResourceVersion"]:
        raise oce.Blocked("startup Secret annotation patch was not observed")
    return {"installationId": identity, "secretUid": current["secretUid"],
            "secretResourceVersion": current["secretResourceVersion"]}


class JobBridge:
    """Send a bounded non-secret proof; the protected runner performs the CAS patch."""

    def __init__(self, expected_sha, job_name):
        if not re.fullmatch(r"oce-journal-bind-installation-[1-9][0-9]{0,19}-[1-9][0-9]{0,4}",
                            job_name):
            raise oce.Blocked("binding Job identity is invalid")
        self.expected_sha = expected_sha
        self.job_name = job_name

    def ready_and_wait(self, identity, metadata, was_bound):
        receipt = {"schema": 1, "expectedSha": self.expected_sha,
                   "jobName": self.job_name, "installationId": identity,
                   "secretUid": metadata["uid"],
                   "secretResourceVersion": metadata["resourceVersion"],
                   "alreadyBound": was_bound, "issuedAt": int(time.time())}
        print("OCE_BIND_READY:" + json.dumps(
            receipt, sort_keys=True, separators=(",", ":")), flush=True)
        if was_bound:
            return
        deadline = time.monotonic() + 120
        candidate = (ROOT / "clusters/homelab/apps/openclaw-enterprise/installation.yaml").read_bytes()
        while time.monotonic() < deadline:
            secret = startup.kube_json("-n", startup.NAMESPACE, "get", "secret",
                                       startup.NAME, "-o=json")
            _secret({"secret": secret}, candidate, identity)
            current = secret["metadata"]
            if current["uid"] != metadata["uid"]:
                raise oce.Blocked("startup Secret was replaced during binding")
            if current["annotations"].get(ANNOTATION) == identity:
                if current["resourceVersion"] == metadata["resourceVersion"]:
                    raise oce.Blocked("startup Secret binding did not change its version")
                return
            if current["resourceVersion"] != metadata["resourceVersion"]:
                raise oce.Blocked("startup Secret changed before protected binding")
            time.sleep(2)
        raise oce.Blocked("protected startup Secret binding did not arrive")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--operator-source-sha")
    parser.add_argument("--reviewed-config-sha256")
    parser.add_argument("--job-name")
    args = parser.parse_args(argv)
    try:
        operator_mode = any((args.config, args.operator_source_sha,
                             args.reviewed_config_sha256, args.job_name))
        if operator_mode:
            if not all((args.config, args.operator_source_sha,
                        args.reviewed_config_sha256, args.job_name)):
                raise oce.Blocked("operator binding source receipt is incomplete")
            oce._require_projected_operator_config(
                args.config, args.expected_sha, args.operator_source_sha,
                args.reviewed_config_sha256)
            bridge = JobBridge(args.expected_sha, args.job_name)
            config_path = args.config
        else:
            # Check source before opening the protected credential file.
            startup.reviewed_main(args.expected_sha)
            bridge = None
            config_path = ROOT / "scripts/config/openclaw-enterprise.json"
        config = json.loads(config_path.read_text())
        oce._validate_config(config)
        if operator_mode and (config.get("journalOperator", {}).get("imageSourceSha") !=
                              args.operator_source_sha or
                              config["bootstrap"]["serviceKeyFile"] != str(args.credential_file)):
            raise oce.Blocked("operator binding source or credential path changed")
        api = oce.API(config["privateOrigins"]["console"], oce._read_key(args.credential_file))
        bind(args.expected_sha, config, api, oce.Kubernetes(), bridge)
    except (startup.Blocked, oce.Blocked, OSError, ValueError, KeyError, TypeError) as error:
        print(f"OpenClaw Enterprise Installation binding blocked: {error}", file=sys.stderr)
        return 1
    print("OpenClaw Enterprise Installation binding verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
