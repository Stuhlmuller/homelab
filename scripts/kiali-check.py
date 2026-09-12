#!/usr/bin/env python3
"""Read-only checks for Kiali config visibility and live Istio traffic."""

import json
import subprocess
import sys
from urllib.parse import urlencode


def api(service, path):
    return json.loads(subprocess.check_output([
        "kubectl", "--request-timeout=30s", "get", "--raw",
        f"/api/v1/namespaces/monitoring/services/http:{service}/proxy/api/{path}",
    ], text=True))


def main():
    failures = []

    def check(ok, message):
        print(f"{'PASS' if ok else 'FAIL'}: {message}")
        if not ok:
            failures.append(message)

    kiali = "kiali:20001"
    config = api(kiali, "config")
    prom = config["prometheus"]
    check(prom.get("enabled") and not prom.get("disabledReason"),
          "Kiali metrics enabled: " + (prom.get("disabledReason") or "no startup failure"))
    check(config.get("clusterWideAccess"), "Kiali cluster-wide discovery")
    namespaces = api(kiali, "namespaces")
    names = [ns["name"] for ns in namespaces]
    check("istio-system" in names and "monitoring" in names,
          f"Kiali lists {len(names)} namespaces including Istio and monitoring")
    resources = api(kiali, "namespaces/istio-system/istio")
    count = sum(len(items) for items in resources.get("resources", {}).values())
    check(count > 0, f"Istio configuration API returns {count} objects in istio-system")
    query = urlencode({"query": 'count({__name__=~"istio_.*"})'})
    metrics = api("prometheus-kube-prometheus-prometheus:9090", "v1/query?" + query)
    check(metrics.get("status") == "success" and bool(metrics.get("data", {}).get("result")),
          "Prometheus contains Istio telemetry")
    query = urlencode({"namespaces": ",".join(names), "duration": "600s",
                       "graphType": "workload", "includeIdleEdges": "true"})
    graph = api(kiali, "namespaces/graph?" + query)
    elements = graph.get("elements", {})
    nodes, edges = elements.get("nodes", []), elements.get("edges", [])
    check(bool(nodes) and bool(edges),
          f"Traffic graph: {len(nodes)} nodes, {len(edges)} connections in last 10m")
    return bool(failures)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, ValueError, KeyError) as error:
        print(f"FAIL: probe could not complete: {error}", file=sys.stderr)
        sys.exit(1)
