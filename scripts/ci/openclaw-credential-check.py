#!/usr/bin/env python3
"""Regression-test the actual static-gate credential contracts with local fixtures."""
import copy
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (ROOT / "scripts/ci/static-checks.sh").read_text()
APP = ROOT / "clusters/homelab/apps/openclaw"


def output(*command):
    return json.loads(subprocess.check_output(command, cwd=ROOT, text=True))


def policy(marker):
    # Exercise the same jq expressions used by the gate, not parallel test policies.
    section = CHECKS.split(marker, 1)[1]
    return section.split("jq -e '", 1)[1].split("' >/dev/null", 1)[0]


count = 0


def verify(expression, document, accepted):
    global count
    result = subprocess.run(["jq", "-e", expression], input=json.dumps(document),
                            capture_output=True, text=True, timeout=30)
    if (result.returncode == 0) is not accepted:
        raise RuntimeError("Credential policy regression")
    count += 1


values = output("yq", "-o=json", ".", str(APP / "values.yaml"))
values_policy = policy("yq -o=json '.' \"$openclaw_values\" |")
verify(values_policy, values, True)
# PR #969 may land in either order; its security contexts remain compatible.
hardened = copy.deepcopy(values)
controller = hardened["controllers"]["openclaw"]
controller["pod"]["securityContext"] = {"seccompProfile": {"type": "RuntimeDefault"}}
for container in [controller["containers"]["app"], controller["containers"]["proxy"],
                  controller["initContainers"]["bootstrap-config"]]:
    container["securityContext"] = {"runAsUser": 1000, "runAsGroup": 1000,
        "runAsNonRoot": True, "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]}}
verify(values_policy, hardened, True)
for name in ["app", "proxy", "bootstrap-config", "00-operator-toolbox"]:
    changed = copy.deepcopy(values)
    controller = changed["controllers"]["openclaw"]
    container = (controller["containers"] if name in controller["containers"] else controller["initContainers"])[name]
    container.setdefault("env", {})["GITHUB_APP_ID"] = "fixture-app-id"
    verify(values_policy, changed, False)
for surface in ["envFrom", "volumeMounts"]:
    changed = copy.deepcopy(values)
    changed["controllers"]["openclaw"]["containers"]["app"][surface] = [{"name": "unreviewed-secret"}]
    verify(values_policy, changed, False)
changed = copy.deepcopy(values)
changed["persistence"]["renamed-credential"] = {"enabled": True, "type": "secret", "name": "openclaw-github-app-private-key"}
verify(values_policy, changed, False)
changed = copy.deepcopy(values)
changed["controllers"]["openclaw"]["pod"]["volumes"] = [{"name": "key", "secret": {"secretName": "openclaw-github-app-private-key"}}]
verify(values_policy, changed, False)
changed = copy.deepcopy(values)
changed["controllers"]["openclaw"]["containers"]["app"]["env"]["GRAFANA_USERNAME"] = {
    "valueFrom": {"secretKeyRef": {"name": "openclaw-secrets", "key": "GITHUB_APP_ID"}}}
verify(values_policy, changed, False)

external = output("yq", "ea", "-o=json", "[.]", str(APP / "externalsecret.yaml"))
external_policy = policy("yq ea -o=json -I=0 '[.]' \"$openclaw_external_secret\" |")
verify(external_policy, external, True)
changed = copy.deepcopy(external)
changed.append({"kind": "ExternalSecret", "metadata": {"name": "openclaw-github-app-private-key"}})
verify(external_policy, changed, False)
changed = copy.deepcopy(external)
changed[0]["spec"]["data"][0]["remoteRef"]["key"] = "/homelab/openclaw/github-app/private-key"
verify(external_policy, changed, False)
changed = copy.deepcopy(external)
changed[0]["spec"]["data"].append({"secretKey": "GITHUB_APP_ID", "remoteRef": {"key": "/homelab/openclaw/github-app/id"}})
verify(external_policy, changed, False)

parameters = output("terragrunt", "--log-disable", "--working-dir", "IaC/live/aws-ssm-parameters",
                    "render", "--json", "--write=false", "--no-color")
parameters_policy = policy("terragrunt --log-disable --working-dir IaC/live/aws-ssm-parameters")
verify(parameters_policy, parameters, True)
for suffix in ["id", "installation-id", "private-key"]:
    path = f"/homelab/openclaw/github-app/{suffix}"
    changed = copy.deepcopy(parameters)
    changed["inputs"]["parameters"][path]["reader_access"] = True
    verify(parameters_policy, changed, False)
changed = copy.deepcopy(parameters)
changed["inputs"]["additional_parameter_reader_names"].append("/homelab/openclaw/github-app/private-key")
verify(parameters_policy, changed, False)
print(f"OpenClaw credential containment: {count} actual-policy baseline and reintroduction checks passed")
