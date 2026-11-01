#!/usr/bin/env python3
"""Sync the manual firewall Application only from protected current-main apply."""

import argparse
import json
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
CLEANUP = runpy.run_path(str(ROOT / "scripts/network-policy-cleanup.py"))
PLATFORM = CLEANUP["PLATFORM"]
ACTIVATION = runpy.run_path(str(ROOT / "scripts/network-policy-activation-capacity.py"))
QUALIFICATION = runpy.run_path(str(ROOT / "scripts/network-policy-qualification.py"))
POLICY = ROOT / "clusters/homelab/platform/network-policy/kustomization.yaml"
CANARY = ROOT / "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
ENFORCER_SOURCE = ("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                   "kind: Kustomization\nresources:\n  - daemonset.yaml\n")
FIXTURE_SOURCE = ("apiVersion: kustomize.config.k8s.io/v1beta1\n"
                  "kind: Kustomization\nresources:\n  - fixtures.yaml\n")
EMPTY_SOURCE = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n"
APP = "platform-network-policy"
CANARY_APP = "platform-network-policy-canary"
TRACKED_FIREWALL = {
    ("", "ServiceAccount", "kube-system", "kube-router-network-policy"),
    ("rbac.authorization.k8s.io", "ClusterRole", "", "kube-router-network-policy"),
    ("rbac.authorization.k8s.io", "ClusterRoleBinding", "", "kube-router-network-policy"),
    ("apps", "DaemonSet", "kube-system", "kube-router-network-policy"),
}
PRUNE_FILTERS = (
    ":ServiceAccount:kube-system/kube-router-network-policy",
    "rbac.authorization.k8s.io:ClusterRole:kube-router-network-policy",
    "rbac.authorization.k8s.io:ClusterRoleBinding:kube-router-network-policy",
    "apps:DaemonSet:kube-system/kube-router-network-policy",
)


def source_phase(source_sha):
    """Only the reviewed activation and retirement states can sync the enforcer."""
    for relative in (POLICY, CANARY):
        committed = CLEANUP["command"]("git", "-C", str(ROOT), "--no-replace-objects",
                                       "show", f"{source_sha}:{relative.relative_to(ROOT)}")
        if relative.read_text() != committed:
            raise ValueError("manual firewall source differs from current main")
    pair = POLICY.read_text(), CANARY.read_text()
    if pair == (ENFORCER_SOURCE, FIXTURE_SOURCE):
        return "enforcer"
    if pair == (EMPTY_SOURCE, EMPTY_SOURCE):
        return "prune"
    raise ValueError("manual firewall sync requires a reviewed source phase")


def require_policy_application():
    ACTIVATION["require_application"](APP)
    application = CLEANUP["kubernetes_json"]("-n", "argocd", "get", "application", APP)
    if application.get("operation") is not None:
        raise ValueError("firewall Application already has a sync operation")
    return application


def require_tracked_firewall_resources(application, allow_partial=False):
    """Bound an explicit prune to only the four reviewed Argo-owned objects."""
    resources = application.get("status", {}).get("resources")
    if not isinstance(resources, list):
        raise ValueError("firewall Application tracked resource inventory is incomplete")
    identities = []
    for resource in resources:
        if not isinstance(resource, dict):
            raise ValueError("firewall Application tracked resource inventory is malformed")
        identities.append((resource.get("group", ""), resource.get("kind"),
                           resource.get("namespace", ""), resource.get("name")))
    observed = set(identities)
    if (len(observed) != len(identities) or not observed <= TRACKED_FIREWALL or
            (not allow_partial and observed != TRACKED_FIREWALL)):
        raise ValueError("firewall Application tracks unreviewed or missing resources")
    return observed


def live_firewall_rbac():
    identities = set()
    for kind, scope, group in (("serviceaccount", ("-n", "kube-system"), ""),
                               ("clusterrole", (), "rbac.authorization.k8s.io"),
                               ("clusterrolebinding", (), "rbac.authorization.k8s.io")):
        response = CLEANUP["command"]("kubectl", "--request-timeout=20s", *scope,
                                      "get", kind, CLEANUP["ENFORCER"],
                                      "--ignore-not-found", "-o", "json")
        if response.strip():
            item = json.loads(response)
            if (item.get("kind", "").lower() != kind or
                    item.get("metadata", {}).get("name") != CLEANUP["ENFORCER"] or
                    item.get("metadata", {}).get("namespace", "") !=
                    ("kube-system" if scope else "")):
                raise ValueError("live firewall RBAC identity changed")
            identities.add((group, item["kind"],
                            item.get("metadata", {}).get("namespace", ""),
                            CLEANUP["ENFORCER"]))
    return identities


def require_canary_application(source_sha, phase):
    if phase == "enforcer":
        ACTIVATION["require_application"](CANARY_APP, source_sha)
        return
    application = CLEANUP["kubernetes_json"]("-n", "argocd", "get", "application", CANARY_APP)
    spec, status = application.get("spec", {}), application.get("status", {})
    sync = status.get("sync", {})
    revisions = sync.get("revisions", [sync.get("revision")])
    if (application.get("metadata", {}).get("name") != CANARY_APP or
            application.get("metadata", {}).get("namespace") != "argocd" or
            application.get("metadata", {}).get("deletionTimestamp") or
            spec.get("project") != "homelab" or
            spec.get("destination") != {"server": "https://kubernetes.default.svc",
                                        "namespace": "network-policy-canary"} or
            spec.get("sources") != [{"repoURL": "https://github.com/Stuhlmuller/homelab.git",
                                     "path": "clusters/homelab/platform/network-policy/canary",
                                     "targetRevision": "main"}] or
            spec.get("syncPolicy", {}).get("automated") !=
            {"enabled": True, "prune": True, "allowEmpty": True, "selfHeal": True} or
            spec.get("syncPolicy", {}).get("syncOptions") !=
            ["CreateNamespace=false", "ServerSideApply=true"] or
            application.get("operation") is not None or
            sync.get("status") != "Synced" or
            revisions != [source_sha] or
            status.get("health", {}).get("status") != "Healthy" or
            status.get("resources", []) != []):
        raise ValueError("fixture Application is not empty and synced at current main")
    namespace = CLEANUP["command"]("kubectl", "--request-timeout=20s", "get", "namespace",
                                   "network-policy-canary", "--ignore-not-found", "-o", "json")
    if namespace.strip():
        raise ValueError("canary fixture namespace still exists")


def require_isolated_node(node_name, placement):
    node = CLEANUP["kubernetes_json"]("get", "node", node_name)
    metadata, spec = node.get("metadata", {}), node.get("spec", {})
    taints = spec.get("taints", [])
    if (metadata.get("name") != node_name or metadata.get("deletionTimestamp") or
            metadata.get("uid") != placement.get("nodeUid") or
            node.get("status", {}).get("nodeInfo", {}).get("bootID") !=
            placement.get("bootID") or
            metadata.get("labels", {}).get(CLEANUP["CANARY"]) != "true" or
            not CLEANUP["ready"](node) or
            not isinstance(taints, list) or
            [item for item in taints if item.get("key") == CLEANUP["CANARY"]] !=
            [{"key": CLEANUP["CANARY"], "value": "true", "effect": "NoSchedule"}]):
        raise ValueError("canary Node lost its reviewed isolation")


def selected_placement(config, source_sha, bucket):
    """Bind the manual stage to the immutable admitted Node UID and boot ID."""
    admission = config.get("activationAdmission")
    if (not isinstance(bucket, str) or not bucket or
            not isinstance(admission, dict) or
            set(admission) != {"sourceSha", "runId", "versionId"} or
            not PLATFORM["SHA"].fullmatch(str(admission["sourceSha"])) or
            not re.fullmatch(r"[1-9][0-9]*", str(admission["runId"])) or
            not isinstance(admission["versionId"], str) or
            admission["versionId"] in {"", "null"}):
        raise ValueError("selected immutable canary admission is required")
    ancestors = CLEANUP["command"]("git", "-C", str(ROOT), "--no-replace-objects",
                                   "rev-list", "--first-parent", source_sha).splitlines()
    if admission["sourceSha"] == source_sha or admission["sourceSha"] not in ancestors:
        raise ValueError("selected canary admission is not on current first-parent main")
    store = ACTIVATION["OWNERSHIP"]["PrivateStore"](bucket)
    store.store.check()
    placement, _, _, _ = ACTIVATION["selected_placement"](store, config, admission)
    ACTIVATION["require_admitted"](config, placement)
    return placement


def require_reviewed_pods(node_name, placement, enforcer_uid=None):
    expected = {(item["namespace"], item["name"], item["uid"])
                for item in placement["systemDaemonSetPods"]}
    pods = CLEANUP["complete_items"](CLEANUP["kubernetes_json"](
        "get", "pods", "-A", "--field-selector", f"spec.nodeName={node_name}",
        "--chunk-size=0"), "canary Pod")
    actual = []
    for pod in pods:
        metadata, spec = pod.get("metadata", {}), pod.get("spec", {})
        identity = tuple(metadata.get(key) for key in ("namespace", "name", "uid"))
        owners = metadata.get("ownerReferences", [])
        if (spec.get("nodeName") != node_name or metadata.get("deletionTimestamp") or
                any(not isinstance(value, str) or not value for value in identity) or
                not isinstance(owners, list) or
                not any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("controller") is True for owner in owners)):
            raise ValueError("canary Pod identity or owner changed before prune")
        if enforcer_uid is not None and identity == enforcer_uid:
            if not any(owner.get("name") == CLEANUP["ENFORCER"] for owner in owners):
                raise ValueError("enforcer Pod ownership changed before prune")
        elif identity not in expected:
            raise ValueError("foreign Pod remains on isolated canary")
        actual.append(identity)
    expected_live = expected | ({enforcer_uid} if enforcer_uid is not None else set())
    if len(set(actual)) != len(actual) or set(actual) != expected_live:
        raise ValueError("canary Pod inventory differs from reviewed placement")


def require_live_enforcer(node_name):
    # Reuse the qualification contract for flags, host namespace, mounts,
    # service account, and RBAC; Ready alone can precede policy programming.
    daemonset = QUALIFICATION["inspect_firewall_source"]()
    status = daemonset.get("status", {})
    if (daemonset.get("metadata", {}).get("deletionTimestamp") or
            status.get("desiredNumberScheduled") != 1 or
            status.get("updatedNumberScheduled") != 1 or
            status.get("numberReady") != 1):
        raise ValueError("live firewall enforcer is not the reviewed single-node DaemonSet")
    pods = CLEANUP["complete_items"](CLEANUP["kubernetes_json"](
        "-n", "kube-system", "get", "pods", "-l",
        f"app.kubernetes.io/name={CLEANUP['ENFORCER']}", "--chunk-size=0"),
        "firewall Pod")
    if len(pods) != 1:
        raise ValueError("live firewall Pod count differs from single-node enforcer")
    pod = pods[0]
    metadata = pod.get("metadata", {})
    pod_spec = pod.get("spec", {})
    containers = pod_spec.get("containers", [])
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else {}
    if (metadata.get("namespace") != "kube-system" or metadata.get("deletionTimestamp") or
            pod_spec.get("nodeName") != node_name or
            pod_spec.get("hostNetwork") is not True or
            pod_spec.get("serviceAccountName") != CLEANUP["ENFORCER"] or
            pod_spec.get("nodeSelector") != {CLEANUP["CANARY"]: "true"} or
            not isinstance(container, dict) or
            container.get("image") != QUALIFICATION["FIREWALL_IMAGE"] or
            set(container.get("args", [])) != QUALIFICATION["FIREWALL_FLAGS"] or
            container.get("securityContext", {}).get("privileged") is not True or
            not CLEANUP["ready"](pod) or
            not any(ref.get("kind") == "DaemonSet" and ref.get("controller") is True and
                    ref.get("uid") == daemonset.get("metadata", {}).get("uid") for ref in
                    metadata.get("ownerReferences", []))):
        raise ValueError("live firewall Pod identity or placement changed")
    return ("kube-system", metadata["name"], metadata["uid"])


def require_enforcer_absent():
    daemonset = CLEANUP["command"]("kubectl", "--request-timeout=20s", "-n", "kube-system",
                                   "get", "daemonset", CLEANUP["ENFORCER"],
                                   "--ignore-not-found", "-o", "json")
    pods = CLEANUP["kubernetes_json"]("-n", "kube-system", "get", "pods", "-l",
                                     f"app.kubernetes.io/name={CLEANUP['ENFORCER']}",
                                     "--chunk-size=0")
    if daemonset.strip() or CLEANUP["complete_items"](pods, "firewall Pod"):
        raise ValueError("firewall enforcer or Pod remains after manual prune")


def require_firewall_resources_absent():
    require_enforcer_absent()
    if live_firewall_rbac():
        raise ValueError("firewall identity or RBAC remains after manual prune")


def require_synced(source_sha, empty=False):
    application = require_policy_application()
    status = application.get("status", {})
    sync = status.get("sync", {})
    revisions = sync.get("revisions", [sync.get("revision")])
    if (sync.get("status") != "Synced" or revisions != [source_sha] or
            status.get("health", {}).get("status") != "Healthy" or
            status.get("operationState", {}).get("phase") != "Succeeded" or
            (empty and status.get("resources", []) != [])):
        raise ValueError("manual firewall sync did not finish at current main")


def already_synced(source_sha, empty=False):
    try:
        require_synced(source_sha, empty)
    except ValueError:
        return False
    return True


def execute(args):
    PLATFORM["protected_context"](args.expected_sha)
    CLEANUP["require_current_main"](args.expected_sha)
    PLATFORM["require_reviewed_execution_config"](CONFIG, args.expected_sha)
    config = PLATFORM["validate_config"](json.loads(CONFIG.read_text()))
    node_name = config["canary"]["node"]
    if config["activationEnabled"] is not True or not isinstance(node_name, str):
        raise ValueError("manual firewall sync requires an activated isolated canary")
    phase = source_phase(args.expected_sha)
    if phase != args.phase:
        raise ValueError("manual firewall sync phase differs from reviewed source")
    placement = selected_placement(config, args.expected_sha, args.bucket)
    require_policy_application()
    require_canary_application(args.expected_sha, phase)
    require_isolated_node(node_name, placement)
    if phase == "enforcer":
        if already_synced(args.expected_sha):
            require_tracked_firewall_resources(require_policy_application())
            require_live_enforcer(node_name)
            CLEANUP["require_current_main"](args.expected_sha)
            return
        require_tracked_firewall_resources(require_policy_application(), allow_partial=True)
        require_firewall_resources_absent()
        if not isinstance(args.bucket, str) or not args.bucket:
            raise ValueError("protected activation capacity store is required")
        ACTIVATION["execute"](argparse.Namespace(
            expected_sha=args.expected_sha, phase="enforcer", bucket=args.bucket))
        require_policy_application()
        require_canary_application(args.expected_sha, phase)
        require_isolated_node(node_name, placement)
        require_tracked_firewall_resources(require_policy_application(), allow_partial=True)
        require_firewall_resources_absent()
    else:
        CLEANUP["require_traefik_off_canary"](args.expected_sha, node_name)
        if already_synced(args.expected_sha, empty=True):
            require_firewall_resources_absent()
            require_reviewed_pods(node_name, placement)
            CLEANUP["require_current_main"](args.expected_sha)
            return
        daemonset = CLEANUP["command"](
            "kubectl", "--request-timeout=20s", "-n", "kube-system", "get", "daemonset",
            CLEANUP["ENFORCER"], "--ignore-not-found", "-o", "json")
        if daemonset.strip():
            enforcer_uid = require_live_enforcer(node_name)
            require_reviewed_pods(node_name, placement, enforcer_uid)
            require_tracked_firewall_resources(require_policy_application())
        else:
            require_enforcer_absent()
            require_reviewed_pods(node_name, placement)
            tracked = require_tracked_firewall_resources(
                require_policy_application(), allow_partial=True)
            if not live_firewall_rbac() <= tracked:
                raise ValueError("remaining firewall RBAC is not tracked for prune")
    CLEANUP["require_current_main"](args.expected_sha)
    command = ["argocd", "app", "sync", APP, "--core", "--revisions", args.expected_sha,
               "--source-positions", "1", "--timeout", "900"]
    if phase == "prune":
        command.append("--prune")
        for resource in PRUNE_FILTERS:
            command.extend(("--resource", resource))
    subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, text=True, check=True, timeout=930)
    subprocess.run(["argocd", "app", "wait", APP, "--core", "--sync", "--health",
                    "--operation", "--timeout", "900"], cwd=ROOT, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, text=True, check=True, timeout=930)
    require_synced(args.expected_sha, empty=phase == "prune")
    if phase == "enforcer":
        require_tracked_firewall_resources(require_policy_application())
        require_live_enforcer(node_name)
    else:
        deadline = time.monotonic() + 120
        while True:
            try:
                require_firewall_resources_absent()
                break
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        CLEANUP["require_traefik_off_canary"](args.expected_sha, node_name)
        require_reviewed_pods(node_name, placement)
    require_isolated_node(node_name, placement)
    CLEANUP["require_current_main"](args.expected_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("enforcer", "prune"), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--bucket")
    args = parser.parse_args()
    try:
        execute(args)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"manual firewall sync blocked: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("Manual firewall Application sync verified at current main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
