#!/usr/bin/env python3
"""Verify webhook changes preserve secrets, require reviewed main, and never emit events."""
import base64
import contextlib
from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('webhook', ROOT/'scripts/policy-bot-webhook.py')
webhook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(webhook)
EMERGENCY_SPEC = importlib.util.spec_from_file_location('emergency', ROOT/'scripts/policy-bot-webhook-emergency.py')
emergency = importlib.util.module_from_spec(EMERGENCY_SPEC)
EMERGENCY_SPEC.loader.exec_module(emergency)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        receipt = patch.object(webhook, 'RECEIPT', Path(temporary.name)/'receipt.json')
        receipt.start()
        self.addCleanup(receipt.stop)
        rollback_receipt = patch.object(webhook, 'ROLLBACK_RECEIPT', Path(temporary.name)/'rollback.json')
        rollback_receipt.start()
        self.addCleanup(rollback_receipt.stop)
        clock = patch.object(webhook.time, 'time', return_value=1791590400)
        clock.start()
        self.addCleanup(clock.stop)
        self.preflight = patch.object(webhook, 'preflight_target')
        self.preflight_mock = self.preflight.start()
        self.addCleanup(self.preflight.stop)

    def receipt(self):
        webhook.save_receipt(webhook.RECEIPT, {'url': webhook.URL, 'started_at': '2026-10-10T00:00:00+00:00', 'previous_delivery_id': 10})

    def api(self, url=None, deliveries=None, readback_changed=False, before=None, patch_url=None):
        config = {'url': url or webhook.PREVIOUS_URL, 'content_type': 'json', 'insecure_ssl': '0', 'secret': 'redacted'}
        deliveries = [] if deliveries is None else deliveries
        calls = []
        delivery_reads = 0
        def request(method, path, body=None):
            nonlocal delivery_reads
            calls.append((method, path, body))
            if path == webhook.CONFIG_PATH:
                if method == 'PATCH':
                    self.assertEqual(body, {'url': patch_url or webhook.URL})
                    config.update(body)
                    if readback_changed:
                        config['secret'] = 'changed'
                return dict(config)
            self.assertEqual(method, 'GET', 'Delivery verification must not create or redeliver events')
            if path == '/app/hook/deliveries?per_page=10':
                delivery_reads += 1
                return before if before is not None and delivery_reads == 1 else deliveries
            return next(item for item in deliveries if path == f"/app/hook/deliveries/{item['id']}")
        return request, calls

    def test_preview_reads_existing_delivery_without_mutation_or_secret_output(self):
        api, calls = self.api(deliveries=[{'id': 11, 'url': webhook.PREVIOUS_URL, 'status_code': 200, 'delivered_at': '2026-10-10T00:01:00Z'}])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(webhook.reconcile(api))
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        self.assertNotIn('redacted', output.getvalue())

    def test_execute_changes_url_only_and_reads_back_before_delivery(self):
        api, calls = self.api(deliveries=[{'id': 12, 'url': webhook.URL, 'status_code': 204, 'delivered_at': '2026-10-10T00:01:00Z'}], before=[])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(webhook.reconcile(api, execute=True, require_delivery=True))
        self.assertEqual(calls[:4], [('GET', webhook.CONFIG_PATH, None),
                                    ('GET', '/app/hook/deliveries?per_page=10', None),
                                    ('PATCH', webhook.CONFIG_PATH, {'url': webhook.URL}),
                                    ('GET', webhook.CONFIG_PATH, None)])
        self.assertNotIn('POST', [call[0] for call in calls])

    def test_rollback_changes_only_url_and_saves_private_separate_receipt(self):
        api, calls = self.api(url=webhook.URL, patch_url=webhook.PREVIOUS_URL,
                              before=[{'id': 20}], deliveries=[
                                  {'id': 21, 'url': webhook.PREVIOUS_URL, 'status_code': 204,
                                   'delivered_at': '2026-10-10T00:01:00Z'}])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertTrue(webhook.reconcile(api, execute=True, rollback=True, require_delivery=True))
        self.preflight_mock.assert_called_once_with(webhook.PREVIOUS_URL)
        self.assertEqual(calls[:4], [('GET', webhook.CONFIG_PATH, None),
                                    ('GET', '/app/hook/deliveries?per_page=10', None),
                                    ('PATCH', webhook.CONFIG_PATH, {'url': webhook.PREVIOUS_URL}),
                                    ('GET', webhook.CONFIG_PATH, None)])
        self.assertNotIn('redacted', output.getvalue())
        self.assertFalse(webhook.RECEIPT.exists())
        self.assertEqual(webhook.ROLLBACK_RECEIPT.stat().st_mode & 0o777, 0o600)
        self.assertEqual(webhook.read_receipt(webhook.ROLLBACK_RECEIPT, webhook.PREVIOUS_URL),
                         {'url': webhook.PREVIOUS_URL, 'started_at': '2026-10-10T00:00:00+00:00',
                          'previous_delivery_id': 20})

    def test_rollback_rejects_changed_secret_and_unapproved_current_url(self):
        api, calls = self.api(url=webhook.URL, patch_url=webhook.PREVIOUS_URL, readback_changed=True)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, rollback=True)
        self.assertIn(('PATCH', webhook.CONFIG_PATH, {'url': webhook.PREVIOUS_URL}), calls)
        self.assertFalse(webhook.ROLLBACK_RECEIPT.exists())
        api, calls = self.api(url='https://other.example.test/hook', patch_url=webhook.PREVIOUS_URL)
        with self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, rollback=True)
        self.assertEqual(calls, [('GET', webhook.CONFIG_PATH, None)])

    def test_unexpected_url_and_changed_settings_fail_closed(self):
        api, calls = self.api(url='https://other.example.test/hook')
        with self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True)
        self.assertEqual(len(calls), 1)
        api, _ = self.api(readback_changed=True)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True)

    def test_repeat_execution_is_idempotent_and_does_not_claim_pending_delivery(self):
        api, calls = self.api(url=webhook.URL)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, require_delivery=True)
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))

    def test_newest_matching_failure_is_not_hidden_by_old_success(self):
        self.receipt()
        api, _ = self.api(url=webhook.URL, deliveries=[
            {'id': 1, 'url': webhook.URL, 'status_code': 200, 'delivered_at': '2026-10-09T00:00:00Z'},
            {'id': 2, 'url': webhook.URL, 'status_code': 500, 'delivered_at': '2026-10-10T00:01:00Z'},
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(webhook.reconcile(api))

    def test_historical_or_pre_cutover_ids_cannot_satisfy_delivery_acceptance(self):
        self.receipt()
        for identifier, delivered in ((11, '2026-01-01T00:00:00Z'), (10, '2026-10-10T00:01:00Z')):
            api, calls = self.api(url=webhook.URL, deliveries=[
                {'id': identifier, 'url': webhook.URL, 'status_code': 200, 'delivered_at': delivered}])
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                webhook.reconcile(api, require_delivery=True)
            self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        api, _ = self.api(url=webhook.URL, deliveries=[
            {'id': 11, 'url': webhook.URL, 'status_code': 200, 'delivered_at': '2026-10-10T00:01:00Z'}])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(webhook.reconcile(api, require_delivery=True))

    def test_funnel_preflight_uses_normal_tls_dns_without_redirects_and_gates_patch(self):
        self.preflight.stop()
        opener = Mock()
        valid = ['db5cg1a1268s73dkrt6g']
        cases = [((404, 404), valid, [], True)]
        cases += [((status, 404), valid, [], False) for status in (200, 301, 400, 500)]
        cases += [((404, status), valid, [], False) for status in (200, 301, 400, 500)]
        cases += [((404, 404), ids, [], False) for ids in (
            [], [''], ['short'], ['z' * 20], ['a' * 21], ['a' * 1000], valid * 2)]
        cases += [((404, 404), valid, ids, False) for ids in (valid, [''])]
        for statuses, hook_ids, root_ids, success in cases:
            errors = []
            for url, status, ids in zip((webhook.URL, webhook.URL.removesuffix('/api/github/hook') + '/'),
                                       statuses, (hook_ids, root_ids)):
                headers = Message()
                for request_id in ids:
                    headers['X-Request-ID'] = request_id
                errors.append(webhook.urllib.error.HTTPError(url, status, '', headers, io.BytesIO()))
            opener.reset_mock()
            opener.open.side_effect = errors
            with self.subTest(statuses=statuses, hook_ids=hook_ids, root_ids=root_ids), \
                    patch.object(webhook.urllib.request, 'build_opener', return_value=opener) as factory:
                if success:
                    webhook.preflight_target()
                    self.assertEqual(factory.call_args.args[0].proxies, {})
                    self.assertIsInstance(factory.call_args.args[1], webhook.NoRedirect)
                    self.assertEqual(opener.open.call_count, 2)
                else:
                    with self.assertRaises(RuntimeError):
                        webhook.preflight_target()
                for call in opener.open.call_args_list:
                    self.assertEqual(call.args[0].method, 'GET')
                    self.assertFalse(call.args[0].headers)
            for error in errors:
                error.close()
        api, calls = self.api()
        with patch.object(webhook, 'preflight_target', side_effect=RuntimeError('unreachable')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True)
        self.assertEqual(calls, [('GET', webhook.CONFIG_PATH, None)])

    def test_rollback_preflight_checks_previous_hook_and_root_before_patch(self):
        self.preflight.stop()
        hook = webhook.PREVIOUS_URL
        root = hook.removesuffix('/api/github/hook') + '/'
        valid_id = 'db5cg1a1268s73dkrt6g'
        calls = []
        def response(*args):
            calls.append(args)
            if args[0] == 'dig':
                return b'104.21.93.45\n172.67.204.106\n'
            url = args[-1]
            return (f'HTTP/2 404\r\nx-request-id: {valid_id}\r\n\r\n' if url == hook
                    else 'HTTP/2 404\r\n\r\n').encode()
        with patch.object(webhook, 'command', side_effect=response):
            webhook.preflight_target(webhook.PREVIOUS_URL)
        self.assertEqual(calls[0], ('dig', '+short', '@1.1.1.1', 'policy-bot-hook.stinkyboi.com', 'A'))
        self.assertEqual([call[-1] for call in calls[1:]], [hook, root, hook, root])
        self.assertEqual([call[call.index('--resolve') + 1] for call in calls[1:]],
                         ['policy-bot-hook.stinkyboi.com:443:104.21.93.45'] * 2 +
                         ['policy-bot-hook.stinkyboi.com:443:172.67.204.106'] * 2)
        self.assertTrue(all('--noproxy' in call and '--resolve' in call and '-k' not in call
                            and '--insecure' not in call and '-L' not in call for call in calls[1:]))
        for bad_hook, bad_root in ((b'HTTP/2 404\r\n\r\n', b'HTTP/2 404\r\n\r\n'),
                                   (b'HTTP/2 302\r\nlocation: /\r\n\r\n', b'HTTP/2 404\r\n\r\n'),
                                   (f'HTTP/2 404\r\nx-request-id: {valid_id}\r\n\r\n'.encode(),
                                    f'HTTP/2 404\r\nx-request-id: {valid_id}\r\n\r\n'.encode())):
            with patch.object(webhook, 'command', side_effect=lambda *args: b'104.21.93.45\n'
                              if args[0] == 'dig' else bad_hook if args[-1] == hook else bad_root):
                with self.assertRaises(RuntimeError):
                    webhook.preflight_target(webhook.PREVIOUS_URL)
        with patch.object(webhook, 'command', return_value=b'not-an-ip\n'):
            with self.assertRaises(RuntimeError):
                webhook.preflight_target(webhook.PREVIOUS_URL)
        api, calls = self.api(url=webhook.URL, patch_url=webhook.PREVIOUS_URL)
        with patch.object(webhook, 'preflight_target', side_effect=RuntimeError('unreachable')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, rollback=True)
        self.assertEqual(calls, [('GET', webhook.CONFIG_PATH, None)])

    def test_execution_guard_checks_clean_checkout_head_and_remote_main(self):
        sha = 'a' * 40
        with patch.object(webhook, 'command', side_effect=[b'', sha.encode(), (sha+'\trefs/heads/main').encode(), b'']) as command:
            webhook.verify_reviewed_main(sha)
            self.assertIn('HEAD:scripts/policy-bot-webhook.py', command.call_args.args)
        for expected, replies in ((None, []), (sha, [b' M tracked-file']),
                                  (sha, [b'', b'b'*40, sha.encode()]),
                                  (sha, [b'', sha.encode(), b'b'*40])):
            with self.subTest(expected=expected, replies=replies), patch.object(webhook, 'command', side_effect=replies):
                with self.assertRaises(RuntimeError):
                    webhook.verify_reviewed_main(expected)
        with patch.object(webhook.sys, 'argv', ['helper', '--execute']), \
             patch.object(webhook, 'credentials') as credentials:
            with self.assertRaises(RuntimeError):
                webhook.main()
            credentials.assert_not_called()
        with patch.object(webhook.sys, 'argv', ['helper', '--execute', '--rollback']), \
             patch.object(webhook, 'credentials') as credentials:
            with self.assertRaises(RuntimeError):
                webhook.main()
            credentials.assert_not_called()

    def test_secret_is_read_only_into_memory(self):
        config = {'github': {'app': {'integration_id': 123, 'private_key': ' '.join(('-----BEGIN', 'PRIVATE', 'KEY-----')) + '\nfixture'}}}
        secret = {'data': {'policy-bot.yml': base64.b64encode(b'private YAML fixture').decode()}}
        with patch.object(webhook, 'command', side_effect=[json.dumps(secret).encode(), json.dumps(config).encode()]) as command:
            app_id, key = webhook.credentials()
            self.assertEqual(app_id, '123')
            self.assertTrue(key.startswith(b'-----BEGIN'))
            self.assertEqual(command.call_args.kwargs['input'], b'private YAML fixture')
            self.assertNotIn(key.decode(), ' '.join(command.call_args.args))

    def test_github_client_accepts_empty_202_for_official_redelivery(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 202
        response.read.return_value = b''
        with patch.object(webhook.urllib.request, 'build_opener', return_value=opener):
            api = webhook.github_client('fixture-token')
            self.assertEqual(api('POST', '/app/hook/deliveries/123/attempts'), 202)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertIsNone(request.data)

    def test_real_rsa_jwt_signature_and_short_expiry(self):
        private_key = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'], stderr=subprocess.DEVNULL)
        public_key = subprocess.run(['openssl', 'pkey', '-pubout'], input=private_key, capture_output=True, check=True).stdout
        with patch.object(webhook.time, 'time', return_value=2000000000):
            token = webhook.app_jwt('123', private_key)
        header, payload, signature = token.split('.')
        def decode(value):
            return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        self.assertEqual(json.loads(decode(header)), {'alg': 'RS256', 'typ': 'JWT'})
        self.assertEqual(json.loads(decode(payload)), {'iat': 1999999940, 'exp': 2000000540, 'iss': '123'})
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'public.pem').write_bytes(public_key)
            (folder/'signature').write_bytes(decode(signature))
            result = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(folder/'public.pem'),
                                     '-signature', str(folder/'signature')], input=(header+'.'+payload).encode(), capture_output=True)
            self.assertEqual(result.returncode, 0)


class EmergencyGuardTests(unittest.TestCase):
    def test_only_clean_signed_current_main_pr_head_passes(self):
        main, head = 'a' * 40, 'b' * 40
        pull = {'state': 'open', 'head': {'sha': head, 'ref': emergency.BRANCH,
                'repo': {'full_name': emergency.REPO}}, 'base': {'ref': 'main', 'sha': main}}
        commit = {'sha': head, 'commit': {'verification': {'verified': True}}}
        replies = [b'', head.encode(), b'', b'', json.dumps(commit).encode(),
                   (main + '\trefs/heads/main').encode(), main.encode(), json.dumps([pull]).encode()]
        with patch.object(emergency, 'command', side_effect=replies) as command:
            emergency.verify_emergency_source(main, head)
        self.assertEqual(command.call_count, len(replies))
        self.assertEqual(command.call_args.args[:2], ('gh', 'api'))

        for change in ('dirty', 'stale-main', 'other-head', 'unsigned', 'other-pr'):
            altered = list(replies)
            if change == 'dirty':
                altered[0] = b' M scripts/policy-bot-webhook.py'
            elif change == 'stale-main':
                altered[5] = ('c' * 40).encode()
            elif change == 'other-head':
                altered[1] = ('c' * 40).encode()
            elif change == 'unsigned':
                altered[4] = json.dumps({'sha': head, 'commit': {'verification': {'verified': False}}}).encode()
            else:
                altered[7] = json.dumps([dict(pull, head=dict(pull['head'], ref='other'))]).encode()
            with self.subTest(change=change), patch.object(emergency, 'command', side_effect=altered):
                with self.assertRaises(RuntimeError):
                    emergency.verify_emergency_source(main, head)

    def test_emergency_requires_explicit_execute_before_source_or_credentials(self):
        with patch.object(emergency.sys, 'argv', ['helper', '--expected-main', 'a' * 40,
                                                   '--expected-head', 'b' * 40, '--rollback']), \
             patch.object(emergency, 'verify_emergency_source') as verify:
            with self.assertRaises(RuntimeError):
                emergency.main()
            verify.assert_not_called()

    def test_emergency_is_only_for_first_rollback_from_active_funnel(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webhook, 'ROLLBACK_RECEIPT', Path(directory)/'rollback.json'):
            api = Mock(return_value={'url': webhook.URL})
            emergency.require_active_funnel(api, webhook)
            api.assert_called_once_with('GET', webhook.CONFIG_PATH)
            api.reset_mock(return_value=True)
            api.return_value = {'url': webhook.PREVIOUS_URL}
            with self.assertRaises(RuntimeError):
                emergency.require_active_funnel(api, webhook)
            webhook.ROLLBACK_RECEIPT.touch()
            api.reset_mock()
            with self.assertRaises(RuntimeError):
                emergency.require_active_funnel(api, webhook)
            api.assert_not_called()

    def test_emergency_resume_saves_missing_receipt_without_second_patch(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webhook, 'ROLLBACK_RECEIPT', Path(directory)/'rollback.json'), \
             patch.object(emergency, 'REDELIVERY_RECEIPT', Path(directory)/'redelivery.json'), \
             patch.object(emergency, 'require_failed_pr_head') as require_pr, \
             patch.object(webhook, 'preflight_target'):
            calls = []
            delivery_reads = 0
            def api(method, path, body=None):
                nonlocal delivery_reads
                calls.append((method, path))
                if method != 'GET':
                    self.fail('Resume must not mutate the App callback')
                if path == webhook.CONFIG_PATH:
                    return {'url': webhook.PREVIOUS_URL, 'secret': 'redacted'}
                if path == '/app/hook/deliveries?per_page=10':
                    delivery_reads += 1
                    return ([{'id': emergency.FAILED_DELIVERY_ID + 1}]
                            if delivery_reads == 1 else [])
                self.fail(f'Unexpected API path: {path}')
            with contextlib.redirect_stdout(io.StringIO()):
                emergency.resume_rollback(api, webhook)
            require_pr.assert_called_once_with()
            self.assertTrue(webhook.ROLLBACK_RECEIPT.exists())
            self.assertNotIn('PATCH', [method for method, _ in calls])
            with self.assertRaises(RuntimeError):
                emergency.resume_rollback(api, webhook)
            webhook.ROLLBACK_RECEIPT.unlink()
            emergency.REDELIVERY_RECEIPT.touch()
            with self.assertRaises(RuntimeError):
                emergency.resume_rollback(api, webhook)
            emergency.REDELIVERY_RECEIPT.unlink()
            with patch.object(webhook, 'reconcile') as reconcile, self.assertRaises(RuntimeError):
                emergency.resume_rollback(lambda *_: {'url': webhook.URL}, webhook)
            reconcile.assert_not_called()
            config_reads = 0
            attempted = []
            def changed_api(method, path, *_args):
                nonlocal config_reads
                attempted.append(method)
                if method != 'GET':
                    self.fail('Resume sent a callback mutation after the URL changed')
                if path == webhook.CONFIG_PATH:
                    config_reads += 1
                    return {'url': webhook.PREVIOUS_URL if config_reads == 1 else webhook.URL}
                if path == '/app/hook/deliveries?per_page=10':
                    return []
                self.fail(f'Unexpected API path: {path}')
            with self.assertRaisesRegex(RuntimeError, 'cannot change the App callback'):
                emergency.resume_rollback(changed_api, webhook)
            self.assertEqual(attempted, ['GET', 'GET', 'GET'])
            self.assertFalse(webhook.ROLLBACK_RECEIPT.exists())

    def test_redelivery_is_one_exact_post_after_receipt_and_payload_checks(self):
        failed = {
            'id': emergency.FAILED_DELIVERY_ID, 'guid': 'fixture-guid', 'url': webhook.URL,
            'event': 'check_run', 'action': 'completed', 'status_code': 500,
            'redelivery': False, 'delivered_at': '2026-10-25T15:12:53Z',
            'request': {'payload': {'action': 'completed', 'repository': {'full_name': emergency.REPO},
                       'check_run': {'name': 'Terragrunt Gate', 'status': 'completed',
                                     'conclusion': 'success', 'head_sha': emergency.FAILED_CHECK_SHA,
                                     'check_suite': {'head_sha': emergency.FAILED_CHECK_SHA},
                                     'pull_requests': [{'number': emergency.FAILED_PR}]}}},
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webhook, 'ROLLBACK_RECEIPT', Path(directory)/'rollback.json'), \
             patch.object(emergency, 'REDELIVERY_RECEIPT', Path(directory)/'redelivery.json'), \
             patch.object(webhook.time, 'time', return_value=2000000000):
            webhook.save_receipt(webhook.ROLLBACK_RECEIPT, {
                'url': webhook.PREVIOUS_URL, 'started_at': '2026-10-25T15:20:00+00:00',
                'previous_delivery_id': emergency.FAILED_DELIVERY_ID + 1})
            calls = []
            def api(method, path):
                calls.append((method, path))
                if path == webhook.CONFIG_PATH:
                    return {'url': webhook.PREVIOUS_URL}
                if method == 'POST':
                    self.assertTrue(emergency.REDELIVERY_RECEIPT.exists())
                    return 202
                return failed
            current_pr = {'state': 'open', 'head': {'sha': emergency.FAILED_CHECK_SHA},
                          'base': {'ref': 'main'}}
            with patch.object(emergency, 'command', return_value=json.dumps(current_pr).encode()), \
                 contextlib.redirect_stdout(io.StringIO()):
                emergency.redeliver_failed_gate(api, webhook)
            self.assertEqual(calls, [('GET', webhook.CONFIG_PATH),
                                     ('GET', f'/app/hook/deliveries/{emergency.FAILED_DELIVERY_ID}'),
                                     ('POST', f'/app/hook/deliveries/{emergency.FAILED_DELIVERY_ID}/attempts')])
            self.assertEqual(emergency.REDELIVERY_RECEIPT.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(emergency.REDELIVERY_RECEIPT.read_text())['guid'], 'fixture-guid')
            with self.assertRaises(RuntimeError):
                emergency.redeliver_failed_gate(api, webhook)
            emergency.REDELIVERY_RECEIPT.unlink()
            uncertain_calls = []
            def uncertain_api(method, path):
                uncertain_calls.append((method, path))
                if path == webhook.CONFIG_PATH:
                    return {'url': webhook.PREVIOUS_URL}
                return 500 if method == 'POST' else failed
            with patch.object(emergency, 'command', return_value=json.dumps(current_pr).encode()), \
                 self.assertRaises(RuntimeError):
                emergency.redeliver_failed_gate(uncertain_api, webhook)
            self.assertTrue(emergency.REDELIVERY_RECEIPT.exists())
            uncertain_calls.clear()
            with self.assertRaises(RuntimeError):
                emergency.redeliver_failed_gate(uncertain_api, webhook)
            self.assertNotIn('POST', [method for method, _ in uncertain_calls])
            emergency.REDELIVERY_RECEIPT.unlink()
            for field, value in (('status_code', 200), ('url', webhook.PREVIOUS_URL),
                                 ('event', 'pull_request')):
                changed = dict(failed, **{field: value})
                with self.subTest(field=field):
                    calls.clear()
                    def bad_api(method, path):
                        calls.append((method, path))
                        return {'url': webhook.PREVIOUS_URL} if path == webhook.CONFIG_PATH else changed
                    with self.assertRaises(RuntimeError):
                        emergency.redeliver_failed_gate(bad_api, webhook)
                    self.assertNotIn('POST', [method for method, _ in calls])
            for change in ('wrong-sha', 'wrong-pr', 'active-funnel'):
                changed = json.loads(json.dumps(failed))
                if change == 'wrong-sha':
                    changed['request']['payload']['check_run']['head_sha'] = '0' * 40
                elif change == 'wrong-pr':
                    changed['request']['payload']['check_run']['pull_requests'] = [{'number': 1680}]
                calls.clear()
                def bad_api(method, path):
                    calls.append((method, path))
                    if path == webhook.CONFIG_PATH:
                        return {'url': webhook.URL if change == 'active-funnel' else webhook.PREVIOUS_URL}
                    return changed
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    emergency.redeliver_failed_gate(bad_api, webhook)
                self.assertNotIn('POST', [method for method, _ in calls])

    def test_verify_requires_exact_fresh_redelivery_and_policy_status(self):
        new_id = emergency.FAILED_DELIVERY_ID + 100
        detail = {
            'id': new_id, 'guid': 'fixture-guid', 'url': webhook.PREVIOUS_URL,
            'event': 'check_run', 'action': 'completed', 'status_code': 204,
            'redelivery': True, 'delivered_at': '2026-10-25T15:21:00Z',
            'request': {'payload': {'action': 'completed', 'repository': {'full_name': emergency.REPO},
                       'check_run': {'name': 'Terragrunt Gate', 'status': 'completed',
                                     'conclusion': 'success', 'head_sha': emergency.FAILED_CHECK_SHA,
                                     'check_suite': {'head_sha': emergency.FAILED_CHECK_SHA},
                                     'pull_requests': [{'number': emergency.FAILED_PR}]}}},
        }
        item = {key: detail[key] for key in ('id', 'guid', 'redelivery', 'delivered_at')}
        status = {'sha': emergency.FAILED_CHECK_SHA,
                  'statuses': [{'context': 'policy-bot: main', 'state': 'success'}]}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webhook, 'ROLLBACK_RECEIPT', Path(directory)/'rollback.json'), \
             patch.object(emergency, 'REDELIVERY_RECEIPT', Path(directory)/'redelivery.json'), \
             patch.object(webhook.time, 'time', return_value=2000000000):
            webhook.save_receipt(webhook.ROLLBACK_RECEIPT, {
                'url': webhook.PREVIOUS_URL, 'started_at': '2026-10-25T15:15:00+00:00',
                'previous_delivery_id': emergency.FAILED_DELIVERY_ID + 1})
            webhook.save_receipt(emergency.REDELIVERY_RECEIPT, {
                'delivery_id': emergency.FAILED_DELIVERY_ID, 'guid': 'fixture-guid',
                'started_at': '2026-10-25T15:20:00+00:00'})
            calls = []
            def api(method, path):
                calls.append((method, path))
                if path == webhook.CONFIG_PATH:
                    return {'url': webhook.PREVIOUS_URL}
                if path.startswith('/app/hook/deliveries?'):
                    return [item]
                return detail
            with patch.object(emergency, 'command', return_value=json.dumps(status).encode()), \
                 contextlib.redirect_stdout(io.StringIO()):
                emergency.verify_redelivery(api, webhook)
            self.assertEqual(calls, [('GET', webhook.CONFIG_PATH),
                                     ('GET', '/app/hook/deliveries?per_page=100&status=success'),
                                     ('GET', f'/app/hook/deliveries/{new_id}')])
            self.assertNotIn('POST', [method for method, _ in calls])
            item['guid'] = 'unrelated-guid'
            with self.assertRaises(RuntimeError):
                emergency.verify_redelivery(api, webhook)
            item['guid'] = 'fixture-guid'
            status['statuses'][0]['state'] = 'pending'
            with patch.object(emergency, 'command', return_value=json.dumps(status).encode()), \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                emergency.verify_redelivery(api, webhook)


if __name__ == '__main__':
    unittest.main()
