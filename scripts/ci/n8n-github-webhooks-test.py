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
            changed=False, delete_changed=False, fresh=True):
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
                        'url': hooks[identifier]['config']['url']}
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


if __name__ == '__main__':
    unittest.main()
