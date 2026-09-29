#!/usr/bin/env python3
"""Prove Multica activation leaves OpenClaw routing and credentials unchanged."""
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
assert "langfuse" not in (ROOT / "clusters/homelab/apps/openclaw/externalsecret.yaml").read_text()
config_path = "clusters/homelab/apps/openclaw/assistant/config.json"
config = json.loads((ROOT / config_path).read_text())
assert "diagnostics-otel" not in config["plugins"]["entries"]
assert not config.get("diagnostics", {}).get("otel", {}).get("enabled", False)
ssm = (ROOT / "IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl").read_text()
existing = ssm.split('"/homelab/openclaw/litellm-token" = {', 1)[1].split("initial_value", 1)[0]
assert 'source_parameter = "/homelab/litellm/master-key"' in existing
assert '"/homelab/openclaw/litellm-app-token" = {' in ssm

print("Unmigrated OpenClaw routing and credentials preserved")
