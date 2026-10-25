#!/usr/bin/env python3
"""Maintain the surviving n8n callback and retire its unused helper hook."""
import sys
if __name__ == '__main__' and not sys.flags.isolated:
    raise SystemExit('Run with python3 -I')

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('callbacks', ROOT / 'scripts/policy-bot-webhook.py')
CALLBACKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALLBACKS)
EMERGENCY_HOOK = 636944763  # Github Emergency Bot
HOOKS = {EMERGENCY_HOOK: '7d4342d3-103b-437a-a941-811a75dacb2f'}
RETIRED_HOOK = 589400612  # Codex Review Helper
RETIRED_PATH = '7cd61c45-077f-45e4-aafe-8e06ce68fbc4'
HOST = 'https://n8n-webhook.tail67beb.ts.net'
PREVIOUS_HOST = 'https://n8n-webhook.stinkyboi.com'
RETIRED_URLS = {host + '/webhook/' + RETIRED_PATH for host in (HOST, PREVIOUS_HOST)}
BASE = '/repos/Stuhlmuller/homelab/hooks/'
COLLECTION = BASE.removesuffix('/') + '?per_page=100'
RECEIPTS = Path.home() / '.local/state/homelab'


def github(method, path, body=None):
    args = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
    if body is not None:
        args += ['--input', '-']
    output = CALLBACKS.command(*args, input=json.dumps(body).encode() if body is not None else None)
    return json.loads(output) if output.strip() else None


def hook_inventory(api):
    hooks = api('GET', COLLECTION)
    if not isinstance(hooks, list) or len(hooks) >= 100:
        raise RuntimeError('Repository hook inventory may be incomplete')
    ids = [item.get('id') for item in hooks if isinstance(item, dict)]
    if (len(ids) != len(hooks) or any(type(identifier) is not int or identifier <= 0 for identifier in ids)
            or len(ids) != len(set(ids)) or any(not isinstance(item.get('config'), dict) for item in hooks)):
        raise RuntimeError('Repository hook inventory has invalid or duplicate IDs')
    return {item['id']: item for item in hooks}


def uses_retired_path(item):
    url = item['config'].get('url')
    return isinstance(url, str) and urllib.parse.urlsplit(url).path.rstrip('/') == '/webhook/' + RETIRED_PATH


def require_retired_absent(api):
    hooks = hook_inventory(api)
    if RETIRED_HOOK in hooks or any(uses_retired_path(item) for item in hooks.values()):
        raise RuntimeError('Retired Codex Review Helper hook or callback path still exists')


def retire_helper(api=github, execute=False):
    hooks = hook_inventory(api)
    if any(uses_retired_path(item) for identifier, item in hooks.items() if identifier != RETIRED_HOOK):
        raise RuntimeError('Another hook uses the retired callback path')
    if RETIRED_HOOK not in hooks:
        print('Codex Review Helper hook already absent')
        return
    endpoint = BASE + str(RETIRED_HOOK)
    before = api('GET', endpoint)
    if (before.get('id') != RETIRED_HOOK or before.get('name') != 'web'
            or before.get('active') is not True or before.get('events') != ['pull_request']
            or before.get('config', {}).get('url') not in RETIRED_URLS):
        raise RuntimeError('Codex Review Helper hook differs from the reviewed identity, URL, activation or events')
    if not execute:
        print(f"Preview only; hook {RETIRED_HOOK}: {before['config']['url']} -> absent")
        return
    emergency = api('GET', BASE + str(EMERGENCY_HOOK))
    api('DELETE', endpoint)
    require_retired_absent(api)
    current = api('GET', BASE + str(EMERGENCY_HOOK))
    if any(current.get(key) != emergency.get(key) for key in ('id', 'name', 'active', 'events', 'config')):
        raise RuntimeError('Surviving Emergency hook changed during retirement')
    print(f'Hook {RETIRED_HOOK} retired; Emergency hook preserved')


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
        preflight()
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
    print('Emergency callback URL verified; existing secret/events preserved' if execute else 'Preview only; Emergency callback unchanged')
    if require_delivery and not all(accepted):
        raise RuntimeError('Emergency hook requires a successful delivery newer than its cutover; no event or redelivery was triggered')
    return all(accepted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Apply the selected guarded callback change')
    parser.add_argument('--retire-helper', action='store_true', help='Preview or retire the exact unused Codex Review Helper hook')
    parser.add_argument('--expected-sha', help='Full reviewed main SHA required for execution')
    parser.add_argument('--require-delivery', action='store_true', help='Require retired helper absence and a fresh Emergency delivery')
    args = parser.parse_args()
    if args.execute:
        CALLBACKS.verify_reviewed_main(args.expected_sha)
        CALLBACKS.command('git', '-C', str(ROOT), 'cat-file', '-e', 'HEAD:scripts/n8n-github-webhooks.py')
    if args.retire_helper:
        if args.execute and RETIRED_HOOK not in hook_inventory(github):
            retire_helper(execute=True)
            return
        reconcile(require_delivery=args.execute or args.require_delivery)
        retire_helper(execute=args.execute)
    else:
        if args.require_delivery:
            require_retired_absent(github)
        reconcile(execute=args.execute, require_delivery=args.require_delivery)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError)
                         else 'n8n callback operation failed; private response output withheld') from None
