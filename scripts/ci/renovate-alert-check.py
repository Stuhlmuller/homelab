#!/usr/bin/env python3
"""Exercise the deployed Renovate missed-slot rule with real PromQL."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
rule = root / "clusters/homelab/apps/prometheus/renovate-prometheusrules.yaml"
promtool = shutil.which("promtool")
if not promtool:
    raise SystemExit("promtool is required; run inside nix develop")
spec = json.loads(subprocess.check_output(["yq", "-o=json", ".spec", str(rule)]))
assert "renovate-prometheusrules.yaml" in json.loads(subprocess.check_output([
    "yq", "-o=json", ".resources", str(rule.with_name("kustomization.yaml"))
]))


def metric(name, values):
    return {"series": f'{name}{{job="kube-state-metrics",namespace="automation",cronjob="renovate"}}', "values": values}


def case(name, schedule=None, suspended=False, at="82m", fires=True):
    series = [metric("kube_cronjob_created", "60x159"), metric("kube_cronjob_spec_suspend", f"{int(suspended)}x159")]
    if schedule is not None:
        series.append(metric("kube_cronjob_status_last_schedule_time", f"{schedule}x159"))
    return {
        "name": name,
        "interval": "1m",
        "input_series": series,
        "promql_expr_test": [{
            "expr": 'count by (namespace, cronjob) (ALERTS{alertname="RenovateHourlyCycleMissing",alertstate="firing"})',
            "eval_time": at,
            "exp_samples": [{"labels": '{namespace="automation",cronjob="renovate"}', "value": 1}] if fires else [],
        }],
    }


tests = [
    case("first slot missed", at="82m"),
    case("first slot still within grace", at="70m", fires=False),
    case("suspended runner does not alert", suspended=True, fires=False),
    case("later slot missed", schedule=3600, at="142m"),
    case("recent run resets freshness", schedule=7200, at="140m", fires=False),
]


def completion_case(name, success=None, fires=True):
    inputs = [
        metric("kube_cronjob_status_last_schedule_time", "3600x139"),
        metric("kube_cronjob_spec_suspend", "0x139"),
    ]
    if success is not None:
        inputs.append(metric("kube_cronjob_status_last_successful_time", f"{success}x139"))
    return {
        "name": name, "interval": "1m", "input_series": inputs,
        "promql_expr_test": [{
            "expr": 'count by (namespace, cronjob) (ALERTS{alertname="RenovateHourlyCycleIncomplete",alertstate="firing"})',
            "eval_time": "121m",
            "exp_samples": [{"labels": '{namespace="automation",cronjob="renovate"}', "value": 1}] if fires else [],
        }],
    }


tests.extend([
    completion_case("deadline passed without success"),
    completion_case("successful schedule clears deadline", success=3600, fires=False),
    {
        "name": "Argo Application without CronJob", "interval": "1m",
        "input_series": [{"series": 'argocd_app_info{name="renovate",project="homelab-workloads"}', "values": "1x19"}],
        "promql_expr_test": [{
            "expr": 'count by (name) (ALERTS{alertname="RenovateCronJobMissing",alertstate="firing"})',
            "eval_time": "15m",
            "exp_samples": [{"labels": '{name="renovate"}', "value": 1}],
        }],
    },
])
with tempfile.TemporaryDirectory(prefix="renovate-alert-") as directory:
    rule_file = Path(directory) / "rules.json"
    test_file = Path(directory) / "tests.json"
    rule_file.write_text(json.dumps(spec))
    test_file.write_text(json.dumps({"rule_files": [str(rule_file)], "evaluation_interval": "1m", "tests": tests}))
    subprocess.run([promtool, "check", "rules", str(rule_file)], check=True)
    subprocess.run([promtool, "test", "rules", str(test_file)], check=True)
