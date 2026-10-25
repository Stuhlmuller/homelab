#!/usr/bin/env python3
"""Fail closed on unreviewed Istio chart sources and an unqualified 1.28 rollout."""

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "clusters/homelab/apps/istio/upgrade-1.28.10.json"
OLD_REPOSITORY = "https://istio-release.storage.googleapis.com/charts"
NEW_REPOSITORY = "oci://harbor.stinkyboi.com/mirror/helm"
BASELINE_FILE = ROOT / "scripts/ci/fixtures/istio-application-1.27.3.json"
BASELINE_MANIFEST_SHA256 = "46693741bf78ea71aab36dd9359422a9cb21478b4c3aa7e87c979a5f24b9c3b5"
REFERENCED_FILES = {
    ".argocd-values-ref-placeholder.yaml": "cb1d512dd7021fe32904661dec7f52219c58ae5ba049303f84c681a4c4f75df6",
    "clusters/homelab/apps/istio/values.yaml": "f9d20e2fb93e22e78dc07db649def6cb1c426c3ef8e8b0c89f050d4dc37211c9",
    "clusters/homelab/apps/istio/octelium-api-gateway-values.yaml": "3cc751beb194a4dfd7c7d29fe360794f0924caf416379cd412415b5e40b6e832",
    "clusters/homelab/apps/istio/kustomization.yaml": "c2dbb06b3c845574e5caca471822aa5b841e43035ea79df0faef9923be37adae",
    "clusters/homelab/apps/istio/certificate.yaml": "357f4da93c854a9986063311d9b85fe7602f4f5b6cd370629f6d19cba99a00f9",
    "clusters/homelab/apps/istio/namespace.yaml": "42706bd1545aa18b40f3c54276db6a8ed38ed3c63e7957827154c12c36dfe054",
    "clusters/homelab/apps/istio/octelium-api-gateway.yaml": "737545be14f2ff76101139ee024e17c5ffc368d0541952ccaa09b3b1148e5038",
    "clusters/homelab/apps/istio/tailnet-gateway.yaml": "17f8e1a1bb6f82ce1fcd17c1f91706b888e88d24823eaccc2e0f9b208f64a716",
    "clusters/homelab/apps/istio/upgrade-1.28.10/istiod-images.json": "61f639a5c9ed40f622f3344bd46351efa1b66a4ab23de5f6b869d73bfa1ab44d",
    "clusters/homelab/apps/istio/upgrade-1.28.10/istiod-final-images.json": "5b3d83df353647f84cd38445870d3f64c099298bc260b3781d0baeafa6181544",
    "clusters/homelab/apps/istio/upgrade-1.28.10/cni-images.json": "9c715a397fe3696df34e1c25a9f0db29fea87ca08e90e29205362e1feb45f0a2",
    "clusters/homelab/apps/istio/upgrade-1.28.10/ztunnel-images.json": "3b0cf9df967226c57f82ce92bad317d5eed6a8220f486d61bdd11017622abfab",
    "clusters/homelab/apps/istio/upgrade-1.28.10/gateway-images.json": "4ebee689df37598aec4dc220375472df00e8b4516ff0848ed7b48e7f2727abe2",
}
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
OVERLAY = "clusters/homelab/apps/istio/upgrade-1.28.10/"
OVERLAYS = {
    1: "istiod-images.json",
    2: "cni-images.json",
    3: "ztunnel-images.json",
    4: "gateway-images.json",
    5: "gateway-images.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_candidate(candidate):
    require(isinstance(candidate, dict) and set(candidate) == {
        "schemaVersion", "activationEnabled", "phase", "from", "to",
        "chartRepository", "components", "priorRunId", "harborRunId",
        "chartRunId", "chartManifestDigests",
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
    for field in ("priorRunId", "harborRunId", "chartRunId"):
        run_id = candidate[field]
        require((run_id is None and candidate["phase"] == 0) or
                (isinstance(run_id, str) and re.fullmatch(r"[1-9][0-9]*", run_id) and
                 candidate["phase"] > 0), f"Istio {field} protected run is missing")
    require(isinstance(candidate["components"], list) and len(candidate["components"]) == len(COMPONENTS),
            "Istio component list changed")
    for item, (chart, release, digest) in zip(candidate["components"], COMPONENTS):
        require(item == {"chart": chart, "releaseName": release, "archiveSha256": digest},
                "Istio component order or chart pin changed")
    manifests = candidate["chartManifestDigests"]
    if candidate["phase"] == 0:
        require(manifests is None, "held Istio charts cannot claim Harbor publication")
    else:
        require(isinstance(manifests, dict) and set(manifests) ==
                {chart for chart, _, _ in COMPONENTS} and all(
                    isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                    for value in manifests.values()),
                "Istio Harbor OCI manifest digests are missing")
    return candidate["phase"]


def expected_manifest(candidate, phase):
    baseline = json.loads(BASELINE_FILE.read_text())
    require(hashlib.sha256(json.dumps(baseline, sort_keys=True,
                                separators=(",", ":")).encode()).hexdigest() ==
            BASELINE_MANIFEST_SHA256, "held Istio Application fixture changed")
    manifest = copy.deepcopy(baseline)
    if phase:
        manifest["spec"]["syncPolicy"]["automated"]["prune"] = False
    for index, (chart, _, _) in enumerate(COMPONENTS[:phase]):
        source = manifest["spec"]["sources"][index]
        source.pop("chart")
        source["repoURL"] = f"{NEW_REPOSITORY}/{chart}"
        source["targetRevision"] = candidate["chartManifestDigests"][chart]
        overlay = "istiod-final-images.json" if phase == 6 and index == 1 else \
                  OVERLAYS.get(index)
        if overlay:
            source["helm"]["valueFiles"].append(f"$values/{OVERLAY}{overlay}")
    return manifest


def check_sources(rendered, candidate):
    phase = check_candidate(candidate)
    require(isinstance(rendered, dict) and
            rendered.get("inputs", {}).get("manifest") == expected_manifest(candidate, phase),
            "Istio Application must match the ordered immutable OCI source and image overlays")


def without_labels(manifest):
    value = copy.deepcopy(manifest)
    value.get("metadata", {}).pop("labels", None)
    return value


def check_referenced_content(root, phase):
    """Git-backed values and Kustomize content must not move during a hop."""
    if phase == 0:
        return
    for name, digest in REFERENCED_FILES.items():
        path = root / name
        require(path.is_file() and not path.is_symlink() and
                hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                "Istio referenced content changed during a staged upgrade")


def authorize_plan(plan_dir, rendered, candidate, allow_transition=False):
    """Allow one ordered chart transition only after private preflight."""
    plans = list(plan_dir.glob("**/istio/argocd/tfplan.json"))
    require(len(plans) <= 1, "multiple planned Istio Applications")
    phase = check_candidate(candidate)
    if not plans:
        require(phase == 0, "active Istio phase has no saved plan")
        return
    plan = json.loads(plans[0].read_text())
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "planned Istio changes are missing")
    intended = rendered["inputs"]["manifest"]
    if phase > 0:
        require(allow_transition and len(changes) == 1,
                "active Istio phase requires protected one-component admission")
        change = changes[0].get("change", {})
        previous = expected_manifest(candidate, phase - 1)
        require(changes[0].get("type") == "kubernetes_manifest" and
                change.get("actions") == ["update"] and
                isinstance(change.get("before"), dict) and
                isinstance(change.get("after"), dict) and
                isinstance(change["before"].get("manifest"), dict) and
                change["after"].get("manifest") == intended and
                without_labels(change["before"].get("manifest")) == without_labels(previous),
                "Istio plan must advance the exact ordered chart and image sources")
        return
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
    check_sources(rendered, candidate)
    check_referenced_content(ROOT, phase)
    if args.action == "authorize-apply":
        require(args.plan_dir is not None and args.plan_dir.is_dir(), "Istio plan directory is missing")
        # A protected post-sync verifier and durable per-component receipts
        # must be added before any changed chart source can be applied.
        authorize_plan(args.plan_dir, rendered, candidate)
    print(f"Istio source phase {phase} validated")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"Istio upgrade gate: {error}", file=sys.stderr)
        sys.exit(1)
