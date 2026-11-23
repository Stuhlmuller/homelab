#!/usr/bin/env python3
"""Inert production-signing state machine: all provider, CLI and GitHub calls mocked."""
import base64
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("signer", Path(__file__).parents[1] / "harbor-tailscale-production-sign.py")
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 29, tzinfo=timezone.utc)


class ProductionSigner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.directory.chmod(0o700)
        self.cache = self.directory / "ci-signed-keys.json"
        self.old = [{'identity': 'plan', 'wrapped': 'inert-plan-preserve'},
                    {'identity': 'cordium', 'wrapped': 'inert-cordium-preserve'},
                    {'identity': 'apply', 'generation': 2, 'fingerprint': 'd' * 64,
                     'authority': 'tlpub:' + 'd' * 64, 'wrapped': 'inert-old-apply-preserve'}]
        self.cache.write_text(json.dumps(self.old))
        self.cache.chmod(0o600)
        self.original = self.cache.read_bytes()
        self.mac = 'tlpub:257f1bcd25b8e90f63ce1fdced5e9232f8c79d9cf01f8e40806d636d4819ca1a'
        self.authority = 'tlpub:' + 'b' * 64
        self.key = T.S.AUTH_PREFIX + 'currentid-inertPrivateSentinel'
        self.wrapped = self.key + '--TL' + base64.b64encode(b'inert').decode() + '-' + base64.b64encode(b'x' * 64).decode()
        self.entry = dict(key=self.key, generation=2, expires_at=T.EXPIRY, tags=[T.P.TAG],
                          reusable=True, ephemeral=True, preauthorized=True, invalid=False)
        self.signed = False
        self.visible = True
        self.sign_calls = 0
        self.reads = []
        self.effect = 'success'
        self.now = 1793300000
        self.metadata = {'purpose': 'pre-auth key', 'authkey_stableid': 'currentid',
                         'wrapper_stableid': 'inert-node', 'wrapper_createtime': '1793300000'}
        self.addCleanup(patch.stopall)
        patch.object(T.S, 'CACHE', self.cache).start()
        patch.object(T.G, 'verify_main', return_value='f' * 40).start()
        patch.object(T.G, 'read_json', self.read).start()
        patch.object(T.P, 'datetime', Clock).start()
        patch.object(T.time, 'time', side_effect=lambda: self.now).start()
        patch.object(T, 'invoke_sign', self.sign).start()

    def read(self, args, operation):
        self.reads.append(args)
        if args[0] == 'terragrunt':
            self.assertIn('--backend-bootstrap=false', args)
            self.assertIn('--no-auto-init', args)
            self.assertEqual(args[-2:], ['output', '-json'])
            return {'github_auth_keys': {'sensitive': True, 'value': {'apply': self.entry}}}
        if args[:2] == ['gh', 'api']:
            self.assertEqual(args[-1], 'user')
            return {'login': 'rstuhlmuller'}
        if args == [T.CLI, 'version', '--json']:
            return {'short': '1.92.3', 'gitCommit': T.CLI_COMMIT}
        if args == [T.CLI, 'status', '--json']:
            return {'BackendState': 'Running', 'Self': {'Online': True, 'ID': 'inert-node'},
                    'CurrentTailnet': {'MagicDNSSuffix': 'tail67beb.ts.net'}}
        if args == [T.CLI, 'lock', 'status', '--json']:
            keys = [{'Key': self.mac.replace('tlpub:', 'nlpub:'), 'Metadata': None, 'Votes': 1},
                    {'Key': 'nlpub:' + 'd' * 64, 'Votes': 1,
                     'Metadata': {'purpose': 'pre-auth key', 'authkey_stableid': 'oldid'}}]
            if self.signed and self.visible:
                keys.append({'Key': self.authority.replace('tlpub:', 'nlpub:'),
                             'Metadata': dict(self.metadata), 'Votes': 1})
            return {'Enabled': True, 'NodeKeySigned': True,
                    'PublicKey': self.mac.replace('tlpub:', 'nlpub:'), 'TrustedKeys': keys}
        self.fail('Unexpected external read')

    def sign(self, key, capture):
        self.sign_calls += 1
        self.assertEqual(key, self.key)
        self.assertTrue(T.paths()[0].is_file(), 'Intent must precede signing')
        self.assertEqual(T.paths()[0].stat().st_mode & 0o777, 0o600)
        if self.effect == 'interrupt':
            raise KeyboardInterrupt
        if self.effect == 'delay':
            self.now += 600
            self.metadata['wrapper_createtime'] = str(self.now)
        self.signed = True
        capture.write(self.key + '--TLpartial' if self.effect == 'partial' else self.wrapped + '\n')
        if self.effect == 'timeout':
            raise subprocess.TimeoutExpired('inert', 120, stderr=self.key)
        if self.effect == 'cache-conflict':
            self.cache.write_text(json.dumps(self.old + [{'identity': 'inert-other-record'}]))
        return 1 if self.effect == 'nonzero' else 0

    def arguments(self, mode='preview'):
        args = ['--identity', 'apply', '--generation', '2', '--expires-at', T.EXPIRY,
                '--signer-authority', self.mac]
        if mode == 'execute':
            args += ['--execute', '--allow-new-delegated-authority']
        elif mode == 'recover':
            args += ['--recover']
        return args

    def run_main(self, mode='execute', extra=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                status = T.main(self.arguments(mode) + (extra or []))
            except SystemExit as e:
                status = e.code
        self.assertNotIn(self.key, out.getvalue() + err.getvalue())
        self.assertNotIn(self.wrapped, out.getvalue() + err.getvalue())
        return status, out.getvalue(), err.getvalue()

    def test_default_preview_is_read_only(self):
        self.assertEqual(self.run_main('preview')[0], 0)
        self.assertEqual(self.sign_calls, 0)
        self.assertEqual(list(self.directory.iterdir()), [self.cache])
        self.assertEqual(self.cache.read_bytes(), self.original)

    def test_exact_approved_invocation_adds_only_production_and_private_receipts(self):
        status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)['authority'], self.authority)
        cache = json.loads(self.cache.read_text())
        self.assertEqual(cache[:-1], self.old)
        self.assertEqual(cache[-1]['identity'], 'apply')
        self.assertEqual(self.sign_calls, 1)
        self.assertEqual(json.loads(T.paths()[0].read_text())['phase'], 'complete')
        for p in [self.cache, *T.paths()]:
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertFalse(any('secret' in a or 'apply' in a for a in self.reads))

    def test_identity_generation_expiry_and_signer_mismatches_reject_without_signing(self):
        for extra in [['--identity', 'plan'], ['--generation', '3'], ['--expires-at', '2027-01-26T02:58:13Z'],
                      ['--signer-authority', 'tlpub:' + 'c' * 64]]:
            with self.subTest(extra=extra):
                self.assertNotEqual(self.run_main(extra=extra)[0], 0)
                self.assertFalse(T.paths()[0].exists())
        self.assertEqual(self.sign_calls, 0)

    def test_wrong_provider_properties_reject_without_signing(self):
        for key, bad in [('generation', 3), ('expires_at', '2027-01-26T02:58:13Z'),
                         ('tags', ['tag:homelab-ci-plan']), ('ephemeral', False), ('invalid', True)]:
            with self.subTest(key=key):
                old = self.entry[key]
                self.entry[key] = bad
                self.assertEqual(self.run_main()[0], 1)
                self.entry[key] = old
        self.assertEqual(self.sign_calls, 0)

    def test_unsupported_cli_and_unapproved_actor_fail_closed(self):
        for which in ['cli', 'actor']:
            def read(args, operation):
                result = self.read(args, operation)
                if which == 'cli' and args == [T.CLI, 'version', '--json']:
                    result['gitCommit'] = '0' * 40
                if which == 'actor' and args[0] == 'gh':
                    result['login'] = 'unapproved'
                return result
            with self.subTest(which=which), patch.object(T.G, 'read_json', read):
                self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 0)

    def test_unsafe_permissions_shared_pending_and_source_drift_reject(self):
        self.cache.chmod(0o644)
        self.assertEqual(self.run_main()[0], 1)
        self.cache.chmod(0o600)
        T.S.pending_path().write_text('inert-untouched')
        self.assertEqual(self.run_main()[0], 1)
        T.S.pending_path().unlink()
        with patch.object(T.G, 'verify_main', side_effect=['f' * 40, 'e' * 40]):
            self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 0)

    def test_existing_authority_never_triggers_duplicate_signing(self):
        self.signed = True
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 0)
        self.assertEqual(self.cache.read_bytes(), self.original)

    def test_nonzero_and_delayed_readback_recover_without_second_sign(self):
        self.effect = 'nonzero'
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 1)
        self.visible = False
        self.assertEqual(self.run_main('recover')[0], 1)
        self.visible = True
        self.assertEqual(self.run_main('recover')[0], 0)
        before = self.cache.read_bytes()
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertEqual(self.sign_calls, 1)

    def test_timeout_with_captured_wrapper_recovers_without_second_sign(self):
        self.effect = 'timeout'
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.sign_calls, 1)

    def test_suspended_preparation_does_not_strand_complete_signing_output(self):
        self.effect = 'delay'
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.sign_calls, 1)

    def test_complete_capture_recovers_when_completion_stamp_was_lost(self):
        self.effect = 'nonzero'
        self.assertEqual(self.run_main()[0], 1)
        path = T.paths()[0]
        receipt = json.loads(path.read_text())
        receipt.pop('attempt_observed_end_at')
        path.write_text(json.dumps(receipt))
        self.now += 10000
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.sign_calls, 1)

    def test_interruption_before_output_never_blindly_retries(self):
        self.effect = 'interrupt'
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.sign_calls, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)
        self.assertTrue(T.paths()[0].exists())

    def test_partial_output_is_retained_and_never_signed_again(self):
        self.effect = 'partial'
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)
        self.assertTrue(T.paths()[1].is_file())

    def test_changed_cache_never_overwrites_existing_records(self):
        self.effect = 'cache-conflict'
        self.assertEqual(self.run_main()[0], 1)
        current = self.cache.read_bytes()
        self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.cache.read_bytes(), current)
        self.assertEqual(self.sign_calls, 1)

    def test_authority_metadata_must_match_authkey_mac_and_interval(self):
        original = dict(self.metadata)
        self.metadata['authkey_stableid'] = 'wrongid'
        self.assertEqual(self.run_main()[0], 1)
        for key, bad in [('wrapper_stableid', 'wrong-node'), ('wrapper_createtime', '1'),
                         ('wrapper_createtime', '1793301000')]:
            self.metadata = dict(original)
            self.metadata[key] = bad
            self.assertEqual(self.run_main('recover')[0], 1)
        self.metadata = original
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.sign_calls, 1)

    def test_unrelated_trust_change_stops_without_retiring_any_authority(self):
        def read(args, operation):
            result = self.read(args, operation)
            if self.signed and args == [T.CLI, 'lock', 'status', '--json']:
                result['TrustedKeys'].append({'Key': 'nlpub:' + 'c' * 64, 'Metadata': None, 'Votes': 1})
            return result
        with patch.object(T.G, 'read_json', read):
            self.assertEqual(self.run_main()[0], 1)
            self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.sign_calls, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)

    def test_old_or_new_authority_vote_changes_stop_without_cache_writes(self):
        for index in [0, -1]:
            def read(args, operation):
                result = self.read(args, operation)
                if self.signed and args == [T.CLI, 'lock', 'status', '--json']:
                    result['TrustedKeys'][index]['Votes'] = 2
                return result
            with patch.object(T.G, 'read_json', read):
                if not self.signed:
                    self.assertEqual(self.run_main()[0], 1)
                else:
                    self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.sign_calls, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)

    def test_output_symlink_and_missing_new_authority_acknowledgement_stop(self):
        target = self.directory / 'preserve.txt'
        target.write_text('preserve')
        T.paths()[1].symlink_to(target)
        self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(target.read_text(), 'preserve')
        T.paths()[1].unlink()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            args = self.arguments('execute')
            args.remove('--allow-new-delegated-authority')
            self.assertEqual(T.main(args), 1)
        self.assertEqual(self.sign_calls, 0)

    def test_provider_key_drift_stops_before_intent(self):
        calls = 0
        def read(args, operation):
            nonlocal calls
            result = self.read(args, operation)
            if args[0] == 'terragrunt':
                calls += 1
                if calls > 1:
                    other = dict(self.entry, key=T.S.AUTH_PREFIX + 'newid-inertNewSecret')
                    return {'github_auth_keys': {'sensitive': True, 'value': {'apply': other}}}
            return result
        with patch.object(T.G, 'read_json', read):
            self.assertEqual(self.run_main()[0], 1)
        self.assertEqual(self.sign_calls, 0)
        self.assertFalse(T.paths()[0].exists())

    def test_recovery_after_cache_write_before_complete_receipt_is_idempotent(self):
        save = T.S.save_private
        def fail_last(path, value):
            if path == T.paths()[0] and value.get('phase') == 'complete':
                raise OSError(self.key)
            return save(path, value)
        with patch.object(T.S, 'save_private', fail_last):
            self.assertEqual(self.run_main()[0], 1)
        before = self.cache.read_bytes()
        self.assertEqual(self.run_main('recover')[0], 0)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertEqual(self.sign_calls, 1)

    def test_receipt_identity_and_permissions_are_not_bypassed_on_recovery(self):
        self.effect = 'nonzero'
        self.assertEqual(self.run_main()[0], 1)
        receipt = T.paths()[0]
        receipt.chmod(0o644)
        self.assertEqual(self.run_main('recover')[0], 1)
        receipt.chmod(0o600)
        data = json.loads(receipt.read_text())
        data['identity'] = 'plan'
        receipt.write_text(json.dumps(data))
        self.assertEqual(self.run_main('recover')[0], 1)
        self.assertEqual(self.sign_calls, 1)

    def test_actual_subprocess_contract_uses_private_stdin_and_captured_output(self):
        with patch.object(T.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run:
            with tempfile.TemporaryFile(mode='w') as capture:
                self.assertEqual(self.original_invoke(self.key, capture), 0)
                args, kwargs = run.call_args
                self.assertEqual(args[0], [T.CLI, 'lock', 'sign', 'file:/dev/stdin'])
                self.assertEqual(kwargs['input'], self.key)
                self.assertIs(kwargs['stdout'], capture)
                self.assertIs(kwargs['stderr'], subprocess.PIPE)
                self.assertNotIn(self.key, ' '.join(args[0]))


ORIGINAL_INVOKE = T.invoke_sign
ProductionSigner.original_invoke = staticmethod(ORIGINAL_INVOKE)

if __name__ == '__main__':
    unittest.main()
