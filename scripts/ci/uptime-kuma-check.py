#!/usr/bin/env python3
"""Validate exhaustive, explicitly classified Kuma coverage and health predicates."""

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "clusters/homelab/apps/uptime-kuma/monitors.json"
PROMETHEUS = "http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090/api/v1/query"
JSON_PATH = '(status = "success" and $count(data.result) = 1 and data.result[0].value[1] = "1") ? "1" : "0"'
KEY = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
APP_FIELDS = {"id", "lifecycle", "source", "reason", "monitorIds"}
MONITOR_FIELDS = {
    "key",
    "name",
    "ownerAppIds",
    "kind",
    "target",
    "expected",
    "intervalSeconds",
    "timeoutSeconds",
    "retries",
    "enabled",
    "meaning",
    "limitations",
    "sourceSignals",
    "workloads",
    "schedule",
    "successAgeSeconds",
}


def selector(signal):
    labels = ",".join(f"{k}={json.dumps(v)}" for k, v in sorted(signal["labels"].items()))
    return signal["metric"] + "{" + labels + "}"


def metric_signal(metric, namespace, kind, name, period=30, source="IaC/homelab/us-west-2/apps/prometheus/stack.hcl"):
    return dict(
        metric=metric,
        labels={"namespace": namespace, kind: name},
        periodSeconds=period,
        maxAgeSeconds=period * 2,
        cadenceSource=source,
    )


def signals_for(workloads):
    signals = []
    for w in workloads:
        kind = w["kind"]
        prefix = "kube_" + kind + "_"
        suffixes = {
            "deployment": [
                "spec_replicas",
                "status_replicas_available",
                "metadata_generation",
                "status_observed_generation",
            ],
            "statefulset": ["replicas", "status_replicas_ready", "status_replicas_updated"],
            "daemonset": ["status_desired_number_scheduled", "status_number_ready", "status_updated_number_scheduled"],
            "cronjob": ["spec_suspend", "status_last_successful_time"],
        }[kind]
        signals.extend(metric_signal(prefix + s, w["namespace"], kind, w["name"]) for s in suffixes)
    return signals


def health_query(signals, workloads=None, success_age=None):
    """A scalar count guards duplicates; every raw source timestamp is checked."""
    parts = []
    for s in signals:
        v = selector(s)
        parts += [
            f"(scalar(count({v})) == bool 1)",
            f"(time() - scalar(timestamp({v})) <= bool {s['maxAgeSeconds']})",
            f"(time() - scalar(timestamp({v})) >= bool 0)",
        ]
    index = 0
    for w in workloads or []:
        count = {"deployment": 4, "statefulset": 3, "daemonset": 3, "cronjob": 2}[w["kind"]]
        vals = [f"scalar({selector(s)})" for s in signals[index : index + count]]
        if w["kind"] == "cronjob":
            parts += [f"({vals[0]} == bool 0)", f"({vals[1]} > bool 0)", f"(time() - {vals[1]} <= bool {success_age})"]
        else:
            parts += [f"({vals[0]} > bool 0)", f"({vals[1]} >= bool {vals[0]})"]
            if w["kind"] == "deployment":
                parts += [f"({vals[3]} >= bool {vals[2]})"]
            else:
                parts += [f"({vals[2]} >= bool {vals[0]})"]
        index += count
    for s in signals[index:]:
        parts.append(f"(scalar({selector(s)}) == bool 1)")
    return "vector(" + " * ".join(parts) + ")"


def validate(catalog, root=ROOT, live_names=()):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(
        set(catalog) == {"schemaVersion", "apps", "monitors"} and catalog["schemaVersion"] == 1,
        "invalid catalog schema",
    )
    apps = catalog["apps"]
    monitors = catalog["monitors"]
    require(isinstance(apps, list) and isinstance(monitors, list), "arrays required")
    appmap = {}
    monmap = {}
    evidenced_retirements = set()
    for app in apps:
        require(set(app) == APP_FIELDS, "unknown/missing app fields")
        require(isinstance(app["id"], str) and KEY.fullmatch(app["id"]), "invalid app id")
        require(app["id"] not in appmap, "duplicate app id")
        appmap[app["id"]] = app
        require(
            app["lifecycle"] in {"active", "staged", "suspended", "retired", "configuration-only"}, "invalid lifecycle"
        )
        require(isinstance(app["reason"], str) and len(app["reason"]) >= 20, "lifecycle justification required")
        path = root / app["source"]
        require(path.is_file() and path.resolve().is_relative_to(root.resolve()), "missing/unsafe source")
        retired = app["lifecycle"] == "retired"
        evidence = path.read_text() if retired else ""
        retirement_marker = f"<!-- uptime-kuma-retired: {app['id']} -->"
        # Preserve the existing recorded fixture disposition; new retirements
        # use an explicit identity-bound declaration in durable owning source.
        retired_fixture = f"fixture/{app['id']}" in evidence and "classified retired fixture" in evidence
        has_retirement_evidence = retired and (retirement_marker in evidence or retired_fixture)
        if retired:
            require(
                has_retirement_evidence and "retired" in app["reason"].lower(),
                "retirement lacks owning evidence",
            )
            evidenced_retirements.add(app["id"])
        special_sources = {
            "platform-network-policy-canary": "clusters/homelab/platform/network-policy/canary/kustomization.yaml",
            "live": "specs/20261116-210437-uptime-kuma/catalog-evidence.md",
            "argocd-self-management": "clusters/homelab/argocd/self-management/application.yaml",
            "cordium-bootstrap": "clusters/homelab/apps/cordium/cordium-bootstrap-application.yaml",
            "cordium-local-path-provisioner": "clusters/homelab/platform/storage/cordium-local-path-provisioner-application.yaml",
            "nfs-subdir-external-provisioner": "clusters/homelab/platform/storage/nfs-subdir-external-provisioner-application.yaml",
        }
        require(
            has_retirement_evidence
            or app["source"] == special_sources.get(app["id"])
            or any(
                app["source"].startswith(prefix)
                for prefix in [
                    "IaC/homelab/us-west-2/apps/" + app["id"] + "/",
                    "clusters/homelab/apps/" + app["id"] + "/",
                    "clusters/homelab/platform/" + app["id"].removeprefix("platform-") + "/",
                ]
            ),
            "source does not own app",
        )
        require(
            isinstance(app["monitorIds"], list) and len(set(app["monitorIds"])) == len(app["monitorIds"]),
            "invalid monitor links",
        )
        if app["lifecycle"] in {"staged", "suspended", "retired"}:
            require(
                any(
                    word in app["reason"].lower()
                    for word in ["disabled", "zero", "paused", "retired", "dormant", "standby", "empty"]
                ),
                "unjustified exclusion",
            )
        else:
            require(bool(app["monitorIds"]), "missing app coverage")
        if app["lifecycle"] in {"staged", "suspended"}:
            evidence = path.read_text()
            pattern = (
                r'(?:replicas|replicaCount):\s*0|value\s*=\s*"0"'
                if app["lifecycle"] == "suspended"
                else r"enabled\s*[=:]\s*false|resources:\s*\[\]"
            )
            require(bool(re.search(pattern, evidence)), "exclusion lacks disabled/zero/empty source evidence")
    source_ids = {p.parent.name for p in (root / "IaC/homelab/us-west-2/apps").glob("*/stack.hcl")}
    baseline_path = root / "specs/20261116-210437-uptime-kuma/inventory-evidence.md"
    baseline = (
        set(re.findall(r"^\| ([a-z][a-z0-9-]+) \|", baseline_path.read_text(), re.M))
        if baseline_path.exists()
        else set()
    )
    require(source_ids.union(live_names).issubset(appmap), "unclassified source/live application")
    require(
        set(appmap).issubset(source_ids.union(live_names, baseline, evidenced_retirements, {"uptime-kuma"})),
        "unknown application id",
    )
    for m in monitors:
        require(set(m).issubset(MONITOR_FIELDS), "unknown monitor fields")
        require(KEY.fullmatch(m["key"]) and m["key"] not in monmap, "duplicate/invalid monitor key")
        monmap[m["key"]] = m
        require(type(m["enabled"]) is bool, "enabled must be boolean")
        require(m["kind"] in {"http", "json-query"}, "unsupported monitor kind")
        require(
            m["intervalSeconds"] == 60 and m["timeoutSeconds"] == 10 and m["retries"] == 1, "invalid monitor timing"
        )
        require(bool(m["meaning"]) and bool(m["limitations"]), "health meaning and limits required")
        require(
            set(m["target"]) == ({"url"} if m["kind"] == "http" else {"url", "method", "body", "headers"}),
            "unsafe target fields",
        )
        url = urlsplit(m["target"]["url"])
        require(url.scheme == "http" and not url.username and not url.password and not url.fragment, "unsafe target")
        require(
            url.hostname == "127.0.0.1" or bool(re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.svc", url.hostname or "")),
            "target must be explicit cluster service",
        )
        require(m["expected"]["statusCodes"] == [200], "redirect/auth response cannot prove health")
        require(m["ownerAppIds"] and len(set(m["ownerAppIds"])) == len(m["ownerAppIds"]), "invalid monitor owners")
        for owner in m["ownerAppIds"]:
            require(owner in appmap and m["key"] in appmap[owner]["monitorIds"], "invalid ownership link")
        active_owners = [
            owner for owner in m["ownerAppIds"] if appmap[owner]["lifecycle"] in {"active", "configuration-only"}
        ]
        require(not m["enabled"] or active_owners, "inactive-only monitor must be disabled")
        require(
            len(m["ownerAppIds"]) == 1 or not active_owners or m["enabled"],
            "shared monitor with active owner must remain enabled",
        )
        if m["kind"] == "json-query":
            require(
                m["expected"] == {"statusCodes": [200], "jsonPath": JSON_PATH, "value": "1"},
                "unsafe JSON success predicate",
            )
            require(m.get("sourceSignals"), "source observation evidence required")
            for s in m["sourceSignals"]:
                require(
                    set(s) == {"metric", "labels", "periodSeconds", "maxAgeSeconds", "cadenceSource"},
                    "invalid source signal",
                )
                require(re.fullmatch(r"[a-z_][a-z0-9_]*", s["metric"]), "invalid metric")
                require(
                    s["labels"]
                    and all(
                        re.fullmatch(r"[a-z_][a-z0-9_]*", k) and isinstance(v, str) and re.fullmatch(r"[a-z0-9-]+", v)
                        for k, v in s["labels"].items()
                    ),
                    "unsafe/broad metric selector",
                )
                require(
                    type(s["periodSeconds"]) is int
                    and s["periodSeconds"] > 0
                    and s["maxAgeSeconds"] == 2 * s["periodSeconds"],
                    "freshness must equal two source periods",
                )
                cadence_path = root / s["cadenceSource"]
                require(
                    cadence_path.is_file() and cadence_path.resolve().is_relative_to(root.resolve()),
                    "missing/unsafe cadence evidence",
                )
                if not m.get("workloads"):
                    intervals = re.findall(r"^\s*interval:\s*([1-9][0-9]*)s\s*$", cadence_path.read_text(), re.M)
                    require(
                        intervals == [str(s["periodSeconds"])], "source cadence differs from committed scrape interval"
                    )
            if m.get("workloads"):
                require(m["sourceSignals"] == signals_for(m["workloads"]), "workload source cadence/identity changed")
            if any(w["kind"] == "cronjob" for w in m.get("workloads", [])):
                require(
                    m.get("schedule") == "0 * * * *" and m.get("successAgeSeconds") == 7200,
                    "scheduled success contract required",
                )
            query = health_query(m["sourceSignals"], m.get("workloads"), m.get("successAgeSeconds"))
            require(
                m["target"]["method"] == "POST"
                and m["target"]["headers"] == {"Content-Type": "application/x-www-form-urlencoded"},
                "unsafe query request",
            )
            require(
                url.geturl() == PROMETHEUS and parse_qs(m["target"]["body"]) == {"query": [query]},
                "unsafe health/freshness query",
            )
        else:
            require(set(m["expected"]) == {"statusCodes"} and not url.query, "unsafe HTTP expectation/target")
    for app in apps:
        for key in app["monitorIds"]:
            require(
                key in monmap and app["id"] in monmap[key]["ownerAppIds"],
                "missing reciprocal coverage",
            )
        if app["lifecycle"] in {"active", "configuration-only"}:
            require(
                any(monmap[key]["enabled"] for key in app["monitorIds"]),
                "active app lacks enabled meaningful coverage",
            )
    return len(apps), len(monitors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument(
        "--live-applications", type=Path, help="Read-only kubectl Applications JSON for live/source union acceptance"
    )
    args = parser.parse_args()
    live = []
    if args.live_applications:
        live = [x["metadata"]["name"] for x in json.loads(args.live_applications.read_text())["items"]]
    try:
        counts = validate(json.loads(args.catalog.read_text()), live_names=live)
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Kuma catalog invalid: {error}") from error
    print(f"Kuma catalog: {counts[0]} classified apps, {counts[1]} monitors")


if __name__ == "__main__":
    main()
