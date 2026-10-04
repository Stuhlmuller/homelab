#!/usr/bin/env python3
"""Exercise the real retirement shell with isolated, offline command stubs."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).parent
SHA = "a" * 40
APPLICATION = {
    "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
    "metadata": {"name": "wazuh", "namespace": "argocd"},
    "spec": {"destination": {"namespace": "wazuh"},
             "syncPolicy": {"automated": {"enabled": False}}},
}

# Network-capable tools never reach the real PATH. jq and the plan guard remain
# real; guard/policy receipts bind both approvals to the exact saved plan bytes.
STUB = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ["FIXTURE_ROOT"])
config = json.loads((root / "fixture.json").read_text())
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
unit = "app" if Path.cwd().name == "wazuh" else "ssm"
log = root / "calls.jsonl"

def event(name):
    with log.open("a") as output:
        output.write(json.dumps({"event": name, "args": args}) + "\n")
    if config.get("fail") == name:
        sys.exit(23)

def unexpected():
    event("UNEXPECTED")
    sys.exit(99)

def receipt(path, kind):
    Path(str(path) + "." + kind).write_text(hashlib.sha256(path.read_bytes()).hexdigest())

def prior(name):
    return sum(json.loads(line)["event"] == name for line in log.read_text().splitlines()) if log.exists() else 0

if tool == "git":
    if args == ["rev-parse", "--show-toplevel"]:
        print(root)
    elif args == ["rev-parse", "HEAD"]:
        event("git.head")
        print(config.get("head", "a" * 40))
    elif args == ["ls-remote", "https://github.com/Stuhlmuller/homelab.git", "refs/heads/main"]:
        event("git.main")
        stale = config.get("stale_main_at") == prior("git.main")
        print(("b" if stale else "a") * 40 + "\trefs/heads/main")
    else:
        unexpected()
elif tool == "kubectl":
    if args[:1] != ["--request-timeout=30s"]:
        unexpected()
    command = args[1:]
    resources = {
        "namespace": ["wazuh"], "pv": ["wazuh-indexer-local", "wazuh-manager-local"],
        "storageclass": ["wazuh-local"], "clusterrole": ["wazuh-collector"],
        "clusterrolebinding": ["wazuh-collector"],
    }
    if len(command) > 1 and command[0] == "get" and command[1] in resources:
        resource = command[1]
        assert command == ["get", resource, *resources[resource], "--ignore-not-found", "-o", "name"]
        event("inactive." + resource)
        if config.get("active") == resource or (
                config.get("activate_on_recheck") == resource and prior("inactive." + resource) == 2):
            print(resource + "/" + resources[resource][0])
    elif command[:5] == ["-n", "argocd", "get", "application", "wazuh"]:
        assert command[5:7] == ["--ignore-not-found", "-o"] and command[7] in ("json", "name")
        event("inactive.application." + command[7])
        exists = config["app"] is not None and (
            not (root / "app-applied").exists() or config.get("remaining") == "application")
        if exists:
            print(json.dumps(config["app"]) if command[7] == "json" else "application.argoproj.io/wazuh")
    else:
        unexpected()
elif tool == "terragrunt":
    command = [arg for arg in args if arg != "--log-disable"]
    if command == ["init", "-no-color"]:
        event(unit + ".init")
    elif command[:2] == ["plan", "-out"] and command[3:] == ["-no-color"]:
        event(unit + ".plan")
        path = Path(command[2])
        assert path.name == unit + ".plan"
        path.write_text(json.dumps(config["plans"][unit]))
    elif command[:2] == ["show", "-json"] and len(command) == 3:
        event(unit + ".show")
        print(Path(command[2]).read_text())
    elif command[:2] == ["apply", "-no-color"] and len(command) == 3:
        path = Path(command[2])
        assert path.name == unit + ".plan"
        for kind in ("app", "ssm"):
            saved = path.parent / (kind + ".plan")
            digest = hashlib.sha256(saved.read_bytes()).hexdigest()
            for approval in ("guard", "policy"):
                assert Path(str(saved) + "." + approval).read_text() == digest
        event(unit + ".apply")
        (root / (unit + "-applied")).touch()
    elif command == ["state", "list"] and unit == "app":
        event("app.state")
        if config.get("remaining") == "state":
            print("kubernetes_manifest.this")
    else:
        unexpected()
elif tool == "python3":
    assert args[:2] == ["-I", str(root / "scripts/ci/wazuh-retire-plan.py")]
    kind, path = args[2], Path(args[3])
    event(kind + ".guard")
    result = subprocess.run([sys.executable, *args], check=False)
    if result.returncode:
        sys.exit(result.returncode)
    receipt(path.with_suffix(".plan"), "guard")
elif tool == "conftest":
    assert args[:4] == ["test", "--policy", str(root / "policy"), "--data"]
    assert args[5:7] == ["--output", "github"] and len(args) == 8
    context, path = Path(args[4]), Path(args[7])
    assert context == path.parent / "retirement-policy.json"
    capability = json.loads(context.read_text())
    assert capability == {"wazuh_retirement": True} and capability["wazuh_retirement"] is True
    saved = path.with_suffix(".plan")
    assert Path(str(saved) + ".guard").read_text() == hashlib.sha256(saved.read_bytes()).hexdigest()
    event(path.stem + ".policy")
    receipt(saved, "policy")
elif tool == "aws":
    assert args == ["ssm", "describe-parameters", "--region", "us-west-2", "--parameter-filters",
                    "Key=Path,Option=Recursive,Values=/homelab/wazuh/", "--query", "Parameters[].Name",
                    "--output", "json"]
    event("ssm.absent")
    print(json.dumps(["/homelab/wazuh/leftover"] if config.get("remaining") == "ssm" else []))
else:
    unexpected()
'''


def deletion(address, kind, before):
    return {"address": address, "mode": "managed", "type": kind, "name": "this",
            "change": {"actions": ["delete"], "before": before, "after": None}}


def plan(changes=()):
    return {"format_version": "1.2", "resource_changes": list(changes)}


class WazuhRetireTest(unittest.TestCase):
    def run_retire(self, environment=None, **overrides):
        parameter = "/homelab/wazuh/api-password"
        credentials = [deletion(f'{kind}.generated["{parameter}"]', kind, before) for kind, before in (
            ("aws_ssm_parameter", {"name": parameter, "type": "SecureString", "region": "us-west-2",
                                   "arn": "arn:aws:ssm:us-west-2:716182248480:parameter" + parameter}),
            ("random_password", {"length": 40}),
        )]
        for resource in credentials:
            resource.update(name="generated", index=parameter)
        plans = {
            "app": plan([deletion("kubernetes_manifest.this", "kubernetes_manifest", {"manifest": APPLICATION})]),
            "ssm": plan(credentials),
        }
        config = {"app": APPLICATION, "plans": plans, **overrides}
        with tempfile.TemporaryDirectory(prefix="wazuh-retire-test-") as temporary:
            root = Path(temporary).resolve()
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("bash", "cut", "mktemp", "rm", "jq"):
                executable = shutil.which(name)
                self.assertIsNotNone(executable, name + " is required")
                (binaries / name).symlink_to(executable)
            for name in ("git", "kubectl", "terragrunt", "aws", "conftest", "python3"):
                path = binaries / name
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o700)
            scripts = root / "scripts/ci"
            scripts.mkdir(parents=True)
            for name in ("wazuh-retire.sh", "wazuh-retire-plan.py"):
                shutil.copyfile(SOURCE / name, scripts / name)
            for name in ("IaC/live/argocd-apps/wazuh", "IaC/live/aws-ssm-parameters", "policy"):
                (root / name).mkdir(parents=True)
            (root / "fixture.json").write_text(json.dumps(config))
            env = {"PATH": str(binaries), "FIXTURE_ROOT": str(root), "RUNNER_TEMP": str(root),
                   "GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA,
                   "TERRAGRUNT_RETIRE_WAZUH": "true", "TERRAGRUNT_ARGOCD_APP": "wazuh",
                   **(environment or {})}
            result = subprocess.run([str(binaries / "bash"), str(scripts / "wazuh-retire.sh")],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=15)
            log = root / "calls.jsonl"
            events = [json.loads(line)["event"] for line in log.read_text().splitlines()] if log.exists() else []
            self.assertNotIn("UNEXPECTED", events, result.stderr)
            self.assertNotIn("Traceback", result.stderr, result.stderr)
            self.assertFalse(list(root.glob("wazuh-retire.*")), "private plans were not removed")
            return result, events

    def assert_refused(self, **options):
        result, events = self.run_retire(**options)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(event.endswith(".apply") for event in events), events)

    def test_both_saved_plans_validated_before_first_apply(self):
        result, events = self.run_retire()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event for event in events if event.endswith(".apply")], ["app.apply", "ssm.apply"])
        first_apply = events.index("app.apply")
        for kind in ("app", "ssm"):
            order = [events.index(kind + suffix) for suffix in (".plan", ".show", ".guard", ".policy")]
            self.assertEqual(order, sorted(order))
            self.assertLess(order[-1], first_apply)
            self.assertEqual(events.count(kind + ".plan"), 1)
        self.assertEqual(events[:first_apply].count("inactive.namespace"), 2)
        self.assertEqual(events[:first_apply].count("git.main"), 2)
        self.assertLess(events.index("app.state"), events.index("ssm.apply"))
        self.assertLess(events.index("inactive.application.name"), events.index("ssm.apply"))
        self.assertLess(events.index("ssm.apply"), events.index("ssm.absent"))

    def test_active_runtime_resources_are_rejected(self):
        for resource in ("namespace", "pv", "storageclass", "clusterrole", "clusterrolebinding"):
            with self.subTest(resource=resource):
                self.assert_refused(active=resource)
        self.assert_refused(activate_on_recheck="namespace")

    def test_active_application_is_rejected(self):
        variants = []
        app = copy.deepcopy(APPLICATION)
        app["metadata"]["finalizers"] = ["resources-finalizer.argocd.argoproj.io"]
        variants.append(app)
        app = copy.deepcopy(APPLICATION)
        app["spec"]["syncPolicy"]["automated"]["enabled"] = True
        variants.append(app)
        app = copy.deepcopy(APPLICATION)
        app["operation"] = {"sync": {}}
        variants.append(app)
        for app in variants:
            with self.subTest(app=app):
                self.assert_refused(app=app)

    def test_authorization_and_revision_gates(self):
        for env in ({"TERRAGRUNT_ARGOCD_APP": "fleet"}, {"GITHUB_ACTIONS": "false"},
                    {"GITHUB_REF": "refs/heads/feature"}, {"TERRAGRUNT_RETIRE_WAZUH": "false"},
                    {"TERRAGRUNT_REPAIR_ARGOCD_APP_STATE": "true"}, {"GITHUB_SHA": "invalid"}):
            with self.subTest(env=env):
                self.assert_refused(environment=env)
        self.assert_refused(head="b" * 40)
        for revision_check in (1, 2):
            self.assert_refused(stale_main_at=revision_check)

    def test_plan_guard_and_policy_failures_never_apply(self):
        for kind in ("app", "ssm"):
            for step in ("plan", "guard", "policy"):
                with self.subTest(kind=kind, step=step):
                    self.assert_refused(fail=kind + "." + step)

    def test_failed_absence_reads_never_look_empty(self):
        for resource in ("namespace", "pv", "storageclass", "clusterrole", "clusterrolebinding", "application.json"):
            with self.subTest(resource=resource):
                self.assert_refused(fail="inactive." + resource)
        result, events = self.run_retire(fail="inactive.application.name")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("app.apply", events)
        self.assertNotIn("ssm.apply", events)

    def test_postdelete_absence_is_required(self):
        for remaining in ("state", "application", "ssm"):
            with self.subTest(remaining=remaining):
                result, events = self.run_retire(remaining=remaining)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("app.apply", events)
                if remaining != "ssm":
                    self.assertNotIn("ssm.apply", events)

    def test_already_absent_application_and_empty_state(self):
        result, events = self.run_retire(app=None, plans={kind: plan() for kind in ("app", "ssm")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event for event in events if event.endswith(".apply")], ["app.apply", "ssm.apply"])


if __name__ == "__main__":
    unittest.main()
