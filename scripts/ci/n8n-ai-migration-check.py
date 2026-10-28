"""Exercise the one-time Job migration with synthetic workflow exports."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

gateway_policy = json.loads(subprocess.check_output([
    "yq", "-o=json", 'select(.metadata.name == "litellm-allow-required-clients")',
    "clusters/homelab/apps/litellm/authorizationpolicy.yaml",
], text=True))
rule = gateway_policy["spec"]["rules"][0]
assert "cluster.local/ns/automation/sa/n8n" in rule["from"][0]["source"]["principals"]
assert rule["to"] == [{"operation": {"ports": ["4000"]}}]

values = json.loads(subprocess.check_output([
    "yq", "-o=json", ".", "clusters/homelab/apps/n8n/values.yaml",
], text=True))
app = values["controllers"]["n8n"]
assert "migrate-ai-workflow" not in app["initContainers"]
assert list(app["initContainers"]) == ["wait-for-postgres"]
assert app["strategy"] == "Recreate"
assert "migrate-ai-workflow-v1" not in values["controllers"]
assert "migration-v1.values.yaml" not in Path("IaC/homelab/us-west-2/apps/n8n/stack.hcl").read_text()
assert "migration-v1.values.yaml" not in Path("clusters/homelab/apps/n8n/kustomization.yaml").read_text()
migration_values = json.loads(subprocess.check_output([
    "yq", "-o=json", ".", "clusters/homelab/apps/n8n/migration-v1.values.yaml",
], text=True))
job = migration_values["controllers"]["migrate-ai-workflow-v1"]
assert job["type"] == "job"
assert job["annotations"] == {"argocd.argoproj.io/sync-wave": "1"}
assert job["job"]["backoffLimit"] == 1
assert job["job"]["activeDeadlineSeconds"] == 900
assert "ttlSecondsAfterFinished" not in job["job"]
assert job["pod"]["affinity"]["podAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"] == [{
    "labelSelector": {"matchLabels": {
        "app.kubernetes.io/controller": "n8n",
        "app.kubernetes.io/instance": "n8n",
        "app.kubernetes.io/name": "n8n",
    }},
    "topologyKey": "kubernetes.io/hostname",
}]
assert migration_values["persistence"]["data"]["advancedMounts"]["migrate-ai-workflow-v1"]["migrate"] == [
    {"path": "/home/node/.n8n"},
]
assert migration_values["persistence"]["postgres-client"]["advancedMounts"]["migrate-ai-workflow-v1"]["migrate"] == [
    {"path": "/run/secrets/n8n-postgres", "readOnly": True},
]
command = job["containers"]["migrate"]["command"][2]
script = command.split('node - "$workflow_id" <<\'NODE\'\n', 1)[1].split("\nNODE", 1)[0]
assert 'if [ "$(cat /tmp/ai-workflow-active)" = true ]; then\n  n8n publish:workflow' in command
assert 'n8n export:workflow --id="$workflow_id"' in command
assert 'n8n import:workflow --input=/tmp/ai-workflow.json' in command
assert 'workflow_ids="$(n8n list:workflow --onlyId)"' in command
assert 'if ! printf' in command
assert 'node - "$workflow_id" <<' in command
assert 'if ! node - "$workflow_id"' not in command
assert 'N8N_AI_MIGRATION_APPLIED workflow_id=$workflow_id active=true restart_required=true' in command
targets = [
    ("s1JVSbnvnmHMCbty", "5c52f616-3b9e-4483-89e3-effffc393750", True, "lmChatAwsBedrock", "anthropic.claude-3-sonnet-20240229-v1:0"),
    ("xaUDsbylSwaveMQ5", "d8f30a03-c3a1-4bdd-b733-8e33da04b004", False, "lmChatOpenAi", "gpt-5.5"),
    ("Wc0AMPBPqBegSey5", "3278c81b-c7cd-4181-aa17-ad91b9d932a8", False, "lmChatAwsBedrock", "anthropic.claude-3-sonnet-20240229-v1:0"),
]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    source = script.replace("'/tmp/ai-", f"'{root}/ai-")
    path = root / "ai-workflow.json"
    originals = {}

    def run(workflow_id, data, success=True, skipped=False):
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        result = subprocess.run(["node", "-", workflow_id], input=source,
                                text=True, capture_output=True, timeout=10)
        assert (result.returncode == 0) == success, result.stderr
        if not success or skipped:
            assert path.read_bytes() == before
        if skipped:
            assert (root / "ai-workflow-changed").read_text() == "skip"
        return json.loads(path.read_text())

    for workflow_id, node_id, active, kind, model in targets:
        assert workflow_id in command.split("; do", 1)[0]
        model_value = {"__rl": True, "value": model, "mode": "list"} if kind == "lmChatOpenAi" else model
        original = [{"id": workflow_id, "active": active, "settings": {"executionTimeout": 30},
                     "connections": {"preserved": []}, "nodes": [
                         {"id": node_id, "name": "preserve this label", "position": [0, 0],
                          "type": "@n8n/n8n-nodes-langchain." + kind, "typeVersion": 1,
                          "parameters": {"model": model_value, "options": {}, "builtInTools": {}},
                          "credentials": {"legacy": {"id": "fixture-reference"}}},
                         {"id": "unrelated", "type": "n8n-nodes-base.noOp", "parameters": {}},
                     ]}]
        originals[workflow_id] = original
        migrated = run(workflow_id, original)
        expected = copy.deepcopy(original)
        expected[0]["nodes"][0].update(
            type="@n8n/n8n-nodes-langchain.lmChatOpenAi", typeVersion=1.3,
            parameters={"model": {"__rl": True, "mode": "list", "value": "openrouter/free"}, "options": {}},
            credentials={"openAiApi": {"id": "litellm-managed", "name": "LiteLLM Gateway"}},
        )
        assert migrated == expected
        assert (root / "ai-workflow-active").read_text() == str(active).lower()
        assert (root / "ai-workflow-changed").read_text() == "true"
        assert run(workflow_id, migrated) == migrated
        assert (root / "ai-workflow-changed").read_text() == "false"
        for data in ({}, [], original * 2, [{**original[0], "id": "unexpected"}]):
            run(workflow_id, data, success=False)
        for field, value in (("model", "unexpected"), ("responsesApiEnabled", True),
                             ("options", {"baseURL": "https://example.invalid"}),
                             ("builtInTools", {"webSearch": True})):
            changed = copy.deepcopy(original)
            changed[0]["nodes"][0]["parameters"][field] = value
            run(workflow_id, changed, skipped=True)
        changed = copy.deepcopy(original)
        changed[0]["nodes"].append(copy.deepcopy(changed[0]["nodes"][0]))
        run(workflow_id, changed, success=False)
        changed = copy.deepcopy(original)
        changed[0]["nodes"] = [node for node in changed[0]["nodes"] if node["id"] != node_id]
        run(workflow_id, changed, skipped=True)
        changed[0]["nodes"].append(None)
        run(workflow_id, changed, success=False)
        changed = copy.deepcopy(original)
        changed[0]["nodes"][0]["parameters"] = None
        run(workflow_id, changed, success=False)

    exports = root / "exports"
    exports.mkdir()
    calls = root / "calls"
    credential_store = root / "credential-store.json"
    password = root / "postgres-password"
    password.write_text("fixture")
    edited = copy.deepcopy(originals["xaUDsbylSwaveMQ5"])
    edited[0]["nodes"][0]["parameters"]["model"]["value"] = "user-edited-model"
    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    (exports / "xaUDsbylSwaveMQ5.json").write_text(json.dumps(edited))
    fixture_command = command.replace("/home/node/.n8n/config", str(root / "config")) \
        .replace("/tmp/ai-", str(root / "ai-")) \
        .replace("/tmp/litellm-", str(root / "litellm-")) \
        .replace("/dev/shm", str(root))
    n8n_stub = '''
n8n() {
  case "$1" in
    export:credentials)
      echo credential-export >> "$CALLS"
      [ "$2" = --id=litellm-managed ] && [ "$3" = --decrypted ] || return 99
      [ "${CREDENTIAL_EXPORT_FAIL:-}" != true ] || {
        echo 'database unavailable' >&2
        return 33
      }
      if [ -f "$CREDENTIAL_STORE" ]; then
        cp "$CREDENTIAL_STORE" "${4#--output=}"
      else
        echo 'No credentials found with specified filters' >&2
        return 1
      fi
      ;;
    import:credentials)
      echo credentials >> "$CALLS"
      cp "${2#--input=}" "$CREDENTIAL_STORE" ;;
    list:workflow)
      [ "$2" = --onlyId ] || return 99
      [ "${LIST_FAIL:-}" != true ] || return 28
      for export in "$EXPORT_DIR"/*.json; do
        [ -f "$export" ] || continue
        export="${export##*/}"
        echo "${export%.json}"
      done
      ;;
    export:workflow)
      workflow_id="${2#--id=}"
      [ "$workflow_id" != "${EXPORT_FAIL_ID:-}" ] || return 27
      [ -f "$EXPORT_DIR/$workflow_id.json" ] || return 1
      cp "$EXPORT_DIR/$workflow_id.json" "${3#--output=}"
      ;;
    import:workflow)
      [ "${IMPORT_FAIL:-}" != true ] || return 29
      echo import >> "$CALLS"
      cp "${2#--input=}" "$EXPORT_DIR/$workflow_id.json" ;;
    publish:workflow) echo "publish:${2#--id=}" >> "$CALLS" ;;
    *) return 99 ;;
  esac
}
'''
    environment = {**os.environ, "DB_POSTGRESDB_PASSWORD_FILE": str(password),
                   "N8N_BOOTSTRAP_ENCRYPTION_KEY": "fixture", "EXPORT_DIR": str(exports),
                   "CREDENTIAL_STORE": str(credential_store), "CALLS": str(calls)}

    def run_job(extra_env=None, shell_command=fixture_command):
        calls.unlink(missing_ok=True)
        result = subprocess.run(["/bin/sh", "-ec", n8n_stub + shell_command],
                                env={**environment, **(extra_env or {})},
                                capture_output=True, text=True, timeout=20)
        observed = calls.read_text().splitlines() if calls.exists() else []
        assert not (root / "litellm-existing.json").exists()
        assert not (root / "litellm-export.log").exists()
        assert not (root / "litellm-credential.json").exists()
        return result, observed

    result, observed = run_job()
    assert result.returncode == 0, result.stderr
    assert observed == ["credential-export", "credentials", "import", "publish:s1JVSbnvnmHMCbty"]
    assert "Skipping AI workflow migration for xaUDsbylSwaveMQ5" in result.stderr
    assert "Skipping AI workflow migration for Wc0AMPBPqBegSey5" in result.stderr
    assert json.loads(credential_store.read_text()) == [{
        "id": "litellm-managed", "name": "LiteLLM Gateway", "type": "openAiApi", "data": {},
    }]

    # A Job retry after import must not rewrite either already-migrated state.
    credential_before = credential_store.read_bytes()
    result, observed = run_job()
    assert result.returncode == 0, result.stderr
    assert observed == []
    assert credential_store.read_bytes() == credential_before

    # A needed migration reuses the existing blank credential without import.
    credential_before = credential_store.read_bytes()
    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    result, observed = run_job()
    assert result.returncode == 0, result.stderr
    assert observed == ["credential-export", "import", "publish:s1JVSbnvnmHMCbty"]
    assert credential_store.read_bytes() == credential_before

    # Type-wide overwrites fill only empty fields: reject stored custom data.
    credential_store.write_text(json.dumps([{
        "id": "litellm-managed", "name": "LiteLLM Gateway", "type": "openAiApi",
        "data": {"apiKey": "user-owned-fixture"},
    }]))
    credential_before = credential_store.read_bytes()
    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    result, observed = run_job()
    assert result.returncode != 0
    assert observed == ["credential-export"]
    assert credential_store.read_bytes() == credential_before

    for export in exports.iterdir():
        export.unlink()
    result, observed = run_job()
    assert result.returncode == 0, result.stderr
    assert observed == []
    assert credential_store.read_bytes() == credential_before

    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    result, observed = run_job({"EXPORT_FAIL_ID": "s1JVSbnvnmHMCbty"})
    assert result.returncode != 0
    assert observed == []
    assert credential_store.read_bytes() == credential_before

    result, observed = run_job({"LIST_FAIL": "true"})
    assert result.returncode != 0
    assert observed == []
    assert credential_store.read_bytes() == credential_before

    result, observed = run_job({"CREDENTIAL_EXPORT_FAIL": "true"})
    assert result.returncode != 0
    assert observed == ["credential-export"]
    assert credential_store.read_bytes() == credential_before

    result, observed = run_job({"IMPORT_FAIL": "true"})
    assert result.returncode != 0
    assert observed == ["credential-export"]
    assert credential_store.read_bytes() == credential_before

    credential_store.write_text(json.dumps([{
        "id": "litellm-managed", "name": "LiteLLM Gateway", "type": "otherCredential",
        "data": {},
    }]))
    credential_before = credential_store.read_bytes()
    result, observed = run_job()
    assert result.returncode != 0
    assert observed == ["credential-export"]
    assert credential_store.read_bytes() == credential_before

    (exports / "s1JVSbnvnmHMCbty.json").write_text("{invalid-json")
    result, observed = run_job()
    assert result.returncode != 0
    assert observed == []

    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    write_failure_command = fixture_command.replace(
        "fs.writeFileSync(path, JSON.stringify(workflows));",
        f"fs.writeFileSync({json.dumps(str(root / 'missing-parent' / 'workflow.json'))}, JSON.stringify(workflows));")
    assert write_failure_command != fixture_command
    result, observed = run_job(shell_command=write_failure_command)
    assert result.returncode != 0
    assert observed == []

    removed = copy.deepcopy(originals["s1JVSbnvnmHMCbty"])
    removed[0]["nodes"] = [node for node in removed[0]["nodes"]
                           if node["id"] != "5c52f616-3b9e-4483-89e3-effffc393750"]
    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(removed))
    result, observed = run_job()
    assert result.returncode == 0, result.stderr
    assert observed == []
    assert "Skipping AI workflow migration for s1JVSbnvnmHMCbty" in result.stderr
print("n8n staged AI migration: startup independence, credential preservation, idempotence and refusal guards passed")
