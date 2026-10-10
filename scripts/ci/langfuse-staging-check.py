#!/usr/bin/env python3
"""Validate static prerequisites for guarded LiteLLM Langfuse attribution."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(ROOT / path)], text=True))


litellm = yaml("clusters/homelab/apps/litellm/values.yaml")
settings = litellm["proxy_config"]["general_settings"]
assert "custom_auth" not in settings, "Custom auth bypasses native database revocation"
assert (ROOT / "clusters/homelab/apps/litellm/native_keys.py").exists()
assert litellm["proxy_config"]["litellm_settings"]["callbacks"] == [
    "/etc/litellm-hooks/app_identity.attribution",
    "/etc/litellm-hooks/app_identity.langfuse",
]
assert [item["model_name"] for item in litellm["proxy_config"]["model_list"]] == ["openrouter/free"]
assert (ROOT / "clusters/homelab/apps/litellm/app_identity.py").exists()
assert (ROOT / "clusters/homelab/apps/litellm/gateway.py").exists()
secret = (ROOT / "clusters/homelab/apps/litellm/externalsecret.yaml").read_text()
assert "litellm-telemetry" in secret
assert "/homelab/litellm/openai-api-key" in secret
print("Langfuse gateway activation contract is present")
