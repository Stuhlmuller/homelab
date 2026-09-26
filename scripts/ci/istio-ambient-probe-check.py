#!/usr/bin/env python3
"""Check the actual runbook queries against a failure before its first scrape."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
queries = re.findall(r"ambient_promql '([^']+)'", (root / "docs/knowledge-base/operations/validation-gates.md").read_text())
increase = next(query for query in queries if "increase(prober_probe_total" in query)
baseline = next(query for query in queries if "prober_probe_total" in query and "offset 24h" in query)
series = 'prober_probe_total{namespace="istio-system",pod="ztunnel-test",pod_uid="uid",probe_type="Readiness",result="failed"}'
tests = []
for name, values, fails, has_baseline in (
    ("clean", "0x2882", False, True),
    ("failure before first in-window scrape", "0x2 1x2879", True, True),
    ("missing baseline", "_ _ _ 1x2879", False, False),
):
    tests.append({"name": name, "interval": "30s", "input_series": [{"series": series, "values": values}],
                  "promql_expr_test": [
                      {"expr": f"count(({increase}) > 0) or vector(0)", "eval_time": "24h1m",
                       "exp_samples": [{"labels": "{}", "value": int(fails)}]},
                      {"expr": f"count(({baseline}) >= 1) or vector(0)", "eval_time": "24h1m",
                       "exp_samples": [{"labels": "{}", "value": int(has_baseline)}]},
                  ]})
with tempfile.TemporaryDirectory() as directory:
    fixture = Path(directory) / "probe.json"
    fixture.write_text(json.dumps({"evaluation_interval": "30s", "tests": tests}))
    subprocess.run(["promtool", "test", "rules", str(fixture)], check=True)
