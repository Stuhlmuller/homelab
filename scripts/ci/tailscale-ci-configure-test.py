#!/usr/bin/env python3
"""Offline checks for the fixed Tailscale-to-GitHub variable bridge."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("tailscale_configure", ROOT / "scripts/tailscale-ci-configure.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
# Reuse the tested owner-review fixture and command boundary, not production credentials.
BASE_SPEC = importlib.util.spec_from_file_location("entra_test", ROOT / "scripts/ci/entra-ci-configure-test.py")
BASE = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(BASE)
# Key.id example from Tailscale's OpenAPI schema; these are synthetic IDs.
CLIENTS = {"plan": "k123456CNTRL", "apply": "k223456CNTRL", "cordium": "k323456CNTRL"}
OUTPUTS = {"github_identity_client_ids": {"sensitive": False, "value": CLIENTS}}


class FakeCommands(BASE.FakeCommands):
    def __init__(self):
        super().__init__()
        self.outputs = deepcopy(OUTPUTS)
        self.readback_wrong = False

    def __call__(self, args, operation, *, data=None):
        if args[:4] == ["gh", "api", "--hostname", "github.com"] and "/variables/" in args[-1]:
            self.calls.append((args, operation, data))
            for identity, (environment, name) in MODULE.BINDINGS.items():
                prefix = f"environments/{environment}/" if environment else "actions/"
                if args[-1].endswith(f"{prefix}variables/{name}"):
                    return json.dumps({"name": name, "value": "wrong" if self.readback_wrong else self.outputs["github_identity_client_ids"]["value"][identity]})
            raise AssertionError("Unexpected variable read")
        return super().__call__(args, operation, data=data)


class TailscaleCIConfigureTest(unittest.TestCase):
    def run_script(self, fake, argv=None):
        output = io.StringIO()
        with patch.object(MODULE.GUARDS, "command", side_effect=fake), \
                redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main(argv or [])
        for value in CLIENTS.values():
            self.assertNotIn(value, output.getvalue())
        return status, output.getvalue()

    def test_preview_never_writes(self):
        fake = FakeCommands()
        status, output = self.run_script(fake)
        self.assertEqual(status, 0, output)
        self.assertEqual(fake.writes, [])
        self.assertIn("Preview passed", output)

    def test_execute_publishes_and_verifies_only_fixed_variable_targets_over_stdin(self):
        fake = FakeCommands()
        status, output = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 0, output)
        expected = []
        for identity, (environment, name) in MODULE.BINDINGS.items():
            scope = ["--env", environment] if environment else []
            expected.append((["gh", "variable", "set", name, "--repo", "github.com/Stuhlmuller/homelab", *scope], CLIENTS[identity]+"\n"))
        self.assertEqual(fake.writes, expected)
        self.assertEqual(sum(operation == "published variable verification" for _, operation, _ in fake.calls), 3)
        first_write = next(i for i, (args, _, _) in enumerate(fake.calls) if "set" in args)
        self.assertEqual(sum(operation == "verified main lookup" for _, operation, _ in fake.calls[:first_write]), 2)

    def test_invalid_provider_outputs_never_write(self):
        invalid = [None, {}, {"github_identity_client_ids": {"value": CLIENTS}}]
        secret_shapes = ["-".join(("tskey", kind, "synthetic-secret")) for kind in ("client", "auth", "api")]
        for value in [None, 123, "", *secret_shapes, "bad\nvalue", "bad\rvalue", "bad\tvalue",
                      "bad value", "bad\x00value", "bad\x7fvalue", "a" * 1025, CLIENTS["apply"]]:
            output = deepcopy(OUTPUTS)
            output["github_identity_client_ids"]["value"]["plan"] = value
            invalid.append(output)
        output = deepcopy(OUTPUTS)
        output["github_identity_client_ids"]["sensitive"] = True
        invalid.append(output)
        output = deepcopy(OUTPUTS)
        output["github_identity_client_ids"]["value"]["extra"] = "extraClient"
        invalid.append(output)
        for output in invalid:
            with self.subTest(output=output):
                fake = FakeCommands(); fake.outputs = output
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])

    def test_opaque_printable_ids_have_no_assumed_prefix_or_minimum_length(self):
        for value in ("x", "opaque.ID:/@+=_", "a" * 1024):
            with self.subTest(value=value[:32]):
                fake = FakeCommands()
                fake.outputs["github_identity_client_ids"]["value"]["plan"] = value
                status, output = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 0, output)
                self.assertEqual(fake.writes[0][1], value + "\n")

    def test_dirty_stale_unsigned_or_unprotected_main_never_writes(self):
        for variant in ("dirty", "stale", "unsigned", "unprotected", "bypass"):
            with self.subTest(variant=variant):
                fake = FakeCommands()
                if variant == "dirty": fake.dirty = "?? untracked\n"
                elif variant == "stale": fake.main["sha"] = "b" * 40
                elif variant == "unsigned": fake.main["commit"]["verification"]["verified"] = False
                elif variant == "unprotected": fake.protected = False
                else: fake.environments["homelab-production"]["can_admins_bypass"] = True
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])

    def test_wrong_scope_and_main_race_never_write(self):
        for scope in (None, "homelab-plan", "homelab-production"):
            fake = FakeCommands()
            name = "TAILSCALE_CORDIUM_CLIENT_ID" if scope else "TAILSCALE_CLIENT_ID"
            fake.names["variable", scope] = [{"name": name}]
            status, _ = self.run_script(fake, ["--execute"])
            self.assertEqual(status, 1); self.assertEqual(fake.writes, [])
        fake = FakeCommands()
        with patch.object(MODULE.GUARDS, "verify_main", side_effect=[BASE.SHA, "b" * 40]):
            status, _ = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 1); self.assertEqual(fake.writes, [])

    def test_mismatched_readback_fails(self):
        fake = FakeCommands(); fake.readback_wrong = True
        status, output = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 1)
        self.assertIn("verification failed", output)


if __name__ == "__main__":
    unittest.main()
