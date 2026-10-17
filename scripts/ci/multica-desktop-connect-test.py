#!/usr/bin/env python3
"""Check mesh readiness, credential preservation, and exact macOS migration ownership."""
import copy
import importlib.util
import json
from pathlib import Path
import plistlib
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('desktop', ROOT / 'scripts/multica-desktop-connect.py')
desktop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(desktop)
ADDRESS = '100.100.10.20'
IPV6 = 'fd7a:115c:a1e0::1234'
ADDRESSES = [ADDRESS, IPV6]
STATUS = {'BackendState': 'Running', 'CurrentTailnet': {'MagicDNSSuffix': desktop.TAILNET},
          'Self': {'ID': 'own-profile', 'UserID': 1, 'Online': True, 'TailscaleIPs': ['100.100.10.21']},
          'Peer': {'ingress': {'DNSName': desktop.INGRESS + '.', 'Online': True, 'TailscaleIPs': ADDRESSES}}}


class MigrationTests(unittest.TestCase):
    def test_resume_changes_no_saved_preferences_or_profile(self):
        stopped = copy.deepcopy(STATUS)
        stopped['BackendState'] = 'Stopped'
        stopped['Self']['Online'] = False
        with patch.object(desktop, 'run', side_effect=[json.dumps(stopped), '', json.dumps(STATUS)]) as run:
            self.assertEqual(desktop.mesh_addresses(True), ADDRESSES)
            self.assertEqual(run.call_args_list[1].args, (desktop.TAILSCALE, 'up'))
        for changed in ('other-tailnet', 'different-owner', 'different-profile', 'stopped'):
            after = copy.deepcopy(STATUS)
            if changed == 'other-tailnet':
                after['CurrentTailnet']['MagicDNSSuffix'] = 'other.ts.net'
            elif changed == 'different-owner':
                after['Self']['UserID'] = 2
            elif changed == 'different-profile':
                after['Self']['ID'] = 'other-profile'
            else:
                after['BackendState'] = 'Stopped'
            with self.subTest(changed=changed), patch.object(desktop, 'run', side_effect=[json.dumps(STATUS), json.dumps(after)]):
                with self.assertRaises(RuntimeError):
                    desktop.mesh_addresses()

    def test_resume_waits_for_same_profile_network_extension(self):
        stopped = copy.deepcopy(STATUS)
        stopped['BackendState'] = 'Stopped'
        stopped['Self']['Online'] = False
        with patch.object(desktop, 'run', side_effect=[json.dumps(stopped), '', json.dumps(stopped), json.dumps(STATUS)]), \
                patch.object(desktop.time, 'sleep') as sleep:
            self.assertEqual(desktop.mesh_addresses(True), ADDRESSES)
            sleep.assert_called_once_with(0.5)

    def test_resume_only_never_migrates_desktop_or_carrier(self):
        with patch.object(desktop.sys, 'argv', ['multica-desktop-connect.py', '--resume-only']), \
             patch.object(desktop.sys, 'platform', 'darwin'), \
             patch.object(desktop.os, 'geteuid', return_value=501), \
             patch.object(desktop, 'mesh_addresses', return_value=ADDRESSES) as mesh, \
             patch.object(desktop, 'migrate') as migrate:
            desktop.main()
            mesh.assert_called_once_with(True)
            migrate.assert_not_called()

    def test_auth_requires_mesh_dns_valid_tls_and_exact_user_without_redirects(self):
        response = SimpleNamespace(status=200, read=lambda _limit: b'{"id":"owner"}')
        connection = Mock()
        connection.getresponse.return_value = response
        resolved = [(2, 1, 6, '', (ADDRESS, 443)), (10, 1, 6, '', (IPV6, 443, 0, 0))]
        with patch.object(desktop.socket, 'getaddrinfo', return_value=resolved), \
             patch.object(desktop.http.client, 'HTTPSConnection', return_value=connection) as factory:
            desktop.authenticated_ready(ADDRESSES, 'fixture-token', 'owner')
            context = factory.call_args.kwargs['context']
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            connection.request.assert_called_with('GET', '/api/me', headers={'Authorization': 'Bearer fixture-token'})
            for status in (301, 401, 403, 500):
                response.status = status
                with self.subTest(status=status), self.assertRaises(RuntimeError):
                    desktop.authenticated_ready(ADDRESSES, 'fixture-token', 'owner')
            response.status = 200
            with self.assertRaises(RuntimeError):
                desktop.authenticated_ready(ADDRESSES, 'fixture-token', 'other-user')
        for invalid in ([], [(2, 1, 6, '', ('1.1.1.1', 443))], resolved + [(2, 1, 6, '', ('1.1.1.1', 443))]):
            with patch.object(desktop.socket, 'getaddrinfo', return_value=invalid):
                with self.assertRaises(RuntimeError):
                    desktop.authenticated_ready(ADDRESSES, 'fixture-token', 'owner')

    def exercise(self, *, auth_failed=False, api_failed=False, conflict=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        profile = home / '.multica'
        source = profile / 'profiles/desktop-127.0.0.1-18080'
        target = profile / 'profiles/desktop-multica.stinkyboi.com'
        source.mkdir(parents=True)
        target.mkdir()
        credentials = {'server_url': 'http://127.0.0.1:18080', 'token': 'fixture-token', 'other': 'preserved'}
        (source/'config.json').write_text(json.dumps(credentials))
        (source/'.desktop-user-id').write_text('owner\n')
        (target/'config.json').write_text(json.dumps(dict(server_url=desktop.API, **({'token': 'different-token'} if conflict else {}))))
        original = json.dumps({'apiUrl': credentials['server_url'], 'wsUrl': 'ws://127.0.0.1:18080/ws', 'appUrl': 'unchanged'})
        (profile/'desktop.json').write_text(original)
        (profile/'desktop.before-octelium.json').write_text('old unrelated backup')
        runner = profile/'octelium-client.py'
        runner.write_text(desktop.LABEL)
        plist = home/'Library/LaunchAgents'/f'{desktop.LABEL}.plist'
        plist.parent.mkdir(parents=True)
        plist.write_bytes(plistlib.dumps({'Label': desktop.LABEL, 'ProgramArguments': ['python3', str(runner), '--supervise', 'octelium']}))
        carrier = SimpleNamespace(probe=Mock(return_value=not api_failed), PLIST=home/'system.plist', MARKER='# unused-fixture')
        carrier.PLIST.touch()
        with patch.object(desktop, 'authenticated_ready', side_effect=RuntimeError('auth failed') if auth_failed else None) as auth, \
             patch.object(desktop, 'carrier_module', return_value=carrier), \
             patch.object(desktop, 'run') as run, \
             patch.object(desktop.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as subprocess_run:
            if auth_failed or api_failed or conflict:
                with self.assertRaises(RuntimeError):
                    desktop.migrate(home, ADDRESSES)
                self.assertEqual((profile/'desktop.json').read_text(), original)
                self.assertTrue(plist.exists() and runner.exists())
                run.assert_not_called()
                subprocess_run.assert_not_called()
                return
            desktop.migrate(home, ADDRESSES)
            auth.assert_called_once_with(ADDRESSES, 'fixture-token', 'owner')
            self.assertEqual(json.loads((target/'config.json').read_text()), dict(credentials, server_url=desktop.API))
            self.assertEqual((target/'.desktop-user-id').read_bytes(), (source/'.desktop-user-id').read_bytes())
            self.assertEqual((target/'config.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((profile/'desktop.json').read_text()), {
                'apiUrl': desktop.API, 'wsUrl': 'wss://multica.stinkyboi.com/ws', 'appUrl': 'unchanged'})
            self.assertEqual((profile/'desktop.json.before-tailscale').read_text(), original)
            self.assertEqual((profile/'desktop.before-octelium.json').read_text(), 'old unrelated backup')
            self.assertEqual(json.loads((source/'config.json').read_text()), credentials)
            self.assertFalse(plist.exists() or runner.exists())
            self.assertTrue(any(call.args[0][-5:] == ['migrate-to-tailscale', '--mesh-address', ADDRESS, '--mesh-address', IPV6]
                                for call in subprocess_run.call_args_list))
            desktop.migrate(home, ADDRESSES)
            self.assertEqual((profile/'desktop.json.before-tailscale').read_text(), original)

    def test_migration_preserves_tokens_markers_unknown_settings_and_backups(self):
        self.exercise()

    def test_failed_auth_keeps_working_octelium_state(self):
        self.exercise(auth_failed=True)

    def test_failed_native_api_keeps_working_octelium_state(self):
        self.exercise(api_failed=True)

    def test_conflicting_canonical_token_is_never_overwritten(self):
        self.exercise(conflict=True)


if __name__ == '__main__':
    unittest.main()
