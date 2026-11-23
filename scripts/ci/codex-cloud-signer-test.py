#!/usr/bin/env python3
"""Offline security checks; no real credentials, network or signatures."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import HTTPServer
import importlib.util
import json
from pathlib import Path
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('signer', ROOT / 'clusters/homelab/apps/codex-cloud-signer/server.py')
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
NOW = 1793600000
KEY = 'synthetic-webhook-secret-for-tests'
NODE = 'nSynthetic123'
DEVICE = {'nodeId': NODE, 'tags': [S.TAG], 'isEphemeral': True, 'isExternal': False,
          'connectedToControl': True, 'authorized': True, 'os': 'linux',
          'created': datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),
          'name': 'agent.' + S.SUFFIX, 'nodeKey': 'nodekey:' + 'a' * 64,
          'tailnetLockKey': 'nlpub:' + 'b' * 64, 'tailnetLockError': 'unsigned'}
EVENT = {'version': 1, 'type': 'nodeNeedsSignature', 'data': {'nodeID': NODE}}
LOCK = {'Enabled': True, 'NodeKeySigned': True, 'PublicKey': 'nlpub:' + 'c' * 64,
        'TrustedKeys': [{'Key': 'nlpub:' + 'c' * 64}],
        'FilteredPeers': [{'StableID': NODE, 'NodeKey': DEVICE['nodeKey']}]}


def header(body, when=NOW):
    digest = hmac.new(KEY.encode(), str(when).encode() + b'.' + body, hashlib.sha256).hexdigest()
    return f't={when},v1={digest}'


class SignerTests(unittest.TestCase):
    def test_short_oauth_id_is_valid_but_short_secrets_are_not(self):
        with TemporaryDirectory() as directory, patch.object(S, 'SECRETS', Path(directory)):
            (Path(directory) / 'oauth-client-id').write_text('k1234511CNTRL')
            self.assertEqual(S.secret('oauth-client-id'), 'k1234511CNTRL')
            for value in ('short', 'REPLACE_ME', ''):
                (Path(directory) / 'webhook-secret').write_text(value)
                with self.assertRaises(RuntimeError):
                    S.secret('webhook-secret')

    def test_hmac_raw_bytes_freshness_and_rotation(self):
        body = b'[ {"version": 1} ]'
        self.assertTrue(S.verify_signature(body, header(body), KEY, NOW))
        self.assertTrue(S.verify_signature(body, header(body), KEY, NOW + 3601))
        self.assertTrue(S.verify_signature(body, header(body) + ',v1=' + 'f' * 64, KEY, NOW))
        for signature, raw, now in ((header(body), b'[]', NOW), (header(body), body, NOW + S.MAX_AGE + 1),
                                    (header(body), body, NOW - 61), ('t=NaN,v1=x', body, NOW),
                                    (header(body) + f',t={NOW}', body, NOW), ('', body, NOW)):
            with self.subTest(signature=signature):
                self.assertFalse(S.verify_signature(raw, signature, KEY, now))

    def test_hourly_retry_rechecks_live_policy_and_remains_eligible(self):
        self.assertTrue(S.eligible(DEVICE, NODE, NOW + 3601))
        with self.assertRaises(S.Denied):
            S.eligible(DEVICE, NODE, NOW + S.MAX_AGE + 1)

    def test_device_policy_fails_closed(self):
        S.eligible(DEVICE, NODE, NOW)
        cases = {'tags': [S.TAG, 'tag:ci'], 'isEphemeral': False, 'isExternal': True,
                 'os': 'windows',
                 'name': 'agent.other.ts.net', 'nodeId': 'nOther', 'nodeKey': 'auth-key',
                 'tailnetLockKey': 'bad', 'created': '2020-01-01T00:00:00Z'}
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises(S.Denied):
                S.eligible({**DEVICE, field: value}, NODE, NOW)
        for field in DEVICE:
            if field == 'tailnetLockError':
                continue
            changed = dict(DEVICE)
            del changed[field]
            with self.subTest(missing=field), self.assertRaises((S.Denied, S.NotReady)):
                S.eligible(changed, NODE, NOW)

    def process(self, devices=None, lock=None, event=None):
        with patch.object(S, 'access_token', return_value='synthetic-token'), \
             patch.object(S, 'api', side_effect=devices or [DEVICE, DEVICE]) as api, \
             patch.object(S, 'signer_status', return_value=lock or LOCK), \
             patch.object(S, 'local_api') as local:
            S.process([event or EVENT], NOW)
            return api, local

    def test_connecting_node_retries_briefly_without_signing_early(self):
        with patch.object(S, 'access_token', return_value='x'), \
             patch.object(S, 'api', side_effect=[{**DEVICE, 'connectedToControl': False}, DEVICE, DEVICE]), \
             patch.object(S, 'signer_status', return_value=LOCK), \
             patch.object(S.time, 'sleep') as sleep, patch.object(S, 'local_api') as local:
            S.process([EVENT], NOW)
            sleep.assert_called_once_with(1)
            local.assert_called_once()
        with patch.object(S, 'access_token', return_value='x'), \
             patch.object(S, 'api', return_value={**DEVICE, 'authorized': False}), \
             patch.object(S.time, 'sleep') as sleep, patch.object(S, 'local_api') as local:
            with self.assertRaises(S.NotReady):
                S.process([EVENT], NOW)
            self.assertEqual(sleep.call_count, 2)
            local.assert_not_called()

    def test_valid_node_signs_exact_api_keys_without_promoting_signer(self):
        api, local = self.process()
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[0], '/device/' + NODE + '?fields=all')
        local.assert_called_once_with('tka/sign', {
            'NodeKey': DEVICE['nodeKey'],
            'RotationPublic': base64.b64encode(bytes.fromhex('b' * 64)).decode()})

    def test_changed_key_or_tag_does_not_sign(self):
        for field, value in (('nodeKey', 'nodekey:' + 'd' * 64), ('tags', ['tag:ci'])):
            with self.subTest(field=field), patch.object(S, 'access_token', return_value='x'), \
                 patch.object(S, 'api', side_effect=[DEVICE, {**DEVICE, field: value}]), \
                 patch.object(S, 'signer_status', return_value=LOCK), patch.object(S, 'local_api') as local:
                S.process([EVENT], NOW)
                local.assert_not_called()

    def test_rejected_event_does_not_discard_later_eligible_devices(self):
        second = {**DEVICE, 'nodeId': 'nSecond123', 'nodeKey': 'nodekey:' + 'e' * 64}
        second_event = {**EVENT, 'data': {'nodeID': second['nodeId']}}
        variants = [
            ([EVENT, second_event], [DEVICE, {**DEVICE, 'tags': ['tag:ci']}, second, second]),
            ([EVENT, second_event], [DEVICE, {**DEVICE, 'nodeKey': 'nodekey:' + 'd' * 64}, second, second]),
            ([EVENT, second_event], [DEVICE, S.Denied('removed'), second, second]),
            ([{**EVENT, 'data': {'nodeID': '../acl'}}, second_event], [second, second]),
            ([{'version': 2}, second_event], [second, second]),
        ]
        for events, devices in variants:
            with self.subTest(events=events, devices=devices), \
                 patch.object(S, 'access_token', return_value='x'), \
                 patch.object(S, 'api', side_effect=devices), \
                 patch.object(S, 'signer_status', return_value=LOCK), patch.object(S, 'local_api') as local:
                S.process(events, NOW)
                local.assert_called_once_with('tka/sign', {
                    'NodeKey': second['nodeKey'],
                    'RotationPublic': base64.b64encode(bytes.fromhex('b' * 64)).decode()})

    def test_large_authenticated_batch_does_not_drop_later_enrollment(self):
        with patch.object(S, 'access_token', return_value='x'), \
             patch.object(S, 'api', side_effect=[DEVICE, DEVICE]), \
             patch.object(S, 'signer_status', return_value=LOCK), patch.object(S, 'local_api') as local:
            S.process([{'version': 1, 'type': 'nodeCreated'}] * 17 + [EVENT], NOW)
            local.assert_called_once()

    def test_removed_device_is_permanent_but_api_outage_still_retries(self):
        for code, expected in ((404, S.Denied), (403, HTTPError), (500, HTTPError)):
            with self.subTest(code=code), \
                 patch.object(S, 'urlopen', side_effect=HTTPError('https://example.invalid', code, 'fixture', {}, None)), \
                 self.assertRaises(expected):
                S.api('/device/' + NODE, 'synthetic-token')

    def test_unrelated_unsigned_or_duplicate_signed_device_is_ignored(self):
        for device in ({**DEVICE, 'tags': ['tag:ci']}, {**DEVICE, 'tailnetLockError': ''}):
            api, local = self.process(devices=[device])
            local.assert_not_called()
            self.assertEqual(api.call_count, 1)
        api, local = self.process(event={'version': 1, 'type': 'nodeCreated'})
        api.assert_not_called()
        local.assert_not_called()

    def test_untrusted_signer_does_not_sign(self):
        with patch.object(S, 'access_token', return_value='x'), \
             patch.object(S, 'api', return_value=DEVICE), \
             patch.object(S, 'signer_status', side_effect=RuntimeError('untrusted')), \
             patch.object(S, 'local_api') as local, self.assertRaises(RuntimeError):
            S.process([EVENT], NOW)
        local.assert_not_called()

    def test_event_cannot_inject_path_or_sign_command(self):
        for node_id in ('../acl', NODE + '?x=y', 'nodekey:' + 'a' * 64, '', None):
            with self.subTest(node_id=node_id), patch.object(S, 'access_token') as token:
                S.process([{**EVENT, 'data': {'nodeID': node_id}}], NOW)
                token.assert_not_called()
        for events in ([], {}):
            with self.assertRaises(S.Denied):
                S.process(events, NOW)

    def test_only_an_existing_trusted_signer_is_ready(self):
        status = {'BackendState': 'Running', 'CurrentTailnet': {'MagicDNSSuffix': S.SUFFIX}}
        for lock in ({**LOCK, 'Enabled': False}, {**LOCK, 'NodeKeySigned': False},
                     {**LOCK, 'TrustedKeys': []}):
            with patch.object(S, 'local_api', side_effect=[status, lock]), self.assertRaises(RuntimeError):
                S.signer_status()
        with patch.object(S, 'local_api', side_effect=[status, LOCK]):
            self.assertEqual(S.signer_status(), LOCK)

    def test_real_http_rejects_unauthenticated_body_before_processing(self):
        server = HTTPServer(('127.0.0.1', 0), S.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(S, 'secret', return_value=KEY), patch.object(S, 'time') as clock, \
                 patch.object(S, 'process') as process:
                clock.time.return_value = NOW
                body = json.dumps([EVENT]).encode()
                for path, headers, code in (
                    (S.HOOK, {}, 401), ('/sign', {}, 404),
                    (S.HOOK, {'Tailscale-Webhook-Signature': header(body)}, 204),
                    (S.HOOK, {'Tailscale-Webhook-Signature': header(body), 'Content-Length': '65537'}, 413),
                ):
                    connection = HTTPConnection(*server.server_address, timeout=2)
                    connection.request('POST', path, body, headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, code)
                    response.read()
                    connection.close()
                process.assert_called_once_with([EVENT], NOW)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
