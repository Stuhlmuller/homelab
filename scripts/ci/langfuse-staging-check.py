#!/usr/bin/env python3
"""Prove Langfuse prerequisites leave caller routing and credentials unchanged."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(ROOT / path)], text=True))


openclaw = yaml("clusters/homelab/apps/openclaw/values.yaml")
litellm = yaml("clusters/homelab/apps/litellm/values.yaml")
controller = openclaw["controllers"]["openclaw"]
for containers in (controller["containers"], controller["initContainers"]):
    assert all("LANGFUSE_OTEL_AUTHORIZATION" not in item.get("env", {}) for item in containers.values())
assert "custom_auth" not in litellm["proxy_config"]["general_settings"]
assert not {"langfuse_otel", "/etc/litellm-hooks/app_identity.langfuse"}.intersection(
    litellm["proxy_config"].get("litellm_settings", {}).get("callbacks", [])
)
assert "LANGFUSE_" not in (ROOT / "clusters/homelab/apps/litellm/externalsecret.yaml").read_text()
assert "langfuse" not in (ROOT / "clusters/homelab/apps/openclaw/externalsecret.yaml").read_text()
config_path = "clusters/homelab/apps/openclaw/assistant/config.json"
config = json.loads((ROOT / config_path).read_text())
assert "diagnostics-otel" not in config["plugins"]["entries"]
assert not config.get("diagnostics", {}).get("otel", {}).get("enabled", False)
ssm = (ROOT / "IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl").read_text()
existing = ssm.split('"/homelab/openclaw/litellm-token" = {', 1)[1].split("initial_value", 1)[0]
assert 'source_parameter = "/homelab/litellm/master-key"' in existing
assert '"/homelab/openclaw/litellm-app-token" = {' in ssm

# A pre-call hook cannot safely enforce the pinned SDK's callback boundary.
# Keep the incomplete implementation out of this prerequisites-only change.
assert not (ROOT / "clusters/homelab/apps/litellm/app_identity.py").exists()
assert not (ROOT / "docs/examples/langfuse/activate-callers.patch").exists()
assert "litellm-app-identity" not in (ROOT / "clusters/homelab/apps/litellm/kustomization.yaml").read_text()
print("Langfuse staging: caller runtime/credentials unchanged; activation implementation deferred")
