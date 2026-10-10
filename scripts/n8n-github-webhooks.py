#!/usr/bin/env python3
"""Preview or move the two existing homelab n8n GitHub callbacks to Funnel."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('callbacks', ROOT / 'scripts/policy-bot-webhook.py')
CALLBACKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALLBACKS)
HOOKS = {
    589400612: '7cd61c45-077f-45e4-aafe-8e06ce68fbc4',  # Codex Review Helper
    636944763: '7d4342d3-103b-437a-a941-811a75dacb2f',  # Github Emergency Bot
}
HOST = 'https://n8n-webhook.tail67beb.ts.net'
PREVIOUS_HOST = 'https://n8n-webhook.stinkyboi.com'
BASE = '/repos/Stuhlmuller/homelab/hooks/'
RECEIPTS = Path.home() / '.local/state/homelab'


def github(method, path, body=None):
    args = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
    if body is not None:
        args += ['--input', '-']
    return json.loads(CALLBACKS.command(*args, input=json.dumps(body).encode() if body is not None else None))


def safe_probe(url, method='GET'):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), CALLBACKS.NoRedirect())
    headers = {'Origin': HOST, 'Access-Control-Request-Method': 'POST'} if method == 'OPTIONS' else {}
    try:
        response = opener.open(urllib.request.Request(url, method=method, headers=headers), timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers


def preflight():
    if safe_probe(HOST + '/')[0] != 404:
        raise RuntimeError('Funnel root must remain unreachable; callback configuration unchanged')
    for path in HOOKS.values():
        status, headers = safe_probe(HOST + '/webhook/' + path, 'OPTIONS')
        # n8n handles OPTIONS before workflow execution and reports registered
        # methods when Origin is present. Never send a triggering webhook POST.
        methods = {method.strip() for method in headers.get('Access-Control-Allow-Methods', '').split(',')}
        if status != 204 or methods != {'OPTIONS', 'POST'}:
            raise RuntimeError('Funnel must reach the existing POST-only n8n workflow; no webhook was sent')


def reconcile(api=github, execute=False, require_delivery=False):
    reviewed = []
    for identifier, path in HOOKS.items():
        endpoint = BASE + str(identifier)
        before = api('GET', endpoint)
        url = HOST + '/webhook/' + path
        if (before.get('id') != identifier or before.get('name') != 'web'
                or before.get('active') is not True or before.get('events') != ['pull_request']
                or before.get('config', {}).get('url') not in (PREVIOUS_HOST + '/webhook/' + path, url)):
            raise RuntimeError('Existing n8n hook differs from the reviewed ID, URL, activation or events')
        receipt = RECEIPTS / f'n8n-github-hook-{identifier}-cutover.json'
        cutover = CALLBACKS.read_receipt(receipt, url)
        reviewed.append((identifier, endpoint, before, url, receipt, cutover))
        print(f"Hook {identifier}: {before['config']['url']} -> {url}")
    if execute:
        preflight()  # Both targets must pass before either hook changes.
    accepted = []
    for identifier, endpoint, before, url, receipt, cutover in reviewed:
        if execute:
            if before['config']['url'] != url or cutover is None:
                cutover = CALLBACKS.new_cutover(api, url, endpoint + '/deliveries')
            if before['config']['url'] != url:
                # The /config endpoint preserves an omitted secret. PATCHing the
                # whole hook's config instead would remove its secret.
                api('PATCH', endpoint + '/config', {'url': url})
            current = api('GET', endpoint)
            if (current.get('config') != dict(before['config'], url=url)
                    or any(current.get(key) != before.get(key) for key in ('id', 'name', 'active', 'events'))):
                raise RuntimeError('n8n hook readback changed settings beyond the fixed callback URL')
            CALLBACKS.save_receipt(receipt, cutover)
        accepted.append(CALLBACKS.delivery_status(api, url if execute else before['config']['url'],
                                                 cutover, endpoint + '/deliveries'))
    print('Fixed callback URLs verified; existing secrets/events preserved' if execute else 'Preview only; callback configuration unchanged')
    if require_delivery and not all(accepted):
        raise RuntimeError('Both hooks require a successful delivery newer than their cutover; no event or redelivery was triggered')
    return all(accepted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='PATCH only the two fixed callback URLs after Funnel preflight')
    parser.add_argument('--expected-sha', help='Full reviewed main SHA required for execution')
    parser.add_argument('--require-delivery', action='store_true', help='Require fresh successful deliveries after both saved cutovers')
    args = parser.parse_args()
    if args.execute:
        CALLBACKS.verify_reviewed_main(args.expected_sha)
        CALLBACKS.command('git', '-C', str(ROOT), 'cat-file', '-e', 'HEAD:scripts/n8n-github-webhooks.py')
    reconcile(execute=args.execute, require_delivery=args.require_delivery)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError)
                         else 'n8n callback operation failed; private response output withheld') from None
