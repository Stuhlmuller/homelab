#!/usr/bin/env python3
"""Exercise credential validation and the exact public callback boundary."""

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch



def yaml_load(text):
    return json.loads(subprocess.check_output(["yq", "-o=json", "-I=0"], input=text, text=True))


root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("multica_secrets", root / "scripts/multica-github-secrets.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manifest = json.loads((root / "clusters/homelab/apps/multica/github-app-manifest.json").read_text())
assert not manifest["public"]
assert set(manifest["default_permissions"]) == {"metadata", "contents", "pull_requests", "checks", "statuses"}
assert set(manifest["default_permissions"].values()) == {"read"}

with tempfile.TemporaryDirectory() as directory:
    credential = Path(directory) / "credentials.json"
    key = subprocess.check_output(["openssl", "genrsa", "2048"], text=True, stderr=subprocess.DEVNULL)
    data = {"slug": manifest["name"], "id": 123, "pem": key, "webhook_secret": "synthetic-" * 8}
    assert module.values(data)["private-key"] == key
    for field, value in [("slug", "unrelated-app"), ("id", True), ("id", 0), ("pem", "not-a-key"), ("webhook_secret", "short")]:
        try:
            module.values({**data, field: value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid {field}")
    credential.write_text(json.dumps(data))
    credential.chmod(0o600)
    with patch.object(sys, "argv", ["import", str(credential)]):
        module.main()  # Dry run performs no AWS writes.
    for missing in [True, False]:
        def output(command, **kwargs):
            if command[0] == "gh":
                return "reviewed-sha"
            if command[0] == "git":
                return "" if "status" in command else "reviewed-sha"
            return json.dumps({"Parameters": [] if missing else [{"Type": "SecureString", "KeyId": "alias/aws/ssm"}]})
        writes = []
        real_run = subprocess.run
        def run(command, **kwargs):
            if command[0] == "openssl":
                return real_run(command, **kwargs)
            assert command == ["aws", "ssm", "put-parameter", "--region", "us-west-2", "--cli-input-json", "file:///dev/stdin"]
            writes.append(json.loads(kwargs["input"]))
            return subprocess.CompletedProcess(command, 0)
        with patch.object(sys, "argv", ["import", str(credential), "--apply"]), patch.object(subprocess, "check_output", output), patch.object(subprocess, "run", run):
            try:
                module.main()
            except ValueError:
                assert missing
        assert len(writes) == (0 if missing else 4)
        assert all(item["Name"].startswith(module.PREFIX) and item["Type"] == "SecureString" for item in writes)

# Activation is checked when the callbacks are present in the app overlay.
app = root / "clusters/homelab/apps/multica"
if (app / "github-virtualservice.yaml").exists():
    rendered_text = subprocess.check_output(["kubectl", "kustomize", str(app)], text=True)
    rendered = [json.loads(line) for line in subprocess.check_output(
        ["yq", "-o=json", "-I=0"], input=rendered_text, text=True,
    ).splitlines()]
    route = next(obj for obj in rendered if obj.get("metadata", {}).get("name") == "multica-github-callbacks")
    assert route["spec"]["http"][0]["match"] == [
        {"uri": {"exact": "/api/webhooks/github"}, "method": {"exact": "POST"}},
        {"uri": {"exact": "/api/github/setup"}, "method": {"exact": "GET"}},
    ]
    assert len(route["spec"]["http"]) == 1
    config = yaml_load((root / "clusters/homelab/apps/octelium-public/configmap.yaml").read_text())
    rules = yaml_load(config["data"]["config.yaml"])["ingress"]
    selected = [r for r in rules if r.get("hostname") == "multica.stinkyboi.com"]
    assert len(selected) == 2 and "octelium-ingress-dataplane" in selected[1]["service"]
    pattern = selected[0]["path"]
    assert selected[0]["originRequest"]["httpHostHeader"] == route["spec"]["hosts"][0]
    for path in ["/api/webhooks/github", "/api/github/setup"]:
        assert re.search(pattern, path)
    for path in ["/", "/auth", "/ws", "/api/github/connect", "/api/webhooks/github/extra", "/api/github/setup/", "/api/github/setup.evil"]:
        assert not re.search(pattern, path), path
    secret = next(obj for obj in rendered if obj.get("metadata", {}).get("name") == "multica-backend-github-secrets")
    assert set(module.values(data)) == {item["remoteRef"]["key"].removeprefix(module.PREFIX) for item in secret["spec"]["data"] if item["remoteRef"]["key"].startswith(module.PREFIX)}
    assert yaml_load((app / "values.yaml").read_text())["existingSecret"] == secret["spec"]["target"]["name"]

print("Multica GitHub credential and callback checks passed")
