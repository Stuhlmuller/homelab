"""Check n8n steady-state startup and its LiteLLM authorization boundary."""
import json
import subprocess

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
assert set(values["controllers"]) == {"n8n"}
print("n8n runtime startup and LiteLLM authorization checks passed")
