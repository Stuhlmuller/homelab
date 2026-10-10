#!/usr/bin/env python3
"""Verify webhook changes preserve secrets, require reviewed main, and never emit events."""
import base64
import contextlib
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
        clock = patch.object(webhook.time, 'time', return_value=1791590400)
        clock.start()
        self.addCleanup(clock.stop)
        self.preflight = patch.object(webhook, 'preflight_target')
        self.preflight.start()
        self.addCleanup(self.preflight.stop)

    def receipt(self):
        webhook.save_receipt(webhook.RECEIPT, {'url': webhook.URL, 'started_at': '2026-10-10T00:00:00+00:00', 'previous_delivery_id': 10})

    def api(self, url=None, deliveries=None, readback_changed=False, before=None):
        config = {'url': url or webhook.PREVIOUS_URL, 'content_type': 'json', 'insecure_ssl': '0', 'secret': 'redacted'}
        deliveries = [] if deliveries is None else deliveries
        calls = []
        delivery_reads = 0
        def request(method, path, body=None):
            nonlocal delivery_reads
            calls.append((method, path, body))
            if path == webhook.CONFIG_PATH:
                if method == 'PATCH':
                    self.assertEqual(body, {'url': webhook.URL})
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
        for statuses, success in (((400, 404), True), ((200, 404), False), ((400, 200), False), ((301, 404), False)):
            errors = [webhook.urllib.error.HTTPError(url, status, '', {}, io.BytesIO())
                                      for url, status in zip((webhook.URL, webhook.URL.removesuffix('/api/github/hook') + '/'), statuses)]
            opener.open.side_effect = errors
            with patch.object(webhook.urllib.request, 'build_opener', return_value=opener) as factory:
                if success:
                    webhook.preflight_target()
                    self.assertEqual(factory.call_args.args[0].proxies, {})
                    self.assertIsInstance(factory.call_args.args[1], webhook.NoRedirect)
                    self.assertEqual(opener.open.call_args.args[0].method, 'GET')
                    self.assertFalse(opener.open.call_args.args[0].headers)
                else:
                    with self.assertRaises(RuntimeError):
                        webhook.preflight_target()
            for error in errors:
                error.close()
        api, calls = self.api()
        with patch.object(webhook, 'preflight_target', side_effect=RuntimeError('unreachable')), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            webhook.reconcile(api, execute=True)
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
