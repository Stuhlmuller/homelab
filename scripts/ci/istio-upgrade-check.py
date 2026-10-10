"""Offline HOME-56 validation. Never contacts Kubernetes or promotes a stage."""

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "specs/istio-upgrade"
INSTANCES = {
    "istio-base": ("base", set()),
    "istiod": (
        "istiod",
        {"profile", "replicaCount", "resources", "global", "meshConfig"},
    ),
    "istio-cni": ("cni", {"profile", "ambient", "podAnnotations", "global"}),
    "ztunnel": (
        "ztunnel",
        {"profile", "resources", "env", "podLabels", "updateStrategy"},
    ),
    "istio-ingressgateway": ("gateway", {"service"}),
    "octelium-api-ingressgateway": ("gateway", {"name", "labels", "service"}),
}
EVIDENCE = {
    "artifacts",
    "injection",
    "independent_access",
    "recovery",
    "reconciler_hold",
    "generated_inventory",
    "forward_reverse_rehearsal",
    "signed_revision",
    "eol_bridge_decision",
    "execution_authorization",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_values(values):
    require(set(values) == set(INSTANCES), "exactly six chart instances required")
    for release, (chart, allowed) in INSTANCES.items():
        row = values[release]
        require(set(row) == {"chart", "values"}, f"{release}: unexpected fields")
        require(row["chart"] == chart, f"{release}: chart mismatch")
        require(isinstance(row["values"], dict), f"{release}: values must be a map")
        require(set(row["values"]) == allowed, f"{release}: wrong chart-specific keys")


def validate_hold(plan):
    require(plan["schema_version"] == 1, "unknown design schema")
    require(plan["mode"] == "design-only", "this checker cannot enable execution")
    require(plan["active_version"] == "1.27.3", "active baseline changed")
    require(
        plan["candidate_hops"] == ["1.28.10", "1.29.8", "1.30.5", "1.31.1"],
        "hop review required",
    )
    require(
        plan["stages"] == ["base", "istiod", "cni", "ztunnel", "gateways"],
        "stage order changed",
    )
    require(plan["state"] == "HOLD", "design must remain on HOLD")
    require(plan["executor_implemented"] is False, "no executor exists in this slice")
    require(plan["promotion_authorized"] is False, "no execution authorization")
    require(set(plan["required_evidence"]) == EVIDENCE, "missing/unknown evidence gate")
    for key, row in plan["required_evidence"].items():
        require(bool(row.get("owner")), f"{key}: owner required")
        require(
            row.get("status") == "unresolved" and row.get("receipt") is None,
            f"{key}: evidence acceptance requires a separately reviewed implementation",
        )


def verified_archive(path, row):
    require(
        hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"],
        f"{path.name}: archive digest mismatch",
    )
    with tarfile.open(path) as archive:
        member = archive.getmember(row["chart"] + "/Chart.yaml")
        require(member.isfile(), "chart metadata must be a regular file")
        metadata = yaml.safe_load(archive.extractfile(member))
        require(
            metadata["name"] == row["chart"]
            and metadata["version"] == row["version"]
            and metadata["appVersion"] == row["version"],
            "chart identity mismatch",
        )
        return any(m.name.endswith("/values.schema.json") for m in archive.getmembers())


def one(objects, kind, name):
    found = [
        o
        for o in objects
        if o.get("kind") == kind and o.get("metadata", {}).get("name") == name
    ]
    require(len(found) == 1, f"expected one {kind}/{name}")
    return found[0]


def semantic_check(release, objects):
    """Check effects, not just accepted input; most charts have no values schema."""
    if release == "istio-cni":
        data = one(objects, "ConfigMap", "istio-cni-config")["data"]
        for key, expected in {
            "AMBIENT_ENABLED": "true",
            "AMBIENT_DNS_CAPTURE": "false",
            "AMBIENT_IPV6": "false",
            "AMBIENT_RECONCILE_POD_RULES_ON_STARTUP": "false",
        }.items():
            require(data.get(key) == expected, f"CNI {key} did not take effect")
        ds = one(objects, "DaemonSet", "istio-cni-node")
        require(
            ds["spec"]["template"]["metadata"]["annotations"].get(
                "homelab.rst.io/ambient-ip-family"
            )
            == "ipv4",
            "CNI annotation missing",
        )
    elif release in {"istiod", "ztunnel"}:
        kind = "Deployment" if release == "istiod" else "DaemonSet"
        obj = one(objects, kind, release)
        containers = obj["spec"]["template"]["spec"]["containers"]
        name = "discovery" if release == "istiod" else "istio-proxy"
        container = next(c for c in containers if c["name"] == name)
        memory = "512Mi" if release == "istiod" else "256Mi"
        require(
            container["resources"]["requests"]["memory"] == memory,
            f"{release}: memory request did not take effect",
        )
        if release == "ztunnel":
            env = {e["name"]: e.get("value") for e in container.get("env", [])}
            require(env.get("IPV6_ENABLED") == "false", "ztunnel IPv6 override missing")
            rolling = obj["spec"]["updateStrategy"]["rollingUpdate"]
            require(
                rolling == {"maxSurge": 0, "maxUnavailable": 1},
                "ztunnel node rollout bounds changed",
            )
    elif release.endswith("ingressgateway"):
        service = one(objects, "Service", release)["spec"]
        expected = "NodePort" if release.startswith("octelium") else "ClusterIP"
        require(service["type"] == expected, "gateway exposure changed")
        if expected == "NodePort":
            require(
                service["ports"]
                == [
                    {
                        "name": "https",
                        "port": 443,
                        "protocol": "TCP",
                        "targetPort": 443,
                        "nodePort": 30443,
                    }
                ],
                "Octelium gateway ports changed",
            )


def images(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "image" and isinstance(value, str):
                yield value
            else:
                yield from images(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from images(value)


def render(helm, charts, version, values, lock):
    rows = [r for r in lock if r["version"] == version]
    require(
        len(rows) == 5
        and {r["chart"] for r in rows}
        == {"base", "istiod", "cni", "ztunnel", "gateway"},
        f"{version}: missing reviewed chart locks (target remains blocked)",
    )
    artifacts = {}
    for row in rows:
        path = charts / f"{row['chart']}-{version}.tgz"
        artifacts[row["chart"]] = (path, verified_archive(path, row))
    results = []
    with tempfile.TemporaryDirectory(prefix="istio-values-") as temp:
        for release, row in values.items():
            path = Path(temp) / (release + ".json")
            path.write_text(json.dumps(row["values"]))
            chart, schema = artifacts[row["chart"]]
            proc = subprocess.run(
                [
                    str(helm),
                    "template",
                    release,
                    str(chart),
                    "--namespace",
                    "istio-system",
                    "--kube-version",
                    "1.34.11",
                    "--include-crds",
                    "-f",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            # Never emit raw renders or stderr: charts may generate Secret bodies.
            require(proc.returncode == 0, f"{release}: strict Helm validation failed")
            objects = [
                o for o in yaml.safe_load_all(proc.stdout) if isinstance(o, dict)
            ]
            semantic_check(release, objects)
            results.append(
                {
                    "release": release,
                    "version": version,
                    "chart_schema_present": schema,
                    "semantic_checks": "passed",
                    "images": sorted(set(images(objects))),
                }
            )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helm", type=Path)
    parser.add_argument("--charts", type=Path, help="local QA chart archive directory")
    parser.add_argument(
        "--version", help="one exact locked version, including baseline"
    )
    parser.add_argument("--promotion-check", action="store_true")
    args = parser.parse_args()
    try:
        values = json.loads((SPEC / "chart-values.json").read_text())
        plan = json.loads((SPEC / "hold.json").read_text())
        validate_values(values)
        validate_hold(plan)
        if args.promotion_check:
            print(
                json.dumps(
                    {
                        "promotion": "BLOCKED",
                        "executor": "not implemented",
                        "gates": plan["required_evidence"],
                    },
                    indent=2,
                )
            )
            return 2
        if any([args.helm, args.charts, args.version]):
            require(
                all([args.helm, args.charts, args.version]),
                "--helm, --charts and --version must be supplied together",
            )
            result = render(
                args.helm.resolve(),
                args.charts.resolve(),
                args.version,
                values,
                json.loads((SPEC / "chart-lock.json").read_text()),
            )
        else:
            result = {"design_structure": "passed", "render": "NOT_RUN"}
        print(
            json.dumps(
                {"offline_checks": result, "operational_acceptance": "HOLD"}, indent=2
            )
        )
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        StopIteration,
        tarfile.TarError,
        yaml.YAMLError,
        subprocess.TimeoutExpired,
    ) as error:
        print(
            f"Offline validation failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
