"""Exercise the staged Emergency GitHub Trigger migration with synthetic exports."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def yaml_json(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", path], text=True))


def digest(value):
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def rewrite(value):
    if isinstance(value, dict):
        return {key: rewrite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite(item) for item in value]
    if isinstance(value, str):
        return value.replace("$json.body.payload", "$json.body")
    return value


values_path = "clusters/homelab/apps/n8n/migration-github-trigger-v1.values.yaml"
values = yaml_json(values_path)
base = yaml_json("clusters/homelab/apps/n8n/values.yaml")
job = values["controllers"]["migrate-github-trigger-v1"]
assert job["type"] == "job"
assert job["annotations"] == {"argocd.argoproj.io/sync-wave": "1"}
assert job["job"] == {"backoffLimit": 1, "activeDeadlineSeconds": 900}
assert job["pod"]["automountServiceAccountToken"] is False
assert job["pod"]["affinity"]["podAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"] == [{
    "labelSelector": {"matchLabels": {
        "app.kubernetes.io/controller": "n8n",
        "app.kubernetes.io/instance": "n8n",
        "app.kubernetes.io/name": "n8n",
    }},
    "topologyKey": "kubernetes.io/hostname",
}]
assert job["containers"]["migrate"]["image"] == base["controllers"]["n8n"]["containers"]["app"]["image"]
assert values["persistence"]["data"]["advancedMounts"]["migrate-github-trigger-v1"]["migrate"] == [
    {"path": "/home/node/.n8n"},
]
assert values["persistence"]["postgres-client"]["advancedMounts"]["migrate-github-trigger-v1"]["migrate"] == [
    {"path": "/run/secrets/n8n-postgres", "readOnly": True},
]
assert "migrate-github-trigger-v1" not in base["controllers"]
assert "migration-github-trigger-v1.values.yaml" not in Path(
    "IaC/homelab/us-west-2/apps/n8n/stack.hcl").read_text()
assert "migration-github-trigger-v1.values.yaml" not in Path(
    "clusters/homelab/apps/n8n/kustomization.yaml").read_text()

command = job["containers"]["migrate"]["command"][2]
assert 'test "$(n8n --version)" = 2.43.7' in command
assert "n8n export:workflow --id=\"$workflow_id\"" in command
assert "n8n import:workflow --input=/tmp/github-trigger-workflow.json" in command
assert "n8n publish:workflow --id=\"$workflow_id\"" in command
assert "verify_readback false" in command
assert "verify_readback true" in command
assert "n8n export:credentials" not in command
assert "kubectl " not in command
script = command.split("node - <<'NODE'\n", 1)[1].split("\nNODE\n", 1)[0]
assert "f3e12cbd-1d01-4ef0-b24e-d68741ea898b" in script
assert "7d4342d3-103b-437a-a941-811a75dacb2f" in script

ids = [
    "f4769735-e1c5-4dbf-aa4a-1a0d3931c884",
    "23bc932a-ca2a-4e7d-88b3-2748f60174d8",
    "7f426a53-7340-4e92-a95e-f2e5f3fd83e6",
    "e1b741ef-b01c-48d1-9129-2b910c495b89",
    "f8bf4b63-e0ff-41f9-8f29-6c870a9f2ade",
    "83da1c4b-26dc-4e4a-ba1f-675f5e876d96",
]
credential = {"id": "fixture-github-app", "name": "Fixture GitHub App"}
nodes = [
    {"id": ids[0], "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2.1,
     "webhookId": "7d4342d3-103b-437a-a941-811a75dacb2f", "position": [0, 0],
     "parameters": {"httpMethod": "POST", "path": "7d4342d3-103b-437a-a941-811a75dacb2f", "options": {}}},
    {"id": ids[1], "name": "Edit Fields", "type": "n8n-nodes-base.set", "typeVersion": 3.4,
     "parameters": {"assignments": {"assignments": [{"value": "={{$json.body.payload.action}}"}]},
                    "options": {}}},
    {"id": ids[2], "name": "Filter", "type": "n8n-nodes-base.filter", "typeVersion": 2.3,
     "parameters": {"conditions": {"conditions": [
         {"leftValue": "={{$json.body.payload.action}}"},
         {"leftValue": "={{$json.body.payload.label.name}}"},
         {"leftValue": "={{$json.body.payload.sender.url}}"},
     ]}, "options": {}}},
    {"id": ids[3], "name": "Create an issue", "type": "n8n-nodes-base.github", "typeVersion": 1.1,
     "credentials": {"githubAppApi": credential},
     "parameters": {"authentication": "githubAppApi", "owner": {"value": "={{$json.body.payload.pull_request.head.repo.owner.login}}"},
                    "repository": {"value": "={{$json.body.payload.pull_request.head.repo.name}}"},
                    "body": "={{$json.body.payload.pull_request.url}} {{$json.body.payload.repository.full_name}} {{$json.body.payload.sender.login}}",
                    "assignees": [], "labels": [], "title": "fixture"}},
    {"id": ids[4], "name": "Merge a pull request", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4,
     "credentials": {"githubAppApi": credential},
     "parameters": {"authentication": "predefinedCredentialType", "nodeCredentialType": "githubAppApi",
                    "method": "PUT", "sendBody": True, "bodyParameters": {}, "options": {}, "url": "https://example.invalid"}},
    {"id": ids[5], "name": "Create a comment on an issue", "type": "n8n-nodes-base.github", "typeVersion": 1.1,
     "credentials": {"githubAppApi": credential},
     "parameters": {"authentication": "githubAppApi", "operation": "createComment", "owner": "fixture",
                    "repository": "fixture", "issueNumber": "1", "body": "fixture"}},
]
connections = {
    source: {"main": [[{"node": target, "type": "main", "index": 0}]]}
    for source, target in zip((node["name"] for node in nodes),
                              (node["name"] for node in nodes[1:]))
}
original = [{"id": "AARG1VWHRxowXlSU", "active": True, "nodes": nodes,
             "connections": connections, "staticData": None, "settings": {"executionTimeout": 60}}]

# Replace only the live parameter fingerprints with fingerprints for synthetic
# parameters. The production Job retains the independently inventoried hashes.
fixture_hashes = []
for index, node in enumerate(nodes):
    fixture_hashes.append(digest(node["parameters"]))
    if index in (1, 2, 3):
        fixture_hashes.append(digest(rewrite(node["parameters"])))
live_hashes = re.findall(r"'([0-9a-f]{64})'", script)
assert len(live_hashes) == len(fixture_hashes) == 9
fixture_script = script
for live_hash, fixture_hash in zip(live_hashes, fixture_hashes):
    fixture_script = fixture_script.replace(live_hash, fixture_hash, 1)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    workflow_file = root / "github-trigger-workflow.json"
    state_file = root / "github-trigger-migration-state"
    source = fixture_script.replace("/tmp/github-trigger-", f"{root}/github-trigger-")

    def run(data, success=True, expected_state=None):
        state_file.unlink(missing_ok=True)
        workflow_file.write_text(json.dumps(data))
        before = workflow_file.read_bytes()
        result = subprocess.run(["node", "-"], input=source, text=True,
                                capture_output=True, timeout=10)
        assert (result.returncode == 0) == success, result.stderr
        if not success or expected_state == "unchanged":
            assert workflow_file.read_bytes() == before
        if expected_state:
            assert state_file.read_text() == expected_state
        else:
            assert not state_file.exists()
        return json.loads(workflow_file.read_text())

    migrated = run(copy.deepcopy(original), expected_state="changed")
    assert migrated[0]["nodes"][0]["type"] == "n8n-nodes-base.githubTrigger"
    assert migrated[0]["nodes"][0]["webhookId"] == "f3e12cbd-1d01-4ef0-b24e-d68741ea898b"
    assert migrated[0]["nodes"][0]["credentials"] == {"githubAppApi": credential}
    assert migrated[0]["nodes"][0]["parameters"]["events"] == ["pull_request"]
    for before, after in zip(original[0]["nodes"][1:], migrated[0]["nodes"][1:]):
        assert after["parameters"] == rewrite(before["parameters"])
        assert after.get("credentials") == before.get("credentials")
    assert migrated[0]["connections"] == original[0]["connections"]
    run(migrated, expected_state="unchanged")

    for data in ({}, [], original * 2, [{**original[0], "id": "wrong"}]):
        run(data, success=False)
    stale_cases = []
    changed = copy.deepcopy(original)
    changed[0]["connections"]["Filter"]["main"][0].append(
        {"node": "Merge a pull request", "type": "main", "index": 0})
    stale_cases.append(changed)
    changed = copy.deepcopy(original)
    changed[0]["nodes"][2]["parameters"]["conditions"]["conditions"][0]["leftValue"] = "user edit"
    stale_cases.append(changed)
    changed = copy.deepcopy(original)
    changed[0]["nodes"][3]["credentials"]["githubAppApi"] = {"id": "different", "name": "Fixture GitHub App"}
    stale_cases.append(changed)
    changed = copy.deepcopy(original)
    changed[0]["nodes"][0]["webhookId"] = "wrong"
    stale_cases.append(changed)
    changed = copy.deepcopy(original)
    changed[0]["staticData"] = {"node:Webhook": {"webhookSecret": "fixture"}}
    stale_cases.append(changed)
    changed = copy.deepcopy(original)
    changed[0]["active"] = False
    stale_cases.append(changed)
    changed = copy.deepcopy(migrated)
    changed[0]["nodes"][2]["parameters"]["conditions"]["conditions"][0]["leftValue"] = "stale"
    stale_cases.append(changed)
    for changed in stale_cases:
        run(changed, success=False)

    exports = root / "export.json"
    exports.write_text(json.dumps(original))
    calls = root / "calls"
    password = root / "postgres-password"
    password.write_text("fixture")
    config = root / "config"
    config.write_text("fixture")
    fixture_command = command.replace("/tmp/github-trigger-", f"{root}/github-trigger-") \
        .replace("/home/node/.n8n/config", str(config))
    for live_hash, fixture_hash in zip(live_hashes, fixture_hashes):
        fixture_command = fixture_command.replace(live_hash, fixture_hash, 1)
    stub = """
set_active() {
  node -e 'const fs=require("fs"); const p=process.argv[1]; const a=JSON.parse(fs.readFileSync(p,"utf8")); a[0].active=process.argv[2]==="true"; fs.writeFileSync(p,JSON.stringify(a))' "$EXPORT" "$1"
}
n8n() {
  case "$1" in
    --version) echo "${VERSION:-2.43.7}" ;;
    list:workflow) echo AARG1VWHRxowXlSU ;;
    export:workflow) cp "$EXPORT" "${3#--output=}" ;;
    import:workflow)
      if [ "${IMPORT_SKIP:-}" = true ]; then
        echo import-skip >> "$CALLS"
      else
        echo import >> "$CALLS"
        cp "${2#--input=}" "$EXPORT"
        set_active false
      fi ;;
    publish:workflow) echo publish >> "$CALLS"; set_active true ;;
    *) return 99 ;;
  esac
}
"""
    env = {**os.environ, "DB_POSTGRESDB_PASSWORD_FILE": str(password),
           "EXPORT": str(exports), "CALLS": str(calls)}
    for expected_calls in (["import", "publish"], ["import", "publish"]):
        result = subprocess.run(["/bin/sh", "-ec", stub + fixture_command], env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert calls.read_text().splitlines() == expected_calls
    assert json.loads(exports.read_text()) == migrated

    # A policy-skipped import may exit zero. The readback must block publishing
    # the original unsigned graph instead of reporting migration success.
    exports.write_text(json.dumps(original))
    calls.unlink()
    result = subprocess.run(["/bin/sh", "-ec", stub + fixture_command],
                            env={**env, "IMPORT_SKIP": "true"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert calls.read_text().splitlines() == ["import-skip"]
    assert json.loads(exports.read_text()) == original

    calls.unlink()
    result = subprocess.run(["/bin/sh", "-ec", stub + fixture_command],
                            env={**env, "VERSION": "2.43.6"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert not calls.exists()

print("n8n GitHub Trigger staged migration fixtures passed")
