#!/usr/bin/env python3
"""Render pinned monitoring chart and validate staged storage/heartbeat contracts."""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "clusters/homelab/apps/prometheus"
CANDIDATE = APP / "reliability-candidate"


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True)


def config_fixture():
    secret = yaml.safe_load((CANDIDATE / "heartbeat-externalsecret.yaml").read_text())
    config = secret["spec"]["target"]["template"]["data"]["alertmanager.yaml"]
    # Emulate ESO's escaping without substituting any real secret values.
    config = re.sub(r"{{\s*`(.*?)`\s*}}", lambda m: m[1], config, flags=re.DOTALL)
    return config.replace(
        "{{ .HEARTBEAT_URL }}", "https://heartbeat.invalid/fixture"
    ).replace("{{ .DISCORD_WEBHOOK_URL }}", "https://discord.invalid/fixture")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--chart", default="prometheus-community/kube-prometheus-stack")
    parser.add_argument("--amtool", default="amtool")
    parser.add_argument("--promtool", default="promtool")
    args = parser.parse_args()
    command = [
        args.helm,
        "template",
        "prometheus",
        args.chart,
        "--version",
        "85.2.0",
        "--namespace",
        "monitoring",
        "-f",
        APP / "values.yaml",
    ]
    rendered = run(
        *command,
        "-f",
        CANDIDATE / "target-prometheus.yaml",
        "-f",
        CANDIDATE / "target-alertmanager.yaml",
        "-f",
        CANDIDATE / "heartbeat-values.yaml",
    )
    resources = [d for d in yaml.safe_load_all(rendered) if d]
    claims = {
        d["metadata"]["name"]: d
        for d in yaml.safe_load_all((CANDIDATE / "storage.yaml").read_text())
        if d["kind"] == "PersistentVolumeClaim"
    }
    for kind, retention, size in [
        ("Prometheus", "15d", "50Gi"),
        ("Alertmanager", "120h", "10Gi"),
    ]:
        resource = next(d for d in resources if d["kind"] == kind)
        spec = resource["spec"]
        assert spec["replicas"] == 0 and spec["paused"] is False
        assert spec["retention"] == retention
        assert spec["persistentVolumeClaimRetentionPolicy"] == {
            "whenDeleted": "Retain",
            "whenScaled": "Retain",
        }
        template = spec["storage"]["volumeClaimTemplate"]
        assert template["spec"]["storageClassName"] == "monitoring-local"
        assert template["spec"]["resources"]["requests"]["storage"] == size
        claim_name = f"{template['metadata']['name']}-{kind.lower()}-{resource['metadata']['name']}-0"
        assert claim_name in claims, claim_name
    rules = [
        r
        for d in resources
        if d["kind"] == "PrometheusRule"
        for g in d["spec"]["groups"]
        for r in g["rules"]
        if r.get("alert") == "Watchdog"
    ]
    assert len(rules) == 1 and rules[0]["expr"] == "vector(1)"
    active = yaml.safe_load((APP / "kustomization.yaml").read_text())
    assert not any("reliability-candidate" in r for r in active["resources"])
    assert (
        "reliability-candidate" not in (ROOT / "IaC/terragrunt.stack.hcl").read_text()
    )
    config = config_fixture()
    parsed = yaml.safe_load(config)
    route = parsed["route"]["routes"][0]
    assert route["repeat_interval"] == route["group_interval"] == "1m"
    receiver = next(
        r for r in parsed["receivers"] if r["name"] == "independent-heartbeat"
    )
    assert receiver["webhook_configs"][0]["send_resolved"] is False
    assert receiver["webhook_configs"][0]["http_config"]["follow_redirects"] is False
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        config_path = folder / "alertmanager.yaml"
        config_path.write_text(config)
        run(args.amtool, "check-config", config_path)
        for label, expected in [
            ("Watchdog", "independent-heartbeat"),
            ("InfoInhibitor", "null"),
            ("SyntheticFailure", "homelab-notifications"),
        ]:
            run(
                args.amtool,
                "config",
                "routes",
                "test",
                "--config.file",
                config_path,
                "--verify.receivers",
                expected,
                f"alertname={label}",
            )
        (folder / "rules.yaml").write_text(
            yaml.safe_dump({"groups": [{"name": "heartbeat", "rules": rules}]})
        )
        (folder / "tests.yaml").write_text(
            yaml.safe_dump(
                {
                    "rule_files": ["rules.yaml"],
                    "evaluation_interval": "1m",
                    "tests": [
                        {
                            "interval": "1m",
                            "input_series": [],
                            "alert_rule_test": [
                                {
                                    "eval_time": "2m",
                                    "alertname": "Watchdog",
                                    "exp_alerts": [
                                        {
                                            "exp_labels": rules[0]["labels"],
                                            "exp_annotations": rules[0]["annotations"],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )
        )
        run(args.promtool, "test", "rules", folder / "tests.yaml")
    print(
        "Pinned chart, claim names, retention, disabled activation, Watchdog and routing passed."
    )


if __name__ == "__main__":
    main()
