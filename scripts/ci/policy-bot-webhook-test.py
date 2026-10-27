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
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('webhook', ROOT/'scripts/policy-bot-webhook.py')
webhook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(webhook)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        receipt = patch.object(webhook, 'RECEIPT', Path(temporary.name)/'receipt.json')
        receipt.start()
        self.addCleanup(receipt.stop)
        recovery_receipt = patch.object(webhook, 'RECOVERY_RECEIPT', Path(temporary.name)/'recovery.json')
        recovery_receipt.start()
        self.addCleanup(recovery_receipt.stop)
        clock = patch.object(webhook.time, 'time', return_value=1791590400)
        clock.start()
        self.addCleanup(clock.stop)
        self.preflight = patch.object(webhook, 'preflight_target')
        self.preflight_mock = self.preflight.start()
        self.addCleanup(self.preflight.stop)
        self.recovery_preflight = patch.object(webhook, 'preflight_recovery')
        self.recovery_preflight_mock = self.recovery_preflight.start()
        self.addCleanup(self.recovery_preflight.stop)

    def receipt(self):
        webhook.save_receipt(webhook.RECEIPT, {'url': webhook.URL, 'started_at': '2026-10-10T00:00:00+00:00', 'previous_delivery_id': 10})

    def api(self, url=None, deliveries=None, readback_changed=False, before=None, target=webhook.URL):
        config = {'url': url or webhook.PREVIOUS_URL, 'content_type': 'json', 'insecure_ssl': '0', 'secret': 'redacted'}
        deliveries = [] if deliveries is None else deliveries
        calls = []
        delivery_reads = 0
        def request(method, path, body=None):
            nonlocal delivery_reads
            calls.append((method, path, body))
            if path == webhook.CONFIG_PATH:
                if method == 'PATCH':
                    self.assertEqual(body, {'url': target})
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

    def test_emergency_rollback_changes_only_fixed_url_and_uses_separate_receipt(self):
        api, calls = self.api(url=webhook.URL, target=webhook.PREVIOUS_URL,
                              deliveries=[{'id': 12, 'url': webhook.PREVIOUS_URL,
                                           'status_code': 204, 'delivered_at': '2026-10-10T00:01:00Z'}], before=[])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(webhook.reconcile(api, execute=True, require_delivery=True, rollback=True))
        self.recovery_preflight_mock.assert_called_once_with()
        self.preflight_mock.assert_not_called()
        self.assertEqual(calls[:4], [('GET', webhook.CONFIG_PATH, None),
                                    ('GET', '/app/hook/deliveries?per_page=10', None),
                                    ('PATCH', webhook.CONFIG_PATH, {'url': webhook.PREVIOUS_URL}),
                                    ('GET', webhook.CONFIG_PATH, None)])
        self.assertTrue(webhook.RECOVERY_RECEIPT.exists())
        self.assertFalse(webhook.RECEIPT.exists())
        self.assertNotIn('POST', [call[0] for call in calls])

    def test_recovery_acceptance_uses_public_receipt_without_mutation(self):
        webhook.save_receipt(webhook.RECOVERY_RECEIPT, {
            'url': webhook.PREVIOUS_URL,
            'started_at': '2026-10-10T00:00:00+00:00',
            'previous_delivery_id': 10,
        })
        api, calls = self.api(deliveries=[{
            'id': 11, 'url': webhook.PREVIOUS_URL,
            'status_code': 200, 'delivered_at': '2026-10-10T00:01:00Z',
        }])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(webhook.reconcile(api, require_delivery=True, rollback=True))
            with self.assertRaises(RuntimeError):
                webhook.reconcile(api, require_delivery=True)
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))

    def test_unwritable_receipt_parent_fails_before_either_webhook_patch(self):
        blocked_parent = webhook.RECOVERY_RECEIPT.parent / 'not-a-directory'
        blocked_parent.write_text('fixture')
        receipt = blocked_parent / 'receipt.json'
        for rollback, current, target in ((False, webhook.PREVIOUS_URL, webhook.URL),
                                          (True, webhook.URL, webhook.PREVIOUS_URL)):
            api, calls = self.api(url=current, target=target)
            with self.subTest(rollback=rollback), self.assertRaises(OSError), \
                 contextlib.redirect_stdout(io.StringIO()):
                webhook.reconcile(api, execute=True, receipt_path=receipt, rollback=rollback)
            self.assertEqual(calls, [('GET', webhook.CONFIG_PATH, None),
                                     ('GET', '/app/hook/deliveries?per_page=10', None)])

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

    def test_recovery_preflight_uses_public_doh_strict_tls_and_gates_patch(self):
        self.recovery_preflight.stop()
        valid = 'dbf16h2clnhc73dhuh60'
        hook = f'HTTP/2 404\r\nX-Request-ID: {valid}\r\n\r\n'.encode()
        root = b'HTTP/2 404\r\n\r\n'
        calls = []
        def run(*args):
            calls.append(args)
            self.assertEqual(args[0], 'curl')
            self.assertEqual(args[1], '--disable')
            self.assertIn(('--noproxy', '*'), list(zip(args, args[1:])))
            self.assertIn(('--proto', '=https'), list(zip(args, args[1:])))
            self.assertIn(('--doh-url', 'https://1.1.1.1/dns-query'), list(zip(args, args[1:])))
            self.assertNotIn('--insecure', args)
            self.assertTrue(args[-1].startswith('https://policy-bot-hook.stinkyboi.com/'))
            return hook if args[-1] == webhook.PREVIOUS_URL else root
        with patch.object(webhook, 'command', side_effect=run):
            webhook.preflight_recovery()
        self.assertEqual(len(calls), 2)
        api, writes = self.api(url=webhook.URL, target=webhook.PREVIOUS_URL)
        with patch.object(webhook, 'command', side_effect=RuntimeError('DoH unavailable')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, rollback=True)
        self.assertEqual(writes, [('GET', webhook.CONFIG_PATH, None)])
        with patch.object(webhook, 'command', return_value=root), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True, rollback=True)
        self.assertEqual(writes, [('GET', webhook.CONFIG_PATH, None),
                                  ('GET', webhook.CONFIG_PATH, None)])

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

    def test_recovery_guard_requires_signed_one_commit_pr_on_current_main(self):
        head, main, pr = 'a' * 40, 'b' * 40, 1683
        replies = [b'', head.encode(), (main + '\trefs/heads/main').encode(), main.encode(),
                   (head + f'\trefs/pull/{pr}/head').encode(),
                   json.dumps({'sha': head, 'commit': {'verification': {'verified': True}}}).encode(), b'']
        with patch.object(webhook, 'command', side_effect=replies) as command:
            webhook.verify_reviewed_main(head, pr)
            self.assertTrue(any(call.args[0] == 'curl' and call.args[-1].endswith(head)
                                and '--fail' in call.args and '--disable' in call.args
                                for call in command.call_args_list))
        for parent, ref in ((head, head), (main, main), (main, '')):
            replies = [b'', head.encode(), main.encode(), parent.encode(),
                       (ref + f'\trefs/pull/{pr}/head').encode() if ref else b'']
            with self.subTest(parent=parent, ref=ref), \
                 patch.object(webhook, 'command', side_effect=replies), self.assertRaises(RuntimeError):
                webhook.verify_reviewed_main(head, pr)
        replies = [b'', head.encode(), main.encode(), main.encode(),
                   (head + f'\trefs/pull/{pr}/head').encode(),
                   json.dumps({'sha': head, 'commit': {'verification': {'verified': False}}}).encode()]
        with patch.object(webhook, 'command', side_effect=replies), self.assertRaises(RuntimeError):
            webhook.verify_reviewed_main(head, pr)
        with patch.object(webhook.sys, 'argv', ['helper', '--rollback-to-previous', '--execute',
                                                 '--expected-sha', head]), \
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


if __name__ == '__main__':
    unittest.main()
