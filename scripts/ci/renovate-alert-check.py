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
resources = json.loads(subprocess.check_output([
    "yq", "-o=json", ".resources", str(rule.with_name("kustomization.yaml"))
]))
if "renovate-prometheusrules.yaml" not in resources:
    raise SystemExit("Renovate alert rules are absent from the Prometheus Kustomization")


def metric(name, values):
    return {"series": f'{name}{{job="kube-state-metrics",namespace="automation",cronjob="renovate"}}', "values": values}


def case(name, schedule=None, suspended=False, at="82m", fires=True, suspend_values=None):
    series = [
        metric("kube_cronjob_created", "60x319"),
        metric("kube_cronjob_spec_suspend", suspend_values or f"{int(suspended)}x319"),
    ]
    if schedule is not None:
        series.append(metric("kube_cronjob_status_last_schedule_time", f"{schedule}x319"))
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
    case("suspended runner does not alert", suspended=True, at="215m", fires=False),
    case("later slot missed", schedule=3600, at="142m"),
    case("recent run resets freshness", schedule=7200, at="140m", fires=False),
    case("repeated suspension resumed at half hour", suspend_values="1x89 0x29 1x89 0x110", at="215m", fires=False),
    case("first enabled slot missed after repeated suspension", suspend_values="1x89 0x29 1x89 0x110", at="261m"),
    case("resume at hour boundary does not warn early", suspend_values="1x59 0x260", at="95m", fires=False),
    case("first slot missed after boundary resume", suspend_values="1x59 0x260", at="141m"),
    case("old schedule does not warn after maintenance", schedule=3600, suspend_values="0x89 1x119 0x110", at="215m", fires=False),
    case("missed slot after maintenance alerts", schedule=3600, suspend_values="0x89 1x119 0x110", at="261m"),
]


def completion_case(name, jobs=(), fires=True, schedule="3600x199", at="121m"):
    inputs = [
        metric("kube_cronjob_status_last_schedule_time", schedule),
        metric("kube_cronjob_spec_suspend", "0x199"),
    ]
    for job_name, created, succeeded in jobs:
        labels = f'namespace="automation",job_name="{job_name}"'
        inputs.extend([
            {"series": f'homelab_job:current_cronjob_owner:info{{{labels},owner_name="renovate"}}', "values": "1x199"},
            {"series": f'kube_job_created{{job="kube-state-metrics",{labels}}}', "values": f"{created}x199"},
            {"series": f'kube_job_status_succeeded{{job="kube-state-metrics",{labels}}}', "values": succeeded},
        ])
    return {
        "name": name, "interval": "1m", "input_series": inputs,
        "promql_expr_test": [{
            "expr": 'count by (namespace, cronjob) (ALERTS{alertname="RenovateHourlyCycleIncomplete",alertstate="firing"})',
            "eval_time": at,
            "exp_samples": [{"labels": '{namespace="automation",cronjob="renovate"}', "value": 1}] if fires else [],
        }],
    }


tests.extend([
    completion_case("deadline passed before next schedule", schedule="3600x119 7200x79", at="118m"),
    completion_case("next schedule resets previous failure", schedule="3600x119 7200x79", at="121m", fires=False),
    completion_case("second failed cycle alerts", schedule="3600x119 7200x79", at="178m"),
    completion_case("successful schedule clears deadline", jobs=[("renovate-current", 3600, "1x199")], fires=False),
    completion_case("late old success cannot clear new failure", schedule="3600x119 7200x79", at="178m", jobs=[
        ("renovate-old", 4500, "0x121 1x77"),
        ("renovate-new", 7205, "0x199"),
    ]),
    completion_case("new successful Job clears its cycle", schedule="3600x119 7200x79", at="178m", jobs=[
        ("renovate-old", 4500, "0x121 1x77"),
        ("renovate-new", 7205, "0x130 1x68"),
    ], fires=False),
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
