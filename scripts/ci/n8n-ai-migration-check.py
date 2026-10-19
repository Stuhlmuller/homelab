"""Exercise the deployed inline migration with synthetic workflow exports."""
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

command = subprocess.check_output([
    "yq", "-r", '.controllers.n8n.initContainers."migrate-ai-workflow".command[2]',
    "clusters/homelab/apps/n8n/values.yaml",
], text=True)
script = command.split('node - "$workflow_id" <<\'NODE\'\n', 1)[1].split("\nNODE", 1)[0]
assert 'if [ "$(cat /tmp/ai-workflow-active)" = true ]; then\n  n8n publish:workflow' in command
assert 'n8n export:workflow --id="$workflow_id"' in command
assert 'n8n import:workflow --input=/tmp/ai-workflow.json' in command
assert 'if ! n8n export:workflow' in command
assert 'if ! node - "$workflow_id"' in command
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

    def run(workflow_id, data, success=True):
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        result = subprocess.run(["node", "-", workflow_id], input=source,
                                text=True, capture_output=True, timeout=10)
        assert (result.returncode == 0) == success, result.stderr
        if not success:
            assert path.read_bytes() == before
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
            run(workflow_id, changed, success=False)
        changed = copy.deepcopy(original)
        changed[0]["nodes"].append(copy.deepcopy(changed[0]["nodes"][0]))
        run(workflow_id, changed, success=False)

    exports = root / "exports"
    exports.mkdir()
    calls = root / "calls"
    password = root / "postgres-password"
    password.write_text("fixture")
    edited = copy.deepcopy(originals["xaUDsbylSwaveMQ5"])
    edited[0]["nodes"][0]["parameters"]["model"]["value"] = "user-edited-model"
    (exports / "s1JVSbnvnmHMCbty.json").write_text(json.dumps(originals["s1JVSbnvnmHMCbty"]))
    (exports / "xaUDsbylSwaveMQ5.json").write_text(json.dumps(edited))
    fixture_command = command.replace("/home/node/.n8n/config", str(root / "config")) \
        .replace("/tmp/ai-", str(root / "ai-")) \
        .replace("/tmp/litellm-", str(root / "litellm-"))
    n8n_stub = '''
n8n() {
  case "$1" in
    import:credentials) echo credentials >> "$CALLS" ;;
    export:workflow)
      workflow_id="${2#--id=}"
      [ -f "$EXPORT_DIR/$workflow_id.json" ] || return 1
      cp "$EXPORT_DIR/$workflow_id.json" "${3#--output=}"
      ;;
    import:workflow) echo import >> "$CALLS" ;;
    publish:workflow) echo "publish:${2#--id=}" >> "$CALLS" ;;
    *) return 99 ;;
  esac
}
'''
    environment = {**os.environ, "DB_POSTGRESDB_PASSWORD_FILE": str(password),
                   "N8N_BOOTSTRAP_ENCRYPTION_KEY": "fixture", "EXPORT_DIR": str(exports),
                   "CALLS": str(calls)}
    result = subprocess.run(["/bin/sh", "-ec", n8n_stub + fixture_command],
                            env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == ["credentials", "import", "publish:s1JVSbnvnmHMCbty"]
    assert "Skipping AI workflow migration for xaUDsbylSwaveMQ5" in result.stderr
    assert "Skipping AI workflow migration for Wc0AMPBPqBegSey5" in result.stderr

    for export in exports.iterdir():
        export.unlink()
    calls.unlink()
    result = subprocess.run(["/bin/sh", "-ec", n8n_stub + fixture_command],
                            env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == ["credentials"]
print("n8n AI migration: three targets, inactive preservation, arrays, idempotence and refusal guards passed")
