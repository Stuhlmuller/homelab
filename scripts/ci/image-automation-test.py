#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("automation", Path(__file__).with_name("image-automation.py"))
automation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(automation)

base = {
    "schema_version": 1, "imports_paused": True, "import_schedule": "0 * * * *",
    "verification_interval_minutes": 5, "images": [], "consumers": [], "applications": []}
automation.validate(base)
reject_top_level = dict(base, imports_paused="false")
try:
    automation.validate(reject_top_level)
except SystemExit:
    pass
else:
    raise AssertionError("non-boolean import pause accepted")
for invalid_interval in (0, "5", 1441):
    invalid = dict(base, verification_interval_minutes=invalid_interval)
    try:
        automation.validate(invalid)
    except SystemExit:
        pass
    else:
        raise AssertionError("invalid verification interval accepted")
assert automation.validate_workload_evidence(
    "curl-workload-v1",
    {"command": ["curl"], "retry": 60, "timeout": 10, "run_as_non_root": True,
     "read_only_root": True, "health_endpoint": "http://prometheus/-/ready"},
)[0] is True
evidence_app = {"application_id": "kiali", "consumer_ids": [],
                "preflight_recipe": "curl-workload-v1", "health_recipe": "curl-workload-v1",
                "recovery_recipe": "stateless-recovery-v1", "deadline_minutes": 30,
                "evidence": {
                    "preflight": {"command": ["curl"], "retry": 60, "timeout": 10,
                                   "run_as_non_root": True, "read_only_root": True, "health_endpoint": "/-/ready"},
                    "health": {"command": ["curl"], "retry": 60, "timeout": 10,
                                "run_as_non_root": True, "read_only_root": True, "health_endpoint": "/-/ready"},
                    "recovery": {"known_good_digest": "sha256:" + "a" * 64,
                                  "data_safety": "safe", "single_attempt": True}}}
assert automation.validate_application_evidence(evidence_app)[0] is True
evidence_app["evidence"]["preflight"]["command"] = ["/bin/sh"]
assert automation.validate_application_evidence(evidence_app)[0] is False
python_evidence = {
    "uid": 65532, "read_only_root": True, "ca_trust": True,
    "health_endpoint": "/livez", "data_paths": ["/app", "/secrets"]}
assert automation.validate_workload_evidence("python-workload-v1", python_evidence)[0] is True
python_evidence["uid"] = 0
assert automation.validate_workload_evidence("python-workload-v1", python_evidence)[0] is False
del python_evidence["uid"]
assert automation.validate_workload_evidence("python-workload-v1", python_evidence)[0] is False
incomplete_app = dict(evidence_app)
incomplete_app["evidence"] = dict(evidence_app["evidence"])
del incomplete_app["evidence"]["health"]
assert automation.validate_application_evidence(incomplete_app)[0] is False
assert automation.validate_workload_evidence(
    "curl-workload-v1",
    {"command": ["/bin/sh", "-ec"], "retry": 0, "timeout": 0, "run_as_non_root": True,
     "read_only_root": True, "health_endpoint": "http://prometheus/-/ready"},
)[0] is False
assert automation.validate_workload_evidence(
    "stateless-recovery-v1",
    {"known_good_digest": "sha256:" + "a" * 64, "data_safety": "safe", "single_attempt": True},
)[0] is True
bad = dict(base, images=[{"image_id": "pilot", "source": "cgr.dev/chainguard/python:latest", "destination": "harbor.stinkyboi.com/homelab/python", "access_class": "public", "required_platforms": [], "release_recipe": "python-release-v1"}])
try:
    automation.validate(bad)
except SystemExit:
    pass
else:
    raise AssertionError("empty platform list accepted")

def rejects(change):
    candidate = json.loads(json.dumps(base))
    candidate["images"] = [{"image_id": "pilot", "source": "cgr.dev/chainguard/python:latest", "destination": "harbor.stinkyboi.com/homelab/python:latest", "access_class": "public", "required_platforms": ["linux/amd64"], "release_recipe": "python-release-v1"}]
    candidate["consumers"] = [{"consumer_id": "pilot", "application_id": "pilot", "image_id": "pilot", "target": "/clusters/homelab/apps/pilot.yaml", "migration_status": "candidate", "automation_status": "not-enrolled", "owner": "argocd"}]
    candidate["applications"] = [{"application_id": "pilot", "consumer_ids": ["pilot"], "preflight_recipe": "python-workload-v1", "health_recipe": "python-workload-v1", "recovery_recipe": "stateless-recovery-v1", "deadline_minutes": 30}]
    change(candidate)
    try:
        automation.validate(candidate)
    except SystemExit:
        return
    raise AssertionError("invalid contract accepted")

rejects(lambda value: value["images"][0].update(extra="nope"))
rejects(lambda value: value["consumers"][0].update(target="/tmp/../escape"))
rejects(lambda value: value["images"][0].update(source="not a ref"))
rejects(lambda value: value["images"][0].update(access_class="restricted", destination="docker.io/public/python:latest"))
rejects(lambda value: value["applications"][0].update(health_recipe="shell-command"))
rejects(lambda value: value["consumers"][0].update(application_id="other-app"))
rejects(lambda value: value["images"].append(value["images"][0].copy()))

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "config.json"
    config = dict(base)
    config["images"] = [{"image_id": "pilot", "source": "cgr.dev/chainguard/python:latest", "destination": "harbor.stinkyboi.com/homelab/python:latest", "access_class": "public", "required_platforms": ["linux/amd64"], "release_recipe": "python-release-v1"}]
    config["consumers"] = [{"consumer_id": "exporter", "application_id": "exporter", "image_id": "pilot", "target": "/clusters/homelab/apps/harbor/vulnerability-exporter.yaml", "migration_status": "candidate", "automation_status": "enrolled", "owner": "argocd"}]
    config["applications"] = [{"application_id": "exporter", "consumer_ids": ["exporter"], "preflight_recipe": "python-workload-v1", "health_recipe": "python-workload-v1", "recovery_recipe": "stateless-recovery-v1", "deadline_minutes": 30}]
    path.write_text(json.dumps(config))
    assert automation.render(config)["spec"][0]["alias"] == "verified-stable"

state = {"applications": {"app": {"paused": True, "failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "safe", "recovery_attempt": "pending", "failed_digest": "sha256:" + "a" * 64}}}
assert automation.operation_allowed(state, "app", "update")[0] is False
assert automation.operation_allowed(state, "app", "rollback")[0] is True
assert automation.operation_allowed(state, "app", "pause-reject")[0] is True

journal = {"applications": {"app": {"failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "safe", "recovery_attempt": None, "failed_digest": "sha256:" + "a" * 64}}}
automation.observe(journal, "app", "d2", "b" * 40, ["sha256:" + "b" * 64], 30)
assert journal["applications"]["app"]["auto_merge"] is False
assert automation.recover(journal, "app", "safe")[0] is True
assert automation.recover(journal, "app", "safe")[0] is False
unsafe = {"applications": {"app": {"failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "unknown", "recovery_attempt": None, "failed_digest": "sha256:" + "a" * 64}}}
assert automation.recover(unsafe, "app", "unknown")[0] is False
paused = {"applications": {"app": {"failed_deployment_id": "d1", "failed_digest": "sha256:" + "a" * 64}}}
assert automation.pause_reject(paused, "app", "failed health")[0] is True

candidate_state = {"applications": {"app": {"failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "safe", "recovery_attempt": None, "failed_digest": "sha256:" + "a" * 64}}}
candidate = {"base_sha": "b" * 40, "candidate_sha": "c" * 40, "parents": ["b" * 40], "application": "app", "operation": "rollback", "changes": {"rejected_digests": ["sha256:" + "a" * 64]}}
assert automation.validate_candidate(candidate_state, candidate, "b" * 40)[0] is True
wrong_parent = dict(candidate, parents=["d" * 40])
assert automation.validate_candidate(candidate_state, wrong_parent, "b" * 40)[0] is False
wrong_sha = dict(candidate, candidate_sha="not-a-commit")
assert automation.validate_candidate(candidate_state, wrong_sha, "b" * 40)[0] is False
candidate["changes"]["receipts"] = [{"forged": True}]
assert automation.validate_candidate(candidate_state, candidate, "b" * 40)[0] is False
del candidate["changes"]["receipts"]
candidate["changes"]["workflow"] = "forged"
assert automation.validate_candidate(candidate_state, candidate, "b" * 40)[0] is False

receipt = {"image_id": "pilot", "source_ref": "cgr.dev/chainguard/python:latest", "source_digest": "sha256:" + "a" * 64, "destination_ref": "harbor.stinkyboi.com/homelab/python:latest", "destination_digest": "sha256:" + "a" * 64, "version": "3.14.7", "platforms": {"linux/amd64": "sha256:" + "b" * 64, "linux/arm64": "sha256:" + "c" * 64}, "consumer_access": True}
assert automation.verify_release(receipt)[0] is True
assert automation.release_eligible(receipt, "3.14.7")[0] is True
assert automation.release_eligible(receipt, "3.14.7", [receipt["destination_digest"]])[0] is False
assert automation.release_eligible(receipt, "4.0.0")[0] is False
receipt["version"] = "3.15.0-rc1"
assert automation.verify_release(receipt)[0] is False
receipt["version"] = "3.15.0"
receipt["consumer_access"] = False
assert automation.verify_release(receipt)[0] is False
