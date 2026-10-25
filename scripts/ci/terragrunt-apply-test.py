#!/usr/bin/env python3
"""Exercise the actual apply shell offline; no cloud CLI is on the fixture PATH."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parent
FIXTURE_SHA = "f" * 40
OIDC_ENVIRONMENT = {
    "ARM_CLIENT_ID": "fixture", "ARM_TENANT_ID": "fixture", "ARM_USE_OIDC": "true",
    "ARM_USE_CLI": "false", "ARM_USE_MSI": "false",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/oidc",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fixture",
}
APPS = ["external-secrets", "cert-manager", "istio", "platform-storage"]
TRAEFIK_APPS = ["cert-manager", "istio", "tailscale"]
CRDS = ["externalsecrets.external-secrets.io", "clustersecretstores.external-secrets.io",
        "authorizationpolicies.security.istio.io", "virtualservices.networking.istio.io"]
PROJECT = {"spec": {
    "sourceRepos": ["https://github.com/Stuhlmuller/homelab.git",
                    "ghcr.io/langfuse/langfuse-k8s/charts"],
    "destinations": [{"namespace": "langfuse", "server": "https://kubernetes.default.svc"}],
    "clusterResourceWhitelist": [{"group": "", "kind": "Namespace"}],
}}
TRAEFIK_PROJECT = {"spec": {
    "sourceRepos": ["https://github.com/Stuhlmuller/homelab.git",
                    "https://bjw-s-labs.github.io/helm-charts"],
    "destinations": [{"namespace": "traefik", "server": "https://kubernetes.default.svc"}],
    "clusterResourceWhitelist": [{"group": "", "kind": "Namespace"}],
}}
ISTIO_RENDER = {"inputs": {"manifest": json.loads(
    (SOURCE / "fixtures/istio-application-1.27.3.json").read_text())}}
ISTIO_CHART_DIGESTS = {chart: "sha256:" + ("1" * 64) for chart in
                       ("base", "istiod", "cni", "ztunnel", "gateway")}


def active_istio_candidate():
    candidate = json.loads((SOURCE.parent.parent /
        "clusters/homelab/apps/istio/upgrade-1.28.10.json").read_text())
    candidate.update(activationEnabled=True, phase=1, priorRunId="123",
                     harborRunId="456", chartRunId="789",
                     chartManifestDigests=ISTIO_CHART_DIGESTS)
    return candidate


def active_istio_render():
    rendered = json.loads(json.dumps(ISTIO_RENDER))
    manifest = rendered["inputs"]["manifest"]
    manifest["spec"]["syncPolicy"]["automated"]["prune"] = False
    source = manifest["spec"]["sources"][0]
    source.pop("chart")
    source.update(repoURL="oci://harbor.stinkyboi.com/mirror/helm/base",
                  targetRevision=ISTIO_CHART_DIGESTS["base"])
    return rendered

# Every external operation is enumerated. Real jq evaluates the production
# predicates; these stubs only provide inputs and verify saved-plan sequencing.
STUB = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["FIXTURE_ROOT"])
config = json.loads((root / "fixture.json").read_text())
args = sys.argv[1:]
tool = Path(sys.argv[0]).name
assert "GH_TOKEN" not in os.environ
cwd = str(Path.cwd().relative_to(root))
units = {
    "IaC/homelab/us-west-2/bootstrap/argocd": "bootstrap",
    "IaC/homelab/us-west-2/shared/aws-ssm-parameters": "ssm",
    "IaC/homelab/us-west-2/apps/langfuse/blob-storage": "s3",
    "IaC/homelab/us-west-2/operator/application-backup-storage": "archive-bucket",
    "IaC/homelab/us-west-2/shared/kubernetes-node-labels": "nodes",
    "IaC/homelab/us-west-2/shared/kubernetes-secrets": "secrets",
    "IaC/homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth": "secret",
    "IaC/homelab/us-west-2/apps": "apps",
    "IaC/homelab/us-west-2/apps/langfuse/argocd": "repair",
    "IaC/homelab/us-west-2/apps/fleet/argocd": "repair",
    "IaC/homelab/us-west-2/apps/mastodon/argocd": "repair",
    "IaC/homelab/us-west-2/apps/traefik/argocd": "repair",
}
unit = units.get(cwd, cwd)

def event(name):
    with (root / "calls.jsonl").open("a") as log:
        log.write(json.dumps({"event": name, "tool": tool, "args": args}) + "\n")
    if config.get("fail") == name:
        sys.exit(23)

def unexpected():
    event("UNEXPECTED")
    sys.stderr.write(f"Unexpected {tool} fixture call: {args}\n")
    sys.exit(99)

def plan(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    actions = ["delete", "create"] if config.get("replacement") else ["create"]
    document = {"unit": unit, "resource_changes": [
        {"type": "kubernetes_manifest", "change": {"actions": actions}}
    ] if unit == "apps" else []}
    if unit == "apps" and config["target"] in ("", "istio"):
        document = istio_plan()
    path.write_text(json.dumps(document))

def istio_plan():
    actions = ["update"] if config.get("istio_change") else ["no-op"]
    change = {"actions": actions}
    if actions == ["update"]:
        change["before"] = {"manifest": config["istio_before_render"]["inputs"]["manifest"]}
        change["after"] = {"manifest": config["istio_render"]["inputs"]["manifest"]}
    return {"unit": "apps", "resource_changes": [
        {"type": "kubernetes_manifest", "change": change}
    ]}

def checked(path):
    data = path.read_bytes()
    assert path.name == ("tfplan" if unit == "apps" else "plan.out")
    assert json.loads(data)["unit"] == unit
    receipt = path.with_suffix(".json.checked")
    assert receipt.read_text() == hashlib.sha256(data).hexdigest()

def bulk_apply():
    if not config.get("simulate_bulk_units"):
        event(unit + ".apply")
        return
    for number in (1, 2):
        result = subprocess.run(["bash", str(root / "scripts/ci/terragrunt-current-main.sh")],
                                env=dict(os.environ, FIXTURE_BULK_UNIT="1"),
                                text=True, capture_output=True, check=False)
        if result.returncode:
            sys.stderr.write(result.stderr)
            sys.exit(result.returncode)
        event(f"{unit}.unit{number}.apply")

if tool == "git":
    if args[:2] == ["ls-remote", "--exit-code"]:
        assert args[2:] == ["https://github.com/Stuhlmuller/homelab.git", "refs/heads/main"]
        name = "unit.main.check" if os.environ.get("FIXTURE_BULK_UNIT") else "main.check"
        event(name)
        checks = sum(json.loads(line)["event"] == name
                     for line in (root / "calls.jsonl").read_text().splitlines())
        threshold = config.get("stale_at_unit" if name == "unit.main.check" else "stale_at", 1000)
        print(("e" * 40 if checks >= threshold else config["sha"])
              + "\trefs/heads/main")
    elif args[:1] == ["rev-parse"]:
        if args == ["rev-parse", "--show-toplevel"]:
            print(root)
        elif args[:3] != ["rev-parse", "--verify", "--quiet"]:
            unexpected()
    elif args[:2] == ["cat-file", "-e"]:
        pass
    elif args[:1] == ["show"] and args[1].endswith(":IaC/terragrunt.stack.hcl"):
        pass  # Both fixture revisions have no deleted units.
    elif args[:1] == ["show"] and args[1].endswith(":IaC/root.hcl"):
        print("locals {}\ninputs = {}")
    elif args[:2] == ["diff", "--name-only"]:
        pass
    elif "diff" in args and "--quiet" in args:
        sys.exit(0 if config.get("unchanged_stack") else 1)
    else:
        unexpected()
elif tool == "kubectl":
    if args == ["-n", "argocd", "get", "appproject", "homelab", "-o", "json"]:
        event("preflight.project")
        print(json.dumps(config["project"]))
    elif args == ["-n", "argocd", "get", "applications", *config["app_names"], "-o", "json"]:
        event("preflight.apps")
        print(json.dumps({"items": config["apps"]}))
    elif args == ["wait", "--for=condition=Established", "--timeout=0s",
                  *["crd/" + name for name in config["crds"]]]:
        event("preflight.crds")
    elif args == ["wait", "--for=condition=Ready", "--timeout=0s", "clustersecretstore/aws-ssm"]:
        event("preflight.store")
    elif args == ["wait", "--for=condition=Ready", "--timeout=0s", "clusterissuer/letsencrypt-cloudflare"]:
        event("preflight.issuer")
    elif args == ["get", "clustersecretstore", "aws-ssm", "-o", "json"]:
        event("preflight.store_scope")
        print(json.dumps(config["store"]))
    elif args == ["get", "storageclass", "nfs-default", "-o", "name"]:
        event("preflight.storage")
    elif args == ["apply", "-f", "clusters/homelab/apps/external-secrets/namespace.yaml"]:
        event("namespace.apply")
    elif args == ["-n", "external-secrets", "get", "secret", "aws-ssm-auth"]:
        event("secret.get")
    else:
        unexpected()
elif tool == "aws":
    expected = ["ssm", "describe-parameters", "--region", "us-west-2", "--parameter-filters"]
    if args[:5] != expected or args[6:] != ["--query", "Parameters[0].Name", "--output", "text"]:
        unexpected()
    event("ssm.lookup")
    print(args[5].split("Values=", 1)[1])
elif tool == "conftest":
    if args[:2] != ["test", "--policy"] or args[3:5] != ["--output", "github"]:
        unexpected()
    for name in args[5:]:
        path = Path(name)
        data = path.read_bytes()
        event(json.loads(data)["unit"] + ".policy")
        Path(str(path) + ".checked").write_text(hashlib.sha256(data).hexdigest())
elif tool == "terragrunt":
    command = [arg for arg in args if arg != "--log-disable"]
    if command == ["--working-dir", "IaC/homelab/us-west-2/apps/istio/argocd",
                   "render", "--json", "--write=false", "--no-color"]:
        event("istio.render")
        print(json.dumps(config["istio_render"]))
    elif command[:1] == ["list"] and cwd == "IaC/homelab/us-west-2/apps":
        expected = "*/argocd | [main...HEAD]" if config.get("unchanged_stack") else "*/argocd"
        assert command[1:3] == ["--filter", expected]
        assert command[3:] == ["--format", "long"]
        event("apps.list")
        print("unrecognized" if config.get("malformed_list") else "Type  Path")
        if config.get("list_istio_selected", True):
            print("unit  istio/argocd")
    elif command == ["stack", "generate"] and cwd == "IaC":
        event("generate")
        for name in ("langfuse", "fleet", "mastodon", "traefik", "nofx", "istio"):
            if name != config.get("missing_target"):
                path = root / "IaC/homelab/us-west-2/apps" / name / "argocd/terragrunt.hcl"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
    elif command == ["init", "-no-color"]:
        event(unit + ".init")
    elif command == ["state", "list", "-no-color"]:
        event(unit + ".state")
        if unit == "bootstrap":
            print("helm_release.this")
        elif unit == "secret":
            print("kubernetes_secret_v1.this")
        elif unit != "ssm":
            unexpected()
    elif command[:2] == ["import", "-no-color"] and unit == "ssm":
        assert command[2] == 'aws_ssm_parameter.this["' + command[3] + '"]'
        assert command[3] in ["/homelab/github-actions-runner/registration-token",
                              "/homelab/cordium/agent-auth-token",
                              "/homelab/cordium-runners/github-app-private-key",
                              "/homelab/cordium-runners/auth-token"]
        event("ssm.import")
    elif command == ["run", "--", "untaint", "-no-color", "kubernetes_manifest.this"]:
        event("repair.untaint")
    elif command[:2] == ["plan", "-out"] and command[3:] == ["-no-color"]:
        event(unit + ".plan")
        plan(Path(command[2]))
    elif command[:2] == ["show", "-json"] and len(command) == 3:
        event(unit + ".show")
        print(Path(command[2]).read_text(), end="")
    elif command[:2] == ["apply", "-no-color"] and len(command) == 3:
        event(unit + ".apply")
        if unit == "bootstrap":
            assert command[2] == "-auto-approve"
        else:
            checked(Path(command[2]))
    elif command[:2] == ["run", "--all"]:
        target = command[command.index("--filter") + 1]
        if target.startswith("*/azuread"):
            unit = "azure"
        if config["target"]:
            assert target == config["target"] + "/argocd"
        elif unit == "azure":
            assert target.startswith("*/azuread")
        elif unit == "apps":
            assert target.startswith("*/argocd")
        else:
            assert target == "*" or target == "* | [main...HEAD]"
        assert "--non-interactive" in command and "--parallelism" in command
        tail = command[command.index("--") + 1:]
        if unit == "apps":
            unit_path = ("*/argocd" if config.get("misname_istio_plan") else "istio/argocd") \
                if config["target"] == "" else target
            path = Path(command[command.index("--out-dir") + 1]) / unit_path / "tfplan"
            if tail == ["plan", "-no-color"]:
                assert command[command.index("--json-out-dir") + 1] == str(path.parents[2])
                event("apps.plan")
                plan(path)
                if not config.get("omit_apps_plan_json"):
                    path.with_suffix(".json").write_bytes(path.read_bytes())
            elif tail == ["apply", "-no-color"]:
                checked(path)
                bulk_apply()
            else:
                unexpected()
        elif unit in ("azure", "secrets") and tail == ["apply", "-no-color", "-auto-approve"]:
            bulk_apply()
        else:
            unexpected()
    else:
        unexpected()
else:
    unexpected()
'''


class TerragruntApplyTest(unittest.TestCase):
    def run_apply(self, target="langfuse", repair="false", scope="false", **overrides):
        candidate = overrides.pop("candidate", None)
        project = json.loads(json.dumps(PROJECT))
        app_names = APPS
        crds = CRDS
        if target in ("fleet", "mastodon"):
            project["spec"]["destinations"][0]["namespace"] = target
            project["spec"]["sourceRepos"] = project["spec"]["sourceRepos"][:1]
            if target == "fleet":
                app_names = [*APPS, "traefik"]
            else:
                app_names = [*APPS, "octelium-public"]
                project["spec"]["clusterResourceWhitelist"] += [
                    {"group": "", "kind": "PersistentVolume"},
                    {"group": "storage.k8s.io", "kind": "StorageClass"},
                ]
        elif target == "traefik":
            project = json.loads(json.dumps(TRAEFIK_PROJECT))
            app_names = TRAEFIK_APPS
            crds = ["certificates.cert-manager.io", "clusterissuers.cert-manager.io",
                    "authorizationpolicies.security.istio.io"]
        config = {"target": target, "sha": FIXTURE_SHA, "project": project,
                  "app_names": app_names, "crds": crds,
                  "istio_render": ISTIO_RENDER,
                  "istio_before_render": ISTIO_RENDER,
                  "store": {"spec": {"conditions": [{"namespaces": [target]}]}},
                  "apps": [{"metadata": {"name": name}, "status": {
                      "sync": {"status": "Synced"}, "health": {"status": "Healthy"}
                  }} for name in app_names], **overrides}
        with tempfile.TemporaryDirectory(prefix="terragrunt-apply-test-") as tmp:
            root = Path(tmp).resolve()
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("bash", "dirname", "find", "rm", "grep", "sort", "sed", "python3",
                         "awk", "comm", "cat", "mktemp", "jq"):
                executable = shutil.which(name)
                self.assertIsNotNone(executable, name + " is required for this offline test")
                (binaries / name).symlink_to(executable)
            for name in ("git", "terragrunt", "kubectl", "aws", "conftest", "helm"):
                path = binaries / name
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o700)
            scripts = root / "scripts/ci"
            scripts.mkdir(parents=True)
            for name in ("terragrunt-apply.sh", "terragrunt-filter-base.sh",
                         "terragrunt-current-main.sh", "istio-upgrade-gate.py"):
                shutil.copyfile(SOURCE / name, scripts / name)
            (scripts / "fixtures").mkdir()
            shutil.copyfile(SOURCE / "fixtures/istio-application-1.27.3.json",
                            scripts / "fixtures/istio-application-1.27.3.json")
            (root / "scripts/istio-upgrade.py").write_text(
                "import json, os, pathlib, sys\n"
                "assert sys.argv[1:4] == ['preapply', '--phase', '1']\n"
                "with (pathlib.Path(os.environ['FIXTURE_ROOT']) / 'calls.jsonl').open('a') as log:\n"
                "    log.write(json.dumps({'event': 'istio.preapply', 'tool': 'python3', "
                "'args': sys.argv[1:]}) + '\\n')\n"
                "sys.exit(43)\n")
            candidate_target = root / "clusters/homelab/apps/istio/upgrade-1.28.10.json"
            candidate_target.parent.mkdir(parents=True)
            candidate_target.write_text(json.dumps(candidate or json.loads(
                (SOURCE.parent.parent / "clusters/homelab/apps/istio/upgrade-1.28.10.json").read_text())))
            for name in ("values.yaml", "octelium-api-gateway-values.yaml", "kustomization.yaml",
                         "certificate.yaml", "namespace.yaml", "octelium-api-gateway.yaml",
                         "tailnet-gateway.yaml"):
                shutil.copyfile(SOURCE.parent.parent / "clusters/homelab/apps/istio" / name,
                                candidate_target.parent / name)
            overlays = candidate_target.parent / "upgrade-1.28.10"
            overlays.mkdir()
            for name in ("istiod-images.json", "istiod-final-images.json", "cni-images.json",
                         "ztunnel-images.json", "gateway-images.json"):
                shutil.copyfile(SOURCE.parent.parent / "clusters/homelab/apps/istio/upgrade-1.28.10" / name,
                                overlays / name)
            shutil.copyfile(SOURCE.parent.parent / ".argocd-values-ref-placeholder.yaml",
                            root / ".argocd-values-ref-placeholder.yaml")
            for unit in ("homelab/us-west-2/bootstrap/argocd",
                         "homelab/us-west-2/shared/aws-ssm-parameters",
                         "homelab/us-west-2/apps/langfuse/blob-storage",
                         "homelab/us-west-2/operator/application-backup-storage",
                         "homelab/us-west-2/shared/kubernetes-node-labels",
                         "homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth",
                         "homelab/us-west-2/apps"):
                (root / "IaC" / unit).mkdir(parents=True, exist_ok=True)
            (root / "fixture.json").write_text(json.dumps(config))
            environment = {"PATH": str(binaries), "FIXTURE_ROOT": str(root),
                           "RUNNER_TEMP": str(root), "APPLY_BASE_SHA": "base",
                           "APPLY_HEAD_SHA": "head", "GITHUB_EVENT_NAME": "workflow_dispatch",
                           "TERRAGRUNT_ARGOCD_APP": target,
                           "ISTIO_PHASE": str(config.get("istio_phase", "")),
                           "TERRAGRUNT_REPAIR_ARGOCD_APP_STATE": repair,
                           "TERRAGRUNT_APPLICATION_BACKUP_STORAGE": scope}
            if not config.get("without_azuread"):
                environment.update(config.get("azuread_environment", {
                    "ARM_CLIENT_ID": "fixture", "ARM_CLIENT_SECRET": "fixture",
                    "ARM_TENANT_ID": "fixture",
                }))
            if config.get("github_actions"):
                environment.update(GITHUB_ACTIONS="true", GITHUB_SHA=FIXTURE_SHA,
                                   GITHUB_REF="refs/heads/main", GITHUB_REPOSITORY="Stuhlmuller/homelab")
            result = subprocess.run(
                [str(binaries / "bash"), str(scripts / "terragrunt-apply.sh")],
                cwd=root, env=environment,
                text=True, capture_output=True, timeout=15, check=False)
            calls_file = root / "calls.jsonl"
            calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
            self.assertNotIn("UNEXPECTED", [call["event"] for call in calls], result.stderr)
            self.assertNotIn("Traceback", result.stderr, result.stderr)
            self.assertFalse(list((root / "IaC").rglob("plan.out")))
            self.assertFalse(list(root.glob("homelab-langfuse-plan.*")))
            self.assertFalse(list(root.glob("homelab-openclaw-archive-plan.*")))
            self.assertFalse(list(root.glob("terragrunt-argocd-apps.*")))
            return result, [call["event"] for call in calls]

    def test_targeted_order_and_checked_saved_plans(self):
        result, events = self.run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [
            "generate", "preflight.project", "preflight.apps", "preflight.crds",
            "preflight.store", "preflight.storage", "ssm.init", "ssm.state",
            "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import",
            "ssm.plan", "ssm.show", "ssm.policy", "ssm.apply", "s3.init",
            "s3.plan", "s3.show", "s3.policy", "s3.apply", "apps.plan", "apps.policy", "apps.apply",
        ])

    def test_active_istio_phase_stops_before_any_argocd_apply(self):
        candidate = active_istio_candidate()
        rendered = active_istio_render()
        result, events = self.run_apply(target="istio", candidate=candidate,
                                        istio_render=rendered, istio_change=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active Istio phase requires protected one-component admission", result.stderr)
        self.assertIn("istio.render", events)
        self.assertNotIn("apps.apply", events)

    def test_active_phase_calls_private_preapply_before_any_application_write(self):
        candidate = active_istio_candidate()
        rendered = active_istio_render()
        result, events = self.run_apply(target="istio", candidate=candidate,
                                        istio_render=rendered, istio_change=True,
                                        istio_phase=1, github_actions=True)
        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertIn("istio.preapply", events)
        self.assertNotIn("apps.apply", events)

    def test_phase_input_rejects_full_or_other_application_scope(self):
        for target in ("", "nofx"):
            with self.subTest(target=target):
                result, events = self.run_apply(target=target, istio_phase=1)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Istio phase requires an unrepaired targeted", result.stderr)
                self.assertNotIn("apps.apply", events)

    def test_changed_istio_source_with_disabled_phase_stops_before_apply(self):
        rendered = json.loads(json.dumps(ISTIO_RENDER))
        rendered["inputs"]["manifest"]["spec"]["sources"][0]["targetRevision"] = "1.28.10"
        result, events = self.run_apply(target="istio", istio_render=rendered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Istio Application must match the ordered immutable OCI source", result.stderr)
        self.assertIn("istio.render", events)
        self.assertNotIn("apps.apply", events)

    def test_full_apply_allows_a_no_op_istio_registration(self):
        result, events = self.run_apply(target="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("istio.render", events)
        self.assertIn("apps.apply", events)

    def test_full_apply_rejects_missing_or_misnamed_selected_istio_plan(self):
        for options in ({"misname_istio_plan": True}, {"omit_apps_plan_json": True}):
            with self.subTest(options=options):
                result, events = self.run_apply(target="", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Selected Istio Application has no saved plan", result.stderr)
                self.assertNotIn("apps.apply", events)

    def test_changed_full_filter_rejects_missing_selected_istio_plan(self):
        result, events = self.run_apply(target="", unchanged_stack=True,
                                        omit_apps_plan_json=True, list_istio_selected=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Selected Istio Application has no saved plan", result.stderr)
        self.assertIn("apps.list", events)
        self.assertNotIn("apps.apply", events)

    def test_changed_full_filter_rejects_unrecognized_selection_output(self):
        result, events = self.run_apply(target="", unchanged_stack=True,
                                        omit_apps_plan_json=True, malformed_list=True,
                                        list_istio_selected=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unrecognized Argo CD Application selection output", result.stderr)
        self.assertIn("apps.list", events)
        self.assertNotIn("apps.apply", events)

    def test_targeted_istio_rejects_absent_plan(self):
        result, events = self.run_apply(target="istio", omit_apps_plan_json=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Selected Istio Application has no saved plan", result.stderr)
        self.assertNotIn("apps.apply", events)

    def test_full_apply_accepts_excluded_istio_without_a_plan(self):
        result, events = self.run_apply(target="", unchanged_stack=True,
                                        omit_apps_plan_json=True,
                                        list_istio_selected=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apps.list", events)
        self.assertNotIn("istio.render", events)
        self.assertNotIn("apps.apply", events)

    def test_unrelated_target_does_not_consume_the_istio_gate(self):
        rendered = json.loads(json.dumps(ISTIO_RENDER))
        rendered["inputs"]["manifest"]["spec"]["sources"][0]["targetRevision"] = "unreviewed"
        result, events = self.run_apply(target="nofx", istio_render=rendered)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("istio.render", events)
        self.assertIn("apps.apply", events)

    def test_github_apply_checks_current_main_before_each_mutation(self):
        for target in ("langfuse", ""):
            with self.subTest(target=target):
                result, events = self.run_apply(target=target, github_actions=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                writes = [index for index, event in enumerate(events)
                          if event.endswith((".import", ".apply", ".untaint"))]
                self.assertTrue(writes)
                self.assertTrue(all(events[index - 1] == "main.check" for index in writes), events)

    def test_main_advancing_between_stages_blocks_later_apply(self):
        result, events = self.run_apply(github_actions=True, stale_at=6)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ssm.apply", events)
        self.assertEqual(events[-1], "main.check")
        self.assertNotIn("s3.apply", events)
        self.assertNotIn("apps.apply", events)
        self.assertIn("Main advanced after dispatch", result.stderr)

    def test_main_lookup_failure_blocks_first_write(self):
        result, events = self.run_apply(github_actions=True, fail="main.check")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events[-1], "main.check")
        self.assertFalse(any(event.endswith((".import", ".apply")) for event in events))
        self.assertIn("Unable to verify current main", result.stderr)

    def test_each_bulk_unit_rechecks_main_without_provider_token(self):
        for stale_at, allowed, denied in (
            (2, "azure.unit1.apply", "azure.unit2.apply"),
            (4, "apps.unit1.apply", "apps.unit2.apply"),
            (6, "secrets.unit1.apply", "secrets.unit2.apply"),
        ):
            with self.subTest(stale_at=stale_at):
                result, events = self.run_apply(target="", github_actions=True,
                                                simulate_bulk_units=True, stale_at_unit=stale_at)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(allowed, events)
                self.assertNotIn(denied, events)
                self.assertEqual(events[-1], "unit.main.check")
                self.assertIn("Main advanced after dispatch", result.stderr)

    def test_bulk_unit_main_lookup_failure_blocks_first_unit(self):
        result, events = self.run_apply(target="", github_actions=True,
                                        simulate_bulk_units=True, fail="unit.main.check")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events[-1], "unit.main.check")
        self.assertNotIn("azure.unit1.apply", events)
        self.assertIn("Unable to verify current main", result.stderr)

    def test_root_hook_reaches_each_bulk_apply_family(self):
        repo = SOURCE.parent.parent
        guard = (repo / "scripts/ci/terragrunt-current-main.sh").resolve()
        for unit in ("homelab/us-west-2/apps/grafana/azuread", "homelab/us-west-2/apps/n8n/argocd",
                     "homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth"):
            with self.subTest(unit=unit):
                result = subprocess.run(
                    ["terragrunt", "--log-disable", "--working-dir", str(repo / "IaC" / unit),
                     "render", "--json", "--write=false", "--no-color"],
                    cwd=repo, text=True, capture_output=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                hook = json.loads(result.stdout)["terraform"]["before_hook"]["verify_current_main_before_apply"]
                self.assertEqual(hook["commands"], ["apply"])
                self.assertEqual(Path(hook["execute"][1]).resolve(), guard)

    def test_bootstrap_after_hook_rechecks_main_before_each_manifest(self):
        repo = SOURCE.parent.parent
        catalog = repo / "IaC/terragrunt-catalog/units/bootstrap/argocd/terragrunt.hcl"
        generated = repo / "IaC/homelab/us-west-2/bootstrap/argocd/terragrunt.hcl"
        self.assertEqual(generated.read_text(), catalog.read_text())
        rendered = subprocess.run(
            ["terragrunt", "--log-disable", "--working-dir", str(generated.parent),
             "render", "--json", "--write=false", "--no-color"],
            cwd=repo, text=True, capture_output=True, timeout=10, check=False)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        hook = json.loads(rendered.stdout)["terraform"]["after_hook"]["apply_self_management_application"]
        self.assertEqual(hook["commands"], ["apply"])
        self.assertEqual(hook["execute"][:2], ["sh", "-c"])

        stub = r'''
import json
import os
from pathlib import Path
import sys

events_path = Path(os.environ["FIXTURE_EVENTS"])
tool = Path(sys.argv[0]).name
args = sys.argv[1:]

def event(name):
    with events_path.open("a") as log:
        log.write(json.dumps(name) + "\n")

if tool == "git":
    assert args == ["ls-remote", "--exit-code",
                    "https://github.com/Stuhlmuller/homelab.git", "refs/heads/main"]
    event("main.check")
    checks = sum(json.loads(line) == "main.check" for line in events_path.read_text().splitlines())
    current = os.environ["GITHUB_SHA"] if checks < int(os.environ["STALE_AT"]) else "e" * 40
    print(current + "\trefs/heads/main")
elif tool == "kubectl":
    if args[0] == "wait":
        event("wait")
    elif args[:2] == ["apply", "-f"]:
        event(Path(args[2]).name)
    else:
        sys.exit(99)
else:
    sys.exit(99)
'''
        manifests = ["appproject.yaml", "workloads-appproject.yaml", "application.yaml"]
        with tempfile.TemporaryDirectory(prefix="argocd-after-hook-test-") as tmp:
            root = Path(tmp)
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("git", "kubectl"):
                path = binaries / name
                path.write_text(f"#!{sys.executable}\n" + stub)
                path.chmod(0o700)
            events_path = root / "events.jsonl"
            environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                               FIXTURE_EVENTS=str(events_path), GITHUB_ACTIONS="true",
                               GITHUB_SHA=FIXTURE_SHA, GITHUB_REF="refs/heads/main",
                               GITHUB_REPOSITORY="Stuhlmuller/homelab")
            for stale_at in (1, 2, 3, 4):
                with self.subTest(stale_at=stale_at):
                    events_path.write_text("")
                    result = subprocess.run(
                        hook["execute"], cwd=repo,
                        env=dict(environment, STALE_AT=str(stale_at)),
                        text=True, capture_output=True, timeout=10, check=False)
                    events = [json.loads(line) for line in events_path.read_text().splitlines()]
                    expected = ["wait", "wait"]
                    for manifest in manifests[:stale_at - 1]:
                        expected.extend(("main.check", manifest))
                    if stale_at <= len(manifests):
                        expected.append("main.check")
                    self.assertEqual(events, expected)
                    self.assertEqual(result.returncode == 0, stale_at == 4, result.stderr)

    def test_missing_target_and_invalid_repair_do_not_write(self):
        for options in ({"missing_target": "langfuse"}, {"repair": "invalid"},
                        {"target": "fleet", "missing_target": "fleet"},
                        {"target": "traefik", "missing_target": "traefik"}):
            with self.subTest(options=options):
                result, events = self.run_apply(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, ["generate"])

    def test_preflight_fails_before_repair_or_prerequisite_writes(self):
        variants = []
        for field in ("sourceRepos", "destinations", "clusterResourceWhitelist"):
            project = json.loads(json.dumps(PROJECT))
            project["spec"][field] = []
            variants.append({"project": project})
        for source in PROJECT["spec"]["sourceRepos"]:
            project = json.loads(json.dumps(PROJECT))
            project["spec"]["sourceRepos"].remove(source)
            variants.append({"project": project})
        for field, key in (("destinations", "namespace"), ("destinations", "server"),
                           ("clusterResourceWhitelist", "group"),
                           ("clusterResourceWhitelist", "kind")):
            project = json.loads(json.dumps(PROJECT))
            project["spec"][field][0][key] = "wrong"
            variants.append({"project": project})
        variants.append({"apps": []})
        for field, status in (("sync", "OutOfSync"), ("health", "Degraded")):
            apps = [{"status": {"sync": {"status": "Synced"},
                                "health": {"status": "Healthy"}}} for _ in APPS]
            apps[0]["status"][field]["status"] = status
            variants.append({"apps": apps})
        variants.extend({"fail": "preflight." + name}
                        for name in ("project", "apps", "crds", "store", "storage"))
        for options in variants:
            with self.subTest(options=options):
                result, events = self.run_apply(repair="true", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(event == "generate" or event.startswith("preflight.")
                                    for event in events), events)

    def test_plan_or_policy_failure_stops_later_stages(self):
        for stage in ("ssm", "s3", "apps"):
            for operation in ("plan", "policy"):
                with self.subTest(stage=stage, operation=operation):
                    result, events = self.run_apply(fail=stage + "." + operation)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(events[-1], stage + "." + operation)
                    self.assertNotIn(stage + ".apply", events)

    def test_application_replacement_is_rejected(self):
        result, events = self.run_apply(replacement=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events[-1], "apps.policy")
        self.assertNotIn("apps.apply", events)

    def test_unrelated_target_has_no_langfuse_prerequisites(self):
        result, events = self.run_apply(target="nofx")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["generate", "apps.plan", "apps.policy", "apps.apply"])

    def test_traefik_checks_only_its_platform_prerequisites_before_saved_plan(self):
        result, events = self.run_apply(target="traefik", without_azuread=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [
            "generate", "preflight.project", "preflight.apps", "preflight.crds",
            "preflight.issuer", "apps.plan", "apps.policy", "apps.apply",
        ])

    def test_traefik_prerequisites_fail_before_repair_or_any_apply(self):
        variants = [{"project": PROJECT}, {"apps": []}]
        for source in TRAEFIK_PROJECT["spec"]["sourceRepos"]:
            project = json.loads(json.dumps(TRAEFIK_PROJECT))
            project["spec"]["sourceRepos"].remove(source)
            variants.append({"project": project})
        for field in ("destinations", "clusterResourceWhitelist"):
            project = json.loads(json.dumps(TRAEFIK_PROJECT))
            project["spec"][field] = []
            variants.append({"project": project})
        for name in TRAEFIK_APPS:
            for field, status in (("sync", "OutOfSync"), ("health", "Degraded")):
                apps = [{"metadata": {"name": app}, "status": {
                    "sync": {"status": "Synced"}, "health": {"status": "Healthy"},
                }} for app in TRAEFIK_APPS]
                next(app for app in apps if app["metadata"]["name"] == name)["status"][field]["status"] = status
                variants.append({"apps": apps})
        variants.extend({"fail": "preflight." + name}
                        for name in ("project", "apps", "crds", "issuer"))
        for options in variants:
            with self.subTest(options=options):
                result, events = self.run_apply(target="traefik", repair="true", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(event == "generate" or event.startswith("preflight.")
                                    for event in events), events)

    def test_generated_secret_apps_check_ssm_then_only_target_without_azuread(self):
        for target in ("fleet", "mastodon"):
            with self.subTest(target=target):
                result, events = self.run_apply(target=target, without_azuread=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, [
                    "generate", "preflight.project", "preflight.apps", "preflight.crds",
                    "preflight.store", "preflight.store_scope", "preflight.storage",
                    "ssm.init", "ssm.state", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import",
                    "ssm.plan", "ssm.show", "ssm.policy", "ssm.apply",
                    "apps.plan", "apps.policy", "apps.apply",
                ])

    def test_generated_secret_apps_missing_prerequisites_fail_before_any_write(self):
        for target, access_app in (("fleet", "traefik"), ("mastodon", "octelium-public")):
            app_names = [*APPS, *([access_app] if access_app else [])]
            variants = [
                {"project": PROJECT},  # Project permits Langfuse, not this target.
                {"apps": []},
                {"store": {"spec": {"conditions": [{"namespaces": ["langfuse"]}]}}},
                {"store": {"spec": {}}},
                {"fail": "preflight.crds"},
                {"fail": "preflight.store_scope"},
            ]
            for name in app_names:
                apps = [{"metadata": {"name": app}, "status": {
                    "sync": {"status": "OutOfSync" if app == name else "Synced"},
                    "health": {"status": "Healthy"},
                }} for app in app_names]
                variants.append({"apps": apps})
            for options in variants:
                with self.subTest(target=target, options=options):
                    result, events = self.run_apply(target=target, repair="true", **options)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(all(event == "generate" or event.startswith("preflight.")
                                        for event in events), events)

    def test_generated_secret_apps_failures_stop_later_stages(self):
        for target in ("fleet", "mastodon"):
            for failure in ("ssm.plan", "ssm.policy", "ssm.apply", "apps.plan", "apps.policy"):
                with self.subTest(target=target, failure=failure):
                    result, events = self.run_apply(target=target, fail=failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(events[-1], failure)
                    self.assertNotIn("apps.apply", events)

    def test_mastodon_requires_cluster_storage_permissions_before_any_write(self):
        for missing in ("PersistentVolume", "StorageClass"):
            project = json.loads(json.dumps(PROJECT))
            project["spec"]["destinations"][0]["namespace"] = "mastodon"
            project["spec"]["clusterResourceWhitelist"] += [
                {"group": "", "kind": "PersistentVolume"},
                {"group": "storage.k8s.io", "kind": "StorageClass"},
            ]
            project["spec"]["clusterResourceWhitelist"] = [
                resource for resource in project["spec"]["clusterResourceWhitelist"]
                if resource["kind"] != missing
            ]
            result, events = self.run_apply(target="mastodon", project=project)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(events, ["generate", "preflight.project"])

    def test_full_apply_still_requires_changed_azuread_credentials(self):
        result, events = self.run_apply(target="", without_azuread=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ["generate"])
        self.assertIn("AzureAD credentials are required", result.stderr)

    def test_full_apply_uses_github_oidc_without_a_client_secret(self):
        result, events = self.run_apply(target="", azuread_environment=OIDC_ENVIRONMENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("azure.apply", events)

    def test_incomplete_oidc_stops_full_apply_before_any_write(self):
        for missing in ("ARM_CLIENT_ID", "ARM_TENANT_ID", "ACTIONS_ID_TOKEN_REQUEST_URL",
                        "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
            with self.subTest(missing=missing):
                environment = {key: value for key, value in OIDC_ENVIRONMENT.items() if key != missing}
                # Selecting OIDC must not silently fall back to a client secret.
                environment.update(ARM_CLIENT_SECRET="fixture")
                result, events = self.run_apply(target="", azuread_environment=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, ["generate"])
                self.assertIn("AzureAD credentials are required", result.stderr)

    def test_full_sequence_is_unchanged(self):
        result, events = self.run_apply(target="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(event.startswith("preflight.") for event in events))
        self.assertEqual([event for event in events if event.endswith(".apply")], [
            "archive-bucket.apply", "bootstrap.apply", "ssm.apply", "s3.apply", "nodes.apply", "azure.apply",
            "apps.apply", "namespace.apply", "secrets.apply",
        ])

    def test_backup_storage_scope_is_isolated_and_checks_saved_plan(self):
        result, events = self.run_apply(target="", scope="true", without_azuread=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["generate", "archive-bucket.init", "archive-bucket.plan",
                                  "archive-bucket.show", "archive-bucket.policy", "archive-bucket.apply"])
        for failure in ("archive-bucket.plan", "archive-bucket.policy"):
            with self.subTest(failure=failure):
                result, events = self.run_apply(target="", scope="true", fail=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events[-1], failure)
                self.assertNotIn("archive-bucket.apply", events)

    def test_backup_storage_scope_rejects_other_targets_before_write(self):
        for options in ({"target": "openclaw", "scope": "true"},
                        {"target": "", "repair": "true", "scope": "true"},
                        {"target": "", "scope": "invalid"}):
            with self.subTest(options=options):
                result, events = self.run_apply(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, [])


class AzureADCredentialsTest(unittest.TestCase):
    def test_plan_and_apply_readiness(self):
        secret = {"ARM_CLIENT_ID": "fixture", "ARM_TENANT_ID": "fixture",
                  "ARM_CLIENT_SECRET": "fixture"}
        cases = [(OIDC_ENVIRONMENT, True), (secret, True), ({}, False),
                 ({**secret, "ARM_USE_OIDC": "invalid"}, False),
                 ({**secret, "ARM_USE_OIDC": "true"}, False)]
        for missing in ("ARM_CLIENT_ID", "ARM_TENANT_ID", "ACTIONS_ID_TOKEN_REQUEST_URL",
                        "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
            cases.append(({key: value for key, value in OIDC_ENVIRONMENT.items()
                           if key != missing}, False))
        for script in ("terragrunt-plan.sh", "terragrunt-apply.sh"):
            source = (SOURCE / script).read_text()
            start = source.index("azuread_credentials_available() {")
            end = source.index("\n}", start) + 2
            command = source[start:end] + "\nazuread_credentials_available\n"
            for environment, expected in cases:
                with self.subTest(script=script, keys=sorted(environment), expected=expected):
                    result = subprocess.run([shutil.which("bash"), "-c", command],
                                            env=environment, text=True, capture_output=True,
                                            timeout=5, check=False)
                    self.assertEqual(result.returncode == 0, expected, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
