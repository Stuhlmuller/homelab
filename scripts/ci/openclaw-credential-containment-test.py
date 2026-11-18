#!/usr/bin/env python3
"""Reject reintroducing broad GitHub credentials to the legacy OpenClaw Pod."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/openclaw"
ALLOWED_SECRET_KEYS = {
    "APP_SECRET", "LITELLM_TOKEN", "DISCORD_BOT_TOKEN", "GRAFANA_USERNAME",
    "GRAFANA_PASSWORD", "GRAFANA_ALERT_HOOK_TOKEN",
}


def contained(values, external_secrets):
    if len(external_secrets) != 1:
        return False
    secret = external_secrets[0]
    if secret.get("kind") != "ExternalSecret" or secret.get("metadata", {}).get("name") != "openclaw-secrets":
        return False
    data = secret.get("spec", {}).get("data", [])
    if {item.get("secretKey") for item in data} != ALLOWED_SECRET_KEYS:
        return False
    if any("github-app" in item.get("remoteRef", {}).get("key", "").lower() for item in data):
        return False

    controller = values.get("controllers", {}).get("openclaw", {})
    if "openclaw-github-app-credentials-ssm-version" in str(controller.get("pod", {}).get("annotations", {})):
        return False
    for container in (*controller.get("containers", {}).values(), *controller.get("initContainers", {}).values()):
        env = container.get("env", {})
        if "envFrom" in container or any(key.startswith("GITHUB_") or key.startswith("GH_") for key in env):
            return False
        if any("github-app" in str(value).lower() for value in env.values()):
            return False
    if any("github-app" in name.lower() or "github-app" in str(volume).lower()
           for name, volume in values.get("persistence", {}).items()):
        return False
    return True


class ContainmentTest(unittest.TestCase):
    def setUp(self):
        self.values = json.loads(subprocess.run(
            ["yq", "eval", "-o=json", "-I=0", ".", str(APP / "values.yaml")],
            check=True, capture_output=True, text=True).stdout)
        self.secrets = json.loads(subprocess.run(
            ["yq", "eval-all", "-o=json", "-I=0", "[.]", str(APP / "externalsecret.yaml")],
            check=True, capture_output=True, text=True).stdout)

    def test_current_contract(self):
        self.assertTrue(contained(self.values, self.secrets))

    def test_rejects_alternate_credential_surfaces(self):
        mutations = (
            lambda v, s: v["controllers"]["openclaw"]["containers"]["app"]["env"].update(
                GITHUB_APP_ID={"valueFrom": {"secretKeyRef": {"name": "other-secret", "key": "id"}}}),
            lambda v, s: v["controllers"]["openclaw"]["containers"]["app"].update(
                envFrom=[{"secretRef": {"name": "other-secret"}}]),
            lambda v, s: v["persistence"].update(
                renamed_key={"type": "secret", "name": "openclaw-github-app-private-key"}),
            lambda v, s: s.append(deepcopy(s[0])),
            lambda v, s: s[0]["spec"]["data"][0]["remoteRef"].update(
                key="/homelab/openclaw/github-app/id"),
        )
        for mutate in mutations:
            values, secrets = deepcopy(self.values), deepcopy(self.secrets)
            mutate(values, secrets)
            with self.subTest(mutation=mutate):
                self.assertFalse(contained(values, secrets))


if __name__ == "__main__":
    unittest.main()
