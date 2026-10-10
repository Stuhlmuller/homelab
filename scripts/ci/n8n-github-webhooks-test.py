#!/usr/bin/env python3
"""Verify the fixed n8n hook cutover never sends events or changes secrets."""
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

    def api(self, *, drift=False, changed=False, fresh=True):
        hooks = {identifier: {'id': identifier, 'name': 'web', 'active': True, 'events': ['pull_request'],
                             'config': {'url': HOOKS.PREVIOUS_HOST + '/webhook/' + path,
                                        'content_type': 'json', 'secret': 'redacted', 'insecure_ssl': '0'}}
                 for identifier, path in HOOKS.HOOKS.items()}
        if drift:
            hooks[list(hooks)[-1]]['events'] = ['push']
        calls, patched = [], set()
        def api(method, path, body=None):
            calls.append((method, path, body))
            self.assertIn(method, ('GET', 'PATCH'))
            suffix = path.removeprefix(HOOKS.BASE)
            identifier = int(suffix.split('/')[0])
            self.assertIn(identifier, HOOKS.HOOKS)
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

    def test_execute_changes_only_both_fixed_urls_and_records_fresh_deliveries(self):
        api, calls = self.api()
        with contextlib.redirect_stdout(io.StringIO()), patch.object(HOOKS, 'preflight') as probe:
            self.assertTrue(HOOKS.reconcile(api, execute=True, require_delivery=True))
            self.assertTrue(HOOKS.reconcile(api, execute=True, require_delivery=True))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(len([call for call in calls if call[0] == 'PATCH']), 2)
        for identifier in HOOKS.HOOKS:
            path = HOOKS.RECEIPTS / f'n8n-github-hook-{identifier}-cutover.json'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['previous_delivery_id'], 11)

    def test_all_hooks_and_preflight_must_pass_before_any_patch(self):
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
            self.assertEqual([call.args[1] for call in probe.call_args_list[1:]], ['OPTIONS', 'OPTIONS'])
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
        with patch.object(HOOKS.sys, 'argv', ['helper', '--execute']), \
             patch.object(HOOKS, 'reconcile') as reconcile, self.assertRaises(RuntimeError):
            HOOKS.main()
        reconcile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
