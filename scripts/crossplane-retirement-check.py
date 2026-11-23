#!/usr/bin/env python3
"""Read-only preflight for the Crossplane 2.3.3 chart-prune stage."""

import json
import subprocess
import sys


NAMESPACE = "crossplane-system"
API_SERVER = "https://10.1.0.199:6443"
CRDS = {
    "apiextensions.crossplane.io": (
        "compositeresourcedefinitions", "compositionrevisions", "compositions",
        "environmentconfigs", "managedresourceactivationpolicies", "managedresourcedefinitions", "usages",
    ),
    "ops.crossplane.io": ("cronoperations", "operations", "watchoperations"),
    "pkg.crossplane.io": (
        "configurationrevisions", "configurations", "deploymentruntimeconfigs", "functionrevisions",
        "functions", "imageconfigs", "locks", "providerrevisions", "providers",
    ),
    "protection.crossplane.io": ("clusterusages", "usages"),
}
DEFAULTS = {
    "deploymentruntimeconfigs.pkg.crossplane.io": ("default", {}),
    "locks.pkg.crossplane.io": ("lock", None),
    "managedresourceactivationpolicies.apiextensions.crossplane.io": ("default", {"activate": ["*"]}),
}
CHART_KINDS = {
    (None, "Secret"), (None, "Service"), (None, "ServiceAccount"), ("apps", "Deployment"),
    ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def kubectl(*args):
    return subprocess.check_output(
        ["kubectl", "--request-timeout=10s", *args], stderr=subprocess.DEVNULL, text=True, timeout=30,
    )


def read(*args):
    return json.loads(kubectl("get", *args, "-o", "json"))


def listing(*args):
    response = read(*args, "--chunk-size=100", "--show-managed-fields")
    require(response["kind"] == "List" and isinstance(response["items"], list), "Invalid Kubernetes list")
    return response["items"]


def crossplane_crd(crd):
    metadata, spec = crd["metadata"], crd["spec"]
    markers = [
        spec["group"], spec.get("conversion"), metadata.get("labels"), metadata.get("annotations"),
        metadata.get("ownerReferences"), [entry["manager"] for entry in metadata.get("managedFields", [])],
    ]
    return any(marker in json.dumps(markers).lower() for marker in ("crossplane", "upbound.io"))


def check_instances(name, instances):
    default = DEFAULTS.get(name)
    if not instances and default is None:
        return
    require(default is not None and len(instances) == 1, f"{name}: unexpected instance count")
    item = instances[0]
    metadata = item["metadata"]
    require(
        metadata["name"] == default[0] and item.get("spec") == default[1]
        and set(item) <= {"apiVersion", "kind", "metadata", "spec", "status", "packages"}
        and item.get("packages") in (None, [])
        and not any(
            metadata.get(field) for field in ("ownerReferences", "finalizers", "deletionTimestamp", "labels", "annotations")
        ),
        f"{name}: instance differs from the built-in default",
    )


def preflight():
    require(kubectl("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}") == API_SERVER,
            "Expected the authenticated homelab API")
    app = read("application.argoproj.io", "platform-crossplane", "-n", "argocd")
    source, = app["spec"]["sources"]
    require(
        source["repoURL"] == "https://charts.crossplane.io/stable"
        and source["chart"] == "crossplane" and source["targetRevision"] == "2.3.3"
        and app["spec"]["destination"]["namespace"] == NAMESPACE
        and app["status"]["sync"]["revisions"] == ["2.3.3"]
        and app["status"]["sync"]["status"] == "Synced" and app["status"]["health"]["status"] == "Healthy",
        "Expected the synced Crossplane 2.3.3 Helm application",
    )
    tracked = app["status"]["resources"]
    require(tracked and all((item.get("group"), item["kind"]) in CHART_KINDS for item in tracked),
            "Argo tracks an unexpected kind")
    expected = {f"{plural}.{group}" for group, plurals in CRDS.items() for plural in plurals}
    crds = [crd for crd in listing("crd") if crossplane_crd(crd)]
    require({crd["metadata"]["name"] for crd in crds} == expected and len(crds) == len(expected)
            and all(not crd["metadata"].get("deletionTimestamp") for crd in crds),
            "Crossplane-associated CRDs differ from the pinned core set")
    for name in sorted(expected):
        check_instances(name, listing(name, "--all-namespaces"))
    namespace = ("-n", NAMESPACE)
    deployments = listing("deployment", *namespace)
    require({item["metadata"]["name"] for item in deployments} == {"crossplane", "crossplane-rbac-manager"}
            and all(item["spec"]["replicas"] == 0 and item["status"].get("replicas", 0) == 0 for item in deployments),
            "Crossplane Deployments must be the two scaled-to-zero controllers")
    require(not listing("daemonsets,statefulsets,jobs,cronjobs", *namespace), "Unexpected namespace workloads")
    require(all(pod["status"]["phase"] in ("Succeeded", "Failed") for pod in listing("pod", *namespace)),
            "Crossplane namespace contains a non-terminal Pod")
    require(not listing("pvc", *namespace)
            and not any((pv["spec"].get("claimRef") or {}).get("namespace") == NAMESPACE for pv in listing("pv")),
            "Crossplane namespace still has volume claims")
    print(f"Crossplane preflight passed: {len(crds)} core CRDs, three unmodified built-in defaults, "
          f"{len(tracked)} tracked chart resources, zero active Pods or volume claims.")


if __name__ == "__main__":
    try:
        preflight()
    except ValueError as error:
        print(f"Crossplane preflight failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except (KeyError, TypeError, OSError, subprocess.SubprocessError):
        print("Crossplane preflight failed: Kubernetes read or response shape error", file=sys.stderr)
        raise SystemExit(1)
