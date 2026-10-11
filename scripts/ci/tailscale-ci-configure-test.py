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
from types import SimpleNamespace
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
        self.node_id = "nTestMac01"
        for environment, _, name in MODULE.BINDINGS.values():
            self.names["variable", environment] = [{"name": name}]

    def __call__(self, args, operation, *, data=None):
        if args[0] == MODULE.TAILSCALE:
            self.calls.append((args, operation, data))
            if args[1:] == ["status", "--json"]:
                return json.dumps({"BackendState": self.running, "Self": {"Online": self.online, "ID": self.node_id},
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
                self.retired.append(args[-1])
                del self.trusted[args[-1]]
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
        self.sleep_patch = patch.object(MODULE.time, "sleep")
        self.sleep_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()
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
                MODULE.pending_path().unlink(missing_ok=True)
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

    def test_delayed_authority_readback_preserves_receipt_before_polling(self):
        fake = FakeCommands()
        command = fake.__call__
        lag = 0
        before = {}

        def delayed(args, operation, *, data=None):
            nonlocal lag, before
            if args[1:3] == ["lock", "sign"]:
                before = fake.trusted.copy()
                value = command(args, operation, data=data)
                lag = 2
                return value
            if args[1:3] == ["lock", "status"] and lag:
                self.assertTrue(MODULE.pending_path().exists())
                self.assertEqual(MODULE.pending_path().stat().st_mode & 0o777, 0o600)
                lag -= 1
                current, fake.trusted = fake.trusted, before
                try:
                    return command(args, operation, data=data)
                finally:
                    fake.trusted = current
            return command(args, operation, data=data)

        with patch.object(MODULE.GUARDS, "command", side_effect=delayed), redirect_stdout(io.StringIO()):
            self.assertEqual(MODULE.main(["--execute"]), 0)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)
        self.assertFalse(MODULE.pending_path().exists())

    def test_timeout_retry_reuses_private_pending_signature(self):
        fake = FakeCommands()
        command = fake.__call__
        before = fake.trusted.copy()

        def stalled(args, operation, *, data=None):
            if args[1:3] == ["lock", "status"]:
                current, fake.trusted = fake.trusted, before
                try:
                    return command(args, operation, data=data)
                finally:
                    fake.trusted = current
            return command(args, operation, data=data)

        with patch.object(MODULE.GUARDS, "command", side_effect=stalled), redirect_stderr(io.StringIO()):
            self.assertEqual(MODULE.main(["--execute"]), 1)
        self.assertFalse(self.cache.exists())
        receipt = MODULE.pending_path().read_bytes()
        self.assertEqual(fake.writes, [])
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 1)
        for arguments in ([], ["--retire-previous"]):
            self.run_script(fake, arguments)
            self.assertEqual(MODULE.pending_path().read_bytes(), receipt)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)
        self.assertFalse(MODULE.pending_path().exists())

    def test_retry_finishes_cached_receipt_after_partial_cache_write(self):
        fake = FakeCommands()
        save = MODULE.save_cache

        def interrupted(entries):
            save(entries)
            raise OSError("interrupted after durable cache write")

        with patch.object(MODULE, "save_cache", side_effect=interrupted):
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertTrue(self.cache.exists())
        self.assertTrue(MODULE.pending_path().exists())
        with patch.object(MODULE, "save_cache", wraps=save) as resumed:
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
            self.assertEqual(resumed.call_count, 3)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)
        self.assertFalse(MODULE.pending_path().exists())

    def test_pending_receipt_survives_cache_failure_and_rejects_changed_provider(self):
        fake = FakeCommands()
        with patch.object(MODULE, "save_cache", side_effect=OSError("private error")):
            self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertTrue(MODULE.pending_path().exists())
        fake.outputs = outputs(generation=2)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 1)
        fake.outputs = outputs(generation=1)
        self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
        self.assertEqual(sum(call[1] == "CI key signing" for call in fake.calls), 3)

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

    def orphan(self, fake):
        authority = "tlpub:" + "b" * 64
        created = int(MODULE.time.time()) - 60
        key_id = fake.outputs["github_auth_keys"]["value"]["apply"]["id"]
        fake.trusted[authority] = {"purpose": "pre-auth key", "authkey_stableid": key_id,
                                   "wrapper_stableid": fake.node_id, "wrapper_createtime": str(created)}
        return authority, ["--recover-orphan", "apply", "--authority", authority,
                           "--created-at", str(created)]

    def test_orphan_preview_and_execute_remove_only_exact_key_without_resigning(self):
        for body in (b"[]", b"null"):
            with self.subTest(body=body):
                fake = FakeCommands()
                authority, arguments = self.orphan(fake)
                before = fake.trusted.copy()
                with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=body)) as query:
                    self.assertEqual(self.run_script(fake, arguments)[0], 0)
                    self.assertEqual(fake.trusted, before)
                    self.assertEqual(fake.retired, [])
                    self.assertEqual(self.run_script(fake, [*arguments, "--execute"])[0], 0)
                    self.assertEqual(fake.retired, [authority])
                    self.assertEqual(fake.trusted, {SIGNER: None})
                    self.assertEqual(self.run_script(fake, [*arguments, "--execute"])[0], 0)
                    self.assertEqual(fake.retired, [authority])
                self.assertEqual(query.call_args.args[0], [MODULE.TAILSCALE, "debug", "localapi", "POST",
                                                          "/localapi/v0/tka/affected-sigs", "-"])
                self.assertEqual(query.call_args.kwargs["input"], bytes.fromhex("b" * 64))
                self.assertIn(([MODULE.TAILSCALE, "lock", "remove", "--re-sign=false", authority],
                               "exact orphan signing-authority removal", None), fake.calls)
                self.assertEqual(fake.writes, [])
                self.assertNotIn("CI key signing", [call[1] for call in fake.calls])

    def test_absent_orphan_preview_and_execute_remain_idempotent_after_publication_or_pending_receipt(self):
        for variant in ("old", "published_cache", "pending"):
            with self.subTest(variant=variant):
                self.cache.unlink(missing_ok=True)
                MODULE.pending_path().unlink(missing_ok=True)
                fake = FakeCommands()
                authority, arguments = self.orphan(fake)
                del fake.trusted[authority]
                arguments[-1] = str(int(MODULE.time.time()) - 86401)
                if variant == "published_cache":
                    self.assertEqual(self.run_script(fake, ["--execute"])[0], 0)
                elif variant == "pending":
                    with patch.object(MODULE, "save_cache", side_effect=OSError("private")):
                        self.assertEqual(self.run_script(fake, ["--execute"])[0], 1)
                trusted = json.dumps(fake.trusted, sort_keys=True)
                saved = {path: path.read_bytes() if path.exists() else None
                         for path in (self.cache, MODULE.pending_path())}
                fake.calls.clear()
                fake.writes.clear()
                with patch.object(MODULE.subprocess, "run") as query:
                    for argv in (arguments, [*arguments, "--execute"]):
                        status, output = self.run_script(fake, argv)
                        self.assertEqual(status, 0, output)
                    query.assert_not_called()
                self.assertEqual(json.dumps(fake.trusted, sort_keys=True), trusted)
                self.assertEqual(fake.retired, [])
                self.assertEqual(fake.writes, [])
                self.assertNotIn("CI key signing", [call[1] for call in fake.calls])
                self.assertEqual({path: path.read_bytes() if path.exists() else None for path in saved}, saved)

    def test_absent_orphan_still_requires_valid_provider_destination_cache_pending_and_main(self):
        for variant in ("provider", "scope", "cache", "pending", "main"):
            with self.subTest(variant=variant):
                self.cache.unlink(missing_ok=True)
                MODULE.pending_path().unlink(missing_ok=True)
                fake = FakeCommands()
                authority, arguments = self.orphan(fake)
                del fake.trusted[authority]
                if variant == "provider":
                    fake.outputs["github_auth_keys"]["value"]["plan"]["expires_at"] = "2000-01-01T00:00:00Z"
                elif variant == "scope":
                    fake.names["secret", None] = [{"name": "TAILSCALE_AUTH_KEY"}]
                elif variant in ("cache", "pending"):
                    self.cache.parent.mkdir(mode=0o700, exist_ok=True)
                    MODULE.save_private(self.cache if variant == "cache" else MODULE.pending_path(), {})
                else:
                    fake.dirty = "?? untracked\n"
                with patch.object(MODULE.subprocess, "run") as query:
                    self.assertEqual(self.run_script(fake, [*arguments, "--execute"])[0], 1)
                    query.assert_not_called()
                self.assertEqual(fake.retired, [])
                self.assertEqual(fake.writes, [])

    def test_orphan_refuses_wrong_identity_signer_time_cache_pending_or_published_secret(self):
        for variant in ("identity", "signer", "created", "old", "purpose", "duplicate", "cache", "pending", "published"):
            with self.subTest(variant=variant):
                self.cache.unlink(missing_ok=True)
                MODULE.pending_path().unlink(missing_ok=True)
                fake = FakeCommands()
                authority, arguments = self.orphan(fake)
                meta = fake.trusted[authority]
                if variant == "identity":
                    meta["authkey_stableid"] = "unrelated"
                elif variant == "signer":
                    meta["wrapper_stableid"] = "othernode"
                elif variant == "created":
                    meta["wrapper_createtime"] = "1"
                elif variant == "old":
                    arguments[-1] = "1"
                elif variant == "purpose":
                    meta["purpose"] = "unrelated signer"
                elif variant == "duplicate":
                    fake.trusted["tlpub:" + "c" * 64] = meta.copy()
                elif variant in ("cache", "pending"):
                    # Use a real private receipt/cache from an offline successful signing fixture.
                    fresh = FakeCommands()
                    if variant == "pending":
                        with patch.object(MODULE, "save_cache", side_effect=OSError("private")):
                            self.assertEqual(self.run_script(fresh, ["--execute"])[0], 1)
                    else:
                        self.assertEqual(self.run_script(fresh, ["--execute"])[0], 0)
                else:
                    fake.names["secret", "homelab-production"] = [{"name": "TAILSCALE_AUTH_KEY"}]
                with patch.object(MODULE.subprocess, "run") as query:
                    self.assertEqual(self.run_script(fake, [*arguments, "--execute"])[0], 1)
                    query.assert_not_called()
                self.assertEqual(fake.retired, [])
                self.assertEqual(fake.writes, [])

    def test_orphan_affected_signatures_or_failed_lookup_never_remove(self):
        for code, body in ((0, b'["private-signature"]'), (0, b'{}'), (0, b'false'),
                           (0, b'malformed-private-output'), (1, b'[]')):
            with self.subTest(code=code, body=body):
                fake = FakeCommands()
                _, arguments = self.orphan(fake)
                with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=code, stdout=body)):
                    status, output = self.run_script(fake, [*arguments, "--execute"])
                self.assertEqual(status, 1)
                self.assertNotIn(body.decode(), output)
                self.assertEqual(fake.retired, [])
                self.assertEqual(fake.writes, [])

    def test_orphan_removal_waits_for_readback_and_rejects_unrelated_trust_change(self):
        for drift in (False, True):
            fake = FakeCommands()
            _, arguments = self.orphan(fake)
            command = fake.__call__
            previous = fake.trusted.copy()
            pending = 0

            def remove(args, operation, *, data=None):
                nonlocal pending
                if args[1:3] == ["lock", "remove"]:
                    value = command(args, operation, data=data)
                    pending = 1
                    if drift:
                        fake.trusted["tlpub:" + "c" * 64] = {}
                    return value
                if args[1:3] == ["lock", "status"] and pending:
                    pending -= 1
                    current, fake.trusted = fake.trusted, previous
                    try:
                        return command(args, operation, data=data)
                    finally:
                        fake.trusted = current
                return command(args, operation, data=data)

            with patch.object(MODULE.GUARDS, "command", side_effect=remove), \
                    patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"[]")), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main([*arguments, "--execute"]), 1 if drift else 0)
            self.assertEqual(fake.writes, [])

    def test_subprocess_boundary_withholds_secret_errors(self):
        failure = OSError("-".join(("tskey", "auth", "redacted")))
        with patch.object(MODULE.GUARDS, "command", side_effect=failure):
            stream = io.StringIO()
            with redirect_stderr(stream):
                self.assertEqual(MODULE.main([]), 1)
            self.assertNotIn(str(failure), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
