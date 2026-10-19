"""Exercise the guarded Codex Review Helper publication decision."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

command = subprocess.check_output([
    "yq", "-r", '.controllers.n8n.initContainers."migrate-ai-workflow".command[2]',
    "clusters/homelab/apps/n8n/values.yaml",
], text=True)
script = command.split("node <<'CODEX'\n", 1)[1].split("\nCODEX", 1)[0]
recorded_digest = re.search(r"if \(digest !== '([0-9a-f]{64})'\)", script)
assert recorded_digest, "reviewed n8n workflow digest missing"
subprocess.run(["sh", "-n"], input=command, text=True, check=True)
assert ('n8n export:workflow --id=6wtwXT4PL5QuSGSD '
        '--output=/tmp/codex-review-workflow.json') in command
assert ('if [ "$(cat /tmp/codex-review-action)" = publish ]; then\n'
        '  n8n publish:workflow --id=6wtwXT4PL5QuSGSD') in command

nodes = [
    {"name": name, "type": kind, "typeVersion": 1, "parameters": {}}
    for name, kind in (
        ("Webhook", "n8n-nodes-base.webhook"),
        ("Filter", "n8n-nodes-base.filter"),
        ("If", "n8n-nodes-base.if"),
        ("Ask Codex for Help", "n8n-nodes-base.github"),
        ("HTTP Request", "n8n-nodes-base.httpRequest"),
        ("Stamp", "n8n-nodes-base.github"),
    )
]
nodes[0]["webhookId"] = "7cd61c45-077f-45e4-aafe-8e06ce68fbc4"
nodes[0]["parameters"] = {"path": nodes[0]["webhookId"], "httpMethod": "POST"}
nodes[1]["parameters"] = {"conditions": {"conditions": [{"left": "status", "right": "ready"}]}}
workflow = {"id": "6wtwXT4PL5QuSGSD", "name": "Codex Review Helper", "isArchived": False,
            "active": False, "activeVersionId": None, "nodes": nodes,
            "connections": {"Webhook": {"main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]}},
            "settings": {"executionOrder": "v1"}}
projected_nodes = [
    {**{key: node[key] for key in ("name", "type", "typeVersion", "webhookId", "parameters", "credentials")
        if key in node}, "disabled": node.get("disabled", False)}
    for node in nodes
]
projected = {"nodes": sorted(projected_nodes, key=lambda node: node["name"]),
             "connections": workflow["connections"], "settings": workflow["settings"]}
fixture_digest = hashlib.sha256(json.dumps(projected, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False).encode()).hexdigest()

with tempfile.TemporaryDirectory() as directory:
    workflow_file = Path(directory) / "workflow.json"
    action_file = Path(directory) / "action"
    source = script.replace(recorded_digest.group(1), fixture_digest).replace(
        "/tmp/codex-review-workflow.json", str(workflow_file)).replace(
            "/tmp/codex-review-action", str(action_file))

    def run(data, expected, error=None):
        action_file.unlink(missing_ok=True)
        workflow_file.write_text(json.dumps(data))
        result = subprocess.run(["node"], input=source, text=True, capture_output=True, timeout=10)
        assert (result.returncode == 0) == (expected is not None), result.stderr
        assert (action_file.read_text() if action_file.exists() else None) == expected
        if error:
            assert error in result.stderr, result.stderr

    run([workflow], "publish")
    published = {**workflow, "active": True, "activeVersionId": "published-version"}
    run([published], "skip")
    for data in ([], [workflow, workflow], {},
                 [{**workflow, "id": "other"}], [{**workflow, "name": "other"}],
                 [{**workflow, "isArchived": True}],
                 [{**workflow, "active": True}],
                 [{**workflow, "activeVersionId": "unexpected"}]):
        run(data, None)
    for change in (lambda w: w["nodes"].pop(),
                   lambda w: w["nodes"].append(copy.deepcopy(w["nodes"][0])),
                   lambda w: w["nodes"][1].update(type="n8n-nodes-base.noOp"),
                   lambda w: w["nodes"][0]["parameters"].update(httpMethod="GET"),
                   lambda w: w["nodes"][0]["parameters"].update(path="other"),
                   lambda w: w["nodes"][0].update(webhookId="other")):
        changed = copy.deepcopy(workflow)
        change(changed)
        run([changed], None)
    for change in (lambda w: w["nodes"][1]["parameters"]["conditions"]["conditions"][0].update(right="blocked"),
                   lambda w: w["connections"]["Webhook"]["main"][0][0].update(node="Stamp"),
                   lambda w: w["nodes"][3].update(credentials={"githubApi": {"id": "changed"}}),
                   lambda w: w["settings"].update(executionOrder="v0")):
        changed = copy.deepcopy(workflow)
        change(changed)
        run([changed], None, "behavior changed")

print("n8n Codex webhook: publication and drift guards passed")
