#!/usr/bin/env python3
"""Admit an Istio phase PR only after its exact protected predecessor succeeded."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = "clusters/homelab/apps/istio/upgrade-1.28.10.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = "Stuhlmuller/homelab"
PUBLICATION_BUNDLE = (
    "scripts/config/harbor-images.json", ".github/workflows/harbor-mirror.yml",
    "scripts/ci/harbor-publish.sh", "scripts/ci/install-kubeconfig.sh",
    "flake.nix", "flake.lock",
)
CHART_PUBLICATION_BUNDLE = (
    "scripts/config/harbor-istio-1.28.10-charts.json",
    ".github/workflows/harbor-helm-charts.yml",
    "scripts/ci/harbor-chart-publish.py", "scripts/ci/harbor-chart-publish.sh",
    "scripts/ci/install-kubeconfig.sh", "flake.nix", "flake.lock",
)


def command(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=30, check=True).stdout


def checked_run(candidate, previous, run, ancestor):
    phase = candidate.get("phase")
    run_id = candidate.get("priorRunId")
    if type(phase) is not int or not 0 <= phase <= 6:
        raise ValueError("Istio phase is invalid")
    if phase == 0:
        if run_id is not None or candidate.get("activationEnabled") is not False:
            raise ValueError("held Istio phase must not claim a prior run")
        return
    if (not isinstance(run_id, str) or
            not re.fullmatch(r"[1-9][0-9]{0,18}", run_id) or
            candidate.get("activationEnabled") is not True or
            not isinstance(previous, dict) or previous.get("phase") != phase - 1 or
            previous.get("activationEnabled") != (phase > 1) or
            any(candidate.get(key) != previous.get(key) for key in
                ("from", "to", "chartRepository", "components")) or
            (phase > 1 and candidate.get("chartManifestDigests") !=
             previous.get("chartManifestDigests"))):
        raise ValueError("Istio phase does not follow the reviewed prior source")
    sha = run.get("head_sha")
    if (run.get("id") != int(run_id) or not isinstance(sha, str) or not SHA.fullmatch(sha) or
            not ancestor(sha) or run.get("event") != "workflow_dispatch" or
            run.get("head_branch") != "main" or run.get("status") != "completed" or
            run.get("conclusion") != "success" or run.get("run_attempt", 0) < 1):
        raise ValueError("prior protected run is missing, unsuccessful or outside main ancestry")
    stage = "talos-1.14.4" if phase == 1 else f"istio-1.28.10-phase-{phase - 1}"
    expected = (f"Platform {stage} @ {sha}",
                ".github/workflows/platform-maintenance.yml")
    if (run.get("name") != expected[0] or run.get("path") != expected[1] or
            run.get("display_title") != expected[0]):
        raise ValueError("prior protected run is for a different stage")


def checked_harbor(candidate, run, ancestor, bundle_equal):
    phase = candidate.get("phase")
    run_id = candidate.get("harborRunId")
    if phase == 0:
        if run_id is not None:
            raise ValueError("held Istio phase must not claim Harbor publication")
        return
    if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", run_id):
        raise ValueError("active Istio phase requires a full Harbor run ID")
    sha = run.get("head_sha")
    if (run.get("id") != int(run_id) or not isinstance(sha, str) or not SHA.fullmatch(sha) or
            not ancestor(sha) or run.get("name") != f"Mirror all @ {sha}" or
            run.get("path") != ".github/workflows/harbor-mirror.yml" or
            run.get("display_title") != f"Mirror all @ {sha}" or
            run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main" or
            run.get("status") != "completed" or run.get("conclusion") != "success" or
            run.get("run_attempt", 0) < 1 or not bundle_equal(sha)):
        raise ValueError("full Harbor publication is missing, stale or outside main ancestry")
    jobs = run.get("jobs")
    if (not isinstance(jobs, list) or len(jobs) != 2 or
            {job.get("name") for job in jobs} !=
            {"Validate Harbor Mirror", "Copy Reviewed Public Images"} or
            any(job.get("status") != "completed" or job.get("conclusion") != "success"
                for job in jobs)):
        raise ValueError("full Harbor mirror jobs did not both succeed")
    required = {"Validate Harbor Mirror": "Validate Harbor Publication Gates",
                "Copy Reviewed Public Images": "Copy And Verify Fixed Public Digests"}
    for job in jobs:
        steps = job.get("steps")
        if (not isinstance(steps, list) or
                sum(step.get("name") == required[job["name"]] and
                    step.get("status") == "completed" and step.get("conclusion") == "success"
                    for step in steps if isinstance(step, dict)) != 1):
            raise ValueError("Harbor digest or authenticated-pull step did not succeed")


def checked_charts(candidate, run, ancestor, bundle_equal):
    phase = candidate.get("phase")
    run_id = candidate.get("chartRunId")
    manifests = candidate.get("chartManifestDigests")
    if phase == 0:
        if run_id is not None or manifests is not None:
            raise ValueError("held Istio phase must not claim chart publication")
        return
    if (not isinstance(run_id, str) or
            not re.fullmatch(r"[1-9][0-9]{0,18}", run_id) or
            not isinstance(manifests, dict) or
            set(manifests) != {"base", "istiod", "cni", "ztunnel", "gateway"} or
            any(not isinstance(value, str) or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                for value in manifests.values())):
        raise ValueError("active Istio phase requires five reviewed chart digests")
    sha = run.get("head_sha")
    if (run.get("id") != int(run_id) or not isinstance(sha, str) or
            not SHA.fullmatch(sha) or not ancestor(sha) or
            run.get("name") != f"Helm charts @ {sha}" or
            run.get("display_title") != f"Helm charts @ {sha}" or
            run.get("path") != ".github/workflows/harbor-helm-charts.yml" or
            run.get("event") != "workflow_dispatch" or
            run.get("head_branch") != "main" or
            run.get("status") != "completed" or
            run.get("conclusion") != "success" or
            run.get("run_attempt", 0) < 1 or not bundle_equal(sha)):
        raise ValueError("Istio chart publication is missing, stale or outside main ancestry")
    jobs = run.get("jobs")
    if (not isinstance(jobs, list) or len(jobs) != 2 or
            {job.get("name") for job in jobs} != {"validate", "publish"} or
            any(job.get("status") != "completed" or job.get("conclusion") != "success"
                for job in jobs)):
        raise ValueError("Istio chart publication jobs did not both succeed")
    required = {"validate": "Validate reviewed inventory and publisher",
                "publish": "Upload Istio Chart Digest Receipt"}
    for job in jobs:
        if (not isinstance(job.get("steps"), list) or
                sum(step.get("name") == required[job["name"]] and
                    step.get("status") == "completed" and step.get("conclusion") == "success"
                    for step in job["steps"] if isinstance(step, dict)) != 1):
            raise ValueError("Istio chart scope or authenticated reader receipt is missing")


def verify_runs(candidate, fetch_run, ancestor, candidate_at, bundle_equal,
                chart_bundle_equal):
    """Shared public run gate; protected apply separately checks private receipts."""
    phase = candidate.get("phase")
    if phase == 0:
        checked_run(candidate, None, {}, ancestor)
        checked_harbor(candidate, {}, ancestor, bundle_equal)
        checked_charts(candidate, {}, ancestor, chart_bundle_equal)
        return
    if type(phase) is not int or not 1 <= phase <= 6:
        raise ValueError("Istio phase is invalid")
    for key in ("priorRunId", "harborRunId", "chartRunId"):
        identifier = candidate.get(key)
        if not isinstance(identifier, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", identifier):
            raise ValueError("active Istio phase requires reviewed protected run IDs")
    manifests = candidate.get("chartManifestDigests")
    if (not isinstance(manifests, dict) or
            set(manifests) != {"base", "istiod", "cni", "ztunnel", "gateway"} or
            any(not isinstance(value, str) or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
                for value in manifests.values())):
        raise ValueError("active Istio phase requires five reviewed chart digests")
    prior = fetch_run(candidate["priorRunId"])
    previous = candidate_at(prior.get("head_sha"))
    checked_run(candidate, previous, prior, ancestor)
    checked_harbor(candidate, fetch_run(candidate["harborRunId"]), ancestor,
                   bundle_equal)
    checked_charts(candidate, fetch_run(candidate["chartRunId"]), ancestor,
                   chart_bundle_equal)


def main():
    candidate = json.loads((ROOT / CANDIDATE).read_text())
    phase = candidate.get("phase")
    if phase == 0:
        verify_runs(candidate, lambda _: {}, lambda _: False, lambda _: {},
                    lambda _: False, lambda _: False)
        print("Held Istio phase requires no prior runs")
        return 0
    if os.environ.get("GH_REPO") != REPOSITORY:
        raise ValueError("Istio run lookup requires the reviewed repository")
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    if event_name == "pull_request":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        base_sha = event.get("pull_request", {}).get("base", {}).get("sha")
    elif event_name == "push":
        base_sha = os.environ.get("GITHUB_SHA")
    else:
        raise ValueError("Istio admission needs a pull request or main push")
    if not isinstance(base_sha, str) or not SHA.fullmatch(base_sha):
        raise ValueError("Istio base revision is invalid")
    run_id = candidate.get("priorRunId")
    if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", run_id):
        raise ValueError("active Istio phase requires a prior protected run ID")
    def ancestor(revision):
        return subprocess.run(["git", "merge-base", "--is-ancestor", revision, base_sha],
                              cwd=ROOT, capture_output=True, timeout=15).returncode == 0
    def fetch_run(identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", identifier):
            raise ValueError("unreviewed protected run ID")
        run = json.loads(command("gh", "api", f"repos/{REPOSITORY}/actions/runs/{identifier}"))
        if run.get("path") in (".github/workflows/harbor-mirror.yml",
                               ".github/workflows/harbor-helm-charts.yml"):
            jobs = json.loads(command("gh", "api", f"repos/{REPOSITORY}/actions/runs/{identifier}/jobs"))
            if jobs.get("total_count") != 2:
                raise ValueError("full Harbor job inventory is incomplete")
            run["jobs"] = jobs.get("jobs")
        return run
    def candidate_at(revision):
        if not isinstance(revision, str) or not SHA.fullmatch(revision) or not ancestor(revision):
            raise ValueError("prior run source is not on the PR base")
        return json.loads(command("git", "show", f"{revision}:{CANDIDATE}"))
    def bundle_equal_for(paths, revision):
        return all(command("git", "rev-parse", f"{revision}:{path}") ==
                   command("git", "rev-parse", f"HEAD:{path}")
                   for path in paths)
    base = candidate_at(base_sha)
    if (not isinstance(base, dict) or type(base.get("phase")) is not int or
            phase not in (base["phase"], base["phase"] + 1)):
        raise ValueError("Istio phase cannot skip or reverse the PR base")
    verify_runs(candidate, fetch_run, ancestor, candidate_at,
                lambda revision: bundle_equal_for(PUBLICATION_BUNDLE, revision),
                lambda revision: bundle_equal_for(CHART_PUBLICATION_BUNDLE, revision))
    print(f"Istio phase {phase} follows verified protected and full Harbor runs")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            json.JSONDecodeError):
        print("Istio prior-run admission failed; source and protected run must match", file=sys.stderr)
        sys.exit(1)
