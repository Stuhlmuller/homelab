#!/usr/bin/env python3
"""Exercise the committed memory-capacity rule with synthetic Prometheus data."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "clusters/homelab/apps/prometheus/memory-prometheusrules.yaml"
PROMTOOL = shutil.which("promtool")
if not PROMTOOL:
    raise SystemExit("promtool is required; run this check inside nix develop")

spec = json.loads(subprocess.check_output(["yq", "-o=json", ".spec", str(RULE)]))
values = json.loads(subprocess.check_output(["yq", "-o=json", ".", str(RULE.with_name("values.yaml"))]))
resources = json.loads(subprocess.check_output(["yq", "-o=json", ".resources", str(RULE.with_name("kustomization.yaml"))]))
assert values["defaultRules"]["disabled"]["KubeMemoryOvercommit"] is True
assert resources.count(RULE.name) == 1
rules = [rule for group in spec["groups"] for rule in group["rules"]]
assert len(rules) == 1 and rules[0]["alert"] == "KubeMemoryOvercommit"
assert rules[0]["for"] == "10m" and rules[0]["labels"]["severity"] == "warning"

GIB = 1024**3
CAPACITY = round(30.4022 * GIB)
tests = []


def fixture(requests, capacity=CAPACITY, cluster=None):
    label = f",cluster={json.dumps(cluster)}" if cluster is not None else ""
    return [
        {"series": f'namespace_memory:kube_pod_container_resource_requests:sum{{namespace="apps"{label}}}', "values": requests},
        {"series": f'kube_node_status_allocatable{{job="kube-state-metrics",resource="memory",node="large"{label}}}', "values": f"{capacity // 2}x20"},
        {"series": f'kube_node_status_allocatable{{job="kube-state-metrics",resource="memory",node="small"{label}}}', "values": f"{capacity - capacity // 2}x20"},
    ]


def case(name, inputs, expected=(), at="10m"):
    tests.append({
        "name": name, "interval": "1m", "input_series": inputs,
        "promql_expr_test": [{
            "expr": 'count by (cluster) (ALERTS{alertname="KubeMemoryOvercommit",alertstate="firing"})',
            "eval_time": at,
            "exp_samples": [{"labels": "{}" if cluster is None else f'{{cluster={json.dumps(cluster)}}}', "value": 1} for cluster in expected],
        }],
    })


case("current requests fit without largest-node reserve", fixture(f"{round(22.8623 * GIB)}x20"))
case("post-suspension requests fit", fixture(f"{round(19.3623 * GIB)}x20"))
case("exact capacity does not alert", fixture(f"{CAPACITY}x20"))
overflow = fixture(f"{CAPACITY + GIB}x20")
case("overflow waits ten minutes", overflow, at="9m")
case("overflow fires after ten minutes", overflow, [None])
case("recovery clears a firing alert", fixture(f"{CAPACITY + GIB}x10 {CAPACITY}x10"), at="11m")
case("other cluster headroom cannot hide overflow", fixture("150x20", 100, "over") + fixture("50x20", 1000, "under"), ["over"])

with tempfile.TemporaryDirectory(prefix="homelab-memory-rules-") as directory:
    rule_file = Path(directory) / "rules.json"
    rule_file.write_text(json.dumps(spec))
    test_file = Path(directory) / "tests.json"
    test_file.write_text(json.dumps({"rule_files": [str(rule_file)], "evaluation_interval": "1m", "tests": tests}))
    subprocess.run([PROMTOOL, "check", "rules", str(rule_file)], check=True)
    subprocess.run([PROMTOOL, "test", "rules", str(test_file)], check=True)
print(f"Memory overcommit: {len(tests)} capacity/timing/isolation scenarios passed")
