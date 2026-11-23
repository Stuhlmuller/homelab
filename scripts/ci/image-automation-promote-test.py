#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location("promote", Path(__file__).with_name("image-automation-promote.py"))
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)

state = {"applications": {"app": {"failed_deployment_id": "d1", "known_good_deployment_id": "d0", "current_data_safety": "safe", "recovery_attempt": None, "failed_digest": "sha256:" + "a" * 64}}}
candidate = {"base_sha": "b" * 40, "candidate_sha": "c" * 40, "parents": ["b" * 40], "application": "app", "operation": "rollback", "changes": {"rejected_digests": ["sha256:" + "a" * 64]}}
assert promote.promotion_plan(state, candidate, "b" * 40)[0] is True
assert promote.promotion_plan(state, candidate, "d" * 40)[0] is False
assert promote.promotion_plan(state, candidate, "c" * 40)[0] is True
malformed = dict(candidate, changes={"workflow": "forged"})
assert promote.promotion_plan(state, malformed, "c" * 40)[0] is False
config = {"schema_version": 1, "imports_paused": False, "import_schedule": "0 * * * *",
          "verification_interval_minutes": 5,
          "images": [{"image_id": "pilot", "source": "cgr.dev/chainguard/python:latest",
                      "destination": "harbor.stinkyboi.com/homelab/python:latest", "access_class": "public",
                      "required_platforms": ["linux/amd64"], "release_recipe": "python-release-v1"}],
          "consumers": [{"consumer_id": "pilot", "application_id": "app", "image_id": "pilot",
                         "target": "/clusters/homelab/apps/pilot.yaml", "migration_status": "candidate",
                         "automation_status": "enrolled", "owner": "argocd"}],
          "applications": [{"application_id": "app", "consumer_ids": ["pilot"],
                             "preflight_recipe": "python-workload-v1", "health_recipe": "python-workload-v1",
                             "recovery_recipe": "stateless-recovery-v1", "deadline_minutes": 30}]}
assert promote.validate_candidate_paths(config, candidate,
    ["scripts/config/image-automation-candidate.json", "clusters/homelab/apps/pilot.yaml"])[0] is True
assert promote.validate_candidate_paths(config, candidate, [".github/workflows/evil.yml"])[0] is False
assert promote.validate_candidate_paths(config, candidate, ["clusters/homelab/apps/pilot.yaml"], ["x"])[0] is False
assert promote.fast_forward_ref("b" * 40, "b" * 40, "c" * 40)[0] is True
assert promote.fast_forward_ref("d" * 40, "b" * 40, "c" * 40)[0] is False

# Check that the CLI accepts the candidate identity only through its SHA argument.
with tempfile.TemporaryDirectory() as directory:
    scratch = Path(directory)
    state_path = scratch / "state.json"
    candidate_path = scratch / "candidate.json"
    state_path.write_text(json.dumps(state))
    metadata = {key: value for key, value in candidate.items() if key != "candidate_sha"}
    candidate_path.write_text(json.dumps(metadata))
    command = [
        sys.executable, "-I", str(Path(__file__).with_name("image-automation-promote.py")),
        "--state", str(state_path), "--candidate", str(candidate_path),
        "--candidate-sha", candidate["candidate_sha"], "--main-sha", candidate["base_sha"],
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["promotable"] is True

    candidate_path.write_text(json.dumps(candidate))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "candidate_sha must come from the fetched Git ref" in result.stderr
