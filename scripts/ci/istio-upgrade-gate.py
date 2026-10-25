#!/usr/bin/env python3
"""Fail closed on unreviewed Istio chart sources and an unqualified 1.28 rollout."""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "clusters/homelab/apps/istio/upgrade-1.28.10.json"
OLD_REPOSITORY = "https://istio-release.storage.googleapis.com/charts"
NEW_REPOSITORY = "https://blob.istio.io/istio-release/charts"
BASELINE_MANIFEST_SHA256 = "46693741bf78ea71aab36dd9359422a9cb21478b4c3aa7e87c979a5f24b9c3b5"
COMPONENTS = (
    ("base", "istio-base", "32b3d9833cf6473e8e567407855c029012b1080416ae4f9ee7bd4ce93617e132"),
    ("istiod", "istiod", "125367e6eec08c8e7fc6e165c35ecf306dc23ea069b7953aed57fe83098004f1"),
    ("cni", "istio-cni", "7fd3133f6232c590493bb94974b2647dc287cd9a3a6acde621f6d4c7c1939295"),
    ("ztunnel", "ztunnel", "02dc5cee6532b0ed7ebf289e4dff003518a9bda5f09ab1ff7eff8c2530d6fc49"),
    ("gateway", "istio-ingressgateway", "7c79ecf1ca2b79760be73ad521b50cc1fa573297c41169042a116a13ce3005df"),
    ("gateway", "octelium-api-ingressgateway", "7c79ecf1ca2b79760be73ad521b50cc1fa573297c41169042a116a13ce3005df"),
)
ZTUNNEL_PARAMETERS = {
    "podLabels.homelab\\.rst\\.io/service-account-issuer-cutover": "10-1-0-199-v1",
    "updateStrategy.rollingUpdate.maxSurge": "0",
    "updateStrategy.rollingUpdate.maxUnavailable": "1",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_candidate(candidate):
    require(isinstance(candidate, dict) and set(candidate) == {
        "schemaVersion", "activationEnabled", "phase", "from", "to",
        "chartRepository", "components",
    }, "Istio candidate contract changed")
    require(type(candidate["schemaVersion"]) is int and candidate["schemaVersion"] == 1 and
            candidate["from"] == "1.27.3" and candidate["to"] == "1.28.10" and
            candidate["chartRepository"] == NEW_REPOSITORY,
            "Istio release or chart repository is unreviewed")
    require(type(candidate["activationEnabled"]) is bool and
            type(candidate["phase"]) is int and 0 <= candidate["phase"] <= len(COMPONENTS),
            "Istio phase is invalid")
    require(candidate["activationEnabled"] == (candidate["phase"] > 0),
            "Istio activation and component phase disagree")
    require(isinstance(candidate["components"], list) and len(candidate["components"]) == len(COMPONENTS),
            "Istio component list changed")
    for item, (chart, release, digest) in zip(candidate["components"], COMPONENTS):
        require(item == {"chart": chart, "releaseName": release, "archiveSha256": digest},
                "Istio component order or chart pin changed")
    return candidate["phase"]


def check_sources(rendered, phase):
    require(isinstance(rendered, dict), "rendered Istio Application is invalid")
    manifest = rendered.get("inputs", {}).get("manifest", {})
    spec = manifest.get("spec", {})
    policy = spec.get("syncPolicy", {}).get("automated", {})
    require(manifest.get("metadata", {}).get("name") == "istio" and
            all(policy.get(field) is True for field in ("enabled", "prune", "selfHeal")),
            "Istio Application identity or self-heal changed")
    sources = spec.get("sources", [])
    require(isinstance(sources, list), "Istio Application sources are invalid")
    charts = [source for source in sources if isinstance(source, dict) and "chart" in source]
    require(len(charts) == len(COMPONENTS), "Istio chart source count changed")
    for index, (source, (chart, release, _)) in enumerate(zip(charts, COMPONENTS)):
        expected = (NEW_REPOSITORY, "1.28.10") if index < phase else (OLD_REPOSITORY, "1.27.3")
        actual = (source.get("repoURL"), source.get("targetRevision"))
        require(actual == expected and source.get("chart") == chart and
                source.get("helm", {}).get("releaseName") == release,
                "Istio charts must advance one ordered source at a time")
    parameters = charts[3].get("helm", {}).get("parameters", [])
    require(isinstance(parameters, list), "Istio ztunnel parameters are invalid")
    for name, value in ZTUNNEL_PARAMETERS.items():
        require(sum(item.get("name") == name and item.get("value") == value
                    for item in parameters if isinstance(item, dict)) == 1,
                "Istio ztunnel rollout safeguard changed")
    baseline = copy.deepcopy(manifest)
    for index in range(phase):
        baseline["spec"]["sources"][index]["repoURL"] = OLD_REPOSITORY
        baseline["spec"]["sources"][index]["targetRevision"] = "1.27.3"
    digest = hashlib.sha256(json.dumps(
        baseline, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(digest == BASELINE_MANIFEST_SHA256,
            "Istio Application specification differs from the held baseline")


def without_labels(manifest):
    value = copy.deepcopy(manifest)
    value.get("metadata", {}).pop("labels", None)
    return value


def authorize_plan(plan_dir, rendered, phase):
    """Allow baseline/no-op plans; hold an actual Istio chart/source transition."""
    plans = list(plan_dir.glob("**/istio/argocd/tfplan.json"))
    require(len(plans) <= 1, "multiple planned Istio Applications")
    if not plans:
        return
    plan = json.loads(plans[0].read_text())
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "planned Istio changes are missing")
    intended = rendered["inputs"]["manifest"]
    for resource in changes:
        require(resource.get("type") == "kubernetes_manifest", "unexpected Istio plan resource")
        change = resource.get("change", {})
        actions = change.get("actions")
        if actions == ["no-op"]:
            continue
        require(actions in (["create"], ["update"]), "Istio replacement or removal is held")
        after = change.get("after")
        require(isinstance(after, dict) and isinstance(after.get("manifest"), dict),
                "planned Istio Application is unknown")
        actual = after["manifest"]
        require(actual == intended, "planned Istio Application differs from reviewed source")
        before = change.get("before")
        if before is None:
            require(actions == ["create"] and phase == 0,
                    "first Istio installation must use the held baseline")
            continue
        require(actions == ["update"] and isinstance(before, dict),
                "Istio plan baseline is unknown")
        require(isinstance(before.get("manifest"), dict) and
                without_labels(actual) == without_labels(before["manifest"]),
                "Istio specification change needs protected post-sync health receipts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-source", "authorize-apply"))
    parser.add_argument("--plan-dir", type=Path)
    args = parser.parse_args()
    candidate = json.loads(CANDIDATE.read_text())
    phase = check_candidate(candidate)
    rendered = json.load(sys.stdin)
    check_sources(rendered, phase)
    if args.action == "authorize-apply":
        require(args.plan_dir is not None and args.plan_dir.is_dir(), "Istio plan directory is missing")
        # A protected post-sync verifier and durable per-component receipts
        # must be added before any changed chart source can be applied.
        authorize_plan(args.plan_dir, rendered, phase)
    print(f"Istio source phase {phase} validated")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"Istio upgrade gate: {error}", file=sys.stderr)
        sys.exit(1)
