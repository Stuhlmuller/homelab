#!/usr/bin/env python3
"""Verify the surviving n8n hook and exact retired helper lifecycle."""
import contextlib
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('n8n_hooks', ROOT / 'scripts/n8n-github-webhooks.py')
HOOKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOKS)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        receipts = patch.object(HOOKS, 'RECEIPTS', Path(temporary.name))
        receipts.start()
        self.addCleanup(receipts.stop)
        clock = patch.object(HOOKS.CALLBACKS.time, 'time', return_value=1791590400)
        clock.start()
        self.addCleanup(clock.stop)

    def api(self, *, drift=False, retired_drift=False, duplicate_callback_host=None,
            changed=False, delete_changed=False, fresh=True, signature='sha256=' + 'a' * 64):
        hooks = {identifier: {'id': identifier, 'name': 'web', 'active': True, 'events': ['pull_request'],
                             'config': {'url': HOOKS.PREVIOUS_HOST + '/webhook/' + path,
                                        'content_type': 'json', 'secret': 'redacted', 'insecure_ssl': '0'}}
                 for identifier, path in HOOKS.HOOKS.items()}
        hooks[HOOKS.RETIRED_HOOK] = {
            'id': HOOKS.RETIRED_HOOK, 'name': 'web', 'active': True, 'events': ['pull_request'],
            'config': {'url': HOOKS.HOST + '/webhook/' + HOOKS.RETIRED_PATH,
                       'content_type': 'json', 'secret': 'redacted', 'insecure_ssl': '0'},
        }
        if drift:
            hooks[next(iter(HOOKS.HOOKS))]['events'] = ['push']
        if retired_drift:
            hooks[HOOKS.RETIRED_HOOK]['events'] = ['push']
        if duplicate_callback_host:
            hooks[777] = {'id': 777, 'config': {'url': duplicate_callback_host + '/webhook/' + HOOKS.RETIRED_PATH}}
        calls, patched = [], set()
        def api(method, path, body=None):
            calls.append((method, path, body))
            self.assertIn(method, ('GET', 'PATCH', 'DELETE'))
            if path == HOOKS.COLLECTION:
                return deepcopy(list(hooks.values()))
            suffix = path.removeprefix(HOOKS.BASE)
            identifier = int(suffix.split('/')[0])
            self.assertIn(identifier, hooks)
            if method == 'DELETE':
                self.assertEqual(suffix, str(HOOKS.RETIRED_HOOK))
                del hooks[identifier]
                if delete_changed:
                    hooks[HOOKS.EMERGENCY_HOOK]['config']['secret'] = 'changed'
                return None
            if method == 'PATCH':
                self.assertEqual(suffix, str(identifier) + '/config')
                self.assertEqual(body, {'url': HOOKS.HOST + '/webhook/' + HOOKS.HOOKS[identifier]})
                hooks[identifier]['config'].update(body)
                if changed:
                    hooks[identifier]['config']['secret'] = 'changed'
                patched.add(identifier)
                return deepcopy(hooks[identifier]['config'])
            if suffix == str(identifier):
                return deepcopy(hooks[identifier])
            delivery = {'id': 12 if identifier in patched else 11, 'status_code': 200,
                        'delivered_at': '2026-10-10T00:01:00Z' if fresh else '2026-01-01T00:00:00Z',
                        'url': hooks[identifier]['config']['url'],
                        'request': {'headers': {'X-Hub-Signature-256': signature} if signature else {}}}
            return [delivery] if '?' in path else delivery
        return api, calls

    def test_preview_has_no_probes_writes_or_secret_output(self):
        api, calls = self.api()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(HOOKS, 'preflight') as probe:
            self.assertFalse(HOOKS.reconcile(api))
        probe.assert_not_called()
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        self.assertNotIn('redacted', output.getvalue())

    def test_execute_changes_only_surviving_url_and_records_fresh_delivery(self):
        api, calls = self.api()
        with contextlib.redirect_stdout(io.StringIO()), patch.object(HOOKS, 'preflight') as probe:
            self.assertTrue(HOOKS.reconcile(api, execute=True, require_delivery=True))
            self.assertTrue(HOOKS.reconcile(api, execute=True, require_delivery=True))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(len([call for call in calls if call[0] == 'PATCH']), 1)
        for identifier in HOOKS.HOOKS:
            path = HOOKS.RECEIPTS / f'n8n-github-hook-{identifier}-cutover.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['previous_delivery_id'], 11)

    def test_surviving_hook_and_preflight_must_pass_before_any_patch(self):
        for drift in (True, False):
            api, calls = self.api(drift=drift)
            with contextlib.redirect_stdout(io.StringIO()), patch.object(HOOKS, 'preflight', side_effect=RuntimeError('not ready')), \
                 self.assertRaises(RuntimeError):
                HOOKS.reconcile(api, execute=True)
            self.assertFalse(any(method == 'PATCH' for method, _, _ in calls))

    def test_changed_settings_and_historical_deliveries_fail(self):
        for arguments in ({'changed': True}, {'fresh': False}):
            api, _ = self.api(**arguments)
            with contextlib.redirect_stdout(io.StringIO()), patch.object(HOOKS, 'preflight'), self.assertRaises(RuntimeError):
                HOOKS.reconcile(api, execute=True, require_delivery=True)

    def test_unsigned_or_malformed_success_cannot_pass_delivery_gate(self):
        for signature in (None, 'sha256=invalid'):
            api, _ = self.api(signature=signature)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(HOOKS, 'preflight'), \
                 self.assertRaisesRegex(RuntimeError, 'lacks a GitHub SHA-256 signature header'):
                HOOKS.reconcile(api, execute=True, require_delivery=True)
            self.assertNotIn('redacted', output.getvalue())

    def test_preflight_uses_only_root_get_and_nonexecuting_options(self):
        with patch.object(HOOKS, 'safe_probe', side_effect=[(404, {}), (204, {'Access-Control-Allow-Methods': 'OPTIONS, POST'}),
                                                         (204, {'Access-Control-Allow-Methods': 'POST, OPTIONS'})]) as probe:
            HOOKS.preflight()
            self.assertEqual(probe.call_args_list[0].args, (HOOKS.HOST + '/',))
            self.assertEqual([call.args[1] for call in probe.call_args_list[1:]], ['OPTIONS'])
        for result in ((200, {}), (204, {}), (204, {'Access-Control-Allow-Methods': 'OPTIONS, POST, GET'})):
            with patch.object(HOOKS, 'safe_probe', side_effect=[(404, {}), result]), self.assertRaises(RuntimeError):
                HOOKS.preflight()
        response = Mock(status=204, headers={'Access-Control-Allow-Methods': 'OPTIONS, POST'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(HOOKS.urllib.request, 'build_opener', return_value=opener) as factory:
            HOOKS.safe_probe(HOOKS.HOST + '/webhook/' + next(iter(HOOKS.HOOKS.values())), 'OPTIONS')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.method, 'OPTIONS')
            self.assertEqual(request.get_header('Access-control-request-method'), 'POST')
            self.assertNotIn('Authorization', request.headers)
            self.assertEqual(factory.call_args.args[0].proxies, {})
            self.assertIsInstance(factory.call_args.args[1], HOOKS.CALLBACKS.NoRedirect)

    def test_exact_main_guard_precedes_reconciliation(self):
        for arguments in (['--execute'], ['--retire-helper', '--execute']):
            with patch.object(HOOKS.sys, 'argv', ['helper', *arguments]), \
                 patch.object(HOOKS, 'reconcile') as reconcile, self.assertRaises(RuntimeError):
                HOOKS.main()
            reconcile.assert_not_called()

    def test_repeated_cli_retirement_skips_delivery_gate_after_verified_absence(self):
        with patch.object(HOOKS.sys, 'argv', ['helper', '--retire-helper', '--execute',
                                             '--expected-sha', 'a' * 40]), \
             patch.object(HOOKS.CALLBACKS, 'verify_reviewed_main') as guard, \
             patch.object(HOOKS.CALLBACKS, 'command', return_value=b''), \
             patch.object(HOOKS, 'hook_inventory', return_value={}), \
             patch.object(HOOKS, 'retire_helper') as retire, \
             patch.object(HOOKS, 'reconcile') as reconcile:
            HOOKS.main()
        guard.assert_called_once_with('a' * 40)
        retire.assert_called_once_with(execute=True)
        reconcile.assert_not_called()

    def test_retirement_is_exact_idempotent_and_preserves_emergency(self):
        api, calls = self.api()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(HOOKS, 'preflight'):
            HOOKS.reconcile(api, execute=True, require_delivery=True)
            HOOKS.retire_helper(api)
            HOOKS.retire_helper(api, execute=True)
            HOOKS.retire_helper(api, execute=True)
            HOOKS.require_retired_absent(api)
        self.assertEqual(len([call for call in calls if call[0] == 'DELETE']), 1)
        self.assertEqual([call[1] for call in calls if call[0] == 'DELETE'],
                         [HOOKS.BASE + str(HOOKS.RETIRED_HOOK)])
        self.assertNotIn('redacted', output.getvalue())
        with patch.object(HOOKS.CALLBACKS, 'command', return_value=b''):
            self.assertIsNone(HOOKS.github('DELETE', HOOKS.BASE + str(HOOKS.RETIRED_HOOK)))

    def test_retirement_rejects_drift_and_incomplete_inventory_before_delete(self):
        for kwargs in ({'retired_drift': True},
                       {'duplicate_callback_host': HOOKS.HOST},
                       {'duplicate_callback_host': 'https://third-host.example'}):
            api, calls = self.api(**kwargs)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                HOOKS.retire_helper(api, execute=True)
            self.assertFalse(any(call[0] == 'DELETE' for call in calls))
        with self.assertRaises(RuntimeError):
            HOOKS.hook_inventory(lambda *_: [{'id': identifier, 'config': {}} for identifier in range(100)])

    def test_retirement_detects_surviving_hook_change_after_delete(self):
        api, calls = self.api(delete_changed=True)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            HOOKS.retire_helper(api, execute=True)
        self.assertEqual(len([call for call in calls if call[0] == 'DELETE']), 1)

    def test_delivery_gate_requires_retired_id_and_path_absent(self):
        api, _ = self.api()
        with self.assertRaises(RuntimeError):
            HOOKS.require_retired_absent(api)
        with contextlib.redirect_stdout(io.StringIO()):
            HOOKS.retire_helper(api, execute=True)
        HOOKS.require_retired_absent(api)
        third_api, _ = self.api(duplicate_callback_host='https://third-host.example')
        third_api('DELETE', HOOKS.BASE + str(HOOKS.RETIRED_HOOK))
        with self.assertRaises(RuntimeError):
            HOOKS.require_retired_absent(third_api)

    def native_fixture(self):
        inventory = [
            {'id': HOOKS.EMERGENCY_HOOK, 'name': 'web', 'active': True,
             'events': ['pull_request'], 'config': {'url': HOOKS.OLD_URL}},
            {'id': 777777, 'name': 'web', 'active': True, 'events': ['pull_request'],
             'config': {'url': HOOKS.NATIVE_URL, 'content_type': 'json',
                        'insecure_ssl': '0', 'secret': 'redacted'}},
        ]
        deliveries = [
            {'id': 61, 'event': 'ping', 'delivered_at': '2026-10-10T00:02:00Z'},
            {'id': 62, 'event': 'pull_request', 'delivered_at': '2026-10-10T00:03:00Z'},
        ]
        detail = {'id': 62, 'event': 'pull_request', 'delivered_at': '2026-10-10T00:03:00Z',
                  'url': HOOKS.NATIVE_URL, 'status_code': 200,
                  'request': {'headers': {'X-Hub-Signature-256': 'sha256=' + 'a' * 64}}}
        current_config = {'url': HOOKS.NATIVE_URL, 'content_type': 'json',
                          'insecure_ssl': '0', 'secret': '********'}
        current_hook = deepcopy(inventory[1])
        current_hook['updated_at'] = '2026-10-10T00:01:00Z'
        calls, probes = [], []
        hook_endpoint = HOOKS.BASE + '777777'
        endpoint = hook_endpoint + '/deliveries'

        def api(method, path, body=None):
            calls.append((method, path, body))
            self.assertEqual(method, 'GET')
            self.assertIsNone(body)
            if path == HOOKS.COLLECTION:
                return deepcopy(inventory)
            if path == endpoint + '?per_page=100':
                return deepcopy(deliveries)
            if path == endpoint + '/62':
                return deepcopy(detail)
            if path == endpoint + '/63':
                return dict(deepcopy(detail), id=63, delivered_at='2026-10-10T00:04:00Z',
                            status_code=500)
            if path == hook_endpoint + '/config':
                return deepcopy(current_config)
            if path == hook_endpoint:
                return deepcopy(current_hook)
            self.fail('Unexpected GitHub API request: ' + path)

        def probe(url, method='GET'):
            probes.append((url, method))
            if url == HOOKS.HOST + '/' and method == 'GET':
                return 404, {}
            if url == HOOKS.OLD_URL and method == 'OPTIONS':
                return 404, {'Content-Type': 'text/plain; charset=utf-8'}
            if url == HOOKS.NATIVE_URL and method == 'OPTIONS':
                return 204, {'Access-Control-Allow-Methods': 'OPTIONS, POST'}
            self.fail('Unexpected network probe')

        return inventory, deliveries, detail, current_config, current_hook, api, calls, probe, probes

    def test_native_verifier_discovers_signed_delivery_and_only_reads(self):
        _, _, _, _, _, api, calls, probe, probes = self.native_fixture()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertTrue(HOOKS.verify_signed_trigger(api, '2026-10-10T00:00:00Z', probe))
        self.assertEqual([path for _, path, _ in calls],
                         [HOOKS.COLLECTION, HOOKS.BASE + '777777/deliveries?per_page=100',
                          HOOKS.BASE + '777777/deliveries/62', HOOKS.BASE + '777777/config',
                          HOOKS.BASE + '777777'])
        self.assertEqual(probes, [(HOOKS.HOST + '/', 'GET'), (HOOKS.OLD_URL, 'OPTIONS'),
                                  (HOOKS.NATIVE_URL, 'OPTIONS')])
        self.assertNotIn('redacted', output.getvalue())
        self.assertNotIn('sha256=', output.getvalue())

    def test_native_verifier_rejects_missing_duplicate_and_drifted_hooks(self):
        for mutation in ('missing', 'duplicate', 'wrong_host', 'wrong_event',
                         'inactive', 'form', 'insecure', 'old_drift', 'retired'):
            inventory, _, _, _, _, api, calls, probe, probes = self.native_fixture()
            native = inventory[1]
            if mutation == 'missing':
                inventory.pop()
            elif mutation == 'duplicate':
                duplicate = deepcopy(native)
                duplicate['id'] = 888888
                inventory.append(duplicate)
            elif mutation == 'wrong_host':
                native['config']['url'] = 'https://elsewhere.example/webhook/' + HOOKS.NATIVE_PATH + '/webhook'
            elif mutation == 'wrong_event':
                native['events'] = ['push']
            elif mutation == 'inactive':
                native['active'] = False
            elif mutation == 'form':
                native['config']['content_type'] = 'form'
            elif mutation == 'insecure':
                native['config']['insecure_ssl'] = '1'
            elif mutation == 'old_drift':
                inventory[0]['config']['url'] = HOOKS.PREVIOUS_HOST + '/webhook/' + HOOKS.HOOKS[HOOKS.EMERGENCY_HOOK]
            elif mutation == 'retired':
                inventory.append({'id': HOOKS.RETIRED_HOOK, 'config': {'url': 'https://example.test'}})
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                HOOKS.verify_signed_trigger(api, '2026-10-10T00:00:00Z', probe)
            self.assertEqual([method for method, _, _ in calls], ['GET'])
            self.assertEqual(probes, [])

    def test_native_verifier_rejects_unsigned_stale_failed_or_superseded_delivery(self):
        for mutation in ('unsigned', 'malformed', 'stale', 'failed', 'wrong_url', 'later_failure'):
            _, deliveries, detail, _, _, api, calls, probe, _ = self.native_fixture()
            if mutation == 'unsigned':
                detail['request']['headers'] = {}
            elif mutation == 'malformed':
                detail['request']['headers']['X-Hub-Signature-256'] = 'sha256=bad'
            elif mutation == 'stale':
                detail['delivered_at'] = deliveries[1]['delivered_at'] = '2026-10-09T00:03:00Z'
            elif mutation == 'failed':
                detail['status_code'] = 500
            elif mutation == 'wrong_url':
                detail['url'] = HOOKS.OLD_URL
            elif mutation == 'later_failure':
                deliveries.append({'id': 63, 'event': 'pull_request', 'delivered_at': '2026-10-10T00:04:00Z'})
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                HOOKS.verify_signed_trigger(api, '2026-10-10T00:00:00Z', probe)
            self.assertTrue(all(method == 'GET' for method, _, _ in calls))

    def test_native_verifier_rejects_missing_secret_and_hook_drift_after_delivery(self):
        for mutation in ('missing_secret', 'empty_secret', 'unmasked_secret',
                         'config_drift', 'updated_after_delivery', 'updated_at_delivery'):
            _, _, _, config, current_hook, api, calls, probe, _ = self.native_fixture()
            if mutation == 'missing_secret':
                del config['secret']
            elif mutation == 'empty_secret':
                config['secret'] = ''
            elif mutation == 'unmasked_secret':
                config['secret'] = 'raw-value-must-not-print'
            elif mutation == 'config_drift':
                config['content_type'] = 'form'
            elif mutation == 'updated_after_delivery':
                current_hook['updated_at'] = '2026-10-10T00:04:00Z'
            elif mutation == 'updated_at_delivery':
                current_hook['updated_at'] = '2026-10-10T00:03:00Z'
            output = io.StringIO()
            with self.subTest(mutation=mutation), contextlib.redirect_stdout(output), \
                 self.assertRaises(RuntimeError):
                HOOKS.verify_signed_trigger(api, '2026-10-10T00:00:00Z', probe)
            self.assertEqual(calls[-2][1:], (HOOKS.BASE + '777777/config', None))
            self.assertEqual(calls[-1][1:], (HOOKS.BASE + '777777', None))
            self.assertNotIn('raw-value-must-not-print', output.getvalue())

    def test_native_verifier_requires_old_denial_new_route_and_activation_time(self):
        _, _, _, _, _, api, calls, probe, _ = self.native_fixture()
        for stamp in (None, '2026-10-10', '2026-10-10T00:00:00+01:00', '2999-01-01T00:00:00Z'):
            with self.subTest(stamp=stamp), self.assertRaises(RuntimeError):
                HOOKS.verify_signed_trigger(api, stamp, probe)
        self.assertEqual(calls, [])
        for denied in (False, True, 'n8n_404'):
            def drift_probe(url, method='GET'):
                status, headers = probe(url, method)
                if denied is True and url == HOOKS.OLD_URL:
                    return 204, headers
                if denied == 'n8n_404' and url == HOOKS.OLD_URL:
                    return 404, {'Content-Type': 'text/html; charset=utf-8',
                                 'Access-Control-Allow-Methods': 'OPTIONS'}
                if denied is False and url == HOOKS.NATIVE_URL:
                    return 404, headers
                return status, headers
            with self.subTest(old_route_open=denied), self.assertRaises(RuntimeError):
                HOOKS.verify_signed_trigger(api, '2026-10-10T00:00:00Z', drift_probe)

    def test_native_cli_is_separate_from_legacy_mutation(self):
        with patch.object(HOOKS.sys, 'argv', ['helper', '--verify-signed-trigger',
                                             '--activated-after', '2026-10-10T00:00:00Z']), \
             patch.object(HOOKS, 'verify_signed_trigger') as verify, \
             patch.object(HOOKS, 'reconcile') as reconcile:
            HOOKS.main()
        verify.assert_called_once_with(activated_after='2026-10-10T00:00:00Z')
        reconcile.assert_not_called()
        for argument in ('--execute', '--retire-helper', '--require-delivery'):
            with patch.object(HOOKS.sys, 'argv', ['helper', '--verify-signed-trigger', argument]), \
                 patch.object(HOOKS, 'verify_signed_trigger') as verify, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                HOOKS.main()
            verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
