#!/usr/bin/env python3
"""Prove caller staging is inert and exercise the pending activation in scratch."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "docs/examples/langfuse/activate-callers.patch"


def yaml(path):
    return json.loads(subprocess.check_output(["yq", "-o=json", ".", str(ROOT / path)], text=True))


openclaw = yaml("clusters/homelab/apps/openclaw/values.yaml")
litellm = yaml("clusters/homelab/apps/litellm/values.yaml")
controller = openclaw["controllers"]["openclaw"]
for containers in (controller["containers"], controller["initContainers"]):
    assert all("LANGFUSE_OTEL_AUTHORIZATION" not in item.get("env", {}) for item in containers.values())
assert "custom_auth" not in litellm["proxy_config"]["general_settings"]
assert "langfuse_otel" not in litellm["proxy_config"].get("litellm_settings", {}).get("callbacks", [])
assert "LANGFUSE_" not in (ROOT / "clusters/homelab/apps/litellm/externalsecret.yaml").read_text()
config_path = "clusters/homelab/apps/openclaw/assistant/config.json"
config = json.loads((ROOT / config_path).read_text())
assert "diagnostics-otel" not in config["plugins"]["entries"]
assert not config.get("diagnostics", {}).get("otel", {}).get("enabled", False)
ssm = (ROOT / "IaC/.catalog/units/live/aws-ssm-parameters/terragrunt.hcl").read_text()
existing = ssm.split('"/homelab/openclaw/litellm-token" = {', 1)[1].split("initial_value", 1)[0]
assert 'source_parameter = "/homelab/litellm/master-key"' in existing
assert '"/homelab/openclaw/litellm-app-token" = {' in ssm

with tempfile.TemporaryDirectory() as directory:
    scratch = Path(directory)
    for name in ("openclaw", "litellm"):
        path = Path("clusters/homelab/apps") / name
        shutil.copytree(ROOT / path, scratch / path, ignore=shutil.ignore_patterns("__pycache__"))
    paths = [line.removeprefix("+++ b/") for line in PATCH.read_text().splitlines() if line.startswith("+++ b/")]
    for name in paths:
        path = Path(name)
        assert not path.is_absolute() and ".." not in path.parts
        (scratch / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, scratch / path)
    subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=scratch, check=True)
    subprocess.run(["git", "apply", str(PATCH)], cwd=scratch, check=True)
    activated = json.loads((scratch / config_path).read_text())
    assert activated["models"] == config["models"], "Activation must preserve provider/model contracts"
    assert activated["agents"] == config["agents"], "Activation must preserve agent execution settings"
    for name in ("openclaw-config-check.py", "openclaw-assistant-check.py"):
        subprocess.run([sys.executable, f"scripts/ci/{name}"], cwd=scratch, check=True)
print("Langfuse staging: existing caller credentials preserved; pending activation applies and passes fixtures")
