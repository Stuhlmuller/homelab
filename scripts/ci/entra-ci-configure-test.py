#!/usr/bin/env python3
"""Offline checks for the fixed Entra-to-GitHub credential bridge."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "entra-ci-configure.py"
SPEC = importlib.util.spec_from_file_location("entra_ci_configure", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CLIENTS = {"plan": "11111111-1111-4111-8111-111111111111",
           "apply": "22222222-2222-4222-8222-222222222222"}
TENANT = "33333333-3333-4333-8333-333333333333"
OUTPUTS = {"client_ids": {"sensitive": True, "value": CLIENTS},
           "tenant_id": {"sensitive": True, "value": TENANT}}
SHA = "a" * 40


def protection(environment):
    rules = [{"type": "required_reviewers", "prevent_self_review": False,
              "reviewers": [{"type": "User", "reviewer": {"id": 57728706}}]}]
    policy = None
    if environment == "homelab-production":
        rules.append({"type": "branch_policy"})
        policy = {"protected_branches": True, "custom_branch_policies": False}
    return {"name": environment, "can_admins_bypass": False,
            "deployment_branch_policy": policy, "protection_rules": rules}


class FakeCommands:
    def __init__(self):
        self.outputs = deepcopy(OUTPUTS)
        self.environments = {name: protection(name) for name in MODULE.ENVIRONMENTS.values()}
        self.names = {}
        self.dirty = ""
        self.main = {"sha": SHA, "commit": {"verification": {"verified": True}}}
        self.protected = True
        self.calls = []
        self.writes = []

    def __call__(self, args, operation, *, data=None):
        self.calls.append((args, operation, data))
        if args[:3] == ["git", "status", "--porcelain=v1"]:
            return self.dirty
        if args == ["git", "rev-parse", "HEAD"]:
            return SHA
        if args[0] == "terragrunt":
            return json.dumps(self.outputs)
        if args[:4] == ["gh", "api", "--hostname", "github.com"]:
            path = args[-1]
            if path.endswith("/commits/main"):
                return json.dumps(self.main)
            if path.endswith("/branches/main"):
                return json.dumps({"protected": self.protected})
            return json.dumps(self.environments[path.rsplit("/", 1)[1]])
        if args[:2] in (["gh", "secret"], ["gh", "variable"]):
            environment = args[args.index("--env") + 1] if "--env" in args else None
            if args[2] == "list":
                return json.dumps(self.names.get((args[1], environment), []))
            if args[2] == "set":
                self.writes.append((args, data))
                return "private success response"
        raise AssertionError("Unexpected external command")


class EntraCIConfigureTest(unittest.TestCase):
    def run_script(self, fake, argv=None):
        output = io.StringIO()
        with patch.object(MODULE, "command", side_effect=fake), \
                redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main(argv or [])
        for value in (*CLIENTS.values(), TENANT):
            self.assertNotIn(value, output.getvalue())
        return status, output.getvalue()

    def test_default_dry_run_checks_guards_without_writing(self):
        fake = FakeCommands()
        status, output = self.run_script(fake)
        self.assertEqual(status, 0, output)
        self.assertEqual(fake.writes, [])
        self.assertIn("Dry run passed", output)
        self.assertEqual(set(fake.environments), {"homelab-plan", "homelab-production"})
        self.assertEqual(len([args for args, _, _ in fake.calls if "api" in args]), 3)

    def test_execute_publishes_only_four_exact_settings_over_stdin(self):
        fake = FakeCommands()
        status, output = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 0, output)
        expected = []
        for identity, environment in MODULE.ENVIRONMENTS.items():
            for name, value in (("AZUREAD_CLIENT_ID", CLIENTS[identity]), ("AZUREAD_TENANT_ID", TENANT)):
                expected.append((["gh", "secret", "set", name, "--repo", "github.com/Stuhlmuller/homelab",
                                  "--env", environment], value + "\n"))
        self.assertEqual(fake.writes, expected)
        for args, _ in fake.writes:
            self.assertNotIn("--body", args)
            self.assertTrue(all(value not in " ".join(args) for value in (*CLIENTS.values(), TENANT)))
        first_write = next(index for index, (args, _, _) in enumerate(fake.calls) if "set" in args)
        before = fake.calls[:first_write]
        self.assertEqual(sum(operation == "verified main lookup" for _, operation, _ in before), 2)
        self.assertEqual(sum(operation == "environment protection lookup" for _, operation, _ in before), 4)

    def test_invalid_identity_outputs_never_publish(self):
        invalid = [None, {}, {"client_ids": {"value": CLIENTS}},
                   {**OUTPUTS, "tenant_id": {"sensitive": False, "value": TENANT}}]
        for value in ("invalid", "00000000-0000-0000-0000-000000000000", CLIENTS["apply"], None, 42):
            item = deepcopy(OUTPUTS)
            item["client_ids"]["value"]["plan"] = value
            invalid.append(item)
        for outputs in invalid:
            with self.subTest(outputs=outputs):
                fake = FakeCommands()
                fake.outputs = outputs
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])

    def test_invalid_environment_guards_never_publish(self):
        for environment in MODULE.ENVIRONMENTS.values():
            fixtures = []
            for key, value in (("can_admins_bypass", True), ("name", "wrong"),
                               ("deployment_branch_policy", {}), ("protection_rules", [])):
                document = protection(environment)
                document[key] = value
                fixtures.append(document)
            for key, value in (("prevent_self_review", True),
                               ("reviewers", [{"type": "User", "reviewer": {"id": 1}}]),
                               ("reviewers", [{"type": "Team", "reviewer": {"id": 57728706}}])):
                document = protection(environment)
                document["protection_rules"][0][key] = value
                fixtures.append(document)
            document = protection(environment)
            document["protection_rules"].append(deepcopy(document["protection_rules"][0]))
            fixtures.append(document)
            document = protection(environment)
            del document["can_admins_bypass"]
            fixtures.append(document)
            for document in fixtures:
                with self.subTest(environment=environment, document=document):
                    fake = FakeCommands()
                    fake.environments[environment] = document
                    status, _ = self.run_script(fake, ["--execute"])
                    self.assertEqual(status, 1)
                    self.assertEqual(fake.writes, [])

    def test_existing_client_secrets_block(self):
        for scope in (None, *MODULE.ENVIRONMENTS.values()):
            with self.subTest(scope=scope):
                fake = FakeCommands()
                fake.names["secret", scope] = [{"name": "AZUREAD_CLIENT_SECRET"}]
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])

    def test_execution_requires_clean_verified_current_main(self):
        for variant in ("dirty", "stale", "unsigned", "unprotected"):
            with self.subTest(variant=variant):
                fake = FakeCommands()
                if variant == "dirty":
                    fake.dirty = "?? untracked-file\n"
                elif variant == "stale":
                    fake.main["sha"] = "b" * 40
                elif variant == "unsigned":
                    fake.main["commit"]["verification"]["verified"] = False
                else:
                    fake.protected = False
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])

    def test_main_change_during_preflight_stops_publication(self):
        fake = FakeCommands()
        with patch.object(MODULE, "verify_main", side_effect=[SHA, "b" * 40]):
            status, _ = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 1)
        self.assertEqual(fake.writes, [])

    def test_subprocess_output_and_exceptions_stay_private(self):
        private = "synthetic-private-command-output"
        outcomes = [subprocess.CompletedProcess([], 1, private, private),
                    subprocess.TimeoutExpired([private], 120, output=private, stderr=private),
                    OSError(private)]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(MODULE.subprocess, "run", **kwargs) as run:
                    with self.assertRaises(MODULE.Failure) as failure:
                        MODULE.command(["gh", "secret", "set", "AZUREAD_CLIENT_ID"],
                                       "protected environment ID publication", data=private)
                self.assertNotIn(private, str(failure.exception))
                self.assertEqual(run.call_args.kwargs["input"], private)
                self.assertTrue(run.call_args.kwargs["capture_output"])


if __name__ == "__main__":
    unittest.main()
