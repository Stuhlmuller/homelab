#!/usr/bin/env python3
"""Offline checks for scoped, private Tailnet Lock CI key publication."""
from contextlib import redirect_stderr, redirect_stdout
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("tailscale_configure", ROOT / "scripts/tailscale-ci-configure.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BASE_SPEC = importlib.util.spec_from_file_location("entra_test", ROOT / "scripts/ci/entra-ci-configure-test.py")
BASE = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(BASE)
SIGNER = "tlpub:" + "a" * 64


def outputs(generation=1):
    return {
        "github_identity_client_ids": {"sensitive": False, "value": {}},
        "github_auth_keys": {"sensitive": True, "value": {
            role: {"id": f"{role}{generation}CNTRL", "key": "-".join(("tskey", "auth", f"{role}{generation}CNTRL", "redacted")),
                   "generation": generation, "expires_at": "2099-01-01T00:00:00Z", "invalid": False,
                   "reusable": True, "ephemeral": True, "preauthorized": True, "tags": [f"tag:homelab-ci-{role}"]}
            for role in MODULE.BINDINGS
        }},
    }


class FakeCommands(BASE.FakeCommands):
    def __init__(self):
        super().__init__()
        self.outputs = outputs()
        self.trusted = {SIGNER: None}
        self.tailnet = "tail67beb.ts.net"
        self.running = "Running"
        self.online = True
        self.enabled = True
        self.signed = True
        self.fail_publication = False
        self.missing_metadata = False
        self.retired = []
        self.authority_change = None
        for environment, _, name in MODULE.BINDINGS.values():
            self.names["variable", environment] = [{"name": name}]

    def __call__(self, args, operation, *, data=None):
        if args[0] == MODULE.TAILSCALE:
            self.calls.append((args, operation, data))
            if args[1:] == ["status", "--json"]:
                return json.dumps({"BackendState": self.running, "Self": {"Online": self.online},
                                   "CurrentTailnet": {"MagicDNSSuffix": self.tailnet}})
            if args[1:3] == ["lock", "status"]:
                return json.dumps({"Enabled": self.enabled, "NodeKeySigned": self.signed,
                                   "PublicKey": SIGNER, "TrustedKeys": [{"Public": key, **({"Meta": meta} if meta is not None else {})}
                                                                       for key, meta in self.trusted.items()]})
            if args[1:3] == ["lock", "sign"]:
                assert args == [MODULE.TAILSCALE, "lock", "sign", "file:/dev/stdin"]
                assert isinstance(data, str)
                raw = data
                stable_id = raw.removeprefix(MODULE.AUTH_PREFIX).split("-", 1)[0]
                public = hashlib.sha256((stable_id + "delegate").encode()).digest()
                authority = "tlpub:" + hashlib.sha256((stable_id + "authority").encode()).hexdigest()
                private = b"0" * 32 + public
                wrapped = raw + "--TL" + base64.b64encode(b"signature").decode().rstrip("=") + "-" + base64.b64encode(private).decode().rstrip("=")
                self.trusted[authority] = {"purpose": "pre-auth key", "authkey_stableid": stable_id}
                if self.authority_change:
                    self.authority_change(self.trusted, authority)
                return wrapped + "\n"
            if args[1:3] == ["lock", "remove"]:
                self.retired.append(args[3])
                del self.trusted[args[3]]
                return ""
            raise AssertionError("Unexpected Tailscale command")
        if args[:3] == ["gh", "secret", "set"]:
            if self.fail_publication and len(self.writes) == 2:
                raise MODULE.GUARDS.Failure("Secret publication failed; private output withheld")
            environment = args[args.index("--env") + 1] if "--env" in args else None
            if not self.missing_metadata:
                self.names["secret", environment] = [{"name": args[3]}]
        if args[:3] == ["gh", "variable", "delete"]:
            self.calls.append((args, operation, data))
            self.writes.append((args, data))
            environment = args[args.index("--env") + 1] if "--env" in args else None
            self.names["variable", environment] = []
            return ""
        return super().__call__(args, operation, data=data)


class TailscaleCIConfigureTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cache = Path(self.directory.name) / "private" / "ci-signed-keys.json"
        self.cache_patch = patch.object(MODULE, "CACHE", self.cache)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.directory.cleanup()

    def run_script(self, fake, argv=None):
        output = io.StringIO()
        with patch.object(MODULE.GUARDS, "command", side_effect=fake), \
                redirect_stdout(output), redirect_stderr(output):
            status = MODULE.main(argv or [])
        for entry in fake.outputs.get("github_auth_keys", {}).get("value", {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                self.assertNotIn(entry["key"], output.getvalue())
                self.assertTrue(all(entry["key"] not in " ".join(call[0]) for call in fake.calls))
        return status, output.getvalue()

    def test_preview_never_signs_writes_or_creates_cache(self):
        fake = FakeCommands()
        status, output = self.run_script(fake)
        self.assertEqual(status, 0, output)
        self.assertEqual(fake.writes, [])
        self.assertNotIn("CI key signing", [call[1] for call in fake.calls])
        self.assertFalse(self.cache.parent.exists())

    def test_execute_publishes_only_fixed_secret_targets_over_stdin_then_removes_variables(self):
        fake = FakeCommands()
        status, output = self.run_script(fake, ["--execute"])
        self.assertEqual(status, 0, output)
        self.assertEqual(len(fake.writes), 6)
        signing = [(args, data) for args, operation, data in fake.calls if operation == "CI key signing"]
        self.assertEqual(signing, [([MODULE.TAILSCALE, "lock", "sign", "file:/dev/stdin"], entry["key"])
                                   for entry in fake.outputs["github_auth_keys"]["value"].values()])
        for index, (identity, (environment, name, old_name)) in enumerate(MODULE.BINDINGS.items()):
            scope = ["--env", environment] if environment else []
            args, data = fake.writes[index]
            self.assertEqual(args, ["gh", "secret", "set", name, "--repo", MODULE.GUARDS.HOST_REPO, *scope])
            self.assertTrue(data.startswith(fake.outputs["github_auth_keys"]["value"][identity]["key"] + "--TL"))
            self.assertEqual(fake.writes[index + 3], (["gh", "variable", "delete", old_name,
                                                     "--repo", MODULE.GUARDS.HOST_REPO, *scope], None))
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cache.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(list(self.cache.parent.iterdir())), 2)  # cache and mutex; no raw-key files
        for record in json.loads(self.cache.read_text()):
            delegate = base64.b64decode(record["wrapped"].split("--TL", 1)[1].split("-", 1)[1] + "==")[32:]
            self.assertNotEqual(record["authority"], "tlpub:" + delegate.hex())
            self.assertIn(record["authority"], fake.trusted)
        first_sign = next(i for i, call in enumerate(fake.calls) if call[1] == "CI key signing")
        self.assertEqual(sum(call[1] == "verified main lookup" for call in fake.calls[:first_sign]), 2)

    def test_retry_reuses_signatures_without_new_authorities(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)
        self.assertEqual(len(fake.trusted), 4)

    def test_unexpected_signing_authority_changes_stop_before_publication(self):
        def remove_added(trusted, authority):
            del trusted[authority]

        def wrong_metadata(trusted, authority):
            trusted[authority]["purpose"] = "unrelated signer"

        def duplicate_match(trusted, authority):
            trusted["tlpub:" + "c" * 64] = trusted[authority].copy()

        def unrelated_added(trusted, authority):
            trusted["tlpub:" + "c" * 64] = {}

        def unrelated_removed(trusted, authority):
            del trusted[SIGNER]

        def unrelated_changed(trusted, authority):
            trusted[SIGNER] = {"purpose": "changed"}

        for mutation in (remove_added, wrong_metadata, duplicate_match, unrelated_added,
                         unrelated_removed, unrelated_changed):
            with self.subTest(mutation=mutation.__name__):
                fake = FakeCommands()
                fake.authority_change = mutation
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertEqual(fake.writes, [])
                self.assertFalse(self.cache.exists())

    def test_cached_authority_identity_or_metadata_mismatch_stops_reuse_and_retirement(self):
        for variant in ("identity", "purpose", "stable_id", "duplicate"):
            with self.subTest(variant=variant):
                self.cache.unlink(missing_ok=True)
                fake = FakeCommands()
                self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
                records = json.loads(self.cache.read_text())
                authority = records[0]["authority"]
                if variant == "identity":
                    records[0]["authority"] = SIGNER
                    self.cache.write_text(json.dumps(records))
                elif variant == "purpose":
                    fake.trusted[authority]["purpose"] = "unrelated signer"
                elif variant == "stable_id":
                    fake.trusted[authority]["authkey_stableid"] = "unrelated"
                else:
                    fake.trusted["tlpub:" + "c" * 64] = fake.trusted[authority].copy()
                writes = len(fake.writes)
                self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
                self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 1)
                self.assertEqual(len(fake.writes), writes)
                self.assertEqual(fake.retired, [])
                self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)

    def test_malformed_or_wrong_provider_wrapper_stops_before_publication(self):
        for invalid in ("malformed", "wrong-prefix"):
            fake = FakeCommands()
            command = fake.__call__

            def altered(args, operation, *, data=None):
                value = command(args, operation, data=data)
                if args[:3] == [MODULE.TAILSCALE, "lock", "sign"]:
                    return value + "!" if invalid == "malformed" else "changed" + value
                return value

            with patch.object(MODULE.GUARDS, "command", side_effect=altered), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main(["--execute"]), 1)
            self.assertEqual(fake.writes, [])
            self.assertFalse(self.cache.exists())

    def test_partial_publication_or_missing_metadata_retains_all_variables(self):
        for variant in ("fail_publication", "missing_metadata"):
            with self.subTest(variant=variant):
                fake = FakeCommands()
                setattr(fake, variant, True)
                # A fresh cache avoids intentionally untrusted records from another signer fixture.
                self.cache.unlink(missing_ok=True)
                status, _ = self.run_script(fake, ["--execute"])
                self.assertEqual(status, 1)
                self.assertFalse(any(args[:3] == ["gh", "variable", "delete"] for args, _ in fake.writes))
                self.assertEqual(len(json.loads(self.cache.read_text())), 3)

    def test_bad_outputs_expiry_tag_or_generation_never_sign(self):
        for key, value in (("key", "redacted"), ("expires_at", "2000-01-01T00:00:00Z"),
                           ("invalid", True), ("reusable", False), ("ephemeral", False),
                           ("preauthorized", False), ("tags", ["tag:homelab-ci-apply"]),
                           ("generation", 0), ("generation", True), ("generation", 2)):
            fake = FakeCommands()
            fake.outputs["github_auth_keys"]["value"]["plan"][key] = value
            status, _ = self.run_script(fake, ["--execute"])
            self.assertEqual(status, 1, (key, value))
            self.assertNotIn("CI key signing", [call[1] for call in fake.calls])
            self.assertEqual(fake.writes, [])
        fake = FakeCommands()
        fake.outputs["github_auth_keys"]["sensitive"] = False
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)

    def test_dirty_stale_unsigned_or_unprotected_main_never_signs(self):
        for variant in ("dirty", "stale", "unsigned", "unprotected", "bypass"):
            fake = FakeCommands()
            if variant == "dirty":
                fake.dirty = "?? untracked\n"
            elif variant == "stale":
                fake.main["sha"] = "b" * 40
            elif variant == "unsigned":
                fake.main["commit"]["verification"]["verified"] = False
            elif variant == "unprotected":
                fake.protected = False
            else:
                fake.environments["homelab-production"]["can_admins_bypass"] = True
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1, variant)
            self.assertEqual(fake.writes, [])
            self.assertFalse(self.cache.exists())

    def test_wrong_scope_and_main_race_never_sign(self):
        for kind, scope, name in (("secret", None, "TAILSCALE_AUTH_KEY"),
                                  ("secret", "homelab-plan", "TAILSCALE_CORDIUM_AUTH_KEY"),
                                  ("variable", "homelab-production", "TAILSCALE_CORDIUM_CLIENT_ID")):
            fake = FakeCommands()
            fake.names[kind, scope] = [{"name": name}]
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
            self.assertEqual(fake.writes, [])
        fake = FakeCommands()
        with patch.object(MODULE.GUARDS, "verify_main", side_effect=[BASE.SHA, "b" * 40]):
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertNotIn("CI key signing", [call[1] for call in fake.calls])

    def test_disabled_locked_out_or_untrusted_mac_never_signs(self):
        for variant in ("enabled", "signed", "trusted"):
            fake = FakeCommands()
            if variant == "trusted":
                fake.trusted = {}
            else:
                setattr(fake, variant, False)
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
            self.assertEqual(fake.writes, [])

    def test_wrong_tailnet_or_offline_profile_never_signs(self):
        for key, value in (("tailnet", "other.ts.net"), ("running", "Stopped"), ("online", False)):
            fake = FakeCommands()
            setattr(fake, key, value)
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
            self.assertEqual(fake.writes, [])
            self.assertNotIn("CI key signing", [call[1] for call in fake.calls])

    def test_private_cache_symlink_or_open_permissions_fail_closed(self):
        fake = FakeCommands()
        self.cache.parent.mkdir(mode=0o700)
        self.cache.write_text("[]")
        self.cache.chmod(0o644)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.cache.unlink()
        target = self.cache.parent / "target.json"
        target.write_text("[]")
        target.chmod(0o600)
        self.cache.symlink_to(target)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertEqual(fake.writes, [])

    def test_uncached_existing_authority_requires_recovery(self):
        fake = FakeCommands()
        key_id = fake.outputs["github_auth_keys"]["value"]["plan"]["id"]
        fake.trusted["tlpub:" + "b" * 64] = {"purpose": "pre-auth key", "authkey_stableid": key_id}
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertNotIn("CI key signing", [call[1] for call in fake.calls])

    def test_cached_authority_removal_does_not_resign_silently(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        fake.trusted = {SIGNER: None}
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)

    def test_rotation_retires_only_old_cached_authorities_after_explicit_command(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        previous = set(fake.trusted) - {SIGNER}
        fake.outputs = outputs(generation=2)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        current = set(fake.trusted) - previous
        fake.trusted["tlpub:" + "e" * 64] = {"purpose": "unrelated signer"}
        self.assertEqual(self.run_script(fake, ["--retire-previous"])[0], 0)
        self.assertEqual(fake.retired, [])
        self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 0)
        self.assertEqual(set(fake.retired), previous)
        self.assertTrue(current.issubset(fake.trusted))
        self.assertIn("tlpub:" + "e" * 64, fake.trusted)
        self.assertEqual(len(json.loads(self.cache.read_text())), 3)
        self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 0)
        self.assertEqual(len(fake.retired), 3)

    def test_retirement_preflights_every_current_and_previous_authority(self):
        for current in (False, True):
            for index in (0, 1, 2):
                with self.subTest(current=current, index=index):
                    self.cache.unlink(missing_ok=True)
                    fake = FakeCommands()
                    self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
                    fake.outputs = outputs(generation=2)
                    self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
                    records = json.loads(self.cache.read_text())
                    authority = records[index + (3 if current else 0)]["authority"]
                    fake.trusted[authority]["authkey_stableid"] = "unrelated"
                    before = self.cache.read_bytes()
                    writes = len(fake.writes)
                    signs = sum(call[1] == "CI key signing" for call in fake.calls)
                    for arguments in (["--retire-previous"], ["--retire-previous", "--execute"]):
                        self.assertEqual(self.run_script(fake, arguments)[0], 1)
                        self.assertEqual(fake.retired, [])
                        self.assertEqual(self.cache.read_bytes(), before)
                        self.assertEqual(len(fake.writes), writes)
                        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), signs)

    def test_retirement_rechecks_target_after_inventory_preflight(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        fake.outputs = outputs(generation=2)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        before = self.cache.read_bytes()
        preflight = MODULE.retirement_preflight

        def changed_after_preflight(keys, cache):
            previous = preflight(keys, cache)
            fake.trusted[previous[0]["authority"]]["authkey_stableid"] = "changed"
            return previous

        with patch.object(MODULE, "retirement_preflight", side_effect=changed_after_preflight):
            self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 1)
        self.assertEqual(fake.retired, [])
        self.assertEqual(self.cache.read_bytes(), before)

    def test_already_absent_previous_authority_is_retired_idempotently(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        previous = [entry["authority"] for entry in json.loads(self.cache.read_text())]
        fake.outputs = outputs(generation=2)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        del fake.trusted[previous[0]]
        before = self.cache.read_bytes()
        self.assertEqual(self.run_script(fake, ["--retire-previous"])[0], 0)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertEqual(fake.retired, [])
        self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 0)
        self.assertEqual(fake.retired, previous[1:])
        self.assertEqual(len(json.loads(self.cache.read_text())), 3)
        self.assertEqual(self.run_script(fake, ["--retire-previous", "--execute"])[0], 0)
        self.assertEqual(fake.retired, previous[1:])

    def test_generation_rollback_and_uncached_retirement_fail_closed(self):
        fake = FakeCommands()
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        fake.outputs = outputs(generation=2)
        for arguments in (["--retire-previous"], ["--retire-previous", "--execute"]):
            self.assertEqual(self.run_script(fake, arguments)[0], 1)
        self.assertEqual(fake.retired, [])
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)
        fake.outputs = outputs(generation=1)
        fake.outputs["github_auth_keys"]["value"]["plan"]["key"] += "changed"
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)

    def test_subprocess_boundary_withholds_secret_errors(self):
        failure = OSError("-".join(("tskey", "auth", "redacted")))
        with patch.object(MODULE.GUARDS, "command", side_effect=failure):
            stream = io.StringIO()
            with redirect_stderr(stream):
                self.assertEqual(MODULE.main([]), 1)
            self.assertNotIn(str(failure), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
