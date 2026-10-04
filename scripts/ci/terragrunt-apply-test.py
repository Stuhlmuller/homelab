#!/usr/bin/env python3
"""Exercise the actual apply shell offline; no cloud CLI is on the fixture PATH."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parent
OIDC_ENVIRONMENT = {
    "ARM_CLIENT_ID": "fixture", "ARM_TENANT_ID": "fixture", "ARM_USE_OIDC": "true",
    "ARM_USE_CLI": "false", "ARM_USE_MSI": "false",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/oidc",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fixture",
}
APPS = ["external-secrets", "cert-manager", "istio", "platform-storage"]
CRDS = ["externalsecrets.external-secrets.io", "clustersecretstores.external-secrets.io",
        "authorizationpolicies.security.istio.io", "virtualservices.networking.istio.io"]
PROJECT = {"spec": {
    "sourceRepos": ["https://github.com/Stuhlmuller/homelab.git",
                    "ghcr.io/langfuse/langfuse-k8s/charts"],
    "destinations": [{"namespace": "langfuse", "server": "https://kubernetes.default.svc"}],
    "clusterResourceWhitelist": [{"group": "", "kind": "Namespace"}],
}}

# Every external operation is enumerated. Real jq evaluates the production
# predicates; these stubs only provide inputs and verify saved-plan sequencing.
STUB = r'''
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURE_ROOT"])
config = json.loads((root / "fixture.json").read_text())
args = sys.argv[1:]
tool = Path(sys.argv[0]).name
cwd = str(Path.cwd().relative_to(root))
units = {
    "IaC/bootstrap/argocd": "bootstrap",
    "IaC/live/aws-ssm-parameters": "ssm",
    "IaC/live/langfuse-blob-storage": "s3",
    "IaC/live/kubernetes-node-labels": "nodes",
    "IaC/live/azuread-applications": "azure",
    "IaC/live/kubernetes-secrets": "secrets",
    "IaC/live/kubernetes-secrets/external-secrets-aws-ssm-auth": "secret",
    "IaC/live/argocd-apps": "apps",
    "IaC/live/argocd-apps/langfuse": "repair",
    "IaC/live/argocd-apps/fleet": "repair",
}
unit = units.get(cwd, cwd)

def event(name):
    with (root / "calls.jsonl").open("a") as log:
        log.write(json.dumps({"event": name, "tool": tool, "args": args}) + "\n")
    if config.get("fail") == name:
        sys.exit(23)

def unexpected():
    event("UNEXPECTED")
    sys.exit(99)

def plan(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    actions = ["delete", "create"] if config.get("replacement") else ["create"]
    path.write_text(json.dumps({"unit": unit, "resource_changes": [
        {"type": "kubernetes_manifest", "change": {"actions": actions}}
    ] if unit == "apps" else []}))

def checked(path):
    data = path.read_bytes()
    assert path.name == ("tfplan" if unit == "apps" else "plan.out")
    assert json.loads(data)["unit"] == unit
    receipt = path.with_suffix(".json.checked")
    assert receipt.read_text() == hashlib.sha256(data).hexdigest()

if tool == "git":
    if args[:1] == ["rev-parse"]:
        if args == ["rev-parse", "--show-toplevel"]:
            print(root)
        elif args[:3] != ["rev-parse", "--verify", "--quiet"]:
            unexpected()
    elif args[:2] == ["cat-file", "-e"]:
        pass
    elif args[:1] == ["show"] and args[1].endswith(":IaC/terragrunt.stack.hcl"):
        pass  # Both fixture revisions have no deleted units.
    elif args[:2] == ["diff", "--name-only"]:
        pass
    elif "diff" in args and "--quiet" in args:
        sys.exit(1)  # Shared inputs changed: existing full-run filters select '*'.
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
    if command == ["stack", "generate"] and cwd == "IaC":
        event("generate")
        for name in ("langfuse", "fleet", "nofx"):
            if name != config.get("missing_target"):
                path = root / "IaC/live/argocd-apps" / name / "terragrunt.hcl"
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
                              "/homelab/cordium/agent-auth-token"]
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
        assert target == (config["target"] or "*")
        assert command[4:8] == ["--non-interactive", "--parallelism", "1", "--source-update"] or (
            unit == "apps" and command[4:7] == ["--non-interactive", "--parallelism", "1"])
        tail = command[command.index("--") + 1:]
        if unit == "apps":
            path = Path(command[command.index("--out-dir") + 1]) / target / "tfplan"
            if tail == ["plan", "-no-color"]:
                assert command[command.index("--json-out-dir") + 1] == str(path.parent.parent)
                event("apps.plan")
                plan(path)
                path.with_suffix(".json").write_bytes(path.read_bytes())
            elif tail == ["apply", "-no-color"]:
                event("apps.apply")
                checked(path)
            else:
                unexpected()
        elif unit in ("azure", "secrets") and tail == ["apply", "-no-color", "-auto-approve"]:
            event(unit + ".apply")
        else:
            unexpected()
    else:
        unexpected()
else:
    unexpected()
'''


class TerragruntApplyTest(unittest.TestCase):
    def run_apply(self, target="langfuse", repair="false", **overrides):
        project = json.loads(json.dumps(PROJECT))
        app_names = APPS
        crds = CRDS
        if target in ("fleet",):
            project["spec"]["destinations"][0]["namespace"] = target
            project["spec"]["sourceRepos"] = project["spec"]["sourceRepos"][:1]
            app_names = [*APPS, "octelium-public"]
        config = {"target": target, "project": project,
                  "app_names": app_names, "crds": crds,
                  "store": {"spec": {"conditions": [{"namespaces": [target]}]}},
                  "apps": [{"metadata": {"name": name}, "status": {
                      "sync": {"status": "Synced"}, "health": {"status": "Healthy"}
                  }} for name in app_names], **overrides}
        with tempfile.TemporaryDirectory(prefix="terragrunt-apply-test-") as tmp:
            root = Path(tmp).resolve()
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("bash", "dirname", "find", "rm", "grep", "sort", "sed",
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
            for name in ("terragrunt-apply.sh", "terragrunt-filter-base.sh"):
                shutil.copyfile(SOURCE / name, scripts / name)
            for unit in ("bootstrap/argocd", "live/aws-ssm-parameters", "live/langfuse-blob-storage",
                         "live/kubernetes-node-labels", "live/azuread-applications",
                         "live/kubernetes-secrets/external-secrets-aws-ssm-auth", "live/argocd-apps"):
                (root / "IaC" / unit).mkdir(parents=True, exist_ok=True)
            (root / "fixture.json").write_text(json.dumps(config))
            environment = {"PATH": str(binaries), "FIXTURE_ROOT": str(root),
                           "RUNNER_TEMP": str(root), "APPLY_BASE_SHA": "base",
                           "APPLY_HEAD_SHA": "head", "GITHUB_EVENT_NAME": "workflow_dispatch",
                           "TERRAGRUNT_ARGOCD_APP": target,
                           "TERRAGRUNT_REPAIR_ARGOCD_APP_STATE": repair}
            if not config.get("without_azuread"):
                environment.update(config.get("azuread_environment", {
                    "ARM_CLIENT_ID": "fixture", "ARM_CLIENT_SECRET": "fixture",
                    "ARM_TENANT_ID": "fixture",
                }))
            result = subprocess.run(
                [str(binaries / "bash"), str(scripts / "terragrunt-apply.sh")],
                cwd=root, env=environment,
                text=True, capture_output=True, timeout=15, check=False)
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            self.assertNotIn("UNEXPECTED", [call["event"] for call in calls], result.stderr)
            self.assertNotIn("Traceback", result.stderr, result.stderr)
            self.assertFalse(list((root / "IaC").rglob("plan.out")))
            self.assertFalse(list(root.glob("homelab-langfuse-plan.*")))
            self.assertFalse(list(root.glob("terragrunt-argocd-apps.*")))
            return result, [call["event"] for call in calls]

    def test_targeted_order_and_checked_saved_plans(self):
        result, events = self.run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [
            "generate", "preflight.project", "preflight.apps", "preflight.crds",
            "preflight.store", "preflight.storage", "ssm.init", "ssm.state",
            "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import",
            "ssm.plan", "ssm.show", "ssm.policy", "ssm.apply", "s3.init",
            "s3.plan", "s3.show", "s3.policy", "s3.apply", "apps.plan", "apps.policy", "apps.apply",
        ])

    def test_missing_target_and_invalid_repair_do_not_write(self):
        for options in ({"missing_target": "langfuse"}, {"repair": "invalid"},
                        {"target": "fleet", "missing_target": "fleet"}):
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

    def test_generated_secret_apps_check_ssm_then_only_target_without_azuread(self):
        for target in ("fleet",):
            with self.subTest(target=target):
                result, events = self.run_apply(target=target, without_azuread=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, [
                    "generate", "preflight.project", "preflight.apps", "preflight.crds",
                    "preflight.store", "preflight.store_scope", "preflight.storage",
                    "ssm.init", "ssm.state", "ssm.lookup", "ssm.import", "ssm.lookup", "ssm.import",
                    "ssm.plan", "ssm.show", "ssm.policy", "ssm.apply",
                    "apps.plan", "apps.policy", "apps.apply",
                ])

    def test_generated_secret_apps_missing_prerequisites_fail_before_any_write(self):
        for target, access_app in (("fleet", "octelium-public"),):
            app_names = [*APPS, access_app]
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
        for target in ("fleet",):
            for failure in ("ssm.plan", "ssm.policy", "ssm.apply", "apps.plan", "apps.policy"):
                with self.subTest(target=target, failure=failure):
                    result, events = self.run_apply(target=target, fail=failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(events[-1], failure)
                    self.assertNotIn("apps.apply", events)

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
            "bootstrap.apply", "ssm.apply", "s3.apply", "nodes.apply", "azure.apply",
            "apps.apply", "namespace.apply", "secrets.apply",
        ])


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
