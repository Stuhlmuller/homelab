#!/usr/bin/env python3
"""Remove only the pinned firewall controller's reviewed IPv4 objects on its canary."""

import argparse
import base64
import hashlib
import json
import os
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts/config/platform-maintenance.json"
PLATFORM = runpy.run_path(str(ROOT / "scripts/platform-maintenance.py"))
IMAGE = ("harbor.stinkyboi.com/mirror/docker.io/cloudnativelabs/kube-router:"
         "64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a"
         "@sha256:64da9a538d29e13780e256ce3897a52932a68657793bef009063bbeb2762146a")
CANARY = "homelab.stinkyboi.com/network-policy-canary"
FIXTURE_NAMESPACE = "network-policy-canary"
CLEANUP = "kube-router-network-policy-cleanup"
ENFORCER = "kube-router-network-policy"
ROOT_CHAINS = {"INPUT": "KUBE-ROUTER-INPUT", "FORWARD": "KUBE-ROUTER-FORWARD",
               "OUTPUT": "KUBE-ROUTER-OUTPUT"}
FIXED_CHAINS = {*ROOT_CHAINS.values(), "KUBE-NWPLCY-DEFAULT", "KUBE-NWPLCY-COMMON",
                "KUBE-NWPLCY-TAIL"}
CHAIN_PREFIXES = ("KUBE-ROUTER-", "KUBE-NWPLCY-", "KUBE-POD-FW-")
SET_PREFIXES = ("KUBE-SRC-", "KUBE-DST-", "kube-router-local-pods")
HASH_CHAIN = re.compile(r"(?:KUBE-NWPLCY|KUBE-POD-FW)-[A-Z2-7]{16}\Z")
HASH_SET = re.compile(r"KUBE-(?:SRC|DST)-[A-Z2-7]{16}\Z")
TERMINAL = {"ACCEPT", "DROP", "REJECT", "RETURN", "MARK", "NFLOG"}
SET_REFERENCES = {"--match-set", "--add-set", "--del-set", "--map-set"}
MAX_SNAPSHOT = 8 * 1024 * 1024


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45, check=True)
    if len(result.stdout) > MAX_SNAPSHOT:
        raise ValueError("firewall or Kubernetes snapshot exceeds reviewed bound")
    return result.stdout


def kubernetes_json(*args):
    return json.loads(command("kubectl", "--request-timeout=20s", *args, "-o", "json"))


def complete_items(listing, inventory):
    if (not isinstance(listing, dict) or not isinstance(listing.get("items"), list) or
            not isinstance(listing.get("metadata"), dict) or
            listing["metadata"].get("continue")):
        raise ValueError(f"{inventory} inventory is incomplete")
    return listing["items"]


def ready(object_):
    return any(item.get("type") == "Ready" and item.get("status") == "True"
               for item in object_.get("status", {}).get("conditions", []))


def tenant_object(object_):
    metadata = object_.get("metadata", {})
    labels = metadata.get("labels", {})
    return (metadata.get("namespace") in {"openclaw-system", "openclaw-agents"} or
            metadata.get("name", "").startswith(("openclaw-enterprise", "oce-")) or
            labels.get("app.kubernetes.io/part-of") == "openclaw-enterprise" or
            labels.get("app.kubernetes.io/name", "").startswith(("openclaw-enterprise", "oce-")))


def ensure_quiesced(items):
    for item in items:
        if not tenant_object(item):
            continue
        kind, spec, status = item.get("kind"), item.get("spec", {}), item.get("status", {})
        if kind == "Pod" and status.get("phase") not in {"Succeeded", "Failed"}:
            raise ValueError("Enterprise tenant Pod is not quiesced")
        if kind in {"Deployment", "StatefulSet", "ReplicaSet"} and spec.get("replicas", 1) != 0:
            raise ValueError("Enterprise tenant controller is not quiesced")
        if kind == "DaemonSet" and status.get("desiredNumberScheduled", 0) != 0:
            raise ValueError("Enterprise tenant DaemonSet is not quiesced")
        if kind == "Job" and (status.get("active", 0) or
                              status.get("succeeded", 0) < spec.get("completions", 1)):
            raise ValueError("Enterprise tenant Job is incomplete")
        if kind == "CronJob" and spec.get("suspend") is not True:
            raise ValueError("Enterprise tenant CronJob is active")


def require_reviewed_node_pods(node_name, placement, cleanup_pod, daemonset_uid):
    reviewed = placement.get("systemDaemonSetPods")
    if (not isinstance(reviewed, list) or
            any(not isinstance(pod, dict) or set(pod) != {"namespace", "name", "uid"} or
                pod.get("namespace") not in {"kube-system", "istio-system"} or
                any(not isinstance(value, str) or not value for value in pod.values())
                for pod in reviewed)):
        raise ValueError("reviewed canary system Pod identities are missing")
    expected = {(pod["namespace"], pod["name"], pod["uid"]) for pod in reviewed}
    if len(expected) != len(reviewed):
        raise ValueError("reviewed canary system Pod identities are duplicated")
    cleanup_id = ("kube-system", cleanup_pod["metadata"]["name"],
                  cleanup_pod["metadata"]["uid"])
    if cleanup_id in expected:
        raise ValueError("cleanup Pod must be separate from reviewed system Pods")
    listing = kubernetes_json("get", "pods", "-A", "--field-selector",
                              f"spec.nodeName={node_name}", "--chunk-size=0")
    actual = []
    for pod in complete_items(listing, "canary node Pod"):
        if not isinstance(pod, dict):
            raise ValueError("canary node Pod inventory has an invalid entry")
        metadata, spec = pod.get("metadata"), pod.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise ValueError("canary node Pod inventory has an invalid entry")
        identity = (metadata.get("namespace"), metadata.get("name"), metadata.get("uid"))
        owners = metadata.get("ownerReferences")
        if (spec.get("nodeName") != node_name or metadata.get("deletionTimestamp") or
                any(not isinstance(value, str) or not value for value in identity) or
                not isinstance(owners, list)):
            raise ValueError("canary node Pod inventory has an invalid entry")
        if identity == cleanup_id:
            valid = any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                        owner.get("name") == CLEANUP and owner.get("uid") == daemonset_uid and
                        owner.get("controller") is True for owner in owners)
        else:
            valid = (identity in expected and
                     any(isinstance(owner, dict) and owner.get("kind") == "DaemonSet" and
                         owner.get("controller") is True and
                         isinstance(owner.get("name"), str) and owner["name"] and
                         (owner["name"] == "ztunnel" if identity[0] == "istio-system"
                          else owner["name"] not in {ENFORCER, CLEANUP})
                         for owner in owners))
        if not valid:
            raise ValueError("canary node has an unreviewed Pod")
        actual.append(identity)
    if len(set(actual)) != len(actual) or set(actual) != expected | {cleanup_id}:
        raise ValueError("canary node Pod inventory differs from reviewed placement")


def inspect_cluster(config, placement):
    node_name = config["canary"]["node"]
    node = kubernetes_json("get", "node", node_name)
    if (node["metadata"].get("uid") != placement["nodeUid"] or
            node["status"].get("nodeInfo", {}).get("bootID") != placement["bootID"] or
            node["metadata"].get("labels", {}).get(CANARY) != "true" or
            not ready(node) or
            not any(item.get("key") == CANARY and item.get("value") == "true" and
                    item.get("effect") == "NoSchedule" for item in node["spec"].get("taints", []))):
        raise ValueError("canary node identity, taint, or readiness changed")
    workloads = kubernetes_json("get", "pods,deployments,statefulsets,replicasets,"
                                "daemonsets,jobs,cronjobs", "-A", "--chunk-size=0")
    workload_items = complete_items(workloads, "Enterprise workload")
    if any(item.get("metadata", {}).get("namespace") == FIXTURE_NAMESPACE
           for item in workload_items):
        raise ValueError("canary fixture workload still exists")
    ensure_quiesced(workload_items)
    enforcer = command("kubectl", "--request-timeout=20s", "-n", "kube-system",
                       "get", "daemonset", ENFORCER, "--ignore-not-found", "-o", "json")
    if enforcer.strip():
        raise ValueError("firewall enforcer DaemonSet still exists")
    pods = kubernetes_json("-n", "kube-system", "get", "pods", "-l",
                           f"app.kubernetes.io/name={ENFORCER}", "--chunk-size=0")
    if complete_items(pods, "firewall enforcer Pod"):
        raise ValueError("firewall enforcer Pod still exists")
    namespace = command("kubectl", "--request-timeout=20s", "get", "namespace",
                        FIXTURE_NAMESPACE, "--ignore-not-found", "-o", "json")
    if namespace.strip():
        raise ValueError("canary fixture namespace must be absent")
    daemonset = kubernetes_json("-n", "kube-system", "get", "daemonset", CLEANUP)
    template = daemonset["spec"]["template"]["spec"]
    container, = template["containers"]
    if (daemonset["metadata"].get("name") != CLEANUP or
            daemonset["spec"]["selector"].get("matchLabels") !=
            {"app.kubernetes.io/name": CLEANUP} or
            daemonset.get("status", {}).get("desiredNumberScheduled") != 1 or
            daemonset.get("status", {}).get("numberReady") != 1 or
            template.get("nodeSelector") != {CANARY: "true"} or
            template.get("automountServiceAccountToken") is not False or
            template.get("hostNetwork") is not True or
            container.get("image") != IMAGE or
            container.get("command") != ["/bin/sh", "-c"] or
            container.get("args") != ["sleep 86400"] or
            container.get("securityContext", {}).get("privileged") is not True):
        raise ValueError("cleanup DaemonSet differs from reviewed dormant source")
    candidates = complete_items(kubernetes_json("-n", "kube-system", "get", "pods", "-l",
                                                f"app.kubernetes.io/name={CLEANUP}",
                                                "--chunk-size=0"), "cleanup Pod")
    if len(candidates) != 1:
        raise ValueError("cleanup Pod identity is ambiguous")
    pod, = candidates
    if (pod["spec"].get("nodeName") != node_name or not ready(pod) or
            pod["metadata"].get("namespace") != "kube-system" or
            pod["spec"].get("hostNetwork") is not True or
            pod["spec"]["containers"][0].get("image") != IMAGE or
            pod["metadata"].get("deletionTimestamp") or
            not any(ref.get("uid") == daemonset["metadata"].get("uid") and
                    ref.get("kind") == "DaemonSet" and ref.get("controller") is True for ref in
                    pod["metadata"].get("ownerReferences", []))):
        raise ValueError("cleanup Pod is not the reviewed node-local executor")
    require_reviewed_node_pods(node_name, placement, pod, daemonset["metadata"]["uid"])
    return pod["metadata"]["name"], pod["metadata"]["uid"]


def exec_cleanup(pod, *args):
    return command("kubectl", "--request-timeout=20s", "-n", "kube-system",
                   "exec", pod, "-c", "cleanup", "--", *args)


def snapshot(pod):
    version = exec_cleanup(pod, "iptables", "-V")
    if "(nf_tables)" in version:
        backend = "nft"
    elif "(legacy)" in version:
        backend = "legacy"
    else:
        raise ValueError("iptables backend is unknown")
    def stable(*args):
        return "\n".join(line for line in exec_cleanup(pod, *args).splitlines()
                         if line and not line.startswith("#")) + "\n"
    return {"backend": backend,
            "nft": stable("iptables-nft-save"),
            "legacy": stable("iptables-legacy-save"),
            "ip6nft": stable("ip6tables-nft-save"),
            "ip6legacy": stable("ip6tables-legacy-save"),
            "ipset": stable("ipset", "save")}


def snapshot_sha256(state):
    """Bind review to both IPv4 backends, IPv6 backends, ipsets, and active mode."""
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_ownership(ownership, placement, state, source_sha, node_name):
    if (not isinstance(ownership, dict) or ownership.get("format") != 1 or
            ownership.get("verified") is not True or
            ownership.get("sourceSha") != source_sha or
            ownership.get("node") != node_name or
            ownership.get("nodeUid") != placement["nodeUid"] or
            ownership.get("bootID") != placement["bootID"] or
            ownership.get("snapshotSha256") != snapshot_sha256(state) or
            not isinstance(ownership.get("reviewedAt"), str) or
            not ownership["reviewedAt"]):
        raise ValueError("independently reviewed firewall ownership snapshot is missing or stale")


def owned_chain(name):
    if name in FIXED_CHAINS or HASH_CHAIN.fullmatch(name):
        return True
    if name.startswith(CHAIN_PREFIXES):
        raise ValueError("unknown kube-router-prefixed chain")
    return False


def owned_set(name):
    if name == "kube-router-local-pods" or HASH_SET.fullmatch(name):
        return True
    if name.startswith(SET_PREFIXES) or name.startswith("inet6:") and \
            name.removeprefix("inet6:").startswith(SET_PREFIXES):
        raise ValueError("unknown kube-router-prefixed ipset")
    return False


def parse_filter(raw):
    chains, rules, table, found = set(), [], None, False
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("*") and table is None:
            table = line[1:]
            if table == "filter":
                if found:
                    raise ValueError("duplicate iptables filter table")
                found = True
            continue
        if line == "COMMIT" and table is not None:
            table = None
            continue
        if table is None:
            raise ValueError("iptables filter snapshot is malformed")
        if table != "filter":
            if any(prefix in line for prefix in (*CHAIN_PREFIXES, *SET_PREFIXES)):
                raise ValueError("owned-looking object appears outside filter table")
            continue
        parts = shlex.split(line)
        if line.startswith(":") and len(parts) == 3:
            chain = parts[0][1:]
            if chain in chains:
                raise ValueError("duplicate filter chain")
            chains.add(chain)
        elif len(parts) >= 4 and parts[0] == "-A":
            rules.append((parts[1], parts[2:]))
        else:
            raise ValueError("unknown iptables filter snapshot line")
    if table is not None or not found or not {"INPUT", "FORWARD", "OUTPUT"}.issubset(chains):
        raise ValueError("iptables filter snapshot is incomplete")
    return chains, rules


def parse_ipsets(raw):
    sets = set()
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        if len(parts) < 3 or parts[0] not in {"create", "add"}:
            raise ValueError("ipset snapshot is malformed")
        name = parts[1]
        if parts[0] == "create":
            if name in sets:
                raise ValueError("duplicate ipset")
            sets.add(name)
            family = parts[parts.index("family") + 1] if "family" in parts and \
                parts.index("family") + 1 < len(parts) else None
            if owned_set(name) and (family != "inet" or
                                    parts[2] not in {"hash:ip", "hash:net"} or
                                    name == "kube-router-local-pods" and parts[2] != "hash:ip"):
                raise ValueError("owned ipset has unexpected type or family")
        elif name not in sets:
            raise ValueError("ipset entry has no declared set")
        elif not owned_set(name) and any(owned_set(value) for value in parts[2:]):
            raise ValueError("foreign ipset references owned ipset")
    return {name for name in sets if owned_set(name)}


def top_jump_comment(builtin, target):
    spec = ["-m", "comment", "--comment", "kube-router netpol", "-j", target]
    digest = hashlib.sha256((builtin + "".join(spec)).encode()).digest()
    return "kube-router netpol - " + base64.b32encode(digest).decode()[:16]


def cleanup_plan(state):
    active = state["backend"]
    if active not in {"nft", "legacy"}:
        raise ValueError("iptables backend is unknown")
    other = "legacy" if active == "nft" else "nft"
    for key in (other, "ip6nft", "ip6legacy"):
        if any(prefix in state[key] for prefix in (*CHAIN_PREFIXES, *SET_PREFIXES)):
            raise ValueError("owned-looking objects exist in another firewall backend")
    chains, rules = parse_filter(state[active])
    owned = {chain for chain in chains if owned_chain(chain)}
    ipsets = parse_ipsets(state["ipset"])
    jumps = []
    for chain, rule in rules:
        if chain not in chains:
            raise ValueError("firewall rule has unknown chain")
        source_owned = chain in owned
        jumps_in_rule = [rule[index + 1] for index, token in enumerate(rule[:-1])
                         if token in {"-j", "--jump", "-g", "--goto"}]
        if source_owned and (len(jumps_in_rule) != 1 or
                             "-g" in rule or "--goto" in rule):
            raise ValueError("owned firewall rule jump is ambiguous")
        target = jumps_in_rule[0] if len(jumps_in_rule) == 1 else None
        target_owned = any(owned_chain(candidate) for candidate in jumps_in_rule)
        if rule and rule[-1] in SET_REFERENCES:
            raise ValueError("iptables SET extension is missing an ipset")
        used_sets = [(token, rule[index + 1]) for index, token in enumerate(rule[:-1])
                     if token in SET_REFERENCES]
        for operation, name in used_sets:
            if owned_set(name):
                if operation != "--match-set" or not source_owned or name not in ipsets:
                    raise ValueError("foreign, mutating, or missing reference to owned ipset")
            elif source_owned:
                raise ValueError("owned chain references foreign ipset")
        if source_owned:
            if not (target_owned and target in owned or target in TERMINAL):
                raise ValueError("owned chain references foreign target")
        elif target_owned:
            expected = ROOT_CHAINS.get(chain)
            if (len(jumps_in_rule) != 1 or expected != target or
                    rule != ["-m", "comment", "--comment",
                             top_jump_comment(chain, target), "-j", target]):
                raise ValueError("foreign reference to owned chain")
            jumps.append((chain, rule))
    if len(jumps) != len(set(chain for chain, _ in jumps)):
        raise ValueError("duplicate top-level kube-router jump")
    binary = f"iptables-{active}"
    commands = [(binary, "-w", "10", "-t", "filter", "-D", chain, *rule)
                for chain, rule in jumps]
    commands += [(binary, "-w", "10", "-t", "filter", "-F", chain)
                 for chain in sorted(owned)]
    commands += [(binary, "-w", "10", "-t", "filter", "-X", chain)
                 for chain in sorted(owned)]
    commands += [("ipset", "destroy", name) for name in sorted(ipsets)]
    return commands, len(owned), len(ipsets)


def write_record(path, record, replace=False):
    path = PLATFORM["private_output"](path)
    if not replace:
        PLATFORM["save_inspection"](path, record)
        return
    fd, temp = tempfile.mkstemp(prefix=".network-policy-cleanup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def require_current_main(source_sha):
    if (command("git", "-C", str(ROOT), "rev-parse", "HEAD").strip() != source_sha or
            PLATFORM["current_main_sha"]() != source_sha):
        raise ValueError("cleanup source is not exact current main")


def require_firewall_removal_transition(evidence_sha, source_sha):
    """Accept pre-removal evidence across two dedicated prunes and unrelated merges."""
    if (not isinstance(evidence_sha, str) or not PLATFORM["SHA"].fullmatch(evidence_sha) or
            evidence_sha == source_sha):
        raise ValueError("firewall evidence is not from the reviewed pre-removal commit")
    canary_manifest = "clusters/homelab/platform/network-policy/canary/kustomization.yaml"
    canary_application = "IaC/platform-network-policy-canary/stack.hcl"
    # Native OpenWiki may update only these non-runtime pages and their provenance.
    wiki_paths = {
        "openwiki/.last-update.json",
        "openwiki/.page-manifest.json",
        "openwiki/workloads/inventory.md",
        "openwiki/.claims/workloads/inventory.json",
        "openwiki/operations/harbor-oci.md",
        "openwiki/.claims/operations/harbor-oci.json",
        "openwiki/runbooks/argocd-app-onboarding.md",
        "openwiki/.claims/runbooks/argocd-app-onboarding.json",
        "openwiki/runbooks/runtime-isolation.md",
        "openwiki/.claims/runbooks/runtime-isolation.json",
    }
    old_canary_manifest = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - fixtures.yaml\n"
    empty_manifest = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n"
    old_canary_sync = "        enabled = true\n        prune   = true\n"
    new_sync = "        enabled    = true\n        prune      = true\n        allowEmpty = true\n"
    manifest = "clusters/homelab/platform/network-policy/kustomization.yaml"
    application = "IaC/platform-network-policy/stack.hcl"
    old_manifest = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - daemonset.yaml\n"
    old_sync = "        enabled = false\n        prune   = false\n"
    commits = command("git", "-C", str(ROOT), "rev-list", "--first-parent", "--reverse",
                      f"{evidence_sha}..{source_sha}").splitlines()
    previous, phase = evidence_sha, 0
    for commit_sha in commits:
        parents = command("git", "-C", str(ROOT), "show", "-s", "--format=%P", commit_sha).split()
        if not parents or parents[0] != previous:
            raise ValueError("firewall evidence is not on the current first-parent history")
        changed = set(command("git", "-C", str(ROOT), "diff", "--no-renames", "--name-only",
                              previous, commit_sha).splitlines())
        if phase == 0 and {canary_manifest, canary_application} & changed:
            old_app = command("git", "-C", str(ROOT), "show", f"{previous}:{canary_application}")
            new_app = command("git", "-C", str(ROOT), "show", f"{commit_sha}:{canary_application}")
            if (changed - wiki_paths != {canary_manifest, canary_application} or
                    command("git", "-C", str(ROOT), "show", f"{previous}:{canary_manifest}") != old_canary_manifest or
                    command("git", "-C", str(ROOT), "show", f"{commit_sha}:{canary_manifest}") != empty_manifest or
                    old_app.count(old_canary_sync) != 1 or
                    new_app != old_app.replace(old_canary_sync, new_sync)):
                raise ValueError("fixture removal differs from the reviewed GitOps transition")
            phase = 1
        elif phase == 1 and {manifest, application} & changed:
            old_app = command("git", "-C", str(ROOT), "show", f"{previous}:{application}")
            new_app = command("git", "-C", str(ROOT), "show", f"{commit_sha}:{application}")
            if (changed - wiki_paths != {manifest, application} or
                    command("git", "-C", str(ROOT), "show", f"{previous}:{manifest}") != old_manifest or
                    command("git", "-C", str(ROOT), "show", f"{commit_sha}:{manifest}") != empty_manifest or
                    old_app.count(old_sync) != 1 or
                    new_app != old_app.replace(old_sync, new_sync)):
                raise ValueError("firewall removal differs from the reviewed GitOps transition")
            phase = 2
        elif any(path.startswith(("clusters/homelab/platform/network-policy/",
                                  "IaC/platform-network-policy", "scripts/network-policy-",
                                  "scripts/ci/network-policy-", "scripts/ci/platform-maintenance-",
                                  "IaC/terragrunt-catalog/units/live/argocd-app/",
                                  "IaC/terragrunt-catalog/modules/argocd-application-kubernetes/")) or
                 path in {"scripts/platform-maintenance.py", "scripts/config/platform-maintenance.json",
                          "scripts/ci/platform-maintenance-stage.sh",
                          "scripts/ci/static-checks.sh", "scripts/ci/offline-static-checks.sh",
                          "scripts/ci/terragrunt-filter-base.sh",
                          "scripts/ci/install-kubeconfig.sh", "scripts/ci/install-octelium-client.sh",
                          ".github/workflows/platform-maintenance.yml", "policy/workflows.rego",
                          "policy/workflows_test.rego",
                          "IaC/root.hcl", "IaC/terragrunt.stack.hcl",
                          "IaC/stack-defaults.hcl",
                          "clusters/homelab/argocd/self-management/appproject.yaml"}
                 for path in changed):
            raise ValueError("policy cleanup source changed after qualification")
        previous = commit_sha
    if phase != 2:
        raise ValueError("both reviewed GitOps prune transitions are required")


def execute(args):
    if args.config.resolve() != CONFIG or not PLATFORM["SHA"].fullmatch(args.expected_sha):
        raise ValueError("cleanup requires committed input and an exact source SHA")
    if not re.fullmatch(r"[1-9][0-9]*", args.capture_run_id):
        raise ValueError("cleanup requires an exact reviewed capture run ID")
    config = PLATFORM["validate_config"](json.loads(args.config.read_text()))
    node_name = config["canary"]["node"]
    if node_name is None:
        raise ValueError("no admitted canary node")
    PLATFORM["protected_context"](args.expected_sha)
    require_current_main(args.expected_sha)
    directory = PLATFORM["private_directory"](args.receipt_dir)
    ownership = PLATFORM["read_private_json"](directory / "firewall-ownership.json")
    if ownership.get("captureRunId") != args.capture_run_id:
        raise ValueError("cleanup ownership receipt differs from selected capture")
    evidence_sha = ownership.get("evidenceSourceSha")
    require_firewall_removal_transition(evidence_sha, args.expected_sha)
    placement = PLATFORM["read_private_json"](directory / "placement.json")
    if (placement.get("format") != 1 or placement.get("verified") is not True or
            placement.get("sourceSha") != evidence_sha or
            placement.get("node") != node_name or
            placement.get("firewallBaselineEmpty") is not True or
            not placement.get("nodeUid") or not placement.get("bootID")):
        raise ValueError("verified pre-enable placement and empty firewall baseline are required")
    output = PLATFORM["private_output"](args.output)
    if output.exists() or output.is_symlink():
        previous = PLATFORM["read_private_json"](output)
        if (previous.get("stage") != "owned-firewall-cleanup" or
                previous.get("sourceSha") != args.expected_sha or
                previous.get("node") != node_name or
                previous.get("status") not in {"started", "interrupted", "verified"}):
            raise ValueError("existing cleanup receipt is unrelated")
    else:
        previous = None
    pod, pod_uid = inspect_cluster(config, placement)
    state = snapshot(pod)
    plan, chains, sets = cleanup_plan(state)
    if previous and previous["status"] == "verified":
        if plan:
            raise ValueError("verified cleanup receipt conflicts with live firewall")
        return previous
    require_ownership(ownership, placement, state, args.expected_sha, node_name)
    record = {"format": 1, "stage": "owned-firewall-cleanup", "status": "started",
              "verified": False, "sourceSha": args.expected_sha, "node": node_name,
              "captureRunId": args.capture_run_id,
              "nodeUid": placement["nodeUid"], "bootID": placement["bootID"],
              "cleanupPodUid": pod_uid, "backend": state["backend"],
              "beforeSha256": snapshot_sha256(state),
              "ownedChains": chains, "ownedSets": sets,
              "capturedAt": datetime.now(timezone.utc).isoformat()}
    write_record(output, record, replace=previous is not None)
    try:
        if plan:
            if inspect_cluster(config, placement) != (pod, pod_uid) or snapshot(pod) != state:
                raise ValueError("cleanup identity or firewall changed before deletion")
            # shortcut: Pod inventory and firewall deletion are not atomic; prove
            # exclusive placement before live rollout or add a reviewed isolation path.
            for operation in plan:
                require_current_main(args.expected_sha)
                exec_cleanup(pod, *operation)
        require_current_main(args.expected_sha)
        if inspect_cluster(config, placement) != (pod, pod_uid):
            raise ValueError("cleanup identity changed during deletion")
        after = snapshot(pod)
        remaining, _, _ = cleanup_plan(after)
        if remaining:
            raise ValueError("owned firewall objects remain after cleanup")
        record.update({"status": "verified", "verified": True,
                       "completedAt": datetime.now(timezone.utc).isoformat(),
                       "afterSha256": hashlib.sha256(after[after["backend"]].encode()).hexdigest()})
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        record.update({"status": "interrupted", "verified": False})
        write_record(output, record, replace=True)
        raise
    write_record(output, record, replace=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--capture-run-id", required=True)
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        execute(args)
        print("Owned firewall cleanup verified; private receipt retained")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Owned firewall cleanup blocked; inspect private receipts", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
