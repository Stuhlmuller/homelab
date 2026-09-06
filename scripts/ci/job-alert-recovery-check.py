#!/usr/bin/env python3
"""Exercise the actual Prometheus rules against ordered Job/CronJob histories."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "clusters/homelab/apps/prometheus/job-prometheusrules.yaml"
PROMTOOL = shutil.which("promtool")
if not PROMTOOL:
    raise SystemExit("promtool is required; run this check inside nix develop")

spec = json.loads(subprocess.check_output(["yq", "-o=json", ".spec", str(RULE)]))
values = json.loads(
    subprocess.check_output(
        ["yq", "-o=json", ".", str(RULE.with_name("values.yaml"))]
    )
)
assert values["defaultRules"]["disabled"]["KubeJobFailed"] is True
assert values["prometheus"]["prometheusSpec"]["retention"] == "15d"
resources = json.loads(
    subprocess.check_output(
        ["yq", "-o=json", ".resources", str(RULE.with_name("kustomization.yaml"))]
    )
)
assert RULE.name in resources
tests = []


def series(metric, value, **labels):
    labels = {"job": "kube-state-metrics", **labels}
    label_text = ",".join(f"{key}={json.dumps(val)}" for key, val in labels.items())
    return {"series": f"{metric}{{{label_text}}}", "values": value}


def fixture(**changes):
    """A Job fails at 5m; its owner succeeds at 15m; evaluate at 30m."""
    job = {"namespace": "apps", "job_name": "backup-old"}
    cronjob = {"namespace": "apps", "cronjob": "backup"}
    inputs = {
        "failure": series("kube_job_failed", "0x4 1x55", condition="true", **job),
        "created": series("kube_job_created", "60x59", **job),
        "active": series("kube_job_status_active", "0x59", **job),
        "owner": series(
            "kube_job_owner",
            "1x59",
            owner_kind="CronJob",
            owner_is_controller="true",
            owner_name="backup",
            **job,
        ),
        "cronjob_created": series("kube_cronjob_created", "30x59", **cronjob),
        "success": series(
            "kube_cronjob_status_last_successful_time", "900x59", **cronjob
        ),
    }
    for key, value in changes.items():
        if value is None:
            del inputs[key]
        elif isinstance(value, str):
            inputs[key]["values"] = value
        else:
            inputs[key] = value
    return list(inputs.values())


def case(name, inputs, expected=(), at="30m"):
    tests.append(
        {
            "name": name,
            "interval": "1m",
            "input_series": inputs,
            "promql_expr_test": [
                {
                    "expr": 'count by (namespace, job_name) (ALERTS{alertname="KubeJobFailed",alertstate="firing"})',
                    "eval_time": at,
                    "exp_samples": [
                        {
                            "labels": '{namespace="%s",job_name="%s"}' % (ns, job),
                            "value": count,
                        }
                        for ns, job, count in expected
                    ],
                }
            ],
        }
    )


OLD = [("apps", "backup-old", 1)]
case("new success clears a retained failed run", fixture())
case("last success predates the failure", fixture(success="240x59"), OLD)
case("overlapping run fails after another succeeds", fixture(failure="0x14 1x44", success="600x59"), OLD)
case("equal failure and success timestamps are not newer", fixture(success="300x59"), OLD)
case("a future success timestamp cannot establish recovery", fixture(success="3600x59"), OLD)
case("zero success timestamp cannot establish recovery", fixture(success="0x59"), OLD)
case("never succeeded CronJob remains alerting", fixture(success=None), OLD)
case("a non-failed Job does not alert", fixture(failure="0x59"))
case("original fifteen minute alert delay is preserved", fixture(success=None), at="10m")
case("the same failure fires after the delay", fixture(success=None), OLD, at="20m")
case("between-boundary failure waits for five-minute detection and hold", fixture(success=None, failure="0x5 1x53"), at="24m")
case("between-boundary failure fires after the unchanged fifteen-minute hold", fixture(success=None, failure="0x5 1x53"), OLD, at="25m")

for missing in ["owner", "created", "active", "cronjob_created"]:
    case(f"missing {missing} preserves failure", fixture(**{missing: None}), OLD)
case("active failed Job is never suppressed", fixture(active="1x59"), OLD)
case("recreated CronJob cannot recover a previous owner's Job", fixture(cronjob_created="1200x59"), OLD)
case("a non-controller owner cannot suppress failure", fixture(owner=series("kube_job_owner", "1x59", namespace="apps", job_name="backup-old", owner_kind="CronJob", owner_is_controller="false", owner_name="backup")), OLD)
case("standalone Job remains alerting", fixture(owner=series("kube_job_owner", "1x59", namespace="apps", job_name="backup-old", owner_kind="", owner_is_controller="", owner_name="")), OLD)
case("success of a different CronJob cannot suppress failure", fixture(success=series("kube_cronjob_status_last_successful_time", "900x59", namespace="apps", cronjob="other")), OLD)
case("success in another namespace cannot suppress failure", fixture(success=series("kube_cronjob_status_last_successful_time", "900x59", namespace="other", cronjob="backup")), OLD)
case("CronJob creation in another namespace cannot prove ownership", fixture(cronjob_created=series("kube_cronjob_created", "30x59", namespace="other", cronjob="backup")), OLD)
case("metrics from another scrape job cannot suppress failure", fixture(success=series("kube_cronjob_status_last_successful_time", "900x59", namespace="apps", cronjob="backup", job="other-exporter")), OLD)
case("conflicting controller owners preserve failure", fixture(extra_owner=series("kube_job_owner", "1x59", namespace="apps", job_name="backup-old", owner_kind="CronJob", owner_is_controller="true", owner_name="other")), OLD)

later = fixture()
later += [
    series("kube_job_failed", "0x19 1x39", namespace="apps", job_name="backup-new", condition="true"),
    series("kube_job_created", "1000x59", namespace="apps", job_name="backup-new"),
    series("kube_job_status_active", "0x59", namespace="apps", job_name="backup-new"),
    series("kube_job_owner", "1x59", namespace="apps", job_name="backup-new", owner_kind="CronJob", owner_is_controller="true", owner_name="backup"),
]
case("later failed run alerts while older failed run stays recovered", later, [("apps", "backup-new", 1)], at="40m")
case("reused Job name excludes a previous incarnation's failure samples", fixture(created="60x19 1200x39", failure="0x4 1x14 0x4 1x34"), OLD, at="45m")
case("failure first observed after success stays alerting", fixture(failure="_x28 1x30"), OLD, at="50m")
case("loss of success metrics restores failure alerting", fixture(success="900x24 stale _x34"), OLD, at="50m")

duplicated = fixture()
duplicated += [
    {"series": item["series"].replace("{", '{instance="second",', 1), "values": item["values"]}
    for item in list(duplicated)
]
case("duplicate scrape targets do not create many-to-many joins", duplicated)

with tempfile.TemporaryDirectory(prefix="homelab-job-rules-") as directory:
    rule_file = Path(directory) / "rules.json"
    rule_file.write_text(json.dumps(spec))
    test_file = Path(directory) / "tests.json"
    test_file.write_text(
        # promtool's suite interval controls evaluation, so use the real group
        # interval instead of silently testing a faster schedule.
        json.dumps({"rule_files": [str(rule_file)], "evaluation_interval": spec["groups"][0]["interval"], "tests": tests})
    )
    subprocess.run([PROMTOOL, "check", "rules", str(rule_file)], check=True)
    subprocess.run([PROMTOOL, "test", "rules", str(test_file)], check=True)
print(f"Job failure recovery: {len(tests)} timestamp/ownership scenarios passed")
