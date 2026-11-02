#!/usr/bin/env python3
"""Production-only cached-key publication; no live services or real keys."""
import base64
import copy
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('production', Path(__file__).parents[1] / 'harbor-tailscale-production.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ProductionOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / 'cache.json'
        self.key = M.SHARED.AUTH_PREFIX + 'testid-inertPrivateSentinel'
        self.authority = 'tlpub:' + 'b' * 64
        self.mac = 'tlpub:' + 'a' * 64
        self.wrapped = self.key + '--TL' + base64.b64encode(b'inert').decode().rstrip('=') + '-' + base64.b64encode(b'x' * 64).decode().rstrip('=')
        self.entry = dict(key=self.key, id='inert-id', generation=2, invalid=False, reusable=True,
                          ephemeral=True, preauthorized=True, tags=[M.TAG],
                          expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
        self.record = dict(identity='apply', generation=2, fingerprint=M.SHARED.fingerprint(self.entry),
                           wrapped=self.wrapped, authority=self.authority)
        self.save_cache([self.record])
        self.commands = []
        self.reads = []
        self.present = False
        self.calls_main = 0
        self.drift = False
        self.failed_confirmation = False
        self.addCleanup(patch.stopall)
        patch.object(M.SHARED, 'CACHE', self.cache).start()
        patch.object(M.G, 'read_json', self.read).start()
        patch.object(M.G, 'github', self.github).start()
        patch.object(M.G, 'command', self.command).start()
        patch.object(M.G, 'verify_main', self.main_sha).start()

    def save_cache(self, records):
        self.cache.write_text(json.dumps(records))
        self.cache.chmod(0o600)

    def main_sha(self):
        self.calls_main += 1
        return ('b' if self.drift and self.calls_main > 1 else 'a') * 40

    def github(self, path, operation):
        if path == 'branches/main':
            return {'protected': True}
        self.assertIn('homelab-production', path)
        if path.endswith('/deployment-branch-policies'):
            return {'branch_policies': [{'id': 1, 'name': 'main', 'type': 'branch'}]}
        return {'name': 'homelab-production', 'can_admins_bypass': False,
                'protection_rules': [{'type': 'branch_policy'}],
                'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}}

    def read(self, args, operation):
        self.reads.append(args)
        if args[:2] == ['gh', 'api']:
            return {'login': 'rstuhlmuller'}
        if args[0] == 'terragrunt':
            return {'github_auth_keys': {'sensitive': True, 'value': {'apply': self.entry,
                    'plan': {'invalid-unrelated': True}, 'cordium': {'invalid-unrelated': True}}}}
        if args[:3] == ['tailscale', 'status', '--json']:
            return {'BackendState': 'Running', 'Self': {'Online': True},
                    'CurrentTailnet': {'MagicDNSSuffix': 'tail67beb.ts.net'}}
        if args[:3] == ['tailscale', 'lock', 'status']:
            return {'Enabled': True, 'NodeKeySigned': True, 'PublicKey': self.mac, 'TrustedKeys': [
                {'Key': self.mac, 'Metadata': None}, {'Key': self.authority,
                 'Metadata': {'purpose': 'pre-auth key', 'authkey_stableid': 'testid'}}]}
        if args[:3] == ['gh', 'secret', 'list']:
            self.assertEqual(args[args.index('--env') + 1], M.ENVIRONMENT)
            return [{'name': M.SECRET}] if self.present and not self.failed_confirmation else []
        self.fail('Unexpected read command')

    def command(self, args, operation, *, data=None):
        self.assertEqual(args, ['gh', 'secret', 'set', M.SECRET, '--repo', M.G.HOST_REPO, '--env', M.ENVIRONMENT])
        self.assertEqual(data, self.wrapped + '\n')
        self.assertNotIn(self.key, ' '.join(args))
        self.commands.append(args)
        self.present = True
        return ''

    def run_main(self, execute=False, *extra):
        args = ['--execute', '--generation', '2', '--authority', self.authority, '--expires-at', self.entry['expires_at']] if execute else []
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = M.main(args + list(extra))
        self.assertNotIn(self.key, out.getvalue() + err.getvalue())
        self.assertNotIn(self.wrapped, out.getvalue() + err.getvalue())
        return status, out.getvalue(), err.getvalue()

    def test_preview_has_no_writes_or_signing(self):
        status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertFalse(json.loads(out)['new_signing'])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.calls_main, 1)

    def test_execute_writes_only_production_and_preserves_cache(self):
        before = self.cache.read_bytes()
        self.assertEqual(self.run_main(True)[0], 0)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertFalse(any('homelab-plan' in args or 'TAILSCALE_CORDIUM_AUTH_KEY' in args for args in self.reads))

    def test_missing_cached_key_never_signs(self):
        self.save_cache([])
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_expired_wrong_tag_or_non_ephemeral_key_stops(self):
        for key, bad in [('tags', ['tag:homelab-ci-plan']), ('ephemeral', False), ('reusable', False),
                         ('expires_at', (datetime.now(timezone.utc) - timedelta(days=1)).isoformat())]:
            with self.subTest(key=key):
                old = self.entry[key]
                self.entry[key] = bad
                self.assertEqual(self.run_main(True)[0], 1)
                self.entry[key] = old
        self.assertEqual(self.commands, [])

    def test_existing_secret_is_not_overwritten(self):
        self.present = True
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_approval_pins_and_main_drift_stop(self):
        self.assertEqual(self.run_main(True, '--generation', '3')[0], 1)
        self.calls_main = 0
        self.assertEqual(self.run_main(True, '--expires-at', '2030-01-01T00:00:00Z')[0], 1)
        self.calls_main = 0
        self.drift = True
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_uncertain_write_is_not_retried(self):
        self.failed_confirmation = True
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(len(self.commands), 1)

    def test_private_cache_permissions_are_required(self):
        self.cache.chmod(0o644)
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_unapproved_github_identity_stops(self):
        def read(args, operation):
            if args[:2] == ['gh', 'api']:
                return {'login': 'unapproved'}
            return self.read(args, operation)
        with patch.object(M.G, 'read_json', read):
            self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_wrong_or_missing_authority_stops(self):
        self.record['authority'] = 'tlpub:' + 'c' * 64
        self.save_cache([self.record])
        self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])


    def nlpub_read(self, args, operation):
        result = self.read(args, operation)
        if args[:3] == ['tailscale', 'lock', 'status']:
            result['PublicKey'] = result['PublicKey'].replace('tlpub:', 'nlpub:')
            for item in result['TrustedKeys']:
                item['Key'] = item['Key'].replace('tlpub:', 'nlpub:')
        return result

    def test_nlpub_status_matches_cli_cache_without_writes(self):
        before = self.cache.read_bytes()
        with patch.object(M.G, 'read_json', self.nlpub_read):
            status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)['authority'], self.authority)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.cache.read_bytes(), before)

    def test_nlpub_cache_uses_canonical_approval_without_cache_changes(self):
        self.record['authority'] = self.authority.replace('tlpub:', 'nlpub:')
        self.save_cache([self.record])
        before = self.cache.read_bytes()
        with patch.object(M.G, 'read_json', self.nlpub_read):
            self.assertEqual(self.run_main(True)[0], 0)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.cache.read_bytes(), before)

    def test_legacy_public_meta_status_remains_supported(self):
        def read(args, operation):
            result = self.read(args, operation)
            if args[:3] == ['tailscale', 'lock', 'status']:
                result['TrustedKeys'] = [{'Public': x['Key'], 'Meta': x['Metadata']}
                                         for x in result['TrustedKeys']]
            return result
        with patch.object(M.G, 'read_json', read):
            self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.commands, [])

    def test_duplicate_key_aliases_are_rejected(self):
        def read(args, operation):
            result = self.nlpub_read(args, operation)
            if args[:3] == ['tailscale', 'lock', 'status']:
                duplicate = dict(result['TrustedKeys'][-1])
                duplicate['Key'] = self.authority
                result['TrustedKeys'].append(duplicate)
            return result
        with patch.object(M.G, 'read_json', read):
            self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_invalid_authority_types_prefixes_lengths_and_hex_stop(self):
        for authority in [None, 42, 'nodekey:' + 'b' * 64, 'nlpub:' + 'b' * 63,
                          'nlpub:' + 'g' * 64, 'nlpub:' + 'b' * 64 + 'suffix']:
            with self.subTest(authority=authority):
                self.record['authority'] = authority
                self.save_cache([self.record])
                with patch.object(M.G, 'read_json', self.nlpub_read):
                    self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_matching_generation_with_different_provider_key_stops(self):
        self.entry['key'] = M.SHARED.AUTH_PREFIX + 'newid-inertDifferentPrivateSentinel'
        with patch.object(M.G, 'read_json', self.nlpub_read):
            self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_same_fingerprint_with_wrong_wrapped_key_stops(self):
        self.record['wrapped'] = self.wrapped.replace('testid-', 'differentid-', 1)
        self.save_cache([self.record])
        with patch.object(M.G, 'read_json', self.nlpub_read):
            self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])

    def test_normalized_authority_still_requires_authkey_metadata(self):
        def read(args, operation):
            result = self.nlpub_read(args, operation)
            if args[:3] == ['tailscale', 'lock', 'status']:
                result['TrustedKeys'][-1]['Metadata']['authkey_stableid'] = 'differentid'
            return result
        with patch.object(M.G, 'read_json', read):
            self.assertEqual(self.run_main(True)[0], 1)
        self.assertEqual(self.commands, [])


class WorkflowPolicy(unittest.TestCase):
    def test_only_reviewed_production_workflow_passes(self):
        root = Path(__file__).resolve().parents[2]
        workflow = json.loads(subprocess.check_output([
            'yq', '-o=json', '.', str(root / '.github/workflows/harbor-mirror.yml')], text=True))
        yaml_result = subprocess.run(['conftest', 'test', '--policy', str(root / 'policy/workflows.rego'),
                                      str(root / '.github/workflows/harbor-mirror.yml')], capture_output=True, text=True)
        self.assertEqual(yaml_result.returncode, 0, yaml_result.stdout + yaml_result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workflow.json'
            def verdict(document):
                path.write_text(json.dumps(document))
                return subprocess.run(['conftest', 'test', '--policy', str(root / 'policy/workflows.rego'),
                                       str(path)], capture_output=True, text=True)
            result = verdict(workflow)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for change in ['environment', 'tag', 'secret', 'action', 'event', 'event_alias', 'output', 'permissions', 'name']:
                bad = copy.deepcopy(workflow)
                job = bad['jobs']['mirror']
                join = next(x for x in job['steps'] if x['name'] == 'Join Production Tailnet')
                if change == 'environment':
                    job['environment']['name'] = 'homelab-plan'
                if change == 'tag':
                    join['with']['tags'] = 'tag:homelab-ci-cordium'
                if change == 'secret':
                    join['with']['authkey'] = '${{ secrets.TAILSCALE_CORDIUM_AUTH_KEY }}'
                if change == 'action':
                    join['uses'] = 'tailscale/github-action@v4'
                if change == 'event':
                    bad['on']['push'] = {}
                if change == 'event_alias':
                    bad['true'] = {'push': {}}
                if change == 'output':
                    job['steps'].append({'run': 'echo "$TAILSCALE_AUTH_KEY"'})
                if change == 'permissions':
                    job['permissions']['contents'] = 'write'
                if change == 'name':
                    bad['name'] = 'Unreviewed workflow'
                with self.subTest(change=change):
                    result = verdict(bad)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Tailnet workflow access requires', result.stdout)


if __name__ == '__main__':
    unittest.main()
